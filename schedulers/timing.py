# schedulers/timing.py
import os
import random
from datetime import datetime, timedelta

from config import WIB

# Experiment post window (14-day experiment charter): when the
# EXPERIMENT_POST_WINDOW env var holds a parseable "HH:MM-HH:MM"
# range (WIB), primary posts may only be scheduled/posted inside
# it; otherwise the window is OFF and all behaviour is byte-identical
# to today. Unparseable values (empty, wrong shape, out-of-range
# hours/minutes, start >= end) mean OFF, never a crash.
EXPERIMENT_WINDOW_ENV = "EXPERIMENT_POST_WINDOW"


def _parse_experiment_window():
    """Parse EXPERIMENT_POST_WINDOW into ((sh, sm), (eh, em)).

    Returns None when the env var is empty or unparseable. Overnight
    windows (start >= end) are not supported and parse as None.
    """
    raw = (os.environ.get(EXPERIMENT_WINDOW_ENV) or "").strip()
    if not raw or "-" not in raw:
        return None
    start_s, end_s = raw.split("-", 1)
    try:
        sh, sm = (int(p) for p in start_s.split(":"))
        eh, em = (int(p) for p in end_s.split(":"))
    except ValueError:
        return None
    if not (0 <= sh < 24 and 0 <= sm < 60 and 0 <= eh < 24 and 0 <= em < 60):
        return None
    if (sh, sm) >= (eh, em):
        return None
    return (sh, sm), (eh, em)


def experiment_window_active() -> bool:
    """True only when EXPERIMENT_POST_WINDOW parses as HH:MM-HH:MM."""
    return _parse_experiment_window() is not None


def _as_wib(now):
    """None -> now (WIB); naive -> assumed WIB; aware -> converted."""
    if now is None:
        return datetime.now(WIB)
    if now.tzinfo is None:
        return now.replace(tzinfo=WIB)
    return now.astimezone(WIB)


def _window_bounds(now):
    """(start, end) datetimes for `now`'s WIB day, or None."""
    parsed = _parse_experiment_window()
    if parsed is None:
        return None
    (sh, sm), (eh, em) = parsed
    start = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
    end = now.replace(hour=eh, minute=em, second=0, microsecond=0)
    return start, end


def in_experiment_window(now=None) -> bool:
    """True when `now` (default: now, WIB) falls inside the window.

    The window end is exclusive: at exactly the end time the window
    has closed. False when the window is inactive.
    """
    now = _as_wib(now)
    bounds = _window_bounds(now)
    if bounds is None:
        return False
    start, end = bounds
    return start <= now < end


def next_experiment_window_start(now=None) -> datetime:
    """The next window start at/after `now` (WIB-aware).

    Today's start when `now` is before it, else tomorrow's start.
    Callers only use this when the window is active; with no window
    configured it returns `now` unchanged.
    """
    now = _as_wib(now)
    bounds = _window_bounds(now)
    if bounds is None:
        return now
    start, _end = bounds
    if now < start:
        return start
    return start + timedelta(days=1)


def clamp_to_experiment_window(epoch_seconds) -> float:
    """Clamp a scheduled epoch time into the experiment window (WIB).

    Before today's window start -> today's start; after the window
    end -> tomorrow's start; inside -> unchanged. No-op when the
    window is inactive.
    """
    if _parse_experiment_window() is None:
        return epoch_seconds
    moment = datetime.fromtimestamp(epoch_seconds, tz=WIB)
    start, end = _window_bounds(moment)
    if moment < start:
        return start.timestamp()
    if moment >= end:
        return (start + timedelta(days=1)).timestamp()
    return epoch_seconds

# WIB (UTC+7)
def get_current_session() -> str:
    """Return current trading session based on WIB time"""
    hour = datetime.now(WIB).hour
    if 7 <= hour < 12:
        return "asia"
    elif 12 <= hour < 17:
        return "europe"
    elif 17 <= hour < 21:
        return "overlap"
    elif 21 <= hour < 24:
        return "us_late"
    else:
        return "night"

# Base delays in seconds. Posts are chained off the last scheduled post
# (orchestrator: scheduled_time = last_time + get_post_delay()), so this
# is also the minimum gap between consecutive posts: 75-90 minutes.
# 10 posts/day x ~80 min gaps fits a 07:30-23:30 WIB window.
SESSION_BASE_DELAYS = {
    "asia": 4800,     # 80 menit
    "europe": 4800,   # 80 menit
    "overlap": 4800,  # 80 menit
    "us_late": 4800,  # 80 menit
    "night": 4800,    # 80 menit
}

MIN_POST_GAP_SECONDS = 4500  # 75 menit — jangan di bawah ini (anti-spam)
MAX_POST_GAP_SECONDS = 5400  # 90 menit

def get_post_delay() -> int:
    """Get randomized delay based on current session"""
    session = get_current_session()
    base = SESSION_BASE_DELAYS.get(session, 4800)
    jitter = random.uniform(0.85, 1.15)  # ±15% jitter
    delay = int(base * jitter)
    return max(MIN_POST_GAP_SECONDS, min(MAX_POST_GAP_SECONDS, delay))

def get_dynamic_post_limit() -> int:
    """Get post limit based on current session (for soft limiting)"""
    session = get_current_session()
    limits = {
        "asia": 20,
        "europe": 25,
        "overlap": 30,
        "us_late": 15,
        "night": 10,
    }
    return limits.get(session, 20)

def get_weighted_delay() -> int:
    """Alias for get_post_delay"""
    return get_post_delay()
