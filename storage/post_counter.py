# storage/post_counter.py
import json
import os
from datetime import datetime
from config import POST_COUNTER_FILE, DAILY_POST_LIMIT

def _get_today():
    return datetime.now().strftime("%Y-%m-%d")

def get_today_posts() -> int:
    """Get number of Square posts made today"""
    if not os.path.exists(POST_COUNTER_FILE):
        return 0
    try:
        with open(POST_COUNTER_FILE, 'r') as f:
            data = json.load(f)
            if data.get("date") == _get_today():
                return data.get("square_count", 0)  # renamed for clarity
    except:
        pass
    return 0

def increment_post_counter():
    """Increment today's Square post counter"""
    today = _get_today()
    current = get_today_posts()
    
    data = {
        "date": today,
        "square_count": current + 1,
        "last_updated": datetime.now().isoformat()
    }
    
    os.makedirs(os.path.dirname(POST_COUNTER_FILE), exist_ok=True)
    with open(POST_COUNTER_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def reset_counter():
    """Force reset counter (for testing)"""
    data = {
        "date": _get_today(),
        "square_count": 0,
        "last_updated": datetime.now().isoformat()
    }
    os.makedirs(os.path.dirname(POST_COUNTER_FILE), exist_ok=True)
    with open(POST_COUNTER_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def can_post() -> bool:
    """Check if we can still post to Square today"""
    return get_today_posts() < DAILY_POST_LIMIT
