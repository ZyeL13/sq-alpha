# storage/news_review.py
"""Antrean review untuk berita besar yang tidak cocok ke token mana pun.

Berita makro/regulatori (ETF, The Fed, gugatan SEC, hack besar) sering
tidak menyebut satu token pun — tapi tetap layak dibaca user, bukan
hilang begitu saja. Modul ini mencatatnya ke file JSON untuk direview
manual. TIDAK ada auto-post dari antrean ini: user yang memutuskan.

Pola penyimpanan sama seperti storage/news_dedup.py (JSON + atomic
write). Entri didedupe berdasarkan kunci artikel, dan antrean dibatasi
100 item terbaru supaya file tidak membengkak.
"""
import json
import logging
import os
import time
from typing import Dict, Any, List

from config import NEWS_REVIEW_FILE
from storage.news_dedup import article_key

log = logging.getLogger(__name__)

MAX_REVIEW_ITEMS = 100


def load_review_queue(storage_file: str = NEWS_REVIEW_FILE) -> List[Dict[str, Any]]:
    if not os.path.exists(storage_file):
        return []
    try:
        with open(storage_file, "r") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError) as e:
        log.error(f"News review file unreadable: {e}")
        return []


def queue_for_review(article: Dict[str, Any], suggested_cashtag: str,
                     storage_file: str = NEWS_REVIEW_FILE) -> bool:
    """Tambah artikel ke antrean review. Kembalikan False kalau artikel
    sudah ada di antrean (dedupe berdasarkan kunci artikel)."""
    items = load_review_queue(storage_file)
    key = article_key(article)
    if any(item.get("key") == key for item in items):
        return False
    items.append({
        "key": key,
        "title": article.get("title", ""),
        "link": article.get("link", ""),
        "source": article.get("source", ""),
        "timestamp": article.get("timestamp", 0),
        "queued_at": time.time(),
        "suggested_cashtag": suggested_cashtag,
    })
    items = items[-MAX_REVIEW_ITEMS:]
    try:
        dir_path = os.path.dirname(storage_file)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)
        temp_file = f"{storage_file}.tmp"
        with open(temp_file, "w") as f:
            json.dump(items, f, indent=2)
        os.replace(temp_file, storage_file)
    except Exception as e:
        log.error(f"Failed to save news review queue: {e}")
        return False
    return True
