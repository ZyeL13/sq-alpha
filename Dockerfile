# sq-alpha — Binance Square auto-poster
# Satu container menjalankan seluruh pipeline (collector + processor + poster
# adalah thread di dalam satu proses `python main.py pipeline`).
# State (antrean, dedupe, counter, cache, log) tinggal di volume, bukan di image.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Jakarta

# tzdata: ZoneInfo("Asia/Jakarta") di config.py butuh database zona waktu.
# fonts-dejavu-core: DejaVu Sans untuk card renderer V3 (Pillow tidak
# membawa font TTF; tanpa ini renderer jatuh ke font default PIL).
# curl: mengambil font Kalam di bawah (python:3.12-slim tidak punya curl).
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata fonts-dejavu-core curl \
    && rm -rf /var/lib/apt/lists/*

# Kalam handwriting font untuk gaya kartu sketchnote (SIL OFL). Tidak
# ada paket Debian bookworm yang menyediakannya, jadi TTF diambil dari
# repo google/fonts saat build (URL terverifikasi 2026-11-16 mengembalikan
# file yang sama dengan yang dipakai mockup Fase 2; build Docker-nya
# sendiri BELUM terverifikasi sampai jalan di VPS). Kalau fetch gagal,
# build gagal (curl -f) daripada image tanpa font; di runtime renderer
# tetap jatuh ke DejaVu kalau Kalam tidak ada.
RUN mkdir -p /usr/share/fonts/truetype/kalam \
    && curl -fL --retry 2 -o /usr/share/fonts/truetype/kalam/Kalam-Regular.ttf \
        https://raw.githubusercontent.com/google/fonts/main/ofl/kalam/Kalam-Regular.ttf \
    && curl -fL --retry 2 -o /usr/share/fonts/truetype/kalam/Kalam-Bold.ttf \
        https://raw.githubusercontent.com/google/fonts/main/ofl/kalam/Kalam-Bold.ttf

WORKDIR /app

# Install dependency dulu (layer ini ke-cache kalau requirements.txt tidak berubah).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# .env TIDAK di-copy (lihat .dockerignore). Isi lewat env_file di compose
# atau --env-file saat `docker run`. Jangan pernah commit .env.
CMD ["python", "main.py", "pipeline"]
