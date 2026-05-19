# collectors/rss_news.py
import time
import feedparser
import logging
import requests
from typing import List, Dict, Any
from datetime import datetime

log = logging.getLogger(__name__)

# Hanya sumber yang valid dan cepat
RSS_SOURCES = {
    "coindesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "cointelegraph": "https://cointelegraph.com/rss",
    "decrypt": "https://decrypt.co/feed",
}

RELEVANT_KEYWORDS = [
    "bitcoin", "btc", "ethereum", "eth", "solana", "sol", "binance", "bnb",
    "crypto", "blockchain", "defi", "nft", "web3", "altcoin", "token",
    "listing", "launch", "airdrop", "upgrade", "fork", "halving",
    "regulation", "sec", "fed", "inflation", "etf",
]

def fetch_feed(source_name: str, url: str, max_articles: int = 10, timeout: int = 10) -> List[Dict[str, Any]]:
    """
    Fetch and parse RSS feed from a single source with timeout.
    """
    try:
        # Gunakan requests untuk kontrol timeout
        resp = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
        
        articles = []
        for entry in feed.entries[:max_articles]:
            published = entry.get('published', entry.get('updated', ''))
            try:
                # Coba parsing pubDate (format RSS standar)
                pub_time = time.mktime(datetime.strptime(published[:25], '%a, %d %b %Y %H:%M:%S %z').timetuple())
            except:
                pub_time = time.time()  # fallback
            
            articles.append({
                "title": entry.get('title', ''),
                "link": entry.get('link', ''),
                "summary": entry.get('summary', '')[:300],
                "published": published,
                "timestamp": pub_time,
                "source": source_name,
            })
        return articles
    except requests.exceptions.Timeout:
        log.warning(f"Timeout fetching {source_name}")
        return []
    except requests.exceptions.RequestException as e:
        log.warning(f"Request error fetching {source_name}: {e}")
        return []
    except Exception as e:
        log.error(f"Unexpected error fetching {source_name}: {e}")
        return []

def is_relevant(article: Dict[str, Any]) -> bool:
    text = (article.get('title', '') + ' ' + article.get('summary', '')).lower()
    return any(kw in text for kw in RELEVANT_KEYWORDS)

def fetch_all_news(max_per_source: int = 5) -> List[Dict[str, Any]]:
    all_articles = []
    for source_name, url in RSS_SOURCES.items():
        print(f"  📡 Fetching {source_name}...")
        articles = fetch_feed(source_name, url, max_per_source)
        for article in articles:
            if is_relevant(article):
                all_articles.append(article)
        time.sleep(1)  # Jeda antar sumber
    
    all_articles.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
    print(f"  📰 Fetched {len(all_articles)} relevant news articles")
    return all_articles[:20]

def get_news_for_symbol(symbol: str, articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    symbol_lower = symbol.lower()
    return [a for a in articles if symbol_lower in (a['title'] + a['summary']).lower()][:3]

def get_catalyst_summary(symbol: str, articles: List[Dict[str, Any]]) -> str:
    relevant = get_news_for_symbol(symbol, articles)
    if not relevant:
        return ""
    
    summaries = []
    for article in relevant[:2]:
        title = article.get('title', '')
        source = article.get('source', '')
        # Format lebih ringkas
        summaries.append(f"• {title[:100]} ({source})")
    
    return "\n".join(summaries)
