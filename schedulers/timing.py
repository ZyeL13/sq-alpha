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
    "asia": 450,
    "europe": 450,
    "overlap": 450,
    "us_late": 450,
    "night": 450,
}

def get_post_delay() -> int:
    session = get_current_session()
    base = SESSION_BASE_DELAYS.get(session, 450)
    jitter = random.uniform(0.9, 1.1)
    delay = int(base * jitter)
    return max(390, min(510, delay))

def get_weighted_delay() -> int:
    return get_post_delay()
