#!/usr/bin/env python
# view_logs.py - Lihat log terbaru

import os
import sys
from datetime import datetime

log_dir = "logs"
if not os.path.exists(log_dir):
    print("No logs found")
    sys.exit(0)

# Cari file log terbaru
log_files = [f for f in os.listdir(log_dir) if f.startswith("pipeline_")]
if not log_files:
    print("No log files")
    sys.exit(0)

log_files.sort(reverse=True)
latest_log = os.path.join(log_dir, log_files[0])

# Tampilkan command yang bisa dijalankan
print(f"📋 Latest log: {latest_log}")
print("\nCommands:")
print(f"  cat {latest_log}              # view full log")
print(f"  tail -f {latest_log}          # follow log")
print(f"  grep ERROR {latest_log}       # show errors only")
print(f"  grep REJECTED {latest_log}    # show quality gate rejects")
