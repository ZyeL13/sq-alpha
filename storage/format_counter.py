# storage/format_counter.py — per-format daily counts (V3 Phase 2).
#
# Mirrors storage/post_counter.py: a small JSON file in cache/ (a
# Docker volume, so counts survive restarts), keyed by the same
# 07:00 WIB reset window. Counts are incremented when a post of
# that format is SCHEDULED — scheduling is the commitment point.
# Queue rows are deleted on claim, so queue-only counting would
# undercount; a scheduled post that later gets stale-dropped still
# consumed its slot, which is acceptable and simpler.
#
# Only "image" and "longform" are counted; "short" is the default
# and is bounded by DAILY_POST_LIMIT instead. A stale reset_key
# reads as zero for both formats, so no explicit reset call is
# needed at the 07:00 rollover.
import json
import os
import threading
from datetime import datetime, timedelta

from config import FORMAT_COUNTER_FILE, WIB
from storage.post_counter import RESET_HOUR

_lock = threading.Lock()

_FORMATS = ("image", "longform")


def _get_today_key() -> str:
    """Same reset-window key as post_counter: the 07:00 WIB reset
    that started the current posting day. RESET_HOUR stays the
    single source of truth in storage/post_counter.py."""
    now = datetime.now(WIB)
    reset = datetime(now.year, now.month, now.day, RESET_HOUR, 0, 0, tzinfo=WIB)
    if now < reset:
        reset -= timedelta(days=1)
    return reset.strftime("%Y-%m-%d_%H:%M")


def get_format_counts() -> dict:
    """Today's scheduled per-format counts: {"image": n, "longform": n}."""
    counts = {fmt: 0 for fmt in _FORMATS}
    if not os.path.exists(FORMAT_COUNTER_FILE):
        return counts
    try:
        with open(FORMAT_COUNTER_FILE, "r") as f:
            data = json.load(f)
        if data.get("reset_key") == _get_today_key():
            for fmt in _FORMATS:
                counts[fmt] = int(data.get(fmt, 0) or 0)
    except Exception:
        pass
    return counts


def increment_format_count(fmt: str) -> None:
    """Record one scheduled post of format fmt. No-op for "short"
    and unknown formats. The lock serialises the read-modify-write
    across processor threads (today there is one, but the cost of
    the lock is nil)."""
    if fmt not in _FORMATS:
        return
    with _lock:
        counts = get_format_counts()
        counts[fmt] += 1
        data = {
            "reset_key": _get_today_key(),
            "last_updated": datetime.now(WIB).isoformat(),
            **counts,
        }
        os.makedirs(os.path.dirname(FORMAT_COUNTER_FILE), exist_ok=True)
        with open(FORMAT_COUNTER_FILE, "w") as f:
            json.dump(data, f, indent=2)
