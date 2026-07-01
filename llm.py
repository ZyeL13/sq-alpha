# llm.py — Multi-provider with priority fallback, rate limiting, and cache
import time
import random
import re
import requests
import logging
from collections import defaultdict
from config import LLM_PROVIDERS, CATEGORY_PREFERRED
from storage.cache import get as cache_get, set as cache_set

try:
    from prompts.rebate import REBATE_SYSTEM as DEFAULT_SYSTEM
except ImportError:
    DEFAULT_SYSTEM = """write 3 short paragraphs. lowercase except $SYMBOLS. no labels. output: <post>"""

log = logging.getLogger(__name__)

# Track request timestamps per provider
_request_history = defaultdict(list)


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
    """Return list of provider names sorted by weight (highest first)"""
    providers = []
    for provider, cfg in LLM_PROVIDERS.items():
        if cfg.get("enabled", True):
            providers.append((provider, cfg.get("weight", 1)))
    providers.sort(key=lambda x: x[1], reverse=True)
    return [p[0] for p in providers]


def _record_request(provider_name: str):
    _request_history[provider_name].append(time.time())


def _call_provider(provider: str, user_prompt: str, system_prompt: str, 
                   max_retries: int, backoff: int) -> tuple[str | None, str | None]:
    """
    Call a specific provider.
    Returns (content, error_message)
    """
    cfg = LLM_PROVIDERS.get(provider)
    if not cfg:
        return None, f"Unknown provider: {provider}"
    
    # Check rate limit
    if not _can_send(provider):
        return None, f"Rate limit exceeded for {provider}"
    
    headers = {
        "Authorization": f"Bearer {cfg['api_key']}",
        "Content-Type": "application/json"
    }
    if provider == "openrouter":
        headers["HTTP-Referer"] = "https://localhost"
        headers["X-Title"] = "Crypto Post Generator"
    
    payload = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "max_tokens": cfg["max_tokens"],
        "temperature": cfg["temperature"],
        "top_p": cfg["top_p"],
    }
    
    current_backoff = backoff
    
    for attempt in range(1, max_retries + 1):
        try:
            print(f"  🔄 LLM ({provider}) attempt {attempt}/{max_retries}...")
            response = requests.post(
                cfg["api_url"], 
                headers=headers, 
                json=payload, 
                timeout=(30, 120)
            )
            
            if response.status_code == 200:
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                import re
                content = re.sub(r'\$([A-Z]+)[\'"]?s\b', r'$\1', content)

                if content and isinstance(content, str):
                    content = content.strip()
        
                    # Strip thinking tags (DeepSeek specific)
                    if "<think>" in content:
                        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
                    # Extract post content
                    if "<post>" in content:
                        content = content.split("<post>")[-1].split("</post>")[0].strip()
        
                    if len(content) >= 30:
                        _record_request(provider)
                        return content, None
                    else:
                        print(f"  ⚠️ Content too short ({len(content)} chars)")
                else:
                    print(f"  ⚠️ Invalid content type")
        
            elif response.status_code == 429:
                # Rate limit - wait longer
                wait_time = min(60, (attempt ** 2) * 5)  # 5, 20, 45, max 60
                print(f"  ⚠️ Rate limit (429), waiting {wait_time}s before retry...")
                time.sleep(wait_time)
                # Don't consume retry count for rate limit
                current_backoff = wait_time + backoff
                continue
    
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
             use_cache: bool = True) -> str | None:
    """
    Generate content with priority fallback.
    Higher weight = higher priority (tried first).
    Falls back to next provider if current fails.
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
        
        content, error = _call_provider(provider, user_prompt, system_prompt, max_retries, backoff)
        if content and use_cache:
            cache_set(user_prompt, system_prompt, cfg["model"], cfg["temperature"], content)
        return content
    
    # Priority fallback: try providers in weight order
    priority_list = _get_providers_by_priority()
    attempted = []
    
    for prov in priority_list:
        attempted.append(prov)
        print(f"  🎯 Trying {prov} (priority {len(attempted)}/{len(priority_list)})...")
        
        content, error = _call_provider(prov, user_prompt, system_prompt, max_retries, backoff)
        
        if content:
            # Save to cache with provider-specific key
            if use_cache:
                cfg = LLM_PROVIDERS.get(prov)
                cache_set(user_prompt, system_prompt, cfg["model"], cfg["temperature"], content)
            return content
        
        print(f"  ⚠️ {prov} failed: {error}")
        print(f"  🔁 Falling back to next provider...")
        time.sleep(2)
    
    print(f"  ❌ All providers failed. Tried: {", ".join(attempted)}")
    return None