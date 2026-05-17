# collectors/alpha_discovery.py
import time
import logging
import requests
from typing import List, Dict, Any
from config import STABLE_BLACKLIST  # Tambahkan ini

log = logging.getLogger(__name__)


def fetch_alpha_discovery(chain_id: str = "56", limit: int = 20) -> List[Dict[str, Any]]:
    """
    Fetch Binance Alpha Discovery tokens for a specific chain.
    Chain IDs:
    - "56" : BSC
    - "8453" : Base
    - "CT_501" : Solana
    - "1" : Ethereum
    """
    url = "https://www.binance.com/bapi/defi/v1/public/wallet-direct/buw/wallet/market/token/pulse/unified/rank/list/ai"
    headers = {
        "Accept-Encoding": "identity",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0",
    }
    body = {
        "rankType": 20,
        "chainId": chain_id,
        "period": 50,
        "page": 1,
        "size": limit,
    }
    
    try:
        resp = requests.post(url, headers=headers, json=body, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if data.get("success") and "data" in data and "tokens" in data["data"]:
            return data["data"]["tokens"]
        return []
    except Exception as e:
        log.error(f"Alpha Discovery error (chain {chain_id}): {e}")
        return []


def fetch_all_alpha(limit_per_chain: int = 10) -> List[Dict[str, Any]]:
    """
    Fetch Alpha Discovery tokens from all chains.
    Returns normalized tokens ready for classification.
    """
    CHAINS = {
        "56": "bsc",
        "8453": "base", 
        "CT_501": "solana",
        "1": "eth"
    }
    
    all_tokens = []
    seen = set()
    
    for chain_id, chain_name in CHAINS.items():
        try:
            raw_tokens = fetch_alpha_discovery(chain_id, limit=limit_per_chain)
            
            for t in raw_tokens:
                # Create unique key to avoid duplicates
                contract = t.get("contractAddress", "")
                key = (chain_id, contract)
                if key in seen:
                    continue
                seen.add(key)
                
                symbol = (t.get("symbol") or "???").replace("$", "").upper()
                if not symbol or symbol in STABLE_BLACKLIST:
                    continue
                
                desc = (t.get("alphaInfo") or {}).get("enDescription", "")
                tags = [tag.get("tagEnName") for tag in (t.get("alphaInfo") or {}).get("tagList", [])]
                
                token_data = {
                    "symbol": symbol,
                    "full_symbol": f"{symbol}USDT",
                    "name": (t.get("metaInfo") or {}).get("name", symbol),
                    "chain": chain_name,
                    "contract_address": contract,
                    "price": float(t.get("price", 0) or 0),
                    "price_change_percent": float(t.get("percentChange24h", 0) or 0),
                    "volume_24h": float(t.get("volume24h", 0) or 0),
                    "market_cap": float(t.get("marketCap", 0) or 0),
                    "liquidity": float(t.get("liquidity", 0) or 0),
                    "holders": int(t.get("holders", 0) or 0),
                    "description": desc[:100] if desc else "",
                    "tags": tags[:5] if tags else [],
                    "source": "alpha_discovery",
                    "timestamp": time.time(),
                }
                
                all_tokens.append(token_data)
            
            log.info(f"Alpha Discovery {chain_name}: fetched {len(raw_tokens)} tokens")
            
        except Exception as e:
            log.error(f"Alpha Discovery chain {chain_id} error: {e}")
            continue
        
        time.sleep(2)  # Delay between chains
    
    # Sort by volume and assign ranks
    all_tokens.sort(key=lambda x: x["volume_24h"], reverse=True)
    for i, t in enumerate(all_tokens):
        t["volume_rank"] = i + 1
    
    log.info(f"Alpha Discovery total: {len(all_tokens)} tokens from {len(CHAINS)} chains")
    return all_tokens


def fetch_alpha_by_category(category: str = "ai", limit: int = 20) -> List[Dict[str, Any]]:
    """
    Fetch Alpha Discovery tokens by specific category.
    Categories: ai, gaming, defi, infrastructure, etc.
    """
    url = "https://www.binance.com/bapi/defi/v1/public/wallet-direct/buw/wallet/market/token/pulse/unified/rank/list/ai"
    headers = {
        "Accept-Encoding": "identity",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0",
    }
    body = {
        "rankType": 20,
        "category": category,
        "period": 50,
        "page": 1,
        "size": limit,
    }
    
    try:
        resp = requests.post(url, headers=headers, json=body, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if data.get("success") and "data" in data and "tokens" in data["data"]:
            return data["data"]["tokens"]
        return []
    except Exception as e:
        log.error(f"Alpha Discovery category error ({category}): {e}")
        return []
