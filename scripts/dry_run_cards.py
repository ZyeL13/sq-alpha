#!/usr/bin/env python3
"""Dry-run: 10 post+card pairs from FIXED sample data (Fase 3 step 5).

No network, no LLM calls, NOTHING posts to Binance. Post texts are
hand-written samples; klines are synthesized deterministically.
Each scenario runs the real pipeline path — build_snapshot,
select_card_type, card_type_angle, extract_closing_question,
render_card — and writes the cards + pairs.txt to --out.

Scenarios cover all 4 card types (including a down-move Volume
Spike, an up-but-lagging Relative Weakness, and a priority
overlap), plus 2 text-only fallbacks (no matching type, klines
fetch failure).

Usage:
  python scripts/dry_run_cards.py --out /tmp/cards-dry-run
  python scripts/dry_run_cards.py --out <dir> --font-dir <kalam dir>
"""
import argparse
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import prompts.styles as styles
from generators.post_generator import extract_closing_question
from prompts.styles import card_type_angle, select_card_type
from schedulers.card_renderer import render_card
from schedulers.snapshot import build_snapshot


def _closes(start, end, seed, wobble=0.12):
    """Deterministic 24-close path from start to end."""
    rng = random.Random(seed)
    span = abs(end - start)
    out = []
    for i in range(24):
        t = i / 23
        base = start + (end - start) * t
        amp = span * wobble + start * 0.001
        out.append(round(base + rng.uniform(-amp, amp), 6))
    out[0] = start
    out[-1] = end
    return out


def _klines(closes24, volume_24h, ratio):
    """168 hourly candles: flat quote volume sized so the 7d daily
    average makes volume_24h / average == ratio exactly."""
    hourly = volume_24h / ratio / 24
    head = [(closes24[0], hourly)] * 144
    return head + [(c, hourly) for c in closes24]


def _token(symbol, price, change, volume, high, low, btc, **extra):
    token = {
        "symbol": symbol,
        "full_symbol": f"{symbol}USDT",
        "price": price,
        "price_change_percent": change,
        "volume_24h": volume,
        "high_24h": high,
        "low_24h": low,
        "btc_change_24h": btc,
        "timestamp": 1794634800,  # fixed: deterministic footer + seed
    }
    token.update(extra)
    return token


# Mockup-verbatim closes for the two proven shapes.
NOVA_CLOSES = [1.09, 1.10, 1.08, 1.11, 1.12, 1.14, 1.13, 1.16, 1.18,
               1.17, 1.20, 1.22, 1.21, 1.24, 1.26, 1.25, 1.28, 1.30,
               1.29, 1.32, 1.34, 1.33, 1.35, 1.29]
KITE_CLOSES = [3.20, 3.18, 3.21, 3.15, 3.12, 3.16, 3.10, 3.08, 3.11,
               3.05, 3.02, 3.06, 3.00, 2.98, 3.01, 2.95, 2.93, 2.97,
               2.91, 2.89, 2.92, 2.88, 2.86, 2.95]

SCENARIOS = [
    dict(
        symbol="NOVA", expected="volume_spike",
        token=_token("NOVA", 1.29, 18.4, 3_200_000, 1.35, 1.08, 2.1),
        closes=NOVA_CLOSES, ratio=3.2,
        post=("$NOVA traded 3.2x its 7-day average volume while price "
              "added 18.4%. Participation showed up before the move did, "
              "and the advance held through the session without giving "
              "much back. Volume leading price is the anomaly here, not "
              "the percentage itself. "
              "Does the tape stay this loud past the weekend?")),
    dict(
        symbol="RUST", expected="volume_spike",
        token=_token("RUST", 0.85, -12.6, 8_200_000, 0.99, 0.83, -9.0),
        closes=_closes(0.972, 0.85, seed=7), ratio=4.1,
        post=("$RUST fell 12.6% on 4.1x its usual volume while BTC "
              "dropped 9% alongside it. The selling was broad rather "
              "than token-specific, but the volume still stands out "
              "against a quiet week. Heavy tape on a red day says more "
              "about participation than direction. "
              "Is this distribution, or just the market moving together?")),
    dict(
        symbol="ORBT", expected="range_squeeze",
        token=_token("ORBT", 4.20, 1.2, 1_800_000, 4.244, 4.156, 1.0),
        closes=_closes(4.15, 4.20, seed=3, wobble=0.3), ratio=0.6,
        post=("$ORBT sits mid-range after a 2.1% wide session, up just "
              "1.2%. The range itself is the story: a full day of "
              "trading that went almost nowhere, on below-average "
              "volume. Nothing broke, nothing resolved. "
              "Does a range this tight resolve with a real move, or "
              "just more of the same?")),
    dict(
        symbol="MOTH", expected="thin_tape",
        token=_token("MOTH", 0.62, 0.8, 900_000, 0.65, 0.60, 0.5),
        closes=_closes(0.615, 0.62, seed=5), ratio=0.3,
        post=("$MOTH barely moved, up 0.8% on a third of its usual "
              "volume. No bounce attempt, no volume spike, no "
              "follow-through in either direction. The absence of "
              "activity is the observation — the market looked "
              "elsewhere all session. "
              "What would it take for anyone to notice this tape again?")),
    dict(
        symbol="KITE", expected="relative_weakness",
        token=_token("KITE", 2.95, -7.9, 3_300_000, 3.21, 2.86, 2.1),
        closes=KITE_CLOSES, ratio=1.1,
        post=("$KITE fell 7.9% while BTC gained 2.1% over the same 24 "
              "hours. Weak against BTC, not just down — the gap is 10 "
              "points, and volume stayed ordinary throughout. "
              "Token-specific softness reads differently from a "
              "market-wide dip. "
              "Is this a token-specific problem, or sector-wide drift?")),
    dict(
        symbol="PALE", expected="relative_weakness",
        token=_token("PALE", 5.15, 3.1, 2_700_000, 5.20, 4.95, 9.5),
        closes=_closes(4.995, 5.15, seed=9), ratio=0.9,
        post=("$PALE gained 3.1%, which would look fine on its own. "
              "Against BTC's 9.5% over the same day, it lagged by more "
              "than 6 points. Up but left behind is its own kind of "
              "weakness, and volume gave no sign of a catch-up bid. "
              "Why is the token trailing the market it usually follows?")),
    dict(
        symbol="VOLT", expected="volume_spike",  # spike beats squeeze
        token=_token("VOLT", 0.44, 2.0, 5_000_000, 0.4444, 0.4356, 1.0),
        closes=_closes(0.431, 0.44, seed=11, wobble=0.3), ratio=2.5,
        post=("$VOLT traded 2.5x its 7-day average volume inside a 2% "
              "range. Heavy participation, almost no price progress — "
              "the tape worked hard to stay in place. Volume this "
              "elevated with price going nowhere is the anomaly, not "
              "the range itself. "
              "Which side breaks first when the range finally gives?")),
    dict(
        symbol="WREN", expected="thin_tape",
        token=_token("WREN", 1.10, -1.5, 1_200_000, 1.15, 1.05, 0.2,
                     news_catalyst="WREN team posts a routine dev update."),
        closes=_closes(1.117, 1.10, seed=13), ratio=0.4,
        post=("$WREN drifted 1.5% lower on thin volume despite a "
              "routine dev update from the team. No reaction, no "
              "bounce, no volume response to the news at all. A "
              "catalyst that moves nothing is still information about "
              "how the market reads this token. "
              "Does anyone still trade the news here, or just the chart?")),
    dict(
        symbol="ORD", expected=None,  # ordinary tape: text-only
        token=_token("ORD", 3.00, 2.0, 3_000_000, 3.18, 2.82, 1.0),
        closes=_closes(2.94, 3.00, seed=15), ratio=1.0,
        post=("$ORD added 2.0% on ordinary volume, mid-range, nothing "
              "unusual in the tape. Sessions like this one are the "
              "market's default state: no anomaly, no story, just "
              "trading. Not every day needs a read attached to it.")),
    dict(
        symbol="FAIL", expected="klines_failed",  # fetch fails: text-only
        token=_token("FAIL", 0.77, 15.0, 6_000_000, 0.80, 0.66, 1.0),
        closes=None, ratio=None,
        post=("$FAIL jumped 15% on heavy volume, but the chart data "
              "failed to load for this one. The move is real; the card "
              "is not available, so this goes out as text only. Better "
              "a plain post than a card with missing pieces.")),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="/tmp/sq-alpha-card-dry-run")
    parser.add_argument("--font-dir", default=None,
                        help="Kalam font dir (else $KALAM_FONT_DIR)")
    args = parser.parse_args()
    if args.font_dir:
        os.environ["KALAM_FONT_DIR"] = args.font_dir
    os.makedirs(args.out, exist_ok=True)

    # Hermetic angle state: the dry-run never touches the real deck.
    styles.ANGLE_STATE_FILE = os.path.join(args.out, "angles.json")
    styles.reset_opening_deck()

    pairs = []
    rendered = 0
    for i, sc in enumerate(SCENARIOS, start=1):
        token = sc["token"]
        if sc["closes"] is None:
            snapshot = build_snapshot(token, fetch=lambda s: None)
        else:
            klines = _klines(sc["closes"], token["volume_24h"], sc["ratio"])
            snapshot = build_snapshot(token, fetch=lambda s: klines)
        label = f"{i:02d} ${sc['symbol']}"
        if snapshot is None:
            assert sc["expected"] == "klines_failed", sc["symbol"]
            pairs.append(f"{label} — TEXT ONLY (klines fetch failed)\n"
                         f"{sc['post']}\n")
            print(f"{label}: text-only (klines failed)")
            continue
        card_type = select_card_type(
            change=token.get("price_change_percent", 0) or 0,
            volume_ratio=snapshot.volume_ratio,
            range_width_pct=snapshot.range_width_pct,
            range_position=snapshot.range_position,
            btc_relative=snapshot.btc_relative)
        assert card_type == sc["expected"], \
            f"{sc['symbol']}: got {card_type}, expected {sc['expected']}"
        if card_type is None:
            pairs.append(f"{label} — TEXT ONLY (no card type matched)\n"
                         f"{sc['post']}\n")
            print(f"{label}: text-only (no card type)")
            continue
        angle_name, _ = card_type_angle(card_type)
        question = extract_closing_question(sc["post"])
        raw_path = render_card(token, output_dir=args.out, snapshot=snapshot,
                               card_type=card_type, question=question,
                               style="sketchnote")
        card_name = f"{i:02d}-{sc['symbol'].lower()}.png"
        os.replace(raw_path, os.path.join(args.out, card_name))
        rendered += 1
        pairs.append(f"{label} — {card_type} — angle={angle_name} "
                     f"— card={card_name}\n"
                     f"Q: {question}\n{sc['post']}\n")
        print(f"{label}: {card_type} angle={angle_name} -> {card_name}")

    with open(os.path.join(args.out, "pairs.txt"), "w") as f:
        f.write("\n".join(pairs))
    print(f"\n{rendered} cards + {len(SCENARIOS) - rendered} text-only "
          f"in {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
