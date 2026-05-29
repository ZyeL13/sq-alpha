# schedulers/orchestrator.py
import time
import random
import threading
from queue import Queue, Empty
from datetime import datetime

from collectors.binance import fetch_all_binance, fetch_new_listings
from collectors.rss_news import fetch_all_news, get_catalyst_summary
from processors.normalize import normalize_token
from processors.classify import classify
from processors.dedupe import is_duplicate, mark_posted, clear_old_entries
from generators.post_generator import generate_post
from schedulers.poster import post_to_targets
from config import PROCESSOR_WORKERS
from schedulers.timing import get_post_delay, get_current_session, get_dynamic_post_limit
from storage.post_counter import can_post, DAILY_POST_LIMIT, get_today_posts, get_seconds_until_reset
import logging_config
from storage.persistent_queue import PersistentQueue
from storage.scheduled_post_queue import ScheduledPostQueue

logger = logging_config.get_logger("orchestrator")
data_queue = PersistentQueue()
stop_flag = threading.Event()
_shutdown = False

# News cache
_news_cache = []
_last_news_refresh = 0
NEWS_REFRESH_INTERVAL = 600  # 10 minutes


def check_and_sleep():
    """Check if daily limit reached, sleep until reset instead of shutdown"""
    global _shutdown
    if not _shutdown and not can_post():
        _shutdown = True
        seconds_until_reset = get_seconds_until_reset()
        hours = seconds_until_reset // 3600
        minutes = (seconds_until_reset % 3600) // 60
        
        print(f"\n  🛑 DAILY LIMIT REACHED: {get_today_posts()}/{DAILY_POST_LIMIT}")
        print(f"  📅 Reset in {hours}h {minutes}m (7 AM WIB)")
        print(f"  💤 Sleeping {hours}h {minutes}m until reset...\n")
        
        # Sleep until reset (7 AM WIB)
        time.sleep(seconds_until_reset)
        
        # Reset setelah bangun
        from storage.post_counter import reset_counter
        reset_counter()
        
        # Reset shutdown flag
        _shutdown = False
        print(f"  🌅 New day! Resuming pipeline...\n")
        
        # Reset stop_flag agar workers bisa lanjut
        stop_flag.clear()
    
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
            if check_and_sleep():
                break

            refresh_news_cache()
            binance_tokens = fetch_all_binance(limit=200)
            new_listings = fetch_new_listings()

            for token in binance_tokens:
                full_symbol = token.get("full_symbol", "")
                symbol = token.get("symbol", "")
                token["age_hours"] = 12 if full_symbol in new_listings else 100
                
                catalyst = get_catalyst_summary(symbol, _news_cache)
                if catalyst:
                    token["news_catalyst"] = catalyst

            queued = 0
            for token in binance_tokens:
                if not check_and_sleep():
                    data_queue.put("binance", token)
                    queued += 1

            logger.info(f"Fetched {len(binance_tokens)} Binance tokens, queued {queued}")
            print(f"  📰 News cache age: {int(time.time() - _last_news_refresh)}s, {len(_news_cache)} articles")

            clear_old_entries()
            time.sleep(60)

        except Exception as e:
            logger.error(f"Collector error: {e}")
            time.sleep(30)


def processor_worker(worker_id: int):
    """Process tokens: normalize → classify → generate → schedule post"""
    print(f"  🧠 Processor {worker_id} started")
    
    from prompts.styles import get_hook
    scheduled_queue = ScheduledPostQueue()
    
    while not stop_flag.is_set():
        try:
            if check_and_sleep():
                break
            
            item = data_queue.get(timeout=5)
            if item is None:
                time.sleep(1)
                continue
            
            source, raw = item
            token = normalize_token(raw, source=source)
            cat = classify(token)
            
            if cat and can_post():
                try:
                    hook = get_hook(cat) or "default"
                    market_cap = token.get("market_cap", 0)
                    
                    if is_duplicate(token["symbol"], cat, market_cap, hook):
                        continue
                    
                    if "news_catalyst" in raw:
                        token["news_catalyst"] = raw["news_catalyst"]
                    
                    post = generate_post(token, cat, {})
                    if post:
                        current_time = time.time()
                        scheduled_queue = ScheduledPostQueue()
    
                        # Get LAST post time (not next)
                        last_time = scheduled_queue.get_last_post_time()
    
                        if last_time and last_time > current_time:
                            # Queue has future posts, schedule after the last one + delay
                            scheduled_time = last_time + get_post_delay()
                            print(f"  📅 Last post at {last_time:.0f}, scheduling +{get_post_delay()}s")
                        else:
                            # Queue empty or all posts past, schedule now + delay
                            scheduled_time = current_time + get_post_delay()
                            print(f"  📅 Queue empty, scheduling in {get_post_delay()}s")
    
                        session = get_current_session()
    
                        scheduled_queue.add_post(
                            post=post,
                            category=cat,
                            symbol=token["symbol"],
                            scheduled_time=scheduled_time,
                            hook=hook,
                            session=session,
                            provider="blockrun"
                        )
    
                        mark_posted(token["symbol"], cat, hook, market_cap)
    
                        wait_min = (scheduled_time - current_time) / 60
                        print(f"  ✍️ P{worker_id}: {token['symbol']} → {cat} scheduled in {wait_min:.1f} min")
                        time.sleep(random.uniform(2, 5))
                    else:
                        print(f"  ⚠️ P{worker_id}: {token['symbol']} → {cat} (no post)")
                        
                except Exception as inner_e:
                    print(f"  ⚠️ P{worker_id}: Error processing {token.get('symbol', '?')}: {inner_e}")
                    continue
            
            time.sleep(random.uniform(0.5, 1))
            
        except Exception as e:
            print(f"  ❌ P{worker_id} error: {e}")
            time.sleep(1)


def poster_worker():
    """Post scheduled posts when they are due"""
    print("  📤 Poster started (waiting for scheduled posts...)")
    
    scheduled_queue = ScheduledPostQueue()
    
    while not stop_flag.is_set():
        try:
            if check_and_sleep():
                break
            
            due_posts = scheduled_queue.get_due_posts(limit=1)
            
            if not due_posts:
                next_time = scheduled_queue.get_next_post_time()
                if next_time:
                    wait_time = max(1, next_time - time.time())
                    print(f"  ⏳ Next scheduled post in {wait_time:.0f}s")
                    time.sleep(min(wait_time, 30))
                else:
                    time.sleep(10)
                continue
            
            for post_id, post, cat, sym, hook, session, provider in due_posts:
                if not can_post():
                    check_and_sleep()
                    break
                
                print(f"  📝 Posting {sym} as {cat}...")
                success = post_to_targets(
                    content=post,
                    category=cat,
                    symbol=sym,
                    hook=hook,
                    session=session,
                    llm_provider=provider
                )
                
                if success:
                    mark_posted(sym, cat)
                    print(f"  ✅ {sym} posted")
                else:
                    print(f"  ❌ {sym} failed to post")
                
                scheduled_queue.remove_post(post_id)
                check_and_sleep()
            
            time.sleep(2)
            
        except Exception as e:
            print(f"  ❌ Poster error: {e}")
            time.sleep(5)


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
