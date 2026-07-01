# generators/post_generator.py
from typing import Dict, Any, Optional
from llm import generate
from prompts.rebate import REBATE_SYSTEM
from prompts.styles import get_hook, get_angle, get_cta, get_transition, generate_data_anchor, get_closer
from generators.quality_gate import validate_post, is_similar_to_recent, clean_redundant_symbol_references, proofread_post
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


def build_prompt(token: Dict[str, Any], category: str) -> str:
    symbol = token["symbol"]
    price = token.get("price", 0)
    chg = token.get("price_change_percent", 0)
    volume_raw = token.get("volume_24h", 0)
    range_pos = token.get("range_position", 0.5)
    data_anchor = generate_data_anchor(symbol, price, chg, volume_raw)
    news = token.get("news_catalyst", "")
    news_context = f"\nrelevant news: {news}" if news else ""

    if range_pos >= 0.85:
        range_context = f"${symbol} trading near 24h high."
    elif range_pos <= 0.15:
        range_context = f"${symbol} trading near 24h low."
    else:
        range_context = ""

    data_section = data_anchor
    if range_context:
        data_section += f"\n{range_context}"

    if price < 0.001:
        price_str = f"{price:.7f}"
    elif price < 1:
        price_str = f"{price:.4f}"
    else:
        price_str = f"{price:.2f}"

    
    hook = get_hook(category)
    angle = get_angle()
    closer = get_closer()
    cta = get_cta(symbol)

    closing_line = closer

    # Generate data anchor for factual reference
    data_anchor = generate_data_anchor(symbol, price, chg, volume_raw)

    prompt = f"""You are writing a short market observation post for Binance Square.

GOAL: Make the reader curious enough to check ${symbol}'s chart.

DATA:
{data_section}

FORMAT:
- Write 4-6 short paragraphs.
- Separate EVERY paragraph with ONE blank line.
- Never write large text blocks.
- Some paragraphs may contain only one sentence.
- The post should feel readable for around 1-2 minutes.
- Start directly with the HOOK below.
- End with the CLOSING line below, verbatim.

HOOK - copy this as your FIRST LINE, word for word:
{hook}

ANGLE - use this as the basis for your second paragraph, reworded with the data above:
{angle}

CLOSING - Your final line must be exactly this, nothing after it:
{closing_line}

RULES:
- Lowercase everything except ${symbol} and other $TOKENS
- Use hedged language: may, appears, looks, seems
- Observable facts only. No predictions, no opinions.
- Do not mention related tokens unless directly relevant to the data.
- $SYMBOL and all token tickers MUST be uppercase: $XRP not $xrp, $BTC not $btc
- Volume format: use capital M, $106.0M not $106.0m
- Expand naturally from the provided data.
- Explain why the behavior may matter.
- Compare the move to normal market behavior when relevant.
- Mild interpretation is allowed.
- The post should feel like a trader thinking through the market in public.
- Avoid dramatic or mysterious language.
- Avoid sounding like a template or summary bot.
- Insert a blank line between every paragraph.
- Keep visual rhythm clean and easy to scan.
- Avoid dense walls of text.
- Always refer to the token as ${symbol} (with $ prefix, uppercase). Never drop the symbol mid-sentence.
- Never repeat the hook line anywhere else in the post.
- End with exactly ONE closing line. Do not add any sentence after the closing line.

FORBIDDEN PHRASES:
- "i'm curious", "it will be interesting", "in the coming days", "it looks like"
- "one might expect", "it's worth noting", "as one might"
- "i", "we", "you" (no first or second person)

Write the post inside <post> tags. Nothing outside the tags."""
    return prompt

def generate_post(token: Dict[str, Any], category: str, scores: Dict[str, float]) -> Optional[str]:
    prompt = build_prompt(token, category)
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

    # Ensure $SYMBOL at start
    if not content.startswith(f"${symbol}"):
        content = f"${symbol} " + content

    # Check similarity with recent posts
    if is_similar_to_recent(content):
        print(f"  🔄 Post too similar to recent, skipping...")
        return None
    
    # Add to recent posts
    add_to_recent(content)

    # AUDIT LOG: Post berhasil di-generate
    audit_logger.info(f"GENERATED|{symbol}|{category}|{len(content)}_chars")

    return content
