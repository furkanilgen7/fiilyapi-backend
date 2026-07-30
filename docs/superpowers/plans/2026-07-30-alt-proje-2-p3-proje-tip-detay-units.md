# Alt-Proje 2 · P3 — Proje tip-detay + `blocks`/`units` uygulama planı

Tarih: 2026-07-30
Spec (onaylı, rev. 2): `backend/docs/superpowers/specs/2026-07-30-alt-proje-2-p3-proje-tip-detay-units-design.md`
Repo: `backend/` (frontend'e **tek satır** yazılmaz)
Task sayısı: **12 uygulama task'ı** (B1–B12). B0 = spec + bu plan, onayla kapandı.

---

## 0. TUZAKLAR — her task'ta tekrar okunacak

> Bu bölüm süs değildir. Aşağıdaki maddelerin **her biri** bu repoda daha önce
> ya veri kaybına ya da yalnız-canlıda görülen bir hataya yol açtı.

### 0.1 TEST DB TUZAĞI (KRİTİK — veri kaybı riski)

`backend/.env` içindeki `TEST_DATABASE_URL` **uzak Railway veritabanını** gösteriyor ve
`tests/conftest.py` oturum başında `Base.metadata.drop_all` çağırıyor. O env ile `pytest`
koşmak **canlı benzeri veritabanını siler**.

**Kural:** `.env` dosyasına **DOKUNULMAZ** (ne düzenlenir, ne geçici değiştirilir).
Her task **tek kullanımlık yerel DB** açar, env'i **komut satırında** verir, sonunda düşürür:

```bash
createdb p3_units_bN && \
  TEST_DATABASE_URL="postgresql+asyncpg://furkanilgen@localhost:5432/p3_units_bN" \
  .venv/bin/pytest <hedef testler> -x
dropdb p3_units_bN      # BAŞARISIZLIKTA BİLE — istisnasız
```

Bu blok **her task'ın kapı komutunda birebir tekrar edilir**; "önceki task'ta yazmıştım"
diye atlanmaz. Task'lar ayrı ajanlara verildiğinde bu bilgi taşınmaz.

### 0.2 Migration ebeveyni — varsayılmaz, DOĞRULANIR

Spec §10.1 `down_revision = "e3a8b4a5b93b"` bekliyor (PR #4 merge edildi varsayımı).
**B1'in ilk adımı** bunu doğrulamaktır:

```bash
.venv/bin/alembic heads
```

- Çıktı **tek** head ve `e3a8b4a5b93b` ise → devam.
- Çıktı **iki head** ise → **KOD YAZILMAZ.** Birleştirme revizyonu (`alembic merge`)
  kullanıcı kararıdır; ajan kendi başına merge revizyonu üretmez. Durulur, sorulur.
- Çıktı tek head ama **başka** bir revizyon ise → yine sorulur (araya yeni migration
  girmiş demektir; `down_revision` o revizyona güncellenir ama bu kullanıcı onayıyla olur).

### 0.3 `python` PATH'te YOK

Her şey `.venv/bin/` üzerinden: `.venv/bin/python`, `.venv/bin/pytest`,
`.venv/bin/alembic`, `.venv/bin/ruff`. Çıplak `python` / `pytest` / `alembic` çağrısı
ya çalışmaz ya yanlış yorumlayıcıyı bulur.

### 0.4 Ruff 0.15.22'ye sabitli

`.venv/bin/ruff --version` → `ruff 0.15.22`. Global kurulum (0.8.6) **kullanılmaz**;
yanlış pozitif üretir ve gereksiz diff açar.

### 0.5 Canlı DB'ye migration koşulmaz

`upgrade → downgrade → upgrade` doğrulaması **yalnız tek kullanımlık yerel DB'de**
yapılır. `DATABASE_URL` canlıyı gösteren bir env ile `alembic upgrade` **çalıştırılmaz**.
Canlı migration, PR merge sonrası Railway auto-deploy'un işidir ve doğrulaması
kullanıcıdadır (`railway logs` / `alembic current`).

### 0.6 `openapi.json` gitignore'lu

Üretilir, frontend'e **kopyalanmaya hazır** bırakılır, **commit edilmez**.
`git add openapi.json` yapan task geçersizdir.

### 0.7 İzin matrisi büyümez — modül sayısı **17'de KALIR**

Spec §8 kararı: yeni izin modülü **açılmaz**. `modules` / `role_permissions` tablolarına
**dokunulmaz**, `app/core/seed_data.py` MATRIX **değişmez**. Şu üç test dosyası
**değiştirilmeden yeşil kalmalıdır** — kırmızıya düşerlerse §8 kararı ihlal edilmiş demektir:

- `tests/modules/test_seed_matrix.py`
- `tests/modules/test_roles_repository.py`
- `tests/modules/test_roles_api.py`

### 0.8 Ajanlar push etmez

Commit serbest (İngilizce, `<type>: <desc>`). `git push`, PR açma, merge, deploy
**kullanıcı kararıdır**.

### 0.9 TDD zorunlu — "KIRMIZI GÖR" atlanamaz

Her task'ta önce test yazılır, **koşulur ve kırmızı olduğu görülür**, sonra uygulama
yazılır, yeşil görülür, sonra refactor edilir. Kırmızıyı görmeden uygulama yazan task
**geçersizdir** ve baştan yapılır. Kırmızı çıktı task raporunda alıntılanır.

### 0.10 %100 mockup sadakati

Spec §2'deki alan tablosu kanondur. Orada olmayan sütun/alan **icat edilmez**.
Spec §2.5'teki dört madde (blocks tablosu, blocks.site_id, bulk/import uçları, DELETE
uçları) **onaylı sapmadır** (spec §13) — bir sonraki ajan bunları "spec ihlali" sanıp
geri almaz.

---

## 1. Task listesi

Boyut ölçeği: **S** ≈ tek dosya + dar test seti · **M** ≈ 2–3 dosya + orta test seti ·
**L** ≈ yeni altyapı, geniş test seti veya yüksek hata riski.

---

### B1 — `blocks` + `units` modelleri + migration  ⚠️ RİSKLİ

| | |
|---|---|
| Boyut | **L** |
| Bağımlı | B0 (spec + plan onayı) |
| Risk | **Enum tipi oluşturma + bileşik FK + downgrade'de `DROP TYPE`.** Bu üçü Postgres'te sessizce yanlış gidebilen yerlerdir. |

**Önce yazılacak testler** (TDD sırası — bu sırayla yazılır, sonra hepsi birden kırmızı görülür):

Dosya: `tests/modules/units/__init__.py` (boş) + `tests/modules/units/test_units_models.py`

1. `test_block_requires_project_and_site` — `project_id`/`site_id` NULL → `IntegrityError`
2. `test_block_name_unique_within_project` — aynı projede aynı ad ikinci kez → `IntegrityError`
3. `test_block_same_name_allowed_in_other_project` — farklı projede aynı ad → başarılı
4. `test_unit_no_unique_within_block` — aynı blokta aynı `unit_no` → `IntegrityError`
5. `test_unit_no_repeatable_across_blocks` — A Blok "1" + B Blok "1" → ikisi de yazılır (SY 76/106)
6. `test_unit_composite_fk_rejects_cross_project_block` — `unit.project_id` ≠ `block.project_id`
   olacak şekilde ham `INSERT` → `IntegrityError` (**bileşik FK'nın kanıtı**; servis korkuluğu
   devre dışıyken bile DB reddetmeli)
7. `test_unit_check_negative_areas` — `gross_area_m2 = -1` → `IntegrityError` (`ck_units_gross_area`)
8. `test_unit_check_negative_net_area` — `ck_units_net_area`
9. `test_unit_check_negative_list_price` / `test_unit_check_negative_appraisal_value`
10. `test_unit_check_net_not_greater_than_gross` — `gross=100, net=120` → `IntegrityError`
    (`ck_units_net_le_gross`, spec §4.3 / karar 5)
11. `test_unit_check_net_le_gross_allows_nulls` — `gross=None, net=50` → başarılı (CHECK NULL'ları geçirir)
12. `test_project_delete_cascades_blocks_and_units` — proje silinince ikisi de gider
13. `test_site_delete_cascades_blocks` — şantiye silinince blok gider (`blocks.site_id` CASCADE)
14. `test_block_delete_restricted_when_units_exist` — ünitesi olan blok `DELETE` → `IntegrityError`
    (`ON DELETE RESTRICT`, spec §4.2)
15. `test_unit_kind_enum_rejects_unknown_value` — `'villa'` → hata
16. `test_unit_owner_side_nullable` — `owner_side = NULL` yazılabilir (spec §5.3)

Ayrı dosya: `tests/modules/units/test_units_migration.py`
17. `test_upgrade_downgrade_upgrade_round_trip` — `alembic upgrade head` → `downgrade -1` →
    `upgrade head`; her adımdan sonra tablo/enum varlığı `information_schema` +
    `pg_type` ile doğrulanır. **Downgrade sonrası `unit_kind` ve `unit_owner_side`
    tiplerinin `pg_type`'da KALMADIĞI** ayrıca doğrulanır (spec §10.3).

**KIRMIZI GÖR:** bu 17 test yazıldıktan sonra kapı komutu koşulur; `ImportError:
cannot import name 'Block'` / `'Unit'` ile **hepsi kırmızı** olmalı. Bu çıktı raporda alıntılanır.

**Dokunulacak/oluşturulacak dosyalar:**
- `backend/app/modules/units/__init__.py` (yeni)
- `backend/app/modules/units/models.py` (yeni) — `Block`, `Unit`, `UnitKind`, `UnitOwnerSide`
- `backend/alembic/versions/<hash>_p3_proje_tip_detay_units.py` (yeni)
- `backend/app/db/base.py` veya modellerin toplandığı yer — **önce grep edilir**
  (`grep -rn "modules.boq.models" app/`), BOQ modellerinin nasıl kaydedildiği birebir taklit edilir
- `backend/tests/modules/units/__init__.py`, `test_units_models.py`, `test_units_migration.py` (yeni)

**Uygulama notları:**
- Migration **sırası** (spec §10.2): (1) `unit_kind` enum, (2) `unit_owner_side` enum,
  (3) `blocks` + 2 UNIQUE + 2 index, (4) `units` + 5 CHECK + 1 UNIQUE + bileşik FK + 2 index.
  `units`'in bileşik FK'sı `uq_blocks_project_id_id`'e bağlıdır → `blocks` **önce** gelmek zorunda.
- Downgrade **ters sırada**: `units` → `blocks` → iki enum `DROP TYPE`.
  Postgres enum'ı tabloyla birlikte silmez; P1'in `project_type`/`project_status`
  migration'larındaki desen izlenir (`sa.Enum(...).drop(op.get_bind())`).
- Numeric hassasiyetleri **model ve migration'da AYNI**: `gross/net_area_m2` `Numeric(10,2)`,
  `list_price`/`appraisal_value` `Numeric(18,2)`. Sapma sessiz yuvarlama hatası üretir (P4 T1 tuzağı).
- `modules` / `role_permissions` tablolarına **DOKUNULMAZ** (§0.7).

**Kabul kriteri:**
- `tests/modules/units/test_units_models.py` — **16 test yeşil**
- `tests/modules/units/test_units_migration.py` — **1 test yeşil**
- `.venv/bin/alembic heads` → **tek** head, yeni revizyon
- `.venv/bin/alembic current` yerel DB'de yeni revizyonu gösteriyor
- `tests/modules/test_seed_matrix.py` + `test_roles_repository.py` + `test_roles_api.py`
  **dosyaları değişmeden** yeşil (modül sayısı 17)
- `ruff check` + `ruff format --check` çıkışı `0`

**Kapı komutu:**
```bash
cd /Users/furkanilgen/Documents/Projeler/insaat/backend
.venv/bin/alembic heads          # ÖNCE — §0.2
createdb p3_units_b1 && \
  TEST_DATABASE_URL="postgresql+asyncpg://furkanilgen@localhost:5432/p3_units_b1" \
  .venv/bin/pytest tests/modules/units tests/modules/test_seed_matrix.py \
    tests/modules/test_roles_repository.py tests/modules/test_roles_api.py -x
dropdb p3_units_b1
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

**Geri alma:** migration `downgrade` ile geri alınır ve bu **test 17 ile zaten
doğrulanmıştır** (round-trip). Kod tarafında geri alma = `app/modules/units/` klasörünün
ve migration dosyasının silinmesi; başka hiçbir dosya değişmediği için (model kayıt
satırı hariç) yan etki yoktur.

---

### B2 — Pydantic şemaları

| | |
|---|---|
| Boyut | **M** |
| Bağımlı | B1 |
| Risk | düşük |

**Önce yazılacak testler** — `tests/modules/units/test_units_schemas.py`

1. `test_unit_price_per_m2_computed` — `list_price=1_150_000`, `gross=142` → doğru değer,
   2 hane, `ROUND_HALF_UP`
2. `test_unit_price_per_m2_none_when_area_missing` — `gross_area_m2=None` → `None`
3. `test_unit_price_per_m2_none_when_area_zero` — `gross_area_m2=0` → `None` (sıfıra bölme yok)
4. `test_unit_label_derived` — `"A Blok"` + `"Daire 12"` → `"A Blok · Daire 12"` (KY 281)
5. `test_is_landowner_share_derived` — `owner_side=landowner` → `True`; `contractor`/`None` → `False`
6. `test_unit_kind_breakdown_total` — 48 daire + 4 dükkan → `total = 52` (KY 71/88)
7. `test_unit_create_rejects_negative_price` — `list_price=-1` → `ValidationError`
8. `test_unit_create_rejects_long_unit_no` — 31 karakter → `ValidationError`
9. `test_unit_update_partial_tracks_unset` — `model_fields_set` ile "gönderilmedi" ≠ "null yapıldı"
10. `test_allocation_request_min_and_max_items` — 0 satır → hata; 501 satır → hata
    (`_MAX_ALLOCATION_ITEMS = 500`)
11. `test_bulk_create_rejects_inverted_floor_range` — `end_floor < start_floor` → `ValidationError`
12. `test_bulk_create_rejects_over_limit` — 501 ünite üretecek kombinasyon → `ValidationError`
    (`_MAX_BULK_UNITS = 500`)
13. `test_decimal_fields_serialize_as_string` — mevcut repo deseni (para alanları str)
14. `test_metric_placeholder_imported_not_redefined` — `UnitResponse` alanının sınıfı
    `app.modules.projects.schemas.MetricPlaceholder`'ın **ta kendisi** (`is` kontrolü),
    kopya değil (spec §6 / BOQ `schemas.py:8` deseni)

**KIRMIZI GÖR:** `ImportError` ile 14 test kırmızı.

**Dosyalar:**
- `backend/app/modules/units/schemas.py` (yeni)
- `backend/tests/modules/units/test_units_schemas.py` (yeni)

**Uygulama notları:**
- `MetricPlaceholder` / `CountPlaceholder` → `from app.modules.projects.schemas import ...`
  **kopyalanmaz** (test 14 bunu kilitliyor).
- `_MAX_ALLOCATION_ITEMS = 500`, `_MAX_BULK_UNITS = 500`, `_MAX_IMPORT_BYTES = 2 * 1024 * 1024`,
  `_MAX_IMPORT_ROWS = 1000` — **modül düzeyi adlandırılmış sabitler**, sihirli sayı bırakılmaz.
- `unit_price_per_m2` tabanı **her zaman `list_price`** (spec §6.1; FDS 60–61).

**Kabul kriteri:** 14 test yeşil; `ruff` iki kapı da `0`; `UnitResponse` alan listesi
spec §6.1 ile **birebir** (alan adı ve tipi tek tek karşılaştırılır, eksik/fazla alan yok).

**Kapı komutu:**
```bash
createdb p3_units_b2 && \
  TEST_DATABASE_URL="postgresql+asyncpg://furkanilgen@localhost:5432/p3_units_b2" \
  .venv/bin/pytest tests/modules/units -x
dropdb p3_units_b2
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

**Geri alma:** tek yeni dosya; silinir. Migration yok.

---

### B3 — Repository + service (okuma yolu)

| | |
|---|---|
| Boyut | **L** |
| Bağımlı | B2 |
| Risk | orta — **N+1 sorgu** ve **Decimal toplama** klasik hata noktaları |

**Önce yazılacak testler** — `tests/modules/units/test_units_service.py`

1. `test_value_basis_kat_karsiligi_uses_appraisal` → `UnitValueBasis.appraisal_value`
2. `test_value_basis_kendi_yatirim_uses_list_price`
3. `test_value_basis_taahhut_uses_list_price`
4. `test_total_value_treats_null_basis_as_zero` — taban sütunu NULL olan satır toplamı bozmaz
5. `test_total_list_price_and_appraisal_returned_separately` — ikisi ayrı ayrı doğru
6. `test_average_value_none_when_no_units` — sıfıra bölme yok
7. `test_unit_share_pct_derived` — 23/42 → `54.76`; sözleşme %55'ten sapma **hata değil** (§5.2)
8. `test_sides_include_unassigned_bucket` — `contractor` / `landowner` / `None` üçü de döner,
   hiç ünite olmasa bile 0'lı grup
9. `test_blocks_without_units_are_returned` — boş blok listede, `units == []` (spec §6.1)
10. `test_block_ordering_sort_order_then_name`
11. `test_unit_ordering_sort_order_then_unit_no` — `"10"` `"2"`'den önce gelmez
12. `test_totals_ignore_filters` — `block_id` süzgeci verildiğinde `blocks` süzülür ama
    `totals` **projenin tamamını** sayar (spec §7.4, P1 `list_projects_overview` kuralı)
13. `test_owner_side_unassigned_filter_matches_nulls`
14. `test_site_filter_resolves_through_block` — `units`'te `site_id` yok, süzgeç blok üzerinden
15. `test_placeholders_carry_correct_pending_module` — `unit_sales`, `shareholder_units`,
    `project_costs`; hepsinde `available=False`
16. `test_empty_project_totals_are_zero_not_none` — ünitesi olmayan projede `total_value == "0.00"`
17. `test_reads_units_in_single_query` — blok başına ayrı sorgu **atılmaz** (N+1 koruması;
    `sqlalchemy` event sayacı veya `echo` yakalama ile sorgu sayısı sabitlenir)

**KIRMIZI GÖR:** `ImportError` / `AttributeError` ile 17 test kırmızı.

**Dosyalar:**
- `backend/app/modules/units/repository.py` (yeni)
- `backend/app/modules/units/service.py` (yeni)
- `backend/tests/modules/units/test_units_service.py` (yeni)

**Uygulama notları:**
- Görünürlük süzgeci **yeniden yazılmaz**:
  `from app.modules.projects.service import visible_projects`
  (`app/modules/projects/service.py:195`; `app/modules/sites/service.py` deseni birebir).
  Kopya süzgeç = zamanla ayrışan sessiz yetki sızıntısı.
- Toplamlar **`Decimal`** ile yapılır, `float` **asla**. Para 2 hane `quantize`
  (`ROUND_HALF_UP`) — BOQ `_quantize_money` deseni yeniden kullanılır, kopyalanmaz.
- Üniteler **tek sorguda** çekilip Python'da bloklara dağıtılır (test 17 bunu kilitliyor).

**Kabul kriteri:** 17 test yeşil; `visible_projects` **import edildiği** grep ile doğrulanır
(`grep -n "visible_projects" app/modules/units/service.py` → eşleşme var); servis katmanında
`float(` geçmiyor (`grep -n "float(" app/modules/units/` → boş).

**Kapı komutu:**
```bash
createdb p3_units_b3 && \
  TEST_DATABASE_URL="postgresql+asyncpg://furkanilgen@localhost:5432/p3_units_b3" \
  .venv/bin/pytest tests/modules/units -x
dropdb p3_units_b3
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

**Geri alma:** iki yeni dosya silinir; başka modül değişmedi.

---

### B4 — Okuma uçları + router kaydı

| | |
|---|---|
| Boyut | **M** |
| Bağımlı | B3 |
| Risk | düşük-orta — **404 vs 403 ayrımı** |

**Önce yazılacak testler** — `tests/modules/units/test_units_api.py`

1. `test_get_blocks_requires_token` → **401**
2. `test_get_blocks_forbidden_without_projects_view` → **403** (`projects` izni `none`)
3. `test_get_blocks_invisible_project_returns_404` → **404**, gövde `"Proje bulunamadı"`
4. `test_get_blocks_returns_empty_block` — ünitesi olmayan blok listede
5. `test_get_units_happy_path_matches_spec_envelope` — yanıt gövdesi spec §6.1 zarfıyla birebir
6. `test_get_units_invisible_project_returns_404`
7. `test_get_units_filter_by_block_id`
8. `test_get_units_filter_by_site_id`
9. `test_get_units_filter_by_kind`
10. `test_get_units_filter_owner_side_unassigned`
11. `test_get_units_totals_unaffected_by_filters`
12. `test_get_units_value_basis_by_project_type` — `kendi_yatirim` → `"list_price"`;
    `kat_karsiligi` → `"appraisal_value"`
13. `test_get_units_invalid_enum_returns_422`
14. `test_admin_role_bypasses_visibility` — `projects=admin` → **200** (P1 kilitlenme koruması)

**KIRMIZI GÖR:** rota kayıtlı olmadığı için **404 (FastAPI'nin kendi 404'ü)** ile kırmızı.
Dikkat: bu 404 ile domain 404'ü karıştırmamak için testler **gövde mesajını** de doğrular.

**Dosyalar:**
- `backend/app/modules/units/router.py` (yeni) — `tags=["units"]`, `responses=COMMON_ERROR_RESPONSES`
- `backend/app/main.py` (değişiklik) — `app.include_router(units_router)`, alfabetik sıraya
  uyularak `sites_router`'dan sonra
- `backend/tests/modules/units/test_units_api.py` (yeni)

**Uygulama notları:**
- İzin: `require_permission("projects", AccessLevel.view)` (spec §8). **Yeni modül açılmaz.**
- Yol kökleri **ikiye ayrılır** (P4 deseni): proje bağlamlı uçlar `/projects/...`,
  tekil uçlar `/blocks/...` ve `/units/...`.
- Görünmeyen kayıt → **404**, 403 **değil** (varlığı sızdırmaz).

**Kabul kriteri:** 14 test yeşil; `GET /projects/{id}/units` yanıtı spec §6.1'deki
`UnitListResponse` alanlarının **tamamını** içeriyor (test 5 alan alan doğruluyor);
seed/roles testleri değişmeden yeşil.

**Kapı komutu:**
```bash
createdb p3_units_b4 && \
  TEST_DATABASE_URL="postgresql+asyncpg://furkanilgen@localhost:5432/p3_units_b4" \
  .venv/bin/pytest tests/modules/units tests/modules/test_seed_matrix.py -x
dropdb p3_units_b4
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

**Geri alma:** `main.py`'deki tek `include_router` satırı çıkarılır, `router.py` silinir.

---

### B5 — Blok yazma uçları (`POST …/blocks`, `PATCH /blocks/{id}`)

| | |
|---|---|
| Boyut | **M** |
| Bağımlı | B4 |
| Risk | orta — **§4.5 tek/çok şantiye kuralı** dört ayrı dala sahip |

**Önce yazılacak testler** — `test_units_api.py` (genişletme)

1. `test_create_block_auto_assigns_single_site` — tek şantiyeli projede `site_id`
   **gönderilmeden** → **201**, yanıtta `site_id` o tek şantiye (spec §4.5, KY 38)
2. `test_create_block_without_any_site_returns_422` → `_NO_SITE_FOR_BLOCK`
   (`Blok tanımlamadan önce projeye şantiye eklenmelidir`)
3. `test_create_block_multi_site_without_site_id_returns_422` → `_SITE_REQUIRED`
4. `test_create_block_multi_site_with_site_id_returns_201`
5. `test_create_block_with_foreign_site_returns_404` — başka projenin şantiyesi
6. `test_create_block_duplicate_name_returns_409` → `_DUPLICATE_BLOCK`
7. `test_create_block_same_name_other_project_returns_201`
8. `test_create_block_requires_full_permission` — `projects=view` → **403**
9. `test_create_block_invisible_project_returns_404`
10. `test_patch_block_renames`
11. `test_patch_block_duplicate_name_returns_409`
12. `test_patch_block_changes_site_within_project`
13. `test_patch_block_foreign_site_returns_404`
14. `test_patch_block_invisible_returns_404` → `"Blok bulunamadı"`
15. `test_patch_block_unknown_uuid_returns_404_same_message` — var olan ama görünmeyen ile
    **ayırt edilemez**

**KIRMIZI GÖR:** uçlar tanımsız → FastAPI 405/404 ile kırmızı.

**Dosyalar:**
- `backend/app/modules/units/router.py`, `service.py` (genişletme)
- `backend/app/modules/units/errors.py` (yeni — Türkçe mesaj sabitleri, spec §7.11)
  *veya* mevcut domain hata deseni neredeyse orası; **B5 başlarken
  `grep -rn "BoqGroupSiteMismatchError" app/` ile mevcut desen bulunur ve birebir izlenir*
- `backend/tests/modules/units/test_units_api.py` (genişletme)

**Uygulama notları:**
- `DuplicateError` **açık `SELECT` ile önden** fırlatılır ki Türkçe alan mesajı verilebilsin;
  `IntegrityError → 409` handler'ı yarış-durumu ağı olarak **kalır** (P4 deseni, spec §4.3).
- Türkçe mesajlar spec §7.11 tablosundan **birebir** alınır; yeniden yazılmaz.

**Kabul kriteri:** 15 test yeşil; §4.5 tablosundaki **beş satırın beşi** de bir testle
karşılanmış (auto-assign / gönderilmiş / 0 şantiye / ≥2 gönderilmemiş / ≥2 gönderilmiş).

**Kapı komutu:**
```bash
createdb p3_units_b5 && \
  TEST_DATABASE_URL="postgresql+asyncpg://furkanilgen@localhost:5432/p3_units_b5" \
  .venv/bin/pytest tests/modules/units -x
dropdb p3_units_b5
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

**Geri alma:** eklenen rota fonksiyonları ve servis fonksiyonları geri alınır; şema/DB değişmedi.

---

### B6 — Ünite yazma uçları (`POST …/units`, `PATCH /units/{id}`)

| | |
|---|---|
| Boyut | **M** |
| Bağımlı | B5 |
| Risk | orta — **tip korkuluğu** (`owner_side`) ve `block_id` taşıma |

**Önce yazılacak testler** — `test_units_api.py` (genişletme)

1. `test_create_unit_happy_path_201`
2. `test_create_unit_duplicate_no_in_block_returns_409` → `_DUPLICATE_UNIT`
3. `test_create_unit_same_no_other_block_returns_201` (SY 76/106)
4. `test_create_unit_foreign_block_returns_404` (IDOR-9)
5. `test_create_unit_in_taahhut_project_returns_201` — **kısıt icat edilmedi** (spec §3.3)
6. `test_create_unit_owner_side_in_kendi_yatirim_returns_422` → `_OWNER_SIDE_NOT_ALLOWED`
7. `test_create_unit_appraisal_value_in_kendi_yatirim_returns_201` — **reddedilmez** (§3.3)
8. `test_create_unit_net_greater_than_gross_returns_422` → `_NET_GT_GROSS`
   (servis mesajı, DB CHECK'e düşmeden)
9. `test_create_unit_requires_full_permission` → 403
10. `test_patch_unit_partial_leaves_unsent_fields`
11. `test_patch_unit_null_clears_layout` — `layout: null` alanı boşaltır
12. `test_patch_unit_net_gt_gross_returns_422`
13. `test_patch_unit_moves_to_other_block`
14. `test_patch_unit_move_with_unit_no_conflict_returns_409`
15. `test_patch_unit_move_to_foreign_block_returns_404`
16. `test_patch_unit_invisible_returns_404` → `"Ünite bulunamadı"`

**KIRMIZI GÖR:** uçlar tanımsız → kırmızı.

**Dosyalar:** `router.py`, `service.py`, `errors.py`, `test_units_api.py` (hepsi genişletme)

**Uygulama notları:**
- `owner_side` korkuluğu servis katmanında; `project_type` başka tabloda olduğu için DB CHECK
  ile zorlanamaz (spec §3.3, P4'ün `BoqGroupSiteMismatchError` deseni birebir).
- `UnitUpdate`'te "gönderilmedi" ≠ "null yapıldı" ayrımı `model_fields_set` ile
  (P1/P2/P4 deseni).

**Kabul kriteri:** 16 test yeşil; spec §11.3'ün 11–19 numaralı senaryolarının **hepsi**
bir testle karşılanmış.

**Kapı komutu:**
```bash
createdb p3_units_b6 && \
  TEST_DATABASE_URL="postgresql+asyncpg://furkanilgen@localhost:5432/p3_units_b6" \
  .venv/bin/pytest tests/modules/units -x
dropdb p3_units_b6
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

**Geri alma:** rota + servis fonksiyonları geri alınır.

---

### B7 — DELETE uçları  ⚠️ RİSKLİ

| | |
|---|---|
| Boyut | **S** |
| Bağımlı | B6 |
| Risk | **veri kaybı sınıfı.** Yanlış yazılırsa tek istekle 24 daire sessizce silinir. |

**Önce yazılacak testler** — `test_units_api.py` (genişletme)

1. `test_delete_unit_returns_204`
2. `test_delete_unit_twice_returns_404`
3. `test_delete_unit_invisible_returns_404`
4. `test_delete_unit_requires_full_permission` → 403
5. `test_delete_block_with_units_returns_409` → `_BLOCK_HAS_UNITS`
   (`Bu blokta ünite var, önce üniteleri silin`)
6. `test_delete_block_with_units_leaves_block_and_units_intact` — 409 sonrası **blok duruyor,
   ünite sayısı değişmemiş** (cascade **olmadığının** kanıtı)
7. `test_delete_block_error_message_omits_unit_count` — mesajda sayı **yok**
   (görünürlük dışı bilgi sızdırmaz, spec §7.9)
8. `test_delete_empty_block_returns_204`
9. `test_delete_block_after_units_removed_returns_204` — akış doğrulaması
10. `test_delete_block_invisible_returns_404`

**KIRMIZI GÖR:** uçlar tanımsız → 405 ile kırmızı.

**Dosyalar:** `router.py`, `service.py`, `errors.py`, `test_units_api.py`

**Uygulama notları:**
- Ünite DELETE **koşulsuzdur** — P3'te üniteye bağlanan hiçbir tablo yok (spec §1.3).
  P8 geldiğinde satış korkuluğu **o dilimde** eklenir; bugün ileri bağ açılmaz.
- Blok DELETE'te cascade **yapılmaz**; servis korkuluğu **ve** DB `ON DELETE RESTRICT`
  (B1'de kondu) iki katmanlı güvence oluşturur.

**Kabul kriteri:** 10 test yeşil; test 6 **cascade olmadığını sayımla** kanıtlıyor.

**Kapı komutu:**
```bash
createdb p3_units_b7 && \
  TEST_DATABASE_URL="postgresql+asyncpg://furkanilgen@localhost:5432/p3_units_b7" \
  .venv/bin/pytest tests/modules/units -x
dropdb p3_units_b7
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

**Geri alma:** iki rota fonksiyonu çıkarılır. DB'de değişiklik yok (RESTRICT B1'de kondu,
B7'ye özel migration yok).

---

### B8 — Toplu üretim ucu (`POST …/units/bulk`)  ⚠️ RİSKLİ

| | |
|---|---|
| Boyut | **M** |
| Bağımlı | B6 |
| Risk | **hep-ya-hiç atomikliği.** Kısmi yazma sessiz veri hatasıdır. |

**Önce yazılacak testler** — `tests/modules/units/test_units_bulk.py`

Birim (numaralandırma):
1. `test_sequential_numbering_1_to_24` — 2 kat × 12 → `1…24` (SY 76–99)
2. `test_sequential_numbering_with_prefix` — `prefix="D"`, 4 adet → `D1…D4` (SY 132–135)
3. `test_sequential_numbering_respects_start_number`
4. `test_floor_based_numbering` — `start_floor=1, end_floor=2, units_per_floor=2` →
   `101, 102, 201, 202`
5. `test_floor_based_numbering_negative_floors` — bodrum katlar (`ge=-5`)

API:
6. `test_bulk_creates_24_units_returns_201` — `totals.counts.total == 24`
7. `test_bulk_response_is_full_unit_list` — yanıt güncel `UnitListResponse`
8. `test_bulk_conflict_returns_409_and_writes_nothing` — üretilecek numaralardan **biri**
   zaten var → **409**; **öncesi/sonrası ünite sayısı EŞİT** (atomiklik kanıtı)
9. `test_bulk_conflict_lists_first_20_numbers` — çakışan ilk 20 numara yanıtta
10. `test_bulk_inverted_floor_range_returns_422` → `_INVALID_FLOOR_RANGE`
11. `test_bulk_over_limit_returns_422` — 501 ünite → `_BULK_LIMIT`
12. `test_bulk_owner_side_type_mismatch_returns_422`
13. `test_bulk_foreign_block_returns_404`
14. `test_bulk_requires_full_permission` → 403
15. `test_bulk_invisible_project_returns_404`

**KIRMIZI GÖR:** uç tanımsız + numaralandırma yardımcısı yok → kırmızı.

**Dosyalar:**
- `backend/app/modules/units/bulk.py` (yeni — numaralandırma saf fonksiyonları; servisten ayrı
  tutulur ki birim testi DB'siz koşsun)
- `backend/app/modules/units/service.py`, `router.py` (genişletme)
- `backend/tests/modules/units/test_units_bulk.py` (yeni)

**Uygulama notları:**
- **Tek transaction**, doğrulama **yazmadan önce**. Numaralar üretilir → blokta mevcut
  `unit_no` kümesi tek `SELECT` ile çekilir → kesişim boş değilse hiçbir `INSERT` yapılmadan
  409 atılır.
- Test 8 bu davranışın **tek gerçek kanıtıdır**; sayım karşılaştırması olmadan test geçersizdir.

**Kabul kriteri:** 15 test yeşil; test 8'de öncesi/sonrası `SELECT count(*)` eşit.

**Kapı komutu:**
```bash
createdb p3_units_b8 && \
  TEST_DATABASE_URL="postgresql+asyncpg://furkanilgen@localhost:5432/p3_units_b8" \
  .venv/bin/pytest tests/modules/units -x
dropdb p3_units_b8
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

**Geri alma:** `bulk.py` silinir, rota çıkarılır. DB değişmedi.

---

### B9 — Excel içe aktarma ucu (`POST …/units/import`)  ⚠️ RİSKLİ

| | |
|---|---|
| Boyut | **L** |
| Bağımlı | B6, B5 (blok örtük oluşumu için) |
| Risk | **En riskli task.** Excel parse + multipart + Türkçe başlık normalizasyonu (`İ/ı`) + hep-ya-hiç + dosyanın **hiçbir yere yazılmaması**. |

**Önce yazılacak testler** — `tests/modules/units/test_units_import.py`

Birim (başlık/hücre çözümleme — DB'siz):
1. `test_header_normalization_trims_and_lowercases` — `"  liste fiyatı "` → `list_price`
2. `test_header_normalization_turkish_uppercase` — `"LİSTE FİYATI"` → `list_price`
3. `test_header_normalization_dotless_i` — `"ÜNİTE NO"` / `"ünite no"` → `unit_no`
4. `test_unknown_extra_columns_ignored`
5. `test_kind_dictionary_mapping` — `Daire`→`apartment`, `Dükkan`→`shop`; bilinmeyen → hata
6. `test_owner_side_dictionary_mapping` — `BİZ`→`contractor`, `ARSA`→`landowner`, boş→`None`

API:
7. `test_import_valid_10_rows_returns_200` — `created == 10`
8. `test_import_creates_missing_block` — dosyada yeni blok adı → `blocks_created == 1`,
   blok §4.5 şantiye kuralıyla açılmış
9. `test_import_row_error_returns_422_and_writes_nothing` — 3. satırda `net > brüt` →
   **422**, `errors[0].row == 3`, **ünite sayısı 0** (hep-ya-hiç kanıtı)
10. `test_import_duplicate_pair_within_file_returns_422` — dosya içinde aynı `(Blok, Ünite No)`
11. `test_import_existing_unit_no_returns_422`
12. `test_import_missing_required_header_returns_422` → `_IMPORT_MISSING_HEADERS`
    (`Excel başlıkları eksik: Blok, Ünite No`)
13. `test_import_csv_returns_422` → `_IMPORT_BAD_TYPE`
14. `test_import_xls_returns_422`
15. `test_import_oversize_file_returns_422` → `_IMPORT_TOO_LARGE` (2 MB, **413 değil**)
16. `test_import_too_many_rows_returns_422` → `_IMPORT_TOO_MANY_ROWS` (1000)
17. `test_import_error_list_capped_at_50` — 60 hatalı satır → 50 hata + `Ve N hata daha`
18. `test_import_owner_side_in_non_land_share_project_returns_422`
19. `test_import_does_not_persist_file` — **istek sonrası** geçici dizinde yeni dosya yok
    ve DB'de dosya içeriği taşıyan satır yok (belge saklama altyapısının
    gerekmediğinin kanıtı, spec §7.8)
20. `test_import_foreign_project_returns_404` / `test_import_requires_full_permission` → 403

**KIRMIZI GÖR:** uç tanımsız + parser yok → kırmızı.

**Dosyalar:**
- `backend/app/modules/units/importer.py` (yeni — saf parse/normalizasyon; DB'siz test edilebilir)
- `backend/app/modules/units/service.py`, `router.py` (genişletme)
- `backend/tests/modules/units/test_units_import.py` (yeni)

**Uygulama notları:**
- Bağımlılıklar **zaten var** (`openpyxl>=3.1`, `python-multipart>=0.0.20`, BOQ Excel
  dışa aktarımından). **`pyproject.toml` değiştirilmez** — B9 başlarken
  `grep -n "openpyxl\|multipart" pyproject.toml` ile doğrulanır; yoksa dur ve kullanıcıya sor.
- Dosya `UploadFile`'dan **bellekte** okunur (`await file.read()`), `openpyxl` ile
  `io.BytesIO` üzerinden açılır, **diske/S3'e/DB'ye yazılmaz**. Test 19 bunu kilitliyor.
- Boyut sınırı okumadan **önce** `content_length` ile, sonra okunan `bytes` uzunluğuyla
  **iki kez** kontrol edilir (istemci başlığına güvenilmez).
- Sütun düzeni spec §7.8 tablosundan **birebir** (A `Blok` … I `Pay`).

**Kabul kriteri:** 20+ test yeşil; test 19 dosya izi bırakılmadığını kanıtlıyor;
`pyproject.toml` **değişmemiş** (`git diff --stat pyproject.toml` boş).

**Kapı komutu:**
```bash
createdb p3_units_b9 && \
  TEST_DATABASE_URL="postgresql+asyncpg://furkanilgen@localhost:5432/p3_units_b9" \
  .venv/bin/pytest tests/modules/units -x
dropdb p3_units_b9
git diff --stat pyproject.toml    # BOŞ olmalı
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

**Geri alma:** `importer.py` silinir, rota çıkarılır. Yeni bağımlılık eklenmediği için
deploy tarafında geri alma etkisi yok.

---

### B10 — Paylaşım ucu + IDOR negatif setinin tamamı  ⚠️ RİSKLİ

| | |
|---|---|
| Boyut | **L** |
| Bağımlı | B6 (pratikte B7–B9 sonrası koşulur, çünkü IDOR seti onların uçlarını da kapsar) |
| Risk | **Güvenlik sınıfı.** P2'de IDOR bu tam noktada yakalandı. |

**Önce yazılacak testler** — `tests/modules/units/test_units_allocation.py` +
`tests/modules/units/test_units_idor.py`

Paylaşım (`test_units_allocation.py`):
1. `test_allocation_updates_42_units_in_one_request` — yanıt güncel `UnitListResponse`
2. `test_allocation_null_clears_owner_side` — `owner_side: null` atamayı kaldırır (§5.3)
3. `test_allocation_duplicate_unit_id_returns_422` → `_DUPLICATE_IN_PAYLOAD`,
   **hiçbir satır yazılmamış**
4. `test_allocation_in_kendi_yatirim_returns_422` → `_ALLOCATION_WRONG_TYPE`
5. `test_allocation_empty_list_returns_422` (min 1)
6. `test_allocation_over_500_items_returns_422`
7. `test_allocation_response_reflects_new_side_totals` — `sides` toplamları güncel

IDOR (`test_units_idor.py` — spec §11.4 tablosunun **14 satırının hepsi**, birebir):
8. `test_idor_get_units_invisible_project_404`
9. `test_idor_get_blocks_invisible_project_404`
10. `test_idor_post_units_blocks_bulk_import_invisible_404` (dört uç, parametrik)
11. `test_idor_patch_unit_invisible_404`
12. `test_idor_patch_block_invisible_404`
13. `test_idor_delete_unit_and_block_invisible_404`
14. `test_idor_unknown_uuid_same_message_as_invisible` — ayırt edilemez
15. `test_idor_allocation_with_other_project_unit_404_and_atomic` — B projesinin ünitesi
    listede → **404** ve **A'nın hiçbir satırı değişmemiş** (öncesi/sonrası karşılaştırma)
16. `test_idor_post_unit_with_foreign_block_404`
17. `test_idor_import_block_name_collision_creates_in_own_project` — Excel'deki `Blok`
    adı başka projenin bloğuyla aynı → yeni blok **A projesinde** açılır, B'ye dokunulmaz
18. `test_idor_no_token_401`
19. `test_idor_projects_permission_none_403`
20. `test_idor_view_permission_rejects_all_writes_403` — POST/PATCH/DELETE/bulk/import/
    allocation (parametrik, **altı uç**)
21. `test_idor_admin_role_bypasses_visibility_200`
22. `test_idor_error_bodies_do_not_leak_record_existence` — her negatif yanıtta gövde
    kayıt kimliği/adı/sayısı **taşımıyor**

**KIRMIZI GÖR:** allocation ucu tanımsız → kırmızı. IDOR testlerinin bir kısmı B4–B9
uçları hazır olduğu için **yeşil başlayabilir** — bu **beklenen**dir ve sorun değildir;
kırmızı görülmesi gereken testler allocation ucuna ait olanlardır. Yeşil başlayan IDOR
testleri regresyon ağıdır, TDD ihlali değildir.

**Dosyalar:** `service.py`, `router.py`, `errors.py` (genişletme) +
`test_units_allocation.py`, `test_units_idor.py` (yeni)

**Uygulama notları:**
- **Tek transaction**; tüm `unit_id`'ler önce tek `SELECT` ile çekilir, proje eşleşmesi
  ve tekrar kontrolü **yazmadan önce** yapılır.
- Proje tipi `kat_karsiligi` değilse hiç işlem yapılmadan 422.

**Kabul kriteri:** spec §11.4 tablosunun **14 satırının 14'ü** en az bir testle karşılanmış
(planı kapatan ajan satır↔test eşleme tablosunu raporunda verir); allocation testleri yeşil;
test 15 ve 3 atomikliği **sayımla** kanıtlıyor.

**Kapı komutu:**
```bash
createdb p3_units_b10 && \
  TEST_DATABASE_URL="postgresql+asyncpg://furkanilgen@localhost:5432/p3_units_b10" \
  .venv/bin/pytest tests/modules/units -x
dropdb p3_units_b10
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

**Geri alma:** allocation rotası + servis fonksiyonu çıkarılır; IDOR testleri **kalır**
(geri alınmaz, regresyon değeri var).

---

### B11 — Denetim günlüğü

| | |
|---|---|
| Boyut | **M** |
| Bağımlı | B5, B6, B7, B8, B9, B10 (tüm yazma uçları hazır olmalı) |
| Risk | düşük |

**Önce yazılacak testler** — `tests/modules/units/test_units_audit.py`

1. `test_block_create_writes_one_audit_row` — `AuditAction.create`,
   mesaj `"Yeni blok oluşturuldu: {proje} · {blok}"`
2. `test_block_update_writes_audit`
3. `test_block_delete_writes_audit_with_delete_action`
4. `test_unit_create_writes_audit` — mesajda **proje adı da var**
   (`"Yeni ünite oluşturuldu: {proje} · {blok} · {no}"`; ünite adları projeler arası tekrar
   ettiği için proje adı olmadan satır anlamsız — spec §9)
5. `test_unit_update_writes_audit`
6. `test_unit_delete_writes_audit_with_delete_action`
7. `test_bulk_writes_exactly_one_audit_row_for_24_units` — **1**, 24 değil
8. `test_import_writes_exactly_one_audit_row_for_10_units` — **1**
9. `test_allocation_writes_exactly_one_audit_row_for_42_units` — **1**
   (42 satırlık kayıt günlüğü boğar, spec §9)
10. `test_read_endpoints_write_no_audit` — `GET …/blocks` ve `GET …/units` sonrası
    `audit_log` **hiç** büyümez
11. `test_audit_rows_carry_actor_and_ip` — `actor_user_id` + `ip_address`
12. `test_failed_write_writes_no_audit` — 409/422 ile reddedilen istek günlük **yazmaz**

**KIRMIZI GÖR:** `record_audit` çağrısı yok → 12 test kırmızı.

**Dosyalar:**
- `backend/app/modules/audit/messages.py` (genişletme — spec §9'daki **9 fonksiyon**, birebir)
- `backend/app/modules/units/service.py` / `router.py` (genişletme — `record_audit` çağrıları)
- `backend/tests/modules/units/test_units_audit.py` (yeni)

**Uygulama notları:**
- Mesaj metinleri spec §9'dan **birebir kopyalanır**; yeniden yazılmaz.
- Mesajlar `audit/messages.py`'de **merkezi**; f-string'ler router içine gömülmez (P4 T7 kuralı).
- Okuma uçları **yazmaz** (test 10 kilitliyor).

**Kabul kriteri:** 12 test yeşil; `messages.py`'ye **tam 9** fonksiyon eklenmiş;
mevcut audit testleri (`test_audit_*.py`) değişmeden yeşil.

**Kapı komutu:**
```bash
createdb p3_units_b11 && \
  TEST_DATABASE_URL="postgresql+asyncpg://furkanilgen@localhost:5432/p3_units_b11" \
  .venv/bin/pytest tests/modules/units tests/modules/test_audit_api.py \
    tests/modules/test_audit_service.py -x
dropdb p3_units_b11
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

**Geri alma:** `record_audit` çağrıları ve 9 mesaj fonksiyonu çıkarılır; DB değişmedi
(`audit_log` tablosu zaten vardı).

---

### B12 — `openapi.json` üretimi + tam kapı koşusu

| | |
|---|---|
| Boyut | **S** |
| Bağımlı | B1–B11 |
| Risk | düşük |

**Önce yazılacak testler** — yeni test yazılmaz; **tam paket** koşulur.
Tek yeni doğrulama `tests/modules/units/test_units_openapi.py` (isteğe bağlı ama önerilir):
1. `test_openapi_exposes_all_eleven_endpoints` — spec §7'deki **11 uç** şemada var
   (yol + yöntem eşlemesi tablosuyla)

**Dosyalar:**
- `backend/openapi.json` (üretilir — **gitignore'lu, COMMIT EDİLMEZ**)
- `backend/tests/modules/units/test_units_openapi.py` (yeni, isteğe bağlı)

**Uygulama notları:**
- `openapi.json` üretimi uygulamayı import eder → env değişkenleri **komut satırında** verilir.
- Şemada `app__modules__projects__schemas__MetricPlaceholder` gibi uzun ad görünmesi
  **beklenen davranıştır** (P4 T9 notu), düzeltilmez.

**Kabul kriteri:**
- **Tüm** test paketi yeşil (`tests/` tamamı, `-x` olmadan, sayı raporlanır)
- `ruff check .` → çıkış `0`; `ruff format --check .` → çıkış `0`
- `.venv/bin/alembic heads` → **tek** head
- `git status` çıktısında `openapi.json` **yok** (gitignore çalışıyor)
- Modül sayısı testleri (17) yeşil ve **dosyaları değişmemiş** (`git diff --stat` boş)

**Kapı komutu:**
```bash
cd /Users/furkanilgen/Documents/Projeler/insaat/backend
createdb p3_units_b12 && \
  TEST_DATABASE_URL="postgresql+asyncpg://furkanilgen@localhost:5432/p3_units_b12" \
  .venv/bin/pytest tests/
dropdb p3_units_b12
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/alembic heads
TEST_DATABASE_URL="postgresql+asyncpg://furkanilgen@localhost:5432/postgres" \
  .venv/bin/python -c "import json;from app.main import app;print(json.dumps(app.openapi(),ensure_ascii=False,indent=2))" \
  > openapi.json
git status --short | grep openapi.json && echo "HATA: openapi.json takip ediliyor" || echo "OK"
```

**Geri alma:** `openapi.json` silinir; kod değişmedi.

---

## 2. Sıralama ve kritik yol

```
B1 → B2 → B3 → B4 → B5 → B6 ─┬─→ B7  ─┐
                              ├─→ B8  ─┤
                              ├─→ B9  ─┼─→ B11 → B12
                              └─→ B10 ─┘
```

**Kritik yol (en uzun zincir, 10 düğüm):**
`B1 → B2 → B3 → B4 → B5 → B6 → B9 → B11 → B12`
(B9 seçildi çünkü dört paralel daldan **en büyüğü** ve B5'e de bağımlı; B7/B8/B10 daha kısa.)

**Paralel koşabilir** (B6 bittikten sonra, ayrı ajanlara verilebilir):
B7 · B8 · B9 · B10. **Ancak** dördü de `service.py` ve `router.py`'ye yazıyor →
**aynı repoda aynı anda iki ajan çalışmaz** kuralı gereği bunlar **sıralı** koşturulur,
paralellik yalnız planlama esnekliğidir. Önerilen sıra: **B7 → B8 → B9 → B10**
(en küçükten en riskliye, her adımda test tabanı büyüyerek).

---

## 3. Riskli task'lar (özet)

| Task | Risk sınıfı | Neden | Ek korkuluk |
|---|---|---|---|
| **B1** | Şema / migration | Enum `CREATE TYPE` + bileşik FK + downgrade'de `DROP TYPE`. Postgres enum'ı tabloyla silmez → downgrade sessizce yarım kalır | round-trip testi (test 17) + `pg_type` doğrulaması |
| **B7** | Veri kaybı | Blok DELETE yanlış yazılırsa 24 daire tek istekte gider | 409 sonrası sayım testi (test 6) + DB `ON DELETE RESTRICT` |
| **B8** | Atomiklik | Kısmi toplu üretim sessiz veri hatası; kullanıcı 48'den 3'ünün atlandığını fark etmez | öncesi/sonrası sayım eşitliği (test 8) |
| **B9** | Parse + kaynak | Excel parse, Türkçe `İ/ı` normalizasyonu, multipart bellek sınırı, dosyanın hiçbir yere yazılmaması | boyut/satır sınırı iki kez kontrol; dosya izi testi (test 19); `pyproject.toml` diff boş kapısı |
| **B10** | Güvenlik (IDOR) | P2'de tam bu sınıf hata yakalandı; dolaylı kimlik çözümleyen uçlar en kolay atlanan nokta | spec §11.4'ün 14 satırının satır↔test eşleme tablosu raporda zorunlu |

---

## 4. "Bitti" tanımı — kapanış kontrol listesi

Dilim ancak aşağıdakilerin **hepsi** işaretlendiğinde kapanır:

**Migration**
- [ ] `.venv/bin/alembic heads` → **tek** head, yeni revizyon
- [ ] `down_revision` doğrulanmış ebeveyne bağlı (B1 §0.2 çıktısı raporda)
- [ ] `upgrade → downgrade → upgrade` yerel DB'de yeşil (B1 test 17)
- [ ] Downgrade sonrası **iki enum tipi de** `pg_type`'da yok
- [ ] Canlı DB'ye **hiçbir** migration koşulmadı

**İzin kararı (spec §8)**
- [ ] `modules` / `role_permissions` tablolarına **dokunulmadı**
- [ ] `app/core/seed_data.py` MATRIX **değişmedi** (`git diff --stat` boş)
- [ ] `test_seed_matrix.py`, `test_roles_repository.py`, `test_roles_api.py`
      **dosyaları değişmeden** yeşil — **modül sayısı 17'de KALDI**
- [ ] Frontend `e2e/mock-backend.ts` ve `ayarlar-izin-matrisi` görsel baseline'ı
      için **yeni bir kayma üretilmedi** (backend tarafında yapılacak iş yok)

**Denetim mesajları (spec §9)**
- [ ] `audit/messages.py`'ye **9 fonksiyon** eklendi, metinler spec'le birebir
- [ ] Dokuz yazma ucunun **dokuzu da** `record_audit` çağırıyor, doğru `AuditAction` ile
- [ ] Toplu uçlar (`bulk` / `import` / `allocation`) **istek başına tek satır** yazıyor
- [ ] Okuma uçları (`GET …/blocks`, `GET …/units`) **hiç** yazmıyor
- [ ] Reddedilen istekler (409/422) günlük yazmıyor

**Uçlar ve sözleşme**
- [ ] Spec §7'deki **11 ucun 11'i** de kayıtlı ve testli
- [ ] Türkçe hata mesajları spec §7.11 tablosuyla **birebir** (22 sabitin hepsi)
- [ ] Spec §11.4 IDOR tablosunun **14 satırının 14'ü** testle karşılanmış
- [ ] `MetricPlaceholder` P1'den **import** edilmiş, kopyalanmamış

**OpenAPI**
- [ ] `openapi.json` üretildi, 11 uç şemada
- [ ] **Commit EDİLMEDİ** (`git status` temiz)
- [ ] Frontend'e kopyalanmaya hazır bırakıldı

**Kapılar**
- [ ] `.venv/bin/pytest tests/` — **tam paket** yeşil (test sayısı raporda)
- [ ] `.venv/bin/ruff check .` → `0`
- [ ] `.venv/bin/ruff format --check .` → `0`
- [ ] Her `createdb` için karşılık gelen `dropdb` koşuldu (artık test DB'si kalmadı:
      `psql -l | grep p3_units` → boş)

**Süreç**
- [ ] Ajanlar **push etmedi**; PR/merge/deploy kullanıcıda
- [ ] `frontend/` altına **tek satır** yazılmadı
- [ ] `backend/.env` **değiştirilmedi** (`git diff .env` boş / dosya takip edilmiyorsa dokunulmadı)

---

## 5. Frontend'e devredilen iş (bu planın kapsamı DIŞI)

Aşağıdakiler backend'in işi **değildir**, ama P3 frontend diliminin **ilk task'ına**
not düşülmek üzere burada kayıtlıdır:

1. **BFF TUZAĞI — İKİ yeni kök var: `units` VE `blocks`.**
   `frontend/src/app/api/backend/[...path]/route.ts` içindeki `ALLOWED_ROOTS` listesine
   **ikisi de** eklenmelidir. Eklenmezse ilgili uçlar **yalnız canlıda 404** verir;
   jsdom testleri bunu **yakalamaz** (`GOREV-SIRASI.md` §3, P4'te aynı tuzağa düşüldü).
   Not: `projects` kökü zaten listede — proje bağlamlı uçlar (`/projects/{id}/units`,
   `/projects/{id}/blocks`, `…/bulk`, `…/import`, `…/allocation`) o kökten geçer;
   eksik olan tekil uçlardır (`PATCH /units/{id}`, `DELETE /units/{id}`,
   `PATCH /blocks/{id}`, `DELETE /blocks/{id}`).

2. **`openapi.json` senkronu:** B12'nin ürettiği dosya `frontend/openapi/openapi.json`'a
   kopyalanmadan `pnpm gen:api` **koşulmaz** (P4 T9'daki sert bariyerin aynısı).

3. **Yeni `pendingModuleLabel` anahtarları:** `unit_sales`, `shareholder_units`,
   `project_costs`. `frontend/src/lib/pending-modules.ts` içinde karşılıkları yoksa
   eklenmelidir; yoksa ekran ham anahtar basar.

4. **UI etiketleme sözleşmesi (spec §4.4, bağlayıcı):**
   `KY 274 → "Liste Fiyatı" → list_price` · `KKP 89 → "Rayiç Değer" → appraisal_value` ·
   ünite formunda **iki alan birden**, proje tipine göre beklenen olan öne çıkarılır.

5. **Excel içe aktarma formu:** `multipart/form-data`, tek alan `file`, yalnız `.xlsx`.
   Sunucu 422 gövdesindeki `errors: [{row, column, message}]` listesi kullanıcıya
   **satır satır** gösterilmeli — tek satırlık genel hata mesajı bu ucun değerini yok eder.

---

## 6. Dilim dışı takip işleri (spec §14'ten aktarıldı — bu planda YAPILMAZ)

| İş | Neden burada değil |
|---|---|
| `boq` DELETE uçları (`DELETE /boq/items/{id}`, `DELETE /boq/groups/{id}`) — kullanıcı 2026-07-30'da karar verdi | `boq` **ayrı dilimdir** (P4, kapandı ve canlıda); P3 PR'ına karıştırmak iki modülü tek PR'da riske atar. Frontend BOQ F8 task'ı buna bağımlıdır → ayrı küçük dilim olarak planlanmalı |
| Paylaşım tablosu Excel **dışa** aktarımı (KKP 24) | P5 / raporlar |
| Teslim kilometre taşları (KKP 176–193) | P11 (Gantt) |
| Sözleşme yükümlülükleri + teminat türü (KK 191, 194–199) | P5 (Sözleşmeler); `project_land_share` şemasına dokunacak |

---

Kapanış akışı: 12 task → review → commit → **kullanıcı** push/PR → CI →
**kullanıcı** merge → Railway auto-deploy → **canlı migration doğrulaması**
(`railway logs` / `alembic current`).
