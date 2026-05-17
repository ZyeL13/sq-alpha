# schedulers/timing.py
import time
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

# Weight: higher = more frequent posts
SESSION_WEIGHTS = {
    "asia": 30,      # 30% of posts
    "europe": 40,    # 40% of posts
    "overlap": 50,   # 50% of posts (most active)
    "us_late": 25,   # 25% of posts
    "night": 10,     # 10% of posts
}

# Base delays in seconds
SESSION_BASE_DELAYS = {
    "asia": 300,     # 5 menit
    "europe": 240,   # 4 menit
    "overlap": 180,  # 3 menit
    "us_late": 360,  # 6 menit
    "night": 600,    # 10 menit
}

def get_post_delay() -> int:
    session = get_current_session()
    base = SESSION_BASE_DELAYS.get(session, 90)
    jitter = random.uniform(0.7, 1.3)
    delay = int(base * jitter)
    return max(30, min(300, delay))
    # Add random jitter ±30%
    jitter = random.uniform(0.7, 1.3)
    delay = int(base * jitter)
    
    # Clamp between 30 and 300 seconds
    return max(30, min(300, delay))

def get_weighted_delay() -> int:
    """Alias for get_post_delay"""
    return get_post_delay()

def should_post_now() -> bool:
    """
    Probabilistic check based on session weight.
    Returns True/False based on whether we should post now.
    """
    session = get_current_session()
    weight = SESSION_WEIGHTS.get(session, 30)
    # Convert weight to probability (max 70% during overlap)
    probability = min(0.7, weight / 100)
    return random.random() < probability
