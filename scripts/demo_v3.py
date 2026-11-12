#!/usr/bin/env python
"""Dry-run SQ-Alpha V3: long-form prompt + local chart PNG + snapshot
card, and the payloads post_to_square() would send for each format.

Prints everything, uploads NOTHING, publishes NOTHING. Safe to run
anywhere; --live also calls generate_longform() (needs LLM keys or
the BlockRun proxy — run that on the VPS).

Chart data is REAL Binance public data (24h ticker + 1h klines for
BTCUSDT, no key). If the fetch fails, rendering is skipped with a
message — values are never fabricated for a chart.

Usage:
  python3 scripts/demo_v3.py               # prompts + renders (system python has matplotlib/PIL)
  python3 scripts/demo_v3.py --live        # also generate a long-form article via LLM
  python3 scripts/demo_v3.py --symbol ETHUSDT

Output: /tmp/sq-alpha-v3-demo/
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

from config import ARTICLE_MAX_CHARS
from generators.post_generator import build_longform_prompt, generate_longform
from generators.quality_gate import validate_longform
from processors.score import score_token
from prompts.styles import select_editorial_style

OUT_DIR = "/tmp/sq-alpha-v3-demo"

# V3 brand (Phase 2 owns visuals/brand.py; duplicated here only so
# the Phase 0 harness can render without it).
BG = "#12151A"        # dark charcoal / midnight
PANEL = "#1A1E24"
ACCENT = "#57C7C1"    # muted cyan / turquoise
TEXT = "#F2F3F5"      # white
MUTED = "#9AA3AD"     # soft grey
GREEN = "#3FA97C"
RED = "#C65B5B"


def fetch_btc_ticker(symbol: str) -> dict | None:
    """Real 24h ticker from Binance public API (no key)."""
    try:
        r = requests.get(
            "https://data-api.binance.vision/api/v3/ticker/24hr",
            params={"symbol": symbol}, timeout=10,
        )
        r.raise_for_status()
        d = r.json()
        price = float(d["lastPrice"])
        high = float(d["highPrice"])
        low = float(d["lowPrice"])
        return {
            "symbol": symbol.replace("USDT", ""),
            "price": price,
            "price_change_percent": float(d["priceChangePercent"]),
            "volume_24h": float(d["quoteVolume"]),
            "range_position": (price - low) / (high - low) if high > low else 0.5,
            "high_24h": high,
            "low_24h": low,
        }
    except Exception as e:
        print(f"  ⚠️ ticker fetch failed ({e}); rendering skipped")
        return None


def fetch_klines(symbol: str, limit: int = 24) -> list | None:
    """Real 1h klines from Binance public API (no key)."""
    try:
        r = requests.get(
            "https://data-api.binance.vision/api/v3/klines",
            params={"symbol": symbol, "interval": "1h", "limit": limit},
            timeout=10,
        )
        r.raise_for_status()
        return [(float(k[4]), float(k[5])) for k in r.json()]  # (close, volume)
    except Exception as e:
        print(f"  ⚠️ klines fetch failed ({e}); chart skipped")
        return None


def render_chart(token: dict, klines: list, path: str) -> str | None:
    """Price line + volume bars, dark V3 theme. Real data only."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("  ⚠️ matplotlib not available (system python has it; venv does not)")
        return None
    closes = [c for c, _ in klines]
    volumes = [v for _, v in klines]
    chg = token["price_change_percent"]
    color = GREEN if chg >= 0 else RED
    fig, (ax_price, ax_vol) = plt.subplots(
        2, 1, figsize=(12, 6.75), gridspec_kw={"height_ratios": [3, 1]},
    )
    fig.patch.set_facecolor(BG)
    for ax in (ax_price, ax_vol):
        ax.set_facecolor(PANEL)
        ax.tick_params(colors=MUTED)
        for spine in ax.spines.values():
            spine.set_color("#2A2F37")
    ax_price.plot(closes, color=color, linewidth=2)
    ax_price.fill_between(range(len(closes)), closes, min(closes), color=color, alpha=0.12)
    ax_price.set_title(
        f"{token['symbol']}  ·  24h {chg:+.1f}%  ·  ${token['price']:,.2f}",
        color=TEXT, fontsize=16, loc="left", pad=12,
    )
    ax_price.set_ylabel("Price (USDT)", color=MUTED)
    ax_vol.bar(range(len(volumes)), volumes, color=ACCENT, alpha=0.6)
    ax_vol.set_ylabel("Volume", color=MUTED)
    ax_vol.set_xlabel("Last 24 hours (1h candles)", color=MUTED)
    fig.text(0.01, 0.01, "SQ-ALPHA", color=MUTED, fontsize=9)
    fig.tight_layout()
    fig.savefig(path, facecolor=BG)
    plt.close(fig)
    return path


def render_snapshot(token: dict, path: str) -> str | None:
    """Branded market-snapshot card (PIL). Metrics are the real
    ticker values passed in — nothing invented."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("  ⚠️ Pillow not available (system python has it; venv does not)")
        return None
    W, H = 1200, 675
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    try:
        font_big = ImageFont.truetype("DejaVuSans-Bold.ttf", 72)
        font_med = ImageFont.truetype("DejaVuSans.ttf", 40)
        font_small = ImageFont.truetype("DejaVuSans.ttf", 28)
    except OSError:
        font_big = ImageFont.load_default()
        font_med = ImageFont.load_default()
        font_small = ImageFont.load_default()
    d.rectangle([0, 0, W, 10], fill=ACCENT)
    chg = token["price_change_percent"]
    chg_color = GREEN if chg >= 0 else RED
    d.text((60, 60), f"${token['symbol']}", fill=TEXT, font=font_big)
    d.text((60, 170), f"${token['price']:,.2f}", fill=TEXT, font=font_med)
    d.text((60, 230), f"24h {chg:+.1f}%", fill=chg_color, font=font_med)
    d.text((60, 310), f"24h volume ${token['volume_24h'] / 1_000_000:,.1f}M", fill=MUTED, font=font_med)
    d.text((60, 370), f"24h range position {token['range_position']:.2f}", fill=MUTED, font=font_med)
    d.text((60, 560), "SQ-ALPHA  ·  24h snapshot", fill=MUTED, font=font_small)
    img.save(path)
    return path


def print_payloads(title: str, body: str, chart_path: str | None, card_path: str | None) -> None:
    """Show exactly what post_to_square() would send per format.
    No HTTP is made here."""
    short_body = body[:900]
    print("\n--- PAYLOAD: short text (unchanged path) ---")
    print(json.dumps({"bodyTextOnly": short_body[:120] + "..."}, indent=2))
    print(f"  (full body {len(short_body)} chars, cap 900)")
    if chart_path:
        print("\n--- PAYLOAD: image post (would upload first) ---")
        print(json.dumps({
            "contentType": 1,
            "bodyTextOnly": short_body[:120] + "...",
            "imageList": ["<processedUrl from upload_image()>"],
        }, indent=2))
        print(f"  local file to upload: {chart_path}")
    print("\n--- PAYLOAD: long-form article ---")
    print(json.dumps({
        "contentType": 2,
        "title": title,
        "bodyTextOnly": body[:120] + "...",
        "cover": "<processedUrl from upload_image()> " if card_path else "(no cover)",
    }, indent=2))
    print(f"  article body {len(body)} chars (cap {ARTICLE_MAX_CHARS})")


def main() -> None:
    live = "--live" in sys.argv
    symbol = "BTCUSDT"
    if "--symbol" in sys.argv:
        symbol = sys.argv[sys.argv.index("--symbol") + 1].upper()
    os.makedirs(OUT_DIR, exist_ok=True)

    token = fetch_btc_ticker(symbol)
    if token is None:
        # Synthetic fallback for the prompt only (clearly fake symbol,
        # realistic shape — same pattern as demo_editorial_v2 CASES).
        # Rendering is skipped: no chart is ever built from fake data.
        token = {
            "symbol": "KITE", "price": 2.40, "price_change_percent": 4.2,
            "volume_24h": 8_500_000, "range_position": 0.55,
        }
        print("  (using synthetic KITE token for the prompt only)")

    scored = score_token(token, "HOT")
    style = select_editorial_style(token, scored["scores"])
    print(f"\nTOKEN {token['symbol']}: style={style} "
          f"score={scored['total']:.2f} passes={scored['passes']}")

    prompt = build_longform_prompt(token, "HOT", scored["scores"])
    print(f"\n--- LONG-FORM PROMPT ({len(prompt)} chars, first 1200) ---")
    print(prompt[:1200])
    print("  [... prompt truncated ...]")

    title = f"{token['symbol']}: 24h read"
    body = ""
    if live:
        result = generate_longform(token, "HOT", scored["scores"])
        if not result:
            print("\n  -> generate_longform returned nothing (see audit log)")
        else:
            title, body = result
            valid, checked = validate_longform(title, body, symbol=token["symbol"])
            print(f"\n--- GENERATED ARTICLE: gate={'PASS' if valid else 'REJECT: ' + checked} ---")
            print(f"TITLE: {title}")
            print("-" * 60)
            print(body[:2000])
            body = checked if valid else body
    else:
        print("\n  (prompts-only: pass --live to generate via LLM)")

    chart_path = card_path = None
    klines = fetch_klines(symbol) if token["symbol"] != "KITE" else None
    if klines:
        chart_path = render_chart(token, klines, f"{OUT_DIR}/chart-{symbol}.png")
        if chart_path:
            print(f"\n  chart rendered: {chart_path}")
    card_path = render_snapshot(token, f"{OUT_DIR}/snapshot-{token['symbol']}.png")
    if card_path:
        print(f"  snapshot card rendered: {card_path}")

    if body:
        print_payloads(title, body, chart_path, card_path)
    else:
        print("\n  (no article body — payloads need --live)")
    print(f"\nDone. Files in {OUT_DIR}/")


if __name__ == "__main__":
    main()
