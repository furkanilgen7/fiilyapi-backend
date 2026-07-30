# Alt-Proje 2 · P4 — İş Kalemleri (BOQ) (tasarım)

Tarih: 2026-07-29
Kapsam: Alt-Proje 2'nin dördüncü dilimi — şantiye düzeyinde BOQ (poz grupları + poz kalemleri)
Mockup kanonu: `projedesign/Ekran 13 - İş Kalemleri.dc.html`
Bağlı spec: `2026-07-27-alt-proje-2-p2-santiye-bolum-design.md` (sites/sections çekirdeği, desen kanonu)
Bağlı desen: `2026-07-25-backend-b6-gosterge-paneli-design.md` §2.3 (yer tutucu sözleşmesi)
Migration ebeveyni: `e2b3c4d5f6a7` (P1.1a proje formu — mevcut head)

---

## 1. Alt-Proje 2 dilim listesi (P3–P11, resmîleştirme)

Dilim listesinin tam metni repoda yoktu; P1 spec §1 ipuçları + mockup envanteri +
mevcut modül durumundan aşağıdaki liste türetildi. **P3 ve P8'in numara/kapsam
eşleşmesi BELİRSİZDİR** (repoda kanonik kaynak yok) — kullanıcı onayına sunulur.

| # | Ad | Mockup dosyaları | Backend modül/tablolar | Önkoşul | Durum |
|---|---|---|---|---|---|
| P1 | Proje çekirdeği + tipler | `Ekran 4 - Projeler.dc.html` | `projects`, `project_investment`, `project_land_share`, `land_share_shareholder` | — | BİTTİ |
| P1.1 | Proje formu (yeni form mockup'ları) | `Form - Proje Oluştur.dc.html` | `projects` genişletme (P1.1a: status enum + form alanları) | P2 | backend B2 bitti; frontend paralel sürüyor |
| P2 | Şantiye & Bölüm | `Proje Detay - Şantiyeler.dc.html`, `Şantiye Detay.dc.html` | `sites`, `sections`, `sites` izin modülü | P1 | BİTTİ |
| P3 | Proje tip-detay ekranları + ortak `units` tablosu | `Proje - Kendi Yatırım.dc.html`, `Proje - Kat Karşılığı.dc.html` | `units` (ortak ünite tablosu), tip-detay uçları | P1 | bekliyor · numara BELİRSİZ |
| **P4** | **İş Kalemleri (BOQ)** | `Ekran 13 - İş Kalemleri.dc.html` | `boq_groups`, `boq_items` | P2 | **BU SPEC** |
| P5 | İşveren sözleşmesi + poz dağılımı | `Sözleşmeler.dc.html`, `Ekran 14 - Sözleşme Detay.dc.html`, `İşveren Sözleşme - Poz Dağılımı.dc.html`, `Form - Sözleşme Oluştur.dc.html`, `Form - Isveren Ekle.dc.html` | `contracts` (+ BOQ→sözleşme bağı, §2.1 not) | P4 | bekliyor |
| P6 | Bölüm Detay | `Bölüm Detay.dc.html` | `sections` detay uçları + BOQ-bölüm bağı (`boq_items.section_id`, §9) | P2, P4 | bekliyor |
| P7 | İşveren hakedişi | `Ekran 15 - İşveren Hakedişi.dc.html`, `İşveren Hakediş Oluştur.dc.html`, `Şantiye - Hakedişler.dc.html`, `Şantiye - Hakediş Özeti.dc.html` | `progress_payments` (gerçek veri) | P4, P5 | bekliyor |
| P8 | Ünite satışı / satış yönetimi | `Satış Yönetimi.dc.html`, `Form - Daire Satisi.dc.html` | `units` satış uçları | P3 | bekliyor · numara BELİRSİZ |
| P9 | Hissedar-ünite dağılımı | `Kat Karşılığı - Paylaşım.dc.html` | `land_share_shareholder` × `units` bağı | P3 | bekliyor |
| P10 | Maliyet / kâr | (Ekran 4 kartlarındaki türev alanlar; ayrı mockup yok — BELİRSİZ) | `project_costs` | P4, P7 | bekliyor |
| P11 | Proje takvimi (Gantt) | `Proje Takvimi.dc.html`, `Şantiye - Planlama.dc.html` | takvim/milestone tabloları | P2 (P4 önerilir) | bekliyor |

Sahipsiz iş: `company_assets` (`Şirket Varlıkları.dc.html`) — ana spec §10.2;
herhangi bir dilime bağlanmadı, ayrı dilim olarak kullanıcıya sorulacak.

## 2. Amaç ve kapsam

P4, şantiye altına poz (BOQ) katmanını kurar:

- `boq_groups` — mockup'taki grup başlık satırları ("1. TOPRAK VE TEMEL İŞLERİ"),
- `boq_items` — poz satırları (Poz No, tarif, birim, miktar, birim fiyat),
- liste + oluşturma + güncelleme uçları ve Excel dışa aktarımı,
- GENEL TOPLAM'ın gerçek hesaplanması; hakediş türevi alanların yer tutucusu.

**Yazılmayan:** sözleşme bağı (P5), bölüm bağı (P6), gerçekleşme yüzdesi (P7),
revizyon/ek iş kaydı (§8 soru 3), silme uçları (P1/P2 deseni), frontend (ayrı spec).

### 2.1 Bağlanma noktası — mockup'tan bilinçli sapma (kullanıcıya sorulacak)

Mockup breadcrumb'ı BOQ'yu bir **sözleşmeye** bağlar:
`Ekran 13` satır 62: `← Sözleşmeler · Güneşkent A-Blok / SZL-2025-001`.
Ancak `contracts` modülü henüz yok (P5). Öneri: BOQ **şantiyeye** (`site_id`)
bağlanır; P5 geldiğinde `boq_items`/`boq_groups`'a nullable `contract_id`
additive eklenir (kırıcı değil). Bu, sessiz atlama değil **açık sapmadır** —
§8 açık soru 1.

## 3. Veri modeli

### 3.1 `boq_groups`

Mockup kaynağı: grup başlık satırları — `Ekran 13` satır 107–108 ("1. TOPRAK VE
TEMEL İŞLERİ"), 129–130 ("2. BETONARME İŞLERİ"), 151–152 ("3. DUVAR VE KAPLAMA
İŞLERİ").

| Sütun | Tip | Not |
|---|---|---|
| `id` | UUID PK | |
| `site_id` | UUID FK → `sites.id` (ON DELETE CASCADE), index `ix_boq_groups_site_id` | §2.1 |
| `name` | text, NOT NULL | "TOPRAK VE TEMEL İŞLERİ" — baştaki "1." numarası SAKLANMAZ; sıra numarası `sort_order`'dan türetilir (frontend basar) |
| `sort_order` | integer, NOT NULL, default 0 | mockup'taki grup sırası |
| `created_at` / `updated_at` | timestamptz | mevcut model deseni |

Grup adı benzersizliği zorlanmaz (mockup'ta böyle bir kural görünmüyor).

### 3.2 `boq_items`

Mockup kaynağı: tablo sütunları — `Ekran 13` satır 96 (Poz No), 97 (İş Kalemi
Tarifi), 98 (Birim), 99 (Miktar), 100 (Birim Fiyat), 101 (Tutar), 102 (Gerç. %);
örnek satır 111–117 (01.001 · Kazı (Makine ile) · m³ · 1.240 · 280 · 347.200 · %100).

| Sütun | Tip | Mockup kaynağı + not |
|---|---|---|
| `id` | UUID PK | |
| `site_id` | UUID FK → `sites.id` (ON DELETE CASCADE), index | §2.1; benzersizlik kapsamı için gerekli |
| `group_id` | UUID FK → `boq_groups.id` (ON DELETE CASCADE), index | mockup'ta her kalem bir grubun altında (satır 107–171) |
| `code` | text, NOT NULL | "Poz No" satır 96; örnek "01.001" (satır 111). Format zorlanmaz (§8 soru 5), benzersizlik: `uq_boq_items_site_code (site_id, code)` |
| `description` | text, NOT NULL | "İş Kalemi Tarifi" satır 97; "Kazı (Makine ile)" satır 112 |
| `unit` | text, NOT NULL | "Birim" satır 98; m³ (113), Ton (144), m² (157). Serbest metin — enum dondurulamaz (§8 soru 4) |
| `quantity` | numeric(14,3), NOT NULL, CHECK `> 0` (`ck_boq_items_quantity_positive`) | "Miktar" satır 99; 1.240 (satır 114, binlik ayraç). Metraj ondalıklı olabilir → 3 hane |
| `unit_price` | numeric(18,2), NOT NULL, CHECK `>= 0` (`ck_boq_items_unit_price_nonneg`) | "Birim Fiyat" satır 100; 280 (satır 115) |
| `sort_order` | integer, NOT NULL, default 0 | grup içi satır sırası |
| `created_at` / `updated_at` | timestamptz | |

**Saklanmayan (türev/yer tutucu):**

| Mockup alanı | Kaynak satır | Karar |
|---|---|---|
| Tutar | 101, 116 | türev: `quantity × unit_price`, yanıtta hesaplanır, sütun açılmaz |
| Gerç. % (satır rozeti) | 102, 117/139/161/170 | hakediş türevi → yer tutucu `pending_module: "progress_payments"` |
| GENEL TOPLAM | 175–176 (12.399.900) | türev: tüm tutarların toplamı — **gerçek** döner |
| GENEL TOPLAM %'si | 177 (%75) | hakediş türevi → yer tutucu `progress_payments` |
| Kart: Toplam Sözleşme ₺11,2M | 74–75 | sözleşme bedeli, BOQ toplamı DEĞİL (11,2M ≠ 12.399.900) → yer tutucu `contracts` |
| Kart: Gerçekleşen ₺8,4M | 78–79 | yer tutucu `progress_payments` |
| Kart: Kalan İş ₺2,8M | 82–83 | yer tutucu `progress_payments` |
| Kart: Revize / Ek İş ₺340K | 86–87 | revizyon kavramı bu dilimde modellenmiyor → yer tutucu `contracts` (zeyilname P5 işi) — §8 soru 3 |

### 3.3 Değişmezler (invariants)

1. `boq_items.group_id`'nin gösterdiği grubun `site_id`'si, kalemin `site_id`'si
   ile aynı olmalı. DB'de bileşik FK **açılmaz** (P1 §3.5 gerekçesi: yazma yolu
   tekil, servis korkuluğu yeter). İhlal → 422 `BoqGroupSiteMismatchError`.
2. `(site_id, code)` benzersiz — DB `uq_boq_items_site_code`, servis 409'a çevirir.
3. `quantity > 0`, `unit_price >= 0` — Pydantic ilk hat, DB CHECK son hat.
4. Grup/kalem taşıma (başka şantiyeye) yok: PATCH şemasında `site_id` alanı yok.
   `group_id` PATCH ile değiştirilebilir (aynı şantiyenin başka grubuna) — 1. kural
   burada da kontrol edilir.

## 4. İzin modeli — **yeni `boq` modülü AÇILIR** (kullanıcı kararı, 2026-07-30)

> **KARAR — aşağıdaki "yeni modül açılmaz" önerisi GEÇERSİZDİR.**
> Kullanıcı: "şantiye şefi görsün de saha mühendisi görmesin". Mevcut matriste
> `sites` satırı `site_chief` ve `field_engineer` için **birebir aynı** (`_LIM`,
> `_LIM` — `projects` satırının aynısı, `seed_data.py` MATRIX). Dolayısıyla
> `sites` izniyle kapı tutulursa bu iki rol ayrılamaz. İstenen ayrım ancak
> **ayrı izin modülü** ile mümkündür.
>
> - Yeni modül anahtarı: **`boq`** (İş Kalemleri) — matrisin 17. satırı.
> - Satır: `system_admin=_A`, `patron=_F`, **`site_chief=_LIM`**,
>   **`field_engineer=_N`**, `hr_manager=_N`, `accounting=_FIN`,
>   `project_manager=_F`, `procurement=_N`.
>   (`accounting`/`project_manager` seviyeleri `projects` satırından türetildi —
>   uygulamadan önce kullanıcıya teyit edilecek.)
> - Okuma uçları `boq:view`, yazma uçları `boq:full` (§5 tablosundaki
>   `sites:view`/`sites:full` bu kararla **değişti**).
> - **Mockup sapması, bilinçli ve kaçınılmaz:** `Ayarlar - İzin Matrisi`
>   mockup'ında `boq` satırı YOK. Ayrım mockup'ta hiç tanımlı olmadığı için
>   mockup'a sadık kalmak istenen davranışı imkânsız kılıyordu. Sapma burada
>   kayıt altındadır; "mockup'ta yok" diye geri alınmaz.
> - **Plan etkisi:** T1'in "`modules`/`role_permissions`'a DOKUNMA" tuzağı
>   T1 için geçerli kalır, ama **T4 kapsamı büyür**: modül satırı migration'ı +
>   `seed_data.py` MATRIX güncellemesi + seed parity testlerinin yeni sayıya
>   göre güncellenmesi + frontend İzin Matrisi ekranının görsel baseline'ının
>   Linux CI'da yenilenmesi.

### 4.1 Geçersiz kılınan özgün öneri (tarihçe için saklanır)

BOQ ekranına sidebar'dan bağımsız girilmez; şantiye/sözleşme bağlamının iç
kırılımıdır (mockup breadcrumb şantiye+sözleşme altından gelir). P2'nin "bölüm
ayrı izin modülü değildir" gerekçesi aynen geçerli: ayrı `boq` modülü, matrisi
17. satıra çıkarır ve `Ayarlar - İzin Matrisi` mockup'ında karşılığı yoktur.

- Okuma uçları: `require_permission("sites", AccessLevel.view)`
- Yazma uçları: `require_permission("sites", AccessLevel.full)`
- `seed_data.py` DEĞİŞMEZ; izin satırları sabit kalır; seed parity testleri dokunulmaz.

**Dikkat — mali veri sızıntısı:** `sites=_LIM` taşıyan Şantiye Şefi/Saha
Mühendisi birim fiyatları görür. Bu kabul edilebilir mi? §8 açık soru 2.
(Yer tutucu anahtarı `boq` olarak KALIR — B6 sözleşmesindeki anahtar, izin
modülü değil kavram anahtarıdır; `units`/`contracts`/`project_costs` de matriste
olmadan anahtar olarak kullanılıyor.)

## 5. Uçlar

Tümü proje görünürlük süzgecinden geçer (P2 §5.2 deseni:
`app/modules/projects` süzgeci; görünmeyen şantiye → **404**, 403 değil).

| Yöntem | Yol | İzin | İş |
|---|---|---|---|
| GET | `/sites/{site_id}/boq` | `boq:view` | gruplar + kalemler + toplamlar |
| POST | `/sites/{site_id}/boq/groups` | `boq:full` | grup oluştur (201) |
| PATCH | `/boq/groups/{group_id}` | `boq:full` | grup güncelle (`name`, `sort_order`) |
| POST | `/sites/{site_id}/boq/items` | `boq:full` | "+ İş Kalemi" (satır 67) (201) |
| PATCH | `/boq/items/{item_id}` | `boq:full` | kalem güncelle |
| GET | `/sites/{site_id}/boq/export` | `boq:view` | "Excel İndir" (satır 66) — xlsx |

**Silme ucu yok** — P1/P2 gerekçesi (silme kuralı ana spec §10'da tek seferde).
BOQ'da yanlış giriş ihtiyacı gerçek olduğundan §8 soru 6 olarak kullanıcıya sorulur.

### 5.1 `GET /sites/{site_id}/boq` yanıtı

```jsonc
{
  "totals": {
    "contract_total":  { "available": false, "value": null, "pending_module": "contracts" },          // satır 74-75
    "realized_total":  { "available": false, "value": null, "pending_module": "progress_payments" },  // satır 78-79
    "remaining_total": { "available": false, "value": null, "pending_module": "progress_payments" },  // satır 82-83
    "revision_total":  { "available": false, "value": null, "pending_module": "contracts" },          // satır 86-87
    "grand_total": "12399900.00",                                                                     // GERÇEK — satır 175-176
    "grand_progress_pct": { "available": false, "value": null, "pending_module": "progress_payments" } // satır 177
  },
  "groups": [
    {
      "id": "…", "name": "TOPRAK VE TEMEL İŞLERİ", "sort_order": 1,
      "group_total": "471900.00",                    // türev: grup kalemlerinin tutar toplamı
      "items": [
        {
          "id": "…", "code": "01.001",
          "description": "Kazı (Makine ile)",
          "unit": "m³",
          "quantity": "1240.000",
          "unit_price": "280.00",
          "amount": "347200.00",                     // türev, saklanmaz
          "progress_pct": { "available": false, "value": null, "pending_module": "progress_payments" },
          "sort_order": 1
        }
      ]
    }
  ]
}
```

Sıralama: gruplar `sort_order, created_at`; kalemler grup içinde `sort_order, code`.
Boş BOQ hata değildir: `groups: []`, `grand_total: "0.00"`.

### 5.2 Yazma gövdeleri

`POST …/boq/groups`: `{ name (zorunlu), sort_order? }`
`POST …/boq/items`: `{ group_id (zorunlu), code, description, unit, quantity, unit_price, sort_order? }`
`PATCH /boq/groups/{id}`: hepsi isteğe bağlı (`name`, `sort_order`)
`PATCH /boq/items/{id}`: hepsi isteğe bağlı; `site_id` yok (§3.3/4); `group_id`
verilirse aynı şantiye kontrolü.

Yazma uçları B5 denetim kaydı yazar (`record_audit`, `create`/`update`;
`app/modules/audit/messages.py`'a Türkçe BOQ mesajları eklenir). Okumalar yazmaz.

### 5.3 Excel dışa aktarımı

Sütun başlıkları mockup tablo başlıklarıyla **birebir** (satır 96–102):
`Poz No · İş Kalemi Tarifi · Birim · Miktar · Birim Fiyat · Tutar · Gerç. %`.
Grup başlık satırları ("1. TOPRAK VE TEMEL İŞLERİ") ve GENEL TOPLAM satırı basılır.
**Gerç. % sütunu başlıkta durur, hücreleri boş kalır** (zarif düşüş — veri P7'de;
sessiz atlama değil, burada kayıt altında). Kitaplık: `openpyxl` (bağımlılık zaten
varsa yenisi eklenmez — plan task'ında doğrulanır). Dosya adı:
`is-kalemleri-{site.code}.xlsx`.
`Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`.

### 5.4 Hatalar (Türkçe mesajlar)

| Durum | Yanıt |
|---|---|
| Oturum yok / geçersiz token | 401 |
| `sites` izni eşiğin altında | 403 "Bu işlem için yetkiniz yok" |
| Şantiye yok / görünür değil | 404 "Şantiye bulunamadı" |
| Grup yok / görünür şantiyede değil | 404 "İş kalemi grubu bulunamadı" |
| Kalem yok / görünür şantiyede değil | 404 "İş kalemi bulunamadı" |
| `group_id` başka şantiyenin grubu | 422 "Grup bu şantiyeye ait değil" (`BoqGroupSiteMismatchError`) |
| `(site_id, code)` çakışması | 409 "Bu poz numarası bu şantiyede zaten kullanılıyor" |
| `quantity <= 0` / `unit_price < 0` | 422 (Pydantic; DB CHECK son hat) |

### 5.5 Yetki/kapsam korkulukları (P2 IDOR dersi)

En riskli uçlar kimliği **yukarı çözümleyenlerdir**:
`PATCH /boq/items/{id}` → item→site→project, `PATCH /boq/groups/{id}` →
group→site→project. Her ikisi proje görünürlük süzgecinden geçirilir; görünmeyen
kayıt **404** döner. Negatif testler zorunlu (plan T6). Ayrıca
`POST …/boq/items` gövdesindeki `group_id` ile yol parametresi `site_id`
arasındaki uyuşmazlık ikinci IDOR vektörüdür (başka şantiyenin grubuna kalem
enjeksiyonu) — 422/404 testi zorunlu.

## 6. Migration

Tek migration: `p4_is_kalemleri_boq`, `down_revision = "e2b3c4d5f6a7"` (P1.1a head).

1. `boq_groups` + `ix_boq_groups_site_id`
2. `boq_items` + `ix_boq_items_site_id` + `ix_boq_items_group_id` +
   `uq_boq_items_site_code` + 2 CHECK
3. Modül/izin satırı YOK (§4) — `modules`/`role_permissions` dokunulmaz.

Tamamen additive; veri göçü yok; downgrade iki tabloyu düşürür (önce items).
Seed BOQ verisi yazılmaz (ana spec §7 — sahte veri yok). Lokal DB'de
upgrade→downgrade→upgrade doğrulanır; canlıya karşı **asla**.

## 7. Testler (asgari küme; ayrıntı planda)

Model/kısıt: unique (aynı şantiye aynı poz → IntegrityError; farklı şantiye aynı
poz → geçerli), CHECK'ler, cascade zinciri (site→group→item). Servis: tutar/grup
toplamı/genel toplam hesabı (Decimal, yuvarlama `quantize(0.01)`), boş BOQ,
yer tutucular. Yetki: 401; `sites:view` yok → 403 (6 uç); görünmeyen şantiye/grup/
kalem → 404 (IDOR, §5.5); `view` var `full` yok → yazma 403. İş kuralı: grup-şantiye
uyuşmazlığı 422, poz çakışması 409. Export: başlık satırı birebir, grup satırları,
GENEL TOPLAM, Gerç. % hücreleri boş. Denetim: create/update kayıtları.

## 8. Açık sorular (uygulamadan önce kullanıcıya)

1. ~~**Bağlanma noktası**~~ → **KARARA BAĞLANDI (kullanıcı, 2026-07-30).**
   BOQ **hiçbir şeye bağlanmayacak** — `contract_id` bu dilimde YOK, eklenmesi
   için P5'i beklemek de gerekmiyor: kullanıcı "her şeyi doğru kendi yerine
   bağlarız, **bütün proje bittikten sonra** bağlanır" dedi. Yani sözleşme,
   bölüm ve hakediş bağları **proje sonunda tek seferde** kurulacak; bu dilimde
   hiçbir ileri bağ (`contract_id`, `section_id`) açılmaz ve bunlara zemin
   hazırlamak için şema esnetilmez. `site_id` bağı KALIR — BOQ'nun bir ebeveyni
   olmadan tablo havada kalır ve mockup breadcrumb'ı da şantiye bağlamından
   geliyor. `Toplam Sözleşme` ve `Revize / Ek İş` kartları yer tutucu kalır (§3.2).
2. **Birim fiyat görünürlüğü:** `sites=_LIM` taşıyan Şantiye Şefi / Saha
   Mühendisi BOQ birim fiyatlarını görecek (ayrı izin modülü açılmıyor).
   Kabul mü, yoksa ayrı `boq` izin modülü mü istersin?
3. **Revize / Ek İş kartı (satır 86–87):** bu dilimde `contracts` yer tutucusu
   olarak mı kalsın (zeyilname P5 işi), yoksa kalem düzeyinde bir
   "orijinal/revize/ek iş" alanı şimdi mi açılsın? Öneri: yer tutucu.
4. **Birim alanı:** serbest metin mi (öneri), sabit liste mi?
5. **Poz No formatı:** "01.001" deseni zorlansın mı? Öneri: serbest, yalnız
   şantiye içi benzersizlik.
6. **Silme:** P1/P2 deseniyle silme ucu yok. BOQ'da yanlış girişin tek çaresi
   PATCH olur; hakediş bağı gelmeden silme aslında güvenli — bu dilimde
   `sites:admin` ile DELETE açılsın mı? Öneri: açılmasın (desen korunur).
7. **"+ İş Kalemi" formu:** Ekran 13'te form/modal mockup'ı yok
   (`Formlar.dc.html` taranmadı — BELİRSİZ). Form alanları tablo sütunlarından
   türetildi (§5.2); ayrı form mockup'ı varsa uygulamadan önce o kanon alınır.
8. **P3/P8 dilim numaraları** (§1): önerilen eşleme onaylanıyor mu?

## 9. Kapsam dışı / sonraki dilimlere notlar

- `boq_items.section_id` (bölüm bağı) bu dilimde YOK — Ekran 13'te bölüm sütunu
  yok; P6 (Bölüm Detay) mockup'ı kanon alınarak nullable FK additive eklenir.
  Bu yüzden P2 yanıtındaki `boq_item_count`/`budget` yer tutucuları bu dilimde
  `available: true`'ya DÖNMEZ (bölüm-kalem eşlemesi olmadan hesaplanamaz) —
  dürüstlük notu.
- Gerç. % gerçek verisi (P7), sözleşme bağı + revize/ek iş (P5), taşeron poz
  dağılımı (Faz 2), frontend Ekran 13 (ayrı spec, frontend reposunda).
