# collectors/coinmarketcap.py — optional market-cap fallback for ALPHA
#
# Used only when CMC_API_KEY is set (CoinMarketCap Basic plan is free:
# 15,000 credits/month, 50 req/min). Fills `market_cap` only for tokens
# CoinGecko did not cover, so CoinGecko stays the primary source.
import logging
from typing import Dict, Any, List

import requests

from config import CMC_API_KEY

log = logging.getLogger(__name__)

CMC_BASE_URL = "https://pro-api.coinmarketcap.com"
CMC_TIMEOUT = 30


def _get_mcap_map(symbols: List[str]) -> Dict[str, float]:
    """Return {SYMBOL: market_cap_usd} from CMC quotes/latest.

    Returns {} when no API key is configured or the call fails — the
    caller treats that as "no enrichment", never as an error.
    """
    if not CMC_API_KEY or not symbols:
        return {}
    # CMC accepts up to 120 symbols per call; keep batches small.
    symbols = sorted({s.upper() for s in symbols})[:100]
    try:
        resp = requests.get(
            f"{CMC_BASE_URL}/v2/cryptocurrency/quotes/latest",
            headers={"X-CMC_PRO_API_KEY": CMC_API_KEY},
            params={"symbol": ",".join(symbols), "convert": "USD"},
            timeout=CMC_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json().get("data", {})
        out = {}
        for symbol, entries in data.items():
            if not entries:
                continue
            quote = entries[0].get("quote", {}).get("USD", {})
            mcap = quote.get("market_cap")
            if mcap:
                out[symbol.upper()] = float(mcap)
        return out
    except Exception as e:
        log.warning(f"CoinMarketCap enrichment failed: {e}")
        return {}


def enrich_tokens_cmc(tokens: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Fill missing market_cap from CoinMarketCap (no-op without a key)."""
    missing = [t for t in tokens if not (t.get("market_cap") or 0)]
    if not missing:
        return tokens
    mcap_map = _get_mcap_map([t.get("symbol", "") for t in missing])
    if not mcap_map:
        return tokens
    for token in missing:
        mcap = mcap_map.get(token.get("symbol", "").upper())
        if mcap:
            token["market_cap"] = mcap
            token["enriched_by"] = "coinmarketcap"
    return tokens
