"""Smoke tests for sq-alpha — Fase 3 langkah 1.

Offline only: no network, no API keys, no LLM calls.
Run:  python -m pytest tests/ -q
"""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _token(**overrides):
    token = {
        "symbol": "XYZ",
        "full_symbol": "XYZUSDT",
        "price": 1.50,
        "price_change_percent": 0.5,
        "volume_24h": 100_000,
        "volume_rank": 50,
        "market_cap": 0,
        "trade_count": 1000,
        "age_hours": 100,
        "high_24h": 1.60,
        "low_24h": 1.40,
    }
    token.update(overrides)
    return token


def test_config_loads():
    import config

    assert config.DAILY_POST_LIMIT == 100
    assert config.DAILY_POST_TARGET == 70
    assert set(config.LLM_PROVIDERS) == {"blockrun", "groq", "deepseek", "nvidia_nim"}
    assert config.ALPHA_MAX_MCAP == 5_000_000


def test_classify_hot_gainers_losers():
    from processors.classify import classify

    assert classify(_token(volume_rank=10, price_change_percent=0.5)) == "HOT"
    assert classify(_token(volume_rank=50, price_change_percent=5.0)) == "GAINERS"
    assert classify(_token(volume_rank=50, price_change_percent=-5.0)) == "LOSERS"


@pytest.mark.xfail(reason="Fase 1 bug: market_cap=0 is treated as small cap; fixed in Fase 3 langkah 4", strict=True)
def test_classify_alpha_needs_real_market_cap():
    from processors.classify import classify

    # Small cap + decent volume -> ALPHA
    assert classify(_token(volume_rank=50, market_cap=4_000_000, volume_24h=100_000)) == "ALPHA"
    # No market cap data at all (0) must NOT be treated as a small cap.
    assert classify(_token(volume_rank=50, market_cap=0, volume_24h=100_000)) is None


def test_classify_skips_stablecoin_and_megacap():
    from processors.classify import classify

    assert classify(_token(price=1.00)) is None
    assert classify(_token(symbol="BTC", price_change_percent=5.0)) is None


def test_normalize_binance_token():
    from processors.normalize import normalize_token

    raw = _token()
    out = normalize_token(raw, source="binance")
    assert out["symbol"] == "XYZ"
    assert out["source"] == "binance"
    assert out["price"] == 1.50
    assert out["volume_rank"] == 50


def test_compute_scores_in_range():
    from processors.score import compute_scores, get_primary_score

    scores = compute_scores(_token(price_change_percent=5.0, volume_24h=10_000_000))
    assert set(scores) >= {"momentum", "anomaly", "wallet", "freshness", "liquidity", "risk"}
    assert all(0.0 <= v <= 1.0 for v in scores.values())
    assert 0.0 <= get_primary_score("GAINERS", scores) <= 1.0


def test_timing_delay_range():
    from schedulers.timing import get_post_delay, get_current_session

    assert get_current_session() in {"asia", "europe", "overlap", "us_late", "night"}
    assert 450 <= get_post_delay() <= 750


def test_dedupe_roundtrip(tmp_path):
    import processors.dedupe as dedupe

    dedupe_file = tmp_path / "dedup.json"
    monkey = pytest.MonkeyPatch()
    monkey.setattr(dedupe, "DEDUP_FILE", str(dedupe_file))
    try:
        mem = dedupe.TokenMemory()
        assert mem.is_duplicate("XYZ", "ALPHA") is False
        mem.mark_posted("XYZ", "ALPHA", hook="test hook")
        assert mem.is_duplicate("XYZ", "ALPHA") is True
        assert mem.is_duplicate("XYZ", "GAINERS") is True  # same symbol, cooldown
        assert mem.is_duplicate("ABC", "ALPHA") is False
    finally:
        monkey.undo()


def test_persistent_queue_put_get(tmp_path):
    from storage.persistent_queue import PersistentQueue

    q = PersistentQueue(db_path=str(tmp_path / "queue.db"))
    assert q.size() == 0
    q.put("binance", {"symbol": "XYZ"})
    assert q.size() == 1
    item = q.get(timeout=2)
    assert item == ("binance", {"symbol": "XYZ"})
    assert q.size() == 0


def test_scheduled_queue_add_due_remove(tmp_path):
    from storage.scheduled_post_queue import ScheduledPostQueue

    q = ScheduledPostQueue(db_path=str(tmp_path / "scheduled.db"))
    now = time.time()
    q.add_post(post="$XYZ test post", category="ALPHA", symbol="XYZ",
               scheduled_time=now - 1, hook="h", session="asia", provider="groq")
    q.add_post(post="$ABC future post", category="HOT", symbol="ABC",
               scheduled_time=now + 3600, hook="h", session="asia", provider="groq")
    due = q.get_due_posts(limit=5)
    assert len(due) == 1
    assert due[0][3] == "XYZ"
    q.remove_post(due[0][0])
    assert q.get_due_posts(limit=5) == []


def test_llm_cache_set_get(tmp_path, monkeypatch):
    import storage.cache as cache

    monkeypatch.setattr(cache, "CACHE_FILE", str(tmp_path / "llm_cache.json"))
    monkeypatch.setattr(cache, "_cache", {})
    response = "$XYZ volume is rising fast and price is holding near the highs today with strong momentum building."
    cache.set("prompt", "system", "model-x", 0.7, response)
    assert cache.get("prompt", "system", "model-x", 0.7) == response
    assert cache.get("other prompt", "system", "model-x", 0.7) is None


def test_quality_gate_rejects_reasoning_leak_and_accepts_valid():
    from generators.quality_gate import validate_post

    valid, _ = validate_post(
        "$XYZ volume is climbing while price holds near the highs, "
        "with buyers stepping in through the session and momentum building."
    )
    assert valid is True

    valid, reason = validate_post("Let me think about $XYZ and draft a post for you.")
    assert valid is False
    assert "Reasoning leak" in reason


def test_llm_providers_enabled_groq_first():
    """Fase 3 langkah 3: Groq (free) is primary, DeepSeek is fallback.

    Previously all providers were disabled and this list was empty.
    """
    from llm import _get_providers_by_priority

    assert _get_providers_by_priority() == ["groq", "deepseek"]
