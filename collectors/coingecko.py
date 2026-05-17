# collectors/coingecko.py
import time
import json
import os
import functools
import logging
from typing import List, Dict, Any, Optional
from pycoingecko import CoinGeckoAPI
from config import COINGECKO_CACHE_FILE

log = logging.getLogger(__name__)

# Cache configuration
CACHE_FILE = COINGECKO_CACHE_FILE
CACHE_TTL_SECONDS = 300  # 5 minutes

# Rate limiting: minimum 6 seconds between calls (10 calls per minute)
MIN_INTERVAL_SECONDS = 6

_cache: Dict[str, Dict] = {}
_last_call_time = 0


def _load_cache():
    """Load cache from disk"""
    global _cache
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r') as f:
                _cache = json.load(f)
        except:
            _cache = {}
    else:
        _cache = {}


def _save_cache():
    """Save cache to disk"""
    try:
        with open(CACHE_FILE, 'w') as f:
            json.dump(_cache, f, indent=2)
    except:
        pass


def _get_cached(key: str) -> Optional[Any]:
    """Get cached value if still valid"""
    if not _cache:
        _load_cache()
    
    entry = _cache.get(key)
    if entry:
        age = time.time() - entry.get("timestamp", 0)
        if age < CACHE_TTL_SECONDS:
            return entry.get("data")
        else:
            del _cache[key]
            _save_cache()
    return None


def _set_cache(key: str, data: Any):
    """Store value in cache"""
    _cache[key] = {
        "data": data,
        "timestamp": time.time()
    }
    _save_cache()


def _rate_limit():
    """Enforce rate limiting for free tier"""
    global _last_call_time
    now = time.time()
    elapsed = now - _last_call_time
    if elapsed < MIN_INTERVAL_SECONDS:
        wait = MIN_INTERVAL_SECONDS - elapsed
        time.sleep(wait)
    _last_call_time = time.time()


# Initialize client
cg = CoinGeckoAPI()


def get_top_coins_market_data(limit: int = 100, vs_currency: str = 'usd') -> List[Dict[str, Any]]:
    """
    Fetch top coins market data from CoinGecko.
    
    Args:
        limit: Number of coins (max 250 per page)
        vs_currency: Quote currency (usd, btc, eth, etc.)
    
    Returns:
        List of coins with market data
    """
    cache_key = f"top_coins_{limit}_{vs_currency}"
    
    # Check cache first
    cached = _get_cached(cache_key)
    if cached:
        print(f"  💾 CoinGecko cache HIT ({len(cached)} coins)")
        return cached
    
    # Apply rate limiting
    _rate_limit()
    
    try:
        data = cg.get_coins_markets(
            vs_currency=vs_currency,
            order='market_cap_desc',
            per_page=min(limit, 250),
            page=1,
            sparkline=False,
            price_change_percentage='24h'
        )
        
        # Normalize data format
        normalized = []
        for coin in data:
            normalized.append({
                "symbol": coin['symbol'].upper(),
                "name": coin['name'],
                "price": coin['current_price'],
                "market_cap": coin['market_cap'],
                "volume_24h": coin['total_volume'],
                "price_change_24h": coin['price_change_percentage_24h'],
                "ath": coin['ath'],
                "atl": coin['atl'],
                "source": "coingecko",
                "timestamp": time.time()
            })
        
        # Cache result
        _set_cache(cache_key, normalized)
        print(f"  📡 CoinGecko fetched {len(normalized)} coins")
        
        return normalized
        
    except Exception as e:
        log.error(f"CoinGecko API error: {e}")
        return []


def get_coin_detail(coin_id: str) -> Optional[Dict[str, Any]]:
    """
    Get detailed information for a specific coin.
    
    Args:
        coin_id: CoinGecko coin ID (e.g., 'bitcoin', 'ethereum')
    
    Returns:
        Detailed coin data
    """
    cache_key = f"coin_detail_{coin_id}"
    
    cached = _get_cached(cache_key)
    if cached:
        return cached
    
    _rate_limit()
    
    try:
        data = cg.get_coin_by_id(
            id=coin_id,
            localization=False,
            tickers=False,
            market_data=True,
            community_data=False,
            developer_data=False,
            sparkline=False
        )
        
        result = {
            "symbol": data['symbol'].upper(),
            "name": data['name'],
            "description": data.get('description', {}).get('en', '')[:500],
            "market_cap_rank": data.get('market_cap_rank'),
            "links": data.get('links', {}),
            "source": "coingecko_detail",
            "timestamp": time.time()
        }
        
        _set_cache(cache_key, result)
        return result
        
    except Exception as e:
        log.error(f"CoinGecko detail error for {coin_id}: {e}")
        return None


def enrich_binance_token(binance_token: Dict[str, Any]) -> Dict[str, Any]:
    """
    Enrich Binance token data with CoinGecko information.
    Matches by symbol.
    """
    symbol = binance_token.get("symbol", "").lower()
    
    # Get top coins for matching
    top_coins = get_top_coins_market_data(limit=250)
    
    for gecko_coin in top_coins:
        if gecko_coin['symbol'].lower() == symbol:
            # Merge data
            enriched = binance_token.copy()
            enriched['coingecko_market_cap'] = gecko_coin.get('market_cap')
            enriched['coingecko_price_change'] = gecko_coin.get('price_change_24h')
            enriched['coingecko_volume'] = gecko_coin.get('volume_24h')
            enriched['enriched_by'] = 'coingecko'
            return enriched
    
    return binance_token


def get_trending_coins() -> List[Dict[str, Any]]:
    """
    Get trending coins from CoinGecko (search trending)
    """
    cache_key = "trending_coins"
    
    cached = _get_cached(cache_key)
    if cached:
        return cached
    
    _rate_limit()
    
    try:
        data = cg.get_search_trending()
        trending = []
        
        for item in data.get('coins', []):
            coin = item.get('item', {})
            trending.append({
                "symbol": coin.get('symbol', '').upper(),
                "name": coin.get('name', ''),
                "market_cap_rank": coin.get('market_cap_rank'),
                "score": coin.get('score'),
                "source": "coingecko_trending",
                "timestamp": time.time()
            })
        
        _set_cache(cache_key, trending)
        print(f"  📡 CoinGecko trending: {len(trending)} coins")
        return trending
        
    except Exception as e:
        log.error(f"CoinGecko trending error: {e}")
        return []


def get_coin_history(coin_id: str, days: int = 7) -> Optional[List]:
    """
    Get historical market data for a coin.
    
    Args:
        coin_id: CoinGecko coin ID
        days: Number of days (1, 7, 14, 30, 90, 180, 365, max)
    
    Returns:
        List of [timestamp, price] pairs
    """
    cache_key = f"coin_history_{coin_id}_{days}"
    
    cached = _get_cached(cache_key)
    if cached:
        return cached
    
    _rate_limit()
    
    try:
        data = cg.get_coin_market_chart_by_id(
            id=coin_id,
            vs_currency='usd',
            days=days
        )
        
        prices = data.get('prices', [])
        
        _set_cache(cache_key, prices)
        return prices
        
    except Exception as e:
        log.error(f"CoinGecko history error for {coin_id}: {e}")
        return []
