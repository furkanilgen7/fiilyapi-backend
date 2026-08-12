# SA — Satınalma (backend spec)

Tarih: 2026-08-12 · Durum: **ONAYLANDI (2026-08-12)** — §7'nin ALTI sorusu da önerildiği gibi:
S1 6'lı durum kümesi · S2 tek onay adımı + ₺500K eşiği (zincir motoru AÇILMAZ) · S3 talepsiz sipariş
meşru · S4 stok girişi otomatik delivered (mal kabul ucu yok; kısmi teslim bilinen sınır) ·
S5 karşılaştırma Excel'i BU dilimde · S6 iki desen de 4 haneli sunucu üretimi.
Mockup: `Satınalma & Teklif.dc.html` (**SAT**) · `Satınalma - Siparişler.dc.html` (**SIP**) ·
`Satınalma - Teklifler.dc.html` (**TEK** — karşılaştırma detayı) · `Satınalma - Tedarikçiler.dc.html`
(**TED**) · `Form - Satinalma Talebi.dc.html` (**FST**). ST spec §4b kanonu (varlık referansı=404)
ve ST hafıza kaydındaki pending zarflar bu dilimin girdisidir.

## 1. Kapsam

Satınalma zinciri: tedarikçi kataloğu + satın alma talebi (kalemli, onaylı) + teklif toplama/
karşılaştırma + sipariş + **ST bağı** (sipariş↔stok girişi; `pending_orders` zarfı gerçeğe döner).
Mockup'ta ÇİZİLMEMİŞ ekranlar (teklif giriş formu · sipariş oluşturma · mal kabul · onay ekranı ·
tedarikçi formu): backend uçları veri modelinden açılır, formlar F-SA'nın işi (türetilmiş etkileşim
kararları o dilimde). "Onay Kutusu" ekranı ayrı dilim.

## 2. Şema (tek migration + ST'ye 1 additive kolon)

- **`suppliers`** (TED kartı): `name` String(200) · `category` String(100) (serbest — TED alt-etiket) ·
  `tax_no` String(10) · `phone` String(30) · `payment_terms` enum `payment_terms(cash, days_15,
  days_30, days_60)` (TED 50/71/91/112 + FST 134) · `is_active` (TED 45 rozet). **Puan/performans
  kolonu AÇILMAZ** (değerlendirme girişi yok — pending); "Bu Yıl Toplam Sipariş" TÜREV.
- **`purchase_requests`** (FST + SAT tablosu): `request_no` (sunucu üretir §7 S6) · `request_date` ·
  `priority` enum `(normal, urgent, critical)` (FST 55) · `project_id` FK · `site_id`/`section_id`
  nullable (FST 57) · `needed_by` Date (FST 58) · `justification` Text(2000) · `status` §7 S1 ·
  `quote_deadline` Date nullable (FST 133) · onay meta (approved_by/at · rejected_at/reason).
- **`purchase_request_lines`**: `request_id` CASCADE · `stock_item_id` FK nullable (FST 104 "stok
  kartından seç") + `free_text_name`/`unit` (FST "yeni malzeme tanımla" — katalogsuz kalem) ·
  `quantity` >0 · `estimated_unit_price` nullable · satır/toplam tutar TÜREV. "Mevcut Stok" sütunu
  (FST 75) TÜREV — ST bakiyesinden, kolon açılmaz.
- **`purchase_quotes`** (TEK kartları): `request_id` CASCADE · `supplier_id` FK · `unit_price` ·
  `delivery_time` String(100) (TEK 67 "3 iş günü"/"Yarın sabah" — SERBEST metin, gün sayısına
  ZORLANMAZ) · `warranty_note` String(200) · `payment_terms` enum (aynı) · `shipping_included` bool +
  `shipping_cost` nullable (TEK 90 "Hariç (+₺8.000)") · `is_selected` bool. "EN İYİ FİYAT"/"EN HIZLI"
  rozetleri TÜREV (kolon yok).
- **`purchase_orders`** (SIP): `order_no` (sunucu §7 S6) · `request_id` FK nullable (SIP çaprazı:
  SP-035'in talebi yok — talepten VEYA doğrudan) · `quote_id` nullable · `supplier_id` FK ·
  `project_id` · `total_amount` · `expected_delivery` Date (SIP 65 renk türevi istemcide) ·
  `status` enum `(approved, in_transit, delivered)` (SIP 34 filtresi birebir) · not.
- **ST bağı:** `stock_entries.purchase_order_id` FK nullable (additive — SG 85 "İlgili Sipariş"
  gerçeğe döner). Kalemler FST 92 `MKN-0192` deseniyle stok kartına bağlanır.
- **Tedarikçi FK'ları:** ST'nin `supplier_name` serbest metni DEĞİŞMEZ (kayıtlı karar); yeni
  satınalma kayıtları `supplier_id` kullanır.
- İzin: seed'de `purchasing` anahtarı (ST zarfı bu adı kullandı) — T1 kontrol; yoksa yeni modül.

## 3. Durum makineleri ve kurallar

- **Talep** (§7 S1): `draft → pending_approval → quote_wait → ordered → delivered` + `rejected`
  (SAT rozetleri: Onay Bekliyor/Teklif Bekleniyor/Sipariş Verildi/Teslim Edildi + FST Taslak).
  `approve` → otomatik `quote_wait`; `reject` gerekçeli (TH emsali).
- **Onay eşiği** (§7 S2): FST 166 "₺500K+ → Patron" — tek onay adımı + eşik kuralı: tahmini toplam
  ≥ 500.000 ise `approve` yalnız üst seviye rolde. Eşik tek kaynak sabit. Çok-adımlı onay MOTORU
  AÇILMAZ (FST 159-165 zinciri frontend görsel türevi).
- **Teklif:** talep `quote_wait`teyken eklenir/düzenlenir; "Sipariş Ver" = teklif seç + sipariş üret
  (atomik; talep → `ordered`). Seçilmeyen teklifler durur (rozet türev).
- **Sipariş → teslim:** stok girişi `purchase_order_id` ile kaydedilince sipariş **otomatik
  `delivered`** + talep `delivered` (§7 S4; kısmi teslim ayrımı YOK — bilinen sınır, SG "eksik
  teslimat" notu metin olarak kalır). `pending_orders` zarfı: `available=true`, değer = approved+
  in_transit sipariş sayısı.
- Durum kodu kanonu: gövde içi varlık referansı 404 · biçim/kural ihlali 422 (ST §4b).
- KPI'lar (SAT 69-86 / SIP 38-43) türev uçtan; "Onay Bekleyen" sayacı dahil.

## 4. Uçlar (~16)

Tedarikçi CRUD (DELETE yok — `is_active`) · talep CRUD (PATCH yalnız draft; DELETE `can_delete`
draft) + `submit`/`approve`/`reject` + liste (durum/proje/öncelik/`q` süzgeç + TB3 sayfalama) ·
teklif alt-kaynağı (talep altında liste/POST/PATCH/DELETE) + `select-and-order` (atomik sipariş
üretimi) · sipariş listesi/detay + doğrudan POST (talepsiz — SIP 35) · `purchasing/summary`.
Excel (TEK 38 karşılaştırma dışa aktarımı) §7 S5.

## 5. Kapsam dışı / pending

Teklif isteme e-postası (FST 135) + eksik-teslimat oto-bildirimi → bildirim altyapısı yok, pending ·
FST ekleri (şartname/görsel) → BC form-slot pending · tedarikçi puanı → değerlendirme girişi yok,
pending · "Onay Kutusu" ekranı/ucu → ayrı dilim · sipariş `expected_delivery` renk kodu → istemci
türevi · tedarikçi detay alanları (adres/e-posta/IBAN) → mockup'ta yok, AÇILMAZ.

## 6. Test odakları

Durum makinesi geçiş matrisi (matris dışı 409 — TH deseni) · eşik kuralı (499.999/500.000 sınır
testleri) · select-and-order atomikliği · stok girişi→delivered zinciri (ST ile entegrasyon testi) ·
katalogsuz kalem (free_text) · IDOR · N+1 · TB3 sayfalama · migration turu.

## 7. AÇIK SORULAR (kullanıcı cevabı ŞART)

- **S1 — Talep durum kümesi:** öneri: `draft/pending_approval/quote_wait/ordered/delivered/rejected`
  (6'lı; SAT+FST rozetleri birebir; "Revize" türevi YOK — mockup'ta yok).
- **S2 — Onay modeli:** öneri: TEK onay adımı + ₺500K eşiği (eşik üstü `approve` yalnız üst seviye
  rol). Çok-adımlı onay motoru (PM→Satınalma→Patron zinciri) AÇILMAZ — zincir görseli frontend
  türevi. Alternatif: gerçek zincir motoru (büyük iş; mockup'ta yalnız bilgi kutusu).
- **S3 — Doğrudan sipariş (talepsiz):** SIP 35 "+ Sipariş Oluştur" + SP-035'in talep karşılığı yok.
  Öneri: talepsiz sipariş MEŞRU (`request_id` nullable). Alternatif: her sipariş talepten.
- **S4 — Teslim akışı:** öneri: stok girişi (`purchase_order_id` ile) sipariş+talebi otomatik
  `delivered` yapar; ayrı "mal kabul" ucu AÇILMAZ (ekranı da yok). Kısmi teslim ayrımı yok — bilinen
  sınır.
- **S5 — Teklif karşılaştırma Excel'i (TEK 38):** öneri: BU dilimde açılır (openpyxl deseni hazır).
  Alternatif: F-SA'ya kadar beklet.
- **S6 — Numara desenleri:** talep `SAT-YYYY-NNNN` (FST 53) · sipariş `SP-YYYY-NNN` (SIP). Öneri:
  İKİSİ DE 4 haneli sıfır dolgulu sunucu üretimi; SIP'in 3 hanesi çizim artefaktı sayılır.
  Alternatif: birebir 3 hane.
