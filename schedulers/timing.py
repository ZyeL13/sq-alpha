import random
from datetime import datetime

def get_current_session() -> str:
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

SESSION_BASE_DELAYS = {
    "asia": 600,
    "europe": 600,
    "overlap": 600,
    "us_late": 600,
    "night": 600,
}

def get_post_delay() -> int:
    session = get_current_session()
    base = SESSION_BASE_DELAYS.get(session, 600)
    jitter = random.uniform(0.9, 1.1)
    delay = int(base * jitter)
    return max(540, min(660, delay))

def get_weighted_delay() -> int:
    return get_post_delay()
