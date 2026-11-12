# config.py — Central configuration
import os
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

load_dotenv()

# All human-facing times (daily reset, sessions, log dates) are WIB.
# The code used to call naive datetime.now(), which follows the server's
# local timezone — on a UTC host the "7 AM WIB" reset fired at 7 AM UTC.
WIB = ZoneInfo("Asia/Jakarta")

# ========== API KEYS ==========
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID")
BINANCE_SQUARE_KEY = os.getenv("BINANCE_SQUARE_KEY")
BINANCE_SQUARE_URL = os.getenv("BINANCE_SQUARE_URL")
GROQ_API_KEY       = os.getenv("GROQ_API_KEY")
CMC_API_KEY        = os.getenv("CMC_API_KEY")
DEEPSEEK_API_KEY   = os.getenv("DEEPSEEK_API_KEY")
NVIDIA_NIM_API_KEY = os.getenv("NVIDIA_NIM_API_KEY")

# ========== PATHS ==========
BASE_DIR = os.path.dirname(__file__)
CACHE_DIR = os.path.join(BASE_DIR, "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

# Cache files
DEDUP_FILE = f"{CACHE_DIR}/dedup_cache.json"
NEWS_DEDUP_FILE = f"{CACHE_DIR}/news_dedup.json"
NEWS_REVIEW_FILE = f"{CACHE_DIR}/news_review.json"
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
    "DOWN", "UP", "BEAR", "BULL", "SHORT", "LONG", "EURI", "WBTC", "WBETH",
    "HIGH",
}

# ========== MULTI LLM PROVIDERS ==========
# Priority: BlockRun (free, local proxy) > Groq (free) > NVIDIA NIM (free).
# DeepSeek is OFF until topped up. Providers with an empty api_key are
# skipped automatically (llm._get_providers_by_priority), so DeepSeek
# also stays out of the rotation while its key is empty.
LLM_PROVIDERS = {
    # BlockRun (ClawRouter) local proxy — free models, wallet $0.
    # The proxy must be running on the host (port 8402). Inside Docker
    # 127.0.0.1 is the container itself, so set BLOCKRUN_API_URL to
    # http://host.docker.internal:8402/v1/chat/completions (see
    # docker-compose.yml). Model IDs are the exact IDs from the proxy's
    # /v1/models output (2026-11-09, 14 free models) — "free" alone is
    # NOT a valid model ID. Three entries = in-provider fallback:
    # deepseek-v4-flash, then llama-4-maverick, then mistral-large-3.
    "blockrun": {
        "api_key": "not-needed",
        "api_url": os.getenv(
            "BLOCKRUN_API_URL", "http://127.0.0.1:8402/v1/chat/completions"
        ),
        "model": "free/deepseek-v4-flash",
        "max_tokens": 555,
        "temperature": 0.55,
        "top_p": 0.9,
        "requests_per_minute": 10,
        "enabled": True,
        "weight": 6,
    },
    "blockrun_llama": {
        "api_key": "not-needed",
        "api_url": os.getenv(
            "BLOCKRUN_API_URL", "http://127.0.0.1:8402/v1/chat/completions"
        ),
        "model": "free/llama-4-maverick",
        "max_tokens": 555,
        "temperature": 0.55,
        "top_p": 0.9,
        "requests_per_minute": 10,
        "enabled": True,
        "weight": 5.5,
    },
    "blockrun_mistral": {
        "api_key": "not-needed",
        "api_url": os.getenv(
            "BLOCKRUN_API_URL", "http://127.0.0.1:8402/v1/chat/completions"
        ),
        "model": "free/mistral-large-3-675b",
        "max_tokens": 555,
        "temperature": 0.55,
        "top_p": 0.9,
        "requests_per_minute": 10,
        "enabled": True,
        "weight": 5.25,
    },
    # Groq Free plan (no card) — openai/gpt-oss-120b,
    # 30 RPM / 1,000 RPD / 200k tokens/day. llama-3.3-70b-versatile was
    # decommissioned by Groq on 2026-08-16 (404 model_not_found).
    # gpt-oss is a reasoning model: its reasoning tokens come out of the
    # same max_tokens budget as the answer, so 600 starved it and Groq
    # returned empty content ("Invalid content type" in llm.py).
    # reasoning_effort=low + 1800 budget leaves room for the answer;
    # include_reasoning=false keeps the reasoning trace out of the reply.
    "groq": {
        "api_key": GROQ_API_KEY,
        "api_url": "https://api.groq.com/openai/v1/chat/completions",
        "model": "openai/gpt-oss-120b",
        "max_tokens": 1800,
        "temperature": 0.69,
        "top_p": 0.85,
        "requests_per_minute": 10,
        "reasoning_effort": "low",
        "include_reasoning": False,
        "enabled": True,
        "weight": 5,
    },
    # DeepSeek deepseek-flash (V4.1 Flash). NOT free — pay per
    # token, ~$0.15 in / $0.60 out per 1M tokens off-peak (~$0.0004/post).
    # Disabled until topped up (2026-11-09). deepseek-v4-flash is a
    # legacy alias; deepseek-flash is canonical.
    # Note: thinking_mode was removed — it was never sent in the payload.
    "deepseek": {
        "api_key": DEEPSEEK_API_KEY,
        "api_url": "https://api.deepseek.com/v1/chat/completions",
        "model": "deepseek-flash",
        "max_tokens": 600,
        "temperature": 0.69,
        "top_p": 0.9,
        "requests_per_minute": 10,
        "enabled": False,
        "weight": 4,
    },
    # NVIDIA NIM free tier (nvapi- key, no card).
    # meta/llama-3.3-70b-instruct retired 2026-08-26 (HTTP 410 Gone).
    # DISABLED until a replacement is verified against the live list:
    #   curl https://integrate.api.nvidia.com/v1/models \
    #     -H "Authorization: Bearer $NVIDIA_NIM_API_KEY"
    # then set "model" to an ID from that output and flip enabled on.
    # (Candidate seen in NVIDIA's Nov-2026 free-tier listing:
    # nvidia/nemotron-3-ultra-550b-a55b — NOT live-verified, do not
    # enable on that basis alone.)
    "nvidia_nim": {
        "api_key": NVIDIA_NIM_API_KEY,
        "api_url": "https://integrate.api.nvidia.com/v1/chat/completions",
        "model": "nvidia/nemotron-3-ultra-550b-a55b",
        "max_tokens": 600,
        "temperature": 0.69,
        "top_p": 0.85,
        "requests_per_minute": 10,
        "enabled": False,
        "weight": 3,
    },
}

# Category to preferred provider (tried first, then weight order)
CATEGORY_PREFERRED = {
    "HOT": "blockrun",
    "ALPHA": "blockrun",
    "GAINERS": "blockrun",
    "LOSERS": "blockrun",
}

# ========== POST MODE ==========
POST_MODE = "rebate"

# ========== PIPELINE SETTINGS ==========
COLLECTOR_INTERVAL = 60      # seconds between fetches
PROCESSOR_WORKERS = 1        # number of processor threads
DAILY_POST_LIMIT = 10        # operator target: max 10/day (Binance API ceiling is 100)

# ========== DEDUPLICATION ==========
DEDUP_TTL_HOURS = 12         # hours before token can repeat in same category

# ========== COINGECKO CONFIG ==========
COINGECKO_ENABLED = True
COINGECKO_CACHE_TTL = 300    # seconds
COINGECKO_RATE_LIMIT_SECONDS = 6

# ========== RSS NEWS CONFIG ==========
RSS_ENABLED = True
RSS_MAX_ARTICLES_PER_SOURCE = 5
RSS_REFRESH_INTERVAL = 120   # seconds (3 sumber x tiap 2 mnt = ~90 req/jam, aman untuk RSS)

# ========== CLASSIFICATION THRESHOLDS ==========
# HOT: low perform, kurangi porsi
HOT_VOLUME_RANK_MAX = 30
HOT_PRICE_CHANGE_MAX = 1.5

# GAINERS/LOSERS
GAINER_THRESHOLD = 3.0
LOSER_THRESHOLD = -3.0

# ALPHA: fokus utama (perbesar threshold)
ALPHA_MAX_MCAP = 5_000_000
ALPHA_MIN_VOLUME = 50_000

# ========== SCORING WEIGHTS ==========
# Used by processors/score.py total_score(). Weights sum to 1.0.
MOMENTUM_WEIGHT = 0.25
ANOMALY_WEIGHT = 0.30
WALLET_WEIGHT = 0.20
LIQUIDITY_WEIGHT = 0.15
FRESHNESS_WEIGHT = 0.10

# Minimum score to generate a post (see processors/score.py score_token).
# Calibrated on sample tokens: HOT ~0.63, GAINERS ~0.43, ALPHA ~0.38,
# new listing ~0.53, junk low-volume flat ~0.30 (rejected).
MIN_TOTAL_SCORE = 0.35
MIN_PRIMARY_SCORE = 0.60

# ========== COOLDOWN CONFIG ==========
# Single source of truth — processors/dedupe.py imports these.
# Values are the ones dedupe.py actually ran with (its own copies
# differed: 3h/5h/8h/12h here vs 4h/8h/24h there).
# Market cap tiers (in USD)
MARKET_CAP_TIERS = [
    (10_000_000_000, 4 * 3600),   # > $10B → 4 jam
    (1_000_000_000, 8 * 3600),    # > $1B → 8 jam
    (0, 24 * 3600),               # default → 24 jam
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

# ========== QUEUE MANAGEMENT ==========
MAX_PERSISTENT_QUEUE_SIZE = 200
POST_EXPIRY_HOURS = 2
TOKEN_EXPIRY_HOURS = 24
MIN_POST_INTERVAL_SECONDS = 10

# ========== SIMILARITY ==========
SIMILARITY_THRESHOLD = 0.65

# ========== DAILY TARGET ==========
DAILY_POST_TARGET = 10  # soft limit (generation stops here; hard limit above is the backstop)

# ========== CLOSER SETTINGS ==========
CLOSER_ENABLED = False  # True untuk aktif, False untuk mati
