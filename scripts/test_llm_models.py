"""Live model test — dry-run, never posts to Binance.

For every provider in the live rotation, generate 10 posts from sample
market data (the same build_prompt + system prompt the pipeline uses),
then print the results side by side: success rate, latency per request,
and whether the content came back filled (not empty/null).

Needs: .env keys for the providers under test + the BlockRun proxy
running on the host (port 8402) if BlockRun is in the rotation.

Run from the repo root:
    python scripts/test_llm_models.py

Exit code 0 when every provider produced at least one filled post.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import llm
from config import LLM_PROVIDERS
from generators.post_generator import build_prompt
from prompts.rebate import REBATE_SYSTEM

POSTS_PER_MODEL = 10

# Sample market data (example values, not live prices). Shape matches
# tests/test_prompt.py::_token — only the fields build_prompt reads.
SAMPLE_TOKENS = [
    ("BTC", "GAINERS", 97432.50, 2.4, 28_500_000_000, 0.72),
    ("ETH", "GAINERS", 3412.10, 3.1, 18_200_000_000, 0.68),
    ("SOL", "LOSERS", 214.55, -4.2, 3_100_000_000, 0.31),
    ("BNB", "HOT", 692.30, 1.1, 1_800_000_000, 0.55),
    ("XRP", "GAINERS", 2.41, 5.6, 4_200_000_000, 0.81),
    ("DOGE", "LOSERS", 0.3214, -3.8, 2_900_000_000, 0.22),
    ("LINK", "HOT", 22.84, 0.8, 890_000_000, 0.48),
    ("AVAX", "GAINERS", 38.12, 6.2, 640_000_000, 0.77),
    ("TRX", "HOT", 0.2811, -1.2, 720_000_000, 0.44),
    ("ADA", "HOT", 0.9123, 2.9, 1_100_000_000, 0.60),
]


def _sample_token(symbol, category, price, change, volume, range_pos):
    return {
        "symbol": symbol,
        "price": price,
        "price_change_percent": change,
        "volume_24h": volume,
        "range_position": range_pos,
    }, category


def test_provider(provider):
    """Generate POSTS_PER_MODEL posts via one provider. Returns a row dict."""
    model = LLM_PROVIDERS[provider]["model"]
    latencies = []
    filled = 0
    empty = 0
    errors = {}
    sample = ""
    for symbol, category, price, change, volume, range_pos in SAMPLE_TOKENS:
        token, cat = _sample_token(symbol, category, price, change, volume, range_pos)
        prompt = build_prompt(token, cat)
        start = time.perf_counter()
        content, error = llm._call_provider(
            provider, prompt, REBATE_SYSTEM, max_retries=1, backoff=0
        )
        latencies.append(time.perf_counter() - start)
        if content and len(content) >= 30:
            filled += 1
            if not sample:
                sample = content[:120].replace("\n", " ")
        else:
            empty += 1
            key = (error or "empty content")[:60]
            errors[key] = errors.get(key, 0) + 1
    return {
        "provider": provider,
        "model": model,
        "ok": filled,
        "total": POSTS_PER_MODEL,
        "empty": empty,
        "avg_s": sum(latencies) / len(latencies),
        "min_s": min(latencies),
        "max_s": max(latencies),
        "errors": errors,
        "sample": sample,
    }


def main():
    providers = llm._get_providers_by_priority()
    if not providers:
        print("No providers in the live rotation (all disabled or keyless).")
        print("Check .env keys and config.py LLM_PROVIDERS.")
        return 1
    print(f"Testing {len(providers)} provider(s), {POSTS_PER_MODEL} posts each (dry-run, no posting).")
    print(f"Rotation order: {', '.join(providers)}\n")
    rows = []
    for provider in providers:
        print(f"--- {provider} ({LLM_PROVIDERS[provider]['model']}) ---")
        rows.append(test_provider(provider))
        print()

    print("=" * 100)
    print(f"{'provider':<18}{'model':<32}{'ok':>6}{'empty':>7}{'avg s':>8}{'min s':>8}{'max s':>8}")
    print("-" * 100)
    all_ok = True
    for r in rows:
        if r["ok"] == 0:
            all_ok = False
        print(f"{r['provider']:<18}{r['model']:<32}{r['ok']}/{r['total']:<4}{r['empty']:>7}"
              f"{r['avg_s']:>8.1f}{r['min_s']:>8.1f}{r['max_s']:>8.1f}")
        for err, count in r["errors"].items():
            print(f"{'':<18}  x{count} {err}")
        if r["sample"]:
            print(f"{'':<18}  sample: {r['sample']}...")
    print("=" * 100)
    if all_ok:
        print("All providers produced at least one filled post.")
        return 0
    print("Some providers produced ZERO filled posts — see errors above.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
