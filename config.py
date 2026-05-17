# config.py — Full configuration for 6 categories + 3 LLM providers
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

# PATHS
BASE_DIR = "/data/data/com.termux/files/home/binance"
DEDUP_FILE = f"{BASE_DIR}/dedup_cache.json"

# BLACKLISTS
STABLE_BLACKLIST = {
    "USDC", "BUSD", "TUSD", "USDP", "DAI", "FDUSD",
    "PAX", "HUSD", "USDN", "UST", "VAI", "USDD", "FRAX",
    "RLUSD", "USD1", "USDE", "U",
    "EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "CNY", "HKD", "SGD",
    "DOWN", "UP", "BEAR", "BULL", "SHORT", "LONG",
}

# ========== MULTI LLM PROVIDERS ==========
LLM_PROVIDERS = {
    "blockrun": {
        "api_key": "not-needed",
        "api_url": "http://127.0.0.1:8402/v1/chat/completions",
        "model": "free/deepseek-v3.2",
        "max_tokens": 500,
        "temperature": 0.75,
        "top_p": 0.9,
        "requests_per_minute": 15,
        "enabled": True,
        "weight": 1,
    },
    "groq": {
        "api_key": GROQ_API_KEY,
        "api_url": "https://api.groq.com/openai/v1/chat/completions",
        "model": "llama-3.3-70b-versatile",
        "max_tokens": 300,
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
        "max_tokens": 300,
        "temperature": 0.8,
        "top_p": 0.9,
        "requests_per_minute": 10,
        "enabled": True,
        "weight": 1,
    }
}

# Category to preferred provider (optional, fallback to round-robin)
CATEGORY_PREFERRED = {
    "HOT": "blockrun",
    "ALPHA": "blockrun",
    "NEW": "blockrun",
    "GAINERS": "blockrun",
    "LOSERS": "blockrun",
    "SIGNAL": "blockrun",
}

POST_MODE = "rebate"

# Pipeline settings
COLLECTOR_INTERVAL = 60
PROCESSOR_WORKERS = 2
#POST_DELAY_MIN = 60
#POST_DELAY_MAX = 120

# Daily post limit (Binance Square = 100 posts/day)
DAILY_POST_LIMIT = 100
POST_COUNTER_FILE = f"{BASE_DIR}/post_counter.json"
