# processors/normalize.py
import time
from typing import Dict, Any

def normalize_token(raw: Dict[str, Any], source: str = None) -> Dict[str, Any]:
    """Normalize token data from any source into unified schema"""
    
    if source == "binance" or raw.get("source") == "binance":
        return {
            "symbol": raw["symbol"],
            "full_symbol": raw.get("full_symbol", f"{raw['symbol']}USDT"),
            "price": raw.get("price", 0),
            "price_change_percent": raw.get("price_change_percent", 0),
            "volume_24h": raw.get("volume_24h", 0),
            "high_24h": raw.get("high_24h", 0),
            "low_24h": raw.get("low_24h", 0),
            "trade_count": raw.get("trade_count", 0),
            "volume_rank": raw.get("volume_rank", 999),
            "source": "binance",
            "age_hours": raw.get("age_hours", 100),  # default old
            "liquidity": raw.get("volume_24h", 0),   # fallback
            "market_cap": raw.get("market_cap", 0),
            "timestamp": raw.get("timestamp", time.time()),
        }
    
    # Placeholder for GeckoTerminal normalization (nanti)
    if source == "gecko" or raw.get("source") == "gecko":
        return {
            "symbol": raw.get("symbol", "?"),
            "price": raw.get("price", 0),
            "price_change_percent": raw.get("percentChange1h", 0),
            "volume_24h": raw.get("volume24h", 0),
            "volume_rank": raw.get("volume_rank", 999),
            "source": "gecko",
            "age_hours": raw.get("age_hours", 100),
            "liquidity": raw.get("liquidity", 0),
            "market_cap": raw.get("marketCap", 0),
            "trade_count": raw.get("count1h", 0),
            "timestamp": time.time(),
        }
    
    # Default: assume already normalized
    return raw


def get_data_summary(token: Dict[str, Any]) -> str:
    """Generate short data string for LLM prompt"""
    sym = token["symbol"]
    price = token.get("price", 0)
    vol = token.get("volume_24h", 0) / 1_000_000  # to millions
    chg = token.get("price_change_percent", 0)
    
    vol_rank = token.get("volume_rank", "?")
    mcap = token.get("market_cap", 0)
    
    parts = [f"${sym} {chg:+.1f}%"]
    
    if price:
        if price < 0.001:
            parts.append(f"${price:.7f}")
        elif price < 1:
            parts.append(f"${price:.4f}")
        else:
            parts.append(f"${price:.2f}")
    
    if vol > 0:
        parts.append(f"${vol:.1f}M vol")
    
    if vol_rank and vol_rank != "?":
        parts.append(f"rank #{vol_rank}")
    
    if mcap and mcap > 0:
        parts.append(f"mcap ${mcap/1000:.0f}k")
    
    return " ".join(parts)
