# Şantiye Günlüğü — site_diary (uygulama planı)

Spec: `../specs/2026-08-02-site-diary-design.md` · Ön şart: spec §7 sorularının kullanıcı cevabı.
Dal: `feat/site-diary` (GÜNCEL main'den — P6+P8+TH merge'li, tek head `d4e5f6a7b8c9`).
Her task = tek subagent + commit · TDD (önce test, KIRMIZI) · DB komutları HEP override'lı (WORKFLOW §4).

## T1 — Migration + modeller
- 3 tablo (`site_diary_entries/_lines/_worker_counts`) + 3 enum (`weather/diary_status/worker_source`)
  + **`progress_payment_lines.quantity_source` kolonu** (S2 onaylıysa; default `manual`, taşeron deseniyle aynı).
- Ebeveyn = güncel main HEAD (**açık revizyon id — `d4e5f6a7b8c9` bekleniyor, `alembic heads` ile doğrula**).
  upgrade→downgrade→upgrade; downgrade'de `DROP TYPE`'lar. İzin migration'ı GEREKMEZ (seed'de hazır) —
  yine de `test_seed_matrix` yeşilliğini kanıtla.

## T2 — Günlük CRUD (TDD)
- `POST /sites/{id}/diary` (BOQ pozlarından satır iskeleti; UQ ihlalinde 409 "bu güne kayıt var") ·
  `GET` liste (ay filtresi + Son Kayıtlar alanları) · `GET/PATCH` detay · `DELETE` draft+can_delete.
- İzin `site_diary` (view/full ayrımı: PM salt-okur) · IDOR `visible_projects` · audit.

## T3 — Satırlar + işçi kırılımı (TDD)
- `PUT {id}/lines` DEĞİŞTİRME semantiği (yalnız draft; FOR UPDATE kilit) — kümülatif/₺ türevleri
  yanıt şemasında (`cumulative_quantity`, `line_amount`), kolon açılmaz.
- Worker counts: entry gövdesinde iç içe liste (PATCH ile birlikte değiştirilir); toplam türev.

## T4 — Durum akışı + agregasyon (TDD)
- `submit` (draft→submitted, damga) · `reopen` (yalnız admin, submitted→draft) · geçiş matrisi testleri.
- `GET /sites/{id}/diary/summary?year&month`: poz bazlı toplamlar + KPI'lar (yalnız submitted);
  Hakediş Özeti ekranının sözleşme/kümülatif kolonları için `contract_item` köprü alanları.

## T5 — Hakediş "günlükten doldur" önerisi (S2 onaylıysa, TDD)
- İşveren: `GET /projects/{id}/progress-payments/diary-suggestion?year&month` — BOQ→`contract_item_id`
  köprüsüyle şantiye-bazlı önerilen miktarlar (mevcut `PUT lines` gövdesine birebir uyan biçimde).
- Taşeron: `GET /subcontractor-contracts/{id}/progress-payments/diary-suggestion?year&month` —
  `source_contract_item_id` köprüsü; **yalnız `contract.site_id = diary.site_id`** (S5); yanıt satırları
  uygulanırsa `quantity_source=diary` işaretlenir (taşeron mevcut mekanizma; işveren T1'deki yeni kolon).
- Öneri ucu YAZMAZ — salt okuma; uygulamak kullanıcının `PUT lines` çağrısıdır.

## T6 — Kapanış
- Tüm paket + ruff (tüm repo) + `alembic check` temiz + migration turu.
- `openapi.json` üret → `frontend/openapi/openapi.json`'a kopyala (backend main güncel — koşulsuz devir;
  gen:api ekran diliminde koşulur; BFF kökü `diary` o dilimin işi — nota yaz).

## T7 — FINAL REVIEW (Opus)
- Odak: IDOR · UQ/409 · draft-kilidi (submitted kayda yazma delikleri) · öneri uçlarının salt-okunurluğu ·
  türev tutarlılığı (summary ↔ lines) · kalıcı karar taraması (fotoğraf/planlama/malzeme sızıntısı var mı).
- `ARCHITECTURE-BACKEND.md` + `ROADMAP-BACKEND.md` güncelle, commit. Push/PR/merge/deploy kullanıcıda.
