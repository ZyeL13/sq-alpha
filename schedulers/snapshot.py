# schedulers/snapshot.py — one shared data snapshot per image post.
#
# prepare_post builds ONE snapshot (ticker + klines168 + BTC
# context) and both the text prompt and the card read from it, so
# the numbers on the card can never disagree with the post text.
# The snapshot is fetched once, only for image posts: short posts
# need no klines call, and long-form covers keep the plain renderer
# (their logic is untouched by the card redesign).
#
# A snapshot with a missing BTC change is still valid — it only
# disables the Relative Weakness rule, which needs BTC context.
# A snapshot is None only when the klines data itself is unusable,
# and then the post goes out as text-only (never a half-empty card).
from dataclasses import dataclass

from collectors.klines import fetch_klines, summarize_klines


def range_position_of(token: dict) -> float:
    """Position of price inside the 24h high/low range, 0..1.

    Same derivation as schedulers/card_renderer._range_position and
    prompts.styles._range_position (normalize_token drops the
    collector's range_position field, so the live pipeline cannot
    rely on it): derive from high/low/price, fall back to the
    token's range_position field, then to the midpoint.
    """
    high = token.get("high_24h") or 0
    low = token.get("low_24h") or 0
    price = token.get("price") or 0
    if high and low and high > low and price:
        return max(0.0, min(1.0, (price - low) / (high - low)))
    rp = token.get("range_position")
    if rp is not None:
        try:
            return max(0.0, min(1.0, float(rp)))
        except (TypeError, ValueError):
            pass
    return 0.5


def range_width_pct_of(token: dict):
    """24h range width as a % of price, or None without a real range."""
    high = token.get("high_24h") or 0
    low = token.get("low_24h") or 0
    price = token.get("price") or 0
    if high and low and high > low and price:
        return (high - low) / price * 100
    return None


@dataclass(frozen=True)
class CardSnapshot:
    """Ticker + klines168 + BTC context for one image post."""

    token: dict
    closes: list  # last 24 hourly closes (the sparkline)
    volume_7d_avg: float  # mean daily quote volume over the window
    btc_change: float | None  # BTC 24h change; None when unknown

    @property
    def volume_ratio(self):
        """24h volume vs the 7d daily average, or None."""
        vol = self.token.get("volume_24h") or 0
        if self.volume_7d_avg <= 0:
            return None
        return vol / self.volume_7d_avg

    @property
    def btc_relative(self):
        """Token 24h change minus BTC 24h change (points), or None."""
        if self.btc_change is None:
            return None
        chg = self.token.get("price_change_percent")
        if chg is None:
            return None
        try:
            return float(chg) - self.btc_change
        except (TypeError, ValueError):
            return None

    @property
    def range_position(self) -> float:
        return range_position_of(self.token)

    @property
    def range_width_pct(self):
        return range_width_pct_of(self.token)


def build_snapshot(token: dict, fetch=fetch_klines):
    """Fetch klines168 once and bundle the snapshot, or None.

    None means the klines fetch failed or the data is unusable
    (too few candles, bad closes) — the caller falls back to
    text-only. A missing/unusable BTC change does NOT fail the
    snapshot: btc_change is None and BTC-relative rules skip.
    """
    symbol = token.get("symbol", "")
    full_symbol = token.get("full_symbol") or f"{symbol}USDT"
    klines = fetch(full_symbol)
    if klines is None:
        return None
    summary = summarize_klines(klines)
    if summary is None:
        return None
    btc_change = token.get("btc_change_24h")
    if btc_change is not None:
        try:
            btc_change = float(btc_change)
        except (TypeError, ValueError):
            btc_change = None
    return CardSnapshot(
        token=dict(token),
        closes=summary["closes"],
        volume_7d_avg=summary["volume_7d_avg"],
        btc_change=btc_change,
    )
