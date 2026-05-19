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

GOAL: Make readers curious enough to check ${symbol}'s chart or token page.

DATA:
${symbol} {chg:+.1f}% at ${price_str}, volume ${vol_m:.1f}M.{news_context}

INSTRUCTIONS:
- 3-4 sentences total, all lowercase except $SYMBOL
- Use the provided HOOK as your opening line exactly as written
- Use the provided ANGLE as your second observation, reworded slightly using the data above
- Mention 1 related token briefly if relevant
- End with the provided CLOSING

HOOK (use this as your first sentence):
"{hook}"

ANGLE (use this as your core observation):
"{angle}"

CLOSING (end the post with this):
"{closing_line}"

TONE:
- calm, observational, practical
- low confidence wording: may, appears, looks, seems
- no urgency, no hype, no predictions

AVOID:
- moon, 100x, buy now, gem alert
- hidden, under the surface, accumulating quietly, nobody sees this
- long explanations or technical breakdowns
- generic filler like "the data suggests" or "worth watching closely"

Write the post inside <post> tags."""
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
