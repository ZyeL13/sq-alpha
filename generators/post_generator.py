# generators/post_generator.py
import json
from typing import Dict, Any, Optional
import llm
from llm import generate
from prompts.fewshot import load_fewshot_examples
from prompts.rebate import REBATE_SYSTEM_CORE
from prompts.styles import (
    STYLE_GUIDANCE,
    VOICE_CALIBRATION,
    derive_stance,
    generate_data_anchor,
    insufficient_insight,
    next_opening_angle,
    record_angle_used,
    select_editorial_style,
    select_post_format_with_reason,
    verb_for_change,
)
from config import LONGFORM_MAX_TOKENS, LONGFORM_TARGET_WORDS, PROMPT_VERSION
from generators.json_validate import parse_json_reply, validate_article_json, validate_draft_json
from generators.quality_gate import validate_post, validate_longform, is_similar_to_recent, clean_redundant_symbol_references, proofread_post, validate_mode_post
from processors.draft_scoring import _token_numbers
from storage.post_history import record_post as add_to_recent
import logging_config
import logging

logger = logging_config.get_logger("post_generator")

# Last successful generation, for the per-post CSV log (the
# orchestrator reads it at schedule time): the drawn angle plus the
# provider/model that actually answered (from llm.last_call_meta).
# generate_longform resets the angle to None on success. Single
# processor worker, so no race; a concurrent caller would overwrite
# it (same known limitation as llm.last_call_meta).
LAST_DRAFT_META: dict = {}

# Setup audit logger
audit_logger = logging.getLogger('post_audit')
if not audit_logger.handlers:
    audit_handler = logging.FileHandler('logs/post_audit.log')
    audit_handler.setFormatter(logging.Formatter('%(asctime)s|%(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
    audit_logger.addHandler(audit_handler)


def _fmt_price(price: float) -> str:
    """Format harga dengan presisi yang sama seperti data anchor."""
    if price < 0.001:
        return f"${price:.7f}"
    if price < 1:
        return f"${price:.4f}"
    return f"${price:.2f}"


def news_price_context(token: Dict[str, Any]) -> str:
    """Perbandingan harga/volume saat berita ditempel vs sekarang.

    Kedua angka berasal dari ticker 24h Binance: harga/volume saat
    collector menempel katalis vs saat post di-generate. Volume 24h
    adalah angka rolling, jadi yang dibandingkan adalah "volume 24h
    saat itu vs sekarang" — bukan volume pada menit berita keluar.
    Kembalikan "" kalau tidak ada snapshot (token tanpa katalis, atau
    snapshot 0) supaya prompt tidak mengandung angka karangan.
    """
    if not token.get("news_catalyst"):
        return ""
    price_then = token.get("price_at_news", 0) or 0
    price_now = token.get("price", 0) or 0
    if not price_then or not price_now:
        return ""
    chg = (price_now - price_then) / price_then * 100
    parts = [f"price at news time {_fmt_price(price_then)}, "
             f"now {_fmt_price(price_now)} ({chg:+.1f}%)"]
    vol_then = token.get("volume_at_news", 0) or 0
    vol_now = token.get("volume_24h", 0) or 0
    if vol_then and vol_now:
        vol_chg = (vol_now - vol_then) / vol_then * 100
        parts.append(f"24h volume at news time ${vol_then / 1_000_000:.1f}M, "
                     f"now ${vol_now / 1_000_000:.1f}M ({vol_chg:+.1f}%)")
    return "news price context: " + "; ".join(parts)


def _data_section(token: Dict[str, Any]) -> str:
    """The data anchor + range/news context shared by short and
    long-form prompts. Same numbers, same wording — one source of
    truth so the two formats can never disagree about the data."""
    symbol = token["symbol"]
    price = token.get("price", 0)
    chg = token.get("price_change_percent", 0)
    volume_raw = token.get("volume_24h", 0)
    range_pos = token.get("range_position", 0.5)
    data_anchor = generate_data_anchor(symbol, price, chg, volume_raw)
    news = token.get("news_catalyst", "")
    news_context = f"\nrelevant news: {news}" if news else ""
    price_context = news_price_context(token)
    price_context_line = f"\n{price_context}" if price_context else ""

    if range_pos >= 0.85:
        range_context = f"${symbol} trading near 24h high."
    elif range_pos <= 0.15:
        range_context = f"${symbol} trading near 24h low."
    else:
        range_context = ""

    # Snapshot context (image posts only): prepare_post enriches the
    # token copy with these fields, so the prompt carries the same
    # derived numbers the card shows. Short/long-form tokens never
    # carry volume_ratio_7d, so their prompts are byte-identical.
    snapshot_context = ""
    ratio = token.get("volume_ratio_7d")
    if ratio is not None:
        try:
            snapshot_context += f"\nvolume vs 7-day average: {float(ratio):.1f}x"
        except (TypeError, ValueError):
            pass
        btc = token.get("btc_change_24h")
        if btc is not None:
            try:
                snapshot_context += (
                    f"\nBTC 24h change: {float(btc):+.1f}% "
                    f"(this token {float(chg) - float(btc):+.1f} pts vs BTC)")
            except (TypeError, ValueError):
                pass

    data_section = data_anchor
    if range_context:
        data_section += f"\n{range_context}"
    if news_context:
        data_section += news_context
    if price_context_line:
        data_section += price_context_line
    if snapshot_context:
        data_section += snapshot_context
    return data_section


# ------------------------------------------------------------------
# Experiment modes (worker C, audit §G): one instruction block per
# short-form mode, in exactly one place. `mode` is one of pulse /
# contrarian / onchain (deep-signal goes through generate_longform,
# not here). A mode post always ends with one SPECIFIC discussion
# question (audit §G.5: a number, a choice, or a falsifiable claim
# in it) — the gate enforces presence only; the prompt teaches the
# specificity.
# ------------------------------------------------------------------
MODE_INSTRUCTIONS = {
    "pulse": (
        "MODE: Market Pulse — one move, one reason it matters, one question.\n"
        "Headline: line 1 is {symbol} + the fact (price + change + volume, exact); "
        "line 2 is the hook. The headline block is at most 2 lines, "
        "each line at most 90 characters. Then the one-sentence read, "
        "then the question. No background paragraph, no disclaimer paragraph."),
    "contrarian": (
        "MODE: Contrarian View — take a position the consensus would argue with, and show the evidence.\n"
        "State what everyone believes in one sentence, fairly stated; give 2-3 checkable facts "
        "from the SNAPSHOT; state the author's stance; and state what would prove the author wrong."),
    "onchain": (
        "MODE: On-chain Watch — numbers first, narrative second.\n"
        "Lead with one metric + its source + timeframe, say what changed vs the previous reading, "
        "what it means in one paragraph, and what to watch next (one specific level or event)."),
}
MODE_QUESTION_LINE = (
    "End the post with ONE specific discussion question — a question with a number, a choice, "
    "or a falsifiable claim in it (audit §G.5). The question must be the last sentence of the post.")


def build_prompt(token: Dict[str, Any], category: str, scores: Dict[str, float] | None = None,
                 opening_angle: "tuple[str, str] | None" = None,
                 closing_question: bool = False,
                 reaction: "tuple[str, str] | None" = None,
                 memory: "str | None" = None,
                 snapshot_dict: "dict | None" = None,
                 avoid_openers: "list[str] | None" = None,
                 mode: "str | None" = None) -> str:
    """Build the user prompt for one post.

    Editorial v2: the style is selected from the token's own data
    (see prompts.styles.select_editorial_style) and the prompt carries
    the style guidance plus the voice calibration. Nothing is forced
    verbatim — no hook first line, no angle paragraph, no closing line.
    The old build_prompt forced all three, which is exactly the
    identical-structure template Editorial v2 removes.

    The opening angle is the one exception to "nothing forced": it is
    an instruction (never verbatim text) drawn from a rotating deck,
    so consecutive posts open differently instead of converging on
    the model's default price-move opener. Callers may pass an
    explicit (name, instruction) pair; otherwise one is drawn here.

    On the JIT path the angle is replaced by a REACTION (see
    prompts/reactions.py): the same instruction-block mechanism, but
    the opener is a human reaction to the data shape, and first
    person is allowed in the opening line only. When a reaction is
    passed, no angle is drawn and the person rule is relaxed for the
    opener line alone; the rest of the prompt is identical.

    closing_question=True is the second, deliberate exception —
    image posts only: the post must end with a closing question,
    which the card then repeats verbatim (see extract_closing_
    question). Text posts keep the no-forced-question rule.

    memory is a pre-formatted MEMORY block (see
    storage/memory_store.format_memory_block) describing the last
    post about this token, or None. It is appended to the DATA
    section so reactions may draw on it; it is never required.

    Step 1 (JSON output): the prompt carries the snapshot as JSON
    (cite ONLY numbers from it), the 5 most recent scheduled openers
    as an avoid-list, a 2-good/1-bad few-shot subset for the drawn
    reaction (pooled across reactions on the flag-off path), and the
    JSON instruction. The system prompt (REBATE_SYSTEM_CORE) stays
    format-agnostic — the JSON contract lives here, in the user
    prompt, so Luna never sees conflicting format demands.
    """
    symbol = token["symbol"]
    if mode is not None and mode not in MODE_INSTRUCTIONS:
        raise ValueError(f"unknown mode: {mode!r}")
    mode_block = ""
    if mode is not None:
        mode_block = (
            "\n" + MODE_INSTRUCTIONS[mode].format(symbol=f"${symbol}")
            + "\n" + MODE_QUESTION_LINE)
    data_section = _data_section(token)
    if memory:
        data_section += f"\nMEMORY: {memory}"

    style = select_editorial_style(token, scores)
    reaction_name = reaction[0] if reaction is not None else None
    if reaction is not None:
        _, reaction_text = reaction
        opening_block = (
            f"OPENING REACTION: {reaction_text}\n"
            "The first line decides whether the reader stops scrolling. Follow the\n"
            "reaction above — react to the data the way a person following this\n"
            "token would, do NOT open with a plain price-move sentence. The post\n"
            f"MUST begin with ${symbol} as the very first characters: put the\n"
            "reaction voice AFTER the cashtag in the same first line, never\n"
            "before it. Do NOT open with any reaction word or phrase before the\n"
            "cashtag — no leading I, Wait, Hmm, Hold on, So, Now, Again,\n"
            "Surprise, or any other word before the cashtag. Shape:\n"
            f"\"${symbol} did it again, third fade this week...\" — cashtag\n"
            "first, reaction second."
        )
        person_rule = ("- First person (\"I\") is allowed ONLY AFTER the cashtag in the "
                       "opening line, never as the first word. No \"we\", no "
                       "\"you\" anywhere; the rest of the post stays third-person.")
        drawn_angle = reaction_name
    else:
        angle_name, angle_text = opening_angle or next_opening_angle()
        opening_block = (
            f"OPENING ANGLE: {angle_text}\n"
            "The first line decides whether the reader stops scrolling. Follow the\n"
            "angle above — do NOT open with a plain price-move sentence. The first\n"
            f"line still carries ${symbol} exactly once: weave the cashtag into the\n"
            "angle, do not bolt a price sentence in front of it."
        )
        person_rule = "- No first or second person: no \"i\", \"we\", \"you\"."
        drawn_angle = angle_name
    if closing_question or mode is not None:
        # Mode posts always end with the specific closing question
        # (MODE_QUESTION_LINE above); image posts keep the old rule.
        ending_rule = ("- End the post with a closing question: the question "
                       "the observation raises. It must be the last sentence "
                       "of the post.")
    else:
        ending_rule = ("- End where the observation ends. No forced closing line, "
                       "no forced question, no \"watching from here\" style sign-off.")

    # SNAPSHOT JSON: the numbers the post may cite, and only those.
    # A missing field means that comparison is unavailable — the
    # prompt says so plainly instead of letting the model invent it.
    snapshot_block = ""
    if snapshot_dict:
        snapshot_block = (
            "\nSNAPSHOT (JSON — cite ONLY numbers from here):\n"
            f"{json.dumps(snapshot_dict, sort_keys=True)}")
        missing = []
        if "btc_change" not in snapshot_dict:
            missing.append("BTC 24h change is unavailable — do not mention "
                           "any BTC comparison.")
        if "volume_ratio" not in snapshot_dict:
            missing.append("Volume vs 7-day average is unavailable — do not "
                           "mention it.")
        if "range_position" not in snapshot_dict:
            missing.append("Position in the 24h range is unavailable — do "
                           "not mention it.")
        if missing:
            snapshot_block += "\n" + " ".join(missing)

    # AVOID-LIST: first lines of the most recent scheduled posts.
    avoid_block = ""
    if avoid_openers:
        lines = []
        for text in avoid_openers[:5]:
            first = (text or "").split("\n")[0].strip()
            if first:
                lines.append(f"- {first}")
        if lines:
            avoid_block = (
                "\nAVOID THESE OPENERS — the last scheduled posts opened "
                "this way; do not repeat their first lines:\n"
                + "\n".join(lines))

    # FEW-SHOT: 2 good + 1 bad for the drawn reaction (pooled across
    # reactions on the flag-off path, where there is no reaction).
    fewshot_block = ""
    examples = load_fewshot_examples(reaction_name)
    good = [post for kind, post in examples if kind == "good"]
    bad = [post for kind, post in examples if kind == "bad"]
    if good or bad:
        parts = ["\nEXAMPLES — follow the good ones' voice and shape, "
                 "never copy their wording:"]
        if good:
            parts.append("GOOD EXAMPLES:")
            parts += [f"{i}. {post}" for i, post in enumerate(good, 1)]
        if bad:
            parts.append("BAD EXAMPLES — do not do this:")
            parts += [f"{i}. {post}" for i, post in enumerate(bad, 1)]
        fewshot_block = "\n".join(parts)

    json_instruction = (
        "Reply with a single JSON object and nothing else:\n"
        '{"event": "<what happened, one sentence>", '
        '"fact": "<the key number(s) from the SNAPSHOT>", '
        '"interpretation": "<why it may matter, one or two sentences>", '
        f'"angle": "{drawn_angle}", '
        '"post": "<the post>"}'
        f"\nRules for the JSON: \"angle\" MUST be exactly \"{drawn_angle}\". "
        f"\"post\" is 40-90 words, MUST begin with ${symbol} as the very "
        "first characters, exactly one cashtag in the first line; afterwards "
        "refer to \"the token\". Cite ONLY numbers from the SNAPSHOT above "
        "(MEMORY is context, not citable numbers). Do not wrap the post in "
        "tags, no markdown fences, no prose outside the JSON object.")

    prompt = f"""You are writing a short market observation post for Binance Square.

GOAL: Make the reader curious enough to check ${symbol}'s chart.

{opening_block}{mode_block}

DATA:
{data_section}{snapshot_block}{avoid_block}{fewshot_block}

EDITORIAL STYLE: {style}
{STYLE_GUIDANCE[style]}

{VOICE_CALIBRATION}

RULES:
- Lowercase everything except ${symbol} and other $TOKENS
- Use only the DATA above. Never invent numbers, technical levels,
  catalysts, or market sentiment.
- An interpretation is a view with reasons, not a trade instruction:
  never tell readers to buy, sell, hold, enter, or exit, and never
  present the post as financial advice.
- Observable facts first, interpretation second.
- Explain why the behavior may matter.
- Compare the move to normal market behavior when relevant.
- Short by default (40-90 words). Longer only when the observation
  needs the room; never pad to fill space.
- Separate paragraphs with ONE blank line. Never write large text blocks.
- Paragraph count and lengths must vary; do not fall into a fixed shape.
{ending_rule}
- Do not mention related tokens unless directly relevant to the data.
- $SYMBOL and all token tickers MUST be uppercase: $XRP not $xrp, $BTC not $btc
- Volume format: use capital M, $106.0M not $106.0m
- Refer to the token as ${symbol} (with $ prefix, uppercase) exactly ONCE, in the first line. In every later sentence use "the token" — never repeat the cashtag.
{person_rule}

{json_instruction}"""
    return prompt


# ------------------------------------------------------------------
# Article redesign (spec §4.1): the research pack is the single
# source of truth for a long-form article — code-built, no LLM.
# ------------------------------------------------------------------

# Gaps that are NEVER collected by any existing collector, so LIMITS
# must name them specifically instead of papering them over (§4.1).
_MISSING_UNAVAILABLE = (
    ">24h price history",
    "market cap at move time",
    "funding rates and open interest",
    "holder flows",
    "order-book depth",
    "sub-hourly timing",
    "catalyst source beyond RSS text",
)


def build_research_pack(token: Dict[str, Any], snapshot, category: str,
                        justification, memory: "str | None" = None) -> dict:
    """Build the research pack for one long-form article (spec §4.1).

    `snapshot` is a CardSnapshot or None (klines failed — the article
    still generates from the token dict, and the pack marks the
    snapshot fields missing). Keys: facts / stance / angle /
    catalyst / memory / missing. `facts` is the snapshot dict (or
    the token dict when snapshot is None) PLUS code-derived path
    facts from the closes; `stance` is the code-derived stance;
    `angle` is the select_post_format justification that triggered
    long-form; `missing` is the two-group split (fillable-but-absent
    vs genuinely-unavailable).
    """
    # Local import: schedulers/ must never be imported at module
    # load by generators/ (orchestrator imports both ways round).
    from schedulers.snapshot import snapshot_dict_for_prompt

    facts = snapshot_dict_for_prompt(token, snapshot)
    if snapshot is not None:
        try:
            facts.update(snapshot.path_facts())
        except Exception:
            pass

    chg = token.get("price_change_percent", 0) or 0
    stance = derive_stance(chg, category)
    if justification is None:
        _, justification = select_post_format_with_reason(token, category)

    catalyst = None
    news = token.get("news_catalyst")
    if news:
        catalyst = {"text": news}
        if token.get("price_at_news"):
            catalyst["price_at_news"] = token.get("price_at_news")
        if token.get("volume_at_news"):
            catalyst["volume_at_news"] = token.get("volume_at_news")

    fillable = []
    if "volume_ratio" not in facts:
        fillable.append("volume vs 7-day average")
    if "btc_change" not in facts:
        fillable.append("BTC 24h change")
    if "range_position" not in facts:
        fillable.append("position in the 24h range")
    if catalyst is None:
        fillable.append("news catalyst")

    return {
        "facts": facts,
        "stance": stance,
        "angle": justification,
        "catalyst": catalyst,
        "memory": memory,
        "missing": {
            "fillable": fillable,
            "unavailable": list(_MISSING_UNAVAILABLE),
        },
    }


def _assemble_article_body(article: dict) -> str:
    """The publishable body text of a validated article JSON: the 7
    sections with their uppercase labels, in order."""
    labels = (
        ("THESIS", "thesis"),
        ("WHAT HAPPENED", "what_happened"),
        ("WHY IT MATTERS", "why_it_matters"),
        ("BULL CASE", "bull_case"),
        ("BEAR CASE", "bear_case"),
        ("LIMITS AND INVALIDATION", "limits"),
        ("CONCLUSION", "conclusion"),
    )
    parts = []
    for label, key in labels:
        parts.append(f"{label}\n\n{article[key].strip()}")
    return "\n\n".join(parts)


def build_longform_prompt(token: Dict[str, Any], category: str,
                          scores: Dict[str, float] | None = None,
                          research_pack: "dict | None" = None,
                          require_question: bool = False) -> str:
    """Build the user prompt for one long-form article (redesign,
    spec §3.2/§4.2).

    Research pack as JSON + the section contracts (each section's job
    stated once) + the §3.1 principles stated once. The old prompt's
    ~7x repeated caution is deleted, not reworded: the prompt says
    "never invent" exactly once, and the system prompt is the trimmed
    REBATE_SYSTEM_CORE. Output is JSON (same contract as step 1).
    Callers that already built a pack pass it; otherwise one is
    built here from the token (no snapshot, no memory).

    require_question (experiment): add ONE line instructing that
    CONCLUSION must end with one specific discussion question. The
    line repeats no section job and no §3.1 principle, so the
    prompt-contract tests still count each exactly once.
    """
    import json as _json

    symbol = token["symbol"]
    if research_pack is None:
        _, justification = select_post_format_with_reason(
            token, category, scores)
        research_pack = build_research_pack(token, None, category,
                                            justification)
    pack = research_pack
    stance = pack["stance"]
    chg = token.get("price_change_percent", 0) or 0
    verb = verb_for_change(chg)
    lo, hi = LONGFORM_TARGET_WORDS
    memory_block = f"\nMEMORY: {pack['memory']}" if pack.get("memory") else ""
    question_line = ""
    if require_question:
        question_line = ("\nCONCLUSION must end with one specific discussion "
                         "question (a number, a choice, or a falsifiable "
                         "claim) — it is the post's discussion prompt.")

    prompt = f"""You are writing a long-form market analysis article for Binance Square.

GOAL: Explain what is happening with ${symbol} and what would prove the read wrong.

STANCE (code-derived — argue this stance, do not choose another): {stance}
ANGLE (why this is an article): {pack.get("angle")}
HEADLINE VERB for a {chg:+.1f}% move: {verb}

RESEARCH PACK (JSON — cite ONLY numbers from here):
{_json.dumps(pack, sort_keys=True, default=str)}{memory_block}

PRINCIPLES (each applies once):
- Every section must add information no earlier section stated.
- A limitation is stated once, in LIMITS AND INVALIDATION only.
- Separate fact, interpretation, speculation: a fact is a RESEARCH PACK number; an interpretation is a read labeled by its reasons; speculation names the unknown and the specific datum that would resolve it, and belongs only in LIMITS AND INVALIDATION and CONCLUSION.
- State a conclusion when the data supports it: the article argues the stance above.
- Missing data is named specifically, from the MISSING list in the research pack — never "limited data" in the abstract.

SECTIONS — {lo}-{hi} words total. Each section has one job; do that job and nothing else:
- THESIS (60-90 words, one paragraph): the stance, the single strongest reason, and the one number that matters most. No caveats, no meta-commentary.
- WHAT HAPPENED (80-120 words): the tape as a path — where price sits in its 24h range, volume vs its 7-day average, BTC-relative performance. Numbers stated here are not repeated in later sections, except the headline number in THESIS.
- WHY IT MATTERS (80-120 words): market context — what this move means vs normal behavior for this token, and who it matters to. The comparison is the new information, not the move.
- BULL CASE (60-100 words): the strongest bull argument from the data, with its number. Or the single sentence "No bullish case in these data." and stop.
- BEAR CASE (60-100 words): the mirror of BULL CASE, analysis first, at most one closing sentence of scope.
- LIMITS AND INVALIDATION (60-90 words): the only section that states limitations. Each limitation once, named from the MISSING list. Plus one specific invalidation condition: a price level or a data point that would prove the read wrong.
- CONCLUSION (40-70 words): restate the stance and the single condition to watch, in one line. No new claims, no new numbers, no fresh hedging. Must end with terminal punctuation.{question_line}

RULES:
- Lowercase everything except ${symbol} and other $TOKENS
- Use only the RESEARCH PACK above. Never invent numbers, technical levels, catalysts, or market sentiment.
- An interpretation is a view with reasons, not a trade instruction: never tell readers to buy, sell, hold, enter, or exit, and never present the article as financial advice.
- Refer to the token as ${symbol} (with $ prefix, uppercase) exactly ONCE, in the first line of the body. In every later sentence use "the token" — never repeat the cashtag.
- Do not mention related tokens unless directly relevant to the data.
- $SYMBOL and all token tickers MUST be uppercase: $XRP not $xrp, $BTC not $btc
- Volume format: use capital M, $106.0M not $106.0m
- No first or second person: no "i", "we", "you".
- Separate paragraphs with ONE blank line. Never write large text blocks.

Reply with a single JSON object and nothing else:
{{"title": "<article title, Title Case, no cashtag, <= 200 chars>", "stance": "{stance}", "thesis": "<THESIS>", "what_happened": "<WHAT HAPPENED>", "why_it_matters": "<WHY IT MATTERS>", "bull_case": "<BULL CASE>", "bear_case": "<BEAR CASE>", "limits": "<LIMITS AND INVALIDATION>", "conclusion": "<CONCLUSION>", "headline": "<short punchy headline, <= 90 chars>", "deck": "<one supporting sentence, <= 140 chars>"}}
Rules for the JSON: "stance" MUST be exactly "{stance}". "headline" uses the headline verb above when it carries a verb. "deck" names a catalyst only when the research pack names one, and then verbatim. No markdown fences, no prose outside the JSON object."""
    return prompt


def generate_longform(token: Dict[str, Any], category: str, scores: Dict[str, float],
                      snapshot=None, justification=None,
                      memory: "str | None" = None,
                      require_question: bool = False) -> Optional[tuple[str, str]]:
    """Generate one long-form article as JSON. Returns (title, body)
    or None.

    One LLM call via output_format="json" (the step-1 bypass), parsed
    with parse_json_reply, then the §6 gates: validate_longform first,
    then validate_article_json. Max 1 retry carrying the failure
    reason (a finish_reason=length reply retries with a shorter
    "500 words max" target); after the retry fails the article is
    skipped and prepare_draft falls back to a short post
    (LONGFORM_FALLBACK). System prompt is REBATE_SYSTEM_CORE.
    On success the validated article JSON is stashed under
    LAST_DRAFT_META["article"] and the research pack under
    LAST_DRAFT_META["research_pack"] (finalize_draft reads these for
    the banner; when absent it falls back to the code-built headline).

    require_question (experiment, default False = today's behavior):
    the prompt instructs CONCLUSION to end with one specific
    discussion question, and after validate_article_json passes the
    CONCLUSION must end with "?" — otherwise the article is
    rejected with 1 retry carrying the failure reason, then None.
    """
    import re

    skip_reason = insufficient_insight(token, scores)
    if skip_reason:
        print(f"  ⏭️ Skipping long-form ${token['symbol']}: {skip_reason}")
        audit_logger.info(f"SKIPPED_LONGFORM|{token['symbol']}|{category}|{skip_reason}")
        return None

    symbol = token["symbol"]
    if justification is None:
        _, justification = select_post_format_with_reason(token, category, scores)
    pack = build_research_pack(token, snapshot, category, justification,
                               memory=memory)
    prompt = build_longform_prompt(token, category, scores, research_pack=pack,
                                   require_question=require_question)

    article = None
    body = None
    title = None
    last_reason = None
    last_gate = None
    current_prompt = prompt
    for attempt in (1, 2):
        content = generate(current_prompt, system_prompt=REBATE_SYSTEM_CORE,
                           category=category, output_format="json",
                           max_tokens=LONGFORM_MAX_TOKENS)
        if not content or not isinstance(content, str):
            audit_logger.warning(f"GENERATE_LONGFORM_FAILED|{symbol}|{category}|no_content")
            return None

        # §6.6a: a non-empty reply cut by finish_reason=length is a
        # truncation, not a success — reject and retry shorter.
        finish = (llm.last_call_meta or {}).get("finish_reason")
        if finish == "length":
            last_reason = "truncated_length"
            last_gate = "6a"
            audit_logger.info(
                f"VALIDATION_FAILED_LONGFORM|{symbol}|{category}|reason={last_reason}|attempt={attempt}")
            if attempt == 1:
                current_prompt = (
                    prompt + "\n\nYour previous reply was cut off before "
                    "finishing (finish_reason=length). Rewrite the article "
                    "at 500 words max, keeping all 11 JSON keys.")
                continue
            break

        parsed = parse_json_reply(content)
        if parsed is None:
            last_reason = "json_invalid"
            last_gate = "6b"
            detail = "json_invalid"
        else:
            title_candidate = re.sub(r"\$([A-Z]+)", r"\1",
                                     str(parsed.get("title") or "")).strip()
            body_candidate = ""
            if isinstance(parsed, dict) and all(
                    k in parsed and isinstance(parsed[k], str)
                    for k in ("thesis", "what_happened", "why_it_matters",
                              "bull_case", "bear_case", "limits", "conclusion")):
                body_candidate = _assemble_article_body(parsed)
            valid, result = validate_longform(
                title_candidate, body_candidate, symbol=symbol)
            if not valid:
                last_reason = result
                last_gate = "6b"
                detail = result
            else:
                ok, reason, gate = validate_article_json(
                    parsed, pack["facts"], pack)
                if not ok:
                    last_reason = reason
                    last_gate = gate
                    detail = f"gate {gate}: {reason}"
                elif (require_question
                        and not str(parsed.get("conclusion") or "")
                        .strip().endswith("?")):
                    # Question gate (experiment): CONCLUSION must end
                    # with one specific discussion question. Same
                    # 1-retry mechanism as every other failure.
                    last_reason = "conclusion_missing_question"
                    last_gate = "question"
                    detail = ("CONCLUSION must end with one specific "
                              "discussion question")
                else:
                    article = parsed
                    title = title_candidate
                    body = result.strip()
                    break
        audit_logger.info(
            f"VALIDATION_FAILED_LONGFORM|{symbol}|{category}|reason={last_reason}|attempt={attempt}")
        if attempt == 1:
            current_prompt = (
                prompt + "\n\nYour previous reply failed validation: "
                f"{detail}. Fix ONLY that and reply with the JSON object again.")
    if article is None or body is None:
        audit_logger.info(
            f"REJECTED_LONGFORM|{symbol}|{category}|{last_reason}|gate={last_gate}")
        return None

    # Exactly-1 cashtag: the model may cite $SYMBOL in several
    # sections; keep the first, rewrite the rest as "the token". If
    # it cited none, open THESIS with it (the old flow prepended it
    # to the body the same way).
    if f"${symbol}" not in body.upper():
        body = body.replace("THESIS\n\n", f"THESIS\n\n${symbol} ", 1)
    body = clean_redundant_symbol_references(body, symbol)

    if is_similar_to_recent(title + "\n\n" + body):
        print("  🔄 Long-form too similar to recent, skipping...")
        return None

    add_to_recent(title + "\n\n" + body)

    # Long-form carries no opener angle: reset LAST_DRAFT_META so a
    # later schedule-time read cannot pick up a stale short-form angle.
    meta = llm.last_call_meta or {}
    LAST_DRAFT_META.clear()
    LAST_DRAFT_META.update({
        "angle": None,
        "provider": meta.get("provider") or "",
        "model": meta.get("model") or "",
        "article": article,
        "research_pack": pack,
    })

    audit_logger.info(f"GENERATED_LONGFORM|{symbol}|{category}|{len(body)}_chars")
    return title, body


def extract_closing_question(content: str):
    """The post's closing question, or None.

    The last sentence of the post, when the post ends with '?'.
    Pure string work — the question is generated as part of the
    post (one LLM call) and passed to the renderer, never invented
    by it. Returns None when the post does not end with a question,
    and the card then omits the question row.
    """
    import re

    stripped = (content or "").strip()
    if not stripped.endswith("?"):
        return None
    sentences = re.split(r"(?<=[.!?])\s+", stripped)
    last = sentences[-1].strip() if sentences else ""
    return last or None


def generate_post(token: Dict[str, Any], category: str, scores: Dict[str, float],
                  opening_angle: "tuple[str, str] | None" = None,
                  closing_question: bool = False,
                  reaction: "tuple[str, str] | None" = None,
                  memory: "str | None" = None,
                  snapshot=None, snapshot_dict: "dict | None" = None,
                  avoid_openers: "list[str] | None" = None,
                  card_type: "str | None" = None,
                  mode: "str | None" = None) -> Optional[dict]:
    """Generate one short-form post as a JSON dict.

    Returns {"event", "fact", "interpretation", "angle", "post"} or
    None. Only "post" is published; the other fields are the LLM's
    structured reasoning (logged, never posted). The reply is
    parsed + validated in code (JSON shape, angle echo, numbers vs
    snapshot, forbidden phrases, quality gate); one retry on
    validation failure, then the draft is skipped. Long-form keeps
    the old <post>-tag flow (generate_longform) — this function is
    short-form only.

    `mode` (experiment): pulse / contrarian / onchain. When set, the
    prompt carries the mode instruction block + the closing-question
    ending rule, and the validation loop adds the mode checks +
    the question gate (validate_mode_post) before accepting the
    post — same 1-retry mechanism as every other failure.
    """
    # Quality over quota: skip before any LLM call when there is
    # genuinely nothing to observe. The reason is audit-logged so the
    # skip rate can be evaluated (Editorial v2 KPI).
    skip_reason = insufficient_insight(token, scores)
    if skip_reason:
        print(f"  ⏭️ Skipping ${token['symbol']}: {skip_reason}")
        audit_logger.info(f"SKIPPED|{token['symbol']}|{category}|{skip_reason}")
        return None

    # Draw the opening angle here (not inside build_prompt) so the
    # audit log can record which angle each published post used.
    # Callers may pass an explicit angle (card-type mapping for
    # image posts); it is recorded as used today, like a draw.
    # A reaction replaces the angle entirely (JIT path): no angle is
    # drawn or recorded, and the reaction itself is NOT recorded
    # here — the pool records only the winning draft's reaction.
    reaction_name = None
    if reaction is not None:
        angle_name = None
        reaction_name, _ = reaction
    elif opening_angle is None:
        angle_name, angle_text = next_opening_angle()
        opening_angle = (angle_name, angle_text)
    else:
        angle_name, angle_text = opening_angle
        record_angle_used(angle_name)
    drawn_angle = reaction_name or angle_name

    prompt = build_prompt(token, category, scores,
                          opening_angle=opening_angle,
                          closing_question=closing_question,
                          reaction=reaction, memory=memory,
                          snapshot_dict=snapshot_dict,
                          avoid_openers=avoid_openers,
                          mode=mode)
    numbers = _token_numbers(token, snapshot)
    symbol = token["symbol"]

    # Validation loop: at most 2 attempts (1 call + 1 retry). The
    # first failure stops the pipeline and triggers the retry with
    # a note naming the failure; after the second failure the draft
    # is skipped, never posted.
    parsed = None
    post = None
    last_reason = None
    current_prompt = prompt
    for attempt in (1, 2):
        content = generate(current_prompt, system_prompt=REBATE_SYSTEM_CORE,
                           category=category, output_format="json",
                           max_tokens=1200)
        if not content or not isinstance(content, str):
            audit_logger.warning(f"GENERATE_FAILED|{symbol}|{category}|no_content")
            return None
        parsed = parse_json_reply(content)
        if parsed is None:
            last_reason = "json_invalid"
            detail = "json_invalid"
        else:
            ok, reason = validate_draft_json(parsed, drawn_angle, numbers,
                                             symbol=symbol)
            if not ok:
                last_reason = reason
                detail = reason
            else:
                candidate = parsed["post"]
                valid, result = validate_post(candidate, symbol=symbol)
                if not valid:
                    last_reason = "quality_gate"
                    detail = result
                elif mode is not None:
                    # Mode checks + question gate, before accepting.
                    # Same 1-retry mechanism as every other failure.
                    # (post is assigned ONLY on success: a failed
                    # attempt must never leak past the loop.)
                    candidate_post = result.strip()
                    ok_m, reason_m = validate_mode_post(
                        candidate_post, symbol, mode)
                    if not ok_m:
                        last_reason = reason_m
                        detail = reason_m
                    else:
                        post = candidate_post
                        break
                else:
                    post = result.strip()
                    break
        audit_logger.info(
            f"VALIDATION_FAILED|{symbol}|{category}|reason={last_reason}|attempt={attempt}")
        if attempt == 1:
            current_prompt = (
                prompt + "\n\nYour previous reply failed validation: "
                f"{detail}. Fix ONLY that and reply with the JSON object again.")
    if post is None:
        audit_logger.info(f"GENERATE_FAILED|{symbol}|{category}|reason={last_reason}")
        return None

    content = post

    if len(content) < 50:
        print(f"  🚫 Post too short ({len(content)} chars)")
        audit_logger.info(f"REJECTED|{symbol}|{category}|too_short_{len(content)}_chars")
        return None

    # Add $SYMBOL temporarily if missing (so cleaner can detect it)
    if symbol.upper() not in content.upper():
        content = f"${symbol} " + content

    # CLEAN REDUNDANT SYMBOL REFERENCES

    content = clean_redundant_symbol_references(content, symbol)
    content = proofread_post(content, symbol)

    # Ensure $SYMBOL present — but only add it if absent entirely.
    # Prepending when the ticker already sits mid-post would create
    # a second occurrence (the cleaner above already ran).
    if f"${symbol}" not in content.upper():
        content = f"${symbol} " + content

    # Check similarity with recent posts
    if is_similar_to_recent(content):
        print("  🔄 Post too similar to recent, skipping...")
        return None

    # Add to recent posts
    add_to_recent(content)

    # LAST_DRAFT_META: the drawn angle + the provider/model that
    # actually answered, for the per-post CSV log at schedule time.
    meta = llm.last_call_meta or {}
    LAST_DRAFT_META.clear()
    LAST_DRAFT_META.update({
        "angle": drawn_angle,
        "provider": meta.get("provider") or "",
        "model": meta.get("model") or "",
    })

    # AUDIT LOG: Post berhasil di-generate
    extra = (f"|card_type={card_type or 'none'}"
             f"|model={LAST_DRAFT_META['model']}"
             f"|provider={LAST_DRAFT_META['provider']}"
             f"|prompt_version={PROMPT_VERSION}")
    if reaction_name is not None:
        audit_logger.info(f"GENERATED|{symbol}|{category}|{len(content)}_chars|reaction={reaction_name}{extra}")
    else:
        audit_logger.info(f"GENERATED|{symbol}|{category}|{len(content)}_chars|angle={angle_name}{extra}")

    return {"event": parsed["event"], "fact": parsed["fact"],
            "interpretation": parsed["interpretation"],
            "angle": parsed["angle"], "post": content}
