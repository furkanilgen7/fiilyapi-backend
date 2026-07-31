# Alt-Proje 2 · P7 — İşveren Hakedişi (tasarım)

Tarih: **2026-07-31**
Repo: `backend` (dal: `feat/p5-contracts`)
Önceki bağımlı dilim: **P5 — Sözleşmeler** (bitti, `feat/p5-contracts` dalında; spec:
`2026-07-30-alt-proje-2-p5-sozlesmeler-design.md`)
Bu dilimde YAPILMAYAN kardeş iş: **Taşeron hakedişi** (`Ekran 2 - Taşeron Hakedişi.dc.html`) —
ayrı dilim; bu spec'te yalnız placeholder olarak geçer.

Kanon mockup'lar (satır numaraları bu dosyalara atıftır):

| Kısaltma | Dosya | Satır |
|---|---|---|
| **E15** | `projedesign/Ekran 15 - İşveren Hakedişi.dc.html` | 198 |
| **OLU** | `projedesign/İşveren Hakediş Oluştur.dc.html` | 229 |
| **SHK** | `projedesign/Şantiye - Hakedişler.dc.html` | 146 |
| **SHO** | `projedesign/Şantiye - Hakediş Özeti.dc.html` | 265 |
| E14 | `projedesign/Ekran 14 - Sözleşme Detay.dc.html` (bağlam) | 154 |
| POZ | `projedesign/İşveren Sözleşme - Poz Dağılımı.dc.html` (bağlam) | 192 |

---

## 0. Bu dilime girerken doğrulanan gerçekler

1. **`project_contracts` kesinti alanlarını ZATEN taşıyor** —
   `app/modules/projects/models.py:166-224` (`ProjectContract`): `advance_pct`
   (default 20), `retainage_pct` (default 5), `vat_pct` (default 20),
   `has_price_escalation`, `index_type` (`PriceIndexType` enum), `base_index_value`,
   `late_penalty_daily`, `amount`, `status`. Hakediş bu alanları **okur, yeniden açmaz**.
2. **İzin matrisi satırı ZATEN var** — `app/modules/roles/seed_data.py:94` modül
   `progress_payments`, satır 169:
   `"progress_payments": [_A, _F, _DRF, _DRF, _N, _APR, _APR, _N]`
   (sysadmin=admin · patron=full · **şef=draft** · **saha=draft** · İK=yok ·
   **muhasebe=approve** · **PM=approve** · satınalma=yok). **YENİ MODÜL AÇILMAZ,
   modül sayısı 18'de kalır** — bu dilimde `modules`/`role_permissions` migration'ı yoktur.
3. **P5 kalem altyapısı hazır** — `employer_contract_groups` + `employer_contract_items`
   (`app/modules/contracts/models.py:44-115`), `boq_items.contract_item_id`
   (`app/modules/boq/models.py:108`, kısmi benzersiz `(contract_item_id, site_id)`).
4. **Alembic baş revizyonu:** `e9e8e6a52f96` (p5_sozlesmeler) — `alembic heads` ile
   2026-07-31'de doğrulandı. Yeni migration'ın ebeveyni budur (uygulama gününde
   yeniden doğrulanır).
5. **P5'ten devreden ön bulgu (GOREV-SIRASI §2/6-2):** işveren kaleminin
   `unit_price`/`code`'u değişince dağıtılmış `boq_items` satırları **tazelenmiyor**.
   Bu spec'in §5 (fiyat otoritesi) kararı bu bulgunun cevabıdır.
6. **`site_diary` modülü bu repoda henüz YOK** (yalnız izin matrisinde satırı var,
   `seed_data.py:163`). OLU 117 "📅 Günlük kayıtlardan hesaplandı" ve SHO 86
   "Günlük kayıtlardan otomatik hesaplanan" bu dilimde **karşılanamaz** — §2.2.
7. **P5 incelemesinde gerçek bir IDOR sızıntısı yakalanmıştı** — kapsam kontrolü bu
   spec'te uç uç açık yazılmıştır (§9.0).

---

## 1. Kapsam

### 1.1 Kapsam içi

* `progress_payments` + `progress_payment_lines` tabloları (§4)
* Hesap motoru: FF katsayısı, KDV, avans mahsubu (kümülatif tavanlı), teminat (§6)
* Durum makinesi: taslak → onay bekliyor → onaylandı → ödendi (§7)
* Uçlar: liste / detay / oluştur / düzenle / durum geçişleri / silme (§9)
* E14 `progress_payment_summary` ve `contracts` liste `progress_payment_total`
  placeholder'larının gerçek veriyle doldurulması (§9.6)
* SHK sol sütunu (İşveren Hakedişleri listesi) + SHK özet kartlarının işveren yarısı
* Denetim günlüğü mesajları (§11), migration (§12), test planı (§13)

### 1.2 Kapsam DIŞI (tek tek, gerekçeli)

| Ne | Mockup kanıtı | Neden | Yanıtta karşılığı |
|---|---|---|---|
| **Taşeron hakedişi** | SHK 117-140 sağ sütun · SHK 83 "Toplam Taşeron Ödemesi" · SHO 105-108, 176-228 | Ayrı dilim (Ekran 2). Şeması bu dilimde açılmaz. | `MetricPlaceholder(pending_module="subcontractor_progress_payments")` |
| **Kar analizi** | OLU 203-222 ("Taşeron Ödemeleri", "Brüt Kar", "Kar Marjı") · SHK 85 · SHO 110-113 | Taşeron ödemesi verisi olmadan hesaplanamaz. | Aynı placeholder |
| **Günlük kayıttan miktar önerisi** | OLU 117/132/147/165 "📅 Günlük kayıtlardan hesaplandı" · SHO 86 | `site_diary` modülü yok (§0/6). Miktarlar **elle girilir**; site_diary dilimi geldiğinde öneri katmanı eklenir. | Satırda alan yok; frontend rozeti basmaz |
| **SHO ekranının tamamı** | SHO 85-86, 127-171 (günlükten birikim), 176-228 (taşeron karşılaştırma), 234-258 (trend) | Ekranın üç ana bloğundan ikisi site_diary + taşeron hakedişine bağlı. Kümülatif KPI'lar (SHO 100-103, 115-119) §9.6 özet ucundan zaten çıkar; ekran kendi dilimini site_diary sonrasında alır. | Uç açılmaz |
| **PDF çıktısı** | E15 70 "PDF" butonu | Sözleşme PDF'iyle aynı gerekçe (P5 §2.2): ayrı üretim katmanı. | Uç yok; frontend butonu devre dışı + bildirim |
| **Fiziksel ilerleme (bağımsız kaynak)** | E15 184 "Fiziksel %75" | Fiziksel ilerlemenin girildiği hiçbir form yok — alan icat edilmez. §8'de miktar-bazlı türev olarak tanımlanır, ayrı veri açılmaz. | Türev |
| **Endeks değerinin otomatik çekilmesi** | OLU 61-66 endeks türleri | TÜİK/endeks servisi entegrasyonu yok; katsayı (Dn/D0) **elle girilir** (OLU 69-70 zaten input). `index_type` yalnız etikettir. | Katsayı alanı |
| **Gecikme cezası** | — | Hiçbir hakediş mockup'ında gecikme cezası satırı yok (`late_penalty_daily` sözleşmede durur, hakedişte kesinti satırı olarak görünmüyor). İcat edilmez. | Yok |
| **Zeyilname / iş artışı** | — | Mockup yok. §6.5 tavan kuralı bu yüzden serttir; zeyilname dilimi gelince gevşetilir. | Yok |

---

## 2. Mockup okuması — ekran ekran, alan alan

### 2.1 E15 — İşveren Hakedişi (detay ekranı)

| Satır | Alan | Kaynak |
|---|---|---|
| 62 | Kırıntı: "← Hakedişler · İşveren Hakedişi" | — |
| 65 | Başlık "İşveren Hakedişi **#5**" | `sequence_no` |
| 66 | "Güneşkent A-Blok · **Temmuz 2026** · **SZL-2025-001**" | proje adı · `period_year/month` · `project_contracts.contract_no` |
| 69 | Rozet "Onay Bekliyor" (sarı) | `status = pending_approval` |
| 70 | "PDF" butonu | kapsam dışı (§1.2) |
| 71 | "Onaya Gönder" butonu | `POST …/submit` (§9.4) |
| 81-82 | Kart "Bu Hakediş ₺2,10M" | türev: bu hakedişin brütü |
| 85-86 | Kart "Toplam Hakediş ₺8,4M" | türev: kümülatif brüt (bu dahil) |
| 89-90 | Kart "Kalan ₺2,8M" | türev: `contract.amount − kümülatif` (11,2M − 8,4M) |
| 96 | "Hakediş Kalemleri" tablosu | **grup düzeyinde tutar toplulaştırması** |
| 100-104 | Kolonlar: İş Kalemi / **Sözleşme** / **Önceki** / **Bu Ay** / **Toplam** | §5-§6 kümülatif modeli; satırlar (109-135) sözleşme gruplarıdır ("Betonarme İşleri"), tutar cinsindendir |
| 136-141 | "Ara Toplam" satırı | grupların toplamı = brüt |
| 151-172 | "Ödeme Hesabı" kartı: Brüt 2.110.000 → KDV (%20) **+422.000** → Avans Kesintisi (%20) **−422.000** → Teminat Kesintisi (%5) **−105.500** → **Net Tahsil ₺2.004.500** | §6 formülleri, işaretleriyle birebir |
| 177-190 | "Sözleşme İlerlemesi": Finansal %75 / Fiziksel %75 / Süre %62 | §8 türevleri |

### 2.2 OLU — İşveren Hakediş Oluştur (form; MEVCUT mockup, bundan çalışılır)

| Satır | Alan | Karşılık |
|---|---|---|
| 21 | Başlık "İşveren Hakediş **#5** Oluştur" | `sequence_no` otomatik (maks+1) |
| 24 | "Taslak Kaydet" | `status=draft` ile POST/PATCH |
| 25 | "Onaya Gönder" | kaydet + `submit` |
| 33-39 | Bağlam şeridi: SZL-2025-001 · işveren · proje · "Poz Dağılımı →" linki | sözleşme + proje başlığından; dağılım P5 ucundan |
| 43-49 | Bilgi kutusu: "**birim fiyatlar sözleşmeden sabit gelir**… FF Katsayısı girerek düzeltilmiş birim fiyat otomatik hesaplanır. Katsayı 1,000 ise fiyat farkı yok" | §5 fiyat otoritesi + §6.1 |
| 53-76 | FF banner'ı: toggle (56) · Endeks select: Sabit Katsayı/ÜFE/TÜFE/İnşaat Maliyet Endeksi (61-66) · "Katsayı (Dn/D0)" input `1.142` step `0.001` (69-70) · "%14,2 fiyat artışı uygulanıyor" (72-73) · "Her poz için ayrı katsayı girebilirsiniz →" (75) | başlıkta genel katsayı + satırda poz-bazlı katsayı (§4.2) |
| 81 | "İşveren" — salt okunur | `projects.employer_name` |
| 82 | "Hakediş Dönemi" select "Temmuz 2026" | `period_year` + `period_month` |
| 83 | "Kapsam: A-Blok + B-Blok" — salt okunur | satırlardaki `site_id`'lerin kümesinden türev |
| 84 | "Hakediş No #5" — salt okunur | `sequence_no` |
| 91-92 | Tablo başlığı "Hakediş Kalemleri — **Şantiye Bazlı**" · "Birim fiyatlar SZL-2025-001'den · **Değiştirilemez**" | §5 |
| 97-106 | Kolonlar: Poz No / Poz Adı / Birim / **Sözl. B.F. 🔒** / **FF Katsayı** / **Düz. B.F.** / 🏗 A-Blok / 🏗 B-Blok / Toplam / Hakediş Tutarı | şantiye kolonları = poz dağılımındaki şantiyeler (POZ 82-83 ile aynı düzen) |
| 110-111, 158-159 | Grup başlıkları "A — Betonarme İşleri", "B — Kalıp İşleri" | `employer_contract_groups` |
| 114-126 | Örnek satır: `03.001` · BF ₺1.850 + "🔒 Sözleşme" alt yazısı (120) · satır katsayı input 1.142 (121) · Düz. B.F. ₺2.113 (122) · A-Blok 900 / B-Blok 420 inputları (123-124) · Toplam 1.320 (125) · Tutar 2.789.160 (126) | §4.2 satır modeli; miktar inputları = **bu dönem** miktarı |
| 151-152 | Katsayısı 1.000 olan satırda Düz. B.F. = Sözl. B.F. (gri) | katsayı satır bazında bağımsız |
| 172 | B-Blok input `value="0"` | **0 miktar meşrudur** (satır CHECK `>= 0`) |
| 178-196 | `tfoot`: TOPLAM (Brüt) 4.920.600 → KDV (%20) 984.120 → "Avans Kesintisi (**%20 · kümülatif**)" −984.120 → Teminat (%5) −246.030 → NET 4.674.570 | §6; "kümülatif" ibaresi avans tavanının kanıtı |
| 203-222 | Kar analizi kartı | kapsam dışı (§1.2) |

### 2.3 SHK — Şantiye - Hakedişler (liste görünümü)

| Satır | Alan | Karşılık |
|---|---|---|
| 24, 66-73 | Şantiye Detay sekmesi "Hakedişler" | frontend; veri §9.1 liste ucundan `site_id` filtresiyle |
| 76 | "A-Blok — Hakedişler · İşveren & Taşeron" | tek ekranda iki tür (taşeron yarısı placeholder) |
| 77 | "+ Hakediş Oluştur" | OLU'ya gider |
| 82 | Kart "Toplam İşveren Hakedişi ₺8,4M · 4 hakediş · %75" | §9.6 özet |
| 84 | Kart "Onay Bekleyen 3" | durum sayacı |
| 93-113 | İşveren Hakedişleri listesi; satır: "Hakediş **#5** — **Tem 2026**" (98) · açıklama "Kat 6–8 döşeme · %62 ilerleme" (98) · tutar ₺2,10M · rozet "Onay Bekliyor"/"Ödendi" (99/103/107/111) | `sequence_no` · dönem · **`description` alanı** · brüt · `status` |

SHK 98'deki serbest metin ("Kat 6–5 döşeme") hakedişin `description` kolonunun
kanıtıdır; "%62 ilerleme" eki süre/finansal türevden basılır, saklanmaz.

### 2.4 E14 — Sözleşme Detay (bağlam: P5'te placeholder bırakılan yerler)

| Satır | Alan | Karşılık |
|---|---|---|
| 93 | "Hakedişler" sekmesi | hakediş listesi (proje filtresi) |
| 127-147 | "Hakediş Özeti" kartı: Sözleşme Bedeli 11.200.000 · Toplam Hakediş 8.400.000 · "%75 hakkedildi" barı · **Avans Kesintisi −1.680.000** · Teminat (%5) −420.000 · Net Ödeme 6.300.000 | §9.6 özet ucu. 1.680.000 = 8.400.000 × %20 → **kümülatif avans kesintisi henüz tavana (₺2,24M, E14 85) varmamış** — §6.3 tavan matematiğinin mockup kanıtı |

### 2.5 POZ — Poz Dağılımı (bağlam: hakedişin ön şartı)

| Satır | Kanıt | Sonuç |
|---|---|---|
| 37 | "Hakediş oluşturulurken **bu dağılım baz alınır**" | hakediş satırının şantiye kolonları dağıtılmış şantiyelerdir |
| 65 | "şantiye ataması yapılmadan günlük kayıt ve **hakediş yapılamaz**" | dağıtılmamış (kalem, şantiye) çiftine hakediş satırı açılamaz — §6.5 kural |
| 72 | "Sözleşme miktarı = tüm şantiye kotaları toplamı olmalı" | tavan zinciri: hakediş kümülatifi ≤ kota ≤ sözleşme miktarı |

---

## 3. Ana tasarım kararları (özet) — ayrıntı ve alternatifler §14'te

| # | Karar | Öneri |
|---|---|---|
| D1 | Bağlanma düzeyi | Hakediş **sözleşmeye (= proje)** bağlanır, TEK kayıttır; şantiye kırılımı **satır** düzeyindedir. SHK ve E14 sekmesi aynı kaydın iki görünümüdür. |
| D2 | Kalem dayanağı | Satır `employer_contract_items`'a dayanır (+ `site_id`); `boq_items`'a DEĞİL. |
| D3 | Fiyat otoritesi | Otorite **sözleşme kalemi**; hakediş anında satıra **snapshot** dondurulur. |
| D4 | Kümülatif/dönemsel | **Dönemsel kaynak** (satırda yalnız bu dönemin miktarı), kümülatif türev. |
| D5 | Kesinti yüzdeleri | Oluşturma anında sözleşmeden **snapshot** kopyalanır. |
| D6 | Durum akışı | `draft → pending_approval → approved → paid` + `reject` (→draft). |
| D7 | Silme | Kapı `draft` + serviste `can_delete`; `approved`/`paid` **silinemez** (409). |
| D8 | Sıralılık | Aynı sözleşmede aynı anda **tek açık** (draft/pending) hakediş. |

---

## 4. Veri modeli

### 4.0 Hiyerarşi

```
Project ──1-1── ProjectContract
                     │
                     ├──1-N── EmployerContractGroup ──1-N── EmployerContractItem   (P5)
                     │                                            ▲
                     └──1-N── ProgressPayment                      │ contract_item_id (SET NULL)
                                   │                               │
                                   └──1-N── ProgressPaymentLine ───┘
                                                 │
                                                 └── site_id → Site (RESTRICT)
```

### 4.1 `progress_payments` (YENİ)

| Kolon | Tip | Null | Mockup / Not |
|---|---|---|---|
| `id` | UUID PK | — | |
| `project_id` | UUID FK → `project_contracts.project_id` **CASCADE**, indeksli | NOT NULL | D1. Sözleşme PK'si `project_id`'dir (P5 §3.2 deseni). Proje silinirse hakedişler gider |
| `sequence_no` | Integer | NOT NULL | E15 65 "#5", OLU 84. Servis üretir: proje içi maks+1 (proje kodu deseni, kalıcı karar 9). `UniqueConstraint(project_id, sequence_no)` |
| `period_year` | Integer | **NULL** | OLU 82 "Temmuz 2026". Taslakta boş olabilir (kalıcı karar 4) |
| `period_month` | Integer | **NULL** | `CHECK period_month BETWEEN 1 AND 12` (dolu ise) |
| `description` | Text | NULL | SHK 98 "Kat 6–8 döşeme" |
| `status` | Enum `progress_payment_status` | NOT NULL, default `draft`, server_default `'draft'` | §7. Sunucu varsayılanı anlamlı → NOT NULL istisnası (P5 §3.1 gerekçesinin aynısı) |
| `vat_pct` | Numeric(5,2) | NOT NULL | **Snapshot** (D5): oluşturmada `project_contracts.vat_pct`'den kopyalanır. Kullanıcı doldurmaz → NOT NULL serbest |
| `advance_pct` | Numeric(5,2) | NOT NULL | Snapshot ← `advance_pct` |
| `retainage_pct` | Numeric(5,2) | NOT NULL | Snapshot ← `retainage_pct` |
| `default_coefficient` | Numeric(8,3) | NOT NULL, default 1.000, server_default `'1.000'` | OLU 69-70 genel katsayı (Dn/D0). Yalnız **yeni satırlara** öntanımlı iner; satırdaki katsayı bağımsızdır (OLU 75) |
| `submitted_at` | timestamptz | NULL | §7 geçiş damgaları |
| `approved_at` | timestamptz | NULL | |
| `approved_by` | UUID FK → `users.id` RESTRICT | NULL | onaylayan |
| `paid_at` | timestamptz | NULL | |
| `created_by` | UUID FK → `users.id` RESTRICT | NOT NULL | `can_delete` korkuluğu ister |
| `created_at` / `updated_at` | timestamptz | NOT NULL | |

CHECK: `ck_progress_payments_month_range` (`period_month IS NULL OR period_month BETWEEN 1 AND 12`) ·
`ck_progress_payments_pct_range` (üç yüzde 0-100) ·
`ck_progress_payments_coefficient_positive` (`default_coefficient > 0`).

Enum `progress_payment_status`: `draft` (OLU 24) · `pending_approval` (E15 69 "Onay
Bekliyor") · `approved` (SHK 129 "Onaylandı" rozeti — taşeron satırında ama rozet
sözlüğü ortak) · `paid` (SHK 103 "Ödendi").

**`is_draft` kolonu AÇILMAZ** — `status` zaten taşıyor. `can_delete` protokolünün
(`app/core/access.py:47-52` `Deletable`) istediği `is_draft` niteliği modele
**property** olarak verilir: `is_draft = (status == draft)`. İki durum alanı
(P5'teki `is_draft` + `status` çifti) burada gereksizdir çünkü hakedişin durum
makinesi taslağı zaten bir durum olarak içeriyor; sözleşmede ise `status`
(aktif/tamam/beklemede) taslaklıktan bağımsız bir eksendi.

**Avans/teminat/KDV `amount` kolonları AÇILMAZ** — K3 (P5) türev ilkesinin aynısı:
brüt, KDV, kesintiler ve net **her okuyuşta satırlardan ve snapshot yüzdelerden
hesaplanır**. Snapshot'lı girdilerden deterministik türedikleri için saklamak iki
doğruluk kaynağı yaratırdı.

### 4.2 `progress_payment_lines` (YENİ)

Satır = (poz, şantiye, bu dönem miktarı). OLU tablosunun bir **satırı** poz, şantiye
kolonları (103-104) ise bu tablodaki ayrı kayıtlardır — OLU 91 "Şantiye Bazlı".

| Kolon | Tip | Null | Mockup / Not |
|---|---|---|---|
| `id` | UUID PK | — | |
| `payment_id` | UUID FK → `progress_payments.id` **CASCADE**, indeksli | NOT NULL | |
| `contract_item_id` | UUID FK → `employer_contract_items.id` **SET NULL**, indeksli | NULL | Bağ. SET NULL: kalem silinse de hakediş evrakı snapshot'la ayakta kalır (P5 §3.3 `boq_items` gerekçesinin aynısı) |
| `site_id` | UUID FK → `sites.id` **RESTRICT**, indeksli | NOT NULL | OLU 103-104. RESTRICT: hakedişi olan şantiye silinemez (P5 §7 desenine `sites/guards.py` eklemesi) |
| `code` | String(50) | NOT NULL | **Snapshot** ← kalemden (OLU 114 `03.001`) |
| `description` | Text | NOT NULL | Snapshot (OLU 116) |
| `unit` | String(50) | NOT NULL | Snapshot (OLU 119 `m³`) |
| `contract_unit_price` | Numeric(18,2) | NOT NULL | **Snapshot** ← `employer_contract_items.unit_price` (OLU 100 "Sözl. B.F. 🔒", 120 "🔒 Sözleşme") — D3 |
| `coefficient` | Numeric(8,3) | NOT NULL, default 1.000, server_default `'1.000'` | OLU 121 satır katsayısı, step 0.001. `CHECK coefficient > 0` |
| `quantity` | Numeric(14,3) | NOT NULL | **Bu dönemin** miktarı (D4). `CHECK quantity >= 0` — OLU 172 `value="0"` kanıtıyla 0 meşru (BOQ'daki `> 0`'dan bilinçli fark) |
| `group_name` | String(200) | NULL | Snapshot ← `employer_contract_groups.name` (OLU 111 grup başlığı; kalem/grup silinse de evrak gruplu basılır) |
| `sort_order` | Integer | NOT NULL default 0 | |
| `created_at` / `updated_at` | timestamptz | NOT NULL | |

Kısıt: kısmi benzersiz indeks
`uq_progress_payment_lines_item_site (payment_id, contract_item_id, site_id)
WHERE contract_item_id IS NOT NULL` — bir hakedişte aynı poz×şantiye hücresi tek
satırdır (OLU tablosunda her hücre tek input).

Türev alanlar (saklanmaz, §6.1): `adjusted_unit_price` · `line_total` ·
`previous_quantity` / `previous_amount` (önceki hakedişlerden) · `cumulative_*`.

---

## 5. ÖN KARAR — fiyat otoritesi (P5 devir bulgusunun cevabı)

**Sorun:** işveren kaleminin `unit_price`/`code`'u değişince dağıtılmış `boq_items`
tazelenmiyor (GOREV-SIRASI §2). Hakediş hangi fiyatı esas alacak?

**Seçenekler:**

1. **BOQ satırı otorite.** Reddedilir: (a) bayat olduğu bilinen kopyadır (bulgunun
   kendisi); (b) OLU 92 açıkça "Birim fiyatlar **SZL-2025-001'den**" diyor — SZL
   numarası sözleşmenin kendisidir; (c) proje-geneli bir hakedişin şantiye-yerel
   kopyalara dayanması her şantiyede farklı fiyat riskini içeri alır.
2. **Sözleşme kalemi otorite, canlı okuma.** Reddedilir: onaylanmış hakedişin
   tutarı, sözleşme kalemi sonradan düzeltilince **geriye dönük değişirdi** —
   muhasebeleşmiş evrak oynar, denetlenemez.
3. **Sözleşme kalemi otorite + hakediş anında satıra snapshot.** ✅ **ÖNERİLEN.**
   * Okuma/öneri her zaman `employer_contract_items.unit_price`'tan yapılır
     (OLU 100 "Sözl. B.F. 🔒" — kullanıcı değiştiremez, OLU 92 "Değiştirilemez").
   * Satır oluştuğunda `code/description/unit/unit_price/group_name` satıra
     kopyalanır ve **bir daha güncellenmez** (taslakta bile; §5.1 tazeleme ucu hariç).
   * BOQ satırlarının bayat fiyatı hakedişi **etkileyemez** — bulgu hakediş için
     kapanır. BOQ ekranının kendi tazelenmesi ayrı iş olarak §15'te kalır.

### 5.1 Taslakta tazeleme

Sözleşme kalemi taslak hakediş açıkken değişirse: taslağın snapshot'ı **kendiliğinden
değişmez**. Detay yanıtı satır başına `is_price_stale: bool`
(`contract_unit_price != kalem.unit_price`, bağ koptuysa `null`) döner; kullanıcı
isterse `POST …/refresh-prices` (§9.3) ile **yalnız taslakta** snapshot'ı tazeler.
`pending_approval` ve sonrasında tazeleme yoktur — onaya giden evrak sabittir.

---

## 6. Hesap kuralları

Tüm parasal ara sonuçlar `Decimal`, `Numeric(18,2)` ölçeğinde
`quantize(Decimal("0.01"), ROUND_HALF_UP)` ile yuvarlanır
(`distribution.py:62` `_quantize_money` deseni genelleştirilir). Miktar
`Numeric(14,3)`, katsayı `Numeric(8,3)`, yüzdeler `Numeric(5,2)`.

### 6.1 Satır

```
adjusted_unit_price = quantize2(contract_unit_price × coefficient)     # OLU 102 "Düz. B.F."
line_total          = quantize2(adjusted_unit_price × quantity)        # OLU 106 "Hakediş Tutarı"
```

> **Mockup sapması (karar sorusu K5):** OLU düzeltilmiş fiyatı **tam liraya**
> yuvarlıyor: 1.850×1,142 = 2.112,70 iken ₺2.113 gösterip 2.113×1.320 = 2.789.160
> hesaplıyor (OLU 122/126; aynı desen 137/141: 2.100×1,142=2.398,20→2.398×300=719.400;
> 170/174: 185×1,142=211,27→211×2.880=607.680). Önerimiz **kuruş hassasiyeti**
> (quantize2, yukarıdaki formül): tam-lira yuvarlama mockup'ın ondalıksız gösterim
> tercihi olarak okunur; kuruş atmak gerçek parayı bozar. Bu, "%100 mockup"
> kuralından **hesap düzeyinde** bir sapma olduğu için kullanıcı onayına sunulur (§16/K5).

### 6.2 Brüt ve KDV

```
gross = Σ line_total                                   # OLU 179-180, E15 154-155
vat   = quantize2(gross × vat_pct / 100)               # OLU 183-184, E15 158-159 (+ işaretli)
```

### 6.3 Avans mahsubu — kümülatif tavanlı

`OLU 187` "Avans Kesintisi (**%20 · kümülatif**)" tavanın kanıtıdır; E14 136-137
(kümülatif kesinti 1.680.000 < toplam avans 2.240.000, E14 85) tavana henüz
varılmamış örneği gösterir.

```
advance_total     = quantize2(contract.amount × contract.advance_pct / 100)   # E14 85 "%20 · ₺2,24M"
advance_recovered = Σ (önceki approved/paid hakedişlerin advance_deduction'ı)
advance_deduction = min( quantize2(gross × advance_pct / 100),
                         max(advance_total − advance_recovered, 0) )
```

`contract.amount` NULL ise (taslak sözleşme) tavan uygulanamaz → hakediş **onaya
gönderilemez** (§7 zorunluluk kuralı; hata `CONTRACT_AMOUNT_REQUIRED`).

### 6.4 Teminat ve net

```
retention = quantize2(gross × retainage_pct / 100)     # E15 166-167, OLU 191-192
net       = gross + vat − advance_deduction − retention  # E15 170-171, OLU 195-196
```

**Sayısal doğrulama (E15 verisi):** gross 2.110.000 · vat = 2.110.000×0,20 =
**422.000** ✓ (159) · advance = min(2.110.000×0,20; 2.240.000−1.258.000*) =
**422.000** ✓ (163) · retention = 2.110.000×0,05 = **105.500** ✓ (167) · net =
2.110.000+422.000−422.000−105.500 = **2.004.500** ✓ (171).
(*E14 127-147 dört önceki hakedişin kümülatif tablosuyla tutarlı.)

**Sayısal doğrulama (OLU verisi, kuruş kuralıyla):** 03.003 satırı katsayı 1,000 →
21.500×61,2 = 1.315.800 ✓ (156). Katsayılı satırlar §6.1 notundaki farkı verir —
K5 kararına bağlı.

### 6.5 Miktar korkulukları (tutarlılık — her durumda koşar)

1. **Dağıtım ön şartı:** satır ancak o (kalem, şantiye) çiftinde dağıtılmış BOQ
   satırı (`boq_items.contract_item_id = kalem AND site_id = şantiye`) varsa
   açılabilir — POZ 65 "şantiye ataması yapılmadan … hakediş yapılamaz".
   Hata: `ITEM_NOT_DISTRIBUTED = "Bu poz seçilen şantiyeye dağıtılmadı; önce poz dağılımını yapın."` (422)
2. **Kota tavanı:** `quantity + Σ(diğer approved/paid hakedişlerde aynı çiftin miktarı)`
   ≤ o çiftin BOQ kotası (`boq_items.quantity`). POZ 37+72 zinciri: kota şantiyenin
   tavanıdır. Hata: `QUANTITY_EXCEEDS_QUOTA = "Kümülatif hakediş miktarı şantiye kotasını aşamaz."` (422).
   Zeyilname dilimi gelene dek serttir (§1.2).

   **Küme SIRASIZDIR — kota ≠ §6.6 "Önceki" (H6 denetimi K1, 2026-07-31):** tavanın
   dayandığı küme, **kaydın kendisi hariç TÜM `approved|paid` hakedişlerdir**;
   `sequence_no` GÖZETİLMEZ. §6.6'nın GÖSTERİM kolonları (`previous_*`/`cumulative_*`)
   ise sıra tabanlı KALIR (`sequence_no <`). İki tanım BİLEREK ayrıdır ve tek
   fonksiyonun (`lines.completed_totals`) iki modu olarak uygulanır; ikinci bir
   toplama yolu açılmaz.

   *Bulgunun gerekçesi:* kota bir TOPLAM kısıtıdır, kronolojik değildir. Sıra
   tabanlı okunduğunda tavan **onay sırası değiştirilerek** meşru uçlarla
   aşılabiliyordu (kota 1.000): seq1'e 600 yaz → submit → approve · seq2'ye 400 yaz
   → submit (toplam sınırda) · seq1'i `unapprove` + `reject` ile taslağa döndür →
   satırı 1.000'e yükselt (yazma kontrolü `seq < 1` baktığı için seq2'yi görmez) →
   submit · seq2'yi onayla · seq1'i onayla ⇒ onaylı toplam **1.400 > 1.000**, hiçbir
   uç hata vermiyordu. Kural hem `PUT …/lines` yazımında hem `approve` yeniden
   doğrulamasında tam kümeyi kullanır (yalnız onayda düzeltmek yazma anındaki
   sızıntıyı açık bırakırdı). Uçtan uca kanıt:
   `test_transitions.py::test_onay_sirasi_degistirerek_kota_asma_zinciri_kapali`.

   **Onaylı sapma — kalemi düşmüş satır kümülatiften çıkar (H6 denetimi D3):**
   `contract_item_id IS NULL` olan satır (kalem silinmiş, FK `SET NULL`) hücre
   kimliğini kaybettiği için hangi (kalem, şantiye) çiftine ait olduğu BİLİNEMEZ;
   hem kota toplamasından hem `approve` yeniden doğrulamasından ATLANIR. Sonuç:
   o miktar kümülatif muhasebeden KALICI olarak düşer. Alternatif — onayı
   engellemek — evrakı kilitlerdi (§4.2 snapshot ilkesi). Bilinçli kabul edilmiştir.

   **İnceltme — kontrol yalnız ARTIŞTA koşar (kullanıcı kararı 2026-07-31, H5
   denetimi O1):** karşılaştırma satırın **mevcut kayıtlı miktarına** göre yapılır;
   miktar azaltılıyorsa (ve `0` gönderiliyorsa) kontrol HİÇ koşmaz. Gerekçe
   kilitlenmedir: kota sonradan düşürülürse (dağıtım revize edilir) taslakta duran
   satır zaten aşmış olur — kural azaltmaya da uygulansaydı kullanıcı `quantity: 0`
   göndererek bile taslağı kurtaramaz, hakediş düzeltilemez hâle gelirdi. **Yeni
   satırda "mevcut miktar" 0'dır**, yani kotayı aşan yeni satır bu inceltmeden
   faydalanmaz ve yine 422 alır; miktarı artırarak kotayı geçmek de yine 422'dir.
3. Şantiye projeye ait olmalı: `SITE_PROJECT_MISMATCH` (P5 metni aynen).
4. Kalem bu projenin sözleşmesine ait olmalı — aksi 422 (IDOR yüzeyi, §9.0).

### 6.6 Türev göstergeler (E15 tablo kolonları)

Poz p, şantiye s için; `prev = sequence_no'su küçük VE status ∈ {approved, paid}`
hakedişler (D8 sayesinde küme nettir — açık hakediş tek olduğundan "önceki"
belirsizliği yoktur).

> **Bu tanım YALNIZ GÖSTERİM içindir.** §6.5/2 kota tavanı BAŞKA bir kümeden
> okur (sırasız, kendisi hariç tüm `approved|paid`) — ayrımın gerekçesi §6.5/2'de.
> Kolonların sıra tabanlı davranışı `test_lines.py::test_onayli_hakedisin_detayinda_kendi_miktari_onceki_sayilmaz`
> ile sabitlenmiştir.

```
previous_amount(p)   = Σ prev satır line_total          # E15 102 "Önceki"
this_amount(p)       = bu hakedişin satır toplamı        # E15 103 "Bu Ay"
cumulative_amount(p) = previous + this                   # E15 104 "Toplam"
contract_amount(p)   = kalem.quantity × kalem.unit_price # E15 101 "Sözleşme"
```

E15 96-141 tablosu bunların **grup düzeyinde toplamıdır** (satırlar "Betonarme
İşleri" gibi grup adları, 109/116/123/130); yanıt hem satır hem grup toplulaştırması döner.

---

## 7. Durum makinesi + izin kapıları

Roller (matris `seed_data.py:169`): şef/saha = **draft** (scope=project) ·
muhasebe/PM = **approve** · patron = full · sysadmin = admin. `AccessLevel` sırası
`none < view < draft < request < approve < full < admin` (`access.py:6-18`) —
`approve` seviyesi `draft`'ı, `full` ikisini de kapsar (`satisfies`).

| Geçiş | Uç | Asgari seviye | Ek koşul |
|---|---|---|---|
| — → `draft` (oluştur) | `POST /projects/{id}/progress-payments` | **draft** | D8: sözleşmede açık (draft/pending) hakediş yoksa; sözleşme kaydı var olmalı |
| `draft` düzenleme | `PATCH` + satır uçları | **draft** | yalnız `status=draft` iken; scope=project olan şef kendi projesinde |
| `draft → pending_approval` | `POST …/submit` | **draft** | zorunluluk kuralları koşar (aşağıda) — E15 71 / OLU 25 "Onaya Gönder" |
| `pending_approval → approved` | `POST …/approve` | **approve** | `approved_by/approved_at` damgalanır |
| `pending_approval → draft` | `POST …/reject` | **approve** | gövdede opsiyonel `reason` (denetim günlüğüne); mockup'ta ret ekranı yok → ek UI gerekiyorsa **kullanıcıdan mockup istenmeli** |
| `approved → paid` | `POST …/mark-paid` | **approve** | `paid_at` damgalanır. Ödeme kaydı formu mockup'ta yok → tek tıkla işaretleme; ödeme detayı (tarih/banka) isteniyorsa **kullanıcıdan mockup istenmeli** |
| `approved → pending_approval` (geri çek) | `POST …/unapprove` | **admin** | yalnız `paid` değilken; D7 silme yolunun ön adımı |
| silme | `DELETE` | §7.1 | |

Tanımsız her geçiş 409 `INVALID_STATUS_TRANSITION = "Bu durumdan bu işleme geçilemez."`.

**Onaya gönderme zorunluluk kuralları** (yalnız `submit`'te; taslak serbest —
kalıcı karar 4 deseni, `guards.py` tek kopya):

| Kural | Hata |
|---|---|
| Dönem dolu | `PERIOD_REQUIRED = "Hakediş dönemi seçiniz."` |
| En az bir satır VE Σ line_total > 0 | `LINES_REQUIRED = "En az bir kalemde miktar giriniz."` |
| `contract.amount` dolu | `CONTRACT_AMOUNT_REQUIRED = "Sözleşme bedeli girilmeden hakediş onaya gönderilemez."` (§6.3 tavanı için) |
| §6.5 tutarlılık kuralları | (zaten her yazımda koşuyor) |

**Eşzamanlılık:** durum geçişleri hakediş satırını `SELECT … FOR UPDATE` ile
kilitleyerek koşar (P5 devir bulgusu 4'ün burada tekrarlanmaması için; iki onay
yarışı `approved_at` çifte damgalayamaz). D8 "tek açık hakediş" kontrolü de aynı
kilit altında yapılır.

### 7.1 Silme (D7) — P5 istisnasıyla karşılaştırma

P5'te `DELETE /subcontractor-contracts/{id}` kapısı `_FULL` + serviste `can_delete`
yapılmıştı; gerekçe: kapı `_ADMIN` olsaydı taslak istisnası ölü kural olurdu (P5 §6.5).
Burada durum daha da keskin: taslağı üreten roller (şef/saha) **draft**
seviyesindedir — kapı `_FULL` bile olsa kendi taslaklarını silemezlerdi.

**Öneri:** kapı `require_permission("progress_payments", AccessLevel.draft)` +
serviste iki katman:

1. `status ∈ {approved, paid}` → **409** `PAYMENT_NOT_DELETABLE = "Onaylanmış veya
   ödenmiş hakediş silinemez."` — **admin dahil**. Muhasebeleşmiş evrak yok edilmez;
   admin gerekirse önce `unapprove` ile durumu geri çeker (denetim izli iki adım).
   Bu, kalıcı karar 2'nin ("silme = admin") ihlali değil **daraltılmasıdır**:
   kalan silinebilir kümede admin koşulsuz siler.
2. `status ∈ {draft, pending_approval}` → `can_delete(actor, level, record)`
   (`access.py:55`): admin koşulsuz; `draft`+ seviye yalnız **kendi taslağını**
   (`created_by = actor AND is_draft`). `pending_approval` kaydı admin-dışı kimse
   silemez (is_draft=false).

**Kilit (H8 denetimi K1, 2026-07-31 bulgusu):** silme de bir YAZMA işlemidir —
yukarıdaki iki katman `visible_payment_locked` (§7'nin `SELECT … FOR UPDATE`
kilidi, sözleşme → hakediş sırası) ile kilitlenmiş satır üzerinden kararlaştırılır.
Kilitsiz okuma (`_visible_payment`) kullanılırsa eşzamanlı bir `approve` katman-1
kontrolünü TOCTOU ile atlatıp `approved`/`paid` kaydı silebilir — bu bölüm ilk
yazıldığında kilitten hiç bahsetmiyordu, kör nokta buradan doğdu.

---

## 8. Sözleşme İlerlemesi göstergeleri (E15 177-190)

| Gösterge | Formül | Kaynak |
|---|---|---|
| Finansal (E15 180) | `kümülatif brüt / contract.amount × 100` | tutar bazlı, FF **dahil** |
| Fiziksel (E15 184) | `Σ(küm. miktar × sözleşme BF) / Σ(kalem.quantity × kalem.unit_price) × 100` | miktar bazlı, FF **hariç** — bağımsız veri açılmaz (§1.2), ikisi FF katsayısı 1 iken eşittir (E15'te ikisi de %75) |
| Süre (E15 188) | `(bugün − project.start_date + 1) / (end_date − start_date + 1) × 100`, 0-100'e kırpılır | kalıcı karar 9: süre uç-dahil |

Tarih/tutar eksikse ilgili gösterge `null` döner (zarif düşüş + frontend bildirimi).

---

## 9. API uçları

Router: `app/modules/progress_payments/` (yeni modül dizini; izin modülü zaten var).
Kapılar: `_VIEW/_DRAFT/_APPROVE/_ADMIN = require_permission("progress_payments", …)`.

### 9.0 Kapsam ve 404 (IDOR)

**Her uç** `projects.service.visible_projects` süzgecinden geçer; şef/saha
`Scope.project` olduğundan yalnız atanmış projelerinin hakedişini görür. Görünmeyen
projedeki gerçek hakediş ile var olmayan kimlik **ayırt edilemez 404** döner
(GOREV-SIRASI §3 sabit kural; P5 incelemesindeki IDOR dersi). Somut olarak:

* `GET/PATCH/DELETE /progress-payments/{id}` → kayıt bulunur, projesi görünür değilse
  **404** (403 değil — varlık sızdırır).
* Satır uçları hakediş üzerinden aynı süzgeci uygular.
* `site_id` filtresi/satırı: şantiye başka projenin ise 422 `SITE_PROJECT_MISMATCH`
  (var olan ama erişilemeyen şantiye kimliği doğrulanamaz bilgi sızdırmaz çünkü
  hata, çiftin uyumsuzluğunu söyler, şantiyenin varlığını değil).

### 9.1 Liste ve detay

| Uç | Kapı | Not |
|---|---|---|
| `GET /progress-payments?project_id=&site_id=&status=` | `_VIEW` | SHK 93-113 listesi. `site_id` filtresi satırlarda EXISTS ile. Öğe: `id, project_id, project_name, sequence_no, period_year, period_month, description, status, gross_total, net_total` |
| `GET /progress-payments/{id}` | `_VIEW` | E15 tamamı: başlık (65-66), durum (69), özet kartlar (81-90), satırlar + grup toplulaştırması (96-141, §6.6), ödeme hesabı (151-172, §6.2-6.4), ilerleme (177-190, §8), `is_price_stale` bayrakları (§5.1) |

### 9.2 Oluşturma ve düzenleme (yalnız `draft`)

| Uç | Kapı | Not |
|---|---|---|
| `POST /projects/{project_id}/progress-payments` | `_DRAFT` | Gövde: `period_year/month?, description?, default_coefficient?, lines[]?` — satırlar iç içe atomik (`sites` deseni). `sequence_no` sunucu üretir. Sözleşme yoksa 422 `NO_EMPLOYER_CONTRACT = "Bu projenin işveren sözleşmesi yok."`; açık hakediş varsa 409 `OPEN_PAYMENT_EXISTS = "Bu sözleşmede açık bir hakediş var; önce onu tamamlayın."` (D8) |
| `PATCH /progress-payments/{id}` | `_DRAFT` | Başlık alanları. `status=draft` değilse 409 `INVALID_STATUS_TRANSITION` |
| `PUT /progress-payments/{id}/lines` | `_DRAFT` | **Ekranın tamamı** tek gövdede: `{lines: [{contract_item_id, site_id, quantity, coefficient?}]}` — OLU formu tek "Taslak Kaydet" ile yazar (24). Birleştirme DEĞİL **değiştirme** semantiği: gövdede olmayan satır SİLİNİR (P5 dağılımının birleştirme kuralının tersi — form her kaydedişte tam tabloyu gönderir; fark frontend kontratına yazılır, §10) |

Satır bazlı `POST/PATCH/DELETE …/lines/{line_id}` uçları **açılmaz** (YAGNI: OLU
tek toplu kaydetme yüzeyi gösteriyor).

### 9.3 Fiyat tazeleme (§5.1)

`POST /progress-payments/{id}/refresh-prices` → `_DRAFT` · yalnız `draft` · bağı
kopmamış satırların snapshot beşlisini kalemden yeniden kopyalar · yanıt
`{refreshed_count}` · denetim günlüğüne yazılır.

### 9.4 Durum geçişleri (§7)

`POST /progress-payments/{id}/submit` `_DRAFT` ·
`…/approve` `_APPROVE` · `…/reject` `_APPROVE` · `…/mark-paid` `_APPROVE` ·
`…/unapprove` `_ADMIN`. Hepsi `SELECT … FOR UPDATE` kilidiyle.

### 9.5 Silme

`DELETE /progress-payments/{id}` → kapı `_DRAFT` + serviste §7.1 kuralları.

### 9.6 Özet (E14 sekmesi + SHK kartları)

`GET /projects/{project_id}/progress-payments/summary` → `_VIEW`
Yanıt: `contract_amount` · `cumulative_gross` (E14 130) · `progress_pct` (E14 132) ·
`advance_deduction_total` (E14 137) · `retention_total` (E14 141) · `net_total`
(E14 145) · `payment_count` (SHK 82 "4 hakediş") · `pending_count` (SHK 84) ·
`remaining = contract_amount − cumulative_gross` (E15 89-90).

**P5 placeholder'larının doldurulması:** `EmployerContractDetail.progress_payment_summary`
ve `ContractListItem.progress_pct` / `ContractSummary.progress_payment_total`
(`contracts/schemas.py:83-101`) artık `MetricPlaceholder` yerine gerçek değer döner;
`pending_modules` listelerinden (`schemas.py:495`) `"progress_payments"` çıkarılır.
**Dikkat — P5 devir bulgusu 3:** `MetricPlaceholder(available=True, …)` çelişkili
sözleşmesi; buradaki değişim frontend'in `pending_module` varlığına dallanma
riskini ortadan kaldırma fırsatıdır — şema tarafında alan tipi düz değere döner
(breaking change frontend'e kontratla bildirilir, §10).

### 9.7 Hata kodları özeti

| Kod | Durumlar |
|---|---|
| 403 | modül izni yetersiz (kapı) |
| 404 | kayıt yok VEYA proje görünmüyor (ayırt edilemez) |
| 409 | `OPEN_PAYMENT_EXISTS` · `INVALID_STATUS_TRANSITION` · `PAYMENT_NOT_DELETABLE` · `DUPLICATE_CELL` |
| 422 | `PERIOD_REQUIRED` · `LINES_REQUIRED` · `CONTRACT_AMOUNT_REQUIRED` · `ITEM_NOT_DISTRIBUTED` · `QUANTITY_EXCEEDS_QUOTA` · `SITE_PROJECT_MISMATCH` · `ITEM_PROJECT_MISMATCH` · `NO_EMPLOYER_CONTRACT` · Pydantic doğrulamaları |

---

## 10. Frontend kontratı notları

1. **BFF `ALLOWED_ROOTS`'a yeni kök: `progress-payments`.** Eklenmezse modül yalnız
   canlıda 404 verir (GOREV-SIRASI §3 BFF tuzağı; jsdom testleri görmez). `projects`
   kökü altındaki iç içe uçlar mevcut `projects` köküyle geçer.
2. `PUT …/lines` **değiştirme** semantiğidir (gövdede olmayan satır silinir) —
   P5 dağılımının `PUT …/distribution` **birleştirme** semantiğinin tersi. İkisi
   yan yana kullanılacağı için bu fark kontrata açıkça yazılır.
3. Satır `quantity` için **`0` meşrudur** (OLU 172) — P5'in "boş hücre `null`,
   `0` 422" kuralı dağılıma özgüdür, hakedişe taşınmaz.
4. `MetricPlaceholder` → düz değer geçişi (§9.6) `contracts` yanıt şemalarında
   kırıcı değişikliktir; `openapi.json` elle kopyalanıp `gen:api` yenilenir.

   **H9'da uygulanan kesin liste (2026-07-31) — `gen:api` bu değişiklikle
   BİRLİKTE gitmeli, aksi hâlde sözleşme ekranları çalışmaz:**

   | Alan | Eski | Yeni |
   |---|---|---|
   | `ContractSummary.progress_payment_total` | `MetricPlaceholder` | `Decimal \| None` — işveren listesinde kümülatif brüt toplamı, taşeron listesinde `null` |
   | `ContractListItem.progress_pct` | `MetricPlaceholder` (işverende `available=true` + `pending_module` ÇELİŞKİSİ, P5 devir bulgusu 3) | `Decimal \| None` — §8 finansal ilerleme; bedel yok/0 ise `null`; taşeronda her zaman `null` |
   | `EmployerContractDetail.progress_payment_summary` | `null` | `ProgressPaymentSummary` (§9.6 gövdesi, hakediş yoksa sıfırlarla) |
   | `EmployerContractDetail.pending_modules` | `["progress_payments", "project_schedule", "documents"]` | `["project_schedule", "documents"]` |
   | `SubcontractorContractDetail.pending_modules` | `["progress_payments", "documents"]` | `["subcontractor_progress_payments", "documents"]` — **çıkarılmadı, yeniden adlandırıldı**: buradaki yer tutucu TAŞERON hakedişidir (§1.2), işveren hakedişi değil |

   Frontend'in `pending_module` **varlığına dallanan** kodu bu üç alanda artık
   gerçek değeri GİZLER — dallanma kaldırılmalıdır (P5 devir bulgusu 3'ün
   kapanışı: `MetricPlaceholder(available=True, …)` çelişkisi bu alanlarda
   ortadan kalktı).

   `sites` modülünün kartlarındaki `progress_payments` yer tutucuları (SHK
   şantiye kartları, `sites/schemas.py`) bu dilimde **DEĞİŞMEDİ** — plan H9
   dosya listesi yalnız `contracts`'ı kapsar; şantiye kartları verisini §9.6
   özet ucundan alır ve kendi diliminde bağlanır.
5. FF toggle'ı (OLU 56): `project_contracts.has_price_escalation = false` olan
   sözleşmede frontend katsayı kolonunu kilitler (1,000); backend yine de gelen
   katsayıyı kabul eder mi? **Hayır** — tutarlılık kuralı: `has_price_escalation =
   false` iken `≠ 1` katsayı gönderimi 422
   (`ESCALATION_DISABLED = "Bu sözleşmede fiyat farkı şartı yok."`).

   **Onaylı sapma — kullanıcı kararı 2026-07-31 (H5 denetimi Y1).** İlk metin
   yalnız satır `coefficient` "gönderimi"nden söz ediyordu; kural iki yönde
   düzeltildi:

   * **Başlık da kapsanır.** `default_coefficient ≠ 1` gönderimi de aynı 422'yi
     alır — hem `POST /projects/{id}/progress-payments` hem
     `PATCH /progress-payments/{id}` yolunda. Aksi hâlde FF'siz sözleşmede
     `default_coefficient = 1.4` kabul edilir, sonra o hakedişin her satırı kilide
     takılırdı: hakediş **doğuştan kullanılamaz** olurdu.
   * **Saklanan değerler grandfather'lanır.** Kilit YALNIZ bu istekte **gelen**
     değere uygulanır, saklanan eski katsayılara geriye dönük UYGULANMAZ. Gerekçe
     yine kilitlenmedir: FF açıkken katsayılı satır yazılmış bir sözleşmede FF
     sonradan kapatılırsa, kural "satıra yazılacak katsayı" üzerinden koşsaydı
     taslak bir daha hiçbir şekilde kaydedilemezdi (kullanıcı katsayı göndermese
     bile 422). Artık katsayısız gövde 200 döner ve eski katsayı korunur; FF
     kapalıyken **yeni** `≠ 1` katsayı gönderimi yine 422'dir.

   Kural tek kopya `guards.validate_coefficient`'tadır; üç çağıran (`service.create`,
   `service.update`, `lines._resolve`) onu ÇAĞIRIR, kopyalamaz.
6. Sunucu uzunluk sınırlı alanlara `maxLength` (sessiz 422 sınıfı).
7. E15 70 "PDF" ve OLU 203-222 kar analizi bu dilimde boş — zarif düşüş +
   kullanıcıya bildirim, sessiz atlama yok.

   **Aynı kuralın satır tarafındaki izdüşümü (H5 denetimi O3):** kalemi silinmiş
   satır (`contract_item_id IS NULL`, FK `SET NULL`) `PUT …/lines` gövdesinden
   ADRESLENEMEZ — gövde tablonun tamamı olduğu için ilk kaydetmede düşer. Bu
   kaçınılmazdır ama sessiz olamaz: yanıt (`ProgressPaymentDetail`) **`dropped_orphan_count`**
   alanıyla kaç satırın düştüğünü bildirir; frontend `> 0` iken kullanıcıya uyarı
   gösterir. Okuma uçlarında (`GET`/`POST`/`PATCH`) alan her zaman `0`'dır.
   409 ile önden onay istenip ikinci tura çıkılmaz — mockup'ta böyle bir adım yok.

---

## 11. Denetim günlüğü

`app/modules/audit/messages.py` (mevcut adlandırma deseni; okuma uçları yazmaz):

```
progress_payment_created / updated / deleted        (project_name, sequence_no)
progress_payment_submitted / approved / rejected /
    paid / unapproved                               (project_name, sequence_no)
progress_payment_lines_saved                        (project_name, sequence_no, count)
progress_payment_prices_refreshed                   (project_name, sequence_no, count)
```

---

## 12. Migration

Tek revizyon, ebeveyn `e9e8e6a52f96` (uygulama günü `alembic heads` ile yeniden
doğrulanır — varsayılmaz).

Upgrade sırası:
1. Enum `progress_payment_status`
2. `progress_payments` (FK'ler: `project_contracts` CASCADE, `users` RESTRICT ×2)
3. `progress_payment_lines` (FK'ler: `progress_payments` CASCADE,
   `employer_contract_items` SET NULL, `sites` RESTRICT) + kısmi benzersiz indeks

**İzin migration'ı YOKTUR** — modül ve 8 satır seed'de zaten var (§0/2).

Downgrade: ters sıra **ve `DROP TYPE progress_payment_status`** — Postgres enum'ı
tabloyla silinmez; unutulursa ikinci upgrade patlar (iki kez yaşanmış tuzak,
GOREV-SIRASI §3).

Nullability (kalıcı karar 4): kullanıcının doldurduğu alanlar (`period_year/month`,
`description`) NULL; sunucu ürettiği/kopyaladığı alanlar (`sequence_no`, `status`,
snapshot yüzdeler, katsayılar, `created_by`) NOT NULL — gerekçe canlı veri değil,
taslak desteğidir. Canlıda veri var ama önemsiz; yine de kural bozulmaz.

Migration testi **açık revizyon id'sine** sabitlenir; `head` / `-1` KULLANILMAZ.

---

## 13. Test planı

* **Birim:** hesap motoru (§6 formülleri — E15 ve OLU sayılarıyla altın testler;
  yuvarlama kenarları; avans tavanı: tavana varmadan / tam varınca / aşınca) ·
  `guards.py` submit kuralları · `can_delete` çapraz tablosu (rol × durum × sahiplik)
* **Entegrasyon:** her uç 200/201/204 · 403 · 404 (yok + görünmez proje ayırt
  edilemez) · 409 (açık hakediş, geçersiz geçiş, silinemez) · 422 (tam liste §9.7)
* **IDOR negatif seti:** başka projenin hakedişini okuma/PATCH'leme · başka
  projenin şantiyesine satır yazma · şef (scope=project) atanmadığı projede 404
* **Durum makinesi:** tüm geçerli geçişler + tüm geçersiz çiftler 409 · submit'te
  zorunluluk 422'leri · reject sonrası yeniden düzenlenebilirlik · eşzamanlı çifte
  approve (FOR UPDATE)
* **Snapshot:** kalem fiyatı değişince taslak etkilenmez · `is_price_stale` döner ·
  `refresh-prices` yalnız taslakta · kalem silinince satır SET NULL + evrak okunur kalır
* **D8:** açık hakediş varken POST 409; approve sonrası yeni POST serbest
* **Kota:** kümülatif aşım 422 · tam sınırda kabul · dağıtılmamış çift 422
* **Migration:** açık revizyon id'siyle upgrade → downgrade → upgrade (yalnız
  yerel DB — `.env`'deki `TEST_DATABASE_URL` uzak Railway'dir, DOKUNULMAZ;
  `createdb`/`dropdb` akışı GOREV-SIRASI §3)

TDD zorunlu: önce test, KIRMIZI GÖR, sonra kod; ilk koşuda yeşil test için mutasyon
denetimi.

---

## 14. Karar gerekçeleri (uzun biçim)

### D1 — Bağlanma düzeyi: sözleşme (proje), şantiye satırda

* **Seçenek A: şantiyeye bağlı ayrı hakedişler.** SHK ekranı şantiye altında durduğu
  için ilk bakışta doğal. Reddedilir: OLU tek formda **iki şantiyenin** kolonunu
  yan yana gösteriyor (103-104) ve "Kapsam: A-Blok + B-Blok" (83) tek hakedişin iki
  şantiyeyi kapsadığını açıkça söylüyor; `sequence_no` da sözleşme düzeyinde tekil
  ("#5", işverene giden evrak numarası). Şantiye başına ayrı kayıt, işverene giden
  tek evrakı ikiye bölerdi.
* **Seçenek B (önerilen): sözleşmeye bağlı tek kayıt; şantiye kırılımı satırda.**
  SHK listesi = `site_id` satır filtresiyle aynı kayıtların görünümü; E14
  "Hakedişler" sekmesi = proje filtresiyle aynı liste. **İki ekran aynı varlığın
  iki görünümüdür, iki ayrı varlık değildir.** SHK 98 "Hakediş #5 — Tem 2026"
  ile E15 65-66 "#5 · Temmuz 2026" aynı numarayı gösteriyor — tek kayıt kanıtı.
* **Seçenek C: ikisine birden (hakediş şantiyeye, üst kayıt sözleşmeye).** İki
  tablo katmanı; OLU'daki tek "Onaya Gönder" düğmesine iki ayrı onay akışı düşerdi.
  Karmaşıklık karşılıksız.

### D2 — Kalem dayanağı: `employer_contract_items`

* **`boq_items` dayanağı lehine:** kota ve saha gerçekleşmesi orada; satır zaten
  şantiyeye özgü.
* **`employer_contract_items` (önerilen) lehine:** (a) hakediş **işverene** kesilen
  evraktır, dili sözleşmenin poz listesidir (OLU 92 "SZL-2025-001'den"); (b) BOQ
  fiyat kopyası bayatlayabilir (§0/5 bulgu) — otorite zincirini kısaltmak gerekir;
  (c) E15 tablosu sözleşme gruplarıyla toplulaştırıyor (109-135), BOQ gruplarıyla
  değil; (d) BOQ satırı `contract_item_id IS NULL` da olabilir (şantiyenin kendi
  pozu, P5 §3.3) — bu satırlar işveren hakedişine hiç giremez, dayanak onlar
  üzerinden kurulamaz. BOQ yalnız **korkuluk** olarak devrededir: dağıtım ön şartı
  ve kota tavanı (§6.5) `boq_items`'tan okunur.

### D3 / D5 — Snapshot

§5'te. Yüzdeler için aynı mantık: sözleşmenin `advance_pct`'i sonradan değişirse
onaylı hakedişin hesabı oynamamalı. Oluşturma anında kopya + taslakta
`refresh-prices` ile bilinçli tazeleme (yüzdeler de aynı uçta tazelenir).

### D4 — Dönemsel kaynak, kümülatif türev

* **Kümülatif kaynak** (klasik YİGŞ yeşil defter: "bugüne kadar toplam" girilir,
  dönem = fark): geleneksel pratikle uyumlu; ama OLU inputları (123-124) dönem
  miktarıdır — form "bu hakedişte A-Blok'ta 900 m³" diye soruyor, "bugüne kadar
  2.400" diye değil (E15 103 "Bu Ay" kolonunun vurgulu/mavi olması da girdinin
  dönemsel olduğunu destekler; "Önceki" ve "Toplam" soluk türev kolonlarıdır).
* **Dönemsel kaynak (önerilen):** satırda yalnız bu dönem; önceki/kümülatif §6.6
  türevleri. Düzeltme ihtiyacı (önceki dönem yanlışsa) sonraki hakedişte eksi…
  girilemez (`quantity >= 0`) — düzeltme senaryosu K7 açık sorusudur.

### D8 — Tek açık hakediş

"Önceki hakedişler" kümesinin (§6.6) belirsizliğini yok eder: iki taslak paralel
açılabilseydi ikisi de aynı "önceki"ye bakar, ikisi onaylanınca kümülatif kota
tavanı (§6.5/2) geçersizce aşılabilirdi. Sıra numarası da (maks+1) yarışsız üretilir.
Maliyeti: reddedilen hakediş düzeltilmeden yenisi açılamaz — kabul edilebilir
(zaten aynı evrakın devamıdır).

---

## 15. Risk / açık iş listesi

| Risk | Karşılık |
|---|---|
| BOQ satırlarının bayat fiyatı (P5 bulgu 2) hakedişte değil ama **BOQ ekranında** sürüyor | Bu dilim kapatmaz; hakediş snapshot'la bağışık. BOQ tazeleme ayrı küçük iş olarak GOREV-SIRASI §2'de kalmalı |
| `MetricPlaceholder` → düz değer geçişi frontend'i kırar | §10/4: openapi + gen:api aynı frontend diliminde |
| Kota tavanı sert 422 — gerçek sahada iş artışı olur | Zeyilname dilimi gelene dek bilinçli; K6 sorusuyla kullanıcıya |
| `paid` sonrası hiçbir düzeltme yolu yok | K7 açık sorusu |
| E15 "Fiziksel" göstergesi türev — bağımsız fiziksel ilerleme beklentisi olabilir | §8'de tanım açık; kullanıcı farklı istiyorsa mockup/veri kaynağı istenir |
| SHO ekranı bu dilimde açılmıyor | §1.2 gerekçeli; site_diary sonrası |
| Onay/ödeme için ek UI (ret sebebi, ödeme detayı) mockup'sız | **Kullanıcıdan mockup istenmeli** — uydurulmadı, tek tık geçişler yapıldı (§7) |

---

## 16. ❗ KARAR GEREKİYOR — kullanıcıya sorular

Her soru cevaplanmadan ilgili kısım uygulanmaz. Önerilen cevaplar işaretlidir.

1. **Bağlanma düzeyi (D1):** Hakediş sözleşme (proje) düzeyinde TEK kayıt, şantiye
   kırılımı satırda; SHK ve E14 sekmesi aynı kaydın iki görünümü — onaylıyor musun?
   **Önerim: evet (OLU 83/103-104 kanıtıyla).**
2. **Kalem dayanağı (D2):** Satırlar `employer_contract_items`'a mı dayansın
   (önerilen), `boq_items`'a mı? BOQ yalnız kota korkuluğu olarak devrede.
   **Önerim: sözleşme kalemi.**
3. **Fiyat otoritesi (D3, ÖN KARAR):** Otorite sözleşme kalemi + hakediş anında
   satıra snapshot + taslakta isteğe bağlı `refresh-prices` — onaylıyor musun?
   (Alternatifler ve retleri §5'te.) **Önerim: evet.**
4. **Kümülatif/dönemsel (D4):** Girdi dönemsel, kümülatif türev — mi; yoksa klasik
   yeşil defter gibi kümülatif girdi, dönem fark mı? **Önerim: dönemsel girdi
   (OLU 123-124 form dili).**
5. **Yuvarlama (§6.1 sapması):** Düzeltilmiş birim fiyat **kuruş** hassasiyetinde mi
   tutulsun (önerilen: `Numeric(18,2)`, ROUND_HALF_UP), yoksa mockup'ın yaptığı gibi
   **tam liraya** mı yuvarlansın (OLU 122/126: 2.112,70→2.113)? Bu, "%100 mockup"
   kuralına hesap düzeyinde dokunan tek nokta. **Önerim: kuruş.**
6. **Kota tavanı (§6.5/2):** Kümülatif hakediş miktarının şantiye kotasını aşması
   sert 422 mi (önerilen, zeyilname gelene dek), yalnız uyarı mı?
   **Önerim: sert 422.**
7. **Düzeltme senaryosu:** `paid` hakedişte hata çıkarsa yol ne? (a) hiçbir yol —
   sonraki hakedişte telafi edilemez çünkü `quantity >= 0`; (b) satırda negatif
   miktara izin (kesinti satırı); (c) admin'e `unpay` geçişi. **Önerim: şimdilik
   (c) YOK, (a) kabul; ihtiyaç doğunca ayrı karar.** (`unapprove` yalnız
   `approved`'dan geriye çalışır, `paid`'den çalışmaz.)
8. **Silme (D7):** `approved`/`paid` hakediş **admin dahil kimse** tarafından
   silinemez (önce admin `unapprove`); taslak sahibi kendi taslağını siler
   (`can_delete`), kapı `draft`. P5'teki `_FULL`-kapı istisnasının bir adım ötesi —
   onaylıyor musun? **Önerim: evet.**
9. **Tek açık hakediş (D8):** Aynı sözleşmede draft/pending varken yeni hakediş
   409 — onaylıyor musun? **Önerim: evet.**
10. **Dönem tekilliği:** Aynı (proje, yıl, ay) için ikinci hakediş engellensin mi?
    **Önerim: HAYIR** — `sequence_no` yeter; ay ortası ek hakediş (ara hakediş)
    pratiği engellenmemeli, mockup da tekillik iddia etmiyor (OLU 82 select).
11. **`mark-paid` yetkisi:** `approve` seviyesi (muhasebe + PM) mi, yalnız muhasebe
    mi işaretlesin? Matris rol bazlı ayrım taşımaz (ikisi de `_APR`), rol-özel kural
    yeni bir desen olur. **Önerim: `approve` seviyesi, rol ayrımı yok.**
12. **Ret sebebi / ödeme detayı UI'ı:** `reject` için sebep alanı ve `mark-paid`
    için ödeme bilgisi (tarih/banka) mockup'ta yok. Tek tık geçiş mi kalsın, yoksa
    form mockup'ı verecek misin? **Önerim: tek tık; form istenirse mockup şart
    (§3 kuralı).**

---

## 17. "Bitti" tanımı

* 2 yeni tablo + 1 enum + 1 migration; upgrade → downgrade → upgrade yerel DB'de temiz
* §9'daki uçların tamamı izin + görünürlük kapılarından geçiyor; IDOR negatif seti yeşil
* Hesap motoru E15/OLU altın sayılarıyla birebir (K5 kararına göre)
* İzin matrisi DEĞİŞMEDİ — modül sayısı 18, satır sayısı 144 sabit (parity testleri dokunulmadan yeşil)
* `contracts` placeholder'ları dolduruldu, `pending_modules`'ten `progress_payments` çıktı
* `ruff` (0.15.22, tüm repo) + tam `pytest` yeşil; `openapi.json` üretildi (commit edilmez)
* Denetim günlüğü mesajları eklendi ve testlendi
* **Push/PR/merge/deploy YAPILMAZ** — karar kullanıcıda
