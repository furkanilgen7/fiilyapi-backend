# Alt-Proje 2 · P7 — İşveren Hakedişi uygulama planı

> **Ajanlar için:** ZORUNLU ALT-BECERİ: `superpowers:subagent-driven-development`.
> Adımlar `- [ ]` kutucuklarıyla izlenir. Her task sonunda **commit** edilir.

**Spec:** `docs/superpowers/specs/2026-07-31-alt-proje-2-p7-isveren-hakedisi-design.md`
(bu planda "spec §N" atıfları o dosyayadır — **her task başında ilgili bölüm okunur**)

**Dal:** `feat/p5-contracts` (P5'in üstüne inşa edilir; yeni dal açılmaz)

**Hedef:** `progress_payments` + `progress_payment_lines` tabloları, hesap motoru
(FF katsayısı, KDV, kümülatif tavanlı avans mahsubu, teminat), durum makinesi
(draft → pending_approval → approved → paid), tüm uçlar, `contracts`
placeholder'larının doldurulması, denetim günlüğü.

**Mimari:** Hakediş **sözleşmeye (= proje) bağlı TEK kayıttır** (D1); şantiye
kırılımı satır düzeyindedir. Satırlar `employer_contract_items`'a dayanır (D2),
fiyat/kod/birim **oluşturma anında satıra snapshot** kopyalanır (D3/D5); kesinti
yüzdeleri de sözleşmeden snapshot'lanır. Girdi **dönemseldir**, kümülatif türevdir
(D4). Aynı sözleşmede aynı anda **tek açık** (draft/pending) hakediş (D8).
**İzin modülü ZATEN VAR** (`seed_data.py:94/169`) — modül sayısı **18'de kalır**,
izin migration'ı YOKTUR.

**Teknoloji:** FastAPI · SQLAlchemy 2 (async) · Alembic · Pydantic v2 · pytest ·
PostgreSQL · ruff 0.15.22

---

## Kullanıcı kararları (spec §16 — BAĞLAYICI, yeniden tartışılmaz)

12 sorunun tamamı onaylandı; **K5 dışında hepsi spec'teki "Önerim" satırıyla**:

| # | Karar |
|---|---|
| K1 | Sözleşme düzeyi TEK kayıt, şantiye satırda (D1) |
| K2 | Kalem dayanağı `employer_contract_items`; BOQ yalnız korkuluk (D2) |
| K3 | Snapshot fiyat + taslakta isteğe bağlı `refresh-prices` (D3) |
| K4 | Dönemsel girdi, kümülatif türev (D4) |
| **K5** | **KURUŞ hassasiyeti** — `Numeric(18,2)`, `ROUND_HALF_UP`. Mockup'ın tam-lira gösterimi (OLU 122/126: 2.112,70→2.113) **ONAYLI SAPMADIR**; testler kuruşa göre yazılır, mockup'ın tam-lira ara sonuçları test edilmez (§H2 notu) |
| K6 | Kota aşımı **sert 422** (zeyilname gelene dek) |
| K7 | `paid` sonrası düzeltme yolu YOK (`unapprove` yalnız `approved`'dan) |
| K8 | `approved`/`paid` **admin dahil** silinemez (409); kapı `draft` + `can_delete` |
| K9 | Tek açık hakediş — ikincisi 409 |
| K10 | Dönem tekilliği **zorlanmaz** (ara hakediş serbest) |
| K11 | `mark-paid` = `approve` seviyesi, rol ayrımı yok |
| K12 | Ret/ödeme için ek form YOK — tek tık geçişler |

---

## Global kısıtlar

Bu bölüm **her task'ın gereksinimlerine dahildir**, tekrar edilmez.

* Python `.venv/bin/{python,pytest,alembic,ruff}` ile çağrılır — **PATH'te `python` YOK**.
* Ruff sürümü **0.15.22**'ye sabitlidir.
* Görünmeyen kayıt → **404**, var olmayan kimlikle **ayırt edilemez** gövde (spec §9.0).
* Tüm parasal ara sonuçlar `Decimal` + `quantize(Decimal("0.01"), ROUND_HALF_UP)` (K5).
* Hata metinleri Türkçe, tek kopya `progress_payments/guards.py`'de; uçlar kopyalamaz, **çağırır**.
* Yeni istisna sınıfı açılmaz — `app/core/errors.py`'deki mevcut sınıflar kullanılır
  (P5'te `SiteValidationError` yeniden kullanılmıştı; aynı desen).
* Kullanıcının doldurduğu alanlar NULL, sunucunun ürettiği/kopyaladığı alanlar NOT NULL
  (kalıcı karar 4 — gerekçe taslak desteği).
* `lazy="selectin"` zorunlu — async oturumda tembel yükleme `MissingGreenlet` atar.
* Ajanlar **push etmez**. Commit serbest; push/PR/merge/deploy kararı kullanıcıdadır.
* Aynı repoda aynı anda tek ajan çalışır.

---

## 0. TUZAKLAR — her task'ta yeniden okunur

### 0.1 TEST DB TUZAĞI (KRİTİK — veri kaybı riski)

`backend/.env`'deki `TEST_DATABASE_URL` **uzak Railway veritabanını** gösterir ve
`conftest.py` `drop_all` çağırır. **`.env`'e DOKUNULMAZ.** Testler her zaman:

```bash
createdb p7_test
TEST_DATABASE_URL="postgresql+asyncpg://furkanilgen@localhost:5432/p7_test" .venv/bin/pytest
dropdb p7_test    # BAŞARISIZLIKTA BİLE
```

### 0.2 Migration ebeveyni varsayılmaz, DOĞRULANIR

```bash
.venv/bin/alembic heads
```

Beklenen çıktı `e9e8e6a52f96` (p5_sozlesmeler) — ama **komut koşulur**, varsayılmaz.
Çıktıdaki revizyon `down_revision` olur.

### 0.3 Migration testinde `head` / `-1` KULLANILMAZ

`.venv/bin/alembic downgrade -1` her yeni migration'da **yanlış** revizyonu geri
alır (iki kez yaşandı). Her zaman açık revizyon id'si:

```bash
.venv/bin/alembic upgrade <p7_rev>
.venv/bin/alembic downgrade e9e8e6a52f96
.venv/bin/alembic upgrade <p7_rev>
```

### 0.4 Postgres enum'ı tabloyla silinmez

`downgrade()` tabloları düşürse de `progress_payment_status` tipi **kalır**.
Sonunda mutlaka:

```python
op.execute("DROP TYPE IF EXISTS progress_payment_status")
```

Unutulursa ikinci `upgrade` patlar (iki kez yaşanmış tuzak).

### 0.5 KAPI TÜM REPODUR

CI `ruff check .` + `ruff format --check .` koşar. **`app tests` ile sınırlı koşum
`alembic/` dizinini kaçırır ve CI'da kırmızıya düşer** (P5'te yaşandı, PR #9).
Her lint adımında:

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

### 0.6 TDD zorunlu — "KIRMIZI GÖR" atlanamaz

Test önce yazılır, **başarısız olduğu görülür**, sonra kod. Test ilk koşuda
yeşilse test yanlıştır → **mutasyon denetimi** yapılır (implementasyonda bir satır
bozulur, testin kırmızıya döndüğü doğrulanır, geri alınır).

### 0.7 İzin modülü AÇILMAZ — sayılar 18 / 144'te SABİT

`progress_payments` modülü ve matris satırı `seed_data.py:94/169`'da **zaten var**.
`seed_data.py`'ye ve izin migration'ına DOKUNULMAZ. Parity testleri
(`tests/modules/test_seed_matrix.py`, `test_seed_migration_matches_seed_data.py`)
**hiç dokunulmadan** yeşil kalmalıdır — kırmızıya dönerlerse yanlış bir şey yapılmıştır.

### 0.8 %100 mockup sadakati + K5 istisnası

Her alan mockup satır numarasıyla gerekçelidir; icat yasak. **TEK onaylı sapma K5**:
düzeltilmiş birim fiyat kuruş hassasiyetinde tutulur, mockup'ın tam-lira ara
sonuçları (OLU 122/126/137/141/170/174 ve bunlardan türeyen tfoot toplamları)
**test edilmez** — katsayısı 1,000 olan satırların sayıları (örn. OLU 156
1.315.800) ve E15'in tüm sayıları iki kuralda da aynıdır, altın testler onlardan yazılır.

### 0.9 `openapi.json` gitignore'ludur

Commit **edilmez**; frontend'e elle kopyalanır.

---

## 1. Dosya haritası

| Dosya | Sorumluluk | Task |
|---|---|---|
| `app/modules/progress_payments/__init__.py` | boş (YENİ) | H1 |
| `app/modules/progress_payments/models.py` | 2 tablo + `ProgressPaymentStatus` + `is_draft` property (YENİ) | H1 |
| `alembic/versions/<p7_rev>_p7_isveren_hakedisi.py` | tek revizyon (YENİ) | H1 |
| `app/modules/progress_payments/calculations.py` | saf hesap motoru (YENİ) | H2 |
| `app/modules/progress_payments/schemas.py` | Pydantic okuma/yazma (YENİ) | H3 |
| `app/modules/progress_payments/guards.py` | hata metinleri + submit/tutarlılık kuralları (YENİ) | H3 |
| `app/modules/progress_payments/repository.py` | sorgular (YENİ) | H4 |
| `app/modules/progress_payments/service.py` | CRUD + snapshot (YENİ) | H4 |
| `app/modules/progress_payments/lines.py` | `PUT …/lines` değiştirme + korkuluklar (YENİ) | H5 |
| `app/modules/progress_payments/transitions.py` | durum makinesi + FOR UPDATE (YENİ) | H6 |
| `app/modules/progress_payments/summary.py` | özet uçları + ilerleme türevleri (YENİ) | H9 |
| `app/modules/progress_payments/router.py` | tüm uçlar (YENİ) | H4–H9 |
| `app/main.py` | router kaydı (MEVCUT) | H4 |
| `app/modules/sites/guards.py` + `service.py` + `repository.py` | `SITE_HAS_PROGRESS_PAYMENTS` korkuluğu (MEVCUT) | H8 |
| `app/modules/contracts/schemas.py` + `service.py` | placeholder → gerçek değer (MEVCUT) | H9 |
| `app/modules/audit/messages.py` | mesaj aileleri (MEVCUT) | H10 |
| `tests/progress_payments/…` | test paketi (YENİ dizin: `__init__.py` + `conftest.py`) | H1–H11 |

---

## 2. Task listesi

### Task H1 — Modeller + enum + migration ⚠️ RİSKLİ

**Amaç:** `progress_payments` + `progress_payment_lines` tablolarını ve
`progress_payment_status` enum'unu şemaya eklemek.
**Spec:** §4 (tamamı), §12.
**Bağımlılık:** yok (ilk task).

**Dosyalar:**
- Oluştur: `app/modules/progress_payments/__init__.py`, `app/modules/progress_payments/models.py`
- Oluştur: `alembic/versions/<p7_rev>_p7_isveren_hakedisi.py`
- Oluştur: `tests/progress_payments/__init__.py`, `tests/progress_payments/conftest.py`
  (başlangıçta `tests/contracts/conftest.py`'deki `admin_headers`/`ornek_proje` deseninden
  gerekli fixture'lar; **fixture adları `tests/conftest.py` ve `tests/contracts/conftest.py`'den
  doğrulanır, uydurulmaz**)
- Test: `tests/progress_payments/test_models_migration.py`

**Arayüzler (üretir):** `ProgressPaymentStatus` (`draft|pending_approval|approved|paid`),
`ProgressPayment` (+ `is_draft` **property**), `ProgressPaymentLine`.

- [ ] **Adım 1: Testi yaz** — `tests/progress_payments/test_models_migration.py`

```python
import pytest
from sqlalchemy import inspect, text

from app.modules.progress_payments.models import (
    ProgressPayment,
    ProgressPaymentLine,
    ProgressPaymentStatus,
)


def test_status_uyeleri():
    assert [s.value for s in ProgressPaymentStatus] == [
        "draft", "pending_approval", "approved", "paid",
    ]


def test_is_draft_property():
    """Spec §4.1: is_draft KOLONU yok; Deletable protokolü için property var."""
    p = ProgressPayment(status=ProgressPaymentStatus.draft)
    assert p.is_draft is True
    p.status = ProgressPaymentStatus.pending_approval
    assert p.is_draft is False


@pytest.mark.asyncio
async def test_yeni_tablolar_olusur(db_session):
    tablolar = await db_session.run_sync(lambda s: inspect(s.bind).get_table_names())
    assert "progress_payments" in tablolar
    assert "progress_payment_lines" in tablolar


@pytest.mark.asyncio
async def test_donem_null_olabilir(db_session):
    """Kalıcı karar 4: kullanıcı alanı NULL (taslak desteği)."""
    sonuc = await db_session.execute(
        text(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name='progress_payments' AND column_name='period_year'"
        )
    )
    assert sonuc.scalar_one() == "YES"


@pytest.mark.asyncio
async def test_snapshot_yuzdeler_not_null(db_session):
    sonuc = await db_session.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='progress_payments' AND is_nullable='NO' "
            "AND column_name IN ('vat_pct','advance_pct','retainage_pct','sequence_no','created_by')"
        )
    )
    assert {r[0] for r in sonuc} == {
        "vat_pct", "advance_pct", "retainage_pct", "sequence_no", "created_by",
    }


@pytest.mark.asyncio
async def test_satir_miktar_sifir_kabul(db_session):
    """OLU 172 `value=\"0\"`: satırda 0 miktar MEŞRU (CHECK >= 0, BOQ'daki > 0'dan bilinçli fark)."""
    # fixture'la payment + line(quantity=0) yaz; IntegrityError BEKLENMEZ.
```

- [ ] **Adım 2: Koştur, KIRMIZI gör** (§0.1 komutlarıyla) —
  beklenen `ModuleNotFoundError: app.modules.progress_payments`

- [ ] **Adım 3: `models.py`'yi yaz** — spec §4.1/§4.2 tablolarındaki **her kolon**,
  her CHECK, her indeks:
  * `ProgressPayment`: FK `project_id → project_contracts.project_id` **CASCADE**
    indeksli; `UniqueConstraint("project_id", "sequence_no")`;
    `ck_progress_payments_month_range`, `ck_progress_payments_pct_range`,
    `ck_progress_payments_coefficient_positive`; `default_coefficient Numeric(8,3)`
    default/server_default `1.000`; `status` NOT NULL default `draft`
    server_default `'draft'`; `submitted_at/approved_at/approved_by/paid_at` NULL;
    `created_by` FK `users.id` RESTRICT NOT NULL; `approved_by` FK RESTRICT NULL.
  * `is_draft` **property** (kolon DEĞİL): `return self.status == ProgressPaymentStatus.draft`
    — `app/core/access.py:47-52` `Deletable` protokolünü karşılar.
  * Avans/teminat/KDV `amount` kolonları **AÇILMAZ** (spec §4.1 türev ilkesi).
  * `ProgressPaymentLine`: FK `payment_id` CASCADE indeksli; `contract_item_id →
    employer_contract_items.id` **SET NULL** indeksli NULL; `site_id → sites.id`
    **RESTRICT** indeksli NOT NULL; snapshot kolonları `code(50)/description/unit(50)/
    contract_unit_price Numeric(18,2)/group_name(200 NULL)` NOT NULL (group_name hariç);
    `coefficient Numeric(8,3)` NOT NULL default 1.000 + `CHECK coefficient > 0`;
    `quantity Numeric(14,3)` NOT NULL + **`CHECK quantity >= 0`**; `sort_order`;
    kısmi benzersiz indeks
    `uq_progress_payment_lines_item_site (payment_id, contract_item_id, site_id)
    WHERE contract_item_id IS NOT NULL`.
  * `ProgressPayment.lines` relationship `lazy="selectin"`,
    `cascade="all, delete-orphan"`, `order_by="ProgressPaymentLine.sort_order"`.

- [ ] **Adım 4: Migration'ı yaz**

```bash
.venv/bin/alembic heads     # ÇIKTI down_revision OLUR — e9e8e6a52f96 beklenir, DOĞRULA
.venv/bin/alembic revision -m "p7_isveren_hakedisi"
```

`upgrade()` sırası (spec §12): enum `progress_payment_status` → `progress_payments`
→ `progress_payment_lines` + kısmi benzersiz indeks. **İzin bloğu YOKTUR** (§0.7).
`downgrade()` ters sırada **ve sonunda**
`op.execute("DROP TYPE IF EXISTS progress_payment_status")`.

- [ ] **Adım 5: Testleri koştur YEŞİL + migration turu (yerel DB, açık id'ler)**

```bash
createdb p7_test
TEST_DATABASE_URL="postgresql+asyncpg://furkanilgen@localhost:5432/p7_test" \
  .venv/bin/pytest tests/progress_payments/test_models_migration.py -v
.venv/bin/alembic upgrade <p7_rev> && .venv/bin/alembic downgrade e9e8e6a52f96 \
  && .venv/bin/alembic upgrade <p7_rev>
dropdb p7_test    # başarısızlıkta bile
```

İkinci `upgrade` patlarsa `DROP TYPE` unutulmuştur (§0.4).

- [ ] **Adım 6: Lint (TÜM repo) + commit**

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check .
git add app/modules/progress_payments alembic/versions tests/progress_payments
git commit -m "feat(progress-payments): P7 şema — progress_payments + lines + enum"
```

**Kabul:** `test_models_migration.py` tümü yeşil · migration turu temiz ·
parity testleri (18/144) **dokunulmadan** yeşil · ruff temiz.

---

### Task H2 — Hesap motoru (saf fonksiyonlar) ⚠️ RİSKLİ (K5 altın sayılar)

**Amaç:** FF katsayısı, KDV, kümülatif tavanlı avans mahsubu, teminat ve net
hesabını DB'siz saf fonksiyonlarla yazmak.
**Spec:** §6 (tamamı), §8.
**Bağımlılık:** yok (H1'den bağımsız çalışabilir; sırada H1'den sonra).

**Dosyalar:**
- Oluştur: `app/modules/progress_payments/calculations.py`
  (H1 öncesi koşulursa `__init__.py` bu task'ta açılır)
- Test: `tests/progress_payments/test_calculations.py`

**Arayüzler (üretir):**
- `quantize2(value: Decimal) -> Decimal` — `distribution.py:62` `_quantize_money`
  deseninin genelleştirilmesi (ROUND_HALF_UP, `0.01`)
- `adjusted_unit_price(contract_unit_price, coefficient) -> Decimal`
- `line_total(contract_unit_price, coefficient, quantity) -> Decimal`
- `vat_amount(gross, vat_pct) -> Decimal`
- `advance_deduction(gross, advance_pct, contract_amount, advance_recovered) -> Decimal`
- `retention_amount(gross, retainage_pct) -> Decimal`
- `net_amount(gross, vat, advance, retention) -> Decimal`
- `duration_pct(start, end, today) -> Decimal | None` — uç-dahil (kalıcı karar 9), 0-100 kırpma

- [ ] **Adım 1: Testi yaz** — altın sayılar E15/OLU'dan, satır atıflarıyla:

```python
from decimal import Decimal

from app.modules.progress_payments import calculations as calc


def test_e15_odeme_hesabi_altin():
    """E15 151-172: brüt 2.110.000 → KDV +422.000 → avans −422.000 →
    teminat −105.500 → net 2.004.500. advance_recovered=1.258.000 (E14 tutarlı)."""
    gross = Decimal("2110000")
    vat = calc.vat_amount(gross, Decimal("20"))
    assert vat == Decimal("422000.00")
    advance = calc.advance_deduction(
        gross, Decimal("20"), Decimal("11200000"), Decimal("1258000")
    )
    assert advance == Decimal("422000.00")            # tavan (2.240.000) henüz uzak
    retention = calc.retention_amount(gross, Decimal("5"))
    assert retention == Decimal("105500.00")
    assert calc.net_amount(gross, vat, advance, retention) == Decimal("2004500.00")


def test_avans_tavani_kismi():
    """Tavana 40.000 kala: kesinti %20·brüt DEĞİL, kalan 40.000."""
    advance = calc.advance_deduction(
        Decimal("2110000"), Decimal("20"), Decimal("11200000"), Decimal("2200000")
    )
    assert advance == Decimal("40000.00")


def test_avans_tavani_dolmus():
    advance = calc.advance_deduction(
        Decimal("2110000"), Decimal("20"), Decimal("11200000"), Decimal("2240000")
    )
    assert advance == Decimal("0.00")


def test_katsayisiz_satir_olu_156():
    """OLU 156 (03.003, katsayı 1,000): 21.500 × 61,2 = 1.315.800 — iki kuralda da aynı."""
    assert calc.line_total(
        Decimal("21500"), Decimal("1.000"), Decimal("61.2")
    ) == Decimal("1315800.00")


def test_katsayili_satir_kurus_k5():
    """K5 ONAYLI SAPMA: 1.850 × 1,142 = 2.112,70 (mockup 2.113'e yuvarlıyordu, OLU 122).
    2.112,70 × 1.320 = 2.788.764,00 (mockup 2.789.160 DEĞİL, OLU 126)."""
    assert calc.adjusted_unit_price(Decimal("1850"), Decimal("1.142")) == Decimal("2112.70")
    assert calc.line_total(
        Decimal("1850"), Decimal("1.142"), Decimal("1320")
    ) == Decimal("2788764.00")


def test_yuvarlama_round_half_up():
    """quantize2 kenarı: .005 yukarı yuvarlanır (banker's rounding DEĞİL)."""
    assert calc.quantize2(Decimal("2.005")) == Decimal("2.01")


def test_sure_pct_uc_dahil():
    """Kalıcı karar 9: (bugün − start + 1) / (end − start + 1) × 100."""
    from datetime import date
    p = calc.duration_pct(date(2026, 1, 1), date(2026, 1, 10), date(2026, 1, 5))
    assert p == Decimal("50.00")


def test_sure_pct_tarih_yoksa_none():
    assert calc.duration_pct(None, None, None) is None
```

Ek kenarlar: `duration_pct` bugün aralık dışında → 0/100 kırpma; `advance_deduction`
`contract_amount=None` → çağıran katman engeller, saf fonksiyon `None` kabul etmez
(tip sözleşmesi); miktar 0 → satır toplamı `0.00`.

- [ ] **Adım 2: Koştur, KIRMIZI gör** — `ModuleNotFoundError` /
  `AttributeError`. **Test ilk koşuda yeşilse mutasyon denetimi** (§0.6).
- [ ] **Adım 3: `calculations.py`'yi yaz** — yalnız `Decimal` girdi/çıktı, DB ve
  ORM importu YOK (saflık); her fonksiyon docstring'inde spec §6.x + mockup satırı;
  `adjusted_unit_price` **önce** quantize2 edilir, `line_total` onun üstünden
  quantize2 (spec §6.1 formül sırası — mutasyon denetimi bu sırayı bozarak doğrulanır).
- [ ] **Adım 4: Koştur, YEŞİL gör**
- [ ] **Adım 5: Lint (tüm repo) + Commit**

```bash
git commit -m "feat(progress-payments): hesap motoru — FF, KDV, kümülatif tavanlı avans, teminat (K5 kuruş)"
```

**Kabul:** yukarıdaki test adlarının tamamı yeşil; `calculations.py` içinde
`sqlalchemy` importu YOK (grep ile doğrulanır).

---

### Task H3 — Pydantic şemaları + guards (hata metinleri, submit kuralları)

**Amaç:** Tüm istek/yanıt şemalarını ve tek-kopya kural/hata katmanını yazmak.
**Spec:** §4, §5.1, §6.5, §7 (zorunluluk kuralları), §9.7, §10/3-5-6.
**Bağımlılık:** H1.

**Dosyalar:**
- Oluştur: `app/modules/progress_payments/schemas.py`, `app/modules/progress_payments/guards.py`
- Test: `tests/progress_payments/test_schemas.py`, `tests/progress_payments/test_guards.py`

**Arayüzler (üretir):**
- Şemalar: `ProgressPaymentCreate` (`period_year/month?`, `description?`,
  `default_coefficient?`, `lines[]?`), `ProgressPaymentUpdate`,
  `ProgressPaymentLineInput` (`contract_item_id`, `site_id`, `quantity >= 0`,
  `coefficient? > 0`), `ProgressPaymentLinesSave` (`{lines: [...]}`),
  `ProgressPaymentListItem`, `ProgressPaymentListResponse`,
  `ProgressPaymentDetail` (satırlar + `is_price_stale` + grup toplulaştırması +
  ödeme hesabı + ilerleme göstergeleri), `PaymentCalculationBlock`,
  `ProgressBlock`, `ProgressPaymentSummary`, `RefreshPricesResponse`,
  `RejectBody` (`reason: str | None`)
- Guards sabitleri (spec §9.7 tam liste): `PERIOD_REQUIRED`, `LINES_REQUIRED`,
  `CONTRACT_AMOUNT_REQUIRED`, `ITEM_NOT_DISTRIBUTED`, `QUANTITY_EXCEEDS_QUOTA`,
  `SITE_PROJECT_MISMATCH` (P5 metni **aynen**: `contracts/guards.py:69`'dan
  kopya değil — metin birebir aynı yazılır), `NO_EMPLOYER_CONTRACT`,
  `ESCALATION_DISABLED`, `OPEN_PAYMENT_EXISTS`, `INVALID_STATUS_TRANSITION`,
  `PAYMENT_NOT_DELETABLE`, `PAYMENT_MISSING`
- `guards.validate_submit(payment, contract) -> None` — spec §7 zorunluluk tablosu

- [ ] **Adım 1: Testleri yaz**

```python
# test_schemas.py
def test_satir_miktari_sifir_kabul():
    """OLU 172: 0 meşru — P5 dağılımının '0 → 422' kuralı hakedişe TAŞINMAZ (spec §10/3)."""
    satir = ProgressPaymentLineInput(
        contract_item_id=uuid.uuid4(), site_id=uuid.uuid4(), quantity=0
    )
    assert satir.quantity == 0


def test_negatif_miktar_reddedilir():        # K7: negatif satır YOK
    with pytest.raises(ValidationError):
        ProgressPaymentLineInput(contract_item_id=uuid.uuid4(), site_id=uuid.uuid4(), quantity=-1)


def test_katsayi_sifir_reddedilir():
    with pytest.raises(ValidationError):
        ProgressPaymentLineInput(
            contract_item_id=uuid.uuid4(), site_id=uuid.uuid4(), quantity=1, coefficient=0
        )


def test_donem_ayi_araligi():
    with pytest.raises(ValidationError):
        ProgressPaymentCreate(period_year=2026, period_month=13)


def test_aciklama_taslakta_bos_olabilir():
    assert ProgressPaymentCreate().description is None
```

```python
# test_guards.py — DB'siz sahte nesnelerle (P5 test_guards deseninin birebiri)
def test_submit_donem_zorunlu():
    with pytest.raises(SiteValidationError) as hata:
        guards.validate_submit(_Hakedis(period_year=None), _Sozlesme())
    assert str(hata.value) == guards.PERIOD_REQUIRED


def test_submit_satirsiz_reddedilir():
    with pytest.raises(SiteValidationError) as hata:
        guards.validate_submit(_Hakedis(lines=[]), _Sozlesme())
    assert str(hata.value) == guards.LINES_REQUIRED


def test_submit_toplami_sifir_reddedilir():
    """Σ line_total > 0 şartı — satır var ama hepsi 0 miktar."""
    with pytest.raises(SiteValidationError) as hata:
        guards.validate_submit(_Hakedis(lines=[_Satir(quantity=0)]), _Sozlesme())
    assert str(hata.value) == guards.LINES_REQUIRED


def test_submit_sozlesme_bedelsiz_reddedilir():
    """Spec §6.3: amount NULL iken avans tavanı kurulamaz."""
    with pytest.raises(SiteValidationError) as hata:
        guards.validate_submit(_Hakedis(), _Sozlesme(amount=None))
    assert str(hata.value) == guards.CONTRACT_AMOUNT_REQUIRED


def test_taslak_serbest():
    """Kalıcı karar 4 deseni: zorunluluk yalnız submit'te; taslak kaydı kuralsız."""
    # validate_submit ÇAĞRILMADAN taslak yazılabilmeli — burada yalnız
    # guards'ın taslak yolunda import edilmediği/koşmadığı H4'te entegrasyonla test edilir.
```

- [ ] **Adım 2: Koştur, KIRMIZI gör**
- [ ] **Adım 3: Uygula** —
  * `schemas.py`: alan sınırları modeldekilerle **birebir** (`description` sınırsız
    Text; `code 50/unit 50/group_name 200` yanıt tarafında) — frontend `maxLength`'i
    buradan okur (spec §10/6). `ProgressPaymentDetail` satır öğesi türev alanları
    içerir: `adjusted_unit_price`, `line_total`, `previous_quantity/amount`,
    `cumulative_quantity/amount`, `is_price_stale: bool | None`.
  * `guards.py`: modül docstring'i `contracts/guards.py` gibi tek cümlelik kural +
    tutarlılık/zorunluluk ayrımı. `SiteValidationError` yeniden kullanılır.
- [ ] **Adım 4: Koştur, YEŞİL gör**
- [ ] **Adım 5: Lint (tüm repo) + Commit** —
  `feat(progress-payments): Pydantic şemaları + guards (submit kuralları, hata metinleri)`

**Kabul:** iki test dosyası yeşil; hata metinleri **yalnız** `guards.py`'de tanımlı
(`grep -rn "onaya gönderilemez" app/modules/progress_payments/` tek dosya döner).

---

### Task H4 — CRUD uçları: liste / detay / oluştur / düzenle + kapsam & IDOR kapıları ⚠️ RİSKLİ

**Amaç:** `GET` liste/detay, `POST` oluşturma (D8 + snapshot + `sequence_no`) ve
`PATCH` başlık düzenlemeyi kapsam süzgeçleriyle açmak.
**Spec:** §9.0, §9.1, §9.2 (POST/PATCH), §5, §6.6, §7 (yalnız draft düzenlenir).
**Bağımlılık:** H1, H2, H3.

**Dosyalar:**
- Oluştur: `app/modules/progress_payments/repository.py`, `service.py`, `router.py`
- Değiştir: `app/main.py` (router kaydı)
- Test: `tests/progress_payments/test_crud.py`, `tests/progress_payments/test_idor.py`

**Arayüzler:**
- Tüketir: H2 `calculations`, H3 şema/guards, mevcut
  `require_permission("progress_payments", …)`, `projects.service.visible_projects`
- Üretir: `progress_payments_router`; kapı sabitleri
  `_VIEW/_DRAFT/_APPROVE/_ADMIN` (H5–H9 bunları import eder);
  `GET /progress-payments?project_id=&site_id=&status=` ·
  `GET /progress-payments/{id}` · `POST /projects/{project_id}/progress-payments` ·
  `PATCH /progress-payments/{id}`

- [ ] **Adım 1: Testleri yaz** — kritik senaryolar:

```python
# test_crud.py
async def test_olusturma_sequence_no_uretir(client, admin_headers, sozlesmeli_proje):
    """E15 65 '#5': proje içi maks+1, sunucu üretir (gövdede gönderilemez)."""
    ilk = await client.post(
        f"/projects/{sozlesmeli_proje}/progress-payments", json={}, headers=admin_headers
    )
    assert ilk.status_code == 201
    assert ilk.json()["sequence_no"] == 1
    assert ilk.json()["status"] == "draft"


async def test_snapshot_yuzdeler_sozlesmeden_kopyalanir(client, admin_headers, sozlesmeli_proje):
    """D5: vat/advance/retainage oluşturma anında project_contracts'tan donar."""
    govde = (await client.post(
        f"/projects/{sozlesmeli_proje}/progress-payments", json={}, headers=admin_headers
    )).json()
    assert Decimal(govde["advance_pct"]) == Decimal("20")
    assert Decimal(govde["retainage_pct"]) == Decimal("5")
    assert Decimal(govde["vat_pct"]) == Decimal("20")


async def test_acik_hakedis_varken_ikincisi_409(client, admin_headers, taslak_hakedisli_proje):
    """D8/K9."""
    yanit = await client.post(
        f"/projects/{taslak_hakedisli_proje}/progress-payments", json={}, headers=admin_headers
    )
    assert yanit.status_code == 409
    assert yanit.json()["detail"] == guards.OPEN_PAYMENT_EXISTS


async def test_sozlesmesiz_proje_422(client, admin_headers, sozlesmesiz_proje):
    yanit = await client.post(
        f"/projects/{sozlesmesiz_proje}/progress-payments", json={}, headers=admin_headers
    )
    assert yanit.status_code == 422
    assert yanit.json()["detail"] == guards.NO_EMPLOYER_CONTRACT


async def test_satirli_olusturma_atomik_ve_snapshot(client, admin_headers, dagitimli_proje, ...):
    """§9.2: lines[] iç içe; satıra code/description/unit/unit_price/group_name kopyalanır."""


async def test_detay_odeme_hesabi_e15(client, admin_headers, e15_senaryosu):
    """E15 151-172 altın sayıları uç seviyesinde: gross/vat/advance/retention/net."""


async def test_liste_site_filtresi_exists(client, admin_headers, iki_santiyeli_hakedis, santiye_a):
    """SHK: site_id filtresi satırlarda EXISTS ile — kayıt tek, iki görünüm (D1)."""


async def test_pending_hakedis_patch_409(client, admin_headers, onay_bekleyen_hakedis):
    yanit = await client.patch(
        f"/progress-payments/{onay_bekleyen_hakedis}", json={"description": "x"},
        headers=admin_headers,
    )
    assert yanit.status_code == 409
```

```python
# test_idor.py — spec §9.0 negatif seti
async def test_gorunmeyen_proje_ile_olmayan_id_ayni_yanit(client, kisitli_headers, gorunmeyen_hakedis):
    gercek = await client.get(f"/progress-payments/{gorunmeyen_hakedis}", headers=kisitli_headers)
    sahte = await client.get(f"/progress-payments/{uuid.uuid4()}", headers=kisitli_headers)
    assert gercek.status_code == sahte.status_code == 404
    assert gercek.json() == sahte.json()


async def test_sef_atanmadigi_projede_olusturamaz_404(client, site_chief_headers, gorunmeyen_proje):
    """Şef scope=project: atanmamış proje 403 DEĞİL 404 (varlık sızdırmaz)."""
    yanit = await client.post(
        f"/projects/{gorunmeyen_proje}/progress-payments", json={}, headers=site_chief_headers
    )
    assert yanit.status_code == 404


async def test_gorunmeyen_hakedis_patch_404(client, kisitli_headers, gorunmeyen_hakedis): ...
async def test_yetkisiz_rol_403(client, hr_headers, hakedis):
    """İK matris satırı _N: modül izni yetersiz → 403 (kapı, görünürlükten ÖNCE)."""
```

Fixture adları (`admin_headers`, `site_chief_headers`, `kisitli_headers`,
`gorunmeyen_proje` …) `tests/contracts/conftest.py`'den **doğrulanır**; P7'ye özgü
olanlar (`sozlesmeli_proje` = `amount=11_200_000, advance 20, retainage 5, vat 20` +
poz + dağıtım) `tests/progress_payments/conftest.py`'de kurulur.

- [ ] **Adım 2: Koştur, KIRMIZI gör** — 404 (router yok)
- [ ] **Adım 3: Uygula** —
  * `router.py`: `_VIEW/_DRAFT/_APPROVE/_ADMIN = require_permission("progress_payments", AccessLevel.…)`
    (`contracts/router.py:54-58` deseni); `app/main.py`'ye `include_router`.
  * `service.create`: sözleşme satırı **`SELECT … FOR UPDATE`** ile kilitlenir; D8
    açık-hakediş kontrolü ve `sequence_no = maks+1` üretimi **aynı kilit altında**
    (spec §7 eşzamanlılık notunun oluşturmaya izdüşümü — iki eşzamanlı POST aynı
    numarayı üretemez). Snapshot: yüzdeler sözleşmeden, satır beşlisi kalemden.
  * Detay yanıtı: H2 fonksiyonlarıyla ödeme hesabı; §6.6 önceki/kümülatif türevleri
    (`prev = sequence_no < bu VE status ∈ {approved, paid}`); grup toplulaştırması
    (E15 96-141) `group_name` üzerinden; `is_price_stale` (spec §5.1: satır
    `contract_unit_price != kalem.unit_price`, bağ koptuysa `null`); §8 ilerleme
    blokları (eksik veri → `null`, zarif düşüş).
  * Her uç `visible_projects` süzgecinden geçer (spec §9.0).
- [ ] **Adım 4: Koştur, YEŞİL gör** + mutasyon denetimi: D8 kontrolü kaldırılıp
  `test_acik_hakedis…`'in kırmızıya döndüğü görülür, geri alınır.
- [ ] **Adım 5: Lint (tüm repo) + Commit** —
  `feat(progress-payments): CRUD uçları — oluşturma (D8+snapshot), liste, detay, PATCH`

**Kabul:** `test_crud.py` + `test_idor.py` yeşil · POST 201/409/422 · PATCH 409
(draft dışı) · görünmez/yok 404 gövdeleri bayt bayt eş.

---

### Task H5 — Satır ucu `PUT …/lines` (DEĞİŞTİRME semantiği) + kota/dağıtım korkulukları ⚠️ EN RİSKLİ

**Amaç:** OLU formunun tek "Taslak Kaydet" gövdesini atomik, değiştirme-semantikli
uçla yazmak; §6.5 korkuluklarını her yazımda koşturmak.
**Spec:** §9.2 (`PUT …/lines`), §6.5 (4 kural), §10/2-3-5.
**Bağımlılık:** H4.

**Dosyalar:**
- Oluştur: `app/modules/progress_payments/lines.py`
- Değiştir: `router.py`
- Test: `tests/progress_payments/test_lines.py`

**Arayüzler:**
- Üretir: `PUT /progress-payments/{id}/lines` (`_DRAFT`, yalnız `status=draft`);
  `lines.save_lines(session, actor, payment_id, data) -> ProgressPaymentDetail`
- Satır bazlı `POST/PATCH/DELETE …/lines/{line_id}` **AÇILMAZ** (YAGNI, spec §9.2).

- [ ] **Adım 1: Testi yaz**

```python
async def test_degistirme_semantigi_govdede_olmayan_silinir(client, admin_headers, satirli_taslak):
    """Spec §9.2/§10-2: P5 dağılımının BİRLEŞTİRME kuralının TERSİ — form tam tabloyu gönderir."""
    yanit = await client.put(
        f"/progress-payments/{satirli_taslak}/lines",
        json={"lines": [tek_satir]},          # önceden 3 satır vardı
        headers=admin_headers,
    )
    assert yanit.status_code == 200
    assert len(yanit.json()["lines"]) == 1


async def test_dagitilmamis_cifte_satir_422(client, admin_headers, taslak, dagitilmamis_kalem, santiye):
    """POZ 65: dağıtım ön şartı. Hata metni guards.ITEM_NOT_DISTRIBUTED."""
    yanit = await client.put(..., json={"lines": [{"contract_item_id": str(dagitilmamis_kalem),
        "site_id": str(santiye), "quantity": 10}]}, ...)
    assert yanit.status_code == 422
    assert yanit.json()["detail"] == guards.ITEM_NOT_DISTRIBUTED


async def test_kota_asimi_422_ve_hicbir_sey_yazilmaz(client, admin_headers, onceki_hakedisli_proje):
    """K6 sert 422: quantity + Σ(önceki approved/paid aynı çift) > BOQ kotası.
    ATOMİKLİK: ilk geçerli satır da yazılmamış olmalı (P5 C8 deseni)."""


async def test_kota_tam_sinirda_kabul(client, admin_headers, onceki_hakedisli_proje):
    """Kümülatif == kota → 200 (aşım DEĞİL)."""


async def test_baska_projenin_santiyesi_422(client, admin_headers, taslak, baska_santiye):
    # guards.SITE_PROJECT_MISMATCH — spec §9.0/§6.5-3


async def test_baska_sozlesmenin_kalemi_422(client, admin_headers, taslak, baska_projenin_kalemi):
    # §6.5-4 IDOR yüzeyi: kalem bu projenin sözleşmesine ait değil


async def test_ff_kapali_sozlesmede_katsayi_422(client, admin_headers, ff_kapali_taslak):
    """Spec §10/5: has_price_escalation=False iken coefficient != 1 → ESCALATION_DISABLED."""
    yanit = await client.put(..., json={"lines": [{..., "coefficient": "1.142"}]}, ...)
    assert yanit.status_code == 422
    assert yanit.json()["detail"] == guards.ESCALATION_DISABLED


async def test_sifir_miktarli_satir_kabul(client, admin_headers, taslak):
    """OLU 172: 0 meşru."""


async def test_ayni_hucre_iki_kez_gonderilirse_422(client, admin_headers, taslak):
    """Kısmi benzersiz indeks (payment, item, site) — gövde içi çift de 422
    (IntegrityError'a düşmeden guards'ta yakalanır; P5 DUPLICATE_ALLOCATION deseni)."""


async def test_pending_hakediste_lines_409(client, admin_headers, onay_bekleyen_hakedis):
    # yalnız draft; INVALID_STATUS_TRANSITION


async def test_yeni_satira_default_coefficient_iner(client, admin_headers, katsayili_taslak):
    """§4.1: default_coefficient yalnız coefficient GÖNDERİLMEYEN satıra öntanımlı iner."""
```

- [ ] **Adım 2: Koştur, KIRMIZI gör**
- [ ] **Adım 3: Uygula** — sıra **önemli** (P5 C8 dersi): önce TÜM doğrulamalar
  (durum, gövde-içi çift, şantiye-proje, kalem-sözleşme, dağıtım ön şartı, kota,
  FF kilidi), **sonra** yazma (sil + yeniden kur / eşle). Kota sorgusu: aynı
  (kalem, şantiye) çiftinin **önceki `approved|paid`** hakediş satırlarının miktar
  toplamı + gelen miktar ≤ `boq_items.quantity` (o çiftin dağıtılmış satırı).
  Snapshot beşlisi her **yeni** satırda kalemden kopyalanır; mevcut satırın
  snapshot'ı korunur (tazeleme yalnız H7 ucundadır — spec §5).
- [ ] **Adım 4: Koştur, YEŞİL gör** + mutasyon denetimi: kota kontrolü kaldırılır,
  `test_kota_asimi…` kırmızıya döner, geri alınır.
- [ ] **Adım 5: Lint (tüm repo) + Commit** —
  `feat(progress-payments): PUT lines — değiştirme semantiği + kota/dağıtım korkulukları`

**Kabul:** tüm testler yeşil; aşımda atomiklik (DB'de satır 0) test edilmiş;
`ITEM_NOT_DISTRIBUTED`/`QUANTITY_EXCEEDS_QUOTA`/`SITE_PROJECT_MISMATCH`/
`ESCALATION_DISABLED` dördü de 422 gövdesinde birebir metinle.

---

### Task H6 — Durum geçişleri + izin kapıları + `SELECT … FOR UPDATE` ⚠️ RİSKLİ

**Amaç:** submit / approve / reject / mark-paid / unapprove geçişlerini kilitli ve
kapılı yazmak.
**Spec:** §7 (tamamı), §9.4.
**Bağımlılık:** H4, H5 (submit zorunlulukları satırlara bakar).

**Dosyalar:**
- Oluştur: `app/modules/progress_payments/transitions.py`
- Değiştir: `router.py`
- Test: `tests/progress_payments/test_transitions.py`

**Arayüzler (üretir):**
`POST /progress-payments/{id}/submit` (`_DRAFT`) · `…/approve` (`_APPROVE`) ·
`…/reject` (`_APPROVE`, gövde `{reason?}` — K12: ek form YOK) ·
`…/mark-paid` (`_APPROVE` — K11) · `…/unapprove` (`_ADMIN`).

- [ ] **Adım 1: Testi yaz**

```python
GECERLI = [("draft", "submit"), ("pending_approval", "approve"),
           ("pending_approval", "reject"), ("approved", "mark-paid"),
           ("approved", "unapprove")]
TUM_GECISLER = [(d, u) for d in DURUMLAR for u in UCLAR]


@pytest.mark.parametrize("durum,uc", [g for g in TUM_GECISLER if g not in GECERLI])
async def test_gecersiz_gecis_409(client, admin_headers, hakedis_fabrikasi, durum, uc):
    """Tanımsız HER çift 409 INVALID_STATUS_TRANSITION (paid→unapprove dahil — K7)."""


async def test_submit_damga_ve_durum(client, admin_headers, gecerli_taslak):
    # 200 · status=pending_approval · submitted_at dolu


async def test_submit_zorunluluklari(client, admin_headers, ...):
    # dönemi boş → PERIOD_REQUIRED · satırsız → LINES_REQUIRED ·
    # Σ=0 → LINES_REQUIRED · contract.amount NULL → CONTRACT_AMOUNT_REQUIRED (hepsi 422)


async def test_approve_damgalari(client, muhasebe_headers, onay_bekleyen):
    # approved_by = aktör, approved_at dolu


async def test_reject_drafta_dondurur_ve_yeniden_duzenlenir(client, pm_headers, admin_headers, onay_bekleyen):
    # reject → draft; ardından PUT lines 200 (yeniden düzenlenebilirlik)


async def test_sef_approve_edemez_403(client, site_chief_headers, onay_bekleyen):
    """Matris: şef=draft; approve seviyesi gerekir."""


async def test_saha_submit_edebilir(client, field_engineer_headers, kendi_projesinde_taslak):
    """Matris: saha=draft (scope=project) — kendi projesinde submit serbest."""


async def test_admin_disinda_unapprove_403(client, muhasebe_headers, onaylanmis): ...


async def test_eszamanli_cifte_approve(db harness):
    """FOR UPDATE: iki eşzamanlı approve'dan biri 200, öbürü 409; approved_at TEK kez damgalanır.
    (İki ayrı oturum/transaction ile; P5 devir bulgusu 4'ün tekrar etmediğinin kanıtı.)"""


async def test_approve_sonrasi_yeni_hakedis_acilabilir(client, admin_headers, onaylanmis_proje):
    """D8: açık hakediş kalmadı → POST 201, sequence_no +1."""
```

- [ ] **Adım 2: Koştur, KIRMIZI gör**
- [ ] **Adım 3: Uygula** — `transitions.py` tek geçiş tablosu
  (`{(mevcut_durum, işlem): yeni_durum}`); her geçiş hakediş satırını
  **`SELECT … FOR UPDATE`** ile okur; submit `guards.validate_submit` + §6.5
  korkuluklarını (kota, dağıtım — satırlar taslakta değişmiş olabilir mi? hayır ama
  **önceki küme** aynı kilit penceresinde yeniden doğrulanır) çağırır; `reject`
  `reason`'ı denetim günlüğüne taşır (H10), ayrı kolon AÇILMAZ (mockup'ta alan yok).
- [ ] **Adım 4: Koştur, YEŞİL gör** + mutasyon denetimi (geçiş tablosundan bir
  çift silinip parametrize testin kırmızıya döndüğü görülür, geri alınır)
- [ ] **Adım 5: Lint (tüm repo) + Commit** —
  `feat(progress-payments): durum makinesi — submit/approve/reject/mark-paid/unapprove (FOR UPDATE)`

**Kabul:** parametrize geçersiz-çift seti tamamen 409 · geçerli geçişler doğru
damgalarla 200 · submit 422 dörtlüsü · eşzamanlılık testi yeşil.

---

### Task H7 — `refresh-prices` (taslakta snapshot tazeleme)

**Amaç:** Taslak hakedişte bağı kopmamış satırların snapshot beşlisini + hakedişin
snapshot yüzdelerini kalemden/sözleşmeden bilinçli tazelemek.
**Spec:** §5.1, §9.3, §14 D3/D5 ("yüzdeler de aynı uçta tazelenir").
**Bağımlılık:** H5, H6.

**Dosyalar:**
- Değiştir: `service.py` (veya `lines.py`), `router.py`
- Test: `tests/progress_payments/test_refresh_prices.py`

**Arayüzler (üretir):** `POST /progress-payments/{id}/refresh-prices` (`_DRAFT`,
yalnız `draft`) → `{refreshed_count}`.

- [ ] **Adım 1: Testi yaz**

```python
async def test_kalem_fiyati_degisince_taslak_etkilenmez_stale_doner(client, admin_headers, ...):
    """§5.1: snapshot kendiliğinden DEĞİŞMEZ; detayda is_price_stale=True döner."""


async def test_refresh_snapshotu_ve_yuzdeleri_tazeler(client, admin_headers, bayat_taslak):
    # kalem fiyatı 1850→1900 + sözleşme retainage 5→10 sonrası:
    yanit = await client.post(f"/progress-payments/{bayat_taslak}/refresh-prices", headers=admin_headers)
    assert yanit.status_code == 200
    assert yanit.json()["refreshed_count"] == 1
    detay = (await client.get(...)).json()
    assert Decimal(detay["lines"][0]["contract_unit_price"]) == Decimal("1900")
    assert Decimal(detay["retainage_pct"]) == Decimal("10")
    assert detay["lines"][0]["is_price_stale"] is False


async def test_bagi_kopuk_satir_atlanir_stale_null(client, admin_headers, kalemi_silinmis_taslak):
    # SET NULL sonrası: refreshed_count o satırı saymaz; is_price_stale null


async def test_pending_hakediste_refresh_409(client, admin_headers, onay_bekleyen):
    """§5.1: onaya giden evrak sabittir."""
```

- [ ] **Adım 2: Koştur, KIRMIZI gör**
- [ ] **Adım 3: Uygula** — `code/description/unit/unit_price(→contract_unit_price)/
  group_name` beşlisi kalemden, `vat/advance/retainage_pct` üçlüsü sözleşmeden;
  `coefficient`/`quantity` DOKUNULMAZ (kullanıcı verisi).
- [ ] **Adım 4: Koştur, YEŞİL gör**
- [ ] **Adım 5: Lint (tüm repo) + Commit** —
  `feat(progress-payments): refresh-prices — taslakta bilinçli snapshot tazeleme`

**Kabul:** dört test yeşil; `refreshed_count` bağı kopukları saymıyor; 409 draft-dışı.

---

### Task H8 — Silme + `sites` RESTRICT korkuluğu

**Amaç:** K8 iki katmanlı silme kuralını ve hakedişli şantiyenin silinemezliğini yazmak.
**Spec:** §7.1, §9.5, §4.2 (`site_id` RESTRICT + `sites/guards.py` eklemesi).
**Bağımlılık:** H6 (unapprove yolu teste girer).

**Dosyalar:**
- Değiştir: `service.py`, `router.py`,
  `app/modules/sites/guards.py`, `app/modules/sites/service.py`,
  `app/modules/sites/repository.py` (P5 C12'de `SITE_HAS_CONTRACTS`'ın konduğu
  üç-korkuluk zincirine beşincisi eklenir; mevcut zincir koddan **doğrulanır**)
- Test: `tests/progress_payments/test_delete.py`

**Arayüzler (üretir):** `DELETE /progress-payments/{id}` (kapı **`_DRAFT`** +
serviste iki katman) · `sites.repository.site_has_progress_payment_lines(session, site_id) -> bool`
· `sites/guards.py`'ye `SITE_HAS_PROGRESS_PAYMENTS` metni.

- [ ] **Adım 1: Testi yaz** — `can_delete` çapraz tablosu (rol × durum × sahiplik):

```python
async def test_approved_admin_bile_silemez_409(client, admin_headers, onaylanmis):
    """K8: PAYMENT_NOT_DELETABLE — kalıcı karar 2'nin daraltılması (spec §7.1 gerekçesi)."""
    yanit = await client.delete(f"/progress-payments/{onaylanmis}", headers=admin_headers)
    assert yanit.status_code == 409
    assert yanit.json()["detail"] == guards.PAYMENT_NOT_DELETABLE


async def test_paid_de_silinemez_409(client, admin_headers, odenmis): ...


async def test_admin_unapprove_sonrasi_silebilir(client, admin_headers, onaylanmis):
    """Denetim izli iki adım: unapprove → pending → (admin) DELETE 204."""


async def test_sef_kendi_taslagini_silebilir(client, site_chief_headers, kendi_taslagi):
    # can_delete: created_by == aktör AND is_draft AND seviye >= draft → 204


async def test_sef_baskasinin_taslagini_silemez_403(client, site_chief_headers, baskasinin_taslagi): ...


async def test_pending_admin_disinda_silinemez(client, muhasebe_headers, onay_bekleyen):
    """is_draft=False → taslak istisnası kapalı; approve seviyesi bile 403."""


async def test_pending_admin_silebilir_204(client, admin_headers, onay_bekleyen): ...


async def test_hakedisli_santiye_silinemez_409(client, admin_headers, hakedisli_santiye):
    """§4.2 RESTRICT: DB hatasına düşmeden serviste 409 + Türkçe metin."""
```

- [ ] **Adım 2: Koştur, KIRMIZI gör**
- [ ] **Adım 3: Uygula** — servis sırası: (1) `status ∈ {approved, paid}` → 409
  `PAYMENT_NOT_DELETABLE` (admin dahil); (2) kalanlar `can_delete(actor.id, level, record)`
  (`app/core/access.py:55`) — `is_draft` property'si H1'de bu yüzden var; ret → 403.
  `sites` silme zincirine `site_has_progress_payment_lines` eklenir.
- [ ] **Adım 4: Koştur, YEŞİL gör** — mevcut `sites` silme testleri de koşturulur
  (`tests/modules/sites/`), kırılmadıkları doğrulanır.
- [ ] **Adım 5: Lint (tüm repo) + Commit** —
  `feat(progress-payments): silme — iki katmanlı kural + hakedişli şantiye korkuluğu`

**Kabul:** çapraz tablo testlerinin tamamı (409/403/204 hücreleri) yeşil;
`sites` mevcut silme testleri yeşil.

---

### Task H9 — Özet ucu + `contracts` placeholder'larının doldurulması ⚠️ RİSKLİ (kırıcı şema değişikliği)

**Amaç:** `GET …/progress-payments/summary` ucunu açmak ve P5'in
`MetricPlaceholder`'larını gerçek değerle değiştirmek.
**Spec:** §9.6, §10/4, §8; P5 devir bulgusu 3.
**Bağımlılık:** H6 (özet yalnız approved/paid kümülatifinden beslenir).

**Dosyalar:**
- Oluştur: `app/modules/progress_payments/summary.py`
- Değiştir: `router.py`; `app/modules/contracts/schemas.py`
  (satır 79-101: `ContractSummary.progress_payment_total` ve
  `ContractListItem.progress_pct` → düz `Decimal | None`; satır 215-219:
  `EmployerContractDetail.progress_payment_summary` → gerçek nesne,
  `pending_modules`'ten `"progress_payments"` çıkarılır);
  `app/modules/contracts/service.py` (liste/detay dolduran kod)
- Test: `tests/progress_payments/test_summary.py`; mevcut
  `tests/contracts/test_contract_list.py` **güncellenir**
  (`progress_payment_total is None` asserti artık gerçek değeri bekler — bilinçli
  test değişikliği, spec §9.6)

**Arayüzler (üretir):**
`GET /projects/{project_id}/progress-payments/summary` (`_VIEW`) — alanlar spec
§9.6: `contract_amount · cumulative_gross · progress_pct · advance_deduction_total ·
retention_total · net_total · payment_count · pending_count · remaining`.

⚠️ **Dikkat (taşeron tarafı):** `SubcontractorContractDetail.pending_modules`
(`contracts/schemas.py:495`) içindeki `"progress_payments"` **işveren hakedişi
değildir** — taşeron hakedişi ayrı dilimdir (spec §1.2). Buradaki değer
`"subcontractor_progress_payments"` olarak **yeniden adlandırılır** (spec §1.2
placeholder adı), listeden çıkarılMAZ. Spec §9.6'nın "schemas.py:495" atfı bu
düzeltmeyle uygulanır; çelişki plan raporunda kullanıcıya not edilmiştir.

- [ ] **Adım 1: Testleri yaz**

```python
async def test_ozet_e14_altin(client, admin_headers, dort_onayli_hakedisli_proje):
    """E14 127-147: bedel 11.200.000 · kümülatif 8.400.000 · %75 ·
    avans −1.680.000 (tavana varmamış: < 2.240.000) · teminat −420.000 · net 6.300.000 ·
    remaining 2.800.000 (E15 89-90)."""


async def test_ozet_sayaclari_shk(client, admin_headers, karisik_durumlu_proje):
    # payment_count (approved+paid; SHK 82 "4 hakediş") · pending_count (SHK 84)


async def test_taslak_kumulatife_girmez(client, admin_headers, taslakli_proje):
    """Yalnız approved/paid sayılır (§6.6 prev kümesi)."""


async def test_sozlesme_listesi_gercek_deger_doner(client, admin_headers, hakedisli_proje):
    """P5 placeholder'ı doldu: progress_payment_total artık MetricPlaceholder DEĞİL sayı."""
    govde = (await client.get("/contracts?type=employer", headers=admin_headers)).json()
    assert Decimal(govde["summary"]["progress_payment_total"]) == Decimal("8400000.00")
    assert "pending_module" not in str(govde["summary"]["progress_payment_total"])


async def test_isveren_detayinda_pending_modules_kucduldu(client, admin_headers, sozlesmeli_proje):
    govde = (await client.get(f"/projects/{sozlesmeli_proje}/contract", headers=admin_headers)).json()
    assert "progress_payments" not in govde["pending_modules"]
    assert govde["progress_payment_summary"] is not None


async def test_hakedissiz_projede_ozet_sifirlar(client, admin_headers, sozlesmeli_proje):
    # kümülatifler 0, progress_pct 0 veya null (amount doluysa 0), remaining = amount
```

- [ ] **Adım 2: Koştur, KIRMIZI gör** (yeni testler) — ayrıca mevcut
  `test_contract_list.py`'nin hangi assertlerinin kırılacağı **önce grep'le bulunur**
  (`grep -rn "progress_payment_total\|progress_pct\|pending_modules" tests/`), tahmin edilmez.
- [ ] **Adım 3: Uygula** — özet tek sorgu ailesiyle (N+1 yok); `contracts/service.py`
  liste yolunda proje başına kümülatif brüt toplu (tek GROUP BY) çekilir;
  dairesel import riski: `contracts` → `progress_payments` yönlü **yerel import**
  (`projects/service.py:401` deseni koddan doğrulanır).
- [ ] **Adım 4: Koştur, YEŞİL gör** — tam `tests/contracts/` paketi de koşturulur.
- [ ] **Adım 5: Lint (tüm repo) + Commit** —
  `feat(progress-payments): özet ucu + contracts placeholder'ları gerçek değere döndü`

**Kabul:** E14 altın sayıları uçtan yeşil · `contracts` paketinin tamamı yeşil ·
`pending_modules` işveren tarafında `progress_payments` içermiyor, taşeron tarafında
`subcontractor_progress_payments` var.

---

### Task H10 — Denetim günlüğü

**Amaç:** Tüm yazma uçlarına denetim mesajlarını bağlamak.
**Spec:** §11.
**Bağımlılık:** H4–H9 (tüm yazma uçları mevcut olmalı).

**Dosyalar:**
- Değiştir: `app/modules/audit/messages.py`, `router.py` (veya servis katmanı —
  mevcut `record_audit` çağrı deseni koddan doğrulanır)
- Test: `tests/progress_payments/test_audit.py`

**Arayüzler (üretir):** `progress_payment_created/updated/deleted` ·
`progress_payment_submitted/approved/rejected/paid/unapproved` ·
`progress_payment_lines_saved(project_name, sequence_no, count)` ·
`progress_payment_prices_refreshed(project_name, sequence_no, count)` —
mevcut adlandırma deseninin (`messages.py:27+`) birebiri.

- [ ] **Adım 1: Testi yaz** — P5 `test_audit.py` deseninin birebiri
  (`_audit_sayisi` yardımcıcısı):

```python
async def test_okuma_denetim_yazmaz(...)          # GET liste + detay + summary
async def test_olusturma_denetime_yazar(...)      # +1
async def test_lines_kaydi_count_ile_yazar(...)   # mesajda satır sayısı
async def test_her_durum_gecisi_yazar(...)        # submit/approve/reject/mark-paid/unapprove — 5 ayrı kayıt
async def test_reject_reason_mesaja_girer(...)    # K12: reason kolonu YOK, günlük metninde
async def test_refresh_prices_yazar(...)
async def test_silme_yazar(...)
```

- [ ] **Adım 2: Koştur, KIRMIZI gör**
- [ ] **Adım 3: Uygula** — okuma uçları YAZMAZ; her mesaj `(project_name, sequence_no)` taşır.
- [ ] **Adım 4: Koştur, YEŞİL gör**
- [ ] **Adım 5: Lint (tüm repo) + Commit** —
  `feat(progress-payments): denetim günlüğü mesajları`

**Kabul:** yazma uçlarının tamamı tam bir denetim kaydı üretir; okuma uçları sayacı artırmaz.

---

### Task H11 — Kapı turu: tam repo lint + tam pytest + migration turu + openapi

**Amaç:** Dilimin "Bitti" tanımını (spec §17) kanıtlarla kapatmak.
**Spec:** §17.
**Bağımlılık:** H1–H10.

**Dosyalar:** `openapi.json` (üretilir, **commit edilmez** — gitignore'lu).

- [ ] **Adım 1: Tam test koşusu (yerel DB, `.env`'e dokunmadan)**

```bash
createdb p7_test
TEST_DATABASE_URL="postgresql+asyncpg://furkanilgen@localhost:5432/p7_test" .venv/bin/pytest -q
dropdb p7_test    # başarısızlıkta bile
```

- [ ] **Adım 2: Lint + biçim — TÜM REPO (§0.5, `app tests` sınırlaması YASAK)**

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

- [ ] **Adım 3: Migration turu — açık revizyon id'leriyle (`head`/`-1` YASAK)**

```bash
.venv/bin/alembic upgrade <p7_rev>
.venv/bin/alembic downgrade e9e8e6a52f96
.venv/bin/alembic upgrade <p7_rev>
```

- [ ] **Adım 4: Parity doğrulaması** — `tests/modules/test_seed_matrix.py` +
  `test_seed_migration_matches_seed_data.py` **değiştirilmeden** yeşil
  (`git diff --stat app/modules/roles/ tests/modules/test_seed*` BOŞ olmalı).

- [ ] **Adım 5: `openapi.json` üret ve gözle doğrula**

```bash
.venv/bin/python -c "import json;from app.main import app;print(json.dumps(app.openapi(),ensure_ascii=False,indent=2))" > openapi.json
grep -c '"/progress-payments' openapi.json     # liste/detay/lines/geçişler/refresh/silme
grep -c 'progress-payments/summary' openapi.json
```

Spec §9'daki **her uç** çıktıda görünmelidir; eksik varsa ilgili task geri açılır.

- [ ] **Adım 6: Spec §17 kontrol listesi tek tek işaretlenir ve commit**

```bash
git add -A ':!openapi.json'
git commit -m "chore(progress-payments): P7 kapanış — tam kapı koşusu"
```

**Kabul:** tam pytest yeşil · ruff (tüm repo) temiz · migration turu temiz ·
parity dosyaları diff'siz · openapi'de tüm uçlar · **push/PR/merge/deploy YAPILMADI**.

---

## 3. "Bitti" tanımı (spec §17'nin izdüşümü)

- [ ] 2 yeni tablo + 1 enum + **tek** migration (ebeveyn `e9e8e6a52f96`); upgrade→downgrade→upgrade temiz; downgrade `DROP TYPE progress_payment_status` içeriyor
- [ ] Spec §9'daki uçların tamamı izin + görünürlük kapılarından geçiyor; IDOR negatif seti yeşil
- [ ] Hesap motoru E15/OLU altın sayılarıyla birebir — **K5 kuruş kuralıyla** (tam-lira ara sonuçlar bilinçli test dışı)
- [ ] İzin matrisi DEĞİŞMEDİ — modül 18, satır 144; parity testleri **dokunulmadan** yeşil
- [ ] `contracts` placeholder'ları dolduruldu; işveren tarafında `pending_modules`'ten `progress_payments` çıktı (taşeron tarafı `subcontractor_progress_payments`'a adlandı)
- [ ] D8 tek açık hakediş; kota sert 422; `approved/paid` admin dahil silinemez
- [ ] `ruff check .` + `ruff format --check .` (tüm repo) + tam `pytest` yeşil
- [ ] Denetim günlüğü mesajları eklendi ve testlendi
- [ ] `openapi.json` üretildi, **commit edilmedi**
- [ ] **Push/PR/merge/deploy YAPILMADI** — karar kullanıcıda

## 4. Riskli task'lar

| Task | Risk | Azaltma |
|---|---|---|
| H1 | Enum/migration; ikinci upgrade patlar; `is_draft` kolon olarak açılabilir | §0.3/0.4 açık id turu + `DROP TYPE`; property testi H1'de |
| H2 | K5 sapması yanlış yöne (mockup'ın tam-lira sayıları teste girer) | §0.8: yalnız katsayısız + E15 sayıları altın; K5 testte açık yorumla |
| H4 | IDOR/404 ayırt edilebilirliği; sequence yarışı | gövde-eş 404 testi; POST'ta FOR UPDATE |
| H5 | Değiştirme semantiği + atomiklik + kota | önce TÜM doğrulama sonra yazma; mutasyon denetimi |
| H6 | Geçiş tablosunda kaçak çift; çifte approve | parametrize TÜM çiftler; eşzamanlılık testi |
| H9 | Kırıcı şema değişikliği P5 testlerini kırar; dairesel import | önce grep ile etkilenen testler bulunur; yerel import deseni |

## 5. Frontend'e devredilen (bu planın DIŞI)

* E15 · OLU · SHK sol sütun ekranları; E14 "Hakedişler" sekmesi
* **BFF `ALLOWED_ROOTS`'a `progress-payments`** (spec §10/1 — eklenmezse modül
  yalnız canlıda 404; "zaten var" varsayma, grep'le). `projects` altındaki iç içe
  uçlar mevcut kökle geçer.
* `PUT …/lines` **değiştirme** semantiği kontrata yazılır (P5 dağılımının
  birleştirme kuralının TERSİ); satır `quantity` için `0` meşru
* `MetricPlaceholder` → düz değer kırıcı değişikliği: `openapi.json` elle kopyalanıp
  `gen:api` yenilenir
* FF toggle: `has_price_escalation=false` sözleşmede katsayı kolonu kilitli (backend
  zaten 422 verir); E15 "PDF" butonu devre dışı + bildirim; OLU kar analizi kartı
  placeholder (`subcontractor_progress_payments`)
