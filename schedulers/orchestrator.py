# schedulers/orchestrator.py — Stable pipeline
import time
import random
import threading
from queue import Queue
from datetime import datetime

from collectors.binance import fetch_all_binance, fetch_new_listings
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


def check_shutdown():
    """Check if we should shutdown due to daily limit"""
    global _shutdown
    if not _shutdown and not can_post():
        _shutdown = True
        print(f"\n  🛑 DAILY LIMIT REACHED: {get_today_posts()}/{DAILY_POST_LIMIT}")
        print("  📅 Reset at midnight")
        print("  💤 Shutting down pipeline...\n")
        time.sleep(2)
        stop_flag.set()
    return _shutdown


def collector_worker():
    """Fetch tokens from Binance only (stable)"""
    print("  🧠 Collector started")
    while not stop_flag.is_set():
        try:
            if check_shutdown():
                break
            
            # Fetch Binance tokens
            binance_tokens = fetch_all_binance(limit=200)
            
            # Fetch new listings for age calculation
            new_listings = fetch_new_listings()
            
            # Add age_hours to tokens
            for token in binance_tokens:
                full_symbol = token.get("full_symbol", "")
                token["age_hours"] = 12 if full_symbol in new_listings else 100
            
            # Queue tokens
            for token in binance_tokens:
                if not check_shutdown():
                    data_queue.put(("binance", token))
            
            print(f"  📡 Fetched {len(binance_tokens)} Binance tokens")
            
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
                post = generate_post(token, cat, {})
                if post:
                    post_queue.put((post, cat, token["symbol"]))
                    print(f"  ✍️ P{worker_id}: {token['symbol']} → {cat}")
                else:
                    print(f"  ⚠️ P{worker_id}: {token['symbol']} → {cat} (no post)")
            
            # Small delay
            time.sleep(random.uniform(0.5, 1))
            
        except Exception as e:
            if "Empty" not in str(e):
                print(f"  ❌ P{worker_id} error: {e}")
            time.sleep(1)


def poster_worker():
    """Post to Telegram and Square"""
    print("  📤 Poster started (waiting for posts...)")
    
    while not stop_flag.is_set():
        try:
            if check_shutdown():
                break
            
            post, cat, sym = post_queue.get(timeout=2)
            
            # Double-check limit before posting
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
            
            # Check limit again after posting
            check_shutdown()
            
            if not stop_flag.is_set():
                delay = get_post_delay()
                print(f"  ⏳ Next post in {delay}s (session: {get_current_session()})")
                time.sleep(delay)
            
        except Exception as e:
            if "Empty" not in str(e):
                print(f"  ❌ Poster error: {e}")
            time.sleep(1)


def run_orchestrator():
    """Start the full pipeline"""
    print(f"\n{'='*50}")
    print(f"🚀 Starting Pipeline Orchestrator")
    print(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📊 Daily limit: {DAILY_POST_LIMIT} posts/day")
    print(f"{'='*50}\n")
    
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
