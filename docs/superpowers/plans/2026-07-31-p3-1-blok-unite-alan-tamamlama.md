# Alt-Proje 2 · P3.1 — Blok/ünite alan tamamlama · UYGULAMA PLANI (taslak)

Tarih: 2026-07-31 · **taslak, onay bekliyor**
Repo: `fiilyapi-backend` (`/Users/furkanilgen/Documents/Projeler/insaat/backend`)
Durum: **yalnız plan.** Kod, migration, test yazılmadı; commit/push atılmadı.

> **Çıktı yolu notu:** bu dosya geçici olarak repo dışında
> (`insaat/P3-1-PLAN-TASLAK.md`) durmaktadır çünkü yazıldığı sırada backend
> reposunda **başka bir oturum (P6)** çalışıyordu. Onaydan sonra
> `backend/docs/superpowers/plans/2026-07-31-alt-proje-2-p3-1-blok-unite-alan-tamamlama.md`
> yoluna taşınacaktır. Spec de aynı anda
> `backend/docs/superpowers/specs/2026-07-31-p3-1-blok-unite-alan-tamamlama-design.md`
> yoluna taşınır.

**Spec:** `P3-1-SPEC-TASLAK.md` (rev. 2) — bu plandaki "spec §N" atıfları o dosyayadır.
**Her task başında ilgili spec bölümü OKUNUR**, ezberden yazılmaz.

**Ajanlar için:** ZORUNLU ALT-BECERİ: `superpowers:subagent-driven-development`.
Adımlar `- [ ]` kutucuklarıyla izlenir. **Her task sonunda commit** edilir; push YOK.

**Hedef:** `blocks` +13 kolon / +4 enum · `units` +8 kolon / +3 enum + `unit_kind`
genişlemesi · blok kodu üretimi · toplu üretimin yeniden tasarımı (slot şablonu, 4 desen,
kat fiyat artışı, önizleme ucu) · Excel içe aktarmanın **kısmi aktarıma** geçişi
(doğrulama ucu + şablon ucu + `site_id`). **11 uç → 14 uç.**

**Teknoloji:** FastAPI · SQLAlchemy 2 (async) · Alembic · Pydantic v2 · pytest ·
PostgreSQL · ruff **0.15.22** · `openpyxl` (mevcut bağımlılık, yeni paket yok)

---

## 0. BAŞLAMADAN ÖNCE — repo durumu doğrulaması (ADIM 1, atlanamaz)

Bu dilim **başka bir oturumun P6 (Bölüm Detay) çalışmasıyla AYNI REPODA** koşacak.
`GOREV-SIRASI.md` §3: *"Aynı repoda aynı anda iki ajan çalışmaz."*

- [ ] **A0.1** `git -C backend status --short --branch` → çalışma ağacı **temiz** mi,
      hangi dal üzerindeyiz?
- [ ] **A0.2** `git -C backend log --oneline -5` → son commit'ler P6'ya mı ait?
- [ ] **A0.3** `git -C backend branch -a --sort=-committerdate | head` → `feat/p6-*`
      dalı var mı, aktif mi?
- [ ] **A0.4** **Kirli ağaç, P6 dalı üzerinde olmak veya P6 commit'lerinin devam etmesi
      → DUR, kullanıcıya sor.** Kendi dalını açma, `stash` yapma, `checkout` etme.
- [ ] **A0.5** Temizse: `main`'in güncelliğini doğrula, `feat/p3-1-blok-unite-alan`
      dalını **kullanıcı onayıyla** aç.

> Bu adım plan içindeki ilk iştir; T1'den **önce** gelir ve sonucunu kullanıcıya bildirir.

---

## 0.A ⚠️⚠️ TUZAKLAR — her task'ta yeniden okunur

### 0.A.1 MIGRATION TUZAĞI — canlı crash'e yol açtı (2026-07-31, P7)

`backend/.env`'deki **`DATABASE_URL` de uzak Railway'i gösteriyor**
(`tokaido.proxy.rlwy.net`) — bilinen `TEST_DATABASE_URL` tuzağının **ikizi**.
`alembic` override'sız çalıştırılırsa **CANLIYA VURUR**; **`alembic heads` bile**
`env.py` üzerinden bağlanmaya çalışır.

**Her alembic çağrısında ŞART — `heads`/`current`/`history` dahil:**

```bash
DATABASE_URL="postgresql+asyncpg://furkanilgen@localhost:5432/<yerel>" .venv/bin/alembic heads
DATABASE_URL="postgresql+asyncpg://furkanilgen@localhost:5432/<yerel>" .venv/bin/alembic upgrade <rev>
```

`.env`'e **DOKUNULMAZ**. **Canlı DB'ye migration KOŞULMAZ** — canlı, merge edilmiş
kodun deploy'unda kendi migration'ını koşar. P7'de bu tuzak `alembic_version`'ı
deploy'daki kodun bilmediği bir revizyona damgaladı ve konteyner
`Can't locate revision identified by …` ile crash döngüsüne girdi.

### 0.A.2 TEST DB TUZAĞI

`TEST_DATABASE_URL` de uzağı gösteriyor **ve** `conftest.py` `drop_all` çağırıyor.
`.env`'e **DOKUNULMAZ**; env **komut satırında** verilir; **başarısızlıkta bile `dropdb`**:

```bash
createdb p31_tN
TEST_DATABASE_URL="postgresql+asyncpg://furkanilgen@localhost:5432/p31_tN" .venv/bin/pytest …
dropdb p31_tN     # BAŞARISIZLIKTA BİLE
```

### 0.A.3 Migration testlerinde `head` / `-1` KULLANILMAZ

Açık revizyon id'sine sabitlenir. `-1` her yeni migration'da yanlış revizyonu geri alır
(bu tuzak **iki kez** yaşandı).

### 0.A.4 Postgres enum'ı tabloyla silinmez

`downgrade()`'de `DROP TYPE IF EXISTS …` unutulursa **ikinci `upgrade` patlar**.
Bu dilimde **8 enum tipi** var (`unit_kind` takası + 7 yeni) → her birinin `DROP TYPE`'ı
kendi revizyonunun `downgrade`'ine yazılır. **Enum takası kendi izole revizyonundadır**
(`d1a2b3c4e5f6` / `f1b2c3d4e5a6` dersi).

### 0.A.5 Hiçbir yeni kolon `NOT NULL` yapılmaz

Gerekçe canlı veri değil, **taslak desteğidir** (`GOREV-SIRASI.md` §4 Kalıcı Karar 4).
`status` ve `sales_status` yalnız `server_default` alır (`'construction'` / `'listed'`);
bu mevcut satırları **değiştirmez**. Mockup'taki kırmızı `*` **yalnız UI ipucudur**
(spec karar 11) — ne DB'de `NOT NULL`, ne Pydantic `Create`'te zorunluluk.

### 0.A.6 İzin modülü sayısı **18**'de SABİT

P5 `contracts` modülünü ekleyip 17 → **18** yaptı; P7 yeni modül açmadı. Matris
**18×8 = 144**. `app/core/seed_data.py`'ye ve izin migration'ına **DOKUNULMAZ**.
`tests/modules/test_seed_matrix.py`, `test_roles_repository.py`, `test_roles_api.py`
**hiç dokunulmadan yeşil kalmalıdır** — kırmızıya dönerlerse yanlış bir şey yapılmıştır.

### 0.A.7 KAPI TÜM REPODUR

CI `ruff check .` + `ruff format --check .` koşar. `app tests` ile sınırlı koşum
`alembic/` dizinini kaçırır ve CI'da kırmızıya düşer (P5'te yaşandı, PR #9).

### 0.A.8 `openapi.json` gitignore'ludur

Commit **edilmez**; frontend'e elle kopyalanır.

### 0.A.9 ⚠️ BU DİLİM MEVCUT DAVRANIŞI İKİ YERDE DEĞİŞTİRİYOR

Her ikisi de **mevcut yeşil testleri kıracak**. Kırılan testler **bilerek** güncellenir;
"regresyon" sanılıp geri alınmaz. Tam liste §4'te, task bazında ilgili task'ta.

1. **Excel: hep-ya-hiç → kısmi aktarım** (spec §6.1, P3 §7.8'den dönüş) → T12
2. **Ünite numarası biçimi: `C-04`/`101` → `C-4`/`11`** (spec §5.2, karar 1;
   `_FLOOR_SEQUENCE_WIDTH = 2` sabiti ve onu açıklayan yorum **silinir**) → T8

### 0.A.10 TDD zorunlu — "KIRMIZI GÖR" atlanamaz

Test önce yazılır, **başarısız olduğu görülür**, sonra kod. Test ilk koşuda yeşilse
test yanlıştır → **mutasyon denetimi**: implementasyonda bir satır bozulur, testin
kırmızıya döndüğü doğrulanır, geri alınır. Bu adım her task'ta ayrı kutucuktur.

### 0.A.11 Ajanlar push etmez

Commit serbest; push/PR/merge/deploy kararı kullanıcıdadır. **Merge ≠ deploy**
(Railway otomatik deploy'u 2026-07-30'dan beri çalışmıyor).

---

## 0.B Kapatılmış açık madde (koordinatör, kesin)

**`{Blok}` jetonu, `code`'u `NULL` olan canlı blokta:** üretim anında
`_derive_block_code(block.name)` ile **türetilir, SAKLANMAZ**. Aynı saf fonksiyon
çağrıldığı için ikinci otorite doğmaz; blok bir kez düzenlenip kodu kalıcılaştığında
çıktı birebir aynıdır. `422 "Önce blok kodunu belirleyin"` alternatifi **reddedildi**
(kullanıcıyı canlı blokta toplu üretimden kilitler). **Kesinleşmiştir**, yeniden
tartışılmaz. Testi: T9 / §12.4-30c.

---

## 0.C ⚠️ PLANIN AÇTIĞI TEK YENİ AÇIK MADDE (T8'den önce cevap gerekir)

**`UnitNumberingPattern` 2 → 4 mi, 2 → 5 mi?**

Spec §5.2 dört mockup desenini kanon yapıyor: `block_sequence`, `floor_sequence`,
`label_sequence`, `block_floor_sequence`. Fakat:

* Mevcut enum `sequential` (`prefix + str(start_number + i)`, **çıplak sayı**) ve
  `floor_based` değerlerini taşıyor.
* Spec §5.2 `prefix`'in **korunduğunu** ve **SY 132–135'in `D1…D4` dükkan
  numaralandırmasının tek yolu** olduğunu söylüyor; spec §12.1/6 testi de
  `prefix="D"` + **"`sequential`-benzeri"** → `D1…D4` diyor.
* Ama dört yeni desenin **hiçbiri çıplak sayı üretmiyor** (`label_sequence` →
  `Daire 1`). Yani `D1…D4` regresyonu dört desenle **üretilemez**.

**Plan önerisi:** enum **5 değerli** olsun — dört mockup deseni + korunan `sequential`
(çıplak sayı, `prefix` ile birlikte SY 132–135'i karşılar). `floor_based` ise
`floor_sequence` olarak **yeniden adlandırılır** (davranış zaten karar 1 ile değişiyor).

**Bu bir icat değil, bir çelişkinin kapatılmasıdır** ve kullanıcı/koordinatör onayı ister.
Onay gelmezse T8 **başlamaz** — alternatif (sequential'ı silip SY regresyonunu düşürmek)
mevcut bir ekranı sessizce kırar.

---

## 1. Dosya haritası

| Dosya | Sorumluluk | Task |
|---|---|---|
| `alembic/versions/<r1>_p31_unit_kind_enum.py` | **R1** — `unit_kind` enum takası, izole (YENİ) | T1 |
| `alembic/versions/<r2>_p31_yeni_enum_tipleri.py` | **R2** — 7 yeni enum tipi, izole (YENİ) | T2 |
| `alembic/versions/<r3>_p31_blok_unite_kolonlari.py` | **R3** — 13+8 kolon, 1 UNIQUE, 10 CHECK (YENİ) | T3 |
| `app/modules/units/models.py` | `UnitKind` +3 değer · 7 yeni enum · 21 yeni kolon · **`sales_status` P8 geçiş notu docstring'e** | T1–T3 |
| `app/modules/units/codes.py` | `_derive_block_code` saf fonksiyonu (YENİ dosya) | T4 |
| `app/modules/units/guards.py` | +10 Türkçe mesaj sabiti · `ensure_block_code_unique` · `ensure_vat_rate` | T4, T5, T6 |
| `app/modules/units/schemas.py` | blok +13, ünite +8, `UnitKindBreakdown` +3, `UnitBulkSlot`, `UnitBulkPreview*`, `UnitImport*` | T5, T6, T8, T9, T12 |
| `app/modules/units/repository.py` | `floor` / `sales_status` süzgeçleri · `by_sales_status` sayacı · blok kodu benzersizlik sorgusu | T4, T7 |
| `app/modules/units/summary.py` | `totals.by_sales_status`, `sold/reserved/available` yer tutucu → gerçek | T7 |
| `app/modules/units/bulk.py` | **yeniden yazım**: 4(+1) desen, dolgu kuralı, kat etiketi, `roof_floor`, slot, fiyat artışı | T8 |
| `app/modules/units/service.py` | blok kodu üretimi · ünite yeni alanları · bulk slot uygulaması · preview | T5, T6, T9, T10 |
| `app/modules/units/importer.py` | 12 sütun, 2 başlık yeniden adlandırma + eşanlamlılar, `Kat`/`Cephe`/`Maliyet` | T11 |
| `app/modules/units/batch.py` | **kısmi aktarım** yeniden yazımı, `site_id`, `include_warnings` | T12 |
| `app/modules/units/template.py` | şablon `.xlsx` üreteci (YENİ dosya) | T14 |
| `app/modules/units/router.py` | 3 yeni uç + 8 değişen uç | T5–T14 |
| `app/core/errors.py` | `UnitImportError` temizliği | T12 |
| `app/modules/audit/messages.py` | `units_imported` imza değişimi | T15 |
| `tests/modules/units/test_units_models.py` | enum üyeleri, kolon nullable'lığı | T1–T3 |
| `tests/modules/units/test_units_migration.py` | R1→R2→R3 upgrade/downgrade/upgrade | T1–T3 |
| `tests/modules/units/test_units_block_codes.py` | `_derive_block_code` birim testleri (YENİ) | T4 |
| `tests/modules/units/test_units_api.py` | blok/ünite uçları | T5, T6, T7 |
| `tests/modules/units/test_units_schemas.py` | şema doğrulamaları, `vat_rate` kümesi | T5, T6 |
| `tests/modules/units/test_units_bulk.py` | numaralandırma + slot + fiyat artışı (**kırılacak testler burada**) | T8, T10 |
| `tests/modules/units/test_units_bulk_preview.py` | önizleme ucu (YENİ) | T9 |
| `tests/modules/units/test_units_import.py` | Excel çözümleme + **kısmi aktarım** (**kırılacak testler burada**) | T11, T12, T13 |
| `tests/modules/units/test_units_import_template.py` | şablon ucu (YENİ) | T14 |
| `tests/modules/units/test_units_audit.py` | `units_imported` + "yazmaz" testleri | T15 |
| `tests/modules/units/test_units_idor.py` | 3 yeni uç için IDOR seti | T16 |
| `tests/modules/units/test_units_openapi.py` | 14 uç şeması | T17 |

**Dokunulmayanlar (bilerek):** `app/core/seed_data.py` · `app/modules/boq/**` ·
`app/modules/sections/**` · `app/modules/contracts/**` · `tests/modules/test_seed_matrix.py`.

---

## 2. Task listesi

Boyut ölçeği: **S** ≈ tek dosya + 3-6 test · **M** ≈ 2-4 dosya + 8-15 test ·
**L** ≈ yeniden yazım + 15+ test veya migration'lı.

Her task'ın **kapı komutu** tek kullanımlık yerel DB kullanır (§0.A.2) ve
**başarısızlıkta bile `dropdb`** çalıştırılır.

---

### Task T0 — Spec + plan onayı · **S** · bağımlılık: yok

- [ ] Spec rev. 2 kullanıcı onayı (§13.2'nin tek maddesi §0.B ile kapatıldı)
- [ ] **§0.C'nin cevabı alınır** (4 mi 5 mi desen) — T8'i bloke eder
- [ ] Bu plan onaylanır
- [ ] §0 repo durumu doğrulaması koşulur ve sonucu bildirilir

**Kabul kriteri:** spec + plan onaylı; §0.C karara bağlanmış; dal açık ve temiz.
**Kapı komutu:** yok (kod yok).

---

### Task T1 — R1: `unit_kind` enum takası (izole) · **M** · ⚠️ **RİSKLİ** · bağımlılık: T0

**Amaç:** `unit_kind` enum'unu `apartment · shop` → `apartment · shop · office ·
warehouse · parking` yapmak. **Başka hiçbir şey yok** (spec §10.2/R1).
**Spec:** §4.3, §10.1, §10.2.

**Neden riskli:** `ALTER TYPE … ADD VALUE` aynı işlem içinde kullanılamaz ve
**geri alınamaz** → tip takası zorunlu; takas `units` tablosunu **yeniden yazar**
(kilit penceresi) — R1'in tek başına koşmasının bir sebebi de budur.

**Önce yazılacak testler:**
- `tests/modules/units/test_units_models.py::test_unit_kind_bes_deger_icerir`
- `tests/modules/units/test_units_models.py::test_unit_kind_db_enum_degerleri` (pg_enum sorgusu)
- `tests/modules/units/test_units_migration.py::test_r1_upgrade_downgrade_upgrade`
  (**açık revizyon id'si**, `head`/`-1` YOK)
- `tests/modules/units/test_units_migration.py::test_r1_downgrade_eski_tipi_birakmaz`
  (`pg_type`'da artık tipin kalmadığı doğrulanır — §0.A.4)

- [ ] **Adım 1:** testleri yaz
- [ ] **Adım 2: KIRMIZI GÖR** — beklenen: `AssertionError` (3 değer eksik)
- [ ] **Adım 3:** `DATABASE_URL` override'ıyla `alembic heads` **koşulur** (varsayılmaz).
      **İki head çıkarsa KOD YAZILMAZ**, kullanıcıya sorulur (birleştirme revizyonu
      kullanıcı kararıdır). Beklenen ~`d2a32dcae735` **civarı** — ama P6 araya girmiş olabilir.
- [ ] **Adım 4:** `models.py`'de `UnitKind` +3 değer
- [ ] **Adım 5:** R1 revizyonu — `f1b2c3d4e5a6` deseni birebir:
      yeni tip `CREATE TYPE` → `ALTER TABLE units ALTER COLUMN unit_kind TYPE …
      USING unit_kind::text::…` → eski tipi `DROP TYPE` → yeniden adlandır.
      `downgrade` aynısını **ters** yapar + `DROP TYPE IF EXISTS`.
- [ ] **Adım 6:** yerel DB'de `upgrade <r1>` → `downgrade <ebeveyn>` → `upgrade <r1>` **yeşil**
- [ ] **Adım 7:** mutasyon denetimi (§0.A.10) · **Adım 8:** commit

**Geri alma:** `downgrade` `office/warehouse/parking` değerli **satır varsa
başarısız olur** — bu bilinçlidir (veri kaybı yerine hata). Downgrade notu revizyon
docstring'ine yazılır: *"bu değerleri taşıyan üniteler önce dönüştürülmelidir."*

**Kabul kriteri:** `UnitKind` 5 üye; `pg_enum`'da 5 etiket; upgrade→downgrade→upgrade
yeşil; `alembic heads` **tek** head; başka hiçbir şema değişikliği yok
(`alembic ... --autogenerate` diff'i boş).

**Kapı komutu:**
```bash
createdb p31_t1 && \
DATABASE_URL="postgresql+asyncpg://furkanilgen@localhost:5432/p31_t1" .venv/bin/alembic upgrade <r1> && \
TEST_DATABASE_URL="postgresql+asyncpg://furkanilgen@localhost:5432/p31_t1" .venv/bin/pytest tests/modules/units -q ; \
dropdb p31_t1
```

---

### Task T2 — R2: 7 yeni enum tipi (izole) · **M** · ⚠️ **RİSKLİ** · bağımlılık: T1

**Amaç:** `block_roof_type`, `block_ground_usage`, `block_parking_type`, `block_status`,
`unit_facing`, `unit_parking_right`, `unit_sales_status` tiplerini oluşturmak + Python
enum sınıflarını yazmak. **Kolon eklenmez** (spec §10.2/R2).
**Spec:** §3.1, §4.1, §4.2, §4.4, §10.2.

**Neden riskli + neden R3'ten ayrı:** Postgres'te `ENUM` kolonla birlikte silinmez;
R2+R3 birleşseydi downgrade kolonları düşürüp tipleri bırakabilir ve **ikinci upgrade
patlardı**. Ayrı revizyon her tipin `DROP TYPE`'ını kendi downgrade'ine yazmayı
**zorunlu kılar**.

**Önce yazılacak testler:**
- `test_units_models.py::test_yedi_yeni_enum_uyeleri` (7 sınıfın değer listeleri birebir)
- `test_units_models.py::test_unit_facing_bes_deger` (karar 7 — `northeast` **YOK**)
- `test_units_migration.py::test_r2_yedi_tip_olusur` (`pg_type` sayımı)
- `test_units_migration.py::test_r2_downgrade_yedi_tipi_de_dusurur`
- `test_units_migration.py::test_r2_ikinci_upgrade_patlamaz`
  (upgrade→downgrade→upgrade — §0.A.4'ün doğrudan testi)

- [ ] Adım 1: testleri yaz · **Adım 2: KIRMIZI GÖR** (`ImportError`)
- [ ] Adım 3: `models.py`'ye 7 enum sınıfı
- [ ] Adım 4: R2 revizyonu (`sa.Enum(...).create(op.get_bind())` ×7;
      downgrade'de `DROP TYPE IF EXISTS` ×7)
- [ ] Adım 5: yerel turu · Adım 6: mutasyon denetimi · Adım 7: commit

**Geri alma:** `DROP TYPE IF EXISTS` ×7 — kolon yok olduğu için bağımlılık yok, temiz.

**Kabul kriteri:** 7 tip `pg_type`'da; downgrade sonrası **sıfır** kalıntı tip;
upgrade→downgrade→upgrade yeşil; `blocks`/`units` kolon sayısı **değişmemiş**.

**Kapı komutu:** T1 deseni, `p31_t2` + `<r2>`.

---

### Task T3 — R3: 21 kolon + 1 UNIQUE + 10 CHECK · **L** · ⚠️ **RİSKLİ** · bağımlılık: T2

**Amaç:** `blocks` +13 kolon (+`uq_blocks_project_code` +6 CHECK), `units` +8 kolon
(+**4** CHECK); `models.py` güncellemesi; **`sales_status` P8 geçiş notu docstring'e**
(spec §4.4 paragrafı **birebir**).
**Spec:** §3.1, §4.1, §7.1, §10.2/R3, §10.3, §10.4.

**Neden riskli:** en geniş şema değişimi; `NOT NULL` kaçağı canlıda ALTER'ı bloklar.

**⚠️ `ck_units_floor` YOKTUR** — kat **metindir** (karar 4). `units` CHECK sayısı
5 → **4**'e düşer (`balcony_area_m2 >= 0`, `bathroom_count >= 0`,
`min_sale_price >= 0`, `vat_rate BETWEEN 0 AND 100`).

**Önce yazılacak testler:**
- `test_units_models.py::test_blocks_13_yeni_kolon_hepsi_nullable`
  (`information_schema.columns` → `is_nullable='YES'` **13/13**)
- `test_units_models.py::test_units_8_yeni_kolon_hepsi_nullable`
- `test_units_models.py::test_units_floor_string20_ve_check_yok`
  (`data_type='character varying'`, `ck_units_floor` **yok**)
- `test_units_models.py::test_status_server_default_construction`
- `test_units_models.py::test_sales_status_server_default_listed`
- `test_units_models.py::test_uq_blocks_project_code_null_serbest`
  (aynı projede iki `code IS NULL` blok → **IntegrityError YOK**)
- `test_units_models.py::test_negatif_sayac_check_ihlali` (`floor_count = -1` → IntegrityError)
- `test_units_models.py::test_sales_status_docstring_p8_notu_icerir`
  (docstring'de `P8` geçiyor — bir sonraki ajanın sütunu "P3 ihlali" sanıp silmesini önler)
- `test_units_migration.py::test_r3_upgrade_downgrade_upgrade`
- `test_units_migration.py::test_r3_mevcut_satirlar_degismez`
  (upgrade öncesi yazılmış blok/ünite satırı upgrade sonrası **aynı**, yeni kolonlar `NULL`)

- [ ] Adım 1–2: testler + **KIRMIZI GÖR**
- [ ] Adım 3: `models.py` — 21 kolon, isimler/tipler spec §3.1 ve §4.1 tablolarından
      **birebir** (`construction_area_m2` `sites` ile **aynı ad ve boy**)
- [ ] Adım 4: R3 revizyonu. **Veri migration'ı YOK** (karar 5/8 — `blocks.code`
      backfill'i yazılmaz). Enum kolonları R2'nin tiplerine bağlanır,
      `create_type=False` ile (tip zaten var, ikinci `CREATE TYPE` patlar).
- [ ] Adım 5: yerel turu · Adım 6: mutasyon denetimi · Adım 7: commit

**Geri alma:** `downgrade` 21 kolonu ve kısıtları düşürür; **tipleri düşürmez**
(onlar R2'nin sorumluluğu). Downgrade veri kaybı yaratır (yeni kolonlardaki değerler)
— bu bilinçlidir ve revizyon docstring'ine yazılır.

**Kabul kriteri:** 21 kolonun **tamamı** nullable; 1 UNIQUE + 9 blocks CHECK + 4 units
CHECK; `ck_units_floor` **yok**; `blocks`/`units` mevcut satırları değişmemiş;
`--autogenerate` diff'i **boş** (model ↔ migration uyumu).

**Kapı komutu:** T1 deseni, `p31_t3` + `<r3>`.

---

### Task T4 — `_derive_block_code` + benzersizlik korkuluğu · **M** · bağımlılık: T3

**Amaç:** blok kodu üretiminin **saf** çekirdeği + proje içi benzersizlik + **kodu
`NULL` blokta anlık türetme** (§0.B).
**Spec:** §3.2, §8.3, §13.2.

**Önce yazılacak testler** — `tests/modules/units/test_units_block_codes.py` (YENİ):
- `test_ad_kisaltilir_a_blok` → `"A Blok"` → `"A"`
- `test_ad_kisaltilir_c_blok` → `"C Blok"` → `"C"`
- `test_turkce_karakter_katlanir` → `"Şantiye Ğ Blok"` → `"SANTIYE-G"`
- `test_blok_kelimesi_atilir_zemin` → `"Zemin"` → `"ZEMIN"`
- `test_noktalama_ve_bosluk_tire_olur` → `"2. Etap A"` → `"2-ETAP-A"`
- `test_yirmi_karaktere_kirpilir`
- `test_bos_kalirsa_sirali_geri_dusus` → `"Blok"` → `"B1"`, ikincisi `"B2"`
- `test_proje_ici_cakisma_eki_alir` → ikinci `"A"` → `"A-2"`
- `test_farkli_projede_ayni_kod_serbest`
- `test_derive_saf_fonksiyondur_dbsiz` (import edilip DB olmadan çağrılır)
- `tests/modules/units/test_units_api.py::test_null_kodlu_blokta_anlik_turetme_saklanmaz`
  (§0.B — fonksiyon çağrılır, `blocks` satırı **UPDATE edilmez**)

- [ ] Adım 1–2: testler + **KIRMIZI GÖR** (`ModuleNotFoundError: app.modules.units.codes`)
- [ ] Adım 3: `app/modules/units/codes.py` — `_derive_block_code(name) -> str` saf;
      Türkçe katlama `Ç→C, Ğ→G, İ/I/ı→I, Ö→O, Ş→S, Ü→U`
      (`importer._LETTER_FOLD` **deseninden**, ama ayrı sözlük — o küçük harfe katlıyor)
- [ ] Adım 4: `guards.ensure_block_code_unique` + `_DUPLICATE_BLOCK_CODE` (409)
- [ ] Adım 5: `repository`'ye proje içi kod sorgusu + maksimum+1 geri düşüşü
- [ ] Adım 6: mutasyon denetimi · Adım 7: commit

**Kabul kriteri:** 11 testin tamamı yeşil; `codes.py` **DB import etmiyor**
(`grep -n "sqlalchemy\|session" app/modules/units/codes.py` → boş).

**Kapı komutu:**
```bash
createdb p31_t4 && TEST_DATABASE_URL="postgresql+asyncpg://furkanilgen@localhost:5432/p31_t4" \
  .venv/bin/pytest tests/modules/units/test_units_block_codes.py tests/modules/units/test_units_api.py -q ; dropdb p31_t4
```

---

### Task T5 — Blok şemaları + uçları · **M** · bağımlılık: T4

**Amaç:** `BlockCreate/Update/Response` +13 alan + `estimated_unit_count` **türevi**;
`POST`/`PATCH` yollarında kod üretimi; Türkçe mesajlar.
**Spec:** §2.1, §3.1, §3.3, §7.2, §8.1/1-4.

**Önce yazılacak testler** (`test_units_api.py` + `test_units_schemas.py`), spec §12.2:
- `test_blok_13_alan_yazilir_ve_doner` (#14)
- `test_blok_kodu_bos_ise_uretilir` / `test_ayni_adli_ikinci_blok_kod_eki_alir` (#15)
- `test_elle_verilen_kod_cakisirsa_409` (#16)
- `test_farkli_projede_ayni_kod_201` (#17)
- `test_blok_patch_kismi_guncelleme_notes_null_bosaltir` (#18)
- `test_estimated_unit_count_8x3_arti_2_esittir_26` (#19, BE 90–93 **birebir**)
- `test_estimated_unit_count_uc_girdi_none_ise_none` (#19 — **0 dönmez**)
- `test_blok_negatif_sayac_422` (#20 — Pydantic, CHECK'ten **önce**)
- `test_patch_kodu_bos_blokta_kod_uretir` (spec §3.2 karar 8)

- [ ] Adım 1–2: testler + **KIRMIZI GÖR**
- [ ] Adım 3: şemalar (13 alanın **hiçbiri zorunlu değil** — karar 11)
- [ ] Adım 4: `service`/`router` genişlemesi + `guards` mesajları
- [ ] Adım 5: mutasyon denetimi · Adım 6: commit

**Kabul kriteri:** 9 test yeşil; `estimated_unit_count` **saklanmıyor**
(`information_schema`'da kolon yok); `notes` `String(500)` `maxLength` OpenAPI'de görünüyor.

**Kapı komutu:** `p31_t5`, `pytest tests/modules/units -q`.

---

### Task T6 — Ünite şemaları + `UnitKindBreakdown` · **M** · bağımlılık: T3

**Amaç:** `UnitCreate/Update/Response` +8 alan + `expected_profit` yer tutucusu;
`sales_status` **`MetricPlaceholder` → gerçek değer**; `UnitKindBreakdown` +3 sayaç.
**Spec:** §4.1, §4.2, §4.3, §4.4, §4.5, §7.2.

**⚠️ Kırıcı değişim:** `UnitResponse.sales_status` tipi değişiyor → mevcut yer tutucu
testleri kırılır (**bilerek**, §4).

**Önce yazılacak testler** (spec §12.1/9,13,13b + §12.3):
- `test_units_schemas.py::test_vat_rate_yalniz_1_10_20` (15 → 422, karar 9)
- `test_units_schemas.py::test_min_sale_price_list_price_ustunde_serbest` (karar 2 —
  **hiçbir katmanda zorlanmaz**)
- `test_units_schemas.py::test_unit_kind_breakdown_bes_sayac_total`
- `test_units_schemas.py::test_breakdown_yeni_sayaclar_sifirken_eski_davranis`
- `test_units_api.py::test_unite_8_yeni_alan_yazilir_ve_doner` (#21)
- `test_units_api.py::test_sales_status_gonderilmezse_listed` (#22)
- `test_units_api.py::test_unit_kind_office_warehouse_parking_201` (#23)
- `test_units_api.py::test_floor_cati_kati_aynen_doner_21_karakter_422` (#25)
- `test_units_api.py::test_floor_gonderilmezse_none_201` (#25, karar 11)
- `test_units_api.py::test_patch_sales_status_sold_200` (#26)
- `test_units_api.py::test_expected_profit_ve_unit_cost_yer_tutucu` (#29)

- [ ] Adım 1–2: testler + **KIRMIZI GÖR**
- [ ] Adım 3: şemalar + `guards.ensure_vat_rate` / `_INVALID_VAT_RATE`
- [ ] Adım 4: **kırılan yer tutucu testlerini güncelle** (§4 tablosu)
- [ ] Adım 5: mutasyon denetimi · Adım 6: commit

**Kabul kriteri:** 11 test yeşil; `sales_status` OpenAPI'de **enum**;
`vat_rate` kümesi **kodda sabit** (migration yok); `min_sale_price` için **hiçbir**
`model_validator`/CHECK yok (`grep`'le doğrulanır).

**Kapı komutu:** `p31_t6`, `pytest tests/modules/units -q`.

---

### Task T7 — Ünite okuma yolu: sayaçlar + süzgeçler · **M** · bağımlılık: T6

**Amaç:** `totals.by_sales_status`; `sold_units`/`reserved_units`/`available_units`
**yer tutucudan gerçeğe**; `floor` (tam eşleşme) + `sales_status` süzgeçleri.
**Spec:** §8.2.

**⚠️ Kırıcı değişim:** üç `CountPlaceholder` alanı gerçek sayaca dönüşüyor →
mevcut testler kırılır (**bilerek**, §4). `sales_revenue` / `average_sale_price`
**yer tutucu KALIR** (gerçekleşen satış tutarı hâlâ P8'in verisi).

**Önce yazılacak testler:**
- `test_units_api.py::test_sales_status_suzgeci_listeyi_daraltir` (#27)
- `test_units_api.py::test_totals_suzgecten_etkilenmez` (#27 — P3 §7.4 kuralı **korunur**)
- `test_units_api.py::test_by_sales_status_dort_degeri_de_sayar` (#28)
- `test_units_api.py::test_floor_suzgeci_tam_eslesme` (`"3. Kat"` eşleşir, `"3"` **eşleşmez**)
- `test_units_api.py::test_sales_revenue_hala_yer_tutucu` (P8 sınırı korunuyor)

- [ ] Adım 1–2: testler + **KIRMIZI GÖR** · Adım 3: `repository` + `summary`
- [ ] Adım 4: kırılan yer tutucu testlerini güncelle · Adım 5: mutasyon · Adım 6: commit

**Kabul kriteri:** 5 test yeşil; `totals` süzgeçten bağımsız (iki ayrı sorgu);
N+1 yok (tek `GROUP BY` sorgusu).

**Kapı komutu:** `p31_t7`, `pytest tests/modules/units -q`.

---

### Task T8 — `bulk.py` yeniden yazımı · **L** · ⚠️⚠️ **EN RİSKLİ** · bağımlılık: T6 + **§0.C onayı**

**Amaç:** 4(+1) numaralandırma deseni · **başa sıfır dolgusunun kaldırılması** ·
kat etiketi üreteci + `roof_floor` turu · slot şablonu · kat fiyat artışı
(**en yakın 100 ₺**). Hepsi **saf/DB'siz**.
**Spec:** §5.2, §5.3, §5.5, §11.5, §12.1/4-8b.

**Neden en riskli:** (a) mevcut yeşil testleri **bilerek** kırıyor, (b) para hesabı
(`Decimal`, `float` **YASAK** — P7 K5 dersi), (c) `{Sıra}` jetonu iki farklı anlam
taşıyor (global sıra ↔ kat içi slot) ve karıştırılması sessiz numara hatası üretir.

**Silinecekler (bırakılırsa bir sonraki ajan kararı geri alır):**
`bulk.py:14-17` `_FLOOR_SEQUENCE_WIDTH = 2` sabiti **ve** onu açıklayan yorum
(*"1. kat 1. daire 101'dir, 11 değil"*) — yorum artık kararın **tersini** söylüyor.

**Önce yazılacak testler** (`test_units_bulk.py`, spec §12.1/4-8b):
- `test_block_sequence_c1_c24` → `C-1 … C-24` (**başa sıfır YOK**, TU 159–166)
- `test_floor_sequence_tek_hane` → `units_per_floor=3` → `11,12,13,21,22,23`
- `test_label_sequence_daire_n` → `Daire 1 …`
- `test_block_floor_sequence` → `C11,C12,C13`
- `test_floor_sequence_width_follows_units_per_floor` → `units_per_floor=12` → `101…112,201`
  (**mevcut `test_floor_based_numbering_pads_to_two_digits` bu ada yeniden adlandırılır**)
- `test_kat_etiketi_uretici` → `0→"Zemin"`, `3→"3. Kat"`, `-2→"2. Bodrum"`
- `test_roof_floor_bir_tur_daha_uretir_etiket_cati_kati`
- `test_fiyat_artisi_TU_bes_satiri_birebir` → §5.5 tablosunun **beş satırı da**
  (C-1 1.280.000 · C-4 1.299.200 · C-5 954.100 · C-6 1.258.600 · **C-7 1.318.700**)
- `test_yuvarlama_en_yakin_100_TL` (karar 6; `Decimal`, `ROUND_HALF_UP`)
- `test_artis_yokken_slot_tabani_yuvarlanmaz` (karar 6 **sınırı**)
- `test_total_list_value_satirlardan_toplanir` — **mockup'ın `₺27.264.000` sayısı
  teste KONMAZ** (karar 5, onaylı sapma §11.6)
- `test_prefix_korunur_D1_D4` (SY 132–135 regresyonu — **§0.C'ye bağlı**)
- `test_slot_sequence_tekrarli_gecersiz` / `test_slot_count_mismatch`

**Bilerek güncellenecek mevcut testler:**
| Test | Bugün | Sonra |
|---|---|---|
| `test_floor_based_numbering` (`units_per_floor=2`) | `101,102,201,202` | **`11,12,21,22`** |
| `test_floor_based_numbering_negative_floors` | `-101,-102` | **`-11,-12`** |
| `test_floor_based_numbering_pads_to_two_digits` | yeşil | **yeniden adlandırılır** (üstte) |
| `test_sequential_numbering_*` (3 test) | `sequential` | **§0.C kararına göre** korunur veya yeniden adlandırılır |

- [ ] Adım 1–2: testler + **KIRMIZI GÖR**
- [ ] Adım 3: `bulk.py` yeniden yazımı — **doğrulama BURADA DEĞİL**
      (`UnitBulkCreate.model_validator`'da; aynı kuralı iki yerde tutmak zamanla ayrışır —
      `bulk.py` docstring'indeki mevcut kural **korunur**)
- [ ] Adım 4: `guards.ensure_net_le_gross` slotlarda **çağrılır, kopyalanmaz**
- [ ] Adım 5: mevcut testleri güncelle · Adım 6: mutasyon · Adım 7: commit

**Kabul kriteri:** `grep -n "_FLOOR_SEQUENCE_WIDTH\|float(" app/modules/units/bulk.py`
→ **boş**; TU beş satırı birebir; `bulk.py` DB/HTTP import etmiyor.

**Kapı komutu:**
```bash
.venv/bin/pytest tests/modules/units/test_units_bulk.py -q   # saf testler DB'siz koşar
createdb p31_t8 && TEST_DATABASE_URL="postgresql+asyncpg://furkanilgen@localhost:5432/p31_t8" \
  .venv/bin/pytest tests/modules/units -q ; dropdb p31_t8
```

---

### Task T9 — `POST …/units/bulk/preview` YENİ UÇ · **M** · ⚠️ **RİSKLİ** · bağımlılık: T8

**Amaç:** önizleme ucu + `UnitBulkPreview`/`UnitBulkPreviewRow` şemaları + çakışma
işaretlemesi. **Denetim YAZMAZ.** İzin `full`.
**Spec:** §5.4, §5.6, §9, §12.4/30-33.

**Neden riskli:** "hiçbir şey yazmaz" garantisi sessizce bozulabilir (servis içinde bir
`flush`/`commit` yeterli) ve `dry_run` yerine ayrı uç kararının **tek gerekçesi** budur.

**Önce yazılacak testler** — `tests/modules/units/test_units_bulk_preview.py` (YENİ):
- `test_preview_TU_senaryosunun_tamami` (#30) — 8 kat × 3 slot, `block_sequence`,
  %1,5 artış → `total_units=24`; `rows[0..6]` **TU 159–165 ile birebir**;
  `floor` sayısal (1/2/3) **ve** `floor_label` metin (`"1. Kat"`)
- `test_preview_roof_floor_son_tur_cati_kati` (#30b)
- `test_preview_null_kodlu_blokta_anlik_turetme` (#30c, §0.B) —
  **`blocks` satırı UPDATE edilmez** (öncesi/sonrası `code IS NULL`)
- `test_preview_cakisma_200_ve_conflict_true` (#31 — **hata değil**, TU 177)
- `test_preview_hicbir_satir_yazilmaz` (#32 — öncesi/sonrası ünite sayımı **eşit**)
- `test_preview_denetim_yazmaz` (#33 — `audit_logs` sayımı eşit)
- `test_preview_tum_satirlari_doner` (500 satırda da kırpma yok, §5.4)

- [ ] Adım 1–2: testler + **KIRMIZI GÖR** (404)
- [ ] Adım 3: şemalar + router + `service` (üretim `bulk.generate_*` **saf
      fonksiyonundan**, kopya kural yok)
- [ ] Adım 4: mutasyon · Adım 5: commit

**Kabul kriteri:** 7 test yeşil; `response_model=UnitBulkPreview` (Union **yok**);
denetim satırı **sıfır**; `POST …/units/bulk` ile aynı saf fonksiyonu çağırdığı
`grep`'le görünür.

**Kapı komutu:** `p31_t9`, `pytest tests/modules/units -q`.

---

### Task T10 — `POST …/units/bulk` genişlemesi · **M** · bağımlılık: T9

**Amaç:** slot + artış + 4(+1) desenin **gerçek üretime** bağlanması; hep-ya-hiç
çakışma kararının **korunduğunun** kanıtı; `preview` ile **birebir aynı çıktı**.
**Spec:** §5.3, §5.6, §12.4/34-39.

**Önce yazılacak testler** (`test_units_bulk.py`):
- `test_bulk_preview_ile_ayni_numara_ve_fiyat` (#34 — **tek kaynak kanıtı**)
- `test_bulk_cakisma_409_hicbir_satir_yazilmaz` (#35 — P3 kararı **korunuyor**)
- `test_bulk_slots_bos_eski_davranis` (#36 — geriye dönük uyum)
- `test_bulk_slot_count_mismatch_422` (#37)
- `test_bulk_slot_sequence_tekrarli_422` (#38)
- `test_bulk_owner_side_yok_sayilir` (#39 — mevcut
  `test_bulk_never_sets_owner_side_in_kendi_yatirim` **korunur**)

- [ ] Adım 1–2: testler + **KIRMIZI GÖR** · Adım 3: `service`/`schemas`
- [ ] Adım 4: mutasyon · Adım 5: commit

**Kabul kriteri:** 6 test yeşil; mevcut 21 bulk testinden **yalnız §4'te listelenenler**
değişmiş; `owner_side` üretilen satırlarda `NULL`.

**Kapı komutu:** `p31_t10`, `pytest tests/modules/units -q`.

---

### Task T11 — `importer.py` genişlemesi (12 sütun) · **M** · bağımlılık: T6

**Amaç:** 9 → 12 sütun; `Tip`→`Oda Tipi`, `Pay`→`Sahiplik` yeniden adlandırma
**+ eski başlıklar eşanlamlı**; `Kat` (**metin, dönüştürme YOK**), `Cephe`,
`Maliyet` (**oku-uyar-at**) çözümlemesi; yeni satır kuralları.
**Spec:** §6.4, §6.5, §12.1/10-12.

**Önce yazılacak testler** (`test_units_import.py`):
- `test_basliklar_12_kanonik_sirada`
- `test_eski_basliklar_esanlamli_tip_pay` (#50 geriye dönük uyum)
- `test_baslik_normalizasyonu_I_tuzagi` (`"  ODA TİPİ "` — mevcut `_LETTER_FOLD`
  testi **genişletilir**)
- `test_kat_metin_donusturme_yok` — `"Zemin"→"Zemin"`, `"3. Kat"→"3. Kat"`,
  `3→"3"` (**`"3. Kat"` DEĞİL**), 21 karakter → satır hatası
- `test_cephe_sozlugu_bes_deger` (karar 7; tanınmayan → satır hatası)
- `test_sahiplik_yeni_etiketler_kabul` (`Yüklenici (Biz)`, `Arsa Sahibi Payı`)
- `test_tur_bes_deger` (`Ofis`, `Depo`, `Otopark`)
- `test_oda_tipi_bos_hata` (EI 161)
- `test_brut_m2_sifir_hata` (EI 161)
- `test_maliyet_okunur_ama_dondurulen_satirda_kolon_yok` (karar 10)

- [ ] Adım 1–2: testler + **KIRMIZI GÖR** · Adım 3: `importer.COLUMNS` + sözlükler
- [ ] Adım 4: mutasyon · Adım 5: commit

**Kabul kriteri:** 10 test yeşil; `ImportRow`'da **maliyet kolonu yok**
(yalnız yerel değişken); `Kat` için **hiçbir** dönüşüm tablosu yok.

**Kapı komutu:** `p31_t11`, `pytest tests/modules/units/test_units_import.py -q`.

---

### Task T12 — Kısmi aktarım · **L** · ⚠️⚠️ **EN RİSKLİ** · bağımlılık: T11

**Amaç:** `batch.import_units` yeniden yazımı (hep-ya-hiç → **kısmi**);
`UnitImportSummary`/`RowReport`/`RowStatus`/`Result` şemaları; `include_warnings`;
**`site_id` hedef şantiye** (karar 3/11); `_IMPORT_NOTHING_TO_WRITE`;
`UnitImportError`/`UnitImportRowError` **temizliği**.
**Spec:** §6.1, §6.2, §6.3, §6.5, §12.5.

**Neden en riskli:** (a) P3'ün açık bir kararından dönüş, (b) kısmi yazımın transaction
sınırı yanlış konursa "hatalı satır yazıldı" veya "geçerli satır yazılmadı" **sessiz**
veri hatası doğar, (c) `site_id` yolu bir **IDOR yüzeyi** açıyor.

**Değişecek yerler (aranacak):** `batch.py::_raise_row_errors` (artık istisna **fırlatmaz**,
rapor üretir) · `batch.py::import_units` · `schemas.py::UnitImportResult` ·
`core/errors.py::UnitImportError` · `guards._IMPORT_ROW_ERRORS` (**kaldırılır**).

**Önce yazılacak testler** (`test_units_import.py`, spec §12.5):
- `test_import_kismi_gecerliler_yazilir_hatali_yazilmaz` (#44 — **asıl kanıt**:
  hatalı satırın ünitesi DB'de **YOK**, geçerlilerinki **VAR**)
- `test_import_include_warnings_true_created_23_skipped_1` (#42)
- `test_import_include_warnings_false_created_22_skipped_2` (#43)
- `test_import_hic_gecerli_satir_yoksa_422_nothing_to_write` (#45 — `created=0` ile
  **200 dönmez**)
- `test_import_ayni_dosya_ikinci_kez_hepsi_atlanir_422` (#46 — §6.1'in 2. gerekçesi)
- `test_import_yeni_blok_olusur_hatali_satirin_blogu_olusmaz` (#47)
- `test_import_cok_santiyeli_site_id_yok_422_site_required` (#47b)
- `test_import_site_id_ile_yeni_bloklar_o_santiyede` (#47b)
- `test_import_mevcut_blogun_site_id_si_degismez` (#47b — **sessiz veri taşıma riski**)
- `test_import_baska_projenin_site_id_404` (#47c, IDOR)
- `test_import_maliyet_hicbir_kolona_yazilmaz` (#48)
- `test_import_fiyat_maliyetin_altinda_warning` (#49, EI 173 biçimi)
- `test_import_csv_422_ve_2mb_ustu_422` (#51 — onaylı sapma §11.3)
- `test_import_dosya_hicbir_yere_yazilmaz` (#52 — P3 test 32 **korunur**)
- `test_summary_EI_sayaclari_birebir` (24/22/1/1)
- `test_hatali_satir_iki_mesaj_tasir` (EI 161 — `messages` **liste**)

**Bilerek tersine dönecek test:** P3 §11.3 **#28** ("3. satırda `net > brüt` → 422,
hiçbir ünite yazılmamış") → artık **o satır atlanır, diğerleri yazılır**.

- [ ] Adım 1–2: testler + **KIRMIZI GÖR**
- [ ] Adım 3: `batch.py` yeniden yazımı — transaction sınırı **açıkça** belirlenir
      ve teste konur
- [ ] Adım 4: şemalar; `UnitImportRowError` + `UnitImportError` **silinir**
      (kullanılmadan bırakılırsa `ruff` uyarmaz ama bir sonraki ajanı yanıltır)
- [ ] Adım 5: P3 #28'i güncelle · Adım 6: mutasyon · Adım 7: commit

**Kabul kriteri:** 16 test yeşil; `grep -rn "UnitImportError\|UnitImportRowError" app/`
→ **boş**; kısmi yazımda `created + skipped == total_rows`.

**Kapı komutu:** `p31_t12`, `pytest tests/modules/units -q`.

---

### Task T13 — `POST …/units/import/validate` YENİ UÇ · **S** · bağımlılık: T12

**Amaç:** doğrulama (dry-run) ucu; `site_id` burada da var; **denetim yazmaz**;
`import` ile **tek kaynaktan** beslendiğinin testi. İzin `full`.
**Spec:** §6.2, §12.5/40-41.

**Önce yazılacak testler:**
- `test_validate_EI_senaryosu_summary_birebir` (#40)
- `test_validate_hicbir_satir_yazilmaz` (#41)
- `test_validate_denetim_yazmaz` (#41)
- `test_validate_ve_import_ayni_rapor_uretir` (aynı dosya → `rows` **aynı**;
  fark yalnız `imported` bayrağı)
- `test_validate_imported_daima_false`

- [ ] Adım 1–2: testler + **KIRMIZI GÖR** (404) · Adım 3: router + `service`
- [ ] Adım 4: mutasyon · Adım 5: commit

**Kabul kriteri:** 5 test yeşil; `response_model=UnitImportValidation`;
denetim satırı sıfır; ortak kural `importer` + `_domain_row_reports`'ta **tek kopya**.

**Kapı komutu:** `p31_t13`, `pytest tests/modules/units -q`.

---

### Task T14 — `GET …/units/import/template` YENİ UÇ · **S** · bağımlılık: T11

**Amaç:** 12 başlıklı boş `.xlsx` şablonu. **İzin `view`** (§6.2 kararı).
Denetim **yazmaz**. Veri satırı **yoktur**.
**Spec:** §6.7, §12.5/53-54.

**Önce yazılacak testler** — `tests/modules/units/test_units_import_template.py` (YENİ):
- `test_sablon_200_ve_xlsx_content_type` (#53)
- `test_sablon_ilk_satir_12_baslik_kanonik_sirada` (#53 — `openpyxl` ile açılır)
- `test_sablon_veri_satiri_yok` (#53)
- `test_sablon_denetim_yazmaz` (#54)
- `test_sablon_view_izniyle_200` (#I6)
- `test_sablon_indirilen_dosya_import_ucunda_kabul_edilir`
  (**döngü testi**: şablon indirilir, bir satır doldurulur, `import`'a verilir → 200.
  Başlık listesi iki yerde ayrışırsa bunu yakalar)

- [ ] Adım 1–2: testler + **KIRMIZI GÖR** · Adım 3: `template.py` +
      `importer.COLUMNS`'tan **türetilen** başlıklar (elle liste **YAZILMAZ** — ikinci otorite)
- [ ] Adım 4: mutasyon · Adım 5: commit

**Kabul kriteri:** 6 test yeşil; başlık listesi `importer.COLUMNS`'tan türetiliyor
(`grep` ile doğrulanır); yeni bağımlılık yok.

**Kapı komutu:** `p31_t14`, `pytest tests/modules/units -q`.

---

### Task T15 — Denetim günlüğü · **S** · bağımlılık: T10, T13, T14

**Amaç:** `units_imported(project_name, created, skipped)` imza değişimi + **üç yeni
ucun yazmadığının** testi.
**Spec:** §9, §12.5/55.

**Önce yazılacak testler** (`test_units_audit.py`):
- `test_units_imported_skipped_varsa_mesaja_yazar`
  (`… · 22 ünite (2 satır atlandı)`)
- `test_units_imported_skipped_yoksa_kisa_mesaj`
- `test_import_istek_basina_tek_denetim_satiri` (#55)
- `test_preview_validate_template_denetim_yazmaz` (üçü tek testte)
- Mevcut 7 denetim mesajının **değişmediği** (`block_created` … `unit_allocation_updated`)

- [ ] Adım 1–2: testler + **KIRMIZI GÖR** · Adım 3: `messages.py`
- [ ] Adım 4: mutasyon · Adım 5: commit

**Kabul kriteri:** 5 test yeşil; okuma uçları **sıfır** denetim satırı (P4 T7 kuralı).

**Kapı komutu:** `p31_t15`, `pytest tests/modules/units -q`.

---

### Task T16 — IDOR negatif seti · **M** · bağımlılık: T9, T13, T14

**Amaç:** üç yeni uç için **tam** negatif set + P3'ün 14 senaryosunun regresyonu.
**Spec:** §12.6.

**Önce yazılacak testler** (`test_units_idor.py`):
| Test | Beklenen |
|---|---|
| `test_preview_gizli_proje_404` (I1) | **404** "Proje bulunamadı" (**403 değil**) |
| `test_validate_gizli_proje_404` (I2) | 404 |
| `test_template_gizli_proje_404` (I3) | 404 |
| `test_preview_baska_projenin_block_id_404` (I4) | 404 "Blok bulunamadı" |
| `test_preview_validate_view_izniyle_403` (I5) | 403 (ikisi de `full`) |
| `test_template_view_izniyle_200` (I6) | **200** (§6.2 kararı) |
| `test_uc_ucu_none_izinle_403` (I7) | 403 |
| `test_uc_ucu_tokensiz_401` (I8) | 401 |
| `test_negatif_govdeler_kayit_varligini_sizdirmaz` | gövde karşılaştırması |

- [ ] Adım 1–2: testler + **KIRMIZI GÖR** · Adım 3: eksik kapıları kapat
- [ ] Adım 4: P3'ün 14 senaryosunun **hâlâ yeşil** olduğu doğrulanır
- [ ] Adım 5: mutasyon · Adım 6: commit

**Kabul kriteri:** 9 yeni + 14 mevcut senaryo yeşil; **görünmeyen kayıt ile var olmayan
kimliğin yanıtı ayırt edilemiyor** (gövde **birebir** aynı).

**Kapı komutu:** `p31_t16`, `pytest tests/modules/units -q`.

---

### Task T17 — Regresyon + tam kapı · **L** · bağımlılık: T1–T16

**Amaç:** kırılması **beklenen** test gruplarının bilinçli güncellenmiş olduğunun
doğrulanması + modül sayısının **18'de kaldığının** kanıtı + tam kapı koşusu +
`openapi.json` üretimi.
**Spec:** §12.7.

- [ ] **Adım 1:** §4'ün **7 grubunun tamamı** tek tek gözden geçirilir; her biri için
      "neden değişti" commit mesajında **spec bölümüne atıfla** yazılır
- [ ] **Adım 2:** `pytest tests/modules/test_seed_matrix.py tests/modules/test_roles_*.py`
      → **dokunulmamış ve yeşil** (18×8 = 144)
- [ ] **Adım 3:** migration turu — R1 → R2 → R3 `upgrade → downgrade → upgrade`
      **açık revizyon id'leriyle**; `alembic heads` **tek** head
- [ ] **Adım 4:** **tüm takım** koşulur (P7 sonrası taban **1411** test) —
      beklenen: taban + ~110 yeni test, kırmızı **sıfır**
- [ ] **Adım 5:** `.venv/bin/ruff check .` + `.venv/bin/ruff format --check .`
      (**KAPI TÜM REPODUR** — `app tests` ile sınırlama `alembic/`'i kaçırır)
- [ ] **Adım 6:** `openapi.json` üretilir (**commit EDİLMEZ**, gitignore'lu);
      14 ucun tamamı ve `sales_status` enum'u şemada doğrulanır
- [ ] **Adım 7:** commit

**Kabul kriteri:** tüm takım yeşil · ruff temiz (tüm repo) · tek head ·
migration turu yeşil · modül sayısı 18 · `openapi.json`'da 14 units/blocks ucu.

**Kapı komutu:**
```bash
createdb p31_t17 && \
  TEST_DATABASE_URL="postgresql+asyncpg://furkanilgen@localhost:5432/p31_t17" .venv/bin/pytest -q ; \
  dropdb p31_t17
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

---

## 3. Bağımlılık grafiği ve kritik yol

```
T0 → T1 → T2 → T3 ─┬─ T4 → T5 ──────────────────────────────┐
                   │                                        │
                   └─ T6 ─┬─ T7 ───────────────────────────┤
                          ├─ T8 → T9 → T10 ────────────────┤
                          └─ T11 ─┬─ T12 → T13 ────────────┤
                                  └─ T14 ─────────────────┤
                                                   T15, T16 → T17
```

**Kritik yol (en uzun zincir):**
`T0 → T1 → T2 → T3 → T6 → T8 → T9 → T10 → T15 → T17`
— **10 task**, içinde **üç L** (T3, T8, T17) ve **üç riskli migration** (T1–T3).

**Paralelleştirilebilir kollar** (aynı repoda tek ajan kuralı gereği **sıralı koşar**,
ama bağımlılık zorlamaz): T4→T5 · T7 · T11→T12→T13 · T14.

---

## 4. Kırılacak mevcut testler — task bazında

> Hepsi **bilerek** güncellenir. Bir sonraki ajan bunları "regresyon" sanıp geri almaz.

| # | Test / grup | Dosya | Kıran değişim | Task |
|---|---|---|---|---|
| 1 | `test_floor_based_numbering` (`101,102,201,202` → `11,12,21,22`) | `test_units_bulk.py` | karar 1, başa sıfır kaldırıldı | **T8** |
| 2 | `test_floor_based_numbering_negative_floors` (`-101,-102` → `-11,-12`) | `test_units_bulk.py` | karar 1 | **T8** |
| 3 | `test_floor_based_numbering_pads_to_two_digits` (yeşil kalır, **yeniden adlandırılır**) | `test_units_bulk.py` | adı kararın tersini ima ediyor | **T8** |
| 4 | `test_sequential_numbering_*` (3 test) | `test_units_bulk.py` | enum değeri yeniden adlandırma — **§0.C'ye bağlı** | **T8** |
| 5 | P3 §11.3 **#28** (`import` hep-ya-hiç: "hiçbiri yazılmaz") | `test_units_import.py` | §6.1 dönüşü — **tersine döner** | **T12** |
| 6 | `UnitKindBreakdown` şema testleri | `test_units_schemas.py` | +3 sayaç (§4.3) | **T6** |
| 7 | `UnitResponse.sales_status` **yer tutucu** testleri | `test_units_api.py`, `test_units_schemas.py` | `MetricPlaceholder` → enum (§4.4) | **T6** |
| 8 | `sold_units` / `reserved_units` / `available_units` yer tutucu testleri | `test_units_api.py` | `CountPlaceholder` → gerçek sayaç (§8.2) | **T7** |
| 9 | `UnitImportResult.errors` alanına dayanan testler | `test_units_import.py` | alan **kaldırıldı**, yerini `rows` aldı (§6.3) | **T12** |
| 10 | `test_units_openapi.py` uç sayımı (11 → 14) | `test_units_openapi.py` | 3 yeni uç | **T17** |

**Kırılmayacağı GARANTİ edilenler** (kırmızıya dönerlerse **yanlış bir şey yapılmıştır**):
`tests/modules/test_seed_matrix.py` · `test_roles_repository.py` · `test_roles_api.py` ·
`test_units_bulk.py::test_bulk_never_sets_owner_side_in_kendi_yatirim` ·
`test_units_allocation.py` (tamamı) · P3'ün 14 IDOR senaryosu.

---

## 5. Riskli task özeti

| Task | Risk | Neden | Azaltma |
|---|---|---|---|
| **T1** | ⚠️ enum takası | `ALTER TYPE ADD VALUE` geri alınamaz; `units` yeniden yazılır | izole revizyon · `USING …::text::…` deseni · downgrade `DROP TYPE` testi |
| **T2** | ⚠️ enum takası | 7 tip; `DROP TYPE` unutulursa 2. upgrade patlar | izole revizyon · `test_r2_ikinci_upgrade_patlamaz` |
| **T3** | ⚠️ `units.floor` tip kararı + 21 kolon | tek `NOT NULL` kaçağı canlıda ALTER'ı bloklar; `ck_units_floor` **yok** | 13/13 + 8/8 nullable testi · `--autogenerate` diff boş |
| **T8** | ⚠️⚠️ numara biçimi | mevcut testleri kırar; `float` sızarsa para hatası; `{Sıra}` iki anlamlı | TU beş satırı altın test · `grep` ile `float(` yasağı · sabit+yorum silinir |
| **T9** | ⚠️ önizleme ucu | "yazmaz" garantisi sessizce bozulabilir | öncesi/sonrası sayım testi + denetim sayımı testi |
| **T12** | ⚠️⚠️ kısmi aktarım | transaction sınırı yanlışsa sessiz veri hatası; `site_id` IDOR yüzeyi | `created + skipped == total_rows` · #44 yazıldı/yazılmadı testi · 3 IDOR testi |

---

## 6. Frontend'e devredilen iş (bu dilimde YAPILMAZ)

> Bu bölüm frontend diliminin **brifingidir**; backend ajanı buraya dokunmaz.

1. **Yeni BFF kökü GEREKMEZ.** Kök yolları değişmiyor (`projects`, `blocks`, `units`) —
   üç yeni uç mevcut köklerin altında. **Yine de `grep`'le doğrulanır**
   (`src/app/api/backend/[...path]/route.ts` → `ALLOWED_ROOTS`); "zaten var" varsayılmaz.
   Bu tuzak atlanırsa modül **yalnız canlıda** 404 verir.
2. **`openapi.json` senkronu ZORUNLU.** `UnitResponse.sales_status` tipi **kırıcı**
   biçimde değişiyor (`MetricPlaceholder` → `UnitSalesStatus` enum'u);
   `UnitImportResult.errors` **kaldırıldı**. Backend merge + deploy sonrası
   `openapi.json` elle kopyalanır ve `gen:api` yeniden koşulur.
   `openapi.json` gitignore'lu — backend commit'inde **aranmaz**.
3. **Ertelenen iki formun sekmeleri BASILMAZ** (karar 12 / onaylı sapma §11.4):
   "Bölüm Ekle" ve "Paylaşım Girişi" sekmeleri **hiç eklenmez** — ne gizli-devre-dışı,
   ne "yakında" rozeti, ne tıklanınca boş sayfa. Şerit **dört** sekmeyle çıkar.
   **Eklenmemesi eksiklik değildir.**
4. **`UnitKindBreakdown` etiketleri DEĞİŞMEZ** (karar 13): KY 71 / KK 72 / SY 74 hâlâ
   "Daire + Dükkan" der. Yeni üç sayaç (`office`, `warehouse`, `parking`) yalnız
   **sayaçlara** eklenir; sayaç **sıfırsa ekranda hiç görünmez**. Mevcut ekran metinlerini
   "eksik" sanıp genişletmek bu kararın **ihlalidir**.
5. **Excel yükleme metni düzeltilir** (onaylı sapma §11.3): `accept` özniteliği ve
   yardım metni **`.xlsx · Maks 2 MB`** olur — mockup'ın "XLSX, XLS veya CSV · Maks 10 MB"
   metni **yanıltıcıdır**.
6. **"Hata Raporunu İndir" istemci tarafında üretilir** (§6.6) — sunucu ucu **yok**;
   rapor zaten `rows` içinde. `Content-Type` tabanlı ikili indirme kuralı burada
   **geçerli değildir** (ağ isteği yok).
7. **"Yeniden Doğrula" → "Aktar" akışında dosya iki kez POST edilir** (§6.2) — dosya
   sunucuda saklanmıyor. Kullanıcı dosyayı **yeniden seçmez**; aynı `File` nesnesi gönderilir.
8. **Maliyet alanları** (UE 91, TU 104) sunucuya **gitmez** (onaylı sapma §11.2):
   UE 91 salt-okunur yer tutucu; TU 104 ya istemci-yerel hesap alanı kalır ya kaldırılır.
9. **`notes` `String(500)`** → frontend'de `maxLength` **konur** (sessiz 422 sınıfı,
   `GOREV-SIRASI.md` §3).

---

## 7. "Bitti" tanımı — kontrol listesi

**Kod / test**
- [ ] T1–T17 tamamlandı, her task'ın kabul kriteri karşılandı
- [ ] Tüm takım yeşil (taban 1411 + ~110 yeni), kırmızı **sıfır**
- [ ] §4'teki **10 grubun** her biri bilerek güncellendi ve commit mesajında gerekçelendi
- [ ] §4'ün "kırılmayacağı garanti edilenler" listesi **dokunulmadan** yeşil
- [ ] Her task'ta "KIRMIZI GÖR" adımı **koşuldu**; ilk koşuda yeşil gelen testte
      **mutasyon denetimi** yapıldı

**Şema / migration**
- [ ] R1 → R2 → R3 `upgrade → downgrade → upgrade` **yerel** DB'de yeşil,
      **açık revizyon id'leriyle** (`head`/`-1` **kullanılmadı**)
- [ ] `alembic heads` **tek** head
- [ ] Her revizyonun `downgrade`'inde ilgili `DROP TYPE IF EXISTS` var (8 tip)
- [ ] **Hiçbir yeni kolon `NOT NULL` değil** (13/13 + 8/8 doğrulandı)
- [ ] **Veri migration'ı YOK** (`blocks.code` backfill'i yazılmadı — karar 5/8)
- [ ] **Canlı DB'ye migration KOŞULMADI**; her alembic komutu `DATABASE_URL` override'lı
- [ ] `--autogenerate` diff'i boş (model ↔ migration uyumu)

**Kurallar**
- [ ] İzin modülü sayısı **18**, matris **144**; `seed_data.py`'ye dokunulmadı
- [ ] Yeni izin modülü **yok**; okuma `projects:view`, yazma `full`, silme `admin`
- [ ] Görünmeyen kayıt → **404**, var olmayan kimlikle **ayırt edilemez**
- [ ] `boq_items` / `sections` / `contracts` tablolarına **dokunulmadı**
- [ ] Hiçbir yeni FK açılmadı (`sales_status` bir **enum sütunudur**, bağ değil)
- [ ] `sales_status` P8 geçiş notu `models.py` docstring'inde **birebir** duruyor

**Kapılar**
- [ ] `.venv/bin/ruff check .` + `.venv/bin/ruff format --check .` temiz
      (**tüm repo**, `alembic/` dahil)
- [ ] `openapi.json` üretildi, **commit edilmedi**, 14 uç doğrulandı
- [ ] Her task sonunda **commit** var; **push YOK**

**Teslim**
- [ ] Spec ve plan `backend/docs/superpowers/{specs,plans}/` altına taşındı
- [ ] `GOREV-SIRASI.md`'ye dilim özeti + alınan kararlar eklendi
      (§0.C'nin cevabı **kalıcı karar** olarak yazılır)
- [ ] Kullanıcıya bildirilecekler: push/PR/merge/deploy kararı bekliyor ·
      **merge ≠ deploy** (`railway up --detach` elle) · canlı doğrulama
      `/openapi.json` üzerinden · **canlı DB'ye migration elle koşulmaz**
