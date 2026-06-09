# utils/performance_logger.py
import json
import os
import time
import csv
from datetime import datetime, timezone
from pathlib import Path

LOG_PATH = Path(os.getenv("LOG_DIR", "logs")) / "post_performance.jsonl"
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


def _rotate_if_needed():
    """Rotate log file if it exceeds max size"""
    if LOG_PATH.exists() and LOG_PATH.stat().st_size > MAX_FILE_SIZE:
        backup_path = LOG_PATH.with_suffix(f".{int(time.time())}.jsonl")
        LOG_PATH.rename(backup_path)
        print(f"📦 Rotated performance log to {backup_path.name}")


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
    # Validasi
    if not symbol or not category:
        print(f"⚠️ Invalid log_post call: symbol={symbol}, category={category}")
        return
    
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _rotate_if_needed()

    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol.upper(),
        "category": category,
        "hook": hook[:100] if hook else "",
        "angle": angle[:100] if angle else "",
        "session": session,
        "llm": llm_provider,
        "post_id": post_id or f"{symbol}_{int(time.time())}",
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
    found = False
    
    for line in lines:
        try:
            entry = json.loads(line)
            if entry.get("post_id") == post_id:
                if views is not None:    entry["views"] = views
                if likes is not None:    entry["likes"] = likes
                if comments is not None: entry["comments"] = comments
                if rebate is not None:   entry["rebate"] = rebate
                found = True
            updated.append(json.dumps(entry))
        except json.JSONDecodeError:
            updated.append(line)

    if found:
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

    hook_views = defaultdict(list)
    session_views = defaultdict(list)
    category_views = defaultdict(list)

    total_rebate = 0.0
    rebate_count = 0

    for e in entries:
        v = e.get("views") or 0
        hook_views[e.get("hook", "")].append(v)
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


def export_to_csv(output_file: str = "posts_export.csv"):
    """Export all posts to CSV for manual audit"""
    if not LOG_PATH.exists():
        print("No log file found")
        return
    
    entries = []
    for line in LOG_PATH.read_text(encoding="utf-8").splitlines():
        try:
            entries.append(json.loads(line))
        except:
            continue
    
    if not entries:
        print("No entries found")
        return
    
    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Date', 'Time', 'Symbol', 'Category', 'Hook', 'Views', 'Likes', 'Rebate', 'Length'])
        
        for e in entries:
            try:
                dt = datetime.fromisoformat(e['ts'].replace('Z', '+00:00'))
                writer.writerow([
                    dt.strftime('%Y-%m-%d'),
                    dt.strftime('%H:%M'),
                    e['symbol'],
                    e['category'],
                    e['hook'][:60] if e['hook'] else '',
                    e.get('views', ''),
                    e.get('likes', ''),
                    e.get('rebate', ''),
                    e.get('length', '')
                ])
            except:
                continue
    
    print(f"✅ Exported {len(entries)} posts to {output_file}")


def export_to_markdown(output_file: str = "posts_audit.md"):
    """Export to Markdown table for documentation"""
    if not LOG_PATH.exists():
        print("No log file found")
        return
    
    entries = []
    for line in LOG_PATH.read_text(encoding="utf-8").splitlines():
        try:
            entries.append(json.loads(line))
        except:
            continue
    
    if not entries:
        return
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("# Post Audit Log\n\n")
        f.write("| Date | Time | Symbol | Category | Views | Rebate |\n")
        f.write("|------|------|--------|----------|-------|--------|\n")
        
        for e in entries[:100]:  # 100 terbaru
            dt = datetime.fromisoformat(e['ts'].replace('Z', '+00:00'))
            views = e.get('views', '') or ''
            rebate = e.get('rebate', '') or ''
            f.write(f"| {dt.strftime('%Y-%m-%d')} | {dt.strftime('%H:%M')} | {e['symbol']} | {e['category']} | {views} | {rebate} |\n")
    
    print(f"✅ Exported {min(len(entries), 100)} posts to {output_file}")
