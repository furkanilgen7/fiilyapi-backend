# P9 — Hissedar-Ünite (backend plan)

Tarih: 2026-08-08 · Spec: `../specs/2026-08-08-p9-hissedar-unite-design.md` (ONAYLI) ·
Dal: `feat/p9-hissedar-unite` (güncel main'den) · Task başına TEK subagent, her task sonunda commit.

## T1 — Migration + model
- `units.shareholder_id`: UUID FK → `land_share_shareholder.id`, nullable, `ondelete="SET NULL"`,
  `ix_units_shareholder_id`. Ebeveyn: **`b8c9d0e1f2a3`** (BC head — `alembic heads` ile TEK head doğrula;
  farklıysa DUR, rapor et). Enum yok, izin migration'ı yok.
- Model: `Unit.shareholder_id` kolonu; `relationship` AÇILMAZ (BC blob izolasyon emsali — okuma
  yüzeyi açık JOIN/sorgu ile besler, lazy-load sürprizi olmaz).
- `units/models.py:229` civarındaki "ileri bağ açılmaz: shareholder_id" docstring'i güncellenir
  (`sale_id`/`contract_id` notu kalır).
- Tur: upgrade→downgrade→upgrade yerelde temiz (override'lı DB). Migration testi açık revizyon id ile.

## T2 — Hissedar kimlik korunumu (TDD; spec §4.1)
- `ShareholderInput.id: UUID | None`. Proje POST/PATCH'inde hissedar listesi artık **id-eşleştirmeli
  birleştirme**: id eşleşen satır YERİNDE güncellenir (name/share_pct); id'siz girdi yeni satır;
  listede olmayan mevcut satır silinir. `project.shareholders = [...]` toptan değiştirme kalkar.
- Bilinmeyen/başka projenin id'si → 422 (uydurma id sessizce yeni satıra dönüşmez).
- **Atanmış ünitesi olan hissedar listeden çıkarılırsa 409** (Türkçe mesaj `messages.py`'ye; audit değişmez).
- Testler: id'li güncellemede satır id'si DEĞİŞMEZ (kimlik kanıtı) · id'siz eski gövde geriye uyumlu ·
  atanmışı silme 409 + hiçbir hissedar satırı değişmez (atomiklik) · atanmamışı silme serbest.
- Mutasyon denetimi (yazma task'ı).

## T3 — Allocation genişletme + okuma yüzeyi (TDD; spec §4.2-4.3, §5)
- `UnitAllocationItem.shareholder_id: UUID | None` (alan yoksa `None` sayılır — DEĞİŞTİRME sözleşmesi).
- Kurallar: `contractor`/`None` tarafla `shareholder_id` → **422** · başka projenin hissedarı → **404**
  (IDOR-8 deseni, atomik: hiçbir satır yazılmaz) · `owner_side` landowner'dan çıkınca `shareholder_id`
  birlikte temizlenir · `landowner + None` geçerli.
- Audit dönem-özetine hissedar ataması sayısı eklenir; yeni `AuditAction` YOK.
- Okuma: `UnitResponse.shareholder` (MetricPlaceholder) **KALKAR** → `shareholder_id` +
  `shareholder_name` gerçek. `_SHAREHOLDER_UNITS` yer tutucu sabiti ve kullanımları temizlenir.
  Adlar tek ek sorgu/JOIN'den (N+1 testi: ünite sayısından bağımsız sorgu sayısı).
- Mutasyon denetimi.

## T4 — Excel dışa aktarım (TDD; spec §5, S3)
- `GET /projects/{project_id}/units/export.xlsx` — `projects:view`, IDOR `visible_projects`.
- Sütunlar KKP 86-92: Ünite (blok · no) · Tip · m² · Rayiç Değer · Sahip · Hissedar/Alıcı · Satış Durumu.
  Veri mevcut liste türevlerinden (`to_unit` ile aynı kaynak — yeniden hesaplanmaz; timesheet
  `matrix.build` emsali). Türkçe başlıklar, `_content_disposition` deseni.
- Testler: içerik doğruluğu (openpyxl ile geri okuma) · yetkisiz 401/403 · görünmeyen proje 404.

## T5 — Kapanış + FINAL REVIEW (Opus)
- Tüm paket: pytest (override'lı) + ruff tüm repo + `alembic check` + migration turu + tek head.
- Opus FINAL REVIEW odağı: §4.1 kimlik korunumu (PATCH ile atama süpürme senaryosu BİZZAT denenir) ·
  IDOR (hissedar id'si üzerinden proje varlığı sızıntısı) · atomiklik · kalıcı karar taraması
  (milestone/PDF/otomatik-dağıt/hissedar-CRUD sızıntısı = bulgu). Bulgular kapatılır.
- `openapi.json` üret → DEVİR KURALI (WORKFLOW §4): frontend checkout main'de+temiz DEĞİLSE
  (F-P5 sürüyor — muhtemelen kirli) KOPYALAMA, rapor et.
- `ARCHITECTURE-BACKEND.md` + `ROADMAP-BACKEND.md` güncelle, commit.
