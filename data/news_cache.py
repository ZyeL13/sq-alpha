# data/news_cache.py — Shared news cache for all runners

from data.fetcher import fetch_all_news

# Module-level cache — diisi ulang oleh main.py saat run_all_once()
_news_feed: list = []

def ensure_news():
    """Fetch news if cache is empty."""
    global _news_feed
    if not _news_feed:
        _news_feed = fetch_all_news()
