# Taşeron Hakedişi (uygulama planı)

Spec: `../specs/2026-08-02-taseron-hakedisi-design.md` · Ön şart: spec §8 sorularının kullanıcı cevabı.
Dal: `feat/taseron-hakedisi` (güncel main'den) · Her task = tek subagent + commit · TDD (önce test,
KIRMIZI) · DB komutları HEP override'lı (WORKFLOW §4).

> **Migration zinciri uyarısı:** yerelde İKİ head olabilir (P6 dalı `d4e5f6a7b8c9` henüz merge değil).
> Bu dilimin migration'ı **main HEAD'ine** bağlanır (açık revizyon id ile tespit et); P6 merge olursa
> ikinci re-parent İKİNCİ merge'de yapılır (WORKFLOW §4 çift-head kuralı). `head`/`-1` YASAK.

## T1 — Migration + modeller
- `subcontractor_progress_payments` + `_lines` + `subcontractor_payment_status` + `quantity_source`
  enum'ları; `subcontractor_contracts.vat_pct` kolonu (S1 kararına göre default); kısmi UQ'lar.
- upgrade→downgrade→upgrade yerelde temiz; downgrade'de `DROP TYPE`'lar.

## T2 — Çekirdek CRUD (TDD)
- `POST /subcontractor-contracts/{id}/progress-payments` (kalemler sözleşmeden otomatik; fiyatsız kalem
  guard'ı 422; snapshot yüzdeler; sequence_no sözleşme içi maks+1; draft/pending varken 409).
- `GET` liste (filtreler) + detay + `PATCH` (dönem/açıklama/katsayı/section) + `DELETE` draft+can_delete.
- IDOR: her uç `visible_projects`; testleri işveren hakediş idor testlerinden desenle.

## T3 — Satırlar + hesap (TDD)
- `PUT {id}/lines` DEĞİŞTİRME semantiği + FOR UPDATE kilit + kota (S3 kararına göre tavan) ·
  `refresh-prices` · `calculations.py` yeniden kullanımı; teminat + katsayı onaylı sapması;
  kuruş hassasiyeti (mockup'ın L146 hesap hatası test edilmez — doğru formül test edilir).

## T4 — Durum makinesi + summary (TDD)
- 5 aksiyon + geçiş tablosu + onayda kota yeniden doğrulaması (kilit altında) + `rejected_at/reason`
  damgası ve "Revize Gerekli" türevinin yanıtta dönmesi (`is_revision_required` alanı).
- `GET .../summary`: 4 KPI (dönem+proje filtreli) — brüt/net tanımını spec §3'e sabitle.

## T5 — index_type ek task'ı
- `GET /projects/{id}/contract` yanıtına `index_type` + `has_price_escalation` (additive; şema testi).

## T6 — Kapanış
- Tüm paket + ruff (tüm repo) + migration turu + `alembic check` temiz.
- `openapi.json` üret; **frontend'e kopyalama KOŞULLU:** P6 backend main'e girdiyse taze (P6+P8+TH)
  devir yapılabilir; girmediyse kopyalama — devir F-P6 kapanışındaki tek seferlik akışa bırakılır, nota yaz.

## T7 — FINAL REVIEW (Opus)
- Odak: IDOR · kota yarışları · geçiş delikleri · snapshot tutarlılığı · işveren deseniyle kopya kod
  yerine paylaşım yapılmış mı (calculations/transitions yeniden kullanım) · kalıcı karar taraması.
- `ARCHITECTURE-BACKEND.md` + `ROADMAP-BACKEND.md` güncelle, commit. Push/PR/merge/deploy kullanıcıda.

## Devir notu (T6, 2026-08-02)

`backend/openapi.json` üretildi (T5 sonrası güncel; `EmployerContractDetail` artık `index_type` +
`has_price_escalation` taşıyor, 18 `subcontractor…` uç yolu şemada). Dosya `.gitignore`'lu, commit
edilmez.

**Frontend'e KOPYALANMADI — bilinçli karar:** P6 backend dalı (`feat/p6-bolum-detay`) main'e
girmedi, dolayısıyla bu dalın şeması P6 uçlarını içermiyor. Şimdi devredilirse frontend
sözleşmesi eksik/kararsız bir ara duruma sabitlenir. Devir **F-P6 kapanışındaki tek seferlik
akışa** bırakıldı: o akışta P6 + P8 + TH (taşeron hakedişi) şemaları BİRLİKTE üretilip
`frontend/openapi/openapi.json`'a tek seferde taşınır ve `pnpm gen:api` bir kez koşulur.
Bu dilimde `frontend/` klasörüne hiç dokunulmadı.
