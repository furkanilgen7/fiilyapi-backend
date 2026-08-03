# Puantaj — timesheet (backend spec)

Tarih: 2026-08-03 · Durum: **ONAYLANDI (2026-08-03)** — §7'nin BEŞ sorusu da önerildiği gibi onaylandı:
S1 minimum `personnel` çekirdeği bu dilimde (İK'nın kalanı ertelenmiş) · S2 `overtime_hours` opsiyonel
kolonu + FM hücresinde opsiyonel saat (onaylı sapma) · S3 onay akışı AÇILMAZ (düz kaydet + audit) ·
S4 toplu kaydet = dönem+şantiye kapsamında DEĞİŞTİRME · S5 meslek serbest metin.
Mockup'lar: `Ekran 5 - Puantaj.dc.html` (E5 — genel, ay×kişi matrisi) · `Şantiye - Puantaj.dc.html`
(ŞP — şantiye sekmesi; +`G` kodu, Tür rozeti, bölüm filtresi, FM saat toplamı).
Hazır zemin: seed'de `timesheet` (şef **full**, saha müh. **view**, İK full, PM none — satır 171) ve
`personnel` (İK full, şef **view** — satır 172) modülleri · `WorkerSource` enum'u (site_diary) ·
`Subcontractor` tablosu · `sites/projects` servislerindeki `_TIMESHEET` worker_count yer tutucuları.

## 1. Kapsam
Minimum `personnel` çekirdeği (§7 S1) + `timesheet_entries` (gün×kişi hücre kaydı) + matris okuma /
toplu yazma / Excel export uçları. **İK'nın geri kalanı (belge takibi, izin yönetimi, SGK, bordro)
ERTELENMİŞ KALIR** — bu dilim yalnız puantajın çalışması için gereken asgari personel kaydını açar.

## 2. Yeni tablolar
### `personnel` (izin modülü `personnel`)
`id` · `full_name` String(200) NOT NULL · `trade` String(100) (serbest metin — diary `trade` deseni,
katalog YOK §7 S5) · `source` enum `worker_source` YENİDEN KULLANILIR (company/subcontractor/general;
`general` mockup'ta görünmese de enum'dan atılmaz) · `subcontractor_id` FK→subcontractors SET NULL
nullable (ŞP 169 "— Akın İnşaat") · `user_id` FK→users SET NULL nullable (ofis personeli opsiyonel
köprü; login ŞART DEĞİL) · `is_active` bool · created/updated_at.
CHECK: `source≠'subcontractor'` iken `subcontractor_id` NULL olmalı (ters yön zorlanmaz — taslak esnekliği).

### `timesheet_entries` (izin modülü `timesheet`)
`id` · `personnel_id` FK→personnel RESTRICT · `site_id` FK→sites CASCADE · `project_id` (görünürlük) ·
`section_id` FK→sections SET NULL nullable (ŞP 99 bölüm filtresi) · `work_date` Date ·
`code` enum `timesheet_code(worked, leave, holiday, overtime, temporary_duty)` — E5'in 4'lüsü + ŞP'nin
`G`'si tek sette · `overtime_hours` Numeric(4,1) nullable (§7 S2) · `created_by` RESTRICT ·
**UQ (personnel_id, work_date)** — kişi bir günde TEK yerde (şantiye çakışması bu UQ ile engellenir).
Kişi/gün toplamları TÜREV — kolon açılmaz (diary deseni).

## 3. Uçlar
### personnel (`personnel` izni; şirket-geneli, proje süzgeci YOK — İK varlığı)
`GET /personnel` (arama + source/subcontractor/is_active filtreleri) · `POST` · `GET/PATCH /{id}` ·
silme YOK (puantaj bağlı; `is_active=false` ile pasifleştirme).
### timesheet (`timesheet` izni; `visible_projects` süzgeci)
- `GET /sites/{site_id}/timesheet?year&month(&section_id)` — matris: kişi listesi (ad+meslek+tür+firma)
  + gün hücreleri + türev toplamlar (kişi adam-gün · günlük sayı · `+` FM'li gün · `G` sayısı ·
  toplam adam-gün · FM saat toplamı) + bölüm başlık şeridi (ŞP 116-119).
- `PUT /sites/{site_id}/timesheet?year&month` — **toplu DEĞİŞTİRME (dönem+şantiye kapsamı):** gövde
  hücrelerin tam kümesi; gönderilmeyen hücre SİLİNİR (§7 S4). FOR UPDATE kilit; audit tek olay
  (dönem özeti ile).
- `GET /sites/{site_id}/timesheet/export.xlsx?year&month` — matris Excel (audit/boq export deseni).
- Genel ekran (E5) ayrı uç GEREKTİRMEZ — aynı uçlar şantiye seçicisiyle kullanılır.
**Onay akışı AÇILMAZ (§7 S3)** — mockup'ta yalnız "Kaydet" var; durum/submit yok, audit izi yeter.

## 4. Köprüler / yer tutucular
`sites/projects` servislerindeki `_TIMESHEET` worker_count yer tutucuları GERÇEK sayıya bağlanır
(aktif dönemde kaydı olan distinct personel). `site_diary_worker_counts` köprüsü bu dilimde KURULMAZ
(günlük agrega ayrı kalır; ileride türetme ayrı iş). Bildirim anahtarı eklenmez.

## 5. Bilinçli sınırlar
Şantiye şefi `personnel:view` — işçi EKLEYEMEZ (İK ekler); matris kararı değişmez, ROADMAP'e not ·
yarım gün/rapor kodu YOK (mockup'ta yok; ileride enum genişletmesi) · bordro/ücret hesabı `payroll`
diliminde · Makine/Personel ekranları kendi dilimlerinde.

## 6. Frontend'e devir notları
BFF kökleri ekran diliminde: `personnel` + `timesheet` (export dahil) · matris UI toplu kaydet
DEĞİŞTİRME semantiğini bilmeli · FM hücresinde opsiyonel saat girişi (S2 onaylanırsa) onaylı sapma.

## 7. AÇIK SORULAR (kullanıcı cevabı ŞART)
- **S1 — Minimum personel çekirdeği:** puantaj için `personnel` tablosu BU dilimde açılsın (İK'nın
  kalanı ertelenmiş kalır)? Önerim: **evet** — bunsuz puantaj yazılamaz (işçiler login kullanıcısı değil).
- **S2 — FM saatleri:** ŞP 119 "128 saat fazla mesai" istiyor ama hücrede saat girişi yok (model
  boşluğu). Önerim: `overtime_hours` nullable kolonu — FM hücresine OPSİYONEL saat girilebilir
  (onaylı sapma); girilmezse toplam yalnız girilenlerden. Alternatif: saat toplamı pending.
- **S3 — Onay akışı:** mockup'ta yok → AÇILMAZ (düz kaydet + audit). Onay?
- **S4 — Toplu kaydet semantiği:** dönem+şantiye kapsamında DEĞİŞTİRME (gönderilmeyen hücre silinir —
  matris bütün olarak kaydedilir). Onay?
- **S5 — Meslek:** serbest metin (katalog tablosu YOK — diary deseniyle tutarlı). Onay?
