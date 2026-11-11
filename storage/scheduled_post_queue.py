# storage/scheduled_post_queue.py
import sqlite3
import time
import threading
import os

from typing import Optional, List, Tuple

class ScheduledPostQueue:
    """Thread-safe persistent queue with scheduled posting times"""
    
    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = os.path.join(os.path.dirname(__file__), "scheduled_queue.db")
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
            self._migrate_v3_columns(conn)
            conn.commit()
            conn.close()

    def _migrate_v3_columns(self, conn):
        """Additive V3 migration (Phase 1): nullable format/title/
        image_paths columns. Old rows keep working — format defaults
        to 'short', title/image_paths default to NULL. Safe to run on
        every init; ALTER TABLE is a no-op when the column exists."""
        existing = {
            row[1] for row in conn.execute(
                "PRAGMA table_info(scheduled_posts)"
            ).fetchall()
        }
        for column, ddl in (
            ("format", "ALTER TABLE scheduled_posts ADD COLUMN format TEXT DEFAULT 'short'"),
            ("title", "ALTER TABLE scheduled_posts ADD COLUMN title TEXT"),
            ("image_paths", "ALTER TABLE scheduled_posts ADD COLUMN image_paths TEXT"),
        ):
            if column not in existing:
                conn.execute(ddl)

    def add_post(self, post: str, category: str, symbol: str,
                 scheduled_time: float, hook: str = "",
                 session: str = "", provider: str = "",
                 format: str = "short", title: str | None = None,
                 image_paths: list | None = None):
        """Add a post to be published at scheduled_time.

        V3: format/title/image_paths travel with the row so the
        poster worker can publish the right shape. image_paths is
        stored as a JSON list. Defaults keep every existing caller
        on the short-text path."""
        import json

        with self._lock:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.execute(
                """INSERT INTO scheduled_posts
                   (post, category, symbol, hook, session, provider, scheduled_time,
                    format, title, image_paths)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (post, category, symbol, hook, session, provider, scheduled_time,
                 format, title, json.dumps(image_paths) if image_paths else None)
            )
            conn.commit()
            conn.close()
            print(f"  📅 Added to schedule: {symbol} at {scheduled_time:.0f}")

    def get_due_posts(self, limit: int = 5) -> List[Tuple]:
        """Get posts that are due to be published (scheduled_time <= now).

        Returns 10-tuples: (id, post, category, symbol, hook, session,
        provider, format, title, image_paths). image_paths is decoded
        from JSON (None when the row has none). Indices 0-6 are
        identical to the pre-V3 shape."""
        import json

        now = time.time()
        with self._lock:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            cursor = conn.execute(
                """SELECT id, post, category, symbol, hook, session, provider,
                          format, title, image_paths
                   FROM scheduled_posts
                   WHERE scheduled_time <= ?
                   ORDER BY scheduled_time
                   LIMIT ?""",
                (now, limit)
            )
            rows = cursor.fetchall()
            conn.close()
            results = []
            for row in rows:
                (post_id, post, category, symbol, hook, session, provider,
                 fmt, title, image_paths_json) = row
                image_paths = None
                if image_paths_json:
                    try:
                        image_paths = json.loads(image_paths_json)
                    except (ValueError, TypeError):
                        image_paths = None
                results.append((
                    post_id, post, category, symbol, hook, session, provider,
                    fmt or "short", title, image_paths,
                ))
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

    def delete_old_posts(self, max_age_seconds: int = 3600):
        """Delete posts that are older than max_age_seconds (default 1 hour)"""
        with self._lock:
            cutoff = time.time() - max_age_seconds
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            cursor = conn.execute("DELETE FROM scheduled_posts WHERE scheduled_time < ?", (cutoff,))
            deleted = cursor.rowcount
            conn.commit()
            conn.close()
            if deleted:
                print(f"  🗑️ Auto-deleted {deleted} expired posts (> {max_age_seconds//60} min)")
            return deleted
