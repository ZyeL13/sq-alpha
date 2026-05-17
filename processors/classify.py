# processors/classify.py
from typing import Dict, Any, Optional
from collectors.binance import get_token_age_hours

MEGA_CAPS = {
    "BTC", "ETH", "BNB", "SOL", "XRP", "DOGE", "ADA", "TRX",
    "TON", "SUI", "NEAR", "PEPE", "SHIB", "LINK", "AVAX",
    "DOT", "MATIC", "UNI", "ATOM", "LTC", "ETC", "ICP", "BCH",
    "ZEC", "XMR", "DASH", "ZEN", "BTG",  # tambah token lama
}


def classify(token: Dict[str, Any]) -> Optional[str]:
    symbol = token.get("symbol", "")
    if symbol in MEGA_CAPS:
        return None
    
    chg = token.get("price_change_percent", 0)
    vol_rank = token.get("volume_rank", 999)
    mcap = token.get("market_cap", 0)
    volume = token.get("volume_24h", 0)
    
    # NEW category disabled (false positive too high)
    # if token.get("age_hours", 100) < 24:
    #     return "NEW"
    
    # HOT: top 15 volume, price change under 2% (anomaly)
    if vol_rank <= 15 and abs(chg) < 2.0:
        return "HOT"
    
    # GAINERS: up more than 7%
    if chg > 7:
        return "GAINERS"
    
    # LOSERS: down more than -7%
    if chg < -7:
        return "LOSERS"
    
    # ALPHA: small cap (< $1M) with decent volume
    if mcap < 1_000_000 and volume > 100_000:
        return "ALPHA"
    
    # SIGNAL: microcap (< $300k) with any volume (disabled, perlu Bitquery)
    # if mcap < 300_000 and volume > 50_000:
    #     return "SIGNAL"
    
    return None
