# storage/persistent_queue.py
import sqlite3
import json
import time
import threading
from datetime import datetime
from typing import Optional, Tuple

class PersistentQueue:
    """Thread-safe persistent queue using SQLite"""
    
    def __init__(self, db_path: str = "storage/queue.db"):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_db()
    
    def _init_db(self):
        """Initialize database and table"""
        with self._lock:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    token_data TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_created ON queue(created_at)")
            conn.commit()
            conn.close()
    
    def put(self, source: str, token_data: dict):
        """Add item to queue"""
        with self._lock:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.execute(
                "INSERT INTO queue (source, token_data) VALUES (?, ?)",
                (source, json.dumps(token_data, default=str))
            )
            conn.commit()
            conn.close()
    
    def get(self, timeout: int = 5) -> Optional[Tuple[str, dict]]:
        """Get and remove oldest item from queue (blocking with timeout)"""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            with self._lock:
                conn = sqlite3.connect(self.db_path, check_same_thread=False)
                cursor = conn.execute(
                    "SELECT id, source, token_data FROM queue ORDER BY id LIMIT 1"
                )
                row = cursor.fetchone()
                
                if row:
                    conn.execute("DELETE FROM queue WHERE id = ?", (row[0],))
                    conn.commit()
                    conn.close()
                    return (row[1], json.loads(row[2]))
                
                conn.close()
            
            time.sleep(0.5)
        
        return None
    
    def size(self) -> int:
        """Get current queue size"""
        with self._lock:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            cursor = conn.execute("SELECT COUNT(*) FROM queue")
            count = cursor.fetchone()[0]
            conn.close()
            return count
    
    def clear(self):
        """Clear all items from queue"""
        with self._lock:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.execute("DELETE FROM queue")
            conn.commit()
            conn.close()
    
    def get_stats(self) -> dict:
        """Get queue statistics"""
        with self._lock:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            cursor = conn.execute("""
                SELECT 
                    COUNT(*) as total,
                    MIN(created_at) as oldest,
                    MAX(created_at) as newest
                FROM queue
            """)
            row = cursor.fetchone()
            conn.close()
            
            return {
                "total": row[0] or 0,
                "oldest": row[1],
                "newest": row[2]
            }
