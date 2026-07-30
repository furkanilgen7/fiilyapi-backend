# Alt-Proje 2 · P4 — İş Kalemleri (BOQ) uygulama planı

Tarih: 2026-07-29
Spec: `backend/docs/superpowers/specs/2026-07-29-alt-proje-2-p4-is-kalemleri-boq-design.md`
Önkoşul: Spec §8'deki açık sorular (özellikle 1 ve 2) kullanıcıya sorulmadan T1'e başlanmaz.

## Kurallar (her task için geçerli — P1.1a kanonundan uyarlandı)

1. **TDD zorunlu:** önce test yazılır, KIRMIZI görülür, sonra uygulama; yeşil
   sonrası refactor. Kırmızıyı görmeden uygulama yazan task geçersizdir.
2. **TEST DB TUZAĞI (KRİTİK):** `backend/.env` içindeki `TEST_DATABASE_URL`
   **uzak Railway'i** gösteriyor ve `tests/conftest.py` oturum başında
   `Base.metadata.drop_all` çağırıyor. Her task **tek kullanımlık yerel DB**
   açar ve env'i **komut satırında** verir; `.env` DÜZENLENMEZ:
   ```bash
   createdb boq_test_t1 && \
   TEST_DATABASE_URL="postgresql+asyncpg://$(whoami)@localhost:5432/boq_test_t1" \
     .venv/bin/pytest tests/modules/test_boq_api.py -x
   dropdb boq_test_t1      # başarısızlıkta bile
   ```
3. **PATH'te `python` yok** — her şey `.venv/bin/...` üzerinden
   (`.venv/bin/pytest`, `.venv/bin/alembic`, `.venv/bin/ruff`).
4. **ruff 0.15.22'ye sabitli**; global 0.8.6 KULLANILMAZ (`.venv/bin/ruff`).
5. **Kapılar (her task sonunda):** `.venv/bin/pytest` + `.venv/bin/ruff check .`
   + `.venv/bin/ruff format --check .` — üçü de yeşil olmadan task bitmez.
6. **Ajanlar push etmez.** Commit serbest (İngilizce `<type>: <desc>`), push kullanıcıda.
7. **`frontend/` altına yazılmaz**; canlı DB'ye migration koşulmaz.
8. **Mockup birebir:** her alan `projedesign/Ekran 13 - İş Kalemleri.dc.html`
   satır numarasıyla gerekçelenir (spec §3). Göz kararı alan icat etmek yasak.

## Task listesi

### T1 — Migration + modeller
- Dosyalar: `alembic/versions/xxxx_p4_is_kalemleri_boq.py`,
  `app/modules/boq/__init__.py`, `app/modules/boq/models.py`,
  test: `tests/modules/test_boq_models.py`
- Ne: spec §3 tabloları; `down_revision = "e2b3c4d5f6a7"`; SQLAlchemy modelleri
  mevcut `sites` modeli deseniyle (timestamptz mixin, UUID PK).
- Tuzaklar: (a) `uq_boq_items_site_code` — `code` üstünde değil `(site_id, code)`
  bileşiği; (b) downgrade sırası: önce `boq_items`; (c) numeric hassasiyetleri
  (14,3)/(18,2) — model ve migration'da AYNI; (d) `modules`/`role_permissions`'a
  DOKUNMA — seed parity testleri değişmeden yeşil kalmalı.
- Testler: unique ihlali IntegrityError; farklı şantiyede aynı kod geçerli;
  CHECK ihlalleri; site silinince group+item cascade; upgrade→downgrade→upgrade.
- Bitti: kapılar yeşil; seed testleri DEĞİŞMEDEN yeşil.

### T2 — Şema katmanı (Pydantic)
- Dosyalar: `app/modules/boq/schemas.py`, test: `tests/modules/test_boq_schemas.py`
- Ne: `BoqListResponse`/`BoqGroupResponse`/`BoqItemResponse` + yazma şemaları
  (spec §5.1–5.2); `MetricPlaceholder` **P1'den import edilir**
  (`app/modules/projects/schemas.py`), kopyalanmaz.
- Tuzaklar: Decimal alanlar str serileşir (mevcut desen); `quantity` 3 hane,
  para 2 hane `quantize`; PATCH şemasında `site_id` YOK.
- Testler: doğrulamalar (`quantity<=0` → hata), türev `amount` hesabı.
- Bitti: kapılar yeşil.

### T3 — Repository + service (okuma yolu)
- Dosyalar: `app/modules/boq/repository.py`, `app/modules/boq/service.py`,
  test: `tests/modules/test_boq_service.py`
- Ne: şantiye görünürlük çözümü (P2'deki site→project süzgeç yardımcıları
  YENİDEN KULLANILIR, kopyalanmaz); gruplu liste; `group_total`/`grand_total`;
  yer tutucular tek yerde.
- Tuzaklar: N+1 — kalemler tek sorguda çekilip grupta toplanır; Decimal toplama
  (float ASLA); boş BOQ `"0.00"`.
- Testler: toplam hesapları, sıralama (`sort_order, code`), boş durum.
- Bitti: kapılar yeşil.

### T4 — `GET /sites/{site_id}/boq` + router kaydı
- Dosyalar: `app/modules/boq/router.py`, `app/main.py` (router include),
  test: `tests/modules/test_boq_api.py`
- Ne: okuma ucu, `require_permission("sites", view)` + görünürlük süzgeci.
- Tuzaklar: görünmeyen şantiye **404** (403 değil); router prefix'leri —
  uçların bir kısmı `/sites/...`, bir kısmı `/boq/...` kökünde.
- Testler: 401; 403 (`sites` izni olmayan rol); 404 (görünmeyen şantiye);
  200 mutlu yol (yanıt gövdesi spec §5.1 ile birebir).
- Bitti: kapılar yeşil.

### T5 — Yazma uçları: POST group / POST item
- Dosyalar: `router.py`, `service.py`, yeni `BoqGroupSiteMismatchError` + handler
  (mevcut domain hata deseni), test: `test_boq_api.py`
- Ne: iki POST; 409 (poz çakışması, mevcut IntegrityError handler deseni);
  422 (grup-şantiye uyuşmazlığı, Türkçe mesaj spec §5.4).
- Tuzaklar: **IDOR-2:** gövdedeki `group_id` başka şantiyenin grubuysa 422;
  görünmeyen şantiyeye POST → 404; `view` var `full` yok → 403.
- Testler: 201 mutlu yol; 409; 422; 403; 404 — hepsi.
- Bitti: kapılar yeşil.

### T6 — PATCH uçları + IDOR negatif seti
- Dosyalar: `router.py`, `service.py`, test: `test_boq_api.py`
- Ne: `PATCH /boq/groups/{id}`, `PATCH /boq/items/{id}`; yukarı çözümleme
  (item→group→site→project) + süzgeç.
- Tuzaklar: **P2'de yakalanan IDOR sınıfı** — dolaylı kimlik çözümleyen PATCH
  en kolay atlanan güvenlik noktası; görünmeyen kayda PATCH **404**.
  `group_id` değişiminde aynı-şantiye kontrolü tekrarlanır.
- Testler: görünmeyen kalem/grup PATCH → 404; başka şantiyenin grubuna taşıma
  → 422; kod değişiminde 409; mutlu yol.
- Bitti: kapılar yeşil.

### T7 — Denetim günlüğü
- Dosyalar: `service.py`, `app/modules/audit/messages.py`,
  test: `test_boq_api.py` (genişletme)
- Ne: 4 yazma ucunda `record_audit` (B5 deseni), Türkçe mesajlar
  (ör. "İş kalemi oluşturuldu: 01.001 — Kazı (Makine ile)").
- Tuzaklar: okuma uçları kayıt YAZMAZ; mesaj anahtarları messages.py'de merkezi.
- Testler: create/update sonrası `audit_log` satırı doğru action ile.
- Bitti: kapılar yeşil.

### T8 — Excel dışa aktarımı
- Dosyalar: `app/modules/boq/export.py`, `router.py`, test: `tests/modules/test_boq_export.py`
- Ne: `GET /sites/{site_id}/boq/export` → xlsx; başlıklar mockup satır 96–102
  ile birebir; grup başlıkları + GENEL TOPLAM satırı; Gerç. % hücreleri boş.
- Tuzaklar: `openpyxl` bağımlılığı — `pyproject.toml`'da var mı ÖNCE bakılır;
  yoksa eklenir ve bu, deploy'da yeni bağımlılık notu olarak commit mesajına
  yazılır; yanıtta `Content-Disposition` dosya adı Türkçe karakter kaçışı.
- Testler: openpyxl ile geri okunarak başlık satırı, grup satırı, toplam ve boş
  Gerç. % hücreleri doğrulanır; izin 403/404 testleri bu uçta da.
- Bitti: kapılar yeşil.

### T9 — OpenAPI üretimi + kapanış
- Dosyalar: `openapi.json` (backend üretimi — **gitignore'lu**, commit edilmez)
- Ne: `openapi.json` üretilir; tüm test paketi + ruff kapıları tam koşu.
- Tuzaklar: openapi üretimi app import eder — env değişkenleri komut satırında.
  Şemada `app__modules__projects__schemas__MetricPlaceholder` uzun adı
  **beklenen davranıştır**, düzeltilmez.
- Bitti: tüm kapılar yeşil; `openapi.json` frontend'e kopyalanmaya hazır.

## Sıralama

- Kritik yol: **T1 → T2 → T3 → T4 → T5 → T6 → T9**
- Paralel koşabilir: T7 (T5 sonrası), T8 (T3 sonrası okuma yolu yeterli;
  router kaydı için T4 ile küçük çakışma — aynı ajana verilmesi önerilir).
- **Backend → frontend SERT BARİYER:** T9'da `openapi.json` üretilip
  `frontend/openapi/openapi.json`'a kopyalanmadan frontend tarafında
  `pnpm gen:api` KOŞULMAZ. Frontend Ekran 13 dilimi bu şemanın üstüne ayrı
  spec'le yazılır — bu planda frontend task'ı YOKTUR.

## Frontend'in bu dilimden beklediği (yalnız sözleşme düzeyi)

- `GET /sites/{site_id}/boq` zarfı (spec §5.1) — yer tutucu alanlar B6
  `MetricPlaceholder` şekliyle birebir; `pendingModuleLabel` anahtarları:
  `contracts`, `progress_payments` (ikisi de `pending-modules.ts`'te zaten var).
- **BFF TUZAĞI (kritik):** yeni uçların iki kökü var: `/sites/...` (P2'de ekli)
  ve `/boq/...` (**YENİ KÖK**). `boq` kökü
  `frontend/src/app/api/backend/[...path]/route.ts` `ALLOWED_ROOTS`'a
  eklenmezse PATCH uçları YALNIZ CANLIDA 404 verir; jsdom testleri bunu
  YAKALAMAZ. Frontend diliminin ilk task'ına not düşülecek.
