# config.py — Central configuration
import os
from dotenv import load_dotenv

load_dotenv()

# ========== API KEYS ==========
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID")
BINANCE_SQUARE_KEY = os.getenv("BINANCE_SQUARE_KEY")
BINANCE_SQUARE_URL = os.getenv("BINANCE_SQUARE_URL")
GROQ_API_KEY       = os.getenv("GROQ_API_KEY")
BITQUERY_API_KEY   = os.getenv("BITQUERY_API_KEY")
DEEPSEEK_API_KEY   = os.getenv("DEEPSEEK_API_KEY")

# ========== PATHS ==========
BASE_DIR = "/data/data/com.termux/files/home/binance"
CACHE_DIR = f"{BASE_DIR}/cache"
os.makedirs(CACHE_DIR, exist_ok=True)

# Cache files
DEDUP_FILE = f"{CACHE_DIR}/dedup_cache.json"
POST_COUNTER_FILE = f"{CACHE_DIR}/post_counter.json"
FIRST_SEEN_FILE = f"{CACHE_DIR}/first_seen.json"
COINGECKO_CACHE_FILE = f"{CACHE_DIR}/coingecko_cache.json"
LLM_CACHE_FILE = f"{CACHE_DIR}/llm_cache.json"

# ========== BLACKLISTS ==========
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
        "max_tokens": 600,
        "temperature": 0.65,
        "top_p": 0.9,
        "requests_per_minute": 10,
        "enabled": True,
        "weight": 5,
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
        "weight": 2,
    },
    "deepseek": {
        "api_key": os.getenv("DEEPSEEK_API_KEY"),
        "api_url": "https://api.deepseek.com/v1/chat/completions",  # endpoint tetap sama
        "model": "deepseek-v4-flash",  # ← ganti dari "deepseek-chat"
        "max_tokens": 600,
        "temperature": 0.69,
        "top_p": 0.9,
        "thinking_mode": "non-thinking",  # tambahan untuk V4
        "requests_per_minute": 10,
        "enabled": True,
        "weight": 1,
    },
    "nvidia_nim": {
        "api_key": os.getenv("NVIDIA_NIM_API_KEY"),
        "api_url": "https://integrate.api.nvidia.com/v1/chat/completions",
        "model": "meta/llama-3.3-70b-instruct",
        "max_tokens": 600,
        "temperature": 0.69,
        "top_p": 0.85,
        "requests_per_minute": 10,
        "enabled": True,
        "weight": 3,
    },
}

# Category to preferred provider
CATEGORY_PREFERRED = {
    "HOT": "nvidia_nim",
    "ALPHA": "nvidia_nim",
    "GAINERS": "nvidia_nim",
    "LOSERS": "nvidia_nim",
}

# ========== POST MODE ==========
POST_MODE = "rebate"

# ========== PIPELINE SETTINGS ==========
COLLECTOR_INTERVAL = 60      # seconds between fetches
PROCESSOR_WORKERS = 1        # number of processor threads
DAILY_POST_LIMIT = 100       # Binance Square limit

# ========== DEDUPLICATION ==========
DEDUP_TTL_HOURS = 24         # hours before token can repeat in same category

# ========== COINGECKO CONFIG ==========
COINGECKO_ENABLED = True
COINGECKO_CACHE_TTL = 300    # seconds
COINGECKO_RATE_LIMIT_SECONDS = 6

# ========== RSS NEWS CONFIG ==========
RSS_ENABLED = True
RSS_MAX_ARTICLES_PER_SOURCE = 5
RSS_REFRESH_INTERVAL = 300   # seconds

# ========== CLASSIFICATION THRESHOLDS ==========
HOT_VOLUME_RANK_MAX = 100
HOT_PRICE_CHANGE_MAX = 3.0
GAINER_THRESHOLD = 3.0
LOSER_THRESHOLD = -3.0
ALPHA_MAX_MCAP = 1_000_000
ALPHA_MIN_VOLUME = 100_000

# ========== SCORING WEIGHTS (unused, reserved) ==========
MOMENTUM_WEIGHT = 0.25
ANOMALY_WEIGHT = 0.30
WALLET_WEIGHT = 0.20
LIQUIDITY_WEIGHT = 0.15
FRESHNESS_WEIGHT = 0.10

# ========== COOLDOWN CONFIG ==========
# Market cap tiers (in USD)
MARKET_CAP_TIERS = [
    (10_000_000_000, 4 * 3600),   # > $10B → 4 jam
    (1_000_000_000, 8 * 3600),    # > $1B → 8 jam
    (0, 24 * 3600),                # default → 24 jam
]

# Specific token overrides
TOKEN_COOLDOWN_OVERRIDES = {
    "BTC": 4 * 3600,
    "ETH": 4 * 3600,
    "SOL": 6 * 3600,
    "BNB": 6 * 3600,
    "XRP": 8 * 3600,
    "DOGE": 8 * 3600,
}

# Similarity threshold (0-1)
SIMILARITY_THRESHOLD = 0.65

# Daily post target (bukan limit hard)
DAILY_POST_TARGET = 70  # dari 100
