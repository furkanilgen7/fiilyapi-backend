# HZ-1 — Hazine Çekirdeği (backend) · tasarım spec'i

Tarih: 2026-08-14 · Yönetim oturumu · Repo: `backend/`
Ön koşul: **FAT-1 merge edilmiş olmalı** (`invoices` + `invoice_lines` tabloları).

Mockup otoritesi:
`projedesign/Ekran 9 - Hazine.dc.html` (E9) · `Ekran 10 - Finans Çek Ödeme.dc.html` (E10) ·
🔑 `projedesign/Fatura - Giden Detay.dc.html` (FGI) — **tahsilat formu burada çizili**, E9'da değil.

> ⚠️ Mockup RAKAMLARI göstermeliktir. Yapı / alan / etiket / ölçü BİREBİR.

---

## 1. Bu dilimin sınırı — mockup'ın ÇİZMEDİĞİ yer çok geniş

E9 ve E10 birlikte **131 + 166 satır**; ikisinde de **hiç form, hiç filtre, hiç satır aksiyonu,
hiç sayfalama yok**. Bu yüzden kapsam **mockup'ın gerçekten çizdiği yüzeyle** sınırlıdır.

### KAPSAM İÇİ (hepsi çizili)
| Ne | Nerede çizili |
|---|---|
| Banka hesabı kartı (4 alan) | E9:70-84 |
| **Tahsilat/ödeme kaydı formu (5 alan)** | **FGI:220-247** — asıl dayanak |
| Yaklaşan Ödemeler (7 gün, 5 alan) | E9:109-125 |
| Nakit akışı özeti (2 toplam + seri) | E9:90-106 |

### KAPSAM DIŞI (bilinçli sınırlar — gerekçeli, "eksik" diye geri açılmaz)
| Dışarıda | Gerekçe | Nereye |
|---|---|---|
| **Çek / Senet** (E10 tamamı) | 🔴 Durum **geçişlerinin hiçbiri çizilmemiş** (satır aksiyonu, aksiyon sütunu bile yok) · `Verilen Çekler` ve `Senetler` sekmelerinin **içeriği hiç çizilmemiş** (verilen çekte `Keşideci` sütunu anlamsız, lehtar alanı yok) · **`Karşılıksız` kelimesi mockup'ta HİÇ GEÇMİYOR** — inşaat ERP'sinde çekin en kritik durumu. Durum makinesi uydurulamaz | **HZ-2**, mockup eki gelince |
| **Nakit hareket (işlem) tablosu** | Hiç çizilmemiş. Yön/tarih/tutar yalnız **toplam** düzeyinde (E9:103-104) ve Yaklaşan Ödemeler metninde görünüyor; açıklama/kategori/dekont alanları yok | **HZ-3** |
| **`+ Ödeme Planla`** (E9:65) | Butonun hedefi tanımsız — ne form, ne modal, ne alan kümesi var. "Planlanan ödeme" ayrı bir varlık mı belli değil | mockup gelince |
| Bakiye bileşenleri (kullanılabilir/bloke) | E9 tek rakam basıyor, ayrım yok | — |
| Para birimi / kur | `₺` her yerde metne gömülü sabit; seçici/kolon/kur yok | çoklu para ayrı dilim |
| Toplam nakit KPI'ı | HTML yorumu `<!-- Toplam + nakit akışı -->` "Toplam" diyor ama **kart çizilmemiş** (E9:87) | — |
| Şube / hesap no / SWIFT / kart rengi | çizilmemiş | — |

---

## 2. Veri modeli

### 2.1 `bank_accounts`

| Kolon | Tip | Kural / dayanak |
|---|---|---|
| `id` | UUID PK | |
| `bank_name` | String(100) NOT NULL | E9:71,76,81 `Ziraat Bank` · `İş Bank` · `Yapı Kredi` |
| `account_type` | enum `bank_account_type` = `checking` \| `cash` | E9:71,81 — **yalnız `Vadesiz` ve `Kasa` çizili.** `Vadeli`/`Kredi`/`POS`/`Döviz` **İCAT EDİLMEZ** (K1) |
| `iban` | String(34) nullable | E9:73,78. **Kasa tipinde YOK** (E9:83) |
| `display_name` | String(100) nullable | E9:83 `Merkez Kasa` — Kasa'da IBAN yerine bu basılır |
| `opening_balance` | Numeric(18,2) NOT NULL default 0 | K2 — bakiye SAKLANMAZ, açılıştan TÜRETİLİR |
| `is_active` | Boolean NOT NULL default true | DELETE ucu YOK (repo kanonu: `is_active=false`) |
| `created_at`/`updated_at` | | |

**Kısıt:** `uq_bank_accounts_iban` UNIQUE **kısmi indeks** (`WHERE iban IS NOT NULL`) — Kasa
satırlarının NULL IBAN'ı çoklanabilir (`customers.national_id` emsali).
`ck_bank_accounts_cash_has_name`: `account_type='cash'` ise `display_name` NOT NULL.

🔴 **Proje/şantiye FK'sı YOK (K3).** E9'da hiçbir alan şantiye göstermiyor, çek tablosunda proje
sütunu yok (envanter F-12). Hesap **şirket genelidir** — `suppliers`/`stock_items`/`customers`
emsali. Erişim `treasury` izin modülüyle denetlenir, IDOR unutulmuş değildir.

### 2.2 `payments` (tahsilat **ve** ödeme — tek tablo)

Dayanak **FGI:220-247** (`Tahsilat Kaydı` formu). Aynı biçim gelen faturanın ödemesi için de
geçerlidir; yönü **faturanın `direction`'ı belirler**, ayrı kolon AÇILMAZ (K4).

| Kolon | Tip | Dayanak |
|---|---|---|
| `id` | UUID PK | |
| `invoice_id` | →`invoices` **RESTRICT** NOT NULL | tahsilat bir faturaya kaydedilir |
| `bank_account_id` | →`bank_accounts` **RESTRICT** NOT NULL | FGI:240-244 `Hesap` select'i |
| `method` | enum `payment_method_kind` = `transfer` \| `cheque` \| `promissory_note` \| `cash` | FGI:225-228 **BİREBİR**: `Banka Havalesi / EFT` · `Çek` · `Senet` · `Nakit` |
| `amount` | Numeric(18,2) NOT NULL, **CHECK > 0** | FGI:232-233 `Tahsil Edilen Tutar` |
| `paid_on` | Date NOT NULL, indeksli | FGI:236-237 `Tahsilat Tarihi` |
| `note` | Text nullable, `FREE_TEXT_MAX_LENGTH` | serbest |
| `created_by_id` | →`users` RESTRICT NOT NULL | |
| `created_at`/`updated_at` | | |

⚠️ `method='cheque'`/`promissory_note` **çek KAYDI AÇMAZ** — yalnız ödeme şeklinin etiketidir
(çek varlığı HZ-2'nin işi). Bu bilinçli bir sınırdır, `cheque_id` kolonu **açılmaz**.

---

## 3. 🔴 Para kararları

### K2 — BAKİYE SAKLANMAZ, TÜRETİLİR (tek kaynak `treasury/balance.py`)
```
bakiye(hesap) = opening_balance
              + Σ payments.amount  (bağlı fatura direction = outgoing → tahsilat, GİRİŞ)
              − Σ payments.amount  (bağlı fatura direction = incoming  → ödeme,   ÇIKIŞ)
```
Gerekçe: saklanan bakiye **kaçınılmaz olarak kayar** (iki eşzamanlı yazma, yarım rollback, elle
düzeltme). Mockup tek rakam basıyor (E9:72) — türetilmiş değer bu sözleşmeyi birebir karşılar.
Hareket tablosu (HZ-3) geldiğinde **aynı formüle bir terim eklenir**, kolon göçü gerekmez.
`inventory/balance.py` bu deseni zaten taşıyor — **emsal alınır**.

### K5 — KISMİ TAHSİLAT: ÖDEMELER SATIRDIR, TEK ALAN DEĞİL
FGI:233 tutarı serbest bıraktığı için kısmi tahsilat **yapısal olarak mümkündür**; ama
`Ödenen`/`Kalan` gösterimi **hiçbir ekranda çizilmemiş** (envanter md.12) ve birden çok tahsilat
listesi de yok.

**Karar:** `invoices` üzerinde `paid_amount` **kolonu AÇILMAZ**. Ödenen = `Σ payments`; kalan =
`invoice.total − Σ payments`. Faturanın durumu bundan **türetilerek damgalanır**:
- `Σ payments >= invoice.total` → giden `collected` · gelen (Hazine kapsamında durum değişmez)
- aksi hâlde durum DEĞİŞMEZ (`sent` kalır — K1/FAT-1'deki "Vadeli" gösterimi)

🔴 **Bu karar BİLİNÇLİ olarak GERİ ALINABİLİR tutulmuştur.** Ödemeler satır olarak durduğu için
politika değişirse (ör. "kısmi tahsilat ayrı bir durum üretsin") çözüm bir **yeniden hesaptır**,
veri göçü değil. Kullanıcı döndüğünde **doğrulanacak açık karardır** — ROADMAP'e öyle yazılır.

### K6 — AŞIRI TAHSİLAT REDDEDİLİR (fail-closed, NULL-EŞİK kanonunun kardeşi)
`Σ payments + yeni.amount > invoice.total` → **422**. Gerekçe: fazla tahsilat mockup'ta hiçbir
yerde modellenmemiş (iade/avans kavramı yok); sessizce kabul etmek bakiyeyi şişirir.
Tolerans **YOK** (kuruş bazında tam karşılaştırma, `Decimal`).

### K7 — 🔴 EŞİK = KİLİT (WORKFLOW §4, İK-2/İK-3 dersi)
K6 bir **eşik denetimidir** → kilitsiz yapılamaz. İki eşzamanlı tahsilat isteği AYNI toplamı
okur ve **her ikisi de kapıdan geçer** (İK-3'te iki eşzamanlı ödeme bordroyu İKİ KEZ ödemişti).
- Kilit **fatura satırında** (`invoices`, sahip/ana satır), `with_for_update + populate_existing`.
- Kilit **denetimlerden ÖNCE** (TOCTOU). Kilit sırası SABİT: fatura → ödemeler → hesap.
- Regresyon **İKİ GERÇEK BAĞLANTIYLA** yazılır ve **kilit kaldırılınca KIRMIZI olduğu KANITLANIR.**

### K8 — N-ÇARPANLI SNAPSHOT KANONU burada UYGULANMAZ, gerekçesi yazılır
Ödeme türev bir değer DEĞİL, **kullanıcının girdiği olgudur** (tutar + tarih + hesap). Donacak bir
çarpanı yoktur. Buna karşılık **fatura tarafı zaten FAT-1'de donmuştur** — ödeme, donmuş `total`a
karşı denetlenir. T-son sınıf araması bunu doğrular.

---

## 4. Uçlar (9 yol) — izin modülü **`treasury` ZATEN AÇIK**

`roles/seed_data.py:103` → `"treasury": [_A, _F, _N, _N, _N, _F, _V, _N]`
(sysadmin admin · patron full · **muhasebe full** · PM görüntüle · saha/İK/satınalma yok).
🔴 **YENİ İZİN MODÜLÜ AÇILMAZ, matris satırına DOKUNULMAZ, migration'da izin satırı YOKTUR.**

| # | Uç | İzin | Not |
|---|---|---|---|
| 1 | `GET /bank-accounts` | view | Kart verisi: her hesap + **türetilmiş `balance`** (K2). Süzgeç `is_active`. Sayfalama YOK (mockup 3 kart, tavan küçük) — ama `limit` (varsayılan 50, `le=200`, aşım **422**) yine de eklenir, repo kanonu |
| 2 | `POST /bank-accounts` | full | |
| 3 | `GET /bank-accounts/{id}` | view | |
| 4 | `PATCH /bank-accounts/{id}` | full | `opening_balance` değişebilir (elle düzeltme meşru); değişince bakiye kendiliğinden yeniden türetilir |
| 5 | `DELETE /bank-accounts/{id}` | **admin** | Ödemesi olan hesap **409** (FK RESTRICT'in servis karşılığı). Kullanımdan kaldırma `is_active=false` |
| 6 | `GET /invoices/{id}/payments` | `invoicing` view | Faturanın tahsilat/ödeme satırları + `paid_total` + `remaining` |
| 7 | `POST /invoices/{id}/payments` | `invoicing` full | K6 + K7. Başarıda fatura durumu K5'e göre damgalanır |
| 8 | `DELETE /payments/{id}` | **admin** | Yanlış tahsilat geri alınabilmeli; silince fatura durumu **yeniden türetilir** (`collected` → `sent`'e düşebilir). Kilit K7'nin aynısı |
| 9 | `GET /treasury/upcoming-payments` | view | E9:109-125. `days` parametresi **varsayılan 7** (E9:110 `(7 Gün)`), `ge=1, le=90`. Alanlar: karşı taraf · evrak atfı · vade · **kalan gün (türetilir)** · tutar |
| 10 | `GET /treasury/cash-flow` | view | E9:90-106. `year`+`month` (varsayılan içinde bulunulan ay, `DISPLAY_TIMEZONE`). Döner: günlük kovalara toplanmış `inflow`/`outflow` serisi + iki toplam (`Giriş`/`Çıkış`) |

> 9 yol yazıyordu, uç listesi **10**'dur — beklenen `openapi.json`: FAT-1 sonrası **194 + 10 = 204**.

### K9 — `upcoming-payments` ÜÇ KAYNAKTAN beslenir, ama bu dilimde **İKİSİ** vardır
E9:113/117/121 üç kaynak gösteriyor: **hakediş**, **bordro**, **fatura**.
- ✅ **fatura** — `invoices` (gelen, `approved`, `due_date` penceresi içinde, tam ödenmemiş)
- ✅ **taşeron hakedişi** — `subcontractor_progress_payments` (onaylı, ödenmemiş) → E9:113
  `Akın İnşaat – Hakediş #47`
- ⛔ **bordro** — `payroll_periods` ödeme vadesi kavramı taşımıyor (İK-3'te vade kolonu AÇILMADI).
  **Uydurulmaz.** Yanıt zarfı kaynağı `source_type` ile bildirir; bordro kaynağı bugün **hiç satır
  üretmez** ve bu ROADMAP'e açık borç olarak yazılır.

### K10 — aciliyet rengi SUNUCUDA ÜRETİLMEZ
E9'un renk kodlaması **kendi içinde tutarsız** (2 gün→turuncu, 3 gün→**kırmızı**, 7 gün→yeşil;
envanter F-7). Ya renk aciliyete değil **evrak tipine** bağlı, ya mockup hatalı. Sunucu
`days_remaining` (sayı) + `source_type` döner; **renk kararı istemcidedir** — SA'nın
"EN HIZLI rozeti sunucuda üretilmez" kanonuyla aynı sınıf.

---

## 5. Modül düzeni (`app/modules/treasury/`)

`models.py · schemas.py · repository.py · service.py · router.py · balance.py (K2 tek kaynak) ·
upcoming.py (uç 9) · cash_flow.py (uç 10)`. Hiçbir dosya **800 satırı** geçmez.

- `alembic/env.py` **ve** `tests/conftest.py`'ye `treasury` EKLENİR (TB1 + SD dersi).
- `app/main.py` router kaydı. 🔴 **Sıra tuzağı:** `/treasury/upcoming-payments` ve
  `/treasury/cash-flow` sabit segmentlidir; `/bank-accounts/{id}` ile çakışmaz ama
  `payments` router'ı `invoices` router'ından **SONRA** kaydedilirse `/invoices/{id}/payments`
  yolu `invoicing`in `/invoices/{invoice_id}` rotasına takılabilir → **`invoices/{id}/payments`
  uçları `invoicing` router'ının İÇİNDE tanımlanır** (MK-2'nin `main.py:94-104` dersi).

## 6. Migration
- Ebeveyn: **FAT-1'in revizyonu** (dilim başlarken `alembic heads` ile OKUNUR, tahmin edilmez).
- 🔴 Merge'den önce `origin/main` head'i son kez kontrol → gerekirse **re-parent + test sabiti
  birlikte** (tek satır YETMEZ). Çift head → `Dockerfile:22` → **uygulama hiç açılmaz**.
- İki yeni enum (`bank_account_type`, `payment_method_kind`) → downgrade'de **`DROP TYPE`**.
- Test'te `head`/`-1` KULLANILMAZ, açık revizyon id'si.

## 7. Kararlar özeti (yönetim bağladı)

| # | Karar | Dayanak |
|---|---|---|
| K1 | Hesap tipi **yalnız 2 değer** (`checking`/`cash`) | E9'da yalnız ikisi çizili |
| K2 | Bakiye **türetilir**, saklanmaz | `inventory/balance.py` emsali |
| K3 | Hesap **şirket geneli**, proje FK'sı yok | E9/E10'da şantiye alanı yok |
| K4 | Tahsilat ve ödeme **tek tablo**, yön faturadan | FGI formu ikisinde de aynı |
| K5 | Kısmi tahsilat = **satırlar**, `paid_amount` kolonu yok · ⚠️ **kullanıcı dönünce doğrulanacak** | FGI:233 serbest tutar · Ödenen/Kalan çizilmemiş |
| K6 | Aşırı tahsilat **422** (fail-closed) | iade/avans modellenmemiş |
| K7 | K6 kilitli, iki bağlantılı regresyon + mutasyon kanıtı | WORKFLOW §4 EŞİK=KİLİT |
| K9 | `upcoming-payments` bugün **iki** kaynaktan; bordro **uydurulmaz** | İK-3'te vade kolonu yok |
| K10 | Aciliyet rengi **istemcide** | E9 renk kodlaması tutarsız (F-7) |
| K11 | **Çek/senet KAPSAM DIŞI** | geçişler + iki sekme + `Karşılıksız` çizilmemiş |
