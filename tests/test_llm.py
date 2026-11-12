"""LLM provider selection — Fase 3 langkah 3.

Offline: _call_provider is mocked, no real API calls.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_config_models_are_current():
    import config

    # BlockRun: exact model IDs from the proxy's /v1/models output —
    # "free" alone is not a valid model ID.
    assert config.LLM_PROVIDERS["blockrun"]["enabled"] is True
    assert config.LLM_PROVIDERS["blockrun"]["model"] == "free/deepseek-v4-flash"
    assert config.LLM_PROVIDERS["blockrun_llama"]["model"] == "free/llama-4-maverick"
    assert config.LLM_PROVIDERS["blockrun_mistral"]["model"] == "free/mistral-large-3-675b"
    assert config.LLM_PROVIDERS["groq"]["model"] == "openai/gpt-oss-120b"
    assert config.LLM_PROVIDERS["groq"]["enabled"] is True
    # gpt-oss is a reasoning model: reasoning eats the max_tokens budget,
    # so the budget must leave room for the answer.
    assert config.LLM_PROVIDERS["groq"]["max_tokens"] == 1800
    assert config.LLM_PROVIDERS["groq"]["reasoning_effort"] == "low"
    assert config.LLM_PROVIDERS["groq"]["include_reasoning"] is False
    assert config.LLM_PROVIDERS["deepseek"]["model"] == "deepseek-flash"
    assert config.LLM_PROVIDERS["deepseek"]["enabled"] is False  # not topped up
    assert "thinking_mode" not in config.LLM_PROVIDERS["deepseek"]
    # meta/llama-3.3-70b-instruct retired 2026-08-26 (HTTP 410 Gone).
    # NIM stays disabled until a replacement is verified live.
    assert config.LLM_PROVIDERS["nvidia_nim"]["enabled"] is False
    assert config.CATEGORY_PREFERRED["ALPHA"] == "blockrun"


def _stub_keys(monkeypatch, llm):
    """Give the enabled providers keys so tests don't depend on env vars."""
    for name in ("blockrun", "blockrun_llama", "blockrun_mistral", "groq"):
        monkeypatch.setitem(llm.LLM_PROVIDERS[name], "api_key", "test-key")


def test_generate_tries_blockrun_models_before_groq(monkeypatch):
    import llm

    _stub_keys(monkeypatch, llm)
    tried = []

    def fake_call(provider, user_prompt, system_prompt, max_retries, backoff):
        tried.append(provider)
        if provider == "blockrun":
            return None, "connection refused"
        return "$XYZ test post content", None

    monkeypatch.setattr(llm, "_call_provider", fake_call)
    result = llm.generate("prompt", category="ALPHA", use_cache=False)
    assert result == "$XYZ test post content"
    assert tried == ["blockrun", "blockrun_llama"]


def test_providers_without_api_key_are_skipped(monkeypatch):
    import llm

    _stub_keys(monkeypatch, llm)
    monkeypatch.setitem(llm.LLM_PROVIDERS["deepseek"], "enabled", True)
    monkeypatch.setitem(llm.LLM_PROVIDERS["deepseek"], "api_key", "")
    assert "deepseek" not in llm._get_providers_by_priority()
    # With a key it rejoins the rotation (weight order).
    monkeypatch.setitem(llm.LLM_PROVIDERS["deepseek"], "api_key", "test-key")
    assert llm._get_providers_by_priority() == [
        "blockrun", "blockrun_llama", "blockrun_mistral", "groq", "deepseek",
    ]


def _fake_response(content, finish_reason="stop", reasoning_tokens=None,
                   status_code=200, text="", headers=None):
    class Resp:
        def __init__(self):
            self.status_code = status_code
            self.text = text
            self.headers = headers or {}

        def json(self):
            return {
                "choices": [{"message": {"content": content}, "finish_reason": finish_reason}],
                "usage": {
                    "completion_tokens_details": {"reasoning_tokens": reasoning_tokens}
                },
            }

    return Resp()


def test_dead_model_410_skips_retry_and_disables(monkeypatch):
    import llm

    monkeypatch.setattr(llm, "_DISABLED_PROVIDERS", set())
    _stub_keys(monkeypatch, llm)
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(url)
        return _fake_response("", status_code=410, text="Gone")

    monkeypatch.setattr(llm.requests, "post", fake_post)
    content, error = llm._call_provider("groq", "prompt", "system", 2, 0)
    assert content is None
    assert "410" in error
    assert len(calls) == 1  # no retry on a dead model
    assert "groq" in llm._DISABLED_PROVIDERS
    # Second call short-circuits without touching the network.
    content, error = llm._call_provider("groq", "prompt", "system", 2, 0)
    assert content is None
    assert len(calls) == 1
    assert "groq" not in llm._get_providers_by_priority()


def test_request_timeout_is_30s(monkeypatch):
    import llm

    seen = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        seen["timeout"] = timeout
        return _fake_response("$BTC test post content here, long enough ok")

    monkeypatch.setattr(llm.requests, "post", fake_post)
    llm._call_provider("groq", "prompt", "system", 1, 0)
    assert seen["timeout"] == 30


def test_non_json_response_logs_raw_body(monkeypatch, capsys):
    import llm

    class HtmlResp:
        status_code = 200
        headers = {"content-type": "text/html"}
        text = "<html>proxy error page</html>"

        def json(self):
            raise ValueError("No JSON object could be decoded")

    monkeypatch.setattr(llm.requests, "post", lambda *a, **k: HtmlResp())
    content, error = llm._call_provider("groq", "prompt", "system", 1, 0)
    assert content is None
    out = capsys.readouterr().out
    assert "text/html" in out
    assert "proxy error page" in out


def test_groq_payload_has_reasoning_params(monkeypatch):
    import llm

    seen = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        seen["json"] = json
        return _fake_response("<post>$BTC test post content here, long enough ok</post>")

    monkeypatch.setattr(llm.requests, "post", fake_post)
    content, error = llm._call_provider("groq", "prompt", "system", 1, 0)
    assert error is None
    assert content.startswith("$BTC")
    assert seen["json"]["reasoning_effort"] == "low"
    assert seen["json"]["include_reasoning"] is False
    assert seen["json"]["max_tokens"] == 1800


def test_blockrun_payload_has_no_reasoning_params(monkeypatch):
    import llm

    seen = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        seen["json"] = json
        return _fake_response("<post>$BTC test post content here, long enough ok</post>")

    monkeypatch.setattr(llm.requests, "post", fake_post)
    content, error = llm._call_provider("blockrun", "prompt", "system", 1, 0)
    assert error is None
    assert "reasoning_effort" not in seen["json"]
    assert "include_reasoning" not in seen["json"]


def test_response_without_post_tags_is_a_failure(monkeypatch):
    """Demo 2026-11-09: BlockRun mistral returned bare chain-of-thought
    with no <post> tags. That must fail the attempt (retry/fallback),
    never be returned as post content."""
    import llm

    monkeypatch.setattr(llm, "_DISABLED_PROVIDERS", set())
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(url)
        return _fake_response(
            "We need to produce a short post (40-120 words). Must start "
            "with \"$KITE\" uppercase in first line. Let's draft: the token "
            "rose 4.2% to $2.40 on $8.5M volume, a level not seen before."
        )

    monkeypatch.setattr(llm.requests, "post", fake_post)
    content, error = llm._call_provider("groq", "prompt", "system", 1, 0)
    assert content is None
    assert error is not None
    assert len(calls) == 1


def test_post_tags_are_extracted_and_reasoning_dropped(monkeypatch):
    import llm

    def fake_post(url, headers=None, json=None, timeout=None):
        return _fake_response(
            "Some reasoning before the tags. "
            "<post>$BTC real post content here, long enough ok</post> "
            "trailing notes after the tags."
        )

    monkeypatch.setattr(llm.requests, "post", fake_post)
    content, error = llm._call_provider("groq", "prompt", "system", 1, 0)
    assert error is None
    assert content == "$BTC real post content here, long enough ok"


def test_unknown_model_400_disables_like_410(monkeypatch):
    """BlockRun proxy answers a dead model ID with HTTP 400, not 404/410
    (2026-11-09: nvidia/deepseek-v4-flash). Same treatment: no retry,
    provider disabled until restart."""
    import llm

    monkeypatch.setattr(llm, "_DISABLED_PROVIDERS", set())
    _stub_keys(monkeypatch, llm)
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(url)
        return _fake_response(
            "", status_code=400,
            text='{"error":"Unknown model: nvidia/deepseek-v4-flash. '
                 'Try one of: openai/gpt-6-astra"}',
        )

    monkeypatch.setattr(llm.requests, "post", fake_post)
    content, error = llm._call_provider("blockrun", "prompt", "system", 2, 0)
    assert content is None
    assert "400" in error
    assert len(calls) == 1  # no retry on a dead model
    assert "blockrun" in llm._DISABLED_PROVIDERS
    content, error = llm._call_provider("blockrun", "prompt", "system", 2, 0)
    assert content is None
    assert len(calls) == 1
    assert "blockrun" not in llm._get_providers_by_priority()


def test_empty_content_logs_finish_reason(monkeypatch, capsys):
    import llm

    def fake_post(url, headers=None, json=None, timeout=None):
        return _fake_response("", finish_reason="length", reasoning_tokens=2000)

    monkeypatch.setattr(llm.requests, "post", fake_post)
    content, error = llm._call_provider("groq", "prompt", "system", 1, 0)
    assert content is None
    assert error is not None
    out = capsys.readouterr().out
    assert "finish_reason=length" in out
    assert "reasoning_tokens=2000" in out


def test_failed_attempts_count_toward_rate_limit(monkeypatch):
    import llm
    from collections import defaultdict

    monkeypatch.setattr(llm, "_request_history", defaultdict(list))
    for _ in range(10):
        llm._record_request("groq")
    assert llm._can_send("groq") is False


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
