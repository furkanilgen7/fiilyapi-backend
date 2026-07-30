# Şantiye Ekle Formu — Backend Genişlemesi · Uygulama Planı

Tarih: 2026-07-30
Repo: `fiilyapi-backend` (`/Users/furkanilgen/Documents/Projeler/insaat/backend`)
Onaylı spec: `backend/docs/superpowers/specs/2026-07-30-santiye-formu-genisleme-design.md`
Mockup kanonu: `projedesign/Form - Santiye Ekle.dc.html` (234 satır)
Biçim emsali: `backend/docs/superpowers/plans/2026-07-30-alt-proje-2-p3-proje-tip-detay-units.md`

Task sayısı: **16 uygulama task'ı (T1–T16)**. Spec + bu plan = T0, onayla kapanır.

> Bu plan **yalnız plandır**. Kod, migration, test yazılmadı; commit atılmadı.
> `frontend/` altına **tek satır** yazılmaz.

---

## 0. TUZAKLAR — her task'ta yeniden okunacak

> Bu bölüm süs değildir. Maddelerin her biri ya spec'ten çıkmış bir veri kaybı riskidir
> ya da bu repoda daha önce gerçekleşmiş bir hatadır. Task'lar ayrı ajanlara verildiğinde
> bu bilgi taşınmaz — bu yüzden **her task'ın kapı komutunda tekrar edilir**.

### 0.1 ⚠️ CASCADE TUZAĞI — bu dilimin **en kritik** maddesi

`sites.id`'yi hedefleyen **dört FK'nın hepsi `ON DELETE CASCADE`**'dir (spec §7.1,
koddan doğrulandı):

| Bağlı tablo | Kolon | Davranış | Kaynak |
|---|---|---|---|
| `sections` | `site_id` | **CASCADE** | `app/modules/sites/models.py` |
| `boq_groups` | `site_id` | **CASCADE** | `app/modules/boq/models.py:36` |
| `boq_items` | `site_id` | **CASCADE** | `app/modules/boq/models.py:75` |
| `blocks` | `site_id` | **CASCADE** | `app/modules/units/models.py:71` |

Yani **DB kendiliğinden korumaz.** Korkuluksuz tek bir `DELETE /sites/{id}` çağrısı
bölümleri, poz gruplarını, poz kalemlerini ve blokları **sessizce yok eder** — ve bu,
testler yazılana kadar fark edilmeyen, **geri alınamaz** bir veri kaybıdır.

**Bu yüzden `T9` (EXISTS korkulukları) → `T10` (DELETE site) sırası PAZARLIK DIŞIDIR.**
T10'un testinde silme denemesinden **sonra** bağlı kayıtların sayımı doğrulanacaktır
(`SELECT count(*)` öncesi/sonrası eşitliği) — bu, cascade'in tetiklenmediğinin **tek**
gerçek kanıtıdır; 409 dönmesi tek başına kanıt değildir.

Tek kısmi doğal ağ: `units.block_id` `RESTRICT` olduğu için üniteli bir bloğun cascade'i
`IntegrityError` üretir. Bu bir **kaza sonucu** korumadır, tasarım değildir ve poz/bölüm
tarafını hiç korumaz — güvenilmez.

### 0.2 TEST DB TUZAĞI (veri kaybı riski)

`backend/.env` içindeki `TEST_DATABASE_URL` **uzak Railway veritabanını** gösteriyor ve
`tests/conftest.py` oturum başında `Base.metadata.drop_all` çağırıyor. O env ile `pytest`
koşmak **canlı benzeri veritabanını siler**.

**Kural:** `.env` dosyasına **DOKUNULMAZ** (ne düzenlenir, ne geçici değiştirilir).
Her task tek kullanımlık yerel DB açar, env'i **komut satırında** verir, sonunda düşürür:

```bash
createdb snt_form_tN && \
  TEST_DATABASE_URL="postgresql+asyncpg://furkanilgen@localhost:5432/snt_form_tN" \
  .venv/bin/pytest <hedef testler> -x
dropdb snt_form_tN      # BAŞARISIZLIKTA BİLE — istisnasız
```

### 0.3 CANLI VERİ KORKULUKLARI (spec §11.3 — beşi de bağlayıcı)

Canlıda `sites` satırları **var** (P2 ve P1.1a akışlarından) ve mockup'ta `*` işaretli
alanlar (şef 69, il/ilçe 79, inşaat alanı 85, tarihler 94/95) o satırlarda **boş olabilir**.

1. **Hiçbir yeni kolon `NOT NULL` + varsayılansız yapılmaz.** Zorunluluk yalnız uygulama
   katmanında, yalnız **taslak-dışı POST**ta uygulanır. `ALTER COLUMN … SET NOT NULL`
   yazan migration canlıda **patlar** ve deploy'u kilitler.
2. `uq_sites_project_code` **global `UNIQUE`'e çevrilmez** — mevcut ad-türevi kodlar
   (`A-BLOK`, `MERKEZ`) iki projede birden bulunabilir; çevirim canlıda patlar.
   **Üretim global tekil, kısıt proje içi tekil** (§3.2).
3. `PATCH /sites/{id}` **tam doğrulama koşmaz** — koşarsa canlıdaki eksik şantiyeler
   düzenlenemez hâle gelir; kullanıcı adını değiştirmek isterken "Şantiye şefi seçiniz."
   duvarına çarpar. Tek istisna: `is_draft: true → false` geçişi (§5.3).
4. Mevcut satırlar `is_draft=false` (yayında) sayılır.
5. **Mevcut şantiye kodlarına dokunulmaz** — `A-BLOK` gibi ad-türevi kodları `SNT-`
   desenine çeviren hiçbir `UPDATE` yazılmaz. Kod evrakta referanstır.

### 0.4 Migration ebeveyni — varsayılmaz, ÖLÇÜLÜR

**T1'in ilk adımı** budur:

```bash
.venv/bin/alembic heads
```

- Bu plan yazılırken ölçüm: **`a4c7f1d2e8b3 (head)` — tek head.** T1 bunu **yeniden
  ölçer**, çünkü X1 (`e3a8b4a5b93b`) PR'ı merge edilirse durum kayabilir.
- Çıktı **iki head** ise → **KOD YAZILMAZ.** Birleştirme revizyonu (`alembic merge`)
  kullanıcı kararıdır; ajan kendi başına merge revizyonu üretmez. **Durulur, sorulur.**
- Çıktı tek head ama **başka** bir revizyon ise → yine sorulur; `down_revision` ancak
  kullanıcı onayıyla güncellenir.

Yanlış ebeveyn = canlıda çoklu head = **deploy kilitlenmesi**.

### 0.5 Enum takası izole revizyonda

`site_status`'a `preparation` eklenmesi **kendi revizyonundadır** (T1), 22 kolonluk
şema genişlemesiyle **aynı dosyaya konmaz** (`d1a2b3c4e5f6_p1_1a_status_enum.py` dersi).
`ALTER TYPE … ADD VALUE` **kullanılmaz** — geri alınamaz; tip takası deseni uygulanır.
Downgrade'de **önce** `UPDATE sites SET status='active' WHERE status='preparation'`,
**sonra** ters takas — sıra tersse `USING` çevrimi geçersiz değerde patlar.

### 0.6 Canlı DB'ye migration koşulmaz

`upgrade → downgrade → upgrade` doğrulaması **yalnız tek kullanımlık yerel DB'de**.
`DATABASE_URL` canlıyı gösteren bir env ile `alembic upgrade` **çalıştırılmaz**.
Canlı migration, PR merge sonrası Railway auto-deploy'un işidir; doğrulama kullanıcıdadır.

### 0.7 `python` PATH'te YOK · Ruff 0.15.22

Her şey `.venv/bin/` üzerinden: `.venv/bin/{python,pytest,alembic,ruff}`.
`.venv/bin/ruff --version` → `ruff 0.15.22`. Global kurulum (0.8.6) **kullanılmaz**;
yanlış pozitif üretir ve gereksiz diff açar.

### 0.8 `openapi.json` gitignore'lu

Üretilir, frontend'e kopyalanmaya hazır bırakılır, **commit edilmez**.
`git add openapi.json` yapan task geçersizdir.

### 0.9 İzin: silme `admin`, yazma `full`, okuma `view` — modül sayısı **17'de KALIR**

* Okuma (GET) → `sites` · `view`
* Yazma (POST/PATCH) → `sites` · `full`
* **Silme (DELETE) → `sites` · `admin`** (2026-07-30 kullanıcı kararı; `units`/`blocks`/
  `boq` ile birebir aynı — `app/modules/units/router.py:181,206` `_ADMIN` deseni).
  `full` **yazmayı kapsar, silmeyi kapsamaz** (`app/core/access.py`).
* Yeni izin modülü **AÇILMAZ**. `modules` / `role_permissions` tablolarına **dokunulmaz**,
  `app/modules/roles/seed_data.py` MATRIX **değişmez**. Şu üç test dosyası
  **değiştirilmeden** yeşil kalmalıdır — kırmızıya düşerlerse karar ihlal edilmiş demektir:
  - `tests/modules/test_seed_matrix.py`
  - `tests/modules/test_roles_repository.py`
  - `tests/modules/test_roles_api.py`

### 0.10 TDD zorunlu — "KIRMIZI GÖR" atlanamaz

Her task'ta önce test yazılır, **koşulur ve kırmızı olduğu görülür**, sonra uygulama
yazılır, yeşil görülür. Kırmızıyı görmeden uygulama yazan task **geçersizdir** ve baştan
yapılır. Kırmızı çıktı task raporunda **alıntılanır**.

### 0.11 %100 mockup sadakati + onaylı sapmalar

Spec §2'deki alan tablosu kanondur; orada olmayan alan **icat edilmez**
(`district`, `floor_count:int`, `latitude`/`longitude`, OSGB firma adı, `estimated_amount`).
Spec §14'teki **üç onaylı sapma** (bölüm şablonu yazılmaz · tesis ön-işaretleri
uygulanmaz · "Tahmini Bedel" yer tutucu kalır) bir sonraki ajan tarafından
"mockup'a uymuyor" diye **geri alınmaz**.

### 0.12 Ajanlar push etmez

Commit serbest (İngilizce, `<type>: <desc>`). `git push`, PR açma, merge, deploy
**kullanıcı kararıdır**.

---

## 1. Task listesi

Boyut ölçeği: **S** ≈ tek dosya + dar test seti · **M** ≈ 2–3 dosya + orta test seti ·
**L** ≈ şema/altyapı değişimi, geniş test seti veya yüksek hata riski.

---

### T1 — Migration ebeveyni doğrulama + `site_status` enum takası (`preparation`)  ⚠️ RİSKLİ

| | |
|---|---|
| Boyut | **M** |
| Bağımlı | — |
| Risk | **Enum tip takası.** Postgres'te sessizce yanlış gidebilen yer; downgrade'de sıra hatası `USING` çevrimini patlatır. Yanlış `down_revision` = canlıda çoklu head. |

**Önce yazılacak testler** — `tests/modules/sites/test_site_status_enum.py` (yeni)

1. `test_alembic_has_single_head` — `alembic heads` çıktısı **tek** satır
   (§0.4'ün otomatik ağı; iki head'de test kırmızı olur)
2. `test_site_status_enum_has_preparation` — `SiteStatus.preparation` var, değeri
   `"preparation"`; sıra `preparation · active · on_hold · completed`
3. `test_site_status_completed_still_exists` — `completed` **KALDIRILMADI**
   (`SiteCounts.completed` + `_remaining_days` + P2 liste sekmesi ona bağlı)
4. `test_site_can_be_created_with_preparation_status` — DB'ye `preparation` yazılabiliyor
5. `test_site_status_default_is_active` — `server_default` hâlâ `active` (mockup 71 `selected`)
6. `test_pg_type_lists_four_labels` — `pg_enum` sorgusu tam **dört** etiket döndürüyor
7. `test_upgrade_downgrade_upgrade_round_trip` — `alembic upgrade head` → `downgrade -1`
   → `upgrade head`; her adımdan sonra `pg_type`/`pg_enum` doğrulanır.
   **Downgrade'den sonra `preparation` etiketinin KALMADIĞI** ayrıca doğrulanır.
8. `test_downgrade_moves_preparation_rows_to_active` — `preparation` durumlu bir satır
   varken `downgrade` → satır `active` oldu, **kaybolmadı** (§3.1 sırası kanıtı)

**KIRMIZI GÖR:** `AttributeError: preparation` / `LookupError` ile 8 test kırmızı.
Çıktı raporda alıntılanır.

**Dokunulacak/oluşturulacak dosyalar:**
- `backend/app/modules/sites/models.py` (değişiklik — `SiteStatus`'a `preparation`, **sıra başta**)
- `backend/alembic/versions/<hash>_site_status_preparation.py` (yeni)
- `backend/tests/modules/sites/test_site_status_enum.py` (yeni)

**Uygulama notları:**
- **İlk adım** `.venv/bin/alembic heads` (§0.4). Çıktı raporda verilir. Tek head ve
  `a4c7f1d2e8b3` değilse → **dur, sor.**
- Migration gövdesi spec §3.1'deki altı satırlık SQL'den **birebir**:
  `CREATE TYPE site_status_new` → `DROP DEFAULT` → `ALTER … TYPE … USING` → `DROP TYPE`
  → `RENAME TO` → `SET DEFAULT 'active'`.
- `ALTER TYPE … ADD VALUE` **kullanılmaz** (§0.5).
- Bu revizyonda **başka hiçbir şey** yok — 22 kolon T2'nin işidir.

**Kabul kriteri:**
- 8 test yeşil
- `.venv/bin/alembic heads` → **tek** head, yeni revizyon
- `pg_enum`'da tam dört etiket, sıra doğru
- Seed/roles üç test dosyası **değişmeden** yeşil (§0.9)
- `ruff check` + `ruff format --check` → `0`

**Kapı komutu:**
```bash
cd /Users/furkanilgen/Documents/Projeler/insaat/backend
.venv/bin/alembic heads          # ÖNCE — §0.4, çıktı raporda
createdb snt_form_t1 && \
  TEST_DATABASE_URL="postgresql+asyncpg://furkanilgen@localhost:5432/snt_form_t1" \
  .venv/bin/pytest tests/modules/sites/test_site_status_enum.py \
    tests/modules/test_seed_matrix.py tests/modules/test_roles_repository.py \
    tests/modules/test_roles_api.py -x
dropdb snt_form_t1
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

**Geri alma:** `downgrade` ile geri alınır ve bu **test 7/8 ile zaten doğrulanmıştır**
(round-trip + veri taşınması). Kod tarafında geri alma = enum satırının ve migration
dosyasının çıkarılması.

---

### T2 — `sites` 22 kolon + `sections.manager_user_id` migration'ı + ORM modelleri  ⚠️ RİSKLİ

| | |
|---|---|
| Boyut | **L** |
| Bağımlı | T1 |
| Risk | **Canlı veri sınıfı.** Yanlışlıkla `NOT NULL` konan tek bir kolon canlı deploy'u kilitler. `CHECK` kısıtı + iki FK + indeksler aynı revizyonda. |

**Önce yazılacak testler** — `tests/modules/sites/test_site_model.py` (genişletme) +
`tests/modules/sites/test_sites_migration.py` (yeni)

Model (`test_site_model.py` genişletmesi):
1. `test_site_has_all_twenty_two_new_columns` — spec §3.0 tablosunun 22 satırı
   `Site.__table__.columns` ile **tek tek** karşılaştırılır (ad + tip + nullable)
2. `test_facility_columns_are_not_null_with_false_default` — sekiz tesis kolonu
   `nullable=False`, `server_default` `false`
3. `test_facility_defaults_are_all_false_on_insert` — hiç değer verilmeden yazılan satırda
   sekizi de `False` (**mockup ön-işaretleri sızmadı** regresyonu, §14.2)
4. `test_is_draft_defaults_to_false`
5. `test_safety_officer_is_outsourced_defaults_to_false`
6. `test_safety_officer_check_rejects_both` — `is_outsourced=True` + `user_id` dolu →
   `IntegrityError` (`ck_sites_safety_officer`)
7. `test_safety_officer_check_allows_fk_only` / `..._allows_outsourced_only` /
   `..._allows_neither` (üç geçerli dal)
8. `test_site_manager_user_delete_sets_null` — kullanıcı silinince FK `NULL`,
   `site_manager_name` **kalır** (`ON DELETE SET NULL`)
9. `test_safety_officer_user_delete_sets_null`
10. `test_no_new_column_is_non_nullable_without_default` — **kritik canlı-veri ağı**:
    22 kolonun her biri ya `nullable=True` ya `server_default` taşıyor
11. `test_section_has_manager_user_id` — `sections.manager_user_id` var, nullable, indexli
12. `test_section_manager_user_delete_sets_null` — `manager_name` anlık görüntüsü kalıyor
13. `test_section_has_no_estimated_amount_column` — **§3.4 kararının kilidi**;
    böyle bir kolon **YOK**
14. `test_no_latitude_longitude_columns` — §3.5 kararının kilidi; `gps_coordinates`
    `String(50)` **tek** kolon
15. `test_uq_sites_project_code_unchanged` — kısıt hâlâ `(project_id, code)`,
    global `UNIQUE` **değil** (§0.3/2)
16. `test_numeric_precisions_match_spec` — `land_area_m2`/`construction_area_m2`
    `Numeric(12,2)`, `budget` `Numeric(18,2)`

Migration (`test_sites_migration.py`):
17. `test_upgrade_downgrade_upgrade_round_trip` — round-trip; her adımda
    `information_schema.columns` ile 22+1 kolonun varlığı/yokluğu doğrulanır
18. `test_downgrade_drops_check_constraint` — `ck_sites_safety_officer`
    `pg_constraint`'te kalmıyor
19. `test_existing_rows_survive_upgrade` — upgrade **öncesi** yazılmış eksik alanlı bir
    `sites` satırı upgrade sonrası **duruyor** ve tesisleri `false` (§11.2 kanıtı)

**KIRMIZI GÖR:** `AttributeError: 'Site' object has no attribute 'neighborhood'` vb. ile
19 test kırmızı.

**Dokunulacak/oluşturulacak dosyalar:**
- `backend/app/modules/sites/models.py` (değişiklik — 22 + 1 kolon, `ck_sites_safety_officer`)
- `backend/alembic/versions/<hash>_santiye_formu_genislemesi.py` (yeni)
- `backend/tests/modules/sites/test_site_model.py` (genişletme)
- `backend/tests/modules/sites/test_sites_migration.py` (yeni)

**Uygulama notları:**
- Kolon listesi spec §3.0 tablosundan **birebir**; sıra da o tablodaki sıra.
- İki FK: `site_manager_user_id`, `safety_officer_user_id` → `users.id`
  **`ON DELETE SET NULL` + index**. `sections.manager_user_id` aynı.
- **`NOT NULL` yalnız** 8 tesis + `safety_officer_is_outsourced` + `is_draft` (onlarda da
  `server_default=text("false")`). Diğer 12 kolon `NULL` (§0.3/1).
- Numeric hassasiyetleri **model ve migration'da AYNI** — sapma sessiz yuvarlama hatası üretir.
- Migration `down_revision` = T1'in revizyonu.
- Silme uçları migration **gerektirmez**: dört `CASCADE` FK **olduğu gibi kalır**,
  koruma servis katmanındadır (§11.1). `RESTRICT`'e çevirmek **bilinçli olarak yapılmaz**.

**Kabul kriteri:**
- 19 test yeşil
- Test 10 (`NOT NULL` ağı) ve test 13/14/15 (karar kilitleri) yeşil
- `alembic heads` → tek head
- Mevcut `tests/modules/sites/` paketinin tamamı **değiştirilmeden** yeşil
- `ruff` iki kapı da `0`

**Kapı komutu:**
```bash
cd /Users/furkanilgen/Documents/Projeler/insaat/backend
createdb snt_form_t2 && \
  TEST_DATABASE_URL="postgresql+asyncpg://furkanilgen@localhost:5432/snt_form_t2" \
  .venv/bin/pytest tests/modules/sites tests/modules/test_seed_matrix.py -x
dropdb snt_form_t2
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/alembic heads
```

**Geri alma:** `downgrade` — test 17/18 ile doğrulanmıştır. Kolonlar düşer, `CHECK` düşer,
enum T1'in revizyonunda olduğu için etkilenmez. Kod tarafında model satırları çıkarılır.

---

### T3 — `_next_site_code` (global, maksimum+1) + `derive_code`/`_unique_code` kaldırılması  ⚠️ RİSKLİ

| | |
|---|---|
| Boyut | **M** |
| Bağımlı | T2 |
| Risk | **Kod üreticisi değişimi.** `projects.service._write_inline_sites` de bu üreticiyi çağırıyor → P1.1a proje formu akışı kırılabilir. Canlıdaki mevcut kodlar **hiç değişmemeli**. |

**Önce yazılacak testler** — `tests/modules/sites/test_site_code.py` (yeniden yazılır)

1. `test_next_site_code_on_empty_table` → `SNT-{bu_yıl}-001`
2. `test_next_site_code_is_max_plus_one` — `003` varken → `004`
3. `test_next_site_code_after_deletion_does_not_reuse` — `003` silinmişken **yine `004`**
   (maksimum+1, **sayım değil**)
4. `test_legacy_derived_codes_do_not_affect_counter` — `A-BLOK`, `MERKEZ` varken
   sayaç etkilenmez (`LIKE 'SNT-{yıl}-%'` onları görmez)
5. `test_next_site_code_is_global_across_projects` — A projesinde `SNT-{yıl}-001` varken
   **B projesinde** üretilen kod `SNT-{yıl}-002` (**`001` tekrar üretilmez**) — §3.2 global karar kilidi
6. `test_next_site_code_ignores_other_years` — `SNT-2025-050` bu yılın sayacını etkilemez
7. `test_explicit_code_is_not_overwritten` — kullanıcı `code` verirse **sessizce değiştirilmez**
8. `test_derive_code_removed` — `app.modules.sites.service` üzerinde `derive_code` ve
   `_unique_code` **YOK** (`hasattr` → `False`); tek üretici `_next_site_code`
9. `test_inline_site_creation_uses_new_generator` — `projects` POST'unda satır içi şantiye
   → kodu `SNT-{yıl}-NNN` (P1.1a geriye uyum, §12.2/16)
10. `test_existing_site_codes_untouched` — üretici çağrıldıktan sonra mevcut satırların
    `code` değerleri **değişmemiş** (hiç `UPDATE` yazılmadığının kanıtı)

**KIRMIZI GÖR:** `ImportError: cannot import name '_next_site_code'` ile 10 test kırmızı.

**Dokunulacak/oluşturulacak dosyalar:**
- `backend/app/modules/sites/service.py` (değişiklik — `_next_site_code` eklenir;
  `_normalize`/`_slug`/`_strip_site_suffix`/`derive_code`/`_unique_code` **kaldırılır**)
- `backend/app/modules/sites/repository.py` (değişiklik — `list_codes_with_prefix` benzeri
  yardımcı; `app/modules/projects/repository.py:47` deseninin **birebiri**)
- `backend/app/modules/projects/service.py` (değişiklik — `_write_inline_sites` içindeki
  `from app.modules.sites.service import _unique_code, derive_code` satırı yeni üreticiye çevrilir)
- `backend/tests/modules/sites/test_site_code.py` (yeniden yazılır)

**Uygulama notları:**
- Sorgu **kapsam süzgeci taşımaz**: `select(Site.code).where(Site.code.like(f"{prefix}%"))` —
  `project_id` süzgeci **YOK** (§3.2, `PRJ-` emsalinin birebiri).
- `prefix = f"SNT-{today().year}-"`, `kod = f"{prefix}{max_seq + 1:03d}"`.
- Sayısal soneki ayrıştırılamayan kodlar **atlanır**, hata üretmez.
- **Hiçbir `UPDATE` yazılmaz** (§0.3/5). Test 10 bunu kilitliyor.
- Yarış durumunda `uq_sites_project_code` ihlali → mevcut `IntegrityError → 409`
  işleyicisi. **Otomatik yeniden deneme yapılmaz** (§8.3).

**Kabul kriteri:**
- 10 test yeşil
- `grep -n "derive_code\|_unique_code" app/` → **hiç eşleşme yok**
- `tests/modules/test_projects_create_b4.py` + `test_projects_create_b5.py` +
  `test_project_site_count.py` **değiştirilmeden** yeşil (P1.1a geriye uyum)

**Kapı komutu:**
```bash
createdb snt_form_t3 && \
  TEST_DATABASE_URL="postgresql+asyncpg://furkanilgen@localhost:5432/snt_form_t3" \
  .venv/bin/pytest tests/modules/sites tests/modules/test_projects_create_b4.py \
    tests/modules/test_projects_create_b5.py tests/modules/test_projects_api.py -x
dropdb snt_form_t3
grep -rn "derive_code\|_unique_code" app/ && echo "HATA: eski uretici duruyor" || echo "OK"
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

**Geri alma:** saf kod değişikliği; migration yok. Eski fonksiyonlar geri konur, iki çağrı
noktası eski hâline döner. **Canlı veri etkilenmez** (hiç `UPDATE` yazılmadı).

---

### T4 — Pydantic şemaları (giriş + çıkış) + `construction_area_m2`

| | |
|---|---|
| Boyut | **M** |
| Bağımlı | T2 |
| Risk | düşük-orta — çıkış şemasından **mevcut alan kaldırmak** P2 frontend'ini kırar |

**Önce yazılacak testler** — `tests/modules/sites/test_sites_schemas.py` (genişletme)

1. `test_facilities_input_all_default_false` — `SiteFacilitiesInput()` → sekizi de `False`
   (§14.2 kilidi)
2. `test_site_create_facilities_default_factory` — `facilities` hiç gönderilmezse sekizi `False`
3. `test_site_section_input_has_no_estimated_amount` — alan **YOK**; gövdede gelirse
   **sessizce yok sayılır** (§3.4, §12.2/8b)
4. `test_site_section_input_has_no_sort_order` — sıra gövdeden gelmez, diziden atanır
5. `test_site_create_defaults` — `status=active`, `is_draft=False`, `sections=[]`, `code=None`
6. `test_site_create_rejects_negative_areas` — `land_area_m2=-1` → `ValidationError`;
   `construction_area_m2=-1`, `budget=-1`, `planned_worker_count=-1` aynı
7. `test_site_create_accepts_construction_area_m2` — **§13/16 kilidi**: alan şemada var
8. `test_gps_is_free_text_no_validation` — `"abc"`, `"39,9042"`, `""` → **hepsi geçerli**
   (§3.5; 422 üretmiyor)
9. `test_gps_max_length_enforced` — 51 karakter → `ValidationError`
10. `test_floor_info_is_string_not_int` — `"2 bodrum + 10 normal"` geçerli
11. `test_site_update_all_fields_optional` — `SiteUpdate()` geçerli; `model_fields_set` boş
12. `test_site_update_has_no_project_id` — şantiye başka projeye taşınamaz
13. `test_site_update_has_no_sections` — bölümler P2 uçlarıyla yönetilir (§7.3)
14. `test_site_update_tracks_unset_vs_null` — "gönderilmedi" ≠ "null yapıldı"
15. `test_site_card_keeps_all_p2_fields` — **geriye uyum ağı**: P2'deki `SiteCard`
    alanlarının **hiçbiri kaldırılmamış/yeniden adlandırılmamış**
16. `test_site_card_has_sixteen_new_fields` — spec §6.2 listesi **tek tek**
17. `test_site_counts_has_draft` — `SiteCounts.draft: int`
18. `test_section_response_has_manager_user_id`
19. `test_section_response_budget_is_metric_placeholder_boq` — `pending_module == "boq"`,
    `available is False` (§14.3 kilidi)
20. `test_section_response_has_no_estimated_amount`
21. `test_metric_placeholder_imported_not_redefined` — sınıf
    `app.modules.projects.schemas.MetricPlaceholder`'ın **ta kendisi** (`is` kontrolü)
22. `test_no_duration_days_field_anywhere` — süre **türevdir**, yanıtta alan **yok** (§3.6)

**KIRMIZI GÖR:** `ImportError: cannot import name 'SiteFacilitiesInput'` ile 22 test kırmızı.

**Dosyalar:**
- `backend/app/modules/sites/schemas.py` (genişletme)
- `backend/tests/modules/sites/test_sites_schemas.py` (genişletme)

**Uygulama notları:**
- Şema gövdeleri spec §6.1/§6.2'den **birebir**; alan sırası da oradaki sıra.
- API'de tesisler **gruplu** (`facilities: {...}`), DB'de **düz 8 kolon** (§4.1).
  Dönüşüm servis katmanında; şema kendi başına DB bilmez.
- `site_manager_name` ve `delivery_date` gövdede **KALIR** (P2/P1.1a mirası).
- `MetricPlaceholder`/`CountPlaceholder` `projects.schemas`'tan **import** edilir,
  kopyalanmaz (test 21 kilitliyor).

**Kabul kriteri:** 22 test yeşil; `SiteCard` alan listesi spec §6.2 ile **birebir**
(eksik/fazla alan yok); mevcut `tests/modules/sites/test_sites_api.py` **değişmeden** yeşil.

**Kapı komutu:**
```bash
createdb snt_form_t4 && \
  TEST_DATABASE_URL="postgresql+asyncpg://furkanilgen@localhost:5432/snt_form_t4" \
  .venv/bin/pytest tests/modules/sites -x
dropdb snt_form_t4
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

**Geri alma:** tek dosya genişlemesi; eklenen sınıf/alanlar çıkarılır. DB değişmedi.

---

### T5 — `_validate_site` + taslak-farkındalıklı doğrulama + `SiteValidationError`

| | |
|---|---|
| Boyut | **M** |
| Bağımlı | T4 |
| Risk | orta — **tutarlılık/zorunluluk ayrımı** yanlış kurulursa ya taslak bozuk veri saklar ya canlı kayıtlar düzenlenemez olur |

**Önce yazılacak testler** — `tests/modules/sites/test_site_validation.py` (yeni)

Spec §5.1 tablosunun **her satırı**, taslak ve taslak-dışı için **ayrı ayrı**:

1. `test_name_required_in_draft` / `test_name_required_in_published` (Pydantic `min_length=1`)
2. `test_end_before_start_rejected_in_draft` — **taslakta da** 422
   `Planlanan bitiş tarihi başlangıçtan önce olamaz.`
3. `test_end_before_start_rejected_in_published`
4. `test_section_end_before_start_rejected_in_draft` → `2. bölüm: bitiş tarihi
   başlangıçtan önce olamaz.` (**`{n}` 1-tabanlı**)
5. `test_section_name_blank_rejected_in_draft` → `{n}. bölüm: bölüm adı zorunludur.`
6. `test_negative_amounts_rejected_in_both` (Pydantic `ge=0`)
7. `test_gps_never_validated` — `"abc"` taslakta da yayında da **geçer** (§3.5)
8. `test_safety_officer_mutual_exclusion_in_draft` — FK+OSGB → 422
   `İSG uzmanı ya sistem kullanıcısı ya dış kaynak (OSGB) olabilir.`
9. `test_safety_officer_never_required` — **§13/6 kilidi**: taslak-dışı, İSG'siz tam gövde
   → **geçerli** (hiçbir koşulda zorunlu değil)
10. `test_site_manager_required_only_when_published` → taslakta geçer; yayında 422
    `Şantiye şefi seçiniz.`
11. `test_city_required_only_when_published` → `İl / ilçe zorunludur.`
12. `test_construction_area_required_only_when_published` → `İnşaat alanı zorunludur.`
13. `test_dates_required_only_when_published` → `Başlangıç ve planlanan bitiş tarihi zorunludur.`
14. `test_validation_stops_at_first_section_error` — çok satırlı hata listesi **üretilmez**
    (form 2–5 satırlık; `UnitImportError` deseni **kullanılmaz**, §8.2)
15. `test_site_validation_error_maps_to_422` — `SiteValidationError` → HTTP 422

**KIRMIZI GÖR:** `ImportError: SiteValidationError` ile 15 test kırmızı.

**Dosyalar:**
- `backend/app/core/errors.py` (değişiklik — `SiteValidationError(DomainError)`;
  `ProjectValidationError`/`UnitValidationError` deseninin **aynısı**)
- `backend/app/modules/sites/guards.py` (yeni — `_validate_site` + Türkçe mesaj sabitleri;
  `app/modules/units/guards.py` deseni)
- `backend/tests/modules/sites/test_site_validation.py` (yeni)

**Uygulama notları:**
- **Kural:** tutarlılık kuralları **her zaman**, zorunluluk kuralları **yalnız taslak-dışında**.
  Yarım kalmış taslak asla geçersiz veri saklamaz, yalnız **eksik** veri saklar.
- Mesajlar spec §7.2 tablosundan **birebir** kopyalanır, yeniden yazılmaz.
- 409 için **yeni sınıf açılmaz**: mevcut `RelatedRecordsExistError` ve `DuplicateError` kullanılır.
- **GPS kuralı yazılmaz** — spec'ten "GPS biçim hatası" satırı bilinçle kaldırıldı.

**Kabul kriteri:** 15 test yeşil; §5.1 tablosunun **11 satırının 11'i** en az bir testle
karşılanmış (task raporunda satır↔test eşleme tablosu verilir); §7.2'deki 14 Türkçe mesaj
sabiti kodda **birebir** mevcut.

**Kapı komutu:**
```bash
createdb snt_form_t5 && \
  TEST_DATABASE_URL="postgresql+asyncpg://furkanilgen@localhost:5432/snt_form_t5" \
  .venv/bin/pytest tests/modules/sites -x
dropdb snt_form_t5
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

**Geri alma:** `guards.py` silinir, `errors.py`'den tek sınıf çıkarılır.

---

### T6 — POST genişlemesi + bölümlerin atomik yazımı + şef/İSG kullanıcı çözümü  ⚠️ RİSKLİ

| | |
|---|---|
| Boyut | **L** |
| Bağımlı | T3, T5 |
| Risk | **Atomiklik.** Şantiye yazılıp bölüm patlarsa kısmi veri kalırsa bu sessiz veri hatasıdır. Ayrıca yeni IDOR yüzeyi (üç `*_user_id`). |

**Önce yazılacak testler** — `tests/modules/sites/test_sites_create.py` (yeni)

Mutlu yol + alanlar:
1. `test_post_minimum_body_draft_returns_201` — yalnız `name` + `is_draft=true` → 201,
   kod üretildi, **tüm tesisler `false`**
2. `test_post_full_mockup_body_returns_201` — mockup'ın **tüm** alanları; 20 alanın hepsi
   GET ile geri okunuyor
3. `test_post_status_preparation_returns_201` — yeni enum değeri
4. `test_post_construction_area_round_trips` — §13/16 regresyonu
5. `test_post_facilities_grouped_body_maps_to_columns` — `facilities: {...}` → 8 kolon
6. `test_post_omitted_facilities_all_false` — §14.2 regresyonu

Bölümler:
7. `test_post_with_three_sections_assigns_sort_order_0_1_2`
8. `test_post_section_manager_user_id_persisted_with_name_snapshot`
9. `test_post_section_estimated_amount_silently_ignored` — gövdede gelirse yok sayılır;
   `SectionResponse`'ta böyle alan **yok**, `budget` yer tutucu geliyor (§3.4)
10. `test_post_without_sections_creates_none` — sıfır bölüm geçerli

Şef / İSG çözümü:
11. `test_site_manager_name_snapshot_overwritten_from_user` — FK doluysa servis
    `users.full_name`i **üzerine yazar**
12. `test_safety_officer_outsourced_writes_fixed_label` — OSGB seçilince
    `safety_officer_name == "Dış Kaynak — OSGB"`
13. `test_unknown_manager_user_returns_422` → `Seçilen kullanıcı bulunamadı`
    (**404 değil** — kaynak şantiyedir, kullanıcı değil); **yazma yok**
14. `test_inactive_user_returns_422`

Atomiklik (§12.4):
15. `test_post_three_sections_second_invalid_writes_nothing` → 422 `2. bölüm: …`;
    DB'de **ne şantiye ne bölüm** var (öncesi/sonrası `count(*)` eşit)
16. `test_post_duplicate_code_writes_no_sections` → 409; `sections` tablosunda yeni satır **yok**
17. `test_post_blank_section_name_writes_nothing` → 422, hiçbir şey yazılmadı

İzin/görünürlük:
18. `test_post_requires_full_permission` — `sites:view` → **403**
19. `test_post_invisible_project_returns_404` → `Proje bulunamadı`

**KIRMIZI GÖR:** yeni alanlar servis tarafından yazılmadığı için 19 test kırmızı
(`KeyError` / alan `None` / 500). Çıktı raporda.

**Dosyalar:**
- `backend/app/modules/sites/service.py` (genişletme — `create_site`)
- `backend/app/modules/sites/repository.py` (genişletme — kullanıcı çözümü yardımcısı)
- `backend/app/modules/sites/router.py` (genişletme)
- `backend/tests/modules/sites/test_sites_create.py` (yeni)

**Uygulama notları:**
- Akış spec §8.1'deki **dokuz adım**, o sırayla. Doğrulama **yazmadan ÖNCE**, tek seferde,
  tüm bölüm satırları için.
- Atomiklik `get_db`'nin **istek başına tek transaction**'ından gelir; herhangi bir
  istisna → `rollback` → hiçbir satır yazılmaz. `_write_inline_sites` deseninin birebiri.
- **`sections` izni ARANMAZ**: bölüm şantiyenin iç kırılımıdır, `sites:full` ikisini kapsar.
- Kullanıcı çözümünde "bu kullanıcıyı görme yetkin var mı" **aranmaz**; yalnız
  var/aktif kontrolü (§9).
- Görünmeyen proje → **404**, gövde ayırt edici **değil**.

**Kabul kriteri:** 19 test yeşil; test 15/16/17 atomikliği **sayımla** kanıtlıyor;
mevcut `test_sites_api.py` + `test_sites_service.py` **değişmeden** yeşil.

**Kapı komutu:**
```bash
createdb snt_form_t6 && \
  TEST_DATABASE_URL="postgresql+asyncpg://furkanilgen@localhost:5432/snt_form_t6" \
  .venv/bin/pytest tests/modules/sites -x
dropdb snt_form_t6
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

**Geri alma:** servis/rota genişlemeleri geri alınır; şema ve DB değişmedi.

---

### T7 — PATCH genişlemesi + `is_draft` yayına geçiş kuralı

| | |
|---|---|
| Boyut | **M** |
| Bağımlı | T5 |
| Risk | orta — **PATCH'te tam doğrulama koşarsa canlı kayıtlar düzenlenemez olur** (§0.3/3) |

**Önce yazılacak testler** — `tests/modules/sites/test_sites_update.py` (yeni)

1. `test_patch_single_field_changes_only_that_field` (`exclude_unset`)
2. `test_patch_all_new_fields_round_trip`
3. `test_patch_facilities_partial_merge` — gönderilen tesis grubu bütün olarak yazılır,
   gönderilmezse **dokunulmaz**
4. `test_patch_does_not_run_full_validation` — **§0.3/3 kilidi**: şefsiz + şehirsiz +
   tarihsiz canlı kayıtta yalnız `name` değiştirmek **200** döner
5. `test_patch_still_runs_consistency_rules` — `end < start` → 422 (tutarlılık her zaman)
6. `test_patch_safety_officer_mutual_exclusion_enforced` → 422
7. `test_patch_publish_with_complete_record_returns_200` — `is_draft: false` + tam kayıt
8. `test_patch_publish_with_missing_fields_returns_422_and_stays_draft` — **birleşik kayıt**
   (mevcut satır + patch) üzerinde §5.1'in 7–11 kuralları koşar; geçmezse satır
   **taslak kalır** (DB'den yeniden okunarak doğrulanır)
9. `test_patch_publish_merges_existing_row_with_patch` — eksik alan **patch'te** geliyorsa
   yayına geçiş **başarılı**
10. `test_patch_draft_true_to_true_no_publish_rule`
11. `test_patch_has_no_project_id` — gövdede gelirse yok sayılır; şantiye taşınmaz
12. `test_patch_sections_not_accepted` — bölümler P2 uçlarıyla yönetilir
13. `test_patch_manager_user_updates_name_snapshot`
14. `test_patch_requires_full_permission` → 403
15. `test_patch_invisible_site_returns_404` → `Şantiye bulunamadı`; var olmayan UUID ile
    **birebir aynı gövde**
16. `test_patch_section_manager_user_id` — `PATCH /sections/{id}` yeni alanı kabul ediyor
17. `test_post_section_manager_user_id` — `POST /sites/{id}/sections` yeni alanı kabul ediyor

**KIRMIZI GÖR:** yeni alanlar PATCH'te yazılmadığı için kırmızı.

**Dosyalar:**
- `backend/app/modules/sites/service.py` (genişletme — `update_site`, `create_section`,
  `update_section`)
- `backend/app/modules/sites/router.py` (genişletme)
- `backend/tests/modules/sites/test_sites_update.py` (yeni)

**Uygulama notları:**
- Yayına geçiş dışında **zorunluluk doğrulaması koşulmaz** (§5.3). Test 4 bunu kilitliyor.
- `is_draft: true → false` geçişi denetim günlüğüne **ayrı satır** yazar — çağrısı T12'de.
- `model_fields_set` ile "gönderilmedi" ≠ "null yapıldı".

**Kabul kriteri:** 17 test yeşil; test 4 ve 8 birlikte "PATCH gevşek ama yayın sıkı"
kuralını kanıtlıyor.

**Kapı komutu:**
```bash
createdb snt_form_t7 && \
  TEST_DATABASE_URL="postgresql+asyncpg://furkanilgen@localhost:5432/snt_form_t7" \
  .venv/bin/pytest tests/modules/sites -x
dropdb snt_form_t7
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

**Geri alma:** servis genişlemeleri geri alınır.

---

### T8 — Okuma uçlarının genişlemesi + `SiteCounts.draft`

| | |
|---|---|
| Boyut | **S** |
| Bağımlı | T4 |
| Risk | düşük — tek risk **mevcut alanı kaldırmak** (P2 frontend'i kırar) |

**Önce yazılacak testler** — `tests/modules/sites/test_sites_api.py` (genişletme)

1. `test_list_response_includes_new_fields` — `SiteCard`'ın 16 yeni alanı listede
2. `test_detail_response_includes_new_fields`
3. `test_list_counts_draft_is_correct`
4. `test_draft_sites_visible_to_everyone_with_project_access` — §13/13 kararı;
   "yalnız benim taslaklarım" kavramı **yok**
5. `test_draft_not_subtracted_from_status_counts` — taslak, durumu neyse o sayaçta **kalır**;
   yalnız `draft` sayacı ayrıca artar
6. `test_section_response_includes_manager_user_id`
7. `test_section_budget_placeholder_pending_boq`
8. `test_no_duration_days_in_response` — §3.6
9. `test_p2_contract_fields_still_present` — **geriye uyum ağı**: eski alanların hiçbiri
   kaybolmadı/yeniden adlandırılmadı
10. `test_facilities_returned_grouped` — yanıt `facilities: {...}` iç içe (§4.1)

**KIRMIZI GÖR:** yanıt alanları eksik → `KeyError` ile kırmızı.

**Dosyalar:**
- `backend/app/modules/sites/service.py` (genişletme — `_card_fields`, `to_card`,
  `to_detail`, `to_section`, `_site_counts`)
- `backend/tests/modules/sites/test_sites_api.py` (genişletme)

**Uygulama notları:**
- Mevcut alanların hiçbiri **kaldırılmaz/yeniden adlandırılmaz** (§6.2).
- `_site_counts`'a **tek ekleme** yapılır; mevcut davranış korunur.
- `_remaining_days` ve `_resolve_city` **dokunulmaz** (P2 mirası).

**Kabul kriteri:** 10 test yeşil; `test_sites_repository.py`/`test_sites_permissions.py`
**değişmeden** yeşil.

**Kapı komutu:**
```bash
createdb snt_form_t8 && \
  TEST_DATABASE_URL="postgresql+asyncpg://furkanilgen@localhost:5432/snt_form_t8" \
  .venv/bin/pytest tests/modules/sites -x
dropdb snt_form_t8
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

**Geri alma:** dönüştürücü fonksiyonlardan eklenen alanlar çıkarılır.

---

### T9 — Repository korkuluk sorguları (`site_has_sections` / `_boq` / `_blocks`)  ⚠️ RİSKLİ

| | |
|---|---|
| Boyut | **S** |
| Bağımlı | T2 |
| Risk | **T10'un tek güvencesi.** Bu üç sorgu yanlış yazılırsa (ör. `boq_groups` unutulursa) korkuluk delinir ve cascade tetiklenir. |

**Önce yazılacak testler** — `tests/modules/sites/test_site_delete_guards.py` (yeni)

1. `test_site_has_sections_true_when_section_exists`
2. `test_site_has_sections_false_when_empty`
3. `test_site_has_boq_true_for_boq_item`
4. `test_site_has_boq_true_for_boq_group_without_items` — **grup tek başına da engeldir**
   (spec §7.1: "`boq_items` **veya** `boq_groups`")
5. `test_site_has_boq_false_when_empty`
6. `test_site_has_blocks_true_when_block_exists`
7. `test_site_has_blocks_false_when_empty`
8. `test_guards_scoped_to_the_given_site` — **başka** şantiyenin bölümü/pozu/bloğu
   `True` döndürmez (kapsam sızıntısı ağı)
9. `test_guards_use_exists_and_fetch_no_rows` — sorgular `EXISTS` kullanıyor, satır çekmiyor
   (`app/modules/units/repository.py:97 block_has_units` deseni)

**KIRMIZI GÖR:** `ImportError: cannot import name 'site_has_sections'` ile 9 test kırmızı.

**Dosyalar:**
- `backend/app/modules/sites/repository.py` (genişletme — üç fonksiyon)
- `backend/tests/modules/sites/test_site_delete_guards.py` (yeni)

**Uygulama notları:**
- `block_has_units` deseni **birebir**: `select(exists().where(...))`, satır çekilmez.
- `boq` ve `units` modelleri import edilir — **döngüsel import** riskine dikkat;
  gerekiyorsa fonksiyon içi import (repoda mevcut desen: `projects/service.py:401`).
- Bu task'ta **hiçbir uç açılmaz**; yalnız sorgular.

**Kabul kriteri:** 9 test yeşil; `grep -n "exists(" app/modules/sites/repository.py` →
üç eşleşme.

**Kapı komutu:**
```bash
createdb snt_form_t9 && \
  TEST_DATABASE_URL="postgresql+asyncpg://furkanilgen@localhost:5432/snt_form_t9" \
  .venv/bin/pytest tests/modules/sites -x
dropdb snt_form_t9
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

**Geri alma:** üç fonksiyon silinir; hiçbir çağrısı yok (T10 henüz yazılmadı).

---

### T10 — `DELETE /sites/{site_id}` — servis + korkuluk + uç  ⚠️⚠️ EN RİSKLİ

| | |
|---|---|
| Boyut | **M** |
| Bağımlı | **T9 (PAZARLIK DIŞI)**, T8 |
| Risk | **VERİ KAYBI SINIFI.** Korkuluksuz tek istek bölümleri, poz gruplarını, poz kalemlerini ve blokları **sessizce** siler (§0.1). Geri alınamaz. |

> **T9 bitmeden bu task'a BAŞLANMAZ.** Korkuluk sorguları yoksa yazılan `DELETE`
> dört `CASCADE` FK üzerinden veri siler ve bu, testler yazılana kadar fark edilmez.

**Önce yazılacak testler** — `tests/modules/sites/test_sites_delete.py` (yeni) — spec §12.3

1. `test_delete_empty_site_returns_204` (S1) — ardından GET → 404
2. `test_delete_site_with_section_returns_409` (S2) →
   `Bu şantiyede bölüm var, önce bölümleri silin`
3. `test_delete_site_with_section_leaves_site_and_sections_intact` (S2 asıl amacı) —
   **409 sonrası `sites` ve `sections` sayımları DEĞİŞMEMİŞ** (cascade tetiklenmedi kanıtı)
4. `test_delete_site_with_boq_item_returns_409` (S3) →
   `Bu şantiyede iş kalemi var, önce iş kalemlerini silin`; `boq_items` sayımı sabit
5. `test_delete_site_with_boq_group_only_returns_409` — grup tek başına da engel
6. `test_delete_site_with_block_returns_409` (S4) →
   `Bu şantiyede blok var, önce blokları silin`; `blocks` **ve** `units` sayımları sabit
7. `test_delete_draft_site_with_section_returns_409` (S5) — **taslağa ayrıcalık yok**
8. `test_delete_stops_at_first_blocker` — bölüm + poz + blok birlikteyken **yalnız bölüm
   mesajı** döner (tek, eyleme dönük mesaj)
9. `test_delete_error_message_omits_counts` — mesajda **sayı yok** (`BLOCK_HAS_UNITS` dersi)
10. `test_delete_after_removing_sections_returns_204` (S9) — korkuluk **kalıcı kilit üretmiyor**
11. `test_delete_returns_204_with_empty_body`

**KIRMIZI GÖR:** uç tanımsız → **405/404** ile kırmızı. Bu 404'ü domain 404'üyle
karıştırmamak için testler **gövde mesajını** de doğrular.

**Dosyalar:**
- `backend/app/modules/sites/service.py` (genişletme — `delete_site`)
- `backend/app/modules/sites/router.py` (genişletme — `_ADMIN` kapısı)
- `backend/tests/modules/sites/test_sites_delete.py` (yeni)

**Uygulama notları:**
- İzin: `require_permission("sites", AccessLevel.admin)` —
  `app/modules/units/router.py:181,206` deseninin **birebiri**. `_ADMIN` sabiti modül
  başında tanımlanır ve **neden `full` değil** olduğu yorumda yazılır.
- **Sıra:** (1) görünürlük süzgeci → 404, (2) `site_has_sections` → 409,
  (3) `site_has_boq` → 409, (4) `site_has_blocks` → 409, (5) denetim metni kur, (6) sil.
  **İlk engelde durur.**
- Hata sınıfı `RelatedRecordsExistError` → 409. `DeleteNotAllowedError` **kullanılmaz**
  (o yetki engelidir).
- Yanıt `204 No Content`, **gövdesiz**.
- Denetim çağrısı T12'de eklenir ama **metnin silmeden önce kurulması** kuralı burada
  hazırlanır (yerel değişkene `project.name` + `site.name` alınır).
- **Yumuşak silme (`deleted_at`) açılmaz** — repoda böyle bir desen yok.

**Kabul kriteri:**
- 11 test yeşil
- Test 3/4/6 **sayımla** cascade'in tetiklenmediğini kanıtlıyor — bu üç test olmadan
  task **kapanmaz**
- `boq` ve `units` test paketleri **değişmeden** yeşil

**Kapı komutu:**
```bash
createdb snt_form_t10 && \
  TEST_DATABASE_URL="postgresql+asyncpg://furkanilgen@localhost:5432/snt_form_t10" \
  .venv/bin/pytest tests/modules/sites tests/modules/units tests/modules/test_boq_api.py -x
dropdb snt_form_t10
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

**Geri alma:** tek rota fonksiyonu + tek servis fonksiyonu çıkarılır. **DB'de değişiklik
yok** (FK davranışları bilinçli olarak `CASCADE` bırakıldı, §11.1).

---

### T11 — `DELETE /sections/{section_id}` — servis + uç

| | |
|---|---|
| Boyut | **S** |
| Bağımlı | T8 (**T9'a bağlı DEĞİL** — T10 ile paralel yürüyebilir) |
| Risk | düşük — `sections.id`'yi hedefleyen **hiçbir FK yok** (doğrulandı) |

**Önce yazılacak testler** — `tests/modules/sites/test_sites_delete.py` (genişletme)

1. `test_delete_section_returns_204` (S8) — şantiye ve **diğer bölümler yerinde**
2. `test_delete_section_twice_returns_404`
3. `test_delete_section_does_not_touch_site` — `sites` sayımı sabit
4. `test_delete_section_reorders_nothing` — kalan bölümlerin `sort_order` değerleri
   **yeniden numaralanmaz** (davranış kilidi; sessiz sürpriz olmasın)
5. `test_delete_section_returns_empty_body`

**KIRMIZI GÖR:** uç tanımsız → 405 ile kırmızı.

**Dosyalar:**
- `backend/app/modules/sites/service.py` (genişletme — `delete_section`)
- `backend/app/modules/sites/router.py` (genişletme — `_ADMIN`)
- `backend/tests/modules/sites/test_sites_delete.py` (genişletme)

**Uygulama notları:**
- Silme **koşulsuzdur**; uydurma engel yazılmaz.
- **Gelecek-korkuluk yorumu zorunlu** — `delete_section` içine tek satır:
  ```
  # P5 notu: boq_groups.section_id gelirse buraya section_has_boq korkuluğu EKLENMELİ.
  ```
  Bu satır spec §7.1'in açık talebidir, atlanmaz.
- Görünürlük süzgeci **önce**: görünmeyen bölüm → 404 `Bölüm bulunamadı`.

**Kabul kriteri:** 5 test yeşil; gelecek-korkuluk yorumu kodda mevcut
(`grep -n "section_has_boq" app/modules/sites/service.py` → eşleşme var).

**Kapı komutu:**
```bash
createdb snt_form_t11 && \
  TEST_DATABASE_URL="postgresql+asyncpg://furkanilgen@localhost:5432/snt_form_t11" \
  .venv/bin/pytest tests/modules/sites -x
dropdb snt_form_t11
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

**Geri alma:** tek rota + tek servis fonksiyonu çıkarılır. DB değişmedi.

---

### T12 — Denetim mesajları (5 yeni fonksiyon + çağrılar)

| | |
|---|---|
| Boyut | **M** |
| Bağımlı | T6, T7, **T10**, **T11** |
| Risk | orta — **silme metni satır silinmeden ÖNCE kurulmazsa** silinen kaydın ne olduğu tamamen kaybolur |

**Önce yazılacak testler** — `tests/modules/sites/test_sites_audit.py` (yeni)

1. `test_site_create_writes_site_created` — `AuditAction.create`,
   `Yeni şantiye oluşturuldu: {name}` (mevcut fonksiyon korunuyor)
2. `test_draft_create_writes_site_draft_created` —
   `Yeni şantiye taslağı oluşturuldu: {name}`
3. `test_sections_create_writes_one_summary_row` — 5 bölümlü form **6 satır değil 2 satır**
   üretir; metin `Şantiye bölümleri oluşturuldu: {site} · {count} bölüm`
4. `test_patch_writes_site_updated`
5. `test_publish_writes_site_published` — `Şantiye taslaktan yayına alındı: {name}`
6. `test_delete_site_writes_site_deleted` — `Şantiye silindi: {project} · {name}`
7. `test_delete_site_audit_text_contains_deleted_site_name` — **metnin silmeden önce
   kurulduğunun kanıtı** (S6); ad boş **değil**
8. `test_delete_section_writes_section_deleted` — `Bölüm silindi: {site} · {name}`
9. `test_failed_delete_writes_no_audit` (S7) — 409 dönen silme denemesi günlüğe
   **hiçbir şey yazmadı**
10. `test_failed_create_writes_no_audit` — 422/409 ile reddedilen POST yazmaz
11. `test_read_endpoints_write_no_audit` — GET liste/detay sonrası `audit_log` büyümedi
12. `test_audit_rows_carry_actor_and_ip`
13. `test_section_created_updated_messages_unchanged` — mevcut iki metin **değişmedi**

**KIRMIZI GÖR:** `ImportError: cannot import name 'site_deleted'` ile 13 test kırmızı.

**Dosyalar:**
- `backend/app/modules/audit/messages.py` (genişletme — spec §10'daki **5 yeni fonksiyon**:
  `site_draft_created`, `site_sections_created`, `site_published`, `site_deleted`,
  `section_deleted`)
- `backend/app/modules/sites/service.py` / `router.py` (genişletme — `record_audit` çağrıları)
- `backend/tests/modules/sites/test_sites_audit.py` (yeni)

**Uygulama notları:**
- Metinler spec §10 tablosundan **birebir kopyalanır**; yeniden yazılmaz.
- Mesajlar `audit/messages.py`'de **merkezi**; f-string'ler router içine gömülmez.
- **Silme metni `session.delete`'ten ÖNCE kurulur** (`units/service.py:327` dersi).
  Test 7 bunu kilitliyor — bu, silme denetiminin en kolay kaçırılan ayrıntısıdır.
- Bölümlü oluşturmada **bölüm başına ayrı satır yazılmaz**; tek özet satır
  (`units_bulk_created` deseni).
- Taslak oluşturma ile yayın oluşturma **ayrı metinlerdir**.

**Kabul kriteri:** 13 test yeşil; `messages.py`'ye **tam 5** fonksiyon eklenmiş; mevcut
audit testleri (`test_audit_api.py`, `test_audit_service.py`, `test_audit_export.py`)
**değişmeden** yeşil.

**Kapı komutu:**
```bash
createdb snt_form_t12 && \
  TEST_DATABASE_URL="postgresql+asyncpg://furkanilgen@localhost:5432/snt_form_t12" \
  .venv/bin/pytest tests/modules/sites tests/modules/test_audit_api.py \
    tests/modules/test_audit_service.py tests/modules/test_audit_export.py -x
dropdb snt_form_t12
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

**Geri alma:** `record_audit` çağrıları ve 5 mesaj fonksiyonu çıkarılır; DB değişmedi
(`audit_log` tablosu zaten vardı).

---

### T13 — Test seti: birim + entegrasyon + atomiklik (§12.1, §12.2, §12.4)

| | |
|---|---|
| Boyut | **M** |
| Bağımlı | T6, T7, T8 |
| Risk | düşük |

Bu task **boşlukları kapatır**: T3–T8 kendi testlerini yazdı, T13 spec §12.1/§12.2/§12.4
listesinden **karşılanmamış** kalan maddeleri ekler ve **satır↔test eşleme tablosunu** üretir.

**Yazılacak testler** — `tests/modules/sites/test_sites_form_coverage.py` (yeni)

Spec §12.1 (birim) 1–5b ve §12.2 (entegrasyon) 6–17b maddelerinden T3–T8'de
karşılanmamış olanlar; en az şunlar:

1. `test_site_manager_snapshot_survives_user_deletion` (§12.2/15) — FK `NULL` oldu,
   **ad kaldı**
2. `test_safety_officer_snapshot_survives_user_deletion`
3. `test_p2_response_contract_unbroken` (§12.2/17) — P2 döneminden kalma tam bir yanıt
   şekli alan alan karşılaştırılıyor
4. `test_inline_site_flow_still_works_end_to_end` (§12.2/16) — P1.1a proje formu satır içi
   şantiye akışı çalışıyor **ve** artık `SNT-` kodu üretiyor
5. `test_duration_days_absent_from_all_responses` (§12.1/5)
6. Spec §12.4 atomiklik 18–20'den T6'da karşılanmayan kalan varyantlar

**Dosyalar:** `backend/tests/modules/sites/test_sites_form_coverage.py` (yeni)

**Uygulama notları:** Bu task **uygulama kodu yazmaz** — kırmızı çıkan test varsa ilgili
task'ın (T3–T8) uygulama kodu **düzeltilir**, testler gevşetilmez.

**Kabul kriteri:** §12.1'in **8 maddesinin 8'i** ve §12.2'nin **19 maddesinin 19'u** ve
§12.4'ün **3 maddesinin 3'ü** en az bir testle karşılanmış; **eşleme tablosu task raporunda**.

**Kapı komutu:**
```bash
createdb snt_form_t13 && \
  TEST_DATABASE_URL="postgresql+asyncpg://furkanilgen@localhost:5432/snt_form_t13" \
  .venv/bin/pytest tests/modules/sites tests/modules/test_projects_api.py -x
dropdb snt_form_t13
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

**Geri alma:** yalnız test dosyası; **geri alınmaz** (regresyon değeri var).

---

### T14 — Silme testleri S1–S9 tamamlanması  ⚠️ RİSKLİ

| | |
|---|---|
| Boyut | **S** |
| Bağımlı | T10, T11, T12 |
| Risk | **Kanıt sınıfı.** S2–S4 cascade'in tetiklenmediğinin **tek** kanıtıdır. |

**Yazılacak testler** — `tests/modules/sites/test_sites_delete.py` (genişletme)

Spec §12.3'ün **dokuz maddesinin dokuzu** (S1–S9) T10/T11/T12'de karşılanmayanlar
tamamlanır ve **S↔test eşleme tablosu** üretilir. Özellikle:

- **S2, S3, S4** — 409 sonrası bağlı kayıtların **sayımla** yerinde olduğu
- **S5** — taslak + bölümlü → 409 (ayrıcalık yok)
- **S6** — başarılı silmenin denetim metni **silinen şantiyenin adını içeriyor**
- **S7** — 409 dönen deneme denetime **hiçbir şey yazmadı**
- **S9** — bölüm silindikten sonra şantiye silinebiliyor

**Kabul kriteri:** S1–S9'un **dokuzu da** en az bir testle karşılanmış; eşleme tablosu
raporda; **hiçbir testte cascade tetiklenmemiş** (her 409 testinde öncesi/sonrası sayım eşit).

**Kapı komutu:**
```bash
createdb snt_form_t14 && \
  TEST_DATABASE_URL="postgresql+asyncpg://furkanilgen@localhost:5432/snt_form_t14" \
  .venv/bin/pytest tests/modules/sites tests/modules/units tests/modules/test_boq_api.py -x
dropdb snt_form_t14
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

**Geri alma:** yalnız test dosyası; geri alınmaz.

---

### T15 — IDOR negatif seti 21–33  ⚠️ RİSKLİ

| | |
|---|---|
| Boyut | **M** |
| Bağımlı | T10, T11 |
| Risk | **Güvenlik sınıfı.** P2'de IDOR tam bu noktada yakalandı. Silme uçları **yeni yüzeydir**. |

**Yazılacak testler** — `tests/modules/sites/test_sites_idor.py` (yeni) — spec §12.5'in
**13 maddesinin 13'ü**, birebir:

Yazma/okuma yüzeyi:
1. `test_post_to_invisible_project_returns_404` (21) — `Proje bulunamadı`, **403 değil**
2. `test_get_invisible_site_returns_404` (22)
3. `test_patch_invisible_site_returns_404_same_body_as_unknown_uuid` (22) —
   **birebir aynı gövde**
4. `test_patch_section_of_invisible_site_returns_404` (23) — `Bölüm bulunamadı`
5. `test_view_permission_rejects_writes_403` (24) — POST/PATCH
6. `test_no_permission_returns_403` (25)
7. `test_random_manager_user_uuid_returns_422_and_writes_nothing` (26)

**Silme uçları — ZORUNLU set (atlanamaz):**
8. `test_delete_site_invisible_returns_404_and_record_survives` (27) — gövde var olmayan
   UUID ile **birebir aynı** ve **kayıt silinmedi**
9. `test_delete_section_invisible_returns_404_and_record_survives` (28)
10. **`test_delete_site_with_full_permission_returns_403`** (29) — **`sites:full`
    (admin değil)** → 403, kayıt yerinde.
    *Bu vaka en kritik olanıdır: `full`'ün silmeyi kapsamadığı kararının **tek** testidir.*
11. **`test_delete_section_with_full_permission_returns_403`** (30)
12. `test_delete_both_with_view_permission_returns_403` (31)
13. `test_delete_both_with_no_permission_returns_403` (32)
14. **`test_admin_without_project_access_delete_returns_404`** (33) —
    `sites:admin` sahibi ama projeye erişimi **yok** → **404 (403 değil)** ve kayıt yerinde.
    *Yetkili olmak görünmeyen kaydın **varlığını sızdırmamalıdır**.*
15. `test_error_bodies_do_not_leak_record_existence` — her negatif yanıtta gövde kayıt
    kimliği/adı/sayısı **taşımıyor**

**KIRMIZI GÖR:** bu testlerin bir kısmı T10/T11 doğru yazıldıysa **yeşil başlayabilir** —
bu **beklenendir** ve TDD ihlali değildir; onlar regresyon ağıdır. Kırmızı görülmesi
gereken, henüz karşılanmamış davranışlara ait olanlardır ve raporda **hangilerinin
kırmızı başladığı** açıkça yazılır.

**Dosyalar:** `backend/tests/modules/sites/test_sites_idor.py` (yeni);
gerekirse `service.py`/`router.py` düzeltmesi.

**Kabul kriteri:** §12.5'in **13 maddesinin 13'ü** testle karşılanmış (madde↔test eşleme
tablosu raporda **zorunlu**); **29/30 ve 33 atlanamaz** — bu üçü eksikse task kapanmaz.

**Kapı komutu:**
```bash
createdb snt_form_t15 && \
  TEST_DATABASE_URL="postgresql+asyncpg://furkanilgen@localhost:5432/snt_form_t15" \
  .venv/bin/pytest tests/modules/sites -x
dropdb snt_form_t15
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

**Geri alma:** testler **geri alınmaz** (regresyon değeri yüksek).

---

### T16 — Kapılar + `openapi.json` üretimi

| | |
|---|---|
| Boyut | **S** |
| Bağımlı | T13, T14, T15 |
| Risk | düşük |

**Yazılacak test** (isteğe bağlı ama önerilir) —
`tests/modules/sites/test_sites_openapi.py`:
1. `test_openapi_exposes_all_eight_site_endpoints` — spec §7'deki **8 uç** şemada
   (yol + yöntem eşleme tablosuyla), **iki DELETE dahil**

**Dosyalar:**
- `backend/openapi.json` (üretilir — **gitignore'lu, COMMIT EDİLMEZ**)
- `backend/tests/modules/sites/test_sites_openapi.py` (yeni, isteğe bağlı)

**Uygulama notları:**
- `openapi.json` üretimi uygulamayı import eder → env değişkenleri **komut satırında**.
- Şemada `app__modules__projects__schemas__MetricPlaceholder` gibi uzun ad görünmesi
  **beklenen davranıştır**, düzeltilmez.

**Kabul kriteri:**
- **Tüm** test paketi yeşil (`tests/` tamamı, `-x` olmadan, test sayısı raporlanır)
- `ruff check .` → `0`; `ruff format --check .` → `0`
- `.venv/bin/alembic heads` → **tek** head
- `git status` çıktısında `openapi.json` **yok**
- Modül sayısı testleri (17) yeşil ve **dosyaları değişmemiş**
- `git diff .env` boş / `.env` takip edilmiyorsa dokunulmamış

**Kapı komutu:**
```bash
cd /Users/furkanilgen/Documents/Projeler/insaat/backend
createdb snt_form_t16 && \
  TEST_DATABASE_URL="postgresql+asyncpg://furkanilgen@localhost:5432/snt_form_t16" \
  .venv/bin/pytest tests/
dropdb snt_form_t16
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/alembic heads
git diff --stat app/modules/roles/seed_data.py    # BOŞ olmalı
TEST_DATABASE_URL="postgresql+asyncpg://furkanilgen@localhost:5432/postgres" \
  .venv/bin/python -c "import json;from app.main import app;print(json.dumps(app.openapi(),ensure_ascii=False,indent=2))" \
  > openapi.json
git status --short | grep openapi.json && echo "HATA: openapi.json takip ediliyor" || echo "OK"
psql -l | grep snt_form && echo "HATA: artik test DB'si var" || echo "OK: temiz"
```

**Geri alma:** `openapi.json` silinir; kod değişmedi.

---

## 2. Sıralama ve kritik yol

```
T1 → T2 ─┬─→ T3 ─┐
         ├─→ T4 ─┴→ T5 ─┬→ T6 ─┐
         │              └→ T7 ─┤
         ├─→ T4 → T8 ──────────┼→ T13 ─┐
         └─→ T9 ──→ T10 ───────┤       │
                     T11 ──────┴→ T12 ─┼→ T14 ─┐
                                        └→ T15 ─┴→ T16
```

**Kritik yol (en uzun zincir, 9 düğüm):**
`T1 → T2 → T3 → T5 → T6 → T12 → T14 → T15 → T16`

T3 seçildi çünkü T4'ten daha risklidir (kod üreticisi değişimi + iki modülü etkiler) ve
T5/T6 zincirini besler. T12 tüm yazma uçlarına bağlıdır, T14/T15 ona.

**Pazarlık dışı sıra:** **T9 → T10.** (§0.1 — cascade tuzağı.)

**Paralel koşabilir** (aynı repoda **aynı anda iki ajan çalışmaz** kuralı gereği bunlar
yalnız *planlama esnekliğidir*, fiilen sıralı koşulur):
- T3 ile T4 (farklı dosyalar)
- T10 ile T11 (T11, T9'a bağlı değil)
- T14 ile T15

**Önerilen fiili sıra:**
`T1 → T2 → T3 → T4 → T5 → T6 → T7 → T8 → T9 → T10 → T11 → T12 → T13 → T14 → T15 → T16`

---

## 3. Riskli task'lar (özet)

| Task | Risk sınıfı | Neden | Ek korkuluk |
|---|---|---|---|
| **T1** | Migration / enum | Enum tip takası Postgres'te sessizce yanlış gidebilir; downgrade'de sıra hatası `USING` çevrimini patlatır; yanlış `down_revision` = canlıda çoklu head = deploy kilidi | `alembic heads` **ölçümü** (kod yazmadan önce); round-trip testi; downgrade'de `preparation → active` taşıma testi |
| **T2** | Canlı veri / şema | Tek bir `NOT NULL` kolon canlı deploy'u kilitler; `CHECK` + 2 FK + indeksler aynı revizyonda; Numeric sapması sessiz yuvarlama hatası | Test 10 (22 kolonun hepsi nullable **veya** default'lu); test 19 (mevcut satır upgrade'i geçiyor); test 15 (`uq_sites_project_code` değişmedi) |
| **T3** | Kod üreticisi değişimi | `_write_inline_sites` de bu üreticiyi çağırıyor → P1.1a kırılabilir; canlıdaki mevcut kodlar hiç değişmemeli | Test 9 (satır içi akış), test 10 (mevcut kodlar dokunulmadı), `grep` kapısı (`derive_code` kalmadı) |
| **T6** | Atomiklik | İç içe bölüm yazımında kısmi başarı = sessiz veri hatası; ayrıca üç yeni `*_user_id` IDOR yüzeyi | Test 15/16/17 öncesi/sonrası **sayım eşitliği**; kullanıcı çözümünde 422 (404 değil) |
| **T10** | **VERİ KAYBI** | Dört `CASCADE` FK; korkuluksuz tek istek bölüm + poz grubu + poz kalemi + blok siler, geri alınamaz | **T9 önkoşulu (pazarlık dışı)**; test 3/4/6 409 sonrası **sayımla** kanıt; `_ADMIN` kapısı |
| **T15** | Güvenlik (IDOR) | Silme uçları **yeni yüzey**; P2'de bu sınıf hata tam burada yakalandı | 29/30 (`full` → 403) ve 33 (admin-ama-görünmez → 404) **atlanamaz**; madde↔test eşleme tablosu zorunlu |

---

## 4. "Bitti" tanımı — kapanış kontrol listesi

Dilim ancak aşağıdakilerin **hepsi** işaretlendiğinde kapanır.

**Migration**
- [ ] T1'de `.venv/bin/alembic heads` **ölçüldü**, çıktı raporda; tek head'di
- [ ] `down_revision` doğrulanmış ebeveyne bağlı
- [ ] **İki revizyon** var ve ayrı: (1) enum takası, (2) 22+1 kolon
- [ ] Enum takası **izole revizyonda** (`preparation` eklenmesi tek başına)
- [ ] `upgrade → downgrade → upgrade` yerel DB'de yeşil (T1 test 7, T2 test 17)
- [ ] Downgrade sonrası `preparation` etiketi `pg_enum`'da **yok**;
      `ck_sites_safety_officer` `pg_constraint`'te **yok**
- [ ] Downgrade `preparation` satırlarını `active`'e **taşıyor** (kaybetmiyor)
- [ ] `.venv/bin/alembic heads` → **tek** head
- [ ] Canlı DB'ye **hiçbir** migration koşulmadı

**Canlı veri korkulukları (§0.3 — beşi de)**
- [ ] Hiçbir yeni kolon `NOT NULL` + varsayılansız **değil** (T2 test 10)
- [ ] `uq_sites_project_code` **global `UNIQUE`'e çevrilmedi** (T2 test 15)
- [ ] `PATCH` tam doğrulama **koşmuyor** (T7 test 4)
- [ ] Mevcut satırlar `is_draft=false` ve upgrade'i **sağ geçti** (T2 test 19)
- [ ] Mevcut şantiye kodlarına **hiç `UPDATE` yazılmadı** (T3 test 10)

**CASCADE korkulukları (§0.1)**
- [ ] `site_has_sections` / `site_has_boq` / `site_has_blocks` **üçü de** `EXISTS` ile yazıldı
- [ ] `site_has_boq` hem `boq_items` hem **`boq_groups`** görüyor (T9 test 4)
- [ ] `DELETE /sites/{id}` üç engeli de kontrol ediyor, **ilk engelde duruyor**
- [ ] 409 dönen her testte bağlı kayıt sayımı **öncesi = sonrası** (T10 test 3/4/6, T14 S2–S4)
- [ ] Hata mesajları **sayı taşımıyor**
- [ ] FK davranışları **`CASCADE` olarak bırakıldı** (bilinçli, §11.1) — `ALTER` yazılmadı

**İzin doğrulaması (17 sabit)**
- [ ] `modules` / `role_permissions` tablolarına **dokunulmadı**
- [ ] `app/modules/roles/seed_data.py` **değişmedi** (`git diff --stat` boş)
- [ ] `test_seed_matrix.py`, `test_roles_repository.py`, `test_roles_api.py`
      **dosyaları değişmeden** yeşil → **modül sayısı 17'de KALDI**
- [ ] Okuma `view`, yazma `full`, **silme `admin`** — `sites:full` ile DELETE **403** (T15/29,30)
- [ ] `sites:admin` ama projeye erişimsiz → **404** (T15/33)

**Denetim mesajları**
- [ ] `audit/messages.py`'ye **tam 5** yeni fonksiyon eklendi, metinler spec §10 ile birebir
- [ ] Mevcut `site_created` / `site_updated` / `section_created` / `section_updated`
      metinleri **değişmedi**
- [ ] Silme metni **`session.delete`'ten ÖNCE** kuruluyor ve silinen kaydın adını içeriyor
- [ ] Bölümlü oluşturma **istek başına tek özet satır** yazıyor (bölüm başına değil)
- [ ] Taslak oluşturma ile yayın oluşturma **ayrı metinler**
- [ ] Reddedilen istekler (409/422) günlük **yazmıyor**
- [ ] Okuma uçları **hiç** yazmıyor

**Uçlar ve sözleşme**
- [ ] Spec §7'deki **8 ucun 8'i** kayıtlı ve testli (**iki DELETE dahil**)
- [ ] Türkçe hata mesajları spec §7.2 tablosuyla **birebir** (18 satırın hepsi)
- [ ] Mevcut `SiteCard` alanlarının **hiçbiri** kaldırılmadı/yeniden adlandırılmadı
- [ ] `MetricPlaceholder` `projects.schemas`'tan **import** edilmiş, kopyalanmamış
- [ ] Spec §12.5'in **13 maddesinin 13'ü** testle karşılanmış (eşleme tablosu raporda)
- [ ] Spec §12.3'ün **S1–S9'unun dokuzu** testle karşılanmış

**Onaylı sapmalar korunmuş (§14)**
- [ ] Bölüm şablonu **yazılmadı** (tablo/uç/akış yok)
- [ ] Tesis ön-işaretleri **hiçbir katmanda yok** (DB/Pydantic ikisi de `false`)
- [ ] `sections.estimated_amount` **açılmadı**; `SectionResponse.budget` yer tutucu (`boq`)

**OpenAPI**
- [ ] `openapi.json` üretildi, **8 şantiye ucu** şemada
- [ ] **Commit EDİLMEDİ** (`git status` temiz)
- [ ] Frontend'e kopyalanmaya hazır bırakıldı

**Kapılar**
- [ ] `.venv/bin/pytest tests/` — **tam paket** yeşil (test sayısı raporda)
- [ ] `.venv/bin/ruff check .` → `0`
- [ ] `.venv/bin/ruff format --check .` → `0`
- [ ] Her `createdb` için karşılık gelen `dropdb` koşuldu:
      **`psql -l | grep snt_form` → boş**

**Süreç**
- [ ] Ajanlar **push etmedi**; PR/merge/deploy kullanıcıda
- [ ] `frontend/` altına **tek satır** yazılmadı
- [ ] `backend/.env` **değiştirilmedi**

---

## 5. Frontend'e devredilen iş (bu planın kapsamı DIŞI)

### 5.1 BFF izin listesi — **değişiklik GEREKMEZ**

Bu dilimde **yeni kök açılmıyor**: `/projects`, `/sites`, `/sections` üçü de
`frontend/src/app/api/backend/[...path]/route.ts` `ALLOWED_ROOTS` listesinde **zaten var**
(P2'de eklendi). İki yeni uç (`DELETE /sites/{id}`, `DELETE /sections/{id}`) mevcut
köklerden geçer.

> Yine de frontend diliminin **ilk task'ı** bunu `grep` ile **doğrulasın** —
> "zaten var" varsayımı bu repoda daha önce yanlış çıktı ve modül **yalnız canlıda 404**
> verdi (jsdom testleri yakalamaz).

### 5.2 `openapi.json` senkronu

T16'nın ürettiği dosya `frontend/openapi/openapi.json`'a **kopyalanmadan** `pnpm gen:api`
**koşulmaz**. Tip üretimi eski şemadan yapılırsa 22 yeni alan frontend tarafında
görünmez ve sessizce düşer.

### 5.3 Yeni frontend sözleşmeleri

- `SiteCard.is_draft` → **rozet** (ayrı sekme **açılmaz**, §13/14)
- `SiteCounts.draft` → liste başlığında rozet sayacı
- `facilities` **gruplu** gelir (8 alan) — form iki grup hâlinde çizilir, **ön-işaret yok** (§14.2)
- "Süre (Gün)" **frontend'de** hesaplanır: `end − start + 1` (**uç-dahil**), `derive.ts`
- "Tahmini Bedel" sütunu **salt-okunur yer tutucu** (`pending_module: "boq"`), girilebilir **değil** (§14.3)
- Belgeler kartı `pending_module: "documents"` zarif düşüşüyle çizilir; backend belge bilmez
- "+ Yeni Personel Ekle" seçeneği **basılmaz**; "şablon kullan" **yalnız** "+ Bölüm Ekle" işlevi taşır
- İSG uzmanı etiketinde **kırmızı `*` yok** (zorunlu değil); "(A Sınıfı)" `users.title`'dan basılır

**Kullanıcı seçicileri — zarif düşüş (ZORUNLU, §5.4 kararının sonucu):**

`GET /users` çağrısı **403** dönerse (admin dışı tüm roller — §5.4) Şantiye Şefi /
İSG Uzmanı / Bölüm Sorumlusu seçicileri:

* **çökmez** (403 yakalanmadan yukarı fırlayıp formu düşüremez),
* **sessizce boş açılır liste** göstermez — kullanıcı "hiç kullanıcı yok" sanmamalı,
* boş liste + **kullanıcıya görünür açıklama** basar (ör. "Kullanıcı listesini görme
  yetkiniz yok — bu alanı sistem yöneticisi doldurabilir") ve alan **devre dışı ama
  boş bırakılabilir** kalır.

Bu, P1.1a'da verilen kararın ve `GOREV-SIRASI.md` §3'teki kalıcı kuralın aynısıdır:
*"Mockup'ta olup backend'in vermediği alan → zarif düşüş **+ kullanıcıya bildirim**,
sessiz atlama yok."* Aynı desen `pending_module` zarif düşüşlerinde kullanılıyor;
buradaki fark, eksikliğin **modül değil yetki** kaynaklı olmasıdır — metin de bunu
söylemeli.

**`GET /users` sayfalama notu (yanlış tespit düzeltmesi):** frontend spec'i bu ucu
**"20 kayıt sınırlı"** diye devretmişti; **bu yanlıştır**. Koddan ölçüm
(`app/modules/users/router.py:38-41`): varsayılan `limit=50`, tavan `le=200`,
`offset` destekli. Seçiciler `?limit=200` ile çağrılır. **Bu konuda backend işi
açılmasın** — 200 üstü için doğru çözüm sunucu tarafı arama (`?q=`) olur ve o,
kullanıcı yönetimi diliminin işidir.

### 5.4 `GET /users` — KARARA BAĞLANDI (2026-07-30)

**Karar 1: `GET /users`'ın *limit* konusu bu planda ELE ALINMAZ. Backend değişikliği
gerekmez.**

*Gerekçe (koddan ölçüldü, `app/modules/users/router.py:38-41`):* uç zaten sayfalıdır —
`limit: Query(ge=1, le=200) = 50`, `offset: Query(ge=0) = 0`. Frontend spec'inin
devrettiği **"20 kayıt sınırlaması" tanımı yanlıştır**: varsayılan 20 değil **50**'dir ve
tavan **200**'dür. Şef/İSG/bölüm-sorumlusu seçicileri `?limit=200` ile çağrılarak
çözülür — bu **saf frontend işidir**. 200'ün üstünde kullanıcısı olan bir kuruluş için
doğru çözüm sunucu tarafı arama (`?q=`) eklemektir; o, kullanıcı yönetimi diliminin işidir,
bu formun değil. Tavanı yükseltmek veya sınırsız liste açmak, ihtiyaç kanıtlanmadan
yapılan bir performans tavizi olurdu (YAGNI).

**ANCAK — planlama sırasında bulunan, spec'te YANLIŞ kayıtlı bir engel var:**

> Spec §9 şöyle diyor: *"kullanıcı listesi `sites:full` sahibi için zaten `GET /users` ile
> erişilebilir"*. **Bu doğru değil.**

Ölçüm:
* `GET /users` kapısı → `require_permission("user_management", AccessLevel.view)`
  (`app/modules/users/router.py:36`)
* İzin matrisinde `user_management` satırı → `[_A, _N, _N, _N, _N, _N, _N, _N]`
  (`app/modules/roles/seed_data.py:169`) — yani **yalnız `admin` rolü**; diğer **yedi rolde
  `none`**.

**Sonuç:** `sites:full` sahibi ama `admin` olmayan bir kullanıcı (ör. şantiye şefi, proje
müdürü) şantiye formunu açtığında **"Şantiye Şefi" ve "İSG Uzmanı" açılırları 403 alır ve
boş kalır** — form mockup'taki hâliyle **kullanılamaz**. Bölüm "Sorumlu" seçicisi de aynı.

**Karar 2 (kullanıcı, 2026-07-30): "Şimdilik böyle kalsın" — yeni seçici ucu AÇILMAZ.**

* `GET /users/selectable` (veya benzeri dar bir seçim ucu) **yazılmaz**.
* İzin matrisinde `user_management` satırı **gevşetilmez** — modül sayısı 17'de,
  matris değerleri olduğu gibi kalır (§0.9 ile tutarlı).
* Bu plana **T17 eklenmez**; task sayısı **16'da kalır**.

*Gerekçe:* iki alternatifin de bedeli, bugünkü faydasından büyüktür. Yeni bir uç, onaylı
spec'te olmayan bir yüzey açar (yeni test seti, yeni IDOR yüzeyi, yeni BFF kökü kararı);
matrisi gevşetmek ise **Ayarlar ekranını da** açar — istenmeyen bir yan etkidir ve izin
matrisi mockup'ı ile frontend görsel baseline'ını kaydırır. Üç alan da `nullable`
olduğu için form **bugün de çalışır durumdadır**; gerçek ihtiyaç ortaya çıktığında
(bir rol fiilen şef atamak isterse) kendi dilimi olarak ele alınır.

#### Kabul edilen sınırlama (hata değil)

`sites:full` yetkili **ama** `user_management:view` yetkisi olmayan roller — yani
`admin` dışındaki **yedi rolün hepsi** — için:

* **Şantiye Şefi**, **İSG Uzmanı** ve **Bölüm Sorumlusu** seçicileri **boş kalır**
  (`GET /users` → 403).
* Üç alan da **nullable** olduğu için (`site_manager_user_id`, `safety_officer_user_id`,
  `sections.manager_user_id`) **form yine kaydedilebilir** — ne taslak ne yayın akışı
  bloke olur. İSG uzmanı zaten hiçbir koşulda zorunlu değildir (§13/6); şantiye şefi
  yalnız **taslak-dışı** POST'ta zorunludur ve o durumda `admin` rolü ya da
  serbest metin `site_manager_name` alanı kullanılabilir.
* Bu **bilinçli ve kabul edilmiş bir sınırlamadır**, hata değildir. İleride
  "seçici neden boş?" diye bir hata kaydı açılırsa **bu madde cevaptır**.

> Not: spec §9'daki *"kullanıcı listesi `sites:full` sahibi için zaten `GET /users` ile
> erişilebilir"* cümlesi **yanlıştır**. Spec bir sonraki revizyonunda düzeltilmeli;
> bu planda bağlayıcı olan yukarıdaki karardır.

---

## 6. Dilim dışı takip işleri (spec §13.1'den aktarıldı — bu planda YAPILMAZ)

| İş | Neden burada değil |
|---|---|
| 6 belge alanı + sürükle-bırak yükleme | Dosya yükleme altyapısı repoda **hiç yok**; ayrı "belge dilimi" (Kalıcı Karar 4) |
| Poz dağılımı bağı ve kotası (mockup 57, 59) | P5 (`contracts` + poz dağılımı); **Kalıcı Karar 1**: ileri bağ açılmaz |
| GPS ayrıştırma + `latitude`/`longitude` migration'ı + veri geçişi | Puantaj / konum doğrulaması dilimi (§3.5'teki üç maddelik gelecek-iş notu) |
| `boq_groups.section_id` gelirse `delete_section` korkuluğu | P5; yeri `service.delete_section` içinde **yorumla işaretlendi** (T11) |
| Bölüm şablonu kartoteksi | Tanımsız özellik; ihtiyaç netleşince ayrı dilim (§14.1) |
| Şantiye bütçesi ↔ proje bütçesi tutarlılık raporu | Mali Özet / gösterge paneli (§3.7) |
| Şef/İSG/sorumlu için dar kullanıcı seçim ucu | **KARARA BAĞLANDI 2026-07-30: açılmıyor** (§5.4). Seçiciler admin dışı rollerde boş kalır; üç alan da nullable olduğu için form kaydedilebilir. Gerçek ihtiyaç doğarsa kendi dilimi olur |

---

Kapanış akışı: 16 task → review → commit → **kullanıcı** push/PR → CI → **kullanıcı**
merge → Railway auto-deploy → **canlı migration doğrulaması**
(`railway logs` / `alembic current` → iki yeni revizyon görünmeli).
