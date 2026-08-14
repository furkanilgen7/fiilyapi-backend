# FAT-1 — Fatura Çekirdeği (backend) · uygulama planı

Spec: `backend/docs/superpowers/specs/2026-08-14-fat1-fatura-cekirdegi-design.md`
Dal: `feat/fat1-fatura-cekirdegi` (base: `main` @ `d39880a`)

TDD zorunlu: **önce test, KIRMIZI GÖR, sonra kod.** İlk koşuda yeşilse mutasyon denetimi.

---

## T1 — Model + migration  · model: **Opus**

**Kapsam:** `invoicing/models.py` (spec §2) + alembic revizyonu (ebeveyn `a0b1c2d3e4f5`) +
`alembic/env.py` ve `tests/conftest.py`'ye `invoicing` eklenmesi.

**Kabul kriteri**
- `invoices` + `invoice_lines` tabloları spec §2.1/§2.2 ile birebir (kolon adı, tip, nullability,
  FK davranışı, CHECK, UNIQUE, indeks).
- Dört yeni enum tipi; **downgrade `DROP TYPE` yapar**.
- Migration testi **açık revizyon id'siyle** (`head`/`-1` YOK): `upgrade → downgrade → upgrade`
  temiz, `alembic heads` **TEK**.
- `tests/test_alembic_env_imports.py` bekçisi yeşil (yeni modül listede).
- `.venv/bin/alembic check` temiz.

**Dosyalar:** `app/modules/invoicing/{__init__,models}.py` · `alembic/versions/<yeni>.py` ·
`alembic/env.py` · `tests/conftest.py` · `tests/modules/invoicing/test_invoicing_migration.py`

---

## T2 — Para çekirdeği + durum matrisi (saf, DB'siz)  · model: **Opus**

**Kapsam:** `amounts.py` (spec §5) + `transitions.py` (spec §3) + `numbering.py` (spec §4) +
`validation.py` (K6).

**Kabul kriteri**
- `amounts.py` 7 adımı sırayla uygular; `Decimal` + `ROUND_HALF_UP`, **kayan nokta YOK**
  (bekçi test: `float` kullanımı yok).
- **K3 kanıtı:** tek oranlı faturada sonucun "subtotal→tax_base→×oran" ile **birebir aynı**
  olduğu testlenir; iki farklı KDV oranlı faturada dağıtımın toplamı `vat_amount`a **kuruşu
  kuruşuna** eşittir (yuvarlama artığı kaybolmaz/uydurulmaz).
- `subtotal = 0` → `vat_amount = 0`, **sıfıra bölme YOK**.
- `transitions.py`: iki yönün matrisleri ayrı; **yön dışı geçiş** ve matris dışı geçiş ayırt edilir.
- `numbering.py`: `FIL2026000001` biçimi; `…000009999`→`…000010000` genişleme testi (metin
  sıralaması tuzağı — SA docstring'i); yalnız `outgoing`.
- Bu task'ta **HİÇBİR uç yazılmaz.**

**Dosyalar:** `app/modules/invoicing/{amounts,transitions,numbering,validation}.py` +
`tests/modules/invoicing/test_{amounts,transitions,numbering}.py`

---

## T3 — CRUD uçları (1, 3, 4, 5, 6, 7)  · model: **Opus**

**Kapsam:** `schemas.py` · `repository.py` · `service.py` · `router.py`; liste + oluştur + detay +
PATCH + DELETE + `PUT lines`. `app/main.py` router kaydı (spec §9 sıra tuzağı).

**Kabul kriteri**
- Spec §7'deki süzgeç/sayfalama sözleşmesi birebir; `limit` tavanı **422** (kırpma DEĞİL).
- İstemci `invoice_no` (giden), `line_total`, `sort_order`, hesaplanmış para alanlarını
  **GÖNDEREMEZ** → 422.
- IDOR: başka projenin faturası **404**; gövde içi görünmeyen referans **404** (ST kanonu).
- `DELETE` yalnız `admin` + yalnız `draft`; `full` rolü **403** alır, `sent` fatura **409**.
- `PATCH`/`PUT lines` yalnız `draft` (giden) — gelen'de yalnız `pending` + üç alan.
- Serbest metin tavanı `app/core/text.py::FREE_TEXT_MAX_LENGTH` (2000) — **TÜM giriş
  noktalarından** (create + patch + `PUT lines`) okunur, ayrı yazılmaz (TB4/B4 dersi).
- `ck_invoices_single_party` / `_single_source` ihlali servis katmanında **422** ile önce yakalanır
  (DB CHECK son savunmadır, kullanıcıya 500 gitmez).

---

## T4 — Durum uçları + kilit + özet (8, 9, 10, 11, 2)  · model: **Opus**

**Kapsam:** dört geçiş ucu + `summary.py`.

**Kabul kriteri**
- 🔴 **EŞİK = KİLİT (spec §8):** her geçiş ucu `with_for_update` + `populate_existing`, kilit
  **denetimlerden önce**. **İKİ GERÇEK BAĞLANTIYLA** eşzamanlılık testi yazılır ve
  **kilit satırı kaldırılınca KIRMIZI olduğu KANITLANIR** (raporda kanıt istenir).
- K6: kalemsiz faturada `send`/`approve` → **422**.
- Yön dışı geçiş → **409** (giden'e `approve`, gelen'e `send`).
- `GET /invoices/summary` beş KPI'ı spec §7'deki tanımla döner; ay penceresi
  `DISPLAY_TIMEZONE`de; **`pending_approval` ADETTİR**, tutar değil.
- Yeni `AuditAction` üyesi **AÇILMAZ**; ayrım `messages.*` metninden.

---

## T5 — FINAL REVIEW (Opus) + sınıf araması + doküman  · model: **Opus**

**Kapsam ve kabul kriteri**
1. **🔴 K7 SNAPSHOT SINIF ARAMASI (spec §5).** Faturanın `total`ını üreten **HER** çarpan tek tek
   listelenir ve kaynağı ("satırdan mı, canlı kayıttan mı") sorulur. Kanıt testi: kaynak kayıt
   (hakediş tutarı · ekipman saat ücreti · cari ünvanı/VKN'si) değiştirilir → `sent`/`approved`
   faturanın **hiçbir alanı değişmez**. Kaçan bir çarpan bulunursa **dilim içinde kapatılır**.
2. **NULL-EŞİK denetimi (SA kanonu):** her toplanabilir alanda NULL girdinin yönü açıkça
   kararlaştırılmış ve testlenmiş mi?
3. Dosya tavanı: hiçbir dosya **800 satırı geçmiyor** (SA `service.py` borcu tekrarlanmaz).
4. Kapılar: `TEST_DATABASE_URL` override'lı **tam pytest** + `ruff check .` + `ruff format --check .`
   (alembic/ dahil, TÜM repo).
5. `openapi.json` üretilir, **yol sayısı raporlanır** (beklenen 183 + 11 = **194**).
   🔴 **openapi DEVRİ YAPILMAZ** — frontend `main`'i temiz olsa bile devir borcu olarak kaydedilir
   (gerekçe: frontend PR #29 `openapi.json`+`schema.d.ts` üzerinde açık; ikinci bir devir çakışır).
6. `ARCHITECTURE-BACKEND.md` (§2 router envanteri · §3 tablo envanteri · §5 alembic zinciri ·
   §6 test düzeni) + `ROADMAP-BACKEND.md` (§1'e yeni dilim bloğu · §2 md.7 `Mali` satırı ·
   §3 borç tablosu: openapi devri + kapsam dışı kalanlar) güncellenir.
   🔴 **`ARCHITECTURE.md` (repo-üstü) dosyasına DOKUNULMAZ** — paralel koşan frontend dilimiyle
   çakışır; yönetim güncelleyecek.

---

## T6 — KOŞULLU KAPANIŞ (⚡ tek paket, MERGE'E KADAR)

Koşullar **hepsi** sağlanıyorsa tek turda yürütülür:
- dört kapı yeşil (pytest + ruff check + ruff format + alembic turu)
- `origin/main` head'i **hâlâ `d39880a`** (değiştiyse DUR)
- `origin/main` alembic head'i **hâlâ `a0b1c2d3e4f5`** (değiştiyse **re-parent + test sabiti**)

→ `git push -u` → `gh pr create` → CI durumu raporlanır → **MERGE-HAZIR raporu, TEK rapor.**

🔴 `gh pr merge` **YOK** · deploy **YOK** · canlıya giriş/yazma **YOK** · canlı DB'ye migration
**YOK**. Merge kararı yönetim oturumundadır.

⚠️ **CI ŞU AN KAPALI** (GitHub Actions faturalandırması). CI kırmızı/atanmamış görünürse bu
**altyapıdır, koda dokunma**. Yerel CI eşdeğeri raporda **ZORUNLU** — aşağıya bak.

### CI eşdeğeri (Docker + PG 16) — raporda kanıt olarak İSTENİR

Yerel PG 18, CI PG 16 (WORKFLOW §4 sürüm tuzağı). Docker Desktop YOK, **colima** var:

```bash
colima start
docker run -d --name pg16 -e POSTGRES_USER=fiil -e POSTGRES_PASSWORD=fiil \
  -p 55432:5432 postgres:16-alpine
TEST_DATABASE_URL="postgresql+asyncpg://fiil:fiil@localhost:55432/fatura" .venv/bin/pytest -q
DATABASE_URL="postgresql+asyncpg://fiil:fiil@localhost:55432/fatura_mig" \
  .venv/bin/alembic upgrade head && … downgrade -1 && … upgrade head
docker rm -f pg16 && colima stop     # başarısızlıkta BİLE
```

Rapor: test sayısı + süre + alembic turu çıktısı + tek head kanıtı.
