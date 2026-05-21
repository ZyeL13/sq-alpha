# logging_config.py
import logging
import os
from datetime import datetime

# Buat folder logs jika belum ada
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

# Nama file log berdasarkan tanggal
LOG_FILE = f"{LOG_DIR}/pipeline_{datetime.now().strftime('%Y%m%d')}.log"

# Format log
LOG_FORMAT = '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s'
DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

def setup_logging(level=logging.INFO):
    """Setup logging to file and console"""
    
    # Konfigurasi root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    
    # Handler untuk file
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
    
    return root_logger

def get_logger(name):
    """Get logger for specific module"""
    return logging.getLogger(name)
