# schedulers/sketchnote.py — sketchnote-style card renderer (Fase 3).
#
# Port of the Fase 2 mockup (mockup_sketchnote.py): cream ruled
# notebook paper, Kalam handwriting font, sketchy multi-pass
# strokes, wobbly stat boxes with curved arrows, a circled hero %,
# and the polaroid avatar top-right. Direction ink, not type
# colors: negative heroes are red pen, the card type is carried by
# the label text. This deliberately breaks the dark V3 identity for
# the CARDS only; post text style is unchanged.
#
# Data contract: render_sketchnote_image takes the dict built by
# build_card_data from a CardSnapshot — the same snapshot the post
# text was generated from. The renderer invents no numbers: the
# Read line is a fixed qualitative sentence per card type (it states
# what the trigger already guarantees), and the closing question is
# passed in from the post text — never written by the renderer. A
# question that cannot fit the card is omitted, never truncated.
#
# Fonts: Kalam first (Docker image fetches the TTFs into
# /usr/share/fonts/truetype/kalam; KALAM_FONT_DIR overrides the
# search for local runs), then DejaVu, then PIL's default font —
# never a crash on missing fonts.
#
# Avatar: the polaroid is best-effort. A decode/paste failure logs
# a warning and the card renders without it; the polaroid can never
# fail a render. Jitter is seeded from symbol + timestamp, so the
# same input renders identical bytes with per-card variation.
import math
import os
import random
import time
import zlib
from datetime import datetime, timezone

import logging_config

logger = logging_config.get_logger("sketchnote")

W, H = 1200, 675
PAPER = "#F7F3E8"
RULE = "#DDE3EC"
MARGIN = "#E8A0A0"
INK = "#2B2B2B"
BLUE = "#2B5CB8"
RED = "#C04545"
MUTED = "#7A8291"
PINK = "#E8A0A0"

CARD_LABELS = {
    "thin_tape": "Thin Tape",
    "volume_spike": "Volume Spike",
    "range_squeeze": "Range Squeeze",
    "relative_weakness": "Relative Weakness",
}

# Tests point these at tmp dirs to exercise the fallback paths.
_KALAM_DIRS = ["/usr/share/fonts/truetype/kalam", "/usr/local/share/fonts"]
_DEJAVU_DIRS = ["/usr/share/fonts/truetype/dejavu", "/usr/share/fonts"]
_KALAM_FILES = {"bold": "Kalam-Bold.ttf", "regular": "Kalam-Regular.ttf"}
_DEJAVU_FILES = {"bold": "DejaVuSans-Bold.ttf", "regular": "DejaVuSans.ttf"}


# ---------------- card data ----------------

def build_card_data(snapshot, card_type, question=None):
    """Build the render dict from a snapshot + card type.

    Raises ValueError for an unknown card type or missing data the
    type needs (Relative Weakness without BTC context). The caller
    (card_renderer) converts this to CardRenderError.
    """
    if card_type not in CARD_LABELS:
        raise ValueError(f"unknown card type: {card_type!r}")
    token = snapshot.token
    symbol = str(token.get("symbol") or "").strip()
    if not symbol:
        raise ValueError("no symbol in token data")
    try:
        change = float(token.get("price_change_percent"))
    except (TypeError, ValueError):
        raise ValueError(f"non-numeric change for ${symbol}")
    ratio = snapshot.volume_ratio
    if ratio is None:
        raise ValueError(f"no volume ratio for ${symbol}")
    stat1 = ("volume vs 7d avg", f"{ratio:.1f}×")
    if card_type == "relative_weakness":
        btc_rel = snapshot.btc_relative
        if btc_rel is None:
            raise ValueError("relative weakness card needs BTC context")
        stat2 = ("vs BTC, same 24h", f"{btc_rel:+.1f} pts")
    else:
        stat2 = ("position in 24h range", f"{snapshot.range_position:.2f}")

    if card_type == "volume_spike":
        read = "Volume leads, price follows."
    elif card_type == "range_squeeze":
        read = "Small range, price mid-way through it."
    elif card_type == "thin_tape":
        read = "Quiet tape, barely any volume."
    elif change < 0:
        read = "Weak against BTC, not just down."
    else:
        read = "Up, but lagging BTC by a wide margin."

    return {
        "label": CARD_LABELS[card_type],
        "symbol": f"${symbol}",
        "hero": f"{change:+.1f}%",
        "down": change < 0,
        "closes": list(snapshot.closes),
        "stat1": stat1,
        "stat2": stat2,
        "read": read,
        "question": question,
        "timestamp": token.get("timestamp"),
    }


# ---------------- fonts ----------------

def _sketch_font(bold: bool, size: int):
    """Kalam first, DejaVu second, PIL default last. Never raises."""
    from PIL import ImageFont

    fname = _KALAM_FILES["bold" if bold else "regular"]
    dirs = []
    env_dir = os.getenv("KALAM_FONT_DIR")
    if env_dir:
        dirs.append(env_dir)
    dirs.extend(_KALAM_DIRS)
    for directory in dirs:
        try:
            return ImageFont.truetype(os.path.join(directory, fname), size)
        except OSError:
            continue
    dfname = _DEJAVU_FILES["bold" if bold else "regular"]
    for directory in _DEJAVU_DIRS:
        try:
            return ImageFont.truetype(os.path.join(directory, dfname), size)
        except OSError:
            continue
    try:
        return ImageFont.truetype(dfname, size)
    except OSError:
        pass
    return ImageFont.load_default()


def _fit_font(draw, text, bold, size, max_width, min_size=20):
    """Shrink the font until the text fits max_width (long tickers,
    long questions). Returns the smallest tried font; the caller
    decides whether an over-wide result is omitted."""
    while size > min_size:
        font = _sketch_font(bold, size)
        if draw.textlength(text, font=font) <= max_width:
            return font
        size -= 2
    return _sketch_font(bold, min_size)


def _text_w(draw, text, font):
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0]


def _centered(draw, y, text, font, fill):
    draw.text(((W - _text_w(draw, text, font)) / 2, y), text, font=font,
              fill=fill)


def _fmt_tag_price(value: float) -> str:
    """Price for a LOW/HIGH tag: readable at every magnitude."""
    if value >= 1:
        return f"${value:.2f}"
    if value >= 0.001:
        return f"${value:.4f}"
    return f"${value:.7f}"


# ---------------- sketchy strokes ----------------

def _jitter_points(pts, rng, amt):
    return [(x + rng.uniform(-amt, amt), y + rng.uniform(-amt, amt))
            for x, y in pts]


def _sketchy_line(draw, pts, fill, width=3, rng=None, passes=2, amt=1.6):
    for _ in range(passes):
        draw.line(_jitter_points(pts, rng, amt), fill=fill, width=width,
                  joint="curve")


def _bezier(p0, p1, p2, n=32):
    return [((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t ** 2 * p2[0],
             (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t ** 2 * p2[1])
            for t in [i / (n - 1) for i in range(n)]]


def _curved_arrow(draw, p0, p1, p2, color, width=3, rng=None):
    pts = _bezier(p0, p1, p2)
    _sketchy_line(draw, pts, color, width=width, rng=rng)
    tip = pts[-1]
    ang = math.atan2(pts[-1][1] - pts[-4][1], pts[-1][0] - pts[-4][0])
    for da in (2.6, -2.6):
        a = ang + da
        draw.line([tip, (tip[0] + 14 * math.cos(a),
                         tip[1] + 14 * math.sin(a))],
                  fill=color, width=width)


def _rounded_points(rect, r=14, n=6):
    x0, y0, x1, y1 = rect
    pts = []
    for cx, cy, a0 in ((x1 - r, y0 + r, -90), (x1 - r, y1 - r, 0),
                       (x0 + r, y1 - r, 90), (x0 + r, y0 + r, 180)):
        for i in range(n + 1):
            a = math.radians(a0 + 90 * i / n)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def _wobbly_box(draw, rect, color, width=3, rng=None):
    pts = _rounded_points(rect)
    _sketchy_line(draw, pts + [pts[0]], color, width=width, rng=rng,
                  amt=1.4)


def _sketchy_ellipse(draw, bbox, color, width=3, rng=None, passes=2):
    x0, y0, x1, y1 = bbox
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    rx, ry = (x1 - x0) / 2, (y1 - y0) / 2
    pts = [(cx + rx * math.cos(math.radians(a)),
            cy + ry * math.sin(math.radians(a))) for a in range(0, 361, 6)]
    for _ in range(passes):
        draw.line(_jitter_points(pts, rng, 1.8), fill=color, width=width,
                  joint="curve")


def _doodle_bunny(draw, cx, cy, s, rng):
    """Tiny bunny face, sketchy strokes. s = head radius.

    Part of the fixed doodle library. The production card shows the
    polaroid avatar in this corner instead; the bunny stays available
    for future variants.
    """
    for dx, tilt in ((-0.45, -12), (0.45, 12)):
        ex, ey = cx + dx * s * 2, cy - s * 1.15
        _sketchy_ellipse(draw, (ex - 0.32 * s, ey - 0.85 * s,
                                ex + 0.32 * s, ey + 0.55 * s),
                         INK, width=3, rng=rng)
    _sketchy_ellipse(draw, (cx - s, cy - s * 0.85, cx + s, cy + s * 0.85),
                     INK, width=3, rng=rng)
    for dx in (-0.38, 0.38):
        draw.ellipse([cx + dx * s - 4, cy - 0.1 * s - 5, cx + dx * s + 4,
                      cy - 0.1 * s + 5], fill=INK)
    draw.arc([cx - 0.25 * s, cy + 0.15 * s, cx + 0.25 * s, cy + 0.55 * s],
             start=15, end=165, fill=INK, width=3)
    for dx in (-0.62, 0.62):
        draw.ellipse([cx + dx * s - 9, cy + 0.25 * s - 5, cx + dx * s + 9,
                      cy + 0.25 * s + 5], fill=PINK)


def _sparkle(draw, x, y, r, color, rng):
    _sketchy_line(draw, [(x - r, y), (x + r, y)], color, width=2, rng=rng,
                  passes=1, amt=0.8)
    _sketchy_line(draw, [(x, y - r), (x, y + r)], color, width=2, rng=rng,
                  passes=1, amt=0.8)
    draw.ellipse([x - 2.5, y - 2.5, x + 2.5, y + 2.5], fill=color)


# ---------------- polaroid avatar ----------------

# None = not attempted yet; False = decode failed; Image = loaded.
_avatar_cache = None


def _load_avatar():
    """Decode the embedded avatar once, cache it. None on any failure."""
    global _avatar_cache
    if _avatar_cache is not None:
        return _avatar_cache or None
    try:
        import base64
        import io

        from PIL import Image

        from schedulers.avatar_b64 import AVATAR_JPEG_B64

        img = Image.open(io.BytesIO(base64.b64decode(AVATAR_JPEG_B64)))
        img.load()
        _avatar_cache = img.convert("RGB")
    except Exception as e:
        logger.warning(f"avatar decode failed ({e}); no polaroid on cards")
        _avatar_cache = False
    return _avatar_cache or None


def _paste_polaroid(img):
    """Tilted photo + tape + faint shadow, top-right. Geometry from
    the approved mockup: 140px photo at (990, 118) — clear of the
    HIGH tag and the symbol underline."""
    from PIL import Image, ImageDraw

    avatar = _load_avatar()
    if avatar is None:
        return
    photo = avatar.resize((140, 140), Image.LANCZOS)
    pol = Image.new("RGBA", (160, 182), (255, 255, 255, 255))
    pol.paste(photo, (10, 10))
    tape = Image.new("RGBA", pol.size, (0, 0, 0, 0))
    td = ImageDraw.Draw(tape)
    td.rectangle([6, -6, 52, 14], fill=(232, 222, 180, 190))
    td.rectangle([108, -6, 154, 14], fill=(232, 222, 180, 190))
    pol = Image.alpha_composite(pol, tape)
    rot = pol.rotate(-5, expand=True, resample=Image.BICUBIC)
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    sh = Image.new("RGBA", rot.size, (0, 0, 0, 0))
    sh.paste((60, 50, 30, 70), (0, 0), rot.split()[3])
    shadow.paste(sh, (993, 121), sh)
    img.paste(Image.alpha_composite(img.convert("RGBA"), shadow)
              .convert("RGB"), (0, 0))
    img.paste(rot, (990, 118), rot)


# ---------------- card ----------------

def render_sketchnote_image(card_data, seed=None):
    """Render the sketchnote card. Returns a PIL Image (RGB).

    Raises ValueError on unusable card data. The polaroid is
    best-effort: any failure there logs a warning and the card
    renders without it.
    """
    from PIL import Image, ImageDraw

    closes = card_data["closes"]
    if len(closes) < 2:
        raise ValueError("sketchnote render needs at least 2 closes")
    if seed is None:
        seed = zlib.crc32(
            f"{card_data['symbol']}|{card_data.get('timestamp', '')}".encode())
    rng = random.Random(seed)

    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    # Ruled paper + margin line.
    for y in range(24, H, 46):
        d.line([(0, y), (W, y)], fill=RULE, width=1)
    d.line([(88, 0), (88, H)], fill=MARGIN, width=2)
    hero_color = RED if card_data["down"] else INK

    # Type tag, top-left: wobbly box.
    tag = card_data["label"].lower() + "!"
    tf = _sketch_font(True, 30)
    tw, th = _text_w(d, tag, tf), 30
    tag_rect = (48, 40, 48 + tw + 36, 40 + th + 22)
    _wobbly_box(d, tag_rect, BLUE, width=3, rng=rng)
    d.text((48 + 18, 40 + 8), tag, font=tf, fill=BLUE)
    # Symbol, top-right, with underline swoosh.
    sf = _fit_font(d, card_data["symbol"], True, 54, 420)
    sw = _text_w(d, card_data["symbol"], sf)
    d.text((W - 48 - sw, 38), card_data["symbol"], font=sf, fill=INK)
    _sketchy_line(d, _bezier((W - 48 - sw, 104), (W - 48 - sw / 2, 116),
                             (W - 48, 102)), BLUE, width=3, rng=rng)
    # Hero, circled.
    hf = _fit_font(d, card_data["hero"], True, 150, 900)
    hw = _text_w(d, card_data["hero"], hf)
    hx, hy = (W - hw) / 2, 118
    d.text((hx, hy), card_data["hero"], font=hf, fill=hero_color)
    _sketchy_ellipse(d, (hx - 34, hy + 6, hx + hw + 34, hy + 148), BLUE,
                     width=3, rng=rng)
    # Left sparkle sits above the HIGH-tag zone (tags start at y 296)
    # so a far-left HIGH tag never collides with it (dry-run 02-rust).
    _sparkle(d, 130, 245, 10, BLUE, rng)
    _sparkle(d, 1085, 330, 8, BLUE, rng)
    # Sparkline, sketchy blue ink. Band bottom 432 (not 440) leaves
    # a 12px gap between a bottom LOW tag and the stat boxes at 478
    # (dry-run 02-rust / 03-orbt crowded the box edge at 440).
    lo, hi = min(closes), max(closes)
    span = (hi - lo) or 1
    x0, x1, y0, y1 = 200, 1000, 330, 432
    pts = [(x0 + (x1 - x0) * i / (len(closes) - 1),
            y1 - (c - lo) / span * (y1 - y0)) for i, c in enumerate(closes)]
    _sketchy_line(d, pts, BLUE, width=3, rng=rng, passes=2, amt=1.2)
    # Stat boxes + curved arrows pointing at real line points.
    for cx, (k, v), li in ((300, card_data["stat1"], 6),
                           (900, card_data["stat2"], 17)):
        kf, vf = _sketch_font(False, 22), _sketch_font(True, 36)
        kw, vw = _text_w(d, k, kf), _text_w(d, v, vf)
        bw = max(kw, vw) + 44
        rect = (cx - bw / 2, 478, cx + bw / 2, 552)
        _wobbly_box(d, rect, INK, width=3, rng=rng)
        d.text((cx - kw / 2, 486), k, font=kf, fill=MUTED)
        d.text((cx - vw / 2, 510), v, font=vf, fill=INK)
        tip = pts[li]
        midx = (cx + tip[0]) / 2
        ctrl = (midx + (60 if cx < 600 else -60), (478 + tip[1]) / 2 - 6)
        _curved_arrow(d, (cx, 478), ctrl, tip, BLUE, width=3, rng=rng)
    # LOW/HIGH dots + handwritten tags, drawn AFTER the arrows so the
    # text stays readable when an arrow tip lands near a tag (dry-run
    # 03-orbt). HIGH tag above its dot (empty space: it is the line's
    # top), LOW tag below (empty: line's bottom).
    for idx, word, above in ((closes.index(lo), "low", False),
                             (closes.index(hi), "high", True)):
        x, y = pts[idx]
        d.ellipse([x - 6, y - 6, x + 6, y + 6], fill=BLUE, outline=PAPER,
                  width=2)
        tag2 = f"{word} {_fmt_tag_price(closes[idx])}"
        lf = _sketch_font(False, 24)
        lw = _text_w(d, tag2, lf)
        tx = min(max(x - lw / 2, 120), 1080 - lw)
        d.text((tx, y - 34 if above else y + 10), tag2, font=lf, fill=MUTED)
    # Read line + question + footer.
    label, sent = "Read: ", card_data["read"]
    lf2 = _fit_font(d, label + sent, True, 28, 1104)
    sf2 = _fit_font(d, label + sent, False, 28, 1104)
    total = _text_w(d, label, lf2) + _text_w(d, sent, sf2)
    tx = (W - total) / 2
    d.text((tx, 564), label, font=lf2, fill=BLUE)
    d.text((tx + _text_w(d, label, lf2), 564), sent, font=sf2, fill=INK)
    question = card_data.get("question")
    if question:
        qf = _fit_font(d, question, True, 30, 1104)
        if d.textlength(question, font=qf) <= 1104:
            _centered(d, 600, question, qf, INK)
        # Too wide even at the smallest size: omitted, never truncated.
    try:
        ts = float(card_data.get("timestamp") or time.time())
        foot = datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
            "%d %b %Y %H:%M UTC")
    except (TypeError, ValueError, OSError, OverflowError):
        foot = datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC")
    d.text((48, 644), "source: Binance public API",
           font=_sketch_font(False, 20), fill=MUTED)
    d.text((W - 48 - _text_w(d, foot, _sketch_font(False, 20)), 644), foot,
           font=_sketch_font(False, 20), fill=MUTED)
    try:
        _paste_polaroid(img)
    except Exception as e:
        logger.warning(f"polaroid paste failed ({e}); card without it")
    return img
