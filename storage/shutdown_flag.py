# storage/shutdown_flag.py
_shutdown = False

def set_shutdown():
    global _shutdown
    _shutdown = True

def is_shutdown() -> bool:
    return _shutdown
