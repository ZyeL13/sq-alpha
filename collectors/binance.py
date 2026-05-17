# collectors/binance.py
import time
import logging
import requests
from typing import List, Dict, Any
from config import STABLE_BLACKLIST
from config import FIRST_SEEN_FILE

_FIRST_SEEN_FILE = FIRST_SEEN_FILE
log = logging.getLogger(__name__)

def fetch_binance_tickers() -> List[Dict[str, Any]]:
    url = "https://api.binance.com/api/v3/ticker/24hr"
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        
        usdt_tokens = []
        for d in data:
            symbol = d['symbol']
            if not symbol.endswith('USDT'):
                continue
            base = symbol.replace('USDT', '')
            
            if base in STABLE_BLACKLIST:
                continue
            if base.endswith(('DOWN', 'UP', 'BEAR', 'BULL', 'SHORT', 'LONG')):
                continue
            
            usdt_tokens.append({
                "symbol": base,
                "full_symbol": symbol,
                "price": float(d['lastPrice']),
                "price_change_percent": float(d['priceChangePercent']),
                "volume_24h": float(d['quoteVolume']),
                "high_24h": float(d['highPrice']),
                "low_24h": float(d['lowPrice']),
                "trade_count": int(d['count']),
                "source": "binance",
                "timestamp": time.time(),
            })
        
        usdt_tokens.sort(key=lambda x: x['volume_24h'], reverse=True)
        for i, t in enumerate(usdt_tokens):
            t['volume_rank'] = i + 1
        
        log.info(f"Fetched {len(usdt_tokens)} Binance tokens")
        return usdt_tokens
    
    except Exception as e:
        log.error(f"Binance fetch error: {e}")
        return []

def fetch_all_binance(limit: int = None) -> List[Dict[str, Any]]:
    tokens = fetch_binance_tickers()
    max_tokens = limit or 200
    
    # Add age_hours to each token
    for token in tokens[:max_tokens]:
        full_symbol = token.get("full_symbol", f"{token['symbol']}USDT")
        token["age_hours"] = get_token_age_hours(token["symbol"], full_symbol)
    
    return tokens[:max_tokens]

def fetch_new_listings() -> List[str]:
    """Get recently listed USDT pairs (last ~30 listings)"""
    url = "https://api.binance.com/api/v3/exchangeInfo"
    try:
        resp = requests.get(url, timeout=15)
        data = resp.json()
        all_usdt = [
            s['symbol'] for s in data['symbols']
            if s['symbol'].endswith('USDT') and s['status'] == 'TRADING'
        ]
        return all_usdt[-30:]
    except Exception as e:
        log.error(f"ExchangeInfo error: {e}")
        return []

_first_seen_cache = {}
_FIRST_SEEN_FILE = "/data/data/com.termux/files/home/binance/first_seen.json"

def load_first_seen_cache():
    global _first_seen_cache
    import json
    import os
    if os.path.exists(_FIRST_SEEN_FILE):
        try:
            with open(_FIRST_SEEN_FILE, 'r') as f:
                _first_seen_cache = json.load(f)
        except:
            _first_seen_cache = {}
    else:
        _first_seen_cache = {}

def save_first_seen_cache():
    import json
    try:
        with open(_FIRST_SEEN_FILE, 'w') as f:
            json.dump(_first_seen_cache, f, indent=2)
    except:
        pass

def get_token_age_hours(symbol: str, full_symbol: str) -> float:
    """
    Calculate token age in hours.
    Uses first_seen cache for newly detected tokens.
    """
    global _first_seen_cache
    import time
    
    if not _first_seen_cache:
        load_first_seen_cache()
    
    now = time.time()
    key = full_symbol
    
    if key not in _first_seen_cache:
        # First time seeing this token
        _first_seen_cache[key] = {
            "symbol": symbol,
            "first_seen": now,
            "full_symbol": full_symbol
        }
        save_first_seen_cache()
        return 0  # brand new
    
    first_seen = _first_seen_cache[key].get("first_seen", now)
    age_seconds = now - first_seen
    age_hours = age_seconds / 3600
    
    return age_hours
