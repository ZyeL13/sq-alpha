"""Poster loud refusal (spec §6.6c): a long-form body over
ARTICLE_MAX_CHARS is never silently truncated — clean_for_square
raises ArticleTooLongError and post_to_targets refuses to publish
(ARTICLE_TRUNCATED logged, False returned, nothing posted anywhere).
Short-form truncation at 900 chars is unchanged. No network: the
Square HTTP call and the Telegram call are stubbed.
"""
import logging

import pytest

import config
import schedulers.poster as poster
from schedulers.poster import ArticleTooLongError, clean_for_square


def test_clean_longform_over_cap_raises_with_length():
    over = "x" * (config.ARTICLE_MAX_CHARS + 250)
    with pytest.raises(ArticleTooLongError) as excinfo:
        clean_for_square(over, format="longform")
    assert excinfo.value.length == config.ARTICLE_MAX_CHARS + 250
    assert str(config.ARTICLE_MAX_CHARS + 250) in str(excinfo.value)


def test_clean_longform_at_cap_passes():
    assert len(clean_for_square("x" * config.ARTICLE_MAX_CHARS,
                                format="longform")) == config.ARTICLE_MAX_CHARS


def test_clean_short_truncation_unchanged():
    assert len(clean_for_square("x" * 1500)) == 900


@pytest.fixture
def _poster_env(monkeypatch):
    """Poster with keys set, limit checks neutralised, no Telegram,
    Square HTTP stubbed; audit logger captured via caplog."""
    monkeypatch.setattr(poster, "BINANCE_SQUARE_KEY", "test-key")
    monkeypatch.setattr(poster, "BINANCE_SQUARE_URL",
                        "https://example.invalid/content/add")
    monkeypatch.setattr(poster, "TELEGRAM_BOT_TOKEN", None)
    monkeypatch.setattr(poster, "TELEGRAM_CHAT_ID", None)
    monkeypatch.setattr(poster, "can_post", lambda: True)
    monkeypatch.setattr(poster, "shutdown_if_limit_reached", lambda: None)
    monkeypatch.setattr(poster, "increment_post_counter", lambda: None)
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append({"url": url, "json": json})

        class _Resp:
            status_code = 200

            def json(self):
                return {"success": True,
                        "data": {"shareLink": "https://sq.example/x"}}

        return _Resp()

    monkeypatch.setattr(poster.requests, "post", fake_post)
    return calls


def test_post_to_targets_longform_over_cap_refuses(_poster_env, caplog):
    calls = _poster_env
    over = "x" * (config.ARTICLE_MAX_CHARS + 10)
    with caplog.at_level(logging.INFO, logger="post_audit"):
        result = poster.post_to_targets(
            over, "LOSERS", symbol="PYR", format="longform",
            title="A Title")
    assert result is False
    assert calls == []  # nothing reached Square (or Telegram)
    assert (f"ARTICLE_TRUNCATED|PYR|{config.ARTICLE_MAX_CHARS + 10}"
            in caplog.text)


def test_post_to_targets_longform_at_cap_posts(_poster_env):
    calls = _poster_env
    body = "x" * config.ARTICLE_MAX_CHARS
    assert poster.post_to_targets(body, "LOSERS", symbol="PYR",
                                  format="longform", title="A Title") is True
    assert len(calls) == 1
    assert calls[0]["json"]["contentType"] == 2
