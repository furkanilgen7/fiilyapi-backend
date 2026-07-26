# Alt-Proje 2 · P1 — Proje çekirdeği ve proje tipleri (tasarım)

Tarih: 2026-07-26
Kapsam: Alt-Proje 2'nin 11 diliminden ilki — yalnızca `Ekran 4 - Projeler`
Mockup kanonu: `projedesign/Ekran 4 - Projeler.dc.html`
Bağlı ana spec: `2026-07-17-temel-modul-design.md` §4.1 (Alt-Proje 2 kapsam notu), §5, §10
Bağlı desen: `2026-07-25-backend-b6-gosterge-paneli-design.md` §2.3 (yer tutucu sözleşmesi)

---

## 1. Amaç ve kapsam

Alt-Proje 2'nin geri kalan her dilimi (şantiye, iş kalemleri, üniteler, maliyet
kırılımı, takvim…) proje kaydının üstüne oturur. P1 bu çekirdeği kurar:

- `projects` tablosunun Ekran 4'ün istediği modele genişletilmesi (üç proje tipi),
- tip başına uzantı tabloları (`project_investment`, `project_land_share`,
  `land_share_shareholder`),
- yeni `projects` izin modülü ve 4 uç (liste + detay + oluştur + güncelle),
- mevcut `GET /projects` uçlarının `user_management` izninden `projects` iznine
  taşınması (kritik geçiş, §5.4).

Yalnızca Ekran 4 yazılır. Proje Detay ekranları (`Proje - Kendi Yatırım`,
`Proje - Kat Karşılığı`, `Proje Detay - Şantiyeler`) sonraki dilimlerin işidir.
Frontend bu spec'in kapsamında değildir; frontend spec'i frontend reposunda ayrıca
yazılır.

## 2. Dürüstlük kararı — B6 deseni: kabuk gerçek, veri dürüst

Ana spec §7 kararı bu ekranda da geçerlidir. Ekran 4 kartlarındaki her alan iki
sınıftan birine girer; sahte/seed rakam **üretilmez**.

**Gerçek (bu dilimde saklanan/dönen):**

| Alan | Kaynak |
|---|---|
| Tip rozeti (TAAHHÜT / KENDİ YATIRIM / KAT KARŞILIĞI) | `projects.project_type` |
| Ad | `projects.name` |
| Kategori · Şehir ("Konut · Ankara") | `projects.category`, `projects.city` |
| Durum rozeti (Aktif / Beklemede / Tamamlandı) | `projects.status` |
| Başlangıç / Bitiş | `projects.start_date`, `projects.end_date` |
| Sözleşme bedeli | `projects.contract_amount` |
| İşveren adı ("İşveren: Güneşkent A.Ş.") | `projects.employer_name` |
| Arsa sahibi + paylaşım oranı ("Yılmaz Ailesi", %55/%45) | `project_land_share` |
| Arsa maliyeti ₺0 | sabit — kat karşılığında tanımı gereği 0, saklanmaz (§3.3) |
| Hissedar sayısı ("3 hissedar") | `land_share_shareholder` satır sayısı |
| Satış hedefi, arsa maliyeti (kendi yatırım) | `project_investment` |
| Tip sekmesi sayaçları ("Tümü (8)" …) | görünür proje kümesinden sayılır |

**Boş durum (`available: false` + `pending_module`):**

| Alan | pending_module |
|---|---|
| Harcanan | `progress_payments` |
| Fiziksel İlerleme / İnşaat İlerlemesi | `progress_payments` |
| Final Hakediş (tamamlanan kart) | `progress_payments` |
| "48 işçi" | `timesheet` |
| "12 taşeron" | `subcontracts` |
| Satılan, satış oranı, ünite adetleri, kendi pay değeri | `units` |
| Toplam maliyet, inşaat maliyeti, tahmini kâr, marj | `project_costs` |

B6 spec §2.3'teki sözleşme aynen geçerli: `pending_module` bir **modül
anahtarıdır**, kullanıcı metni değil; kullanıcıya gösterilecek Türkçe kopya
frontend'in işidir. İlgili dilim geldiğinde backend `available: true` döndürmeye
başlar, frontend'de tek satır değişmez.

**Bilinçli ikilik — `progress_pct`:** `projects.progress_pct` ve `budget` sütunları
**kalır**; F6 gösterge paneli kartları onları tüketiyor. Ekran 4'teki "Fiziksel
İlerleme" ise hakediş türevi bir değerdir ve bu ekranda boş durum döner. İki ekran
aynı sözcüğü farklı kaynaktan doldurur; hakediş dilimi geldiğinde ikisi de aynı
kaynağa bağlanır.

## 3. Veri modeli

### 3.1 `projects` genişletmesi

Yeni enum: `project_type` → `taahhut` · `kendi_yatirim` · `kat_karsiligi`.

| Yeni sütun | Tip | Not |
|---|---|---|
| `project_type` | enum `project_type`, NOT NULL, default `taahhut` | mevcut 3 seed satırı taahhut olur |
| `category` | text, null | "Konut", "Endüstri", "Altyapı" — serbest metin |
| `city` | text, null | "Ankara" |
| `start_date` | date, null | |
| `end_date` | date, null | geciken bitişin kırmızı gösterimi frontend'in işi |
| `contract_no` | text, null | |
| `contract_amount` | numeric(18,2), null | Sözleşme Bedeli |
| `employer_name` | text, null | **serbest metin.** `employers` tablosu Alt-Proje 3'ün işidir; şimdi FK açmak taksonomiyi erken dondurmak olur |

Tüm yeni sütunlar nullable ya da varsayılanlı — mevcut satırlar bozulmaz.
`budget` ve `progress_pct` kalır (§2). `Project` modelindeki "v1'de minimal ve
salt-okunur" docstring'i bu dilimle geçersizleşir ve güncellenir.

### 3.2 `project_investment` (kendi yatırım uzantısı, 1-1)

| Sütun | Tip | Not |
|---|---|---|
| `project_id` | UUID PK, FK → `projects.id` (ON DELETE CASCADE) | 1-1'i PK zorlar |
| `sales_target` | numeric(18,2), null | Satış Hedefi |
| `land_cost` | numeric(18,2), null | Arsa Maliyeti (kendi yatırımda gerçek gider) |

Kartın kalan alanları (satılan, toplam maliyet, tahmini kâr, satış oranı, marj)
türev değerlerdir ve P10'un (maliyet/kâr dilimi) işidir; burada sütun açılmaz.

### 3.3 `project_land_share` (kat karşılığı uzantısı, 1-1)

| Sütun | Tip | Not |
|---|---|---|
| `project_id` | UUID PK, FK → `projects.id` (ON DELETE CASCADE) | |
| `landowner_name` | text, NOT NULL | "Yılmaz Ailesi" |
| `our_share_pct` | numeric(5,2), NOT NULL | %55 |
| `owner_share_pct` | numeric(5,2), NOT NULL | %45 |
| `contract_no` | text, null | kat karşılığı sözleşme no |
| `notary_date` | date, null | noter tarihi |
| `land_area_m2` | numeric(12,2), null | |
| `construction_area_m2` | numeric(12,2), null | |
| `delivery_date` | date, null | teslim tarihi |
| `daily_penalty` | numeric(18,2), null | günlük gecikme cezası |
| `guarantee_amount` | numeric(18,2), null | teminat |

DB kısıtı: `CHECK (our_share_pct + owner_share_pct = 100)`
(`ck_land_share_pct_total`).

**Arsa maliyeti sütunu yok** — kat karşılığında tanımı gereği ₺0'dır; saklamak,
"değiştirilebilir bir alan" yanılsaması yaratır. Yanıt şemasında sabit `0` döner.

### 3.4 `land_share_shareholder` (1-N)

| Sütun | Tip | Not |
|---|---|---|
| `id` | UUID PK | |
| `project_id` | UUID FK → `projects.id` (ON DELETE CASCADE), index | |
| `name` | text, NOT NULL | |
| `share_pct` | numeric(5,2), NOT NULL | |

Hissedar başına ünite dağılımı P9'un işidir; burada yalnız ad + pay yüzdesi.
Hissedar paylarının toplamı üzerinde DB kısıtı **yoktur** — hissedarlar bizim
payımızın iç dağılımıdır ve eksik girilmiş olabilir; doğrulama ileride ekran
gerektirirse servis katmanına gelir.

### 3.5 Tip tutarlılığı korkuluğu — servis katmanında

- `project_investment` satırı yalnız `kendi_yatirim` projelerine,
- `project_land_share` + `land_share_shareholder` yalnız `kat_karsiligi`
  projelerine yazılabilir.

İhlal **422** döner (`ProjectTypeMismatchError`, §5.6). DB seviyesinde bileşik
FK/CHECK **bilinçli olarak yapılmıyor**: `project_type`'ı uzantı tablolarına
denormalize edip bileşik FK kurmanın maliyeti, tek satırlık servis kontrolünün
sağladığı güvenceden pahalıdır. Yazma yolları tekil (yalnız bu servis) olduğu
için korkuluk tek noktada durur.

`project_type` **PATCH ile değiştirilemez** (güncelleme şemasında alan yok).
Tip, projenin iş modelidir; sonradan değiştirmek uzantı satırlarını öksüz
bırakır. Yanlış tiple açılmış proje silinip yeniden açılır (silme admin işi,
bu dilimde uç yok — §10; gerekirse DB'den).

## 4. Yeni izin modülü: `projects`

İzin matrisine 15. modül eklenir (invoicing 14. idi):

| Alan | Değer |
|---|---|
| `key` | `projects` |
| `name` | `Projeler` |
| `group` | `GENEL` |
| `sort_order` | **3** — mockup sidebar'ında Projeler GENEL grubundadır; `site_diary`'den `user_management`'a kadar mevcut modüller birer kayar (3→4 … 14→15), invoicing migration'ının (`2cffc2fcfcf0`) kurduğu kaydırma deseniyle |

Matris satırı (8 rol, `ROLE_ORDER` sırasıyla):

```python
"projects": [_A, _F, _LIM, _LIM, _LIM, _FIN, _F, _N],
#            sysadmin patron şef   saha   İK    muhasebe PM  satınalma
```

**Gerekçe:** proje kartları gösterge paneliyle aynı görünürlük yüzeyidir; satır,
`dashboard` satırının birebir aynısıdır. Hangi projelerin görüneceğini zaten
`user_project_access` süzer (§5.2) — buradaki seviye yalnız ekrana girip
girememeyi ve yazabilmeyi belirler. "+ Yeni Proje" (`full`) yalnız Patron, Proje
Müdürü ve Sistem Yöneticisi'nde.

Toplam: 8 rol × 15 modül = **120** izin satırı. `company_assets` bu dilimin
**dışındadır** (eklendiğinde 16. modül olur; ana spec §10.2'deki "15. modül"
ifadesi invoicing'in eklenmesiyle eskimişti, bkz. §11).

## 5. Uçlar

Hepsi `app/modules/projects/` içinde; modüle `service.py` eklenir
(router → service → repository).

| Uç | İzin | İş |
|---|---|---|
| `GET /projects` | `projects` ≥ `view` | liste + sayaçlar + filtreler |
| `GET /projects/{id}` | `projects` ≥ `view` | tekil proje, uzantısıyla |
| `POST /projects` | `projects` ≥ `full` | "+ Yeni Proje" |
| `PATCH /projects/{id}` | `projects` ≥ `full` | güncelleme |

**DELETE yok** — bilinçli erteleme: silme `admin` seviyesi ister ve altında
şantiye/sözleşme kayıtları varken silmenin ne demek olduğu (kaskad mı, blok mu)
o dilimler yazılmadan tanımsızdır.

### 5.1 `GET /projects` — filtreler ve sayaçlar

Sorgu parametreleri: `?type=` (`taahhut` | `kendi_yatirim` | `kat_karsiligi`) ve
`?status=` (`active` | `on_hold` | `completed`; mockup'taki sekme yalnız
`completed` kullanır). İkisi birlikte verilebilir (kesişim).

Yanıt: `{ "counts": …, "items": […] }`.

`counts` **filtrelerden etkilenmez** — mockup sekme sayaçları hangi sekme açık
olursa olsun tüm kümeyi gösterir. Sayaçlar aktörün **görünür** kümesi üzerinden:

```jsonc
"counts": {
  "all": 8,            // görünür projelerin tamamı
  "taahhut": 4,        // tip sayaçları durumdan bağımsız (4+2+2 = 8)
  "kendi_yatirim": 2,
  "kat_karsiligi": 2,
  "completed": 2       // durum sayacı tiplerle kesişir
}
```

### 5.2 Kapsam süzgeci

B6'daki `list_projects_for_user` (`app/modules/projects/repository.py`,
`user_project_access` süzgeci) **aynen** kullanılır: `all_projects=true` → tümü;
yalnız `project_id` satırları → o projeler; satır yok → boş liste.

**Admin istisnası:** aktörün `projects` modülündeki seviyesi `admin` ise süzgeç
atlanır ve tüm projeler döner. Gerekçe: Ayarlar'daki kullanıcı-proje erişim
ekranı, erişim **vermek için** tüm projeleri listeleyebilmelidir; erişim satırı
olmayan taze bir Sistem Yöneticisi süzgece takılsaydı kimseye proje erişimi
veremezdi (kilitlenme, ana spec §5.0'daki korumanın ruhu). Seviye
`roles.repository.get_permission(session, user.role_id, "projects")` ile okunur.

Boş liste hata değildir — yeni kurulan şirkette normal durumdur; `200` +
`items: []`, sayaçlar 0 döner.

### 5.3 Liste/detay yanıt gövdesi

Kart varyantını frontend `project_type`'a göre seçer. Tip uzantıları yalnız
ilgili tipte doludur, diğerlerinde `null`:

```jsonc
{
  "id": "…",
  "code": "GK-A",
  "name": "Güneşkent A-Blok",
  "project_type": "taahhut",
  "category": "Konut",
  "city": "Ankara",
  "status": "active",
  "start_date": "2025-03-01",
  "end_date": "2026-12-31",
  "contract_no": null,
  "contract_amount": "11200000.00",
  "employer_name": "Güneşkent A.Ş.",
  "budget": "1500000.00",          // F6 mirası, kalır
  "progress_pct": "42.50",         // F6 mirası, kalır (§2 ikilik notu)

  "contracting": {                  // yalnız taahhut'ta dolu
    "spent":                  { "available": false, "value": null, "pending_module": "progress_payments" },
    "physical_progress":      { "available": false, "value": null, "pending_module": "progress_payments" },
    "final_progress_payment": { "available": false, "value": null, "pending_module": "progress_payments" },
    "worker_count":           { "available": false, "count": null, "pending_module": "timesheet" },
    "subcontractor_count":    { "available": false, "count": null, "pending_module": "subcontracts" }
  },
  "investment": null,               // yalnız kendi_yatirim'da dolu
  "land_share": null                // yalnız kat_karsiligi'nda dolu
}
```

`investment` dolu olduğunda:

```jsonc
"investment": {
  "sales_target": "48200000.00",   // gerçek (project_investment)
  "land_cost": "9500000.00",       // gerçek
  "sold_amount":      { "available": false, "value": null, "pending_module": "units" },
  "sales_ratio":      { "available": false, "value": null, "pending_module": "units" },
  "unit_summary":     { "available": false, "count": null, "pending_module": "units" },
  "total_cost":       { "available": false, "value": null, "pending_module": "project_costs" },
  "estimated_profit": { "available": false, "value": null, "pending_module": "project_costs" },
  "margin":           { "available": false, "value": null, "pending_module": "project_costs" }
}
```

`land_share` dolu olduğunda:

```jsonc
"land_share": {
  "landowner_name": "Yılmaz Ailesi",          // gerçek
  "our_share_pct": "55.00",                   // gerçek
  "owner_share_pct": "45.00",                 // gerçek
  "land_cost": "0.00",                        // sabit — tanım gereği (§3.3)
  "contract_no": null, "notary_date": null,
  "land_area_m2": null, "construction_area_m2": null,
  "delivery_date": null, "daily_penalty": null, "guarantee_amount": null,
  "shareholder_count": 3,                     // gerçek (land_share_shareholder)
  "shareholders": [ { "id": "…", "name": "…", "share_pct": "40.00" } ],
  "our_unit_count":        { "available": false, "count": null, "pending_module": "units" },
  "owner_unit_count":      { "available": false, "count": null, "pending_module": "units" },
  "our_share_value":       { "available": false, "value": null, "pending_module": "units" },
  "construction_cost":     { "available": false, "value": null, "pending_module": "project_costs" },
  "estimated_profit":      { "available": false, "value": null, "pending_module": "project_costs" },
  "margin":                { "available": false, "value": null, "pending_module": "project_costs" },
  "construction_progress": { "available": false, "value": null, "pending_module": "progress_payments" }
}
```

Yer tutucu şekilleri B6 §2.3 sözleşmesinin aynısıdır (`MetricPlaceholder`;
sayı taşıyanlar için `CountPlaceholder` — `value` yerine `count: int | null`).
v1'de hepsi `available: false`; değerler servis katmanında tek yerde üretilir.

`GET /projects/{id}` aynı gövdeyi tekil döner. Eski `ProjectResponse` şeması
kaldırılır (dashboard kendi `DashboardProjectCard`'ını kullanıyor, etkilenmez).

### 5.4 KRİTİK GEÇİŞ: `user_management` → `projects` izni

Bugün `GET /projects` ve `GET /projects/{id}` uçları
`require_permission("user_management", AccessLevel.view)` kapısındadır ve
Ayarlar'daki **kullanıcı-proje erişim ekranı** bu uçları tüketir. Bu dilimle
uçlar `projects` iznine taşınır. Geçişin kırmaması için:

1. Seed'de o ekranı kullanan roller `projects >= view` almalıdır.
   `user_management >= view` bugün yalnız `system_admin`'dedir; §4 matrisi ona
   `projects = admin` verir — karşılanır.
2. **Regresyon testi zorunlu:** `system_admin`, hiç `user_project_access` satırı
   olmadan `GET /projects`'ten tüm projeleri alabilmelidir (admin istisnası,
   §5.2). Bu, kullanıcı-proje erişim ekranının çalışmaya devam etmesinin
   testidir.
3. Mevcut `tests/modules/test_projects_api.py` içindeki
   `test_list_projects_forbidden_for_non_admin` (patron → 403) **tersine döner**:
   patron artık `projects = full` taşır ve 200 alır. 403 negatif testi
   `procurement` (`projects = none`) ile yazılır.
4. Liste yanıtının `list[…]`'ten `{counts, items}` zarfına dönmesi OpenAPI'yi
   değiştirir; frontend'deki kullanıcı-proje erişim ekranının uyarlanması
   frontend spec'inin işidir (şema `pnpm gen:api` ile derleme hatası olarak
   görünür, sessizce kırılmaz).

### 5.5 Yazma uçları

`POST /projects` gövdesi: ortak alanlar (`code`, `name`, `project_type`,
`status`, `category`, `city`, `start_date`, `end_date`, `contract_no`,
`contract_amount`, `employer_name`) + tipe göre en fazla biri:
`investment` (nesne) veya `land_share` (hissedar listesi dahil, nesne).

Servis korkuluğu (§3.5): `investment` yalnız `kendi_yatirim` ile,
`land_share` yalnız `kat_karsiligi` ile verilebilir; aksi 422. Uzantısı
verilmeyen `kendi_yatirim`/`kat_karsiligi` projesi de açılabilir (uzantı satırı
sonradan PATCH ile gelir) — zorunluluk yok, alanlar zaten nullable.

`PATCH /projects/{id}`: tüm alanlar isteğe bağlı; `project_type` **yok** (§3.5).
`investment`/`land_share` verildiğinde mevcut uzantı satırı güncellenir ya da
yoksa oluşturulur; `land_share.shareholders` verildiğinde hissedar listesi
**bütünüyle değiştirilir** (replace) — parça parça hissedar CRUD'u bu ekranın
ihtiyacı değil. `code` benzersizliği ihlali mevcut `IntegrityError` handler'ı
ile 409 döner.

Her iki uç da B5 denetim kaydı yazar (`record_audit`; `create`/`update`,
mevcut modüllerle aynı desen, `app/modules/audit/messages.py`'a proje mesajları
eklenir). Okuma uçları kayıt yazmaz.

### 5.6 Hatalar

| Durum | Yanıt |
|---|---|
| Oturum yok / token geçersiz | 401 |
| `projects` izni eşiğin altında | 403 "Bu işlem için yetkiniz yok" |
| Proje bulunamadı / görünür kümede değil | 404 "Proje bulunamadı" |
| Tip-uzantı uyuşmazlığı (§3.5) | **422** — yeni `ProjectTypeMismatchError(DomainError)` + handler |
| `our_share_pct + owner_share_pct != 100` | 422 (Pydantic model doğrulaması; DB CHECK son savunma hattı) |
| `code` çakışması | 409 (mevcut `IntegrityError` handler'ı) |
| Erişilebilir proje yok | 200, `items: []`, sayaçlar 0 |

`GET /projects/{id}` görünürlük dışı projeye **404** döner (403 değil — varlığı
sızdırmamak için), admin istisnası burada da geçerlidir.

## 6. Migration — tek migration

Tek Alembic migration (`2cffc2fcfcf0` üstüne):

1. `project_type` enum'ı + `projects`'e 8 sütun (hepsi nullable/varsayılanlı;
   mevcut 3 seed satırı `server_default` ile `taahhut` olur, veri bozulmaz).
2. 3 yeni tablo (§3.2–3.4) + CHECK kısıtı.
3. `modules`'a `projects` satırı (sort_order 3) + sonraki modüllerin sort_order
   kaydırması + 8 izin satırı — invoicing migration'ının idempotent SQL deseni
   (`ON CONFLICT … DO NOTHING`, `role_id`/`module_id` çalışma anında okunur,
   `SORT_ORDER_UPDATES` / `PREVIOUS_SORT_ORDERS` sabitleriyle geri alınabilir).

Downgrade tam tersini yapar (izinler + modül + sort geri, tablolar drop, sütunlar
drop, enum drop). Migration lokal DB'de upgrade + downgrade koşularak doğrulanır;
canlıya karşı **asla**.

**Yeni tip örneği seed'e eklenmez** — mevcut 3 proje taahhut kalır; kendi
yatırım/kat karşılığı örneği eklemek sahte veri üretmek olur (§2).

`tests/modules/test_seed_migration_matches_seed_data.py` migration bileşkesine
bu migration'ı da katacak şekilde genişletilir (112 → 120 hücre);
`tests/modules/test_seed_matrix.py`'deki 112/14 sabitleri 120/15 olur.

## 7. Testler

TDD, hedef ≥%80 kapsam. Ayrıntılı adımlar uygulama planında; asgari küme:

| Test | Beklenen |
|---|---|
| Model/migration: uzantı tabloları, CHECK, cascade | yeşil |
| Seed: 120 hücre, `projects` satırı dashboard satırıyla aynı, sort kaydırması | yeşil |
| `procurement` liste çağırır | 403 |
| Kimliksiz çağrı | 401 |
| `system_admin`, erişim satırı yokken | tüm projeler (admin istisnası, §5.4 regresyonu) |
| `patron` (`full`), yalnız 1 projeye erişimli | yalnız o proje + sayaçlar o kümeden |
| `?type=` / `?status=completed` filtreleri | items süzülür, `counts` değişmez |
| Taahhut yanıtı | `contracting` dolu, `investment`/`land_share` null, yer tutucular doğru `pending_module` |
| Kat karşılığı POST (paylar + hissedarlar) | 201; `shareholder_count` gerçek; `land_cost` `"0.00"` |
| Taahhut projesine `investment` POST/PATCH | 422 |
| Pay toplamı ≠ 100 | 422 |
| PATCH ile hissedar listesi replace | eski satırlar gider, yeniler gelir |
| POST/PATCH denetim kaydı | `audit_log`'a `create`/`update` düşer |
| Mevcut dashboard + projects testleri | izin geçişi sonrası yeşil (3. madde §5.4) |

Testler lokal Postgres'te koşar (brew `postgresql@18`, port 5432).
`backend/.env` içindeki `TEST_DATABASE_URL` uzak Railway host'unu gösteriyor ve
conftest ona `drop_all` uyguluyor — **oraya asla koşturulmaz**.

## 8. Teslim sonrası

`openapi.json` üretilir → `frontend/openapi/openapi.json`'a kopyalanır →
`pnpm gen:api`. Akış `backend/README.md`'de. Frontend Ekran 4 spec'i bu şemanın
üstüne frontend reposunda yazılır.

## 9. Kapsam dışı

Şantiye/bölüm, ünite yönetimi, maliyet kırılımı, kâr projeksiyonu, teslim
milestone'ları, hissedar-ünite dağılımı (P9), satış/maliyet türev alanları
(P10), silme ucu, `employers` tablosu (Alt-Proje 3), `company_assets`, Proje
Takvimi, frontend (ayrı spec, frontend reposunda).

## 10. Mevcut kodla bulunan çelişkiler ve çözümleri

1. **Ayarlar kilitlenme riski.** Onaylı tasarım "kapsam süzgeci:
   `list_projects_for_user` aynen" der; ama kullanıcı-proje erişim ekranı erişim
   *vermek için* tüm projeleri listelemek zorundadır ve taze `system_admin`'in
   erişim satırı yoktur — süzgeç aynen uygulansaydı ekran boş kalır, kimseye
   erişim verilemezdi. Çözüm: `projects = admin` seviyesine süzgeç istisnası
   (§5.2) + regresyon testi (§5.4). Süzgecin kendisi diğer tüm roller için aynen.
2. **`test_list_projects_forbidden_for_non_admin` tersine döner** — patron
   izin geçişiyle 403 yerine 200 alır; test `procurement`'a taşınır (§5.4).
3. **Ana spec §10.2 "company_assets = 15. modül" eskidi** — invoicing 14. modül
   olarak eklendiğinden `projects` 15. olur, `company_assets` sırası 16'ya
   kayar. Bu spec düzeltmez, yalnızca kayda geçirir; `company_assets`
   spec'lendiğinde numara oradan alınır.
4. **`Project` docstring'i** ("v1'de minimal ve salt-okunur… Yazma ucu yok")
   bu dilimle yanlışlaşır; model güncellenirken düzeltilir.
5. **`seed_migration` parity testi** yalnız `a477fdf00fdf` + `2cffc2fcfcf0`
   bileşkesini biliyor; yeni migration eklenince test bileşkeye katılmazsa
   yanlış negatif verir — test genişletilir (§6).
