"""LLM provider selection — Fase 3 langkah 3.

Offline: _call_provider is mocked, no real API calls.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_config_models_are_current():
    import config

    assert config.LLM_PROVIDERS["groq"]["model"] == "openai/gpt-oss-120b"
    assert config.LLM_PROVIDERS["groq"]["enabled"] is True
    assert config.LLM_PROVIDERS["deepseek"]["model"] == "deepseek-flash"
    assert config.LLM_PROVIDERS["deepseek"]["enabled"] is True
    assert "thinking_mode" not in config.LLM_PROVIDERS["deepseek"]
    assert config.CATEGORY_PREFERRED["ALPHA"] == "groq"


def test_generate_tries_groq_first_then_deepseek(monkeypatch):
    import llm

    tried = []

    def fake_call(provider, user_prompt, system_prompt, max_retries, backoff):
        tried.append(provider)
        if provider == "groq":
            return None, "rate limited"
        return "$XYZ test post content", None

    monkeypatch.setattr(llm, "_call_provider", fake_call)
    result = llm.generate("prompt", category="ALPHA", use_cache=False)
    assert result == "$XYZ test post content"
    assert tried == ["groq", "deepseek"]


def test_generate_returns_none_when_all_providers_fail(monkeypatch):
    import llm

    monkeypatch.setattr(
        llm, "_call_provider",
        lambda *a, **k: (None, "boom"),
    )
    assert llm.generate("prompt", category="HOT", use_cache=False) is None


def test_generate_specific_provider_only(monkeypatch):
    import llm

    tried = []

    def fake_call(provider, user_prompt, system_prompt, max_retries, backoff):
        tried.append(provider)
        return "$XYZ specific provider post", None

    monkeypatch.setattr(llm, "_call_provider", fake_call)
    result = llm.generate("prompt", provider="deepseek", use_cache=False)
    assert result == "$XYZ specific provider post"
    assert tried == ["deepseek"]
