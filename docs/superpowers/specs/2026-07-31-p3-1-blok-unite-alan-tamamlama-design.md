# Alt-Proje 2 · P3.1 — Blok/ünite alanlarının form mockup'larına göre tamamlanması (tasarım)

Tarih: 2026-07-31 · **revizyon 2 (2026-07-31 akşam — 13 karar işlendi)**
Repo: `fiilyapi-backend` (`/Users/furkanilgen/Documents/Projeler/insaat/backend`)
Durum: **yalnız tasarım.** Kod, migration, test yazılmadı; commit atılmadı.

> **Not (çıktı yolu):** bu dosya geçici olarak repo dışında (`insaat/P3-1-SPEC-TASLAK.md`)
> durmaktadır çünkü yazıldığı sırada backend reposunda başka bir oturum (P5) çalışıyordu.
> Onaydan sonra `backend/docs/superpowers/specs/2026-07-31-p3-1-blok-unite-alan-tamamlama-design.md`
> yoluna taşınacaktır.

> **Revizyon 2'de ne değişti:**
> 1. §13'ün 13 açık sorusu **karara bağlandı** — bölüm yeniden yazıldı (kalan tek soru §13.2'de).
> 2. **P5 ve P7 dilimleri bitti, merge edildi ve canlıya alındı.** Bunun bu spec'e üç etkisi var:
>    izin modülü sayısı **17 değil 18** (`contracts` eklendi) · `boq_items.contract_item_id`
>    **açıldı** (P5, onaylı sapma — §1.3) · migration ebeveyni ilerledi (§10.1).
> 3. **MIGRATION TUZAĞI** uygulama notlarına eklendi (§10.1, §12) — P7'de canlı crash'e yol açtı.
> 4. Onaylı sapma listesi 3 → **7** (§11).

## Mockup kanonu (satır satır okundu, tamamı)

| Kısaltma | Dosya | Satır |
|---|---|---|
| **BE** | `projedesign/Form - Blok Ekle.dc.html` | 121 |
| **UE** | `projedesign/Form - Unite Ekle.dc.html` | 134 |
| **TU** | `projedesign/Form - Toplu Unite.dc.html` | 190 |
| **EI** | `projedesign/Form - Unite Excel Import.dc.html` | 209 |

Bağlam mockup'ları (P3'te zaten haritalanmış, burada yeniden haritalanmaz):
`Proje - Kendi Yatırım.dc.html` (**KY**), `Proje - Kat Karşılığı.dc.html` (**KK**),
`Kat Karşılığı - Paylaşım.dc.html` (**KKP**), `Satış Yönetimi.dc.html` (**SY**),
`Form - Daire Satisi.dc.html` (**FDS**).

## Bağlı belgeler

- `backend/docs/superpowers/specs/2026-07-30-alt-proje-2-p3-proje-tip-detay-units-design.md` — **P3**,
  bu dilimin temeli. Aşağıdaki her "mevcut" alan oradan gelir.
- `backend/docs/superpowers/specs/2026-07-30-santiye-formu-genisleme-design.md` — form genişleme
  deseninin birebir kaynağı (taslak-farkındalıklı nullable kolonlar, kod üreteci, enum takas migration'ı).
- `GOREV-SIRASI.md` §3 (sabit kurallar) · §4 (kalıcı kararlar).

## P3'ün korunan kararları (bu dilim BUNLARI BOZMAZ)

1. Hiyerarşi **Proje › Şantiye › Blok › Ünite**. `blocks.site_id` zorunlu FK.
2. `units` tablosunda **`site_id` YOKTUR** — şantiye blok üzerinden türetilir.
3. **Toplu üretim pay atamaz** (`owner_side` `UnitBulkCreate`'te yoktur; `GOREV-SIRASI.md` §4.6).
4. İleri bağlar açılmaz: `sale_id`, `shareholder_id`, `contract_id`, `boq_item_id` **yok**
   (§1.3'ün istisnası aşağıda §1.3'te tek tek gerekçelendirilmiştir).
5. İzin: okuma `projects:view`, yazma `projects:full`, silme `projects:admin`. **Yeni izin modülü yok.**
6. Görünmeyen kayıt → **404**, var olmayan kimlikle ayırt edilemez.

---

## 1. Kapsam / kapsam dışı

### 1.1 Kapsam içi

1. **`blocks` genişlemesi** — BE'nin istediği 13 yeni kolon + 4 yeni enum (§3).
   P3 §4.1'de "ŞİMDİ EKLENMEZ" denen kat sayısı / teslim tarihi / blok kodu / blok durumu
   alanları **artık mockup'lıdır** ve eklenir. P3 o notu "ihtiyaç doğduğunda additive olarak
   eklenecektir" diye bırakmıştı; ihtiyaç bu mockup'larla doğdu.
2. **Blok kodu otomatik üretimi** — `blocks.code`, ad'dan kısaltılır ("A Blok" → `A`),
   proje içinde benzersiz, boş bırakılırsa üretilir (BE 71 + kullanıcı kararı 4, §3.2).
3. **`units` genişlemesi** — UE'nin istediği 8 yeni kolon + 3 yeni enum + `unit_kind` enum'unun
   3 yeni değerle genişlemesi (§4). *Kat alanı **metin**tir, enum/integer değildir — karar 4, §4.2.*
4. **Satış durumu ünitede tutulur ve elle değiştirilebilir** (`units.sales_status`) —
   kullanıcı kararı 2, **P3 §4.6 kararından bilinçli dönüş** (§4.4).
5. **Toplu üretimin yeniden tasarımı** — kat şablonu (slot) tablosu, 4 numaralandırma deseni,
   kat başına fiyat artışı ve **önizleme ucu** (§5).
6. **Excel içe aktarmanın KISMİ AKTARIMA geçişi** — geçerli satırlar yazılır, hatalı satırlar
   raporlanır; uyarı kategorisi eklenir; ayrı **doğrulama (dry-run)** ucu; **şablon indirme** ucu;
   **"Hedef Şantiye" (`site_id`) alanı** (karar 3 — çok şantiyeli projede bugün 422 veren
   yolu açar). **P3 §7.8'in hep-ya-hiç kararından bilinçli dönüş** (§6).
7. Şemalar, uçlar, Türkçe hata mesajları, denetim günlüğü, migration, test stratejisi.

### 1.2 Kapsam **DIŞI** — tek tek, gerekçeli

| Konu | Mockup | Neden dışarıda |
|---|---|---|
| **`Form - Bolum Ekle.dc.html`** — bölüm ekleme formunun tamamı | ayrı dosya | Form **bölüm ↔ İş Kalemi (BOQ) bağı** istiyor. **P6 (Bölüm Detay)** dilimine bırakıldı — `GOREV-SIRASI.md` §1'de P6 hâlâ "BOQ-bölüm bağı açılmaz" kaydıyla duruyor. **Bu dilimde ne `sections`'a ne `boq`'a tek kolon eklenir.** Kullanıcı kararı 5. **Sekmesi hiç basılmaz** (karar 12) |
| **`Form - Paylasim Girisi.dc.html`** — paylaşım girişi formunun tamamı | ayrı dosya | Form **hissedar kişileri** (→ **P9**) ve **sözleşme oranını** (→ P5, artık canlı) istiyor; ikisi de bu dilimde yok. Mevcut `PATCH …/units/allocation` ucu (P3 §7.10) **dokunulmadan kalır**. Kullanıcı kararı 5. **Sekmesi hiç basılmaz** (karar 12) |
| **Ünite belgeleri** — Kat Planı, Görseller/Render, Kat İrtifakı Tapusu | UE 103–122 | Belge saklama altyapısı repoda **hiç yok** (`GOREV-SIRASI.md` §2 "Belge çekirdeği" açık işi, §4 Kalıcı Karar 8). Alanlar `MetricPlaceholder(pending_module="documents")` ile boş kalır. Kullanıcı kararı 6 |
| **Ünite maliyeti — ELLE GİRİLMEZ** | UE 91 "Maliyet (₺)", TU 104 "Maliyet (₺)" sütunu | Kullanıcı kararı 3: maliyet ileride İş Kalemleri/satınalmadan **otomatik** hesaplanacak. `units`'e `cost` kolonu **AÇILMAZ**; alan `MetricPlaceholder(pending_module="project_costs")` kalır (P3'teki `unit_cost` yer tutucusunun aynısı). **İstisna:** Excel'deki `Maliyet` sütunu **yalnız doğrulama için okunur, saklanmaz** — §6.4 |
| **"Beklenen Kâr" kutusu** | UE 97–100 (₺500.000 · %33,8 marj) | Maliyetin türevidir; maliyet yoksa kâr da yoktur. `MetricPlaceholder(pending_module="project_costs")` |
| **"Kaydettikten sonra toplu ünite üretimine geç" kutucuğu** | BE 108–109 | Saf istemci navigasyon tercihi; sunucuya gitmez, saklanmaz (şantiye formundaki "poz dağılımı ekranına git" kutucuğuyla aynı karar) |
| **"Kaydet & Yeni Ekle"** | UE 41, 126 | İstemci akışı; sunucuda ayrı uç değildir — mevcut `POST` iki kez çağrılır |
| **"Hata Raporunu İndir"** | EI 195 | **Uç AÇILMAZ** — gerekçe §6.6 |
| Şantiye / proje seçicilerinin **listelenmesi** | BE 63/67, UE 63–65, TU 61–63, EI 60–61 | Mevcut `GET /projects`, `GET /projects/{id}/sites`, `GET /projects/{id}/blocks` uçları yeterli; yeni uç yok |

### 1.3 Kalıcı Karar 1 ("ileri bağ açılmaz") ile ilişki

Bu dilim **hiçbir FK** açmaz. `units.sales_status` bir **enum sütunudur**, bir bağ değildir —
`sales`, `buyers`, `contracts` tablolarına referans **yoktur** ve P8 geldiğinde de bu sütun
FK'ya dönüştürülmeyecektir (§4.4'teki geçiş notu). `blocks` tarafında da yeni bağ yoktur;
eklenen 13 kolonun tamamı skaler veridir.

> **P5 sonrası düzeltme (2026-07-31):** Kalıcı Karar 1 artık **mutlak değildir** —
> P5 diliminde **`boq_items.contract_item_id` onaylı sapma olarak AÇILDI** ve canlıdadır
> (`GOREV-SIRASI.md` §0.1 karar 2). Yani "ileri bağ açılmaz" kuralı bugün "ileri bağ
> **gerekçesiz** açılmaz; sapma kullanıcı onayıyla olur" biçimindedir. **Bu, P3.1'in
> kararını değiştirmez** (burada hiçbir bağa ihtiyaç doğmuyor), ama bir sonraki ajan
> "kural mutlak" sanıp `boq_items.contract_item_id`'yi ihlal olarak raporlamamalıdır.
> Bu dilim `boq_items`'a **dokunmaz**.

---

## 2. Mockup alan tablosu — dört formun HER alanı

Kolon anlamları:
**tip** = HTML girdi tipi · **zor.** = mockup'ta kırmızı `*` var mı ·
**backend** = `(var)` mevcut kolon, `(YENİ)` bu dilimde açılan, `(türev)` saklanmaz,
`(—)` sunucuya hiç gitmez, `(yer tutucu)` `MetricPlaceholder`.

### 2.1 `Form - Blok Ekle.dc.html` (BE)

| Satır | Etiket | Tip | Zor. | Backend karşılığı | Not |
|---|---|---|---|---|---|
| 35 | Breadcrumb "Satış Yönetimi / Blok Ekle" | metin | — | (—) | Frontend |
| 38, 112 | "İptal" | bağlantı | — | (—) | Frontend |
| 39, 113 | "Bloğu Kaydet" | buton | — | `POST /projects/{id}/blocks` (var) | — |
| 48–52 | Form sekmeleri (Blok/Ünite/Toplu/Excel/Paylaşım) | sekme | — | (—) | Frontend navigasyonu. **Karar 12: yalnız DÖRT sekme basılır** — "Paylaşım" (ve Bölüm) sekmesi **hiç basılmaz**, "yakında" etiketi de yoktur (onaylı sapma §11.4) |
| 56 | "Blok bir şantiyeye bağlıdır — çok şantiyeli projelerde şantiye seçimi zorunludur" | metin | — | (—) | **P3 §4.5 kuralının mockup onayı** — kural değişmez |
| 63 | Proje | select | ✔ | `blocks.project_id` (var) | Yol parametresi, gövdede taşınmaz |
| 67 | Şantiye | select | ✔ | `blocks.site_id` (var) | P3 §4.5 aynen geçerli |
| 68 | ipucu "Bu projede 2 şantiye var — seçim zorunlu" | metin | — | (—) | `_SITE_REQUIRED` mesajının UI karşılığı |
| 70 | Blok Adı | text, örnek "C Blok" | ✔ | `blocks.name` (var) | `String(50)` |
| **71** | **Blok Kodu**, mono, örnek `YV-C`, ipucu "Boş bırakılırsa otomatik" | text | — | **`blocks.code` (YENİ)** | §3.2 — **örnek `YV-C` uygulanmaz**, kullanıcı kararı 4 ile ad'dan kısaltılır (onaylı sapma §11.1) |
| **78** | **Bodrum Kat Sayısı** (2) | number | — | **`basement_floor_count` (YENİ)** | `Integer`, `ge=0` |
| **79** | **Normal Kat Sayısı** (8) | number | ✔ | **`floor_count` (YENİ)** | `Integer`, `ge=0`; **nullable** (taslak, §7.1) |
| **80** | **Çatı Katı** — Yok · Var (Dubleks) · Var (Teras) | select | — | **`roof_type` (YENİ enum)** | `none` · `duplex` · `terrace` |
| **81** | **Kat Başına Daire** (3), ipucu "Toplu üretimde kullanılır" | number | — | **`units_per_floor` (YENİ)** | `Integer`, `ge=0`. İpucu doğrudan §5'in girdi ön-doldurmasıdır |
| **82** | **Zemin Kat Kullanımı** — Dükkan / Ticari · Daire · Ortak Alan | select | — | **`ground_floor_usage` (YENİ enum)** | `commercial` · `apartment` · `common` |
| **83** | **Dükkan Sayısı** (2) | number | — | **`shop_count` (YENİ)** | `Integer`, `ge=0` |
| **84** | **Toplam İnşaat Alanı (m²)** (3200) | number | — | **`construction_area_m2` (YENİ)** | `Numeric(12,2)`; `sites.construction_area_m2` ile **aynı ad ve boy** |
| **85** | **Asansör Sayısı** (1) | number | — | **`elevator_count` (YENİ)** | `Integer`, `ge=0` |
| **86** | **Otopark** — Kapalı · Açık · Yok | select | — | **`parking_type` (YENİ enum)** | `closed` · `open` · `none` |
| 90–93 | "Tahmini Toplam Ünite **26**" · "8 kat × 3 daire + 2 dükkan" | türev sayaç | — | **(türev)** | `floor_count × units_per_floor + shop_count`. **Saklanmaz** — saklanırsa üç girdi değişince sessizce bayatlar. §3.3 |
| **100** | **Tahmini Teslim Tarihi** | date | — | **`estimated_delivery_date` (YENİ)** | `Date` |
| **101** | **Durum** — Planlama · **İnşaat Halinde** (seçili) · Tamamlandı | select | — | **`status` (YENİ enum `block_status`)** | `planning` · `construction` · `completed`; sunucu varsayılanı **`construction`** (mockup `selected`) |
| **102** | **Not** | textarea rows=2 | — | **`notes` (YENİ)** | `String(500)` |
| 108–109 | "Kaydettikten sonra toplu ünite üretimine geç" | checkbox | — | (—) | İstemci navigasyonu (§1.2) |

### 2.2 `Form - Unite Ekle.dc.html` (UE)

| Satır | Etiket | Tip | Zor. | Backend karşılığı | Not |
|---|---|---|---|---|---|
| 37 | Breadcrumb "… / Ünite Ekle" | metin | — | (—) | Frontend |
| 40, 125 | "İptal" | bağlantı | — | (—) | Frontend |
| 41, 126 | "Kaydet & Yeni" / "Kaydet & Yeni Ekle" | buton | — | (—) | İstemci akışı (§1.2) |
| 42, 127 | "Üniteyi Kaydet" | buton | — | `POST /projects/{id}/units` · `PATCH /units/{id}` (var) | Başlık "Ünite Ekle / **Düzenle**" (57) → aynı form iki uca hizmet eder |
| 63 | Proje | select | ✔ | `units.project_id` (var) | Yol parametresi |
| 64 | Şantiye | select | ✔ | (türev) | `units`'te `site_id` **YOK** (P3 §4.0) — seçici blok listesini süzer, sunucuya **gitmez** |
| 65 | Blok | select | ✔ | `units.block_id` (var) | — |
| **66** | **Kat** — Zemin · 1. Kat · **3. Kat** (seçili) · Çatı Katı | select | — | **`units.floor` (YENİ)** | **`String(20)` — METİN**, mockup etiketi aynen saklanır ("Zemin", "3. Kat", "Çatı Katı"). **Karar 4:** integer + konvansiyon **icat edilmez**; sıralama zaten `units.sort_order` üzerindendir. §4.2. Mockup'ta `*` var ama **`Create`'te zorunlu değil** (karar 11) |
| 73 | Ünite No, mono, `B-12`, ipucu "Blok-No formatı önerilir" | text | ✔ | `units.unit_no` (var) | İpucu §5.2'deki `{Blok}-{Sıra}` deseninin mockup onayı |
| **74** | **Ünite Türü** — **Daire** (seçili) · Dükkan / Ticari · Ofis · Depo · Otopark | select | ✔ | `units.unit_kind` (var) + **3 YENİ enum değeri** | Mevcut: `apartment`, `shop`. **YENİ:** `office`, `warehouse`, `parking`. §4.3 |
| 75 | Oda Tipi — 1+0 (Stüdyo) · 1+1 · 2+1 · **3+1** · 4+1 · 5+1 Dubleks | select | ✔ | `units.layout` (var) | `String(20)` serbest metin kalır — mockup listesi kapalı değil ("Dubleks" gibi türetmeler var) |
| 76 | Brüt m² (178) | number | ✔ | `units.gross_area_m2` (var) | — |
| 77 | Net m² (152) | number | ✔ | `units.net_area_m2` (var) | `ck_units_net_le_gross` aynen geçerli |
| **78** | **Cephe / Yön** — Güney · **Güney-Batı** (seçili) · Doğu · Kuzey | select | — | **`units.facing` (YENİ enum)** | §4.2 — **karar 7: mockup'taki 5 değerle kalır**, 8'e çıkarılmaz |
| **79** | **Balkon m²** (14) | number | — | **`units.balcony_area_m2` (YENİ)** | `Numeric(10,2)`, `ge=0` |
| **80** | **Banyo Sayısı** (2) | number | — | **`units.bathroom_count` (YENİ)** | `Integer`, `ge=0` |
| **81** | **Otopark Hakkı** — Yok · **1 Araç (Kapalı)** (seçili) · 2 Araç | select | — | **`units.parking_right` (YENİ enum)** | `none` · `one_closed` · `two` |
| 88 | Liste Fiyatı (₺) (1480000) | number | ✔ | `units.list_price` (var) | KY 274 / FDS 60 ile aynı sütun |
| 89 | m² Birim Fiyat (8315) **readonly**, ipucu "Brüt m² üzerinden" | number | — | **(türev)** | `UnitResponse.unit_price_per_m2` **zaten var** (P3 §6.1, FDS 61) — değişmez |
| 90 | Rayiç Değer (₺) (1420000), ipucu "Tapu harcı hesabı için" | number | — | `units.appraisal_value` (var) | KKP 89 ile aynı sütun |
| **91** | **Maliyet (₺)** (980000), ipucu "Kâr hesabı için" | number | — | **(yer tutucu)** | **ELLE GİRİLMEZ** — kullanıcı kararı 3. `MetricPlaceholder(pending_module="project_costs")`. Onaylı sapma §11.2 |
| **92** | **Min. Satış Fiyatı (₺)** (1380000), ipucu "Danışman bu fiyatın altına inemez" | number | — | **`units.min_sale_price` (YENİ)** | `Numeric(18,2)`, `ge=0`. Kullanıcı kararı 3'teki "taban fiyat" budur. **Karar 2: `min_sale_price ≤ list_price` ZORLANMAZ** — ne DB'de ne serviste ne şemada (§4.1) |
| **93** | **KDV Oranı** — %1 (150m² altı) · **%10** (seçili) · %20 (Ticari) | select | — | **`units.vat_rate` (YENİ)** | `Numeric(5,2)`; `company.default_vat_rate` ile **aynı tip**. **Karar 9: yalnız `{1, 10, 20}`** — liste kodda sabit (§4.2) |
| **94** | **Durum** — **Satışta (Boş)** (seçili) · Rezerve · Satıldı · Satışa Kapalı | select | ✔ | **`units.sales_status` (YENİ enum)** | **Kullanıcı kararı 2** — P3 §4.6'dan dönüş. §4.4. `Create`'te varsayılan `listed` (karar 11) |
| 95 | Sahiplik — **Yüklenici (Biz)** (seçili) · Arsa Sahibi Payı, ipucu "Kat karşılığı projelerde" | select | — | `units.owner_side` (var) | `contractor` / `landowner`. **İpucu, P3 §3.3 korkuluğunun mockup onayıdır** — kural değişmez |
| 97–99 | "Beklenen Kâr ₺500.000 · %33,8 marj" · "Liste fiyatı − maliyet" | türev | — | **(yer tutucu)** | Maliyet yoksa kâr da yok (§1.2) |
| 103–121 | Ünite Belgeleri (3 yükleme kutusu) | file | — | **(yer tutucu)** | `pending_module="documents"` (§1.2) |

### 2.3 `Form - Toplu Unite.dc.html` (TU)

| Satır | Etiket | Tip | Zor. | Backend karşılığı | Not |
|---|---|---|---|---|---|
| 36 | Breadcrumb "… / Toplu Ünite Üretimi" | metin | — | (—) | Frontend |
| 40, 183 | "**24 Üniteyi Oluştur**" (sayı dinamik) | buton | — | `POST …/units/bulk` (var, **değişiyor**) | Sayı `preview.total_units`'ten gelir |
| 56 | "Kat aralığı ve numaralandırma deseni girin — sistem tüm üniteleri otomatik oluşturur" | metin | — | (—) | — |
| 61 | Proje | select | ✔ | yol parametresi (var) | — |
| 62 | Şantiye | select | ✔ | (—) | Blok listesini süzer, gövdede taşınmaz |
| 63 | Blok — "**C Blok (8 kat · 3 daire/kat)**" | select | ✔ | `UnitBulkCreate.block_id` (var) | Parantez içi `blocks.floor_count` + `units_per_floor` (§2.1, BE 79/81) — **seçici etiketinin veri kaynağı budur** |
| 70 | Başlangıç Katı — Zemin · **1. Kat** · 2. Kat | select | ✔ | `start_floor` (var, **Integer kalır**) | Toplu üretimin **girdisi** sayısaldır (P3, `ge=-5 le=100`); üretilen üniteye **etiket** yazılır (§4.2, §5.5) |
| 71 | Bitiş Katı — **8. Kat** · Çatı Katı | select | ✔ | `end_floor` (var, **Integer kalır**) | **Çatı katı artık sorun değil** (karar 4): `roof_floor: bool` bayrağıyla son bir tur daha üretilir ve o turun etiketi `"Çatı Katı"` olur — §5.3 |
| 72 | Kat Başına Daire (3) | number | ✔ | `units_per_floor` (var) | `blocks.units_per_floor`'dan ön-doldurulur |
| 73 | "Toplam Üretilecek — **24 ünite**" readonly | text | — | **(türev)** | `(end−start+1) × units_per_floor`; `UnitBulkPreview.total_units` (§5.4) |
| **79** | **Numaralandırma Deseni** — `{Blok}-{Sıra}` → C-1… · `{Kat}{Sıra}` → 11, 12, 21… · `Daire {Sıra}` · `{Blok}{Kat}{Sıra}` → C11… | select | ✔ | **`numbering` (var enum, DEĞİŞİYOR: 2 → 4 değer)** | §5.2. `{Blok}` **blok kodudur** (kullanıcı kararı 4). **Karar 1: başa sıfır KONMAZ** — `C-4`, `11`, `12`, `21`; P3'ün iki haneli dolgusu kaldırılıyor (onaylı sapma §11.5) |
| 80 | ipucu "Süslü parantez içindekiler otomatik doldurulur" | metin | — | (—) | — |
| 84 | Başlangıç Numarası (1), ipucu "Mevcut ünitelerle çakışmaması için" | number | — | `start_number` (var) | — |
| **93–94** | **"Kat Şablonu" · "Her katta aynı düzen tekrarlanır"** | başlık | — | **`slots: list[UnitBulkSlot]` (YENİ)** | §5.3 — **mevcut ucun tek ortak varsayılan kümesi yerine kat-içi slot listesi** |
| **98** | slot **Sıra** (1, 2, 3) | metin | — | `UnitBulkSlot.sequence` (YENİ) | Salt sıra; `unit_no`'nun `{Sıra}` jetonunu **beslemez** (§5.2) |
| **99/109/118/127** | slot **Oda Tipi** (3+1 / 2+1 / 3+1) | select | — | `UnitBulkSlot.layout` (YENİ) | — |
| **100/110/119/128** | slot **Brüt m²** (148 / 112 / 148) | number | — | `UnitBulkSlot.gross_area_m2` (YENİ) | — |
| **101/111/120/129** | slot **Net m²** (128 / 96 / 128) | number | — | `UnitBulkSlot.net_area_m2` (YENİ) | — |
| **102/112/121/130** | slot **Cephe** (Güney / Doğu / Batı) | select | — | `UnitBulkSlot.facing` (YENİ) | **Cephe SLOT'a bağlıdır, kata değil** — önizleme bunu doğruluyor (§5.5) |
| **103/113/122/131** | slot **Liste Fiyatı (₺)** (1.280.000 / 940.000 / 1.240.000) | number | — | `UnitBulkSlot.list_price` (YENİ) | Kat artışının **tabanı** budur (§5.5) |
| **104/114/123/132** | slot **Maliyet (₺)** (860.000 / 620.000 / 860.000) | number | — | **(—)** | **Sunucuya GİTMEZ** — kullanıcı kararı 3 + karar 10, §1.2. Onaylı sapma §11.2 |
| **137** | "**Üst katlarda fiyat artışı uygula**" (işaretli) | checkbox | — | `floor_price_increase_pct is not None` (YENİ) | Ayrı boolean açılmaz: yüzde `None` ise artış yok |
| **138** | "Kat başına **1.5** % artış" | number step .1 | — | **`floor_price_increase_pct` (YENİ)** | `Numeric(5,2)`. Formül §5.5; **karar 6: en yakın 100 ₺'ye yuvarlanır** |
| **145–146** | "👁 **Üretim Önizlemesi**" · "24 ünite oluşturulacak · Toplam değer ₺27.264.000" | başlık | — | **`POST …/units/bulk/preview` (YENİ UÇ)** | §5.4. **Karar 5: mockup'ın ₺27.264.000 sayısı MOCKUP HATASIDIR**; toplam satırlardan hesaplanır (onaylı sapma §11.6) |
| **151–156** | önizleme sütunları: Ünite No · Kat · Tip · Brüt/Net m² · Cephe · Liste Fiyatı | tablo | — | `UnitBulkPreviewRow` (YENİ) | §5.4. Kat sütunu **iki alanla** döner: `floor: int` (üretim girdisi, mockup 152'de "1/2/3" böyle basılıyor) + `floor_label: str` (üniteye yazılan metin, karar 4) |
| 159–165 | önizleme satırları C-1…C-7 | veri | — | (türev) | Formül doğrulaması §5.5 |
| 166 | "… 17 ünite daha (C-8 → C-24)" | metin | — | (—) | Frontend kırpması; **sunucu tüm satırları döner** (§5.4 gerekçesi) |
| 171–172 | "24 Ünite · Toplam Liste Değeri **₺27.264.000**" | toplam | — | `UnitBulkPreview.total_list_value` (YENİ) | **Karar 5:** satırlardan hesaplanır; mockup'ın sayısı **kanon değildir** (§5.5) |
| 177 | "⚠ Oluşturulan üniteler daha sonra tek tek düzenlenebilir. **Mevcut ünite numaraları ile çakışma varsa uyarı verilir**" | metin | — | `UnitBulkPreviewRow.conflict` + `conflicting_unit_nos` (YENİ) | Mockup "uyarı" diyor, "hata" demiyor → önizlemede **uyarı**, gerçek üretimde **409** (§5.6) |
| **182** | "**Önizlemeyi Yenile**" | buton | — | `POST …/units/bulk/preview` (YENİ UÇ) | §5.4 |

### 2.4 `Form - Unite Excel Import.dc.html` (EI)

| Satır | Etiket | Tip | Zor. | Backend karşılığı | Not |
|---|---|---|---|---|---|
| 34 | Breadcrumb "… / Excel İçe Aktarma" | metin | — | (—) | Frontend |
| **37, 87** | "**Şablon İndir**" (iki kez) | buton | — | **`GET …/units/import/template` (YENİ UÇ)** | §6.7 |
| **38, 202** | "**22 Geçerli Satırı Aktar**" (sayı dinamik) | buton | — | `POST …/units/import` (var, **davranışı DEĞİŞİYOR**) | **Kısmi aktarım** — §6.1 |
| 54 | "Şablonu indirip doldurun, sonra yükleyin — sistem **satır satır doğrular**" | metin | — | (—) | Kısmi aktarım kararının mockup dayanağı |
| 60 | Hedef Proje | select | ✔ | yol parametresi (var) | — |
| 61 | Hedef Şantiye | select | ✔ | **`site_id: UUID \| None` (YENİ, gövdede)** | **Karar 3: EKLENİR.** Dosyada şantiye sütunu yok; içe aktarımda **açılacak yeni blokların `site_id`'si** bu değerden gelir. Bugün çok şantiyeli projede içe aktarma P3 §4.5 gereği **422 veriyor** ve uç kullanılamaz hâlde — bu alan o yolu açar. §6.4 |
| 65–73 | Yüklenmiş dosya kartı: ad · "248 KB · **24 satır okundu** · Yükleme tamamlandı ✓" · Değiştir · × | bilgi | — | `UnitImportSummary.total_rows` (YENİ) | Boyut istemcide bilinir |
| 75–80 | Sürükle-bırak alanı · "XLSX, XLS veya CSV · **Maks 10 MB**" | file | — | (—) + **sınır çelişkisi** | **`.xls`/`.csv` REDDEDİLİR** (P3 §7.8, `openpyxl` yalnız `.xlsx` okur) ve sınır **2 MB**'tır. Onaylı sapma §11.3 |
| **85** | "**Beklenen kolonlar:** Blok, Kat, Ünite No, Tür, Oda Tipi, Brüt m², Net m², Cephe, Liste Fiyatı, Rayiç Değer, Maliyet, Sahiplik" | metin | — | **`importer.COLUMNS` DEĞİŞİYOR** | 9 → 12 sütun; 2 başlık **yeniden adlandırılıyor**. §6.4 |
| **95–98** | 4 sayaç: **Toplam Satır 24** · **Geçerli 22** · **Uyarı 1** · **Hata 1** | sayaç | — | **`UnitImportSummary` (YENİ)** | §6.3 |
| 101 | "**1 satır aktarılamayacak.** Hatalı satırları düzeltip tekrar yükleyin **veya sadece geçerli satırları aktarın**" | metin | — | (—) | **Kısmi aktarım kararının en açık mockup kanıtı** |
| **110–112** | Süzgeç düğmeleri: Tümü (24) · Hatalı (1) · Uyarılı (1) | sekme | — | (—) | İstemci süzgeci; sunucu **tüm satırları** döner |
| **118–126** | Satır raporu sütunları: Satır · Durum · Ünite No · Blok · Kat · Tip · Brüt m² · Liste Fiyatı · **Mesaj** | tablo | — | **`UnitImportRowReport` (YENİ)** | §6.3 |
| 131/142/177 | durum simgesi ✓ (yeşil) | enum | — | `status = ok` | Mesaj sütunu "Hazır" (138) |
| **154, 161** | durum ✗ · mesaj "**Oda Tipi boş · Brüt m² sıfır olamaz**" | enum + metin | — | `status = error`, `messages: list[str]` | **Bir satırda BİRDEN ÇOK mesaj** → `messages` liste olmalı (§6.3). Ayrıca **iki yeni kural**: `Oda Tipi` zorunlu, `Brüt m² > 0` (§6.5) |
| **166, 173** | durum ⚠ · mesaj "**Fiyat maliyetin altında (₺860K) — kontrol edin**" | enum + metin | — | `status = warning` | **Tek uyarı kuralı**; **karar 10:** `Maliyet` sütunu **okunur → uyarı üretir → atılır**; maliyet kolonu açılmaz (§6.4/§6.5) |
| **192–193** | "**Uyarılı satırları da aktar (1 satır)**" (işaretli) | checkbox | — | **`include_warnings: bool = True` (YENİ)** | §6.2 |
| **195** | "**Hata Raporunu İndir**" | buton | — | **(—) — uç açılmaz** | §6.6 |
| **201** | "**Yeniden Doğrula**" | buton | — | **`POST …/units/import/validate` (YENİ UÇ)** | §6.2 |

---

## 3. `blocks` genişlemesi

### 3.1 Yeni kolonlar

**Hiçbiri `NOT NULL` yapılmaz** — gerekçe canlı veri değil, **taslak desteğidir**
(`GOREV-SIRASI.md` §4 Kalıcı Karar 4: "zorunluluk yalnız taslak-dışı kayıtta"). BE 79
kırmızı `*` taşır ama bu **form zorunluluğudur**, sütun zorunluluğu değil; şantiye formunda
aynı ayrım yapıldı (`sites.city`, `start_date` vb. `*` işaretli ama nullable).

| Sütun | Tip | Null | Varsayılan | Kısıt | Mockup |
|---|---|---|---|---|---|
| `code` | `String(20)` | ✓ | — | `uq_blocks_project_code (project_id, code)` | BE 71 |
| `basement_floor_count` | `Integer` | ✓ | — | `ck_blocks_basement_floor_count >= 0` | BE 78 |
| `floor_count` | `Integer` | ✓ | — | `ck_blocks_floor_count >= 0` | BE 79 |
| `roof_type` | `Enum(block_roof_type)` | ✓ | — | `none · duplex · terrace` | BE 80 |
| `units_per_floor` | `Integer` | ✓ | — | `ck_blocks_units_per_floor >= 0` | BE 81 |
| `ground_floor_usage` | `Enum(block_ground_usage)` | ✓ | — | `commercial · apartment · common` | BE 82 |
| `shop_count` | `Integer` | ✓ | — | `ck_blocks_shop_count >= 0` | BE 83 |
| `construction_area_m2` | `Numeric(12,2)` | ✓ | — | `ck_blocks_construction_area >= 0` | BE 84 |
| `elevator_count` | `Integer` | ✓ | — | `ck_blocks_elevator_count >= 0` | BE 85 |
| `parking_type` | `Enum(block_parking_type)` | ✓ | — | `closed · open · none` | BE 86 |
| `estimated_delivery_date` | `Date` | ✓ | — | — | BE 100 |
| `status` | `Enum(block_status)` | ✓ | `'construction'` (server_default) | `planning · construction · completed` | BE 101 |
| `notes` | `String(500)` | ✓ | — | — | BE 102 |

**13 yeni kolon · 4 yeni enum tipi** (`block_roof_type`, `block_ground_usage`,
`block_parking_type`, `block_status`).

`status` neden `NOT NULL DEFAULT 'construction'` değil: mevcut canlı bloklar için de bir
değer üretmek gerekirdi ve "İnşaat Halinde" varsayımı yanlış olabilir. Sunucu **varsayılanı**
`construction`'dır (mockup 101 `selected`), fakat sütun nullable kalır ve `server_default`
yalnız yeni satırlar için geçerlidir. **Karar 8 bu tercihi pekiştirir:** canlı satırlara
dokunan hiçbir veri migration'ı yazılmaz.

`notes` neden `String(500)` ve `Text` değil: `sites`/`projects` desenlerinde serbest metin
alanları sınırlı `String`'tir; sınırsız `Text` frontend'de `maxLength` konamamasına ve
**sessiz 422 sınıfına** yol açar (`GOREV-SIRASI.md` §3 frontend kuralı).

### 3.2 Blok kodu üretimi — `blocks.code`

**Kullanıcı kararı 4 (kesin):** blok kodu **ad'dan kısaltılır** — `"A Blok"` → `A`,
`"Yeşilvadi C"` → `YESILVADI-C`. Proje içinde benzersizdir. Boş bırakılırsa otomatik üretilir.

**`PRJ-{YYYY}-{NNN}` / `SNT-{YYYY}-{NNN}` deseni KULLANILMAZ.** Gerekçe (kullanıcı kararı 4):
TU 79 ve TU 159–165 ünite numaralarını **blok koduna** bağlıyor — `C-1`, `C-4`, `B-1`.
`SNT-2026-003` biçiminde bir kod ünite numarasını `SNT-2026-003-1` yapardı; mockup'ın
gösterdiği kısa kod bunun tam tersidir.

Üretim algoritması (`_derive_block_code`, saf fonksiyon, DB'siz test edilir):

1. Ad Türkçe karakterlerden arındırılır (`Ç→C`, `Ğ→G`, `İ/I/ı→I`, `Ö→O`, `Ş→S`, `Ü→U`) ve
   büyük harfe çevrilir.
2. `BLOK` / `BLOCK` kelimesi ve noktalama atılır; kalan sözcükler `-` ile birleştirilir.
   `"A Blok"` → `A` · `"C Blok"` → `C` · `"Zemin"` → `ZEMIN` · `"2. Etap A"` → `2-ETAP-A`
3. Sonuç 20 karaktere kırpılır (`String(20)`).
4. Boş kalırsa (ad tamamen "Blok" ise) sıralı geri düşüş: `B1`, `B2`, … (proje içi maksimum+1).
5. Proje içinde çakışırsa `-2`, `-3` … eki verilir (`sites`'in `_next_site_code`
   maksimum+1 mantığının kısa-kod karşılığı).

Kullanıcı elle kod girerse **aynen kabul edilir** (BE 71'de alan serbest yazılabilir);
yalnız benzersizlik doğrulanır → çakışma **409** `_DUPLICATE_BLOCK_CODE`.

**`uq_blocks_project_code` nullable sütun üzerindedir:** PostgreSQL'de birden çok `NULL`
serbesttir, dolayısıyla kodu olmayan eski bloklar kısıtı ihlal etmez.

**Karar 8 — canlı blokların kodu için migration YAZILMAZ.**
Mevcut (canlı) blokların `code` sütunu **`NULL` doğar ve `NULL` kalır**; bir sonraki
`PATCH /blocks/{id}` sırasında **kod boşsa üretilir** (yeni blok yaratmadaki mantığın aynısı).
Yani üretim tek yerdedir: `code` yazma yolunda boşsa `_derive_block_code` çalışır — ne
`UPDATE blocks SET code = …` içeren bir veri migration'ı vardır, ne de okuma yolunda gizli
bir geri düşüş.

> **Kalan sonuç (§13.2'nin tek açık maddesi):** `code`'u `NULL` olan bir blokta
> `block_sequence` / `block_floor_sequence` desenlerinin `{Blok}` jetonu **neye çözülecek?**
> Bu spec'in önerisi: **üretim anında `_derive_block_code(block.name)` çağrılır, sonuç
> saklanmaz.** İkinci otorite doğmaz çünkü çağrılan fonksiyon **aynı saf fonksiyondur**;
> blok bir kez düzenlenip kodu kalıcılaştığında çıktı **birebir aynıdır** (kullanıcı kodu
> elle değiştirmediyse). Alternatif — `422 "Önce blok kodunu belirleyin"` — kullanıcıyı
> canlı blokta toplu üretimden kilitler.

### 3.3 Saklanmayan türev — "Tahmini Toplam Ünite"

BE 90–93: `26` = `8 kat × 3 daire + 2 dükkan`. Yani

```
estimated_unit_count = (floor_count or 0) * (units_per_floor or 0) + (shop_count or 0)
```

`BlockResponse.estimated_unit_count: int | None` olarak **hesaplanır**, saklanmaz. Üç girdi
de `None` ise `None` döner (0 dönmek "hesaplandı ve sıfır" der; bu yanlış bilgidir).
Bu sayacın `counts` (gerçek ünite adedi, P3) ile **karıştırılmaması** kritiktir: biri plan,
diğeri gerçektir ve ikisi bilerek ayrı alanlardır.

---

## 4. `units` genişlemesi

### 4.1 Yeni kolonlar

| Sütun | Tip | Null | Varsayılan | Kısıt | Mockup |
|---|---|---|---|---|---|
| `floor` | **`String(20)`** | ✓ | — | — (metin, CHECK yok) | UE 66, TU 152, EI 122 |
| `facing` | `Enum(unit_facing)` | ✓ | — | §4.2 | UE 78, TU 102 |
| `balcony_area_m2` | `Numeric(10,2)` | ✓ | — | `ck_units_balcony_area >= 0` | UE 79 |
| `bathroom_count` | `Integer` | ✓ | — | `ck_units_bathroom_count >= 0` | UE 80 |
| `parking_right` | `Enum(unit_parking_right)` | ✓ | — | `none · one_closed · two` | UE 81 |
| `min_sale_price` | `Numeric(18,2)` | ✓ | — | `ck_units_min_sale_price >= 0` | UE 92 |
| `vat_rate` | `Numeric(5,2)` | ✓ | — | `ck_units_vat_rate BETWEEN 0 AND 100` | UE 93 |
| `sales_status` | `Enum(unit_sales_status)` | ✓ | `'listed'` (server_default) | `listed · reserved · sold · closed` | UE 94 |

**8 yeni kolon · 3 yeni enum tipi** (`unit_facing`, `unit_parking_right`, `unit_sales_status`)
**+ `unit_kind` enum'unun 3 yeni değerle takası** (§4.3). **`units` tarafında `CHECK` sayısı
5 → 4'e düşer** — `ck_units_floor` **yoktur** (kat artık metindir).

**`floor` neden `String(20)` (karar 4):** mockup her yerde bir **etiket** gösteriyor
("Zemin", "1. Kat", "Çatı Katı"). Bir integer sütun, bu etiketleri sayıya çeviren bir
**konvansiyon icat etmeyi** zorunlu kılardı (çatı katı = `floor_count + 1`? bodrum = negatif?)
ve `GOREV-SIRASI.md` §3'ün icat yasağına takılırdı. Sıralama ihtiyacı **zaten karşılanmıştır**:
`units.sort_order` (Integer, `NOT NULL default 0`) P3'ten beri var ve üretim sırasını taşır.
Sonuç: kat **gösterim verisidir**, sıralama anahtarı değildir.

`min_sale_price ≤ list_price` **hiçbir katmanda ZORLANMAZ** (karar 2, kesin): ne DB CHECK,
ne servis doğrulaması, ne Pydantic `model_validator`. Taban fiyat **serbest girilir**.
Gerekçe: mockup böyle bir kural söylemiyor (UE 92 ipucu yalnız danışmanı bağlar), ikisi de
nullable olduğu için CHECK kısmi doldurulmuş taslak satırları bloklardı ve icat edilmiş
kısıt yasağı vardır (`GOREV-SIRASI.md` §3). Onaylı sapma §11.7.

### 4.2 Enum değer kümeleri ve kat etiketi

**`unit_facing`** — **karar 7:** mockup'ta geçen **tam olarak 5 değer**, fazlası icat edilmez
ve **8'e çıkarılmaz**:

| Değer | Etiket | Mockup |
|---|---|---|
| `south` | Güney | UE 78, TU 112 |
| `southwest` | Güney-Batı | UE 78 |
| `east` | Doğu | UE 78, TU 112/121 |
| `north` | Kuzey | UE 78, TU 112 |
| `west` | Batı | TU 112/130 |

Pusulanın kalan 3 yönü (`northeast`, `northwest`, `southeast`) **eklenmez** — hiçbir mockup'ta
yok. İhtiyaç doğarsa additive olarak eklenir (enum takas migration'ı, §4.3 deseni).

**`vat_rate`** değer kümesi — **karar 9: yalnız `{1, 10, 20}`.** UE 93 üç seçenek gösteriyor
(`%1`, `%10`, `%20`) ve `GOREV-SIRASI.md` §4 Kalıcı Karar 9 zaten "KDV listesi (20/10/1)
**kodda sabit**" diyor. Sütun `Numeric(5,2)` serbest kalır (mevcut `company.default_vat_rate`
ile aynı tip, DB CHECK yalnız `0..100`), **kümeyi Pydantic şeması zorlar** → küme dışı değer
**422** `_INVALID_VAT_RATE`. Tip serbest, kapı dar: KDV oranı yasayla değişen bir listedir ve
gün gelip `%8` eklenirse migration değil, tek satır kod değişikliği gerekir.

**Kat etiketi (`units.floor`) — karar 4: METİN olarak saklanır.**

UE 66 ve TU 70/71 dört tür etiket gösteriyor: **Zemin** · **`N. Kat`** · **Çatı Katı**
(+ BE 78 bodrum kat sayısı). Bunların hiçbiri sayı değildir; mockup **etiket** gösterir.

| Etiket | `units.floor` (String(20)) | Mockup |
|---|---|---|
| Zemin | `"Zemin"` | UE 66, TU 70 |
| `N. Kat` | `"1. Kat"`, `"3. Kat"` … | UE 66, TU 70/71, EI 122 |
| Çatı Katı | `"Çatı Katı"` | UE 66, TU 71 |
| Bodrum | `"1. Bodrum"` … (blok bodrumluysa) | BE 78 |

**Neden integer + konvansiyon YOK:**
1. Çatı katı bir tam sayıya sığmıyordu; `floor_count + 1` sözleşmesi "en üst normal kat"
   ile "çatı katı"nı **karıştırır** ve `roof_type = none` blokta anlamsız kat üretir.
2. Bir sözleşme icat etmek `GOREV-SIRASI.md` §3 "göz kararı icat yasağı"na girer.
3. Sıralama gerekçesi **çürük**: `units.sort_order` P3'ten beri var ve üretim sırasını taşır.

**Sonuç — bu kararın bağlayıcı yan etkileri (uygulamada aranacak):**
- `ck_units_floor` CHECK'i **yoktur** (§4.1).
- `GET …/units` süzgeci `floor: str | None` — **tam eşleşme** (§8.2).
- Toplu üretimde `start_floor` / `end_floor` **Integer kalır** (TU 70/71 girdi tarafı);
  üretilen üniteye **etiket** yazılır. Etiket üreteci mockup'ın kendi sözlüğüdür:
  `0 → "Zemin"`, `n > 0 → "{n}. Kat"`, `n < 0 → "{|n|}. Bodrum"`, çatı turu → `"Çatı Katı"` (§5.3).
- Excel `Kat` sütunu **serbest metindir**: hücre ne yazıyorsa (`"Zemin"`, `"3. Kat"`, `3`)
  kırpılıp aynen yazılır; sayı yazılmışsa `"{n}. Kat"` değil, **`"3"`** olarak kalır —
  kullanıcının dosyasındaki gösterimi değiştirmek sessiz veri dönüşümü olurdu. Tek doğrulama
  `max_length=20` (§6.5).

### 4.3 `unit_kind` enum genişlemesi

UE 74: **Daire · Dükkan / Ticari · Ofis · Depo · Otopark.** Mevcut enum iki değerlidir
(`apartment`, `shop`). Üç değer eklenir: `office`, `warehouse`, `parking`.

Bu **`UnitKindBreakdown` şemasını da genişletir** (P3 §6.1): bugün `apartment` + `shop`
alanları ve türev `total` var. Yeni biçim:

```python
class UnitKindBreakdown(BaseModel):
    apartment: int = 0      # KY 71 "48 Daire"
    shop: int = 0           # KY 71 "4 Dukkan"
    office: int = 0         # UE 74 (YENI)
    warehouse: int = 0      # UE 74 (YENI)
    parking: int = 0        # UE 74 (YENI)

    @computed_field
    def total(self) -> int: ...     # BES sayacin toplami
```

**Karar 13 — ekran etiketleri DEĞİŞMEZ:** KY 71 / KK 72 / SY 74 hâlâ "Daire + Dükkan" der;
yeni üç sayaç yalnız **sayaçlara** eklenir, mevcut etiketler korunur. Sayaç sıfırsa ekranda
**hiç görünmez**. Bu, frontend dilimi için **bağlayıcı** nottur — mevcut ekran metinlerini
"eksik" sanıp genişletmek bu kararın ihlalidir.

**Migration tuzağı:** `ALTER TYPE … ADD VALUE` aynı işlem içinde kullanılamaz ve **geri
alınamaz**. `f1b2c3d4e5a6_site_status_preparation.py` deseni birebir uygulanır: yeni tip
oluştur → sütunu `USING …::text::…` ile çevir → eski tipi düşür → yeniden adlandır.
**Enum takası KENDİ İZOLE REVİZYONUNDA** yapılır (`d1a2b3c4e5f6` dersi, §7.2).

### 4.4 Satış durumu — P3 §4.6 kararından **dönüş**

**Kullanıcı kararı 2 (kesin): `units.sales_status` sütunu AÇILIR ve ELLE değiştirilebilir.**

| | P3 §4.6 (eski) | P3.1 (yeni) |
|---|---|---|
| Saklama | `units`'te sütun **yok** | `units.sales_status` enum sütunu |
| Yanıt | `MetricPlaceholder(pending_module="unit_sales")` | gerçek değer |
| Gerekçe | "P8 geldiğinde iki otorite oluşur, senkron kayması sessiz veri hatası olur" | Ekran bugün bu alanı **zorunlu** istiyor (UE 94 kırmızı `*`) ve P8 belirsiz bir gelecekte |

Değerler (UE 94, birebir):

| Enum | Etiket |
|---|---|
| `listed` | Satışta (Boş) |
| `reserved` | Rezerve |
| `sold` | Satıldı |
| `closed` | Satışa Kapalı |

Sunucu varsayılanı `listed` (mockup `selected`).

**KKP 92 sözlüğüyle ilişki:** KKP dört değer gösteriyor — Satıldı / Satışta / Rezerve /
**Arsa Sahibinde**. "Arsa Sahibinde" **sütuna girmez**: o `owner_side='landowner'`
türevidir ve P3'te zaten `is_landowner_share` olarak dönüyor. Ekran ikisini birleştirerek
basar. KY 276'nın "Tapulu" değeri de sütuna girmez — tapu devri **P8'in** kaydıdır ve bu
dilimde karşılığı yoktur (KY 276 alanı `sold` ile eşlenir).

> **GELECEK İŞ — P8 (ünite satışı) geldiğinde:**
> `sales_status` **otomatik yönetilmeye** başlayacak (satış kaydı açıldığında `reserved`,
> tapu devrinde `sold` vb.) ve **elle giriş kilitlenecektir**: `UnitCreate`/`UnitUpdate`
> şemalarından alan çıkarılacak ya da salt-okunur hâle gelecek. Bugün elle girilmesi
> **geçici bir çözümdür**, kalıcı tasarım değildir. P8 spec'i bu paragrafı kaynak alarak
> geçişi (mevcut elle girilmiş değerlerin ne olacağını) tanımlamak zorundadır.
> Bu not `units/models.py` docstring'ine de **birebir** yazılır — bir sonraki ajan
> sütunu "P3'ün ihlali" sanıp silmemelidir.

### 4.5 Maliyet — kolon AÇILMAZ

**Kullanıcı kararı 3 (kesin):** maliyet elle girilmez; ileride İş Kalemleri/satınalmadan
otomatik hesaplanacaktır. Dolayısıyla:

- UE 91 "Maliyet (₺)" → `MetricPlaceholder(pending_module="project_costs")` (P3'teki
  `unit_cost` alanı **zaten bu**, değişmiyor).
- UE 97–99 "Beklenen Kâr / marj" → `MetricPlaceholder(pending_module="project_costs")` (YENİ alan
  `expected_profit`).
- TU 104 "Maliyet" slot sütunu → **gövdede taşınmaz** (§5.3).
- EI 85 `Maliyet` Excel sütunu → **okunur ama saklanmaz**, yalnız uyarı kuralını besler (§6.4).

Satış fiyatı tarafı **elle girilir**: `list_price` (var) + `min_sale_price` (YENİ, UE 92).

---

## 5. Toplu üretim (`Form - Toplu Unite`)

### 5.1 Mevcut ucun neden yetmediği

Bugünkü `UnitBulkCreate` (P3 §6.3) **tek bir ortak varsayılan kümesi** taşır: tüm üretilen
üniteler aynı `layout`, aynı `gross_area_m2`, aynı `list_price` değerini alır. TU 96–133
ise **kat içinde slot başına farklı** oda tipi, m², cephe ve fiyat gösteriyor
(3+1/148/Güney/1.280.000 · 2+1/112/Doğu/940.000 · 3+1/148/Batı/1.240.000). Mevcut uç bu
formu **hiç** karşılayamaz. Ayrıca mockup bir **önizleme** ve **kat başına fiyat artışı**
istiyor; ikisi de yok.

### 5.2 Numaralandırma desenleri — 2 → 4

TU 79 dört desen listeliyor. `{Blok}` jetonu **blok kodudur** (kullanıcı kararı 4, §3.2).

| Yeni enum değeri | Mockup deseni | Örnek | Formül |
|---|---|---|---|
| `block_sequence` | `{Blok}-{Sıra}` | `C-1, C-2, C-3…` | `{code}-{start_number + i}` |
| `floor_sequence` | `{Kat}{Sıra}` | `11, 12, 13, 21, 22…` | `{floor}{slot}` |
| `label_sequence` | `Daire {Sıra}` | `Daire 1, Daire 2…` | `Daire {start_number + i}` |
| `block_floor_sequence` | `{Blok}{Kat}{Sıra}` | `C11, C12, C13…` | `{code}{floor}{slot}` |

`{Kat}` jetonu **numaralandırmaya özgü sayıdır** — üretim turunun tam sayı katıdır
(`start_floor…end_floor`), üniteye yazılan **metin etiket değildir** (§4.2). Çatı turu
kullanılırsa `{Kat}` = `end_floor + 1`; bu **yalnız numaralandırma içinde** yaşayan bir
sayıdır, hiçbir sütuna yazılmaz.

`{Sıra}` iki farklı anlamda kullanılıyor ve **karıştırılmamalıdır**:
- `block_sequence` / `label_sequence`'ta **üretim boyunca artan global sıra**
  (TU 159–165: C-1…C-7 kat değişse de artıyor).
- `floor_sequence` / `block_floor_sequence`'ta **kat içi slot sırası** (11, 12, 13 → sonra 21).

**Slot genişliği — KARAR 1: başa sıfır KONMAZ, P3'ten dönülür.**

Bugün `app/modules/units/bulk.py`'de `_FLOOR_SEQUENCE_WIDTH = 2` **sabittir** ve
`f"{floor}{sequence:0{_FLOOR_SEQUENCE_WIDTH}d}"` üretiyor (`101, 102, 201`). Mockup ise
TU 79'da **tek hane** gösteriyor (`11, 12, 13, 21`) ve TU 159–165'te `C-1 … C-7`
(`C-01` değil). **Mockup kazanır** (`GOREV-SIRASI.md` §3).

**Kural:** `W = len(str(units_per_floor))` — dolgu **slot sayısı kadar**, sabit 2 değil.
- `units_per_floor ≤ 9` → `W = 1` → `11, 12, 13, 21` (**mockup'a birebir**)
- `units_per_floor = 10..20` → `W = 2` → `101 … 110, 201` (çakışma korunur: tek hane olsaydı
  kat 1 slot 11 ile kat 11 slot 1 aynı numarayı alırdı)

**Kırılacak P3 testleri — bilerek güncellenir** (§12.7, T8):
| Test (`tests/modules/units/test_units_bulk.py`) | Bugün | Karar 1'den sonra |
|---|---|---|
| `test_floor_based_numbering` (`units_per_floor=2`) | `101,102,201,202` | **`11,12,21,22`** |
| `test_floor_based_numbering_negative_floors` (`units_per_floor=2`) | `-101,-102` | **`-11,-12`** |
| `test_floor_based_numbering_pads_to_two_digits` (`units_per_floor=10`) | `101 … 110` | **yeşil kalır** (W=2), ama adı/docstring'i yanıltıcı → `test_floor_sequence_width_follows_units_per_floor` olarak **yeniden adlandırılır** |

`bulk.py:14-17`'deki `_FLOOR_SEQUENCE_WIDTH` sabiti ve yorumu ("1. kat 1. daire *101*dir,
*11* değil") **kaldırılır** — yorum artık kararın tersini söylüyor ve bırakılırsa bir sonraki
ajan kodu "regresyon" sanıp geri alır.

**`prefix` alanı KORUNUR.** P3'te serbest `prefix` vardı ve `SY 132–135`'in `D1…D4` dükkan
numaralandırmasının tek yoludur. Dört desen onun yerine geçmez; `prefix` desen çıktısının
**önüne** eklenir ve varsayılanı `""` olduğu için mevcut davranış bozulmaz.

### 5.3 Kat şablonu (slot) şeması

```python
class UnitBulkSlot(BaseModel):
    """TU 107-133 'Kat Sablonu' tablosunun BIR satiri. Her katta tekrarlanir (TU 94)."""
    sequence: int = Field(ge=1, le=20)          # TU 98 "Sira"
    layout: str | None = Field(default=None, max_length=20)          # TU 99
    gross_area_m2: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)   # TU 100
    net_area_m2: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)     # TU 101
    facing: UnitFacing | None = None            # TU 102
    list_price: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)      # TU 103
    # TU 104 "Maliyet" sutunu BILEREK YOKTUR — kullanici karari 3 (§4.5).

class UnitBulkCreate(BaseModel):
    block_id: uuid.UUID
    unit_kind: UnitKind
    start_floor: int = Field(ge=-5, le=100)     # TU 70
    end_floor: int = Field(ge=-5, le=100)       # TU 71
    roof_floor: bool = False                    # TU 71 "Cati Kati" secenegi (karar 4)
    units_per_floor: int = Field(ge=1, le=20)   # TU 72
    numbering: UnitNumberingPattern             # TU 79 (4 deger)
    prefix: str = Field(default="", max_length=10)
    start_number: int = Field(default=1, ge=0)  # TU 84
    slots: list[UnitBulkSlot] = Field(default_factory=list, max_length=20)   # TU 96-133
    floor_price_increase_pct: Decimal | None = Field(         # TU 138
        default=None, ge=0, le=100, max_digits=5, decimal_places=2
    )
    # `owner_side` HALA YOKTUR (P3 §6.3 / Kalici Karar 6) — dokunulmadi.
```

Doğrulama (`model_validator`):
- `end_floor >= start_floor` (mevcut) → `_INVALID_FLOOR_RANGE`
- toplam ≤ `_MAX_BULK_UNITS = 500` (mevcut) → `_BULK_LIMIT`
- `slots` boş **değilse** `len(slots) == units_per_floor` → `_SLOT_COUNT_MISMATCH`
- `slots` içindeki `sequence` değerleri `1..units_per_floor` aralığında ve **tekrarsız**
  → `_SLOT_SEQUENCE_INVALID`
- her slot için `net_area_m2 <= gross_area_m2` (`guards.ensure_net_le_gross` **çağrılır**,
  kopyalanmaz)

**`roof_floor` ve kat etiketi (karar 4'ün toplu üretim tarafı).** TU 71'in "Bitiş Katı"
seçeneklerinden biri **"Çatı Katı"**dır; `end_floor` bir tam sayı olduğu için bu seçenek
ayrı bir bayrakla taşınır. `roof_floor = True` ise `start_floor…end_floor` turlarından
**sonra bir tur daha** üretilir ve o turun etiketi `"Çatı Katı"`dır. Kat etiketi üreteci
(saf, `bulk.py`) mockup'ın kendi sözlüğüdür:

```
0        → "Zemin"          (TU 70, UE 66)
n > 0    → f"{n}. Kat"      (TU 70/71, UE 66)
n < 0    → f"{-n}. Bodrum"  (BE 78 "Bodrum Kat Sayisi")
cati     → "Çatı Katı"      (TU 71, UE 66)
```

Fiyat artışı üssü (§5.5) çatı turunda `end_floor − start_floor + 1`'dir; numaralandırmadaki
`{Kat}` jetonu ise `end_floor + 1` (§5.2). İkisi de **yalnız üretim içinde** yaşayan
sayılardır, saklanmazlar.

`slots` **boş bırakılabilir** — o zaman P3'ün eski davranışı (alan-boş üniteler) korunur.
Böylece mevcut çağıranlar kırılmaz. *Gerekçe: mockup her zaman slot doldurmayı zorlamıyor
(tablo örnek değerlerle geliyor ama boş bırakılabilir bir tablodur).*

### 5.4 **Önizleme: ayrı uç mu, `dry_run` kipi mi — ÖNERİ ve gerekçe**

> **ÖNERİ: AYRI UÇ** — `POST /projects/{project_id}/units/bulk/preview` → `200 UnitBulkPreview`.

Gerekçe (üç madde, hepsi bu repodaki mevcut kurallardan türüyor):

1. **Yanıt şekilleri farklıdır ve OpenAPI dürüst kalmalıdır.** Gerçek üretim
   `201 UnitListResponse` döner (P3 §7.7, ekran tabloyu yeniden çizer). Önizleme
   `UnitListResponse` **döndüremez**: ortada `id`'si olan ünite yoktur, `totals` projenin
   tamamını sayar, `blocks` grupları mevcut kayıtlardır. Tek uca `dry_run` bayrağı koymak
   `response_model`'i iki şeklin birleşimine (`Union`) zorlar; frontend `gen:api` çıktısı
   her iki alanı da `optional` görür ve **istemci tarafında sessiz `undefined` sınıfı** doğar.
   Repoda bu sınıfı önlemek için konmuş bir kural var (`GOREV-SIRASI.md` §3: "Backendin
   vermediği alan → zarif düşüş **+ kullanıcıya bildirim**, sessiz atlama yok").
2. **İzin ve denetim ayrımı temiz olur.** Önizleme hiçbir şey yazmaz → denetim günlüğüne
   **yazmaz** (P4 T7 kuralı: okuma uçları denetim satırı üretmez). Aynı uçta `dry_run`
   olsaydı, "yazan uç denetim yazar" kuralı bayrağa bağlı hâle gelirdi ve bu tam olarak
   denetim boşluklarının doğduğu yerdir. İzin ise `full` kalır: önizleme yazma akışının
   parçasıdır ve `view` kullanıcısına fiyat üretim kurallarını açmaz.
3. **Üretim mantığı yine TEK kopyadır.** İki uç da `bulk.generate_units(...)` saf
   fonksiyonunu çağırır (`bulk.py` bugün de saf, DB'siz bir modüldür). Kopyalanan tek şey
   uç imzasıdır; kural değildir. `POST …/units/bulk` önizleme sonucunu **yeniden üretir**,
   önizlemeden gelen satırları **kabul etmez** — aksi hâlde istemci gövdesi fiyat
   uydurabilirdi (mockup TU 182 "Önizlemeyi Yenile" da bunu ima ediyor: önizleme
   otoriter değil, tekrarlanabilir bir hesaptır).

**Aynı gerekçe Excel doğrulama ucu için de geçerlidir** (§6.2) — iki özellik simetrik kalır.

```python
class UnitBulkPreviewRow(BaseModel):
    unit_no: str                 # TU 151
    floor: int                   # TU 152 — uretim turunun SAYISI (mockup 1/2/3 boyle basiyor)
    floor_label: str             # uniteye YAZILACAK metin: "1. Kat" / "Zemin" / "Cati Kati" (karar 4)
    layout: str | None           # TU 153 "Tip"
    gross_area_m2: Decimal | None    # TU 154 "Brut/Net m²"
    net_area_m2: Decimal | None
    facing: UnitFacing | None    # TU 155
    list_price: Decimal | None   # TU 156
    conflict: bool               # TU 177 "cakisma varsa uyari verilir"

class UnitBulkPreview(BaseModel):
    total_units: int                    # TU 73, 146, 171
    total_list_value: Decimal           # TU 146, 172
    conflicting_unit_nos: list[str]     # TU 177
    rows: list[UnitBulkPreviewRow]      # TU 159-165
```

**Sunucu TÜM satırları döner** (24 değil 500 bile olsa). TU 166 "… 17 ünite daha" bir
**frontend kırpmasıdır**; sunucunun kırpması ekranın "hangi satır çakışıyor" sorusunu
cevaplayamamasına yol açardı.

### 5.5 Fiyat üretimi — mockup'tan çıkarılan, uydurulmayan

**Slot bazlı taban fiyat.** TU 103/113/122 üç slot için üç farklı `list_price` veriyor.
Önizleme (TU 159–161) birinci katta bunları **birebir** basıyor: C-1 = 1.280.000,
C-2 = 940.000, C-3 = 1.240.000. → **Fiyat slottan gelir.**

**Cepheye göre fark YOKTUR.** Cephe de slotun bir alanıdır (TU 102) ve fiyatla arasında
mockup'ta **hiçbir bağ yok** — C-1 (Güney) ile C-3 (Batı) farklı fiyatta ama farklı m²'de de.
Cepheye göre fiyat katsayısı **icat edilmez**.

**Kata göre artış VARDIR** (TU 137–138: "Üst katlarda fiyat artışı uygula · Kat başına 1.5 %
artış"). Mockup verisinden doğrulanan formül:

```
list_price(floor, slot) = slot.list_price × (1 + pct/100) ^ (floor − start_floor)
```

| Önizleme satırı | Kat | Slot tabanı | Formül | Mockup |
|---|---|---|---|---|
| C-1 (159) | 1 | 1.280.000 | ×1.015⁰ = 1.280.000 | **1.280.000** ✓ |
| C-4 (162) | 2 | 1.280.000 | ×1.015¹ = 1.299.200 | **1.299.200** ✓ |
| C-5 (163) | 2 | 940.000 | ×1.015¹ = 954.100 | **954.100** ✓ |
| C-6 (164) | 2 | 1.240.000 | ×1.015¹ = 1.258.600 | **1.258.600** ✓ |
| C-7 (165) | 3 | 1.280.000 | ×1.015² = 1.318.688 | **1.318.700** ≈ |

Bileşik (kümülatif) artıştır, doğrusal değil — C-7 bunu kanıtlıyor
(doğrusal olsaydı 1.280.000 × (1 + 0,03) = 1.318.400 çıkardı; mockup 1.318.700 diyor).

**Yuvarlama — KARAR 6: en yakın 100 ₺.** Beş satırın dördü tam sayı çıkıyor; yalnız C-7
yuvarlama gerektiriyor ve **en yakın 100 ₺'ye** yuvarlanmış (1.318.688 → 1.318.700).
Mockup'ın tek veri noktası bununla uyumludur ve karara bağlanmıştır.

Uygulama: `(raw / 100).quantize(0, ROUND_HALF_UP) * 100`, `Decimal` üzerinde — `float`
kullanılmaz (para hesabı, P7 K5 dersi). Yuvarlama **yalnız artış uygulanan** fiyata girer;
`floor_price_increase_pct is None` iken slot tabanı **aynen** yazılır (yuvarlanmaz, aksi
hâlde kullanıcının girdiği 1.234.567 ₺ sessizce 1.234.600 olurdu).

**Mockup'ta OLMAYAN, dolayısıyla uygulanmayanlar** (açıkça yazılır ki sonradan "eksik" sanılmasın):
- Cepheye göre fiyat farkı → **mockup'ta yok**
- Kata göre m² değişimi → **mockup'ta yok** (her katta aynı slot m²'si)
- Zemin kat / çatı katı için özel fiyat kuralı → **mockup'ta yok**
- Bodrum katlar için negatif artış → **mockup'ta yok**
- `appraisal_value` / `min_sale_price` / `vat_rate`'in toplu üretimde üretilmesi →
  **mockup'ta yok** (TU tablosunda bu sütunlar hiç geçmiyor); `None` doğarlar

**Toplam değer — KARAR 5: mockup HATASI, sayı kanon değildir.** TU 146/172 `₺27.264.000`
diyor. Slot toplamı `1.280.000 + 940.000 + 1.240.000 = 3.460.000`; 8 kat, artışsız →
`27.680.000`; %1,5 bileşik artışla → `≈29.177.000`. **Mockup'ın toplamı ikisiyle de
tutmuyor** — artışsız toplamın bile **altında**, yani mockup'ın kendi verisiyle
uzlaştırılamaz. Karar: `total_list_value` **satırlardan toplanır**
(`sum(row.list_price or 0)`), mockup'ın sayısı **hedeflenmez ve teste konmaz**.
Onaylı sapma §11.6.

### 5.6 Çakışma davranışı — önizlemede uyarı, üretimde hata

TU 177: "Mevcut ünite numaraları ile çakışma varsa **uyarı verilir**".

| Uç | Davranış |
|---|---|
| `POST …/units/bulk/preview` | Çakışan satırlar `conflict = true` ile **döner**, `conflicting_unit_nos` listelenir. **Hata değildir** — kullanıcı `start_number`'ı değiştirip yeniden önizler (TU 84 ipucu: "Mevcut ünitelerle çakışmaması için") |
| `POST …/units/bulk` | **HEP-YA-HİÇ korunur** → **409** `_BULK_NUMBERS_TAKEN` + ilk 20 çakışan numara. P3 §7.7 kararı **değişmiyor** |

Bu ayrım mockup'a birebir sadıktır: uyarı önizlemede, blokaj kaydetmede.

---

## 6. Excel içe aktarma — **kısmi aktarıma geçiş**

### 6.1 Önceki karardan DÖNÜŞ (açık kayıt)

> **P3 §7.8 kararı:** *"Kısmi başarısızlık davranışı — hep-ya-hiç + satır bazlı rapor
> (ikisi birden). Tek transaction'da tüm satırlar doğrulanır; **bir** satır bile hatalıysa
> **hiçbiri yazılmaz** ve `422` gövdesinde `errors` listesi döner."*
>
> **P3.1 kararı (kullanıcı, kesin): bu karardan DÖNÜLÜYOR. Kısmi aktarım uygulanacak.**

**Neden dönülüyor:**

1. **Mockup açıkça kısmi aktarım istiyor.** EI 38/202 düğmesi "**22 Geçerli Satırı Aktar**"
   diyor (24 satırın 22'si). EI 101 metni: "1 satır aktarılamayacak. Hatalı satırları
   düzeltip tekrar yükleyin **veya sadece geçerli satırları aktarın**." Bu, hep-ya-hiç ile
   uzlaştırılamaz. `GOREV-SIRASI.md` §3: *"Mockup mimariyle çelişirse kullanıcıya sor;
   **varsayılan mockup kazanır**"* — soruldu, kullanıcı mockup lehine karar verdi.
2. **P3'ün gerekçesi kısmi aktarımda da karşılanıyor.** P3 hep-ya-hiçi şöyle savunmuştu:
   *"yarı yazılmış bir içe aktarımdan sonra kullanıcı dosyayı düzeltip tekrar yükleyemez —
   başarılı satırlar artık çakışır."* Bu itiraz **kısmi aktarımda da geçerlidir ama
   zararsızdır**: yeniden yükleme sırasında zaten yazılmış satırlar "bu ünite numarası bu
   blokta zaten kullanılıyor" **hatası** ile raporlanır ve **atlanır**; kalan (düzeltilmiş)
   satırlar yazılır. Yani "düzelt ve yeniden yükle" döngüsü **yine tek adımda tekrarlanabilir**;
   fark, kullanıcının 22 satırı ikinci kez yazmaması ve raporda 22 "zaten var" satırı görmesidir.
3. **Uyarı kategorisi hep-ya-hiçe sığmıyor.** EI 97/166/192 bir **uyarı** durumu ve
   "uyarılı satırları da aktar" kutucuğu gösteriyor. Hep-ya-hiçte "uyarılı satırı aktar/aktarma"
   seçeneğinin anlamı yoktur — tüm dosya ya yazılır ya yazılmaz.

**Değişecek olanlar (uygulama sırasında bunlar aranacak):**
- `app/modules/units/batch.py::_raise_row_errors` — artık istisna fırlatmaz, rapor üretir
- `app/modules/units/batch.py::import_units` — hatalı satırlar **atlanır**, geçerliler yazılır
- `app/modules/units/schemas.py::UnitImportResult` — genişler (§6.3)
- `app/core/errors.py::UnitImportError` — **kullanılmaz hâle gelir** (§6.3 sonu)
- P3 §11.3 test **28** ("3. satırda `net > brüt` → 422, hiçbir ünite yazılmamış") → **tersine döner**
- `messages.units_imported` — imza değişir (§9)

### 6.2 Üç uç: doğrula · aktar · şablon

| Uç | Yöntem | İzin | Yanıt | Mockup |
|---|---|---|---|---|
| `POST /projects/{id}/units/import/validate` | POST multipart | `full` | `200 UnitImportValidation` | EI 201 "Yeniden Doğrula", EI 92–197 (Adım 2 ve 3) |
| `POST /projects/{id}/units/import` | POST multipart | `full` | `200 UnitImportResult` | EI 38/202 "22 Geçerli Satırı Aktar" |
| `GET /projects/{id}/units/import/template` | GET | `view` | `200` `.xlsx` akışı | EI 37, 87 "Şablon İndir" |

**Doğrulama neden ayrı uç (yine `dry_run` bayrağı değil):** §5.4'teki üç gerekçenin aynısı —
yanıt şekli farklı (`UnitImportValidation` ≠ `UnitImportResult`), denetim günlüğü davranışı
farklı (doğrulama **yazmaz**), ve iki uç aynı saf `importer.parse_units_file` +
`_domain_row_reports` fonksiyonlarını çağırır, kural kopyalanmaz.

> **Sonuç — kullanıcıya söylenmesi gereken UX kısıtı:** dosya **sunucuda saklanmaz**
> (P3 §7.8'in değişmeyen sınırı). Bu yüzden "Yeniden Doğrula" ve ardından "Aktar" akışında
> dosya **iki kez yüklenir**. Tarayıcıda bu bedava sayılır: `File` nesnesi zaten istemcinin
> belleğindedir ve ikinci `POST` aynı nesneyi gönderir; kullanıcı dosyayı yeniden seçmez.
> Frontend dilimi bunu bilerek yazmalıdır.

`GET …/import/template` **izni `view`'dır**: boş bir başlık satırı hiçbir proje verisi
içermez; onu `full`'a kapatmak, veri girecek kullanıcıyı şablona ulaşamaz hâle getirirdi.
**Karar 3 uyarınca uç bu dilimde açılır** (§6.7).

**Hedef Şantiye (`site_id`) — karar 3, iki yazma ucunun da gövdesinde.**
`POST …/units/import` ve `POST …/units/import/validate` multipart gövdesine
**opsiyonel `site_id: UUID | None`** alanı eklenir (EI 61).

| Durum | Davranış |
|---|---|
| Projede **tek** şantiye | `site_id` gönderilmese de o şantiye kullanılır (P3 §4.5 aynen) |
| Projede **birden çok** şantiye + `site_id` **yok** | **422** `_SITE_REQUIRED` (P3 §4.5, değişmedi) |
| Projede birden çok şantiye + `site_id` **var** | **Yeni bloklar bu şantiyede açılır** — bugün 422 veren yol böyle açılır |
| `site_id` başka projenin şantiyesi / görünmez | **404** "Şantiye bulunamadı" (IDOR seti §12.6) |

`site_id` **yalnız yeni blok açarken** kullanılır. Dosyadaki blok adı projede **zaten
varsa** o blok aynen kullanılır ve `site_id` ile **karşılaştırılmaz**: kullanıcı mevcut
bir bloğa ünite eklerken bloğun şantiyesini değiştirmiş olmaz (blok taşımak bu ucun işi
değildir). Bu, sessiz bir veri taşıma riskini kapatır.

### 6.3 Yanıt şemaları

```python
class UnitImportRowStatus(str, enum.Enum):
    ok = "ok"           # EI 131/142/177 yesil ✓, mesaj "Hazir" (138)
    warning = "warning" # EI 166 ⚠
    error = "error"     # EI 154 ✗

class UnitImportRowReport(BaseModel):
    """EI 118-126 sutunlari BIREBIR."""
    row: int                       # EI 118 "Satir" — Excel satir no (baslik=1, veri 2'den)
    status: UnitImportRowStatus    # EI 119 "Durum"
    unit_no: str | None            # EI 120
    block_name: str | None         # EI 121 "Blok"
    floor: str | None              # EI 122 "Kat" — METIN (karar 4)
    layout: str | None             # EI 123 "Tip"
    gross_area_m2: Decimal | None  # EI 124
    list_price: Decimal | None     # EI 125
    messages: list[str]            # EI 126 "Mesaj" — EI 161 BIR satirda IKI mesaj
    imported: bool                 # gercek aktarimda yazildi mi (dogrulamada daima false)

class UnitImportSummary(BaseModel):
    """EI 94-99 dort sayac kutusu."""
    total_rows: int      # EI 95 "Toplam Satir 24" (EI 69 "24 satir okundu")
    valid: int           # EI 96 "Gecerli 22"
    warning: int         # EI 97 "Uyari 1"
    error: int           # EI 98 "Hata 1"

class UnitImportValidation(BaseModel):
    summary: UnitImportSummary
    rows: list[UnitImportRowReport]
    blocks_to_create: list[str]     # dosyada gecen, projede olmayan blok adlari

class UnitImportResult(BaseModel):      # P3'teki sema GENISLIYOR
    summary: UnitImportSummary
    created: int          # gercekten yazilan unite adedi (EI 202 "22")
    skipped: int          # atlanan satir adedi
    blocks_created: int   # (var)
    rows: list[UnitImportRowReport]
```

`UnitImportResult.errors: list[UnitImportRowError]` alanı **kaldırılır**; yerini
`rows` alır (uyarı/başarı satırlarını da taşıyabilen tek liste). `UnitImportRowError` şeması
ve `app/core/errors.py::UnitImportError` istisnası **artık kullanılmaz** — silinip
silinmeyeceği uygulama task'ında karar verilir; **kullanılmadığı hâlde bırakılırsa
`ruff` ölü kod uyarısı vermez ama bir sonraki ajanı yanıltır**, bu yüzden **silinmesi önerilir**.

`sales_status` ve `min_sale_price`/`vat_rate` **Excel'de yoktur** (EI 85 kolon listesi) →
içe aktarılan üniteler bu alanlarda sunucu varsayılanıyla (`listed`) / `None` ile doğar.

### 6.4 Excel sütunları — 9 → 12, iki başlık yeniden adlandırılıyor

EI 85 kanon: `Blok, Kat, Ünite No, Tür, Oda Tipi, Brüt m², Net m², Cephe, Liste Fiyatı,
Rayiç Değer, Maliyet, Sahiplik`.

| Sütun | Başlık (YENİ kanon) | Zor. | Hedef | Değişim |
|---|---|---|---|---|
| A | `Blok` | ✔ | `blocks.name` (yoksa oluşturulur) | (var) |
| B | **`Kat`** | — | `units.floor` (**metin**, karar 4) | **YENİ** |
| C | `Ünite No` | ✔ | `unit_no` | (var) |
| D | `Tür` | ✔ | `unit_kind` — `Daire`·`Dükkan`·**`Ofis`·`Depo`·`Otopark`** | değer kümesi genişledi (§4.3) |
| E | **`Oda Tipi`** | **✔** | `layout` | **başlık değişti** (`Tip` → `Oda Tipi`) **ve zorunlu oldu** (EI 161) |
| F | `Brüt m²` | **✔** | `gross_area_m2` | **zorunlu oldu ve `> 0`** (EI 161 "Brüt m² sıfır olamaz") |
| G | `Net m²` | — | `net_area_m2` | (var) |
| H | **`Cephe`** | — | `units.facing` | **YENİ** |
| I | `Liste Fiyatı` | — | `list_price` | (var) |
| J | `Rayiç Değer` | — | `appraisal_value` | (var) |
| K | **`Maliyet`** | — | **(saklanmaz)** | **YENİ — karar 10: okunur → uyarı üretir → ATILIR** (§4.5, §6.5). Maliyet kolonu **açılmaz**; maliyet ileride İş Kalemleri/satınalmadan gelecek |
| L | **`Sahiplik`** | — | `owner_side` | **başlık değişti** (`Pay` → `Sahiplik`) |

**Geriye dönük uyum:** eski başlıklar (`Tip`, `Pay`) **eşanlamlı olarak kabul edilir**.
Gerekçe: P3 canlıdadır ve kullanıcının elinde eski şablonla doldurulmuş dosyalar olabilir;
başlık eşleştirme zaten normalize ediliyor (`importer.normalize_header`), eşanlamlı kabul
etmek üç satırlık iştir ve sessiz bir "başlık eksik" 422'sini önler.

`Sahiplik` değer sözlüğü: mevcut `BİZ`/`ARSA`'ya ek olarak UE 95 etiketleri
(`Yüklenici (Biz)` → `contractor`, `Arsa Sahibi Payı` → `landowner`) de kabul edilir —
kullanıcı formda gördüğü etiketi Excel'e yazacaktır.

`Cephe` değer sözlüğü: `Güney`, `Güney-Batı`, `Doğu`, `Kuzey`, `Batı` (§4.2).

`Kat` **sözlüğü YOKTUR** (karar 4): hücre metni kırpılıp **aynen** yazılır
(`"Zemin"`, `"3. Kat"`, `"Çatı Katı"`, `"3"`). Sayıya çevirme, `"Zemin" → 0` eşlemesi ve
`"3" → "3. Kat"` güzelleştirmesi **yapılmaz** — kullanıcının gösterimini sessizce
değiştirmek veri dönüşümüdür. Tek kural: `max_length = 20` (§6.5).

### 6.5 Satır kuralları — hata mı uyarı mı

**HATA (`error`) — satır yazılmaz:**

| Kural | Kaynak |
|---|---|
| `Blok` boş | EI 85 zorunlu |
| `Ünite No` boş | EI 85 zorunlu |
| `Tür` boş / sözlükte yok | (var) |
| **`Oda Tipi` boş** | **EI 161 "Oda Tipi boş"** |
| **`Brüt m²` boş veya `0`** | **EI 161 "Brüt m² sıfır olamaz"** |
| sayısal alan sayıya çevrilemiyor / negatif | (var) |
| `Net m² > Brüt m²` | (var, `guards.ensure_net_le_gross`) |
| `Sahiplik` dolu ama proje `kat_karsiligi` değil | (var, `guards.ensure_owner_side_allowed`) |
| `Cephe` sözlükte yok | §4.2 (YENİ) |
| **`Kat` 20 karakterden uzun** | §4.2 (YENİ) — kat **metindir**, sayı kuralı **yoktur** |
| dosya içinde aynı `(Blok, Ünite No)` iki kez | (var) |
| blokta o `unit_no` **zaten var** | (var) — kısmi aktarımda artık **satır atlanır**, dosya reddedilmez |

**UYARI (`warning`) — kullanıcı isterse yazılır (EI 192):**

| Kural | Kaynak |
|---|---|
| **`Liste Fiyatı < Maliyet`** → mesaj `Fiyat maliyetin altında (₺{maliyet}) — kontrol edin` | **EI 173, tek uyarı kuralı** |

**Uyarı kümesi KAPALIDIR.** Mockup'ta başka uyarı yok; `min_sale_price` karşılaştırması,
`m²` başına fiyat sapması, `KDV` tutarsızlığı gibi kurallar **icat edilmez**.

**Karar 10** `Maliyet` sütununun rolünü kesinleştirir: **okunur, uyarıyı üretir, atılır.**
Maliyet kolonu **açılmaz** — maliyet ileride İş Kalemleri/satınalmadan gelecektir. Bu,
kullanıcı kararı 3 ile çelişmez: dosyadaki maliyet **hiçbir yere yazılmaz**, yalnız
kullanıcının kendi verisiyle kendi fiyatını çapraz kontrol etmesini sağlar. Sütunu hiç
okumamak seçeneği **reddedildi** — o zaman EI 173'teki uyarı hiç üretilemez ve mockup'ın
uyarı kategorisi anlamsızlaşırdı.

### 6.6 "Hata Raporunu İndir" (EI 195) — **uç açılmaz**, gerekçe

**Karar: sunucu ucu YOK; rapor istemcide üretilir.**

1. **Sunucuda üretecek veri yok.** Dosya saklanmıyor (P3 §7.8'in değişmeyen sınırı), rapor
   ise yüklenen dosyanın türevi. Bir uç açmak, kullanıcının dosyayı **üçüncü kez** yüklemesi
   demek olurdu — sırf az önce JSON olarak aldığı veriyi `.xlsx` biçiminde geri almak için.
2. **Rapor zaten yanıtın içinde.** `UnitImportValidation.rows` / `UnitImportResult.rows`
   EI 118–126'daki dokuz sütunun **tamamını** taşıyor. İstemci bunu bir `.csv`/`.xlsx`
   olarak indirtebilir; ek sunucu turu yok.
3. **BOQ Excel dışa aktarım ucuyla karışmasın:** orada veri **sunucuda yaşıyor** (BOQ kalemleri
   DB'de), burada yaşamıyor. Aynı görünen iki işin altyapı gereksinimi farklıdır.

Frontend dilimi için bağlayıcı not: düğme **istemci tarafı** indirme olarak yazılır;
`GOREV-SIRASI.md` §3'ün "ikili indirme `Content-Type` tabanlıdır" kuralı burada **geçerli
değildir**, çünkü ağ isteği yoktur.

### 6.7 "Şablon İndir" (EI 37, 87) — uç **açılır**

`GET /projects/{project_id}/units/import/template` → `.xlsx`, tek sayfa, tek satır: §6.4'ün
12 başlığı, kanonik sırayla. Veri satırı **yoktur** (örnek satır koymak, kullanıcının onu
silmeyi unutup hatalı satır olarak yüklemesine yol açar).

Gerekçe: mockup düğmeyi **iki kez** gösteriyor (üst çubuk 37 ve bilgi kutusu 87) ve
EI 54 akışı "**şablonu indirip doldurun**, sonra yükleyin" diye tarif ediyor — şablon akışın
ilk adımıdır, süs değil. `openpyxl` zaten bağımlılıktır (BOQ dışa aktarımı), yeni paket yok.
Denetim günlüğüne **yazmaz** (okuma ucu).

---

## 7. Şemalar

### 7.1 Taslak kuralı — zorunluluk nerede

`GOREV-SIRASI.md` §4 Kalıcı Karar 4: *"Taslak desteği projelerde ve şantiyelerde:
zorunluluk yalnız taslak-dışı kayıtta. Bu yüzden yeni kolonlar nullable."*

`blocks` ve `units` tablolarında **`is_draft` sütunu YOKTUR** ve bu dilimde **açılmaz**
(mockup'ta blok/ünite için "Taslak Kaydet" düğmesi yok — BE 113 ve UE 127 yalnız "Kaydet"
diyor). Yine de **hiçbir yeni kolon `NOT NULL` yapılmaz**; gerekçe iki katmanlıdır:

1. Canlıda P3 blokları/üniteleri **zaten var** ve yeni kolonlarda değerleri yok. `NOT NULL`
   bir backfill zorlar; backfill uydurulmuş varsayılan demektir.
2. Formun `*` işaretli alanları **Pydantic düzeyinde** zorlanır (`UnitCreate.floor`,
   `BlockCreate.floor_count` vb.), DB düzeyinde değil — şantiye formu genişlemesinde
   alınan kararın birebir aynısı.

> **KARAR 11 (kesin): yeni alanların HİÇBİRİ `Create` şemasında zorunlu DEĞİLDİR.**
> Mockup'taki `*` (BE 79 `floor_count` · UE 66 `floor` · UE 74 `unit_kind` · UE 94
> `sales_status`) **yalnız UI ipucudur**; ne DB'de `NOT NULL`, ne Pydantic `Create`'te
> zorunluluk doğurur. `sales_status` `Create`'te **varsayılan** `listed` alır (mockup
> zaten seçili geliyor) — varsayılan ≠ zorunluluk.
>
> Gerekçe üç katmanlı: (1) taslak desteği (Kalıcı Karar 4), (2) Excel içe aktarma `Kat`
> sütununu zorunlu tutmuyor (EI 85'te `*` yok) — zorunlu yapılsaydı içe aktarma **kendi
> kendini** kırardı, (3) P3'ün mevcut `POST …/units` testleri gövdeye bu alanları
> koymuyor; zorunluluk mevcut takımın (1411 test) bir bölümünü **gereksiz yere** kırardı.
> *İstisna yok — `unit_kind` P3'ten beri zaten zorunludur ve öyle kalır (yeni alan değil).*

### 7.2 Değişen ve yeni şemalar (özet)

| Şema | Değişim |
|---|---|
| `BlockCreate` | +13 alan (§3.1); `code` opsiyonel (boşsa üretilir) |
| `BlockUpdate` | +13 alan, hepsi opsiyonel |
| `BlockResponse` | +13 alan + **`estimated_unit_count: int \| None`** (türev, §3.3) |
| `UnitCreate` | +8 alan (§4.1); **hiçbiri zorunlu değil** (karar 11); `floor: str \| None` (karar 4) |
| `UnitUpdate` | +8 alan, hepsi opsiyonel |
| `UnitResponse` | +8 alan + **`expected_profit: MetricPlaceholder`** (UE 97, YENİ yer tutucu); `sales_status` artık **gerçek değer** (eskiden `MetricPlaceholder`) |
| `UnitKindBreakdown` | +3 sayaç (`office`, `warehouse`, `parking`), §4.3 |
| `UnitNumberingPattern` | 2 → **4 değer** (§5.2) |
| `UnitBulkCreate` | +`slots`, +`floor_price_increase_pct`, **+`roof_floor: bool`** (TU 71, §5.3); `numbering` genişledi |
| `UnitImportRequest` (multipart alanları) | **+`site_id: UUID \| None`** — karar 3, §6.2 |
| `UnitBulkSlot` | **YENİ** (§5.3) |
| `UnitBulkPreview`, `UnitBulkPreviewRow` | **YENİ** (§5.4) |
| `UnitImportSummary`, `UnitImportRowReport`, `UnitImportRowStatus`, `UnitImportValidation` | **YENİ** (§6.3) |
| `UnitImportResult` | **genişledi**; `errors` alanı kaldırıldı |
| `UnitImportRowError` | **kaldırılır** (§6.3) |
| `UnitFacing`, `UnitParkingRight`, `UnitSalesStatus`, `BlockRoofType`, `BlockGroundUsage`, `BlockParkingType`, `BlockStatus` | **YENİ enum'lar** |

**`UnitResponse.sales_status` tip değişimi kırıcıdır** (`MetricPlaceholder` → `UnitSalesStatus`).
Frontend `gen:api` yeniden üretilmeli; `openapi.json` elle kopyalanmalı (`GOREV-SIRASI.md` §3).

---

## 8. Uçlar

### 8.1 Tablo

| # | Uç | Yöntem | İzin | Durum |
|---|---|---|---|---|
| 1 | `/projects/{id}/blocks` | GET | `view` | **değişti** (yanıt +13 alan) |
| 2 | `/projects/{id}/blocks` | POST | `full` | **değişti** (gövde +13 alan, kod üretimi) |
| 3 | `/blocks/{id}` | PATCH | `full` | **değişti** (gövde +13 alan) |
| 4 | `/blocks/{id}` | DELETE | `admin` | değişmedi |
| 5 | `/projects/{id}/units` | GET | `view` | **değişti** (yanıt +8 alan) + **yeni süzgeçler** §8.2 |
| 6 | `/projects/{id}/units` | POST | `full` | **değişti** (gövde +8 alan) |
| 7 | `/units/{id}` | PATCH | `full` | **değişti** |
| 8 | `/units/{id}` | DELETE | `admin` | değişmedi |
| 9 | `/projects/{id}/units/bulk` | POST | `full` | **değişti** (slot + artış + 4 desen) |
| **10** | **`/projects/{id}/units/bulk/preview`** | **POST** | `full` | **YENİ** (§5.4) |
| 11 | `/projects/{id}/units/import` | POST | `full` | **davranış değişti — kısmi** (§6) + **gövdeye `site_id`** (karar 3) |
| **12** | **`/projects/{id}/units/import/validate`** | **POST** | `full` | **YENİ** (§6.2), gövdede `site_id` |
| **13** | **`/projects/{id}/units/import/template`** | **GET** | `view` | **YENİ** (§6.7) |
| 14 | `/projects/{id}/units/allocation` | PATCH | `full` | değişmedi |

**11 uç → 14 uç.** Kök yolları değişmiyor (`projects`, `blocks`, `units`) → **BFF izin
listesi güncellemesi GEREKMEZ** (`GOREV-SIRASI.md` §3 tuzağı bu dilimde tetiklenmiyor;
yine de frontend dilimi `grep`'le doğrulamalıdır).

### 8.2 `GET /projects/{id}/units` yeni süzgeçler

Mevcut: `block_id`, `site_id`, `kind`, `owner_side`.
**YENİ:** `floor: str | None` (**tam eşleşme**, kat metindir — karar 4),
`sales_status: UnitSalesStatus | None`.

Gerekçe: `sales_status` artık gerçek bir sütundur ve KY 264–267 / SY 101 satış durumu
kırılımını gösteriyor; süzgeçsiz bu ekran istemcide filtrelemek zorunda kalır.
**Kural değişmez:** süzgeçler yalnız listeyi daraltır, `totals` **daima projenin tamamını**
sayar (P3 §7.4).

`UnitTotals`'a **`by_sales_status: dict[UnitSalesStatus, int]`** eklenir — KY 258–259
("34 satıldı · 5 rezerve · 13 boş") ve KKP 161–163 tfoot kırılımı artık **gerçek** sayılabilir.
Bunun sonucu olarak P3'teki `sold_units` / `reserved_units` / `available_units`
`CountPlaceholder` alanları **gerçek sayaçlara dönüşür**; `sales_revenue` ve
`average_sale_price` **yer tutucu kalır** (gerçekleşen satış tutarı hâlâ P8'in verisidir).

### 8.3 Türkçe hata mesajları — yeni sabitler

`app/modules/units/guards.py`'ye eklenecekler (mevcut 13 sabit korunur):

| Sabit | Metin | Kod |
|---|---|---|
| `_DUPLICATE_BLOCK_CODE` | `Bu blok kodu bu projede zaten kullanılıyor` | 409 |
| `_SLOT_COUNT_MISMATCH` | `Kat şablonu satır sayısı kat başına daire sayısıyla eşleşmiyor` | 422 |
| `_SLOT_SEQUENCE_INVALID` | `Kat şablonunda sıra numaraları geçersiz veya tekrarlı` | 422 |
| `_INVALID_FLOOR` | `Kat bilgisi en fazla 20 karakter olabilir` | 422 (kat **metindir**, karar 4) |
| `_INVALID_VAT_RATE` | `KDV oranı yalnızca %1, %10 veya %20 olabilir` | 422 |
| `_IMPORT_NOTHING_TO_WRITE` | `Aktarılabilecek geçerli satır yok` | 422 |
| `_IMPORT_ROW_LAYOUT_REQUIRED` | `Oda Tipi boş olamaz` | satır mesajı |
| `_IMPORT_ROW_GROSS_REQUIRED` | `Brüt m² sıfır olamaz` | satır mesajı |
| `_IMPORT_ROW_PRICE_BELOW_COST` | `Fiyat maliyetin altında (₺{cost}) — kontrol edin` | satır uyarısı |
| `_IMPORT_ROW_UNIT_EXISTS` | `Bu ünite numarası bu blokta zaten kullanılıyor` | satır mesajı (mevcut `_DUPLICATE_UNIT` yeniden kullanılır) |

`_IMPORT_ROW_ERRORS` (`Dosya işlenemedi, {n} satırda hata var`) **kaldırılır** — kısmi
aktarımda dosya artık "işlenemedi" durumuna düşmez; yalnız **hiç geçerli satır yoksa**
`_IMPORT_NOTHING_TO_WRITE` ile 422 döner (aksi hâlde `created=0` ile 200 dönmek, kullanıcının
"aktarıldı" sanmasına yol açar).

---

## 9. Denetim günlüğü

`app/modules/audit/messages.py` — **değişen ve yeni** fonksiyonlar:

```python
def units_imported(project_name: str, created: int, skipped: int) -> str:
    """DEGISTI (§6.1): kismi aktarimda atlanan satir sayisi da yazilir, yoksa
    denetim gunlugu 'kac unite geldi' sorusuna yaniltici cevap verir."""
    if skipped:
        return f"Üniteler Excel'den içe aktarıldı: {project_name} · {created} ünite ({skipped} satır atlandı)"
    return f"Üniteler Excel'den içe aktarıldı: {project_name} · {created} ünite"
```

| Uç | `AuditAction` | Mesaj |
|---|---|---|
| `POST …/blocks` | `create` | `block_created` (değişmedi) |
| `PATCH /blocks/{id}` | `update` | `block_updated` (değişmedi) |
| `DELETE /blocks/{id}` | `delete` | `block_deleted` (değişmedi) |
| `POST …/units` | `create` | `unit_created` (değişmedi) |
| `PATCH /units/{id}` | `update` | `unit_updated` (değişmedi) |
| `DELETE /units/{id}` | `delete` | `unit_deleted` (değişmedi) |
| `POST …/units/bulk` | `create` | `units_bulk_created` (değişmedi) |
| **`POST …/units/bulk/preview`** | — | **YAZMAZ** (okuma ucu, P4 T7) |
| `POST …/units/import` | `create` | **`units_imported` — imza değişti** |
| **`POST …/units/import/validate`** | — | **YAZMAZ** |
| **`GET …/units/import/template`** | — | **YAZMAZ** |
| `PATCH …/units/allocation` | `update` | `unit_allocation_updated` (değişmedi) |

Blok kodu üretimi ayrı mesaj **almaz** — `block_created` zaten blok adını taşır ve kod
yanıt gövdesinde döner.

---

## 10. Migration planı

### 10.1 Ebeveyn revizyon

**Bu spec SABİT REVİZYON YAZMAZ.** Ebeveyn, uygulama anında `alembic heads` ile
doğrulanacaktır. P5 ve P7 merge edildikten sonra head `d2a32dcae735` **civarındadır**
(`GOREV-SIRASI.md` §0.2), ama araya başka dilim girebilir — **spec'e sabitlemek, T1'i
yanlış ebeveyne bağlayan bir tuzaktır.**

**T1'de `.venv/bin/alembic heads` KOŞULUR ve çıktı doğrulanır.** İki head çıkarsa **kod
yazılmaz**, kullanıcıya sorulur (birleştirme revizyonu kullanıcı kararıdır).

### ⚠️ MIGRATION TUZAĞI — `alembic` override'sız çalıştırılırsa CANLIYA VURUR

`backend/.env`'deki **`DATABASE_URL` de uzak Railway'i gösteriyor** (`TEST_DATABASE_URL`
tuzağının ikizi). P7 diliminde bu tuzak **canlı crash döngüsüne** yol açtı: migration'lar
canlı DB'ye koşuldu, `alembic_version` damgalandı, deploy'daki kod o revizyonu içermediği
için konteyner `Can't locate revision identified by …` ile çöktü.

**Her `alembic` çağrısında override ŞARTTIR — `heads` dahil** (`env.py` bağlanmayı dener):

```bash
DATABASE_URL="postgresql+asyncpg://furkanilgen@localhost:5432/<yerel>" .venv/bin/alembic heads
DATABASE_URL="postgresql+asyncpg://furkanilgen@localhost:5432/<yerel>" .venv/bin/alembic upgrade <rev>
```

`.env`'e **DOKUNULMAZ**. **Canlı DB'ye migration koşulmaz** — canlı, merge edilmiş kodun
deploy'u sırasında kendi migration'ını koşar. Bu blok her uygulama ajanının brifingine
**birebir** kopyalanır.

### 10.2 Üç izole revizyon

`d1a2b3c4e5f6` ve `f1b2c3d4e5a6` dersi: **enum takası kendi revizyonunda izole edilir.**

| # | Revizyon | İçerik |
|---|---|---|
| **R1** | `unit_kind` enum takası | `apartment · shop` → `apartment · shop · office · warehouse · parking`. Tip takası (§4.3). **Başka hiçbir şey yok** |
| **R2** | yeni enum tipleri | `CREATE TYPE`: `block_roof_type`, `block_ground_usage`, `block_parking_type`, `block_status`, `unit_facing`, `unit_parking_right`, `unit_sales_status` (**7 tip**) |
| **R3** | kolon eklemeleri | `blocks` +13 kolon +1 UNIQUE +6 CHECK; `units` +8 kolon **+4 CHECK** (`ck_units_floor` **yok** — kat metin, karar 4) |

R2 ve R3 birleştirilebilir görünür ama ayrılmalarının nedeni **downgrade'dir**: Postgres'te
`ENUM` tablo/kolon ile birlikte silinmez; kolonları düşürüp tipleri bırakmak ikinci
`upgrade`'i patlatır (`GOREV-SIRASI.md` §3). Ayrı revizyonlar her tipin `DROP TYPE`'ını
kendi `downgrade`'ine yazmayı **zorunlu** kılar.

### 10.3 `NOT NULL` yok

**Bu dilimde hiçbir kolon `NOT NULL` yapılmaz** — §7.1'deki taslak gerekçesi. `status` ve
`sales_status` yalnız `server_default` alır (`'construction'` / `'listed'`), bu mevcut
satırları **değiştirmez**.

### 10.4 Veri geçişi

- **Mevcut satırlar değişmez.** 13+8 kolonun tamamı `NULL` ile doğar.
- **`blocks.code` backfill'i YOKTUR — karar 8.** Canlı blokların koduna dokunan **hiçbir
  veri migration'ı yazılmaz**; `code` `NULL` kalır ve bloğun **bir sonraki düzenlemesinde**
  (`PATCH /blocks/{id}`, kod boşsa) üretilir. `{Blok}` jetonunun kodu olmayan blokta neye
  çözüleceği §3.2'de ele alındı (§13.2'nin tek açık maddesi).
- **Tablo kilidi:** `ALTER TABLE … ADD COLUMN` varsayılansız/nullable ise Postgres'te
  metadata-only'dir; `server_default`'lu ekleme PG 11+ sürümünde de tabloyu yeniden yazmaz.
  `blocks` ve `units` küçük tablolardır. `unit_kind` tip takası (R1) `units`'i **yeniden
  yazar** — canlıda ünite adedi düşük olduğu için kabul edilebilir, ama kilit penceresi
  R1'in tek başına koşmasının bir sebebi daha.
- `modules` / `role_permissions` tablolarına **dokunulmaz** (§8 izin kararı değişmedi).

---

## 11. Onaylı sapmalar

> `GOREV-SIRASI.md` §3 "%100 mockup" kuralından **bilinçli yedi sapma**. Yedisi de
> **kullanıcı/koordinatör kararıdır** (2026-07-31). Bir sonraki ajan bunları "spec ihlali"
> sanıp düzeltmeye kalkmamalıdır.

### 11.1 Blok kodu biçimi — BE 71'deki `YV-C` örneği uygulanmaz

**Sapma:** mockup BE 71 yer tutucusu `YV-C` (proje kısaltması + blok harfi).
**Karar:** kod **yalnız blok adından** kısaltılır (`"C Blok"` → `C`), proje öneki yok.
**Gerekçe (kullanıcı kararı 4):** TU 79/159–165 ve EI 132–178 ünite numaralarını
`C-1`, `C-4`, `B-1` biçiminde gösteriyor — proje ön ekli bir kod bu numaraları
`YV-C-1` yapardı ve mockup'ın **asıl** gösterdiği çıktıyla çelişirdi. Yer tutucu metni
mockup'ın en zayıf kanıtıdır; üretilen veri en güçlüsüdür.
**Sınır:** kullanıcı elle `YV-C` yazarsa **aynen kabul edilir**; yalnız otomatik üretim
kısa biçimi kullanır.

### 11.2 Maliyet alanları formda görünür ama sunucuya gitmez

**Sapma:** UE 91 ve TU 104 birer **girdi alanıdır** (kullanıcı yazabiliyor).
**Karar:** ikisi de sunucuya gönderilmez; UE 91 salt-okunur yer tutucuya dönüşür, TU 104
sütunu istemci-yerel bir hesap alanı olarak kalır (ya da frontend dilimi kaldırır).
**Gerekçe (kullanıcı kararı 3):** maliyet İş Kalemleri/satınalmadan otomatik hesaplanacak;
elle girilen maliyet ikinci bir otorite yaratır ve otomatik hesap geldiğinde hangisinin
doğru olduğu **sessizce** belirsizleşir.
**Sınır:** Excel'deki `Maliyet` sütunu **okunur ama saklanmaz** (§6.4) — bu sapmanın istisnası
değil, doğrudan sonucudur: veri girdi değil, doğrulama girdisidir.

### 11.3 Dosya tipi ve boyut sınırı

**Sapma:** EI 76/79 `.xlsx, .xls, .csv` ve "Maks **10 MB**" diyor.
**Karar:** yalnız `.xlsx`, en fazla **2 MB** (P3 §7.8, değişmiyor).
**Gerekçe:** `openpyxl` `.xls` ve `.csv` okumaz; başka bir kütüphane eklemek
(`xlrd`/`pandas`) bu dilimin kapsamını aşar. 2 MB sınırı 1000 satırlık bir `.xlsx` için
(~50 KB) fazlasıyla yeterlidir ve bellek saldırısını keser. **Frontend dilimi için bağlayıcı:**
sürükle-bırak alanının `accept` özniteliği ve yardım metni `.xlsx · Maks 2 MB` olarak
düzeltilir — mockup'ın metni **yanıltıcıdır**, kullanıcıya 10 MB'lık `.csv` yükletip 422
almak sessiz olmayan ama gereksiz bir hatadır.

### 11.4 Ertelenen iki formun sekmesi HİÇ BASILMAZ (karar 12)

**Sapma:** BE 48–52 (ve UE/TU/EI'nin aynı şeridi) **beş** sekme gösteriyor; ikisi
(Bölüm Ekle, Paylaşım Girişi) bu dilimin kapsamı dışında (§1.2).
**Karar:** o iki sekme **hiç basılmaz** — ne gizli-devre-dışı, ne "yakında" etiketi,
ne tıklanınca boş sayfa. Şerit **dört** sekmeyle çıkar.
**Gerekçe:** "yakında" rozeti, kullanıcıya tarih vaat etmeyen bir vaattir ve ekranda
kalıcılaşır; tıklanabilir ama boş bir sekme ise sessiz düşüş sınıfıdır. Ertelenen iş
`GOREV-SIRASI.md`'de zaten kayıtlıdır — ekranda izini bırakmasına gerek yoktur.
**Bağlayıcı:** frontend dilimi bu iki sekmeyi **eklemez**; eklenmemesi eksiklik değildir.

### 11.5 Ünite numarasında başa sıfır YOK (karar 1) — P3'ten dönüş

**Sapma:** mockup değil, **P3'ün kendi kararı** aşılıyor: `bulk.py:_FLOOR_SEQUENCE_WIDTH = 2`
sabiti `101, 102, 201` üretiyor.
**Karar:** dolgu **slot sayısı kadar** (`W = len(str(units_per_floor))`) → mockup'ın
`C-4`, `11`, `12`, `21` biçimi. Sabit ve onu açıklayan yorum **kaldırılır**.
**Gerekçe:** TU 79 ve TU 159–165 kanon; yer tutucu değil **üretilmiş veri** gösteriyor.
**Sınır:** çakışma güvencesi korunur — `units_per_floor ≥ 10` iken W kendiliğinden 2 olur.
**Kırılan P3 testleri** §5.2'de tek tek listelidir; **bilerek** güncellenir.

### 11.6 TU 146/172'deki toplam mockup hatasıdır (karar 5)

**Sapma:** mockup `₺27.264.000` diyor; kendi slot/kat verisiyle **hiçbir formülde** bu sayı
çıkmıyor (artışsız 27.680.000, %1,5 bileşik ≈29.177.000 — mockup ikisinin de **altında**).
**Karar:** mockup hatası kabul edilir; `total_list_value` **satırlardan** hesaplanır.
**Gerekçe:** bir sayıyı tutturmak için formülü bozmak, doğru formülü kaybettirir.
**Sınır:** satır fiyatlarının kendisi (TU 159–165) **kanondur** ve teste birebir konur —
sapma yalnız tfoot toplamını kapsar. (P7'nin "OLU tfoot toplamları altın sayı değildir"
bulgusunun aynısı — mockup'ların tablo toplamları elle yazılmış görünüyor.)

### 11.7 Taban fiyat (`min_sale_price`) kısıtsızdır (karar 2)

**Sapma:** UE 92 ipucu "Danışman bu fiyatın altına inemez" diyor — bir kural ima ediyor.
**Karar:** `min_sale_price ≤ list_price` **hiçbir katmanda zorlanmaz**; taban fiyat serbest
girilir. İpucunun bağladığı taraf **danışmandır** (satış akışı, P8), veri girişi değil.
**Gerekçe:** ikisi de nullable; kısıt taslak satırları bloklar ve mockup böyle bir doğrulama
göstermiyor (kırmızı hata metni yok). İcat edilmiş kısıt yasağı (`GOREV-SIRASI.md` §3).
**Sınır:** P8 satış akışı geldiğinde **satış fiyatı** `min_sale_price` ile karşılaştırılabilir —
o kural **o dilimin** işidir ve bu sapmayı geçersiz kılmaz.

---

## 12. Test stratejisi

**TDD zorunlu:** önce test, **KIRMIZI GÖR**, sonra kod. Test ilk koşuda yeşilse mutasyon denetimi.
**TEST DB TUZAĞI** (`GOREV-SIRASI.md` §3): her task tek kullanımlık yerel DB açar,
`TEST_DATABASE_URL`'i **komut satırında** verir, `.env`'e **DOKUNMAZ**.

```bash
createdb p31_t1 && \
  TEST_DATABASE_URL="postgresql+asyncpg://furkanilgen@localhost:5432/p31_t1" .venv/bin/pytest
dropdb p31_t1     # basarisizlikta BILE
```

**MIGRATION TUZAĞI aynı derecede bağlayıcıdır** (§10.1): `alembic`'in **her** çağrısı
— `heads` dahil — `DATABASE_URL` override'ı ile koşulur, yoksa **canlıya vurur**:

```bash
DATABASE_URL="postgresql+asyncpg://furkanilgen@localhost:5432/p31_t1" .venv/bin/alembic upgrade <rev>
```

### 12.1 Birim (saf, DB'siz)

1. `_derive_block_code`: `"A Blok"`→`A` · `"C Blok"`→`C` · `"Zemin"`→`ZEMIN` ·
   `"2. Etap A"`→`2-ETAP-A` · `"Şantiye Ğ Blok"`→`SANTIYE-G` · `"Blok"`→ geri düşüş `B1`
2. `_derive_block_code` çakışması: aynı projede ikinci `A` → `A-2`
3. `estimated_unit_count`: `8×3+2 = 26` (BE 90–93 birebir); üç girdi de `None` → `None`
4. Numaralandırma **dört desen**: `block_sequence` → `C-1…C-24` (TU 159–166, **başa sıfır
   YOK** — karar 1); `floor_sequence` → `11,12,13,21,22` (TU 79, **tek hane**);
   `label_sequence` → `Daire 1…`; `block_floor_sequence` → `C11,C12,C13` (TU 79)
5. `floor_sequence` genişliği: `units_per_floor=12` → iki hane (`101…112, 201…`);
   `units_per_floor=3` → tek hane (`11,12,13,21`) — **W = len(str(units_per_floor))**
5b. **Kat etiketi üreteci** (karar 4): `0→"Zemin"`, `3→"3. Kat"`, `-2→"2. Bodrum"`,
   çatı turu → `"Çatı Katı"`; `roof_floor=True` bir tur **daha** üretir (TU 71)
6. `prefix` korunumu: `prefix="D"` + `sequential`-benzeri → `D1…D4` (SY 132–135 regresyonu)
7. Fiyat artışı: TU tablosunun **beş satırı da** doğrulanır (§5.5 tablosu birebir test edilir),
   C-7 satırı **en yakın 100 ₺** yuvarlamasını kanıtlar (karar 6: `1.318.688 → 1.318.700`)
8. Fiyat artışı `None` iken tüm katlar slot tabanını **yuvarlanmadan** alır (karar 6 sınırı)
8b. `total_list_value` **satırlardan** toplanır; mockup'ın `₺27.264.000` sayısı **teste
   KONMAZ** (karar 5, onaylı sapma §11.6)
9. `UnitKindBreakdown.total` beş sayacın toplamı; `office/warehouse/parking` sıfırken
   eski davranış korunur
10. Excel başlık eşleştirmesi: `Oda Tipi` **ve** eski `Tip`; `Sahiplik` **ve** eski `Pay`;
    `"  ODA TİPİ "` normalizasyonu (`İ` tuzağı, mevcut `_LETTER_FOLD` testi genişletilir)
11. `Cephe` sözlüğü **5 değer** (karar 7); tanınmayan değer → satır hatası; `northeast`
    gibi bir değer enum'da **yoktur**
12. `Kat` **metin** (karar 4): `"Zemin"`→`"Zemin"`, `"3. Kat"`→`"3. Kat"`, `3`→`"3"`
    (dönüştürme YOK), 21 karakter → satır hatası
13. `min_sale_price > list_price` **hata DEĞİL** (karar 2 — hiçbir katmanda zorlanmaz)
13b. `vat_rate = 15` → şema hatası; `1/10/20` → geçerli (karar 9)

### 12.2 Entegrasyon — blok

14. `POST …/blocks` — 13 alanın tamamı yazılır ve `GET`'te geri döner
15. `POST` — `code` boş → otomatik üretilir; ikinci blok aynı ada sahipse kod `-2` alır
16. `POST` — `code` elle verilir, projede zaten var → **409** `_DUPLICATE_BLOCK_CODE`
17. `POST` — farklı projede aynı `code` → **201** (benzersizlik proje içi)
18. `PATCH /blocks/{id}` — kısmi güncelleme; gönderilmeyen alan değişmez;
    `notes: null` alanı boşaltır
19. `GET …/blocks` — `estimated_unit_count` türevi doğru; kolonlar `None` iken `None`
20. Negatif sayaç (`floor_count = -1`) → **422** (CHECK'ten önce Pydantic)

### 12.3 Entegrasyon — ünite

21. `POST …/units` — 8 yeni alan yazılır ve döner
22. `POST` — `sales_status` gönderilmezse `listed` doğar (UE 94 `selected`)
23. `POST` — `unit_kind = office/warehouse/parking` → **201** (enum genişlemesi)
24. `POST` — `vat_rate = 15` → **422** `_INVALID_VAT_RATE`; `1/10/20` → **201** (karar 9)
25. `POST` — `floor = "Çatı Katı"` → **201** ve aynen döner; 21 karakter → **422**;
    `floor` gönderilmezse → **201**, `None` (karar 4 + karar 11)
26. `PATCH /units/{id}` — `sales_status` elle `sold`'a çekilir → **200** (kullanıcı kararı 2)
27. `GET …/units?sales_status=sold` süzgeci çalışır; **`totals` süzgeçten etkilenmez**
28. `GET …/units` — `totals.by_sales_status` dört değeri de sayar
29. `UnitResponse.expected_profit` ve `unit_cost` **yer tutucu** (`available=false`,
    `pending_module="project_costs"`)

### 12.4 Entegrasyon — toplu üretim + önizleme

30. `POST …/units/bulk/preview` — TU senaryosunun **tamamı**: 8 kat × 3 slot,
    `block_sequence`, %1,5 artış → `total_units = 24`, `rows[0..6]` mockup TU 159–165
    ile **birebir** (`C-1`…`C-7`, kat, tip, m², cephe, fiyat). `floor` sayısal (1/2/3),
    `floor_label` metin (`"1. Kat"`) — karar 4
30b. `preview` — `roof_floor = True` → **bir tur daha**; son turun `floor_label` değeri
    `"Çatı Katı"` (TU 71)
30c. `preview` — kodu **`NULL`** olan blokta `block_sequence` → `{Blok}` jetonu blok
    adından **anlık** türetilir, blok satırı **güncellenmez** (karar 8, §3.2)
31. `preview` — çakışan numara varsa `conflict = true` ve `conflicting_unit_nos` dolu;
    **HTTP 200** (hata değil, TU 177)
32. `preview` — **hiçbir satır yazılmaz** (öncesi/sonrası ünite sayımı eşit)
33. `preview` — denetim günlüğüne **yazmaz**
34. `POST …/units/bulk` — aynı gövdeyle üretim; sonuç `preview` ile **aynı numaraları ve
    aynı fiyatları** verir (iki yolun tek kaynaktan beslendiğinin kanıtı)
35. `bulk` — çakışma → **409**, hiçbir satır yazılmamış (P3 kararı korunuyor)
36. `bulk` — `slots` boş → eski davranış (alanlar `None`), geriye dönük uyum
37. `bulk` — `len(slots) != units_per_floor` → **422** `_SLOT_COUNT_MISMATCH`
38. `bulk` — slot `sequence` tekrarlı → **422** `_SLOT_SEQUENCE_INVALID`
39. `bulk` — `owner_side` gövdeye konsa bile **yok sayılır**, üretilenler `NULL`
    (P3'ün `test_bulk_never_sets_owner_side_in_kendi_yatirim` testi **korunur**)

### 12.5 Entegrasyon — Excel (kısmi aktarım)

40. `import/validate` — EI senaryosu: 24 satır, 22 geçerli, 1 uyarı, 1 hata →
    `summary` **birebir** (EI 95–98); `rows` 24 satır; hatalı satırın `messages` **iki**
    mesaj taşır (EI 161)
41. `validate` — **hiçbir satır yazılmaz**, denetim yazılmaz
42. `import` — aynı dosya, `include_warnings=True` (varsayılan) → `created = 23`
    (22 geçerli + 1 uyarılı), `skipped = 1` (yalnız hatalı satır)
43. `import` — `include_warnings=False` → `created = 22`, `skipped = 2`
44. `import` — **hatalı satırın ünitesi DB'de YOK**, geçerli satırların ünitesi **VAR**
    (kısmi yazımın asıl kanıtı)
45. `import` — hiç geçerli satır yoksa → **422** `_IMPORT_NOTHING_TO_WRITE`, hiç yazma yok
46. `import` — **aynı dosya ikinci kez** yüklenir → tüm satırlar "bu ünite numarası bu
    blokta zaten kullanılıyor" hatasıyla atlanır, `created = 0` → **422**
    (§6.1'in 2. gerekçesinin testi)
47. `import` — yeni blok adı → blok oluşur, `blocks_created = 1`; hatalı satırların
    bloğu **oluşmaz** (blok oluşturma geçerli satırlara bağlıdır)
47b. `import` — çok şantiyeli projede **`site_id` yok** → **422** `_SITE_REQUIRED`;
    `site_id` verilince → **200** ve yeni bloklar **o şantiyede** açılır (karar 3);
    dosyadaki blok zaten varsa bloğun `site_id`'si **değişmez**
47c. `import` — başka projenin `site_id`'si → **404** (IDOR)
48. `import` — `Maliyet` sütunundaki değer **hiçbir kolona yazılmaz** (DB'de karşılığı yok,
    karar 10)
49. `import` — `Liste Fiyatı < Maliyet` → satır `warning`, mesaj EI 173 biçiminde
50. `import` — eski başlıklı dosya (`Tip`, `Pay`) → **200**, geriye dönük uyum
51. `import` — `.csv` → **422** `_IMPORT_BAD_TYPE`; 2 MB üstü → **422**
52. `import` — dosya **hiçbir yere yazılmaz** (P3 test 32 korunur)
53. `import/template` — `200`, `Content-Type` xlsx, ilk satır **12 başlık**, veri satırı yok
54. `import/template` — denetim yazmaz
55. Denetim: `import` **istek başına TEK** satır; mesaj `skipped` sayısını içerir

### 12.6 IDOR negatif seti — **üç yeni uç için tam tekrar**

P3 §11.4'ün 14 senaryosu **aynen korunur**; yeni uçlar için eklenenler:

| # | Senaryo | Beklenen |
|---|---|---|
| I1 | `POST /projects/{gizli}/units/bulk/preview` | **404** "Proje bulunamadı" (403 değil) |
| I2 | `POST /projects/{gizli}/units/import/validate` | **404** |
| I3 | `GET /projects/{gizli}/units/import/template` | **404** |
| I4 | `preview` gövdesinde **başka projenin** `block_id`'si | **404** "Blok bulunamadı" |
| I5 | `projects` izni `view` iken `preview` / `validate` | **403** (ikisi de `full`) |
| I6 | `projects` izni `view` iken `template` | **200** (§6.2 kararı) |
| I7 | `projects` izni `none` iken üçü de | **403** |
| I8 | Token yok | **401** |

Her negatif senaryoda yanıt gövdesinin **kayıt varlığını sızdırmadığı** ayrıca doğrulanır.

### 12.7 Parity / regresyon

- **Modül sayısı 18'de KALIR** — yeni izin modülü yok. (P5 `contracts` modülünü ekleyip
  sayıyı 17 → **18**'e çıkardı, P7 yeni modül açmadı; matris **18×8 = 144**.)
  `test_seed_matrix.py`, `test_roles_repository.py`, `test_roles_api.py` **dokunulmaz**
  ve yeşil kalır. *Bu spec'in ilk sürümü "17" diyordu — P5/P7 öncesi yazılmıştı.*
- Migration: R1 → R2 → R3 `upgrade → downgrade → upgrade` yerel DB'de yeşil;
  `alembic heads` **tek** head. Testte **açık revizyon id'si** kullanılır, `head`/`-1` **asla**
  (`GOREV-SIRASI.md` §3, iki kez yaşanan tuzak).
- **Tüm takım koşulur** (P3'ün 1020 testi P5+P7 ile **1411**'e çıktı, `GOREV-SIRASI.md` §0.2);
  kırılması **beklenen** olanlar önceden listelenir ve bilerek güncellenir:
  | Test | Neden |
  |---|---|
  | P3 §11.3 **#28** (`import` hep-ya-hiç) | §6.1 dönüşü |
  | `test_units_bulk.py::test_floor_based_numbering` (`101,102,201,202` → `11,12,21,22`) | **karar 1** (§5.2) |
  | `test_units_bulk.py::test_floor_based_numbering_negative_floors` (`-101,-102` → `-11,-12`) | **karar 1** |
  | `test_units_bulk.py::test_floor_based_numbering_pads_to_two_digits` | yeşil kalır ama **yeniden adlandırılır** (§5.2) |
  | `UnitKindBreakdown` şema testleri | §4.3 |
  | `UnitResponse.sales_status` yer tutucu testleri | §4.4 |
  | `sold_units`/`reserved_units`/`available_units` yer tutucu testleri | §8.2 (gerçeğe döner) |
- `openapi.json` üretilir (gitignore'lu), frontend'e kopyalanmaya hazır.
- Kapılar: `.venv/bin/pytest` + `.venv/bin/ruff check` + `.venv/bin/ruff format --check`
  (ruff **0.15.22**).

---

## 13. Kararlar ve kalan açık madde

### 13.1 Karara bağlandı (2026-07-31)

> Revizyon 1'in **13 açık sorusunun tamamı** cevaplandı. Aşağıdaki tablo **bağlayıcıdır**;
> hiçbiri yeniden tartışılmaz. "Kaynak" sütunu kararı verenin kim olduğunu söyler
> (K = kullanıcı, KO = koordinatör).

| # | Soru (rev. 1) | **KARAR** | Kaynak | Spec'te nerede |
|---|---|---|---|---|
| 1 | Çatı katı `units.floor` içinde nasıl kodlanacak? | **Soru düştü** — kat **metin** olarak saklanır (`String(20)`), etiket aynen yazılır ("Zemin", "1. Kat", "Çatı Katı"). Integer + konvansiyon **icat edilmez**; sıralama zaten `units.sort_order` üzerinden. Toplu üretimde çatı turu `roof_floor: bool` ile taşınır | **KO** | §4.2, §5.3 |
| 2 | TU 146/172'deki `₺27.264.000` toplamı tutmuyor | **Mockup hatası** kabul edilir; toplam **satırlardan** hesaplanır, mockup'ın sayısı kanon değildir ve teste konmaz | **KO** | §5.5, §11.6 |
| 3 | Kat artışında yuvarlama | **En yakın 100 ₺** (mockup'ın tek veri noktasıyla uyumlu). `Decimal` + `ROUND_HALF_UP`; artış yokken yuvarlama da yok | **KO** | §5.5 |
| 4 | `unit_facing` 5 mi 8 mi? | **Mockup'taki 5 değerle kalır**; 8'e çıkarılmaz | **KO** | §4.2 |
| 5 | `blocks.code` migration'da doldurulsun mu? | **HAYIR** — canlı blokların koduna dokunan migration **yazılmaz**; `code` boş kalır, **sonraki düzenlemede** üretilir | **KO** | §3.2, §10.4 |
| 6 | `min_sale_price ≤ list_price` zorlanacak mı? | **ZORLANMAZ** — taban fiyat serbest girilir; ne DB, ne servis, ne şema kısıtı | **K** | §4.1, §11.7 |
| 7 | `floor_sequence` genişliği (P3 testini kırıyor) | **Başa sıfır konmaz** — `C-4`, `11`, `12`, `21`. `W = len(str(units_per_floor))`. P3'ün iki haneli üreten kodu ve testi **güncellenir** | **K** | §5.2, §11.5 |
| 8 | `UnitKindBreakdown` ekran etiketleri | **DEĞİŞMEZ** — yeni `unit_kind` değerleri sayaçlara eklenir, mevcut "Daire + Dükkan" etiketleri korunur | **KO** | §4.3 |
| 9 | Excel `Maliyet` sütunu | **Okunur → uyarı üretir → ATILIR.** Maliyet kolonu **açılmaz** (maliyet ileride İş Kalemleri/satınalmadan gelecek) | **KO** | §6.4, §6.5 |
| 10 | `vat_rate` değer kümesi | **Yalnız `{1, 10, 20}`** — KDV listesi kodda sabit (mevcut kalıcı karar 9) | **KO** | §4.2 |
| 11 | `import/template` ucu + EI 61 "Hedef Şantiye" | **İkisi de bu dilimde.** Şablon ucu açılır; **Hedef Şantiye seçimi EKLENİR** (`site_id`, opsiyonel) — çok şantiyeli projede bugün 422 veren yol açılır, yeni bloklar seçilen şantiyeye açılır | **K** | §6.2, §6.7 |
| 12 | `*` taşıyan yeni alanlar `Create`'te zorunlu mu? | **HİÇBİRİ ZORUNLU DEĞİL.** `*` yalnız UI ipucudur | **KO** | §7.1 |
| 13 | Ertelenen iki formun sekmesi | **Hiç basılmaz** — "yakında" etiketi de yok; şerit dört sekmeyle çıkar | **KO** | §11.4 |

### 13.2 Kalan tek açık madde

**`{Blok}` jetonu, `code`'u `NULL` olan canlı blokta neye çözülecek?**
Karar 5 ("backfill yok") bu boşluğu bırakıyor. Spec'in önerisi (§3.2): **üretim anında
`_derive_block_code(block.name)` çağrılır, sonuç saklanmaz** — çağrılan **aynı saf
fonksiyon** olduğu için ikinci otorite doğmaz ve blok bir kez düzenlenince çıktı birebir
aynı kalır. Alternatif (`422 "Önce blok kodunu belirleyin"`) kullanıcıyı canlı blokta
toplu üretimden kilitler. **Onay yeterlidir; uygulamayı bloke etmiyor** — T8/T9 önerilen
davranışla yazılır, aksi söylenirse tek fonksiyon değişir.

> *Aşağıdaki rev. 1 metni kayıt olarak bırakılmıştır — hangi sorunun neyle kapandığı
> §13.1'den okunur. Uygulama ajanı §13.1'i esas alır.*

<details>
<summary>Revizyon 1'in açık soru metni (arşiv)</summary>

1. **Çatı katı `units.floor` içinde nasıl kodlanacak?** (UE 66, TU 71)
   `Zemin = 0`, bodrum negatif, normal kat pozitif net; **çatı katının** tam sayı karşılığı
   yok. Seçenekler: (a) `floor = floor_count + 1` sözleşmesi (basit, ama `roof_type = none`
   olan blokta anlamsız kat üretir ve "en üst normal kat" ile karışır), (b) ayrı bir
   `floor_kind` enum sütunu (kesin, ama iki otorite ve şemayı büyütür), (c) çatı katı
   ünitelerinin `floor`'unu `None` bırakmak (kayıp bilgi). **Öneri: (a)**, ama karar sizin.
2. **TU 146/172'deki `₺27.264.000` toplamı mockup'ın kendi verisiyle tutmuyor**
   (artışsız 27.680.000, %1,5 bileşik artışla ≈29.177.000). Sunucu toplamı satırlardan
   hesaplayacak — mockup'taki sayı hedeflenmeyecek, **doğru mu?**
3. **Kat artışında yuvarlama**: mockup'ın tek yuvarlama örneği (TU 165, `1.318.688 → 1.318.700`)
   **en yakın 100 ₺**'ye işaret ediyor. (a) en yakın 100 ₺, (b) kuruşa (`ROUND_HALF_UP`, 2 hane),
   (c) en yakın 1.000 ₺. **Öneri: (a)**, ama tek veri noktası.
4. **`unit_facing` enum'u 5 değerle mi kalsın?** Mockup'ta yalnız Güney · Güney-Batı · Doğu ·
   Kuzey · Batı var. Pusulanın kalan 3 yönü (Kuzey-Doğu, Kuzey-Batı, Güney-Doğu) eklensin mi?
   **Öneri: mockup'taki 5 ile başla** (icat yasağı), ihtiyaç doğunca additive ekle.
5. **`blocks.code` mevcut canlı bloklar için migration'da doldurulsun mu?**
   (a) doldur (tek otorite, `block_sequence` deseni canlı bloklarda hemen çalışır),
   (b) `NULL` bırak + servis geri düşüşü. **Öneri: (a).**
6. **`min_sale_price ≤ list_price` kuralı** hiçbir yerde zorlanmıyor (§4.1). Mockup böyle
   bir kural söylemiyor. **Zorlanmasın, doğru mu?**
7. **`floor_sequence` genişliği** P3'te sabit 2 (`101,102,201`), mockup 1 hane (`11,12,21`).
   Öneri: `W = len(str(units_per_floor))`. Bu **mevcut bir P3 testini kırar** (§12.7).
   **Onaylıyor musunuz?**
8. **`UnitKindBreakdown` genişlemesi**: `office`/`warehouse`/`parking` sayaçları eklenince
   KY 71 / KK 72 / SY 74'ün "Daire + Dükkan" etiketi **değişmemeli** (yeni sayaçlar sıfırsa
   görünmez). Bu frontend bağlayıcılığı **kabul mü?**
9. **Excel `Maliyet` sütunu yalnız uyarı için okunsun, saklanmasın** (§6.4/§6.5). Alternatif:
   sütunu hiç okuma → o zaman EI 173'teki uyarı **hiç üretilemez** ve mockup'ın uyarı
   kategorisi anlamsızlaşır. **Öneri: oku-uyar-at.**
10. **`vat_rate` değer kümesi**: yalnız `{1, 10, 20}` mi (UE 93 + Kalıcı Karar 9), yoksa
    `0..100` serbest mi? **Öneri: `{1,10,20}` (şema düzeyinde), sütun serbest `Numeric(5,2)`.**
11. **`GET …/units/import/template` ucu bu dilimde mi açılsın?** (EI 37/87'de iki kez
    görünüyor, EI 54 akışın ilk adımı olarak tarif ediyor.) Ayrıca EI 61'deki **"Hedef Şantiye"**
    seçicisi: dosyada şantiye sütunu **yok**; seçici yalnız blok çözümlemesini mi süzecek,
    yoksa yeni blokların `site_id`'sini mi belirleyecek? **Öneri: gövdeye opsiyonel `site_id`
    alanı ekle**, P3 §4.5 kuralı bu değerle çalışsın (çok şantiyeli projede içe aktarma
    bugün 422 alıyor — bu ucu kullanılamaz kılıyor).
12. **Mockup'ta `*` taşıyan yeni alanlar Pydantic `Create` şemasında zorunlu olsun mu?**
    (`blocks.floor_count` BE 79, `units.floor` UE 66). Zorunlu yaparsak **mevcut testler ve
    Excel içe aktarma** (dosyada `Kat` boş bırakılabiliyor, EI 85'te `*` yok) kırılır.
    **Öneri: `units.floor` opsiyonel kalsın** (Excel ile tutarlı), `blocks.floor_count`
    opsiyonel kalsın (taslak). Yani **hiçbiri zorunlu değil**, `*` yalnız UI ipucu.
13. **`Form - Bolum Ekle` ve `Form - Paylasim Girisi` kapsam dışı** (kullanıcı kararı 5) —
    bu iki formun sekmeleri (BE 52, UE 54, TU 52, EI 50) ekranda **görünmeye devam edecek**
    ama tıklanınca ne olacak? (a) sekme gizlenir, (b) sekme durur, "yakında" durumu basılır.
    Frontend dilimini ilgilendiriyor ama karar burada verilmeli.

</details>

---

## 14. Task listesi

> **Revizyon 2 notu:** kararlar task **sayısını değiştirmedi** ama iki task'ın içeriğini
> genişletti (**T8** ünite numarası dönüşünü de kapsıyor, **T11/T12** `site_id`'yi de).
> Karar 1'in kırdığı P3 testi için **ayrı task açılmadı**: değişiklik `bulk.py`'nin tek
> sabitinde ve aynı dosyanın testlerinde; T8 zaten `bulk.py`'yi yeniden yazıyor ve iki
> ajan aynı dosyaya dokunmamalı.

| Task | Ne yapılacak | Bağımlı |
|---|---|---|
| **T0** | Bu spec → **kullanıcı onayı** (§13.1 kararları işlendi; §13.2'nin tek maddesi onay bekliyor, uygulamayı bloke etmiyor); sonra plan yaz → **onay** | — |
| **T1** | `alembic heads` doğrulaması (**`DATABASE_URL` override'ı ile**, §10.1) + **R1** (`unit_kind` enum takası, izole) + `UnitKind` modeli. upgrade→downgrade→upgrade **yerel** DB'de yeşil | T0 |
| **T2** | **R2** (7 yeni enum tipi, izole) + enum sınıfları (`BlockRoofType`, `BlockGroundUsage`, `BlockParkingType`, `BlockStatus`, `UnitFacing`, `UnitParkingRight`, `UnitSalesStatus`) | T1 |
| **T3** | **R3** — `blocks` +13 kolon +1 UNIQUE +6 CHECK, `units` +8 kolon **+4 CHECK** (`floor` **metin**, `ck_units_floor` yok — karar 4); `models.py` güncellemesi; **`sales_status` P8 geçiş notu docstring'e** (§4.4). **Veri migration'ı YOK** (karar 5) | T2 |
| **T4** | `_derive_block_code` saf fonksiyonu + birim testleri (§12.1/1-2) + benzersizlik korkuluğu `ensure_block_code_unique` + **kodu `NULL` blokta anlık türetme** (§3.2, §13.2) | T3 |
| **T5** | Blok şemaları (`BlockCreate/Update/Response` +13 alan + `estimated_unit_count` türevi) + blok yazma/okuma uçlarının genişlemesi + Türkçe mesajlar | T4 |
| **T6** | Ünite şemaları (`UnitCreate/Update/Response` +8 alan + `expected_profit` yer tutucusu; `sales_status` **gerçek** değere dönüşür) + `UnitKindBreakdown` genişlemesi | T3 |
| **T7** | Ünite okuma yolu: `totals.by_sales_status`, `sold/reserved/available` sayaçlarının yer tutucudan **gerçeğe** dönüşü, `floor` ve `sales_status` süzgeçleri (§8.2) | T6 |
| **T8** | `bulk.py` yeniden yazımı: 4 numaralandırma deseni + **başa sıfır dolgusunun kaldırılması** (karar 1: `_FLOOR_SEQUENCE_WIDTH` sabiti + yorumu silinir, `W = len(str(units_per_floor))`, **iki P3 testi bilerek güncellenir** — §5.2 tablosu) + **kat etiketi üreteci ve `roof_floor` turu** (karar 4, §5.3) + slot şablonu + kat fiyat artışı **en yakın 100 ₺** yuvarlamayla (karar 6) — hepsi saf/DB'siz + §12.1/4-8b birim testleri | T6 |
| **T9** | **`POST …/units/bulk/preview` YENİ UCU** (§5.4) + `UnitBulkPreview` şemaları + çakışma işaretlemesi; denetim **yazmaz** | T8 |
| **T10** | `POST …/units/bulk` genişlemesi (slot + artış) + hep-ya-hiç çakışma kararının **korunduğunun** testi + `preview` ile birebir aynı çıktı testi | T9 |
| **T11** | `importer.py` genişlemesi: 12 sütun, 2 başlık yeniden adlandırma + eşanlamlılar, `Kat` (**metin, dönüştürme yok** — karar 4) / `Cephe` / `Maliyet` (**oku-uyar-at**, karar 9) çözümlemesi, yeni satır kuralları (§6.4/§6.5) | T6 |
| **T12** | **Kısmi aktarım** (§6.1): `batch.import_units` yeniden yazımı, `UnitImportSummary`/`RowReport`/`Result` şemaları, `include_warnings`, **`site_id` hedef şantiye alanı** (karar 11, §6.2), `_IMPORT_NOTHING_TO_WRITE`; `UnitImportError`/`UnitImportRowError` temizliği | T11 |
| **T13** | **`POST …/units/import/validate` YENİ UCU** (§6.2) — `site_id` alanı burada da var; denetim yazmaz; `import` ile tek kaynaktan beslendiğinin testi | T12 |
| **T14** | **`GET …/units/import/template` YENİ UCU** (§6.7) — 12 başlık, veri satırı yok, `view` izni | T11 |
| **T15** | Denetim günlüğü: `units_imported` imza değişimi (§9) + üç yeni ucun **yazmadığının** testi | T10, T13, T14 |
| **T16** | **IDOR negatif setinin tamamı** (§12.6) + P3'ün 14 senaryosunun regresyonu | T9, T13, T14 |
| **T17** | Regresyon: kırılması beklenen **7 test grubunun** bilinçli güncellenmesi (§12.7) + **modül sayısının 18'de kaldığının** doğrulanması + tam kapı koşusu (`pytest` + `ruff check .` + `ruff format --check .` — **kapı tüm repodur**, `app tests` ile sınırlamak `alembic/` dizinini kaçırır ve CI'da kırmızıya düşer) + `openapi.json` üretimi | T1–T16 |

**T0–T17 = 18 task** (revizyon 2'de sayı değişmedi). T0 spec/plan task'ı sayılmazsa
uygulama tarafında **17 task**.

Sonra: PR → CI → merge → **deploy** (`railway up --detach` ile **elle** — otomatik deploy
2026-07-30'dan beri çalışmıyor) → canlı `/openapi.json` içeriğine bakılarak doğrulama
(**merge ≠ deploy**, `GOREV-SIRASI.md` §0). **Canlı DB'ye migration elle koşulmaz** —
P7'de bu, canlı crash döngüsüne yol açtı (§10.1).
