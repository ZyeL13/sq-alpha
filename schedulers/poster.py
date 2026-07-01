# schedulers/poster.py — Stable poster with daily limit
import time
import requests
import re
import sys
import os
import logging  # TAMBAHKAN

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, BINANCE_SQUARE_KEY, BINANCE_SQUARE_URL
from storage.post_counter import can_post, increment_post_counter, get_today_posts, DAILY_POST_LIMIT
from utils.performance_logger import log_post


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Setup audit logger
audit_logger = logging.getLogger('post_audit')
if not audit_logger.handlers:
    audit_handler = logging.FileHandler('logs/post_audit.log')
    audit_handler.setFormatter(logging.Formatter('%(asctime)s|%(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
    audit_logger.addHandler(audit_handler)

# Global flag to prevent multiple shutdown messages
_shutdown_done = False


def clean_for_square(text: str) -> str:
    """Clean content for Binance Square API"""
    if not text:
        return ""
    
    # Remove markdown characters that might cause issues
    text = text.replace('*', '')
    text = text.replace('_', '')
    text = text.replace('`', '')
    text = text.replace('>', '')
    text = text.replace('<', '')
    text = text.replace('#', '')
    text = text.replace('—', '')

    # Remove multiple newlines (max 2)
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    # Remove trailing/leading spaces
    text = text.strip()
    
    # Limit length (Square max ~1000 chars)
    if len(text) > 900:
        text = text[:900]
    
    return text


def shutdown_if_limit_reached():
    """Shutdown gracefully if daily limit reached"""
    global _shutdown_done
    if _shutdown_done:
        return
    
    if not can_post():
        _shutdown_done = True
        print(f"\n  🛑 DAILY LIMIT REACHED: {get_today_posts()}/{DAILY_POST_LIMIT} posts to Square")
        print("  📅 Reset at midnight")
        print("  💤 Shutting down pipeline...\n")
        sys.exit(0)


def post_to_telegram(text, category):
    """Send post to Telegram channel (optional, not counted)"""
    label_map = {
        "HOT": "🔥 HOT", 
        "GAINERS": "🚀 GAINERS", 
        "LOSERS": "📉 LOSERS",
        "ALPHA": "🐺 ALPHA",
    }
    label = label_map.get(category, category)
    full = f"✍️ *yè writing... - {label}*\n\n{text}"
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    
    for attempt in range(2):
        try:
            r = requests.post(url, json={
                "chat_id": TELEGRAM_CHAT_ID, 
                "text": full, 
                "parse_mode": "Markdown"
            }, timeout=15)
            
            if r.status_code == 200:
                return True
            else:
                print(f"  ⚠️ Telegram attempt {attempt+1}: HTTP {r.status_code}")
                time.sleep(2)
        except Exception as e:
            print(f"  ⚠️ Telegram attempt {attempt+1}: {e}")
            time.sleep(2)
    
    return False


def post_to_square(content):
    """Send post to Binance Square (THIS IS WHAT COUNTS)"""
    if not BINANCE_SQUARE_KEY or not BINANCE_SQUARE_URL:
        print("  ⚠️ Square not configured, skipping")
        return False
    
    # Check limit BEFORE posting
    shutdown_if_limit_reached()
    
    # Clean content
    cleaned = clean_for_square(content)
    if len(cleaned) < 20:
        print("  ⚠️ Content too short for Square")
        return False
    
    headers = {
        "X-Square-OpenAPI-Key": BINANCE_SQUARE_KEY, 
        "Content-Type": "application/json",
        "clienttype": "binanceSkill"
    }
    
    payload = {"bodyTextOnly": cleaned}
    
    try:
        r = requests.post(BINANCE_SQUARE_URL, headers=headers, json=payload, timeout=15, verify=False)
        
        if r.status_code == 200:
            result = r.json()
            if result.get("success"):
                share_link = result.get("data", {}).get("shareLink", "")
                print(f"  ✅ Square posted: {share_link[:60]}...")
                return True
            else:
                error_code = result.get("code")
                print(f"  ⚠️ Square error {error_code}")
                
                # 220009 = daily limit reached
                if error_code == "220009":
                    audit_logger.info(f"SQUARE_LIMIT|{get_today_posts()}/{DAILY_POST_LIMIT}")
                    shutdown_if_limit_reached()
                return False
        else:
            print(f"  ⚠️ Square HTTP {r.status_code}")
            return False
            
    except Exception as e:
        print(f"  ❌ Square exception: {e}")
        return False


def post_to_targets(content, category, symbol=None, hook=None, angle=None, session=None, llm_provider=None):
    """
    Post content to all platforms.
    Counter ONLY increments if Square post succeeds.
    """
    # Check limit before anything
    shutdown_if_limit_reached()
    
    today_posts = get_today_posts()
    remaining = DAILY_POST_LIMIT - today_posts
    print(f"  📊 Square posts today: {today_posts}/{DAILY_POST_LIMIT} (remaining: {remaining})")
    
    # Post to Telegram (optional, not counted)
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        if post_to_telegram(content, category):
            print("  ✅ Telegram posted (not counted)")
        else:
            print("  ⚠️ Telegram failed")
    
    time.sleep(1)
    
    # Post to Square (counts toward limit)
    square_success = False
    if BINANCE_SQUARE_KEY and BINANCE_SQUARE_URL:
        square_success = post_to_square(content)
        if square_success:
            print("  ✅ Square posted (COUNTED)")
            increment_post_counter()
            
            # AUDIT LOG: Post berhasil ke Square
            audit_logger.info(f"SQUARE_POSTED|{symbol}|{category}|{hook}|{session}")
            
            # Log performance data if symbol provided
            if symbol:
                try:
                    log_post(
                        symbol=symbol,
                        category=category,
                        hook=hook or "",
                        angle=angle or "",
                        session=session or "",
                        post_content=content,
                        llm_provider=llm_provider or "",
                        post_id=f"{symbol}_{int(time.time())}"
                    )
                except Exception as e:
                    print(f"  ⚠️ Failed to log post: {e}")
            
            return True
        else:
            print("  ❌ Square failed (not counted)")
            audit_logger.warning(f"SQUARE_FAILED|{symbol}|{category}")
            return False
    else:
        print("  ⚠️ Square not configured")
        return False
