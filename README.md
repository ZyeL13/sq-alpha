# Binance Square Auto Poster

Crypto content generator for Binance Square + Telegram.

## Active Categories
- 🔥 HOT (volume anomaly)
- 🚀 GAINERS (up >7%)
- 📉 LOSERS (down >7%)
- 🐺 ALPHA (small cap)

## Installation
```bash
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your API keys

Usage

```bash
python main.py test      # test one post
python main.py pipeline  # run full pipeline
```

Configuration

Edit config.py for thresholds, LLM providers, daily limit, etc.

Daily Limit

100 posts/day (Binance Square limit). Auto shutdown when reached.

```
