# Binance Square Auto Poster

Crypto content generator for Binance Square + Telegram.

## Active Categories
- 🔥 HOT (top volume, small move)
- 🚀 GAINERS (up ≥ 3%)
- 📉 LOSERS (down ≤ −3%)
- 🐺 ALPHA (small cap, market cap < $5M and volume > $50k)

## LLM Providers
Priority: **BlockRun models → Groq**. DeepSeek and NVIDIA NIM are
disabled; providers with an empty API key are skipped automatically.
A provider that returns HTTP 404/410 (dead model) is skipped without
retry and disabled until the process restarts. Each request times out
after 30 seconds.

- **BlockRun (free)** — local ClawRouter proxy, three entries sharing
  one proxy: `free/deepseek-v4-flash`, then `free/llama-4-maverick`,
  then `free/mistral-large-3-675b` (exact IDs from the proxy's
  `/v1/models` output — `free` alone is not a valid model ID).
  The proxy must be running on the host (port 8402); make it
  permanent with pm2/systemd. Inside Docker it is reached via
  `host.docker.internal` (see `docker-compose.yml`); `127.0.0.1`
  inside the container is the container itself, not the host, so
  pointing the bot at `127.0.0.1:8402` from Docker fails with
  "Connection refused".
- **Groq (free plan)** — `openai/gpt-oss-120b`. Reasoning model:
  `reasoning_effort=low` + `max_tokens=1800` so its reasoning does
  not eat the whole token budget and return empty content;
  `include_reasoning=false` keeps the reasoning trace out of replies.
- **NVIDIA NIM (off)** — `meta/llama-3.3-70b-instruct` retired
  2026-08-26 (HTTP 410 Gone). No replacement has been verified live
  yet — list the live models with
  `curl https://integrate.api.nvidia.com/v1/models -H "Authorization: Bearer $NVIDIA_NIM_API_KEY"`,
  set `model` to an ID from that output, and re-enable it.
- **DeepSeek (off)** — `deepseek-flash`, pay per token. Re-enable in
  `config.py` after topping up.

API keys go in `.env` (see `.env.example`).

Live model test (dry-run, never posts): `python scripts/test_llm_models.py`
generates 10 posts per live provider from sample market data and prints
success rate + latency side by side.

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

## News
Market news is attached to tokens as a catalyst for the post
(`collectors/rss_news.py`).

- **Sources (RSS):** CoinDesk, CoinTelegraph, Decrypt (weight 1.0) and
  The Block, CryptoSlate (weight 1.5 — crypto-native outlets with
  original reporting). There is no official Binance announcements RSS,
  so no announcement feed is included and announcement pages are not
  scraped. Cache refreshes every **120 seconds**, 5 articles per source.
- **Freshness:** timestamps are parsed from the feed (UTC). Articles
  older than **1 hour** are dropped — a post should go out within 1 hour
  of the event, not with yesterday's news.
- **Matching (score-based, threshold 2.0):** a symbol in the title
  scores 2.0, a full name/alias in the title 3.0; in the summary the
  same signals score 1.0 / 2.0. Latin symbols match on word boundaries
  (`$SOL` no longer matches "solution", `$ETH` no longer matches
  "tether"/"method"); non-Latin symbols such as `$币安人生` still match
  as substrings. Symbols that are also common English words (ONE, APT,
  SOL, …) score half as plain words — only their `$CASHTAG` form or
  full project name counts in full. Below threshold 2.0, no catalyst
  is attached.
- **Dedupe:** one article goes to exactly one token — the highest
  scoring one. Used articles are recorded in `cache/news_dedup.json`
  (24 h TTL) and are not attached again.
- **Price context:** when a catalyst is attached, the token's price
  and volume at that moment are snapshotted; the prompt compares them
  with the price/volume at generation time.
- **Review queue:** big news that matches no token (ETF, The Fed, SEC
  lawsuits, major hacks, …) is queued in `cache/news_review.json`
  (max 100 items) for manual review with a suggested cashtag. It is
  never auto-posted.

## Daily Limit
Max **10 posts/day** (hard limit and soft target are both 10 — the
Binance Square API ceiling of 100/day is not used; the bot was built
to test that ceiling, not to post that much). Consecutive posts are
scheduled **75–90 minutes apart** (80 min base ±15% jitter, chained
off the last scheduled post), so 10 posts fit a 07:30–23:30 WIB window.
When the limit is reached the pipeline sleeps until the reset at
**07:00 WIB** and then resumes — it does not shut down.

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

## Docker
One container runs the whole pipeline (collector, processor, and poster
are threads inside a single process).
```bash
cp .env.example .env   # fill in your API keys first
docker compose up -d --build
docker compose logs -f
```
State (queues, dedupe, post counter, cache, logs) lives in the
`./storage`, `./cache`, and `./logs` bind mounts, so it survives container
restarts. `.env` is passed via `env_file` and never copied into the image.

## Tests
```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -q
```

## Configuration
Edit `config.py` for thresholds, LLM providers, scoring weights,
daily limit, etc.
