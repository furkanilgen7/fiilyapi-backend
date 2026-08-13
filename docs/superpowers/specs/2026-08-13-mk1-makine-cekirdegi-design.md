# MK-1 — Makine & Ekipman Çekirdeği (backend)

Tarih: 2026-08-13 · Repo: `backend/` · Dal: `feat/mk1-makine-cekirdegi`
Yönetim oturumu yazdı (⚡ hızlandırılmış düzen).

Mockup'lar (`projedesign/`, `ls | grep` ile varlığı doğrulandı):
**M1** `Makine & Ekipman.dc.html` · **M2** `Form - Makine Ekle.dc.html` ·
**M3** `Makine - Çalışma Kaydı.dc.html` · **M4** `Makine - Yakıt Takibi.dc.html` ·
(**M5** `Makine - Kira Hakedişi.dc.html` — **KAPSAM DIŞI**, §9'a bak)

---

## 1. Kapsam

**MK-1 = ekipman kartı + çalışma kaydı + yakıt kaydı + üç ekranın özet uçları.**

M5 (Kira Hakedişi) **bilerek dışarıda**: mockup'ın kendi aritmetiğinde çözülmemiş **para
tutarsızlıkları** var (§9) — bir para yüzeyi, kullanıcı kararı gerektiriyor, ayrı dilim (MK-2)
hak ediyor. Ekipman **belgeleri** de MK-2'ye: mockup 6 belge slotu çiziyor ama "Periyodik
Muayene · Yıllık zorunlu" için **geçerlilik tarihi alanı çizmiyor** — tarihsiz belge, süresi
dolmuş muayeneyi "var" gösterir; eksik mockup ile kodlanmaz (WORKFLOW §3).

Bu dilim **21. izin modülünü** açar: `equipment` (BC'nin `documents` emsali — yeni modül +
migration).

---

## 2. Tablolar

### 2.1 `equipment` (ekipman kartı — M1 + M2)

| Kolon | Tip | Not |
|---|---|---|
| `id` | UUID PK | |
| `name` | String, **NOT NULL** | M2:84 zorunlu |
| `category` | enum `equipment_category` **NOT NULL** | M2:85, 6 değer (§5) |
| `brand` | String, nullable | M1:94 markayı TEK BAŞINA basıyor → **`brand` ve `model` AYRI kolon** (K1) |
| `model` | String, nullable | |
| `serial_no` | String, nullable | M2:87 |
| `plate_no` | String, nullable | M2:88 · M5:103 |
| `model_year` | Integer, nullable | M2:89 |
| `ownership` | enum `equipment_ownership` **NOT NULL** | `owned`/`rented` — M2:54-66, varsayılan `owned` |
| `purchase_amount` | Numeric(18,2), nullable | M2:98 (K2: koşullu zorunlu) |
| `purchase_date` | Date, nullable | M2:99 |
| `depreciation_years` | Integer, nullable | M2:100 (5/10/15; **serbest tamsayı**, enum değil) |
| `supplier_id` | FK→`suppliers` **SET NULL**, nullable | M2:101 + M2:108 → **TEK FK** (K3) |
| `financing` | enum `equipment_financing`, nullable | M2:102 |
| `market_value` | Numeric(18,2), nullable | M2:103 |
| `rate_amount` | Numeric(18,2), nullable | M2:110 |
| `rate_period` | enum `equipment_rate_period`, nullable | M2:109 |
| `site_id` | FK→`sites` **SET NULL**, nullable | M2:118 (K4) |
| `operator_id` | FK→`personnel` **SET NULL**, nullable | M2:119 |
| `status` | enum `equipment_status` **NOT NULL** | M2:120, varsayılan `working` |
| `status_note` | Text, nullable | M1:122/148 |
| `status_expected_date` | Date, nullable | M1:123 / M1:149 |
| `fuel_type` | enum `equipment_fuel_type`, nullable | M2:121 |
| `norm_consumption` | Numeric(10,2), nullable | M2:122 **sayı** (K5) |
| `norm_unit` | enum `equipment_norm_unit`, nullable | `lt_hour`/`lt_km` (K5) |
| `maintenance_period` | enum `equipment_maintenance_period`, nullable | M2:123 dört seçenek (K6) |
| `monthly_capacity_hours` | Integer **NOT NULL**, default **200** | Kullanım % paydası (K7) |
| `is_company_asset` | Boolean **NOT NULL**, default `true` | M2:166 — yalnız işaret (K8) |
| `is_active` | Boolean **NOT NULL**, default `true` | Silme yerine pasifleştirme |
| standart zaman damgaları | | |

**`is_draft` AÇILMAZ** — M2'de taslak butonu YOK (personel formunun aksine).

### 2.2 `equipment_work_logs` (M3)

| Kolon | Tip | Not |
|---|---|---|
| `id` | UUID PK | |
| `equipment_id` | FK→`equipment` **RESTRICT** | 🔴 maliyet izi: kaydı olan ekipman silinemez (`payroll_lines`→`personnel` emsali) |
| `work_date` | Date **NOT NULL** | |
| `site_id` | FK→`sites` **SET NULL**, nullable | M3:258 kaydın KENDİ şantiyesi (K9) |
| `operator_id` | FK→`personnel` **SET NULL**, nullable | M3:258/291; arıza kaydında YOK (M3:280) |
| `record_type` | enum `work_log_type` **NOT NULL** | `worked`/`breakdown` (K10) |
| `start_time` / `end_time` | Time, nullable | M3:261 `06:00–15:00` |
| `hours` | Numeric(6,2) **NOT NULL** | 🔴 **SUNUCU HESAPLAR** (K11) |
| `note` | Text, nullable | M3:283 arıza sebebi |
| standart damgalar + `created_by_id`→users SET NULL | | |

**UQ YOK** — bir ekipman aynı gün birden çok vardiya/arıza kaydı taşıyabilir. Tavan: K12.

### 2.3 `equipment_fuel_logs` (M4)

| Kolon | Tip | Not |
|---|---|---|
| `id` | UUID PK | |
| `equipment_id` | FK→`equipment` **RESTRICT** | |
| `fuel_date` | Date **NOT NULL** | M4:107 |
| `site_id` | FK→`sites` **SET NULL**, nullable | M4:109 (K4 ile aynı hedef) |
| `liters` | Numeric(10,2) **NOT NULL**, CHECK `> 0` | M4:110 |
| `unit_price` | Numeric(10,4) **NOT NULL**, CHECK `> 0` | M4:111 **satır bazlı** (K13) |
| `entered_by_id` | FK→`users` **SET NULL**, nullable | M4:114 (K14) |
| `note` | Text, nullable | |
| standart damgalar | | |

`amount` **KOLON DEĞİLDİR** — `liters × unit_price` her okumada türetilir (P10 "tek formül"
kanonu; iki yerde yaşayan para zamanla ayrışır).

---

## 3. Bağlanan kararlar (yönetim; yeniden tartışılmaz)

**K1 — `brand` ve `model` AYRI kolon.** M2:86 tek alan ("Marka / Model") çiziyor ama M1:94 kart
yalnız markayı basıyor. Tek alanda saklansaydı liste ekranı markayı ayıklamak için metin
parçalamak zorunda kalırdı. Form iki input basar; **onaylı sapma**, ROADMAP'e yazılır.

**K2 — `purchase_amount` koşullu zorunludur, DB'de nullable.** M2:98 `*` işaretli ama kiralık
makinenin alış bedeli yoktur. Kural **serviste**: `ownership == owned` iken zorunlu (**422**),
`rented` iken serbest. DB CHECK'i DEĞİL — kural nerede yaşadığı bilinsin (İK-3 S3 emsali).

**K3 — Satıcı ve kiralama firması TEK `supplier_id`'dir.** M2:101 serbest metin, M2:108 select,
ikisinde de aynı firma. İki alan tutulsaydı aynı firma iki kez yazılır, tedarikçi bakiyesi
ikiye bölünürdü. SA'nın `suppliers` tablosu **yeniden kullanılır**, yeni tablo AÇILMAZ.

**K4 — Atama hedefi `site_id`'dir (nullable), depo AÇILMAZ.** M2:118 etiketi "Atandığı Proje"
ama seçenekleri proje/şantiye/depo karışımı; **M5:89 aynı sütuna "Şantiye" diyor** → şantiye
kazanır. `Depoda (Atanmadı)` = `site_id IS NULL`. "Stok Deposu" için `warehouse_id` **AÇILMAZ** —
ikinci bir atama hedefi, "makine nerede" sorusunun iki cevabı olması demektir. **Onaylı sapma.**

**K5 — `norm_consumption` SAYI + `norm_unit` ENUM'a ayrılır.** M2:122 serbest metin
("4,2 Lt/saat") ama M4 bunun üzerinden **yüzde sapma** hesaplıyor (M4:52,62). Metin saklansaydı
hesap her okumada metin ayrıştırmaya bağlı olurdu. Birim iki değerlidir (M4:62 **Lt/km**).

**K6 — `maintenance_period` M2:123'ün DÖRT seçeneğini olduğu gibi taşır**
(`hours_250`/`hours_500`/`hours_1000`/`monthly`). "Aylık"ı saat kolonuna sıkıştırmak (NULL +
ayrı bayrak) aynı bilgiyi iki kolona bölerdi.

**K7 — `monthly_capacity_hours` VERİDİR, koda gömülmez** (İK-3 K1 emsali). Varsayılan **200**,
mockup'tan tersine mühendislikle doğrulandı: 186/200 = %93 · 152/200 = %76 · 42/200 = %21 ·
168/200 = %84 · 144/200 = %72 — **beşi de M3 rozetleriyle birebir**. Ekipman başına
değiştirilebilir (vinç ile el aleti aynı kapasitede değildir).

**K8 — "Şirket varlıklarına otomatik eklensin" (M2:166) YALNIZ BİR İŞARETTİR.** Sabit kıymet
modülü YOK; yan-etki uydurulmaz. `is_company_asset` saklanır, hiçbir şey tetiklemez.

**K9 — Tarihsel atama izi `work_log.site_id`de yaşar**, `equipment.site_id` **bugünkü**
atamadır. Makine şantiye değiştirir; geçmiş maliyet dağılımı kaydın kendi şantiyesinden
üretilir — yoksa makine taşındığında geçmiş aylar geriye dönük başka projeye yazılırdı.

**K10 — Arıza AYRI KAYIT TİPİDİR** (`record_type`), aynı kayıtta ikinci saat kolonu değil.
M3:282 arızayı kendi satırı olarak basıyor (operatörsüz, aralık yerine sebep metniyle) ve
M5:128-139 ayrı satır yapıyor. İki kolonlu tek kayıt bu iki sunumu da üretemezdi.

**K11 — 🔴 `hours` SUNUCU HESABIDIR, istemci gönderemez (422).** `start_time`+`end_time`
verilmişse `hours = end − start` (M3:261 `06:00–15:00` → 9 saat, mockup'ta doğrulandı).
Aralık verilmemişse `hours` doğrudan alınır (arıza kaydında aralık basılmıyor — M3:283).
İki alan **birlikte** ya hiç verilmez ya ikisi de verilir (yalnız biri → 422).
**Emsal: İK-2 K2 `days` sunucu hesabı.** Gece yarısını geçen vardiya (`end < start`) bu dilimde
**DESTEKLENMEZ** → 422 + açık Türkçe mesaj (mockup'ta örneği yok; sessiz negatif saatten iyidir).

**K12 — Çakışma denetimi YAPILMAZ, ama günlük tavan VAR.** Aynı ekipman + aynı gün kayıtlarının
**saat toplamı 24'ü aşamaz** (422). Vardiya örtüşmesi denetlenmez (mockup vardiya modeli
çizmiyor). 🔴 **EŞİK = KİLİT KANONU**: bu bir eşik denetimidir → `equipment` satırı
`with_for_update` ile **denetimden ÖNCE** kilitlenir; kilit sırası tüm uçlarda SABİT; regresyon
**iki gerçek bağlantıyla** yazılır ve kilit kaldırılınca KIRMIZI olduğu kanıtlanır.

**K13 — `unit_price` satır bazlıdır** (M4:111 kendi sütunu). Dönem sabiti olsaydı geçmiş
kayıtların tutarı bugünkü fiyatla değişirdi.

**K14 — "Giren" (M4:114) `entered_by_id` → `users`'tır.** Mockup rol basıyor ("Makine Op.")
ama rol kullanıcıdan türetilebilir; rol saklansaydı kimin girdiği kaybolurdu.

**K15 — 🔴 TOPLAMLARIN TEK KAYNAĞI SATIRLARDIR.** M3'ün tfoot'u kendi satırlarıyla
**tutarsızdır** (satır toplamı 692 saat / ₺144.200, tfoot 428 saat / ₺124.800; %69 ortalama
tabloyla uyuşmuyor). Bunlar mockup'ın aritmetik hatalarıdır. Sunucu **her zaman satırlardan**
toplar. **Emsal: TSD tfoot = `contract_total` TEK KAYNAK (F-P5 K5).**

**K16 — 🔴 NULL-EŞİK / fail-closed: hesaplanamayan oran UYDURULMAZ.**
- `norm_unit = lt_km` olan ekipmanda **kilometre verisi hiçbir ekranda girilmiyor** (odometre
  alanı YOK). Sapma **hesaplanmaz** → `deviation_pct = null` + makine-okunur
  `deviation_reason = "no_distance_data"`. Saatten uydurma bir Lt/km üretmek yanlış bir
  "anormal tüketim" alarmı doğururdu.
- `norm_consumption` yoksa sapma `null`.
- Çalışma saati **0** ise fiili tüketim `null` (sıfıra bölme → 0 basmak "hiç yakmadı" der).
- `monthly_capacity_hours` 0 ise kullanım % `null`.
**Hiçbir yerde uydurma 0 basılmaz** (İK-3 S4 emsali).

**K17 — Sapma eşikleri sabittir ama TEK YERDE durur.** Mockup: %7 → sarı, %16 → kırmızı
(M4:52, M4:62). Bağlanan eşik: `dev ≤ 0` → `normal` · `0 < dev < 10` → `warning` ·
`dev ≥ 10` → `critical`. Tek modülde (`consumption.py`), her uç oradan okur. **Rozetin kendisi
sunucudan gelir** (`consumption_status`) — F-P10 "rozet sunucu damgasıdır" kanonu.

**K18 — Maliyet formülü TEK YERDEDİR:** `cost = hours × saatlik_bedel`;
`saatlik_bedel = rate_amount` (`hourly`) · `rate_amount / DAILY_HOURS` (`daily`) ·
`rate_amount / monthly_capacity_hours` (`monthly`). **`DAILY_HOURS = 10`** — mockup'tan tersine
mühendislikle doğrulandı, DÖRT ekipmanda birden tutuyor: 3.200/320 · 2.800/280 · 1.400/140 ·
650/65 = **10** (M1:96,109,135,161 ↔ M3 satır maliyetleri). Sabit, gerekçesiyle tek yerde
(`cost.py`). `rate_amount` yoksa maliyet **`null`** (K16), 0 DEĞİL.

**K19 — `Decimal`, asla `float`.** Yuvarlama: para **tam sayıya, ROUND_HALF_UP**
(M4: 45×39,70 = 1.786,5 → ₺1.787 ✓; 62×39,70 = 2.461,4 → ₺2.461 ✓; dört satırda doğrulandı).
Oranlar bir ondalık (`4,5 Lt/saat`).

**K20 — `visible_projects` süzgeci UYGULANIR.** Ekipman bir şantiyeye atanır, maliyeti bir
projeye yansır — `personnel`/`payroll`ün şirket-geneli istisnası burada GEÇERLİ DEĞİL.
`site_id IS NULL` olan (depodaki) ekipman **herkese görünür** (hiçbir projeye ait değildir).
Çalışma/yakıt kayıtları kendi `site_id`leriyle süzülür.

**K21 — Sunucu mockup'tan FAZLA veri verebilir, EKSİK veremez.** Dördüncü durum sayacı (`idle`)
gibi alanlar açılır; hangisinin basılacağı frontend dilimin kararıdır.

---

## 4. Uçlar

İzin anahtarı **`equipment`** (21. modül) — okuma `view`, yazmanın tamamı `full`.
Görünmeyen kayıt → **404**.

### Ekipman
- `GET /equipment` — liste (M1 kartları). Süzgeç: `status`, `category`, `site_id`, `ownership`,
  `q`. **TB3 sayfalama kanonu: `limit ≤ 200`, `total` döner.**
- `POST /equipment` — K2 koşullu zorunluluk.
- `GET /equipment/{id}` · `PATCH /equipment/{id}` (kısmi).
- `DELETE` **YOKTUR** — `is_active=false` (PATCH). Kaydı olan ekipman zaten RESTRICT'lidir.
- `GET /equipment/summary` — M1 KPI'ları: `working`/`broken`/`maintenance`/**`idle`** sayaçları
  (K21) + `monthly_cost` (cari ay çalışma maliyeti toplamı, K15/K18).

### Çalışma kaydı
- `GET /equipment/work-logs` — süzgeç: `equipment_id`, `site_id`, `date_from`/`date_to`,
  `record_type`. Sayfalamalı.
- `POST /equipment/work-logs` · `PATCH /…/{id}` · `DELETE /…/{id}` (kayıt hatası düzeltilebilir;
  mali iz DEĞİL — türev maliyet).
- `GET /equipment/work-summary?year=&month=[&site_id=]` — **M3 ana tablosu**: ekipman başına
  `hours` · `usage_pct` · `breakdown_hours` · `cost` + **satırlardan türetilen** toplamlar (K15)
  + haftalık kova dizisi (M3:219-243; ay içi hafta bazlı, her kovada `hours` + baskın `record_type`).

### Yakıt
- `GET /equipment/fuel-logs` — süzgeç: `equipment_id`, `site_id`, `date_from`/`date_to`. Sayfalamalı.
- `POST` · `PATCH` · `DELETE`.
- `GET /equipment/fuel-summary?year=&month=[&equipment_id=]` — **M4 üst bloğu**: toplam litre ·
  toplam tutar · `lt_per_hour_avg` (payda **çalışma kaydı** saat toplamı — modüller arası bağ,
  M4:39'da 2.840/428 = 6,6 ile doğrulandı) · ortalama litre fiyatı · `abnormal_count` +
  ekipman başına satırlar (`liters` · `amount` · `actual` · `norm` · `deviation_pct` ·
  `consumption_status`).

---

## 5. Enum'lar (dokuzu da YENİ; downgrade'de hepsi `DROP TYPE`)

| Tip | Değerler | Kaynak |
|---|---|---|
| `equipment_category` | `crane` · `machinery` · `truck` · `concrete` · `compressor` · `hand_tool` | M2:85 |
| `equipment_status` | `working` · `maintenance` · `broken` · `idle` | M2:120 |
| `equipment_ownership` | `owned` · `rented` | M2:54-66 |
| `equipment_financing` | `cash` · `bank_loan` · `leasing` | M2:102 |
| `equipment_rate_period` | `hourly` · `daily` · `monthly` | M2:109 |
| `equipment_fuel_type` | `diesel` · `gasoline` · `electric` · `none` | M2:121 |
| `equipment_norm_unit` | `lt_hour` · `lt_km` | K5 |
| `equipment_maintenance_period` | `hours_250` · `hours_500` · `hours_1000` · `monthly` | M2:123 |
| `work_log_type` | `worked` · `breakdown` | K10 |

Kategori ikonu (M1 emojileri) **DB'de tutulmaz** — kategoriden türer, frontend haritası.

---

## 6. İzin matrisi (`seed_data.py` + migration)

Yeni modül: `{"key": "equipment", "name": "Makine & Ekipman", "group": ModuleGroup.SAHA, …}`
(`sort_order` mevcut en yüksekten sonraya — şef son değeri okuyup uyarlar).

Rol satırı (semantik — şef mevcut `_A/_F/_V/_N` sabitlerine çevirir, `payroll` satırının
kolon sırasını izler):
`system_admin` admin · `patron` full · `site_chief` **full** (makineyi sahada o kullanır) ·
`field_engineer` **view** · `hr_manager` **none** · `accounting` **full** (varlık + maliyet) ·
`project_manager` **full** · `procurement` **view**.

🔴 Yeni izin modülü **migration ister** (BC/`documents` emsali) — seed'i değiştirmek canlıdaki
mevcut kayıtlara satır eklemez.

---

## 7. Tuzaklar (bu dilime özgü)

- 🔴 **`alembic/env.py`'ye yeni modül EKLENİR** (TB1 dersi) — unutulursa autogenerate tabloları görmez.
- 🔴 **`down_revision` canlı head `c5d6e7f8a9b0`'dır** (İK-3). `alembic heads` **TEK satır**
  olduğu doğrulanır (çift head = canlıda TAM KESİNTİ).
- 🔴 Postgres enum downgrade'de **dokuz tipin hepsi `DROP TYPE`**.
- 🔴 **PG sürüm tuzağı:** yerel 18, CI 16 — RESTRICT ihlali SQLSTATE'i farklı (`23001` ↔ `23503`).
  Sürüme özgü tek kod iddia eden test YAZILMAZ, iki değeri kabul eden **dar tuple** kullanılır.
- 🔴 `suppliers` (SA) / `sites` / `personnel` importları **çember riski** taşır (P10 `cost_cards`
  dersi) — gerekirse gecikmeli import + AST bekçisi.

---

## 8. Kabul kriterleri

1. Üç tablo + dokuz enum + izin modülü migration'ı; `upgrade` **ve** `downgrade` turu testli.
2. K11 (`hours` sunucu hesabı) · K12 (24 saat tavanı **kilitli**, iki bağlantılı regresyon,
   kilit kaldırılınca KIRMIZI) · K16 (dört fail-closed `null` yolu) · K18 (maliyet formülü tek
   yerde) — hepsi testli.
3. K15: özet toplamları **satırlardan** üretiliyor; mockup'ın tfoot sayıları kopyalanmamış —
   bunu kanıtlayan test var.
4. K7/K18'in mockup doğrulaması test olarak kayıtlı (200 saat paydası · `DAILY_HOURS = 10`).
5. `visible_projects` süzgeci (K20) uçlarda testli; `site_id IS NULL` ekipman herkese görünür.
6. TDD: **önce test, KIRMIZI GÖR.** İlk koşuda yeşilse mutasyon denetimi.
7. `ruff check .` + `ruff format --check .` **tüm repo** (alembic dahil) temiz.
8. Testler yalnız **yerel** DB'de (`TEST_DATABASE_URL` override) — canlıya DOKUNULMAZ.

---

## 9. Kapsam DIŞI — MK-2'ye devredilenler (ROADMAP'e yazılır)

1. **M5 Kira Hakedişi.** 🔴 **Mockup'ta çözülmemiş para tutarsızlığı:** gelen fatura tutarı
   122.496 = "bizim hesap" 102.080 × 1,20 **tam olarak**; üstüne bir kez daha %20 KDV eklenip
   ₺146.995 "ödenecek" çıkıyor (M5:156,163,166,170) — ya **çift KDV** ya mockup'ta yanlış rakam.
   İddia edilen fark "6 saat × 280 = 1.680" ile de uyuşmuyor. **KDV matrahı KULLANICIYA
   sorulacak** — para kararı, uydurulmaz. Diğer açık uçlar: fatura tek toplam mı satır bazlı mı
   (M5:63 ↔ M5:111/125 ikisi de var) · fark çözüm durumları (yalnız `Doğrulama Bekliyor` çizili) ·
   `Kiracıya Gönder` butonu akış yönüyle çelişiyor · "Kendi" makinenin maliyet tabanı (mockup
   "Amortisman" yazıp saatlik hesap basıyor) · bir hakediş tek firmaya mı ait (başlık tek firma
   seçiyor, tablo iki markayı karıştırıyor).
2. **Ekipman belgeleri** (M2:128-162, 6 slot) — mockup **geçerlilik tarihi alanı çizmiyor**;
   tarihsiz saklanırsa süresi dolmuş muayene "var" görünür. İK-1 `personnel_documents` emsali
   hazır. **Mockup eki istenecek.**
3. **Bakım Takvimi** — M3:39 menüde var, **mockup YOK**. `maintenance_period` verisi bu dilimde
   saklanıyor; ekran ve bakım kaydı tablosu bekliyor.
4. **Ekipman detay sayfası** — hiçbir mockup'ta yok (kartlar tıklanabilir değil).
5. Çalışma kaydı ve yakıt girişi **formlarının mockup'ı YOK** (M3:49, M4:22). Uçlar bu dilimde
   açılır, **ekran mockup bekler.**
6. Alt-navigasyon çelişkisi (M3 sidebar'ı ile M4 sekmeleri farklı 4 öğe listeliyor) — frontend
   dilimin kararı, kullanıcıya sorulacak.
