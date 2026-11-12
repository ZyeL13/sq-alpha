# llm.py — Multi-provider with priority fallback, rate limiting, and cache
import time
import requests
import logging
from collections import defaultdict
from config import LLM_PROVIDERS, CATEGORY_PREFERRED
from storage.cache import set as cache_set

try:
    from prompts.rebate import REBATE_SYSTEM as DEFAULT_SYSTEM
except ImportError:
    DEFAULT_SYSTEM = """write 3 short paragraphs. lowercase except $SYMBOLS. no labels. output: <post>"""

log = logging.getLogger(__name__)

# Track request timestamps per provider
_request_history = defaultdict(list)

# Providers disabled at runtime because their model returned 404/410
# (dead model ID). In-memory only — cleared on restart.
_DISABLED_PROVIDERS = set()


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
        providers.append((provider, cfg.get("weight", 1)))
    providers.sort(key=lambda x: x[1], reverse=True)
    return [p[0] for p in providers]


def _record_request(provider_name: str):
    _request_history[provider_name].append(time.time())


def _call_provider(provider: str, user_prompt: str, system_prompt: str,
                   max_retries: int, backoff: int,
                   max_tokens: int | None = None) -> tuple[str | None, str | None]:
    """
    Call a specific provider.
    Returns (content, error_message)
    max_tokens overrides the provider's configured budget when given
    (V3 long-form only — short posts always use the configured value).
    """
    cfg = LLM_PROVIDERS.get(provider)
    if not cfg:
        return None, f"Unknown provider: {provider}"

    # Dead model (404/410 earlier): skip without even trying.
    if provider in _DISABLED_PROVIDERS:
        return None, f"Provider {provider} disabled (dead model, restart to re-enable)"

    # Check rate limit
    if not _can_send(provider):
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
                    # Extract post content — <post> tags are mandatory.
                    # A reply without them is reasoning or free-form text,
                    # never a post: fail the attempt so the caller retries
                    # or falls back, instead of queuing leaked reasoning.
                    if "<post>" in content:
                        content = content.split("<post>")[-1].split("</post>")[0].strip()
                    else:
                        print("  ⚠️ No <post> tags in response (possible reasoning leak)")
                        content = ""

                    if len(content) >= 30:
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
             max_tokens: int | None = None) -> str | None:
    """
    Generate content with priority fallback.
    Higher weight = higher priority (tried first).
    Falls back to next provider if current fails.
    max_tokens overrides every provider's configured budget for this
    call only (V3 long-form); None keeps the configured values.
    """
    if system_prompt is None:
        system_prompt = DEFAULT_SYSTEM
    
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
        
        # max_tokens override is passed only when given, so the
        # default call path stays identical to the pre-V3 signature.
        if max_tokens is not None:
            content, error = _call_provider(provider, user_prompt, system_prompt, max_retries, backoff,
                                            max_tokens=max_tokens)
        else:
            content, error = _call_provider(provider, user_prompt, system_prompt, max_retries, backoff)
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
        
        if max_tokens is not None:
            content, error = _call_provider(prov, user_prompt, system_prompt, max_retries, backoff,
                                            max_tokens=max_tokens)
        else:
            content, error = _call_provider(prov, user_prompt, system_prompt, max_retries, backoff)
        
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