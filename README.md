# Binance Square Auto Poster

Crypto content generator for Binance Square + Telegram.

## Active Categories
- 🔥 HOT (top volume, small move)
- 🚀 GAINERS (up ≥ 3%)
- 📉 LOSERS (down ≤ −3%)
- 🐺 ALPHA (small cap, market cap < $5M and volume > $50k)

## LLM Providers
- **Groq (primary, free plan)** — `openai/gpt-oss-120b`
- **DeepSeek (fallback, pay per token)** — `deepseek-flash`

Both need API keys in `.env` (see `.env.example`).

## Market-cap enrichment (ALPHA)
Binance data has no market cap, so tokens are enriched before
classification: CoinGecko first (one cached top-250 call per cycle),
CoinMarketCap as an optional fallback when `CMC_API_KEY` is set.
A token with unknown market cap is never classified as ALPHA.

## Scoring
Every token is scored before a post is generated (`processors/score.py`).
A post is generated when the weighted total is ≥ 0.35, or the
category's primary signal is ≥ 0.60. Weak tokens are skipped and
logged as `SCORE_REJECTED`.

## Daily Limit
100 posts/day (Binance Square limit). When the limit is reached the
pipeline sleeps until the reset at **07:00 WIB** and then resumes —
it does not shut down.

## Installation
```bash
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your API keys
```

## Usage
```bash
python main.py test      # test one post
python main.py pipeline  # run full pipeline
```

## Tests
```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -q
```

## Configuration
Edit `config.py` for thresholds, LLM providers, scoring weights,
daily limit, etc.
