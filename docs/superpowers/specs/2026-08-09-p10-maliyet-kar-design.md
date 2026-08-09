# P10 — Maliyet/Kâr (backend spec)

Tarih: 2026-08-09 · Durum: **ONAYLANDI (2026-08-09)** — §7'nin BEŞ sorusu da önerildiği gibi onaylandı:
S1 harcanan = approved+paid (ödenen/bekleyen ayrı) · S2 BRÜT (`gross_total`) · S3 bütçe bazlı m²
dağıtımı, m²'sizde `None` · S4 gelir = ünite liste fiyatları toplamı (`sales_target` çeliştirilmez) ·
S5 E1 "Ortalama Marj" dokunulmaz, pending.
Mockup: `Proje - Kendi Yatırım.dc.html` (**KY**) · `Proje - Kat Karşılığı.dc.html` (**KK**) ·
`Ekran 4 - Projeler.dc.html` (**E4**) · `Form - Daire Satisi.dc.html` (**DS**) · `Form - Unite Ekle.dc.html` (**UE** 98).

## 1. Kapsam ve ana gerçek

Mockup taraması (2026-08-09, satır numaralı envanter): **hiçbir mockup'ta maliyet GİRİŞ yüzeyi yok** —
8 ekranın 7'si %100 salt gösterim; tek giriş DS'de ve orada da maliyet girilmez, türetilir (DS 90:
"Satış bedeli − ünite maliyeti"). Yazılı tek kaynak ifadesi: KY 205 "taşeron … **inşaat maliyetinin ana
kalemi**" + KK 208 "taşeron çalışır, hakediş kesilir".

**Sonuç: P10 bir TÜREV OKUMA dilimidir.** Yeni tablo YOK, **migration YOK** (bekleniyor), yeni izin
modülü YOK, elle maliyet girişi AÇILMAZ (form mockup'ı yok — icat yasağı). Bütçe tarafı ZATEN var:
`projects.budget` + 4 kalem (material/labor/subcontractor/overhead, P1) · `project_investment.land_cost` ·
`sites.budget` · `sections.budget_amount`. P10 bunların karşısına **gerçekleşeni ve kâr türevlerini** koyar.

## 2. Maliyet tanımları (türev; §7 S1-S2'ye bağlı)

- **İnşaat maliyeti (gerçekleşen)** = taşeron hakedişlerinden: `harcanan` = approved+paid BRÜT toplam ·
  `ödenen` = paid · `bekleyen` = approved (KY 212-249 tablo sütunları: Sözleşme/Ödenen/Bekleyen birebir).
- **Arsa maliyeti** = kendi yatırımda `project_investment.land_cost` (KY 118-122); kat karşılığında
  **tanım gereği 0** (KK 104-106 "Arsa Maliyeti ₺0 — Kat karşılığı ✓"; ProjectLandShare kararıyla tutarlı).
- **Ruhsat & Harçlar · Finansman · Pazarlama** (KY 134-154): kaynak modül yok (muhasebe/fatura/kredi) →
  **pending** (`pending_module` doğru anahtarlarla; uydurma 0 basılmaz).
- **Ünite maliyeti** (DS 62, UE 98) = m² dağıtımı: proje **toplam bütçe maliyeti** (bütçe kalemleri +
  arsa) × ünite brüt m² / proje toplam brüt m². Bütçe bazlı — gerçekleşen bazlı olsaydı inşaat sürerken
  saçma düşük çıkardı. m²'siz ünite/projede `None` (uydurma değer yok).
- **Kâr türevleri** (proje tipine göre — E4 kart alan setleri farklı, E4 75/82/89):
  - Kendi yatırım: tahmini kâr = ünite liste fiyatları toplamı − toplam bütçe maliyeti (KY 168-188:
    48,2 − 29,8 = 18,4 ✓); marj = kâr / satış toplamı (%38,2 ✓).
  - Kat karşılığı: kâr = kendi pay (contractor) ünite değer toplamı − inşaat bütçesi (KK 121-141:
    30,4 − 17,6 = 12,8 ✓; marj %42,1 = 12,8/30,4 ✓). Arsa maliyeti 0 kuralı hesaba gömülü.
  - Taahhüt: kâr = sözleşme bedeli − harcanan (E4 180-181 yalnız "Sözleşme Bedeli / Harcanan" basar;
    tahmini kâr KARTTA YOK — alan yalnız iç türev olarak döner).
- **Satıştan kâr** (DS 90-91) = satış bedeli − ünite maliyeti; marj = kâr / satış bedeli.

## 3. Uçlar / değişen yüzey

| Yüzey | Değişiklik |
|---|---|
| **YENİ** `GET /projects/{id}/costs` | KY "Maliyet Kırılımı" kartı (113-161) + kâr projeksiyonu (168-194) + taşeron maliyet tablosu (212-249, mevcut sözleşme+hakediş verisinden). İzin `projects:view`, IDOR `visible_projects` |
| Proje kartları/listesi | `construction_cost` · `estimated_profit` · `margin` · `our_share_value` yer tutucuları GERÇEK değere bağlanır |
| `units` yanıtları | `unit_cost` · `expected_profit` gerçek (UE 98 "Beklenen Kâr" = liste fiyatı − ünite maliyeti) |
| `sales` yanıtları | "Bu Satıştan Kâr" + marj gerçek (`COST_MODULE` yer tutucuları) |
| Gösterge paneli | "Ortalama Marj" (E1 246-250) — tanımsız dipnotsuz metrik; §7 S5 |

**Zarf kuralı (KIRICILIK YOK):** yer tutucular `MetricPlaceholder` zarfı İÇİNDE gerçeğe döner —
`available=true` + `value` dolar, `pending_module` null olur (PT `CountPlaceholder` emsali). Alan tipi
DEĞİŞMEZ çünkü bu kez tüketen UI CANLIDA (E4 proje kartları). Bu, ROADMAP'teki "MetricPlaceholder
çelişkili sözleşme" borcunu da kapatır: `available=true` iken `pending_module` artık taşınmaz.

## 4. Performans sınırı

Liste uçlarında (E4 kartları) türevler proje başına sabit sorguyla (GROUP BY toplamları) hesaplanır —
N+1 yasak, test ölçümle (TB3 sayaç emsali). `costs` ucu tek proje olduğu için serbest ama yine tek
gidiş-dönüş hedeflenir.

## 5. Kapsam dışı / pending (icat yasağı)

- Elle maliyet/kategori girişi AÇILMAZ (form mockup'ı yok; ihtiyaç doğarsa mockup istenir, ayrı dilim).
- Ruhsat/Finansman/Pazarlama kalemleri + KY 103-104 "Nakit Durumu" + tahsilat entegrasyonu → pending.
- Şantiye "Brüt Kar Marjı"na DOKUNULMAZ (F-TH `computeGrossMargin` istemcide, çalışıyor).
- Başabaş noktası (KY 193) türev metin — frontend işi, backend alan açmaz.
- E1 portföy "Bütçe ₺28M" kıyası (203) — dashboard dilimi kapsamına girmedi, pending kalır.

## 6. Test odakları

Hesap doğrulukları mockup sayılarıyla birebir senaryolu (KY 18,4/38,2 · KK 12,8/42,1 · DS 460K/31,9) ·
tip-bazlı alan setleri · taşeron durum süzgeci (draft/submitted/rejected maliyete GİRMEZ) · m²'siz
ünite `None` · IDOR · N+1 ölçümü · zarf sözleşmesi (`available=true` ⇒ `pending_module=null`).

## 7. AÇIK SORULAR (kullanıcı cevabı ŞART)

- **S1 — "Harcanan" tanımı:** öneri: taşeron hakedişlerinde **approved+paid BRÜT** toplam = harcanan;
  `ödenen`=paid, `bekleyen`=approved ayrıca döner (KY tablosu birebir). Alternatif: yalnız paid.
- **S2 — Brüt mü net mi:** öneri: **BRÜT** (`gross_total`) — teminat/avans kesintileri ödeme
  zamanlamasıdır, iş maliyetini değiştirmez. Alternatif: net ödenecek.
- **S3 — Ünite maliyeti dağıtım kuralı:** öneri: **bütçe bazlı m² oranı** (§2). Mockup kural yazmıyor —
  bu bir iş kuralı icadıdır, onayın şart. Alternatif: gerçekleşen bazlı ya da tamamen pending bırakmak.
- **S4 — Kendi yatırım satış hedefi kaynağı:** öneri: kâr hesabında **ünite liste fiyatları toplamı**
  (KY 168 "52 ünite · ort ₺927K" üniteden türev); `sales_target` kolonu yalnız kendi alanında dönmeye
  devam eder, hesapla ÇELİŞTİRİLMEZ.
- **S5 — E1 "Ortalama Marj":** tanımsız (dipnot yok). Öneri: BU dilimde dokunulmaz, pending kalır;
  tanım netleşince dashboard mini işi. Alternatif: proje marjlarının basit ortalaması (icat).
