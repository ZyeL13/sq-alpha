# data/dedup.py — Dedup logic
# Namespace A: price events — in-memory set, reset per run_all_once()
# Namespace B: news events  — file-based JSON, TTL-based (DUPLICATE_TTL_HOURS)
#
# Moved from: square_auto.py (_used_tokens)
#             berita.py      (load_seen, save_seen, make_hash, is_duplicate, should_skip)

import json
import hashlib
import logging
import os
from datetime import datetime, timedelta

from config import DUPLICATE_TTL_HOURS, DEDUP_FILE

log = logging.getLogger(__name__)


# ─── NAMESPACE A: PRICE DEDUP (in-memory, per-run) ────────────────────────────

_used_tokens: set = set()


def reset_used():
    """Call at the start of each run_all_once() to clear the session token lock."""
    global _used_tokens
    _used_tokens = set()


def mark_used(symbol: str):
    _used_tokens.add(symbol)


def is_used(symbol: str) -> bool:
    return symbol in _used_tokens


# ─── NAMESPACE B: NEWS DEDUP (file-based, TTL) ────────────────────────────────

def load_seen() -> dict:
    """Load seen news hashes from disk. Returns {hash: datetime}."""
    if os.path.exists(DEDUP_FILE):
        try:
            with open(DEDUP_FILE, "r") as f:
                data = json.load(f)
                return {k: datetime.fromisoformat(v) for k, v in data.items()}
        except Exception as e:
            log.warning(f"load_seen failed: {e}")
    return {}


def save_seen(seen: dict):
    """Persist seen dict to disk. Keeps last 500 entries."""
    items = list(seen.items())[-500:]
    data  = {k: v.isoformat() for k, v in items}
    os.makedirs(os.path.dirname(DEDUP_FILE), exist_ok=True)
    with open(DEDUP_FILE, "w") as f:
        json.dump(data, f)


def make_hash(title: str, link: str) -> str:
    return hashlib.md5((title + link).strip().lower().encode()).hexdigest()


def is_duplicate(hash_id: str, seen: dict) -> bool:
    if hash_id not in seen:
        return False
    return datetime.now() - seen[hash_id] <= timedelta(hours=DUPLICATE_TTL_HOURS)


def should_skip(title: str, link: str, seen: dict) -> bool:
    """Returns True if duplicate (within TTL). Marks as seen if not."""
    hash_id = make_hash(title, link)
    if is_duplicate(hash_id, seen):
        return True
    seen[hash_id] = datetime.now()
    return False

