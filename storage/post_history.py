
from collections import deque
from typing import List

_recent_posts: deque[str] = deque(maxlen=20) # Store last 20 posts

def record_post(content: str):
    """Add post to history."""
    _recent_posts.append(content)

def get_recent_posts() -> List[str]:
    """Get recent posts."""
    return list(_recent_posts)
