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

`openapi.json` bir **üretim çıktısıdır ve bu depoda izlenmez** (`.gitignore`). Frontend'in
TÜKETTİĞİ tek kopya frontend deposundadır: `frontend/openapi/openapi.json`. İki depoda iki
tüketilebilir kopya tutmak kaçınılmaz olarak birbirinden ayrışır.

### 🔴 Sözleşme sürüklenme kapısı (TB-PIN, 2026-08-25)

Sözleşme bir **kod** çıktısı değil, **yorumlayıcı davranışının** çıktısıdır: `pydantic` /
`fastapi` / `starlette` sürümü değiştiğinde tek satır kod değişmeden yüzlerce şema değişir
(ölçüldü: pydantic 2.11.10 → 2.12+ geçişinde `Decimal` alanları `pattern` kazanıyor,
554 şemanın 230 kalemi oynadı). Bunun iki sonucu vardı ve ikisi de kapatıldı:

1. **Sözleşmeyi üreten kütüphaneler tam sürümle PİNLİ** — bkz. `pyproject.toml`
   `[project.dependencies]` ve `requirements.txt`. Sürümler **canlıda koşana** göre
   seçildi: canlı `/openapi.json` kimliksiz indirildi ve pinli takımla üretilen sözleşmeyle
   **kanonik md5'i birebir eşleşti**. `ruff==0.15.22` pininin gerekçesiyle aynı sınıftandır.
2. **`tests/contract/openapi_baseline.json`** sözleşmenin **içeriğini** kilitler ve
   `tests/contract/test_openapi_contract_baseline.py` her koşuda uygulamadan üretilenle
   karşılaştırır. Fark varsa **hangi şema / hangi alan** değiştiğini basar.
   ⚠️ Bu **üçüncü bir kopya değil, bir BEKÇİDİR**: bir test onu üretilene eşit olmaya
   zorladığı için tanım gereği ayrışamaz — yukarıdaki "iki kopya ayrışır" gerekçesi buna
   uygulanmaz, tam tersine o ayrışmayı görünür kılan mekanizmadır.
   ⚠️ Mevcut `test_YOL_ve_OPERASYON_sayisi_SABIT_kalir` bekçisi bu sınıfa **kördür**:
   yol/operasyon SAYISI sürümle değişmez (ölçüldü: 231/339 sabit kalırken 230 şema kalemi
   oynadı ve o test YEŞİL geçti). İkisi birbirinin yerine geçmez.

### Sözleşme kasıtlı değiştiğinde (yeni uç / yeni alan)

Bu üç adım **tek commit'te** yapılır; ilkini atlarsan kapı kırmızı verir, ikincisini
atlarsan frontend tipleri sessizce bayatlar.

```bash
# 1) Kapının tabanını yenile ve DIFF'İ GÖZLE DOĞRULA
cd backend
UPDATE_OPENAPI_BASELINE=1 .venv/bin/pytest tests/contract/test_openapi_contract_baseline.py
git diff -- tests/contract/openapi_baseline.json        # beklenen fark bu mu?
.venv/bin/pytest tests/contract/                        # yeşile dönmeli

# 2) Frontend sözleşmesini ve tiplerini yenile  🔴 DEVİR BORCU
.venv/bin/python -c "import json; from app.main import app; print(json.dumps(app.openapi(), ensure_ascii=False, indent=2))" > openapi.json
cp openapi.json ../frontend/openapi/openapi.json
cd ../frontend && pnpm gen:api   # openapi-typescript openapi/openapi.json -o src/lib/api/schema.d.ts
```

🔴 Sözleşmeyi değiştiren şef, **raporuna frontend devri gerektiğini yazar**. Tabanı
gerekçesiz yenilemek kapıyı hükümsüz kılar.

Üretilen `backend/openapi.json` commit'lenmez; `tests/contract/openapi_baseline.json`,
frontend'deki kopya ve `schema.d.ts` commit'lenir.
