# storage/post_counter.py
import json
import os
from datetime import datetime, timedelta
from config import POST_COUNTER_FILE, DAILY_POST_LIMIT

# Reset hour in WIB (GMT+7)
RESET_HOUR = 7  # jam 7 pagi

def _get_reset_time() -> datetime:
    """Get today's reset time (7 AM WIB)"""
    now = datetime.now()
    reset = datetime(now.year, now.month, now.day, RESET_HOUR, 0, 0)
    if now >= reset:
        return reset
    else:
        return reset - timedelta(days=1)

def _get_today_key() -> str:
    """Get key based on reset time (not calendar day)"""
    reset_time = _get_reset_time()
    return reset_time.strftime("%Y-%m-%d_%H:%M")

def get_today_posts() -> int:
    if not os.path.exists(POST_COUNTER_FILE):
        return 0
    try:
        with open(POST_COUNTER_FILE, 'r') as f:
            data = json.load(f)
            if data.get("reset_key") == _get_today_key():
                return data.get("square_count", 0)
    except:
        pass
    return 0

def increment_post_counter():
    today_key = _get_today_key()
    current = get_today_posts()
    
    data = {
        "reset_key": today_key,
        "square_count": current + 1,
        "last_updated": datetime.now().isoformat()
    }
    
    os.makedirs(os.path.dirname(POST_COUNTER_FILE), exist_ok=True)
    with open(POST_COUNTER_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def can_post() -> bool:
    return get_today_posts() < DAILY_POST_LIMIT

def get_seconds_until_reset() -> int:
    """Seconds until next reset (7 AM WIB)"""
    from datetime import datetime, timedelta
    now = datetime.now()
    reset = datetime(now.year, now.month, now.day, 7, 0, 0)  # 7 AM
    if now >= reset:
        reset += timedelta(days=1)
    return int((reset - now).total_seconds())
