# ST — Stok Çekirdeği (backend plan)

Tarih: 2026-08-11 · Spec: `../specs/2026-08-11-st-stok-cekirdegi-design.md` (ONAYLI) ·
Dal: `feat/st-stok-cekirdegi` (güncel main'den — `e0f96e5` P11 merge'i dahil) · Task başına TEK
subagent, her task sonunda commit.

## T1 — Migration + modeller + izin
- ÖNCE seed kontrolü: `roles/seed_data.py`de stok anahtarı var mı? VARSA o kullanılır, izin
  migration'ı GEREKMEZ; YOKSA 21. modül `inventory` (seed+migration+matris testi BİRLİKTE — tuzak).
- 4 tablo (`stock_items` · `warehouses` · `stock_entries` · `stock_entry_lines`) + 3 enum
  (`stock_category` · `stock_entry_type` · `stock_quality`) — alanlar spec §2 birebir.
  Ebeveyn: **`d0e1f2a3b4c5`** (P11 head — `alembic heads` TEK head doğrula; farklıysa DUR).
  `alembic/env.py` importu (TB1 kuralı). Downgrade'de `DROP TYPE` ×3.
- Tur upgrade→downgrade→upgrade temiz; migration testi açık revizyon id.

## T2 — Katalog + depo uçları (TDD)
- `GET/POST /stock/items` + `PATCH /stock/items/{id}`: `code` UQ 409 · DELETE YOK (`is_active=false`;
  405 bekçisi) · liste filtreleri kategori/`q`/aktiflik.
- `GET/POST /warehouses` + `PATCH` + `DELETE` (yalnız hareketsizken, admin; doluysa 409).
  `site_id` nullable; şantiyeli depo IDOR `visible_projects`ten, merkez depo (S2b) izinle herkese.
- Mutasyon denetimi.

## T3 — Hareketler + türevler (TDD)
- `POST /stock/entries` (başlık+satırlar atomik): tip kuralları — `purchase` miktar >0 ·
  `transfer` `source_warehouse_id` ZORUNLU (kendine transfer 422) + kaynak depodan otomatik düşüş
  (ÇİFT BACAK — toplam korunumu testli) · `adjustment` negatif serbest. Eksi bakiye engellenmez.
  Bozuk satır → hiçbir şey yazılmaz. Audit giriş başına TEK olay.
- `GET /stock/entries` (tip/depo/tarih süzgeci, sayfalama TB3 deseni: limit 50/200 + offset + total).
- `GET /stock/summary` + `GET /sites/{id}/stock`: bakiyeler SUM türevi (kolon yok) · durum formülü
  S1 (tek kaynak sabitler; `min_stock` yoksa `None`; E3'ün 7 örnek satırı birebir senaryo) ·
  toplam değer = son giriş fiyatı × bakiye (S6; fiyatsız kalem ayrıca sayılır) · "Bekleyen Sipariş"
  + ŞS "Aylık İhtiyaç"/"Bölüm" pending zarfla. N+1 ölçüm testi.
- Mutasyon denetimi.

## T4 — Kapanış + FINAL REVIEW (Opus)
- Tüm paket + ruff tüm repo + `alembic check` + migration turu + tek head.
- Review odağı: çift bacak toplam korunumu (transfer stok yaratamaz — BİZZAT dene) · atomiklik ·
  IDOR (şantiye deposu + merkez depo ayrımı) · durum formülü sınırları · kalıcı karar taraması
  (sipariş FK / tedarikçi tablosu / sarf ucu / belge alanı / bölüm-ihtiyaç kolonu sızıntısı = bulgu).
- `openapi.json` üret → DEVİR KURALI (frontend durumuna bak; muhtemelen devir yapılmaz, rapor).
- `ARCHITECTURE-BACKEND.md` + `ROADMAP-BACKEND.md` güncelle, commit.
