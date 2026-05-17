# collectors/news.py
import re
import logging
import requests
import xml.etree.ElementTree as ET
from typing import List, Dict, Any

log = logging.getLogger(__name__)

NEWS_SOURCES = {
    "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "Decrypt": "https://decrypt.co/feed",
    "Cointelegraph": "https://cointelegraph.com/rss",
    "Bloomberg Crypto": "https://feeds.bloomberg.com/crypto/news.rss",
}

NEWS_KEYWORDS = [
    "bitcoin", "btc", "ethereum", "eth", "crypto", "blockchain",
    "solana", "defi", "altcoin", "ai", "listing", "launch", "regulation"
]


def clean_text(text: str, max_chars: int = 300) -> str:
    """Clean HTML tags and truncate"""
    text = re.sub(r'<[^>]+>', '', text).strip()
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rfind('. ')
    if cut > max_chars // 2:
        return text[:cut + 1]
    return text[:max_chars]


def fetch_rss_feed(source_name: str, url: str) -> List[Dict[str, Any]]:
    """Fetch and parse RSS feed"""
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        
        # Fix encoding issues
        content = resp.content
        try:
            root = ET.fromstring(content)
        except ET.ParseError:
            # Remove invalid XML characters
            content_str = re.sub(r'[^\x09\x0A\x0D\x20-\x7F\x80-\xFF]', '', content.decode('utf-8', errors='ignore'))
            root = ET.fromstring(content_str)
        
        items = []
        for item in root.findall(".//item"):
            title = item.findtext("title", "").strip()
            link = item.findtext("link", "").strip()
            desc = clean_text(item.findtext("description", "").strip())
            
            if title and link and _is_relevant(title, desc):
                items.append({
                    "title": title,
                    "link": link,
                    "description": desc,
                    "source": source_name,
                    "timestamp": time.time(),
                })
        
        log.info(f"{source_name}: fetched {len(items)} relevant articles")
        return items[:10]
    
    except Exception as e:
        log.error(f"{source_name}: fetch failed — {e}")
        return []


def _is_relevant(title: str, description: str) -> bool:
    """Check if article is relevant to crypto"""
    text = (title + " " + description).lower()
    return any(kw in text for kw in NEWS_KEYWORDS)


def fetch_all_news() -> List[Dict[str, Any]]:
    """Fetch news from all configured sources"""
    all_articles = []
    for name, url in NEWS_SOURCES.items():
        articles = fetch_rss_feed(name, url)
        all_articles.extend(articles)
        time.sleep(1)  # Rate limit protection
    
    # Sort by timestamp (newest first)
    all_articles.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
    log.info(f"Total news articles fetched: {len(all_articles)}")
    return all_articles[:30]  # Return only latest 30
