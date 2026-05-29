# monitor/simple.py - Minimal dot progress indicator
import time
import threading
import sys

class DotMonitor:
    def __init__(self, interval=10):
        self.interval = interval
        self.running = False
        self.last_activity = time.time()
    
    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
    
    def stop(self):
        self.running = False
    
    def _run(self):
        dot_count = 0
        while self.running:
            time.sleep(self.interval)
            dot_count += 1
            # Print dot every interval, newline every 60 dots
            sys.stdout.write('.')
            sys.stdout.flush()
            
            if dot_count % 60 == 0:
                sys.stdout.write(f' {dot_count//60}m\n')
                sys.stdout.flush()
    
    def activity(self):
        """Call this when something happens (post, error, etc)"""
        self.last_activity = time.time()

# Singleton
_monitor = None

def start_dot_monitor(interval=10):
    global _monitor
    _monitor = DotMonitor(interval)
    _monitor.start()
    return _monitor

def log_activity():
    if _monitor:
        _monitor.activity()
