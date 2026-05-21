#!/usr/bin/env python
# manage_queue.py - Manage persistent queue

import sys
from storage.persistent_queue import PersistentQueue

def main():
    if len(sys.argv) < 2:
        print("Usage: python manage_queue.py [stats|clear]")
        return
    
    cmd = sys.argv[1]
    queue = PersistentQueue()
    
    if cmd == "stats":
        stats = queue.get_stats()
        print(f"\n📊 Persistent Queue Statistics:")
        print(f"   Total items: {stats['total']}")
        print(f"   Oldest: {stats['oldest']}")
        print(f"   Newest: {stats['newest']}")
    
    elif cmd == "clear":
        queue.clear()
        print("🗑️ Queue cleared")
    
    else:
        print(f"Unknown command: {cmd}")

if __name__ == "__main__":
    main()
