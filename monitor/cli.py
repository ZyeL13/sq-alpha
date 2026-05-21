# monitor/cli.py
import os
import time
import threading
import sys
from datetime import datetime

# Tambah path parent
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from storage.persistent_queue import PersistentQueue
from storage.post_counter import get_today_posts, DAILY_POST_LIMIT
from processors.dedupe import get_stats


def clear_screen():
    """Clear terminal screen"""
    os.system('clear' if os.name == 'posix' else 'cls')


def format_time(seconds: int) -> str:
    """Format seconds to HH:MM:SS"""
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def get_uptime(start_time: float) -> str:
    """Get formatted uptime"""
    elapsed = int(time.time() - start_time)
    return format_time(elapsed)


def monitor_worker(stop_flag: threading.Event, start_time: float):
    """Monitor thread to display pipeline status"""
    queue = PersistentQueue()
    
    while not stop_flag.is_set():
        clear_screen()
        
        # Get statistics
        today_posts = get_today_posts()
        remaining = DAILY_POST_LIMIT - today_posts
        queue_stats = queue.get_stats()
        dedup_stats = get_stats()
        
        # Calculate progress bar
        progress = int((today_posts / DAILY_POST_LIMIT) * 30)
        bar = "█" * progress + "░" * (30 - progress)
        
        print(f"""
╔══════════════════════════════════════════════════════════════════╗
║                       PIPELINE MONITOR                           ║
╠══════════════════════════════════════════════════════════════════╣
║  🕐 Uptime:     {get_uptime(start_time)}                                                 
║  📅 Date:       {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}                                     
╠══════════════════════════════════════════════════════════════════╣
║  📊 POSTS                                                       ║
║     Today:      {today_posts:>3}/{DAILY_POST_LIMIT} ({bar})                         
║     Remaining:  {remaining:>3}                                                         
╠══════════════════════════════════════════════════════════════════╣
║  📦 QUEUE                                                       ║
║     Total:      {queue_stats['total']:>5} items                                                
║     Oldest:     {queue_stats['oldest'][:16] if queue_stats['oldest'] else 'N/A'}                             
╠══════════════════════════════════════════════════════════════════╣
║  💾 DEDUP                                                       ║
║     Records:    {dedup_stats.get('posted_entries', 0):>5}                                                
║     Cooldown:   {dedup_stats.get('cooldown_entries', 0):>5} tokens                                          
╠══════════════════════════════════════════════════════════════════╣
║  🎯 TARGET                                                     ║
║     Daily:      70 posts (soft limit)                                          
╚══════════════════════════════════════════════════════════════════╝

Press Ctrl+C to exit monitor
""")
        
        time.sleep(5)  # Update every 5 seconds


def start_monitor(stop_flag: threading.Event, start_time: float):
    """Start monitor in separate thread"""
    monitor_thread = threading.Thread(
        target=monitor_worker,
        args=(stop_flag, start_time),
        daemon=True
    )
    monitor_thread.start()
    return monitor_thread


if __name__ == "__main__":
    # Test monitor standalone
    stop_flag = threading.Event()
    try:
        start_monitor(stop_flag, time.time())
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n👋 Monitor stopped")
