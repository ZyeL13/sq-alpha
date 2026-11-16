# storage/memory_store.py — durable per-symbol post memory (JIT path).
#
# The reaction openers (dejavu, smug) need to know what the bot last
# wrote about a token: when, which way it was moving, and the post's
# first line. The existing storage/post_history.py is in-memory only
# (last 20 contents, no timestamps, lost on restart) — unusable for
# this. This store is a small JSON file in cache/ (a Docker volume),
# written at schedule time for the winning draft only.
#
# Patterns follow storage/news_dedup.py: atomic write via tmp file +
# os.replace, corrupt file moved to .bak, every operation best-effort
# (a missing/corrupt/unwritable file yields empty memory, never a
# crash). Entries older than 30 days are pruned lazily on write.
import json
import logging
import os
import threading
import time
from datetime import datetime

from config import POST_MEMORY_FILE, WIB

log = logging.getLogger(__name__)

MEMORY_TTL_DAYS = 30
MAX_FIRST_LINE_CHARS = 120

# Tests point this at a tmp file; production uses the config path.
MEMORY_FILE: str = POST_MEMORY_FILE

_lock = threading.Lock()


def _load() -> dict:
    """Whole store as {SYMBOL: record}. Empty on any failure; a
    corrupt file is moved aside so the next write starts clean."""
    try:
        if not os.path.exists(MEMORY_FILE):
            return {}
        with open(MEMORY_FILE, "r") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError as e:
        log.error(f"Post memory file corrupted: {e}")
        try:
            os.rename(MEMORY_FILE, f"{MEMORY_FILE}.bak")
        except OSError:
            pass
        return {}
    except Exception as e:
        log.exception(f"Unexpected error loading post memory: {e}")
        return {}


def _save(data: dict) -> None:
    """Atomic best-effort write. Callers hold _lock."""
    try:
        dir_path = os.path.dirname(MEMORY_FILE)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)
        temp_file = f"{MEMORY_FILE}.tmp"
        with open(temp_file, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(temp_file, MEMORY_FILE)
    except Exception as e:
        log.error(f"Failed to save post memory: {e}")


def get_memory(symbol: str) -> "dict | None":
    """Last post record for a symbol, or None. Never raises."""
    try:
        with _lock:
            return _load().get((symbol or "").upper())
    except Exception:
        return None


def record_memory(symbol: str, change: float, content: str,
                  now: "float | None" = None) -> None:
    """Record a scheduled post. The first line of the content is
    stored (single line, truncated); entries older than 30 days are
    pruned. Best-effort: never raises."""
    try:
        first_line = (content or "").split("\n")[0].strip()
        first_line = first_line[:MAX_FIRST_LINE_CHARS]
        try:
            change = float(change)
        except (TypeError, ValueError):
            change = 0.0
        direction = "up" if change > 0 else ("down" if change < 0 else "flat")
        now = time.time() if now is None else now
        with _lock:
            data = _load()
            cutoff = now - MEMORY_TTL_DAYS * 24 * 3600
            for key in [k for k, v in data.items()
                        if isinstance(v, dict)
                        and v.get("time", 0) < cutoff]:
                del data[key]
            data[(symbol or "").upper()] = {
                "time": now,
                "change": change,
                "direction": direction,
                "first_line": first_line,
            }
            _save(data)
    except Exception as e:
        log.error(f"Failed to record post memory: {e}")


def format_memory_block(record: "dict | None", symbol: str,
                        current_change: float) -> str:
    """The MEMORY block for the prompt, or "" without a record.

    Names the last post's date (WIB), its 24h change, and its first
    line, then the current change — all numbers from stored data or
    the live token, never invented.
    """
    if not record:
        return ""
    try:
        when = datetime.fromtimestamp(record.get("time", 0), tz=WIB)
        date = when.strftime("%d %b %Y")
        prev = float(record.get("change") or 0)
        current = float(current_change or 0)
        first_line = (record.get("first_line") or "").strip()
        block = (f"You last wrote about ${symbol} on {date} when it "
                 f"was {prev:+.1f}%")
        if first_line:
            block += f" ({first_line})"
        block += f". Now it is {current:+.1f}%."
        return block
    except Exception:
        return ""
