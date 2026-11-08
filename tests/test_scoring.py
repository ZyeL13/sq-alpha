"""Scoring upgrade — Fase 3 langkah 5a.

Offline: pure functions on sample tokens.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from processors.score import compute_scores, get_primary_score, total_score, score_token


def _token(chg=0.5, vol=100_000, trades=1000, age=100):
    return {
        "symbol": "XYZ",
        "price_change_percent": chg,
        "volume_24h": vol,
        "trade_count": trades,
        "age_hours": age,
    }


def test_total_score_uses_config_weights():
    scores = {"momentum": 1.0, "anomaly": 0.0, "wallet": 0.0,
              "liquidity": 0.0, "freshness": 0.0, "risk": 0.0}
    assert total_score(scores) == 0.25  # MOMENTUM_WEIGHT
    scores = {"momentum": 0.0, "anomaly": 1.0, "wallet": 0.0,
              "liquidity": 0.0, "freshness": 0.0, "risk": 0.0}
    assert total_score(scores) == 0.30  # ANOMALY_WEIGHT


def test_primary_score_losers_is_inverted():
    # -8% drop: momentum is low (0.3) but the LOSERS signal is strong.
    scores = compute_scores(_token(chg=-8, vol=20_000_000, trades=5000))
    assert get_primary_score("LOSERS", scores) == 1.0 - scores["momentum"]
    assert get_primary_score("LOSERS", scores) >= 0.6
    assert get_primary_score("GAINERS", compute_scores(_token(chg=8))) > 0.6


def test_score_gate_passes_strong_tokens():
    cases = [
        ("HOT", _token(chg=0.5, vol=500_000_000, trades=50000)),   # total ~0.63
        ("GAINERS", _token(chg=8, vol=20_000_000, trades=5000)),  # total ~0.43
        ("LOSERS", _token(chg=-8, vol=20_000_000, trades=5000)),  # primary 0.7
        ("ALPHA", _token(chg=2, vol=200_000, trades=200, age=12)),  # total ~0.38
        ("NEW", _token(chg=15, vol=5_000_000, trades=2000, age=3)),  # total ~0.53
    ]
    for category, token in cases:
        result = score_token(token, category)
        assert result["passes"], f"{category} should pass: {result}"


def test_score_gate_rejects_junk():
    # Flat, low volume, old: total ~0.30, no strong primary signal.
    result = score_token(_token(chg=0.1, vol=10_000, trades=10), "ALPHA")
    assert not result["passes"]
    assert result["total"] < 0.35
    assert result["primary"] < 0.60


def test_score_token_returns_all_fields():
    result = score_token(_token(), "HOT")
    assert set(result) == {"scores", "total", "primary", "passes"}
    assert 0.0 <= result["total"] <= 1.0
    assert set(result["scores"]) >= {"momentum", "anomaly", "wallet",
                                     "liquidity", "freshness", "risk"}
