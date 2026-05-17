# llm.py — Multi-provider with auto routing, rate limiting, and cache
import time
import random
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
    # Clean old timestamps
    _request_history[provider_name] = [t for t in _request_history[provider_name] if now - t < 60]
    return len(_request_history[provider_name]) < rpm


def _select_provider(category: str = None) -> str | None:
    """Select best available provider based on category preference and rate limit"""
    # Try preferred provider for category first
    if category and category in CATEGORY_PREFERRED:
        preferred = CATEGORY_PREFERRED[category]
        if _can_send(preferred):
            return preferred
    
    # Fallback: any enabled provider that can send
    candidates = [p for p, cfg in LLM_PROVIDERS.items() 
                  if cfg.get("enabled", True) and _can_send(p)]
    if not candidates:
        return None
    
    # Weighted random selection
    weights = [LLM_PROVIDERS[p].get("weight", 1) for p in candidates]
    return random.choices(candidates, weights=weights, k=1)[0]


def _record_request(provider_name: str):
    _request_history[provider_name].append(time.time())


def generate(user_prompt: str,
             system_prompt: str = None,
             provider: str = None,
             category: str = None,
             max_retries: int = 2,
             backoff: int = 10,
             use_cache: bool = True) -> str | None:
    
    if system_prompt is None:
        system_prompt = DEFAULT_SYSTEM
    
    # Select provider if not specified
    if provider is None:
        provider = _select_provider(category)
        if not provider:
            print(f"  ⚠️ No provider available for {category}, waiting...")
            time.sleep(15)
            return generate(user_prompt, system_prompt, category=category, 
                          max_retries=max_retries, backoff=backoff, use_cache=use_cache)
    
    cfg = LLM_PROVIDERS.get(provider)
    if not cfg:
        print(f"  ❌ Unknown provider: {provider}")
        return None

    # Check cache BEFORE request
    if use_cache:
        cache_key_params = (user_prompt, system_prompt, cfg["model"], cfg["temperature"])
        cached = cache_get(*cache_key_params)
        if cached:
            return cached

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
                timeout=(15, 90)
            )
            
            if response.status_code == 200:
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                
                if content and isinstance(content, str):
                    content = content.strip()
                    if "<post>" in content:
                        content = content.split("<post>")[-1].split("</post>")[0].strip()
                    if len(content) >= 30:
                        _record_request(provider)
                        # Save to cache
                        if use_cache:
                            cache_set(user_prompt, system_prompt, cfg["model"], cfg["temperature"], content)
                        return content
                    else:
                        print(f"  ⚠️ Content too short ({len(content)} chars)")
                else:
                    print(f"  ⚠️ Invalid content type")
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
    
    return None
