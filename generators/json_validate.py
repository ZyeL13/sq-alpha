"""Tolerant JSON parsing + validation for short-form draft replies.

Step 1 (editorial revision, spec §2.3): `generate_post` returns a JSON
object `{"event", "fact", "interpretation", "angle", "post"}`; this
module parses the raw LLM reply and validates the parsed object
(steps 2-5: fields, angle echo, cashtag-first, number check,
forbidden phrases). Parse failure is signalled by `parse_json_reply`
returning None; the caller maps that to "json_invalid".

Number matching is imported from `processors.draft_scoring` (not
copied); the forbidden-phrase check from `generators.quality_gate`.
No imports from `llm` or the orchestrator: this module is imported by
`generators.post_generator`, so it must stay cycle-free.
"""
import json
import re

from generators.quality_gate import (
    LONGFORM_ABSENCE_SENTENCES,
    LONGFORM_MAX_HEADLINE_CHARS,
    LONGFORM_MIN_CONCLUSION_WORDS,
    LONGFORM_MIN_SECTION_WORDS,
    has_editorial_violation,
)
from processors.draft_scoring import (
    _MULTIPLIERS,
    _DOLLAR_RE,
    _PCT_RE,
    _VOL_RE,
    _X_RE,
    _close_pct,
    _close_rel,
    _match_cited,
    _num,
    _token_numbers,
    find_unmatched_numbers,
)
from prompts.styles import VERB_SCALE, derive_stance, verb_for_change

# Re-exported for callers that build the snapshot numbers dict the
# same way the scorer does (also marks the imports as used for ruff).
__all__ = [
    "_match_cited",
    "_token_numbers",
    "find_unmatched_numbers",
    "parse_json_reply",
    "validate_article_json",
    "validate_draft_json",
]

REQUIRED_FIELDS = ("event", "fact", "interpretation", "angle", "post")

# Article JSON contract (spec §4.2): the 9 content keys (title,
# stance + 7 sections) plus headline + deck. `deck` may be an empty
# string; every other field must be a non-empty string.
ARTICLE_FIELDS = (
    "title", "stance", "thesis", "what_happened", "why_it_matters",
    "bull_case", "bear_case", "limits", "conclusion", "headline", "deck",
)
ARTICLE_SECTION_KEYS = (
    "thesis", "what_happened", "why_it_matters", "bull_case",
    "bear_case", "limits", "conclusion",
)
# JSON key -> LONGFORM_SECTIONS label (for the shared word minimums).
ARTICLE_SECTION_LABELS = {
    "thesis": "THESIS",
    "what_happened": "WHAT HAPPENED",
    "why_it_matters": "WHY IT MATTERS",
    "bull_case": "BULL CASE",
    "bear_case": "BEAR CASE",
    "limits": "LIMITS AND INVALIDATION",
    "conclusion": "CONCLUSION",
}
DECK_MAX_CHARS = 140


def _strip_fences(text: str) -> str:
    """Remove a surrounding markdown fence (```json ... ``` or
    ``` ... ```, also a lone leading/trailing fence)."""
    s = text.strip()
    if s.startswith("```"):
        s = s[3:].lstrip()
        if s.lower().startswith("json") and (
                len(s) == 4 or s[4] in " \t\r\n{"):
            s = s[4:].lstrip()
    if s.endswith("```"):
        s = s[:-3].rstrip()
    return s


def _first_json_object(text: str):
    """First balanced {...} block in `text`, parsed as a dict.

    Brace scan that respects string literals and backslash escapes.
    A block that does not parse is skipped and scanning continues
    after it; returns None when no block parses as a dict.
    """
    i = text.find("{")
    while i != -1:
        depth = 0
        in_string = False
        escaped = False
        j = i
        while j < len(text):
            ch = text[j]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
            elif ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[i:j + 1])
                    except ValueError:
                        obj = None
                    if isinstance(obj, dict):
                        return obj
                    break
            j += 1
        i = text.find("{", i + 1)
    return None


def parse_json_reply(text: str) -> dict | None:
    """Tolerant JSON extraction from an LLM reply.

    Strip markdown fences, try `json.loads` on the result; if that
    fails, extract the first balanced {...} block (prose around it is
    ignored). Returns the parsed object only when it is a dict, else
    None (unparseable text, or JSON that is not an object).
    """
    if not text or not isinstance(text, str):
        return None
    stripped = _strip_fences(text)
    try:
        obj = json.loads(stripped)
    except ValueError:
        return _first_json_object(stripped)
    return obj if isinstance(obj, dict) else None


def validate_draft_json(d, drawn_angle, numbers, symbol=None):
    """Validation steps 2-5 (spec §2.3), first failure wins.

    (a) dict with all five keys, all strings, post non-empty ->
        "json_missing_field"
    (b) angle == drawn_angle -> "angle_mismatch"
    (c) when `symbol` is given, post starts with f"${symbol}"
        (case-insensitive) -> "cashtag_not_first"
    (d) every unit-carrying number in post matches `numbers` ->
        "number_not_in_snapshot"
    (e) no editorial forbidden phrase -> "forbidden_phrase"
    Returns (True, None) when the draft passes all steps.
    """
    if not isinstance(d, dict):
        return (False, "json_missing_field")
    for key in REQUIRED_FIELDS:
        if key not in d or not isinstance(d[key], str):
            return (False, "json_missing_field")
    if not d["post"].strip():
        return (False, "json_missing_field")
    if d["angle"] != drawn_angle:
        return (False, "angle_mismatch")
    if symbol:
        if not d["post"].lstrip().lower().startswith(f"${symbol}".lower()):
            return (False, "cashtag_not_first")
    if find_unmatched_numbers(d["post"], numbers or {}):
        return (False, "number_not_in_snapshot")
    if has_editorial_violation(d["post"]) is not None:
        return (False, "forbidden_phrase")
    return (True, None)


# ---------------------------------------------------------------- article
# Article JSON validation (spec §6). Each gate is its own function so
# tests can pin the before-state per gate; validate_article_json runs
# them in order and reports the first failure as (False, reason, gate).
# Gate order: 6b (structure — nothing else can run without the keys),
# 5 (headline/deck/stance), 2 (numbers + causal claims), 1
# (repetition), 3 (named missing data), 4 (differentiation).

_ARTICLE_STOPWORDS = frozenset("""
a an the is are was were be been being of to in on for with by at from as
and or but it its this that these those than then so such no not nor if
when while which who whom what how all any each every both few more most
other some own same too very can could may might must shall should will
would do does did done have has had having i we you he she they them his
her their our your my me him us him it there here now today yesterday
token tokens price prices market crypto session day days move moves moved
""".split())

_WORD_RE = re.compile(r"[a-z][a-z\-']*")
_NEG_RE = re.compile(r"\b(?:no|none|cannot|without|never)\b")
_LIMIT_TOPIC_RE = re.compile(
    r"\b(?:timeframes?|periods?|baselines?|histor(?:y|ies)|"
    r"catalysts?|forecasts?|prov\w*)\b")
_CAUSAL_RE = re.compile(
    r"caused by|driven by|triggered by|sparked by|on news of|"
    r"amid\b.*\b(?:announcement|launch|hack|exploit)\b",
    re.IGNORECASE)
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def _content_words(text: str) -> set:
    """Lowercased content-word set of a section (stopwords removed)."""
    return {w for w in _WORD_RE.findall((text or "").lower())
            if w not in _ARTICLE_STOPWORDS}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _limitation_sentences(text: str) -> list:
    """Sentences carrying a limitation: a negation word AND a
    limitation topic word in the same sentence (spec §6.1)."""
    out = []
    for sent in _SENTENCE_RE.split(text or ""):
        lowered = sent.lower()
        if _NEG_RE.search(lowered) and _LIMIT_TOPIC_RE.search(lowered):
            out.append(sent.strip())
    return out


def _article_numbers(snapshot_dict: dict) -> dict:
    """Matchable numbers for an article, keyed by class like
    _token_numbers — but built from a snapshot dict (change_24h,
    volume_24h, ...) instead of a token dict, and extended with the
    code-derived path facts (price_24h_ago, session low/high) and
    range_width_pct so the article may cite them."""
    numbers = {}

    def _put(key, value):
        try:
            numbers[key] = float(value)
        except (TypeError, ValueError):
            pass

    d = snapshot_dict or {}
    _put("change", d.get("change_24h"))
    _put("btc_change", d.get("btc_change"))
    _put("btc_relative", d.get("btc_relative"))
    _put("range_width_pct", d.get("range_width_pct"))
    _put("price", d.get("price"))
    _put("high", d.get("high"))
    _put("low", d.get("low"))
    _put("volume", d.get("volume_24h"))
    _put("volume_7d_avg", d.get("volume_7d_avg"))
    _put("price_24h_ago", d.get("price_24h_ago"))
    _put("session_low", d.get("session_low"))
    _put("session_high", d.get("session_high"))
    _put("volume_ratio", d.get("volume_ratio"))
    return numbers


def _find_unmatched_article_numbers(content: str, numbers: dict) -> list:
    """Unit-carrying numbers in `content` matching NO snapshot value.

    Same regexes/tolerances as find_unmatched_numbers (0.15 pct /
    2% rel), except percent matching is sign-insensitive: an article
    writes "fell 48.8%" for a -48.8% move, so a cited percent matches
    when it is within tolerance of the value OR its negation.
    Returns the cited strings as they appear.
    """
    if not content or not isinstance(content, str):
        return []
    numbers = numbers or {}
    unmatched = []
    seen = set()
    pct_keys = ("change", "btc_change", "btc_relative", "range_width_pct")
    dollar_keys = ("price", "high", "low", "volume", "volume_7d_avg",
                   "price_24h_ago", "session_low", "session_high")

    def _record(match, value, keys, closer, sign_insensitive=False):
        if value is None:
            return
        for key in keys:
            if key in numbers:
                try:
                    if closer(value, numbers[key]):
                        return
                    if sign_insensitive and closer(value, -numbers[key]):
                        return
                except (TypeError, ValueError):
                    continue
        display = content[match.start():match.end()].strip()
        if display and display not in seen:
            seen.add(display)
            unmatched.append(display)

    for m in _PCT_RE.finditer(content):
        _record(m, _num(m.group(1)), pct_keys, _close_pct,
                sign_insensitive=True)
    for m in _X_RE.finditer(content):
        _record(m, _num(m.group(1)), ("volume_ratio",), _close_pct)
    for m in _DOLLAR_RE.finditer(content):
        value = _num(m.group(1))
        if value is None:
            continue
        suffix = (m.group(2) or "").upper()
        value *= _MULTIPLIERS.get(suffix, 1.0)
        for key in dollar_keys:
            if key in numbers:
                try:
                    if _close_rel(value, numbers[key]):
                        break
                except (TypeError, ValueError):
                    continue
        else:
            display = content[m.start():m.end()].strip()
            if display and display not in seen:
                seen.add(display)
                unmatched.append(display)
    for m in _VOL_RE.finditer(content):
        _record(m, _num(m.group(1)), ("volume_ratio",), _close_pct)
    return unmatched


def _pack_catalyst(research_pack: dict):
    """The catalyst text from a research pack, or None. The pack
    stores it as a dict {"text": ...} or a bare string (both read)."""
    pack = research_pack or {}
    catalyst = pack.get("catalyst")
    if isinstance(catalyst, dict):
        return catalyst.get("text")
    return catalyst


def _pack_missing(research_pack: dict) -> list:
    """The flat missing list from a research pack (both groups)."""
    pack = research_pack or {}
    missing = pack.get("missing") or {}
    if isinstance(missing, dict):
        items = list(missing.get("fillable") or []) + list(
            missing.get("unavailable") or [])
    elif isinstance(missing, list):
        items = list(missing)
    else:
        items = []
    return [str(i) for i in items if str(i).strip()]


def _is_absence_section(text: str) -> bool:
    """True when a BULL/BEAR section is the allowed 1-sentence
    absence ("No bullish case in these data." / bearish)."""
    lowered = (text or "").strip().lower()
    return any(lowered.startswith(s) for s in LONGFORM_ABSENCE_SENTENCES)


def _gate_completeness(article) -> "str | None":
    """Gate 6b: all keys present; deck may be empty, the rest
    non-empty strings; CONCLUSION >= 25 words ending in [.!?]."""
    if not isinstance(article, dict):
        return "article_not_a_dict"
    for key in ARTICLE_FIELDS:
        if key not in article or not isinstance(article[key], str):
            return f"article_missing_field:{key}"
    for key in ARTICLE_FIELDS:
        if key != "deck" and not article[key].strip():
            return f"article_empty_field:{key}"
    conclusion = article["conclusion"].strip()
    if len(conclusion.split()) < LONGFORM_MIN_CONCLUSION_WORDS:
        return "conclusion_too_short"
    if not conclusion[-1] in ".!?":
        return "conclusion_incomplete"
    return None


def _gate_banner_text(article, snapshot_dict, research_pack) -> "str | None":
    """Gate 5 (JSON-level): headline <= 90 chars; headline/deck
    numbers match the snapshot; stance echo equals the code-derived
    stance; headline verb (if any) matches the magnitude band;
    deck <= 140 chars; deck names a catalyst only when one exists
    (and then verbatim)."""
    headline = article["headline"]
    deck = article["deck"]
    if len(headline) > LONGFORM_MAX_HEADLINE_CHARS:
        return "headline_too_long"
    numbers = _article_numbers(snapshot_dict)
    unmatched = (_find_unmatched_article_numbers(headline, numbers)
                 + _find_unmatched_article_numbers(deck, numbers))
    if unmatched:
        return f"headline_deck_number_not_in_snapshot:{unmatched[0]}"
    pack = research_pack or {}
    expected_stance = pack.get("stance")
    if not expected_stance:
        chg = (snapshot_dict or {}).get("change_24h", 0)
        expected_stance = derive_stance(chg, pack.get("category"))
    if article["stance"].strip().upper() != expected_stance:
        return "stance_mismatch"
    chg = (snapshot_dict or {}).get("change_24h", 0)
    expected_verb = verb_for_change(chg)
    lowered = headline.lower()
    for _floor, bearish, bullish in VERB_SCALE:
        for verb in (bearish, bullish):
            if verb.lower() in lowered and verb != expected_verb:
                return "headline_verb_mismatch"
    if len(deck) > DECK_MAX_CHARS:
        return "deck_too_long"
    catalyst = _pack_catalyst(research_pack)
    if _CAUSAL_RE.search(deck):
        if not catalyst:
            return "deck_names_catalyst_without_one"
        if catalyst.lower() not in deck.lower():
            return "deck_catalyst_not_verbatim"
    return None


def _gate_unsupported(article, snapshot_dict, research_pack) -> "str | None":
    """Gate 2: every unit-carrying number in every field matches the
    snapshot; no causal claim without a named catalyst."""
    numbers = _article_numbers(snapshot_dict)
    text = "\n".join(str(article[k]) for k in ARTICLE_FIELDS)
    unmatched = _find_unmatched_article_numbers(text, numbers)
    if unmatched:
        return f"number_not_in_snapshot:{unmatched[0]}"
    if _CAUSAL_RE.search(text) and not _pack_catalyst(research_pack):
        return "causal_claim_without_catalyst"
    return None


def _gate_repetition(article) -> "str | None":
    """Gate 1: no section pair with content-word Jaccard > 0.45;
    at most 4 limitation sentences outside LIMITS, at most 2 inside
    any single non-LIMITS section."""
    sections = {k: article[k] for k in ARTICLE_SECTION_KEYS}
    words = {k: _content_words(v) for k, v in sections.items()}
    keys = list(ARTICLE_SECTION_KEYS)
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            if _jaccard(words[keys[i]], words[keys[j]]) > 0.45:
                return (f"section_repetition:{keys[i]}:{keys[j]}")
    outside = 0
    for key in ARTICLE_SECTION_KEYS:
        if key == "limits":
            continue
        hits = _limitation_sentences(sections[key])
        if len(hits) > 2:
            return f"limitation_restatement:{key}"
        outside += len(hits)
    if outside > 4:
        return "limitation_restatement:outside_limits"
    return None


def _gate_missing(article, research_pack) -> "str | None":
    """Gate 3: LIMITS names >= 1 item from the pack's missing list."""
    limits = article["limits"].lower()
    for item in _pack_missing(research_pack):
        if item.lower() in limits:
            return None
    return "limits_names_no_missing_data"


def _gate_differentiation(article) -> "str | None":
    """Gate 4: all 7 sections present/non-empty with word minimums
    (CONCLUSION >= 25, BULL/BEAR may be the 1-sentence absence);
    pairwise Jaccard <= 0.45; each section adds >= 5 new content
    words vs all earlier sections (THESIS exempt; an absence
    section is exempt from the new-words check — the spec's own
    1-sentence absence cannot add 5 new words)."""
    for key in ARTICLE_SECTION_KEYS:
        text = article.get(key, "")
        if not isinstance(text, str) or not text.strip():
            return f"missing_section:{key}"
        words = len(text.split())
        label = ARTICLE_SECTION_LABELS[key]
        if label == "CONCLUSION":
            if words < LONGFORM_MIN_CONCLUSION_WORDS:
                return "conclusion_too_short"
        elif key in ("bull_case", "bear_case") and _is_absence_section(text):
            continue
        elif words < LONGFORM_MIN_SECTION_WORDS:
            return f"section_too_short:{key}"
    words = {k: _content_words(article[k]) for k in ARTICLE_SECTION_KEYS}
    keys = list(ARTICLE_SECTION_KEYS)
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            if _jaccard(words[keys[i]], words[keys[j]]) > 0.45:
                return (f"section_repetition:{keys[i]}:{keys[j]}")
    seen: set = set()
    for idx, key in enumerate(keys):
        if idx == 0:
            seen |= words[key]
            continue
        if key in ("bull_case", "bear_case") and _is_absence_section(article[key]):
            seen |= words[key]
            continue
        if len(words[key] - seen) < 5:
            return f"section_adds_no_new_info:{key}"
        seen |= words[key]
    return None


def validate_article_json(article, snapshot_dict, research_pack):
    """Validate a parsed article JSON dict against spec §6.

    Returns (True, None, None) on pass, else (False, reason,
    failed_gate) with failed_gate one of "1", "2", "3", "4", "5",
    "6b" (first failure wins, in gate order 6b, 5, 2, 1, 3, 4).
    `snapshot_dict` is the research pack's facts (snapshot numbers
    + path facts); `research_pack` carries stance/catalyst/missing.
    """
    reason = _gate_completeness(article)
    if reason:
        return (False, reason, "6b")
    reason = _gate_banner_text(article, snapshot_dict, research_pack)
    if reason:
        return (False, reason, "5")
    reason = _gate_unsupported(article, snapshot_dict, research_pack)
    if reason:
        return (False, reason, "2")
    reason = _gate_repetition(article)
    if reason:
        return (False, reason, "1")
    reason = _gate_missing(article, research_pack)
    if reason:
        return (False, reason, "3")
    reason = _gate_differentiation(article)
    if reason:
        return (False, reason, "4")
    return (True, None, None)
