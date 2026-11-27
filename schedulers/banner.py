# schedulers/banner.py — article banners (spec §5.4–§5.6, PIL only).
#
# Five PIL templates (A–E, 1200x675) for long-form article covers.
# Numbers are formatted from the snapshot by code at draw time —
# never copied from LLM text. No image-model provider code, keys, or
# calls anywhere in this module (spec §5.8 stays unwired).
#
# Style selection is deterministic (select_banner_style, first match
# wins) with a variety guard over cache/banner_styles.json (last 3
# styles, lock + atomic write, same pattern as
# prompts/styles.py _read_used/_write_used). The history is written
# by render_article_banner on success; select_banner_style only
# reads it, so a selection never contradicts the render-time
# assertion that follows it. ARTICLE_BANNER_STYLE=A–E skips AUTO
# and the guard (tests/manual).
#
# Render-time assertions (§5.6/§6.7) raise BannerAssertionError (a
# CardRenderError): accent == stance color, style != last style
# (unless env override), headline fits at >= 54pt, style C has real
# closes. The caller (finalize_draft) publishes coverless on any
# CardRenderError — the article is never dropped for a banner
# problem.
import json
import os
import re
import threading
import time
from datetime import datetime

import logging_config
from config import ARTICLE_BANNER_STYLE, CACHE_DIR, WIB
from prompts.styles import derive_stance, verb_for_change
from schedulers.card_renderer import (
    BG,
    CARD_HEIGHT,
    CARD_WIDTH,
    MUTED,
    RULE,
    TEXT,
    CardRenderError,
    _fit_font,
    _fmt_price,
    _load_font,
    _prune_old_cards,
    _safe_filename,
)

logger = logging_config.get_logger("banner")

# Accent colors (spec §5.3). The stance color is the single accent
# on every style; gold/purple are secondary accents inside D/E only,
# never the stance color.
BANNER_RED = "#C65B5B"
BANNER_GREEN = "#3FA97C"
BANNER_CYAN = "#57C7C1"
BANNER_GOLD = "#C9A227"
BANNER_PURPLE = "#8B7BC7"

_BG_NEAR_BLACK = "#0B0D10"
_BG_NAVY_DEEP = (13, 22, 48)
_PANEL_FILL = "#171B21"

_MARGIN = 60
_RIGHT = CARD_WIDTH - _MARGIN
_STYLES = ("A", "B", "C", "D", "E")
# "Deck short" for the rule-4 single-metric conclusion (spec §5.5
# does not define "short"; 100 chars is one punchy sentence).
_DECK_SHORT_CHARS = 100
# AI/infra/upgrade/ecosystem keywords for the rule-3 style-D pick.
_AI_KEYWORDS = ("infra", "upgrade", "protocol", "ecosystem", "network",
                "launch")

# Style history: last 3 rendered styles. Tests point this at a tmp
# file; production uses the cache dir. No day-scoping — articles are
# max 1/day, so "consecutive" already means across days.
BANNER_STYLES_FILE = os.path.join(CACHE_DIR, "banner_styles.json")
CARDS_DIR = os.path.join(CACHE_DIR, "cards")

_history_lock = threading.RLock()

# Set on a successful render: {"style": style}. Same single-worker
# pattern as generators.post_generator.LAST_DRAFT_META — the
# orchestrator reads it at schedule time for card_type.
LAST_BANNER_STYLE: dict = {}


class BannerAssertionError(CardRenderError):
    """A banner assertion failed (§5.6/§6.7): the banner is dropped
    and the article publishes coverless (logged
    IMAGE_FALLBACK|banner_mismatch)."""


# ------------------------------------------------------------------ style
def _env_override() -> str:
    """ARTICLE_BANNER_STYLE, live env first, config value as fallback."""
    raw = os.environ.get("ARTICLE_BANNER_STYLE") or ARTICLE_BANNER_STYLE
    return (raw or "AUTO").strip().upper()


def _accent_for_stance(stance: str) -> str:
    """The single accent for a code-derived stance (spec §5.3)."""
    stance = (stance or "").strip().upper()
    if stance == "BEARISH":
        return BANNER_RED
    if stance == "BULLISH":
        return BANNER_GREEN
    return BANNER_CYAN


def _stance_color(stance: str) -> str:
    """Alias kept for the render-time assertion's readability."""
    return _accent_for_stance(stance)


def _fmt_volume_short(volume: float) -> str:
    """$500K / $512.5K under $1M; $X.XM at/above $1M (spec §5.3)."""
    if volume < 1_000_000:
        k = volume / 1000
        if k == int(k):
            return f"${int(k)}K"
        return f"${k:.1f}K"
    return f"${volume / 1_000_000:.1f}M"


def _num(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _read_banner_history() -> "list[str]":
    """Last rendered styles (max 3), from the state file. Empty on
    any failure. Same best-effort pattern as styles._read_used."""
    with _history_lock:
        try:
            if not os.path.exists(BANNER_STYLES_FILE):
                return []
            with open(BANNER_STYLES_FILE, "r") as f:
                data = json.load(f)
            styles = data.get("styles", data) if isinstance(data, dict) else data
            return [s for s in styles if s in _STYLES][-3:]
        except Exception:
            return []


def _record_banner_style(style: str) -> None:
    """Append a rendered style, keeping the last 3. Lock + atomic
    write (tmp file + os.replace); best-effort, never a crash."""
    with _history_lock:
        try:
            styles = _read_banner_history()
            styles.append(style)
            styles = styles[-3:]
            os.makedirs(os.path.dirname(BANNER_STYLES_FILE), exist_ok=True)
            tmp = BANNER_STYLES_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump({"styles": styles}, f)
            os.replace(tmp, BANNER_STYLES_FILE)
        except Exception:
            pass


def _mentions_ai_tech(text: str) -> bool:
    """Catalyst text mentions AI/infra/upgrade/ecosystem keywords."""
    low = (text or "").lower()
    if re.search(r"\bai\b", low):
        return True
    return any(k in low for k in _AI_KEYWORDS)


def _anomaly_estimate(facts: dict) -> float:
    """Mirror of styles._anomaly's token-data rule (vol < $1M and
    |chg| > 10 -> 0.8): the pack's angle already encodes the
    pipeline's own anomaly score when present; this covers packs
    built without one (e.g. the renderer's minimal pack)."""
    vol = _num(facts.get("volume_24h"), 0.0)
    chg = abs(_num(facts.get("change_24h"), 0.0))
    if vol and vol < 1_000_000 and chg > 10:
        return 0.8
    return 0.0


def _priority_candidates(pack: dict, article: dict) -> "list[str]":
    """AUTO candidates in priority order (spec §5.5), before the
    variety guard. Defensive: every field is .get with a default,
    so a minimal pack still selects."""
    facts = (pack or {}).get("facts") or {}
    chg = _num(facts.get("change_24h"), 0.0)
    stance = ((pack or {}).get("stance") or "").strip().upper()
    if not stance:
        stance = derive_stance(chg)
    category = str((pack or {}).get("category") or "").upper()
    angle = (pack or {}).get("angle")
    catalyst = (pack or {}).get("catalyst")
    catalyst_text = ""
    if isinstance(catalyst, dict):
        catalyst_text = str(catalyst.get("text") or "")
    elif isinstance(catalyst, str):
        catalyst_text = catalyst
    has_catalyst = bool(catalyst_text.strip())
    deck = str((article or {}).get("deck") or "")
    volume_ratio = facts.get("volume_ratio")
    closes = facts.get("closes")
    has_closes = isinstance(closes, list) and len(closes) >= 2

    candidates = []
    # 1. Major crash -> B (unless NEUTRAL, then A).
    if abs(chg) >= 30 or (category == "LOSERS" and abs(chg) >= 20):
        candidates.append("B" if stance != "NEUTRAL" else "A")
    # 2. Volume/technical anomaly -> C (needs real closes: no
    # closes, no chart, no C — spec §5.6).
    if has_closes and (
            angle == "volume event"
            or (angle == "anomaly" and volume_ratio is not None)
            or _anomaly_estimate(facts) >= 0.7):
        candidates.append("C")
    # 3. ALPHA + AI/infra catalyst -> D.
    if category == "ALPHA" and has_catalyst and _mentions_ai_tech(catalyst_text):
        candidates.append("D")
    # 4. Single dominant metric -> E.
    if deck and len(deck) <= _DECK_SHORT_CHARS and abs(chg) >= 10 \
            and not has_catalyst:
        candidates.append("E")
    # 5. Default -> A.
    candidates.append("A")
    return candidates


def select_banner_style(research_pack, article_json) -> str:
    """Pick the banner style for one article (spec §5.5).

    Deterministic priority, first match wins; the variety guard
    falls through to the next fitting style when AUTO picks the
    last rendered style. An explicit ARTICLE_BANNER_STYLE env
    override skips AUTO and the guard. This function only READS
    the history — render_article_banner records the style on
    success, so a selection never contradicts the render-time
    assertion that follows it.
    """
    override = _env_override()
    if override in _STYLES:
        return override
    candidates = _priority_candidates(research_pack or {},
                                      article_json or {})
    history = _read_banner_history()
    last_style = history[-1] if history else None
    for cand in candidates:
        if cand != last_style:
            return cand
    # Only the last style fits (the default A, nothing else): cycle
    # to the next style in rotation instead of repeating it, so no
    # two consecutive article covers share a style.
    order = list(_STYLES)
    return order[(order.index(last_style) + 1) % len(order)]


# ---------------------------------------------------------------- drawing
def _hex_to_rgb(hex_color: str) -> "tuple[int, int, int]":
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _wrap_text(draw, text: str, font, max_width: int) -> "list[str]":
    """Greedy word wrap; a single over-long word stays on its own
    line (the caller checks it fits and raises otherwise)."""
    lines = []
    for paragraph in (text or "").split("\n"):
        words = paragraph.split()
        if not words:
            continue
        current = words[0]
        for word in words[1:]:
            trial = f"{current} {word}"
            if draw.textlength(trial, font=font) <= max_width:
                current = trial
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines or [""]


def _fit_headline(draw, text: str, max_width: int, start_size: int):
    """Fit the headline in at most 2 lines at >= 54pt (spec §5.4).

    Shrinks from start_size to the 54pt floor; raises
    BannerAssertionError when it still does not fit — the headline
    is shortened in the editorial layer, never shrunk below 54pt.
    """
    size = start_size
    while size >= 54:
        font = _load_font(True, size)
        lines = _wrap_text(draw, text, font, max_width)
        if len(lines) <= 2 and all(
                draw.textlength(line, font=font) <= max_width
                for line in lines):
            return font, lines
        size -= 2
    raise BannerAssertionError(
        f"headline does not fit at 54pt in 2 lines: {text[:60]!r}")


def _fit_deck(draw, text: str, max_width: int) -> "list[str]":
    """Deck at 20pt, at most 2 lines (spec §6.7 composition
    invariant); more lines raise instead of shrinking."""
    if not text:
        return []
    font = _load_font(False, 20)
    lines = _wrap_text(draw, text, font, max_width)
    if len(lines) > 2:
        raise BannerAssertionError(
            f"deck needs {len(lines)} lines at 20pt (max 2)")
    return lines


def _draw_tracked(draw, xy, text: str, font, fill, tracking=2):
    """Draw text with manual letter spacing (small-caps labels)."""
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += draw.textlength(ch, font=font) + tracking
    return x


def _draw_stance_chip(draw, xy, stance: str, accent: str):
    """Stance chip: stance text in the stance color, stance-color
    outline. Returns its box (x0, y0, x1, y1)."""
    font = _load_font(True, 22)
    pad_x, pad_y = 16, 8
    w = draw.textlength(stance, font=font) + 2 * pad_x
    h = 40
    x, y = xy
    draw.rounded_rectangle([x, y, x + w, y + h], radius=8,
                           outline=accent, width=2)
    draw.text((x + pad_x, y + pad_y + 1), stance, font=font, fill=accent)
    return (x, y, x + w, y + h)


def _draw_brand_row(draw, date_text: str):
    """ZYEL / MARKET INTELLIGENCE + date, on every style."""
    font_brand = _load_font(True, 22)
    draw.text((_MARGIN, 34), "ZYEL / MARKET INTELLIGENCE",
              fill=TEXT, font=font_brand)
    font_date = _load_font(False, 20)
    draw.text((_RIGHT - draw.textlength(date_text, font=font_date), 36),
              date_text, fill=MUTED, font=font_date)
    draw.line([(_MARGIN, 96), (_RIGHT, 96)], fill=RULE, width=2)


def _draw_footer(draw, date_text: str):
    """MARKET SNAPSHOT / ZYEL RESEARCH footer, on every style."""
    font_foot = _load_font(False, 18)
    draw.text((_MARGIN, 622), "MARKET SNAPSHOT", fill=MUTED, font=font_foot)
    right = "ZYEL RESEARCH"
    draw.text((_RIGHT - draw.textlength(right, font=font_foot), 622),
              right, fill=MUTED, font=font_foot)


def _sparkline_points(closes, box):
    """Polyline points through the closes (oldest first) inside box."""
    x0, y0, x1, y1 = box
    lo, hi = min(closes), max(closes)
    n = len(closes)
    pts = []
    for i, c in enumerate(closes):
        x = x0 + (x1 - x0) * i / max(1, n - 1)
        y = y1 - (c - lo) / (hi - lo) * (y1 - y0) if hi > lo else (y0 + y1) / 2
        pts.append((x, y))
    return pts


def _check_layout(boxes: dict):
    """Composition invariants (§6.7): headline must not overlap the
    metric panel or the deck line; every box stays inside the
    canvas; the deck stays above the footer."""
    def overlaps(a, b):
        return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]

    headline = boxes.get("headline")
    panel = boxes.get("panel")
    if headline and panel and overlaps(headline, panel):
        raise BannerAssertionError("headline overlaps metric panel")
    deck = boxes.get("deck")
    if headline and deck and deck[1] < headline[3]:
        raise BannerAssertionError("deck overlaps headline")
    if deck and deck[3] > 622:
        raise BannerAssertionError("deck runs into the footer")
    for name, box in boxes.items():
        if box[0] < 0 or box[1] < 0 or box[2] > CARD_WIDTH or box[3] > CARD_HEIGHT:
            raise BannerAssertionError(f"{name} box outside the canvas")


def _style_a(draw, ctx):
    """Institutional Editorial: headline left, metric panel right,
    sparkline strip along the bottom when closes exist.

    The headline column is 760px: the fixture headline's longest
    greedy line at the 54pt floor is 715px, so a narrower column
    could never fit it (measured DejaVu Bold widths)."""
    font_head, lines = _fit_headline(draw, ctx["headline"], 760, 84)
    y = 130
    for line in lines:
        draw.text((_MARGIN, y), line, fill=TEXT, font=font_head)
        y += 100
    headline_box = (_MARGIN, 130, _MARGIN + 760, y - 100 + 84)
    # Right metric panel (300px; inner width 268 after padding).
    panel = (840, 120, _RIGHT, 470)
    draw.rounded_rectangle(panel, radius=10, fill=_PANEL_FILL,
                           outline=RULE, width=1)
    font_label = _load_font(False, 18)
    draw.text((856, 140), "PRICE", fill=MUTED, font=font_label)
    font_price = _fit_font(draw, ctx["price_text"], True, 48, 268)
    draw.text((856, 168), ctx["price_text"], fill=TEXT, font=font_price)
    font_chg = _fit_font(draw, ctx["change_text"], True, 40, 268)
    draw.text((856, 228), ctx["change_text"], fill=ctx["accent"],
              font=font_chg)
    if ctx["volume_text"]:
        draw.text((856, 296), "24H VOLUME", fill=MUTED, font=font_label)
        font_vol = _fit_font(draw, ctx["volume_text"], True, 36, 268)
        draw.text((856, 322), ctx["volume_text"], fill=TEXT, font=font_vol)
    chip_box = _draw_stance_chip(draw, (856, 400), ctx["stance"], ctx["accent"])
    boxes = {"headline": headline_box, "panel": panel, "chip": chip_box}
    # Deck under the headline.
    deck_lines = _fit_deck(draw, ctx["deck"], 760)
    if deck_lines:
        dy = 360
        for line in deck_lines:
            draw.text((_MARGIN, dy), line, fill=MUTED,
                      font=_load_font(False, 20))
            dy += 26
        boxes["deck"] = (_MARGIN, 360, _MARGIN + 760, dy - 26 + 20)
    # Sparkline strip (muted cyan here: in A the sentiment color
    # belongs only to the change figure + stance chip).
    if ctx["closes"]:
        font_path = _load_font(False, 18)
        draw.text((_MARGIN, 496), "24H PRICE PATH", fill=MUTED,
                  font=font_path)
        pts = _sparkline_points(ctx["closes"], (_MARGIN, 520, _RIGHT, 600))
        draw.line(pts, fill=BANNER_CYAN, width=2)
        boxes["sparkline"] = (_MARGIN, 520, _RIGHT, 600)
    return ctx["accent"], boxes


def _style_b(draw, ctx, base_img):
    """Dark Cinematic: near-black + soft stance-color glow behind a
    huge headline + oversized dim $SYM watermark; almost nothing
    else (price at the 48pt floor, one deck line)."""
    from PIL import Image, ImageDraw, ImageFilter

    accent_rgb = _hex_to_rgb(ctx["accent"])
    glow = Image.new("RGBA", (CARD_WIDTH, CARD_HEIGHT), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([80, 40, 1120, 560], fill=(*accent_rgb, 40))
    glow = glow.filter(ImageFilter.GaussianBlur(60))
    base_img.alpha_composite(glow)
    # Watermark: dim $SYM, right side.
    wm = Image.new("RGBA", (CARD_WIDTH, CARD_HEIGHT), (0, 0, 0, 0))
    wd = ImageDraw.Draw(wm)
    font_wm = _load_font(True, 200)
    wm_text = f"${ctx['symbol']}"
    wd.text((_RIGHT - wd.textlength(wm_text, font=font_wm), 190),
            wm_text, fill=(255, 255, 255, 14), font=font_wm)
    base_img.alpha_composite(wm)
    draw = ImageDraw.Draw(base_img)
    chip_box = _draw_stance_chip(draw, (_MARGIN, 120), ctx["stance"],
                                 ctx["accent"])
    font_head, lines = _fit_headline(draw, ctx["headline"], 1080, 110)
    y = 190
    for line in lines:
        draw.text((_MARGIN, y), line, fill=TEXT, font=font_head)
        y += 130
    headline_box = (_MARGIN, 190, _RIGHT, y - 130 + 110)
    font_price = _load_font(True, 48)
    draw.text((_MARGIN, 500), ctx["price_text"], fill=TEXT, font=font_price)
    px = _MARGIN + draw.textlength(ctx["price_text"], font=font_price) + 28
    font_chg = _load_font(True, 48)
    draw.text((px, 500), ctx["change_text"], fill=ctx["accent"],
              font=font_chg)
    boxes = {"chip": chip_box, "headline": headline_box,
             "price": (_MARGIN, 500, px + draw.textlength(
                 ctx["change_text"], font=font_chg), 548)}
    deck_lines = _fit_deck(draw, ctx["deck"], 1080)
    if deck_lines:
        dy = 566
        for line in deck_lines:
            draw.text((_MARGIN, dy), line, fill=MUTED,
                      font=_load_font(False, 20))
            dy += 26
        boxes["deck"] = (_MARGIN, 566, _RIGHT, dy - 26 + 20)
    return ctx["accent"], boxes, draw


def _style_c(draw, ctx):
    """Quant Terminal: headline top-left, 2x2 metric panels, sparkline
    across the lower third in the stance color."""
    font_head, lines = _fit_headline(draw, ctx["headline"], 1080, 64)
    y = 116
    for line in lines:
        draw.text((_MARGIN, y), line, fill=TEXT, font=font_head)
        y += 76
    headline_box = (_MARGIN, 116, _RIGHT, y - 76 + 64)
    boxes = {"headline": headline_box}
    deck_lines = _fit_deck(draw, ctx["deck"], 1080)
    if deck_lines:
        dy = 284
        for line in deck_lines:
            draw.text((_MARGIN, dy), line, fill=MUTED,
                      font=_load_font(False, 20))
            dy += 26
        boxes["deck"] = (_MARGIN, 284, _RIGHT, dy - 26 + 20)
    # 2x2 metric panels (a metric is omitted individually when None).
    panels = [
        ("PRICE", ctx["price_text"], TEXT),
        ("CHANGE 24H", ctx["change_text"], ctx["accent"]),
        ("VOL VS 7D AVG",
         f"{ctx['volume_ratio']:.1f}x" if ctx["volume_ratio"] is not None else None,
         TEXT),
        ("BTC-RELATIVE",
         f"{ctx['btc_relative']:+.1f} PTS" if ctx["btc_relative"] is not None else None,
         TEXT),
    ]
    grid = [(60, 350, 588, 414), (612, 350, 1140, 414),
            (60, 430, 588, 494), (612, 430, 1140, 494)]
    font_label = _load_font(False, 18)
    for (label, value, color), box in zip(panels, grid):
        if value is None:
            continue
        draw.rounded_rectangle(box, radius=8, outline=BANNER_CYAN, width=1)
        _draw_tracked(draw, (box[0] + 20, box[1] + 12), label,
                      font_label, MUTED)
        font_val = _fit_font(draw, value, True, 36, box[2] - box[0] - 40)
        draw.text((box[0] + 20, box[1] + 34), value, fill=color,
                  font=font_val)
    boxes["panels"] = (60, 350, 1140, 494)
    # Sparkline: ONLY from the snapshot's real closes (asserted by
    # the caller before drawing).
    pts = _sparkline_points(ctx["closes"], (_MARGIN, 520, _RIGHT, 600))
    draw.line(pts, fill=ctx["accent"], width=3)
    boxes["sparkline"] = (_MARGIN, 520, _RIGHT, 600)
    return ctx["accent"], boxes


def _style_d(draw, ctx, base_img):
    """Modern Tech Editorial: vertical 2-stop gradient + translucent
    geometric shapes; headline left, oversized; metric row bottom."""
    from PIL import Image, ImageDraw

    top, bottom = (18, 21, 26), _BG_NAVY_DEEP
    for row in range(CARD_HEIGHT):
        t = row / max(1, CARD_HEIGHT - 1)
        color = tuple(round(top[i] + (bottom[i] - top[i]) * t)
                      for i in range(3))
        draw.line([(0, row), (CARD_WIDTH, row)], fill=color)
    shapes = Image.new("RGBA", (CARD_WIDTH, CARD_HEIGHT), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shapes)
    sd.ellipse([800, -10, 1100, 290], fill=(*_hex_to_rgb(BANNER_CYAN), 25))
    sd.ellipse([940, 380, 1160, 600], fill=(*_hex_to_rgb(BANNER_PURPLE), 25))
    sd.rectangle([60, 580, 300, 612], fill=(*_hex_to_rgb(BANNER_GOLD), 25))
    base_img.alpha_composite(shapes)
    draw = ImageDraw.Draw(base_img)
    chip_box = _draw_stance_chip(draw, (_MARGIN, 104), ctx["stance"],
                                 ctx["accent"])
    font_head, lines = _fit_headline(draw, ctx["headline"], 1080, 100)
    y = 150
    for line in lines:
        draw.text((_MARGIN, y), line, fill=TEXT, font=font_head)
        y += 118
    headline_box = (_MARGIN, 150, _RIGHT, y - 118 + 100)
    # Metric row: price + change + volume on one baseline.
    font_price = _load_font(True, 48)
    draw.text((_MARGIN, 500), ctx["price_text"], fill=TEXT, font=font_price)
    px = _MARGIN + draw.textlength(ctx["price_text"], font=font_price) + 28
    font_chg = _load_font(True, 48)
    draw.text((px, 500), ctx["change_text"], fill=ctx["accent"],
              font=font_chg)
    mx = px + draw.textlength(ctx["change_text"], font=font_chg) + 40
    if ctx["volume_text"]:
        font_vol = _load_font(True, 36)
        draw.text((mx, 512), ctx["volume_text"], fill=TEXT, font=font_vol)
    boxes = {"chip": chip_box, "headline": headline_box,
             "metrics": (_MARGIN, 500, _RIGHT, 548)}
    deck_lines = _fit_deck(draw, ctx["deck"], 1080)
    if deck_lines:
        dy = 566
        for line in deck_lines:
            draw.text((_MARGIN, dy), line, fill=MUTED,
                      font=_load_font(False, 20))
            dy += 26
        boxes["deck"] = (_MARGIN, 566, _RIGHT, dy - 26 + 20)
    return ctx["accent"], boxes, draw


def _style_e(draw, ctx):
    """Minimalist Intelligence: one dominant headline, brand + stance
    chip only, optional deck line; everything else omitted."""
    chip_box = _draw_stance_chip(draw, (_MARGIN, 140), ctx["stance"],
                                 ctx["accent"])
    font_head, lines = _fit_headline(draw, ctx["headline"], 1080, 110)
    y = 210
    for line in lines:
        draw.text((_MARGIN, y), line, fill=TEXT, font=font_head)
        y += 130
    headline_box = (_MARGIN, 210, _RIGHT, y - 130 + 110)
    boxes = {"chip": chip_box, "headline": headline_box}
    deck_lines = _fit_deck(draw, ctx["deck"], 1080)
    if deck_lines:
        dy = 500
        for line in deck_lines:
            draw.text((_MARGIN, dy), line, fill=MUTED,
                      font=_load_font(False, 20))
            dy += 26
        boxes["deck"] = (_MARGIN, 500, _RIGHT, dy - 26 + 20)
    return ctx["accent"], boxes


def _minimal_pack(token, snapshot, stance):
    """The AUTO pack render_article_banner builds when no style was
    passed: snapshot facts (closes included — they live on the
    snapshot object, not in to_dict() of a token-only pack) +
    stance + catalyst presence. Angle/category are unknown here;
    finalize_draft passes the real pack via select_banner_style."""
    facts = snapshot.to_dict()
    catalyst = token.get("news_catalyst")
    return {
        "facts": facts,
        "stance": stance,
        "angle": None,
        "catalyst": {"text": catalyst} if catalyst else None,
        "missing": {"fillable": [], "unavailable": []},
    }


def render_article_banner(token, snapshot, stance, deck, headline,
                          style=None) -> str:
    """Render one article banner (1200x675 PNG). Returns the path.

    Numbers are formatted from the snapshot by code at draw time.
    `style` None -> AUTO via select_banner_style; an explicit style
    is used as-is (the env override still wins). Raises
    CardRenderError on any failure; BannerAssertionError (a
    CardRenderError) on assertion failures. On success sets
    LAST_BANNER_STYLE and records the style in the history file.
    """
    symbol = str(token.get("symbol") or "").strip()
    if not symbol:
        raise CardRenderError("no symbol in token data")
    if snapshot is None:
        raise CardRenderError(f"no snapshot for ${symbol} banner")
    try:
        price = float(token.get("price"))
        change = float(token.get("price_change_percent"))
        volume = token.get("volume_24h")
        volume = float(volume) if volume is not None else None
    except (TypeError, ValueError):
        raise CardRenderError(f"non-numeric market data for ${symbol}")
    if price <= 0:
        raise CardRenderError(f"no usable price for ${symbol}")

    stance = (stance or "").strip().upper()
    if stance not in ("BEARISH", "BULLISH", "NEUTRAL"):
        stance = derive_stance(change)
    headline = (headline or "").strip()
    if not headline:
        headline = f"{symbol} {verb_for_change(change)} {change:+.1f}%"
    deck = (deck or "").strip()

    # Style resolution: env override > explicit style > AUTO.
    override = _env_override()
    env_override = override in _STYLES
    if env_override:
        style = override
    elif style is None:
        style = select_banner_style(
            _minimal_pack(token, snapshot, stance),
            {"headline": headline, "deck": deck})
    else:
        style = str(style).strip().upper()
        if style not in _STYLES:
            raise CardRenderError(f"unknown banner style {style!r}")

    # Render-time assertions (§5.6/§6.7).
    history = _read_banner_history()
    if not env_override and history and style == history[-1]:
        raise BannerAssertionError(
            f"banner style {style} repeats the last style")
    closes = list(snapshot.closes or [])
    if style == "C" and len(closes) < 2:
        raise BannerAssertionError(
            "style C needs the snapshot's 24 closes; none present")
    accent = _accent_for_stance(stance)

    try:
        from PIL import Image, ImageDraw
    except ImportError:
        raise CardRenderError("Pillow not available")

    # Footer date from the token's own timestamp (deterministic);
    # wall clock only when the token carries no timestamp.
    ts = token.get("timestamp") or time.time()
    try:
        date_text = datetime.fromtimestamp(float(ts), tz=WIB).strftime(
            "%d %b %Y").upper()
    except (TypeError, ValueError, OSError, OverflowError):
        date_text = datetime.now(WIB).strftime("%d %b %Y").upper()

    bg = _BG_NEAR_BLACK if style == "B" else BG
    img = Image.new("RGB", (CARD_WIDTH, CARD_HEIGHT), bg)
    draw = ImageDraw.Draw(img)
    _draw_brand_row(draw, date_text)

    ctx = {
        "symbol": symbol,
        "stance": stance,
        "accent": accent,
        "headline": headline,
        "price_text": _fmt_price(price),
        "change_text": f"{change:+.1f}%",
        "volume_text": _fmt_volume_short(volume) if volume is not None else "",
        "volume_ratio": snapshot.volume_ratio,
        "btc_relative": snapshot.btc_relative,
        "closes": closes,
        "deck": deck,
    }

    if style == "A":
        used_accent, boxes = _style_a(draw, ctx)
    elif style == "B":
        # _style_b composites the glow/watermark onto this same
        # image object (in place) and returns a fresh draw for it.
        img = img.convert("RGBA")
        used_accent, boxes, draw = _style_b(draw, ctx, img)
    elif style == "C":
        used_accent, boxes = _style_c(draw, ctx)
    elif style == "D":
        img = img.convert("RGBA")
        used_accent, boxes, draw = _style_d(draw, ctx, img)
    else:  # E
        used_accent, boxes = _style_e(draw, ctx)

    # The accent actually drawn must be the stance color.
    if used_accent != _stance_color(stance):
        raise BannerAssertionError(
            f"banner accent {used_accent} != stance color "
            f"{_stance_color(stance)} for {stance}")
    _draw_footer(draw, date_text)
    boxes["footer"] = (_MARGIN, 622, _RIGHT, 642)
    _check_layout(boxes)

    out_dir = CARDS_DIR
    try:
        os.makedirs(out_dir, exist_ok=True)
    except OSError as e:
        raise CardRenderError(f"cannot create cards dir: {e}")
    _prune_old_cards(out_dir)
    filename = (f"{_safe_filename(symbol)}_banner_{style}_"
                f"{int(time.time() * 1000)}.png")
    path = os.path.join(out_dir, filename)
    try:
        img.convert("RGB").save(path, format="PNG")
    except Exception as e:
        raise CardRenderError(f"banner save failed for ${symbol}: {e}")
    LAST_BANNER_STYLE.clear()
    LAST_BANNER_STYLE.update({"style": style})
    _record_banner_style(style)
    logger.info(f"BANNER_RENDERED|{symbol}|{style}|{path}")
    return path
