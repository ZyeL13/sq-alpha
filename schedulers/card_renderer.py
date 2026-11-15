# schedulers/card_renderer.py — V3 Phase 2 local data-card renderer.
#
# Renders a 1200x675 PNG "market snapshot" card from the SAME token
# data the post text uses (symbol, price, 24h change, 24h volume,
# range position). No generic crypto artwork, no invented numbers,
# no chart values beyond the ticker fields — the card restates the
# post's own data in the SQ-Alpha visual identity (spec section 3):
# dark charcoal/midnight background, muted cyan accent, white/soft
# grey type, restrained red/green for direction only.
#
# Placement: next to schedulers/square_media.py — this module makes
# the artifact that module uploads. It is deliberately not in
# generators/: generators/ is LLM content; this is deterministic
# publishing artwork with no model call.
#
# Failure contract: render_card() raises CardRenderError on ANY
# failure (missing Pillow, missing/invalid data, font or write
# error). The caller (processor) catches it and falls back to
# text-only — a bad render can never crash the pipeline. Pillow is
# imported lazily so this module imports cleanly even where Pillow
# is absent; the error then surfaces at render time, not at startup.
#
# Fonts: DejaVu Sans from fonts-dejavu-core (installed in the Docker
# image). No font file is vendored in the repo. If no usable font is
# found, rendering degrades to PIL's built-in default font instead
# of failing. Note: DejaVu has no CJK glyphs, so a non-Latin ticker
# renders with the font's fallback glyphs; the numbers (ASCII) are
# always correct.
#
# Cards land in cache/cards/ (a Docker volume, same as the queue
# DB). Each render prunes cards older than 48h: a card can only
# belong to a live queue row for ~90 minutes (stale-drop), so
# anything older is unreachable and safe to delete.
import os
import re
import time
from datetime import datetime

from config import CACHE_DIR, WIB

CARD_WIDTH = 1200
CARD_HEIGHT = 675
CARD_MAX_AGE_SECONDS = 48 * 3600

CARDS_DIR = os.path.join(CACHE_DIR, "cards")

# V3 brand palette (same values as scripts/demo_v3.py).
BG = "#12151A"        # dark charcoal / midnight
ACCENT = "#57C7C1"    # muted cyan / turquoise
TEXT = "#F2F3F5"      # white
MUTED = "#9AA3AD"     # soft grey
GREEN = "#3FA97C"
RED = "#C65B5B"
RULE = "#2A2F37"      # hairline / range-track grey

_MARGIN = 60
_RIGHT = CARD_WIDTH - _MARGIN

# Where DejaVu lives on Debian (fonts-dejavu-core). Tests point this
# at an empty/nonexistent directory to exercise the fallback path.
_FONT_DIRS = ["/usr/share/fonts/truetype/dejavu", "/usr/share/fonts"]
_FONT_FILES = {"bold": "DejaVuSans-Bold.ttf", "regular": "DejaVuSans.ttf"}


class CardRenderError(Exception):
    """Raised for any render failure. Callers fall back to text-only."""


def _fmt_price(price: float) -> str:
    """Same precision rules as generators.post_generator._fmt_price,
    so the card and the post text can never disagree about the price."""
    if price < 0.001:
        return f"${price:.7f}"
    if price < 1:
        return f"${price:.4f}"
    return f"${price:.2f}"


def _fmt_volume(volume: float) -> str:
    """Same shape as the data anchor: $2.8M, never a fabricated unit."""
    return f"${volume / 1_000_000:.1f}M"


def _range_position(token: dict) -> float:
    """Position of price inside the 24h high/low range, 0..1.

    Derived from the ticker's own high/low/price when available
    (normalize_token drops the collector's range_position field, so
    the live pipeline cannot rely on it); falls back to the token's
    range_position field, then to the midpoint.
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


def _load_font(bold: bool, size: int):
    """Best-effort DejaVu load; PIL's default font when none is found."""
    from PIL import ImageFont

    fname = _FONT_FILES["bold" if bold else "regular"]
    for directory in _FONT_DIRS:
        try:
            return ImageFont.truetype(os.path.join(directory, fname), size)
        except OSError:
            continue
    try:
        return ImageFont.truetype(fname, size)
    except OSError:
        pass
    return ImageFont.load_default()


def _fit_font(draw, text: str, bold: bool, size: int, max_width: int):
    """Shrink the font until the text fits max_width (long tickers)."""
    while size > 40:
        font = _load_font(bold, size)
        if draw.textlength(text, font=font) <= max_width:
            return font
        size -= 8
    return _load_font(bold, size)


def _prune_old_cards(out_dir: str, max_age_seconds: int = CARD_MAX_AGE_SECONDS) -> None:
    """Delete rendered cards older than max_age_seconds. Best effort:
    pruning must never break a render, so every failure is swallowed."""
    try:
        cutoff = time.time() - max_age_seconds
        names = os.listdir(out_dir)
    except OSError:
        return
    for name in names:
        if not name.lower().endswith(".png"):
            continue
        path = os.path.join(out_dir, name)
        try:
            if os.path.getmtime(path) < cutoff:
                os.remove(path)
        except OSError:
            continue


def _safe_filename(symbol: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9]+", "_", symbol).strip("_")
    return safe or "TOKEN"


def render_card(token: dict, output_dir: str | None = None) -> str:
    """Render the snapshot card for one token. Returns the PNG path.

    Raises CardRenderError on any failure. Rendering is a pure
    function of the token dict (the footer date comes from the
    token's own timestamp), so the same input renders identical
    bytes; only the filename carries wall-clock time.
    """
    symbol = str(token.get("symbol") or "").strip()
    if not symbol:
        raise CardRenderError("no symbol in token data")
    try:
        price = float(token.get("price"))
        change = float(token.get("price_change_percent"))
        volume = float(token.get("volume_24h"))
    except (TypeError, ValueError):
        raise CardRenderError(f"non-numeric market data for ${symbol}")
    if price <= 0:
        raise CardRenderError(f"no usable price for ${symbol}")

    try:
        from PIL import Image, ImageDraw
    except ImportError:
        raise CardRenderError("Pillow not available")

    out_dir = output_dir or CARDS_DIR
    try:
        os.makedirs(out_dir, exist_ok=True)
    except OSError as e:
        raise CardRenderError(f"cannot create cards dir: {e}")
    _prune_old_cards(out_dir)

    high = token.get("high_24h") or 0
    low = token.get("low_24h") or 0
    has_range = bool(high and low and high > low)
    range_pos = _range_position(token)
    chg_color = GREEN if change >= 0 else RED
    change_text = f"{change:+.1f}%"

    # Footer date from the token's own timestamp (deterministic);
    # wall clock only when the token carries no timestamp.
    ts = token.get("timestamp") or time.time()
    try:
        date_text = datetime.fromtimestamp(float(ts), tz=WIB).strftime("%d %b %Y").upper()
    except (TypeError, ValueError, OSError, OverflowError):
        date_text = datetime.now(WIB).strftime("%d %b %Y").upper()

    try:
        img = Image.new("RGB", (CARD_WIDTH, CARD_HEIGHT), BG)
        d = ImageDraw.Draw(img)

        # Top accent bar + header.
        d.rectangle([0, 0, CARD_WIDTH, 6], fill=ACCENT)
        font_brand = _load_font(True, 30)
        d.text((_MARGIN, 34), "SQ-ALPHA", fill=TEXT, font=font_brand)
        font_kicker = _load_font(False, 24)
        kicker = "24H SNAPSHOT"
        d.text((_RIGHT - d.textlength(kicker, font=font_kicker), 40),
               kicker, fill=MUTED, font=font_kicker)
        d.line([(_MARGIN, 96), (_RIGHT, 96)], fill=RULE, width=2)

        # Symbol, then price + change on one baseline.
        font_symbol = _fit_font(d, f"${symbol}", True, 96, _RIGHT - _MARGIN)
        d.text((_MARGIN, 122), f"${symbol}", fill=TEXT, font=font_symbol)
        font_price = _load_font(True, 60)
        price_text = _fmt_price(price)
        d.text((_MARGIN, 292), price_text, fill=TEXT, font=font_price)
        font_chg = _load_font(True, 52)
        chg_x = _MARGIN + d.textlength(price_text, font=font_price) + 28
        d.text((chg_x, 298), change_text, fill=chg_color, font=font_chg)

        # Volume metric.
        font_label = _load_font(False, 22)
        d.text((_MARGIN, 396), "24H VOLUME", fill=MUTED, font=font_label)
        font_value = _load_font(True, 36)
        d.text((_MARGIN, 424), _fmt_volume(volume), fill=TEXT, font=font_value)

        # Range bar (only when the ticker carries a real high/low).
        if has_range:
            bar_y = 520
            d.rectangle([_MARGIN, bar_y, _RIGHT, bar_y + 10], fill=RULE)
            marker_x = _MARGIN + range_pos * (_RIGHT - _MARGIN)
            d.ellipse([marker_x - 9, bar_y - 4, marker_x + 9, bar_y + 14],
                      fill=ACCENT, outline=TEXT, width=2)
            font_range = _load_font(False, 22)
            low_text = f"LOW {_fmt_price(low)}"
            high_text = f"HIGH {_fmt_price(high)}"
            d.text((_MARGIN, bar_y + 26), low_text, fill=MUTED, font=font_range)
            d.text((_RIGHT - d.textlength(high_text, font=font_range), bar_y + 26),
                   high_text, fill=MUTED, font=font_range)

        # Footer: data attribution + date.
        font_foot = _load_font(False, 20)
        d.text((_MARGIN, 622), "DATA: BINANCE 24H TICKER", fill=MUTED, font=font_foot)
        d.text((_RIGHT - d.textlength(date_text, font=font_foot), 622),
               date_text, fill=MUTED, font=font_foot)

        filename = f"{_safe_filename(symbol)}_{int(time.time() * 1000)}.png"
        path = os.path.join(out_dir, filename)
        img.save(path, format="PNG")
        return path
    except CardRenderError:
        raise
    except Exception as e:
        raise CardRenderError(f"render failed for ${symbol}: {e}")
