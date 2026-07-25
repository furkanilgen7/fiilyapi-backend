# FİİL Yapı ERP — Backend

FastAPI · SQLAlchemy 2.0 (async, asyncpg) · Alembic · PostgreSQL

## Kurulum

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
cp .env.example .env   # DATABASE_URL, TEST_DATABASE_URL, JWT_SECRET doldurulur
```

PATH'te `python` olmayabilir; komutlarda daima `.venv/bin/...` kullanın.

## Çalıştırma

```bash
.venv/bin/uvicorn app.main:app --reload
```

## Migration

```bash
.venv/bin/alembic upgrade head
.venv/bin/alembic downgrade -1
.venv/bin/alembic revision --autogenerate -m "aciklama"
```

## Test ve linter

```bash
.venv/bin/pytest -q
.venv/bin/pytest --cov=app --cov-report=term-missing
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

Testler `TEST_DATABASE_URL`'e bağlanır ve oturum başında şemayı **düşürüp yeniden kurar**
(`drop_all` + `create_all`). Bu değişkeni asla üretim/canlı veritabanına yöneltmeyin.

## OpenAPI şeması (frontend sözleşmesi)

`openapi.json` bir **üretim çıktısıdır ve bu depoda izlenmez** (`.gitignore`). Sözleşmenin
izlenen tek kopyası frontend deposundadır: `frontend/openapi/openapi.json`. İki depoda iki
izlenen kopya tutmak kaçınılmaz olarak birbirinden ayrışır.

Yeni bir uç eklendiğinde veya bir şema değiştiğinde:

```bash
# 1) Backend'de güncel şemayı üret
cd backend
.venv/bin/python -c "import json; from app.main import app; print(json.dumps(app.openapi(), ensure_ascii=False, indent=2))" > openapi.json

# 2) Frontend deposuna taşı
cp openapi.json ../frontend/openapi/openapi.json

# 3) Frontend'de TypeScript tiplerini yeniden üret
cd ../frontend
pnpm gen:api        # openapi-typescript openapi/openapi.json -o src/lib/api/schema.d.ts
```

Üretilen `backend/openapi.json` commit'lenmez; frontend'deki kopya ve `schema.d.ts`
commit'lenir.
