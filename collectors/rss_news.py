# collectors/rss_news.py
import time
import feedparser
import logging
from typing import List, Dict, Any
from datetime import datetime

log = logging.getLogger(__name__)

# RSS Sources
RSS_SOURCES = {
    "coindesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "cointelegraph": "https://cointelegraph.com/rss",
    "decrypt": "https://decrypt.co/feed",
    "bloomberg_crypto": "https://feeds.bloomberg.com/crypto/news.rss",
    "bitcoin_magazine": "https://bitcoinmagazine.com/.rss/full/",
    "the_block": "https://www.theblock.co/rss",
    "defi_pulse": "https://defipulse.com/feed",
    "crypto_slate": "https://slate.com/feeds/technology.rss",
}

# Keywords for relevance filtering
RELEVANT_KEYWORDS = [
    "bitcoin", "btc", "ethereum", "eth", "solana", "sol", "binance", "bnb",
    "crypto", "blockchain", "defi", "nft", "web3", "altcoin", "token",
    "listing", "launch", "airdrop", "upgrade", "fork", "halving",
    "regulation", "sec", "fed", "inflation", "etf",
]


def fetch_feed(source_name: str, url: str, max_articles: int = 10) -> List[Dict[str, Any]]:
    """
    Fetch and parse RSS feed from a single source.
    """
    try:
        feed = feedparser.parse(url)
        articles = []
        
        for entry in feed.entries[:max_articles]:
            # Extract published time
            published = entry.get('published', entry.get('updated', ''))
            try:
                pub_time = time.mktime(datetime.strptime(published[:25], '%a, %d %b %Y %H:%M:%S %z').timetuple())
            except:
                pub_time = time.time()
            
            articles.append({
                "title": entry.get('title', ''),
                "link": entry.get('link', ''),
                "summary": entry.get('summary', '')[:300],
                "published": published,
                "timestamp": pub_time,
                "source": source_name,
            })
        
        return articles
    except Exception as e:
        log.error(f"Error fetching {source_name}: {e}")
        return []


def is_relevant(article: Dict[str, Any]) -> bool:
    """
    Check if article is relevant to crypto.
    """
    text = (article.get('title', '') + ' ' + article.get('summary', '')).lower()
    return any(kw in text for kw in RELEVANT_KEYWORDS)


def fetch_all_news(max_per_source: int = 5) -> List[Dict[str, Any]]:
    """
    Fetch news from all RSS sources.
    Returns list of relevant articles sorted by timestamp.
    """
    all_articles = []
    
    for source_name, url in RSS_SOURCES.items():
        print(f"  📡 Fetching {source_name}...")
        articles = fetch_feed(source_name, url, max_per_source)
        
        for article in articles:
            if is_relevant(article):
                all_articles.append(article)
        
        time.sleep(1)  # Rate limit between sources
    
    # Sort by timestamp (newest first)
    all_articles.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
    
    print(f"  📰 Fetched {len(all_articles)} relevant news articles")
    return all_articles[:20]  # Return latest 20


def get_news_for_symbol(symbol: str, articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Filter news articles relevant to a specific symbol.
    """
    symbol_lower = symbol.lower()
    relevant = []
    
    for article in articles:
        text = (article.get('title', '') + ' ' + article.get('summary', '')).lower()
        if symbol_lower in text:
            relevant.append(article)
    
    return relevant[:3]  # Max 3 relevant articles


def get_catalyst_summary(symbol: str, articles: List[Dict[str, Any]]) -> str:
    """
    Generate a short summary of catalysts for a symbol.
    """
    relevant = get_news_for_symbol(symbol, articles)
    
    if not relevant:
        return ""
    
    summaries = []
    for article in relevant[:2]:
        title = article.get('title', '')
        source = article.get('source', '')
        summaries.append(f"• {title[:80]} ({source})")
    
    return "\n".join(summaries)
