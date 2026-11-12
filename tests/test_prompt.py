"""Prompt building — regression for the dropped news catalyst.

build_prompt() used to build `news_context` and never insert it into
the prompt, so the news catalyst the collector fetched never reached
the LLM. Fixed in Fase 3 langkah 5c.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from generators.post_generator import build_prompt


def _token(**overrides):
    token = {
        "symbol": "XYZ",
        "price": 1.50,
        "price_change_percent": 5.0,
        "volume_24h": 1_000_000,
        "range_position": 0.5,
    }
    token.update(overrides)
    return token


def test_news_catalyst_reaches_prompt():
    prompt = build_prompt(_token(news_catalyst="XYZ launches mainnet"), "GAINERS")
    assert "relevant news: XYZ launches mainnet" in prompt


def test_no_news_no_news_line():
    prompt = build_prompt(_token(), "HOT")
    assert "relevant news" not in prompt


def test_news_price_context_compares_snapshot_vs_now():
    from generators.post_generator import news_price_context

    token = _token(
        news_catalyst="XYZ launches mainnet",
        price=110.0,
        price_at_news=100.0,
        volume_24h=1_500_000,
        volume_at_news=1_000_000,
    )
    ctx = news_price_context(token)
    assert "price at news time $110.00" not in ctx  # then-price, not now-price
    assert "price at news time $100.00, now $110.00 (+10.0%)" in ctx
    assert "24h volume at news time $1.0M, now $1.5M (+50.0%)" in ctx
    prompt = build_prompt(token, "GAINERS")
    assert "news price context: price at news time $100.00" in prompt


def test_news_price_context_empty_without_snapshot():
    from generators.post_generator import news_price_context

    # Ada katalis tapi tidak ada snapshot -> tidak ada konteks (jangan ngarang).
    assert news_price_context(_token(news_catalyst="XYZ launches")) == ""
    # Ada snapshot tapi tidak ada katalis -> tidak ada konteks.
    assert news_price_context(_token(price_at_news=100.0, price=110.0)) == ""
    # Snapshot 0 -> tidak ada konteks, tidak crash (bagi nol).
    assert news_price_context(
        _token(news_catalyst="XYZ launches", price_at_news=0, price=110.0)
    ) == ""
