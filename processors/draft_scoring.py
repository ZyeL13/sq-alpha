# processors/draft_scoring.py — mechanical draft pool scoring (JIT path).
#
# No LLM judge: the pool winner is picked by three auditable
# components (spec 5.2), each logged per draft:
#   signal strength  (45): the token's existing total score x 45.
#   data specificity (30): +7.5 per DISTINCT token number cited WITH
#     a market unit (%, x, $, vol) and matched against the token's
#     own numbers, capped at 4 numbers. Bare numbers ("3 days",
#     "top 10") never count — no stray-number credit.
#   opener freshness (25): 25 when the opener's first 8 words differ
#     from all of the last 5 scheduled posts' openers, else 0.
# Hard reject (None): empty content, or the existing validate_post
# fails. Drafts reaching here already passed validation inside
# generate_post; the re-check keeps this module self-contained and
# makes the hard-reject rule testable in isolation.
import re
from dataclasses import dataclass, field

from generators.quality_gate import validate_post

SIGNAL_WEIGHT = 45.0
SPECIFICITY_WEIGHT = 30.0
SPECIFICITY_PER_NUMBER = 7.5
SPECIFICITY_CAP = 4
FRESHNESS_WEIGHT = 25.0
OPENER_WORDS = 8

# Rounding slop for cited-vs-actual matching. Posts round to 1
# decimal ("+4.2%") or 2 decimals ("$1.35"); 0.15 absolute covers
# percent/ratio rounding, 2% relative covers prices and volumes at
# every magnitude (a $0.0001234 price must not match any tiny number).
_PCT_TOL = 0.15
_REL_TOL = 0.02

_MULTIPLIERS = {"K": 1e3, "M": 1e6, "B": 1e9}

# Cited numbers WITH a market unit. The vol pattern is deliberately
# narrow: "vol"/"volume" directly attached to a number ("vol 2.1x"
# is already caught by the x pattern; this covers "volume 2.1").
_PCT_RE = re.compile(r"([+-]?\d[\d,]*\.?\d*)\s*%")
_X_RE = re.compile(r"([+-]?\d[\d,]*\.?\d*)\s*x\b", re.IGNORECASE)
_DOLLAR_RE = re.compile(r"\$\s*([\d,]+\.?\d*)\s*([KMB])?(?![A-Za-z])",
                        re.IGNORECASE)
_VOL_RE = re.compile(r"\bvol(?:ume)?\b\s*:?\s*([+-]?\d[\d,]*\.?\d*)",
                     re.IGNORECASE)


@dataclass(frozen=True)
class DraftScore:
    total: float
    signal: float
    specificity: float
    freshness: float
    matched: tuple = field(default_factory=tuple)

    def components_str(self) -> str:
        return (f"signal={self.signal:.1f}|spec={self.specificity:.1f}|"
                f"fresh={self.freshness:.1f}")


def _num(text: str) -> "float | None":
    try:
        return float(text.replace(",", ""))
    except (TypeError, ValueError):
        return None


def _close_pct(cited: float, actual: float) -> bool:
    return abs(cited - actual) <= _PCT_TOL


def _close_rel(cited: float, actual: float) -> bool:
    if actual == 0:
        return cited == 0
    return abs(cited - actual) <= _REL_TOL * abs(actual)


def _token_numbers(token: dict, snapshot=None) -> dict:
    """The token's own matchable numbers, keyed by what they are.

    Percent-class: 24h change, BTC change, BTC-relative points.
    Dollar-class: price, 24h high/low, 24h volume, news-time
    price/volume. Ratio-class: 24h volume vs the 7d average (from
    the snapshot when present, else the enriched token field).
    Range position is deliberately absent: bare (unit-less), it can
    never earn specificity credit.
    """
    numbers = {}

    def _put(key, value):
        try:
            value = float(value)
        except (TypeError, ValueError):
            return
        numbers[key] = value

    _put("change", token.get("price_change_percent"))
    _put("price", token.get("price"))
    _put("high", token.get("high_24h"))
    _put("low", token.get("low_24h"))
    _put("volume", token.get("volume_24h"))
    _put("price_at_news", token.get("price_at_news"))
    _put("volume_at_news", token.get("volume_at_news"))
    _put("btc_change", token.get("btc_change_24h"))
    if "change" in numbers and "btc_change" in numbers:
        numbers["btc_relative"] = numbers["change"] - numbers["btc_change"]
    ratio = None
    if snapshot is not None:
        try:
            ratio = snapshot.volume_ratio
        except Exception:
            ratio = None
    if ratio is None:
        ratio = token.get("volume_ratio_7d")
    _put("volume_ratio", ratio)
    return numbers


def _match_cited(content: str, numbers: dict) -> set:
    """Token-number keys cited in the content with a market unit.

    One cited number earns at most one key (the first matching
    field in class order): a price sitting inside a tight high/low
    range must not triple-count, and a percent equal to both the
    change and the BTC change must not double-count. The cap is on
    distinct cited numbers, not on fields that happen to coincide.
    """
    matched = set()
    pct_keys = ("change", "btc_change", "btc_relative")
    dollar_keys = ("price", "high", "low", "volume", "price_at_news",
                   "volume_at_news")
    for m in _PCT_RE.finditer(content):
        value = _num(m.group(1))
        if value is None:
            continue
        for key in pct_keys:
            if key in numbers and _close_pct(value, numbers[key]):
                matched.add(key)
                break
    for m in _X_RE.finditer(content):
        value = _num(m.group(1))
        if value is not None and "volume_ratio" in numbers \
                and _close_pct(value, numbers["volume_ratio"]):
            matched.add("volume_ratio")
    for m in _DOLLAR_RE.finditer(content):
        value = _num(m.group(1))
        if value is None:
            continue
        suffix = (m.group(2) or "").upper()
        value *= _MULTIPLIERS.get(suffix, 1.0)
        for key in dollar_keys:
            if key in numbers and _close_rel(value, numbers[key]):
                matched.add(key)
                break
    for m in _VOL_RE.finditer(content):
        value = _num(m.group(1))
        if value is not None and "volume_ratio" in numbers \
                and _close_pct(value, numbers["volume_ratio"]):
            matched.add("volume_ratio")
    return matched


def extract_opener(content: str) -> str:
    """The opener: first 8 words, lowercased, whitespace collapsed."""
    words = (content or "").split()
    return " ".join(words[:OPENER_WORDS]).lower()


def score_draft(content: str, token: dict, total_score: float,
                recent_openers: "list[str] | None" = None,
                snapshot=None) -> "DraftScore | None":
    """Score one draft, or None for a hard reject."""
    if not content or not isinstance(content, str):
        return None
    valid, _ = validate_post(content)
    if not valid:
        return None
    try:
        total_score = float(total_score)
    except (TypeError, ValueError):
        total_score = 0.0
    signal = max(0.0, min(SIGNAL_WEIGHT, total_score * SIGNAL_WEIGHT))

    matched = _match_cited(content, _token_numbers(token, snapshot))
    specificity = min(len(matched), SPECIFICITY_CAP) * SPECIFICITY_PER_NUMBER

    opener = extract_opener(content)
    recent = [extract_opener(o) for o in (recent_openers or [])]
    freshness = 0.0 if opener and opener in recent else FRESHNESS_WEIGHT

    total = signal + specificity + freshness
    return DraftScore(total=total, signal=signal, specificity=specificity,
                      freshness=freshness, matched=tuple(sorted(matched)))


def pick_winner(scores: list) -> int:
    """Index of the winning draft: highest total, ties go to the
    earliest candidate. Raises ValueError on an empty list."""
    if not scores:
        raise ValueError("pick_winner needs at least one scored draft")
    best = 0
    for i in range(1, len(scores)):
        if scores[i].total > scores[best].total:
            best = i
    return best


# Class order for cited-number matching (same as _match_cited).
_PCT_KEYS = ("change", "btc_change", "btc_relative")
_DOLLAR_KEYS = ("price", "high", "low", "volume", "price_at_news",
                "volume_at_news")
_RATIO_KEYS = ("volume_ratio",)

# Unicode minus/dash signs that read as "-" in a cited number.
# 1:1 replacement, so offsets into the original content stay valid.
_UNICODE_MINUS = str.maketrans({"−": "-", "–": "-", "—": "-"})


def find_unmatched_numbers(content: str, numbers: dict) -> list:
    """Unit-carrying numbers cited in `content` matching NO key in
    `numbers` (the JSON validator's number check, spec §1.3/§2.3).

    Reuses the module regexes, tolerances and class order of
    `_match_cited`: percent-class keys for % matches, "volume_ratio"
    for x- and vol-matches, dollar-class keys for $ matches (K/M/B
    multiplier applied first). One cited number checks every key in
    its class; it is unmatched only if it matches none of them.
    Returns the cited strings as they appear (e.g. "+9.9%", "$5.55",
    "7.7x"). Bare digits with no unit are ignored entirely.
    """
    if not content or not isinstance(content, str):
        return []
    numbers = numbers or {}
    # Normalised copy for matching only; displays come from `content`.
    normalized = content.translate(_UNICODE_MINUS)
    unmatched = []
    seen = set()

    def _safe_close(closer, value, actual):
        try:
            return closer(value, actual)
        except (TypeError, ValueError):
            return False

    def _record(match, value, keys, closer):
        if value is None:
            return
        for key in keys:
            if key in numbers and _safe_close(closer, value, numbers[key]):
                return
        display = content[match.start():match.end()].strip()
        if display and display not in seen:
            seen.add(display)
            unmatched.append(display)

    for m in _PCT_RE.finditer(normalized):
        _record(m, _num(m.group(1)), _PCT_KEYS, _close_pct)
    x_spans = []
    for m in _X_RE.finditer(normalized):
        x_spans.append((m.start(1), m.end(1)))
        _record(m, _num(m.group(1)), _RATIO_KEYS, _close_pct)
    for m in _DOLLAR_RE.finditer(normalized):
        value = _num(m.group(1))
        if value is None:
            continue
        suffix = (m.group(2) or "").upper()
        value *= _MULTIPLIERS.get(suffix, 1.0)
        _record(m, value, _DOLLAR_KEYS, _close_rel)
    for m in _VOL_RE.finditer(normalized):
        # "volume 3.2x" is already cited by the x pattern; do not
        # report it a second time as a vol citation.
        if any(s <= m.start(1) < e for s, e in x_spans):
            continue
        _record(m, _num(m.group(1)), _RATIO_KEYS, _close_pct)
    return unmatched
