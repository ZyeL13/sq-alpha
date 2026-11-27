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

    def path_facts(self) -> dict:
        """Code-derived price-path facts from the 24 hourly closes
        (article redesign §4.1): the 24h-ago price plus the session
        low/high and how many hours ago each occurred. `closes` is
        oldest-first, so closes[0] is ~24h ago and closes[-1] is the
        latest hour; hours_ago counts back from the latest close.
        Empty dict when there are no usable closes. These are NOT in
        to_dict() — they live here so the short-form snapshot JSON
        (and its prompt bytes) stay unchanged; build_research_pack
        merges them into the article pack's facts.
        """
        closes = [c for c in (self.closes or []) if c]
        if not closes:
            return {}
        n = len(closes)
        low_idx = min(range(n), key=lambda i: closes[i])
        high_idx = max(range(n), key=lambda i: closes[i])
        return {
            "price_24h_ago": closes[0],
            "session_low": closes[low_idx],
            "session_low_hours_ago": n - 1 - low_idx,
            "session_high": closes[high_idx],
            "session_high_hours_ago": n - 1 - high_idx,
        }

    def to_dict(self) -> dict:
        """Plain-dict view of the snapshot: the same numbers feed the
        prompt, the number validator, and the card — no second fetch,
        no drift. Fields whose value is None are omitted, so the
        prompt can say 'do not mention that comparison' for missing
        data (spec 2.4)."""
        d = {
            "symbol": self.token.get("symbol"),
            "price": self.token.get("price"),
            "change_24h": self.token.get("price_change_percent"),
            "volume_24h": self.token.get("volume_24h"),
            "high": self.token.get("high_24h"),
            "low": self.token.get("low_24h"),
            "volume_ratio": self.volume_ratio,
            "volume_7d_avg": self.volume_7d_avg,
            "range_position": self.range_position,
            "range_width_pct": self.range_width_pct,
            "btc_change": self.btc_change,
            "btc_relative": self.btc_relative,
            "closes": list(self.closes),
        }
        return {k: v for k, v in d.items() if v is not None}


def snapshot_dict_for_prompt(token: dict, snapshot: "CardSnapshot | None" = None) -> dict:
    """The prompt's SNAPSHOT JSON section: one dict for the prompt,
    the number validator, and the card. From the CardSnapshot when
    present, else from the token's own numbers. Omits None fields.
    The 24 closes are dropped: they are sparkline data, and a close
    cited in the post would fail number validation (the validator
    only knows the token's own numbers) — so the prompt never
    invites the model to cite one."""
    if snapshot is not None:
        d = snapshot.to_dict()
    else:
        d = {
            "symbol": token.get("symbol"),
            "price": token.get("price"),
            "change_24h": token.get("price_change_percent"),
            "volume_24h": token.get("volume_24h"),
            "high": token.get("high_24h"),
            "low": token.get("low_24h"),
            "volume_ratio": token.get("volume_ratio_7d"),
            "volume_7d_avg": token.get("volume_7d_avg"),
            "range_position": range_position_of(token),
            "range_width_pct": range_width_pct_of(token),
            "btc_change": token.get("btc_change_24h"),
        }
        chg = d.get("change_24h")
        btc = d.get("btc_change")
        if chg is not None and btc is not None:
            try:
                d["btc_relative"] = float(chg) - float(btc)
            except (TypeError, ValueError):
                pass
        d = {k: v for k, v in d.items() if v is not None}
    d.pop("closes", None)
    return d


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
