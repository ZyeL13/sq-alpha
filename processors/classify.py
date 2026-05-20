# processors/classify.py
from typing import Dict, Any, Optional
from config import (
    HOT_VOLUME_RANK_MAX,
    HOT_PRICE_CHANGE_MAX,
    GAINER_THRESHOLD,
    LOSER_THRESHOLD,
    ALPHA_MAX_MCAP,
    ALPHA_MIN_VOLUME
)

MEGA_CAPS = {
    "BTC",
}


def classify(token: Dict[str, Any]) -> Optional[str]:
    symbol = token.get("symbol", "")
    price = token.get("price", 0)  # ✅ ambil price dari token
    
    # Skip stablecoins by price (0.99 - 1.01)
    if price and 0.99 <= price <= 1.01:
        return None
    
    if symbol in MEGA_CAPS:
        return None
    
    chg = token.get("price_change_percent", 0)
    vol_rank = token.get("volume_rank", 999)
    mcap = token.get("market_cap", 0)
    volume = token.get("volume_24h", 0)
    
    # HOT: top volume, small price change (anomaly)
    if vol_rank <= HOT_VOLUME_RANK_MAX and abs(chg) < HOT_PRICE_CHANGE_MAX:
        return "HOT"
    
    # GAINERS: strong upward movement
    if chg > GAINER_THRESHOLD:
        return "GAINERS"
    
    # LOSERS: strong downward movement
    if chg < LOSER_THRESHOLD:
        return "LOSERS"
    
    # ALPHA: small cap with decent volume
    if mcap < ALPHA_MAX_MCAP and volume > ALPHA_MIN_VOLUME:
        return "ALPHA"
    
    return None
