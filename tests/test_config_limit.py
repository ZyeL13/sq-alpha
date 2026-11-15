"""DAILY_POST_LIMIT is tunable via .env, defaulting to 10.

The override exists for temporary tests (e.g. raising the cap to 25 so
the bot resumes the same day after the 10/day quota is exhausted). Each
test reloads config and restores the default afterwards, so later tests
still see the default value.
"""
import importlib

import config


def _reload_with_env(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("DAILY_POST_LIMIT", raising=False)
    else:
        monkeypatch.setenv("DAILY_POST_LIMIT", value)
    importlib.reload(config)


def test_daily_post_limit_env_override(monkeypatch):
    _reload_with_env(monkeypatch, "25")
    try:
        assert config.DAILY_POST_LIMIT == 25
    finally:
        _reload_with_env(monkeypatch, None)
    assert config.DAILY_POST_LIMIT == 10


def test_daily_post_limit_invalid_env_falls_back_to_default(monkeypatch):
    _reload_with_env(monkeypatch, "bukan-angka")
    try:
        assert config.DAILY_POST_LIMIT == 10
    finally:
        _reload_with_env(monkeypatch, None)
    assert config.DAILY_POST_LIMIT == 10
