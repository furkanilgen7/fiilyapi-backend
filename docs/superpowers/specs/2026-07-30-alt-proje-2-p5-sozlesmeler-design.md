# Alt-Proje 2 · P5 — Sözleşmeler (tasarım)

Tarih: **2026-07-30**
Repo: `backend`
Önceki dilimler: P1 (proje çekirdeği) · P1.1a (proje formu + `project_contracts`) · P2 (şantiye/bölüm) ·
P4 (BOQ) · P3 (blok/ünite)
Sonraki bağımlı dilim: **P7 — hakediş** (bu dilimde YAPILMAZ, ama şema onu taşıyabilmelidir)

Kanon mockup'lar (satır numaraları bu dosyada bu dosyalara atıftır):

| Kısaltma | Dosya |
|---|---|
| **SZL** | `projedesign/Sözleşmeler.dc.html` (111 satır) |
| **E14** | `projedesign/Ekran 14 - Sözleşme Detay.dc.html` (154 satır) |
| **TSD** | `projedesign/Taşeron Sözleşme Detay.dc.html` (209 satır) |
| **FORM** | `projedesign/Form - Sözleşme Oluştur.dc.html` (241 satır) |
| **POZ** | `projedesign/İşveren Sözleşme - Poz Dağılımı.dc.html` (192 satır) |
| TL | `projedesign/Taşeron Listesi.dc.html` (112 satır) — yalnız kartoteks alanları için |

---

## 0. Bu dilime girerken bulunan üç gerçek

Spec'in geri kalanı bu üç bulgunun üzerine kuruludur.

1. **İşveren sözleşmesi zaten var ve canlıda.** `app/modules/projects/models.py:165`
   `ProjectContract` → `project_contracts`, proje ile **1-1** (PK = `project_id`).
   Taşıdığı alanlar: `contract_no`, `signature_date`, `amount`, `advance_pct`,
   `retainage_pct`, `vat_pct`, `late_penalty_daily`, `has_price_escalation`,
   `index_type`, `base_index_value`. Yani görev tanımındaki *"fiyat farkı / endeks /
   teminat alanları"* işveren tarafında **P1.1a'da yazılmış**. Bu dilim onları yeniden
   yazmaz, **üstüne inşa eder**.
2. **Taşeron kartoteksi yok.** `employers` tablosu var (P1'de Alt-Proje 3'ten öne
   çekilmişti), `subcontractors` yok. Taşeron sözleşmesi için asgari kartoteks bu
   dilimde açılmak zorundadır — `Employer` deseninin birebiri.
3. **İşveren sözleşmesi için form mockup'ı yok.** `FORM` dosyasının başlığı
   "Yeni **Taşeron** Sözleşmesi"dir (satır 47). İşveren tarafının tek giriş yüzeyi
   bugün `Form - Proje Oluştur` içindeki gömülü alanlardır. Sonucu §13.2'de.

---

## 1. Kullanıcı kararları (2026-07-30 oturumu — yeniden tartışılmaz)

| # | Karar | Gerekçe |
|---|---|---|
| **K1** | **Ayrı tablolar.** `project_contracts` yerinde kalır (yalnız eksik alanlar eklenir), yeni `subcontractor_contracts` açılır. Tek `contracts` tablosuna göç YOK. | Göç riski sıfır; `projects.contract_no`/`contract_amount` anlık görüntü mantığı, P1 proje formunun nested `contract` yazımı, dashboard ve `sites` şemaları kırılmaz. İki tarafın alan kümesi zaten büyük ölçüde ayrışıyor. |
| **K2** | **`employer_contract_items` açılır ve `boq_items.contract_item_id` eklenir.** | `POZ` ekranının üç unsuru (Kalan kolonu 84/100, "2 poz henüz dağıtılmadı" uyarısı 65, şantiye kota özetleri 168-187) ancak sözleşme düzeyinde bir poz listesi varsa çıkar. **Kalıcı karar 1'den ("BOQ'da `contract_id` YOK") BİLİNÇLİ SAPMA** — kullanıcı onayıyla. §3.3'te ayrıntılı. |
| **K3** | **Taşeron bedeli türev, işveren bedeli elle.** Taşeron: bedel = Σ(miktar × taşeron b.f.), kolon saklanmaz. İşveren: `project_contracts.amount` elle girilmeye devam eder, yanında türev `items_total` ve fark döner. | `FORM` 181-182 ve `TSD` 176-177 `tfoot`'ları türev bir toplam gösteriyor. İşveren tarafında mockup'ın kendisi türetmiyor: `POZ` 47'de toplam ₺22,4M iken şantiye özetleri 11,2 + 9,4 = 20,6M. |
| **K4** | **Taşeron sözleşmesi proje düzeyinde, şantiye isteğe bağlı.** `project_id` zorunlu, `site_id` nullable. | Proje geneli ortak taşeron sözleşmesi mümkün olmalı. **`FORM` 59'daki "Şantiye *" zorunluluk işaretinden ONAYLI SAPMA.** |
| **K5** | **Yeni `contracts` izin modülü — 18. modül.** | Şantiye şefi / saha mühendisi / İK (hepsi `projects=_LIM`) taşeron birim fiyatlarını görmemelidir. `boq` modülünde aynı gerekçeyle aynı sapma yapılmıştı. |

**K2 ve K4 birer onaylı sapmadır.** Sonraki oturumlarda "spec'ten sapma" diye geri alınmaz.

---

## 2. Kapsam

### 2.1 Kapsam içi

* `project_contracts` genişlemesi: `status` (§3.1)
* `employer_contract_groups` + `employer_contract_items` (§3.2)
* `boq_items.contract_item_id` + poz dağılımı okuma/yazma yolu (§3.3, §6.3)
* `subcontractors` kartoteksi (§3.4)
* `subcontractor_contracts` + `subcontractor_contract_items` (§3.5, §3.6)
* Birleşik sözleşme listesi + özet kartları (§6.1)
* Yeni `contracts` izin modülü, matris satırı, migration (§5)
* Taslak desteği, durum akışı, silme korkulukları, denetim günlüğü (§4, §7, §8)

### 2.2 Kapsam DIŞI (tek tek, gerekçeli)

| Ne | Neden | Yanıtta karşılığı |
|---|---|---|
| **Hakediş** (`TSD` 184-204 geçmiş tablosu, `E14` 126-148 özet, `SZL` 37 "Toplam Hakediş", `TSD` 103 "Hakediş %") | P7'nin işi. Şema onu taşır: sözleşme + kalem sabit kimliklerdir. | `progress_payment_summary: null` + `pending_module: "progress_payments"` |
| **Milestone Takvimi** (`E14` 99-122) | Milestone verisi P11 (Gantt / Proje Takvimi) diliminin modelidir. Burada ikinci bir kaynak açmak kaçınılmaz olarak ayrışır. | `milestones: null` + `pending_module: "project_schedule"` |
| **Sözleşme belgeleri** (`FORM` 190-230 — 6 yükleme alanı; `E14` 94 "Belgeler" sekmesi) | **Kalıcı karar 8:** belgeler kendi diliminde, ara çözüm yazılmaz. | `documents: null` + `pending_module: "documents"` |
| **PDF çıktısı** (`E14` 76, `TSD` 24) | Ayrı bir üretim katmanı; BOQ Excel çıktısı deseni var ama sözleşme PDF'i bu dilimin işi değil. | Uç yok. Frontend butonu devre dışı + kullanıcıya bildirim. |
| **Taşeron "Puan"ı** (`TL` kolon 7) | Puanın girildiği hiçbir form yok — alan icat edilmez. | Kolon yok. |
| **Zeyilname / ek sözleşme** | Mockup'ı yok; §13.2'de kullanıcıdan istenecek. | Yok. |
| **Sözleşme durum makinesi** (geçiş kısıtları) | YAGNI: mockup üç rozet gösteriyor, geçiş kuralı göstermiyor. | `status` serbestçe PATCH'lenir. |

---

## 3. Şema

### 3.0 Hiyerarşi

```
Project ──1-1── ProjectContract (işveren sözleşmesi)
   │                  │
   │                  └──1-N── EmployerContractGroup ──1-N── EmployerContractItem
   │                                                                │
   │                                                     (nullable) │ contract_item_id
   │                                                                ▼
   ├──1-N── Site ──1-N── BoqGroup ──1-N── BoqItem  ← şantiye kotası
   │
   └──1-N── SubcontractorContract ──1-N── SubcontractorContractItem
                   │                              │
                   │ subcontractor_id             │ source_contract_item_id (nullable)
                   ▼                              ▼
             Subcontractor                EmployerContractItem
```

**Tek cümle:** işveren sözleşmesi pozları *ne yapılacağını*, BOQ satırları *hangi
şantiyede ne kadarının yapılacağını*, taşeron sözleşmesi kalemleri *kime ne fiyata
yaptırılacağını* söyler.

### 3.1 `project_contracts` genişlemesi — TEK yeni kolon

```python
status: Mapped[ContractStatus] = mapped_column(
    Enum(ContractStatus, name="contract_status"),
    nullable=False, default=ContractStatus.active, server_default="active",
)
```

`ContractStatus` yeni enum: `active` · `completed` · `on_hold`
(`SZL` 61 "Aktif" yeşil · 71 "Tamamlandı" gri · 91 "Beklemede" sarı).

**Neden NOT NULL, "yeni kolonlar NOT NULL yapılmaz" kuralına rağmen:** o kural
*kullanıcının doldurması gereken* alanlar içindir; gerekçesi taslak desteğidir.
`status`'ün sunucu tarafında anlamlı bir varsayılanı vardır (`active`) ve boş
bırakılması "girilmedi" diye bir durum üretmez. `sites`'taki 8 Boolean ve
`projects.status` aynı desendedir.

**Başlangıç/bitiş tarihi BURAYA AÇILMAZ.** P1.1a spec §2.4 kararı: tarihler
`projects.start_date` / `projects.end_date`'te durur. `SZL` 47-48 Başlangıç/Bitiş
kolonları işveren satırlarında oradan okunur. İkinci bir tarih kaynağı açmak
`projects` ile ayrışır.

**`amount` elle kalır** (K3). Yanıt ayrıca `items_total` (türev) ve
`items_total_diff = amount − items_total` döner; frontend uyuşmazlığı gösterir.

### 3.2 `employer_contract_groups` + `employer_contract_items` (YENİ)

`BoqGroup` / `BoqItem` deseninin **birebiri** — bilinçli simetri: poz dağılımı bu iki
yapıyı satır satır eşleştirir; şekilleri ayrışırsa eşleştirme kodu her iki tarafı da
çevirmek zorunda kalır.

**`employer_contract_groups`** (`POZ` 90 "A — Betonarme İşleri", 125 "B — Kalıp
İşleri", 140 "C — Duvar & Kaplama"):

| Kolon | Tip | Not |
|---|---|---|
| `id` | UUID PK | |
| `project_id` | UUID FK → `project_contracts.project_id` **CASCADE**, NOT NULL, indeksli | Sözleşme PK'si `project_id`'dir |
| `name` | Text NOT NULL | Baştaki "A —" harfi SAKLANMAZ; sıra `sort_order`'dan türer, harfi frontend basar (`BoqGroup` kuralının aynısı) |
| `sort_order` | Integer NOT NULL default 0 | |
| `created_at` / `updated_at` | timestamptz | |

**`employer_contract_items`**:

| Kolon | Tip | Mockup | Not |
|---|---|---|---|
| `id` | UUID PK | | |
| `project_id` | UUID FK → `project_contracts.project_id` CASCADE, NOT NULL, indeksli | | `(project_id, code)` benzersizliği için gerekli |
| `group_id` | UUID FK → `employer_contract_groups.id` CASCADE, NOT NULL, indeksli | | |
| `code` | String(50) NOT NULL | `POZ` 93 `03.001` | |
| `description` | Text NOT NULL | `POZ` 94 | |
| `unit` | String(50) NOT NULL | `POZ` 95 `m³` | Serbest metin, enum değil (`BoqItem` kararı) |
| `quantity` | Numeric(14,3) NOT NULL | `POZ` 97 "Toplam Miktar" 3.200 | |
| `unit_price` | Numeric(18,2) NOT NULL | `POZ` 96 "Sözl. Birim F." ₺1.850 | |
| `sort_order` | Integer NOT NULL default 0 | | |
| `created_at` / `updated_at` | timestamptz | | |

Kısıtlar (`BoqItem` ile birebir): `UniqueConstraint(project_id, code)` ·
`CHECK quantity > 0` · `CHECK unit_price >= 0`.

Grup→sözleşme tutarlılığı DB'de bileşik FK ile **zorlanmaz**, servis korkuluğuyla
sağlanır (`BoqItem` §3.3 invariant 1'in aynısı): yazma yolu tekildir.

### 3.3 `boq_items.contract_item_id` — ONAYLI SAPMA (K2)

```python
contract_item_id: Mapped[uuid.UUID | None] = mapped_column(
    UUID(as_uuid=True),
    ForeignKey("employer_contract_items.id", ondelete="SET NULL"),
    nullable=True, index=True,
)
```

* **Neden `SET NULL`, `CASCADE` değil:** BOQ satırı sahadaki *gerçekleşen işin*
  kaydıdır ve ona bağlı günlük kayıt/hakediş doğar. Sözleşme kalemi silinince satır
  yok olmaz, yalnız bağ kopar.
* **Kısmi benzersiz indeks:**
  `uq_boq_items_contract_item_site (contract_item_id, site_id) WHERE contract_item_id IS NOT NULL`
  — `POZ` tablosunda her şantiye için **tek** kota hücresi vardır (98-99, 108-109).
* **`contract_item_id IS NULL` meşrudur ve kalıcıdır:** şantiye kendi başına poz
  girebilir (P4'ün mevcut davranışı). Bu satırlar dağılım ekranında görünmez, BOQ
  ekranında görünür. **Kalıcı karar 1 tamamen iptal edilmemiştir** — `boq_items`'a
  `section_id` hâlâ AÇILMAZ, açılan tek ileri bağ budur.
* **Kalan hesabı:** `remaining = contract_item.quantity − Σ(bağlı boq_items.quantity)`
  (`POZ` 84 "Kalan", 100 `✓ 0`, 161 kırmızı `18.400`).
* **Aşım engellenir (422):** bağlı kotaların toplamı sözleşme miktarını geçemez.
  `POZ` 72: "Sözleşme miktarı = tüm şantiye kotaları toplamı olmalı" ve hiçbir yerde
  negatif Kalan gösterilmiyor. Bu bir **tutarlılık** kuralıdır → taslakta da koşar.

### 3.4 `subcontractors` (YENİ) — `Employer` deseninin birebiri

Asgari çekirdek. Tam cari hesap alanları (kısa ad, cari kod, IBAN, adres) Alt-Proje
3'ün işidir — `Employer`'da olduğu gibi.

| Kolon | Tip | Mockup |
|---|---|---|
| `id` | UUID PK | |
| `name` | String(200) NOT NULL | `FORM` 76 "Taşeron Firma *" |
| `tax_number` | String(11) NULL | `FORM` 78 "VKN" |
| `contact_person` | String(200) NULL | `FORM` 79 "Yetkili Kişi" |
| `phone` | String(30) NULL | `FORM` 80 "Telefon" |
| `email` | String(255) NULL | `FORM` 81 "E-posta" |
| `category` | String(100) NULL | `FORM` 82 "İş Kategorisi *" / `TL` "Kategori" |
| `is_active` | Boolean NOT NULL default true | `Employer` deseni |
| `created_at` / `updated_at` | timestamptz | |

* Kısmi benzersiz indeks `uq_subcontractors_tax_number (tax_number) WHERE tax_number IS NOT NULL`
  + `ix_subcontractors_name` — `Employer` ile birebir.
* **`category` enum DEĞİL, String.** `FORM` 82'deki altı seçenek (Betonarme, Elektrik,
  Mekanik Tesisat, Sıhhi Tesisat, Doğrama, Boya & Kaplama) frontend'de sabit liste
  olarak durur; **sunucu listeyi zorlamaz**. Gerekçe: enum her yeni iş kolunda
  migration ister; ayrıca `FORM` 76 zaten "+ Yeni Taşeron Ekle" ile serbestlik
  vaat ediyor. KDV listesinin kodda sabit tutulması kararının (kalıcı karar 9) aynı
  mantığı.
* **`rating` kolonu YOK** (§2.2).

### 3.5 `subcontractor_contracts` (YENİ)

Alanların **tamamı** `FORM` ve `TSD`'den; satır numarası verilmeyen tek alan yoktur.

| Kolon | Tip | Mockup | Not |
|---|---|---|---|
| `id` | UUID PK | | |
| `project_id` | UUID FK → `projects.id` CASCADE, NOT NULL, indeksli | `FORM` 56 | K4 |
| `site_id` | UUID FK → `sites.id` **RESTRICT**, NULL, indeksli | `FORM` 60 | K4: boşsa proje geneli. RESTRICT → sözleşmesi olan şantiye silinemez (§7) |
| `subcontractor_id` | UUID FK → `subcontractors.id` **RESTRICT**, NULL | `FORM` 76 | Nullable: taslak. RESTRICT: sözleşmesi olan taşeron silinemez |
| `subcontractor_name` | String(200) NULL | `TSD` 41 | **Anlık görüntü** — servis her yazmada kartotekten kopyalar (`projects.employer_name` deseni). Kartoteks silinse de evrakta ad kalır |
| `work_category` | String(100) NULL | `FORM` 82 | |
| `contract_no` | String(100) NULL | `FORM` 90 `TSZ-2026-004` | Kısmi benzersiz indeks (global, NULL hariç) |
| `signature_date` | Date NULL | `FORM` 91 | |
| `is_notarized` | Boolean NOT NULL default false | `FORM` 92 "Noter Onaylı" | |
| `start_date` | Date NULL | `FORM` 93 "İşe Başlama" | |
| `end_date` | Date NULL | `FORM` 94 "Bitiş Tarihi" | |
| `late_penalty_daily` | Numeric(18,2) NULL | `FORM` 95 "Gecikme Cezası (₺/gün)" | |
| `advance_pct` | Numeric(5,2) NOT NULL default **10** | `FORM` 99 `value="10"` | İşveren tarafındaki 20'den farklı — mockup böyle |
| `retainage_pct` | Numeric(5,2) NOT NULL default **5** | `FORM` 100 "Teminat Kesintisi" | |
| `payment_period` | Enum `payment_period` NOT NULL default `monthly` | `FORM` 101 | `monthly` (Aylık) · `biweekly` (15 Günlük) · `on_completion` (İş Bitiminde) |
| `payment_term_days` | Integer NOT NULL default 30 | `FORM` 102 "Ödeme Vadesi (Gün)" | |
| `materials_by_contractor` | Boolean NOT NULL default **false** | `FORM` 105 | Mockup'ta `checked` ama **ön-işaretler örnek veridir, uygulanmaz** (şantiye formu spec §14.2 kuralı) |
| `subcontractor_files_own_sgk` | Boolean NOT NULL default **false** | `FORM` 106 | Aynı kural |
| `vat_withholding` | Boolean NOT NULL default false | `FORM` 107 "KDV tevkifatı" | |
| `status` | Enum `contract_status` NOT NULL default `active` | `TSD` 38 "Aktif" | §3.1'deki enum |
| `is_draft` | Boolean NOT NULL default false | `FORM` 234 "Taslak Kaydet" | |
| `created_by` | UUID FK → `users.id` **RESTRICT**, NOT NULL | | `can_delete` korkuluğu (`app/core/access.py`) `created_by` + `is_draft` ister |
| `created_at` / `updated_at` | timestamptz | | |

CHECK kısıtları:
* `ck_subcontract_pct_range`: `advance_pct BETWEEN 0 AND 100 AND retainage_pct BETWEEN 0 AND 100`
* `ck_subcontract_payment_term`: `payment_term_days >= 0`

**`amount` kolonu YOKTUR** (K3) — bedel türevdir.
**`employer_contract_id` kolonu YOKTUR:** `FORM` 63-65'teki "İşveren Sözleşmesi
SZL-2025-001" salt okunur bir bağlamdır ve `project_id` üzerinden türer
(sözleşme projeyle 1-1). İkinci bir FK aynı bilgiyi iki yerde tutar.

### 3.6 `subcontractor_contract_items` (YENİ)

| Kolon | Tip | Mockup | Not |
|---|---|---|---|
| `id` | UUID PK | | |
| `contract_id` | UUID FK → `subcontractor_contracts.id` CASCADE, NOT NULL, indeksli | | |
| `source_contract_item_id` | UUID FK → `employer_contract_items.id` **SET NULL**, NULL, indeksli | `FORM` 115 "SZL-2025-001'den yüklendi" | Bağ kopsa da taşeron kalemi ve fiyatı kalır |
| `code` | String(50) NOT NULL | `FORM` 134 | |
| `description` | Text NOT NULL | `FORM` 135 | |
| `unit` | String(50) NOT NULL | `FORM` 136 | |
| `quantity` | Numeric(14,3) NOT NULL | `FORM` 137 (düzenlenebilir input) | İşverenden kopyalanır, sonra serbestçe değiştirilir |
| `unit_price` | Numeric(18,2) **NULL** | `FORM` 138 "⭐ Taşeron B.F." | **Nullable bilinçli:** işverenden yüklenen kalem fiyatsız gelir; "girilmedi" ile "0 TL" ayrımı korunur |
| `sort_order` | Integer NOT NULL default 0 | | |
| `created_at` / `updated_at` | timestamptz | | |

Kısıtlar: `UniqueConstraint(contract_id, code)` · `CHECK quantity > 0` ·
`CHECK unit_price IS NULL OR unit_price >= 0`.

**Ayrı grup tablosu AÇILMAZ.** `FORM` 132/160'taki grup başlıkları
`source_contract_item_id` → `employer_contract_items.group_id` üzerinden **türer**.
Bağsız kalemler (`+ Poz Ekle`, `FORM` 116) gruba düşmez; yanıtta `group: null` ile
döner, frontend onları listenin sonunda gösterir. İşveren sözleşmesi olmayan bir
projede (ör. kendi yatırım) tüm kalemler grupsuzdur — kabul edilen sonuç.

Türev alanlar (saklanmaz): `line_total = quantity × unit_price` (`FORM` 139) ·
`contract_total = Σ line_total` (`FORM` 182 ₺3.065.500, `TSD` 177 ₺3.281.500).
`unit_price IS NULL` olan satır toplama **0 katkı verir** ve yanıt
`items_missing_price` sayısını döner.

---

## 4. Taslak desteği ve durum

**Taslak VAR** — `FORM` 234'te "Taslak Kaydet" butonu mockup'ta açıkça duruyor.
Desen `sites`/`projects` ile birebir (kalıcı karar 4):

> **Tutarlılık kuralları HER ZAMAN koşar, zorunluluk kuralları YALNIZ taslak-dışında.**

**Zorunluluk kuralları** (yalnız `is_draft = false`) — `FORM`'daki `*` işaretleri:

| Kural | Mockup | Hata metni |
|---|---|---|
| Proje seçilmeli | `FORM` 55 | `PROJECT_REQUIRED = "Proje seçiniz."` |
| Taşeron firma seçilmeli | `FORM` 75 | `SUBCONTRACTOR_REQUIRED = "Taşeron firma seçiniz."` |
| İş kategorisi | `FORM` 82 | `CATEGORY_REQUIRED = "İş kategorisi zorunludur."` |
| Sözleşme no | `FORM` 90 | `CONTRACT_NO_REQUIRED = "Sözleşme no zorunludur."` |
| İmza tarihi | `FORM` 91 | `SIGNATURE_DATE_REQUIRED = "İmza tarihi zorunludur."` |
| İşe başlama + bitiş | `FORM` 93-94 | `DATES_REQUIRED = "İşe başlama ve bitiş tarihi zorunludur."` |
| Girilen kalemlerin **hepsinde** birim fiyat | `FORM` 138 (sarı alan) | `ITEM_PRICES_REQUIRED = "Tüm pozlarda taşeron birim fiyatı zorunludur."` |

> **Kullanıcı kararı (2026-07-30, C4 incelemesi):** "en az bir kalem" şartı **UYGULANMAZ.**
> Kalemsiz sözleşme yayına geçebilir; kalemler sonradan eklenir (götürü bedelli işler ve
> `load-from-employer` akışı için esneklik). Kural yalnız **girilmiş** kalemlere bakar.
> Bu bir eksik uygulama değildir — geri getirilmez.

**Şantiye zorunlu DEĞİLDİR** — K4 gereği `FORM` 59'daki `*`'tan onaylı sapma.

**Tutarlılık kuralları** (her zaman):

| Kural | Hata metni |
|---|---|
| `end_date >= start_date` | `END_BEFORE_START = "Bitiş tarihi işe başlama tarihinden önce olamaz."` |
| `site_id` doluysa şantiye o projeye ait olmalı | `SITE_PROJECT_MISMATCH = "Seçilen şantiye bu projeye ait değil"` |
| Poz kotaları toplamı sözleşme miktarını aşamaz | `DISTRIBUTION_EXCEEDS = "Şantiye kotaları toplamı sözleşme miktarını aşamaz."` |
| Dağıtılan şantiye o projeye ait olmalı | `SITE_PROJECT_MISMATCH` |

Kurallar tek kopya `app/modules/contracts/guards.py`'de durur; POST ve PATCH'in
taslak→yayın dalı **kopyalamaz, çağırır** (`sites/guards.py` docstring'indeki kural).

`PATCH` genel dalında zorunluluk kuralları **koşmaz** (`sites` §0.3/3 dersi: aksi
hâlde canlıdaki eksik kayıtlar düzenlenemez hâle gelir); yalnız `is_draft: true →
false` geçişinde birleşik kayıt üzerinde tüm kurallar koşar.

---

## 5. İzin modülü (K5)

`app/modules/roles/seed_data.py`:

```python
{"key": "contracts", "name": "Sözleşmeler", "group": ModuleGroup.MALI, "sort_order": 18},
```

**`sort_order` 18, kaydırma YOK.** Mockup sidebar'ında (`E14` 52-53) Sözleşmeler
"Sözleşme & Mali" grubunun başındadır, ama `boq` da GENEL grubunda olmasına rağmen
17 ile sona eklenmişti. Mevcut modüllerin `sort_order`'larını kaydırmak canlıdaki
İzin Matrisi ekranını gereksizce oynatır; grup içi görsel sıra frontend'in işidir.

Matris satırı:

```python
"contracts": [_A, _F, _N, _N, _N, _FIN, _F, _N],
#             sysadm patron şef  saha  İK  muhasebe PM  satınalma
```

* `site_chief` / `field_engineer` / `hr_manager` = `_N` — **bu modülün var oluş
  sebebi.** `projects=_LIM` oldukları için mevcut bir modüle bağlansaydı taşeron
  birim fiyatlarını görürlerdi.
* `accounting` = `_FIN` (görüntüle, mali kapsam) — sözleşmeyi görür, oluşturmaz;
  `accounting`/`invoicing`/`treasury` satırlarındaki mali görünürlük deseni.
* `project_manager` = `_F` — taşeron sözleşmesini pratikte proje müdürü yapar.
* `procurement` = `_N` — satınalma malzeme alır, alt yüklenici sözleşmesi yapmaz.

**Maliyet listesi (kullanıcıya bildirilmiş):** migration'da modül satırı + 8 izin
satırı · `MATRIX`/`MODULES` güncellemesi · parity testleri · **modül sayısını 17'de
sabitleyen tüm testler 18'e taşınır** · `Ayarlar - İzin Matrisi` mockup'ında
"Sözleşmeler" satırı YOK → **bilinçli sapma** (`boq`'daki sapmanın aynısı) ·
frontend tarafında `me` izin haritası + BFF `ALLOWED_ROOTS`'a `contracts`,
`subcontractors`, `subcontractor-contracts` kökleri.

---

## 6. Uçlar

Router deseni `boq`'unkiyle aynı: alt kaynağa POST `/…/{parent_id}/…` altında,
PATCH/DELETE düz kökte (dolaylı kimlik çözümlemesi).

Kapılar: `_VIEW = require_permission("contracts", AccessLevel.view)` ·
`_FULL = …full` · `_ADMIN = …admin`.

**Her uç ayrıca proje görünürlüğünden geçer** (`projects.service.visible_projects`).
İki katman: `contracts` izni *yetkiyi*, `user_project_access` *kapsamı* belirler.
Görünmeyen projedeki gerçek sözleşme ile var olmayan sözleşme **ayırt edilemez**
404 döner.

### 6.1 Birleşik liste

`GET /contracts?type=employer|subcontractor&project_id=&status=&q=` → `_VIEW`

`type` **zorunludur** (`SZL` 27-28'de daima biri seçili).

Yanıt `ContractListResponse`:
* `summary` (`SZL` 34-38): `total_amount` · `active_count` ·
  `progress_payment_total: null` + `pending_module: "progress_payments"` ·
  `expiring_this_month_count` (bitiş tarihi içinde bulunulan ay olan, `active` sözleşmeler)
* `items[]` (`SZL` 44-51 kolonları): `id` · `title` · `contract_no` ·
  `counterparty_name` · `amount` · `start_date` · `end_date` · `progress_pct` ·
  `status` · `is_draft`

Alan eşlemesi:

| Kolon | İşveren | Taşeron |
|---|---|---|
| `title` | `projects.name` | `subcontractor_name + " — " + work_category` (`TSD` 40 deseni) |
| `contract_no` | `project_contracts.contract_no` | `subcontractor_contracts.contract_no` |
| `counterparty_name` | `projects.employer_name` | `subcontractor_name` |
| `amount` | `project_contracts.amount` (elle) | `Σ(quantity × unit_price)` (türev) |
| `start_date`/`end_date` | `projects.start_date`/`end_date` | sözleşmenin kendi tarihleri |
| `progress_pct` | `projects.progress_pct` | `null` + `pending_module` |

### 6.2 İşveren sözleşmesi

| Uç | Kapı | Not |
|---|---|---|
| `GET /projects/{project_id}/contract` | `_VIEW` | `E14` başlığı: sözleşme + `items_total` + `advance_amount = amount × advance_pct/100` (`E14` 85) + yüklenici adı (`company` tek satırından, `E14` 73) |
| `GET /projects/{project_id}/contract/items` | `_VIEW` | Gruplar + kalemler + her kalemin `distributed_quantity`/`remaining_quantity`'si |
| `POST /projects/{project_id}/contract/groups` | `_FULL` | |
| `PATCH /contracts/employer/groups/{group_id}` | `_FULL` | |
| `DELETE /contracts/employer/groups/{group_id}` | `_ADMIN` | 409: grupta kalem varsa |
| `POST /projects/{project_id}/contract/items` | `_FULL` | 409: `(project_id, code)` çakışması |
| `PATCH /contracts/employer/items/{item_id}` | `_FULL` | 422: `quantity`, dağıtılmış toplamın altına indirilemez |
| `DELETE /contracts/employer/items/{item_id}` | `_ADMIN` | Bağlı BOQ satırlarının `contract_item_id`'si NULL olur (SET NULL); denetim günlüğüne yazılır |

**Sözleşmenin kendi alanları için YENİ yazma ucu AÇILMAZ.** `contract_no`, `amount`,
`advance_pct`, endeks vb. bugün olduğu gibi `PATCH /projects/{id}` içindeki nested
`contract` ile yazılır; bu dilim oraya yalnız `status` alanını ekler. İkinci bir
yazma yolu açmak "iki kopya kural" tuzağıdır — P1.1a doğrulaması orada duruyor.

### 6.3 Poz dağılımı (`POZ` ekranı)

`GET /projects/{project_id}/contract/distribution` → `_VIEW`

Yanıt tam olarak `POZ` ekranının gerektirdiği kadarıdır:
* `sites[]`: dağıtım kolonları (`POZ` 82-83)
* `groups[] → items[]`: her kalem için `quantity`, `unit_price`,
  `allocations[{site_id, quantity, boq_item_id}]`, `remaining_quantity` (`POZ` 84)
* `undistributed_item_count` + `undistributed_item_names[]` (`POZ` 65 uyarısı)
* `site_summaries[]` (`POZ` 168-187): şantiye başına kalem listesi ve
  `total_amount = Σ(kota × sözleşme birim fiyatı)`
* `distributed_item_count` / `total_item_count` (`POZ` 56 "8/10")

`PUT /projects/{project_id}/contract/distribution` → `_FULL` (`POZ` 24 "Dağılımı Kaydet")

Gövde: `{ allocations: [{contract_item_id, site_id, quantity}] }` — **ekranın tamamı**.

Davranış (tek işlemde **atomik**, `sites`'ın iç içe yazımı deseni):
1. `quantity` verilmeyen / `null` gönderilen (kalem, şantiye) çifti için varsa bağlı
   BOQ satırının `contract_item_id`'si NULL yapılır — **satır silinmez** (sahadaki
   iş kaydı korunur).
2. Yeni çift için hedef şantiyede BOQ satırı oluşturulur:
   `code`/`description`/`unit`/`unit_price` sözleşme kaleminden kopyalanır,
   `quantity` = kota. Grup: şantiyede sözleşme grubuyla **aynı adlı** BOQ grubu varsa
   kullanılır, yoksa o adla yeni `BoqGroup` açılır (`boq_items.group_id` NOT NULL).
3. Mevcut çiftte yalnız `quantity` güncellenir.
4. Kural: Σ kota ≤ `contract_item.quantity`, aksi hâlde 422 `DISTRIBUTION_EXCEEDS`;
   şantiye projeye ait değilse 422 `SITE_PROJECT_MISMATCH`.

**Bu dilimin en riskli ucudur** — plan onu tek başına bir task yapar.

### 6.4 Taşeron kartoteksi

`GET /subcontractors?q=&active_only=` `_VIEW` · `POST /subcontractors` `_FULL` ·
`PATCH /subcontractors/{id}` `_FULL` · `DELETE /subcontractors/{id}` `_ADMIN`
(409: sözleşmesi varsa — `SUBCONTRACTOR_HAS_CONTRACTS = "Bu taşeronun sözleşmesi var, önce sözleşmeleri silin"`).

`employers` router'ının birebir deseni.

### 6.5 Taşeron sözleşmesi

| Uç | Kapı | Not |
|---|---|---|
| `POST /projects/{project_id}/subcontractor-contracts` | `_FULL` | Kalemler **iç içe** ve atomik gönderilebilir (`sites` + bölümler deseni). `is_draft` gövdede |
| `GET /subcontractor-contracts/{id}` | `_VIEW` | `TSD` başlığı + bağlantı zinciri (47-67) + kalemler + türev toplam |
| `PATCH /subcontractor-contracts/{id}` | `_FULL` | Taslak→yayın geçişinde tüm kurallar koşar |
| `DELETE /subcontractor-contracts/{id}` | `_FULL` + serviste `can_delete` | Kapı bilerek `_FULL`'dür: `_ADMIN` olsaydı taslak istisnası **hiçbir zaman tetiklenemezdi** (kapıdan yalnız admin geçer, admin de koşulsuz siler). Yetki kararı serviste `can_delete` ile verilir → `full` kullanıcı **yalnız kendi taslağını** siler; başkasının taslağı ve yayındaki sözleşme 403. Kalıcı karar 2 korunur. (C12 incelemesi, 2026-07-31) |
| `POST /subcontractor-contracts/{id}/items` | `_FULL` | 409: `(contract_id, code)` |
| `PATCH /subcontractor-contracts/items/{item_id}` | `_FULL` | |
| `DELETE /subcontractor-contracts/items/{item_id}` | `_ADMIN` | |
| `POST /subcontractor-contracts/{id}/items/load-from-employer` | `_FULL` | `FORM` 115 / `TSD` 91 |

**`load-from-employer` davranışı:** projenin işveren sözleşmesindeki kalemleri
kopyalar — `code`/`description`/`unit`/`quantity` kopyalanır,
**`unit_price` NULL bırakılır** (taşeron fiyatını kullanıcı girer, `TSD` 82-83'ün
açık ifadesi), `source_contract_item_id` bağlanır. **Idempotent:** aynı `code`
zaten varsa atlanır, üzerine yazmaz. Yanıt `{created_count, skipped_count}`.
İşveren sözleşmesi ya da kalemi yoksa 422
`NO_EMPLOYER_ITEMS = "Bu projenin işveren sözleşmesinde poz yok"`.

---

## 7. Silme ve bağlı kayıt korkulukları

**Kalıcı karar 2 aynen:** silme = `admin` seviyesi. Tek istisna `can_delete`'in
taslak istisnasıdır (kaydı aktör açmış + hâlâ taslak + en az `draft`).

Yeni istisna sınıfı **açılmaz** — mevcut `RelatedRecordsExistError` (409) ve
`NotFoundError` (404) kullanılır.

| Silinen | Engel | Metin |
|---|---|---|
| `subcontractors` | Sözleşmesi var | `SUBCONTRACTOR_HAS_CONTRACTS` |
| `employer_contract_groups` | Grupta kalem var | `GROUP_HAS_ITEMS = "Bu grupta poz var, önce pozları silin"` |
| `sites` (mevcut uç) | **YENİ:** şantiyeye bağlı taşeron sözleşmesi var | `SITE_HAS_CONTRACTS = "Bu şantiyede taşeron sözleşmesi var, önce sözleşmeleri silin"` — `sites/guards.py`'ye eklenir; `site_id` FK'si RESTRICT olduğu için DB seviyesinde de korunur |
| `employer_contract_items` | Engel YOK | Bağlı BOQ satırları `SET NULL` ile serbest kalır |
| `projects` | Değişiklik yok | Sözleşmeler CASCADE ile gider |

Metinlerde **adet verilmez** (`BLOCK_HAS_UNITS` dersi) ve metinler eyleme dönüktür.

---

## 8. Denetim günlüğü

`app/modules/audit/messages.py`'ye eklenecek fonksiyonlar (mevcut adlandırma
deseniyle):

```
subcontractor_created / updated / deleted (name)
subcontract_created / updated / published / deleted (project_name, subcontractor_name)
subcontract_item_created / updated / deleted (contract_no, code)
subcontract_items_loaded (contract_no, count)
employer_contract_group_created / updated / deleted (project_name, name)
employer_contract_item_created / updated / deleted (project_name, code)
contract_distribution_saved (project_name, count)
```

**Okuma uçları denetim günlüğüne yazmaz** (mevcut kural).

---

## 9. Migration

Tek revizyon. Ebeveyn **varsayılmaz, doğrulanır** (`alembic heads`).

Upgrade sırası:
1. Enum'lar: `contract_status`, `payment_period`
2. `project_contracts.status` (NOT NULL, `server_default='active'`)
3. `subcontractors`
4. `employer_contract_groups`, `employer_contract_items`
5. `boq_items.contract_item_id` + kısmi benzersiz indeks
6. `subcontractor_contracts`, `subcontractor_contract_items`
7. `modules`'e `contracts` satırı + 8 `role_permissions` satırı
   (`b8a66b6fd431_boq_izin_modulu.py` deseninin birebiri)

Downgrade: ters sıra **ve `DROP TYPE contract_status`, `DROP TYPE payment_period`**.
Postgres enum'ı tabloyla silinmez; unutulursa ikinci upgrade patlar (§3 kuralı, iki
kez yaşanmış tuzak).

**Yeni kolonlarda NOT NULL yalnızca sunucu varsayılanı olanlarda** (`status`,
Boolean'lar, `advance_pct`, `retainage_pct`, `payment_period`, `payment_term_days`,
`created_by`). Kullanıcının doldurduğu hiçbir alan NOT NULL değildir — gerekçe canlı
veri değil, **taslak desteğidir**.

Migration testi **açık revizyon id'sine sabitlenir**; `head` / `-1` kullanılmaz.

---

## 10. Pydantic şemaları

`app/modules/contracts/schemas.py` (okuma/yazma ayrı, mevcut desen):

* Okuma: `ContractListResponse` · `ContractListItem` · `ContractSummary` ·
  `EmployerContractDetail` · `EmployerContractItemsResponse` ·
  `ContractDistributionResponse` · `SubcontractorResponse` · `SubcontractorListResponse` ·
  `SubcontractorContractDetail` · `SubcontractorContractItemResponse`
* Yazma: `SubcontractorCreate/Update` · `SubcontractorContractCreate/Update` ·
  `SubcontractorContractItemCreate/Update` · `EmployerContractGroupCreate/Update` ·
  `EmployerContractItemCreate/Update` · `ContractDistributionSave`

Pydantic'te duran ve `guards.py`'de **tekrarlanmayan** kurallar: ad boş olamaz,
tutarlar `>= 0`, `quantity > 0`, yüzdeler 0-100, `payment_term_days >= 0`.
İki kopya kural zamanla ayrışır.

Sunucu uzunluk sınırı olan her alan frontend'e `maxLength` ile bildirilir
(sessiz 422 sınıfı).

---

## 11. Modül yerleşimi

```
app/modules/contracts/
    __init__.py
    models.py         # 5 yeni tablo + ContractStatus, PaymentPeriod enum'ları
    schemas.py
    guards.py         # §4 kuralları + hata metinleri, TEK kopya
    repository.py
    service.py        # işveren sözleşmesi + birleşik liste
    subcontractors.py # kartoteks servisi
    subcontracts.py   # taşeron sözleşmesi servisi
    distribution.py   # §6.3 — en riskli yol, kendi dosyası
    router.py
```

`ContractStatus` `contracts/models.py`'de tanımlanır; `project_contracts`'a eklenen
`status` kolonu onu **import eder** (`projects` → `contracts` yönünde tek yönlü
bağımlılık; `sites` → `projects` deseninin aynısı). Alternatif olan "enum'u
`projects`'a koy" seçeneği ters bağımlılık üretirdi.

Dosya başına 800 satır sınırı korunur; `service.py`'nin üçe bölünmesinin sebebi budur.

---

## 12. Test planı

* **Birim:** `guards.py` kuralları (taslak / taslak-dışı çapraz tablosu) · türev
  hesaplar (`items_total`, `remaining_quantity`, `line_total`, eksik fiyatlı satır)
* **Entegrasyon:** her uç için 200/201/204 · 403 (izin yok) · 404 (yok + görünmez
  proje **ayırt edilemez**) · 409 (kod çakışması, bağlı kayıt) · 422 (zorunluluk,
  tutarlılık, kota aşımı)
* **IDOR negatif seti:** başka projenin şantiyesine kota yazma · başka projenin
  sözleşme kalemini PATCH'leme · görünmeyen projenin sözleşmesini okuma
* **Taslak:** taslak eksik alanlarla kaydedilir; yayına geçişte 422; yayındaki kayıt
  PATCH ile eksikleştirilemez
* **Dağılım:** oluştur / güncelle / bağı kaldır / aşım reddi / grup otomatik açılması
  / atomiklik (bir satır hatalıysa hiçbiri yazılmaz)
* **`load-from-employer`:** idempotentlik, `unit_price` NULL gelmesi, boş sözleşme 422
* **İzin parity:** modül sayısı **18**, izin satırı sayısı **8 × 18 = 144**;
  17'yi sabitleyen tüm testler taşınır
* **Migration:** açık revizyon id'siyle upgrade → downgrade → upgrade (yalnız yerel DB)

TDD zorunlu: önce test, **KIRMIZI GÖR**, sonra kod. İlk koşuda yeşil olan test için
mutasyon denetimi yapılır.

---

## 13. Açık kalanlar

### 13.1 Bu dilimde çözülmeyen, kullanıcıya bildirilen

* **Milestone Takvimi** (`E14` 99-122) — P11'e bırakıldı, `pending_module` ile boş döner.
* **Belgeler** (`FORM` 190-230) — kalıcı karar 8.
* **Sözleşme PDF'i** (`E14` 76, `TSD` 24) — uç yok.
* **`SZL` 37 "Toplam Hakediş" / `TSD` 103 "Hakediş %"** — P7.

### 13.2 Kullanıcıdan mockup istenecek (§3 kuralı — kod yazmadan önce)

1. **İşveren sözleşmesi poz ekleme/düzenleme formu.** `POZ` ekranı yalnız *kota*
   input'ları içeriyor (98-99); pozun kendisinin (poz no, ad, birim, miktar, sözleşme
   birim fiyatı) nereden girildiği hiçbir mockup'ta yok.
   **Backend bunu beklemeden ilerleyebilir**, çünkü alan kümesi `boq_items` ile
   birebir aynıdır ve icat gerektirmez — ancak **frontend dilimi başlamadan önce bu
   mockup istenmelidir.**
2. **Zeyilname / ek sözleşme formu** — eğer bu özellik istenirse. Şu an kapsam dışı.

---

## 14. "Bitti" tanımı

* 5 yeni tablo + 2 yeni kolon + 1 migration, upgrade/downgrade/upgrade yerel DB'de temiz
* §6'daki uçların tamamı, hepsi izin + görünürlük kapılarından geçiyor
* Modül sayısı 18, izin matrisi 144 satır, parity testleri yeşil
* `ruff` (0.15.22) + tam `pytest` koşusu yeşil
* `openapi.json` üretildi (commit edilmez, frontend'e elle kopyalanır)
* Denetim günlüğü mesajları eklendi ve testlendi
* **Push/PR/merge/deploy YAPILMAZ** — karar kullanıcıda
