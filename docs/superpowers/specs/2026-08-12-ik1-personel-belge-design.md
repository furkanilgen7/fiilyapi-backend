# İK-1 — Personel kartı genişletme + belge takibi (backend spec)

Tarih: 2026-08-12 · Durum: **ONAYLANDI (hızlandırılmış düzen — kararlar §5'te yönetimce bağlı)**
Mockup: `Form - Personel Ekle.dc.html` (**PE**, 219) · `İK - Belge Takibi.dc.html` (**BT**, 191) ·
`Personel.dc.html` / `Personel Detay.dc.html` (liste/detay alan karşılıkları — F-PT2 pending'lerini
gerçeğe çevirir). Kapsam DIŞI: izin yönetimi (İK-2) · bordro/SGK bildirge üretimi (İK-3) ·
"Toplu Randevu"/"Randevu/Kurs/Eğitim Ata" aksiyonları (hedef ekran yok — AÇILMAZ).

## 1. Personel kartı genişletme (PE 51-118 birebir)

`personnel` tablosuna YENİ kolonlar (hepsi nullable — taslak-farkındalıklı zorunluluk §5 K3):
`tc_no` String(11) UQ-kısmi (PE 65; TCKN checksum doğrulaması — geçersizse 422) · `birth_date` ·
`gender` enum(male,female) · `marital_status` enum(single,married) · `phone` · `email` · `address`
Text · `emergency_contact_name` · `emergency_contact_phone` · `hire_date` (PE 101; P 147 "İşe giriş"
alt satırının kaynağı) · `wage_type` enum(daily,monthly,hourly) (PE 113) · `wage_amount` Numeric ·
`payment_method` enum(bank,cash,mixed) (PE 115) · `iban` String(34) · `sgk_no` String(20) (PE 117;
"otomatik sorgulama" YOK — pending İK-3) · `subcontractor_id` FK→subcontractors SET NULL (PE 94;
yalnız `worker_source=subcontractor` iken — aksi 422) · `assigned_project_id` FK SET NULL +
`assigned_section_id` FK SET NULL (PE 103/107; §5 K4) · `is_draft` bool (PE 39/211 "Taslak").
**Fotoğraf kolonu AÇILMAZ** (BC form-slot pending — §5 K6). Vergi no formda YOK → AÇILMAZ.

## 2. Belge takibi (BT birebir)

- **`personnel_document_types`** katalog: `name` · `is_mandatory` (PE B1-B3 ✱) · `validity_months`
  nullable (PE 141 "1 yıl" / 151 "3 yıl"; süresizler NULL) · `sort_order`. **SEED: 6 sabit tip**
  (Kimlik Fotokopisi · Sağlık Raporu[12 ay,✱] · İSG Eğitim Sertifikası[36 ay,✱] · Mesleki
  Yeterlilik · Operatör/Ehliyet · İş Sözleşmesi). Katalog CRUD ucu AÇILMAZ (yönetimi ayarlar
  dilimi); serbest belge = `type_id NULL + free_label` (PE 188-193 dropzone).
- **`personnel_documents`**: `personnel_id` CASCADE · `type_id` FK nullable · `free_label` nullable
  (ikisinden tam biri — CHECK) · `valid_until` Date nullable · `issued_at` Date nullable ·
  **`document_id` FK→documents SET NULL nullable** — **BC-2 PİLOTU**: dosya baytları BC arşivine
  (`POST /documents`, proje kapsamı §5 K5), İK kaydı künyeye bağlanır. Dosyasız kayıt da meşru
  (yalnız takip).
- **Durum TÜREV** (kolon yok): `valid` · `expiring` (≤30 gün — tek kaynak sabit) · `expired` ·
  `missing` (zorunlu tip için kaydı olmayan AKTİF personel). BT KPI/dağılım/iki liste bu türevden.

## 3. Uçlar (~9; izin `personnel` modülü — mevcut)

Personel POST/PATCH genişlemesi (taslak-farkındalıklı: `is_draft=true` gevşek, yayında PE ✱ alanları
zorunlu — P6 `_merged_for_validation` deseni) · `GET /personnel` liste yanıtına yeni alanlar +
`?project_id=` süzgeci (§5 K4 ile artık anlamlı; PT'nin "proje süzgeci yok" kararı atama kolonu
olmadığı İÇİNDİ — kolon açılınca süzgeç meşru, karar güncellendi) · belge alt-kaynağı
(`GET/POST /personnel/{id}/documents` + `PATCH/DELETE /personnel/documents/{id}` — silme `admin`) ·
**`GET /hr/documents/summary`** (BT: 5 KPI + tip dağılımı + süresi-dolan/yaklaşan listeleri;
tek gidiş-dönüş hedefi, N+1 ölçümlü).

## 4. Kapsam dışı / pending

SGK bildirge üretimi + "otomatik oluşturulsun" checkbox'ı (İK-3) · sgk_no otomatik sorgulama ·
30-gün hatırlatma BİLDİRİMİ (altyapı yok — durum türevi yeter) · randevu/kurs/eğitim aksiyonları ·
foto (BC form-slot) · izin/bordro · P KPI'larından "Sahada Aktif"/"İzinde"/"Aylık Maliyet"
(izin+puantaj türevi — İK-2/3).

## 5. Yönetimin bağladığı kararlar

K1 TCKN checksum doğrulanır, UQ (NULL'lar serbest; çift TCKN 409) · K2 `Serbest Meslek`/`Stajyer`
tipleri: `worker_source` enum'una **eklenmez** — PE 90 select'i 4 seçenekli ama backend enum'u 3'lü
(company/subcontractor/general); F-PT kararı 4'ün devamı: iki seçenek frontend'de devre-dışı KALIR,
enum takası İK-3'te (SGK 4a/4b ayrımı netleşince) · K3 tüm yeni kolonlar nullable + taslak-yayın
zorunluluğu servis katmanında · K4 atama kolonları açılır (PE ✱), liste süzgeci `?project_id=`
eklenir · K5 BC-2 pilotu: İK belgeleri BC arşivine `personnel` klasör kapsamında proje-düzeyi yazılır
(personelin atandığı projesi varsa o proje; dosyasız kayıt + sonradan bağlama serbest) · K6 foto
kolonu yok · K7 kapanış TEK PAKET (⚡); smoke "a" projesinde, SMOKE- önekli, kalıntı politikası
WORKFLOW §4.

## 6. Test odakları

Taslak→yayın zorunluluk atlatması (P6 emsali senaryo) · TCKN checksum + UQ · tip-kaynak CHECK
(type_id XOR free_label) · durum türev sınırları (30/31 gün · expired · missing yalnız aktif+zorunlu) ·
BC bağı (document_id görünmez belge → 404; SET NULL davranışı) · `subcontractor_id` yalnız taşeron
tipinde · IDOR · N+1 · migration turu (yeni enum'larda DROP TYPE).
