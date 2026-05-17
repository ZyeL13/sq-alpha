```markdown
# Binance Square Auto Poster

Crypto content generator pipeline untuk posting otomatis ke Binance Square + Telegram.  
Dirancang untuk 100+ posts/hari dengan gaya rebate/human-like.

## 🚀 Fitur

- **6 Kategori**: HOT, GAINERS, LOSERS, ALPHA, NEW, SIGNAL
- **Multi-LLM**: OpenRouter, Groq, Blockrun (auto fallback & load balancing)
- **Daily Limit**: 100 post/hari (sesuai batas API Binance)
- **Pipeline Architecture**: Collector → Processor → Generator → Poster
- **Quality Gate**: Deteksi reasoning leak, banned phrases, similarity check
- **Style Randomization**: Hook, angle, CTA bervariasi
- **Cache**: LLM response cache (kurangi hit API)

## 📁 Struktur Project

```

binance/
├── collectors/           # Data fetcher
│   ├── binance.py       # Binance spot + new listings
│   ├── alpha_discovery.py  # Alpha Discovery (disabled)
│   ├── gecko.py         # GeckoTerminal (disabled)
│   └── news.py          # RSS news
│
├── processors/          # Data processing
│   ├── normalize.py     # Normalize token data
│   ├── score.py         # Scoring engine
│   ├── classify.py      # Route token to category
│   ├── dedupe.py        # Token memory (TTL 12h)
│   └── filters.py
│
├── generators/          # Content generation
│   ├── post_generator.py   # LLM prompt builder
│   ├── quality_gate.py     # Reject reasoning leaks
│   └── style_guard.py      # Anti-template, banned phrases
│
├── schedulers/          # Pipeline orchestration
│   ├── orchestrator.py     # Main pipeline (multithread)
│   ├── poster.py           # Telegram + Square poster
│   └── timing.py           # Weighted posting windows
│
├── storage/             # Persistence
│   ├── cache.py         # LLM response cache
│   ├── post_counter.py  # Daily post counter
│   └── shutdown_flag.py
│
├── prompts/             # System prompts
│   ├── rebate.py        # Main system prompt
│   └── styles.py        # Hooks, angles, CTAs
│
├── data/                # Legacy (migration in progress)
├── config.py            # Central configuration
├── llm.py               # Multi-provider LLM interface
├── main.py              # Entry point
└── *.json               # Cache files (auto-generated)

```

## 🔧 Instalasi

```bash
# Clone repo
git clone https://github.com/your-repo/binance.git
cd binance

# Install dependencies
pip install requests python-dotenv

# Copy environment template
cp .env.example .env
# Edit .env with your API keys
```

⚙️ Konfigurasi

Edit config.py:

```python
# LLM Provider (openrouter / groq / blockrun)
LLM_PROVIDER = "openrouter"

# Daily post limit (Binance Square = 100)
DAILY_POST_LIMIT = 100

# Number of processor workers
PROCESSOR_WORKERS = 2

# Post Mode
POST_MODE = "rebate"
```

🚀 Menjalankan

```bash
# Test single post
python main.py test

# Run full pipeline
python main.py pipeline

# Help
python main.py
```

📊 Daily Limit

Bot akan shutdown otomatis setelah mencapai 100 post ke Binance Square.
Counter reset setiap hari pukul 00:00 WIB.

🧠 LLM Provider

Provider Model Status
OpenRouter free (auto-routing) ✅ Stable
Groq llama-3.3-70b-versatile ⚠️ Rate limit
Blockrun free/deepseek-v3.2 ⚠️ Local proxy needed

📝 Output Style (Rebate)

· Lowercase except $SYMBOL
· 3-4 short paragraphs
· Hook + angle + insight + soft CTA
· No labels, no hashtags, no marketer hype

⚠️ Troubleshooting

Square error 220009: Daily limit reached — bot akan shutdown otomatis.

Reasoning leak di output: Quality gate akan reject dan retry.

Rate limit Groq: Switch ke OpenRouter atau kurangi PROCESSOR_WORKERS.

📄 License

Internal use only.

👤 Author

yè

```

