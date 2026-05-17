# storage/cache.py
import json
import os
import hashlib
import time
from typing import Optional
from config import LLM_CACHE_FILE

CACHE_FILE = LLM_CACHE_FILE
CACHE_TTL_SECONDS = 3600  # 1 jam

_cache: dict = {}


def _load_cache():
    global _cache
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r') as f:
                _cache = json.load(f)
        except:
            _cache = {}
    else:
        _cache = {}


def _save_cache():
    try:
        with open(CACHE_FILE, 'w') as f:
            json.dump(_cache, f, indent=2)
    except:
        pass


def _make_key(user_prompt: str, system_prompt: str, model: str, temperature: float) -> str:
    """Create hash key from all cache-relevant parameters"""
    content = f"{user_prompt}|{system_prompt}|{model}|{temperature}"
    return hashlib.md5(content.encode()).hexdigest()


def get(user_prompt: str, system_prompt: str, model: str, temperature: float) -> Optional[str]:
    """Get cached response if still valid"""
    if not _cache:
        _load_cache()
    
    key = _make_key(user_prompt, system_prompt, model, temperature)
    entry = _cache.get(key)
    
    if entry:
        age = time.time() - entry.get("timestamp", 0)
        if age < CACHE_TTL_SECONDS:
            print(f"  💾 Cache HIT (age: {age:.0f}s)")
            return entry.get("response")
        else:
            # Expired, remove
            del _cache[key]
            _save_cache()
    
    return None


def set(user_prompt: str, system_prompt: str, model: str, temperature: float, response: str):
    """Store response in cache"""
    if not _cache:
        _load_cache()
    
    key = _make_key(user_prompt, system_prompt, model, temperature)
    _cache[key] = {
        "response": response,
        "timestamp": time.time()
    }
    _save_cache()


def clear():
    """Clear entire cache"""
    global _cache
    _cache = {}
    _save_cache()
    print("  🗑️ Cache cleared")


def stats() -> dict:
    """Return cache statistics"""
    if not _cache:
        _load_cache()
    return {
        "size": len(_cache),
        "file": CACHE_FILE,
        "ttl_seconds": CACHE_TTL_SECONDS
    }
