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


# ------------------------------------------------- step 1: JSON prompt
def test_build_prompt_contains_json_schema_and_drawn_angle():
    prompt = build_prompt(
        _token(), "GAINERS", reaction=("smug", "SMUG TEXT"),
        snapshot_dict={"symbol": "XYZ", "price": 1.5, "change_24h": 5.0})
    assert '"event"' in prompt and '"post"' in prompt
    assert '"angle": "smug"' in prompt
    assert '"change_24h": 5.0' in prompt  # snapshot JSON
    assert "GOOD EXAMPLES" in prompt
    assert "BAD EXAMPLES" in prompt
    assert "<post>" not in prompt  # no tag instruction anywhere


def test_build_prompt_avoid_list_uses_first_lines():
    openers = ["$AAA first line here\nsecond line", "$BBB another opener\nmore"]
    prompt = build_prompt(_token(), "GAINERS", avoid_openers=openers)
    assert "AVOID THESE OPENERS" in prompt
    assert "$AAA first line here" in prompt
    assert "second line" not in prompt


def test_build_prompt_missing_btc_says_do_not_mention():
    prompt = build_prompt(_token(), "GAINERS",
                          snapshot_dict={"symbol": "XYZ", "price": 1.5})
    assert "do not mention" in prompt.lower()


def test_system_core_is_short_and_tag_free():
    from prompts.rebate import REBATE_SYSTEM_CORE

    assert "<post>" not in REBATE_SYSTEM_CORE
    assert len(REBATE_SYSTEM_CORE.split()) <= 150


# ------------------------------------------------- step 1: generate_post (JSON + retry)
# Three distinct wordings: generate_post records every success in the
# shared in-memory recent-posts list, so each test needs its own text
# or the similarity check skips the second one.
_POST_A = ("$XYZ climbed +5.0% to $1.50 on $1.0M of volume, a steady "
           "grind higher with no single catalyst in sight and buyers "
           "still showing up near the highs.")
_POST_B = ("$XYZ pushed +5.0% to $1.50 as $1.0M of volume crossed the "
           "tape, buyers still active into the close with no sign of "
           "the move fading yet.")
_POST_C = ("$XYZ held +5.0% to $1.50 while $1.0M of volume went through, "
           "the tape staying firm after the move with sellers nowhere "
           "near the offer.")


def _reply(post=_POST_A, angle="smug"):
    import json

    return json.dumps({
        "event": "XYZ climbed",
        "fact": "+5.0% to $1.50 on $1.0M volume",
        "interpretation": "buyers are showing up steadily",
        "angle": angle,
        "post": post,
    })


def _stub_generate(monkeypatch, replies):
    import generators.post_generator as pg

    calls = []

    def fake(prompt, system_prompt=None, category=None, **kwargs):
        calls.append(prompt)
        assert kwargs.get("output_format") == "json"
        assert kwargs.get("max_tokens") == 1200
        return replies.pop(0) if replies else None

    monkeypatch.setattr(pg, "generate", fake)
    return calls


def test_generate_post_returns_dict_on_valid_json(monkeypatch):
    from generators.post_generator import generate_post

    _stub_generate(monkeypatch, [_reply(post=_POST_A)])
    result = generate_post(_token(), "GAINERS", {},
                           reaction=("smug", "SMUG TEXT"))
    assert result is not None
    assert result["post"] == _POST_A
    assert result["angle"] == "smug"
    assert result["event"] == "XYZ climbed"


def test_generate_post_retries_once_on_invalid_json(monkeypatch):
    from generators.post_generator import generate_post

    calls = _stub_generate(monkeypatch, ["not json at all", _reply(post=_POST_B)])
    result = generate_post(_token(), "GAINERS", {},
                           reaction=("smug", "SMUG TEXT"))
    assert result is not None
    assert result["post"] == _POST_B
    assert len(calls) == 2
    assert "failed validation: json_invalid" in calls[1]


def test_generate_post_skips_after_second_failure(monkeypatch):
    from generators.post_generator import generate_post

    calls = _stub_generate(monkeypatch, ["nope", "still nope"])
    assert generate_post(_token(), "GAINERS", {},
                         reaction=("smug", "SMUG TEXT")) is None
    assert len(calls) == 2  # one retry, then skip — never more


def test_generate_post_retries_on_angle_mismatch_then_skips(monkeypatch):
    from generators.post_generator import generate_post

    calls = _stub_generate(monkeypatch,
                           [_reply(angle="question"), _reply(angle="question")])
    assert generate_post(_token(), "GAINERS", {},
                         reaction=("smug", "SMUG TEXT")) is None
    assert len(calls) == 2
    assert "angle_mismatch" in calls[1]


def test_generate_post_retries_on_unmatched_number(monkeypatch):
    from generators.post_generator import generate_post

    bad_post = _POST_C.replace("+5.0%", "+9.9%")
    calls = _stub_generate(monkeypatch, [_reply(post=bad_post), _reply(post=_POST_C)])
    result = generate_post(_token(), "GAINERS", {},
                           reaction=("smug", "SMUG TEXT"))
    assert result is not None
    assert result["post"] == _POST_C
    assert "number_not_in_snapshot" in calls[1]
