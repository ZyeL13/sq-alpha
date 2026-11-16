#!/usr/bin/env python3
"""Dry-run: ONE JIT pool round on FIXED sample tokens (JIT step 8).

No network, no LLM calls, NOTHING posts to Binance. The generator is
a deterministic stub that writes plausible post texts from each
token's own numbers; klines are synthesized; the reaction deck, the
variant cursor, the post memory, and the scheduled queue all live in
tmp files under --out. The real pool path runs end to end:
collect (real classify + score gate) -> draft (real prepare_draft,
stubbed generation) -> mechanical scoring (real score_draft) ->
winner scheduling (real finalize + render + side effects).

Prints the scored drafts + the winner, and writes report.txt +
the winner's card (when the winner is an image post) to --out.

Usage:
  python scripts/dry_run_pool.py --out /tmp/pool-dry-run
  python scripts/dry_run_pool.py --out <dir> --pool-size 3
"""
import argparse
import json
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import prompts.reactions as reactions  # noqa: E402
import prompts.styles as styles  # noqa: E402
import schedulers.card_renderer as card_renderer  # noqa: E402
import schedulers.orchestrator as orch  # noqa: E402
import schedulers.sketchnote as sketchnote  # noqa: E402
import storage.memory_store as memory_store  # noqa: E402
from schedulers.snapshot import CardSnapshot  # noqa: E402
from storage.scheduled_post_queue import ScheduledPostQueue  # noqa: E402

# Real illustrations when they exist on this machine (the VM); an
# empty dir elsewhere renders the card without art, like production
# does when the files are missing.
REAL_ART = os.path.expanduser(
    "~/workspace/your_files/sq-alpha-card-redesign/illustrations")

# ------------------------------------------------------------------ data
# Five shapes: volume spike, range squeeze, relative weakness, thin
# tape, plain gainer (no card type -> short text). NOVA carries a
# catalyst + a memory record. MORPHO's opener repeats a seeded
# scheduled post, so the freshness penalty shows in the scores.

def _token(symbol, price, change, volume, high, low, ratio, btc=2.1,
           volume_rank=999, market_cap=0, **extra):
    token = {
        "symbol": symbol,
        "price": price,
        "price_change_percent": change,
        "volume_24h": volume,
        "high_24h": high,
        "low_24h": low,
        "volume_ratio_7d": ratio,
        "btc_change_24h": btc,
        "volume_rank": volume_rank,
        "market_cap": market_cap,
        "timestamp": 1794634800,  # fixed: deterministic card footer
    }
    token.update(extra)
    return token


TOKENS = [
    _token("NOVA", 1.29, 18.4, 3_200_000, 1.35, 1.08, 3.2,
           volume_rank=12, market_cap=90_000_000,
           news_catalyst="Nova Labs ships v2; volume follows the news.",
           news_article_keys=[{"link": "https://example.invalid/nova-v2",
                               "title": "Nova Labs ships v2",
                               "source": "dry-run"}]),
    _token("KITE", 1.015, 1.2, 8_000_000, 1.03, 1.00, 1.4,
           volume_rank=3, market_cap=40_000_000),
    _token("WREN", 0.42, -6.3, 12_000_000, 0.46, 0.40, 1.8,
           volume_rank=20, market_cap=120_000_000),
    _token("ORBT", 2.55, 0.8, 5_000_000, 2.60, 2.50, 0.3,
           volume_rank=8, market_cap=30_000_000),
    _token("MORPHO", 0.87, 4.2, 6_500_000, 0.91, 0.82, 1.1,
           volume_rank=40, market_cap=70_000_000),
]

# The stub generator writes one fixed text per symbol. Specificity
# varies deliberately: NOVA cites 4 unit-carrying numbers, WREN and
# MORPHO 3, KITE 2, ORBT 1 plus stray bare numbers ("3 days",
# "top 10") that the unit filter must NOT count. Every text is
# >100 chars with exactly one cashtag, first line.
TEXTS = {
    "NOVA": ("$NOVA ripped +18.4% to $1.29 as volume ran 3.2x the 7-day "
             "average while BTC added 2.1%. Does the tape stay loud?"),
    "KITE": ("$KITE squeezed +1.2% to $1.015 inside a 3% range all day, "
             "barely moving while the rest of the board chopped around."),
    "WREN": ("$WREN slid -6.3% to $0.42 while BTC added 2.1%, lagging "
             "the market by a wide margin on a heavy tape. What gives?"),
    "ORBT": ("$ORBT drifted +0.8% over 3 days of quiet trading, still a "
             "top 10 name by mentions but barely a pulse on the tape."),
    "MORPHO": ("$MORPHO climbed +4.2% to $0.87 as volume ran 1.1x the "
               "7-day average, a steady grind with no single catalyst."),
}

# The seeded scheduled post shares MORPHO's first 8 words, so
# MORPHO's freshness component scores 0.
SEED_POST = ("$MORPHO climbed +4.2% to $0.87 as volume ran wild yesterday "
             "on the same headline, before fading into the close.")


class _FakeQueue:
    def __init__(self, items):
        self.items = list(items)

    def get(self, timeout=5):
        if self.items:
            return ("binance", self.items.pop(0))
        return None


def _closes(token):
    """Deterministic 24-close ramp from low to price."""
    rng = random.Random(hash(token["symbol"]) & 0xFFFF)
    low, end = token["low_24h"], token["price"]
    span = end - low
    return [low + span * (i / 23) + rng.uniform(-span * 0.05, span * 0.05)
            for i in range(24)]


def _fake_snapshot(token):
    ratio = token.get("volume_ratio_7d") or 1.0
    return CardSnapshot(
        token=dict(token), closes=_closes(token),
        volume_7d_avg=token["volume_24h"] / ratio,
        btc_change=token.get("btc_change_24h"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="dry-run-pool")
    ap.add_argument("--pool-size", type=int, default=5)
    args = ap.parse_args()

    out = os.path.abspath(args.out)
    cards_dir = os.path.join(out, "cards")
    state_dir = os.path.join(out, "state")
    os.makedirs(cards_dir, exist_ok=True)
    os.makedirs(state_dir, exist_ok=True)
    art_dir = os.path.join(state_dir, "art")
    os.makedirs(art_dir, exist_ok=True)

    print("=" * 64)
    print("DRY RUN — one JIT pool round. No network, no LLM, no posting.")
    print("=" * 64)

    # ---- hermetic state: deck, cursor, memory, queue, cards, art ----
    reactions.REACTION_STATE_FILE = os.path.join(state_dir,
                                                 "reactions_used.json")
    reactions.VARIANT_STATE_FILE = os.path.join(state_dir,
                                                "reaction_variants.json")
    # The angle deck too: a draft with no reaction falls back to the
    # card-type angle path, which records into the deck file.
    styles.ANGLE_STATE_FILE = os.path.join(state_dir, "opening_angles.json")
    styles.reset_opening_deck(clear_file=True)
    memory_store.MEMORY_FILE = os.path.join(state_dir, "post_memory.json")
    sketchnote._ILLUSTRATIONS_DIR = (REAL_ART if os.path.isdir(REAL_ART)
                                     else art_dir)
    card_renderer.CARDS_DIR = cards_dir
    queue = ScheduledPostQueue(db_path=os.path.join(state_dir,
                                                    "scheduled.db"))
    queue.add_post(post=SEED_POST, category="GAINERS", symbol="MORPHO",
                   scheduled_time=time.time() + 3600)
    memory_store.record_memory(
        "NOVA", -2.1,
        "$NOVA slipped -2.1% on thin volume, nothing to chase.")

    # ---- recorders for the winner-only side effects ----
    scored = []       # (symbol, reaction, DraftScore)
    generated = []    # (symbol, reaction name or None, memory block or None)
    news_marked = []
    dedupe_marked = []
    formats = []

    real_score_draft = orch.score_draft

    def _recording_score(content, token, total, recent, snapshot=None):
        result = real_score_draft(content, token, total, recent, snapshot)
        scored.append((token["symbol"], result))
        return result

    def _fake_generate(token, category, scores, opening_angle=None,
                       closing_question=False, reaction=None, memory=None):
        generated.append((token["symbol"],
                          reaction[0] if reaction else None,
                          memory))
        return TEXTS[token["symbol"]]

    # ---- stub the seams: generation, klines, dedupe, news, counts ----
    orch.data_queue = _FakeQueue(TOKENS)
    orch.normalize_token = lambda raw, source=None: dict(raw)
    orch.generate_post = _fake_generate
    orch.generate_longform = lambda *a, **k: None
    orch.build_snapshot = _fake_snapshot
    orch.score_draft = _recording_score
    orch.can_post = lambda: True
    orch.get_post_delay = lambda: 4800
    orch.get_format_counts = lambda: {"image": 0, "longform": 0}
    orch.increment_format_count = lambda fmt: formats.append(fmt)
    orch.is_duplicate = lambda *a, **k: False
    orch.mark_posted = lambda s, c, h, m: dedupe_marked.append(s)
    orch.is_news_seen = lambda s: False
    orch.mark_news_used = lambda a, s: news_marked.append((a["title"], s))
    orch.DRAFT_POOL_SIZE = args.pool_size
    orch.SCHEDULE_BUFFER_MAX = 3

    scheduled = orch.run_pool_round(1, queue)

    # ---- report ----
    lines = []
    lines.append(f"pool size: {args.pool_size}  scheduled: {scheduled}")
    lines.append("")
    lines.append("DRAFTS (mechanical score 45 signal / 30 specificity / "
                 "25 freshness):")
    gen_by_symbol = {s: (r, m) for s, r, m in generated}
    for symbol, result in scored:
        reaction, memory = gen_by_symbol.get(symbol, (None, None))
        if result is None:
            lines.append(f"  ${symbol}  reaction={reaction}  REJECTED")
            continue
        lines.append(f"  ${symbol}  reaction={reaction}  "
                     f"total={result.total:.1f}  [{result.components_str()}]"
                     + ("  +memory" if memory else ""))
    for symbol, reaction, memory in generated:
        if symbol not in {s for s, _ in scored}:
            lines.append(f"  ${symbol}  reaction={reaction}  "
                         "(pool-1: scoring skipped)"
                         + ("  +memory" if memory else ""))
    lines.append("")
    rows = queue.get_recent_scheduled_posts(5)
    winner_text = rows[0] if rows else None
    winner_symbol = None
    if scheduled and winner_text and winner_text != SEED_POST:
        winner_symbol = winner_text.split()[0].lstrip("$")
        lines.append(f"WINNER: ${winner_symbol}")
        lines.append(f"  {winner_text}")
    else:
        lines.append("WINNER: none (round scheduled nothing)")
    lines.append("")
    lines.append(f"scheduled rows: {queue.get_post_count()} "
                 f"(1 seeded + {'1 winner' if scheduled else '0'})")
    lines.append(f"format slots consumed: {formats or 'none'}")
    lines.append(f"dedupe marked: {dedupe_marked or 'none'}")
    lines.append(f"news marked (winner only): "
                 f"{news_marked or 'none'}")
    for name, path in (("reaction deck", reactions.REACTION_STATE_FILE),
                       ("variant cursor", reactions.VARIANT_STATE_FILE),
                       ("post memory", memory_store.MEMORY_FILE)):
        try:
            with open(path) as f:
                lines.append(f"{name}: {json.dumps(json.load(f))}")
        except (OSError, ValueError):
            lines.append(f"{name}: (no file)")
    cards = sorted(os.listdir(cards_dir))
    lines.append(f"cards rendered: {cards or 'none'}")

    report = "\n".join(lines)
    print()
    print(report)
    with open(os.path.join(out, "report.txt"), "w") as f:
        f.write(report + "\n")
    print()
    print(f"report + state written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
