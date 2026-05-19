# config.py — update path section
import os
from dotenv import load_dotenv

load_dotenv()

# API KEYS
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID")
BINANCE_SQUARE_KEY = os.getenv("BINANCE_SQUARE_KEY")
BINANCE_SQUARE_URL = os.getenv("BINANCE_SQUARE_URL")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
GROQ_API_KEY       = os.getenv("GROQ_API_KEY")
BITQUERY_API_KEY   = os.getenv("BITQUERY_API_KEY")

# ========== PATHS ==========
BASE_DIR = "/data/data/com.termux/files/home/binance"
CACHE_DIR = f"{BASE_DIR}/cache"

# Pastikan folder cache ada
os.makedirs(CACHE_DIR, exist_ok=True)

# Cache files
DEDUP_FILE = f"{CACHE_DIR}/dedup_cache.json"
POST_COUNTER_FILE = f"{CACHE_DIR}/post_counter.json"
FIRST_SEEN_FILE = f"{CACHE_DIR}/first_seen.json"
COINGECKO_CACHE_FILE = f"{CACHE_DIR}/coingecko_cache.json"
LLM_CACHE_FILE = f"{CACHE_DIR}/llm_cache.json"

# BLACKLISTS
STABLE_BLACKLIST = {
    "USDC", "BUSD", "TUSD", "USDP", "DAI", "FDUSD",
    "PAX", "HUSD", "USDN", "UST", "VAI", "USDD", "FRAX",
    "RLUSD", "USD1", "USDE", "U", "XUSD",
    "EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "CNY", "HKD", "SGD",
    "DOWN", "UP", "BEAR", "BULL", "SHORT", "LONG", "EURI",
}

# ========== MULTI LLM PROVIDERS ==========
LLM_PROVIDERS = {
    "blockrun": {
        "api_key": "not-needed",
        "api_url": "http://127.0.0.1:8402/v1/chat/completions",
        "model": "free/deepseek-v3.2",
        "max_tokens": 500,
        "temperature": 0.65,
        "top_p": 0.9,
        "requests_per_minute": 15,
        "enabled": True,
        "weight": 1,
    },
    "groq": {
        "api_key": GROQ_API_KEY,
        "api_url": "https://api.groq.com/openai/v1/chat/completions",
        "model": "llama-3.3-70b-versatile",
        "max_tokens": 500,
        "temperature": 0.7,
        "top_p": 0.9,
        "requests_per_minute": 10,
        "enabled": True,
        "weight": 1,
    },
    "openrouter": {
        "api_key": OPENROUTER_API_KEY,
        "api_url": "https://openrouter.ai/api/v1/chat/completions",
        "model": "openrouter/free",
        "max_tokens": 500,
        "temperature": 0.8,
        "top_p": 0.9,
        "requests_per_minute": 10,
        "enabled": True,
        "weight": 1,
    }
}

# ========== DEDUPLICATION ==========
DEDUP_TTL_HOURS = 24  # 24 jam

# Category to preferred provider
CATEGORY_PREFERRED = {
    "HOT": "blockrun",
    "ALPHA": "blockrun",
    "GAINERS": "blockrun",
    "LOSERS": "blockrun",
}

POST_MODE = "rebate"

# Pipeline settings
COLLECTOR_INTERVAL = 60
PROCESSOR_WORKERS = 1

# Daily post limit (Binance Square = 100 posts/day)
DAILY_POST_LIMIT = 100

# ========== COINGECKO CONFIG ==========
COINGECKO_ENABLED = True
COINGECKO_CACHE_TTL = 300  # 5 minutes
COINGECKO_RATE_LIMIT_SECONDS = 6  # 10 calls per minute

# ========== RSS NEWS CONFIG ==========
RSS_ENABLED = True
RSS_MAX_ARTICLES_PER_SOURCE = 5
RSS_REFRESH_INTERVAL = 300  # 5 minutes

# ========== CLASSIFICATION THRESHOLDS ==========
HOT_VOLUME_RANK_MAX = 100
HOT_PRICE_CHANGE_MAX = 3.0
GAINER_THRESHOLD = 3.0
LOSER_THRESHOLD = -3.0
ALPHA_MAX_MCAP = 1_000_000
ALPHA_MIN_VOLUME = 100_000

# ========== SCORING WEIGHTS ==========
MOMENTUM_WEIGHT = 0.25
ANOMALY_WEIGHT = 0.30
WALLET_WEIGHT = 0.20
LIQUIDITY_WEIGHT = 0.15
FRESHNESS_WEIGHT = 0.10
