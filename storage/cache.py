# storage/cache.py
import json
import os
import hashlib
import time
from typing import Optional
from config import LLM_CACHE_FILE

CACHE_FILE = LLM_CACHE_FILE
CACHE_TTL_SECONDS = 3600  # 1 jam

# Pola response yang tidak valid (debug/proses gagal)
RESPONSE_BLOCKLIST = [
    "Okay, let's see",
    "The user wants",
    "I need to check",
    "Wait, the problem says",
    "Let me try",
    "Hmm, let me think",
    "This is a problem",
    "I should be careful",
    "Let me draft",
    "The user says",
    "Let me tackle this",
    "First, I need to",
    "Looking at the rules",
    "Wait, the instruction",
    "Let me read",
    "Let me start",
    "I think",
    "Let me analyze",
    "Let me break this down",
    "Let me rephrase",
    "Let me check",
    "I'm going to",
    "I'll write",
    "Let me structure",
    "I need to mention",
    "Let me think about",
    "I can write",
    "Let me try again",
    "Actually,",
    "Hmm",
    "Wait,",
    "I should be",
    "Let me make",
    "I'll keep",
    "Let me look",
    "Let me see what",
    "I don't have",
    "I'll use",
    "Let me pick",
    "I'm not sure",
]

# Minimal panjang response yang valid
MIN_RESPONSE_LENGTH = 50

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


def is_valid_response(response: str) -> bool:
    """Check if response looks like a valid social post (not debugging/failed)"""
    if not response or not isinstance(response, str):
        return False
    
    if len(response) < MIN_RESPONSE_LENGTH:
        return False
    
    # Untuk response panjang (>1000 chars), langsung anggap valid
    # Karena kemungkinan besar itu post lengkap, bukan reasoning leak
    if len(response) > 1000:
        return True
    
    # Cek pola debugging (hanya untuk response pendek)
    response_lower = response.lower()
    for phrase in RESPONSE_BLOCKLIST:
        if phrase.lower() in response_lower:
            return False
    
    # Response valid harus mengandung $SYMBOL (ciri post crypto)
    if '$' not in response:
        return False
    
    # Cek apakah response berisi tag HTML atau markdown berlebihan
    if response.count('```') > 2:
        return False
    
    return True


def get(user_prompt: str, system_prompt: str, model: str, temperature: float) -> Optional[str]:
    """Get cached response if still valid"""
    if not _cache:
        _load_cache()
    
    key = _make_key(user_prompt, system_prompt, model, temperature)
    entry = _cache.get(key)
    
    if entry:
        age = time.time() - entry.get("timestamp", 0)
        if age < CACHE_TTL_SECONDS:
            response = entry.get("response")
            # Validasi response saat mengambil dari cache
            if is_valid_response(response):
                print(f"  💾 Cache HIT (age: {age:.0f}s)")
                return response
            else:
                # Response di cache tidak valid, hapus
                print(f"  ⚠️ Cache invalid, removing...")
                del _cache[key]
                _save_cache()
        else:
            # Expired, remove
            del _cache[key]
            _save_cache()
    
    return None


def set(user_prompt: str, system_prompt: str, model: str, temperature: float, response: str):
    """Store response in cache (only if valid)"""
    if not is_valid_response(response):
        print(f"  ⚠️ Cache SKIP: invalid response (length={len(response)}, has_symbol={'$' in response})")
        return
    
    if not _cache:
        _load_cache()
    
    key = _make_key(user_prompt, system_prompt, model, temperature)
    _cache[key] = {
        "response": response,
        "timestamp": time.time()
    }
    _save_cache()
    print(f"  💾 Cached (size: {len(_cache)} entries)")


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
    
    # Hitung response valid di cache
    valid_count = 0
    for entry in _cache.values():
        if is_valid_response(entry.get("response", "")):
            valid_count += 1
    
    return {
        "size": len(_cache),
        "valid_count": valid_count,
        "file": CACHE_FILE,
        "ttl_seconds": CACHE_TTL_SECONDS
    }


def cleanup_invalid():
    """Remove invalid responses from cache"""
    if not _cache:
        _load_cache()
    
    to_remove = []
    for key, entry in _cache.items():
        if not is_valid_response(entry.get("response", "")):
            to_remove.append(key)
    
    for key in to_remove:
        del _cache[key]
    
    if to_remove:
        _save_cache()
        print(f"  🧹 Removed {len(to_remove)} invalid entries from cache")
    
    return len(to_remove)
