# processors/dedupe.py
import time
import json
import os
import logging
from typing import Dict, Optional
from config import DEDUP_FILE, DEDUP_TTL_HOURS


log = logging.getLogger(__name__)

class TokenMemory:
    def __init__(self):
        self.posted: Dict[str, Dict] = {}
        self.storage_file = DEDUP_FILE
        self.ttl_hours = DEDUP_TTL_HOURS
        self._load()
    
    def _make_key(self, symbol: str, category: str) -> str:
        return f"{symbol.upper()}|{category}"
    
    def is_duplicate(self, symbol: str, category: str) -> bool:
        key = self._make_key(symbol, category)
        if key not in self.posted:
            return False
        age = (time.time() - self.posted[key]["timestamp"]) / 3600
        return age < self.ttl_hours
    
    def mark_posted(self, symbol: str, category: str):
        key = self._make_key(symbol, category)
        self.posted[key] = {"symbol": symbol, "category": category, "timestamp": time.time()}
        self._save()
    
    def clear_old(self):
        now = time.time()
        cutoff = now - (self.ttl_hours * 3600)
        to_delete = [k for k, v in self.posted.items() if v["timestamp"] < cutoff]
        for k in to_delete:
            del self.posted[k]
        if to_delete:
            self._save()
    
    def _load(self):
        """Load dedup cache from disk with proper error handling"""
        if not os.path.exists(self.storage_file):
            self.posted = {}
            return
        
        try:
            with open(self.storage_file, 'r') as f:
                self.posted = json.load(f)
        except FileNotFoundError:
            log.warning(f"Dedup file not found: {self.storage_file}")
            self.posted = {}
        except json.JSONDecodeError as e:
            log.error(f"Dedup file corrupted (JSON decode error): {e}")
            # Backup corrupted file
            if os.path.exists(self.storage_file):
                backup = f"{self.storage_file}.bak"
                try:
                    os.rename(self.storage_file, backup)
                    log.info(f"Backed up corrupted dedup file to {backup}")
                except:
                    pass
            self.posted = {}
        except PermissionError as e:
            log.error(f"Permission denied reading dedup file: {e}")
            self.posted = {}
        except Exception as e:
            log.exception(f"Unexpected error loading dedup file: {e}")
            self.posted = {}
    
    def _save(self):
        """Save dedup cache to disk with proper error handling"""
        try:
            # Ensure directory exists
            dir_path = os.path.dirname(self.storage_file)
            if dir_path:
                os.makedirs(dir_path, exist_ok=True)
            
            # Write to temporary file first, then rename
            temp_file = f"{self.storage_file}.tmp"
            with open(temp_file, 'w') as f:
                json.dump(self.posted, f, indent=2)
            
            # Atomic rename (works on Unix)
            os.replace(temp_file, self.storage_file)
            
        except IOError as e:
            log.error(f"IOError saving dedup cache: {e}")
        except PermissionError as e:
            log.error(f"Permission denied saving dedup cache: {e}")
        except Exception as e:
            log.exception(f"Unexpected error saving dedup cache: {e}")


_memory = None
_lock = None  # Will be initialized with threading.Lock when needed

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
