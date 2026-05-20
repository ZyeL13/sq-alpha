# main.py
import sys
import signal
from config import POST_MODE

print(f"📝 Post Mode: {POST_MODE}")

def signal_handler(sig, frame):
    print("\n🛑 Shutting down...")
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

def show_help():
    print("""
Usage: python main.py [COMMAND]

Commands:
  pipeline          Run full pipeline (collect -> classify -> post)
  test              Generate one test post
  cache-stats       Show cache statistics
  cache-clean       Remove invalid responses from cache
  cache-clear       Clear entire cache
  dedup-stats       Show deduplication statistics
  dedup-clear       Clear all deduplication records
  help              Show this help message
""")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        
        if cmd == "pipeline":
            from schedulers.orchestrator import run_orchestrator
            run_orchestrator()
        
        elif cmd == "test":
            from collectors.binance import fetch_all_binance
            from processors.normalize import normalize_token
            from processors.classify import classify
            from generators.post_generator import generate_post
            print("\n🧪 Test mode: generating one post...\n")
            tokens = fetch_all_binance(limit=50)
            for raw in tokens:
                token = normalize_token(raw)
                cat = classify(token)
                if cat:
                    post = generate_post(token, cat, {})
                    if post:
                        print(f"\n✅ {cat}: {token['symbol']}")
                        print("-" * 40)
                        print(post)
                        print("-" * 40)
                        break
                    else:
                        print(f"❌ Failed for {token['symbol']}")
        
        elif cmd == "cache-stats":
            from storage.cache import stats
            s = stats()
            print(f"\n📊 Cache Statistics:")
            print(f"   File: {s['file']}")
            print(f"   Total entries: {s['size']}")
            print(f"   Valid entries: {s.get('valid_count', 'N/A')}")
            print(f"   TTL: {s['ttl_seconds']} seconds")
        
        elif cmd == "cache-clean":
            from storage.cache import cleanup_invalid
            removed = cleanup_invalid()
            print(f"\n🧹 Removed {removed} invalid entries from cache")
        
        elif cmd == "cache-clear":
            from storage.cache import clear
            clear()
        
        elif cmd == "dedup-stats":
            from processors.dedupe import get_memory, get_stats
            mem = get_memory()
            stats = get_stats() if hasattr(get_memory(), 'get_stats') else {}
            print(f"\n📊 Deduplication Statistics:")
            print(f"   Posted records: {len(mem.posted)}")
            print(f"   Token cooldown records: {len(mem.last_post_time)}")
            print(f"   Cooldown: {stats.get('cooldown_seconds', 43200)} seconds ({stats.get('cooldown_seconds', 43200)//3600} hours)")
            print(f"   Category TTL: {stats.get('category_ttl', {})}")
        
        elif cmd == "dedup-clear":
            from processors.dedupe import get_memory
            mem = get_memory()
            mem.posted = {}
            mem.last_post_time = {}
            mem._save()
            print(f"\n🗑️ Cleared all deduplication records")
        
        elif cmd == "help" or cmd == "-h" or cmd == "--help":
            show_help()
        
        else:
            print(f"❌ Unknown command: {cmd}")
            show_help()
    
    else:
        show_help()
