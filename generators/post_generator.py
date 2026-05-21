# generators/post_generator.py
from typing import Dict, Any, Optional
from llm import generate
from prompts.rebate import REBATE_SYSTEM
from prompts.styles import get_hook, get_angle, get_cta, get_transition
from generators.quality_gate import validate_post, finalize_post


def build_prompt(token: Dict[str, Any], category: str) -> str:
    symbol = token["symbol"]
    price = token.get("price", 0)
    chg = token.get("price_change_percent", 0)
    vol_m = token.get("volume_24h", 0) / 1_000_000

    news = token.get("news_catalyst", "")
    news_context = f"\nrelevant news: {news}" if news else ""

    if price < 0.001:
        price_str = f"{price:.7f}"
    elif price < 1:
        price_str = f"{price:.4f}"
    else:
        price_str = f"{price:.2f}"

    from prompts.styles import get_hook, get_angle, get_cta, get_closer
    hook = get_hook(category)
    angle = get_angle()
    closer = get_closer()
    cta = get_cta(symbol)

    closing_line = f"{closer}\n{cta}" if closer else cta

    prompt = f"""You are writing a short market observation post for Binance Square.

GOAL: Make the reader curious enough to check ${symbol}'s chart.

DATA:
${symbol} {chg:+.1f}% | price: ${price_str} | volume: ${vol_m:.1f}M{news_context}

FORMAT:
- Write 4-7 short paragraphs.
- Separate EVERY paragraph with ONE blank line.
- Never write large text blocks.
- Some paragraphs may contain only one sentence.
- The post should feel readable for around 1-2 minutes.
- Start directly with the HOOK below.
- End with the CLOSING line below, verbatim.

HOOK — copy this as your FIRST LINE, word for word:
{hook}

ANGLE — use this as the basis for your second paragraph, reworded with the data above:
{angle}

CLOSING — this is your last line, copy exactly:
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
        return None
    
    # Quality validation
    valid, result = validate_post(content)
    if not valid:
        print(f"  🚫 Quality gate REJECTED for ${token['symbol']}: {result}")
        return None
    
    content = result.strip()
    
    if len(content) < 50:
        print(f"  🚫 Post too short ({len(content)} chars)")
        return None
    
    # Finalize (record for similarity check)
    content = finalize_post(content, token["symbol"])
    
    return content
