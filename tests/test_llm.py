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
    # Step 1 (spec §5.2): CATEGORY_PREFERRED is empty — weight order
    # governs, so Luna (weight 7) is tried first on every category.
    assert config.CATEGORY_PREFERRED == {}
    # Luna (Coarena gpt-6-luna) registry entry.
    luna = config.LLM_PROVIDERS["coarena_luna"]
    assert luna["api_url"] == "https://coarena.ai/api/v1/chat/completions"
    assert luna["model"] == "gpt-6-luna"
    assert luna["max_tokens"] == 1200
    assert luna["temperature"] == 0.5
    assert luna["top_p"] == 0.9
    assert luna["requests_per_minute"] == 10
    assert luna["enabled"] is True
    assert luna["weight"] == 7
    assert config.ABSTAIN_THRESHOLD == 50.0
    assert config.COARENA_SQALPHA_DAILY_CALLS == 100
    assert config.PROMPT_VERSION == "json-v1"


def _stub_keys(monkeypatch, llm):
    """Give the enabled providers keys so tests don't depend on env vars."""
    for name in ("coarena_luna", "blockrun", "blockrun_llama", "blockrun_mistral", "groq"):
        monkeypatch.setitem(llm.LLM_PROVIDERS[name], "api_key", "test-key")


def _reset_coarena_state(monkeypatch, llm):
    """Clear Luna marker/counter/meta so each Luna test starts fresh."""
    monkeypatch.setattr(llm, "_COARENA_ALLOWANCE_RESET_UTC", 0.0)
    monkeypatch.setattr(llm, "_COARENA_EXHAUSTION_LOGGED", {})
    monkeypatch.setattr(llm, "_COARENA_CALL_COUNT", 0)
    monkeypatch.setattr(llm, "_COARENA_CALL_COUNT_DATE", None)
    monkeypatch.setattr(llm, "last_call_meta", None)
    monkeypatch.setattr(llm, "_DISABLED_PROVIDERS", set())
    from collections import defaultdict
    monkeypatch.setattr(llm, "_request_history", defaultdict(list))


def test_generate_tries_luna_before_blockrun_before_groq(monkeypatch):
    """Step 1 (spec §5.2/§5.3): Luna first, then BlockRun, then Groq —
    on every category, since CATEGORY_PREFERRED is empty."""
    import llm

    _stub_keys(monkeypatch, llm)
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    tried = []
    seen_kwargs = []

    def fake_call(provider, user_prompt, system_prompt, max_retries, backoff, **kwargs):
        tried.append(provider)
        seen_kwargs.append(kwargs)
        if provider == "coarena_luna":
            return None, "allowance exhausted"
        if provider == "blockrun":
            return None, "connection refused"
        return "$XYZ test post content", None

    monkeypatch.setattr(llm, "_call_provider", fake_call)
    result = llm.generate("prompt", category="ALPHA", use_cache=False)
    assert result == "$XYZ test post content"
    assert tried == ["coarena_luna", "blockrun", "blockrun_llama"]
    # Default path passes no overrides (old fakes keep working).
    assert seen_kwargs == [{}, {}, {}]


def test_providers_without_api_key_are_skipped(monkeypatch):
    import llm

    _stub_keys(monkeypatch, llm)
    # Luna sorts first (weight 7) when it has a key.
    assert llm._get_providers_by_priority()[0] == "coarena_luna"
    # Luna with an empty key is skipped, like DeepSeek.
    monkeypatch.setitem(llm.LLM_PROVIDERS["coarena_luna"], "api_key", "")
    assert "coarena_luna" not in llm._get_providers_by_priority()
    monkeypatch.setitem(llm.LLM_PROVIDERS["coarena_luna"], "api_key", "test-key")
    monkeypatch.setitem(llm.LLM_PROVIDERS["deepseek"], "enabled", True)
    monkeypatch.setitem(llm.LLM_PROVIDERS["deepseek"], "api_key", "")
    assert "deepseek" not in llm._get_providers_by_priority()
    # With a key it rejoins the rotation (weight order).
    monkeypatch.setitem(llm.LLM_PROVIDERS["deepseek"], "api_key", "test-key")
    assert llm._get_providers_by_priority() == [
        "coarena_luna", "blockrun", "blockrun_llama", "blockrun_mistral", "groq", "deepseek",
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

    def fake_call(provider, user_prompt, system_prompt, max_retries, backoff, **kwargs):
        tried.append(provider)
        return "$XYZ specific provider post", None

    monkeypatch.setattr(llm, "_call_provider", fake_call)
    result = llm.generate("prompt", provider="deepseek", use_cache=False)
    assert result == "$XYZ specific provider post"
    assert tried == ["deepseek"]


# --- JIT pool rate-limit signal (spec 5.6) ---------------------------------
# _call_provider returns only (content, error), so the pool needs a
# separate signal to tell a 429 from an ordinary generation failure:
# a timestamped marker per provider.

def test_429_marks_rate_limit_hit(monkeypatch):
    import time

    import llm

    monkeypatch.setattr(llm, "_RATE_LIMIT_HITS", {})
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    _stub_keys(monkeypatch, llm)
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(url)
        return _fake_response("", status_code=429, text="Too Many Requests")

    monkeypatch.setattr(llm.requests, "post", fake_post)
    t0 = time.time()
    content, error = llm._call_provider("groq", "prompt", "system", 2, 0)
    assert content is None
    assert len(calls) == 2
    assert "groq" in llm._RATE_LIMIT_HITS
    assert llm.was_rate_limited_since(t0) is True
    # A window starting after the hit sees nothing.
    assert llm.was_rate_limited_since(time.time() + 100) is False


def test_non_429_failure_does_not_mark(monkeypatch):
    import time

    import llm

    monkeypatch.setattr(llm, "_RATE_LIMIT_HITS", {})
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    _stub_keys(monkeypatch, llm)

    def fake_post(url, headers=None, json=None, timeout=None):
        return _fake_response("", status_code=500, text="boom")

    monkeypatch.setattr(llm.requests, "post", fake_post)
    t0 = time.time()
    content, error = llm._call_provider("groq", "prompt", "system", 1, 0)
    assert content is None
    assert llm.was_rate_limited_since(t0) is False


def test_local_throttle_marks_rate_limit(monkeypatch):
    import time
    from collections import defaultdict

    import llm

    monkeypatch.setattr(llm, "_RATE_LIMIT_HITS", {})
    monkeypatch.setattr(llm, "_request_history", defaultdict(list))
    _stub_keys(monkeypatch, llm)
    for _ in range(10):
        llm._record_request("groq")
    assert llm._can_send("groq") is False

    def fake_post(url, headers=None, json=None, timeout=None):
        raise AssertionError("throttled call must not reach the network")

    monkeypatch.setattr(llm.requests, "post", fake_post)
    t0 = time.time()
    content, error = llm._call_provider("groq", "prompt", "system", 1, 0)
    assert content is None
    assert "Rate limit" in error
    assert llm.was_rate_limited_since(t0) is True


def test_disabled_provider_throttle_does_not_mark(monkeypatch):
    import time
    from collections import defaultdict

    import llm

    monkeypatch.setattr(llm, "_RATE_LIMIT_HITS", {})
    monkeypatch.setattr(llm, "_request_history", defaultdict(list))
    monkeypatch.setattr(llm, "_DISABLED_PROVIDERS", {"groq"})
    _stub_keys(monkeypatch, llm)
    for _ in range(10):
        llm._record_request("groq")
    t0 = time.time()
    content, error = llm._call_provider("groq", "prompt", "system", 1, 0)
    assert content is None
    assert "disabled" in error
    assert llm.was_rate_limited_since(t0) is False


# --- Step 1: JSON output_format, last_call_meta, Luna 402/403/budget ---
# (spec §3.4, §5). No live calls — same monkeypatched requests.post +
# _fake_response pattern as the tests above.

def test_output_format_json_bypasses_post_tags(monkeypatch):
    """Regression test for spec §3.4.1: a JSON reply has no <post>
    tags, so the default path would empty EVERY JSON call. With
    output_format="json" the raw stripped content is returned."""
    import llm

    _reset_coarena_state(monkeypatch, llm)

    def fake_post(url, headers=None, json=None, timeout=None):
        return _fake_response(
            '{"event": "listing", "fact": "volume up", '
            '"interpretation": "momentum", "angle": "surprise", '
            '"post": "$BTC test post content here, long enough ok"}'
        )

    monkeypatch.setattr(llm.requests, "post", fake_post)
    content, error = llm._call_provider("groq", "prompt", "system", 1, 0,
                                        output_format="json")
    assert error is None
    assert content.startswith("{")
    assert '"post": "$BTC test post content here, long enough ok"' in content
    # Default path still empties a tag-less reply (see
    # test_response_without_post_tags_is_a_failure above).
    content, error = llm._call_provider("groq", "prompt", "system", 1, 0)
    assert content is None


def test_output_format_json_still_rejects_short_content(monkeypatch):
    """The len(content) >= 30 check still applies on the JSON path."""
    import llm

    def fake_post(url, headers=None, json=None, timeout=None):
        return _fake_response('{"post": "$BTC ok"}')

    monkeypatch.setattr(llm.requests, "post", fake_post)
    content, error = llm._call_provider("groq", "prompt", "system", 1, 0,
                                        output_format="json")
    assert content is None
    assert error is not None


def test_generate_threads_output_format(monkeypatch):
    """generate() passes output_format through to _call_provider on
    both the single-provider and the priority-fallback path."""
    import llm

    _stub_keys(monkeypatch, llm)
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    seen = []

    def fake_call(provider, user_prompt, system_prompt, max_retries, backoff, **kwargs):
        seen.append((provider, kwargs))
        return '{"post": "$XYZ json content here, long enough ok"}', None

    monkeypatch.setattr(llm, "_call_provider", fake_call)
    assert llm.generate("prompt", use_cache=False,
                        output_format="json") is not None
    assert seen == [("coarena_luna", {"output_format": "json"})]
    seen.clear()
    assert llm.generate("prompt", provider="groq", use_cache=False,
                        output_format="json") is not None
    assert seen == [("groq", {"output_format": "json"})]


def test_last_call_meta_set_on_success(monkeypatch):
    import llm

    _reset_coarena_state(monkeypatch, llm)
    assert llm.last_call_meta is None

    def fake_post(url, headers=None, json=None, timeout=None):
        return _fake_response("<post>$BTC test post content here, long enough ok</post>")

    monkeypatch.setattr(llm.requests, "post", fake_post)
    content, error = llm._call_provider("groq", "prompt", "system", 1, 0)
    assert error is None
    assert content.startswith("$BTC")
    assert llm.last_call_meta["provider"] == "groq"
    assert llm.last_call_meta["model"] == "openai/gpt-oss-120b"
    assert isinstance(llm.last_call_meta["usage"], dict)
    assert llm.last_call_meta["usage"] == {
        "completion_tokens_details": {"reasoning_tokens": None}
    }


def test_luna_200_returns_content_and_meta(monkeypatch):
    import llm

    _reset_coarena_state(monkeypatch, llm)
    _stub_keys(monkeypatch, llm)
    seen = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        seen["url"] = url
        seen["json"] = json
        return _fake_response("<post>$BTC luna post content here, long enough ok</post>")

    monkeypatch.setattr(llm.requests, "post", fake_post)
    content, error = llm._call_provider("coarena_luna", "prompt", "system", 1, 0)
    assert error is None
    assert content == "$BTC luna post content here, long enough ok"
    assert "coarena.ai" in seen["url"]
    assert seen["json"]["model"] == "gpt-6-luna"
    assert seen["json"]["max_tokens"] == 1200
    assert llm.last_call_meta["provider"] == "coarena_luna"
    assert llm.last_call_meta["model"] == "gpt-6-luna"


def test_luna_402_no_retry_sets_marker(monkeypatch, capsys):
    import llm

    _reset_coarena_state(monkeypatch, llm)
    _stub_keys(monkeypatch, llm)
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(url)
        return _fake_response("", status_code=402, text="payment_required")

    monkeypatch.setattr(llm.requests, "post", fake_post)
    content, error = llm._call_provider("coarena_luna", "prompt", "system", 2, 0)
    assert content is None
    assert "402" in error
    assert "allowance" in error.lower()
    assert len(calls) == 1  # no retry consumed on a 402
    assert llm._coarena_allowance_exhausted() is True
    out = capsys.readouterr().out
    assert "COARENA_ALLOWANCE_EXHAUSTED" in out
    assert "reset_utc=" in out
    # Priority list skips Luna while the marker is active, so later
    # drafts go straight to BlockRun/Groq.
    assert "coarena_luna" not in llm._get_providers_by_priority()
    assert llm._get_providers_by_priority()[0] == "blockrun"
    # The marker log fires once per UTC day: a second 402 attempt is
    # short-circuited without sending and without a second log line.
    content, error = llm._call_provider("coarena_luna", "prompt", "system", 2, 0)
    assert content is None
    assert len(calls) == 1
    out = capsys.readouterr().out
    assert "COARENA_ALLOWANCE_EXHAUSTED" not in out


def test_other_provider_402_goes_generic_no_marker(monkeypatch):
    """A 402 on a non-Luna provider is an ordinary failure: retried
    per max_retries, no exhaustion marker, Luna unaffected."""
    import llm

    _reset_coarena_state(monkeypatch, llm)
    _stub_keys(monkeypatch, llm)
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(url)
        return _fake_response("", status_code=402, text="payment_required")

    monkeypatch.setattr(llm.requests, "post", fake_post)
    content, error = llm._call_provider("groq", "prompt", "system", 2, 0)
    assert content is None
    assert "402" not in error  # generic "All N attempts failed" error
    assert len(calls) == 2  # retried, unlike Luna's 402
    assert llm._coarena_allowance_exhausted() is False
    assert "coarena_luna" in llm._get_providers_by_priority()


def test_luna_403_terms_required_disables_no_retry(monkeypatch, capsys):
    import llm

    _reset_coarena_state(monkeypatch, llm)
    _stub_keys(monkeypatch, llm)
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(url)
        return _fake_response(
            "", status_code=403,
            text='{"error": {"code": "model_api_terms_required", '
                 '"message": "accept the Model API terms"}}',
        )

    monkeypatch.setattr(llm.requests, "post", fake_post)
    content, error = llm._call_provider("coarena_luna", "prompt", "system", 2, 0)
    assert content is None
    assert "403" in error
    assert len(calls) == 1  # no retry on a config error
    assert "coarena_luna" in llm._DISABLED_PROVIDERS
    assert "coarena_luna" not in llm._get_providers_by_priority()
    out = capsys.readouterr().out
    assert "accept Model API terms on the Coarena account page" in out
    # Second call short-circuits without touching the network.
    content, error = llm._call_provider("coarena_luna", "prompt", "system", 2, 0)
    assert content is None
    assert len(calls) == 1


def test_other_403_goes_generic_no_disable(monkeypatch):
    """A 403 without model_api_terms_required is an ordinary failure:
    retried, provider NOT disabled."""
    import llm

    _reset_coarena_state(monkeypatch, llm)
    _stub_keys(monkeypatch, llm)
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(url)
        return _fake_response("", status_code=403, text="Forbidden")

    monkeypatch.setattr(llm.requests, "post", fake_post)
    content, error = llm._call_provider("coarena_luna", "prompt", "system", 2, 0)
    assert content is None
    assert len(calls) == 2  # retried
    assert "coarena_luna" not in llm._DISABLED_PROVIDERS
    assert "coarena_luna" in llm._get_providers_by_priority()


def test_luna_call_budget_blocks_after_limit(monkeypatch, capsys):
    """Call-count cap (spec §5.4): exactly N calls are sent, the
    (N+1)th is blocked without sending and sets the same exhaustion
    marker as a 402, logging COARENA_CALL_BUDGET once."""
    import llm

    _reset_coarena_state(monkeypatch, llm)
    _stub_keys(monkeypatch, llm)
    monkeypatch.setattr(llm, "COARENA_SQALPHA_DAILY_CALLS", 2)
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(url)
        return _fake_response("<post>$BTC luna post content here, long enough ok</post>")

    monkeypatch.setattr(llm.requests, "post", fake_post)
    assert llm._call_provider("coarena_luna", "prompt", "system", 1, 0)[0] is not None
    assert llm._call_provider("coarena_luna", "prompt", "system", 1, 0)[0] is not None
    assert len(calls) == 2
    content, error = llm._call_provider("coarena_luna", "prompt", "system", 1, 0)
    assert content is None
    assert "budget" in error.lower()
    assert len(calls) == 2  # blocked call never sent
    assert llm._coarena_allowance_exhausted() is True
    assert "coarena_luna" not in llm._get_providers_by_priority()
    out = capsys.readouterr().out
    assert "COARENA_CALL_BUDGET" in out
    assert "limit=2" in out
