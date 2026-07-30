# Alt-Proje 2 · P3 — Proje tip-detay ekranları + `blocks` / `units` tabloları (tasarım)

Tarih: 2026-07-30 (rev. 2 — kullanıcı kararları işlendi)
Kapsam: Alt-Proje 2'nin üçüncü dilimi — proje düzeyinde ortak **blok** ve **ünite** katmanı
ve iki tip-detay ekranının backend sözleşmesi.

Mockup kanonu (satır satır okundu):
- `projedesign/Proje - Kendi Yatırım.dc.html` (324 satır) — kısaltma: **KY**
- `projedesign/Proje - Kat Karşılığı.dc.html` (252 satır) — kısaltma: **KK**
- `projedesign/Kat Karşılığı - Paylaşım.dc.html` (206 satır) — kısaltma: **KKP**

Destek mockup'lar (ünite alanlarının doğrulanması için tarandı; ekranları P8'in işi):
- `projedesign/Satış Yönetimi.dc.html` (239 satır) — **SY**
- `projedesign/Form - Daire Satisi.dc.html` (219 satır) — **FDS**

Bağlı spec'ler:
- `2026-07-26-alt-proje-2-p1-proje-cekirdegi-design.md` — proje çekirdeği, tip uzantıları,
  görünürlük süzgeci, `MetricPlaceholder`/`CountPlaceholder` sözleşmesi
- `2026-07-27-alt-proje-2-p2-santiye-bolum-design.md` — görünürlük süzgecinin yeniden kullanımı, `sites`
- `2026-07-29-alt-proje-2-p4-is-kalemleri-boq-design.md` §1 — P3/P8/P9 dilim numaralarının türetildiği yer
- `2026-07-25-backend-b6-gosterge-paneli-design.md` §2.3 — yer tutucu sözleşmesi

Kalıcı karar bağı: `GOREV-SIRASI.md` §4.1 — **hiçbir ileri bağ açılmaz**.
Bu dilimde bu kuraldan **iki onaylı sapma** vardır; ikisi de §13'te kullanıcı kararı olarak kayıtlıdır.

> **Bu revizyonun kaynağı:** kullanıcının 2026-07-30 tarihli kararları (§12 tablosu).
> Rev. 1'deki 12 açık sorunun tamamı karara bağlandı; yeni açık soru kalmadı (§12.2).

---

## 1. Kapsam / kapsam dışı

### 1.1 Kapsam (P3)

1. **`blocks` tablosu** — proje altındaki blok kaydı, **şantiyeye bağlı** (§4.2, §13.1, §13.2).
   *Kullanıcı kararı; mockup'ta blok CRUD'u yok, ekranda blok yine yalnız grup başlığıdır.*
2. **`units` tablosu** — blok altındaki ünite (daire/dükkan) kaydı. P8 (ünite satışı)
   ve P9 (hissedar-ünite dağılımı) bu tablo olmadan yazılamaz; ikisinin de ortak temeli budur.
3. Ünite **okuma** ucu: blok bazlı gruplama + gerçek toplamlar (adet, m², değer, pay dağılımı).
4. Ünite **yazma** uçları — **üç yol** (§7.6–§7.8):
   (a) tek tek form (`POST`), (b) **toplu üretim** (blok + kat aralığı + kat başına adet →
   N ünite), (c) **Excel içe aktarma** (dosya saklanmaz, §7.8). *(b) ve (c) kullanıcı kararıdır.*
5. **Paylaşım ataması** (kat karşılığı): ünitelerin `BİZ` / `ARSA` tarafına toplu atanması
   (KKP satır 25 "Paylaşımı Kaydet").
6. **DELETE uçları**: ünite silme + blok silme (bağlı kayıt korkuluğuyla). *Kullanıcı kararı.*
7. İki tip-detay ekranının backend sözleşmesinin **eksiksiz haritalanması**: hangi alan
   gerçek, hangisi yer tutucu, hangisi hangi dilime ait (§2 tabloları).
8. Denetim günlüğü, Türkçe hata mesajları, IDOR korkulukları, migration.

### 1.2 Kapsam DIŞI (bilinçli, tek tek)

| Konu | Nereye ait | Bu dilimde ne olur |
|---|---|---|
| Satış kaydı, alıcı, ödeme planı, tahsilat, tapu (KY 275–277, 284–287; SY tamamı; FDS tamamı) | **P8** | Ünite yanıtında `MetricPlaceholder`/`CountPlaceholder` |
| Ünite → hissedar dağılımı (KK 159–164; KKP 91, 110) | **P9** | Yer tutucu; **FK açılmaz** |
| Maliyet/kâr/marj kırılımı (KY 114–159, 165–196; KK 137–143) | **P10** | Yer tutucu |
| Taşeron hakedişleri tabloları (KY 202–252; KK 205–247) | **P5/P7** | Bu dilimde uç yok |
| İnşaat ilerleme yüzdesi (KY 83–85; KK 89–91; KKP 183) | **P7 / site_diary** | Yer tutucu |
| Nakit durumu (KY 103–105) | `treasury` | Yer tutucu |
| **Teslim takibi kilometre taşları** (KKP 176–193: kat irtifakı, anahtar teslim, tapu devirleri) | **P11 — Proje Takvimi / Gantt** (karar 2026-07-30) | Tablo açılmaz; ekranda bölüm boş kalır |
| **Sözleşme yükümlülük maddeleri** (KK 194–199) ve **teminat türü "(ipotek)"** (KK 191) | **P5 — Sözleşmeler** (karar 2026-07-30) | `project_land_share`'e sütun **eklenmez**; ekranda alanlar boş kalır |
| **Paylaşım tablosu Excel *dışa* aktarımı** (KKP 24) | **P5 / raporlar** (karar 2026-07-30) | Bu dilimde uç yok. *(Excel **içe** aktarma P3'tedir — §7.8; ikisi ayrı iştir.)* |
| Blok başına kat sayısı / blok teslim tarihi | ileride `blocks`'a eklenecek | **ŞİMDİ EKLENMEZ** (§4.1 notu) |
| Frontend | ayrı spec | — |

### 1.3 Kalıcı karar 4.1'in bu dilimdeki uygulaması

`units` tablosuna **hiçbir ileri bağ konmaz**: `sale_id`, `shareholder_id`, `contract_id`,
`section_id`, `boq_item_id`, `cost_id` **yoktur**; "ileride P8 buraya yazar" diye
`sales_status` gibi bir sütun da **açılmaz**. Satış durumu P8'in tablosunun türevidir;
bugün ünitede saklanırsa yarın iki otorite oluşur ve senkron kayması sessiz bir veri
hatasına dönüşür. Bugün ekranda gösterilecek değer yoksa dürüst boş durum basılır.

**İstisna:** `blocks` tablosu ve `blocks.site_id` bağı. İkisi de §13'te kullanıcı kararı
ve **onaylı sapma** olarak kayıtlıdır. Sapma yalnız bu ikisiyle sınırlıdır; `blocks`
tablosuna da ileri bağ konmaz.

---

## 2. Mockup alan tablosu

Kolon anlamları: **Kaynak** = alanın verisini kim üretir. `P3` = bu dilim (gerçek veri),
`P1` = zaten var (projects/project_investment/project_land_share/land_share_shareholder),
`P2` = zaten var (`sites`), `PN` = ilgili dilim → `MetricPlaceholder(pending_module=…)`.

### 2.1 `Proje - Kendi Yatırım.dc.html` (KY) — `project_type = kendi_yatirim`

| Satır | Alan etiketi | Tip | Zorunlu | Kaynak | Not |
|---|---|---|---|---|---|
| 21 | `KENDİ YATIRIM` rozeti | enum | ✓ | P1 | `projects.project_type` |
| **38** | kenar çubuğu "📍 **Şantiye**" (tekil) | bağlantı | — | P2 | tek şantiyeli proje varsayımının kanıtı (§4.3) |
| 67 | "Kendi Yatırım · Konut Geliştirme" | metin | — | P1 | tip etiketi + `projects.category` ("Tür") |
| 68 | Proje adı | metin | ✓ | P1 | `projects.name` |
| 70 | 📍 Çayyolu, Ankara | metin | — | P1 | `projects.city` (+ `address`) |
| **71** | **"48 Daire + 4 Dükkan"** | türev sayaç | — | **P3** | `units` içinde `unit_kind` bazlı **gerçek** sayım |
| 72 | Mar 2025 – Ara 2026 | tarih aralığı | — | P1 | `start_date`/`end_date` |
| 76–78 | Tahmini Net Kâr · %38,2 marj | para/oran | — | P10 | yer tutucu |
| 83–85 | İnşaat İlerlemesi %68 | oran | — | P7 | yer tutucu |
| **88–90** | **Satılan Ünite 34 / 52 · %65 satıldı** | sayaç | — | **P3 + P8** | payda **52 = gerçek** (`units` toplam adet); pay 34 ve oran **P8 yer tutucu** |
| 93–95 | Satış Geliri ₺31,4M / ₺48,2M hedef | para | — | P8 + **P1** | hedef `project_investment.sales_target` **gerçek**; gerçekleşen P8 |
| 98–100 | Toplam Maliyet ₺20,3M / ₺29,8M bütçe | para | — | P10 + P1 | bütçe `projects.budget` gerçek; harcanan P10 |
| 103–105 | Nakit Durumu | para | — | `treasury` | yer tutucu |
| 118–122 | Arsa Bedeli ₺8.400.000 · ✓ Ödendi | para + durum | — | **P1** + P10 | tutar `project_investment.land_cost` gerçek; ödeme durumu P10/`treasury` |
| 126–131 | İnşaat Maliyeti / harcanan % | para | — | P10 | yer tutucu |
| 134–139 | Ruhsat & Harçlar | para | — | P10 | yer tutucu |
| 142–147 | Finansman (Kredi Faizi) | para | — | P10 | yer tutucu |
| 150–155 | Pazarlama & Satış | para | — | P10 | yer tutucu |
| 156–159 | Toplam Harcanan | para | — | P10 | yer tutucu |
| 168–169 | Toplam Satış Hedefi · 52 ünite · Ort. ₺927K | para+sayaç | — | **P1 + P3** | hedef P1; **52 ünite ve ortalama `list_price` P3 gerçek** |
| 172–177 | Gerçekleşen Satış / Kalan Stok Değeri | para | — | P8 | yer tutucu |
| 181–196 | Bütçe maliyeti · net kâr · başabaş | para | — | P10 | yer tutucu |
| 204–251 | Taşeron Hakedişleri tablosu | tablo | — | P5/P7 | kapsam dışı |
| 258–259 | "Ünite Satış Durumu · 34 satıldı · 5 rezerve · 13 boş" | sayaç | — | P8 | yer tutucu |
| 264–267 | Satıldı / Rezerve / Boş / Ort. Satış Fiyatı | sayaç+para | — | P8 | yer tutucu |
| **271** | **Blok / Ünite** ("A Blok · Daire 12", satır 281) | metin | ✓ | **P3** | `blocks.name` + `units.unit_no` (§4.2) |
| **272** | **Tip** ("3+1", "2+1", "4+1", "Ticari") | metin | — | **P3** | `units.layout` |
| **273** | **m²** (142 / 108 / 178 / 86) | sayı | — | **P3** | `units.gross_area_m2` |
| **274** | **Liste Fiyatı** (1.150.000) | para | — | **P3** | **`units.list_price`** — kendi yatırımda beklenen fiyat sütunu (§4.4) |
| 275 | Satış Fiyatı (1.120.000 / "—") | para | — | P8 | yer tutucu |
| 276 | Durum (Tapulu / Rezerve / Boş) | enum | — | P8 | yer tutucu (§4.6) |
| 277 | Alıcı (Mehmet Aydın) | metin | — | P8 | yer tutucu |
| 281 / 290 / 299 | "A Blok", "A Blok", "B Blok" | metin | ✓ | **P3** | `blocks.name` kanıtı |
| 308–309 | "Zemin · Dükkan 2" · "Ticari" | metin | — | **P3** | `blocks.name='Zemin'`, `unit_kind=shop` |

### 2.2 `Proje - Kat Karşılığı.dc.html` (KK) — `project_type = kat_karsiligi`

| Satır | Alan etiketi | Tip | Zorunlu | Kaynak | Not |
|---|---|---|---|---|---|
| 21 | `KAT KARŞILIĞI` rozeti | enum | ✓ | P1 | `projects.project_type` |
| **39** | kenar çubuğu "📍 **Şantiye**" (tekil) | bağlantı | — | P2 | §4.3 |
| 68 | "Arsa Sahibi: Yılmaz Ailesi (3 hissedar)" | metin+sayaç | ✓ | P1 | `project_land_share.landowner_name` + `land_share_shareholder` adedi |
| 69 | Proje adı | metin | ✓ | P1 | |
| 71 | 📍 Bahçelievler, Ankara | metin | — | P1 | `city` |
| **72** | **"36 Daire + 6 Dükkan"** | türev sayaç | — | **P3** | `unit_kind` bazlı gerçek sayım |
| 73 | Oca 2026 – Haz 2027 | tarih | — | P1 | |
| 77–79 | Kendi Payım — Tahmini Kâr · %42,1 | para/oran | — | P10 | yer tutucu |
| 84–86 | Paylaşım Oranı %55 / %45 · "Biz / Arsa Sahibi" | oran | ✓ | **P1** | `our_share_pct` / `owner_share_pct` |
| 89–91 | İnşaat İlerlemesi %42 | oran | — | P7 | yer tutucu |
| **94–96** | **Kendi Payım — 23 ünite · ₺30,4M değer** | sayaç+para | — | **P3** | `owner_side='contractor'` adedi ve **`appraisal_value`** toplamı gerçek (§4.4) |
| 99–101 | İnşaat Maliyeti ₺7,4M / ₺17,6M bütçe | para | — | P10 + P1 | bütçe `projects.budget` gerçek |
| 104–106 | Arsa Maliyeti ₺0 · "Kat karşılığı ✓" | para | ✓ | P1 | tanım gereği sabit 0 (P1 spec §3.3) |
| **116–117** | **BİZİM PAY · %55 — 23 Ünite** | oran+sayaç | — | **P1 + P3** | |
| **121–122** | **"20 Daire + 3 Dükkan" · Ort. ₺1,32M · ₺30,4M** | sayaç+para | — | **P3** | kind kırılımı, ortalama ve toplam `appraisal_value` gerçek |
| 125–126 | Satılan (8 ünite) ₺10,6M | sayaç+para | — | P8 | yer tutucu |
| 129–130 | Kalan Stok (15 ünite) ₺19,8M | sayaç+para | — | P8 | yer tutucu |
| 134–135 | İnşaat Maliyeti (Toplam) | para | — | P10 | yer tutucu |
| 137–142 | Tahmini Net Kâr · %42,1 marj | para | — | P10 | yer tutucu |
| **150–151** | **ARSA SAHİBİ PAYI · %45 — 19 Ünite** | oran+sayaç | — | **P1 + P3** | `owner_side='landowner'` adedi gerçek |
| **155–156** | **"16 Daire + 3 Dükkan" · 3 hissedar · ₺24,9M** | sayaç+para | — | **P3 + P1** | kind kırılımı + değer toplamı P3; hissedar adedi P1 |
| 159–163 | Hissedar Dağılımı: "Ahmet Yılmaz (%50) → 10 ünite" | liste | — | **P1** + P9 | ad ve `share_pct` **gerçek**; **ünite adedi P9 yer tutucusu** |
| 166–168 | ⚠ Teslim Yükümlülüğü · 19 ünite · 30 Haziran 2027 | sayaç+tarih | — | **P3 + P1** | adet P3; tarih `project_land_share.delivery_date` |
| 170–174 | "Arsa sahibi kendi satar / tapu devri" bilgi metni | sabit metin | — | — | şema alanı yok, statik |
| 184 | Sözleşme No `KKS-2026-001` | metin | — | P1 | `project_land_share.contract_no` |
| 185 | Noter Tarihi 08.01.2026 | tarih | — | P1 | `notary_date` |
| 186 | Arsa Alanı 2.840 m² | sayı | — | P1 | `land_area_m2` |
| 187 | İnşaat Alanı 6.420 m² | sayı | — | P1 | `construction_area_m2` |
| 188 | Paylaşım Oranı %55 / %45 | oran | — | P1 | |
| 189 | Teslim Tarihi 30.06.2027 | tarih | — | P1 | `delivery_date` |
| 190 | Gecikme Cezası ₺15K/gün | para | — | P1 | `daily_penalty` |
| 191 | Teminat ₺2,5M **(ipotek)** | para | — | P1 + **P5** | tutar `guarantee_amount` gerçek; **"(ipotek)" türü P5'e bırakıldı** (§1.2), ekranda boş |
| 194–199 | Sözleşme Yükümlülükleri (4 madde) | metin listesi | — | **P5** | şemada yok, ekranda boş (§1.2) |
| 207–246 | Taşeron Hakedişleri | tablo | — | P5/P7 | kapsam dışı |

### 2.3 `Kat Karşılığı - Paylaşım.dc.html` (KKP)

| Satır | Alan etiketi | Tip | Zorunlu | Kaynak | Not |
|---|---|---|---|---|---|
| 24 | `Excel` butonu (**dışa** aktarım) | eylem | — | **P5/raporlar** | bu dilimde yok (§1.2) |
| **25** | **`Paylaşımı Kaydet` butonu** | eylem | — | **P3** | toplu paylaşım ucu (§7.10) |
| 55 | "Paylaşım Oranı — Sözleşme KKS-2026-001" | metin | — | P1 | `contract_no` |
| 57–63 | %55 / 23 ünite · %45 / 19 ünite şeridi | oran+sayaç | — | P1 + **P3** | |
| **67** | **Toplam Ünite 42** | sayaç | — | **P3** | `units` gerçek adedi |
| 68 | 6.420 m² İnşaat Alanı | sayı | — | P1 | `construction_area_m2` (ünite m² toplamı **değil**) |
| **69** | **Toplam Değer ₺55,3M** | para | — | **P3** | `appraisal_value` toplamı (§4.4) |
| 70 | Arsa Maliyeti ₺0 | para | — | P1 | sabit |
| 78 | "Hangi ünite kime ait — noterde belirlendi" | metin | — | — | statik |
| **86** | **Ünite** ("A · Daire 1" satır 96, "Zemin · Dükkan 1" satır 141) | metin | ✓ | **P3** | `blocks.name` + `units.unit_no` |
| **87** | **Tip** ("3+1", "Ticari") | metin | — | **P3** | `layout` |
| **88** | **m²** (148 / 112 / 186 / 94) | sayı | — | **P3** | `gross_area_m2` |
| **89** | **Rayiç Değer** (1.380.000) | para | — | **P3** | **`units.appraisal_value`** — kat karşılığında beklenen fiyat sütunu (§4.4) |
| **90 / 100 / 109** | **Sahip** (`BİZ` / `ARSA`) | enum | — | **P3** | `units.owner_side` |
| 91 / 110 | Hissedar / Alıcı ("Ahmet Yılmaz (hissedar)", "Serkan Öz") | metin | — | P9 / P8 | yer tutucu |
| 92 / 102 / 111 | Satış Durumu (Satıldı / Satışta / Rezerve / **Arsa Sahibinde**) | enum | — | P8 (+P3) | "Arsa Sahibinde" `owner_side`'dan **türetilebilir**; kalan üçü P8 (§4.6) |
| **161–163** | tfoot BİZİM PAY (23 ünite · %55) · **30.415.000** · "8 satıldı · 3 rezerve · 12 satışta" | toplam | — | **P3** + P8 | adet ve tutar gerçek; satış kırılımı yer tutucu |
| **166–168** | tfoot ARSA SAHİBİ PAYI (19 ünite · %45) · **24.885.000** · "Teslim: 30.06.2027" | toplam | — | **P3** + P1 | |
| 176–193 | Arsa Sahibi Teslim Takibi (4 kilometre taşı) | liste | — | **P11** | tablo açılmaz (§1.2) |
| 195–199 | Gecikme cezası uyarısı ₺15.000 · "%8 gecikme riski" | para+oran | — | P1 + P7 | tutar `daily_penalty` gerçek; risk yer tutucu |

### 2.4 Destek mockup'lar — ünite alanlarının doğrulanması

| Dosya · satır | Alan | `units` / `blocks` karşılığı |
|---|---|---|
| FDS 54 | Proje seçici (ilk adım) | `units.project_id` |
| FDS 55 | "B Blok · Daire 3 (4+1)" seçicisi | `blocks.name` + `unit_no` + `layout` |
| FDS 59 | **Brüt / Net m² → 178 / 152** | `gross_area_m2` + **`net_area_m2`** (net alanın tek kanıtı) |
| FDS 60 | Liste Fiyatı ₺1.480.000 | `list_price` |
| FDS 61 | m² Birim Fiyat ₺8.315 | **türev** (`list_price / gross_area_m2`), saklanmaz |
| FDS 62 | Maliyet ₺980.000 | P10 yer tutucusu — `units`'te sütun **açılmaz** |
| SY 74 / 104 | "A Blok — 24 Daire", "B Blok — 24 Daire + 4 Dükkan" | `blocks.name` + blok içi `unit_kind` kırılımı |
| SY 76–99 | Daire kutuları `1`…`24` | `unit_no` |
| SY 132–135 | Dükkan kutuları `D1`…`D4` | `unit_kind='shop'`, `unit_no='D1'` |
| SY 101 / 137 | "18 tapulu · 2 rezerve · 4 boş" | P8 yer tutucusu |

### 2.5 Mockup karşılığı OLMAYAN, kullanıcı kararıyla eklenenler

> %100 mockup sadakati kuralı gereği bu üç madde **ayrı** işaretlenir: mockup satırı yoktur,
> gerekçesi kullanıcı kararıdır. Üçü de **ekranın görünümünü değiştirmez**.

| Ekleme | Mockup satırı | Etiket | Gerekçe |
|---|---|---|---|
| `blocks` tablosu (blok artık metin değil kayıt) | **yok** — blok yalnız başlık olarak görünüyor (KY 281, SY 74, KKP 96) | **kullanıcı kararı 2026-07-30** | §13.1 |
| `blocks.site_id` (hiyerarşi Proje › Şantiye › Blok › Ünite) | **yok** — mockup ünite ile şantiye arasında bağ kurmuyor | **kullanıcı kararı 2026-07-30** | §13.2 |
| Toplu ünite üretimi + Excel içe aktarma uçları | **yok** — mockup'ta yalnız tekil satırlar var | **kullanıcı kararı 2026-07-30** | 52 üniteyi tek tek `POST` etmek kullanılamaz bir akış; §7.7–§7.8 |
| Ünite / blok DELETE uçları | **yok** — mockup'ta silme düğmesi yok | **kullanıcı kararı 2026-07-30** | §7.9 |

---

## 3. Proje tipi ayrımı

### 3.1 Mevcut model (P1/P1.1a) — değişmez

`projects.project_type` üç değerli: `taahhut` · `kendi_yatirim` · `kat_karsiligi`
(`app/modules/projects/models.py:35–41`). Tip uzantıları 1-1 tablolarda durur:

- `project_investment` — `sales_target`, `land_cost`
- `project_land_share` — `landowner_name`, `our_share_pct`, `owner_share_pct`, `contract_no`,
  `notary_date`, `land_area_m2`, `construction_area_m2`, `delivery_date`, `daily_penalty`,
  `guarantee_amount`
- `land_share_shareholder` — `name`, `share_pct` (1-N)

**P3 bu tabloların hiçbirine sütun eklemez.** (KK 191 "(ipotek)" ve KK 194–199 yükümlülükler
P5'e bırakıldığı için `project_land_share` dokunulmadan kalır — §1.2.)
§2 tablolarında `Kaynak = P1` yazan her alan zaten mevcut ve GET `/projects/{id}` yanıtında
dönüyor (P1 `InvestmentCard` / `LandShareCard`).

### 3.2 `units` neden tek tablo, tipe göre iki tablo değil

| Alan | `investment` | `land_share` | Karar |
|---|---|---|---|
| blok, ünite no, tip, m² | KY 271–273 | KKP 86–88 | **ortak** — sütun sütun aynı |
| fiyat | KY 274 "Liste Fiyatı" | KKP 89 "Rayiç Değer" | **iki ayrı nullable sütun** (§4.4) |
| `owner_side` (BİZ/ARSA) | yok | KKP 90 | **nullable ortak sütun** |
| satış alanları | KY 275–277 | KKP 91–92 | ikisinde de P8 |

Ortak sütun kümesi örtüştüğü için tek tablo + tipe özgü nullable sütunlar doğru modeldir.
İki tablo, P8 ve P9'un iki ayrı okuma yolu yazmasını zorlardı — bu dilimin varlık sebebine
(ortak temel) aykırı.

### 3.3 Tipe özgü kurallar (servis korkuluğu)

| Kural | Uygulama |
|---|---|
| `owner_side` yalnız `kat_karsiligi` projelerde dolu olabilir | servis; ihlal → **422** `ProjectTypeMismatchError` |
| `kat_karsiligi` projede `owner_side` **zorunlu değil** (paylaşım noterden sonra girilir; KKP 78) | nullable kalır; özet `unassigned` sayacı verir |
| `taahhut` projede ünite tanımlamak | **SERBEST** — karara bağlandı (2026-07-30). Mockup yasaklamıyor, kısıt icat edilmez |
| `list_price` / `appraisal_value` | ikisi de **her tipte kabul edilir**, hiçbiri zorunlu değil; yalnız *beklenen* sütun tipe göre değişir (§4.4). Reddedilmez — reddetmek mockup'ta olmayan bir kısıt icat etmek olurdu |

DB `CHECK` ile zorlanamaz (`project_type` başka tabloda). P4'ün
`BoqGroupSiteMismatchError` deseni birebir tekrarlanır: tek yazma yolunda servis korkuluğu.

---

## 4. Şema: `blocks` + `units`

### 4.0 Hiyerarşi

```
Project  ──1:N──▶  Site  ──1:N──▶  Block  ──1:N──▶  Unit
   │                                  ▲
   └──────────── project_id ──────────┘   (bileşik FK ile tutarlılık zorlanır)
```

**Proje › Şantiye › Blok › Ünite.** `units`'te `site_id` **YOKTUR** — şantiye blok
üzerinden türetilir (kullanıcı kararı, §13.2). İki farklı yoldan aynı gerçeğe ulaşmak
(hem `units.site_id` hem `blocks.site_id`) senkron kayması demektir; tek otorite `blocks`'tur.

### 4.1 `blocks` sütunları

*(Tablo ve tüm sütunları: **kullanıcı kararı**, mockup satırı yok — §2.5.)*

| Sütun | Tip | Null | Varsayılan | Gerekçe |
|---|---|---|---|---|
| `id` | UUID PK | ✗ | `uuid4` | mevcut desen |
| `project_id` | UUID FK → `projects.id` `ON DELETE CASCADE`, index | ✗ | — | KKP 67 proje düzeyi toplam; blok proje altında benzersiz |
| `site_id` | UUID FK → `sites.id` `ON DELETE CASCADE`, index | ✗ | — | **kullanıcı kararı** §13.2 |
| `name` | `String(50)` | ✗ | — | KY 281 "A Blok", 299 "B Blok", 308 "Zemin"; KKP 96 "A", 141 "Zemin"; SY 74/104 |
| `sort_order` | `Integer` | ✗ | `0` | SY 74/104 blok sırası (A Blok, B Blok) alfabetik olmayabilir ("Zemin" en sonda görünüyor: KY 308) |
| `created_at` / `updated_at` | `timestamptz` | ✗ | `now()` | mevcut model deseni |

> **NOT (bilinçli eksik):** blok başına **kat sayısı**, **teslim tarihi**, blok kodu, blok
> durumu gibi alanlar **ŞİMDİ EKLENMEZ**. Mockup'ta karşılıkları yok; ihtiyaç doğduğunda
> `blocks` tablosuna **additive** olarak eklenecektir — tablo zaten açıldığı için o ekleme
> ucuz olacak. Bugün eklemek spekülatif genellemedir.

Kısıtlar:

```
UniqueConstraint("project_id", "name", name="uq_blocks_project_name")
UniqueConstraint("project_id", "id",   name="uq_blocks_project_id_id")   # bilesik FK icin
Index("ix_blocks_project_id", "project_id")
Index("ix_blocks_site_id", "site_id")
```

`uq_blocks_project_name`: blok adı **proje** içinde benzersizdir, şantiye içinde değil.
Gerekçe: KY 271 ve KKP 86 blok adını şantiye bağlamı olmadan gösteriyor ("A Blok · Daire 12");
aynı projede iki şantiyede birer "A Blok" olsaydı ekrandaki etiket ayırt edilemezdi.

`uq_blocks_project_id_id` yapay görünür ama işlevseldir: `units`'in bileşik FK'sının
hedefidir (§4.3), böylece `unit.project_id ≠ block.project_id` durumu **DB düzeyinde
imkânsız** olur; servis korkuluğuna güvenilmez.

### 4.2 `units` sütunları

| Sütun | Tip | Null | Varsayılan | Mockup gerekçesi (satır) |
|---|---|---|---|---|
| `id` | UUID PK | ✗ | `uuid4` | mevcut desen |
| `project_id` | UUID FK → `projects.id` `ON DELETE CASCADE`, index | ✗ | — | FDS 54 (önce **Proje** seçilir), KKP 67 proje düzeyi toplam, KY 71 |
| `block_id` | UUID FK → `blocks.id` `ON DELETE RESTRICT`, index | ✗ | — | KY 271 "Blok / Ünite"; SY 74/104 blok gruplaması — *tablolaşması kullanıcı kararı* |
| `unit_no` | `String(30)` | ✗ | — | KY 281 "Daire 12"; KKP 96 "Daire 1"; SY 76–99 `1…24`, 132–135 `D1…D4` |
| `unit_kind` | `Enum('apartment','shop', name='unit_kind')` | ✗ | — | KY 71 "48 Daire + 4 Dükkan", 308 "Dükkan 2"; KK 72; SY 104/132–135 ayrı ızgara |
| `layout` | `String(20)` | ✓ | — | KY 272 "Tip" → "3+1"/"2+1"/"4+1"/"Ticari"; KKP 87 |
| `gross_area_m2` | `Numeric(10,2)` | ✓ | — | KY 273 (142/108/178/86); KKP 88; FDS 59 "Brüt" |
| `net_area_m2` | `Numeric(10,2)` | ✓ | — | FDS 59 "Brüt / Net m² 178 / 152" — **tek kanıt bu satır** |
| **`list_price`** | `Numeric(18,2)` | ✓ | — | **KY 274 "Liste Fiyatı"**; FDS 60 (§4.4) |
| **`appraisal_value`** | `Numeric(18,2)` | ✓ | — | **KKP 89 "Rayiç Değer"**; KK 94–96/121–122/155–156 değer toplamları (§4.4) |
| `owner_side` | `Enum('contractor','landowner', name='unit_owner_side')` | ✓ | — | KKP 90 "Sahip", 100 `BİZ`, 109 `ARSA` |
| `sort_order` | `Integer` | ✗ | `0` | SY 76–99 ünite ızgarasının sabit sırası (`unit_no` metin olduğu için alfabetik sıralama "10 < 2" verir) |
| `created_at` / `updated_at` | `timestamptz` | ✗ | `now()` | mevcut model deseni |

**Mockup'ta olmadığı için AÇILMAYAN sütunlar:**
`floor`/kat (hiçbir mockup'ta yok), `sales_status`, `sale_price`, `buyer_name`,
`shareholder_id`, `cost_amount`, **`site_id`** (blok üzerinden türetilir — §4.0), `code`,
`is_active`, `deed_status`.

`block_id` üzerinde `ON DELETE RESTRICT`: blok silme davranışı §7.9'da açıkça tanımlıdır
(ünitesi olan blok silinemez); veritabanı bunu sessiz cascade'e çevirmemelidir.

### 4.3 Kısıtlar, benzersizlik, indeksler (`units`)

```
ForeignKeyConstraint(
    ["project_id", "block_id"], ["blocks.project_id", "blocks.id"],
    name="fk_units_block_project",  ondelete="RESTRICT",
)
UniqueConstraint("block_id", "unit_no", name="uq_units_block_no")
CheckConstraint("gross_area_m2 IS NULL OR gross_area_m2 >= 0",  name="ck_units_gross_area")
CheckConstraint("net_area_m2 IS NULL OR net_area_m2 >= 0",      name="ck_units_net_area")
CheckConstraint("list_price IS NULL OR list_price >= 0",        name="ck_units_list_price")
CheckConstraint("appraisal_value IS NULL OR appraisal_value >= 0", name="ck_units_appraisal_value")
CheckConstraint(
    "gross_area_m2 IS NULL OR net_area_m2 IS NULL OR net_area_m2 <= gross_area_m2",
    name="ck_units_net_le_gross",
)
Index("ix_units_project_id", "project_id")
Index("ix_units_block_id", "block_id")
```

- **Benzersizlik**: blok içinde `unit_no`. Gerekçe: KY 281/290 aynı blokta farklı daire no;
  KKP 96/105 aynı; SY 76–99 blok içinde 1…24 tekrarsız, **ama** A Blok 1 ile B Blok 1 aynı
  anda var (SY 76 ve 106) → benzersizlik blokla birlikte tanımlanmalı. `block_id` zaten
  projeye bağlı olduğu için `(block_id, unit_no)` proje-içi benzersizliği de sağlar.
- `ck_units_net_le_gross`: **karara bağlandı (2026-07-30) — DB CHECK olarak konur.**
  Tek kanıt FDS 59'daki 178/152'dir; kullanıcı sert kısıtı onayladı.
- `sort_order` benzersiz **değildir** (BOQ deseni).
- P4 gibi, `DuplicateError` `IntegrityError`'a düşmeden önce açık `SELECT` ile fırlatılır ki
  Türkçe alan mesajı verilebilsin; `IntegrityError → 409` yarış-durumu ağı olarak kalır.

### 4.4 İki fiyat sütunu — `list_price` ve `appraisal_value`

**Karara bağlandı (2026-07-30): iki ayrı sütun.** Rev. 1'de tek sütun önerilmişti; kullanıcı
ayrı sütun kararı verdi.

| Sütun | Mockup etiketi | Nerede | Beklendiği proje tipi |
|---|---|---|---|
| `list_price` | **"Liste Fiyatı"** | KY 274, FDS 60 | `kendi_yatirim` (ve `taahhut`, kullanılırsa) |
| `appraisal_value` | **"Rayiç Değer"** | KKP 89 | `kat_karsiligi` |

Gerekçe: ikisi aynı kavram değildir. *Liste fiyatı* satışa çıkarılan fiyattır (pazarlama
kararı, zamanla değişir). *Rayiç değer* paylaşımın adil olduğunu göstermek için noterde/
ekspertizde belirlenen değerdir (KKP 78 "noterde belirlendi") ve paylaşım tablosunun
tfoot toplamlarının (KKP 161–168) tabanıdır. Tek sütuna sıkıştırmak, kat karşılığı bir
projede kendi payımızı satışa çıkardığımızda (KK 40 "🏠 Kendi Payım Satışı" kenar çubuğu
girdisi) rayiç değerin üzerine yazılması demek olurdu — paylaşım tablosu geçmişe dönük bozulurdu.

**İkisi de nullable, ikisi de her tipte kabul edilir** (§3.3). Reddetme yok; yalnız
toplamların hangi sütundan hesaplandığı proje tipine göre seçilir:

| Proje tipi | Toplamların tabanı (`value_basis`) |
|---|---|
| `kat_karsiligi` | `appraisal_value` |
| `kendi_yatirim`, `taahhut` | `list_price` |

`UnitTotals.value_basis` alanı bu seçimi **yanıtta açıkça bildirir** (§6.1) — ekran hangi
sütunu gösterdiğini tahmin etmek zorunda kalmaz.

**UI etiketlemesi (frontend dilimi için bağlayıcı):**

| Ekran | Sütun başlığı | Okunan alan |
|---|---|---|
| KY 274 (Kendi Yatırım · Ünite Satış Durumu) | `Liste Fiyatı` | `list_price` |
| KKP 89 (Paylaşım Tablosu) | `Rayiç Değer` | `appraisal_value` |
| Ünite formu (mockup yok) | **iki alan birden**, `Liste Fiyatı` ve `Rayiç Değer`; proje tipine göre beklenen olan öne çıkarılır, diğeri isteğe bağlı kalır | ikisi |

### 4.5 Tek şantiyeli projede blok–şantiye ataması

Mockup kanıtı: KY 38 ve KK 39 kenar çubuğunda proje altında **tekil** bir "📍 Şantiye"
girdisi var (liste değil, sayaç değil). Yani mockup'ın kanonik projesi **tek şantiyelidir**
ve hiçbir ekranda şantiye seçici gösterilmiyor. Bu yüzden davranış şudur:

| Projedeki şantiye sayısı | `POST /projects/{id}/blocks` içinde `site_id` | Davranış |
|---|---|---|
| **1** | gönderilmemiş | **otomatik atanır** (tek şantiye) — mockup'ta seçici olmadığı için ekran değişmez |
| **1** | gönderilmiş | doğrulanır; projeye ait değilse **404** |
| **0** | — | **422** `Blok tanımlamadan önce projeye şantiye eklenmelidir` |
| **≥2** | gönderilmemiş | **422** `Birden fazla şantiye var, blok için şantiye seçilmelidir` |
| **≥2** | gönderilmiş | doğrulanır |

Gerekçe: otomatik atama **tek şantiyeli** durumda mockup'a %100 sadakati korur (ekran
seçici göstermez, göstermek zorunda da kalmaz). Çok şantiyeli durumda otomatik atama
**yanlış veri üretme riski** taşır (hangi şantiye keyfî olurdu), o yüzden orada seçim
zorunludur — ve o ekran zaten mockup'ta yok, dolayısıyla sapma da yok.

`PATCH /blocks/{id}` ile `site_id` değiştirilebilir (blok yanlış şantiyeye açılmışsa);
yeni şantiye aynı projeye ait olmalıdır, değilse **404**.

### 4.6 Satış durumu neden sütun değil

KY 276 ve KKP 92 bir "Durum" sütunu gösterir; ama iki mockup **iki farklı sözlük** kullanır
(KY: Tapulu/Rezerve/Boş — KKP: Satıldı/Satışta/Rezerve/Arsa Sahibinde). İkisinin de kaynağı
satış kaydıdır (P8) — "Arsa Sahibinde" hariç, o `owner_side='landowner'`'dan **türetilir**.
Durumu `units`'te saklamak, P8 geldiğinde ikinci bir otorite yaratır ve senkron kaydığında
hata sessiz olur. Bu yüzden yanıt şu biçimi verir:

```
sales_status: { available: false, pending_module: "unit_sales" }   # P8
is_landowner_share: true                                            # P3 gerçek, owner_side türevi
```

---

## 5. Kat karşılığı paylaşım modeli

### 5.1 Mockup'ta ne var

| Kavram | Nerede | Nerede saklanır |
|---|---|---|
| Yüzde paylaşımı %55 / %45 | KK 85, 188; KKP 58/62 | **P1** `project_land_share.our_share_pct/owner_share_pct` (CHECK toplam = 100) |
| Ünite bazlı paylaşım (hangi ünite kime) | KKP 86–157 | **P3** `units.owner_side` |
| Taraf başına adet ve değer | KK 117/121–122, 151/155–156; KKP 161–168 | **P3 türev** (`GROUP BY owner_side`, `SUM(appraisal_value)`) |
| Hissedar listesi ve yüzdeleri | KK 161–163 | **P1** `land_share_shareholder` |
| Hissedar başına ünite adedi | KK 161–163 sağ sütun | **P9** yer tutucu |
| Hissedar → ünite eşlemesi | KKP 110 "Ahmet Yılmaz (hissedar)" | **P9** — FK **açılmaz** |
| Teslim yükümlülüğü (19 ünite, 30.06.2027) | KK 166–168; KKP 168 | adet P3 türevi, tarih P1 |
| Paylaşımı kaydet eylemi | KKP 25 | **P3** toplu ata ucu (§7.10) |
| Teslim kilometre taşları | KKP 176–193 | **P11** — kapsam dışı (§1.2) |

### 5.2 Yüzde ile adet arasındaki tutarsızlık — doğrulanmaz, raporlanır

KKP: 42 ünitenin 23'ü bizde = **%54,8**, sözleşme yüzdesi **%55**. Ünite paylaşımı noterde
tek tek belirlenir (KKP 78) ve yüzdeyle birebir tutmak zorunda değildir. Bu yüzden
"adet oranı = sözleşme oranı" **doğrulaması yapılmaz** (yazmayı bloke etmez); özet yanıtı
her iki değeri de verir, sapmayı ekran gösterir:

```
contract_share: { our_pct: 55.00, owner_pct: 45.00 }        # P1
unit_share:     { our_pct: 54.76, owner_pct: 45.24 }        # P3 türev
```

### 5.3 `owner_side` atanmamış üniteler

Paylaşım girilmeden önce tüm üniteler `owner_side = NULL`'dır. Özet `unassigned` sayacı ve
`unassigned_value` toplamı verir; ekran "henüz paylaşılmadı" durumunu bundan basar.
Boş bırakmak hata değildir.

---

## 6. Pydantic şemaları

Dosya: `app/modules/units/schemas.py` (bloklar da bu modülde — ayrı bir modül açmak
tek ekranlık bir kavram için gereksiz bölünmedir).
`MetricPlaceholder` ve `CountPlaceholder` **`app.modules.projects.schemas`'tan import edilir**
(BOQ'daki `app/modules/boq/schemas.py:8` deseni birebir) — kopyalanmaz.

### 6.1 Okuma

```python
class BlockResponse(BaseModel):
    id: uuid.UUID
    name: str                   # KY 281 "A Blok"
    site_id: uuid.UUID          # §13.2
    site_name: str              # ekran blok basliginda santiyeyi gosterebilsin diye (join)
    sort_order: int
    counts: UnitKindBreakdown   # SY 74 "A Blok — 24 Daire", 104 "24 Daire + 4 Dukkan"

class UnitResponse(BaseModel):
    id: uuid.UUID
    block_id: uuid.UUID
    block_name: str             # KY 271, KKP 86
    unit_no: str
    label: str                  # turev: f"{block_name} · {unit_no}" (KY 281, KKP 96)
    unit_kind: UnitKind         # apartment | shop
    layout: str | None          # KY 272 "Tip"
    gross_area_m2: Decimal | None
    net_area_m2: Decimal | None
    list_price: Decimal | None       # KY 274 "Liste Fiyati"
    appraisal_value: Decimal | None  # KKP 89 "Rayic Deger"
    unit_price_per_m2: Decimal | None   # computed: list_price / gross_area_m2 (FDS 61)
    owner_side: UnitOwnerSide | None    # KKP 90
    is_landowner_share: bool            # turev: owner_side == landowner (KKP 111)
    sort_order: int
    # --- ileri dilim yer tutuculari ---
    sales_status: MetricPlaceholder     # pending_module="unit_sales"   (KY 276, KKP 92)
    sale_price: MetricPlaceholder       # pending_module="unit_sales"   (KY 275)
    buyer_name: MetricPlaceholder       # pending_module="unit_sales"   (KY 277)
    shareholder: MetricPlaceholder      # pending_module="shareholder_units" (KKP 91)
    unit_cost: MetricPlaceholder        # pending_module="project_costs"     (FDS 62)
```

`unit_price_per_m2`: `gross_area_m2` yok/0 ise `None`; `computed_field`, `ROUND_HALF_UP`,
2 hane (BOQ `_quantize_money` deseni). Tabanı **her zaman `list_price`**'tır (FDS 60–61
aynı formda yan yana duruyor); `appraisal_value` birim fiyatı mockup'ta yok.

```python
class UnitKindBreakdown(BaseModel):     # KY 71, KK 121, SY 104
    apartment: int
    shop: int
    total: int

class UnitSideSummary(BaseModel):       # KK 116-122 / 150-156, KKP 161-168
    side: UnitOwnerSide | None          # None = henuz atanmamis (§5.3)
    counts: UnitKindBreakdown
    total_value: Decimal                # value_basis sutununun toplami (NULL'lar 0 sayilir)
    average_value: Decimal | None       # KK 121 "Ortalama ₺1,32M"
    share_pct: Decimal | None           # turev adet orani (§5.2)
    sold: CountPlaceholder              # P8  (KKP 163)
    reserved: CountPlaceholder          # P8
    listed: CountPlaceholder            # P8

class UnitValueBasis(str, enum.Enum):   # §4.4
    list_price = "list_price"
    appraisal_value = "appraisal_value"

class UnitTotals(BaseModel):
    counts: UnitKindBreakdown           # KKP 67, KY 71/88
    value_basis: UnitValueBasis         # §4.4 — toplamlar hangi sutundan hesaplandi
    total_value: Decimal                # KKP 69 "Toplam Deger"
    average_value: Decimal | None       # KY 168 "Ortalama ₺927K"
    total_list_price: Decimal           # her iki sutun da AYRICA doner ki ekran
    total_appraisal_value: Decimal      # ihtiyaci olani sorgusuz alabilsin
    total_gross_area_m2: Decimal        # unite m² toplami (KKP 68'in yerine GECMEZ)
    sides: list[UnitSideSummary]        # contractor / landowner / atanmamis
    sold_units: CountPlaceholder        # P8 (KY 88 payi, 264)
    reserved_units: CountPlaceholder    # P8 (KY 265)
    available_units: CountPlaceholder   # P8 (KY 266)
    sales_revenue: MetricPlaceholder    # P8 (KY 93)
    average_sale_price: MetricPlaceholder  # P8 (KY 267)

class UnitBlockGroup(BaseModel):        # SY 74 / 104 blok basliklari
    block: BlockResponse
    units: list[UnitResponse]

class UnitListResponse(BaseModel):
    totals: UnitTotals
    blocks: list[UnitBlockGroup]

class BlockListResponse(BaseModel):
    blocks: list[BlockResponse]
```

Sıralama: bloklar `sort_order`, sonra `name`; blok içinde üniteler `sort_order`, sonra `unit_no`.
**Ünitesi olmayan blok da `blocks` listesinde döner** (boş `units` ile) — yeni açılmış blok
ekranda görünmeli, aksi hâlde kullanıcı bloğu kaydettiğini göremez.

### 6.2 Yazma

```python
class BlockCreate(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    site_id: uuid.UUID | None = None     # §4.5 — tek santiyede opsiyonel
    sort_order: int = Field(default=0, ge=0)

class BlockUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=50)
    site_id: uuid.UUID | None = None
    sort_order: int | None = Field(default=None, ge=0)

class UnitCreate(BaseModel):
    block_id: uuid.UUID
    unit_no: str = Field(min_length=1, max_length=30)
    unit_kind: UnitKind
    layout: str | None = Field(default=None, max_length=20)
    gross_area_m2: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    net_area_m2: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    list_price: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    appraisal_value: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    owner_side: UnitOwnerSide | None = None
    sort_order: int = Field(default=0, ge=0)

class UnitUpdate(BaseModel):
    # TUM alanlar opsiyonel; "gonderilmedi" ile "null yapildi" ayrimi
    # P1/P2/P4'teki model_fields_set deseniyle cozulur.
    block_id: uuid.UUID | None = None
    unit_no: str | None = Field(default=None, min_length=1, max_length=30)
    unit_kind: UnitKind | None = None
    layout: str | None = None
    gross_area_m2: Decimal | None = None
    net_area_m2: Decimal | None = None
    list_price: Decimal | None = None
    appraisal_value: Decimal | None = None
    owner_side: UnitOwnerSide | None = None
    sort_order: int | None = Field(default=None, ge=0)

class UnitAllocationItem(BaseModel):        # KKP 25 "Paylasimi Kaydet"
    unit_id: uuid.UUID
    owner_side: UnitOwnerSide | None        # None = atamayi kaldir

class UnitAllocationRequest(BaseModel):
    items: list[UnitAllocationItem] = Field(min_length=1, max_length=_MAX_ALLOCATION_ITEMS)
```

`_MAX_ALLOCATION_ITEMS = 500`: KKP'de 42 ünite var; 500 makul bir üst sınırdır ve tek istekte
sınırsız satır yazılmasını engeller. Sabit modül düzeyinde adlandırılır, sihirli sayı bırakılmaz.

### 6.3 Toplu üretim şeması *(kullanıcı kararı — mockup yok)*

```python
class UnitNumberingPattern(str, enum.Enum):
    sequential = "sequential"     # 1, 2, 3, ... N        — SY 76-99 deseni
    floor_based = "floor_based"   # 101, 102, 201, 202    — kat*100 + sira

class UnitBulkCreate(BaseModel):
    block_id: uuid.UUID
    unit_kind: UnitKind
    start_floor: int = Field(ge=-5, le=100)       # bodrum katlar icin negatif serbest
    end_floor: int = Field(ge=-5, le=100)
    units_per_floor: int = Field(ge=1, le=20)
    numbering: UnitNumberingPattern = UnitNumberingPattern.sequential
    prefix: str = Field(default="", max_length=10)   # "D" -> D1..D4 (SY 132-135)
    start_number: int = Field(default=1, ge=0)       # sequential icin baslangic
    # tum uretilen unitelere uygulanacak ORTAK varsayilanlar (hepsi opsiyonel)
    layout: str | None = Field(default=None, max_length=20)
    gross_area_m2: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    net_area_m2: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    list_price: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    appraisal_value: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
```

Doğrulama: `end_floor >= start_floor`; üretilecek toplam adet
`(end_floor - start_floor + 1) * units_per_floor` ≤ **`_MAX_BULK_UNITS = 500`**.
`sequential`'da numaralar `prefix + str(start_number + i)`; `floor_based`'de
`prefix + f"{floor}{sira:02d}"`.

**Hep-ya-hiç:** üretilen numaralardan **biri bile** blokta mevcutsa hiçbiri yazılmaz →
**409** + çakışan ilk 20 numara yanıtta listelenir. Gerekçe: 48 üniteden 3'ü sessizce
atlanırsa kullanıcı bunu asla fark etmez.

### 6.4 Excel içe aktarma şeması *(kullanıcı kararı — mockup yok)*

```python
class UnitImportRowError(BaseModel):
    row: int          # Excel satir numarasi (baslik = 1, veri 2'den baslar)
    column: str | None
    message: str      # Turkce

class UnitImportResult(BaseModel):
    created: int
    blocks_created: int
    errors: list[UnitImportRowError]   # basarili sonucta bos
```

---

## 7. Uçlar

Router: `app/modules/units/router.py`, `tags=["units"]`, `responses=COMMON_ERROR_RESPONSES`.
Yol köklerinin karışıklığı P4 deseniyle aynıdır: proje bağlamlı uçlar `/projects/...`
altında, kimliği yukarı çözümleyen tekil uçlar `/units/...` ve `/blocks/...` kökündedir.

> **BFF TUZAĞI (frontend'e not):** **İKİ kök** var — `units` **ve** `blocks`. İkisi de
> frontend'in `src/app/api/backend/[...path]/route.ts` `ALLOWED_ROOTS` listesine eklenmezse
> ilgili modül **yalnız canlıda 404** verir (`GOREV-SIRASI.md` §3). Frontend dilimi ikisini de içermeli.

**İzin (tüm uçlar):** okuma `projects` · `view`, yazma `projects` · `full` (§8).

| # | Uç | Yöntem | İzin | Bölüm |
|---|---|---|---|---|
| 1 | `/projects/{project_id}/blocks` | GET | view | §7.1 |
| 2 | `/projects/{project_id}/blocks` | POST | full | §7.2 |
| 3 | `/blocks/{block_id}` | PATCH | full | §7.3 |
| 4 | `/blocks/{block_id}` | DELETE | full | §7.9 |
| 5 | `/projects/{project_id}/units` | GET | view | §7.4 |
| 6 | `/projects/{project_id}/units` | POST | full | §7.5 |
| 7 | `/units/{unit_id}` | PATCH | full | §7.6 |
| 8 | `/units/{unit_id}` | DELETE | full | §7.9 |
| 9 | `/projects/{project_id}/units/bulk` | POST | full | §7.7 |
| 10 | `/projects/{project_id}/units/import` | POST | full | §7.8 |
| 11 | `/projects/{project_id}/units/allocation` | PATCH | full | §7.10 |

### 7.1 `GET /projects/{project_id}/blocks`

Yanıt `200 BlockListResponse`. Hata: `401` · `403` · `404` görünmeyen/olmayan proje.
Blok seçicileri (ünite formu, toplu üretim formu) bu ucu kullanır.

### 7.2 `POST /projects/{project_id}/blocks`

Gövde `BlockCreate`. Yanıt `201 BlockResponse`.
Hata: `404` görünmeyen proje **veya projeye ait olmayan `site_id`** · `409` aynı ad ·
`422` §4.5 şantiye kuralları.

### 7.3 `PATCH /blocks/{block_id}`

Gövde `BlockUpdate` (kısmi). Yanıt `200 BlockResponse`.
Kimlik **yukarı çözümlenir**: `block → project → görünürlük`. Görünmeyen projenin bloğu **404**.
Hata: `404` · `409` ad çakışması · `422` yeni `site_id` başka projeye ait.

### 7.4 `GET /projects/{project_id}/units`

| | |
|---|---|
| Sorgu | `block_id: UUID \| None`, `site_id: UUID \| None`, `kind: UnitKind \| None`, `owner_side: 'contractor'\|'landowner'\|'unassigned' \| None` |
| Yanıt | `200 UnitListResponse` |
| Hata | `401` · `403` · **`404` görünmeyen/olmayan proje** · `422` geçersiz enum |

**Sayaçlar filtreden ETKİLENMEZ** — `totals` her zaman projenin tamamını sayar
(P1 `list_projects_overview` kuralının birebir tekrarı); yalnız `blocks` süzülür.
`owner_side=unassigned` NULL'ları getirir. `site_id` süzgeci blok üzerinden çalışır (§4.0).

### 7.5 `POST /projects/{project_id}/units`

Gövde `UnitCreate`. Yanıt `201 UnitResponse`.
Hata: `404` görünmeyen proje **veya projeye ait olmayan `block_id`** · `409` blokta aynı
`unit_no` · `422` tip uyuşmazlığı (`owner_side`) / `net > gross`.

### 7.6 `PATCH /units/{unit_id}`

Gövde `UnitUpdate` (kısmi). Yanıt `200 UnitResponse`.
Kimlik yukarı çözümlenir: `unit → project → görünürlük`. Görünmeyen projenin ünitesi
**404**'tür, 403 değil (varlığını sızdırmaz).
`block_id` değiştirilebilir (ünite yanlış bloğa girilmişse) — yeni blok aynı projede olmalı,
değilse **404**; hedef blokta `unit_no` çakışırsa **409**.

### 7.7 `POST /projects/{project_id}/units/bulk` — toplu üretim *(kullanıcı kararı)*

Gövde `UnitBulkCreate` (§6.3). Yanıt `201 UnitListResponse` (güncel tam liste — ekran
tabloyu yeniden çizer).
Hata: `404` görünmeyen proje / blok · **`409` üretilen numaralardan biri mevcut**
(hiçbiri yazılmaz, çakışanlar listelenir) · `422` kat aralığı geçersiz / sınır aşımı /
`owner_side` gerektiren tip uyuşmazlığı.

Atomiktir: tek transaction, doğrulama yazmadan önce.

### 7.8 `POST /projects/{project_id}/units/import` — Excel içe aktarma *(kullanıcı kararı)*

> **KRİTİK — belge saklama altyapısı GEREKMEZ.** Dosya `multipart/form-data` ile alınır,
> **bellekte** `openpyxl` ile okunur, üniteler oluşturulur, dosya **atılır**. Diske, S3'e,
> veritabanına **hiçbir şey yazılmaz**; `documents` çekirdeği (Faz 6, `GOREV-SIRASI.md` §4.4)
> beklenmez. P3'e sığmasının tek sebebi budur ve bu sınır aşılmayacaktır.

| | |
|---|---|
| İstek | `multipart/form-data`, tek alan: `file` |
| Kabul edilen tip | yalnız `.xlsx` (`openpyxl`); `.xls` / `.csv` **reddedilir** → `422` |
| Yanıt | `200 UnitImportResult` |

Bağımlılıklar hazır: `openpyxl>=3.1` ve `python-multipart>=0.0.20` `pyproject.toml`'da
zaten var (BOQ Excel dışa aktarımından) — yeni paket eklenmez.

**Beklenen sütun düzeni** (ilk satır başlık; başlıklar Türkçe, mockup etiketleriyle birebir):

| Sütun | Başlık | Zorunlu | Hedef alan | Mockup kaynağı |
|---|---|---|---|---|
| A | `Blok` | ✓ | `blocks.name` (yoksa **oluşturulur**, §4.5 şantiye kuralıyla) | KY 271, SY 74 |
| B | `Ünite No` | ✓ | `unit_no` | KY 281, SY 76–99 |
| C | `Tür` | ✓ | `unit_kind` — `Daire`→`apartment`, `Dükkan`→`shop` | KY 71, 308 |
| D | `Tip` | — | `layout` | KY 272 |
| E | `Brüt m²` | — | `gross_area_m2` | KY 273, FDS 59 |
| F | `Net m²` | — | `net_area_m2` | FDS 59 |
| G | `Liste Fiyatı` | — | `list_price` | KY 274 |
| H | `Rayiç Değer` | — | `appraisal_value` | KKP 89 |
| I | `Pay` | — | `owner_side` — `BİZ`→`contractor`, `ARSA`→`landowner`, boş→`NULL` | KKP 90/100/109 |

Başlık eşleştirmesi büyük/küçük harf ve baştaki/sondaki boşluklardan bağımsızdır; Türkçe
karakter normalizasyonu yapılır (`İ/ı`). Beklenmeyen ek sütunlar **yok sayılır**. Zorunlu
başlıklardan biri eksikse dosya hiç işlenmez → `422 Excel başlıkları eksik: Blok, Ünite No`.

**Sınırlar** (modül sabitleri, sihirli sayı yok):

| Sabit | Değer | Gerekçe |
|---|---|---|
| `_MAX_IMPORT_BYTES` | **2 MB** | 1000 satırlık bir `.xlsx` ~50 KB'tır; 2 MB fazlasıyla yeterli, bellek saldırısını keser |
| `_MAX_IMPORT_ROWS` | **1000** | KY'de 52, KKP'de 42 ünite var; 1000 en büyük gerçekçi projenin üstünde |

Sınır aşımı → `422` (`413` değil: hata gövdesi Türkçe mesaj taşısın, aynı hata sözleşmesi kalsın).

**Doğrulama kuralları** (satır satır, tekil `POST` ile birebir aynı kurallar):
zorunlu alan boş; `Tür` sözlükte yok; sayısal alan sayıya çevrilemiyor; negatif değer;
`net > brüt`; `Pay` dolu ama proje `kat_karsiligi` değil; dosya içinde aynı `(Blok, Ünite No)`
iki kez; blokta o `unit_no` zaten var.

**Kısmi başarısızlık davranışı — ÖNERİ: hep-ya-hiç + satır bazlı rapor (ikisi birden).**
Tek transaction'da tüm satırlar doğrulanır; **bir** satır bile hatalıysa **hiçbiri yazılmaz**
ve `422` gövdesinde `errors: [{row, column, message}]` listesi döner (en fazla ilk **50** hata;
fazlası `Ve N hata daha` özetiyle bildirilir). Başarıda `200` + `created` / `blocks_created`.

Gerekçe: yarı yazılmış bir içe aktarımdan sonra kullanıcı dosyayı düzeltip **tekrar**
yükleyemez (başarılı satırlar artık çakışır) — elle temizlik gerekir. Hep-ya-hiç, "düzelt ve
yeniden yükle" döngüsünü tek adımda tekrarlanabilir kılar. Satır bazlı rapor da korunur,
çünkü tek tek "ilk hatada dur" 48 satırlık bir dosyayı 48 kez yüklemeye zorlardı.

Denetim günlüğü: **istek başına tek satır** (§9).

### 7.9 DELETE uçları *(kullanıcı kararı — mockup yok)*

Rev. 1'de "DELETE yok" yazıyordu; kullanıcı 2026-07-30'da DELETE açılmasına karar verdi.

**`DELETE /units/{unit_id}`** → `204 No Content`.
Kimlik yukarı çözümlenir; görünmeyen proje / olmayan ünite → **404**.
Bağlı kayıt yok (P3'te üniteye bağlanan hiçbir tablo yok — §1.3), bu yüzden **koşulsuz silinir**.
P8 geldiğinde satışı olan ünite için korkuluk **o dilimde** eklenecektir (ileri bağ bugün açılmaz).

**`DELETE /blocks/{block_id}`** → `204 No Content`.
Bağlı kayıt korkuluğu: blokta **en az bir ünite varsa** silme **engellenir** →
**409** `Bu blokta ünite var, önce üniteleri silin` (ünite adedi mesajda **verilmez** —
görünürlük dışı bilgi sızdırmaz; ünite sayısını zaten GET ile görüyor).
Cascade **yapılmaz**: 24 daireyi tek tıkla sessizce silmek geri alınamaz veri kaybıdır.
DB tarafında da `ON DELETE RESTRICT` (§4.2) bunu ikinci kez garantiler.

İkisi de denetim günlüğüne yazar (§9).

### 7.10 `PATCH /projects/{project_id}/units/allocation`

KKP 25 "Paylaşımı Kaydet".

| | |
|---|---|
| Gövde | `UnitAllocationRequest` |
| Yanıt | `200 UnitListResponse` (güncel özet — ekran tabloyu yeniden çizer) |
| Hata | `404` görünmeyen proje **veya listede başka projeye ait / olmayan ünite** · `422` proje tipi `kat_karsiligi` değil |

**Atomiktir**: tek satır bile reddedilirse hiçbiri yazılmaz (tek transaction, doğrulama
yazmadan önce). Listede tekrarlanan `unit_id` → `422` ("Aynı ünite listede birden çok kez var").

### 7.11 Türkçe hata mesajları

| Sabit | Metin | Kod |
|---|---|---|
| `_PROJECT_MISSING` | `Proje bulunamadı` | 404 |
| `_BLOCK_MISSING` | `Blok bulunamadı` | 404 |
| `_UNIT_MISSING` | `Ünite bulunamadı` | 404 |
| `_SITE_MISSING` | `Şantiye bulunamadı` | 404 |
| `_DUPLICATE_BLOCK` | `Bu blok adı bu projede zaten kullanılıyor` | 409 |
| `_DUPLICATE_UNIT` | `Bu ünite numarası bu blokta zaten kullanılıyor` | 409 |
| `_BLOCK_HAS_UNITS` | `Bu blokta ünite var, önce üniteleri silin` | 409 |
| `_BULK_NUMBERS_TAKEN` | `Üretilecek ünite numaralarından bazıları blokta zaten var` | 409 |
| `_NO_SITE_FOR_BLOCK` | `Blok tanımlamadan önce projeye şantiye eklenmelidir` | 422 |
| `_SITE_REQUIRED` | `Birden fazla şantiye var, blok için şantiye seçilmelidir` | 422 |
| `_OWNER_SIDE_NOT_ALLOWED` | `Ünite payı yalnızca kat karşılığı projelerde belirlenebilir` | 422 |
| `_ALLOCATION_WRONG_TYPE` | `Paylaşım yalnızca kat karşılığı projelerde kaydedilebilir` | 422 |
| `_NET_GT_GROSS` | `Net alan brüt alandan büyük olamaz` | 422 |
| `_DUPLICATE_IN_PAYLOAD` | `Aynı ünite listede birden çok kez var` | 422 |
| `_INVALID_FLOOR_RANGE` | `Bitiş katı başlangıç katından küçük olamaz` | 422 |
| `_BULK_LIMIT` | `Tek seferde en fazla 500 ünite üretilebilir` | 422 |
| `_IMPORT_BAD_TYPE` | `Yalnızca .xlsx dosyası yüklenebilir` | 422 |
| `_IMPORT_TOO_LARGE` | `Dosya çok büyük (en fazla 2 MB)` | 422 |
| `_IMPORT_TOO_MANY_ROWS` | `Dosyada en fazla 1000 satır olabilir` | 422 |
| `_IMPORT_MISSING_HEADERS` | `Excel başlıkları eksik: {alanlar}` | 422 |
| `_IMPORT_ROW_ERRORS` | `Dosya işlenemedi, {n} satırda hata var` | 422 |

---

## 8. Görünürlük / yetki — **karara bağlandı**

**Karar (kullanıcı, 2026-07-30): yeni izin modülü AÇILMAZ. `projects` modülünün seviyeleri
kullanılır.**

- `GET` uçları → `require_permission("projects", AccessLevel.view)`
- `POST` / `PATCH` / `DELETE` uçları → `require_permission("projects", AccessLevel.full)`

Görünürlük süzgeci **yeniden yazılmaz**: `app.modules.projects.service.visible_projects`
import edilir (P2'nin `app/modules/sites/service.py:16` deseni). Kopya süzgeç = zamanla
ayrışan sessiz yetki sızıntısı.

Gerekçe:

1. `Ayarlar - İzin Matrisi` mockup'ında **ünite/blok/satış satırı yoktur** → sapma yok.
   (`boq`'ta sapma **kaçınılmazdı**; burada değil — `GOREV-SIRASI.md` §4.2.)
2. Ünite ve blok, projenin alt kayıtlarıdır — P1'de `employers` için de aynı karar verildi
   (`projects/models.py:56`: "Yeni izin modülü AÇILMAZ").
3. `boq`'u ayırmayı zorunlu kılan rol ayrımı (`site_chief` görür / `field_engineer` görmez)
   ünite için hiçbir mockup'ta talep edilmiyor.
4. **Sıfır migration, sıfır matris genişlemesi, sıfır parity testi güncellemesi.**
   Modül sayısı **17'de kalır** — `tests/modules/test_seed_matrix.py`,
   `test_roles_repository.py`, `test_roles_api.py` ve frontend `e2e/mock-backend.ts`
   **dokunulmaz**; `ayarlar-izin-matrisi` görsel baseline'ı üçüncü kez kaymaz.

İleride "satış ekibi projeyi görsün ama bütçeyi görmesin" istenirse ayrı modül eklemek
**additive**'dir (P4'te `boq` modülünün sonradan eklenmesi gibi) — bugün borç yaratmıyor.

---

## 9. Denetim günlüğü

B5 deseni: `record_audit(...)` **yalnız yazma uçlarında**; okuma uçları (§7.1, §7.4) yazmaz
(P4 T7 kuralı, `boq/router.py` export ucundaki nota bakınız).

`app/modules/audit/messages.py`'ye eklenecek fonksiyonlar (mevcut biçim: fiil + iki nokta + ad):

```python
def block_created(project_name: str, block_name: str) -> str:
    return f"Yeni blok oluşturuldu: {project_name} · {block_name}"

def block_updated(project_name: str, block_name: str) -> str:
    return f"Blok güncellendi: {project_name} · {block_name}"

def block_deleted(project_name: str, block_name: str) -> str:
    return f"Blok silindi: {project_name} · {block_name}"

def unit_created(project_name: str, block_name: str, unit_no: str) -> str:
    # Unite adlari projeler arasinda tekrar eder ("A Blok · Daire 1" her projede olabilir);
    # proje adi olmadan denetim satiri anlamsizlasir (section_created ile ayni gerekce).
    return f"Yeni ünite oluşturuldu: {project_name} · {block_name} · {unit_no}"

def unit_updated(project_name: str, block_name: str, unit_no: str) -> str:
    return f"Ünite güncellendi: {project_name} · {block_name} · {unit_no}"

def unit_deleted(project_name: str, block_name: str, unit_no: str) -> str:
    return f"Ünite silindi: {project_name} · {block_name} · {unit_no}"

def units_bulk_created(project_name: str, block_name: str, count: int) -> str:
    return f"Toplu ünite üretildi: {project_name} · {block_name} · {count} ünite"

def units_imported(project_name: str, count: int) -> str:
    return f"Üniteler Excel'den içe aktarıldı: {project_name} · {count} ünite"

def unit_allocation_updated(project_name: str, count: int) -> str:
    return f"Ünite paylaşımı güncellendi: {project_name} · {count} ünite"
```

| Uç | `AuditAction` | Mesaj |
|---|---|---|
| `POST /projects/{id}/blocks` | `create` | `block_created` |
| `PATCH /blocks/{id}` | `update` | `block_updated` |
| `DELETE /blocks/{id}` | `delete` | `block_deleted` |
| `POST /projects/{id}/units` | `create` | `unit_created` |
| `PATCH /units/{id}` | `update` | `unit_updated` |
| `DELETE /units/{id}` | `delete` | `unit_deleted` |
| `POST /projects/{id}/units/bulk` | `create` | `units_bulk_created` — **istek başına tek satır** |
| `POST /projects/{id}/units/import` | `create` | `units_imported` — **istek başına tek satır** |
| `PATCH /projects/{id}/units/allocation` | `update` | `unit_allocation_updated` — **istek başına tek satır** (42 ünitelik bir kayıt günlüğü boğar) |

`actor_user_id=user.id`, `ip_address=client_ip(request)` — mevcut desen.
Toplu uçlarda satır başına günlük **yazılmaz**; gerekçe yukarıdaki gibi hacimdir.

---

## 10. Migration planı

### 10.1 Ebeveyn revizyon

**Karara bağlandı (2026-07-30):** PR #4 merge edildi, `e3a8b4a5b93b`
(`boq_procurement_izin_duzeltmesi`) `main`'dedir. `down_revision = "e3a8b4a5b93b"`.

**Yine de B1 task'ında `.venv/bin/alembic heads` KOŞULUR ve çıktı doğrulanır.** İki head
çıkarsa **kod yazılmaz**, kullanıcıya sorulur (birleştirme revizyonu kullanıcı kararıdır).

### 10.2 Upgrade

1. `unit_kind` enum tipi (`apartment`, `shop`)
2. `unit_owner_side` enum tipi (`contractor`, `landowner`)
3. **`blocks` tablosu** + 2 UNIQUE + 2 index (§4.1)
4. `units` tablosu + 5 CHECK + 1 UNIQUE + bileşik FK + 2 index (§4.3)

Sıra önemlidir: `units` bileşik FK'sı `uq_blocks_project_id_id`'e bağlıdır, `blocks` önce gelir.

### 10.3 Downgrade

`units` düşürülür → `blocks` düşürülür → **iki enum tipi de `DROP TYPE`** edilir
(Postgres'te `ENUM` tablo ile birlikte silinmez; P1'in `project_type`/`project_status`
migration'larındaki desen izlenir). `upgrade → downgrade → upgrade` yalnız **tek kullanımlık
yerel DB'de** koşulur; canlıya migration koşulmaz (`GOREV-SIRASI.md` §3).

### 10.4 Veri geçişi ve kilit riski

- **Veri geçişi yok**: `blocks` ve `units` yepyeni tablolardır, mevcut satır dönüştürülmez.
- **Tablo kilidi yok**: mevcut hiçbir tabloya `ALTER` yapılmaz — `projects` ve **`sites` dahil**.
  `blocks.site_id` bir FK'dır, `sites`'e sütun eklemez; şantiye↔proje tutarlılığı
  (§4.5) **servis korkuluğuyla** sağlanır, `sites` üzerinde yeni UNIQUE index açılmaz.
  `CREATE TABLE` + `CREATE TYPE` üretim trafiğini bloke etmez.
- İzin kararı §8 olduğu için `modules` / `role_permissions` tablolarına **dokunulmaz**.

---

## 11. Test stratejisi

**TDD zorunlu:** önce test, **KIRMIZI GÖRÜLECEK**, sonra kod.

### 11.1 TEST DB TUZAĞI (uygulama notu — `GOREV-SIRASI.md` §3'ten tekrar)

`backend/.env` içindeki `TEST_DATABASE_URL` **UZAK Railway'i** gösteriyor ve
`tests/conftest.py` `drop_all` çağırıyor → o env ile pytest **canlı benzeri DB'yi siler**.
Her task tek kullanımlık yerel DB açar, env'i **komut satırında** verir, `.env`'e **DOKUNMAZ**:

```bash
createdb p3_units_t1 && \
  TEST_DATABASE_URL="postgresql+asyncpg://furkanilgen@localhost:5432/p3_units_t1" .venv/bin/pytest
dropdb p3_units_t1      # basarisizlikta BILE
```

`python` PATH'te **yok** → `.venv/bin/{python,pytest,alembic,ruff}`. Ruff **0.15.22**'ye sabitli.
Kapılar: `.venv/bin/pytest` + `.venv/bin/ruff check` + `.venv/bin/ruff format --check`.

### 11.2 Birim (servis/şema)

1. `unit_price_per_m2`: normal, `gross_area_m2 = None`, `gross_area_m2 = 0` → `None`
2. `label` türevi: `"A Blok"` + `"Daire 12"` → `"A Blok · Daire 12"` (KY 281)
3. `UnitKindBreakdown`: 48 daire + 4 dükkan → `total = 52` (KY 71/88)
4. `value_basis` seçimi: `kat_karsiligi` → `appraisal_value`; `kendi_yatirim` ve `taahhut` →
   `list_price` (§4.4)
5. `total_value`: `value_basis` sütunu `NULL` olan satırlar 0 sayılır, toplam bozulmaz;
   `total_list_price` ve `total_appraisal_value` **ayrı ayrı** doğru döner
6. `average_value`: 0 ünitede `None` (sıfıra bölme yok)
7. `unit_share` yüzdesi: 23/42 → `54.76`; sözleşme %55'ten sapma **hata değil** (§5.2)
8. `sides`: `contractor` / `landowner` / `None` üçü de döner, hiç ünite yoksa da (boş grup 0'lı)
9. Yer tutucu alanları `available=False` ve doğru `pending_module` taşır
10. Sıralama: blok `sort_order` → `name`; blok içinde `sort_order` → `unit_no`;
    `"10"` `"2"`'den önce gelmez (`sort_order` sayesinde)
11. Toplu üretim numaralandırması: `sequential` 1…24 (SY 76–99); `floor_based`
    `start_floor=1,end_floor=2,units_per_floor=2` → `101,102,201,202`; `prefix="D"` → `D1…D4`
    (SY 132–135)
12. Excel başlık normalizasyonu: `"  liste fiyatı "` → `list_price`; `"LİSTE FİYATI"` → aynı

### 11.3 Entegrasyon (API)

**Blok**
1. `POST /projects/{id}/blocks` — tek şantiyeli projede `site_id` **gönderilmeden** → `201`,
   şantiye **otomatik atanmış** (§4.5)
2. `POST` — şantiyesiz projede → `422` `_NO_SITE_FOR_BLOCK`
3. `POST` — iki şantiyeli projede `site_id` yok → `422` `_SITE_REQUIRED`; `site_id` ile → `201`
4. `POST` — başka projenin `site_id`'si → `404`
5. `POST` — aynı ad ikinci kez → `409`
6. `PATCH /blocks/{id}` — `site_id` değişimi; başka projenin şantiyesi → `404`
7. `GET /projects/{id}/blocks` — ünitesi olmayan blok da döner

**Ünite okuma**
8. `GET` — blok gruplaması ve toplamlar mockup örneğiyle (KKP 42 ünite / 23-19 /
   30.415.000 · 24.885.000 ölçeğinde kurgulanmış fikstür) uyuşur
9. `GET` — `block_id` / `site_id` / `kind` / `owner_side=unassigned` süzgeçleri;
   **`totals` süzgeçten etkilenmez**
10. `GET` — `kendi_yatirim` projede `value_basis == "list_price"`; `kat_karsiligi`'nda
    `"appraisal_value"`

**Ünite yazma**
11. `POST` — 201 + gövde; aynı blokta ikinci kez aynı `unit_no` → **409** + Türkçe mesaj
12. `POST` — **farklı blokta** aynı `unit_no` → **201** (A Blok 1 ve B Blok 1, SY 76/106)
13. `POST` — başka projenin `block_id`'si → **404**
14. `POST` — `taahhut` projede ünite → **201** (§3.3, kısıt icat edilmedi)
15. `POST` — `kendi_yatirim` projede `owner_side` gönder → **422**
16. `POST` — `kendi_yatirim` projede `appraisal_value` gönder → **201** (reddedilmez, §3.3)
17. `PATCH /units/{id}` — kısmi güncelleme; gönderilmeyen alan değişmez; `layout: null`
    gönderimi alanı boşaltır
18. `PATCH` — `net > gross` → **422** (§4.3 CHECK'i öncesinde servis mesajı verir)
19. `PATCH` — `block_id` değişimi; hedef blokta `unit_no` çakışması → **409**

**DELETE**
20. `DELETE /units/{id}` → **204**; ikinci çağrı → **404**
21. `DELETE /blocks/{id}` — ünitesi olan blok → **409** `_BLOCK_HAS_UNITS`, blok **duruyor**
22. `DELETE /blocks/{id}` — boş blok → **204**
23. `DELETE /blocks/{id}` — üniteler silindikten sonra → **204** (akış doğrulanır)

**Toplu üretim**
24. `POST …/units/bulk` — 2 kat × 12 daire = 24 ünite, `sequential` → `201`, `totals.counts.total == 24`
25. `bulk` — üretilen numaralardan biri zaten var → **409**, **hiçbir satır yazılmamış**
    (öncesi/sonrası sayım eşit)
26. `bulk` — `end_floor < start_floor` → **422**; 501 ünite → **422** `_BULK_LIMIT`

**Excel içe aktarma**
27. `import` — geçerli 10 satırlık `.xlsx` (testte `openpyxl` ile bellekte üretilir) → `200`,
    `created == 10`, yeni blok adı geçtiyse `blocks_created == 1`
28. `import` — 3. satırda `net > brüt` → **422**, `errors[0].row == 3`,
    **hiçbir ünite yazılmamış** (hep-ya-hiç doğrulanır)
29. `import` — zorunlu başlık eksik → **422** `_IMPORT_MISSING_HEADERS`
30. `import` — `.csv` yüklenirse → **422** `_IMPORT_BAD_TYPE`
31. `import` — 2 MB üstü / 1000 satır üstü → **422**
32. `import` — dosya **hiçbir yere yazılmaz**: istek sonrası geçici dizinde/DB'de dosya
    izi kalmadığı doğrulanır (belge saklama altyapısı gerekmediğinin kanıtı)

**Paylaşım**
33. `PATCH allocation` — 42 satır tek istekte; yanıt güncel `UnitListResponse`
34. `PATCH allocation` — listede tekrarlanan `unit_id` → **422**, hiçbir satır yazılmaz
35. `PATCH allocation` — `kendi_yatirim` projede → **422**

**Denetim**
36. Her yazma **bir** `audit_log` satırı üretir; allocation 42 satır için **1**, bulk 24 ünite
    için **1**, import 10 ünite için **1** kayıt
37. Okuma uçları `audit_log`'a **hiç** yazmaz
38. DELETE uçları `AuditAction.delete` ile yazar

### 11.4 IDOR negatif seti (kimliği yukarı çözümleyen her uç)

| # | Senaryo | Beklenen |
|---|---|---|
| 1 | `GET /projects/{gizli}/units` (kullanıcının erişimi yok) | **404** "Proje bulunamadı" |
| 2 | `GET /projects/{gizli}/blocks` | **404** |
| 3 | `POST /projects/{gizli}/units` · `.../blocks` · `.../units/bulk` · `.../units/import` | **404** (403 **değil**) |
| 4 | `PATCH /units/{id}` — ünite görünmeyen projeye ait | **404** "Ünite bulunamadı" |
| 5 | `PATCH /blocks/{id}` — blok görünmeyen projeye ait | **404** "Blok bulunamadı" |
| 6 | `DELETE /units/{id}` / `DELETE /blocks/{id}` — görünmeyen projeye ait | **404** |
| 7 | `PATCH`/`DELETE` — var olmayan UUID | **404**, aynı mesaj (ayırt edilemez) |
| 8 | `PATCH /projects/{A}/units/allocation` — listede **B projesinin** ünitesi | **404**, A'nın hiçbir satırı **değişmez** (atomiklik doğrulanır) |
| 9 | `POST /projects/{A}/units` — `block_id` B projesine ait | **404** |
| 10 | Excel'de `Blok` sütunu başka projenin bloğuyla aynı adı taşıyor | yeni blok **A projesinde** açılır, B'ye dokunulmaz |
| 11 | Token yok | **401** |
| 12 | `projects` izni `none` | **403** |
| 13 | `projects` izni `view` iken `POST`/`PATCH`/`DELETE`/`bulk`/`import`/`allocation` | **403** |
| 14 | `projects=admin` rolü — görünürlük süzgecini atlar (P1 kilitlenme koruması) | **200** |

Her negatif senaryoda yanıt gövdesinin **kayıt varlığını sızdırmadığı** ayrıca doğrulanır.

### 11.5 Parity / regresyon

- **Modül sayısı testleri (17) DEĞİŞMEZ** — §8 kararı gereği. Bunun böyle kaldığı açıkça
  koşulur (`test_seed_matrix.py`, `test_roles_repository.py`, `test_roles_api.py` yeşil kalır).
- Migration: `upgrade → downgrade → upgrade` yerel DB'de yeşil; `alembic heads` **tek** head.
- B11: `openapi.json` üretilir (gitignore'lu, commit edilmez), frontend'e kopyalanmaya hazır.

---

## 12. Kararlar ve kalan açık sorular

### 12.1 Karara bağlandı (2026-07-30 · kullanıcı)

| # | Konu | Karar | Spec'te nerede |
|---|---|---|---|
| 1 | Ünite ↔ şantiye bağı | **Hiyerarşi Proje › Şantiye › Blok › Ünite.** `blocks.site_id` FK; `units`'te `site_id` **YOK** | §4.0, §4.5, §13.2 |
| 2 | Blok ayrı tablo mu | **EVET, `blocks` tablosu açılır.** UI değişmez (blok yine grup başlığı). Kat sayısı/teslim tarihi **şimdi eklenmez** | §4.1, §13.1 |
| 3 | `taahhut` projede ünite | **Serbest** — kısıt icat edilmez | §3.3 |
| 4 | Fiyat sütunu | **İKİ AYRI SÜTUN**: `list_price` (KY 274 "Liste Fiyatı") + `appraisal_value` (KKP 89 "Rayiç Değer"); ikisi de nullable | §4.4 |
| 5 | `net_area_m2 <= gross_area_m2` | **DB CHECK olarak konur** (`ck_units_net_le_gross`) | §4.3 |
| 6 | İzin | **Yeni izin modülü AÇILMAZ** — okuma `projects:view`, yazma `projects:full`. Modül sayısı 17'de kalır | §8 |
| 7 | DELETE uçları | **Ünite DELETE + blok DELETE açılır.** Ünitesi olan blok → 409 + Türkçe mesaj; cascade yok. Denetim günlüğüne yazılır | §7.9 |
| 8 | Teslim takibi kilometre taşları (KKP 176–193) | **P3 kapsamı dışı → P11 (Gantt)** | §1.2 |
| 9 | Sözleşme yükümlülük maddeleri (KK 194–199) + "(ipotek)" teminat türü (KK 191) | **P3 kapsamı dışı → P5 (Sözleşmeler).** Ekranda alanlar boş kalır; `project_land_share` dokunulmaz | §1.2, §3.1 |
| 10 | Paylaşım Excel **dışa** aktarımı (KKP 24) | **P3 kapsamı dışı → P5 / raporlar** | §1.2 |
| 11 | Toplu ünite üretimi | **AÇILIR** (`POST …/units/bulk`) + ayrıca **Excel içe aktarma** (`POST …/units/import`, dosya **saklanmaz**) | §6.3, §6.4, §7.7, §7.8 |
| 12 | Dilim numaralandırması (P3/P8/P9) | **ONAYLANDI** | — |
| 13 | Migration ebeveyni | PR #4 merge edildi → `e3a8b4a5b93b` `main`'de. B1'de `alembic heads` ile yine de doğrulanır | §10.1 |

### 12.2 Hâlâ açık

**Yok.** Bu spec'in uygulanması için karar bekleyen soru kalmamıştır.
Uygulama sırasında ortaya çıkabilecek tek doğrulama noktası §10.1'deki `alembic heads`
çıktısıdır; iki head çıkarsa kod yazılmaz, kullanıcıya sorulur.

---

## 13. Onaylı sapmalar

> `GOREV-SIRASI.md` §4.1 ("hiçbir ileri bağ açılmaz") ve %100 mockup sadakati kuralından
> **bilinçli** iki sapma. İkisi de **kullanıcı kararıdır**, ajan kararı değildir; geri
> alınmayacaktır. Bir sonraki ajan bunları "spec ihlali" sanıp düzeltmeye kalkmamalıdır.

### 13.1 `blocks` ayrı tablo *(kullanıcı, 2026-07-30)*

**Sapma:** rev. 1'de blok, `units.block` metin alanıydı ve "ayrı `blocks` tablosu
spekülatif genellemedir" diye reddedilmişti. Mockup'ta blok için CRUD, blok özelliği veya
blok kimliği **yok** — blok yalnız grup başlığı olarak görünüyor (KY 281, SY 74/104, KKP 96).

**Karar:** `blocks` ayrı tablo olacak.

**Gerekçe:** blok, kullanıcının kafasında bir *kayıt*tır (bir binadır), bir *etiket* değil.
Metin alanı olarak tutulunca "A Blok" / "A blok" / "A-Blok" yazım farkları sessizce iki ayrı
grup üretir ve toplamları bozar; blok adını değiştirmek N satırlık bir `UPDATE` olur;
blok–şantiye bağı (§13.2) hiç kurulamaz. Ayrıca §13.2 kararı zaten bir blok kimliği gerektiriyor.

**Sınır (bu sapma nereye kadar):** tablo **minimaldir** — `id`, `project_id`, `site_id`,
`name`, `sort_order`, zaman damgaları. Kat sayısı, teslim tarihi, blok kodu, blok durumu
**ŞİMDİ EKLENMEZ**; ihtiyaç doğduğunda additive olarak eklenecektir (§4.1 notu).

**UI etkisi: YOK.** Blok ekranda yine grup başlığı olarak görünür (SY 74 "A Blok — 24 Daire",
KY 271 "A Blok · Daire 12"). Mockup'a birebir sadakat korunur; blok yönetimi ekranı bu
dilimde **çizilmez** — bloklar ünite formundan / toplu üretimden / Excel'den örtük oluşur
(§7.8 A sütunu) ya da `POST /projects/{id}/blocks` ile açılır.

### 13.2 Blok–şantiye bağı: hiyerarşi Proje › Şantiye › Blok › Ünite *(kullanıcı, 2026-07-30)*

**Sapma:** rev. 1'de hiyerarşi Proje › Blok › Ünite'ydi ve `site_id` "mockup'ta karşılığı yok"
diye reddedilmişti (KY 38 / KK 39 kenar çubuğunda ünite ile şantiye arasında bağ kurulmuyor;
FDS 54–55'te seçim sırası Proje → Blok/Ünite, arada şantiye adımı yok).

**Karar:** `blocks.site_id` **zorunlu** FK. `units`'te `site_id` **yoktur** — şantiye blok
üzerinden türetilir.

**Gerekçe:** bir blok fiziksel olarak tek bir şantiyede durur; bu bağ ileri bir dilimin
ihtiyacı değil, bugünün gerçeğidir. Çok şantiyeli bir projede blok–şantiye bağı olmadan
şantiye bazlı ünite/değer raporu **hiç** üretilemez ve sonradan eklenmesi mevcut satırların
elle eşleştirilmesini gerektirir. Bağı bloğa (üniteye değil) koymak tek otorite bırakır:
24 dairenin 24'ünde `site_id` tekrarlanmaz, dolayısıyla kayma imkânsızdır.

**Sınır:** `sites` tablosuna **hiç dokunulmaz** (sütun yok, index yok, ALTER yok — §10.4).
Bağ tek yönlüdür (`blocks → sites`); `sites` tarafında blok bilgisi tutulmaz.

**UI etkisi: YOK (tek şantiyeli projede).** Tek şantiyeli projede şantiye **otomatik atanır**
ve ekranda seçici gösterilmez — mockup'ın kanonik durumu budur (KY 38 / KK 39 tekil
"📍 Şantiye" girdisi). Çok şantiyeli projede seçim zorunludur; o ekran zaten mockup'ta yok (§4.5).

---

## 14. P3 dışı takip işleri

| İş | Neden burada değil | Kime bağlı |
|---|---|---|
| **`boq` DELETE ucu** (`DELETE /boq/items/{id}`, `DELETE /boq/groups/{id}`) — kullanıcı 2026-07-30'da BOQ kalemi için de DELETE kararı verdi | `boq` **ayrı bir dilimdir** (P4, kapandı ve canlıda); P3 içine karıştırmak iki modülü tek PR'da riske atar | **Frontend BOQ ekranı (`GOREV-SIRASI.md` §1) bu uca bağımlıdır** — F8 (kalem düzenleme) akışında silme düğmesi varsa uç önce açılmalı. `GOREV-SIRASI.md` §5'teki "BOQ DELETE ucu açılacak mı?" sorusu bu kararla **kapanmıştır**, geriye yalnız uygulaması kalmıştır |
| Paylaşım tablosu Excel **dışa** aktarımı (KKP 24) | P5 / raporlar dilimi | — |
| Teslim kilometre taşları (KKP 176–193) | P11 (Gantt) | — |
| Sözleşme yükümlülükleri + teminat türü (KK 191, 194–199) | P5 (Sözleşmeler) | `project_land_share` şemasına dokunacaktır |

---

## 15. Task listesi (B0–B12)

Rev. 1'de 9 task vardı (B0–B8). Blok tablosu, DELETE uçları, toplu üretim ve Excel içe
aktarma eklendiği için **13 task**tır (B0–B12). Eski B6 (izin kararı) **kaldırıldı** —
§8 kararı gereği yapılacak iş yok; yerine dört yeni task geldi (blok yazma, DELETE, toplu
üretim, Excel içe aktarma) ve yazma tasklarının ayrışması bir task daha ekledi.

| Task | Ne yapılacak | Bağımlı |
|---|---|---|
| **B0** | Spec (bu dosya) → **kullanıcı onayı**; sonra plan yaz → **onay** | — |
| **B1** | `blocks` + `units` modelleri + migration. Ebeveyn `e3a8b4a5b93b`, **`alembic heads` ile DOĞRULA** (§10.1). `blocks` önce, `units` bileşik FK'sı sonra (§10.2). upgrade→downgrade→upgrade yerel DB'de yeşil | B0 |
| **B2** | Pydantic şemaları: `BlockCreate/Update/Response`, `UnitCreate/Update/Response`, `UnitTotals` (+`value_basis`), `UnitSideSummary`, `UnitBlockGroup`, `UnitAllocation*`. `MetricPlaceholder` P1'den **import** edilir | B1 |
| **B3** | Repository + service **okuma yolu**: blok gruplaması, `value_basis` seçimi (§4.4), taraf toplamları, `unit_share` türevi. P2'nin `visible_projects` süzgeci **yeniden kullanılır** | B2 |
| **B4** | Okuma uçları (`GET …/blocks`, `GET …/units`) + router kaydı + süzgeçler. Görünmeyen kayıt → **404**, 403 değil | B3 |
| **B5** | **Blok yazma uçları** (`POST …/blocks`, `PATCH /blocks/{id}`) + §4.5 tek/çok şantiye kuralı + Türkçe mesajlar | B4 |
| **B6** | **Ünite yazma uçları** (`POST …/units`, `PATCH /units/{id}`) + tip korkulukları (§3.3) + Türkçe mesajlar | B5 |
| **B7** | **DELETE uçları** (`DELETE /units/{id}`, `DELETE /blocks/{id}`) + `_BLOCK_HAS_UNITS` korkuluğu (§7.9) | B6 |
| **B8** | **Toplu üretim ucu** (`POST …/units/bulk`) + numaralandırma desenleri + hep-ya-hiç çakışma kontrolü (§6.3, §7.7) | B6 |
| **B9** | **Excel içe aktarma ucu** (`POST …/units/import`) — multipart, `openpyxl`, **dosya saklanmaz**, başlık eşleme, hep-ya-hiç + satır bazlı hata raporu, boyut/satır sınırları (§6.4, §7.8) | B6, B5 (blok örtük oluşumu için) |
| **B10** | **Paylaşım ucu** (`PATCH …/units/allocation`) + atomiklik + **IDOR negatif setinin tamamı** (§11.4) | B6 |
| **B11** | Denetim günlüğü (`record_audit` + `audit/messages.py` 9 Türkçe mesaj, §9); okuma uçları yazmaz | B5–B10 |
| **B12** | `openapi.json` üretimi + tam kapı koşusu (`pytest` + `ruff check` + `ruff format --check`). Frontend'e kopyalanmaya hazır | B1–B11 |

> Sayım notu: B0–B12 = **13 task**. (B0 spec/plan task'ı sayılmazsa uygulama tarafında **12 task**.)

Sonra: PR → CI → merge → **canlı migration doğrulaması** (`railway logs` / `alembic current`).
