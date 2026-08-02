# P8 — Ünite Satışı (uygulama planı)

Spec: `../specs/2026-08-02-p8-unite-satisi-design.md` · Ön şart: spec §8 sorularının kullanıcı cevabı.
Dal: `feat/p8-unite-satisi` (main'den; TB1 merge'liyse taze main). Her task = tek subagent + commit ·
TDD (önce test, KIRMIZI) · DB komutları HEP override'lı (WORKFLOW §4).

## T1 — Migration + modeller
- `customers` + `unit_sales` + `sale_installments` + enum'lar (spec §2); kısmi unique index'ler
  (TCKN/VKN; ünite başına tek açık satış). S1 cevabına göre `sales` izin modülü seed'i
  (seed_data + migration + matris testi ÜÇÜ BİRLİKTE — tuzak: `test_seed_migration_matches_seed_data`).
- Ebeveyn = o günkü main HEAD (açık revizyon id; `head`/`-1` yasak). upgrade→downgrade→upgrade;
  downgrade'de `DROP TYPE`'lar.

## T2 — customers modülü (TDD)
- Router/service/repository/schemas: GET liste (arama: ad/TCKN/VKN) · POST · GET/PATCH detay.
- Tip-bazlı doğrulama (person→TCKN, company→VKN), çakışmada 409. Audit.

## T3 — unit_sales çekirdeği (TDD)
- POST /projects/{id}/sales (ünite görünürlük + `owner_side` kapısı + açık-kayıt tekliği) · GET liste
  (tahsil/kalan türevleri) · GET/PATCH detay · DELETE (yalnız reservation, can_delete deseni).
- `units.sales_status` senkronu (spec §3) + elle girişin PATCH /units'ten çıkarılması + testleri.

## T4 — Ödeme planı (TDD)
- `generate-plan` (peşinat + eşit taksit + vade farkı; kuruş dengeleme son taksitte) ·
  `PUT installments` (DEĞİŞTİRME semantiği; toplam=sale_price doğrulaması; FOR UPDATE kilit —
  TB1 dağıtım kilidi deseni) · S2 onaylıysa `pay` ucu (kısmi ödeme destekli).

## T5 — Durum geçişleri + summary (TDD)
- `activate`/`transfer-deed`/`cancel` (gerekçeli; geçiş matrisi testleri; ünite senkronu her geçişte).
- `GET /projects/{id}/sales/summary`: S55-59 KPI'ları + yaklaşan tahsilatlar (30 gün) + gecikme faizi
  gösterim türevi (S5). `units/summary.py`'daki `_UNIT_SALES` yer tutucuları GERÇEK veriye bağlanır.

## T6 — Kapanış
- Tüm paket + ruff (tüm repo) + migration turu. `openapi.json` üret → `frontend/openapi/`ye kopyala,
  gen:api devri notu (BFF kökleri frontend diliminde: `sales`, `customers`).

## T7 — FINAL REVIEW (Opus)
- Odak: IDOR (visible_projects her uçta) · ünite-satış senkron yarışları · plan toplam/kuruş ·
  geçiş matrisi delikleri · seed matris tutarlılığı · kalıcı karar ihlali var mı (maliyet/kâr, min_sale_price).
- `ARCHITECTURE-BACKEND.md` (modül+router+tablo+migration) + `ROADMAP-BACKEND.md` güncelle, commit.
  Push/PR/merge/deploy kararı kullanıcıda.
