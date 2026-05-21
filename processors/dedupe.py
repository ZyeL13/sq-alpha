# processors/dedupe.py
import time
import json
import os
import logging
import hashlib
from typing import Dict, Optional, List, Tuple
from config import DEDUP_FILE

log = logging.getLogger(__name__)

# ========== COOLDOWN CONFIG ==========
# Market cap tiers (in USD)
MARKET_CAP_TIERS = [
    (10_000_000_000, 4 * 3600),   # > $10B → 4 jam
    (1_000_000_000, 8 * 3600),    # > $1B → 8 jam
    (0, 24 * 3600),                # default → 24 jam
]

# Specific token overrides
TOKEN_COOLDOWN_OVERRIDES = {
    "BTC": 4 * 3600,
    "ETH": 4 * 3600,
    "SOL": 6 * 3600,
    "BNB": 6 * 3600,
    "XRP": 8 * 3600,
    "DOGE": 8 * 3600,
}

# Similarity threshold
SIMILARITY_THRESHOLD = 0.65
DAILY_POST_TARGET = 70  # target post per hari (bukan limit hard)


def get_cooldown_seconds(symbol: str, market_cap: float = 0) -> int:
    """Get cooldown based on market cap and symbol overrides"""
    symbol_upper = symbol.upper()
    
    # Check specific token override
    if symbol_upper in TOKEN_COOLDOWN_OVERRIDES:
        return TOKEN_COOLDOWN_OVERRIDES[symbol_upper]
    
    # Check market cap tiers
    for cap, cooldown in MARKET_CAP_TIERS:
        if market_cap >= cap:
            return cooldown
    
    return 24 * 3600  # default 24 jam


# Simple hook similarity cache
_recent_hooks: List[Tuple[str, float]] = []


def is_similar_hook(hook: str) -> bool:
    """Check if similar hook was used recently (last 6 hours)"""
    if not hook:
        return False
    
    hook_hash = hashlib.md5(hook.lower().encode()).hexdigest()[:16]
    now = time.time()
    
    # Clean old entries (>6 hours)
    global _recent_hooks
    _recent_hooks = [(h, ts) for h, ts in _recent_hooks if now - ts < 6 * 3600]
    
    # Check similarity
    for h, ts in _recent_hooks:
        if h == hook_hash:
            return True
    
    # Add to recent hooks
    _recent_hooks.append((hook_hash, now))
    return False


class TokenMemory:
    def __init__(self):
        self.posted: Dict[str, Dict] = {}           # key: symbol|category
        self.last_post_time: Dict[str, float] = {}  # key: symbol uppercase
        self.storage_file = DEDUP_FILE
        self._load()
    
    def _make_key(self, symbol: str, category: str) -> str:
        return f"{symbol.upper()}|{category}"
    
    def is_duplicate(self, symbol: str, category: str, market_cap: float = 0, hook: str = "") -> bool:
        symbol_upper = symbol.upper()
        now = time.time()
        cooldown = get_cooldown_seconds(symbol, market_cap)
        
        # 1. Hard cooldown (symbol-based)
        last_time = self.last_post_time.get(symbol_upper, 0)
        if now - last_time < cooldown:
            log.debug(f"Cooldown: {symbol} ({cooldown//3600}h)")
            return True
        
        # 2. Category-specific check (TTL 24 jam per kategori)
        key = self._make_key(symbol, category)
        if key in self.posted:
            age = (now - self.posted[key]["timestamp"]) / 3600
            if age < 24:  # 24 jam TTL per kategori
                log.debug(f"Category duplicate: {symbol} in {category}")
                return True
        
        # 3. Semantic similarity (hook-based)
        if hook and is_similar_hook(hook):
            log.debug(f"Similar hook detected: {hook[:50]}...")
            return True
        
        return False
    
    def mark_posted(self, symbol: str, category: str, hook: str = "", market_cap: float = 0):
        now = time.time()
        symbol_upper = symbol.upper()
        
        # Update last_post_time (global cooldown)
        self.last_post_time[symbol_upper] = now
        
        # Update category posting
        key = self._make_key(symbol, category)
        self.posted[key] = {
            "symbol": symbol,
            "category": category,
            "hook": hook[:100] if hook else "",
            "market_cap": market_cap,
            "timestamp": now
        }
        self._save()
    
    def should_post_today(self) -> bool:
        """Check if we've reached daily target (soft limit)"""
        now = time.time()
        today_posts = sum(1 for v in self.posted.values() 
                         if now - v.get("timestamp", 0) < 24 * 3600)
        return today_posts < DAILY_POST_TARGET
    
    def clear_old(self):
        now = time.time()
        cutoff_24h = now - (24 * 3600)
        
        # Clean posted entries older than 24h
        to_delete = [k for k, v in self.posted.items() if v["timestamp"] < cutoff_24h]
        for k in to_delete:
            del self.posted[k]
        
        # Clean last_post_time older than 7 days
        cutoff_7d = now - (7 * 24 * 3600)
        old_tokens = [t for t, ts in self.last_post_time.items() if ts < cutoff_7d]
        for t in old_tokens:
            del self.last_post_time[t]
        
        if to_delete or old_tokens:
            self._save()
            log.debug(f"Cleaned: {len(to_delete)} entries, {len(old_tokens)} tokens")
    
    def _load(self):
        if not os.path.exists(self.storage_file):
            self.posted = {}
            self.last_post_time = {}
            return
        
        try:
            with open(self.storage_file, 'r') as f:
                data = json.load(f)
                # Handle new format (dict with posted and last_post_time)
                if isinstance(data, dict) and "posted" in data:
                    self.posted = data.get("posted", {})
                    self.last_post_time = data.get("last_post_time", {})
                else:
                    # Old format, migrate
                    self.posted = data if isinstance(data, dict) else {}
                    self.last_post_time = {}
                    self._save()
        except json.JSONDecodeError as e:
            log.error(f"Dedup file corrupted: {e}")
            if os.path.exists(self.storage_file):
                try:
                    os.rename(self.storage_file, f"{self.storage_file}.bak")
                except:
                    pass
            self.posted = {}
            self.last_post_time = {}
        except Exception as e:
            log.exception(f"Unexpected error loading dedup file: {e}")
            self.posted = {}
            self.last_post_time = {}
    
    def _save(self):
        try:
            dir_path = os.path.dirname(self.storage_file)
            if dir_path:
                os.makedirs(dir_path, exist_ok=True)
            
            temp_file = f"{self.storage_file}.tmp"
            data = {
                "posted": self.posted,
                "last_post_time": self.last_post_time
            }
            with open(temp_file, 'w') as f:
                json.dump(data, f, indent=2)
            os.replace(temp_file, self.storage_file)
        except Exception as e:
            log.error(f"Failed to save dedup cache: {e}")


_memory = None
_lock = None


def _get_lock():
    global _lock
    if _lock is None:
        import threading
        _lock = threading.Lock()
    return _lock


def get_memory():
    global _memory
    if _memory is None:
        with _get_lock():
            if _memory is None:
                _memory = TokenMemory()
    return _memory


def is_duplicate(symbol: str, category: str, market_cap: float = 0, hook: str = "") -> bool:
    return get_memory().is_duplicate(symbol, category, market_cap, hook)


def mark_posted(symbol: str, category: str, hook: str = "", market_cap: float = 0):
    get_memory().mark_posted(symbol, category, hook, market_cap)


def clear_old_entries():
    get_memory().clear_old()


def should_post_today() -> bool:
    return get_memory().should_post_today()


def get_stats() -> dict:
    mem = get_memory()
    return {
        "posted_entries": len(mem.posted),
        "cooldown_entries": len(mem.last_post_time),
        "daily_target": DAILY_POST_TARGET,
        "today_posts": sum(1 for v in mem.posted.values() 
                          if time.time() - v.get("timestamp", 0) < 24 * 3600)
    }
