#!/usr/bin/env python
"""Dry-run Editorial v2: 4 synthetic tokens (one per style) + 1 skip case.

Prints the selected style and the generated post for each case. Never
posts, never touches post history, the queue, or the daily counter:
it calls build_prompt() + llm.generate() directly, not generate_post().

Needs: .env keys for the providers under test + the BlockRun proxy
running (on the VPS). Run it there, not in this VM (no keys here).

Usage:
  python scripts/demo_editorial_v2.py               # live generations
  python scripts/demo_editorial_v2.py --prompts-only  # prompts only, no LLM
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from generators.post_generator import build_prompt, news_price_context  # noqa: F401
from generators.quality_gate import validate_post
from llm import generate
from prompts.rebate import REBATE_SYSTEM
from prompts.styles import insufficient_insight, select_editorial_style
from processors.score import score_token

# Synthetic tokens — clearly fake symbols, realistic shapes. Each one
# is built to trip exactly one style gate (see test_editorial_v2.py).
CASES = [
    ("analytical", "GAINERS", {
        "symbol": "KITE", "price": 2.40, "price_change_percent": 4.2,
        "volume_24h": 8_500_000, "range_position": 0.55,
    }),
    ("contrarian", "GAINERS", {
        "symbol": "NOVA", "price": 95.50, "price_change_percent": 6.0,
        "volume_24h": 12_000_000, "range_position": 0.6,
        "news_catalyst": "NOVA launches mainnet",
        "price_at_news": 100.0, "volume_at_news": 11_000_000,
    }),
    ("data_observation", "HOT", {
        "symbol": "ORBIT", "price": 0.85, "price_change_percent": 0.4,
        "volume_24h": 150_000_000, "range_position": 0.5,
    }),
    ("dry_humor", "GAINERS", {
        "symbol": "MEME", "price": 0.0121, "price_change_percent": 21.0,
        "volume_24h": 6_000_000, "range_position": 0.5,
    }),
    ("skip", "HOT", {
        "symbol": "FLAT", "price": 1.10, "price_change_percent": 0.3,
        "volume_24h": 3_000_000, "range_position": 0.5,
    }),
]


def main() -> None:
    prompts_only = "--prompts-only" in sys.argv
    for expected, category, token in CASES:
        scored = score_token(token, category)
        style = select_editorial_style(token, scored["scores"])
        skip = insufficient_insight(token, scored["scores"])
        print(f"\n{'=' * 60}")
        print(f"CASE {token['symbol']}: expected={expected} "
              f"selected={style} skip={skip}")
        if skip:
            print(f"  -> skipped before any LLM call ({skip})")
            continue
        assert style == expected, f"{token['symbol']}: {style} != {expected}"
        prompt = build_prompt(token, category, scored["scores"])
        if prompts_only:
            print(prompt[:1200])
            print("  [... prompt truncated ...]")
            continue
        content = generate(
            prompt, system_prompt=REBATE_SYSTEM, category=category,
            use_cache=False,
        )
        if not content:
            print("  -> LLM returned nothing")
            continue
        valid, result = validate_post(content)
        print(f"  quality gate: {'PASS' if valid else 'REJECT: ' + str(result)}")
        print("-" * 60)
        print(result if valid else content)
        print("-" * 60)


if __name__ == "__main__":
    main()
