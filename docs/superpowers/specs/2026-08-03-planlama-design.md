# Şantiye Planlama (backend spec)

Tarih: 2026-08-03 · Durum: **ONAYLANDI (2026-08-03)** — §6'nın BEŞ sorusu da önerildiği gibi onaylandı:
S1 izin `site_diary` · S2 ızgara TEK kaynak, GK gömülü bloğu salt-okunur türev özet + link (GK giriş
kontrollerinden ONAYLI SAPMA) · S3 ekipman satırları serbest metin (FK köprüsü makine dilimine) ·
S4 `site_plan_sprints` mini tablo; Hafta/Ay/Sprint kipi UI işi · S5 malzeme planı stok/satınalmaya pending.
Mockup: `Şantiye - Planlama.dc.html` (P — kanonik ızgara) · `Şantiye - Günlük Kayıt.dc.html` 321-348
(GK — gömülü 5-gün bloğu; §6 S2). SD'nin S3 kararıyla ayrılan dilim.
Not: mockup ızgara hücreleri salt-okunur `div` — düzenleme etkileşimi çizilmemiş; backend hücre-listesi
PUT'u sunar, giriş biçimi frontend diliminin tasarım işidir (o dilimde ayrıca ele alınır).

## 1. Kapsam
Haftalık plan ızgarası (kaynak × gün hücreleri) + haftalık hedefler + (S4'e göre) sprint etiketi.
İzin modülü **`site_diary`** (§6 S1 — bölüm emsali: ayrı modül açılmaz). Malzeme planı kartı bu dilimde
YOK (§6 S5). Plan-gerçekleşen kıyası YOK (mockup'ta da yok — türev raporu ileride).

## 2. Yeni tablolar
### `site_plan_rows` (ızgaranın satırları — kaynak)
`id` · `site_id` FK→sites CASCADE · `project_id` (görünürlük) · `kind` enum `plan_resource_kind
(crew, equipment)` (P158 "Makine & Ekipman" grubu) · `section_id` FK→sections SET NULL nullable
(crew satırının bölüm grubu; equipment'ta NULL) · `label` String(100) (P126 "Kalıpçı" / P162
"Tower Crane" — SERBEST METİN; makine modülü gelince FK köprüsü ayrı iş §6 S3) ·
`planned_worker_count` Integer nullable (P126 "(14)" — satır düzeyi) · `sort_order` ·
UQ (site_id, kind, section_id, label).

### `site_plan_cells` (satır × gün hücresi)
`id` · `row_id` FK→site_plan_rows CASCADE · `plan_date` Date · `text` String(200) (P127 "Kat 9 Kalıp",
P163 "✓ Çalışıyor" — metin ne diyorsa o) · `tag` enum `plan_cell_tag(blue, green, yellow, purple,
gray, red)` nullable — mockup'un renk kodu YORUMLANMADAN taşınır (P127-179; kategori/durum ayrımı
mockup'ta karışık, anlam frontend'de renkle birebir) · UQ (row_id, plan_date). Hücre yokluğu = plan yok.

### `site_plan_goals` (haftalık hedefler; P203-227)
`id` · `site_id` CASCADE · `project_id` · `week_start` Date (haftanın Pzt'si) · `title` Text (P208) ·
`note` Text nullable (P208/213/218/223 heterojen alt satırlar TEK serbest alanda — sorumlu/tarih/
miktar/bağımlılık ayrı kolonlara AYRIŞTIRILMAZ, mockup üç farklı biçim gösteriyor) · `is_done` bool
(P207 checkbox) · `status` enum `plan_goal_status(completed, in_progress, waiting, service_pending)`
(P209-224 rozetleri) — checkbox ve rozet mockup'ta AYRI göründüğü için ikisi de saklanır, birbirine
bağlanmaz · `sort_order`.

### (S4 onaylıysa) `site_plan_sprints`
`id` · `site_id` CASCADE · `name` String(150) (P107 "Kat 8–9 Tamamlama") · `is_active` bool ·
kısmi UQ (site_id) WHERE is_active. Tarih alanı YOK (mockup göstermiyor).

## 3. Uçlar (izin `site_diary`; `visible_projects` süzgeci; audit)
- `GET /sites/{site_id}/plan?week_start=` — satırlar (bölüm gruplu) + o haftanın hücreleri + hedefler
  + aktif sprint. Hafta aralığı/hafta sonu vurgusu TÜREV.
- `PUT /sites/{site_id}/plan/rows` — satır listesi DEĞİŞTİRME (satır silinince hücreleri CASCADE).
- `PUT /sites/{site_id}/plan/cells?week_start=` — **yalnız o haftanın** hücreleri DEĞİŞTİRME
  (kapsam sınırı: başka haftaya dokunulmadığı test edilir — PT PUT deseni) · FOR UPDATE.
- `PUT /sites/{site_id}/plan/goals?week_start=` — hedef listesi DEĞİŞTİRME.
- (S4) `PUT /sites/{site_id}/plan/sprint` — aktif sprint adı.
- Durum/taslak akışı YOK — mockup'ta tek "Kaydet" (P97); düz yazma + audit.

## 4. GK gömülü bloğu (§6 S2 kararına bağlı)
Öneri: ızgara TEK kaynak; GK'deki 5-gün bloğu F-SD ekranında ızgaradan TÜRETİLMİŞ SALT-OKUNUR özet
olur (gün başına: hücre metinlerinin birleşimi + crew satırlarının işçi toplamı + bölüm etiketleri) +
"Planlama'ya git" linki. Backend'e ek uç: `GET /sites/{site_id}/plan/day-summary?start=&days=5`.
GK bloğundaki textarea/number/select GİRİŞLERİ basılmaz (iki ekranın aynı veriyi farklı granülerlikte
düzenlemesi çelişki üretir) — bu, GK mockup'ından ONAYLI SAPMA olur.

## 5. Kapsam dışı / pending
Malzeme planı kartı (P185-201) → stok/satınalma dilimleri (frontend'de pending basılır) · ekipman
FK/makine modülü → kendi dilimi · plan-gerçekleşen kıyası → rapor katmanı · "Acil Sipariş" aksiyonları
→ procurement.

## 6. AÇIK SORULAR (kullanıcı cevabı ŞART)
- **S1 — İzin modülü:** planlama `site_diary` iznini kullanır (bölüm emsali; ayrı modül açılmaz;
  şef+saha müh. yazar, PM okur). Onay?
- **S2 — GK gömülü bloğu:** ızgara tek kaynak; GK bloğu salt-okunur türev özet + link (GK'nin giriş
  kontrollerinden ONAYLI SAPMA). Onay? Alternatif: iki ayrı veri modeli (önermem — çelişki üretir).
- **S3 — Ekipman satırları:** makine modülü yokken serbest metin `label` ile BU dilimde saklansın
  (modül gelince FK köprüsü ayrı iş)? Önerim: evet — mockup'un yarısı ekipman satırı.
- **S4 — Sprint:** mini tablo `site_plan_sprints` (yalnız ad + aktiflik) açılsın mı? Önerim: evet —
  P107 başlıkta gösteriyor; "Sprint" görünüm kipi ise UI işi, backend'e period tipi AÇILMAZ.
- **S5 — Malzeme planı:** stok/satınalma dilimlerine pending (backend'de tablo yok, frontend'de kart
  pending basılır). Onay?
