# data/fetcher.py — Binance (spot/futures/alpha) + Berita + GeckoTerminal

import time
import requests
import re
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from config import STABLE_BLACKLIST, NEWS_SOURCES, NEWS_KEYWORDS

log = logging.getLogger(__name__)

# ─── BINANCE SPOT ──────────────────────────────────────────────
def get_binance_data():
    url = "https://api.binance.com/api/v3/ticker/24hr"
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        usdt = []
        for d in data:
            symbol = d['symbol']
            if not symbol.endswith('USDT'):
                continue
            base = symbol.replace('USDT', '')
            if base in STABLE_BLACKLIST:
                continue
            # Skip synthetic leverage tokens
            if base.endswith(('DOWN', 'UP', 'BEAR', 'BULL', 'SHORT', 'LONG')):
                continue
            d['priceChangePercent'] = float(d['priceChangePercent'])
            d['quoteVolume']        = float(d['quoteVolume'])
            d['count']              = int(d['count'])
            usdt.append(d)
        return usdt
    except Exception as e:
        log.error(f"Binance API error: {e}")
        return []

def get_new_listings():
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

# ─── BINANCE FUTURES ──────────────────────────────────────────
def get_futures_symbols():
    url = "https://fapi.binance.com/fapi/v1/exchangeInfo"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        symbols = set()
        for s in data['symbols']:
            if s['quoteAsset'] == 'USDT' and s['status'] == 'TRADING':
                symbols.add(s['symbol'])
        return symbols
    except Exception as e:
        log.error(f"Futures symbols error: {e}")
        return set()

# ─── BINANCE ALPHA DISCOVERY (untuk runner alpha) ─────────────
def get_alpha_discovery(chain_id="56", limit=20):
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
        log.error(f"Alpha Discovery error ({chain_id}): {e}")
        return []

def get_alpha_multi_chain(limit_per_chain=10):
    CHAINS = ["56", "8453", "CT_501"]
    CHAIN_NAMES = {"56": "bsc", "8453": "base", "CT_501": "solana", "1": "eth"}
    all_tokens = []
    seen = set()
    for chain_id in CHAINS:
        raw = get_alpha_discovery(chain_id, limit=limit_per_chain)
        for t in raw:
            key = (chain_id, t.get("contractAddress", ""))
            if key in seen:
                continue
            seen.add(key)
            sym = (t.get("symbol") or "???").replace("$", "").upper()
            desc = (t.get("alphaInfo") or {}).get("enDescription", "")
            tags = [tag.get("tagEnName") for tag in (t.get("alphaInfo") or {}).get("tagList", [])]
            all_tokens.append({
                "symbol":          sym,
                "name":            (t.get("metaInfo") or {}).get("name", sym),
                "chain":           CHAIN_NAMES.get(chain_id, chain_id),
                "contractAddress": t.get("contractAddress", ""),
                "price":           float(t.get("price", 0) or 0),
                "change_24h":      float(t.get("percentChange24h", 0) or 0),
                "volume_24h":      float(t.get("volume24h", 0) or 0),
                "market_cap":      float(t.get("marketCap", 0) or 0),
                "liquidity":       float(t.get("liquidity", 0) or 0),
                "holders":         int(t.get("holders", 0) or 0),
                "desc":            desc[:100] if desc else "",
                "tags":            tags[:5] if tags else [],
            })
    all_tokens.sort(key=lambda x: x["volume_24h"], reverse=True)
    log.info(f"Alpha multi-chain total: {len(all_tokens)} tokens")
    return all_tokens

# ─── RSS NEWS ──────────────────────────────────────────────────
def clean_desc(desc, max_chars=400):
    desc = re.sub(r'<[^>]+>', '', desc).strip()
    if len(desc) <= max_chars:
        return desc
    cut = desc[:max_chars].rfind('. ')
    if cut > 200:
        return desc[:cut + 1]
    cut = desc[:max_chars].rfind(', ')
    if cut > 200:
        return desc[:cut + 1]
    return desc[:max_chars]

def fetch_rss(name, url):
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError:
            content = re.sub(r'[^\x09\x0A\x0D\x20-\x7F\x80-\xFF]', '', resp.text)
            root    = ET.fromstring(content)

        ns    = {"atom": "http://www.w3.org/2005/Atom"}
        items = []

        for item in root.findall(".//item"):
            title = item.findtext("title", "").strip()
            link  = item.findtext("link", "").strip()
            desc  = clean_desc(item.findtext("description", "").strip())
            if title and link:
                items.append({"title": title, "link": link, "desc": desc, "source": name})

        if not items:
            for entry in root.findall(".//atom:entry", ns):
                title   = entry.findtext("atom:title", "", ns).strip()
                link_el = entry.find("atom:link", ns)
                link    = link_el.get("href", "") if link_el is not None else ""
                desc    = clean_desc(entry.findtext("atom:summary", "", ns).strip())
                if title and link:
                    items.append({"title": title, "link": link, "desc": desc, "source": name})

        log.info(f"{name}: fetched {len(items)} items")
        return items[:8]
    except Exception as e:
        log.error(f"{name}: fetch failed — {e}")
        return []

def relevance_score(title, desc):
    text = (title + " " + desc).lower()
    return sum(1 for kw in NEWS_KEYWORDS if kw in text)

def fetch_all_news() -> list:
    feed = []
    for name, url in NEWS_SOURCES.items():
        articles = fetch_rss(name, url)
        for a in articles:
            if relevance_score(a["title"], a.get("desc", "")) >= 1:
                feed.append(a)
    log.info(f"fetch_all_news: {len(feed)} relevant articles")
    return feed

# ─── GECKO TERMINAL MICROCAP SCOUT ─────────────────────────────
GECKO_BASE  = "https://api.geckoterminal.com/api/v2"
GECKO_HDRS  = {
    "Accept": "application/json;version=20230302",
    "User-Agent": "microcap-scout/1.0",
}

CHAIN_MAP = {
    "eth"    : "eth",
    "bsc"    : "bsc",
    "base"   : "base",
    "solana" : "solana",
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
    for item in (included or []):
        if item.get("type") == "token":
            attrs = item.get("attributes", {})
            sym   = (attrs.get("symbol") or "").strip().upper().replace("$", "")
            if sym:
                sym_map[item["id"]] = sym
    return sym_map

def _normalize(pool: dict, sym_map: dict, network: str) -> dict | None:
    attrs = pool.get("attributes", {})
    if not attrs:
        return None

    base_rel = (pool.get("relationships") or {}).get("base_token") or {}
    token_id = (base_rel.get("data") or {}).get("id", "")
    symbol   = sym_map.get(token_id, "")
    if not symbol:
        name = attrs.get("name", "")
        symbol = name.split("/")[0].strip().replace("$", "").upper() if name else ""
    if not symbol:
        return None

    if symbol in {"WETH", "WBNB", "WBTC", "WSOL", "USDT", "USDC", "DAI",
                  "BUSD", "FDUSD", "ETH", "BNB", "SOL", "BTC"}:
        return None

    mcap = float(attrs.get("market_cap_usd") or 0)
    if mcap <= 0:
        mcap = float(attrs.get("fdv_usd") or 0)

    liquidity = float(attrs.get("reserve_in_usd") or 0)

    vol_h1 = float((attrs.get("volume_usd") or {}).get("h1") or 0)

    txns_h1    = attrs.get("transactions", {}).get("h1", {})
    buys_h1    = int(txns_h1.get("buys", 0) or 0)
    sells_h1   = int(txns_h1.get("sells", 0) or 0)
    count_1h   = buys_h1 + sells_h1

    total_txns = buys_h1 + sells_h1
    buy_ratio  = buys_h1 / total_txns if total_txns > 0 else 0.5
    vol_buy    = vol_h1 * buy_ratio
    vol_sell   = vol_h1 * (1 - buy_ratio)

    txns_h24  = attrs.get("transactions", {}).get("h24", {})
    holders   = int(txns_h24.get("buyers", 0) or 0)

    launch_ms = _parse_iso(attrs.get("pool_created_at", ""))

    change_1h = float((attrs.get("price_change_percentage") or {}).get("h1") or 0)

    pool_addr = attrs.get("address", "")

    if mcap <= 0 or liquidity <= 0 or launch_ms <= 0:
        return None

    return {
        "symbol"          : symbol,
        "marketCap"       : mcap,
        "liquidity"       : liquidity,
        "holders"         : holders,
        "launchTime"      : launch_ms,
        "volume1h"        : vol_h1,
        "volume1hBuy"     : vol_buy,
        "volume1hSell"    : vol_sell,
        "count1h"         : count_1h,
        "percentChange1h" : change_1h,
        "contractAddress" : pool_addr,
        "network"         : network,
    }

def get_alpha_scout_pool(chains: list | None = None, limit_per_chain: int = 100) -> list:
    if chains is None:
        chains = ["eth", "bsc", "base", "solana"]

    all_tokens = []
    seen_addrs = set()

    for network in chains:
        gecko_net = CHAIN_MAP.get(network, network)
        collected = 0
        page      = 1
        max_pages = min(10, -(-limit_per_chain // 20))

        while collected < limit_per_chain and page <= max_pages:
            url    = f"{GECKO_BASE}/networks/{gecko_net}/new_pools"
            params = {"include": "base_token", "page": page}

            try:
                resp = requests.get(url, headers=GECKO_HDRS, params=params, timeout=15)
                resp.raise_for_status()
                body = resp.json()
            except Exception as e:
                log.error(f"GeckoTerminal fetch error {network} page {page}: {e}")
                break

            pools    = body.get("data") or []
            included = body.get("included") or []
            sym_map  = _build_symbol_map(included)

            if not pools:
                break

            for pool in pools:
                token = _normalize(pool, sym_map, network)
                if token is None:
                    continue
                addr = token["contractAddress"]
                if addr and addr in seen_addrs:
                    continue
                if addr:
                    seen_addrs.add(addr)
                all_tokens.append(token)
                collected += 1
                if collected >= limit_per_chain:
                    break

            page += 1
            time.sleep(3)

        log.info(f"GeckoTerminal {network}: collected {collected} pools")

    log.info(f"get_alpha_scout_pool total: {len(all_tokens)} tokens")
    return all_tokens
