# generators/post_generator.py
from typing import Dict, Any, Optional
from llm import generate
from prompts.rebate import REBATE_SYSTEM
from prompts.styles import (
    STYLE_GUIDANCE,
    VOICE_CALIBRATION,
    generate_data_anchor,
    insufficient_insight,
    next_opening_angle,
    record_angle_used,
    select_editorial_style,
)
from config import LONGFORM_MAX_TOKENS
from generators.quality_gate import validate_post, validate_longform, is_similar_to_recent, clean_redundant_symbol_references, proofread_post
from storage.post_history import record_post as add_to_recent
import logging_config
import logging

logger = logging_config.get_logger("post_generator")

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


def build_prompt(token: Dict[str, Any], category: str, scores: Dict[str, float] | None = None,
                 opening_angle: "tuple[str, str] | None" = None,
                 closing_question: bool = False,
                 reaction: "tuple[str, str] | None" = None,
                 memory: "str | None" = None) -> str:
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
    """
    symbol = token["symbol"]
    data_section = _data_section(token)
    if memory:
        data_section += f"\nMEMORY: {memory}"

    style = select_editorial_style(token, scores)
    if reaction is not None:
        _, reaction_text = reaction
        opening_block = (
            f"OPENING REACTION: {reaction_text}\n"
            "The first line decides whether the reader stops scrolling. Follow the\n"
            "reaction above — react to the data the way a person following this\n"
            "token would, do NOT open with a plain price-move sentence. The first\n"
            f"line still carries ${symbol} exactly once: weave the cashtag into the\n"
            "reaction, do not bolt a price sentence in front of it."
        )
        person_rule = ("- First person (\"I\") is allowed ONLY in the opening line, as part "
                       "of the reaction. No \"we\", no \"you\" anywhere; the rest of "
                       "the post stays third-person.")
    else:
        _, angle_text = opening_angle or next_opening_angle()
        opening_block = (
            f"OPENING ANGLE: {angle_text}\n"
            "The first line decides whether the reader stops scrolling. Follow the\n"
            "angle above — do NOT open with a plain price-move sentence. The first\n"
            f"line still carries ${symbol} exactly once: weave the cashtag into the\n"
            "angle, do not bolt a price sentence in front of it."
        )
        person_rule = "- No first or second person: no \"i\", \"we\", \"you\"."
    if closing_question:
        ending_rule = ("- End the post with a closing question: the question "
                       "the observation raises. It must be the last sentence "
                       "of the post.")
    else:
        ending_rule = ("- End where the observation ends. No forced closing line, "
                       "no forced question, no \"watching from here\" style sign-off.")

    prompt = f"""You are writing a short market observation post for Binance Square.

GOAL: Make the reader curious enough to check ${symbol}'s chart.

{opening_block}

DATA:
{data_section}

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
- Short by default (40-120 words). Longer only when the observation
  needs the room; never pad to fill space.
- Separate paragraphs with ONE blank line. Never write large text blocks.
- Paragraph count and lengths must vary; do not fall into a fixed shape.
{ending_rule}
- Do not mention related tokens unless directly relevant to the data.
- $SYMBOL and all token tickers MUST be uppercase: $XRP not $xrp, $BTC not $btc
- Volume format: use capital M, $106.0M not $106.0m
- Refer to the token as ${symbol} (with $ prefix, uppercase) exactly ONCE, in the first line. In every later sentence use "the token" — never repeat the cashtag.
{person_rule}

Write the post inside <post> tags. Nothing outside the tags."""
    return prompt


def build_longform_prompt(token: Dict[str, Any], category: str, scores: Dict[str, float] | None = None) -> str:
    """Build the user prompt for one long-form article (V3 Phase 1).

    Same data section, system prompt, style selection and voice
    calibration as the short form — only the shape changes: a title
    line, then a structured article (thesis, what happened, why it
    matters, bull case, bear case, limitations/invalidation,
    conclusion). Section labels are plain uppercase lines, never
    markdown '#' headings (Square parses '#' as a hashtag and
    clean_for_square strips it).
    """
    symbol = token["symbol"]
    data_section = _data_section(token)
    style = select_editorial_style(token, scores)

    prompt = f"""You are writing a long-form market analysis article for Binance Square.

GOAL: Explain what is happening with ${symbol} and what would prove the read wrong.

DATA:
{data_section}

EDITORIAL STYLE: {style}
{STYLE_GUIDANCE[style]}

{VOICE_CALIBRATION}

STRUCTURE — write the article inside <post> tags, exactly like this:
- Line 1: the article title, in Title Case, on its own line. No cashtag in the title.
- Then ONE blank line.
- Then the body, 600-900 words, in sections. Each section starts with
  its label on its own line in UPPERCASE, then a blank line, then the
  prose. Use these sections, in this order:
  THESIS, WHAT HAPPENED, WHY IT MATTERS, BULL CASE, BEAR CASE,
  LIMITS AND INVALIDATION, CONCLUSION.
  A section may use a short list when the data genuinely calls for
  one; prose is the default.

RULES:
- Lowercase everything except ${symbol} and other $TOKENS
- Use only the DATA above. Never invent numbers, technical levels,
  catalysts, or market sentiment.
- An interpretation is a view with reasons, not a trade instruction:
  never tell readers to buy, sell, hold, enter, or exit, and never
  present the article as financial advice.
- Bull case and bear case must both be argued from the DATA, not
  from vibes. If one side has no support in the data, say so plainly
  instead of inventing it.
- State the limits of the read and the condition that would
  invalidate it. No fabricated certainty.
- Refer to the token as ${symbol} (with $ prefix, uppercase) exactly ONCE, in the first line of the body. In every later sentence use "the token" — never repeat the cashtag.
- Do not mention related tokens unless directly relevant to the data.
- $SYMBOL and all token tickers MUST be uppercase: $XRP not $xrp, $BTC not $btc
- Volume format: use capital M, $106.0M not $106.0m
- No first or second person: no "i", "we", "you".
- Separate paragraphs with ONE blank line. Never write large text blocks.

Write the article inside <post> tags. Nothing outside the tags."""
    return prompt


def generate_longform(token: Dict[str, Any], category: str, scores: Dict[str, float]) -> Optional[tuple[str, str]]:
    """Generate one long-form article. Returns (title, body) or None.

    Mirrors generate_post: skip check first, ONE LLM call (with the
    long-form-only max_tokens bump), format-aware validation, exactly-1
    cashtag cleaning. proofread_post is NOT applied — its paragraph
    reshaping would mangle article sections.
    """
    skip_reason = insufficient_insight(token, scores)
    if skip_reason:
        print(f"  ⏭️ Skipping long-form ${token['symbol']}: {skip_reason}")
        audit_logger.info(f"SKIPPED_LONGFORM|{token['symbol']}|{category}|{skip_reason}")
        return None

    prompt = build_longform_prompt(token, category, scores)
    content = generate(prompt, system_prompt=REBATE_SYSTEM, category=category,
                       max_tokens=LONGFORM_MAX_TOKENS)

    if not content or not isinstance(content, str):
        audit_logger.warning(f"GENERATE_LONGFORM_FAILED|{token['symbol']}|{category}|no_content")
        return None

    # Line 1 is the title, then a blank line, then the body.
    lines = [ln for ln in content.split("\n")]
    title = ""
    body_lines = []
    for i, line in enumerate(lines):
        if line.strip():
            title = line.strip().lstrip("#").strip()
            body_lines = lines[i + 1:]
            break
    body = "\n".join(body_lines).strip()
    if not title or not body:
        audit_logger.info(f"REJECTED_LONGFORM|{token['symbol']}|{category}|no_title_or_body")
        return None

    # A cashtag in the title would break the exactly-once count for
    # the article as published — strip the $ and keep the ticker name.
    import re
    title = re.sub(r"\$([A-Z]+)", r"\1", title)

    valid, result = validate_longform(title, body, symbol=token["symbol"])
    if not valid:
        logger.warning(f"Quality gate REJECTED long-form for ${token['symbol']}: {result}")
        audit_logger.info(f"REJECTED_LONGFORM|{token['symbol']}|{category}|{result}")
        return None
    body = result.strip()

    symbol = token["symbol"]
    if f"${symbol}" not in body.upper():
        body = f"${symbol} " + body

    body = clean_redundant_symbol_references(body, symbol)

    if is_similar_to_recent(title + "\n\n" + body):
        print("  🔄 Long-form too similar to recent, skipping...")
        return None

    add_to_recent(title + "\n\n" + body)

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
                  memory: "str | None" = None) -> Optional[str]:
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
    prompt = build_prompt(token, category, scores,
                          opening_angle=opening_angle,
                          closing_question=closing_question,
                          reaction=reaction, memory=memory)
    content = generate(prompt, system_prompt=REBATE_SYSTEM, category=category)

    if not content or not isinstance(content, str):
        # AUDIT LOG: Gagal generate dari LLM
        audit_logger.warning(f"GENERATE_FAILED|{token['symbol']}|{category}|no_content")
        return None
    
    # Quality validation
    valid, result = validate_post(content)
    if not valid:
        logger.warning(f"Quality gate REJECTED for ${token['symbol']}: {result}")
        # AUDIT LOG: Reject karena quality gate
        audit_logger.info(f"REJECTED|{token['symbol']}|{category}|{result}")
        return None
    
    content = result.strip()
    
    if len(content) < 50:
        print(f"  🚫 Post too short ({len(content)} chars)")
        audit_logger.info(f"REJECTED|{token['symbol']}|{category}|too_short_{len(content)}_chars")
        return None

    # Add $SYMBOL temporarily if missing (so cleaner can detect it)
    symbol = token['symbol']
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

    # AUDIT LOG: Post berhasil di-generate
    if reaction_name is not None:
        audit_logger.info(f"GENERATED|{symbol}|{category}|{len(content)}_chars|reaction={reaction_name}")
    else:
        audit_logger.info(f"GENERATED|{symbol}|{category}|{len(content)}_chars|angle={angle_name}")

    return content
