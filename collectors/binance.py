# collectors/binance.py
import time
import logging
import requests
import json
import os
import certifi
import urllib3
from typing import List, Dict, Any
from config import STABLE_BLACKLIST, FIRST_SEEN_FILE
import logging_config

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

TERMUX_CERT = "/data/data/com.termux/files/usr/etc/tls/cert.pem"

def _ssl_verify():
    import os
    if os.path.exists(TERMUX_CERT):
        return TERMUX_CERT
    try:
        return certifi.where()
    except Exception:
        return False

_VERIFY = False

logger = logging_config.get_logger("binance")

_first_seen_cache = {}
_FIRST_SEEN_FILE = FIRST_SEEN_FILE


def load_first_seen_cache():
    """Load first seen cache from disk"""
    global _first_seen_cache
    if os.path.exists(_FIRST_SEEN_FILE):
        try:
            with open(_FIRST_SEEN_FILE, 'r') as f:
                _first_seen_cache = json.load(f)
        except:
            _first_seen_cache = {}
    else:
        _first_seen_cache = {}


def save_first_seen_cache():
    """Save first seen cache to disk"""
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
    
    if not _first_seen_cache:
        load_first_seen_cache()
    
    now = time.time()
    key = full_symbol
    
    if key not in _first_seen_cache:
        _first_seen_cache[key] = {
            "symbol": symbol,
            "first_seen": now,
            "full_symbol": full_symbol
        }
        save_first_seen_cache()
        return 0
    
    first_seen = _first_seen_cache[key].get("first_seen", now)
    age_seconds = now - first_seen
    age_hours = age_seconds / 3600
    
    return age_hours


def fetch_binance_tickers(retries: int = 3) -> List[Dict[str, Any]]:
    """Fetch 24hr ticker data from Binance with retry and certifi SSL"""
    urls = [
        "https://data-api.binance.vision/api/v3/ticker/24hr",
        "https://data-api.binance.vision/api/v3/exchangeInfo",  # untuk get_new_listings
    ]
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
    }
    
    for url in urls:
        for attempt in range(retries):
            try:
                resp = requests.get(url, timeout=30, headers=headers, verify=_VERIFY)
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
                        "range_position": round(
                            (float(d['lastPrice']) - float(d['lowPrice'])) / 
                            (float(d['highPrice']) - float(d['lowPrice'])), 
                            2
                        ) if (float(d['highPrice']) - float(d['lowPrice'])) > 0 else 0.5,

                    })
                
                usdt_tokens.sort(key=lambda x: x['volume_24h'], reverse=True)
                for i, t in enumerate(usdt_tokens):
                    t['volume_rank'] = i + 1
                
                logger.info(f"Fetched {len(usdt_tokens)} Binance tokens from {url}")
                return usdt_tokens
            
            except requests.exceptions.Timeout:
                logger.warning(f"Timeout on {url} (attempt {attempt+1})")
                time.sleep(5 * (attempt + 1))
            except requests.exceptions.SSLError as e:
                logger.error(f"SSL Error on {url}: {e}")
                try:
                    resp = requests.get(url, timeout=30, headers=headers, verify=False)
                    resp.raise_for_status()
                    data = resp.json()
                    logger.warning(f"SSL verification disabled for {url}")
                except:
                    pass
                time.sleep(5)
            except Exception as e:
                logger.error(f"Error on {url}: {e}")
                time.sleep(3)
        
        logger.warning(f"All retries failed for {url}, trying next endpoint...")
    
    logger.error("All Binance endpoints failed")
    return []


def fetch_all_binance(limit: int = None) -> List[Dict[str, Any]]:
    """Main entry point - fetch and add age_hours"""
    tokens = fetch_binance_tickers()
    max_tokens = limit or 200
    
    for token in tokens[:max_tokens]:
        full_symbol = token.get("full_symbol", f"{token['symbol']}USDT")
        token["age_hours"] = get_token_age_hours(token["symbol"], full_symbol)
    
    return tokens[:max_tokens]


def fetch_new_listings() -> set:
    url = "https://data-api.binance.vision/api/v3/exchangeInfo?permissions=SPOT"
    try:
        resp = requests.get(url, timeout=60, verify=_VERIFY)  # 60s, file besar
        data = resp.json()
        all_usdt = [
            s['symbol'] for s in data['symbols']
            if s['symbol'].endswith('USDT') and s['status'] == 'TRADING'
        ]
        return set(all_usdt[-30:])
    except Exception as e:
        logger.error(f"ExchangeInfo error: {e}")
        return set()
