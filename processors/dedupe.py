# processors/dedupe.py
import time
import json
import os
from typing import Dict, Optional
from config import DEDUP_FILE

class TokenMemory:
    def __init__(self):
        self.posted: Dict[str, Dict] = {}
        self.storage_file = DEDUP_FILE
        self.ttl_hours = 12
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
        if os.path.exists(self.storage_file):
            try:
                with open(self.storage_file, 'r') as f:
                    self.posted = json.load(f)
            except:
                self.posted = {}
    
    def _save(self):
        try:
            os.makedirs(os.path.dirname(self.storage_file), exist_ok=True)
            with open(self.storage_file, 'w') as f:
                json.dump(self.posted, f, indent=2)
        except:
            pass

_memory = None
def get_memory():
    global _memory
    if _memory is None:
        _memory = TokenMemory()
    return _memory

def is_duplicate(symbol: str, category: str) -> bool:
    return get_memory().is_duplicate(symbol, category)

def mark_posted(symbol: str, category: str):
    get_memory().mark_posted(symbol, category)

def clear_old_entries():
    get_memory().clear_old()
