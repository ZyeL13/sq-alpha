# sq-alpha — Binance Square auto-poster
# Satu container menjalankan seluruh pipeline (collector + processor + poster
# adalah thread di dalam satu proses `python main.py pipeline`).
# State (antrean, dedupe, counter, cache, log) tinggal di volume, bukan di image.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Jakarta

# tzdata: ZoneInfo("Asia/Jakarta") di config.py butuh database zona waktu.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependency dulu (layer ini ke-cache kalau requirements.txt tidak berubah).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# .env TIDAK di-copy (lihat .dockerignore). Isi lewat env_file di compose
# atau --env-file saat `docker run`. Jangan pernah commit .env.
CMD ["python", "main.py", "pipeline"]
