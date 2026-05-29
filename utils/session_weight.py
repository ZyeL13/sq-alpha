# utils/session_weight.py
from datetime import datetime, timezone

# Session windows (UTC)
SESSIONS = {
    "asia_open":    {"start": 0,  "end": 5,  "weight": 0.6},
    "eu_open":      {"start": 6,  "end": 10, "weight": 0.9},
    "eu_us_overlap":{"start": 13, "end": 17, "weight": 1.0},
    "us_session":   {"start": 17, "end": 21, "weight": 0.8},
    "dead_zone":    {"start": 21, "end": 24, "weight": 0.3},
}

# Posts per session per run
SESSION_POST_LIMITS = {
    "asia_open":     3,
    "eu_open":       6,
    "eu_us_overlap": 8,
    "us_session":    5,
    "dead_zone":     1,
}


def get_current_session() -> tuple[str, float]:
    """Return current session name and weight."""
    hour = datetime.now(timezone.utc).hour
    for name, s in SESSIONS.items():
        if s["start"] <= hour < s["end"]:
            return name, s["weight"]
    return "dead_zone", 0.3


def get_post_limit() -> int:
    """Return how many posts to generate this run."""
    session, _ = get_current_session()
    return SESSION_POST_LIMITS.get(session, 2)


def should_post(base_probability: float = 1.0) -> bool:
    """Weight-adjusted post decision."""
    import random
    _, weight = get_current_session()
    return random.random() < (base_probability * weight)


def session_info() -> dict:
    name, weight = get_current_session()
    return {
        "session": name,
        "weight": weight,
        "post_limit": get_post_limit(),
        "utc_hour": datetime.now(timezone.utc).hour,
    }

