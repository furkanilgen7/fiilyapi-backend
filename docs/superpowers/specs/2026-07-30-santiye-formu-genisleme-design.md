# Şantiye Ekle Formu — Backend Genişlemesi (Design Spec)

Tarih: 2026-07-30
Repo: `fiilyapi-backend`
Mockup kanonu: `projedesign/Form - Santiye Ekle.dc.html` (234 satır)
Desen kaynakları: P1.1a proje formu (`frontend/docs/.../2026-07-29-p1-1a-proje-formu-design.md`),
P2 şantiye/bölüm (`2026-07-27-alt-proje-2-p2-santiye-bolum-design.md`),
P3 üniteler (`2026-07-30-alt-proje-2-p3-proje-tip-detay-units-design.md`)

> Bu belge yalnız **tasarım**dır. Kod, migration, test yazılmadı; commit atılmadı.
> Uygulama planı ayrı bir belgede ve **kullanıcı onayından sonra** yazılır.

> **Revizyon 2026-07-30 (kullanıcı kararları):** §13'teki açık soruların tamamı karara
> bağlandı. Değişen bölümler: §1 (kapsam), §2.3/§2.5/§2.6, §3.0, §3.2, §3.4, §3.5, §4,
> §5, §6, §7 (silme uçları), §9, §10, §11, §12, §13 (yeniden yazıldı), §14 (yeni: onaylı
> sapmalar), §15 (yeni: task listesi). Karar özeti §13'tedir.

---

## 1. Kapsam

### 1.1 Kapsam içi

1. `sites` tablosunun mockup'ın istediği ~20 alanla genişletilmesi (kimlik, konum &
   alan, takvim & bütçe, tesisler).
2. `site_status` enum'una **`preparation`** ("Hazırlık") değerinin eklenmesi (satır 71).
3. Şantiye kodu **otomatik üretimi** — `SNT-{YYYY}-{NNN}` (satır 67 ipucu:
   "Boş bırakılırsa otomatik", örnek `SNT-2026-003`).
4. **Taslak desteği**: `sites.is_draft` + taslak-farkındalıklı doğrulama
   (satır 226 "Taslak Kaydet"). Projelerdeki desenin birebiri.
5. **Şantiye şefi** ve **İSG uzmanı**nın sistem kullanıcısına bağlanması
   (nullable FK + ad anlık görüntüsü) — satır 69, 70.
6. **Bölümlerin (fazların) şantiye ile aynı istekte, atomik olarak** yazılması
   (satır 102–144). P2'nin mevcut `sections` şeması yeniden kullanılır, kopyalanmaz.
7. `sections` tablosuna **yalnız `manager_user_id`** eklenmesi (satır 111).
   `estimated_amount` **EKLENMEZ** — "Tahmini Bedel" sütunu yer tutucu kalır (§3.4,
   kullanıcı kararı 2026-07-30).
8. **`DELETE /sites/{site_id}`** ve **`DELETE /sections/{section_id}`** uçlarının
   açılması — izin `sites` · **`admin`**, bağlı kayıt korkuluğu + denetim günlüğü (§7.1).
9. Pydantic şemaları, uçlar, Türkçe hata mesajları, denetim günlüğü kayıtları,
   migration ve test stratejisi.

### 1.2 Kapsam **dışı** (bu dilimde yapılmayacak)

| Konu | Mockup satırı | Gerekçe |
|---|---|---|
| **6 belge alanı** (Yapı Ruhsatı, İSG Risk Değerlendirmesi, Acil Durum Planı, Şantiye Yerleşim Planı, Zemin Etüt Raporu, Başlangıç Fotoğrafları) | 177–209 | Dosya yükleme altyapısı repoda **hiç yok**; kullanıcı kararı: ayrı "belge dilimi"ne bırakıldı. **Backend'e belge alanı/tablosu EKLENMEZ** |
| Sürükle-bırak "diğer belgeler" kutusu | 211–216 | Aynı gerekçe |
| "+ Yeni Personel Ekle" seçeneği | 69 | Personel modülü yok (`personnel` izin satırı var, kodu yok). Seçenek **basılmaz** — kullanıcı kararı |
| "Bölüm ekle veya **şablon kullan**" | 138 | Bölüm şablonu **hiç yazılmaz** — kullanıcı kararı 2026-07-30. **Onaylı sapma §14.1** |
| Bölüm satırı "Tahmini Bedel" sütunu | 114, 123 | Sunucuda saklanmaz; **yer tutucu** kalır (tek gerçek kaynak İş Kalemleri/BOQ). **Onaylı sapma §14.3** |
| "Oluşturduktan sonra poz dağılımı ekranına git" kutucuğu | 220–222 | Saf istemci navigasyon tercihi; sunucuda saklanmaz |
| "Poz Dağılımı →" bağlantısı ve poz kotası | 57, 59 | P5 (`contracts` + poz dağılımı) işi. **Kalıcı Karar 1**: ileri bağ açılmaz |

---

## 2. Mockup alan tablosu (satır satır)

Sıra mockup'taki DOM sırasıdır. "Backend karşılığı" sütununda **(var)** = mevcut kolon,
**(YENİ)** = bu dilimde açılan kolon, **(türev)** = saklanmaz, **(—)** = sunucuya gitmez.

### 2.1 Üst çubuk / bağlam (satır 31–60)

| Satır | Etiket | Tip | Zorunlu | Backend karşılığı | Not |
|---|---|---|---|---|---|
| 36–38 | Breadcrumb: Projeler / Güneşkent Konut / Yeni Şantiye | metin | — | — | Frontend |
| 42, 227 | "Şantiyeyi Oluştur" | buton | — | `POST /projects/{project_id}/sites` | `is_draft=false` |
| 226 | "Taslak Kaydet" | buton | — | aynı uç, `is_draft=true` | §5 |
| 41, 225 | "İptal" | bağlantı | — | — | Frontend |
| 56 | "Bağlı Proje: Güneşkent Konut (SZL-2025-001) · Taahhüt Projesi" | bilgi kutusu | — | mevcut `GET /projects/{id}` | Yalnız okuma; `contract_no` + `project_type` |
| 57, 59 | Poz dağılımı bilgisi / bağlantısı | metin + link | — | — | Kapsam dışı (§1.2) |

### 2.2 📍 Şantiye Bilgileri (satır 63–73)

| Satır | Etiket | Tip | Zorunlu | Backend karşılığı | Not |
|---|---|---|---|---|---|
| 66 | Şantiye Adı | text | **✔** | `sites.name` (var) | `String(150)`, hep zorunlu (taslakta da) |
| 67 | Şantiye Kodu | text (mono), ipucu "Boş bırakılırsa otomatik", örnek `SNT-2026-003` | — | `sites.code` (var) + **YENİ üretici** | §3.2 — mevcut ad-türevi üretici (`A-BLOK`) mockup'la çelişiyor, değiştirilir |
| 68 | Bağlı Proje | select | **✔** | `sites.project_id` (var) | Yol parametresi; gövdede taşınmaz |
| 69 | Şantiye Şefi | select (kullanıcı listesi) | **✔** (taslak-dışı) | `site_manager_user_id` **(YENİ, FK)** + `site_manager_name` (var, anlık görüntü) | "+ Yeni Personel Ekle" **basılmaz** (§1.2) |
| 70 | İSG Uzmanı | select: "Emre Şahin (A Sınıfı)" · "**Dış Kaynak — OSGB**", ipucu "İSG mevzuatı gereği zorunlu" | — (etikette `*` **yok**) | `safety_officer_user_id` **(YENİ, FK)** + `safety_officer_name` **(YENİ)** + `safety_officer_is_outsourced` **(YENİ, bool)** | §3.3 — OSGB seçeneğinin ele alınışı |
| 71 | Durum | select: Hazırlık · **Aktif** (seçili) · Beklemede | — | `sites.status` (var) + enum'a **`preparation`** eklenir | §3.1; varsayılan `active` (mockup `selected`) |

> **Karara bağlandı (2026-07-30) — satır 70:** İSG Uzmanı **zorunlu değildir**.
> Etikette kırmızı `*` yok; ipucu metni ("İSG mevzuatı gereği zorunlu") kullanıcıya
> **yalnız bilgilendirme**dir, sunucu zorlaması değildir. Alan taslak-dışı POST'ta da
> `nullable` kalır ve `_validate_site` onu **aramaz**. Gerekçe: mevzuat uyarısı ile
> veri zorunluluğu ayrı şeylerdir; canlıdaki İSG uzmanı atanmamış şantiyeler
> düzenlenemez hâle gelmemelidir (§11.3).

### 2.3 🗺 Konum & Alan (satır 76–88)

| Satır | Etiket | Tip | Zorunlu | Backend karşılığı | Not |
|---|---|---|---|---|---|
| 79 | İl / İlçe | text, örnek "Çankaya / Ankara" | **✔** (taslak-dışı) | `sites.city` (var) | **Tek serbest metin** — ayrı `district` kolonu İCAT EDİLMEZ (mockup tek input). `projects.city` ile aynı desen |
| 80 | Mahalle | text | — | `neighborhood` **(YENİ)** | `String(150)` |
| 81 | Ada / Parsel | text (mono), örnek "1234 / 5" | — | `parcel` **(YENİ)** | `String(50)`; `projects.parcel` ile aynı ad ve boy |
| 82 | Açık Adres | textarea rows=2 | — | `sites.address` (var) | `String(300)` yeterli, büyütülmez |
| 83 | GPS Koordinatı | text (mono), örnek "39.9042, 32.8597", ipucu "Puantaj konum doğrulaması için" | — | `gps_coordinates` **(YENİ)** | `String(50)` serbest metin, **doğrulama yok** — §3.5 (karar 2026-07-30 revize) |
| 84 | Arsa Alanı (m²) | number | — | `land_area_m2` **(YENİ)** | `Numeric(12,2)`, `ge=0` |
| 85 | İnşaat Alanı (m²) | number | **✔** (taslak-dışı) | `construction_area_m2` (**model**de var, P1.1a'da eklendi; **şemalarda YOK → bu dilimde eklenir**) | `Numeric(12,2)`, `ge=0`. Karara bağlandı (2026-07-30): `SiteCreate`/`SiteUpdate`/`SiteCard`'a eklenir |
| 86 | Kat Sayısı | **text** ("2 bodrum + 10 normal") | — | `floor_info` **(YENİ)** | `String(100)` — **sayı değil**; mockup `type="text"` ve örnek metinsel. `floor_count:int` İCAT EDİLMEZ |

### 2.4 📅 Takvim & Bütçe (satır 91–99)

| Satır | Etiket | Tip | Zorunlu | Backend karşılığı | Not |
|---|---|---|---|---|---|
| 94 | Başlangıç Tarihi | date | **✔** (taslak-dışı) | `sites.start_date` (var) | — |
| 95 | Planlanan Bitiş | date | **✔** (taslak-dışı) | `sites.end_date` (var) | — |
| 96 | Süre (Gün) | number, ipucu "Otomatik hesaplanır" | — | **(türev — saklanmaz)** | §3.6: `end − start + 1` (**uç-dahil**, Kalıcı Karar 3 ve P1.1a §4.5 ile birebir) |
| 97 | Şantiye Bütçesi (₺) | number | — | `budget` **(YENİ)** | `Numeric(18,2)` **nullable**, `ge=0`. §3.7 — BOQ türevi DEĞİL, kullanıcı planı |

> `sites.delivery_date` (var) mockup'ta **yok**; P2 mirasıdır, dokunulmaz — formdan
> yazılmaz, yanıtta durmaya devam eder.

### 2.5 🏗 Bölümler (Fazlar) (satır 102–144)

| Satır | Etiket | Tip | Zorunlu | Backend karşılığı | Not |
|---|---|---|---|---|---|
| 105 | "Şantiye iş fazlarına bölünür…" | metin | — | — | Frontend |
| 106, 136–139 | "+ Bölüm Ekle" / "Bölüm ekle veya şablon kullan" | buton | — | istemci satır ekler | **Şablon YAZILMAZ** — onaylı sapma §14.1 |
| 110, 119 | Bölüm Adı | text | ✔ (satır varsa) | `sections.name` (var) | `String(150)` |
| 111, 120 | Sorumlu | select (kullanıcı listesi) | — | `manager_user_id` **(YENİ, FK)** + `sections.manager_name` (var, anlık görüntü) | Şef ile aynı desen |
| 112, 121 | Başlangıç | date | — | `sections.start_date` (var) | — |
| 113, 122 | Bitiş | date | — | `sections.end_date` (var) | — |
| 114, 123 | Tahmini Bedel | number | — | **(yer tutucu — saklanmaz)** | **Kolon AÇILMAZ** (karar 2026-07-30). `SectionResponse.budget` `MetricPlaceholder(pending_module="boq")` olarak kalır; değer ileride İş Kalemleri/BOQ'dan hesaplanır. §3.4 · §14.3 |
| 115, 124 | Satır sil (`×`) | buton | — | — | Oluşturmadan önce istemci tarafı; sunucuya gitmez |
| — | (sıra) | — | — | `sections.sort_order` (var) | Gövdedeki dizi sırasından 0,1,2… atanır |
| — | (durum) | — | — | `sections.status` (var) | Formda yok → varsayılan `planned` |

### 2.6 📦 Depo & Şantiye Altyapısı (satır 147–174)

| Satır | Etiket | Tip | Zorunlu | Backend karşılığı | Mockup'ta ön-işaretli mi? |
|---|---|---|---|---|---|
| 153 | D-1 Kapalı Ambar | checkbox | — | `has_closed_warehouse` **(YENİ)** | ✔ (yok sayılır) |
| 154 | D-2 Açık Alan (Demir, kum, çakıl) | checkbox | — | `has_open_storage` **(YENİ)** | ✔ (yok sayılır) |
| 155 | D-3 Soğuk Hava Deposu | checkbox | — | `has_cold_storage` **(YENİ)** | ✗ |
| 161 | Şantiye Ofisi (Konteyner) | checkbox | — | `has_site_office` **(YENİ)** | ✔ (yok sayılır) |
| 162 | İşçi Yemekhanesi | checkbox | — | `has_canteen` **(YENİ)** | ✔ (yok sayılır) |
| 163 | Soyunma / WC | checkbox | — | `has_changing_room_wc` **(YENİ)** | ✔ (yok sayılır) |
| 164 | İşçi Yatakhanesi | checkbox | — | `has_dormitory` **(YENİ)** | ✗ |
| 165 | Revir / İlk Yardım | checkbox | — | `has_infirmary` **(YENİ)** | ✔ (yok sayılır) |
| 170 | Elektrik Aboneliği | text (mono), "Abone no" | — | `electricity_subscription_no` **(YENİ)** | `String(50)` |
| 171 | Su Aboneliği | text (mono), "Abone no" | — | `water_subscription_no` **(YENİ)** | `String(50)` |
| 172 | Planlanan İşçi Sayısı | number | — | `planned_worker_count` **(YENİ)** | `Integer` nullable, `ge=0` |

> **Karara bağlandı (2026-07-30) — tesis varsayılanları HEPSİ BOŞ başlar.**
> Mockup'taki 6 ön-işaretli kutucuk **örnek veri** sayılır, gerçek varsayılan değil:
> her şantiyenin kapalı ambarı, yemekhanesi veya revirinin olduğunu varsaymak
> **sessiz yanlış veri** üretir (kullanıcı işaretlemediği hâlde "var" kaydedilir).
> Bu yüzden:
> * DB kolon varsayılanı: sekizi de `NOT NULL` + `server_default=false`.
> * Pydantic `SiteFacilitiesInput` alan varsayılanı: sekizi de `False`.
> * **Frontend de ön-işaret basmaz** — form boş açılır (onaylı sapma §14.2).
>
> Yani mockup'ın işaretli hâli hiçbir katmanda uygulanmaz.

> **Depo alanları ileri bağ AÇMAZ** (Kalıcı Karar 1): `inventory` modülü geldiğinde
> gerçek depo kayıtları açılacak. Buradaki üç kutucuk yalnız **beyan**dır, `warehouses`
> tablosuna FK verilmez ve öyle bir tablo bu dilimde açılmaz.

### 2.7 📎 Şantiye Belgeleri (satır 177–217) — **KAPSAM DIŞI**

| Satır | Etiket | Karar |
|---|---|---|
| 183 | Yapı Ruhsatı `*` | **Yapılmaz** — ayrı belge dilimi |
| 188 | İSG Risk Değerlendirmesi `*` | **Yapılmaz** |
| 193 | Acil Durum Planı `*` | **Yapılmaz** |
| 198 | Şantiye Yerleşim Planı | **Yapılmaz** |
| 203 | Zemin Etüt Raporu | **Yapılmaz** |
| 208 | Başlangıç Fotoğrafları | **Yapılmaz** |
| 211–216 | "Diğer şantiye belgelerini sürükleyin" | **Yapılmaz** |

Backend'e **hiçbir belge kolonu, tablosu veya ucu eklenmez.** Frontend bu kartı
`pending_module: "documents"` zarif düşüşüyle gösterir (Kalıcı Karar 4 deseni).
Üç belgenin mockup'ta `*` ile zorunlu işaretlenmesi, şantiye oluşturmayı **engellemez**:
sunucu belge bilmez.

---

## 3. `sites` şema genişlemesi

### 3.0 Yeni kolon listesi (özet)

| # | Kolon | Tip | Null | Sunucu varsayılanı | Mockup |
|---|---|---|---|---|---|
| 1 | `site_manager_user_id` | UUID FK → `users.id` `ON DELETE SET NULL`, index | ✔ | — | 69 |
| 2 | `safety_officer_user_id` | UUID FK → `users.id` `ON DELETE SET NULL`, index | ✔ | — | 70 |
| 3 | `safety_officer_name` | `String(200)` | ✔ | — | 70 |
| 4 | `safety_officer_is_outsourced` | `Boolean` | ✗ | `false` | 70 |
| 5 | `neighborhood` | `String(150)` | ✔ | — | 80 |
| 6 | `parcel` | `String(50)` | ✔ | — | 81 |
| 7 | `gps_coordinates` | `String(50)` | ✔ | — | 83 |
| 8 | `land_area_m2` | `Numeric(12,2)` | ✔ | — | 84 |
| 9 | `floor_info` | `String(100)` | ✔ | — | 86 |
| 10 | `budget` | `Numeric(18,2)` | ✔ | — | 97 |
| 11 | `has_closed_warehouse` | `Boolean` | ✗ | `false` | 153 |
| 12 | `has_open_storage` | `Boolean` | ✗ | `false` | 154 |
| 13 | `has_cold_storage` | `Boolean` | ✗ | `false` | 155 |
| 14 | `has_site_office` | `Boolean` | ✗ | `false` | 161 |
| 15 | `has_canteen` | `Boolean` | ✗ | `false` | 162 |
| 16 | `has_changing_room_wc` | `Boolean` | ✗ | `false` | 163 |
| 17 | `has_dormitory` | `Boolean` | ✗ | `false` | 164 |
| 18 | `has_infirmary` | `Boolean` | ✗ | `false` | 165 |
| 19 | `electricity_subscription_no` | `String(50)` | ✔ | — | 170 |
| 20 | `water_subscription_no` | `String(50)` | ✔ | — | 171 |
| 21 | `planned_worker_count` | `Integer` | ✔ | — | 172 |
| 22 | `is_draft` | `Boolean` | ✗ | `false` | 226 |

**Toplam: `sites` tablosuna 22 yeni kolon.**

`sections` tablosuna: **yalnız** `manager_user_id UUID FK → users.id ON DELETE SET NULL, index` (111).
`estimated_amount` **eklenmez** (§3.4, §14.3).

Tek yeni DB `CHECK` kısıtı `ck_sites_safety_officer`'dır (§3.3). GPS için aralık/biçim
`CHECK`'i **açılmaz** (§3.5).

**Hiçbir yeni kolon `NOT NULL` + varsayılansız değildir** → mevcut canlı satırlar kırılmaz (§11).

### 3.1 `site_status` enum'una `preparation`

Mockup satır 71 sırası: **Hazırlık · Aktif (seçili) · Beklemede**. Mevcut enum
`active · on_hold · completed`. Yeni enum:

```
preparation · active · on_hold · completed
```

`completed` UI'da görünmez ama **KALIR**: `SiteCounts.completed`, `_remaining_days`
(satır `sites/service.py:143`) ve P2 liste sekmesi ona bağlıdır — kaldırmak canlı veriyi
ve iki ekranı kırar (`projects` `completed` kararının birebir aynısı).

Migration deseni `d1a2b3c4e5f6_p1_1a_status_enum.py`den **birebir kopyalanır**
(tip takası; `ALTER TYPE … ADD VALUE` kullanılmaz, çünkü geri alınamaz):

```sql
CREATE TYPE site_status_new AS ENUM ('preparation','active','on_hold','completed');
ALTER TABLE sites ALTER COLUMN status DROP DEFAULT;
ALTER TABLE sites ALTER COLUMN status TYPE site_status_new USING status::text::site_status_new;
DROP TYPE site_status;
ALTER TYPE site_status_new RENAME TO site_status;
ALTER TABLE sites ALTER COLUMN status SET DEFAULT 'active';
```

`downgrade`: önce `UPDATE sites SET status='active' WHERE status='preparation'`, sonra
ters takas (sıra tersse `USING` çevrimi geçersiz değerde patlar).

Varsayılan `active` **kalır** (mockup 71'de `Aktif` `selected`).

### 3.2 Şantiye kodu üretimi — `SNT-{YYYY}-{NNN}`

Mockup satır 67: yer tutucu `SNT-2026-003`, ipucu "Boş bırakılırsa otomatik".
Mevcut üretici `sites/service.py:derive_code` **addan** kod türetiyor (`A-Blok Şantiyesi`
→ `A-BLOK`) — mockup ile **çelişir**. Kural: mockup kazanır.

Yeni üretici, `projects.service._next_project_code` deseninin birebiri:

```
prefix = f"SNT-{today().year}-"
max_seq = mevcut kodlar arasındaki en büyük sayısal sonek
kod = f"{prefix}{max_seq + 1:03d}"      # sayımla DEĞİL, maksimum+1
```

**Karara bağlandı (2026-07-30): numaralandırma kapsamı ŞİRKET GENELİ (global).**

Gerekçe — `PRJ-` emsali koddan doğrulandı:
`projects/repository.py:47 list_codes_with_prefix` sorgusu
`select(Project.code).where(Project.code.like(f"{prefix}%"))` — **hiçbir kapsam
süzgeci yok**. `projects` tablosunun kendisi zaten en üst katman olduğu için
`PRJ-{YYYY}-{NNN}` fiilen şirket geneli tek sayaçtır. Şantiye kodu da aynı deseni
kullanacaksa aynı kapsamda olmalıdır: `_next_site_code` sorgusu **`project_id`
süzgeci taşımaz**, `Site.code LIKE 'SNT-{yıl}-%'` üzerinden maksimum+1 alır.
İkinci gerekçe: şantiye kodu evrakta (irsaliye, puantaj, hakediş) kurumsal kimlik
gibi kullanılır; iki farklı projede aynı `SNT-2026-003` kullanıcıyı yanıltır.

**Kısıt değişmez:** DB benzersizlik kısıtı `uq_sites_project_code (project_id, code)`
**olduğu gibi kalır** — global `UNIQUE`'e çevirmek mevcut canlı ad-türevi kodlarda
(`A-BLOK` iki projede birden olabilir) migration'ı patlatır (§11.3). Yani **üretim
global tekil, kısıt proje içi tekil**; kullanıcı elle çakışan kod girerse 409 döner.

**Karara bağlandı (2026-07-30): mevcut `derive_code` / `_unique_code` KALDIRILIR.**
Tek üretici `_next_site_code` olur; `projects.service._write_inline_sites` (proje
formundaki satır içi şantiyeler) de onu çağırır — iki farklı kod deseni yan yana
yaşamaz. **Canlıdaki mevcut kodlar OLDUĞU GİBİ KALIR**: hiçbir `UPDATE` yazılmaz,
`A-BLOK` gibi eski kodlar yerinde durur ve `SNT-` sayacına **karışmaz** (`LIKE`
süzgeci onları görmez). Yalnız yeni kayıtlar `SNT-{YYYY}-{NNN}` alır.
Kullanıcı **açıkça** kod verdiyse sessizce değiştirilmez (mevcut davranış korunur).

### 3.3 İSG uzmanı ve "Dış Kaynak — OSGB" (satır 70)

Mockup açılırında iki tür seçenek var:
`Emre Şahin (A Sınıfı)` (bir kişi) ve `Dış Kaynak — OSGB` (bir kişi değil, bir tedarik biçimi).

**Öneri (mockup satır 70'e dayalı):** üç kolonlu ayrım —

* `safety_officer_user_id` (FK): "Emre Şahin" seçilirse dolu.
* `safety_officer_is_outsourced` (bool): "Dış Kaynak — OSGB" seçilirse `true`.
* `safety_officer_name` (String 200): FK doluyken `users.full_name` anlık görüntüsü
  (`projects.employer_name` deseni: join'siz okunur, kullanıcı silinse/pasifleşse de
  denetim ve liste ekranı kırılmaz). OSGB seçilince sabit `"Dış Kaynak — OSGB"` yazılır.

**OSGB firma adı alanı İCAT EDİLMEZ** — mockup'ta böyle bir input yok. OSGB sözleşmesi
gerçek bir kartoteks ihtiyacına dönüşürse Alt-Proje 3 (firmalar) işidir.

DB `CHECK` (karşılıklı dışlama):

```sql
CONSTRAINT ck_sites_safety_officer CHECK (
  NOT (safety_officer_is_outsourced AND safety_officer_user_id IS NOT NULL)
)
```

`(A Sınıfı)` etiketi kullanıcı **unvanıdır** (`users.title`) — yeni kolon açılmaz,
frontend `title`ı parantez içinde basar.

### 3.4 "Tahmini Bedel" — yer tutucu kalır (karar 2026-07-30)

P2 spec §2.2 açıkça diyor: *"`budget` sütunu YOK — bölüm bedeli BOQ kalemlerinin
toplamıdır, türevdir."* Mockup satır 114/123 ise **elle girilen** "Tahmini Bedel"
istiyor (`1840000`, `2960000`).

**Karar: P2 kazanır — `sections.estimated_amount` EKLENMEZ.**

Gerekçe: elle girilen tahmin ile İş Kalemleri/BOQ toplamı **aynı büyüklüğün iki
kaynağıdır**. İkisi yan yana durursa kaçınılmaz olarak ayrışır ve hangisinin doğru
olduğu belirsizleşir — bu, sistemin en pahalı hata biçimidir (sessiz veri çelişkisi).
Tek gerçek kaynak korunur: **bölüm bedeli İş Kalemleri/BOQ'dan hesaplanır.**

Uygulama sonuçları:

* `sections` tablosuna **yalnız `manager_user_id`** eklenir.
* `SiteSectionInput` şemasında `estimated_amount` alanı **yoktur**; gövdede
  gelirse Pydantic tarafından yok sayılır (mevcut `model_config` davranışı).
* `SectionResponse.budget` **`MetricPlaceholder(pending_module="boq")` olarak kalır**.
* Frontend "Tahmini Bedel" sütununu **yer tutucu** olarak gösterir (girilebilir ama
  sunucuya gitmeyen bir alan **basılmaz**; sütun salt-okunur "—" / bekleyen modül
  rozetiyle çizilir). Onaylı sapma §14.3.

### 3.5 GPS koordinatı — tek metin kolonu (karar 2026-07-30, revize)

**Karar: `gps_coordinates String(50)`, nullable, serbest metin.**
`latitude`/`longitude` `Numeric` ikilisi **açılmaz**.

> Bu madde gün içinde **iki kez** karara bağlandı. İlk karar iki sayısal kolondu;
> gerekçesi puantaj konum doğrulamasıydı. Ardından kullanıcı **puantaj konum
> doğrulamasının şu an yapılmayacağını** bildirdi → tek metin kolonuna dönüldü.
> Kayıt burada bilerek bırakılmıştır ki ileride "neden metin?" sorusu tekrar sorulmasın.

**Gerekçe:** koordinatın bugün **hiçbir tüketicisi yok**. Değeri okuyup mesafe/harita
işi yapan tek aday puantaj dilimiydi ve o iş kapsam dışına alındı. Tüketicisi olmayan
bir alanı iki sayısal kolona bölmek, aralık `CHECK`'leri ve "yarım koordinat" kuralı
eklemek **şu an spekülatif yapıdır** (YAGNI): kullanılmayan invariantlar bakım borcu
üretir. Mockup da tek kutu veriyor (satır 83) — birebir karşılığı tek kolondur.

**Doğrulama: YOK.** Sunucu tarafında ayrıştırma yapılmaz, enlem/boylam aralığı
(−90..90 / −180..180) **kontrol edilmez**, biçim regex'i **koşulmaz**. Alan
`max_length=50` dışında serbesttir. Ayrıştırma olmadığı için aralık doğrulaması da
tanımsızdır; yarım doğrulama (bazı biçimleri kabul, bazılarını reddet) kullanıcıyı
geçerli girdide bloke ederdi.

**DB `CHECK` açılmaz.**

**Gelecek iş notu (puantaj dilimi):** konum doğrulaması geldiğinde iş şudur —
(1) `latitude`/`longitude Numeric(9,6)` kolonlarını ekleyen migration,
(2) mevcut `gps_coordinates` metinlerini ayrıştırıp dolduran veri geçişi
(ayrıştırılamayan satırlar `NULL` bırakılır, **sessizce atılmaz**, rapor edilir),
(3) `gps_coordinates`'ın görüntüleme alanı olarak kalması veya düşürülmesi kararı.
**Bu üç iş o dilimin sorumluluğudur, bu dilimin değil.** Metinden sayıya göç
tersinden kolaydır; bu yüzden geç karar vermenin maliyeti düşüktür.

### 3.6 Süre (Gün) saklanmaz

Satır 96 ipucu "Otomatik hesaplanır" → **türev**. Kalıcı Karar 3 ve P1.1a §4.5 ile
birebir: `end − start + 1` (**uç-dahil**), hesabı **frontend** yapar (`derive.ts`).
Backend ne kolon açar ne alan döner. Tarihlerden biri boşsa veya `end < start` ise boş.

### 3.7 `sites.budget` — plan, türev değil

Satır 97 "Şantiye Bütçesi (₺)". P2'de `sites.contract_amount` bilinçli olarak yoktu
(işveren sözleşmesi proje düzeyinde). `budget` **onun yerini almaz**: sözleşme bedeli
değil, şantiyeye ayrılan **planlanan bütçedir** (`projects.budget` ile aynı anlam).
`nullable` — "girilmedi" ile "sıfır bütçe" ayrımı korunsun (`projects.budget` NOT NULL
default 0'dan bilinçli farklılık; orada dört kalemden hesaplanıyor, burada elle giriliyor).

**Karara bağlandı (2026-07-30): çapraz kontrol YOK.** Bir projeye bağlı şantiyelerin
`budget` toplamı `projects.budget`'ı aşsa bile sunucu **uyarı üretmez, engellemez**.
Gerekçe: proje bütçesi dört kalemden hesaplanan bir plan, şantiye bütçesi ayrı bir
plandır; ikisi arasında zorunlu bir muhasebe bağı bu dilimde tanımlı değildir. Böyle
bir kural, henüz sahibi olmayan bir invariant uydurmak olurdu. Bütçe tutarlılığı
raporlaması ileride (Mali Özet / gösterge paneli) ele alınır.

---

## 4. Tesisler nasıl saklanacak? — **KARAR: 8 ayrı Boolean kolon**

Söz konusu 8 kutucuk: 3 depo (153–155) + 5 tesis (161–165).

> **Karara bağlandı (2026-07-30): Seçenek A — her tesis ayrı `Boolean` kolon.**
> JSONB / yan tablo alternatifi **değerlendirmeden çıkarılmıştır**; aşağıda yalnız
> seçilen tasarım ve gerekçesi durur. Bu karar tekrar açılmaz.

```python
has_closed_warehouse: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                                   default=False, server_default=text("false"))
# … 7 tane daha
```

**Gerekçe**
* Liste mockup'ta **sabit ve sonlu**; şema gerçeği yansıtır.
* Tip güvenliği: Pydantic alan alan doğrular, yazım hatası **derleme/şema** zamanında yakalanır.
* Sorgulanabilir/indekslenebilir: "yatakhanesi olan şantiyeler" düz `WHERE`; JSONB'de
  operatör + cast gerekir.
* Alembic ile açıkça göç eder; kolon ekleme/kaldırma tarihçesi görünür.
* Repo deseniyle uyumlu: `project_contracts.has_price_escalation`, `employers.is_active` —
  bu kod tabanında hiç JSONB yok, ilk JSONB'yi buraya sokmak tek başına bir mimari sapmadır.

**Kabul edilen bedel**
* `sites` 22 yeni kolonla toplam ~35 kolona çıkar (Postgres için sorun değil, okunabilirlik için gürültü).
* Yeni bir tesis türü eklemek migration ister — liste mockup'ta sabit olduğu için bu
  maliyet gerçekleşmesi düşük bir maliyettir.

### 4.1 API'de gruplanmış sözleşme

Kolon gürültüsü API'de **iç içe bir şema ile** gizlenir — DB düz, sözleşme gruplu
(mockup'taki iki grup birebir):

```json
"facilities": {
  "closed_warehouse": false, "open_storage": false, "cold_storage": false,
  "site_office": false, "canteen": false, "changing_room_wc": false,
  "dormitory": false, "infirmary": false
}
```

Yukarıdaki gövde **yeni bir şantiyenin varsayılan hâlidir**: sekizi de `false`
(§2.6 kararı — ön-işaret yok).

### 4.2 Neden JSONB değil (kayıt)

Değerlendirilip **reddedilen** alternatif tek `facilities JSONB` kolonuydu. Ret
gerekçesi kayda geçer ki ileride tekrar önerilmesin: anahtar yazım hatası JSONB'de
**sessizce** geçer (`has_canteene: true` → kimse fark etmez), `NOT NULL` anahtar
düzeyinde ifade edilemez, kısmi güncelleme elle birleştirme kodu ister ve bu kod
tabanında **hiç JSONB deseni yok** — ilkini buraya sokmak tek başına bir mimari
sapmadır.

---

## 5. `is_draft` ve taslak davranışı

`projects.is_draft` deseninin birebiri (`Boolean NOT NULL default false server_default false`).

### 5.1 Doğrulamanın taslakta gevşemesi

`_validate_site(data, is_draft)` — P1.1a `_validate_project` deseni:

| # | Kural | Taslakta | Taslak-dışında |
|---|---|---|---|
| 1 | `name` boş olamaz | **uygulanır** (Pydantic `min_length=1`) | uygulanır |
| 2 | `end_date >= start_date` | **uygulanır** (tutarlılık) | uygulanır |
| 3 | Bölüm satırı: `end_date >= start_date` | **uygulanır** | uygulanır |
| 4 | Alanlar/tutarlar `>= 0` | **uygulanır** (Pydantic `ge=0`) | uygulanır |
| 5 | GPS biçimi | **kural YOK** (§3.5) | **kural YOK** |
| 6 | İSG: FK + OSGB aynı anda olamaz | **uygulanır** | uygulanır |
| 6b | İSG uzmanı **hiçbir koşulda zorunlu değil** (§2.2 kararı) | — | — |
| 7 | Şantiye şefi zorunlu (69) | atlanır | **uygulanır** |
| 8 | İl/İlçe zorunlu (79) | atlanır | **uygulanır** |
| 9 | İnşaat alanı zorunlu (85) | atlanır | **uygulanır** |
| 10 | Başlangıç + bitiş tarihi zorunlu (94, 95) | atlanır | **uygulanır** |
| 11 | Bölüm adı boş olamaz (satır varsa) | **uygulanır** | uygulanır |

Kural: **tutarlılık kuralları her zaman, zorunluluk kuralları yalnız taslak-dışında.**
Yarım kalmış bir taslak asla geçersiz veri saklamaz, yalnız eksik veri saklar.

### 5.2 Görünürlük ve sayaç

* **Karara bağlandı (2026-07-30):** taslak şantiye, **projeye erişimi olan herkese
  görünür** — projelerdeki desenin birebiri. Ayrı süzgeç, "yalnız benim taslaklarım"
  kavramı veya oluşturan-kullanıcı bazlı gizleme **yoktur**.
* `SiteCard.is_draft` alanı eklenir → frontend rozet basar (`ProjectListItem.is_draft` deseni).
* **Karara bağlandı (2026-07-30):** `SiteCounts.draft` listede **ROZET** olarak
  gösterilir; **ayrı sekme açılmaz** (projelerdeki desen). Backend her hâlükârda
  sayacı döndürür; bu karar frontend dilimini bağlar.
* `SiteCounts`'a **`draft: int`** eklenir (`ProjectCounts.draft` deseni). Ekleme, kırıcı değil.
* Taslaklar `counts.active/on_hold/completed` sayaçlarından **düşülmez** (durumları ne ise
  o sayılır); yalnız `draft` sayacı ayrıca artar — mevcut `_site_counts` davranışı korunur,
  tek ekleme yapılır. *(Projede dashboard "aktif proje" sayacı taslakları eliyor; şantiye
  için dashboard sayacı **yok**, dolayısıyla bu dilimde eleme gerekmez.)*

### 5.3 Taslaktan yayına geçiş

`PATCH /sites/{id}` gövdesinde `is_draft: false` gelirse: **birleşik kayıt** (mevcut satır +
patch) üzerinde §5.1'in 7–11 kuralları koşar. Geçmezse `422`, satır **taslak kalır**.
`is_draft: true` → `false` geçişi denetim günlüğüne ayrı satır yazar (§10).

`PATCH`'te bunun dışında **zorunluluk doğrulaması koşulmaz** — koşarsa canlıdaki eski
(şefsiz/alan bilgisi olmayan) şantiyeler düzenlenemez hâle gelir (§11.4).

---

## 6. Pydantic şemaları

### 6.1 Giriş

```python
class SiteFacilitiesInput(BaseModel):
    """Mockup 153–155 (depo) + 161–165 (tesis). DB'de 8 düz Boolean kolon (§4).

    Sekizinin de varsayılanı `False` — mockup'taki ön-işaretler ÖRNEK VERİDİR,
    varsayılan değildir (§2.6 kararı, 2026-07-30).
    """
    closed_warehouse: bool = False
    open_storage: bool = False
    cold_storage: bool = False
    site_office: bool = False
    canteen: bool = False
    changing_room_wc: bool = False
    dormitory: bool = False
    infirmary: bool = False


class SiteSectionInput(BaseModel):
    """Form içi bölüm satırı (mockup 119–124). P2 `SectionCreate`'in yerine geçmez;
    ONUN yanında durur ve aynı `Section` modelini yazar."""
    name: str = Field(min_length=1, max_length=150)
    code: str | None = Field(default=None, min_length=1, max_length=50)
    manager_user_id: uuid.UUID | None = None
    start_date: date | None = None
    end_date: date | None = None
    # `estimated_amount` YOK (§3.4 kararı): "Tahmini Bedel" yer tutucudur, saklanmaz.
    # sort_order gövdede YOK: dizi sırasından atanır (0,1,2…)


class SiteCreate(BaseModel):
    # --- kimlik (63–73) ---
    name: str = Field(min_length=1, max_length=150)
    code: str | None = Field(default=None, min_length=1, max_length=50)   # boşsa SNT-YYYY-NNN
    status: SiteStatus = SiteStatus.active                                # 71
    site_manager_user_id: uuid.UUID | None = None                         # 69
    safety_officer_user_id: uuid.UUID | None = None                       # 70
    safety_officer_is_outsourced: bool = False                            # 70
    # --- konum & alan (76–88) ---
    city: str | None = Field(default=None, max_length=100)                # 79
    neighborhood: str | None = Field(default=None, max_length=150)        # 80
    parcel: str | None = Field(default=None, max_length=50)               # 81
    address: str | None = Field(default=None, max_length=300)             # 82
    gps_coordinates: str | None = Field(default=None, max_length=50)      # 83 (biçim doğrulaması YOK, §3.5)
    land_area_m2: Decimal | None = Field(default=None, ge=0)              # 84
    # 85 — modelde vardı ama şemalarda YOKTU; bu dilimde EKLENİYOR (karar 2026-07-30)
    construction_area_m2: Decimal | None = Field(default=None, ge=0)
    floor_info: str | None = Field(default=None, max_length=100)          # 86
    # --- takvim & bütçe (91–99) ---
    start_date: date | None = None                                        # 94
    end_date: date | None = None                                          # 95
    budget: Decimal | None = Field(default=None, ge=0)                    # 97
    # --- tesisler (147–174) ---
    facilities: SiteFacilitiesInput = Field(default_factory=SiteFacilitiesInput)
    electricity_subscription_no: str | None = Field(default=None, max_length=50)  # 170
    water_subscription_no: str | None = Field(default=None, max_length=50)        # 171
    planned_worker_count: int | None = Field(default=None, ge=0)                  # 172
    # --- bölümler + taslak ---
    sections: list[SiteSectionInput] = Field(default_factory=list)        # 102–144
    is_draft: bool = False                                                # 226
    # P2 mirası, mockup'ta yok ama sözleşmede kalır:
    site_manager_name: str | None = Field(default=None, max_length=200)
    delivery_date: date | None = None
```

> `site_manager_name` gövdede **kalır** ama artık ikincildir: `site_manager_user_id`
> doluysa servis `users.full_name`i üzerine yazar (`projects.employer_name` deseni).
> Böylece P1.1a'nın satır içi şantiye akışı (`ProjectSiteInput.site_manager_name`) kırılmaz.

```python
class SiteUpdate(BaseModel):
    """project_id YOK (şantiye başka projeye taşınamaz).
    `sections` YOK — bölümler mevcut P2 uçlarıyla yönetilir (§7.3)."""
    # SiteCreate'in tüm alanları `| None` + exclude_unset semantiği
    # + is_draft: bool | None = None
```

### 6.2 Çıkış

* `SiteFacilities` (çıkış, `SiteFacilitiesInput` ile aynı 8 alan).
* `SiteCard` **eklenen** alanlar: `is_draft`, `site_manager_user_id`,
  `safety_officer_user_id`, `safety_officer_name`, `safety_officer_is_outsourced`,
  `neighborhood`, `parcel`, `gps_coordinates`, `land_area_m2`, `construction_area_m2`,
  `floor_info`, `budget`, `facilities`, `electricity_subscription_no`,
  `water_subscription_no`, `planned_worker_count`.
  *(Mevcut alanların hiçbiri kaldırılmaz/yeniden adlandırılmaz → P2 frontend'i kırılmaz.)*
* `SiteCounts` **+`draft: int`**.
* `SectionResponse` **+`manager_user_id: uuid.UUID | None`** (tek ekleme).
  `estimated_amount` **YOKTUR**; `budget: MetricPlaceholder` **kalır** (§3.4) ve
  "Tahmini Bedel" sütununun kaynağı odur.
* `SiteDetailResponse` değişmez (SiteCard'dan miras alır).

---

## 7. Uçlar

Yeni **kök** açılmaz → BFF izin listesi (`ALLOWED_ROOTS`) değişmez; `sites` zaten var.

| # | Yol | Metot | İzin | Değişiklik | Yanıt |
|---|---|---|---|---|---|
| 1 | `/projects/{project_id}/sites` | POST | `sites:full` | **genişledi** — 20 yeni alan + `sections[]` + `is_draft` | `201` `SiteDetailResponse` |
| 2 | `/projects/{project_id}/sites` | GET | `sites:view` | yanıt genişledi (yeni alanlar + `counts.draft`) | `200` `SiteListResponse` |
| 3 | `/sites/{site_id}` | GET | `sites:view` | yanıt genişledi | `200` `SiteDetailResponse` |
| 4 | `/sites/{site_id}` | PATCH | `sites:full` | **genişledi** — yeni alanlar + `is_draft` geçişi | `200` `SiteDetailResponse` |
| 5 | `/sites/{site_id}/sections` | POST | `sites:full` | `manager_user_id` eklendi | `201` `SectionResponse` |
| 6 | `/sections/{section_id}` | PATCH | `sites:full` | `manager_user_id` eklendi | `200` `SectionResponse` |
| 7 | `/sites/{site_id}` | **DELETE** | `sites:`**`admin`** | **YENİ UÇ** (§7.1) | `204` gövdesiz |
| 8 | `/sections/{section_id}` | **DELETE** | `sites:`**`admin`** | **YENİ UÇ** (§7.1) | `204` gövdesiz |

Mevcut altı ucun gövdesi genişliyor; tüm yeni gövde alanları opsiyonel/varsayılanlı
olduğu için **eski istemciler kırılmaz** (P1.1a'nın satır içi şantiye yazımı dahil).
İki yeni uç açılıyor ama **yeni kök açılmıyor** (`/sites`, `/sections` zaten
`ALLOWED_ROOTS` içinde) → BFF izin listesi değişmez.

### 7.1 Silme uçları (karar 2026-07-30)

#### İzin

İkisi de `require_permission("sites", AccessLevel.admin)`. Gerekçe: 2026-07-30
"silme = sistem yöneticisi" kararı; `units` / `blocks` / `boq` uçlarıyla **birebir aynı**
(`units/router.py:181,206` → `_ADMIN`; `boq/router.py:178`). `full` **yazmayı kapsar,
silmeyi kapsamaz** (`app/core/access.py`). Bu, §9'daki tabloyu artık varsayımsal
olmaktan çıkarır: kural yürürlüktedir.

#### `DELETE /sites/{site_id}` — bağlı kayıt korkuluğu

**KRİTİK:** `sites.id`'yi hedefleyen **dört** FK'nın **tamamı `ON DELETE CASCADE`**'dir
(koddan doğrulandı):

| Bağlı tablo | Kolon | FK davranışı | Kaynak |
|---|---|---|---|
| `sections` | `site_id` | `CASCADE` | `sites/models.py:124` |
| `boq_groups` | `site_id` | `CASCADE` | `boq/models.py:36` |
| `boq_items` | `site_id` | `CASCADE` | `boq/models.py:75` |
| `blocks` | `site_id` | `CASCADE` | `units/models.py:71` |

Yani **DB kendiliğinden korumaz**: korkuluk olmadan tek bir `DELETE` çağrısı bölümleri,
poz gruplarını, poz kalemlerini ve blokları **sessizce yok eder**. (Tek kısmi ağ:
`units.block_id` `RESTRICT` olduğu için üniteli bir bloğun cascade'i `IntegrityError`
üretir — ama bu bir *kaza sonucu* koruma, tasarım değil ve poz/bölüm tarafını hiç
korumaz.) Bu yüzden **korkuluk servis katmanında ZORUNLUDUR** ve `delete_block`
deseninin (`units/service.py:307`) birebir uygulanmasıdır.

Kural: **aşağıdakilerden herhangi biri varsa silme 409 ile reddedilir.**

| # | Engel | Kontrol | Mesaj |
|---|---|---|---|
| 1 | Şantiyede bölüm var | `sections` sayımı | `Bu şantiyede bölüm var, önce bölümleri silin` |
| 2 | Şantiyede iş kalemi (poz) var | `boq_items` **veya** `boq_groups` sayımı | `Bu şantiyede iş kalemi var, önce iş kalemlerini silin` |
| 3 | Şantiyede blok/ünite var | `blocks` sayımı | `Bu şantiyede blok var, önce blokları silin` |

Kontrol sırası yukarıdaki gibidir ve **ilk engelde durur** (kullanıcıya tek, eyleme
dönük mesaj verilir). Sayı/adet **verilmez** (`BLOCK_HAS_UNITS` dersi: hata gövdesi
görünürlük dışı bilgi taşımaz). Hata sınıfı `RelatedRecordsExistError` → 409
(`app/core/errors.py:61`; `DeleteNotAllowedError` **kullanılmaz** — o yetki engelidir).

**Taslak şantiye için ayrıcalık yoktur:** bölümlü bir taslak da 409 döner. "Taslak
zaten yarım, gitsin" kısayolu yazılmaz — taslak/yayın ayrımı silme güvenliğini
gevşetmez.

Yeni repository yardımcıları: `site_has_sections`, `site_has_boq`, `site_has_blocks`
(`units/repository.py:97 block_has_units` deseni: `EXISTS` sorgusu, satır çekmez).

#### `DELETE /sections/{section_id}`

Kod tabanında **`sections.id`'yi hedefleyen hiçbir FK yoktur** (doğrulandı) — bölümün
bugün bağlı alt kaydı olamaz. Bu yüzden silme **koşulsuzdur**; uydurma bir engel
yazılmaz.

**Gelecek iş notu:** P5'te BOQ grupları/kalemleri bölüme bağlanırsa (`boq_groups.section_id`)
buraya `section_has_boq` korkuluğu **eklenmelidir**; o dilimin görev listesine bu madde
yazılmalıdır. Korkuluğun yeri şimdiden `service.delete_section` içinde tek satırlık bir
yorumla işaretlenir.

#### Ortak kurallar (iki uç)

* Görünürlük süzgeci **önce** koşar: görünmeyen şantiye/bölüm → **404**, gövdesi var
  olmayan UUID ile **birebir aynı** (`sites/service.py:244` dersi).
* Yanıt `204 No Content`, gövdesiz.
* Denetim günlüğüne yazılır (§10) ve **denetim metni satır silinmeden ÖNCE kurulur**
  (`delete_block` dersi: silinen satırın alanları sonradan okunamaz).
* Silme **geri alınamaz**; "yumuşak silme" (`deleted_at`) bu dilimde açılmaz — repoda
  böyle bir desen yok, ilkini burada icat etmek mimari sapmadır.

### 7.2 Türkçe hata mesajları

| Durum | HTTP | Mesaj |
|---|---|---|
| Proje görünmüyor / yok | 404 | `Proje bulunamadı` |
| Şantiye görünmüyor / yok | 404 | `Şantiye bulunamadı` |
| Bölüm görünmüyor / yok | 404 | `Bölüm bulunamadı` |
| Şef/İSG için verilen kullanıcı yok veya pasif | 422 | `Seçilen kullanıcı bulunamadı` |
| Kod çakışması (proje içinde) | 409 | `Bu şantiye kodu bu projede zaten kullanılıyor` |
| Bölüm kodu çakışması (şantiye içinde) | 409 | `Bu bölüm kodu bu şantiyede zaten kullanılıyor` |
| Şef zorunlu (taslak-dışı) | 422 | `Şantiye şefi seçiniz.` |
| İl/ilçe zorunlu (taslak-dışı) | 422 | `İl / ilçe zorunludur.` |
| İnşaat alanı zorunlu (taslak-dışı) | 422 | `İnşaat alanı zorunludur.` |
| Tarihler zorunlu (taslak-dışı) | 422 | `Başlangıç ve planlanan bitiş tarihi zorunludur.` |
| Bitiş < başlangıç (şantiye) | 422 | `Planlanan bitiş tarihi başlangıçtan önce olamaz.` |
| Bitiş < başlangıç (bölüm) | 422 | `{n}. bölüm: bitiş tarihi başlangıçtan önce olamaz.` |
| Bölüm adı boş | 422 | `{n}. bölüm: bölüm adı zorunludur.` |
| İSG hem kullanıcı hem OSGB | 422 | `İSG uzmanı ya sistem kullanıcısı ya dış kaynak (OSGB) olabilir.` |
| Silinecek şantiyede bölüm var | 409 | `Bu şantiyede bölüm var, önce bölümleri silin` |
| Silinecek şantiyede iş kalemi var | 409 | `Bu şantiyede iş kalemi var, önce iş kalemlerini silin` |
| Silinecek şantiyede blok var | 409 | `Bu şantiyede blok var, önce blokları silin` |
| İzin yok (silme dahil) | 403 | mevcut ortak gövde |

> **GPS biçim hatası satırı KALDIRILDI** (§3.5 revize kararı): sunucu GPS metnini
> doğrulamaz, dolayısıyla böyle bir hata üretmez.

`{n}` **1-tabanlıdır** (kullanıcı 2. satırı görüyor, 1 indeksini değil).

Yeni istisna sınıfı: `app/core/errors.py` içine `SiteValidationError(DomainError)` → 422
(`UnitValidationError` / `ProjectValidationError` deseninin aynısı). Metinler modül içinde
sabit olarak durur (`units/guards.py` deseni). 409 için **yeni sınıf açılmaz**: mevcut
`RelatedRecordsExistError` kullanılır.

---

## 8. Bölümlerin atomik oluşturulması

### 8.1 Akış

```
POST /projects/{project_id}/sites
  1. görünür proje süzgeci  → yoksa 404 (gövde ayırt edici DEĞİL)
  2. _validate_site(data)   → 422 (hiçbir şey yazılmadı)
  3. şef/İSG kullanıcı çözümü (varsa) → 422
  4. kod üretimi (boşsa)    → SNT-{YYYY}-{NNN}
  5. Site satırı            → session.add + flush
  6. her SiteSectionInput   → Section satırı (sort_order = dizi indeksi)
  7. tek flush              → benzersizlik ihlali → 409
  8. denetim günlüğü        → §10
  9. yanıt: SiteDetailResponse (bölümler dahil)
```

### 8.2 Atomiklik garantisi

* `get_db` bağımlılığı **istek başına tek transaction** açar; commit istek sonunda olur.
  Herhangi bir adımda istisna → `rollback` → **hiçbir satır yazılmaz**.
  Kısmi başarı **mümkün değildir**: şantiye yazılıp bölüm patlarsa şantiye de geri alınır.
* Bu, P1.1a `_write_inline_sites` deseninin birebiri
  (*"kod çakışması tüm oluşturmayı geri alır"*, `projects/service.py:466`).
* **Kural:** doğrulama (`_validate_site` + bölüm satır doğrulaması) yazmadan **ÖNCE**,
  tek seferde, tüm bölüm satırları için koşar. İlk hatalı satırda durur ve `{n}.` ile
  bildirir. *(Kalem-bazlı toplu hata listesi (`UnitImportError` deseni) burada
  kullanılmaz: form ekranı 2–5 satırlık, Excel içe aktarma değil.)*
* Bölüm kodu formda **yok**; yalnız program tarafından `None` gider → kısmi benzersiz
  indeks (`uq_sections_site_code`, `code IS NOT NULL`) çakışma üretmez.
* **`sections` izni ARANMAZ**: bölüm şantiyenin iç kırılımıdır, `sites:full` ikisini de
  kapsar (P2 spec §4).

### 8.3 Yarış durumu

İki kullanıcı aynı anda kod üretirse `uq_sites_project_code` ihlali → mevcut
`IntegrityError → 409` işleyicisi. Otomatik yeniden deneme **yapılmaz** (P1'de de yok);
kullanıcı formu yeniden gönderir. Global numaralandırma (§3.2) tekilliği garanti etmez,
yalnız *öngörülebilir* kılar — bu bilinçlidir.

---

## 9. İzin

**Yeni izin modülü AÇILMAZ.** `sites` modülü matriste zaten var
(`seed_data.py:157` → `[_A, _F, _LIM, _LIM, _LIM, _FIN, _F, _LIM]`).

| İşlem | Seviye |
|---|---|
| Okuma (GET) | `sites` · `view` |
| Yazma (POST/PATCH) — şantiye ve bölüm | `sites` · `full` |
| Silme (DELETE) — şantiye ve bölüm | `sites` · **`admin`** (2026-07-30 kullanıcı kararı: `full` silmeyi kapsamaz; `units`/`blocks`/`boq` ile aynı) |

Görünürlük süzgeci `projects.service.visible_projects`ten **gelir**, kopyalanmaz
(mevcut `sites/service._visible_project` korunur). Görünmeyen kayıt → **404**, 403 değil;
404 gövdesi de ayırt edici olmamalıdır (`sites/service.py:244` yorumundaki ders).

**Yeni IDOR yüzeyi:** `site_manager_user_id` / `safety_officer_user_id` / bölüm
`manager_user_id` — verilen UUID'ler `users` tablosunda çözümlenir. Kullanıcı **var mı**
diye bakılır; "bu kullanıcıyı görme yetkin var mı" **aranmaz** (kullanıcı listesi
`sites:full` sahibi için zaten `GET /users` ile erişilebilir). Var olmayan/pasif kullanıcı
→ 422 `Seçilen kullanıcı bulunamadı` — 404 değil, çünkü kaynak şantiyedir, kullanıcı değil.

---

## 10. Denetim günlüğü

`app/modules/audit/messages.py` (mevcutlar korunur, yenileri eklenir):

| Uç | Aksiyon | Fonksiyon | Metin |
|---|---|---|---|
| POST site | `create` | `site_created(name)` *(mevcut)* | `Yeni şantiye oluşturuldu: {name}` |
| POST site (taslak) | `create` | `site_draft_created(name)` **(yeni)** | `Yeni şantiye taslağı oluşturuldu: {name}` |
| POST site (bölümlü) | `create` | `site_sections_created(site, count)` **(yeni)** | `Şantiye bölümleri oluşturuldu: {site} · {count} bölüm` |
| PATCH site | `update` | `site_updated(name)` *(mevcut)* | `Şantiye güncellendi: {name}` |
| PATCH `is_draft: true→false` | `update` | `site_published(name)` **(yeni)** | `Şantiye taslaktan yayına alındı: {name}` |
| POST section | `create` | `section_created(site, name)` *(mevcut)* | değişmez |
| PATCH section | `update` | `section_updated(site, name)` *(mevcut)* | değişmez |
| **DELETE site** | `delete` | `site_deleted(project, name)` **(yeni)** | `Şantiye silindi: {project} · {name}` |
| **DELETE section** | `delete` | `section_deleted(site, name)` **(yeni)** | `Bölüm silindi: {site} · {name}` |

Kurallar:
* Bölümlü oluşturmada **bölüm başına ayrı satır yazılmaz** — tek özet satır
  (`units_bulk_created` deseni: `Toplu ünite üretildi: … · {count} ünite`). 5 bölümlü bir
  form 6 denetim satırı üretmez, 2 üretir.
* **Silme metni satır silinmeden ÖNCE kurulur** (`units/service.py:327` dersi): silinen
  satırın `name`/`project.name` alanları `session.delete` sonrasında güvenilir okunamaz.
  Bu, silme denetiminin en kolay kaçırılan ayrıntısıdır ve kaçırılırsa denetim kaydı
  boş adla yazılır — yani silinen kaydın **ne olduğu tamamen kaybolur**.
* Silme **başarısız** olursa (409 korkuluğu) denetim satırı **yazılmaz**: denetim
  gerçekleşen olayı kaydeder, denemeyi değil.
* Okuma uçları denetim **yazmaz**.
* Taslak oluşturma ile yayın oluşturma **ayrı metinlerdir**: denetim ekranında
  "gerçekten şantiye açıldı mı" sorusu metinden cevaplanabilmelidir.

---

## 11. Migration planı

### 11.1 Revizyonlar

**İki ayrı revizyon** (enum takası izole edilir — `d1a2b3c4e5f6` dersi):

| Sıra | Revizyon | İçerik |
|---|---|---|
| 1 | `…_site_status_enum` | `site_status` tip takası: `preparation` eklenir (§3.1) |
| 2 | `…_santiye_formu_genislemesi` | **22 `sites` kolonu** + **1 `sections` kolonu** (`manager_user_id`) + `ck_sites_safety_officer` + FK'ler + indeksler |

Silme uçları **migration gerektirmez**: mevcut FK'ler (`CASCADE`) olduğu gibi kalır,
koruma servis katmanındadır (§7.1). FK davranışlarını `RESTRICT`'e çevirmek **bilinçli
olarak yapılmaz** — canlıda hangi şantiyenin hangi bağı olduğu bilinmeden yapılan bir
`ALTER` deploy'u kilitleyebilir ve servis korkuluğu zaten daha iyi (Türkçe, eyleme dönük)
bir hata üretir.

**Ebeveyn:** şu an `a4c7f1d2e8b3` (P3 üniteler) görünüyor, **ama B1'de
`.venv/bin/alembic heads` ile DOĞRULANACAK** — X1 (`e3a8b4a5b93b`) ve P3 merge
durumuna göre kayabilir. Yanlış ebeveyn = canlıda çoklu head = deploy kilitlenmesi.

### 11.2 Veri geçişi

**Gerekmiyor.** Tüm yeni kolonlar ya `NULL` kabul eder ya `server_default` taşır:

* 8 tesis kutucuğu + `safety_officer_is_outsourced` + `is_draft`
  → `NOT NULL` + `server_default=false` → mevcut satırlar `false` olur.
  Tesislerin `false` başlaması §2.6 kararıyla **uyumludur**: ne mevcut satırlarda ne
  yeni satırlarda ön-işaret yoktur.
* Diğer 12 kolon `NULL`.
* Enum takası mevcut satırların değerini değiştirmez (`preparation`e kimse taşınmaz).

`UPDATE` yazılmaz; `sites`'ın canlı satır sayısı azdır ama yine de tam tablo `UPDATE`
kilidinden kaçınılır.

### 11.3 **KRİTİK: mevcut canlı veri**

Canlıda `sites` satırları **var** (P2 ve P1.1a akışlarından). Mockup'ta `*` işaretli olan
alanlar (şef 69, il/ilçe 79, inşaat alanı 85, tarihler 94/95) mevcut satırlarda **boş
olabilir**.

Bu yüzden:

1. **DB'de hiçbir kolon `NOT NULL` yapılmaz** — zorunluluk yalnız **uygulama katmanında**,
   yalnız **taslak-dışı POST**ta uygulanır. `ALTER COLUMN … SET NOT NULL` yazan bir
   migration canlıda **patlar** ve deploy'u kilitler.
2. `uq_sites_project_code` **global `UNIQUE`'e çevrilmez** — mevcut ad-türevi kodlar
   (`A-BLOK`, `MERKEZ`) iki projede birden bulunabilir; çevirim canlıda patlar (§3.2).
3. `PATCH /sites/{id}` **tam doğrulama koşmaz** (§5.3) — koşarsa canlıdaki eksik şantiyeler
   düzenlenemez hâle gelir; kullanıcı adını değiştirmek isterken "Şantiye şefi seçiniz."
   duvarına çarpar.
4. Mevcut satırlar `is_draft=false` (yayında) sayılır — doğru varsayım: onlar zaten
   kullanımda.
5. **Mevcut kodlar dokunulmaz** — `A-BLOK` gibi ad-türevi kodları `SNT-` desenine
   çeviren hiçbir `UPDATE` yazılmaz (§3.2). Kod, evrakta ve kullanıcı belleğinde
   referanstır; geriye dönük değişmesi izlenebilirliği kırar.

> Bu dört (artık beş) korkuluk **2026-07-30 revizyonunda da aynen korunmuştur**:
> hiçbir kolon `NOT NULL` yapılmadı, `PATCH` tam doğrulama koşmuyor,
> `uq_sites_project_code` global `UNIQUE`'e çevrilmedi.

### 11.4 Doğrulama

* Yerel tek kullanımlık DB'de `upgrade → downgrade → upgrade`.
* `downgrade` enum'da önce `preparation → active` düşürür (§3.1).
* Canlı DB'ye migration **koşulmaz**; merge sonrası Railway auto-deploy + `alembic current`
  ile doğrulanır.

---

## 12. Test stratejisi

TDD: önce test, **KIRMIZI GÖR**, sonra kod. Tek kullanımlık yerel DB
(`createdb` + komut satırında `TEST_DATABASE_URL`; `.env`'e **DOKUNULMAZ**).

### 12.1 Birim

1. `_next_site_code`: boş tablo → `SNT-{yıl}-001`; `003` varken → `004`;
   `003` silinmişken tekrar `004` (maksimum+1, sayım değil); ad-türevi eski kodlar
   (`A-BLOK`) sayaca **karışmaz**.
1b. **Global numaralandırma** (§3.2): A projesinde `SNT-{yıl}-001` varken B projesinde
   üretilen kod `SNT-{yıl}-002`'dir — `001` **tekrar üretilmez**.
2. **GPS doğrulanmadığı**: `"abc"`, `"39,9042"`, `""` gibi girdiler 422 **ÜRETMEZ**,
   olduğu gibi saklanır (§3.5). `max_length=50` aşımı 422 üretir.
3. `_validate_site`: §5.1 tablosunun her satırı, taslak ve taslak-dışı için ayrı ayrı.
3b. **İSG uzmanı hiçbir koşulda zorunlu değil**: taslak-dışı, İSG'siz tam gövde → 201.
4. İSG karşılıklı dışlama: FK+OSGB → 422; yalnız FK → geçer; yalnız OSGB → geçer; ikisi de
   boş → geçer.
5. Süre türevinin **saklanmadığı**: yanıtta `duration_days` alanı **yok**.
5b. **Tesis varsayılanları**: `facilities` hiç gönderilmeyen POST → sekizi de `false`
   (§2.6; "mockup ön-işaretleri sızmadı" regresyonu).

### 12.2 Entegrasyon

6. POST minimum gövde (yalnız `name`, `is_draft=true`) → 201, kod üretildi, tüm tesisler `false`.
7. POST tam gövde (mockup'ın **tüm** alanları) → 201; 20 alanın hepsi geri okunuyor.
8. POST 3 bölümle → 201; `sort_order` 0,1,2; `manager_user_id` korunuyor.
8b. POST gövdesinde bölüme `estimated_amount` yollanırsa **sessizce yok sayılır**;
    `SectionResponse`'ta böyle bir alan **yok**, `budget` yer tutucu geliyor (§3.4).
9. POST `code` elle verilmiş ve çakışıyor → 409, **şantiye yazılmadı**.
10. POST `status=preparation` → 201 (yeni enum değeri).
11. PATCH tek alan → yalnız o alan değişti (`exclude_unset`).
12. PATCH `is_draft: false` eksik zorunlularla → 422, satır **taslak kaldı**.
13. PATCH `is_draft: false` tam kayıtla → 200, denetimde `site_published`.
14. GET liste → `counts.draft` doğru; taslak kayıt listede **görünüyor**.
15. Şef/İSG FK doluyken `*_name` anlık görüntüsü doldu; kullanıcı silinince FK `NULL`
    oldu ama **ad kaldı** (`ON DELETE SET NULL`).
16. Geriye uyum: P1.1a proje formu satır içi şantiye akışı (`_write_inline_sites`)
    hâlâ çalışıyor ve artık `SNT-` kodu üretiyor.
17. Mevcut P2 uçlarının yanıt sözleşmesi kırılmadı (eski alanlar yerinde).
17b. `construction_area_m2` POST'ta yazılıyor ve GET yanıtında geri okunuyor
     (şemalara eklenme regresyonu).

### 12.3 Silme uçları (YENİ — §7.1)

S1. `DELETE /sites/{id}` boş şantiye (bölümsüz, pozsuz, bloksuz) → **204**;
    kayıt gerçekten gitti (ardından GET → 404).
S2. Bölümü olan şantiye → **409** `Bu şantiyede bölüm var…`; **şantiye de bölüm de
    yerinde** (cascade tetiklenmedi — bu testin asıl amacı budur).
S3. Poz kalemi olan şantiye → **409**; `boq_items` satırları yerinde.
S4. Bloğu olan şantiye → **409**; `blocks` satırları yerinde.
S5. **Taslak** ama bölümlü şantiye → **409** (taslağa ayrıcalık yok).
S6. Başarılı silme denetim günlüğüne `site_deleted` yazdı ve metin **silinen şantiyenin
    adını içeriyor** (metnin silmeden önce kurulduğunun kanıtı).
S7. 409 dönen silme denemesi denetim günlüğüne **hiçbir şey yazmadı**.
S8. `DELETE /sections/{id}` → **204**; şantiye ve diğer bölümler yerinde.
S9. Bölüm silindikten sonra şantiye silinebiliyor (S2'nin devamı — korkuluk kalıcı
    kilit üretmiyor).

### 12.4 Atomiklik

18. POST 3 bölümlü, **2. bölüm** tarihi ters → 422 `2. bölüm: …`; DB'de **ne şantiye ne bölüm** var.
19. POST 2 bölümlü, şantiye kodu çakışıyor → 409; `sections` tablosunda yeni satır **yok**.
20. POST bölüm adı boş → 422 `{n}. bölüm: bölüm adı zorunludur.`; hiçbir şey yazılmadı.

### 12.5 IDOR negatif seti

Kimliği yukarı çözümleyen **her uç** için (P3 §11.4 deseni):

21. Görünmeyen projeye POST → **404** `Proje bulunamadı` (403 değil).
22. Görünmeyen projedeki şantiyeye GET/PATCH → **404** `Şantiye bulunamadı`;
    var olmayan UUID ile **birebir aynı gövde**.
23. Görünmeyen şantiyenin bölümüne PATCH → **404** `Bölüm bulunamadı`.
24. `sites:view` olan kullanıcı POST/PATCH → **403**.
25. İzinsiz kullanıcı (`sites:none` — matriste yok ama rol izinleri düzenlenebilir) → 403.
26. `site_manager_user_id` olarak rastgele UUID → 422, **yazma yok**.

**Silme uçları için ZORUNLU negatif set** (yeni yüzey, §7.1):

27. **Görünmeyen** projedeki şantiyeye `DELETE` → **404** `Şantiye bulunamadı`;
    gövde var olmayan UUID ile **birebir aynı** ve **kayıt silinmedi**.
28. Görünmeyen şantiyenin bölümüne `DELETE` → **404** `Bölüm bulunamadı`; kayıt yerinde.
29. `sites:full` (admin **değil**) kullanıcı `DELETE /sites/{id}` → **403**; kayıt yerinde.
    *Bu vaka en kritik olanıdır: `full`'ün silmeyi kapsamadığı kararının tek testidir.*
30. `sites:full` kullanıcı `DELETE /sections/{id}` → **403**.
31. `sites:view` kullanıcı her iki `DELETE` → **403**.
32. İzinsiz kullanıcı her iki `DELETE` → **403**.
33. **Yetki ile görünürlük sırası**: `sites:admin` sahibi ama projeye erişimi olmayan
    kullanıcı `DELETE` → **404** (403 değil) ve kayıt yerinde — yetkili olmak
    görünmeyen kaydın **varlığını sızdırmamalıdır**.

### 12.6 Kapılar

`.venv/bin/pytest` + `.venv/bin/ruff check` + `.venv/bin/ruff format --check`
(ruff **0.15.22**). `openapi.json` üretilir, **commit edilmez**, frontend'e kopyalanır.

---

## 13. Karara bağlandı (2026-07-30)

Bu dilimin **tüm** açık soruları kullanıcı tarafından karara bağlanmıştır. Aşağıdaki
tablo kararların özetidir; ayrıntı ve gerekçe ilgili bölümdedir.

| # | Konu | **Karar** | Bölüm |
|---|---|---|---|
| 1 | Şantiye kodu deseni | `SNT-{YYYY}-{NNN}`, `PRJ-` emsalinin aynısı, **maksimum+1**. Numaralandırma **şirket geneli (global)** — `PRJ-` üreticisinin sorgusunda kapsam süzgeci olmadığı koddan doğrulandı. Kısıt `(project_id, code)` olarak **kalır** | §3.2 |
| 2 | Mevcut `derive_code` | **Kaldırılır**; tek üretici `_next_site_code`. Canlıdaki mevcut kodlar **olduğu gibi kalır**, hiçbir `UPDATE` yazılmaz; yalnız yeni kayıtlar `SNT-` alır | §3.2, §11.3 |
| 3 | Tesisler nasıl saklanır | **Her biri ayrı `Boolean` kolon** (Seçenek A). JSONB/yan tablo alternatifi **çıkarıldı**, ret gerekçesi kayıtta | §4 |
| 4 | Tesis varsayılanları | **Hepsi boş başlar.** Mockup'taki 6 ön-işaret **örnek veridir**; DB, Pydantic ve frontend varsayılanı `false` | §2.6, §14.2 |
| 5 | `sections.estimated_amount` | **EKLENMEZ.** "Tahmini Bedel" **yer tutucu** kalır; değer ileride İş Kalemleri/BOQ'dan hesaplanır (tek gerçek kaynak). `sections`'a **yalnız `manager_user_id`** eklenir | §3.4, §14.3 |
| 6 | İSG Uzmanı | **Zorunlu değil** — nullable; ipucu metni yalnız bilgilendirme, sunucu zorlaması değil | §2.2, §5.1 |
| 7 | GPS | **Tek metin kolonu** `gps_coordinates String(50)`, **doğrulama yok**. (Gün içinde revize edildi: puantaj konum doğrulaması kapsam dışına alındığı için iki sayısal kolon kararından dönüldü.) Ayrıştırma + migration, konum doğrulamasını getiren dilimin işi | §3.5 |
| 8 | `DELETE /sites/{id}` | **AÇILIR.** İzin `sites:`**`admin`**. Bölüm / iş kalemi / blok varsa **409** + Türkçe mesaj. Dört FK'nın da `CASCADE` olması nedeniyle korkuluk **servis katmanında zorunludur** | §7.1 |
| 9 | `DELETE /sections/{id}` | **AÇILIR.** İzin `sites:`**`admin`**. `sections.id`'yi hedefleyen FK olmadığı için bugün **koşulsuz**; P5 bölüm-BOQ bağı gelirse korkuluk o dilimde eklenir | §7.1 |
| 10 | Denetim | İki silme ucu da denetim günlüğüne yazar; metin **silmeden önce** kurulur; başarısız silme yazmaz | §10 |
| 11 | IDOR | Silme uçları için negatif set **zorunludur** (görünmeyen kayıt → 404, `full` → 403, admin-ama-görünmez → 404) | §12.5 |
| 12 | Bölüm şablonu (mockup 138) | **YAZILMAZ** — özellik yok | §14.1 |
| 13 | Taslak görünürlüğü | Projeye **erişimi olan herkes** görür; projelerdeki desenin aynısı | §5.2 |
| 14 | `SiteCounts.draft` | Listede **rozet**; **ayrı sekme açılmaz** | §5.2 |
| 15 | Bütçe çapraz kontrolü | Şantiye bütçeleri toplamı proje bütçesini aşarsa **uyarı üretilmez** | §3.7 |
| 16 | `construction_area_m2` | Modelde vardı, şemalarda yoktu → `SiteCreate`/`SiteUpdate`/`SiteCard`'a **eklenir** | §2.3, §6 |

### 13.1 Hâlâ açık olan

**Yok.** Bu dilimin uygulanmasını bekleten açık soru kalmamıştır.

Aşağıdakiler açık soru **değildir**, uygulama sırasında doğrulanacak **kontrol
maddeleridir**:

* **Migration ebeveyni**: §11.1'de `a4c7f1d2e8b3` (P3) görünüyor ama T1'de
  `.venv/bin/alembic heads` ile **doğrulanacak**. Yanlış ebeveyn = canlıda çoklu head
  = deploy kilitlenmesi. Bu bir karar değil, bir ölçümdür.
* **Sonraki dilimlere devredilen işler** (bu dilimi bloke etmez): belge yükleme
  altyapısı (§1.2), poz dağılımı bağı (§1.2), GPS ayrıştırma + konum doğrulaması
  (§3.5), bölüm-BOQ bağı gelirse `delete_section` korkuluğu (§7.1).

---

## 14. Onaylı sapmalar (mockup'tan bilinçli ayrılmalar)

Bu üç madde mockup'ta **görünen** ama uygulanmayacak olan davranışlardır. Kullanıcı
tarafından onaylanmıştır; ileride "mockup'a uymuyor" gerekçesiyle **geri alınmamalıdır**.

### 14.1 Bölüm şablonu yazılmaz (mockup satır 138)

Mockup'ta "Bölüm ekle **veya şablon kullan**" butonu var. **Şablon özelliği hiç
yazılmaz** — ne backend tablosu, ne uç, ne frontend akışı. Buton yalnız "+ Bölüm Ekle"
işlevini taşır.

*Gerekçe:* mockup şablonun **içeriğini tanımlamıyor** — şablonlar sabit bir kod listesi
mi, kullanıcı tanımlı bir kartoteks mi, projeye/şantiye tipine göre mi değişiyor belli
değil. Tanımsız bir özelliği tahmin ederek yazmak, sonradan tamamı atılacak bir tablo
ve uç üretir. İhtiyaç netleştiğinde ayrı bir dilim olarak ele alınır.

### 14.2 Tesis ön-işaretleri uygulanmaz (mockup satır 153–165)

Mockup'ta 8 kutucuktan 6'sı işaretli açılıyor. **Hiçbir katmanda ön-işaret yoktur**:
DB `server_default=false`, Pydantic varsayılanı `False`, form boş açılır.

*Gerekçe:* ön-işaretli kutucuk, kullanıcı **hiç dokunmadan** kaydettiğinde "bu şantiyede
kapalı ambar, yemekhane ve revir var" beyanını üretir. Bu, kullanıcının vermediği bir
bilgidir — sessiz yanlış veridir ve İSG/altyapı raporlarına doğrudan sızar. Mockup'taki
işaretli hâl bir **örnek şantiyenin görüntüsüdür**, varsayılan tasarım değildir.

### 14.3 "Tahmini Bedel" yer tutucu kalır (mockup satır 114, 123)

Mockup bölüm tablosunda elle girilen "Tahmini Bedel" sütunu var (`1840000`, `2960000`).
Sütun **kalır** ama **girilebilir değildir**: değer sunucuya gitmez, saklanmaz;
`SectionResponse.budget` yer tutucusundan (bekleyen modül: `boq`) beslenir.

*Gerekçe:* bölüm bedeli için **tek gerçek kaynak** İş Kalemleri/BOQ toplamıdır (P2 spec
§2.2). Elle girilen ikinci bir tahmin, aynı büyüklüğün rakip kaynağı olur; ikisi
kaçınılmaz olarak ayrışır ve hangisinin doğru olduğu belirsizleşir. Ayrışan iki sayı,
olmayan tek sayıdan daha zararlıdır.

---

## 15. Uygulama task listesi

TDD zorunludur: her task **önce test, KIRMIZI GÖR, sonra kod**. Tasklar sıralıdır;
bağımlılık sütunu paralelleştirilebilecek olanları gösterir.

| # | Task | Bağımlılık | Kapsam |
|---|---|---|---|
| **T1** | Migration ebeveyni doğrulama + `site_status` enum takası (`preparation`) | — | `.venv/bin/alembic heads` ölçümü; tip takası migration'ı; `upgrade→downgrade→upgrade` | 
| **T2** | `sites` 22 kolon + `sections.manager_user_id` migration'ı + ORM modelleri | T1 | §3.0 tablosu; `ck_sites_safety_officer`; FK + indeksler; **hiçbir kolon `NOT NULL` değil** |
| **T3** | `_next_site_code` (global, maksimum+1) + `derive_code`/`_unique_code` kaldırılması | T2 | §3.2; `projects.service._write_inline_sites` de yeni üreticiyi çağırır |
| **T4** | Pydantic şemaları: `SiteFacilitiesInput`, `SiteSectionInput`, `SiteCreate`, `SiteUpdate`, çıkış şemaları + `construction_area_m2` | T2 | §6; `estimated_amount` **yok**; GPS düz metin |
| **T5** | `_validate_site` + taslak-farkındalıklı doğrulama + `SiteValidationError` | T4 | §5.1 tablosu; İSG karşılıklı dışlama; GPS kuralı **yok** |
| **T6** | POST genişlemesi + bölümlerin atomik yazımı + şef/İSG kullanıcı çözümü | T3, T5 | §8; `sort_order` dizi sırasından; tek transaction |
| **T7** | PATCH genişlemesi + `is_draft` yayına geçiş kuralı | T5 | §5.3; **PATCH tam doğrulama koşmaz** |
| **T8** | Okuma uçları: `SiteCard`/`SiteDetailResponse`/`SectionResponse` genişlemesi + `SiteCounts.draft` | T4 | §6.2; eski alanlar **kaldırılmaz** |
| **T9** | Repository korkuluk sorguları: `site_has_sections`, `site_has_boq`, `site_has_blocks` | T2 | `block_has_units` deseni (`EXISTS`, satır çekmez) |
| **T10** | `DELETE /sites/{site_id}` — servis + korkuluk + uç | **T9**, T8 | §7.1; `_ADMIN` kapısı; 409 üç engel; 404 görünürlük önce |
| **T11** | `DELETE /sections/{section_id}` — servis + uç | T8 (T9'a **bağlı değil**) | §7.1; koşulsuz silme + gelecek-korkuluk yorumu |
| **T12** | Denetim mesajları: `site_draft_created`, `site_sections_created`, `site_published`, `site_deleted`, `section_deleted` | T6, T7, **T10**, **T11** | §10; silme metni **silmeden önce** kurulur |
| **T13** | Test seti: birim + entegrasyon + atomiklik (§12.1, §12.2, §12.4) | T6, T7, T8 | — |
| **T14** | **Silme testleri** S1–S9 (§12.3) | T10, T11, T12 | Cascade'in tetiklenmediğinin kanıtı S2–S4'tedir |
| **T15** | **IDOR negatif seti** 21–33 (§12.5) | T10, T11 | 29/30 (`full` → 403) ve 33 (admin-ama-görünmez → 404) **atlanamaz** |
| **T16** | Kapılar: `pytest` + `ruff check` + `ruff format --check` + `openapi.json` üretimi | T13, T14, T15 | §12.6; `openapi.json` **commit edilmez** |

**Silme uçlarının eklenmesiyle gelen yeni tasklar: T9, T10, T11, T14, T15** (T12 genişledi).

**Kritik bağımlılık:** T10 **T9'suz yazılamaz.** Korkuluk sorguları olmadan yazılan bir
`DELETE /sites/{id}`, dört `CASCADE` FK sayesinde bölümleri, poz gruplarını, poz
kalemlerini ve blokları **sessizce siler** — ve bu, testler yazılana kadar fark
edilmeyen, geri alınamaz bir veri kaybıdır. T9 → T10 sırası pazarlık konusu değildir.

**T11, T9'a bağlı değildir** (bölümün bağlı kaydı yok) → T10 ile paralel yürüyebilir.
