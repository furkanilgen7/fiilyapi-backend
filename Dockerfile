# Railway bu Dockerfile'ı bulunca Nixpacks yerine bunu kullanır — PEP-621 pyproject'ten
# build planı üretemeyen Nixpacks'in sessiz "Deploy failed" sorununu tümden ortadan kaldırır.
FROM python:3.12-slim

# `ENVIRONMENT=production` İMAJIN KENDİ BEYANIDIR ve fail-closed'dur: tek tüketicisi
# `app/core/config.py`deki varsayılan-JWT-secret reddidir. Bu satır olmadan o kapı
# YALNIZCA Railway panelinde elle girilmiş bir değişkene bağlı kalır; panelden silinen
# tek satır, canlıyı herkese açık `dev-only-change-me` ile token imzalar hâle getirir.
# Bekçisi: tests/contract/test_uretim_imaji.py
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app \
    ENVIRONMENT=production

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
# 🔴 `ALEMBIC_ALLOW_REMOTE=1` ŞART: Railway'in veritabanı host'u localhost DEĞİLDİR ve
# `alembic/env.py`deki fail-closed uzak-DB kapısı bayraksız migration'ı reddeder —
# bayrak olmadan `alembic` patlar, `&&` kısa devre yapar, uvicorn HİÇ başlamaz (canlı 502).
# Bayrak YALNIZ bu satırdadır (imaj geneli `ENV` değil): kapı, insanın elindeki kabukta
# kapalı kalsın. Bekçisi: tests/contract/test_alembic_uzak_db_kapisi.py
CMD ALEMBIC_ALLOW_REMOTE=1 alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
