# schedulers/timing.py
import random
from datetime import datetime

from config import WIB

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
