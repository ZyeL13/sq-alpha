# schedulers/timing.py
import random
from datetime import datetime

# WIB (UTC+7)
def get_current_session() -> str:
    """Return current trading session based on WIB time"""
    hour = datetime.now().hour
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

# Base delays in seconds
SESSION_BASE_DELAYS = {
    "asia": 600,     # 10 menit
    "europe": 600,   # 10 menit
    "overlap": 600,  # 10 menit
    "us_late": 600,  # 10 menit
    "night": 600,    # 10 menit
}

def get_post_delay() -> int:
    """Get randomized delay based on current session"""
    session = get_current_session()
    base = SESSION_BASE_DELAYS.get(session, 600)
    jitter = random.uniform(0.85, 1.15)  # ±15% jitter
    delay = int(base * jitter)
    return max(450, min(750, delay))  # between 450-750 seconds

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
