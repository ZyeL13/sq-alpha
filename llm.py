# llm.py — Multi-provider with priority fallback, rate limiting, and cache
import time
from datetime import datetime, timezone
import requests
import logging
from collections import defaultdict
from config import LLM_PROVIDERS, CATEGORY_PREFERRED, COARENA_SQALPHA_DAILY_CALLS
from storage.cache import set as cache_set

try:
    from prompts.rebate import REBATE_SYSTEM as DEFAULT_SYSTEM
except ImportError:
    DEFAULT_SYSTEM = """write 3 short paragraphs. lowercase except $SYMBOLS. no labels. output: <post>"""

log = logging.getLogger(__name__)

# Metadata of the most recent successful provider call:
# {"provider": str, "model": str, "usage": dict}. In-memory only; set
# on every successful _call_provider return. _schedule_winner reads it
# for the logs/posts.csv row (provider/model must not be hardcoded).
# Known limitation: a concurrent caller would overwrite it, but
# PROCESSOR_WORKERS = 1 makes that impossible today.
last_call_meta: dict | None = None

# Coarena (Luna) allowance-exhaustion marker: epoch of the next 00:00
# UTC, the allowance reset. While time.time() is below it, Luna is
# skipped (see _coarena_allowance_exhausted). In-memory only — cleared
# on restart, same as _DISABLED_PROVIDERS; a restart re-probes Luna once.
_COARENA_ALLOWANCE_RESET_UTC: float = 0.0
# kind -> UTC date ("YYYY-MM-DD") the exhaustion line was last logged,
# so COARENA_ALLOWANCE_EXHAUSTED / COARENA_CALL_BUDGET each log once
# per UTC day (kinds: "allowance", "call_budget").
_COARENA_EXHAUSTION_LOGGED: dict = {}
# In-process Coarena call counter for the daily call-count cap (spec
# §5.4): reset when the UTC date changes.
_COARENA_CALL_COUNT: int = 0
_COARENA_CALL_COUNT_DATE: str | None = None

# Track request timestamps per provider
_request_history = defaultdict(list)

# Providers disabled at runtime because their model returned 404/410
# (dead model ID). In-memory only — cleared on restart.
_DISABLED_PROVIDERS = set()

# Last time each provider answered HTTP 429 (or the local per-minute
# throttle blocked it). The JIT pool reads this to distinguish a
# rate-limit failure from an ordinary generation failure: on a 429
# the pool stops drafting and picks a winner from the drafts already
# completed, instead of hammering the provider pool_size times.
# In-memory only; timestamps, so stale hits never mislead a later call.
_RATE_LIMIT_HITS = {}


def mark_rate_limited(provider_name: str) -> None:
    """Record a rate-limit hit for a provider, right now."""
    _RATE_LIMIT_HITS[provider_name] = time.time()


def was_rate_limited_since(t0: float) -> bool:
    """True when any provider was rate-limited at or after t0.

    The pool records t0 just before a draft call and checks right
    after a failed draft: only hits inside that window count, so a
    429 from an earlier, unrelated call never triggers an early-exit.
    """
    return any(hit >= t0 for hit in _RATE_LIMIT_HITS.values())


def _utc_today() -> str:
    """Current UTC date as "YYYY-MM-DD" (allowance / budget day)."""
    return datetime.now(timezone.utc).date().isoformat()


def _next_utc_midnight_epoch() -> float:
    """Epoch seconds of the next 00:00 UTC (allowance reset)."""
    now = datetime.now(timezone.utc)
    midnight = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    return midnight.timestamp() + 86400


def _coarena_allowance_exhausted() -> bool:
    """True while the Luna allowance-exhaustion marker is active."""
    return time.time() < _COARENA_ALLOWANCE_RESET_UTC


def _set_coarena_allowance_exhausted(kind: str, log_line: str) -> None:
    """Set the Luna exhaustion marker until the next 00:00 UTC.

    kind is "allowance" (HTTP 402) or "call_budget" (daily call-count
    cap); each kind logs its line once per UTC day.
    """
    global _COARENA_ALLOWANCE_RESET_UTC
    _COARENA_ALLOWANCE_RESET_UTC = _next_utc_midnight_epoch()
    today = _utc_today()
    if _COARENA_EXHAUSTION_LOGGED.get(kind) != today:
        _COARENA_EXHAUSTION_LOGGED[kind] = today
        print(log_line)


def _check_coarena_call_budget() -> str | None:
    """Enforce the daily Luna call-count cap (spec §5.4).

    Increments the in-process counter for this invocation (callers
    check the marker first, so a blocked call never increments).
    Returns an error string when the cap is reached — the caller
    returns it without sending — else None.
    """
    global _COARENA_CALL_COUNT, _COARENA_CALL_COUNT_DATE
    today = _utc_today()
    if _COARENA_CALL_COUNT_DATE != today:
        _COARENA_CALL_COUNT_DATE = today
        _COARENA_CALL_COUNT = 0
    _COARENA_CALL_COUNT += 1
    if _COARENA_CALL_COUNT > COARENA_SQALPHA_DAILY_CALLS:
        _set_coarena_allowance_exhausted(
            "call_budget",
            f"  ❌ COARENA_CALL_BUDGET|provider=coarena_luna|"
            f"calls={_COARENA_CALL_COUNT}|limit={COARENA_SQALPHA_DAILY_CALLS}",
        )
        return (f"Coarena daily call budget reached "
                f"({_COARENA_CALL_COUNT}>{COARENA_SQALPHA_DAILY_CALLS} calls)")
    return None


def _can_send(provider_name: str) -> bool:
    """Check if provider is within rate limit"""
    cfg = LLM_PROVIDERS.get(provider_name)
    if not cfg or not cfg.get("enabled", True):
        return False
    rpm = cfg.get("requests_per_minute", 30)
    now = time.time()
    _request_history[provider_name] = [t for t in _request_history[provider_name] if now - t < 60]
    return len(_request_history[provider_name]) < rpm


def _get_providers_by_priority() -> list:
    """Return list of provider names sorted by weight (highest first).

    Providers that are disabled or have no api_key are skipped — e.g.
    DeepSeek stays out of the rotation while its key is empty.
    """
    providers = []
    for provider, cfg in LLM_PROVIDERS.items():
        if not cfg.get("enabled", True):
            continue
        if not cfg.get("api_key"):
            continue
        if provider in _DISABLED_PROVIDERS:
            continue
        # Luna allowance exhausted (402 or daily call-count cap):
        # skip until the next 00:00 UTC so drafts go straight to
        # BlockRun/Groq with no per-draft 402 tax.
        if provider == "coarena_luna" and _coarena_allowance_exhausted():
            continue
        providers.append((provider, cfg.get("weight", 1)))
    providers.sort(key=lambda x: x[1], reverse=True)
    return [p[0] for p in providers]


def _record_request(provider_name: str):
    _request_history[provider_name].append(time.time())


def _call_provider(provider: str, user_prompt: str, system_prompt: str,
                   max_retries: int, backoff: int,
                   max_tokens: int | None = None,
                   output_format: str | None = None) -> tuple[str | None, str | None]:
    """
    Call a specific provider.
    Returns (content, error_message)
    max_tokens overrides the provider's configured budget when given
    (V3 long-form only — short posts always use the configured value).
    output_format="json" skips the <post>-tag extraction and returns
    the raw stripped content (step 1 short-form JSON path); the
    default (None) keeps the tag extraction — the reasoning-leak guard
    is NOT weakened. Appended after max_tokens so existing positional
    callers keep working.
    """
    global last_call_meta
    cfg = LLM_PROVIDERS.get(provider)
    if not cfg:
        return None, f"Unknown provider: {provider}"

    # Dead model (404/410 earlier): skip without even trying.
    if provider in _DISABLED_PROVIDERS:
        return None, f"Provider {provider} disabled (dead model, restart to re-enable)"

    # Luna allowance exhausted (402 earlier today, or daily call-count
    # cap): skip without sending, so a direct call can't re-pay the
    # per-draft 402 tax either. _get_providers_by_priority already
    # excludes Luna while the marker is set; this is the backstop.
    if provider == "coarena_luna":
        if _coarena_allowance_exhausted():
            return None, ("Coarena allowance exhausted for coarena_luna "
                          "(HTTP 402 / daily budget, resets 00:00 UTC)")
        budget_error = _check_coarena_call_budget()
        if budget_error is not None:
            return None, budget_error

    # Check rate limit
    if not _can_send(provider):
        if cfg.get("enabled", True):
            # Local per-minute throttle: a rate-limit signal, like a
            # server 429 — the JIT pool treats it as one.
            mark_rate_limited(provider)
        return None, f"Rate limit exceeded for {provider}"
    
    headers = {
        "Authorization": f"Bearer {cfg['api_key']}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "max_tokens": max_tokens if max_tokens is not None else cfg["max_tokens"],
        "temperature": cfg["temperature"],
        "top_p": cfg["top_p"],
    }
    # Provider-specific extras, only when configured — e.g. Groq's
    # reasoning_effort is a 400 on providers that don't support it.
    for extra in ("reasoning_effort", "include_reasoning"):
        if extra in cfg:
            payload[extra] = cfg[extra]

    current_backoff = backoff

    for attempt in range(1, max_retries + 1):
        try:
            print(f"  🔄 LLM ({provider}) attempt {attempt}/{max_retries}...")
            # Record BEFORE sending: failed attempts count toward the
            # per-minute throttle too. Previously only successes were
            # recorded, so the throttle never engaged while every
            # attempt failed and Groq 429'd us server-side.
            _record_request(provider)
            response = requests.post(
                cfg["api_url"],
                headers=headers,
                json=payload,
                timeout=30,
            )

            if response.status_code == 200:
                try:
                    data = response.json()
                except ValueError:
                    # Log the raw reply before parsing: if a proxy or
                    # Cloudflare error page came back as HTML, json()
                    # fails — the raw body shows what actually happened.
                    print(f"  ⚠️ Non-JSON 200 response: status={response.status_code}, "
                          f"content-type={response.headers.get('content-type')}, "
                          f"body={response.text[:300]!r}")
                    if attempt < max_retries:
                        print(f"  ⏳ Retry dalam {current_backoff}s...")
                        time.sleep(current_backoff)
                        current_backoff *= 2
                    continue
                choice = data["choices"][0]
                content = choice["message"].get("content")
                import re
                if isinstance(content, str):
                    content = re.sub(r'\$([A-Z]+)[\'"]?s\b', r'$\1', content)

                if content and isinstance(content, str):
                    content = content.strip()

                    # Strip thinking tags (DeepSeek specific)
                    if "<think>" in content:
                        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
                    if output_format == "json":
                        # JSON path (step 1 short-form): skip the
                        # <post>-tag extraction entirely — a JSON reply
                        # has no tags, so the default path would empty
                        # every JSON call. Still subject to the
                        # len(content) >= 30 check below.
                        pass
                    elif "<post>" in content:
                        # Extract post content — <post> tags are mandatory.
                        # A reply without them is reasoning or free-form text,
                        # never a post: fail the attempt so the caller retries
                        # or falls back, instead of queuing leaked reasoning.
                        content = content.split("<post>")[-1].split("</post>")[0].strip()
                    else:
                        print("  ⚠️ No <post> tags in response (possible reasoning leak)")
                        content = ""

                    if len(content) >= 30:
                        last_call_meta = {
                            "provider": provider,
                            "model": cfg["model"],
                            "usage": data.get("usage", {}) or {},
                        }
                        return content, None
                    else:
                        print(f"  ⚠️ Content too short ({len(content)} chars)")
                else:
                    # Empty content from a reasoning model usually means
                    # the reasoning ate the whole token budget
                    # (finish_reason=length). Log the real cause instead
                    # of a generic "invalid type".
                    finish = choice.get("finish_reason")
                    usage = data.get("usage", {}) or {}
                    reasoning = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
                    print(f"  ⚠️ Empty content (finish_reason={finish}, "
                          f"reasoning_tokens={reasoning}, usage={usage})")
        
            elif response.status_code == 429:
                # Rate limit - wait longer
                mark_rate_limited(provider)
                wait_time = min(60, (attempt ** 2) * 5)  # 5, 20, 45, max 60
                print(f"  ⚠️ Rate limit (429), waiting {wait_time}s before retry...")
                time.sleep(wait_time)
                # Don't consume retry count for rate limit
                current_backoff = wait_time + backoff
                continue
    
            elif response.status_code in (404, 410):
                # Dead model (retired model ID): retrying is pointless.
                # Skip to the next provider and disable this one until
                # the process restarts.
                _DISABLED_PROVIDERS.add(provider)
                print(f"  ❌ HTTP {response.status_code}: dead model, "
                      f"{provider} disabled until restart: {response.text[:200]}")
                return None, f"Model gone (HTTP {response.status_code}) for {provider}"

            elif response.status_code == 400 and "unknown model" in response.text.lower():
                # Dead model ID reported as 400, not 404/410 (BlockRun
                # proxy, 2026-11-09: nvidia/deepseek-v4-flash). Retrying
                # is pointless — disable until restart like a 404/410.
                _DISABLED_PROVIDERS.add(provider)
                print(f"  ❌ HTTP 400: unknown model, "
                      f"{provider} disabled until restart: {response.text[:200]}")
                return None, f"Unknown model (HTTP 400) for {provider}"

            elif response.status_code == 402 and provider == "coarena_luna":
                # Allowance exhausted ($1/day shared with Dialectica):
                # do NOT consume retries — return immediately and set
                # the marker until the next 00:00 UTC, so after the
                # first 402 of the day there is no per-draft 402 tax.
                # A 402 on any other provider falls through to the
                # generic branch below (no marker).
                reset_utc = _next_utc_midnight_epoch()
                _set_coarena_allowance_exhausted(
                    "allowance",
                    f"  ❌ COARENA_ALLOWANCE_EXHAUSTED|provider=coarena_luna|"
                    f"reset_utc={int(reset_utc)}",
                )
                return None, ("Coarena allowance exhausted (HTTP 402) for "
                              "coarena_luna, resets 00:00 UTC")

            elif response.status_code == 403 and "model_api_terms_required" in response.text:
                # Config error, not a retryable failure: the Coarena
                # account has not accepted the Model API terms.
                # Disable for this process lifetime (same set as
                # 404/410) and fall through to the next provider.
                _DISABLED_PROVIDERS.add(provider)
                print(f"  ❌ HTTP 403: model_api_terms_required — accept "
                      f"Model API terms on the Coarena account page; "
                      f"{provider} disabled until restart: {response.text[:200]}")
                return None, f"Model API terms not accepted (HTTP 403) for {provider}"

            else:
                print(f"  ❌ HTTP {response.status_code}: {response.text[:100]}")
                
        except requests.exceptions.Timeout:
            print(f"  ⏱️ Timeout attempt {attempt}")
        except Exception as e:
            print(f"  ❌ Attempt {attempt} error: {e}")
        
        if attempt < max_retries:
            print(f"  ⏳ Retry dalam {current_backoff}s...")
            time.sleep(current_backoff)
            current_backoff *= 2
    
    return None, f"All {max_retries} attempts failed for {provider}"


def generate(user_prompt: str,
             system_prompt: str = None,
             provider: str = None,
             category: str = None,
             max_retries: int = 2,
             backoff: int = 10,
             use_cache: bool = True,
             max_tokens: int | None = None,
             output_format: str | None = None) -> str | None:
    """
    Generate content with priority fallback.
    Higher weight = higher priority (tried first).
    Falls back to next provider if current fails.
    max_tokens overrides every provider's configured budget for this
    call only (V3 long-form); None keeps the configured values.
    output_format="json" is passed through to _call_provider (skips
    the <post>-tag extraction); None keeps the default tag path.
    """
    if system_prompt is None:
        system_prompt = DEFAULT_SYSTEM

    # Optional overrides are passed only when given, so the default
    # call path stays identical to the pre-V3 signature.
    call_kwargs: dict = {}
    if max_tokens is not None:
        call_kwargs["max_tokens"] = max_tokens
    if output_format is not None:
        call_kwargs["output_format"] = output_format

    # Check cache first
    if use_cache and provider is None:
        # Need to try cache for each provider? Skip cache for priority mode
        pass

    # If specific provider requested, try only that one
    if provider:
        cfg = LLM_PROVIDERS.get(provider)
        if not cfg:
            print(f"  ❌ Unknown provider: {provider}")
            return None

        content, error = _call_provider(provider, user_prompt, system_prompt, max_retries, backoff,
                                        **call_kwargs)
        if content and use_cache:
            cache_set(user_prompt, system_prompt, cfg["model"], cfg["temperature"], content)
        return content

    # Priority fallback: category-preferred provider first (if enabled),
    # then the remaining providers in weight order.
    priority_list = _get_providers_by_priority()
    if category:
        preferred = CATEGORY_PREFERRED.get(category)
        if preferred in priority_list:
            priority_list.remove(preferred)
            priority_list.insert(0, preferred)
    attempted = []

    for prov in priority_list:
        attempted.append(prov)
        print(f"  🎯 Trying {prov} (priority {len(attempted)}/{len(priority_list)})...")

        content, error = _call_provider(prov, user_prompt, system_prompt, max_retries, backoff,
                                        **call_kwargs)

        if content:
            # Save to cache with provider-specific key
            if use_cache:
                cfg = LLM_PROVIDERS.get(prov)
                cache_set(user_prompt, system_prompt, cfg["model"], cfg["temperature"], content)
            return content
        
        print(f"  ⚠️ {prov} failed: {error}")
        print("  🔁 Falling back to next provider...")
        time.sleep(2)
    
    print("  ❌ All providers failed. Tried: " + ", ".join(attempted))
    return None