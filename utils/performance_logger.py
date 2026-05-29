# utils/performance_logger.py
import json
import os
from datetime import datetime, timezone
from pathlib import Path

LOG_PATH = Path(os.getenv("LOG_DIR", "logs")) / "post_performance.jsonl"


def log_post(
    symbol: str,
    category: str,
    hook: str,
    angle: str,
    session: str,
    post_content: str,
    llm_provider: str = "",
    post_id: str = "",
):
    """Log a posted entry. Call immediately after successful post."""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "category": category,
        "hook": hook,
        "angle": angle,
        "session": session,
        "llm": llm_provider,
        "post_id": post_id,
        "length": len(post_content),
        # fill these later via update_metrics()
        "views": None,
        "likes": None,
        "comments": None,
        "rebate": None,
    }

    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def update_metrics(post_id: str, views: int = None, likes: int = None,
                   comments: int = None, rebate: float = None):
    """Update performance metrics for a logged post by post_id."""
    if not LOG_PATH.exists():
        return

    lines = LOG_PATH.read_text(encoding="utf-8").splitlines()
    updated = []
    for line in lines:
        try:
            entry = json.loads(line)
            if entry.get("post_id") == post_id:
                if views is not None:    entry["views"] = views
                if likes is not None:    entry["likes"] = likes
                if comments is not None: entry["comments"] = comments
                if rebate is not None:   entry["rebate"] = rebate
            updated.append(json.dumps(entry))
        except json.JSONDecodeError:
            updated.append(line)

    LOG_PATH.write_text("\n".join(updated) + "\n", encoding="utf-8")


def get_stats() -> dict:
    """Basic stats: best hooks, best sessions, avg rebate."""
    if not LOG_PATH.exists():
        return {}

    entries = []
    for line in LOG_PATH.read_text(encoding="utf-8").splitlines():
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    if not entries:
        return {}

    from collections import defaultdict

    hook_views    = defaultdict(list)
    session_views = defaultdict(list)
    category_views = defaultdict(list)

    total_rebate = 0.0
    rebate_count = 0

    for e in entries:
        v = e.get("views") or 0
        hook_views[e.get("hook", "")][:]; hook_views[e["hook"]].append(v)
        session_views[e.get("session", "")].append(v)
        category_views[e.get("category", "")].append(v)
        if e.get("rebate") is not None:
            total_rebate += e["rebate"]
            rebate_count += 1

    def top(d, n=3):
        return sorted(
            {k: sum(v)/len(v) for k, v in d.items() if v}.items(),
            key=lambda x: x[1], reverse=True
        )[:n]

    return {
        "total_posts": len(entries),
        "avg_rebate": round(total_rebate / rebate_count, 4) if rebate_count else None,
        "top_hooks": top(hook_views),
        "top_sessions": top(session_views),
        "top_categories": top(category_views),
    }

