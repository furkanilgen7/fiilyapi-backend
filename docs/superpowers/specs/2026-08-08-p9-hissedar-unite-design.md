# P9 — Hissedar-Ünite (backend spec)

Tarih: 2026-08-08 · Durum: **ONAYLANDI (2026-08-08)** — §7'nin BEŞ sorusu da önerildiği gibi onaylandı:
S1 `ShareholderInput.id` kimlik korur + atanmış hissedar silmeye 409 · S2 yer tutucu KALKAR
(`shareholder_id`+`shareholder_name`) · S3 Excel dışa aktarım BU dilimde · S4 teslim takibi tamamı
pending/türev · S5 Otomatik Dağıt istemci + PDF ayrı dilim.
Mockup: `Kat Karşılığı - Paylaşım.dc.html` (**KKP**) · `Form - Paylasim Girisi.dc.html` (**PG**)
Bağlam: P3 kararı (GOREV-SIRASI §0.3 madde 7): "`Form - Paylasim Girisi` → P5 oranı + **P9 hissedarları**".
`units/models.py:229`: "İleri bağ AÇILMAZ (spec §1.3): `shareholder_id` … P9'un işi."

## 1. Kapsam

Kat karşılığı projede ünite ↔ hissedar bağı: `units.shareholder_id` kolonu + mevcut paylaşım
ucunun (`PATCH /projects/{id}/units/allocation`) hissedar taşıması + okuma yüzeyindeki
`shareholder` yer tutucusunun gerçeğe bağlanması. **Yeni tablo YOK, yeni izin modülü YOK**
(`projects` — allocation zaten orada). Dilim küçüktür; asıl riski §4.1'deki kimlik-korunum tuzağıdır.

## 2. Mevcut altyapı (P3/P3.1/P8'den — DEĞİŞMEZ)

- `units.owner_side` nullable enum (`contractor`/`landowner`) + atomik toplu atama ucu
  `PATCH /projects/{id}/units/allocation` (`owner_side=None` atamayı kaldırır; IDOR-8; tek denetim satırı).
- `land_share_shareholder` (id · project_id CASCADE · name · share_pct) — proje oluştur/güncelle
  gövdesindeki `shareholders: list[ShareholderInput]` ile yazılır.
- KKP 56-71 özet + 159-170 tfoot toplamları **P3'te yapıldı** (`_side_summary`, atanmamış = `side=None`).
- KKP 91 "Hissedar / Alıcı" sütununun **alıcı yarısı** P8 T5'te gerçek (`buyer_name`); **hissedar
  yarısı** yer tutucu (`shareholder=_metric(_SHAREHOLDER_UNITS)`).
- Proje kartındaki hissedar sayısı/listesi zaten gerçek (`shareholder_count`, `shareholders`).

## 3. Şema değişikliği (tek migration)

`units.shareholder_id` — UUID FK → `land_share_shareholder.id`, **nullable**, `ondelete=SET NULL`.
SET NULL yalnız proje silme kaskadının DB emniyetidir (kaskat sırası deterministik değil; RESTRICT
proje silmeyi rastgele kırardı). Uygulama katmanındaki asıl koruma §4.1'dedir.
İndeks: `ix_units_shareholder_id`. Enum yok. Downgrade: kolon + indeks düşer.

## 4. Kurallar

### 4.1 ⚠️ KİMLİK KORUNUMU (dilimin ana tuzağı)
`projects/service.py:325` bugün hissedar listesini **komple silip yeniden açıyor**
(`delete-orphan`). FK açıldıktan sonra bu davranış, sıradan bir proje PATCH'inde TÜM ünite
atamalarını sessizce süpürür (SET NULL). Çözüm — PL "opsiyonel id kimlik korur" emsali:
- `ShareholderInput.id` **opsiyonel** olur. id eşleşirse satır YERİNDE güncellenir (name/share_pct);
  id'siz girdi yeni satırdır; listede olmayan mevcut satır silinir.
- **Atanmış ünitesi olan hissedar listeden çıkarılırsa 409** (görünür Türkçe gerekçe; sessiz
  süpürme yok — WORKFLOW §3 ruhu). Önce üniteleri boşalt, sonra hissedarı sil.
- Geriye uyum: id'siz eski istekler eskisi gibi çalışır (ancak atanmış hissedar varken 409'a düşer —
  bu bilinçlidir ve testlidir).

### 4.2 Atama kuralları (PG'den)
- `shareholder_id` yalnız `owner_side=landowner` iken anlamlı (PG 221: select yalnız ARSA satırında;
  PG 190: BİZ satırı "Yüklenici payı" basar). `contractor`/`None` tarafla birlikte gönderilirse **422**.
- `owner_side` `contractor`a dönerse veya `None` olursa `shareholder_id` **birlikte temizlenir**
  (ayrı istek beklenmez; atomik uç, yarım durum bırakmaz). Davranış dokümante + testli.
- Hissedar **başka projenin** hissedarıysa: atomik reddin parçası, hiçbir satır yazılmaz —
  görünmezlik deseni gereği var-olmayanla aynı yanıt (**404**, IDOR-8 ile tutarlı).
- Hissedar ataması ARSA tarafında **zorunlu DEĞİL** (KKP 119: BİZ ünitesinde "—"; PG akışı atamayı
  kademeli yapar). `landowner + shareholder_id=None` geçerlidir.
- Proje tipi kapısı: mevcut allocation ucunun tip davranışı NE İSE o korunur; hissedar taşıyan
  istek yalnız `kat_karsiligi`de anlamlıdır (hissedar satırı zaten yalnız o tipte var olabilir).

### 4.3 Okuma yüzeyi
- `UnitResponse.shareholder` yer tutucusu **kalkar**; yerine `shareholder_id: UUID | None` +
  `shareholder_name: str | None` (P8 `sale_price`/`buyer_name` emsali — yer tutucu bitince alan
  gerçeğe döner). N+1 yok: hissedar adları tek JOIN/tek ek sorgudan.
- KKP 91 birleşimi frontend'in işi: ARSA → `shareholder_name`, BİZ → `buyer_name`.
- KKP 110 "(hissedar)" eki, PG 97 "%50" ekleri: görüntü türevi, backend ek alan taşımaz
  (`share_pct` zaten hissedar satırında).

## 5. Uçlar (değişen yüzey)

| Uç | Değişiklik |
|---|---|
| `PATCH /projects/{id}/units/allocation` | `UnitAllocationItem` + `shareholder_id: UUID \| None` (item'da alan yoksa `None` sayılır — mevcut atomik DEĞİŞTİRME sözleşmesi korunur) |
| `POST/PATCH /projects` (gövde) | `ShareholderInput.id` opsiyonel (§4.1) + 409 koruması |
| `GET /projects/{id}/units` (+tekil yanıtlar) | `shareholder_id`/`shareholder_name` gerçek (§4.3) |
| (§7 S3 onaylıysa) `GET /projects/{id}/units/export.xlsx` | KKP 24 "Excel" — paylaşım tablosunun dışa aktarımı (timesheet/BOQ openpyxl deseni; sütunlar KKP 86-92) |

Audit: allocation zaten tek dönem-özeti satırı yazar — hissedar sayısı o özete eklenir; yeni
`AuditAction` AÇILMAZ (TB3 T3 emsali).

## 6. Kapsam dışı / pending (icat yasağı)

- **Teslim takibi kartı (KKP 174-200):** milestone tablosu İCAT EDİLMEZ. Kartın verisinin
  mevcut karşılıkları: `delivery_date` (KKP 168/187), `daily_penalty` (KKP 197). Kat irtifakı
  tarihi · inşaat ilerlemesi · tapu devir durumu → **pending** (kaynak yok).
- **"Otomatik Dağıt %55/%45" (PG 101):** istemci hesabı + mevcut allocation ucu; backend ucu YOK.
- **Paylaşım tutanağı PDF (PG 270-273):** pending, ayrı dilim (PDF altyapısı yok).
- **Değer dengesi / "sözleşme gereği 23-19" (PG 243-267, KKP denge metinleri):** türev —
  gerekli girdiler (oranlar, taraf toplamları, rayiç toplamları) yanıtlarda ZATEN var; backend
  yeni alan açmaz, doğrulamaz (P3 kararı: "sapma DOĞRULANMAZ, yalnızca raporlanır").
- Hissedar CRUD'u ayrı uca AÇILMAZ — proje gövdesindeki liste tek giriş noktası kalır.

## 7. AÇIK SORULAR (kullanıcı cevabı ŞART)

- **S1 — Kimlik korunumu + 409 (§4.1):** öneri: `ShareholderInput.id` opsiyonel + atanmış
  hissedarı silmeye 409. Alternatif (önerilmez): SET NULL ile sessiz boşaltma.
- **S2 — Yer tutucu alanın kalkması (§4.3):** `shareholder` MetricPlaceholder'ı kaldırıp
  `shareholder_id`+`shareholder_name` koymak şema açısından kırıcıdır; ancak KKP ekranı frontend'de
  HENÜZ YOK (F-P3 sırada), tüketen UI yok — pratik risk sıfır, F-P3 `gen:api` ile alır. Öneri: kaldır.
- **S3 — Excel dışa aktarım (KKP 24):** öneri: BU dilimde açılır (küçük; openpyxl deseni hazır).
  Alternatif: F-P3'e kadar beklet, pending basılır.
- **S4 — Teslim takibi (§6):** öneri: tamamı pending/türev, backend'e hiçbir şey açılmaz.
- **S5 — Otomatik Dağıt + PDF (§6):** öneri: ikisi de backend dışı (istemci hesabı / ayrı dilim).
