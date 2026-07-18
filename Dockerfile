# Railway bu Dockerfile'ı bulunca Nixpacks yerine bunu kullanır — PEP-621 pyproject'ten
# build planı üretemeyen Nixpacks'in sessiz "Deploy failed" sorununu tümden ortadan kaldırır.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

# Önce bağımlılıklar (katman önbelleği): kaynak değişse de wheel kurulumu tekrar çalışmaz.
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# Uygulama kaynağı ve migration'lar.
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./

# Railway $PORT enjekte eder. Önce şema migration'larını uygula, sonra uvicorn'u başlat.
CMD alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
