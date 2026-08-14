# MK-2 — Kira Hakedişi + Ekipman Belgeleri (backend)

Tarih: 2026-08-14 · Repo: `backend/` · Dal: `feat/mk2-kira-hakedisi`
Yönetim oturumu yazdı. Öncülü: `2026-08-13-mk1-makine-cekirdegi-design.md` (§9 devir listesi).

Mockup: **M5** `Makine - Kira Hakedişi.dc.html` · **M2** `Form - Makine Ekle.dc.html:128-162`
(belge slotları).

---

## 0. 🔴 MOCKUP RAKAMLARI GÖSTERMELİKTİR (kullanıcı kararı, 2026-08-14)

MK-1 spec'i M5'in aritmetiğindeki tutarsızlığı (₺122.496 = ₺102.080 × 1,20, üstüne yine %20 KDV)
**çift KDV şüphesi** diye yönetime taşımıştı. **Kullanıcı kararı: mockup'taki sayılar yalnız
görsel doldurmadır, iş kuralı kanıtı DEĞİLDİR.** Bu yüzden:

- **Kural mockup'ın SAYILARINDAN değil, YAPISINDAN (alan/sütun/etiket/durum) okunur.**
- Aynı ayrım MK-1'de zaten uygulanmıştı: M3'ün tfoot'u kendi satırlarıyla tutarsızdı ve
  **satır kazandı** (K15). MK-2 aynı ilkeyi sürdürür.
- ⚠️ **Ama sayıdan türetilmiş MK-1 sabitleri geçerliliğini KORUR** (`DAILY_HOURS = 10`,
  `monthly_capacity_hours = 200`): onlar tek bir hücreden değil, **dört-beş bağımsız satırda
  birbirini doğrulayan** örüntülerden çıkarılmıştı ve zaten canlıda. Yeniden türetilmez.

---

## 1. Kapsam

1. **Kira hakedişi** (M5): kiralama firmasından **GELEN** faturanın, çalışma kaydından
   hesaplanan saatlerle doğrulanması + ödenecek tutarın çıkarılması.
2. **Ekipman belgeleri** (M2:128-162): MK-1'de mockup eksiği yüzünden ertelenmişti.

**Kapsam dışı:** Bakım Takvimi (mockup YOK) · çalışma/yakıt giriş formları (mockup YOK, uçları
MK-1'de zaten açık) · muhasebe/sabit kıymet entegrasyonu (modül yok).

---

## 2. Tablolar

### 2.1 `equipment_rental_invoices` (M5 başlığı)

| Kolon | Tip | Not |
|---|---|---|
| `id` | UUID PK | |
| `supplier_id` | FK→`suppliers` **RESTRICT** | M5:50-55; 🔴 mali iz |
| `invoice_no` | String, nullable | M5:59 |
| `invoice_amount` | Numeric(18,2), nullable | M5:63 — **firmanın kestiği tutar, KDV HARİÇ** (K1) |
| `period_year` / `period_month` | Integer **NOT NULL** | M5:72 |
| `site_id` | FK→`sites` **SET NULL**, nullable | M5:73 (`Tüm Projeler` = NULL) |
| `rate_period` | enum `equipment_rate_period` **NOT NULL** | M5:74 — MK-1'in tipi YENİDEN KULLANILIR |
| `vat_rate` | Numeric(5,2) **NOT NULL**, default `20.00` | K1 (oran VERİDİR, koda gömülmez) |
| `status` | enum `rental_invoice_status` **NOT NULL** | K5, varsayılan `draft` |
| `approved_by_id` / `approved_at` / `paid_at` | | İK-3 dönem deseni |
| standart damgalar | | |

**UQ `(supplier_id, invoice_no)`** — `invoice_no` NULL iken NULLS DISTINCT (taslakta çok NULL
serbest, `personnel.tc_no` emsali). Aynı faturayı iki kez ödemeyi yapısal olarak engeller.

### 2.2 `equipment_rental_invoice_lines`

| Kolon | Tip | Not |
|---|---|---|
| `id` | UUID PK | |
| `invoice_id` | FK→…invoices **CASCADE** | |
| `equipment_id` | FK→`equipment` **RESTRICT** | |
| `line_kind` | enum `rental_line_kind` **NOT NULL** | `rented` · `owned` · `breakdown` (K3) |
| `worked_hours` | Numeric(8,2) **NOT NULL** | çalışma kaydından **SNAPSHOT** (K2) |
| `breakdown_hours` | Numeric(8,2) **NOT NULL**, default 0 | M5:92 |
| `rate_amount` | Numeric(18,2), nullable | M5:93 **düzenlenebilir**; boşsa maliyet `null` |
| `invoiced_hours` | Numeric(8,2), nullable | M5:95 **düzenlenebilir**; firmanın iddia ettiği saat |
| standart damgalar | | |

`our_amount` **KOLON DEĞİLDİR** — türetilir (§3 K4).
**UQ `(invoice_id, equipment_id, line_kind)`** — aynı makine hem `rented` hem `breakdown` satırı
taşıyabilir (M5 ikisini ayrı satır çiziyor), ama aynı türden iki satır taşıyamaz.

### 2.3 `equipment_document_types` (SEED 6) + `equipment_documents`

M2:134-159'un altı slotu, **İK-1 `personnel_document_types` / `personnel_documents` deseninin
birebiri**: `code` · `name` · `is_required` · `sort_order`.
SEED: `invoice_or_contract` (zorunlu) · `periodic_inspection` (zorunlu) · `ce_certificate` ·
`manual` · `insurance_policy` · `delivery_photos`.

`equipment_documents`: →`equipment` **CASCADE** · →`equipment_document_types` **RESTRICT** ·
dosya alanları (İK-1'in `personnel_documents` şeması birebir) · **`valid_until` Date, nullable**
(K7 — onaylı sapma).

---

## 3. Bağlanan kararlar

**K1 — 🔴 KDV: `invoice_amount` KDV HARİÇ matrahtır.** `vat_amount = invoice_amount × vat_rate/100`,
`payable_total = invoice_amount + vat_amount`. Mockup'ın ₺122.496'sı **kullanılmaz** (§0).
`vat_rate` **kolondur, sabit değil** — oran mevzuatla değişir ve geçmiş fatura kendi oranıyla
okunabilir kalmalıdır (İK-3'ün `payroll_rates` dersi: oran koda gömülürse geçmiş geriye dönük oynar).

**K2 — 🔴 `worked_hours` SNAPSHOT'tır, canlı sorgu DEĞİL.** Satır kurulurken çalışma kaydından
okunur ve **kopyalanır**. Gerekçe: fatura onaylandıktan sonra biri geçmiş bir çalışma kaydını
düzeltirse, onaylanmış bir ödemenin dayanağı sessizce değişirdi. (İK-3 `personnel_source`
snapshot'ı ile aynı ilke.) Tazeleme ayrı ve **açık** bir eylemdir → `POST …/reload`, yalnız `draft`ta.

**K3 — `line_kind` üç değerlidir ve ÖDENECEĞE KATILIM buradan okunur.**
- `rented` → **ödenecek toplama GİRER**
- `owned` → görünür, maliyeti raporlanır, **toplama GİRMEZ** (M5:140-151 "Kendi", tfoot'a katılmıyor)
- `breakdown` → görünür, tutarı **hariç tutulan** olarak raporlanır, **toplama GİRMEZ**
  (M5:128-139 üstü çizili)
🔴 **Çift ödeme yapısal olarak imkânsızdır** — `owned`/`breakdown` hiçbir toplamın kaynağı
değildir (İK-3 K2'nin `excluded` deseni birebir).

**K4 — Para TEK FORMÜLDEN türer, kolonlaşmaz.**
`our_amount = worked_hours × saatlik_bedel`; **saatlik bedel MK-1'in `cost.py`sinden İTHAL
EDİLİR**, MK-2'de yeniden tanımlanmaz (`rate_period` dönüşümü + `DAILY_HOURS = 10` orada yaşıyor).
Satırın `rate_amount`ı doluysa o, boşsa ekipmanın kendi bedeli; ikisi de yoksa **`null`**
(MK-1 K16 fail-closed), 0 DEĞİL. Toplamlar **satırlardan** türer (MK-1 K15).

**K5 — Durum makinesi (dört değer):** `draft` → `pending_verification` → `approved` → `paid`.
- `draft`: her şey düzenlenebilir, `reload` serbest.
- `pending_verification` (M5:65 "Doğrulama Bekliyor"): satır düzenlenebilir, `reload` **kapalı** (K2).
- `approved`: **hiçbir şey düzenlenemez** (409). Reddetme = `approved → pending_verification`
  (ayrı `rejected` durumu YOK — İK-3'ün red deseni).
- `paid`: uç damgası, ikinci çağrı **409**.
🔴 `approved`/`paid` faturanın satırına PATCH → **409** (İK-3 S5 emsali).
M5:27'deki "Kiracıya Gönder" etiketi **akış yönüyle çelişir** (gelen faturayı biz ödüyoruz) →
eylem adı **"Onayla ve Ödemeye Gönder"**; **onaylı sapma**, ROADMAP'e yazılır.

**K6 — Fark tespiti bir DURUM değil, TÜREV alandır.**
`hours_variance = invoiced_hours − worked_hours` (ikisi de doluysa; değilse `null`).
Rozet sunucudan gelir (`variance_status`: `match` / `over` / `under` / `unknown`) — F-P10
"rozet sunucu damgasıdır" kanonu. **Fark ödemeyi BLOKE ETMEZ** (mockup bir çözüm akışı çizmiyor);
yalnız görünür kılınır. Onay, farkın kullanıcı tarafından kabulüdür.

**K7 — `valid_until` EKLENİR (onaylı sapma).** Mockup belge slotunda tarih alanı çizmiyor ama
"Periyodik Muayene · İSG mevzuatı · **Yıllık zorunlu**" (M2:139) ve "Sigorta Poliçesi" (M2:154)
süreli belgelerdir; tarihsiz saklanan bir muayene, süresi dolduğunda da "var" görünür — **güvenlik
yüzeyi**. Alan **nullable**dır (zorunlu kılınmaz, mockup çizmiyor).
`GET …/documents/summary` `expiring_soon` (30 gün) + `expired` sayar — İK-1'in
`/hr/documents/summary` deseni.

**K8 — Bir fatura TEK tedarikçiye aittir.** `rented` satırların ekipmanı, faturanın
`supplier_id`siyle **eşleşmek zorundadır** (ihlal **422**). `owned` satırlarda tedarikçi aranmaz.
(M5 tablosu iki marka karıştırıyor ama **marka ≠ tedarikçi** — MK-1 K1/K3'te ayrılmıştı.)

**K9 — `visible_projects` süzgeci uygulanır** (MK-1 K20 ile aynı); `site_id IS NULL` fatura
herkese görünür.

**K10 — `Decimal`, asla `float`; para tam sayıya ROUND_HALF_UP** (MK-1 K19 birebir).

---

## 4. Uçlar

İzin anahtarı **`equipment`** (MK-1'de açıldı, **yeni modül AÇILMAZ** — `payroll`/İK-3 emsali).
Okuma `view`, yazma `full`. Görünmeyen kayıt → **404**.

**Fatura:** `GET /equipment/rental-invoices` (sayfalamalı, `limit ≤ 200`) · `POST` ·
`GET /{id}` (M5 tamamı) · `PATCH /{id}` (K5 kapıları) · `POST /{id}/reload` (yalnız `draft`) ·
`POST /{id}/approve` · `POST /{id}/pay` · `POST /{id}/reject`.
**Satır:** `PATCH /rental-invoice-lines/{id}` (yalnız `rate_amount` + `invoiced_hours`) ·
`DELETE` (yalnız `draft`).
**Yanıt toplamları (K4'ten türetilir):** `our_total` · `invoice_amount` · `vat_amount` ·
`payable_total` · `excluded_breakdown_amount` · `owned_total` + **proje bazlı dağılım**
(M5:177-193, satırların `site_id`sinden — MK-1 K9: kaydın kendi şantiyesi).

**Belgeler:** `GET /equipment/document-types` · `GET /equipment/{id}/documents` ·
`POST /equipment/{id}/documents` (multipart) · `GET /equipment/documents/{id}/download` ·
`DELETE /equipment/documents/{id}` · `GET /equipment/documents/summary` (K7).

---

## 5. Enum'lar (ikisi de YENİ; downgrade'de ikisi de `DROP TYPE`)

| Tip | Değerler |
|---|---|
| `rental_invoice_status` | `draft` · `pending_verification` · `approved` · `paid` |
| `rental_line_kind` | `rented` · `owned` · `breakdown` |

`equipment_rate_period` **YENİDEN TANIMLANMAZ** — MK-1'in tipi import edilir (DB tipi TEK;
`worker_source` dersi).

---

## 6. Tuzaklar

- 🔴 `down_revision` = **`d7e8f9a0b1c2`** (MK-1, canlı head). `alembic heads` **TEK satır**.
- 🔴 Downgrade **iki yeni enum'u** düşürür; `equipment_rate_period`e **DOKUNMAZ** (MK-1'in malı).
- 🔴 **PG sürüm tuzağı:** yerel 18 / CI 16 — RESTRICT ihlali `23001` ↔ `23503`; dar tuple.
- 🔴 MK-1'in `cost.py`si **import edilir**, kopyalanmaz (K4).
- İzin modülü **YENİDEN AÇILMAZ** — `equipment` var; izin migration'ı YOK.
- 🔴 Belge yükleme: BC/İK-1'in dosya saklama deseni (bytea + tip/boyut doğrulaması + `nosniff`)
  birebir izlenir; yeni saklama yolu İCAT EDİLMEZ.

---

## 7. Kabul kriterleri

1. İki fatura tablosu + iki belge tablosu + iki enum + migration; `upgrade`/`downgrade` turu testli.
2. **K1** KDV zinciri testli (`vat_rate` kolonundan, sabitten değil).
3. **K2** snapshot: satır kurulduktan sonra çalışma kaydı değişince fatura toplamı **DEĞİŞMEZ** — testli.
4. **K3** çift ödeme imkânsızlığı: `owned`/`breakdown` hiçbir toplamın kaynağı değil — testli.
5. **K5** geçiş tablosu mutasyonla testli; `approved` satır PATCH'i 409.
6. **K8** tedarikçi eşleşmesi 422; **K9** görünürlük süzgeci testli.
7. **K7** `expiring_soon`/`expired` sayaçları testli.
8. TDD: önce test, KIRMIZI GÖR. `ruff check .` + `ruff format --check .` tüm repo temiz.
9. Testler yalnız yerel DB'de (`TEST_DATABASE_URL` override) — canlıya DOKUNULMAZ.
