# Alt-Proje 2 · P2 — Şantiye & Bölüm (tasarım)

Tarih: 2026-07-27
Kapsam: Alt-Proje 2'nin ikinci dilimi — `sites` + `sections` çekirdeği
Mockup kanonu: `projedesign/Proje Detay - Şantiyeler.dc.html`, `projedesign/Şantiye Detay.dc.html`
Bağlı spec: `2026-07-26-alt-proje-2-p1-proje-cekirdegi-design.md` (proje çekirdeği)
Bağlı desen: `2026-07-25-backend-b6-gosterge-paneli-design.md` §2.3 (yer tutucu sözleşmesi)
Onaylı kararlar: bellek notu `alt-proje-2-p2-kararlari` (2026-07-27, kullanıcı)

---

## 1. Amaç ve kapsam

P1 proje çekirdeğini kurdu. P2 onun altına **iki katman** ekler:

```
Proje  (P1) ─┬─ Şantiye (P2) ─┬─ Bölüm (P2)
             │                └─ Bölüm
             └─ Şantiye       └─ (bölümsüz de olabilir)
```

Bu dilimde yazılan:

- `sites` tablosu — proje altındaki şantiye kaydı,
- `sections` tablosu — şantiye altındaki bölüm kaydı (**isteğe bağlı katman**, §2.4),
- `sites` ve `sections` için CRUD uçları (liste + detay + oluştur + güncelle),
- yeni `sites` izin modülü (16. modül) ve 8 rol için izin satırı,
- `GET /projects/{id}` yanıtına şantiye sayacı eklenmesi.

**Bu dilimde yazılmayan:** BOQ/pozlar, sözleşmeler, hakediş, puantaj, stok, günlük
kayıt, belgeler, milestone. Şantiye ekranındaki bu alanlar `available: false` +
`pending_module` ile döner (§3).

### 1.1 Mockup ikiliği — hangi dosya kanon

`projedesign/` altında iki farklı şantiye detay mockup'ı var:

| Dosya | Durum |
|---|---|
| `Ekran 6 - Şantiye Detay.dc.html` | **ESKİ — kanon DEĞİL.** İçerik alanı "Son Günlük Kayıtlar" + "Yaklaşan Milestone'lar" iki sütunu; bölüm kavramı yok, 220px sidebar. |
| `Şantiye Detay.dc.html` | **KANON.** Bölümler ızgarası + 6 sekme + 260px drill-in sidebar. |

Ana spec §10.3 zaten "eski `Ekran 6 - Şantiye Detay` tek ekran varsayımı artık
geçerli değil" diyor. Uygulama `Şantiye Detay.dc.html`'i izler; `Ekran 6` yalnız
tarihsel referanstır ve görsel karşılaştırmada kullanılmaz.

---

## 2. Veri modeli

### 2.1 `sites` (şantiye)

| Sütun | Tip | Not |
|---|---|---|
| `id` | UUID PK | |
| `project_id` | UUID FK → `projects.id` (ON DELETE CASCADE), index | |
| `code` | text, NOT NULL | proje içinde benzersiz — `uq_sites_project_code (project_id, code)` |
| `name` | text, NOT NULL | "A-Blok Şantiyesi" |
| `status` | enum `site_status`, NOT NULL, default `active` | `active` · `on_hold` · `completed` |
| `address` | text, null | "Kuyubaşı Mah." |
| `city` | text, null | "Ankara" — boşsa projeninki gösterilir (§4.3) |
| `site_manager_name` | text, null | "Sercan Öztürk" — **serbest metin**, §2.1.1 |
| `start_date` | date, null | |
| `end_date` | date, null | |
| `delivery_date` | date, null | tamamlanmış şantiyede "Teslim: Mayıs 2026" |
| `created_at` / `updated_at` | timestamptz | |

### 2.1.1 Şantiye şefi — bu dilimde serbest metin (kullanıcı kararı 2026-07-28)

`Form - Proje Oluştur.dc.html` satır 140 şantiye şefini **`<select>`** olarak
gösteriyor (Sercan Öztürk / Kadir Yıldız / Murat Arslan). Yani nihai hedef bir
seçim listesidir.

Ama kullanıcı kararı: *"şef işi şimdi kalsın, sonra select'e bağlarsın."*
**Bu dilimde bağlanmaz.** `site_manager_name` düz metin sütunu olarak kalır;
yanıtta `"site_manager_name": "Sercan Öztürk" | null` döner.

Ertelenmesinin gerekçesi: seçim listesinin doğru kaynağı **Personel** modülüdür,
o modül henüz yok. Şimdi `users.id`'ye FK açmak, Personel geldiğinde ikinci bir
göçe zorlar — ve şantiye şefi çoğu zaman sistem kullanıcısı değildir (taşeron
tarafı, dışarıdan atanan şef).

**Sonraki dilime not (takip işi):** Personel modülü yazıldığında bu alan nullable
bir FK'ya dönecek ve UI'da select olacak. Metin sütunu o göçte veri kaynağı olarak
kullanılır (ad eşleştirmesi), sonra düşürülür. Alan bugün de nullable olduğu için
geçiş kırıcı değildir.

**`contract_amount` sütunu YOK.** Karar 3 gereği işveren sözleşmesi proje
düzeyindedir; şantiyeye pay biçilmesi BOQ dağıtımının türevidir. Şantiyeye elle
bir sözleşme bedeli sütunu açmak, eski projede kaldırılan hatanın tekrarı olur
(bkz. bellek `santiye-merkezli-sozlesme` — `sites.contract_amount` migration 0023
ile düşürülmüştü). Mockup'taki "Toplam Hakediş ₺8,4M / ₺11,2M" paydası bu dilimde
yer tutucudur.

### 2.2 `sections` (bölüm)

| Sütun | Tip | Not |
|---|---|---|
| `id` | UUID PK | |
| `site_id` | UUID FK → `sites.id` (ON DELETE CASCADE), index | |
| `code` | text, null | şantiye içinde benzersiz kısmi indeks (`WHERE code IS NOT NULL`) |
| `name` | text, NOT NULL | "Kat 6–10 Kaba İnşaat" |
| `status` | enum `section_status`, NOT NULL, default `planned` | `planned` · `active` · `completed` |
| `manager_name` | text, null | boşsa mockup "Atanmadı" yazar (frontend işi) |
| `start_date` | date, null | |
| `end_date` | date, null | |
| `sort_order` | integer, NOT NULL, default 0 | kart sıralaması — mockup kronolojik |
| `created_at` / `updated_at` | timestamptz | |

**`budget` / `Bölüm Bedeli` sütunu YOK.** Mockup'ta "Bölüm Bedeli ₺3,52M" ve
"Tahmini Bedel ₺1,96M" iki ayrı etiket taşıyor (tamamlanan/aktif vs planlanan).
Bu değer bölümün BOQ kalemlerinin toplamıdır — türev. P4 (iş kalemleri) gelene
kadar yer tutucu döner (§3).

### 2.3 Enum'lar

```
site_status     : active | on_hold | completed
section_status  : planned | active | completed
```

`site_status`, `project_status` ile aynı üçlüdür ama **ayrı enum**'dur — şantiye
ve proje durum kümeleri ileride ayrışabilir (ör. şantiyeye `suspended` gelebilir);
paylaşılan enum bunu engeller.

`section_status` varsayılanı `planned`'dır (`active` değil) — mockup'ta 5 bölümün
2'si "Planlandı"; yeni bölüm kural olarak planlanmış doğar.

### 2.4 Bölüm isteğe bağlıdır (Karar 4)

Şantiye **sıfır bölümle geçerlidir**. Otomatik "Genel" bölümü açılmaz.

Sonuçları:
- `sections` üzerinde "her şantiyenin en az bir bölümü olmalı" kısıtı **yok**.
- Sonraki dilimlerde günlük kayıt/hakediş satırları `section_id`'yi **nullable**
  taşıyacak (bu dilimde o tablolar yazılmıyor; kural burada kayıt altına alınıyor).
- `GET /sites/{id}` bölüm listesi boş dizi döner; frontend boş durum gösterir.

---

## 3. Dürüstlük — B6/P1 deseni

`MetricPlaceholder` / `CountPlaceholder` şemaları P1'de zaten var
(`app/modules/projects/schemas.py`); P2 bunları yeniden kullanır, kopyalamaz.

### 3.1 `Proje Detay - Şantiyeler` ekranı

**Gerçek:**

| Alan | Kaynak |
|---|---|
| Şantiye adı | `sites.name` |
| "Kuyubaşı Mah. · Şantiye Şefi: S. Öztürk" | `sites.address`, `site_manager.full_name` (§2.1.1) |
| Durum rozeti (Aktif / Tamamlandı) | `sites.status` |
| "Teslim · Mayıs 2026" | `sites.delivery_date` |
| Kalan Gün | `sites.end_date` − bugün (Europe/Istanbul, §4.2) |
| "Şantiyeler (2)" başlık sayacı | `sites` satır sayısı |
| Üst şerit: proje adı, kategori·şehir, işveren | P1 `projects` alanları |

**Yer tutucu:**

| Alan | `pending_module` |
|---|---|
| Kart: İşçi (48) | `timesheet` |
| Kart: İlerleme (%75) + ilerleme çubuğu | `progress_payments` |
| Üst şerit: Toplam Sözleşme ₺22,4M | `contracts` |
| Alt KPI: Toplam Hakediş | `progress_payments` |
| Alt KPI: Toplam Taşeron | `subcontracts` |
| Alt KPI: Aktif İşçi | `timesheet` |
| Alt KPI: Ortalama Marj | `project_costs` |

### 3.2 `Şantiye Detay` ekranı

**Gerçek:** şantiye adı, adres·şehir, şantiye şefi, tarih aralığı, durum, üst
satırdaki proje adı + işveren adı, Kalan Gün, **Bölüm Sayısı** (+ "3 aktif ·
2 bekliyor" kırılımı — `sections.status` sayımı), bölüm kartlarının adı/durumu/
tarihi/sorumlusu.

**Yer tutucu:** Fiziksel İlerleme (`progress_payments`), Aktif İşçi
(`timesheet`), Toplam Hakediş + paydası (`progress_payments`), bölüm kartındaki
İlerleme (`progress_payments`), İş Kalemleri "16 / 26" (`boq`), Bölüm Bedeli
(`boq`), İşçi (zirve) (`timesheet`).

**Modül anahtarları:** `progress_payments`, `timesheet`, `boq`, `contracts`,
`subcontracts`, `project_costs`, `stock`, `documents`, `site_diary`. Bunlar
**modül anahtarıdır**, kullanıcı metni değil (B6 §2.3); Türkçe kopya frontend'in
işidir.

### 3.3 "3 gecikme riski" basılmaz

Mockup'ta aktif bölüm kartında "3 gecikme riski" yazıyor. Bu, iş kalemi düzeyinde
plan-gerçekleşme kıyası gerektirir (P4+). Bu dilimde ne gerçek değer ne yer tutucu
üretilir — alan **hiç dönmez**, frontend satırı basmaz. Yer tutucu göstermek
"hesaplanabilir ama modül yok" demektir; burada durum "hesabın girdisi yok".

---

## 4. Uçlar

Tümü `require_permission("sites", ...)` ile korunur ve **proje görünürlük
süzgecinden** geçer (§5).

| Yöntem | Yol | İzin | Yanıt |
|---|---|---|---|
| GET | `/projects/{project_id}/sites` | `sites:view` | `SiteListResponse` |
| POST | `/projects/{project_id}/sites` | `sites:full` | `SiteDetailResponse` (201) |
| GET | `/sites/{site_id}` | `sites:view` | `SiteDetailResponse` |
| PATCH | `/sites/{site_id}` | `sites:full` | `SiteDetailResponse` |
| GET | `/sites/{site_id}/sections` | `sites:view` | `SectionListResponse` |
| POST | `/sites/{site_id}/sections` | `sites:full` | `SectionResponse` (201) |
| PATCH | `/sections/{section_id}` | `sites:full` | `SectionResponse` |

**Silme ucu yok** — P1 ile aynı gerekçe; silme kuralı (kesinleşmiş kayıt / taslak
ayrımı) ana spec §10'da tanımlı ve ilgili dilimde tek seferde uygulanacak.

**Bölüm ayrı izin modülü değil.** Bölüm şantiyenin iç kırılımıdır; ayrı bir
`sections` modülü izin matrisini 17 satıra çıkarır ve kullanıcıya "şantiyeyi
görüp bölümü görememe" gibi anlamsız bir kombinasyon sunar. `sites` izni ikisini
de kapsar.

### 4.1 Yanıt zarfları

`GET /projects/{id}/sites` — P1'in `{counts, items}` zarfıyla tutarlı:

```jsonc
{
  "counts": { "all": 2, "active": 1, "on_hold": 0, "completed": 1 },
  "items": [ /* SiteCard */ ],
  "totals": {                         // alt KPI şeridi — tümü yer tutucu
    "total_progress_payment": { "available": false, "pending_module": "progress_payments" },
    "subcontractor_count":    { "available": false, "pending_module": "subcontracts" },
    "active_worker_count":    { "available": false, "pending_module": "timesheet" },
    "average_margin":         { "available": false, "pending_module": "project_costs" }
  }
}
```

`SiteCard`:

```jsonc
{
  "id": "…", "code": "A-BLOK", "name": "A-Blok Şantiyesi",
  "status": "active",
  "address": "Kuyubaşı Mah.", "city": "Ankara", "city_inherited": false,
  "site_manager": { "id": "…", "full_name": "Sercan Öztürk" },   // atanmamışsa null
  "start_date": "2025-03-01", "end_date": "2026-12-31",
  "delivery_date": null,
  "remaining_days": 157,                                     // completed ise null
  "section_count": 5,
  "worker_count":  { "available": false, "pending_module": "timesheet" },
  "progress_pct":  { "available": false, "pending_module": "progress_payments" }
}
```

`SiteDetailResponse` = `SiteCard` + `project` özeti (`id`, `name`, `city`,
`employer_name`) + `section_status_counts` (`{planned, active, completed}`) +
`sections: [SectionResponse]` + şantiye düzeyi yer tutucuları
(`total_progress_payment`, `contract_amount`).

`SectionResponse`:

```jsonc
{
  "id": "…", "code": null, "name": "Kat 6–10 Kaba İnşaat",
  "status": "active", "manager_name": "Sercan Öztürk",
  "start_date": "2026-01-01", "end_date": "2026-09-30",
  "sort_order": 2,
  "progress_pct":   { "available": false, "pending_module": "progress_payments" },
  "boq_item_count": { "available": false, "pending_module": "boq" },
  "budget":         { "available": false, "pending_module": "boq" },
  "worker_count":   { "available": false, "pending_module": "timesheet" }
}
```

### 4.2 `remaining_days` hesabı

`end_date` − bugün, **Europe/Istanbul** günü üzerinden (`app/core/timezone.py`),
tam gün farkı. Kurallar:

- `end_date` yoksa → `null`
- `status == completed` → `null` (mockup o kartta "Teslim · Mayıs 2026" gösterir)
- Geçmişte kalmışsa → **negatif değer döner**, kırpılmaz. Gecikmeyi kırmızı
  göstermek frontend'in işidir; backend gerçeği bastırmaz.

### 4.3 `city` devralma

`sites.city` boşsa yanıtta **projenin şehri** doldurulur ve `city_inherited: true`
bayrağı eklenir. Böylece frontend "Kuyubaşı Mah. Ankara" satırını her zaman
basabilir, `null` dallanması taşımaz.

---

## 5. Yetki ve görünürlük

### 5.1 Yeni izin modülü — `sites`

`app/modules/roles/seed_data.py` `MODULES` listesine 16. satır:

```python
{"key": "sites", "name": "Şantiyeler", "group": ModuleGroup.GENEL, "sort_order": 4}
```

`projects` `sort_order: 3` olduğundan `sites` hemen ardına gelir; migration'da
`sort_order: 4`'ün boş olduğu doğrulanır, çakışırsa sonrakiler kaydırılır.

8 rol için izin satırı (`projects` satırıyla aynı profil, tek fark: Proje Müdürü
şantiye/bölüm açabilmeli):

| Rol | `projects` | `sites` (öneri) | Gerekçe |
|---|---|---|---|
| Sistem Yöneticisi | `_A` | `_A` | |
| Patron | `_F` | `_F` | |
| Proje Müdürü | `_LIM` | `_F` | şantiye/bölüm açar |
| Şantiye Şefi | `_LIM` | `_LIM` | görür, düzenleyemez |
| Saha Mühendisi | `_LIM` | `_LIM` | |
| Muhasebe | `_FIN` | `_FIN` | |
| Satınalma | `_F` | `_LIM` | şantiye tanımlamaz |
| Taşeron | `_N` | `_N` | |

> **Satınalma istisnası (kullanıcı onayı 2026-07-28):** `projects=_N` iken
> `sites=_LIM` bilinçli istisnadır — Satınalma projeyi görmez ama şantiyeleri
> görüntüleyebilir (yazamaz). Tutarsızlık gibi görünse de kasıtlıdır, geri
> düzeltilmemelidir.

> Bu satır **öneridir**; `Ayarlar - İzin Matrisi` mockup'ında `sites` sütunu yok.
> Uygulamadan önce kullanıcıya doğrulatılır (§8, açık soru 1).

Toplam: 8 rol × 16 modül = **128** izin satırı. `roles` testlerindeki sabit modül
sayısı 15 → 16 güncellenir (P1'de 14 → 15 yapılmıştı, aynı yer).

### 5.2 Proje görünürlük süzgeci

`sites` uçları **kendi görünürlük mantığını yazmaz**; P1'in
`app/modules/projects/service.py::_visible_projects` süzgecini yeniden kullanır.
Kural: kullanıcı projeyi göremiyorsa o projenin şantiyelerini de göremez → 404
(403 değil; varlığın kendisi sızdırılmaz).

`GET /sites/{site_id}` ve `PATCH /sections/{section_id}` proje kimliğini
şantiye/bölüm üzerinden yukarı doğru çözer ve aynı süzgeçten geçirir. **Bu, en
kolay atlanacak güvenlik noktasıdır** — negatif test zorunludur (§7).

---

## 6. Migration

Tek migration: `p2_santiye_bolum`, `down_revision = "b7fcd67bde1e"` (P1 head).

Sıra:
1. `site_status`, `section_status` enum'ları
2. `sites` tablosu + `uq_sites_project_code` + `ix_sites_project_id`
3. `sections` tablosu + `ix_sections_site_id` + kısmi benzersiz `uq_sections_site_code`
4. `modules` tablosuna `sites` satırı
5. 8 rol için `role_permissions` satırı

`downgrade()` tam tersini yapar (izin satırları → modül → tablolar → enum'lar).
CI'daki "Migrations on real Postgres (up→down→up)" adımı bunu doğrular.

**Seed veri yazılmaz.** P1'in 3 seed projesine şantiye eklenmez — sahte veri
üretmeme kuralı (ana spec §7). Şantiye listesi boş durumla açılır.

---

## 7. Testler

TDD: her task kırmızı → yeşil → refactor. Hedef %80+ kapsam.

**Model/migration**
- `uq_sites_project_code`: aynı projede aynı kod → IntegrityError; farklı projede aynı kod → geçerli
- `sections.code` NULL çoklu satır → geçerli (kısmi indeks)
- Proje silinince şantiyeler, şantiye silinince bölümler cascade düşer

**Servis**
- `remaining_days`: `end_date` yok → null; `completed` → null; geçmiş tarih → negatif
- `city_inherited`: şantiye şehri boş → proje şehri + bayrak true; dolu → bayrak false
- `section_status_counts` üç durumu doğru sayar
- Bölümsüz şantiye: `sections: []`, `section_count: 0` (Karar 4)
- Yer tutucu alanlar her zaman `available: false` + doğru `pending_module`

**Yetki — negatif testler (zorunlu, ana spec §10)**
- `sites:view` olmayan rol → 403, tüm 7 uçta
- `sites:view` olan ama projeye erişimi olmayan kullanıcı → **404** (403 değil):
  - `GET /projects/{gizli}/sites`
  - `GET /sites/{gizli şantiye}`
  - `GET /sites/{gizli}/sections`
  - `PATCH /sites/{gizli}`
  - `PATCH /sections/{gizli şantiyenin bölümü}`  ← en kritik, dolaylı erişim
- `sites:view` var ama `sites:full` yok → POST/PATCH 403
- Taşeron rolü (`_N`) hiçbir uca erişemez

**Denetim günlüğü**
- Şantiye ve bölüm oluşturma/güncelleme `record_audit` yazar (B5 deseni,
  `messages.py`'ye yeni Türkçe metinler eklenir)

---

## 8. Açık sorular (uygulamadan önce kullanıcıya)

1. **`sites` izin satırı profili** (§5.1 tablosu) — özellikle "Şantiye Şefi
   şantiye/bölüm açabilmeli mi?" Şu anki öneri: hayır, yalnız görür.
2. **Şantiye kodu zorunlu mu?** Mockup kod göstermiyor ("A-Blok Şantiyesi" ad).
   Öneri: zorunlu ama ad'dan otomatik türetilir (`A-BLOK`), kullanıcı düzeltebilir.

Bu ikisi cevaplanmadan da uygulama başlayabilir; ikisi de tek dosyada, sonda
değiştirilebilir.

---

## 9. Kapsam dışı (sonraki dilimler)

Milestone takvimi, BOQ/pozlar, sözleşmeler, hakediş (P5+), puantaj, stok, günlük
kayıt, belgeler, "gecikme riski" hesabı, şantiye silme ucu, `site_manager_user_id`
FK'si, bölüm başına maliyet.
