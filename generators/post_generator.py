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
    
    # Random style components
    hook = get_hook(category)
    angle = get_angle()
    transition = get_transition()
    cta = get_cta(symbol)
    
    if price < 0.001:
        price_str = f"{price:.7f}"
    elif price < 1:
        price_str = f"{price:.4f}"
    else:
        price_str = f"{price:.2f}"
    
    prompt = f"""${symbol} {chg:+.1f}% at ${price_str}. volume ${vol_m:.1f}M.

hook: {hook}
angle: {angle}
transition: {transition}
cta: {cta}

write 3-4 short paragraphs using above components as inspiration.
do not copy them exactly. use your own words.

output inside <post>."""
    
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
