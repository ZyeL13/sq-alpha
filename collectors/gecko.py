# collectors/gecko.py (update fetch_gecko_pools dengan retry)
import time
import logging
import requests
from datetime import datetime
from typing import List, Dict, Any

log = logging.getLogger(__name__)

GECKO_BASE = "https://api.geckoterminal.com/api/v2"
GECKO_HEADERS = {
    "Accept": "application/json;version=20230302",
    "User-Agent": "crypto-collector/1.0",
}

CHAIN_MAP = {
    "eth": "eth",
    "bsc": "bsc",
    "base": "base",
    "solana": "solana",
    "polygon": "polygon",
    "arbitrum": "arbitrum",
}


def _parse_iso(ts: str) -> int:
    if not ts:
        return 0
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return int(dt.timestamp() * 1000)
    except Exception:
        return 0


def _build_symbol_map(included: list) -> dict:
    sym_map = {}
    for item in included or []:
        if item.get("type") == "token":
            attrs = item.get("attributes", {})
            sym = (attrs.get("symbol") or "").strip().upper().replace("$", "")
            if sym:
                sym_map[item["id"]] = sym
    return sym_map


def _normalize_pool(pool: dict, sym_map: dict, network: str) -> Dict[str, Any] | None:
    attrs = pool.get("attributes", {})
    if not attrs:
        return None

    base_rel = (pool.get("relationships") or {}).get("base_token") or {}
    token_id = (base_rel.get("data") or {}).get("id", "")
    symbol = sym_map.get(token_id, "")

    if not symbol:
        name = attrs.get("name", "")
        symbol = name.split("/")[0].strip().replace("$", "").upper() if name else ""

    if not symbol:
        return None

    skip_tokens = {
        "WETH", "WBNB", "WBTC", "WSOL", "USDT", "USDC", "DAI",
        "BUSD", "FDUSD", "ETH", "BNB", "SOL", "BTC", "WMATIC", "WAVAX"
    }
    if symbol in skip_tokens:
        return None

    mcap = float(attrs.get("market_cap_usd") or 0)
    if mcap <= 0:
        mcap = float(attrs.get("fdv_usd") or 0)

    liquidity = float(attrs.get("reserve_in_usd") or 0)
    volume_1h = float((attrs.get("volume_usd") or {}).get("h1") or 0)
    volume_24h = float((attrs.get("volume_usd") or {}).get("h24") or 0)

    txns_1h = attrs.get("transactions", {}).get("h1", {})
    buys_1h = int(txns_1h.get("buys", 0) or 0)
    sells_1h = int(txns_1h.get("sells", 0) or 0)
    total_txns = buys_1h + sells_1h
    buy_ratio = buys_1h / total_txns if total_txns > 0 else 0.5

    txns_24h = attrs.get("transactions", {}).get("h24", {})
    holders = int(txns_24h.get("buyers", 0) or 0)

    launch_ms = _parse_iso(attrs.get("pool_created_at", ""))
    age_hours = (time.time() * 1000 - launch_ms) / (1000 * 3600) if launch_ms > 0 else 100

    price_change = (attrs.get("price_change_percentage") or {}).get("h1", 0)
    if isinstance(price_change, str):
        price_change = float(price_change) if price_change else 0

    if mcap <= 0 or liquidity <= 0 or launch_ms <= 0:
        return None

    return {
        "symbol": symbol,
        "full_symbol": f"{symbol}",
        "price": float(attrs.get("base_token_price_usd", 0) or 0),
        "price_change_percent": float(price_change),
        "volume_24h": volume_24h,
        "volume_1h": volume_1h,
        "market_cap": mcap,
        "liquidity": liquidity,
        "holders": holders,
        "trade_count_1h": total_txns,
        "buy_ratio_1h": buy_ratio,
        "age_hours": age_hours,
        "launch_time": launch_ms,
        "contract_address": attrs.get("address", ""),
        "chain": network,
        "source": "gecko",
        "timestamp": time.time(),
    }


def fetch_gecko_pools(chain: str = "eth", page: int = 1, retries: int = 2) -> dict:
    """Fetch new pools from GeckoTerminal with retry logic"""
    gecko_chain = CHAIN_MAP.get(chain, chain)
    url = f"{GECKO_BASE}/networks/{gecko_chain}/new_pools"
    params = {"include": "base_token", "page": page}
    
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=GECKO_HEADERS, params=params, timeout=15)
            if resp.status_code == 429:
                wait = (attempt + 1) * 10
                print(f"  ⏳ Rate limit on {chain}, waiting {wait}s...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            log.error(f"GeckoTerminal fetch error for {chain} (attempt {attempt+1}): {e}")
            if attempt < retries - 1:
                time.sleep(5)
    return {}


def fetch_all_gecko_tokens(limit_per_chain: int = 10) -> List[Dict[str, Any]]:
    """
    Fetch microcap tokens from multiple chains on GeckoTerminal.
    Focus on new pools with small market cap.
    """
    chains = ["eth", "bsc", "base", "solana", "polygon", "arbitrum"]
    all_tokens = []
    seen_symbols = set()
    
    for chain in chains:
        collected = 0
        page = 1
        max_pages = min(2, -(-limit_per_chain // 20))  # Limit pages to 2
        
        while collected < limit_per_chain and page <= max_pages:
            data = fetch_gecko_pools(chain, page)
            
            pools = data.get("data", [])
            included = data.get("included", [])
            sym_map = _build_symbol_map(included)
            
            if not pools:
                break
            
            for pool in pools:
                token = _normalize_pool(pool, sym_map, chain)
                if token is None:
                    continue
                
                # Skip duplicates
                if token["symbol"] in seen_symbols:
                    continue
                seen_symbols.add(token["symbol"])
                
                # Microcap focus: market cap under $2M
                if token["market_cap"] > 2_000_000:
                    continue
                
                all_tokens.append(token)
                collected += 1
                
                if collected >= limit_per_chain:
                    break
            
            page += 1
            time.sleep(5)  # Delay between pages
        
        log.info(f"GeckoTerminal {chain}: collected {collected} tokens")
        time.sleep(5)  # Delay between chains
    
    # Sort by volume
    all_tokens.sort(key=lambda x: x["volume_24h"], reverse=True)
    for i, t in enumerate(all_tokens):
        t["volume_rank"] = i + 1
    
    log.info(f"GeckoTerminal total: {len(all_tokens)} microcap tokens")
    return all_tokens


def fetch_microcap_pools(min_mcap: int = 50000, max_mcap: int = 500000) -> List[Dict[str, Any]]:
    """
    Fetch pools with specific market cap range (microcap focus).
    min_mcap: minimum market cap in USD (default 50k)
    max_mcap: maximum market cap in USD (default 500k)
    """
    all_tokens = fetch_all_gecko_tokens(limit_per_chain=10)
    
    # Filter by market cap range
    filtered = [
        t for t in all_tokens 
        if min_mcap <= t.get("market_cap", 0) <= max_mcap
    ]
    
    log.info(f"Microcap filter: {len(filtered)} tokens between ${min_mcap} and ${max_mcap}")
    return filtered
