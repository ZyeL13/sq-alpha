# schedulers/orchestrator.py (lengkap dengan logging audit)
import time
import random
import threading
from datetime import datetime
from collections import deque

from collectors.binance import fetch_all_binance, fetch_new_listings
from collectors.coingecko import enrich_tokens
from collectors.coinmarketcap import enrich_tokens_cmc
from collectors.rss_news import fetch_all_news, get_catalyst_summary
from processors.normalize import normalize_token
from processors.classify import classify
from processors.score import score_token
from processors.dedupe import is_duplicate, mark_posted, clear_old_entries
from generators.post_generator import generate_post
from schedulers.poster import post_to_targets
from config import PROCESSOR_WORKERS, COINGECKO_ENABLED, WIB
from schedulers.timing import get_post_delay, get_current_session
from storage.post_counter import can_post, DAILY_POST_LIMIT, get_today_posts, get_seconds_until_reset
import logging_config
from storage.persistent_queue import PersistentQueue
from storage.scheduled_post_queue import ScheduledPostQueue

logger = logging_config.get_logger("orchestrator")
data_queue = PersistentQueue()
stop_flag = threading.Event()
# Coordinates the daily-limit reset sleep: exactly one thread sleeps
# until the 07:00 WIB reset, the others wait for it (see check_and_sleep).
_reset_lock = threading.Lock()
_reset_in_progress = threading.Event()

# Setup audit logger
from logging_config import get_audit_logger
audit_logger = get_audit_logger()

# Rate limiter untuk poster
_post_times = deque(maxlen=10)

# News cache
_news_cache = []
_last_news_refresh = 0
NEWS_REFRESH_INTERVAL = 600  # 10 minutes


def can_post_now(min_interval: int = 10):
    """Check if we can post now (min_interval seconds between posts)"""
    now = time.time()
    if _post_times:
        last_post = _post_times[-1]
        if now - last_post < min_interval:
            return False, min_interval - (now - last_post)
    return True, 0


def check_and_sleep():
    """Check if the daily limit is reached; sleep until reset if so.

    Returns True if the caller should stop, False to keep working.
    When the limit is hit, exactly one thread sleeps until the 07:00 WIB
    reset; the other threads wait for that reset instead of exiting —
    the old _shutdown flag made every other thread break out of its
    loop permanently, so only the sleeping thread survived the reset.
    The sleep is interruptible: a stop request during the wait returns
    True immediately instead of being cleared away afterwards.
    """
    if can_post():
        return False

    with _reset_lock:
        owner = not _reset_in_progress.is_set()
        if owner:
            _reset_in_progress.set()

    if not owner:
        # Another thread is already sleeping until reset; wait for it.
        # Short wait timeout: clearing the event does not wake waiters,
        # so poll frequently instead of sleeping through the reset.
        while _reset_in_progress.is_set():
            if stop_flag.is_set():
                return True
            _reset_in_progress.wait(timeout=1)
        return False

    # This thread owns the reset sleep.
    seconds_until_reset = get_seconds_until_reset()
    hours = seconds_until_reset // 3600
    minutes = (seconds_until_reset % 3600) // 60

    print(f"\n  🛑 DAILY LIMIT REACHED: {get_today_posts()}/{DAILY_POST_LIMIT}")
    print(f"  📅 Reset in {hours}h {minutes}m (7 AM WIB)")
    print(f"  💤 Sleeping {hours}h {minutes}m until reset...\n")

    audit_logger.info(f"DAILY_LIMIT|{get_today_posts()}|sleep_{hours}h{minutes}m")

    stopped = stop_flag.wait(timeout=seconds_until_reset)
    if stopped:
        _reset_in_progress.clear()
        return True

    from storage.post_counter import reset_counter
    reset_counter()

    _reset_in_progress.clear()
    print("  🌅 New day! Resuming pipeline...\n")
    audit_logger.info("DAILY_RESET|resumed")
    return False


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

            # Enrich market caps (needed for ALPHA classification).
            # CoinGecko first (one cached call for the batch); CoinMarketCap
            # only fills symbols CoinGecko missed, and is a no-op without
            # CMC_API_KEY. Any failure leaves tokens unenriched — classify()
            # then simply skips ALPHA instead of misclassifying.
            try:
                if COINGECKO_ENABLED:
                    binance_tokens = enrich_tokens(binance_tokens)
                binance_tokens = enrich_tokens_cmc(binance_tokens)
            except Exception as e:
                logger.warning(f"Market-cap enrichment failed: {e}")

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
                    # Score gate: skip tokens whose signal is too weak to
                    # be worth a post (see processors/score.py).
                    scored = score_token(token, cat)
                    if not scored["passes"]:
                        print(f"  🚫 P{worker_id}: {token['symbol']} → {cat} "
                              f"(score too low: total={scored['total']:.2f}, "
                              f"primary={scored['primary']:.2f})")
                        audit_logger.info(
                            f"SCORE_REJECTED|{token['symbol']}|{cat}|"
                            f"total={scored['total']:.2f}|primary={scored['primary']:.2f}")
                        continue

                    hook = get_hook(cat) or "default"
                    market_cap = token.get("market_cap", 0)

                    if is_duplicate(token["symbol"], cat, market_cap, hook):
                        continue

                    if "news_catalyst" in raw:
                        token["news_catalyst"] = raw["news_catalyst"]

                    post = generate_post(token, cat, scored["scores"])
                    if post:
                        current_time = time.time()
                        scheduled_queue = ScheduledPostQueue()
                        
                        last_time = scheduled_queue.get_last_post_time()
                        
                        if last_time and last_time > current_time:
                            scheduled_time = last_time + get_post_delay()
                            print(f"  📅 Last post at {last_time:.0f}, scheduling +{get_post_delay()}s")
                        else:
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
                        
                        # AUDIT LOG: Post dijadwalkan
                        audit_logger.info(f"SCHEDULED|{token['symbol']}|{cat}|{hook}|{session}|{int(scheduled_time)}")
                        logger.info(f"POST_SCHEDULED: {token['symbol']} -> {cat} scheduled in {wait_min:.1f} min")
                        time.sleep(random.uniform(2, 5))
                    else:
                        print(f"  ⚠️ P{worker_id}: {token['symbol']} → {cat} (no post)")
                        # AUDIT LOG: Gagal generate
                        audit_logger.info(f"NO_POST|{token['symbol']}|{cat}|generate_failed")
                        
                except Exception as inner_e:
                    print(f"  ⚠️ P{worker_id}: Error processing {token.get('symbol', '?')}: {inner_e}")
                    audit_logger.info(f"ERROR|{token.get('symbol', '?')}|{cat}|{str(inner_e)[:50]}")
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
            
            # Rate limit check
            can_post_now_flag, wait_time = can_post_now(10)
            if not can_post_now_flag:
                print(f"  ⏳ Rate limit: waiting {wait_time:.0f}s...")
                time.sleep(wait_time)
                continue
            
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
                    _post_times.append(time.time())
                    # AUDIT LOG: Post berhasil
                    audit_logger.info(f"POSTED|{sym}|{cat}|{hook}|{session}|{provider}")
                    logger.info(f"POST_SUCCESS: {sym} -> {cat} posted successfully")
                else:
                    print(f"  ❌ {sym} failed to post")
                    # AUDIT LOG: Post gagal
                    audit_logger.info(f"FAILED|{sym}|{cat}|post_to_targets_failed")
                
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
    print("🚀 Starting Pipeline Orchestrator")
    print(f"📅 {datetime.now(WIB).strftime('%Y-%m-%d %H:%M:%S')} WIB")
    print(f"📊 Daily limit: {DAILY_POST_LIMIT} posts/day")
    print(f"📰 News refresh interval: {NEWS_REFRESH_INTERVAL}s")
    print(f"{'='*50}\n")
    
    audit_logger.info(f"PIPELINE_START|{datetime.now(WIB).strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Auto-clean queues
    print("  🧹 Auto-cleaning queues...")
    scheduled_queue = ScheduledPostQueue()
    deleted_posts = scheduled_queue.delete_old_posts(3600)  # 1 hour
    print(f"  🧹 Cleaned {deleted_posts} expired posts")
    
    deleted_tokens = data_queue.delete_old_entries(24)  # 24 hours
    print(f"  🧹 Cleaned {deleted_tokens} old token entries")
    
    # Initialize news cache
    _last_news_refresh = 0
    _news_cache = []
    refresh_news_cache()
    
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
        audit_logger.info("PIPELINE_STOP|keyboard_interrupt")
        stop_flag.set()
        time.sleep(2)
        print("👋 Bye!")
