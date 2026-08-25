# Railway bu Dockerfile'ı bulunca Nixpacks yerine bunu kullanır — PEP-621 pyproject'ten
# build planı üretemeyen Nixpacks'in sessiz "Deploy failed" sorununu tümden ortadan kaldırır.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

# Önce bağımlılıklar (katman önbelleği): kaynak değişse de wheel kurulumu tekrar çalışmaz.
#
# 🔴 KURULUM KAYNAĞI **KİLİT DOSYASIDIR** (TB-LOCK, 2026-08-25) — `requirements.lock`,
# TAM ağacı (doğrudan + geçişli, 41 paket) `==` ile sabitler. Kilitsiz kurulumda pinlenmemiş
# her geçişli katman aralıkta kalır: ölçüldü, `argon2-cffi-bindings` böyle 25.1.0 → 26.1.0'a
# tek satır kod değişmeden taşındı. Kilit `pip install -r` ile tüketilir; imaja `uv`/`poetry`
# gibi YENİ BİR ARAÇ GİRMEZ (kurulum akışı bire bir aynıdır, yalnız dosya adı değişti).
# Yenileme komutu kilit dosyasının başlığında yazılıdır.
# Bekçisi: tests/contract/test_bagimlilik_kilidi.py
COPY requirements.lock ./
RUN pip install --upgrade pip && pip install -r requirements.lock

# Uygulama kaynağı ve migration'lar.
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./

# Railway $PORT enjekte eder. Önce şema migration'larını uygula, sonra uvicorn'u başlat.
CMD alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
