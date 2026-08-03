# Şantiye Günlüğü — site_diary (backend spec)

Tarih: 2026-08-02 · Durum: **ONAYLANDI (2026-08-02)** — §7'nin BEŞ sorusu da önerildiği gibi onaylandı:
S1 fotoğraflar belge çekirdeğine ertelendi (tablo yok) · S2 **Seçenek B**: salt-okunur "günlükten doldur"
öneri ucu + işveren satırına `quantity_source` kolonu; otomatik ay-sonu üretim YOK (ileride B'nin üstüne
ayrı dilim olabilir) · S3 Planlama ayrı dilim · S4 malzeme kullanımı stok dilimine pending ·
S5 site'sız taşeron sözleşmeleri öneriden hariç (elle).
Mockup'lar: `Şantiye - Günlük Kayıt.dc.html` (GK — **kanonik**, 457 satır) · `Ekran 7 - Şantiye Günlüğü
Girişi.dc.html` (E7 — eski/basit sürüm; GK'de olmayan alanları korunur) · ilişkili: `Şantiye - Hakediş
Özeti` (aynı ekranın 3. modu, türev) · `Şantiye - Planlama` (§7 S3).
Hazır bağlantılar: `QuantitySource.diary` enum'u (taşeron hakediş satırında) · seed'de `site_diary`
izin modülü (şef+saha müh. **full**, patron full, PM **view**, İK/muhasebe/satınalma none) ·
`daily_log_missing` bildirim anahtarı.

## 1. Kapsam
Günlük kayıt çekirdeği: 3 yeni tablo + durum akışı + poz-bazlı günlük miktar girişi + ay-bazlı
agregasyon + hakediş "günlükten doldur" önerisi (§7 S2). İzin modülü **`site_diary`** (seed hazır —
matris DEĞİŞMEZ, izin migration'ı gerekmez).

## 2. Yeni tablolar
### `site_diary_entries`
`id` · `site_id` FK→sites CASCADE · `project_id` (görünürlük süzgeci) · `entry_date` Date ·
**UQ (site_id, entry_date)** — günde TEK kayıt (GK deseni; bölüm kırılımı satırda değil etikette) ·
`section_id` FK→sections SET NULL nullable (GK198 "Bölüm") · `weather` enum
(`sunny/partly_cloudy/cloudy/rainy/snowy` — E7'nin 5'lisi süperset; GK'nin 4'lüsü alt küme) ·
`temperature_c` Numeric(4,1) · `work_done` Text (GK271) · `chief_note` Text (E7 143 — korunur) ·
İSG: `safety_meeting_held` + `ppe_checked` + `has_incident` bool + `incident_note` Text (GK444-447) ·
`status` enum `diary_status(draft, submitted)` + `submitted_at` (E7'de iki buton: Taslak Kaydet /
Gönder; GK'nin tek "Kaydet & Gönder" butonu ikisinin bileşiği — iki uç da açılır) · `created_by` RESTRICT.
**"Yağışlı" rozeti (GK370) kolon DEĞİL** — frontend `weather=rainy` türevi.

### `site_diary_lines`
`entry_id` CASCADE · **`boq_item_id` FK→boq_items SET NULL** — poz kaynağı **BOQ** (tek şantiye-bazlı
+ fiyatlı + `contract_item_id` köprülü tablo; GK212 "Sözleşme BOQ'a bağlı" rozetiyle birebir) ·
snapshot `code/description/unit/unit_price` · `quantity` Numeric(14,3) ≥0 (GK228 "Bugün Yapılan") ·
UQ (entry_id, boq_item_id). Kümülatif (GK229) ve ₺ katkı (GK230) TÜREV — kolon açılmaz; ₺ hesabı
katsayısız `quantity × unit_price` (katsayı hakediş katmanının işi).

### `site_diary_worker_counts`
`entry_id` CASCADE · `trade` String(100) (serbest metin — katalog yok; GK "Kalıpçı/Demirci/…") ·
`source` enum `worker_source(company, subcontractor, general)` (GK418-430 rozetleri) · `count` ≥0 ·
UQ (entry_id, trade, source). Toplam türev. Taşeron ADI bağlanmaz (mockup'ta seçici yok);
puantaj modülü gelince köprülenir.

## 3. Uçlar (izin `site_diary`; hepsi `visible_projects` süzgeci; audit tam kapsam)
- `GET /sites/{site_id}/diary?year&month` (liste + "Son Kayıtlar" verisi: durum, işçi toplamı, satır
  ₺ toplamı) · `GET /diary/{entry_id}` · `POST /sites/{site_id}/diary` (BOQ pozları otomatik satır
  iskeleti — GK'de satır ekle/sil yok, liste BOQ'dan gelir) · `PATCH /diary/{entry_id}` +
  `PUT /diary/{entry_id}/lines` (DEĞİŞTİRME semantiği) — yalnız `draft` · `POST /diary/{entry_id}/submit`
  · `POST /diary/{entry_id}/reopen` (yalnız admin — yanlış gönderim düzeltmesi) · `DELETE` draft+`can_delete`.
- **Agregasyon:** `GET /sites/{site_id}/diary/summary?year&month` — poz bazlı aylık toplamlar
  (Hakediş Özeti ekranının veri kaynağı; yalnız `submitted` kayıtlar sayılır).

## 4. Hakediş entegrasyonu (§7 S2 kapsam onayına bağlı)
- **Otomasyon YOK** (zamanlanmış iş altyapısı yok; ay sonu kendiliğinden hakediş ÜRETİLMEZ).
- **"Günlükten doldur" önerisi:** taslak hakediş için `GET .../diary-suggestion?year&month` ucu:
  günlük toplamlarını sözleşme kalemine eşleyip önerilen miktarları döner (işveren:
  `boq_items.contract_item_id` köprüsü; taşeron: `source_contract_item_id` köprüsü + **yalnız
  `contract.site_id = günlük.site_id` eşleşen sözleşmeler** — site'sız sözleşme kapsam DIŞI → §7 S5).
- Öneriyle yazılan taşeron satırı `quantity_source=diary` işaretlenir (mekanizma hazır);
  **işveren satırına da `quantity_source` kolonu eklenir** (bugün yalnız taşeronda var — asimetri kapanır).

## 5. Pending / kapsam dışı
Fotoğraflar (GK274-318) → §7 S1 · Planlama bloğu + `Şantiye - Planlama` ekranı → §7 S3 ·
Malzeme kullanımı (E7 107-138) → §7 S4 (stok) · "Belgeler" sekmesi → belge çekirdeği ·
Onay Kutusu rozeti → approvals dilimi · `daily_log_missing` bildirimi → bildirim motoru yok, tetikleyici yazılmaz.

## 6. Frontend'e devir notları (bu dilim backend; ekran dilimi ayrı)
Mod anahtarı (Kayıt Gir / Planlama / Hakediş Özeti) tek `site_id` bağlamında üç görünüm ·
BFF kökü `diary` o dilimde eklenecek · GK'nin sağ panel hakediş birikimi mevcut summary uçları +
yeni diary summary'den beslenir.

## 7. AÇIK SORULAR (kullanıcı cevabı ŞART)
- **S1 — Fotoğraflar:** Kalıcı karar 8 "belgeler kendi diliminde" der; 20×10MB DB bytea'ya uygun değil.
  Önerim: fotoğraflar **belge çekirdeğine ertelenir** (tablo açılmaz, ekran diliminde pending kart).
  Alternatif: şimdi `site_diary_photos` bytea (önerMEM). Onay?
- **S2 — Hakediş entegrasyon kapsamı:** "günlükten doldur" ÖNERİ ucu (kullanıcı onaylı, otomasyon yok)
  + işveren satırına `quantity_source` kolonu — bu kapsam yeterli mi? (Tam otomatik ay-sonu üretim
  önermiyorum — geri alınamaz yazma + zamanlayıcı yok.)
- **S3 — Planlama:** GK'deki 5-gün bloğu + `Şantiye - Planlama.dc.html` AYRI dilime kalsın
  (kendi mockup'ı var, günlükten farklı kimlik)? Önerim: evet.
- **S4 — Malzeme kullanımı (E7):** stok dilimine pending? Önerim: evet (stok tablosu yok).
- **S5 — Site'sız taşeron sözleşmesi:** proje-geneli sözleşmeler (site_id NULL) günlük önerisinden
  hariç, miktarları elle mi girilir? Önerim: evet (şantiye eşlemesi tek-anlamlı değil).
