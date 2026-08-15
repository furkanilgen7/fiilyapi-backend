# MU-1 — Muhasebe Çekirdeği (hesap planı + yevmiye) · tasarım

- **Dal:** `feat/mu1-muhasebe-cekirdegi` · **base** `38336eb`
- **Modül dizini:** `app/modules/accounting/` · **izin anahtarı:** `accounting`
  (🔴 seed'de **ZATEN VAR** — `roles/seed_data.py:99`; **yeni izin modülü AÇILMAZ, izin migration'ı YOKTUR**)
- **Mockup'lar (tasarım otoritesi):**
  - `projedesign/Muhasebe - Hesap Planı.dc.html` → bu belgede **HP:n**
  - `projedesign/Ekran 8 - Muhasebe.dc.html` → bu belgede **E8:n**

Bu belge T1'in (Opus) çıktısıdır; şefin bağladığı üç ek karar §11'dedir. **Bağlayıcıdır** —
T2/T3/T4 buradan sapamaz, sapma gerekirse şefe bildirir.

---

## 1. Mockup okuması

### 1a. Hesap Planı (HP)

| Satır | Okunan | Karar |
|---|---|---|
| HP:47 | `Hesap ara...` tek kutu | `q` süzgeci **kod + ad** üzerinde |
| HP:49 · HP:50 | `Excel` · `+ Hesap Ekle` | Excel ucu AÇILMAZ (§9); ekleme ucu VAR (form mockup'ı yok → §11 K-Ş1) |
| HP:58-62 | Sütunlar: `Kod` · `Hesap Adı` · `Tür` · `Bakiye (₺)` · `Durum` | Tablo sözleşmesi = beş alan. **Proje/şantiye sütunu YOK** → §3 kapsam kararı |
| HP:69,135,161,187 | `SINIF 1/2/3/5` bantları, dördü de `colspan="5"`, **kod sütunu YOK** | 🔴 **Sınıf bir KAYIT DEĞİLDİR** — kodun ilk hanesinden türetilir |
| HP:72,97,115 | `10 Hazır Değerler` · `12 Ticari Alacaklar` · `15 Stoklar`; kod DOLU, kalan dört sütun `colspan="4"` | **Grup bir KAYITTIR**; Tür/Bakiye/Durum yalnız RENDER EDİLMEZ |
| HP:76-131 | `100`,`101`,`102`,`120`,`127`,`150`,`191` | Üç hane = ana hesap |
| HP:126 | `191` İndirilecek KDV, görsel olarak `15 Stoklar` bandının altında | Mockup iç tutarsızlığı — grup **KODDAN** türer (`19`), bant yerleşiminden değil |
| HP:138-155 | `252`,`254`,`257 Birikmiş Amortismanlar (-)` | `(-)` hesap **ADININ** parçası |
| HP:164-182 | `320`,`360`,`391` | — |
| HP:190-208 | `600`,`730`,`760` — hepsi **"SINIF 5" bandının altında ama kodları 6 ve 7** | 🔴 **K15: satırlar kazanır.** Sınıf `6`/`7`; bant etiketi yanlış |
| HP:78,154,192,199 | Tür rozetleri, kapalı küme: `Aktif` · `Pasif` · `Gelir` · `Gider` | K5 enum = **4 üye**, beşinci İCAT EDİLMEZ |
| HP:80 vd. | Durum sütunu: her satırda tek yeşil nokta, **METİN YOK** | 🔴 **Durum ≠ Tür.** Durum = `is_active` (boolean); "Aktif/Pasif" METNİ **Tür** sütunundadır |
| HP:155 | `257` bakiyesi **`(620.000)`** — tek parantezli satır | §1c |

**Kod dilbilgisi (K4) — mockup'tan ÇIKARILAN, icat edilmeyen:**

| Düzey | Biçim | Kanıt | Örnek |
|---|---|---|---|
| Sınıf | tek hane, **kayıt değil** | HP:69,135,161,187 (kodsuz bant) | `1`,`2`,`3`,`6`,`7` |
| Grup | `NN` | HP:72,97,115 | `10`,`12`,`15` |
| Ana hesap | `NNN` | HP:76…204 | `100`,`191`,`257`,`600` |
| Alt hesap | `NNN.NN` | E8:112,120,128,136,144,152 | `120.01`,`320.04`,`153.01` |

🔴 **`NNN.NN.NNN` (üçüncü kırılım) hiçbir mockup'ta YOKTUR → AÇILMAZ.**

### 1b. Yevmiye (E8)

| Satır | Okunan | Karar |
|---|---|---|
| E8:73-77 | `‹ Temmuz 2026 ›` | 🔴 Dönem = **AY** (yıl+ay). Varsayılan = içinde bulunulan ay → **K6 sınır çağrısı** |
| E8:79-88 | KPI: **Toplam Borç** `3.842.600` · **Toplam Alacak** `4.120.000` · **Net Bakiye** `277.400` | 🔴 `4.120.000 − 3.842.600 = 277.400` **TAM TUTUYOR** → **Net = ALACAK − BORÇ**. Bu, göstermelik olmayan tek aritmetiktir ve işaret yönünü KANITLAR |
| E8:72 | KPI şeridi tablonun **DIŞINDA**, dönem seçiciyle aynı satırda | KPI'lar yalnız DÖNEM'e bağlıdır, **hesap süzgecine bağlı DEĞİL** (FAT-1 `summary.py` emsali) |
| E8:96 | `select`: Tüm Hesaplar / Kasa / Banka / Alıcılar | TEK hesap süzgeci (`account_id`), çoklu değil |
| E8:101-106 | `Tarih` · `Hesap Kodu` · `Açıklama` · `Borç` · `Alacak` · `Bakiye` | 🔴 Tablo **SATIR (fiş satırı) bazlıdır**, fiş bazlı değil |
| E8:111-157 | 6 satır, `17.07 → 10.07` | Sıralama **tarih DESC** |
| E8:114,123,131,139,146,155 | Boş taraf hep **`—`** | 🔴 Her satır **TEK TARAFLIDIR** → `ck_journal_lines_single_side` |
| E8:113,121,129,137,145,153 | Açıklama hücresi **İKİ satırlı**: üst = işlemin adı, alt = dayanak | İki ayrı alan (aşağıda) |
| E8:116,124,132,140,148,156 | Bakiye sütunu: `4.120.000 → 2.880.000 → 3.896.800 → 4.225.300 → 5.117.300 → 4.537.300` | 🔴 **Hiçbir aritmetiği tutmuyor** (tarih DESC iken artıp düşüyor) → **göstermelik**; kural YAPIDAN okunur (§6d) |

**Açıklamanın ikinci satırı bir FK DEĞİLDİR.** Altı örnek: `Ziraat Bank · TRF-20260717` · `Fatura No: AKN-2026-047` ·
`Demirsan A.Ş · F-2026-1122` · **`48 personel · SGK dahil`** · `İş Bank · TRF-20260712` · `Vergi Dairesi`.
Dördüncüsü **hiçbir varlığa çözülmez**; heterojen küme = **serbest metin** → `detail_note String(200)`
(FAT-1 `invoice_lines.detail_note` ile aynı ad/rol/ölçü). FK açılsaydı MU-3'ün (entegrasyon) işi buraya sızardı.

### 1c. `257` parantezi — mockup ile K3'ün çatışması

| Kod | Tür | Ekranda | K3 kuralının çıktısı | Tutuyor mu |
|---|---|---|---|---|
| `320` Satıcılar | Pasif | `2.184.000` | `+2.184.000` | ✅ |
| `391` Hesaplanan KDV | Pasif | `412.000` | `+412.000` | ✅ |
| `257` Birikmiş Amort. **(-)** | Pasif | **`(620.000)`** | `+620.000` | ❌ |

Aynı Tür'e sahip üç hesaptan yalnız biri parantezli → **parantezin kaynağı `account_type` DEĞİLDİR**;
verideki tek ayırt edici işaret **adın `(-)` son ekidir** (HP:153) — Tekdüzen Hesap Planı'nın kontra
hesap yazım geleneği. **Karar:** `is_contra` kolonu **AÇILMAZ** (hiçbir form onay kutusu çizmiyor —
icat yasağı). Parantez bir **SUNUM** kuralıdır. MU-2 açık sorusu → §11 K-Ş2.

---

## 2. Çakışma envanteri (isim tutarlılığı)

| Kavram | Emsal | MU-1 seçimi | Gerekçe |
|---|---|---|---|
| durum enum tipi | `invoicing.invoice_status` | `journal_entry_status` | enum TİPİ modül başına ayrı (FAT-1) |
| ikincil serbest metin | `invoice_lines.detail_note String(200)` | `journal_entries.detail_note` **birebir** | aynı rol → aynı ad |
| ana serbest metin | `invoice_lines.description` | `journal_entries.description Text` | E8:113 üst satırı NOT değil işlemin ADI; `note` AÇILMAZ |
| satır sırası | `invoice_lines.sort_order` (NOT NULL, **server_default YOK**) | **birebir** | FAT-1/SA dersi |
| dönem | `equipment_rental_invoices.period_year/period_month` (MK-2) | **birebir** | K9; üçüncü bir dönem yazımı açılmaz |
| para tutarı | `payments.amount` tek kolon | **`debit` + `credit` iki kolon** | tek `amount`+`side` seçilseydi `SUM(borç)` bir `CASE` içine gizlenir, **K1'in DB kısıtı yazılamazdı** |
| türev-ama-saklanan | `invoices.subtotal…total` (K7 bilinçli istisnası) | `total_debit`/`total_credit` | §4 |
| bakiye | `treasury/balance.py` (SAKLANMAZ) | `accounting/balance.py` **birebir desen** | K3 |
| `opening_balance` | `bank_accounts.opening_balance` = SAKLANAN kolon | MU-1'de kolon YOK; türev alanın adı **`carried_balance`** | aynı ad biri kolon biri türev olsaydı frontend ayırt edemezdi |
| sayfalama zarfı | `{items,total,limit,offset}` | üç liste ucunda **birebir** | K7 |
| izin modülü | `accounting` seed'de VAR | **yeni modül AÇILMAZ** | **K8** |
| `AuditAction` | 6 üye | **yeni üye AÇILMAZ**; `post→approve`, `reverse→update` | K5 / TB3 kanonu; ayrım `messages.*` metninde |

---

## 3. Şema

### 🔴 Kapsam kararı (IDOR) — üç tabloda da `project_id`/`site_id` YOKTUR

HP'nin beş, E8'in altı sütununda **hiçbir proje/şantiye alanı yoktur**. E8:28-30 topbar'da
`Güneşkent Konut · A-Blok` yazar ama tabloda karşılığı yoktur; E8:113'teki `– Güneşkent`
**serbest metnin içindedir**. Hesap planı şirket geneli bir katalogtur
(`suppliers`/`stock_items`/`bank_accounts` sınıfı). Erişim tamamen `accounting` izniyle denetlenir.
**IDOR unutulmuş DEĞİLDİR, yapısal olarak yoktur.** Maliyet merkezi/proje kırılımı = **MU-3**.

### 3a. `chart_of_accounts`

| Kolon | Tip | Null | Default | Kısıt | Kaynak |
|---|---|---|---|---|---|
| `id` | `UUID` | ✗ | `uuid4` | PK | — |
| `code` | `String(20)` | ✗ | — | `uq_chart_of_accounts_code` · `ck_chart_of_accounts_code_format` | HP:58,72,76 · K4 |
| `name` | `String(200)` | ✗ | — | — | HP:59,77 |
| `account_type` | `Enum(ChartAccountType, name="chart_account_type")` | ✗ | — | — | HP:60,78 · K5 |
| `is_active` | `Boolean` | ✗ | `server_default text("true")` | — | HP:62,80 |
| `created_at`/`updated_at` | `DateTime(timezone=True)` | ✗ | `func.now()` (+`onupdate`) | — | repo deseni |

**Enum `chart_account_type`:** `asset` (Aktif, HP:78) · `liability` (Pasif, HP:154) ·
`revenue` (Gelir, HP:192) · `expense` (Gider, HP:199). **Kapalı küme — beşinci üye AÇILMAZ.**

**`ck_chart_of_accounts_code_format`:**
```sql
code ~ '^[1-9][0-9]$' OR code ~ '^[1-9][0-9]{2}(\.[0-9]{2})?$'
```
İlk hane `0` olamaz (sınıfsız hesap yoktur). Üçüncü kırılım **yapısal olarak reddedilir**.

**Hiyerarşi `parent_id` FK'siyle DEĞİL, KODUN İÇİNDE taşınır.** K4 zaten "kod hiyerarşiktir" der;
`120.01`in ebeveyni `120`, `120`inki `12`, `12`ninki yoktur (sınıf kayıt değil). `parent_id`
açılsaydı türetilebilir bir şey saklanır ve kod düzeltildiğinde FK bayatlardı.

**Index:** `uq_chart_of_accounts_code` (UNIQUE) · `ix_chart_of_accounts_account_type`.
`is_active` için indeks AÇILMAZ (iki değerli, seçicilik yok).

### 3b. `journal_entries`

| Kolon | Tip | Null | Default | Kısıt | Kaynak |
|---|---|---|---|---|---|
| `id` | `UUID` | ✗ | `uuid4` | PK | — |
| `entry_date` | `Date` | ✗ | — | — | E8:101,111 · K6 |
| `period_year` | `Integer` | ✗ | — | `ck_journal_entries_period_matches_date` | E8:75 · K9 |
| `period_month` | `Integer` | ✗ | — | aynı CHECK | E8:75 · K9 |
| `description` | `Text` | ✗ | — | tavan ŞEMADA (`FREE_TEXT_MAX_LENGTH`) | E8:103,113 |
| `detail_note` | `String(200)` | ✓ | — | — | E8:113 alt satır |
| `status` | `Enum(JournalEntryStatus, name="journal_entry_status")` | ✗ | — | `ck_journal_entries_posted_balanced` | K2 |
| `total_debit` | `Numeric(18,2)` | ✗ | `server_default text("0")` | `ck_journal_entries_totals_non_negative` | E8:104 · **K1 DB katmanı** |
| `total_credit` | `Numeric(18,2)` | ✗ | `server_default text("0")` | aynı CHECK | E8:105 · **K1 DB katmanı** |
| `reversal_of_id` | `UUID` FK `journal_entries.id` **RESTRICT** | ✓ | — | `uq_journal_entries_reversal_of` | K2 storno |
| `created_by_id` | `UUID` FK `users.id` **RESTRICT** | ✗ | — | — | repo deseni |
| `created_at`/`updated_at` | `DateTime(timezone=True)` | ✗ | `func.now()` (+`onupdate`) | — | repo deseni |

**Enum `journal_entry_status`:** `draft` · `posted` · `reversed`.

🔴 **`entry_no` (fiş numarası) AÇILMAZ** — ne HP'de ne E8'de fiş numarası sütunu vardır.
FAT-1'de vardı çünkü FY tablosunda çiziliydi. Kimlik `id`dir. `numbering.py` YOKTUR.

**`ck_journal_entries_period_matches_date` (K9'un drift-proof hâli):**
```sql
period_year  = EXTRACT(YEAR  FROM entry_date)::int AND
period_month = EXTRACT(MONTH FROM entry_date)::int
```
Dönem türetilebilirdir ama K9 MU-2'nin EŞİK=KİLİT'i için alan istiyor. Bu CHECK ikisini uzlaştırır:
kolon VARDIR (MU-2 `(period_year, period_month)` üzerinden kilitleyebilir) ve **kayamaz**.
`EXTRACT` bir **`date`** kolonu üzerinde IMMUTABLE'dır, CHECK'te yasaldır.
🔴 K6 açısından temiz: `entry_date` `Mapped[date]`tir, `timestamptz` değil → AST bekçisinin
3. kalıbı tetiklenmez (`tests/test_local_calendar_guard.py` `date kolonu` testi bunu doğruluyor).

**Index:** `ix_journal_entries_entry_date` · `ix_journal_entries_period` (`period_year`,`period_month`) ·
`ix_journal_entries_status` · `uq_journal_entries_reversal_of` (UNIQUE; PG'de çok sayıda NULL
serbesttir → kısıt tam olarak "bir fişin en fazla BİR stornosu olur" der).

### 3c. `journal_lines`

| Kolon | Tip | Null | Default | Kısıt | Kaynak |
|---|---|---|---|---|---|
| `id` | `UUID` | ✗ | `uuid4` | PK | — |
| `entry_id` | `UUID` FK `journal_entries.id` **CASCADE** | ✗ | — | `ix_journal_lines_entry_id` | FAT-1 emsali |
| `sort_order` | `Integer` | ✗ | **default YOK** | — | gövde dizisinin indeksi |
| `account_id` | `UUID` FK `chart_of_accounts.id` **RESTRICT** | ✗ | — | `ix_journal_lines_account_id` | E8:102,112 |
| `debit` | `Numeric(18,2)` | ✗ | `server_default text("0")` | `ck_journal_lines_amounts_non_negative` · `ck_journal_lines_single_side` | E8:104,122 · **K1** |
| `credit` | `Numeric(18,2)` | ✗ | `server_default text("0")` | aynı iki CHECK | E8:105,115 · **K1** |

**`account_id` RESTRICT:** fiş satırı olan hesap SİLİNEMEZ. CASCADE olsaydı hesabın silinmesi
yevmiye satırlarını sessizce yok eder ve türetilmiş bakiye (K3) **kaydığı fark edilmeden** kayardı.

**Satırda `description` ve zaman damgası AÇILMAZ:** bir fişin iki bacağı aynı işlemi anlatır;
satıra taşınsaydı aynı metin tekrarlanır ve ayrışabilirdi. Satırın ömrü başlığa bağlıdır (CASCADE).

---

## 4. K1'in İKİ KATMANI

### Katman 1 — SERVİS (`validation.py`, yazımdan ÖNCE, **422**)

`balance_blockers(lines)` üç engeli TEK 422'de toplar (FAT-1 `_raise_blockers` deseni):

1. `Σ debit ≠ Σ credit` → `"Fiş dengede değil: borç ve alacak toplamları eşit olmalıdır"`.
   Karşılaştırma `Decimal` üzerinde **kuruş bazında TAM, tolerans YOK** (HZ-1 K6 kanonu).
2. `len(lines) < 2` → `"Fişte en az iki satır olmalıdır"`.
3. Yaprak olmayan hesaba satır → `"Fiş satırı yalnızca alt düzey hesaba kesilebilir"` (§4c).

Kapı **iki yazma yolundan da** geçer (`POST /journal-entries`, `PUT …/lines`) **ve**
`POST …/post` anında **yeniden** koşar (FAT-1 `gate_blockers` deseni): taslak dengesiz
bırakılabilir ama kayıtlaştırılamaz.

### Katman 2 — DB (SON savunma)

```python
# journal_lines — NULL fail-closed'un YAPISAL garantisi
CheckConstraint("debit >= 0 AND credit >= 0",
                name="ck_journal_lines_amounts_non_negative")
CheckConstraint("(debit > 0 AND credit = 0) OR (credit > 0 AND debit = 0)",
                name="ck_journal_lines_single_side")

# journal_entries — DENGESİZ FİŞ `posted` OLAMAZ
CheckConstraint("status <> 'posted' OR total_debit = total_credit",
                name="ck_journal_entries_posted_balanced")
CheckConstraint("total_debit >= 0 AND total_credit >= 0",
                name="ck_journal_entries_totals_non_negative")
```

### 🔴 NULL fail-closed — üç mekanizma, hiçbiri tek başına yetmez

- `debit`/`credit` **`nullable=False`** → NULL tutar satıra hiç giremez.
- `CHECK (>= 0)` → negatif tutar `Σ`yı sessizce dengeleyemez (bir borç satırına `-100` yazıp
  sahte denge kurmak imkânsız).
- `CHECK single_side` → `(0,0)` satırı reddedilir; toplama katkısı olmayan satır fişi şişiremez.

Üçü olmadan senaryo: `debit=NULL, credit=NULL` olan satır `SUM` tarafından **yutulur**, iki toplam
da değişmez ve **dengesiz fiş dengede sayılır**. Şimdi bu satır DB'ye hiç giremez.
Aynı gerekçe başlıkta da tekrarlanır: `total_debit`/`total_credit` **NOT NULL'dır**, çünkü
`NULL = NULL` → **NULL üretir ve CHECK'i GEÇER**; nullable bırakılsalardı
`ck_journal_entries_posted_balanced` **sessizce devre dışı kalırdı**.

### Toplamlar neden türev oldukları hâlde saklanıyor

Bir CHECK **başka satırların toplamını GÖREMEZ** (HZ-1 aşırı-tahsilat notunun aynısı,
`treasury/models.py:179-181`). K1 "DB düzeyinde korunur" diyorsa toplam başlıkta kolon olmak
zorundadır. Sapma penceresi kapalıdır: satırlar **yalnız `draft`ta** ve **yalnız tek yoldan**
(`_apply_totals`, FAT-1 `_apply_amounts` emsali) yazılır; `posted`tan sonra satırlar değişmez (K2).
CHECK zaten sadece `posted`ta ısırdığı için pencere ile kısıt **tam örtüşür**.

**Trigger YOK** — repo hiçbir yerde trigger kullanmıyor. "posted fişin satırı UPDATE edilemez"
iddiası DB'de zorlanamaz, **servis katmanında** durur → §10 R5.

### 4c. Yaprak hesap kuralı (KARAR, mockup dolaylı)

Fiş satırı yalnızca **çocuğu olmayan** hesaba kesilir. Kanıt: E8'in altı satırının HEPSİ en derin
biçimdedir (`NNN.NN`); HP'nin grup satırları (HP:72,97,115) Tür/Bakiye sütunlarını hiç basmaz.
Gerekçe: üst hesabın bakiyesi çocuklarının toplamıdır; hem üste hem alta kayıt atılırsa MU-2'nin
mizanı **çift sayar**. Servis katmanında **422** (DB'de zorlanamaz).

🔴 **Ters yön de kapatılır (şef kararı, §11 K-Ş3):** fiş satırı OLAN bir hesabın altına çocuk
hesap açmak **409**'dur (`guards.PARENT_HAS_JOURNAL_LINES`). Yoksa `120`e satır atıp sonra
`120.01` açmak yaprak kuralını geçmişe dönük deler.

---

## 5. K2 durum makinesi

`transitions.py` — matris TEK kopya; servis/uçta hiç `if status == …` yok (FAT-1 deseni).

```
draft ──post──▶ posted ──reverse──▶ reversed  (+ YENİ storno fişi, doğrudan `posted`)
```

```python
JOURNAL_TRANSITIONS = {
    (JournalEntryStatus.draft,  JournalAction.post):    JournalEntryStatus.posted,
    (JournalEntryStatus.posted, JournalAction.reverse): JournalEntryStatus.reversed,
}
INITIAL_STATUS        = JournalEntryStatus.draft      # gövde `status` GÖNDEREMEZ
EDITABLE_STATUS       = frozenset({JournalEntryStatus.draft})
LINES_EDITABLE_STATUS = frozenset({JournalEntryStatus.draft})
DELETABLE_STATUS      = frozenset({JournalEntryStatus.draft})
```
Tabloda olmayan her çift **409**. `reversed` **TERMİNALDİR**.

| İşlem | İzin | Kabul | Ret kodu | Metin |
|---|---|---|---|---|
| oluştur | `full` | — | — | `messages.journal_entry_created` |
| düzenle (PATCH) | `full` | `draft` | **409** | `guards.JOURNAL_ENTRY_NOT_EDITABLE` = `"Kayıtlı fiş düzenlenemez"` |
| satır yaz (PUT lines) | `full` | `draft` | **409** | aynı |
| sil (DELETE) | 🔴 **`admin`** | `draft` | **409** (yetkisiz → **403**) | `guards.JOURNAL_ENTRY_NOT_DELETABLE` |
| kayıtlaştır (post) | `full` | `draft` | **409** · dengesiz → **422** | `messages.journal_entry_posted` |
| ters kayıt (reverse) | `full` | `posted` | **409** | `messages.journal_entry_reversed` |

**`DELETE` düz `admin`:** `full` silmeyi KAPSAMAZ; `can_delete` taslak istisnası burada
**geçersizdir** — fişin sahibi onu giren muhasebeci değil ŞİRKETTİR (FAT-1 gerekçesinin birebiri).

**`posted`ta 409, 403 DEĞİL:** kullanıcının yetkisi VARDIR; engelleyen kaydın DURUMUDUR.

### Ters kayıt (storno) — YENİ BİR FİŞ üretir (alan değil, bayrak değil)

| Alan | Değer | Gerekçe |
|---|---|---|
| `status` | **`posted`** doğrudan | storno taslak değildir |
| `entry_date` | 🔴 **`timezone.today()`** | **K6 SINIR ÇAĞRISI.** Orijinalin tarihi kullanılsaydı storno KAPALI bir döneme düşerdi (MU-2'nin kilitleyeceği şey). Saf çekirdek `today`yi **parametre** alır; `timezone`u yalnız `state_service` bilir |
| `period_year/month` | `entry_date`ten (CHECK zorlar) | K9 |
| `description` | `f"{REVERSAL_PREFIX}{orijinal.description}"`, `REVERSAL_PREFIX = "Ters kayıt: "` (`guards.py`de TEK kopya) | iki yerde kurulsaydı ayrışırdı |
| `detail_note` | orijinalinden kopya | dayanak aynıdır |
| `reversal_of_id` | orijinalin `id`si | `uq_…_reversal_of` çift stornoyu engeller |
| satırlar | orijinalinkiler, **`debit ↔ credit` TAKAS**, `sort_order` korunur | ters kayıt tanımı |
| orijinal | `posted → reversed` | matris |

**İki ek 409** (`state_service` kapıları): zaten stornosu varsa → `guards.ENTRY_ALREADY_REVERSED`
(UNIQUE'in servis karşılığı; kullanıcı Türkçe mesaj alsın diye IntegrityError'a düşülmeden) ·
`reversal_of_id IS NOT NULL` olan fiş terslenemez → `guards.REVERSAL_NOT_REVERSIBLE`
(stornonun stornosu sonsuz zincir açardı, mali anlamı yok).

**Denetim:** yeni `AuditAction` üyesi **AÇILMAZ**. `post → approve`, `reverse → update`;
ayrım `messages.*` metnindedir. **Tutar metne GİRMEZ** (HZ-1 kanonu). Metin silmeden ÖNCE kurulur.

### 🔴 EŞİK = KİLİT sırası (`state_service.py`) — SIRA DEĞİŞMEZ

1. **kilit** — `visible_entry(..., for_update=True)` (`with_for_update` + **`populate_existing`**)
2. matris → **409**
3. K1 kapısı → **422**
4. damga + (reverse ise) storno yazımı
5. `session.refresh(entry)` — `updated_at` sunucu damgasıdır; tazelenmezse yanıt şeması onu
   okurken async bağlamda `MissingGreenlet` = **500** (P11 dersi)

Kilit 2. adımdan sonra alınsaydı iki eşzamanlı `post` da `draft` okur, ikisi de matrisi geçer ve
fiş **İKİ KEZ** kayıtlaştırılırdı; iki eşzamanlı `reverse` **İKİ storno** üretirdi.
**Kilit sırası uçtan uca SABİT: fiş → satırlar → hesap.**

---

## 6. K3 bakiye türetme

`accounting/balance.py` — **TEK KAYNAK** (treasury `balance.py` deseni). İkinci bir formül
yazılsaydı liste ile detay aynı hesap için farklı sayı basardı ve **bakiye saklanmadığı için
hiçbir kolon farkı ele vermezdi**.

### 6a. 🔴 Hangi fişler bakiyeye girer — bu dilimin en sinsi tuzağı

```python
POSTING_STATUSES = (JournalEntryStatus.posted, JournalEntryStatus.reversed)
```
`draft` **GİRMEZ**. Ama `reversed` **GİRER**, ve bu şart:

| | Orijinal | Storno | Net |
|---|---|---|---|
| Yalnız `posted` sayılsaydı | `reversed` → **düşer** | `posted` → ters bacaklar eklenir | **−orijinal** ❌ çift ters |
| `posted + reversed` sayılınca | kalır (+X) | eklenir (−X) | **0** ✅ |

**K2'nin mali iz kanonu budur:** kayıtlaştırılmış fiş defterden ÇIKMAZ, yalnız ters kaydıyla
**nötrlenir**. T4'te bekçi testiyle kilitlenir.

### 6b. Ham nicelik — TEK yazım

```sql
net(account) = COALESCE(SUM(jl.debit) - SUM(jl.credit), 0)
  FROM journal_lines jl JOIN journal_entries je ON je.id = jl.entry_id
 WHERE jl.account_id = :id AND je.status IN ('posted','reversed')
```
🔴 **`COALESCE` ŞARTTIR** — satırı olmayan hesapta `SUM()` **NULL** döner, `0` değil; kart bakiye
yerine BOŞ basardı (HZ-1'in ayrı testli tuzağı). N+1 yasağı: `balances_for(session, ids)` **tek
sorguda** sözlük döner, `select_accounts_with_balance()` satır+bakiyeyi tek `Select`te birleştirir;
ikisi de `before_cursor_execute` sayacıyla **ÖLÇÜLÜR**.

### 6c. İşaret kuralı (K3)

```python
SIGN = {asset: +1, expense: +1, liability: -1, revenue: -1}
balance = SIGN[account_type] * net          # net = Σdebit − Σcredit
```
Doğrulama: `320` Pasif → `+2.184.000` ✅ · `600` Gelir → `+24.870.500` ✅ ·
`730`/`760` Gider → pozitif ✅ · `100`…`191` Aktif → pozitif ✅. Tek uymayan `257` (§1c).

**İki "Bakiye" TEK kaynaktan doğar:** ham `net` bir kez yazılır; hesap planı üzerine işaret
dönüşümünü uygular, yevmiye ham `net`i kullanır (§6d).

### 6d. Koşan bakiye (E8:106)

**Tanım (TEK):** süzülmüş satır kümesinin kanonik sıralamada **`Σ(debit − credit)`** kümülatif
toplamı; başlangıç değeri **`carried_balance`** (pencere ÖNCESİ tüm satırların aynı işaretli toplamı).

```sql
carried_balance + SUM(jl.debit - jl.credit) OVER (
    ORDER BY je.entry_date, je.created_at, jl.sort_order, jl.id
    ROWS UNBOUNDED PRECEDING)
```

1. **Devir şart.** Olmasaydı sayfa 2'de ya da ay değişince bakiye sıfırdan başlar, anlamsız seri çıkardı.
   Devir aynı süzgeçlerle (hesap süzgeci dahil), pencerenin **öncesindeki** satırlardan hesaplanır ve
   zarfın kökünde ayrı alan olarak döner.
2. **Birikim ESKİDEN YENİYE, gösterim YENİDEN ESKİYE.** E8 tarih DESC'tir ama koşan bakiye yalnız
   kronolojik birikimde anlamlıdır: pencere fonksiyonu ASC koşar, yanıt DESC döner.
3. **İşaret ham `net`tir** (borç `+`, alacak `−`), türe göre çevrilmez — hesap süzgeci
   **opsiyoneldir** (E8:96 `Tüm Hesaplar`) ve karışık hesaplarda tür-bazlı işaret tanımsız olurdu.

### 6e. Sıralama determinizmi — aynı tarihli iki satır

```
ORDER BY je.entry_date ASC,   -- E8:101 (görünen tek ölçüt)
         je.created_at ASC,   -- aynı gün girilen iki fiş
         jl.sort_order ASC,   -- aynı fişin bacakları
         jl.id ASC            -- MUTLAK tiebreaker (PK)
```
🔴 `jl.id` olmadan: `func.now()` **işlem başına SABİTTİR**, aynı işlemde yazılan iki fişin
`created_at`i eşittir → sıra Postgres'in keyfine kalır, **sayfalama satır tekrarlar/atlar** ve
koşan bakiye sayfadan sayfaya oynar. `created_at` yalnız **ORDER BY**da kullanılır — takvim
bileşeni ÇIKARILMAZ, K6 AST bekçisi tetiklenmez.

---

## 7. Uçlar

Kapı **`accounting`**. Zarf `{items,total,limit,offset}`; `limit` varsayılan **50**, `ge=1 le=200`,
aşım **422** (kırpma DEĞİL), `offset ge=0` (K7).

### Hesap planı — `accounts_router.py`

| Metot | Yol | İzin | Kodlar |
|---|---|---|---|
| `GET` | `/chart-of-accounts` | `view` | 200 · 422 |
| `POST` | `/chart-of-accounts` | `full` | **201** · 409 (kod tekrarı, **409 ebeveynin satırı var** §4c) · 422 |
| `GET` | `/chart-of-accounts/{account_id}` | `view` | 200 · 404 |
| `PATCH` | `/chart-of-accounts/{account_id}` | `full` | 200 · 404 · 409 · 422 |
| `DELETE` | `/chart-of-accounts/{account_id}` | 🔴 **`admin`** | **204** · 404 · 409 |

Süzgeçler (hepsi mockup'tan): `q` (HP:47, kod+ad, **`_like_escape` ŞART** §10 R15) ·
`account_type` (HP:60) · `is_active` (HP:62). Sıralama `code ASC`.
`DELETE` 409: fiş satırı **ya da** alt hesabı var. `full` → **403**; kaldırma yolu `PATCH is_active=false`.
`PATCH` 409: `code` değişimi yalnız **hiç fiş satırı olmayan** hesapta serbesttir; aksi hâlde tüm
geçmiş yevmiye sessizce kayardı.

### Yevmiye — `router.py`

| Metot | Yol | İzin | Kodlar |
|---|---|---|---|
| `GET` | `/journal-entries` | `view` | 200 · 422 |
| `POST` | `/journal-entries` | `full` | **201** · 404 (hesap yok) · 422 |
| `GET` | **`/journal-entries/summary`** | `view` | 200 |
| `GET` | `/journal-entries/{entry_id}` | `view` | 200 · 404 |
| `PATCH` | `/journal-entries/{entry_id}` | `full` | 200 · 404 · 409 · 422 |
| `DELETE` | `/journal-entries/{entry_id}` | 🔴 **`admin`** | **204** · 404 · 409 |
| `PUT` | `/journal-entries/{entry_id}/lines` | `full` | 200 · 404 · 409 · 422 |
| `POST` | `/journal-entries/{entry_id}/post` | `full` | 200 · 404 · 409 · 422 |
| `POST` | `/journal-entries/{entry_id}/reverse` | `full` | **201** (storno fişinin detayı) · 404 · 409 |
| `GET` | `/journal` | `view` | 200 · 422 |

🔴 **ROTA SIRASI (MK-2 dersi):** `/journal-entries/summary` **İKİ SEGMENTLİDİR** ve
`/journal-entries/{entry_id}` ile aynı şekli taşır. FastAPI KAYIT SIRASINA göre eşler →
**`summary`, `{entry_id}`den ÖNCE kaydedilir** + bekçi testi (FAT-1 `router.py:181-189` deseni).
`/journal` ile `/journal-entries` ayrı köklerdir, çakışmazlar.

**`GET /journal-entries` neden var (onaylı sapma, §11 K-Ş4):** mockup'ta fiş listesi ekranı YOKTUR;
ama K2 gereği `draft` fişler deftere (`/journal`) **girmez** → açılan bir taslağı bulup
kayıtlaştırmanın **başka hiçbir yolu kalmazdı**. Yapısal boşluğu kapatır.

**`/journal` süzgeçleri:** `year`+`month` (E8:75, varsayılan **`timezone.today()`nin ayı** — K6
sınır çağrısı) · `account_id` (E8:96) · `status` (varsayılan `POSTING_STATUSES`).
Yanıt satırı: `entry_date` · `account_code` · `account_name` · `description` · `detail_note` ·
`debit` · `credit` · `running_balance` · `entry_id` · `entry_status`. Kök alan: `carried_balance`.

**`/journal-entries/summary`:** `total_debit` (E8:80) · `total_credit` (E8:84) ·
`net_balance` = **alacak − borç** (E8:88 aritmetiğinden birebir). Yalnız `year`+`month` alır,
**hesap süzgeci ALMAZ** (§1b). `POSTING_STATUSES` burada da geçerlidir.

### Yol sayısı — 🔴 TAHMİN

9 yeni **YOL** / 15 operasyon (*yol ≠ operasyon* — FAT-1 dersi):
`/chart-of-accounts` · `/chart-of-accounts/{id}` · `/journal-entries` · `/journal-entries/summary` ·
`/journal-entries/{id}` · `/journal-entries/{id}/lines` · `/journal-entries/{id}/post` ·
`/journal-entries/{id}/reverse` · `/journal`

**Taban 197 → TAHMİN 206.** 🔴 Gerçek sayıyı **T5 ÖLÇER**, hedefe uydurulmaz.

**Frontend devir borcu (BFF tuzağı):** üç yeni kök — **`chart-of-accounts`**, **`journal-entries`**,
**`journal`**. İzin listesine eklenmezse modül canlıda tamamen **404**'tür; jsdom testleri GÖRMEZ.

---

## 8. Dosya bölümlemesi (800 tavanı — BAŞTAN bölünmüş)

| Dosya | Sorumluluk | ~satır |
|---|---|---|
| `models.py` | 3 tablo + 2 PG enum + tüm kısıtlar + kanon docstring'i | 250 |
| `codes.py` | 🔴 **SAF** kod dilbilgisi: regex, `class_code`, `level`, `parent_code`, `child_prefix`. DB/`today` bilmez | 90 |
| `balance.py` | **K3 TEK KAYNAK**: `POSTING_STATUSES`, `net_expression`, `balances_for`, `select_accounts_with_balance`, `SIGN` | 150 |
| `transitions.py` | **K2 matrisi** + `assert_editable/lines_editable/deletable` | 150 |
| `guards.py` | `PERMISSION_MODULE` + TÜM Türkçe metinler (TEK kopya) + `REVERSAL_PREFIX` | 120 |
| `validation.py` | **K1 servis katmanı** | 110 |
| `schemas.py` | Pydantic; `FREE_TEXT_MAX_LENGTH`; `debit/credit/total_*/balance/status` **gövdeden GELEMEZ** | 330 |
| `repository.py` | Yalnız SQL; `get_entry(for_update=True)` (`populate_existing` ŞART); `_like_escape` | 260 |
| `accounts_service.py` | Hesap planı iş kuralları | 220 |
| `service.py` | Fiş CRUD + `_apply_totals` (**K1 tek yazım**) | 330 |
| `state_service.py` | `post` + `reverse` — kilit/matris/K1 sırası + storno (**K6 sınır çağrısı BURADA**) | 180 |
| `ledger.py` | `/journal` — koşan bakiye + `carried_balance` + kanonik sıralama | 200 |
| `summary.py` | `/journal-entries/summary` — üç KPI + ay penceresi | 110 |
| `accounts_router.py` | 5 uç | 190 |
| `router.py` | 10 uç + 🔴 ROTA SIRASI ayrılmış yeri | 350 |
| migration | 3 tablo + 2 PG enum. **İzin migration'ı YOK** | 170 |

En büyüğü ~350. FAT-1'in `service.py`si 494'tü ve geçiş uçları onu tavana itiyordu →
burada `state_service`+`ledger`+`summary` **baştan ayrıldı**; SA'nın 973 satırlık borcu tekrarlanmaz.

🔴 **İKİ ZORUNLU KAYIT NOKTASI** (atlanırsa `alembic check` sahte diff üretir, testler tabloyu görmez):
- `alembic/env.py` → `from app.modules.accounting import models as accounting_models  # noqa: F401`
- `tests/conftest.py` → aynı satır

**Modül BAŞKA MODÜLÜ IMPORT ETMEZ:** `created_by_id → "users.id"` **string tablo adıyla**
(P10 `cost_cards` import çemberi tekrarlanmaz).

---

## 9. AÇILMAYANLAR (kasıtlı — "eksik" diye geri açılmaz)

| Açılmayan | Gerekçe |
|---|---|
| **Mizan** (HP:33) · **KDV Beyanı** (HP:36) · **Banka Mutabakatı** (HP:34) · **e-Fatura** (HP:35) · **Mali Tablolar** (HP:38) | Emirde açıkça MU-2+; hiçbirinin tablosu çizilmemiş |
| **Dönem kapanışı / `accounting_periods`** | K9: bu dilimde YOK; yapı hazır (`period_year/month` + `ix_..._period`) |
| **Fatura/hazine/bordro → otomatik yevmiye fişi** | MU-3; FAT-1 `approve` ucu zaten "muhasebe fişi ÜRETİLMEZ" diye yazılı (`invoicing/router.py:428-435`) |
| **`entry_no` + `numbering.py`** | Hiçbir mockup sütununda yok |
| **`parent_id` FK** | Hiyerarşi KODUN içinde (K4); türetilebilen saklanmaz |
| **Sınıf KAYDI ve etiketi** | HP:69,135,161,187 bantlarında kod sütunu YOK → kayıt değil; etiketleri kendi satırlarıyla çelişiyor (K15) |
| **`is_contra` kolonu** | `257`in parantezi için hiçbir form onay kutusu çizilmemiş (§1c) |
| **`Excel` (HP:49) / `Dışa Aktar` (E8:66)** | Biçim/kapsam çizilmemiş |
| **Proje/şantiye/maliyet merkezi kırılımı** | Üç tabloda da sütunu yok (§3); MU-3 |
| **Para birimi / kur** | `₺` metne gömülü sabit; repo geneli TRY |
| **Fişe belge eki** | BC dilimi; yükleme alanı çizilmemiş |
| **Toplu içe aktarım / Tekdüzen hesap planı seed'i** | Hiçbir mockup çizmiyor; hesaplar uçtan açılır |
| **`draft` için onay akışı (`request`/`approve`)** | K2 iki geçiş tanımlar; ara onay adımı çizilmemiş |

---

## 10. Risk / tuzak listesi

| # | Risk | Karşı önlem |
|---|---|---|
| **R1** | 🔴 `+ Yevmiye Kaydı` (E8:67) ve `+ Hesap Ekle` (HP:50) **FORMLARI çizilmemiş** | **Alan İCAT EDİLMEZ** — §11 K-Ş1 |
| **R2** | HP:187 `SINIF 5` der, kodlar `6`/`7` | **K15: satırlar kazanır.** Sunucu yalnız `class_code` döner; bant etiketi sunucu alanı değil |
| **R3** | 🔴 `Tür`ün "Aktif/Pasif"i ile `Durum` karıştırılabilir (ikisi de Türkçe'de "aktif") | Kolon adları ayrık (`account_type` vs `is_active`); docstring'de büyük harfle + bekçi testi |
| **R4** | `257`in parantezi hiçbir sunucu alanından üretilemiyor | Sunum kuralı; §11 K-Ş2 |
| **R5** | 🔴 "posted fişin satırı UPDATE edilemez" **DB'de zorlanamaz** (trigger yok) | Satır yazan **TEK yol** `service.replace_lines`; `assert_lines_editable` orada koşar; T4'te bekçi |
| **R6** | 🔴 `reversed`i bakiyeden düşürmek **çift ters kayıt** üretir | `POSTING_STATUSES` TEK kopya; test: orijinal+storno → net **tam sıfır** |
| **R7** | K1 bekçisi **İZOLE koşuda kör olabilir** (FAT-1 kalıcı dersi) | K1 testleri **dosya bütünüyle** koşulur; mutasyon kanıtı T4'te |
| **R8** | `func.now()` işlem başına SABİT → aynı `created_at` | Sıralamanın son parçası **`jl.id`**; sayfalama testi aynı işlemde 3 fiş yazar |
| **R9** | Pencere fonksiyonu LIMIT'ten SONRA hesaplanırsa her sayfa sıfırdan başlar | `carried_balance` ayrı sorgu; pencere alt sorguda, LIMIT dışta |
| **R10** | 🔴 K6: storno tarihi için `date.today()` refleksi | AST bekçisi anında kırmızı; `state_service` yalnız `timezone.today()` çağırır |
| **R11** | 🔴 ROTA SIRASI: `summary` `{entry_id}`den sonra → **422** | Ayrılmış yer + bekçi testi |
| **R12** | `SUM()` NULL yutması → bakiye BOŞ basar | `COALESCE` + ayrı test |
| **R13** | N+1: hesap başına bakiye sorgusu | TOPLU API + `before_cursor_execute` ile **ÖLÇÜLEN** test |
| **R14** | `chart_of_accounts` boş açılır (seed yok) | Bilinçli; canlı smoke'ta ÖNCE hesap açılır, sonra fiş |
| **R15** | `q`de LIKE jokeri kaçırılmazsa `%` yazan TÜM hesapları görür | `_like_escape` (kaçış karakterinin kendisi ÖNCE) |
| **R16** | `code` UNIQUE ihlali servis öncesi yakalanmazsa Türkçe mesaj kaybolur | Açık `SELECT` → `guards.ACCOUNT_DUPLICATE_CODE` |

---

## 11. 🔴 ŞEFİN BAĞLADIĞI KARARLAR (T1'in açık sorularına yanıt)

**K-Ş1 — Form mockup'ı yok, DEVAM EDİLİR; alan İCAT EDİLMEZ.**
Gövde **yalnızca çizili tablo sütunlarından** türetilir:
`entry_date` (E8:101) · `description` (E8:103 üst) · `detail_note` (E8:113 alt) ·
`lines[account_id (E8:102), debit (E8:104), credit (E8:105)]`; hesap formu için
`code`·`name`·`account_type`·`is_active` (HP:58-62). **Hiçbir alan uydurulmadı** — kural §9 "mockup'ta
eksik olan BEKLER"in kapsamı çizilmemiş *kavramlardır* (fiş tipi, fiş no, belge tarihi), çizili
sütunların yazma karşılığı değil. Emsal: FAT-1 aynı durumda aynı yolu izledi. Çizilmemiş kavramlar
§9'da AÇILMAYAN olarak durur.

**K-Ş2 — `is_contra` AÇILMAZ.** Parantez sunum kuralıdır (`name`in `(-)` son eki).
MU-2 için **açık soru** olarak kayda geçer, MU-1'de kolon açılmaz (icat yasağı).

**K-Ş3 — Yaprak kuralının TERS YÖNÜ de kapatılır.** Fiş satırı OLAN hesabın altına çocuk hesap
açmak **409** (`guards.PARENT_HAS_JOURNAL_LINES`). Yoksa `120`e satır atıp sonra `120.01` açmak
yaprak kuralını **geçmişe dönük deler** ve MU-2 mizanı çift sayar. T3'te testli.

**K-Ş4 — `GET /journal-entries` ONAYLI SAPMADIR.** Mockup'ta ekranı yoktur; K2 gereği taslakları
bulmanın **tek yolu**dur. Gerekçesiyle ROADMAP'e yazılır, "mockup'ta yok" diye geri alınmaz.
