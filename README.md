# FİİL Yapı ERP — Backend

FastAPI · SQLAlchemy 2.0 (async, asyncpg) · Alembic · PostgreSQL

## Kurulum

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.lock   # 🔴 KİLİTTEN kurulur, aralık çözülmez
.venv/bin/pip install -e . --no-deps             # --no-deps ŞART: onsuz kilit ezilir
cp .env.example .env   # DATABASE_URL, TEST_DATABASE_URL, JWT_SECRET doldurulur
```

> ⚠️ `pip install -e '.[dev]'` **KULLANILMAZ** — aralıkları her seferinde yeniden çözer ve
> yerel ağacınız canlıdan/CI'dan sessizce ayrışır. Bkz. "Bağımlılık kilidi".

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
# TAM KÜME (dilimin KAPANIŞ kapısı) — paralel:
.venv/bin/pytest -q -n 4 --dist loadfile
.venv/bin/pytest -n 4 --dist loadfile --cov=app --cov-report=term-missing --cov-fail-under=80
.venv/bin/ruff check --no-cache . && .venv/bin/ruff format --check --no-cache .
```

Testler `TEST_DATABASE_URL`'e bağlanır ve oturum başında şemayı **düşürüp yeniden kurar**
(`drop_all` + `create_all`). Bu değişkeni asla üretim/canlı veritabanına yöneltmeyin.

### 🔴 Testi paralel koşmak — ve HEDEFLİ koşu (TB-XDIST, 2026-08-25)

**Ölçülen sorun:** tam küme tek çekirdekte **24 dk 24 sn** sürüyordu (CI turu, PR #80 `test`
işi; **6144 test**). Şefler bu kümeyi turda 2-3 kez koşuyordu → dilim başına giden 50-100
dakikanın en büyük tek kalemi buydu.

**İki ayrı koşu türü vardır ve BİRBİRİNİN YERİNE GEÇMEZ:**

| Tür | Komut | Ne zaman |
|---|---|---|
| **HEDEFLİ** (mutasyon turu) | `.venv/bin/pytest tests/<hedef> -q` | Bir bekçinin kırmızı verdiğini görmek için. **Paralel DEĞİL** — tek dosya için 4 süreç açmak yavaşlatır. |
| **TAM KÜME** (kapanış kapısı) | `.venv/bin/pytest -q -n 4 --dist loadfile` | Dilim kapanışında ve CI'da. |

⚠️ **Hedefli koşu tam kümenin YERİNİ TUTMAZ.** Bu deponun kanonu: *"paylaşılan test kaynağı —
izole koşuda yeşil olan tam kümede kırmızı olabilir ve tersi"* (FAT-1 dersi: eşzamanlılık
bekçisi izole koşuda **3/3 yeşil**, dosya bütününde kırmızıydı; kök neden soğuk bağlantı
havuzu). Hedefli koşu **mutasyon turu içindir**; kapanış kapısı **her zaman tam kümedir**.

**🔴 `-n auto` KULLANILMAZ, üst sınır 4'tür.** Makine 8 çekirdek ama **8 GB RAM**; swap'e düşen
bir koşu seri koşudan **yavaştır**. Ayrıca bu depoda paralel frontend hattı koşar.

**Yerel ölçüm (aynı makine, aynı ağaç, 6144 test):**

| Koşu | Süre | Zirve `pytest` RSS |
|---|---|---|
| seri (`-p no:randomly`) | **751,02 s** (12:31) | ~200 MB |
| `-n 3 --dist loadfile` | **434,54 s** (7:14) | ~824 MB |
| `-n 4 --dist loadfile` | **385,09 s** (6:25) | ~813 MB |
| `tests/site_planning` (hedefli, 102 test) | **10,98 s** | — |

`-n 4` seçildi: `-n 3`ten **%11 daha hızlı** ve RAM'de fark yok (ikisi de < 1 GB, 8 GB'ın
**%10**'u). Swap büyümesi ölçüldü, iki koşuda da ihmal edilebilir.

**Yalıtım — her işçi KENDİ veritabanını alır.** `tests/conftest.py`, `PYTEST_XDIST_WORKER`
ortam değişkeninden `<taban>_gw0`, `<taban>_gw1`, … adlarını türetir ve
`settings.test_database_url`i **o adla yamalar** (motoru değil: migration/eşzamanlılık
testleri kendi DSN'lerini doğrudan o ayardan üretiyor). Veritabanı `pytest_sessionstart`ta
kurulur, `pytest_sessionfinish`te `DROP DATABASE … WITH (FORCE)` ile **başarısızlıkta da**
düşürülür. `DROP` çalıştıran her yol, adın `_gwN` son ekini taşıdığını önce çakar — taban
veritabanı bu koddan düşürülemez.

## OpenAPI şeması (frontend sözleşmesi)

`openapi.json` bir **üretim çıktısıdır ve bu depoda izlenmez** (`.gitignore`). Frontend'in
TÜKETTİĞİ tek kopya frontend deposundadır: `frontend/openapi/openapi.json`. İki depoda iki
tüketilebilir kopya tutmak kaçınılmaz olarak birbirinden ayrışır.

### 🔴 Bağımlılık kilidi (TB-LOCK, 2026-08-25)

Elle pin **yetmez**: pinlenmeyen her **geçişli** katman `>=` aralığında kalır. Ölçüldü —
`argon2-cffi` pinliyken parola özetini fiilen üreten `argon2-cffi-bindings`, TB-PIN'in
**kendi deploy'unda** 25.1.0 → 26.1.0'a tek satır kod değişmeden taşındı. Bu yüzden **tam
ağaç** kilitlenir.

| Dosya | Kapsam | Kuran |
|---|---|---|
| `requirements.lock` | üretim ağacı — **41 paket** | `Dockerfile` (Railway) |
| `requirements-dev.lock` | üretim + dev/test — **54 paket** | CI ve yerel kurulum |

Her ikisi de düz `requirements.txt` biçimindedir; `pip install -r` doğrudan tüketir —
imaja/CI'a `uv` ya da `poetry` **binary'si girmez**. Kaynak dosyalar (`requirements.txt`,
`pyproject.toml`) elle tutulmaya devam eder; kilitler onlardan **üretilir**.

**Yenileme (bağımlılık ekleyen/yükselten her dilim yapar):**

```bash
uv pip compile requirements.txt --python-version 3.12 \
    --python-platform x86_64-unknown-linux-gnu -o requirements.lock
uv pip compile pyproject.toml --extra dev --python-version 3.12 \
    --python-platform x86_64-unknown-linux-gnu -o requirements-dev.lock
.venv/bin/pip install -r requirements-dev.lock && .venv/bin/pip install -e . --no-deps
```

Hedef platform **linux/x86_64**: hem Railway imajı (`python:3.12-slim`) hem CI
(`ubuntu-latest`) odur.
⚠️ `uv pip compile -o X`, var olan `X`i **tercih girdisi** olarak okur (gereksiz
yükseltmeyi önlemek için). Kasıtlı yükseltmede `--upgrade-package <ad>` kullanın; sıfırdan
çözüm için kilidi önce **silin**. Her durumda `git diff` gözle doğrulanır.

**Bekçi:** `tests/contract/test_bagimlilik_kilidi.py` dört iddiayı ölçer —
(1) dev kilidi ↔ **fiilen kurulu** ağaç, (2) üretim kilidi ⊆ dev kilidi (canlıya testlerin
doğrulamadığı sürüm gitmesin), (3) kaynak pinleri ↔ kilit (bayat kilit), (4) `Dockerfile` ve
CI'ın **fiilen kilitten kurduğu** (kilit, onu kuran adım olmadan yalnızca dekorasyondur).

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
#    🔴 KAYNAK **TABAN DOSYASIDIR**, `app.openapi()` çıktısı DEĞİL (AI-0b'de ölçüldü):
#    taban `sort_keys=True` ile yazılır, `app.openapi()` ise ekleme sırasını korur.
#    Doğrudan üretilen dosya SIRASIZ olur ve devir 22.000 satırlık sahte bir diff
#    üretir. Ölçüm: `git show HEAD:tests/contract/openapi_baseline.json` ile
#    `frontend/openapi/openapi.json` **cmp ile BİREBİR AYNI** çıktı.
cp tests/contract/openapi_baseline.json ../frontend/openapi/openapi.json
cd ../frontend && pnpm gen:api   # openapi-typescript openapi/openapi.json -o src/lib/api/schema.d.ts
```

⚠️ Eskiden burada `python -c "... json.dumps(app.openapi(), indent=2)" > openapi.json`
+ `cp` yazıyordu. O komut **`sort_keys` taşımıyordu** ve fiilen hiç kullanılmamıştı;
`frontend/scripts/gen-api.md` de aynı hatanın ikinci kopyasıydı. İkisi de düzeltildi.

🔴 Sözleşmeyi değiştiren şef, **raporuna frontend devri gerektiğini yazar**. Tabanı
gerekçesiz yenilemek kapıyı hükümsüz kılar.

Üretilen `backend/openapi.json` commit'lenmez; `tests/contract/openapi_baseline.json`,
frontend'deki kopya ve `schema.d.ts` commit'lenir.
