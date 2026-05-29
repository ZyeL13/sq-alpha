# storage/scheduled_post_queue.py
import sqlite3
import json
import time
import threading
from datetime import datetime
from typing import Optional, List, Tuple

class ScheduledPostQueue:
    """Thread-safe persistent queue with scheduled posting times"""
    
    def __init__(self, db_path: str = "storage/scheduled_queue.db"):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_db()
    
    def _init_db(self):
        with self._lock:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS scheduled_posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    post TEXT NOT NULL,
                    category TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    hook TEXT,
                    session TEXT,
                    provider TEXT,
                    scheduled_time REAL NOT NULL,
                    created_at REAL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_scheduled_time ON scheduled_posts(scheduled_time)")
            conn.commit()
            conn.close()
    
    def add_post(self, post: str, category: str, symbol: str, 
                 scheduled_time: float, hook: str = "", 
                 session: str = "", provider: str = ""):
        """Add a post to be published at scheduled_time"""
        with self._lock:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.execute(
                """INSERT INTO scheduled_posts 
                   (post, category, symbol, hook, session, provider, scheduled_time) 
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (post, category, symbol, hook, session, provider, scheduled_time)
            )
            conn.commit()
            conn.close()
            print(f"  📅 Added to schedule: {symbol} at {scheduled_time:.0f}")
    
    def get_due_posts(self, limit: int = 5) -> List[Tuple]:
        """Get posts that are due to be published (scheduled_time <= now)"""
        now = time.time()
        with self._lock:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            cursor = conn.execute(
                """SELECT id, post, category, symbol, hook, session, provider 
                   FROM scheduled_posts 
                   WHERE scheduled_time <= ? 
                   ORDER BY scheduled_time 
                   LIMIT ?""",
                (now, limit)
            )
            results = cursor.fetchall()
            conn.close()
            return results
    
    def remove_post(self, post_id: int):
        """Remove a post after publishing"""
        with self._lock:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.execute("DELETE FROM scheduled_posts WHERE id = ?", (post_id,))
            conn.commit()
            conn.close()
    
    def get_next_post_time(self) -> Optional[float]:
        """Get the earliest scheduled post time (next to be published)"""
        with self._lock:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            cursor = conn.execute("SELECT MIN(scheduled_time) FROM scheduled_posts")
            result = cursor.fetchone()[0]
            conn.close()
            return result
    
    def get_last_post_time(self) -> Optional[float]:
        """Get the latest scheduled post time (last in queue)"""
        with self._lock:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            cursor = conn.execute("SELECT MAX(scheduled_time) FROM scheduled_posts")
            result = cursor.fetchone()[0]
            conn.close()
            return result
    
    def get_post_count(self) -> int:
        """Get total number of scheduled posts"""
        with self._lock:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            cursor = conn.execute("SELECT COUNT(*) FROM scheduled_posts")
            count = cursor.fetchone()[0]
            conn.close()
            return count
    
    def clear(self):
        """Clear all scheduled posts"""
        with self._lock:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.execute("DELETE FROM scheduled_posts")
            conn.commit()
            conn.close()
            print("  🗑️ Scheduled queue cleared")
    
    def get_stats(self) -> dict:
        """Get queue statistics"""
        with self._lock:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            cursor = conn.execute("""
                SELECT 
                    COUNT(*) as total,
                    MIN(scheduled_time) as next_post,
                    MAX(scheduled_time) as last_post
                FROM scheduled_posts
            """)
            row = cursor.fetchone()
            conn.close()
            return {
                "total": row[0] or 0,
                "next_post": row[1],
                "last_post": row[2]
            }
