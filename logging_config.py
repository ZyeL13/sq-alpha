# logging_config.py
import logging
import os
from datetime import datetime

# Buat folder logs jika belum ada
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

# Nama file log berdasarkan tanggal
LOG_FILE = f"{LOG_DIR}/pipeline_{datetime.now().strftime('%Y%m%d')}.log"
AUDIT_FILE = f"{LOG_DIR}/audit_{datetime.now().strftime('%Y%m%d')}.log"  # TAMBAHKAN

# Format log
LOG_FORMAT = '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s'
AUDIT_FORMAT = '%(asctime)s | %(message)s'  # Format sederhana untuk audit
DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

# Flag untuk inisialisasi
_logging_initialized = False
_audit_logger = None


def setup_logging(level=logging.INFO):
    """Setup logging to file and console"""
    global _logging_initialized
    
    if _logging_initialized:
        return logging.getLogger()
    
    # Konfigurasi root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    
    # Handler untuk file pipeline
    file_handler = logging.FileHandler(LOG_FILE, encoding='utf-8')
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
    root_logger.addHandler(file_handler)
    
    # Handler untuk console (tetap pakai print untuk user)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter('%(message)s'))
    root_logger.addHandler(console_handler)
    
    # Log awal
    root_logger.info("=" * 60)
    root_logger.info(f"Pipeline started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    root_logger.info("=" * 60)
    
    _logging_initialized = True
    return root_logger


def get_logger(name):
    """Get logger for specific module"""
    if not _logging_initialized:
        setup_logging()
    return logging.getLogger(name)


def get_audit_logger():
    """Get audit logger for post tracking (separate file)"""
    global _audit_logger
    
    if _audit_logger is None:
        _audit_logger = logging.getLogger('audit')
        _audit_logger.setLevel(logging.INFO)
        
        # Handler untuk file audit terpisah
        audit_handler = logging.FileHandler(AUDIT_FILE, encoding='utf-8')
        audit_handler.setFormatter(logging.Formatter(AUDIT_FORMAT, DATE_FORMAT))
        _audit_logger.addHandler(audit_handler)
        
        # Jangan propagasi ke root logger
        _audit_logger.propagate = False
    
    return _audit_logger


def log_audit(event_type: str, data: dict):
    """Helper untuk log audit dengan format terstruktur"""
    audit = get_audit_logger()
    
    # Format: TIMESTAMP|event_type|field1=value1|field2=value2
    parts = [event_type]
    for key, value in data.items():
        parts.append(f"{key}={value}")
    
    audit.info("|".join(parts))


def rotate_logs_if_needed(max_size_mb: int = 50):
    """Rotate log files if they exceed max size"""
    for log_file in [LOG_FILE, AUDIT_FILE]:
        if os.path.exists(log_file):
            size_mb = os.path.getsize(log_file) / (1024 * 1024)
            if size_mb > max_size_mb:
                backup_name = f"{log_file}.{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak"
                os.rename(log_file, backup_name)
                print(f"📦 Rotated {os.path.basename(log_file)} to {os.path.basename(backup_name)}")
