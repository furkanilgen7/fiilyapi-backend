# FAT-1 — Fatura Çekirdeği (backend) · tasarım spec'i

Tarih: 2026-08-14 · Yönetim oturumu · Repo: `backend/`
Mockup otoritesi: `projedesign/Fatura Yönetimi.dc.html` (FY) ·
`projedesign/Fatura - Gelen Detay.dc.html` (FGE) ·
`projedesign/Fatura - Giden Detay.dc.html` (FGI) ·
`projedesign/Fatura - Kes.dc.html` (FK)

> ⚠️ Mockup RAKAMLARI göstermeliktir (kullanıcı kararı) — kural mockup'ın **yapısından** okunur,
> aritmetiğinden değil. Yapı / alan / etiket / ölçü BİREBİR.

---

## 1. Amaç ve kapsam

Mali zincirin (fatura → hazine → muhasebe → mali tablolar) **ilk halkası**. 17 mali mockup'ın
tamamı yazılmamış, backend'i de yok — kalan işin tek en büyük bloğu (ROADMAP-FRONTEND §0).

Bu dilim **fatura çekirdeğidir**: gelen/giden fatura başlığı + kalemleri + para hesabı +
durum makinesi + numaralandırma + liste/özet uçları.

### KAPSAM DIŞI (bilinçli sınırlar — gerekçeleriyle, "eksik" diye geri açılmaz)

| Dışarıda kalan | Gerekçe | Nereye |
|---|---|---|
| **GİB / e-Fatura entegrasyonu** (`GİB'den Çek` FY:23 · UUID/ETTN FGI:63 · Zarf No FGI:206 · GİB işlem geçmişi FGI:196-215) | Dış servis (entegratör) bağı; hiçbir mockup ayar ekranı çizmiyor, kimlik/uç bilgisi yok. **Kolonları da AÇILMAZ** — hiçbir yazma yolu olmayan kolon her zaman NULL döner, uydurma alan olur | Ayrı **FAT-3 e-Fatura** dilimi |
| **Muhasebe / yevmiye kaydı** (FGE:197-241 önizleme, hesap planı 740.01/191.01/360.01/320.05) | Hesap planı tablosu YOK; hangi masraf tipinin hangi 7xx hesabına gideceği hiçbir yerde tanımlı değil (envanter maddesi 18) | **Muhasebe** dilimi |
| **Tahsilat kaydı** (FGI:220-247 formu; `Hesap` select'i banka hesabı ister) | `bank_accounts` tablosu YOK — Hazine diliminin varlığı | **Hazine** dilimi. Bu dilimde yalnız **durum damgası** vardır (`mark-collected`, `progress_payments.mark-paid` emsali) |
| **Eşleştirme motoru** (FGE:105-143 saat karşılaştırma kartı · `Kısmi Onayla` FGE:140) | Yalnız makine/saat senaryosu çizili; taşeron ve malzeme için karşılığı YOK (envanter maddesi 19). Onay sonrası durum da çizilmemiş (madde 8) | Ayrı **FAT-2 Eşleştirme** dilimi |
| **`e-Arşiv` ve `İtiraz/İade` sekmeleri** (FY:64-65) | Sekme başlıkları var, **içerikleri hiç çizilmemiş** (madde 1) — sütun/durum bilinmiyor | Mockup gelince |
| **Sayfalama üstü toplu seçim / toplu onay** (FY) | Mockup'ta checkbox sütunu ve toplu buton YOK (madde 20) | — |
| **Para birimi seçimi / kur** | FGI:97 yalnız `TRY` **görüntülüyor**, FK formunda alan YOK, kur hiçbir yerde yok (madde 6) | TRY sabittir; çoklu para ayrı dilim |
| **`Firmayla İletişim`** (FGE:60) | Hedefi tanımsız (madde 9); bildirim altyapısı yok (SA emsali) | — |

---

## 2. Veri modeli

### 2.1 `invoices` (yeni tablo)

| Kolon | Tip | Kural / mockup dayanağı |
|---|---|---|
| `id` | UUID PK | |
| `direction` | enum `invoice_direction` = `outgoing` \| `incoming` | FGI:58 `GİDEN FATURA` (mavi) · FGE:68 `GELEN FATURA` (kırmızı) |
| `invoice_no` | String(30) **NOT NULL** | FY:111 `FIL2026000184` · FGE:72 `LT2026070184`. **Giden'de sunucu üretir** (§4), **gelen'de istemci gönderir** (satıcının kendi serisi — FY:165,174,183 üç farklı seri) |
| `document_type` | enum `invoice_document_type` = `einvoice` \| `earchive` \| `refund` \| `withholding` | FK:136-139 birebir: `e-Fatura (Satış)` · `e-Arşiv Fatura` · `İade Faturası` · `Tevkifatlı Fatura` |
| `status` | enum `invoice_status` | §3 |
| `issue_date` | Date NOT NULL, **indeksli** | FGI:94 `Fatura Tarihi` · FK:126 |
| `due_date` | Date **nullable** | FGI:68 `Vade: 18.08.2026 (24 gün)` · FK:130. "kalan gün" TÜRETİLİR, saklanmaz |
| `payment_method` | enum `invoice_payment_method` = `transfer` \| `cheque` \| `cash` \| `credit_card`, nullable | FK:145-148 birebir: `Havale / EFT` · `Çek` · `Nakit` · `Kredi Kartı` |
| `note` | Text, `FREE_TEXT_MAX_LENGTH` (2000) | FK:153 `Not / Açıklama` — TB4/B4 kanonu, `app/core/text.py` |
| **Taraf snapshot'ı** | | 🔴 §5 SNAPSHOT KANONU |
| `party_name` | String(200) NOT NULL | FGI:84 · FGE:85 · FK:104-106 |
| `party_tax_number` | String(11) **nullable** | FGI:86 `VKN: 9876543210` · FK:111 `VKN / TCKN` (TCKN 11 / VKN 10 — `customers` emsali) |
| `party_tax_office` | String(100) nullable | FGI:86 `Çankaya V.D.` · FK:115 `Vergi Dairesi` |
| `party_address` | Text nullable, 2000 | FGI:87-88 · FK:119 |
| **Taraf izi (opsiyonel FK'lar)** | | en fazla BİRİ dolu (CHECK) |
| `employer_id` | →`employers` **RESTRICT** nullable | FK:105 `Güneşkent Gayrimenkul A.Ş.` bir İŞVERENDİR (hakediş karşı tarafı) |
| `customer_id` | →`customers` **RESTRICT** nullable | ünite satışı faturası |
| `supplier_id` | →`suppliers` **RESTRICT** nullable | FY:184 `Malzeme Tedarikçi` · FGE:85 `Liebherr` (kiralama firması) |
| `subcontractor_id` | →`subcontractors` **RESTRICT** nullable | FY:166 `Taşeron` |
| **Kaynak izi (opsiyonel FK'lar)** | | en fazla BİRİ dolu (CHECK) |
| `progress_payment_id` | →`progress_payments` **RESTRICT** nullable | FGI:105 `Kaynak: İşveren Hakediş #5` · FK:88 |
| `subcontractor_progress_payment_id` | →`subcontractor_progress_payments` **RESTRICT** nullable | FY:167 `Hakediş #47 →` |
| `equipment_rental_invoice_id` | →`equipment_rental_invoices` **RESTRICT** nullable | FY:176 makine kira hakedişi (MK-2) |
| `purchase_order_id` | →`purchase_orders` **RESTRICT** nullable | FY:185 `SP-2026-042 →` · FK:71 `Siparişten` |
| `project_id` | →`projects` **CASCADE** nullable, indeksli | 🔴 **görünürlük süzgecinin kolonu** (`purchase_requests` emsali) |
| `site_id` | →`sites` **SET NULL** nullable | FGI:106 `Güneşkent Konut · A-Blok + B-Blok` bilgi alanı |
| **Para (hepsi Numeric(18,2), NOT NULL, sunucu hesaplar)** | | §5 |
| `subtotal` | | FGI:164 · FGE:177 · FK:246 `Mal/Hizmet Toplamı` |
| `advance_rate` / `advance_amount` | Numeric(5,2) nullable / Numeric(18,2) NOT NULL default 0 | FGI:168 `Avans Kesintisi (%20)` · FK:223-226 (checkbox + oran) |
| `retention_rate` / `retention_amount` | aynı | FGI:172 `Teminat Kesintisi (%5)` · FK:229-232 |
| `tax_base` | | FGI:176 · FK:248 `Vergi Matrahı` |
| `vat_amount` | | FGI:180 · FGE:181 · FK:249 `Hesaplanan KDV` |
| `withholding_rate` / `withholding_amount` | aynı | FGE:185 `Tevkifat (%20 · Yapı İşleri)` · FK:235-238 (varsayılan **İŞARETSİZ**) |
| `total` | | FGI:184 `ÖDENECEK TOPLAM` · FK:250 `Fatura Toplamı` |
| `created_by_id` | →`users` RESTRICT NOT NULL | FGI:198 `Ayşe Demir (Muhasebe)` |
| `created_at`/`updated_at` | | |

**Kısıtlar**
- `uq_invoices_no_direction` UNIQUE (`direction`, `invoice_no`) — giden seri sunucu üretimi, gelen
  seri satıcıya ait; ikisi çakışabilir, **yön içinde** benzersizdir.
- `ck_invoices_single_party`: `employer_id`+`customer_id`+`supplier_id`+`subcontractor_id`
  dolu sayısı **≤ 1**.
- `ck_invoices_single_source`: dört kaynak FK'sının dolu sayısı **≤ 1**.
- `ck_invoices_amounts_non_negative`: `subtotal`, `advance_amount`, `retention_amount`,
  `vat_amount`, `withholding_amount`, `total` ≥ 0.
- Oranlar (`*_rate`) `CHECK BETWEEN 0 AND 100`.
- İndeks: `ix_invoices_issue_date`, `ix_invoices_project_id`, `ix_invoices_status`.

### 2.2 `invoice_lines` (yeni tablo)

| Kolon | Tip | Mockup |
|---|---|---|
| `id` | UUID PK | |
| `invoice_id` | →`invoices` **CASCADE** | |
| `sort_order` | Integer NOT NULL | FGI:116 `Sıra` sütunu (mono, 60px). 🔴 **SA/T3 dersi:** sırasız liste kullanıcı girdisini karıştırır |
| `description` | Text NOT NULL, 2000 | FGI:117 · FGE:150 · FK:168 `Açıklama`. **Poz AYRI ALAN DEĞİLDİR** — FK:178 açıklamaya gömüyor (`… (Poz 03.001)`), envanter maddesi 14 |
| `unit` | String(20) **nullable** | FGI:118 `m³`/`Ton`/`m²` · FGE:151 `Saat` · FK:169 **serbest metin input** — enum YOK (madde 15) |
| `quantity` | Numeric(14,3) NOT NULL, **CHECK > 0** | `purchase_request_lines` emsali |
| `unit_price` | Numeric(18,2) NOT NULL, CHECK ≥ 0 | FGI:120 `Birim Fiyat` |
| `vat_rate` | Numeric(5,2) NOT NULL, CHECK 0..100 | FGI:121 · FGE:154 · FK:172 `KDV %` — 🔴 **SATIR BAZINDA** |
| `line_total` | Numeric(18,2) NOT NULL | FK:183 `Tutar` **salt okunur hesaplanan** → sunucu yazar |
| `detail_note` | String(200) nullable | FGI:127 alt satırı (`Poz 03.001 · Fiyat farkı katsayısı: 1,142`) · FGE:159 (`Temmuz 2026 · Güneşkent A-Blok`). Kaynaktan kopyalanan **serbest metin snapshot'ı** |

**İskonto sütunu AÇILMAZ** — üç kalem tablosunun hiçbirinde çizili değil.

---

## 3. Durum makinesi — TEK kaynak `invoicing/transitions.py`

Uçlar/servis kendi `if status == …` denetimini **YAZMAZ**; matris dışı her geçiş **409**.
Yön dışı geçiş de **409** (giden faturaya `approve` atılamaz).

### Giden (`outgoing`)
```
draft ──send──▶ sent ──mark-collected──▶ collected
```
- `draft` (FK:24 `Taslak Kaydet`) · `sent` (FK:25 `GİB'e Gönder`) · `collected` (FY:130 `Tahsil Edildi`)
- **İptal/iade geçişi YOKTUR** — FGI'de iptal aksiyonu çizilmemiş. `draft` fatura **silinebilir**
  (§6 izin).

**K1 — "Vadeli" AYRI BİR DURUM DEĞİLDİR (onaylı sapma).** FY:91 filtresi `Gönderildi` ve `Vadeli`
seçeneklerini yan yana sunar ama FY'de `Gönderildi` rozeti taşıyan **tek satır yoktur**; `Vadeli`
(FY:119) ile `Tahsil Edildi` (FY:130) satır rozetleridir. Envanter maddesi 3 bu tutarsızlığı
işaretledi. **Karar: `sent` tek durumdur; ekran etiketi `due_date` doluysa "Vadeli", boşsa
"Gönderildi"dir.** `status` süzgeci üç değeri alır; frontend "Vadeli" seçeneğini `sent`e eşler.
Gerekçe: ikisi ayrı durum değil, aynı durumun iki gösterimidir — türetilebilen SAKLANMAZ.

### Gelen (`incoming`)
```
pending ──approve──▶ approved
   └────dispute────▶ disputed
```
- `pending` (FGE:70 `Onay Bekliyor`) · `approved` (FGE:25 `Onayla & Muhasebeleştir`) ·
  `disputed` (FGE:24 `İtiraz Et` → FY:65 `İtiraz/İade` sekmesi)
- **`approved` sonrası ödeme durumu YOKTUR** — Hazine dilimi.
- **`Kısmi Onayla` (FGE:140) AÇILMAZ** — etkisi çizilmemiş (madde 8), FAT-2'nin işi.

**K2 — `draft` yalnız giden tarafta vardır.** Gelen fatura sisteme zaten kesilmiş olarak girer
(FGE:69 `GİB'den Geldi ✓`); taslak gelen fatura mockup'ta hiç yoktur.

---

## 4. Numaralandırma — `invoicing/numbering.py`

`procurement/numbering.py` deseninden **BİREBİR** (advisory xact lock; docstring'i oku).

- Biçim: **`FIL` + yıl + 6 hane sıfır dolgulu**, ayraçsız → `FIL2026000184` (FY:111, FGI:62).
  ⚠️ `SAT-2026-0001`ten farklı olarak **tire YOKTUR ve genişlik 6'dır** — mockup böyle çiziyor.
- **Yalnız `direction=outgoing` için üretilir.** Gelen faturada `invoice_no` **istemciden gelir ve
  ZORUNLUDUR** (satıcının serisi — FY:165/174/183 üç ayrı seri kökü).
- İstemci giden faturada `invoice_no` **GÖNDEREMEZ** (gönderirse 422) — SA kanonu.
- Kilit anahtarı yeni ve sabit: `_INVOICE_LOCK_KEY = 82601` (82501/82502 SA'nın, çakışmaz).
- `SEQUENCE_WIDTH = 6` **en az** genişliktir, tavan değil.
- Seri kökü (`FIL`) hiçbir ayar ekranında çizilmemiş (madde 5) → **modül sabiti**, ayar YAPILMAZ.

---

## 5. 🔴 PARA HESABI — tek kaynak `invoicing/amounts.py`

**Hiçbir uç/servis kendi toplamını hesaplamaz.** Hesap sırası FGI:163-186 + FK:246-250 tfoot
sırasından BİREBİR:

```
1. subtotal   = Σ line_total          (line_total = quantity × unit_price, satır bazında yuvarlanır)
2. advance_amount   = round(subtotal × advance_rate   / 100)
3. retention_amount = round(subtotal × retention_rate / 100)
4. tax_base   = subtotal − advance_amount − retention_amount
5. vat_amount = Σ_satır  round( pay_satır × vat_rate_satır / 100 )
6. withholding_amount = round(vat_amount × withholding_rate / 100)
7. total      = tax_base + vat_amount − withholding_amount
```

**K3 — çok oranlı KDV, kesintiye ORANTILI dağıtılır.** Mockup tek `%20` çiziyor (FGI:180) ama
kalem tablosu `KDV %`yi **satır bazında** taşıyor (FGI:121). Kesintiler başlık düzeyindedir →
5. adımdaki `pay_satır` = `line_total × (tax_base / subtotal)`. `subtotal = 0` ise KDV = 0
(sıfıra bölme yok). Tek oranlı faturada sonuç mockup'la birebir aynıdır (matematiksel olarak
kanıtlanır, testlenir).

**K4 — tevkifat matrahı KDV'dir.** FGE:181→185: `20.752` KDV, `– 4.150` tevkifat ≈ KDV × %20.
Rakam göstermelik ama **yapı** (tevkifatın KDV'den düşülmesi) mockup'tan okunur. Tevkifat
`total`dan DÜŞÜLÜR (FGE tfoot sırası).

**K5 — yuvarlama:** her ara adım `Decimal` `ROUND_HALF_UP` ile 2 haneye. Kayan nokta KULLANILMAZ.

**K6 — sıfır kalem = sıfır tutar, ama `send`/`approve` KAPISI kalemsiz faturayı REDDEDER (422).**
NULL-EŞİK kanonunun (SA dersi) kardeşi: "kalem yok" ile "tutar sıfır" aynı 0'ı üretmemeli.

### 🔴 K7 — N-ÇARPANLI SNAPSHOT KANONU (MK-2→MK-3 dersi, WORKFLOW §4)

> *Bir türev para değeri N çarpandan oluşuyorsa, snapshot iddiası N'in **HEPSİNİ** kapsamalıdır.*

Faturanın `total`ını üreten çarpanların **TAMAMI** fatura satırlarında/başlığında **DONMUŞ**tur ve
hiçbiri kaynaktan (hakediş/sözleşme/ekipman/cari kartı) **CANLI OKUNMAZ**:

| Çarpan | Nerede donuyor |
|---|---|
| miktar · birim fiyat · KDV oranı | `invoice_lines` (satır başına) |
| avans oranı · teminat oranı · tevkifat oranı | `invoices` başlık kolonları |
| taraf ünvanı · VKN · vergi dairesi · adres | `invoices.party_*` snapshot'ı |
| hesaplanan her ara toplam | `invoices` para kolonları (**saklanır**, okumada yeniden hesaplanmaz) |

**Kanıt zorunluluğu (T-son sınıf araması):** kaynak kayıt (hakediş tutarı, ekipman saat ücreti,
cari ünvanı) değiştirilir → **`sent`/`approved` faturanın hiçbir alanı DEĞİŞMEZ** testi yazılır.
`draft` fatura da değişmez (kopyalama yazma anında olur), ama `PUT lines` ile elle güncellenebilir.

---

## 6. İzin ve görünürlük

- **Modül `invoicing` ZATEN AÇIK** (`roles/seed_data.py:102`, grup MALI, `sort_order: 13`).
  🔴 **YENİ İZİN MODÜLÜ AÇILMAZ**, matris satırına **DOKUNULMAZ**:
  `"invoicing": [_A, _F, _N, _N, _N, _F, _V, _N]` — sysadmin admin · patron full · şef/saha/İK yok ·
  **muhasebe full** · PM görüntüle · satınalma yok. Migration'da izin satırı YOKTUR.
- Silme (`DELETE`) yalnız `admin` (yani `system_admin`) — `full` silmeyi kapsamaz (repo kanonu).
- **Görünürlük (IDOR):** `project_id` üzerinden `user_project_access` süzgeci (`purchase_requests`
  emsali). `project_id` NULL fatura (şirket geneli) **yalnız modül izni** ile görünür.
- Görünmeyen kayıt → **404** (var olmayanla ayırt edilemez — repo kanonu).
- Gövde içi varlık referansı (`employer_id`, `progress_payment_id`, …) görünmüyorsa → **404**
  (ST kanonu), 403 değil.

---

## 7. Uçlar (11 yol)

| # | Uç | İzin | Not |
|---|---|---|---|
| 1 | `GET /invoices` | view | Süzgeçler: `direction` · `status` · `project_id` · `site_id` · `q` (fatura no + taraf adı, FY:94 `Fatura ara...`) · `date_from`/`date_to`. **`limit` varsayılan 50, `le=200` → tavan aşımı 422** (TB3/T2 kanonu) + `offset` + `total`. Zarf `{items, total, limit, offset}` |
| 2 | `GET /invoices/summary` | view | FY:69-75 beş KPI: `issued_this_month` (tutar+adet) · `received_this_month` (tutar+adet) · `receivable` (tutar+adet, `sent`) · `vat_difference` (giden KDV − gelen KDV) · `pending_approval` (**adet**, gelen `pending`). Ay = `DISPLAY_TIMEZONE`de içinde bulunulan ay |
| 3 | `POST /invoices` | full | Başlık + `lines[]` **tek gövdede**. `direction` zorunlu. Giden → `draft`, gelen → `pending` (K2) |
| 4 | `GET /invoices/{id}` | view | Kalemler + hesaplanmış toplamlar |
| 5 | `PATCH /invoices/{id}` | full | **Yalnız `draft`** (giden) — başka durumda 409. Gelen fatura PATCH'i **yalnız `pending`** ve yalnız `note`/`due_date`/`payment_method` |
| 6 | `DELETE /invoices/{id}` | **admin** | Yalnız `draft` → 204; başka durum 409 |
| 7 | `PUT /invoices/{id}/lines` | full | Kalem kümesini **toptan** yazar (hakediş/puantaj emsali). Yalnız `draft`. Gövdeden `line_total`/`sort_order` **hesaplanır/atanır**, istemci `line_total` GÖNDEREMEZ |
| 8 | `POST /invoices/{id}/send` | full | `draft → sent`. K6 kapısı |
| 9 | `POST /invoices/{id}/mark-collected` | full | `sent → collected` |
| 10 | `POST /invoices/{id}/approve` | full | `pending → approved`. K6 kapısı |
| 11 | `POST /invoices/{id}/dispute` | full | `pending → disputed` |

Hepsi audit'lenir (`AuditAction` mevcut üyeleri kullanılır — **yeni enum üyesi AÇILMAZ**, gerçek
Postgres enum tipi migration ister; TB3/T3 kanonu. Ayrım `messages.*` metninden yapılır).

---

## 8. 🔴 EŞİK = KİLİT (WORKFLOW §4 kanonu, İK-2 dersi)

Durum geçişi ve numara üretimi eşzamanlı iki istekte **her ikisini de geçirmemelidir**.

1. **Numaralandırma:** advisory xact lock (§4) — SA'da kanıtlanmış desen.
2. **Durum geçişleri (8-11) + `PUT lines` + `PATCH`:** fatura satırı **`with_for_update` +
   `populate_existing`** ile kilitlenir, kilit **denetimlerden ÖNCE** alınır (TOCTOU).
   Kilitsiz hâlde iki eşzamanlı `send` iki numara/iki audit üretebilir.
3. **Regresyon testi İKİ GERÇEK BAĞLANTIYLA** yazılır ve **kilit kaldırılınca KIRMIZI olduğu
   KANITLANIR** (İK-2/İK-3 emsali; tek istekli test bunu ASLA görmez).
4. Kilit sırası tüm uçlarda SABİT: fatura → kalemler.

---

## 9. Modül dosya düzeni (`app/modules/invoicing/`)

`procurement` emsali; **hiçbir dosya 800 satırı geçmez** (SA'nın 973 satırlık `service.py`'si
açık borç olarak kayıtlı — tekrarlanmaz):

```
models.py · schemas.py · repository.py · service.py · router.py
transitions.py   (§3 tek kaynak)
amounts.py       (§5 tek kaynak)
numbering.py     (§4)
validation.py    (K6 + gövde kuralları)
summary.py       (uç 2)
```

- `alembic/env.py`'ye **`invoicing` modülü EKLENİR** (TB1 kanonu — yoksa autogenerate tabloları
  "silinecek" sanır) **ve `tests/conftest.py`'ye de** (env.py tek başına YETMEZ, SD dersi).
- `app/main.py`'ye router eklenir. **Sıra tuzağı:** `/invoices/summary` iki segmentlidir ve
  `/invoices/{invoice_id}` (UUID) ile çakışır → `summary` rotası **router içinde `{invoice_id}`
  rotasından ÖNCE** tanımlanır (MK-2 dersi, `main.py:94-104`).

---

## 10. Migration

- Yeni revizyon, **ebeveyn `a0b1c2d3e4f5`** (MK-3, 2026-08-14 itibarıyla `origin/main` tek head'i —
  doğrulandı).
- 🔴 **Merge'den ÖNCE `origin/main` alembic head'i SON KEZ kontrol edilir**; arada başka bir dilim
  merge edilmişse **re-parent ŞART** ve testteki **açık revizyon sabiti de birlikte** güncellenir
  (tek satır YETMEZ — P8/TH'de iki kez gerekti). Çift head → `Dockerfile:22` `upgrade head`
  "multiple heads" ile çıkar → **uvicorn hiç başlamaz, tam kesinti**.
- Migration testinde `head`/`-1` KULLANILMAZ — açık revizyon id'si.
- Üç yeni Postgres enum tipi (`invoice_direction`, `invoice_document_type`, `invoice_status`,
  `invoice_payment_method` → dört) → **downgrade'de `DROP TYPE` unutulmaz**.

---

## 11. Açık sorular (yönetim bağladı, kullanıcıya SORULMADI)

| # | Soru | Bağlanan cevap | Dayanak |
|---|---|---|---|
| S1 | "Vadeli" ayrı durum mu? | Hayır — `sent`in gösterimi | K1 |
| S2 | Poz ayrı alan mı? | Hayır — açıklamaya gömülü serbest metin | FK:178, envanter md.14 |
| S3 | Birim enum mu? | Hayır — serbest metin | FK:169, envanter md.15 |
| S4 | Taraf tek tablo mu? | Hayır — **snapshot ZORUNLU + dört opsiyonel FK** | K7 |
| S5 | Gelen fatura numarasını kim verir? | İstemci (satıcının serisi), giden'de sunucu | FY:165/174/183 |
| S6 | Çok oranlı KDV nasıl? | Kesintiye orantılı dağıtım | K3 |
| S7 | Tevkifat matrahı? | KDV | K4 |
| S8 | Yeni izin modülü? | **HAYIR — `invoicing` zaten var** | seed_data.py:102 |

> Para/veri-kaybı sınıfı yeni bir karar ÇIKMADI: mockup'ın aritmetiği göstermelik sayıldığı için
> (kullanıcı kararı) oran/matrah tercihleri **yapıdan** okundu. Bir sonraki dilimde (Hazine)
> kısmi tahsilat modeli kullanıcıya sorulacaktır — bu dilimde tahsilat yoktur.
