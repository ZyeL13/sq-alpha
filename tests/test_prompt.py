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
