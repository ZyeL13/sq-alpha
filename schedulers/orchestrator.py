# schedulers/orchestrator.py
import time
import random
import threading
from queue import Queue
from datetime import datetime

from collectors.binance import fetch_all_binance, fetch_new_listings
from collectors.rss_news import fetch_all_news, get_catalyst_summary
from processors.normalize import normalize_token
from processors.classify import classify
from processors.dedupe import is_duplicate, mark_posted, clear_old_entries
from generators.post_generator import generate_post
from schedulers.poster import post_to_targets
from config import PROCESSOR_WORKERS
from schedulers.timing import get_post_delay, get_current_session
from storage.post_counter import can_post, DAILY_POST_LIMIT, get_today_posts

data_queue = Queue(maxsize=500)
post_queue = Queue(maxsize=100)
stop_flag = threading.Event()
_shutdown = False

# News cache
_news_cache = []
_last_news_refresh = 0
NEWS_REFRESH_INTERVAL = 300  # 5 minutes


def check_shutdown():
    global _shutdown
    if not _shutdown and not can_post():
        _shutdown = True
        seconds_until_reset = get_seconds_until_reset()
        hours = seconds_until_reset // 3600
        minutes = (seconds_until_reset % 3600) // 60
        print(f"\n  🛑 DAILY LIMIT REACHED: {get_today_posts()}/{DAILY_POST_LIMIT}")
        print(f"  📅 Reset in {hours}h {minutes}m (7 AM WIB)")
        print("  💤 Shutting down pipeline...\n")
        time.sleep(2)
        stop_flag.set()
    return _shutdown


def refresh_news_cache():
    """Refresh news cache if needed"""
    global _news_cache, _last_news_refresh
    now = time.time()
    if now - _last_news_refresh > NEWS_REFRESH_INTERVAL:
        print("  📰 Refreshing news cache...")
        _news_cache = fetch_all_news()
        _last_news_refresh = now
        print(f"  📰 News cache updated: {len(_news_cache)} articles")
    return _news_cache


def collector_worker():
    """Fetch tokens from Binance + refresh news cache"""
    print("  🧠 Collector started")
    
    while not stop_flag.is_set():
        try:
            if check_shutdown():
                break

            # Refresh news cache periodically
            refresh_news_cache()

            # Fetch Binance tokens
            binance_tokens = fetch_all_binance(limit=200)

            # Fetch new listings for age calculation
            new_listings = fetch_new_listings()

            # Add age_hours and news context to tokens
            for token in binance_tokens:
                full_symbol = token.get("full_symbol", "")
                symbol = token.get("symbol", "")
                
                # Age calculation
                token["age_hours"] = 12 if full_symbol in new_listings else 100
                
                # Add news catalyst summary if available
                catalyst = get_catalyst_summary(symbol, _news_cache)
                if catalyst:
                    token["news_catalyst"] = catalyst

            # Queue tokens
            queued = 0
            for token in binance_tokens:
                if not check_shutdown():
                    data_queue.put(("binance", token))
                    queued += 1

            print(f"  📡 Fetched {len(binance_tokens)} Binance tokens, queued {queued}")
            print(f"  📰 News cache age: {int(time.time() - _last_news_refresh)}s, {len(_news_cache)} articles")

            # Clean old dedup entries
            clear_old_entries()

            # Wait before next fetch
            time.sleep(60)

        except Exception as e:
            print(f"  ❌ Collector error: {e}")
            time.sleep(30)


def processor_worker(worker_id: int):
    """Process tokens: normalize → classify → generate"""
    print(f"  🧠 Processor {worker_id} started")
    
    while not stop_flag.is_set():
        try:
            if check_shutdown():
                break
            
            source, raw = data_queue.get(timeout=5)
            
            # Normalize
            token = normalize_token(raw, source=source)
            
            # Classify
            cat = classify(token)
            
            # Check duplicate and limit
            if cat and not is_duplicate(token["symbol"], cat) and can_post():
                # Pass news context to generator via token
                if "news_catalyst" in raw:
                    token["news_catalyst"] = raw["news_catalyst"]
                
                post = generate_post(token, cat, {})
                if post:
                    post_queue.put((post, cat, token["symbol"]))
                    print(f"  ✍️ P{worker_id}: {token['symbol']} → {cat}")
                    time.sleep(random.uniform(2, 5))  # Tambah delay 2-5 detik
                else:
                    print(f"  ⚠️ P{worker_id}: {token['symbol']} → {cat} (no post)")
            
            # Small delay
            time.sleep(random.uniform(0.5, 1))
            
        except Exception as e:
            if "Empty" not in str(e):
                print(f"  ❌ P{worker_id} error: {e}")
            time.sleep(1)


def poster_worker():
    print("  📤 Poster started (waiting for posts...)")
    
    while not stop_flag.is_set():
        try:
            if check_shutdown():
                break
            
            post, cat, sym = post_queue.get(timeout=5)
            
            if not can_post():
                check_shutdown()
                break
            
            print(f"  📝 Posting {sym} as {cat}...")
            success = post_to_targets(post, cat)
            
            if success:
                mark_posted(sym, cat)
                print(f"  ✅ {sym} posted")
            else:
                print(f"  ❌ {sym} failed to post")
            
            check_shutdown()
            
            if not stop_flag.is_set():
                delay = get_post_delay()
                print(f"  ⏳ Next post in {delay}s (session: {get_current_session()})")
                time.sleep(delay)
            
        except Exception as e:
            # Only show error if not empty queue (normal)
            if "Empty" not in str(e):
                print(f"  ⚠️ Poster waiting for posts... (queue empty)")
            time.sleep(1)


def run_orchestrator():
    """Start the full pipeline"""
    global _last_news_refresh, _news_cache
    
    print(f"\n{'='*50}")
    print(f"🚀 Starting Pipeline Orchestrator")
    print(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📊 Daily limit: {DAILY_POST_LIMIT} posts/day")
    print(f"📰 News refresh interval: {NEWS_REFRESH_INTERVAL}s")
    print(f"{'='*50}\n")
    
    # Initialize news cache
    _last_news_refresh = 0
    _news_cache = []
    refresh_news_cache()
    
    # Reset shutdown flag
    global _shutdown
    _shutdown = False
    
    # Start workers
    threading.Thread(target=collector_worker, daemon=True).start()
    
    for i in range(PROCESSOR_WORKERS):
        threading.Thread(target=processor_worker, args=(i+1,), daemon=True).start()
    
    threading.Thread(target=poster_worker, daemon=True).start()
    
    print("✅ All workers started. Press Ctrl+C to stop.\n")
    
    try:
        while not stop_flag.is_set():
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 Stopping orchestrator...")
        stop_flag.set()
        time.sleep(2)
        print("👋 Bye!")
