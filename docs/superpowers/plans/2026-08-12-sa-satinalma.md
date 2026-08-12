# SA — Satınalma (backend plan)

Tarih: 2026-08-12 · Spec: `../specs/2026-08-12-sa-satinalma-design.md` (ONAYLI) ·
Dal: `feat/sa-satinalma` (güncel main'den — `3562a63` ST merge'i dahil) · Task başına TEK subagent,
her task sonunda commit.

## T1 — Migration + modeller + izin
- ÖNCE seed kontrolü: `purchasing` anahtarı seed'de mi (ST zarfı bu adı kullandı)? Varsa izin
  migration'ı yok; yoksa yeni modül (seed+migration+matris testi birlikte).
- **5 tablo** (`suppliers` · `purchase_requests` · `purchase_request_lines` · `purchase_quotes` ·
  `purchase_orders`) + **4 enum** (`payment_terms` · `purchase_priority` · `purchase_request_status` ·
  `purchase_order_status`) + **`stock_entries.purchase_order_id`** additive kolonu.
  Ebeveyn: **`e1f2a3b4c5d6`** (`alembic heads` TEK head doğrula; farklıysa DUR). `env.py` importu
  (TB1 kuralı). Downgrade `DROP TYPE` tam.
- Numara üreticileri: `SAT-YYYY-NNNN` / `SP-YYYY-NNNN` sunucu tarafı (yıl bazlı sıra; yarış koşulu
  FOR UPDATE/sequence ile).
- Tur upgrade→downgrade→upgrade temiz; migration testi açık revizyon id.

## T2 — Tedarikçi + talep (TDD)
- Tedarikçi CRUD (DELETE yok, `is_active`); "Bu Yıl Toplam Sipariş" türevi liste yanıtında.
- Talep CRUD: taslak-farkındalıklı zorunluluk (P6 emsali: draft gevşek, submit sıkı) · kalemler
  gövdede (stok kartlı VEYA free_text; "Mevcut Stok" yanıtta ST bakiye türevi) · PATCH yalnız draft ·
  DELETE draft · liste süzgeçleri + TB3 sayfalama · IDOR.
- Mutasyon denetimi.

## T3 — Onay + teklif + sipariş (TDD)
- `submit`/`approve`/`reject`: geçiş matrisi tek kaynak (TH `build_transition_table` deseni);
  approve → otomatik `quote_wait`; **₺500K eşiği** (sınır testleri 499.999/500.000; eşik üstü
  approve yalnız üst seviye rol — tek kaynak sabit).
- Teklif alt-kaynağı (yalnız `quote_wait`te yazılır; başka talebin teklifi 404) + `select-and-order`
  (atomik: teklif işaretle + sipariş üret + talep `ordered`; numara üret).
- Doğrudan sipariş POST (`request_id`siz) + sipariş listesi/detay + durum filtreleri.
- Mutasyon denetimi.

## T4 — ST bağı + summary + Excel (TDD)
- Stok girişi `purchase_order_id` taşıyınca: sipariş → `delivered` + bağlı talep → `delivered`
  (ST modülüyle entegrasyon testi; görünmez sipariş referansı 404 — §4b kanonu).
- `pending_orders` zarfı gerçeğe: `available=true`, değer = approved+in_transit sayısı
  (zarf sözleşme testi: available=true ⇒ pending_module=null).
- `purchasing/summary` (SAT/SIP KPI'ları) · teklif karşılaştırma Excel'i (S5; openpyxl geri-okuma).
- Mutasyon denetimi.

## T5 — Kapanış + FINAL REVIEW (Opus)
- Tüm paket + ruff tüm repo + `alembic check` + tur + tek head.
- Review odağı: geçiş matrisi dışı 409 · eşik atlatma denemesi (draft'ta düşük tutarla submit,
  sonra kalem şişirme — approve anında yeniden doğrulama VAR MI, bizzat dene) · select-and-order
  atomikliği · ST zinciri · kalıcı karar taraması (onay motoru / puan kolonu / e-posta / mal kabul
  ucu / kısmi teslim alanı = bulgu). Bulgular kapatılır.
- openapi üret → DEVİR KURALI; **ST dersi gereği devir bu merge'le AYNI turda hedeflenir** —
  frontend F-ST dalında olabilir; durumu raporla, main'e dönüş anını kullanıcıyla koordine et.
- `ARCHITECTURE-BACKEND.md` + `ROADMAP-BACKEND.md` güncelle, commit.
