# processors/dedupe.py
import time
import json
import os
import logging
from typing import Dict, Optional
from config import DEDUP_FILE

log = logging.getLogger(__name__)

# Cooldown dalam detik untuk token yang sama (terlepas dari kategori)
TOKEN_COOLDOWN_SECONDS = 43200  # 12 jam

# TTL berbeda per kategori (dalam jam)
CATEGORY_TTL = {
    "HOT": 24,
    "GAINERS": 24,
    "LOSERS": 24,
    "ALPHA": 48,
}
DEFAULT_TTL = 24


class TokenMemory:
    def __init__(self):
        self.posted: Dict[str, Dict] = {}          # key: symbol|category
        self.last_post_time: Dict[str, float] = {} # key: symbol uppercase
        self.storage_file = DEDUP_FILE
        self._load()
    
    def _make_key(self, symbol: str, category: str) -> str:
        return f"{symbol.upper()}|{category}"
    
    def _get_ttl(self, category: str) -> int:
        """Get TTL in hours for specific category"""
        return CATEGORY_TTL.get(category, DEFAULT_TTL)
    
    def is_duplicate(self, symbol: str, category: str) -> bool:
        symbol_upper = symbol.upper()
        now = time.time()
        
        # 1. Cooldown check (global per token, semua kategori)
        last_time = self.last_post_time.get(symbol_upper, 0)
        if now - last_time < TOKEN_COOLDOWN_SECONDS:
            log.debug(f"Cooldown: {symbol} posted {now - last_time:.0f}s ago (limit {TOKEN_COOLDOWN_SECONDS}s)")
            return True
        
        # 2. Category-specific check (token di kategori yang sama)
        key = self._make_key(symbol, category)
        if key in self.posted:
            age = (now - self.posted[key]["timestamp"]) / 3600
            ttl = self._get_ttl(category)
            if age < ttl:
                log.debug(f"Category duplicate: {symbol} in {category} posted {age:.1f}h ago (TTL {ttl}h)")
                return True
        
        return False
    
    def mark_posted(self, symbol: str, category: str):
        now = time.time()
        symbol_upper = symbol.upper()
        
        # Update last_post_time untuk cooldown (global)
        self.last_post_time[symbol_upper] = now
        
        # Update posted untuk dedup per kategori
        key = self._make_key(symbol, category)
        self.posted[key] = {
            "symbol": symbol,
            "category": category,
            "timestamp": now
        }
        self._save()
    
    def clear_old(self):
        now = time.time()
        # Hapus entry posted yang sudah melebihi TTL kategorinya
        to_delete = []
        for key, entry in self.posted.items():
            category = entry.get("category", "HOT")
            ttl = self._get_ttl(category)
            age = (now - entry["timestamp"]) / 3600
            if age >= ttl:
                to_delete.append(key)
        
        for k in to_delete:
            del self.posted[k]
        
        # Hapus last_post_time yang sudah lebih dari cooldown (biar ga numpuk)
        old_tokens = [t for t, ts in self.last_post_time.items() if now - ts > TOKEN_COOLDOWN_SECONDS]
        for t in old_tokens:
            del self.last_post_time[t]
        
        if to_delete or old_tokens:
            self._save()
            log.debug(f"Cleaned: {len(to_delete)} category entries, {len(old_tokens)} cooldown entries")
    
    def _load(self):
        """Load dedup cache from disk with proper error handling"""
        if not os.path.exists(self.storage_file):
            self.posted = {}
            self.last_post_time = {}
            return
        
        try:
            with open(self.storage_file, 'r') as f:
                data = json.load(f)
                # Handle new format (dict with posted and last_post_time)
                if isinstance(data, dict) and "posted" in data and "last_post_time" in data:
                    self.posted = data.get("posted", {})
                    self.last_post_time = data.get("last_post_time", {})
                else:
                    # Old format, migrate
                    self.posted = data if isinstance(data, dict) else {}
                    self.last_post_time = {}
                    self._save()
        except FileNotFoundError:
            self.posted = {}
            self.last_post_time = {}
        except json.JSONDecodeError as e:
            log.error(f"Dedup file corrupted: {e}")
            if os.path.exists(self.storage_file):
                try:
                    os.rename(self.storage_file, f"{self.storage_file}.bak")
                    log.info(f"Backed up corrupted file")
                except:
                    pass
            self.posted = {}
            self.last_post_time = {}
        except Exception as e:
            log.exception(f"Unexpected error loading dedup file: {e}")
            self.posted = {}
            self.last_post_time = {}
    
    def _save(self):
        """Save dedup cache to disk"""
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
    
    def get_stats(self) -> dict:
        """Return statistics for debugging"""
        return {
            "posted_entries": len(self.posted),
            "cooldown_entries": len(self.last_post_time),
            "cooldown_seconds": TOKEN_COOLDOWN_SECONDS,
            "category_ttl": CATEGORY_TTL,
        }


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


def is_duplicate(symbol: str, category: str) -> bool:
    return get_memory().is_duplicate(symbol, category)


def mark_posted(symbol: str, category: str):
    get_memory().mark_posted(symbol, category)


def clear_old_entries():
    get_memory().clear_old()


def get_stats():
    return get_memory().get_stats()
