# P6 — Bölüm Detay (uygulama planı)

Spec: `../specs/2026-08-02-p6-bolum-detay-design.md` · Ön şart: spec §7 sorularının kullanıcı cevabı.
Her task = tek subagent + commit. TDD: önce test, KIRMIZI gör. DB komutları HEP override'lı (WORKFLOW §4).

## T1 — Migration + model
- `sections`'a spec §3 kolonları (+ S1 onaylıysa `on_hold`, S2a onaylıysa `budget_amount Numeric(18,2) CHECK ≥0`).
- Tek migration, ebeveyn `c3d4e5f6a7b8`. Yerelde upgrade→downgrade→upgrade; testte açık revizyon id.
- Enum eklemelerinde downgrade stratejisi (yeni tip yarat-taşı-değiştir) test edilir.
- Kabul: migration testi + model testi yeşil; `alembic check` sahte diff'ine dokunulmaz.

## T2 — GET /sections/{id} (TDD)
- Yeni detay ucu `sites:view`; IDOR testleri (görünmeyen proje → 404, var olmayanla ayırt edilemez).
- `SectionDetailResponse`: tüm kolonlar + mevcut placeholder'lar. openapi tag/hata şemaları desene uygun.

## T3 — POST/PATCH genişletme (TDD)
- `SectionCreate/Update`'e yeni alanlar; taslak-dışı zorunluluk kuralları (spec §3'e sadık).
- `deputy_manager` için `on_leave` atanabilirlik testi; snapshot `deputy_manager_name` kuralı `manager_name` ile aynı.
- `code` otomatik üretimi doğrula/ekle (`BLM-NN`), çakışmada 409/422 davranışı test edilir.
- Audit: yeni alan değişimleri `AuditAction`+`messages.py`; audit testleri.

## T4 — Kapanış
- Tüm paket: pytest (yerel DB) + `ruff check .` + `ruff format --check .` (alembic/ dahil).
- `openapi.json` üret → `frontend/openapi/openapi.json`'a kopyala; gen:api devri notu.

## T5 — FINAL REVIEW (Opus)
- IDOR/silme/migration geri-alınabilirlik/audit/mockup sadakati denetimi; bulgular kapanır.
- `ARCHITECTURE-BACKEND.md` (§2 sites, §3 sections, §5 HEAD) + `ROADMAP-BACKEND.md` güncelle, commit.
