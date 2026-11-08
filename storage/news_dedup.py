# storage/news_dedup.py
"""Pelacakan artikel berita yang sudah dipakai sebagai katalis.

Satu event berita hanya boleh jadi satu post (lihat
collectors/rss_news.py: assign_news_to_tokens). Modul ini menyimpan
kunci artikel yang sudah dipakai ke file JSON — pola yang sama dengan
processors/dedupe.py TokenMemory (atomic write via file tmp +
os.replace, file korup dipindah ke .bak).

Kunci artikel = hash dari link yang dinormalisasi (tanpa query string,
tanpa trailing slash), fallback ke judul yang dinormalisasi kalau
tidak ada link. Normalisasi ini yang membuat satu event yang sama
dari dua sumber/agregator yang berbeda URL tetap satu event hanya
kalau link-nya sama; event yang sama dengan link berbeda tetap
dideteksi sebagai event berbeda — keterbatasan yang dicatat, bukan
diatasi dengan membandingkan isi (terlalu rapuh untuk judul yang
sedikit berbeda).
"""
import hashlib
import json
import logging
import os
import re
import time
from typing import Dict, Any

from config import NEWS_DEDUP_FILE

log = logging.getLogger(__name__)

# Entri lebih tua dari ini dibersihkan (artikel RSS sudah lama hilang
# dari feed pada titik ini, jadi tidak akan ditempel lagi).
NEWS_DEDUP_TTL_HOURS = 24


def normalize_link(link: str) -> str:
    """Link tanpa query string/fragment, huruf kecil, tanpa '/' akhir."""
    link = (link or "").strip().lower()
    link = re.split(r"[?#]", link, maxsplit=1)[0]
    return link.rstrip("/")


def normalize_title(title: str) -> str:
    """Judul huruf kecil, whitespace diratakan, tanpa tanda baca akhir."""
    title = (title or "").strip().lower()
    title = re.sub(r"\s+", " ", title)
    return title.rstrip(" .!?:;")


def article_key(article: Dict[str, Any]) -> str:
    """Kunci stabil untuk satu artikel (hash link, fallback judul)."""
    link = normalize_link(article.get("link", ""))
    if link:
        raw = f"link:{link}"
    else:
        raw = f"title:{normalize_title(article.get('title', ''))}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]


class NewsDedup:
    def __init__(self, storage_file: str = NEWS_DEDUP_FILE):
        self.storage_file = storage_file
        self.used: Dict[str, Dict[str, Any]] = {}  # key -> {symbol, title, timestamp}
        self._load()

    def is_seen(self, article: Dict[str, Any]) -> bool:
        return article_key(article) in self.used

    def mark_used(self, article: Dict[str, Any], symbol: str) -> None:
        self.used[article_key(article)] = {
            "symbol": symbol,
            "title": (article.get("title", "") or "")[:120],
            "source": article.get("source", ""),
            "timestamp": time.time(),
        }
        self._save()

    def clear_old(self, max_age_hours: float = NEWS_DEDUP_TTL_HOURS) -> int:
        now = time.time()
        cutoff = now - max_age_hours * 3600
        old = [k for k, v in self.used.items()
               if v.get("timestamp", 0) < cutoff]
        for k in old:
            del self.used[k]
        if old:
            self._save()
        return len(old)

    def _load(self):
        if not os.path.exists(self.storage_file):
            self.used = {}
            return
        try:
            with open(self.storage_file, "r") as f:
                data = json.load(f)
            self.used = data if isinstance(data, dict) else {}
        except json.JSONDecodeError as e:
            log.error(f"News dedup file corrupted: {e}")
            try:
                os.rename(self.storage_file, f"{self.storage_file}.bak")
            except OSError:
                pass
            self.used = {}
        except Exception as e:
            log.exception(f"Unexpected error loading news dedup file: {e}")
            self.used = {}

    def _save(self):
        try:
            dir_path = os.path.dirname(self.storage_file)
            if dir_path:
                os.makedirs(dir_path, exist_ok=True)
            temp_file = f"{self.storage_file}.tmp"
            with open(temp_file, "w") as f:
                json.dump(self.used, f, indent=2)
            os.replace(temp_file, self.storage_file)
        except Exception as e:
            log.error(f"Failed to save news dedup file: {e}")


_news_dedup = None
_lock = None


def _get_lock():
    global _lock
    if _lock is None:
        import threading
        _lock = threading.Lock()
    return _lock


def get_news_dedup() -> NewsDedup:
    global _news_dedup
    if _news_dedup is None:
        with _get_lock():
            if _news_dedup is None:
                _news_dedup = NewsDedup()
    return _news_dedup


def is_news_seen(article: Dict[str, Any]) -> bool:
    return get_news_dedup().is_seen(article)


def mark_news_used(article: Dict[str, Any], symbol: str) -> None:
    get_news_dedup().mark_used(article, symbol)


def clear_old_news_entries() -> int:
    return get_news_dedup().clear_old()
