# collectors/klines.py — 1h klines from the Binance public API (no key).
#
# One call with limit=168 supplies BOTH the 24h sparkline (last 24
# closes) and the 7-day volume average (hourly quote volumes) — no
# history store needed. The volume field used is the kline's QUOTE
# asset volume (index 7), so the 7d average is in the same units as
# the 24h ticker's quoteVolume and the ratio volume_24h /
# volume_7d_avg is unit-consistent. (scripts/demo_v3.py's fetch uses
# base volume, index 5, which is fine for a chart but wrong for the
# ratio — do not copy that index here.)
#
# Failure contract: fetch_klines returns None on ANY failure
# (network, HTTP, malformed payload). Callers treat None as "no
# card data" and fall back to text-only — never a half-empty card.
import requests

import logging_config
from collectors.binance import _ssl_verify

logger = logging_config.get_logger("klines")

KLINES_URL = "https://data-api.binance.vision/api/v3/klines"
KLINES_LIMIT = 168  # 7 days of hourly candles
MIN_CANDLES = 24    # a full day of hourly closes for the sparkline

_VERIFY = _ssl_verify()

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}


def fetch_klines(symbol: str, limit: int = KLINES_LIMIT,
                 interval: str = "1h", timeout: int = 10):
    """Fetch hourly klines for one pair (e.g. "KITEUSDT").

    Returns a list of (close, quote_volume) tuples in API order
    (oldest first), or None on any failure. Rows that fail to parse
    are skipped; an empty result is None. The caller (summarize)
    enforces the minimum candle count.
    """
    try:
        resp = requests.get(
            KLINES_URL,
            params={"symbol": symbol, "interval": interval, "limit": limit},
            timeout=timeout,
            headers=_HEADERS,
            verify=_VERIFY,
        )
        resp.raise_for_status()
        rows = resp.json()
    except Exception as e:
        logger.warning(f"Klines fetch failed for {symbol}: {e}")
        return None
    klines = []
    try:
        for row in rows:
            try:
                klines.append((float(row[4]), float(row[7])))
            except (TypeError, ValueError, IndexError):
                continue
    except TypeError:
        return None
    return klines or None


def summarize_klines(klines):
    """Derive the card inputs from raw klines, or None.

    Needs >= 24 candles (a full day of hourly closes). Returns
    {"closes": last 24 closes, "volume_7d_avg": mean daily quote
    volume over the window}. The average divides by the days
    actually covered (candles / 24): for a full 168-candle window
    that is the 7-day daily average; for a shorter window (a young
    listing) it is the average over the days available — still
    unit-consistent with volume_24h. Zero/negative closes or a
    non-positive average mean the data is unusable: None.
    """
    if not klines or len(klines) < MIN_CANDLES:
        return None
    closes = [c for c, _ in klines[-MIN_CANDLES:]]
    if any(c <= 0 for c in closes):
        return None
    total_quote_volume = sum(v for _, v in klines)
    days = len(klines) / 24
    volume_7d_avg = total_quote_volume / days if days else 0
    if volume_7d_avg <= 0:
        return None
    return {"closes": closes, "volume_7d_avg": volume_7d_avg}
