# storage/posts_csv.py — per-post experiment log (step 1).
#
# One row per scheduled post, written at schedule time (the
# commitment point). Columns: time_wib, symbol, angle, card_type,
# word_count, model, provider, prompt_version, views_1h, replies_1h,
# format, mode, hypothesis, variable_tested, views_6h, age_h,
# replies_24h. The views/replies columns are blank at write time;
# zyel fills them manually from the Square views harvest. The CSV is
# the human-filled experiment record; the audit logs stay machine
# text. Appended columns keep old rows' shape (new fields are
# empty on old rows).
# Header is written once (create-if-missing or empty file).
# POSTS_CSV_PATH is module-level so tests can point it at a tmp file.
import csv
import os
from datetime import datetime

from config import BASE_DIR, WIB

POSTS_CSV_PATH = os.path.join(BASE_DIR, "logs", "posts.csv")

COLUMNS = ["time_wib", "symbol", "angle", "card_type", "word_count",
           "model", "provider", "prompt_version", "views_1h", "replies_1h",
           "format", "mode", "hypothesis", "variable_tested",
           "views_6h", "age_h", "replies_24h"]


def append_post_row(*, symbol, angle, card_type, word_count, model,
                    provider, prompt_version, csv_path=None,
                    format="short", mode="", hypothesis="",
                    variable_tested="", views_6h="", age_h="",
                    replies_24h=""):
    """Append one row. Returns the path written. Best-effort: a
    logging failure must never break scheduling, so callers swallow
    exceptions from this function."""
    path = csv_path or POSTS_CSV_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    write_header = (not os.path.exists(path)
                    or os.path.getsize(path) == 0)
    with open(path, "a", newline="") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(COLUMNS)
        writer.writerow([
            datetime.now(WIB).strftime("%Y-%m-%d %H:%M:%S"),
            symbol,
            angle or "",
            card_type or "none",
            word_count,
            model or "",
            provider or "",
            prompt_version,
            "",
            "",
            format or "short",
            mode or "",
            hypothesis or "",
            variable_tested or "",
            views_6h,
            age_h,
            replies_24h,
        ])
    return path
