# main.py
import sys
import signal
from config import POST_MODE

print(f"📝 Post Mode: {POST_MODE}")

def signal_handler(sig, frame):
    print("\n🛑 Shutting down...")
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

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
        else:
            print("Usage: python main.py [pipeline|test]")
    else:
        print("Usage: python main.py [pipeline|test]")
