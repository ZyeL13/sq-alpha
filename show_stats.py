#!/usr/bin/env python
# show_stats.py - Quick stats without running pipeline

from storage.persistent_queue import PersistentQueue
from storage.post_counter import get_today_posts, DAILY_POST_LIMIT
from processors.dedupe import get_stats

queue = PersistentQueue()
queue_stats = queue.get_stats()
dedup_stats = get_stats()

print(f"""
📊 PIPELINE STATISTICS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📅 Posts today:   {get_today_posts()}/{DAILY_POST_LIMIT}
📦 Queue items:   {queue_stats['total']}
💾 Dedup records: {dedup_stats.get('posted_entries', 0)}
🔥 Cooldown:      {dedup_stats.get('cooldown_entries', 0)} tokens
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""")
