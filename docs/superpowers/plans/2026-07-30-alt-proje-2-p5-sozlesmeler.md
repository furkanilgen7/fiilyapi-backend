# Alt-Proje 2 · P5 — Sözleşmeler uygulama planı

> **Ajanlar için:** ZORUNLU ALT-BECERİ: `superpowers:subagent-driven-development`.
> Adımlar `- [ ]` kutucuklarıyla izlenir. Her task sonunda **commit** edilir.

**Spec:** `docs/superpowers/specs/2026-07-30-alt-proje-2-p5-sozlesmeler-design.md`
(bu planda "spec §N" atıfları o dosyayadır — **her task başında ilgili bölüm okunur**)

**Hedef:** İşveren sözleşmesi poz listesi + poz dağılımı + taşeron kartoteksi +
taşeron sözleşmesi ve kalemleri; hepsi yeni `contracts` izin modülü altında.

**Mimari:** `project_contracts` (mevcut, 1-1) yerinde kalır ve yalnız `status`
kolonu eklenir. Beş yeni tablo `app/modules/contracts/` altında toplanır. İşveren
sözleşmesi pozları `boq_items`'a nullable `contract_item_id` ile bağlanır; poz
dağılımı bu bağı toplu yazan tek atomik uçtur.

**Teknoloji:** FastAPI · SQLAlchemy 2 (async) · Alembic · Pydantic v2 · pytest ·
PostgreSQL · ruff 0.15.22

---

## Global kısıtlar

Bu bölüm **her task'ın gereksinimlerine dahildir**, tekrar edilmez.

* Python `.venv/bin/{python,pytest,alembic,ruff}` ile çağrılır — **PATH'te `python` YOK**.
* Ruff sürümü **0.15.22**'ye sabitlidir.
* Görünmeyen kayıt → **404**, var olmayan kimlikle **ayırt edilemez** gövde.
* Silme = `admin` seviyesi (kalıcı karar 2); tek istisna `can_delete`'in taslak istisnası.
* Yeni kolonlarda NOT NULL **yalnız** sunucu varsayılanı olanlarda (gerekçe: taslak desteği).
* Tutarlılık kuralları her zaman, zorunluluk kuralları **yalnız taslak-dışında** koşar.
* Hata metinleri Türkçe, tek kopya `contracts/guards.py`'de; POST ve PATCH kopyalamaz, **çağırır**.
* Yeni istisna sınıfı açılmaz — `app/core/errors.py`'deki mevcut sınıflar kullanılır.
* Ajanlar **push etmez**. Commit serbest; push/PR/merge/deploy kararı kullanıcıdadır.
* Aynı repoda aynı anda tek ajan çalışır.

---

## 0. TUZAKLAR — her task'ta yeniden okunur

### 0.1 TEST DB TUZAĞI (KRİTİK — veri kaybı riski)

`backend/.env`'deki `TEST_DATABASE_URL` **uzak Railway veritabanını** gösterir ve
`conftest.py` `drop_all` çağırır. **`.env`'e DOKUNULMAZ.** Testler her zaman:

```bash
createdb p5_test
TEST_DATABASE_URL="postgresql+asyncpg://furkanilgen@localhost:5432/p5_test" .venv/bin/pytest
dropdb p5_test    # BAŞARISIZLIKTA BİLE
```

### 0.2 Migration ebeveyni varsayılmaz, DOĞRULANIR

```bash
.venv/bin/alembic heads
```

Çıktıdaki revizyon `down_revision` olur. Bugünkü head'in `f1b2c3d4e5a6` olduğu
**varsayılmaz** — komut koşulur.

### 0.3 Migration testinde `head` / `-1` KULLANILMAZ

`.venv/bin/alembic downgrade -1` her yeni migration'da **yanlış** revizyonu geri
alır. Bu tuzak iki kez yaşandı. Her zaman açık revizyon id'si:

```bash
.venv/bin/alembic upgrade <p5_rev>
.venv/bin/alembic downgrade <onceki_rev>
.venv/bin/alembic upgrade <p5_rev>
```

### 0.4 Postgres enum'ı tabloyla silinmez

`downgrade()` içinde tabloları düşürmek `contract_status` / `payment_period`
tiplerini **silmez**. `DROP TYPE` unutulursa ikinci `upgrade` patlar.

### 0.5 `openapi.json` gitignore'ludur

Commit **edilmez**; frontend'e elle kopyalanır.

### 0.6 TDD zorunlu — "KIRMIZI GÖR" atlanamaz

Test önce yazılır, **başarısız olduğu görülür**, sonra kod yazılır. Test ilk
koşuda yeşilse test yanlıştır → mutasyon denetimi yapılır (implementasyonda bir
satır bozulur, testin kırmızıya döndüğü doğrulanır, geri alınır).

### 0.7 Modül sayısı 17 → **18** olur

`boq` dilimindeki plan "17'de KALIR" diyordu; **bu dilim onu bilinçli olarak
büyütür** (spec K5). Modül sayısını veya izin satırı sayısını (8×17=136) sabitleyen
**tüm** testler 18 / 144'e taşınır. Sayıyı arayıp bulmak Task C2'nin işidir.

### 0.8 %100 mockup sadakati

Her alan mockup satır numarasıyla gerekçelidir. Mockup'ta olmayan alan **icat
edilmez**; spec §2.2'de kapsam dışı sayılan alanlar `pending_module` ile boş döner.

---

## 1. Dosya haritası

| Dosya | Sorumluluk | Task |
|---|---|---|
| `app/modules/contracts/__init__.py` | boş | C1 |
| `app/modules/contracts/models.py` | 5 tablo + `ContractStatus`, `PaymentPeriod` | C1 |
| `app/modules/projects/models.py` | `ProjectContract.status` eklenir | C1 |
| `app/modules/boq/models.py` | `BoqItem.contract_item_id` + kısmi indeks | C1 |
| `alembic/versions/<p5_rev>_p5_sozlesmeler.py` | tek revizyon (şema C1, izin verisi C2) | C1, C2 |
| `app/modules/roles/seed_data.py` | `MODULES` + `MATRIX` satırı | C2 |
| `app/modules/contracts/schemas.py` | Pydantic okuma/yazma | C3 |
| `app/modules/contracts/guards.py` | kurallar + hata metinleri (TEK kopya) | C4 |
| `app/modules/contracts/repository.py` | sorgular | C5 |
| `app/modules/contracts/service.py` | işveren sözleşmesi + birleşik liste | C5, C6 |
| `app/modules/contracts/distribution.py` | poz dağılımı okuma + toplu yazma | C7, C8 |
| `app/modules/contracts/subcontractors.py` | kartoteks servisi | C9 |
| `app/modules/contracts/subcontracts.py` | taşeron sözleşmesi servisi | C10, C11 |
| `app/modules/contracts/router.py` | tüm uçlar | C5–C12 |
| `app/main.py` | router kaydı | C5 |
| `app/modules/sites/guards.py` | `SITE_HAS_CONTRACTS` | C12 |
| `app/modules/audit/messages.py` | 7 mesaj ailesi | C13 |
| `tests/contracts/…` | test paketi | C1–C14 |

---

## 2. Task listesi

### Task C1 — Modeller + migration (şema) ⚠️ RİSKLİ

**Dosyalar:**
- Oluştur: `app/modules/contracts/__init__.py`, `app/modules/contracts/models.py`
- Değiştir: `app/modules/projects/models.py` (`ProjectContract`), `app/modules/boq/models.py` (`BoqItem`)
- Oluştur: `alembic/versions/<p5_rev>_p5_sozlesmeler.py`
- Test: `tests/contracts/test_models_migration.py`

**Arayüzler:**
- Üretir: `ContractStatus` (`active|completed|on_hold`), `PaymentPeriod`
  (`monthly|biweekly|on_completion`), `EmployerContractGroup`, `EmployerContractItem`,
  `Subcontractor`, `SubcontractorContract`, `SubcontractorContractItem`;
  `ProjectContract.status`; `BoqItem.contract_item_id`

Spec §3.1–§3.6 ve §9 okunur.

- [ ] **Adım 1: Testi yaz** — `tests/contracts/test_models_migration.py`

```python
import pytest
from sqlalchemy import inspect, text

from app.modules.contracts.models import (
    ContractStatus,
    EmployerContractGroup,
    EmployerContractItem,
    PaymentPeriod,
    Subcontractor,
    SubcontractorContract,
    SubcontractorContractItem,
)


def test_contract_status_uyeleri():
    assert [s.value for s in ContractStatus] == ["active", "completed", "on_hold"]


def test_payment_period_uyeleri():
    assert [p.value for p in PaymentPeriod] == ["monthly", "biweekly", "on_completion"]


@pytest.mark.asyncio
async def test_yeni_tablolar_olusur(db_session):
    tablolar = await db_session.run_sync(lambda s: inspect(s.bind).get_table_names())
    for ad in (
        "subcontractors",
        "employer_contract_groups",
        "employer_contract_items",
        "subcontractor_contracts",
        "subcontractor_contract_items",
    ):
        assert ad in tablolar


@pytest.mark.asyncio
async def test_boq_item_contract_item_id_nullable(db_session):
    sonuc = await db_session.execute(
        text(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name='boq_items' AND column_name='contract_item_id'"
        )
    )
    assert sonuc.scalar_one() == "YES"


@pytest.mark.asyncio
async def test_project_contract_status_varsayilani(db_session):
    sonuc = await db_session.execute(
        text(
            "SELECT column_default, is_nullable FROM information_schema.columns "
            "WHERE table_name='project_contracts' AND column_name='status'"
        )
    )
    varsayilan, nullable = sonuc.one()
    assert nullable == "NO"
    assert "active" in varsayilan
```

`db_session` fixture'ının adı `tests/conftest.py`'den **doğrulanır**; farklıysa
mevcut ad kullanılır (uydurma fixture adı yazılmaz).

- [ ] **Adım 2: Testi koştur, KIRMIZI gör**

```bash
createdb p5_test
TEST_DATABASE_URL="postgresql+asyncpg://furkanilgen@localhost:5432/p5_test" \
  .venv/bin/pytest tests/contracts/test_models_migration.py -v
```

Beklenen: `ModuleNotFoundError: app.modules.contracts.models`

- [ ] **Adım 3: `app/modules/contracts/models.py`'yi yaz**

Spec §3.2, §3.4, §3.5, §3.6 tablolarındaki **her kolon** yazılır. İskelet:

```python
import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean, CheckConstraint, Date, DateTime, Enum, ForeignKey, Index,
    Integer, Numeric, String, Text, UniqueConstraint, func, text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class ContractStatus(str, enum.Enum):
    """Sözleşme durumu — SZL 61/71/91 rozetleri."""

    active = "active"
    completed = "completed"
    on_hold = "on_hold"


class PaymentPeriod(str, enum.Enum):
    """Hakediş periyodu — FORM 101 açılır sırası."""

    monthly = "monthly"
    biweekly = "biweekly"
    on_completion = "on_completion"


class EmployerContractGroup(Base):
    """İşveren sözleşmesi poz grubu (POZ 90/125/140). BoqGroup deseninin birebiri:
    baştaki 'A —' harfi SAKLANMAZ, sıra sort_order'dan türer."""

    __tablename__ = "employer_contract_groups"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("project_contracts.project_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    items: Mapped[list["EmployerContractItem"]] = relationship(
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="EmployerContractItem.sort_order, EmployerContractItem.code",
    )
```

`EmployerContractItem` (spec §3.2 tablosu; `UniqueConstraint("project_id", "code")`,
`CHECK quantity > 0`, `CHECK unit_price >= 0`), `Subcontractor` (§3.4; kısmi
benzersiz `tax_number` indeksi — `Employer` modelindeki `postgresql_where` deseni),
`SubcontractorContract` (§3.5; iki CHECK), `SubcontractorContractItem` (§3.6;
`CHECK unit_price IS NULL OR unit_price >= 0`) aynı titizlikte yazılır.
**`lazy="selectin"` zorunludur** — async oturumda tembel yükleme `MissingGreenlet` atar.

`app/modules/projects/models.py`, `ProjectContract` sınıfına:

```python
    status: Mapped[ContractStatus] = mapped_column(
        Enum(ContractStatus, name="contract_status"),
        nullable=False,
        default=ContractStatus.active,
        server_default="active",
    )
```

(import: `from app.modules.contracts.models import ContractStatus` — bağımlılık yönü
`projects` → `contracts`, spec §11.)

`app/modules/boq/models.py`, `BoqItem`'a:

```python
    # Spec §3.3 ONAYLI SAPMA (kalıcı karar 1'den): sözleşme kalemine bağ. SET NULL
    # çünkü BOQ satırı sahadaki gerçekleşen işin kaydıdır; sözleşme kalemi silinince
    # satır yok olmaz, yalnız bağ kopar.
    contract_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employer_contract_items.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
```

ve `__table_args__`'a:

```python
        Index(
            "uq_boq_items_contract_item_site",
            "contract_item_id",
            "site_id",
            unique=True,
            postgresql_where=text("contract_item_id IS NOT NULL"),
        ),
```

- [ ] **Adım 4: Migration'ı yaz**

```bash
.venv/bin/alembic heads      # ÇIKTI down_revision OLUR — varsayma
.venv/bin/alembic revision -m "p5_sozlesmeler"
```

`upgrade()` sırası spec §9/1-6 (izin verisi **C2'de** eklenecek):
enum'lar → `project_contracts.status` → `subcontractors` →
`employer_contract_groups` → `employer_contract_items` →
`boq_items.contract_item_id` + kısmi indeks → `subcontractor_contracts` →
`subcontractor_contract_items`.

`downgrade()` ters sırada **ve sonunda**:

```python
    op.execute("DROP TYPE IF EXISTS payment_period")
    op.execute("DROP TYPE IF EXISTS contract_status")
```

- [ ] **Adım 5: Testleri koştur, YEŞİL gör + migration turu**

```bash
TEST_DATABASE_URL="postgresql+asyncpg://furkanilgen@localhost:5432/p5_test" \
  .venv/bin/pytest tests/contracts/test_models_migration.py -v
.venv/bin/alembic upgrade <p5_rev> && .venv/bin/alembic downgrade <onceki_rev> \
  && .venv/bin/alembic upgrade <p5_rev>
dropdb p5_test
```

İkinci `upgrade`'in patlaması = `DROP TYPE` unutulmuş (§0.4).

- [ ] **Adım 6: Commit**

```bash
.venv/bin/ruff check app tests && .venv/bin/ruff format --check app tests
git add app/modules/contracts app/modules/projects/models.py app/modules/boq/models.py \
  alembic/versions tests/contracts
git commit -m "feat(contracts): P5 şema — 5 tablo, ProjectContract.status, boq contract_item_id"
```

---

### Task C2 — `contracts` izin modülü (18.) ⚠️ RİSKLİ

**Dosyalar:**
- Değiştir: `app/modules/roles/seed_data.py`, `alembic/versions/<p5_rev>_p5_sozlesmeler.py`
- Değiştir: modül/izin sayısını sabitleyen **tüm** testler
- Test: `tests/contracts/test_contracts_permission.py`

**Arayüzler:**
- Üretir: `"contracts"` modül anahtarı — C5'ten sonraki tüm task'lar
  `require_permission("contracts", …)` ile ona bağlanır.

Spec §5 okunur.

- [ ] **Adım 1: Sayıyı sabitleyen testleri BUL**

```bash
grep -rn "17\|136\|len(MODULES)\|len(MATRIX)" tests/ app/modules/roles/ | grep -v __pycache__
```

Çıkan her yer listelenir. **Tahmin edilmez, aranır.**

- [ ] **Adım 2: Testi yaz** — `tests/contracts/test_contracts_permission.py`

```python
import pytest

from app.core.access import AccessLevel, Scope
from app.modules.roles.seed_data import MATRIX, MODULES, ROLE_ORDER


def test_contracts_modulu_matriste_var():
    anahtarlar = [m["key"] for m in MODULES]
    assert "contracts" in anahtarlar
    assert len(MODULES) == 18


def test_contracts_satiri_dogru_rollere_kapali():
    hucreler = dict(zip(ROLE_ORDER, MATRIX["contracts"], strict=True))
    # Bu modülün var oluş sebebi: projects=_LIM olan roller taşeron
    # birim fiyatlarını GÖRMEMELİ (spec §5).
    for rol in ("site_chief", "field_engineer", "hr_manager", "procurement"):
        assert hucreler[rol][0] == AccessLevel.none
    assert hucreler["system_admin"][0] == AccessLevel.admin
    assert hucreler["patron"][0] == AccessLevel.full
    assert hucreler["project_manager"][0] == AccessLevel.full
    assert hucreler["accounting"] == (AccessLevel.view, Scope.finance)


@pytest.mark.asyncio
async def test_seed_144_izin_satiri_uretir(db_session):
    from sqlalchemy import func, select

    from app.modules.roles.models import RolePermission

    toplam = await db_session.scalar(select(func.count()).select_from(RolePermission))
    assert toplam == 8 * 18
```

- [ ] **Adım 3: Koştur, KIRMIZI gör**

Beklenen: `KeyError: 'contracts'` ve `assert 17 == 18`.

- [ ] **Adım 4: `seed_data.py`'yi güncelle**

`MODULES` sonuna:

```python
    # spec §5 (P5, 2026-07-30): AYRI modül. Gerekçe: projects=_LIM olan roller
    # (şef, saha, İK) taşeron birim fiyatlarını görmemeli. `Ayarlar - İzin Matrisi`
    # mockup'ında bu satır YOK — `boq`'daki gibi BİLİNÇLİ SAPMA, geri alınmaz.
    # sort_order 18: mevcut modüllerin sırası KAYDIRILMAZ (boq da 17 ile sona eklendi).
    {"key": "contracts", "name": "Sözleşmeler", "group": ModuleGroup.MALI, "sort_order": 18},
```

`MATRIX` sonuna:

```python
    "contracts": [_A, _F, _N, _N, _N, _FIN, _F, _N],
```

`seed_reference_data` docstring'indeki "16 modül ve 128 izin satırı" ifadesi
**18 modül ve 144 izin satırı** olarak düzeltilir (zaten bayattı).

- [ ] **Adım 5: Migration'a izin bloğunu ekle**

C1'de yazılan **aynı** revizyon dosyasına, `b8a66b6fd431_boq_izin_modulu.py`
deseninde: `modules`'e `contracts` satırı + her rol için `role_permissions` satırı.
`downgrade()`'de ters yönde silinir. **İkinci revizyon açılmaz** (spec §9).

- [ ] **Adım 6: Adım 1'de bulunan tüm testleri 18 / 144'e taşı**

- [ ] **Adım 7: Tam test koşusu — YEŞİL**

```bash
createdb p5_test
TEST_DATABASE_URL="postgresql+asyncpg://furkanilgen@localhost:5432/p5_test" .venv/bin/pytest
dropdb p5_test
```

- [ ] **Adım 8: Commit**

```bash
git add app/modules/roles/seed_data.py alembic/versions tests/
git commit -m "feat(contracts): contracts izin modülü (18.) + matris satırı"
```

---

### Task C3 — Pydantic şemaları

**Dosyalar:** Oluştur `app/modules/contracts/schemas.py` · Test `tests/contracts/test_schemas.py`

**Arayüzler:**
- Üretir: `ContractType` (`Literal["employer","subcontractor"]`),
  `ContractSummary`, `ContractListItem`, `ContractListResponse`,
  `EmployerContractDetail`, `EmployerContractGroupCreate/Update`,
  `EmployerContractItemCreate/Update`, `EmployerContractItemResponse`,
  `EmployerContractItemsResponse`, `ContractDistributionResponse`,
  `ContractAllocationInput`, `ContractDistributionSave`,
  `SubcontractorCreate/Update/Response/ListResponse`,
  `SubcontractorContractCreate/Update/Detail`,
  `SubcontractorContractItemCreate/Update/Response`

Spec §10 okunur.

- [ ] **Adım 1: Testi yaz**

```python
import uuid

import pytest
from pydantic import ValidationError

from app.modules.contracts.schemas import (
    EmployerContractItemCreate,
    SubcontractorContractItemCreate,
)


def test_miktar_sifir_olamaz():
    with pytest.raises(ValidationError):
        EmployerContractItemCreate(
            group_id=uuid.uuid4(),
            code="03.001",
            description="Beton",
            unit="m³",
            quantity=0,
            unit_price=100,
        )


def test_taseron_kalemi_fiyatsiz_kabul_edilir():
    kalem = SubcontractorContractItemCreate(
        code="03.001", description="Beton", unit="m³", quantity=10, unit_price=None
    )
    assert kalem.unit_price is None


def test_taseron_kalemi_negatif_fiyat_reddedilir():
    with pytest.raises(ValidationError):
        SubcontractorContractItemCreate(
            code="03.001", description="Beton", unit="m³", quantity=10, unit_price=-1
        )
```

- [ ] **Adım 2: Koştur, KIRMIZI gör** — `ModuleNotFoundError`

- [ ] **Adım 3: `schemas.py`'yi yaz**

Alan sınırları modeldekilerle **birebir** (`code` `max_length=50`,
`name`/`subcontractor_name` 200, `unit` 50, `phone` 30, `email` 255,
`contract_no` 100, `category`/`work_category` 100) — frontend `maxLength`'i buradan okur.

```python
class SubcontractorContractItemCreate(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    description: str = Field(min_length=1)
    unit: str = Field(min_length=1, max_length=50)
    quantity: Decimal = Field(gt=0)
    # NULL bilinçli (spec §3.6): işverenden yüklenen kalem fiyatsız gelir.
    unit_price: Decimal | None = Field(default=None, ge=0)
    sort_order: int = 0
```

Kapsam dışı alanlar yanıt şemalarında **açıkça** yer alır (spec §2.2):

```python
class SubcontractorContractDetail(BaseModel):
    ...
    progress_payment_summary: None = None
    documents: None = None
    pending_modules: list[str] = ["progress_payments", "documents"]
```

- [ ] **Adım 4: Koştur, YEŞİL gör**
- [ ] **Adım 5: Commit** — `feat(contracts): Pydantic şemaları`

---

### Task C4 — `guards.py`: kurallar + hata metinleri

**Dosyalar:** Oluştur `app/modules/contracts/guards.py` · Test `tests/contracts/test_guards.py`

**Arayüzler:**
- Üretir: sabit metinler (`PROJECT_REQUIRED`, `SUBCONTRACTOR_REQUIRED`,
  `CATEGORY_REQUIRED`, `CONTRACT_NO_REQUIRED`, `SIGNATURE_DATE_REQUIRED`,
  `DATES_REQUIRED`, `ITEM_PRICES_REQUIRED`, `END_BEFORE_START`,
  `SITE_PROJECT_MISMATCH`, `DISTRIBUTION_EXCEEDS`, `CONTRACT_MISSING`,
  `SUBCONTRACTOR_MISSING`, `ITEM_MISSING`, `GROUP_MISSING`, `GROUP_HAS_ITEMS`,
  `SUBCONTRACTOR_HAS_CONTRACTS`, `NO_EMPLOYER_ITEMS`) ve
  `validate_subcontract(data, *, is_draft) -> None`

Spec §4 okunur. `sites/guards.py` docstring'i **örnek alınır**.

- [ ] **Adım 1: Testi yaz**

```python
from datetime import date

import pytest

from app.core.errors import SiteValidationError
from app.modules.contracts import guards


class _Sozlesme:
    def __init__(self, **kw):
        self.project_id = kw.get("project_id", "p")
        self.subcontractor_id = kw.get("subcontractor_id", "s")
        self.work_category = kw.get("work_category", "Betonarme")
        self.contract_no = kw.get("contract_no", "TSZ-2026-004")
        self.signature_date = kw.get("signature_date", date(2026, 1, 1))
        self.start_date = kw.get("start_date", date(2026, 1, 5))
        self.end_date = kw.get("end_date", date(2026, 12, 31))
        self.items = kw.get("items", [])


def test_taslak_eksik_alanlari_kabul_eder():
    guards.validate_subcontract(_Sozlesme(subcontractor_id=None, contract_no=None), is_draft=True)


def test_yayinda_taseron_zorunlu():
    with pytest.raises(SiteValidationError) as hata:
        guards.validate_subcontract(_Sozlesme(subcontractor_id=None), is_draft=False)
    assert str(hata.value) == guards.SUBCONTRACTOR_REQUIRED


def test_bitis_baslangictan_once_olamaz_taslakta_bile():
    with pytest.raises(SiteValidationError) as hata:
        guards.validate_subcontract(
            _Sozlesme(start_date=date(2026, 5, 1), end_date=date(2026, 4, 1)), is_draft=True
        )
    assert str(hata.value) == guards.END_BEFORE_START


def test_santiye_zorunlu_degildir():
    """K4 onaylı sapma: FORM 59'daki * uygulanmaz."""
    guards.validate_subcontract(_Sozlesme(), is_draft=False)
```

- [ ] **Adım 2: Koştur, KIRMIZI gör**

- [ ] **Adım 3: `guards.py`'yi yaz**

Modül docstring'i `sites/guards.py`'ninki gibi **tek cümlelik kuralı** ve PATCH'te
neden koşmadığını açıklar. `SiteValidationError` yeniden kullanılır (yeni istisna
sınıfı açılmaz).

```python
def validate_subcontract(data, *, is_draft: bool) -> None:
    # --- Tutarlılık: HER ZAMAN ---
    if data.start_date and data.end_date and data.end_date < data.start_date:
        raise SiteValidationError(END_BEFORE_START)

    # --- Zorunluluk: YALNIZ taslak-dışında ---
    if is_draft:
        return
    if data.project_id is None:
        raise SiteValidationError(PROJECT_REQUIRED)
    if data.subcontractor_id is None:
        raise SiteValidationError(SUBCONTRACTOR_REQUIRED)
    if not (data.work_category or "").strip():
        raise SiteValidationError(CATEGORY_REQUIRED)
    if not (data.contract_no or "").strip():
        raise SiteValidationError(CONTRACT_NO_REQUIRED)
    if data.signature_date is None:
        raise SiteValidationError(SIGNATURE_DATE_REQUIRED)
    if data.start_date is None or data.end_date is None:
        raise SiteValidationError(DATES_REQUIRED)
    # ŞANTİYE BİLİNÇLİ OLARAK YOK — K4 onaylı sapma (FORM 59'daki *).
    if data.items and any(k.unit_price is None for k in data.items):
        raise SiteValidationError(ITEM_PRICES_REQUIRED)
```

- [ ] **Adım 4: Koştur, YEŞİL gör**
- [ ] **Adım 5: Commit** — `feat(contracts): guards — taslak/yayın kuralları ve hata metinleri`

---

### Task C5 — Repository + birleşik liste ucu + router kaydı

**Dosyalar:** Oluştur `repository.py`, `service.py`, `router.py` · Değiştir `app/main.py`
· Test `tests/contracts/test_contract_list.py`

**Arayüzler:**
- Tüketir: C3 şemaları, C2 modül anahtarı
- Üretir: `contracts_router`;
  `service.list_contracts(session, actor, contract_type, project_id, status, q) -> ContractListResponse`;
  `_VIEW` / `_FULL` / `_ADMIN` kapı sabitleri (C6–C12 bunları import eder)

Spec §6.1 okunur.

- [ ] **Adım 1: Testi yaz**

```python
@pytest.mark.asyncio
async def test_isveren_listesi_ozet_dondurur(client, admin_headers, ornek_proje):
    yanit = await client.get("/contracts?type=employer", headers=admin_headers)
    assert yanit.status_code == 200
    govde = yanit.json()
    assert set(govde["summary"]) >= {
        "total_amount", "active_count", "progress_payment_total", "expiring_this_month_count",
    }
    assert govde["summary"]["progress_payment_total"] is None


@pytest.mark.asyncio
async def test_tip_zorunlu(client, admin_headers):
    assert (await client.get("/contracts", headers=admin_headers)).status_code == 422


@pytest.mark.asyncio
async def test_yetkisiz_rol_403(client, site_chief_headers):
    yanit = await client.get("/contracts?type=employer", headers=site_chief_headers)
    assert yanit.status_code == 403


@pytest.mark.asyncio
async def test_gorunmeyen_proje_listede_yok(client, kisitli_headers, gorunmeyen_proje):
    govde = (await client.get("/contracts?type=employer", headers=kisitli_headers)).json()
    assert all(k["id"] != str(gorunmeyen_proje) for k in govde["items"])
```

Fixture adları `tests/conftest.py`'den doğrulanır; olmayan fixture uydurulmaz.

- [ ] **Adım 2: Koştur, KIRMIZI gör** — 404 (router yok)

- [ ] **Adım 3: Uygula**

```python
# router.py
router = APIRouter(tags=["contracts"], responses=COMMON_ERROR_RESPONSES)

_VIEW = require_permission("contracts", AccessLevel.view)
_FULL = require_permission("contracts", AccessLevel.full)
# Silme YALNIZ sistem yöneticisinde (kalıcı karar 2): full silmeyi KAPSAMAZ.
_ADMIN = require_permission("contracts", AccessLevel.admin)


@router.get("/contracts", response_model=ContractListResponse, dependencies=[_VIEW])
async def list_contracts_endpoint(
    contract_type: Annotated[ContractType, Query(alias="type")],
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    project_id: uuid.UUID | None = None,
    status_filter: ContractStatus | None = Query(default=None, alias="status"),
    q: str | None = None,
) -> ContractListResponse:
    return await service.list_contracts(session, user, contract_type, project_id, status_filter, q)
```

`service.list_contracts` **`projects.service.visible_projects`** ile başlar; taşeron
tarafında bedel `Σ(quantity × unit_price)` olarak hesaplanır (`unit_price IS NULL`
→ 0 katkı). `expiring_this_month_count`: `status == active` ve bitiş tarihi içinde
bulunulan ay olan sözleşmeler. `app/main.py`'ye `app.include_router(contracts_router)`.

- [ ] **Adım 4: Koştur, YEŞİL gör**
- [ ] **Adım 5: Commit** — `feat(contracts): birleşik sözleşme listesi ucu`

---

### Task C6 — İşveren sözleşmesi okuma + grup/kalem yazma uçları

**Dosyalar:** Değiştir `service.py`, `router.py` · Test `tests/contracts/test_employer_items.py`

**Arayüzler:**
- Tüketir: C5 kapıları
- Üretir: `GET /projects/{id}/contract`, `GET /projects/{id}/contract/items`,
  `POST /projects/{id}/contract/groups`, `PATCH /contracts/employer/groups/{id}`,
  `POST /projects/{id}/contract/items`, `PATCH /contracts/employer/items/{id}`

Spec §6.2 okunur. **Sözleşmenin kendi alanları için yazma ucu AÇILMAZ** — o alanlar
`PATCH /projects/{id}` nested `contract`'ında kalır.

- [ ] **Adım 1: Testi yaz**

```python
@pytest.mark.asyncio
async def test_avans_tutari_ve_kalem_toplami(client, admin_headers, sozlesmeli_proje):
    govde = (await client.get(
        f"/projects/{sozlesmeli_proje}/contract", headers=admin_headers
    )).json()
    # amount=11_200_000, advance_pct=20 (E14 85)
    assert Decimal(govde["advance_amount"]) == Decimal("2240000")
    assert "items_total" in govde and "items_total_diff" in govde


@pytest.mark.asyncio
async def test_ayni_poz_kodu_409(client, admin_headers, sozlesmeli_proje, grup):
    govde = {"group_id": str(grup), "code": "03.001", "description": "Beton",
             "unit": "m³", "quantity": 100, "unit_price": 1850}
    ilk = await client.post(
        f"/projects/{sozlesmeli_proje}/contract/items", json=govde, headers=admin_headers
    )
    assert ilk.status_code == 201
    ikinci = await client.post(
        f"/projects/{sozlesmeli_proje}/contract/items", json=govde, headers=admin_headers
    )
    assert ikinci.status_code == 409


@pytest.mark.asyncio
async def test_gorunmeyen_proje_ile_olmayan_proje_ayni_yanit(
    client, kisitli_headers, gorunmeyen_proje
):
    gercek = await client.get(f"/projects/{gorunmeyen_proje}/contract", headers=kisitli_headers)
    sahte = await client.get(f"/projects/{uuid.uuid4()}/contract", headers=kisitli_headers)
    assert gercek.status_code == sahte.status_code == 404
    assert gercek.json() == sahte.json()


@pytest.mark.asyncio
async def test_miktar_dagitilmis_toplamin_altina_inemez(
    client, admin_headers, dagitimli_proje, sozlesme_kalemi
):
    """200 Ton'un 200'ü dağıtılmışken miktar 150'ye indirilemez."""
    yanit = await client.patch(
        f"/contracts/employer/items/{sozlesme_kalemi}",
        json={"quantity": 150},
        headers=admin_headers,
    )
    assert yanit.status_code == 422
```

- [ ] **Adım 2: Koştur, KIRMIZI gör**
- [ ] **Adım 3: Uygula** — grup→sözleşme tutarlılığı servis korkuluğu; `DuplicateError` → 409
- [ ] **Adım 4: Koştur, YEŞİL gör**
- [ ] **Adım 5: Commit** — `feat(contracts): işveren sözleşmesi poz grup/kalem uçları`

---

### Task C7 — Poz dağılımı okuma ucu

**Dosyalar:** Oluştur `distribution.py` · Değiştir `router.py`
· Test `tests/contracts/test_distribution_read.py`

**Arayüzler:**
- Üretir: `GET /projects/{id}/contract/distribution`;
  `distribution.build_distribution(session, actor, project_id) -> ContractDistributionResponse`

Spec §6.3 (GET kısmı) okunur.

- [ ] **Adım 1: Testi yaz**

```python
@pytest.mark.asyncio
async def test_kalan_ve_dagitilmamis(client, admin_headers, dagitimli_proje):
    yanit = await client.get(
        f"/projects/{dagitimli_proje}/contract/distribution", headers=admin_headers
    )
    govde = yanit.json()
    kalem = govde["groups"][0]["items"][0]        # 200 Ton, A:120 B:80
    assert Decimal(kalem["remaining_quantity"]) == Decimal("0")
    assert govde["undistributed_item_count"] == 1
    assert "İnce Sıva (Alçı)" in govde["undistributed_item_names"]
    assert govde["distributed_item_count"] == 1
    assert govde["total_item_count"] == 2


@pytest.mark.asyncio
async def test_santiye_ozeti_bedeli(client, admin_headers, dagitimli_proje, santiye):
    govde = (await client.get(
        f"/projects/{dagitimli_proje}/contract/distribution", headers=admin_headers
    )).json()
    ozet = next(o for o in govde["site_summaries"] if o["site_id"] == str(santiye))
    # 120 Ton × ₺21.500
    assert Decimal(ozet["total_amount"]) == Decimal("2580000")
```

- [ ] **Adım 2: Koştur, KIRMIZI gör**
- [ ] **Adım 3: Uygula** — kalemler ve bağlı BOQ satırları tek sorguda; N+1 yok
- [ ] **Adım 4: Koştur, YEŞİL gör**
- [ ] **Adım 5: Commit** — `feat(contracts): poz dağılımı okuma ucu`

---

### Task C8 — Poz dağılımı toplu yazma ⚠️ EN RİSKLİ

**Dosyalar:** Değiştir `distribution.py`, `router.py`
· Test `tests/contracts/test_distribution_write.py`

**Arayüzler:**
- Üretir: `PUT /projects/{id}/contract/distribution`;
  `distribution.save_distribution(session, actor, project_id, data) -> ContractDistributionResponse`

Spec §6.3 (PUT kısmı, 4 madde) okunur. **Dört davranışın hepsi test edilir.**

- [ ] **Adım 1: Testi yaz**

```python
@pytest.mark.asyncio
async def test_yeni_kota_boq_satiri_ve_grubu_olusturur(
    client, admin_headers, sozlesmeli_proje, santiye, sozlesme_kalemi
):
    yanit = await client.put(
        f"/projects/{sozlesmeli_proje}/contract/distribution",
        json={"allocations": [
            {"contract_item_id": str(sozlesme_kalemi), "site_id": str(santiye), "quantity": 120}
        ]},
        headers=admin_headers,
    )
    assert yanit.status_code == 200
    boq = (await client.get(f"/sites/{santiye}/boq", headers=admin_headers)).json()
    assert boq["groups"][0]["name"] == "A — Betonarme İşleri"   # grup otomatik açıldı
    kalem = boq["groups"][0]["items"][0]
    assert Decimal(kalem["quantity"]) == Decimal("120")
    assert Decimal(kalem["unit_price"]) == Decimal("21500")     # sözleşmeden kopyalandı


@pytest.mark.asyncio
async def test_asim_422_ve_hicbir_sey_yazilmaz(
    client, admin_headers, sozlesmeli_proje, santiye, santiye2, sozlesme_kalemi
):
    """200 Ton'luk kaleme 120 + 100 dağıtılamaz; ilk satır da yazılmamalıdır."""
    yanit = await client.put(
        f"/projects/{sozlesmeli_proje}/contract/distribution",
        json={"allocations": [
            {"contract_item_id": str(sozlesme_kalemi), "site_id": str(santiye), "quantity": 120},
            {"contract_item_id": str(sozlesme_kalemi), "site_id": str(santiye2), "quantity": 100},
        ]},
        headers=admin_headers,
    )
    assert yanit.status_code == 422
    boq = (await client.get(f"/sites/{santiye}/boq", headers=admin_headers)).json()
    assert boq["groups"] == []          # ATOMİKLİK


@pytest.mark.asyncio
async def test_kota_kaldirilinca_boq_satiri_silinmez_bag_kopar(
    client, admin_headers, dagitimli_proje, santiye, sozlesme_kalemi
):
    await client.put(
        f"/projects/{dagitimli_proje}/contract/distribution",
        json={"allocations": [
            {"contract_item_id": str(sozlesme_kalemi), "site_id": str(santiye), "quantity": None}
        ]},
        headers=admin_headers,
    )
    boq = (await client.get(f"/sites/{santiye}/boq", headers=admin_headers)).json()
    assert len(boq["groups"][0]["items"]) == 1            # satır DURUYOR
    assert boq["groups"][0]["items"][0]["contract_item_id"] is None


@pytest.mark.asyncio
async def test_baska_projenin_santiyesine_kota_422(
    client, admin_headers, sozlesmeli_proje, baska_projenin_santiyesi, sozlesme_kalemi
):
    yanit = await client.put(
        f"/projects/{sozlesmeli_proje}/contract/distribution",
        json={"allocations": [{
            "contract_item_id": str(sozlesme_kalemi),
            "site_id": str(baska_projenin_santiyesi),
            "quantity": 10,
        }]},
        headers=admin_headers,
    )
    assert yanit.status_code == 422


@pytest.mark.asyncio
async def test_ayni_gruba_iki_kalem_tek_boq_grubu_acar(
    client, admin_headers, sozlesmeli_proje, santiye, iki_kalem_ayni_grup
):
    kalem_a, kalem_b = iki_kalem_ayni_grup
    await client.put(
        f"/projects/{sozlesmeli_proje}/contract/distribution",
        json={"allocations": [
            {"contract_item_id": str(kalem_a), "site_id": str(santiye), "quantity": 10},
            {"contract_item_id": str(kalem_b), "site_id": str(santiye), "quantity": 20},
        ]},
        headers=admin_headers,
    )
    boq = (await client.get(f"/sites/{santiye}/boq", headers=admin_headers)).json()
    assert len(boq["groups"]) == 1
    assert len(boq["groups"][0]["items"]) == 2
```

- [ ] **Adım 2: Koştur, KIRMIZI gör**

- [ ] **Adım 3: Uygula**

Sıra **önemlidir**: önce tüm doğrulamalar (şantiye-proje eşleşmesi, kalem-proje
eşleşmesi, aşım toplamı), **sonra** yazma. Doğrulama yazmanın arasına serpiştirilirse
`test_asim_422_ve_hicbir_sey_yazilmaz` kırmızı kalır. Hata `HTTPException`'a
dönüşünce oturumun rollback edildiği `app/core/exception_handlers.py`'den
**doğrulanır**, varsayılmaz.

Grup çözümü: hedef şantiyede sözleşme grubuyla **aynı adlı** `BoqGroup` aranır;
yoksa aynı adla açılır. Aynı çağrı içinde iki kalem aynı gruba düşerse **tek** grup
açılır — yerel önbellek `dict[tuple[site_id, group_name], BoqGroup]`.

- [ ] **Adım 4: Koştur, YEŞİL gör** + mutasyon denetimi (aşım kontrolünü kaldır,
  `test_asim…`'in kırmızıya döndüğünü gör, geri al)
- [ ] **Adım 5: Commit** — `feat(contracts): poz dağılımı toplu yazma ucu`

---

### Task C9 — Taşeron kartoteksi uçları

**Dosyalar:** Oluştur `subcontractors.py` · Değiştir `router.py`
· Test `tests/contracts/test_subcontractors.py`

**Arayüzler:**
- Üretir: `GET/POST /subcontractors`, `PATCH /subcontractors/{id}`

Spec §6.4 okunur. `employers_router` deseninin birebiri.

- [ ] **Adım 1: Testi yaz**

```python
@pytest.mark.asyncio
async def test_ayni_vkn_409(client, admin_headers):
    govde = {"name": "Akın İnşaat", "tax_number": "1234567890"}
    ilk = await client.post("/subcontractors", json=govde, headers=admin_headers)
    assert ilk.status_code == 201
    ikinci = await client.post(
        "/subcontractors", json={**govde, "name": "Başka"}, headers=admin_headers
    )
    assert ikinci.status_code == 409


@pytest.mark.asyncio
async def test_vkn_siz_iki_kayit_serbest(client, admin_headers):
    for ad in ("A Ltd", "B Ltd"):
        yanit = await client.post("/subcontractors", json={"name": ad}, headers=admin_headers)
        assert yanit.status_code == 201


@pytest.mark.asyncio
async def test_listede_olmayan_kategori_kabul_edilir(client, admin_headers):
    """Spec §3.4: sunucu kategori listesini ZORLAMAZ."""
    yanit = await client.post(
        "/subcontractors", json={"name": "X", "category": "Peyzaj"}, headers=admin_headers
    )
    assert yanit.status_code == 201


@pytest.mark.asyncio
async def test_active_only_suzgeci(client, admin_headers, pasif_taseron):
    govde = (await client.get("/subcontractors?active_only=true", headers=admin_headers)).json()
    assert all(t["id"] != str(pasif_taseron) for t in govde["items"])
```

- [ ] **Adım 2: Koştur, KIRMIZI gör**
- [ ] **Adım 3: Uygula**
- [ ] **Adım 4: Koştur, YEŞİL gör**
- [ ] **Adım 5: Commit** — `feat(contracts): taşeron kartoteksi uçları`

---

### Task C10 — Taşeron sözleşmesi POST / GET / PATCH

**Dosyalar:** Oluştur `subcontracts.py` · Değiştir `router.py`
· Test `tests/contracts/test_subcontracts.py`

**Arayüzler:**
- Tüketir: C4 `validate_subcontract`, C9 kartoteks
- Üretir: `POST /projects/{id}/subcontractor-contracts`,
  `GET/PATCH /subcontractor-contracts/{id}`

Spec §6.5, §4 okunur.

- [ ] **Adım 1: Testi yaz**

```python
@pytest.mark.asyncio
async def test_taslak_eksik_alanlarla_kaydedilir(client, admin_headers, proje):
    yanit = await client.post(
        f"/projects/{proje}/subcontractor-contracts",
        json={"is_draft": True, "contract_no": None},
        headers=admin_headers,
    )
    assert yanit.status_code == 201
    assert yanit.json()["is_draft"] is True


@pytest.mark.asyncio
async def test_yayinda_eksik_alan_422(client, admin_headers, proje):
    yanit = await client.post(
        f"/projects/{proje}/subcontractor-contracts",
        json={"is_draft": False, "contract_no": None},
        headers=admin_headers,
    )
    assert yanit.status_code == 422


@pytest.mark.asyncio
async def test_santiyesiz_sozlesme_gecerli(client, admin_headers, proje, taseron):
    """K4: site_id boşsa sözleşme proje genelidir."""
    yanit = await client.post(
        f"/projects/{proje}/subcontractor-contracts",
        json={
            "is_draft": False, "subcontractor_id": str(taseron), "work_category": "Betonarme",
            "contract_no": "TSZ-2026-004", "signature_date": "2026-01-01",
            "start_date": "2026-01-05", "end_date": "2026-12-31", "site_id": None,
            "items": [{"code": "03.001", "description": "Beton", "unit": "m³",
                       "quantity": 100, "unit_price": 1200}],
        },
        headers=admin_headers,
    )
    assert yanit.status_code == 201
    assert Decimal(yanit.json()["contract_total"]) == Decimal("120000")


@pytest.mark.asyncio
async def test_baska_projenin_santiyesi_422(client, admin_headers, proje, baska_santiye, taseron):
    yanit = await client.post(
        f"/projects/{proje}/subcontractor-contracts",
        json={"is_draft": True, "subcontractor_id": str(taseron), "site_id": str(baska_santiye)},
        headers=admin_headers,
    )
    assert yanit.status_code == 422
    assert yanit.json()["detail"] == guards.SITE_PROJECT_MISMATCH


@pytest.mark.asyncio
async def test_taseron_adi_anlik_goruntu_olarak_kopyalanir(client, admin_headers, proje, taseron):
    yanit = await client.post(
        f"/projects/{proje}/subcontractor-contracts",
        json={"is_draft": True, "subcontractor_id": str(taseron)},
        headers=admin_headers,
    )
    assert yanit.json()["subcontractor_name"] == "Akın İnşaat Ltd. Şti."


@pytest.mark.asyncio
async def test_taslaktan_yayina_gecis_kurallari_kosar(client, admin_headers, eksik_taslak):
    yanit = await client.patch(
        f"/subcontractor-contracts/{eksik_taslak}",
        json={"is_draft": False},
        headers=admin_headers,
    )
    assert yanit.status_code == 422
```

- [ ] **Adım 2: Koştur, KIRMIZI gör**
- [ ] **Adım 3: Uygula** — kalemler **iç içe ve atomik**; `created_by = actor.id`;
  `subcontractor_name` her yazmada kartotekten kopyalanır; PATCH'te
  `is_draft: true → false` geçişinde **birleşik kayıt** üzerinde tüm kurallar koşar
  (mevcut satır + patch), genel PATCH dalında zorunluluk kuralları **koşmaz**
- [ ] **Adım 4: Koştur, YEŞİL gör**
- [ ] **Adım 5: Commit** — `feat(contracts): taşeron sözleşmesi uçları`

---

### Task C11 — Taşeron kalem uçları + `load-from-employer`

**Dosyalar:** Değiştir `subcontracts.py`, `router.py`
· Test `tests/contracts/test_subcontract_items.py`

**Arayüzler:**
- Üretir: `POST /subcontractor-contracts/{id}/items`,
  `PATCH /subcontractor-contracts/items/{item_id}`,
  `POST /subcontractor-contracts/{id}/items/load-from-employer`

Spec §6.5 (`load-from-employer` paragrafı) okunur.

- [ ] **Adım 1: Testi yaz**

```python
@pytest.mark.asyncio
async def test_isverenden_yukleme_fiyatsiz_gelir(client, admin_headers, taseron_sozlesmesi):
    yanit = await client.post(
        f"/subcontractor-contracts/{taseron_sozlesmesi}/items/load-from-employer",
        headers=admin_headers,
    )
    assert yanit.status_code == 200
    assert yanit.json() == {"created_count": 3, "skipped_count": 0}
    detay = (await client.get(
        f"/subcontractor-contracts/{taseron_sozlesmesi}", headers=admin_headers
    )).json()
    assert all(k["unit_price"] is None for k in detay["items"])
    assert detay["items_missing_price"] == 3


@pytest.mark.asyncio
async def test_ikinci_yukleme_idempotent(client, admin_headers, taseron_sozlesmesi):
    await client.post(
        f"/subcontractor-contracts/{taseron_sozlesmesi}/items/load-from-employer",
        headers=admin_headers,
    )
    ikinci = await client.post(
        f"/subcontractor-contracts/{taseron_sozlesmesi}/items/load-from-employer",
        headers=admin_headers,
    )
    assert ikinci.json() == {"created_count": 0, "skipped_count": 3}


@pytest.mark.asyncio
async def test_isveren_sozlesmesi_pozsuzsa_422(client, admin_headers, pozsuz_sozlesme):
    yanit = await client.post(
        f"/subcontractor-contracts/{pozsuz_sozlesme}/items/load-from-employer",
        headers=admin_headers,
    )
    assert yanit.status_code == 422


@pytest.mark.asyncio
async def test_grup_isveren_kaleminden_turer(client, admin_headers, taseron_sozlesmesi):
    await client.post(
        f"/subcontractor-contracts/{taseron_sozlesmesi}/items/load-from-employer",
        headers=admin_headers,
    )
    detay = (await client.get(
        f"/subcontractor-contracts/{taseron_sozlesmesi}", headers=admin_headers
    )).json()
    assert detay["items"][0]["group"] == "A — Betonarme İşleri"


@pytest.mark.asyncio
async def test_bagsiz_kalem_grupsuz(client, admin_headers, taseron_sozlesmesi):
    await client.post(
        f"/subcontractor-contracts/{taseron_sozlesmesi}/items",
        json={"code": "99.001", "description": "Ek iş", "unit": "m²",
              "quantity": 5, "unit_price": 100},
        headers=admin_headers,
    )
    detay = (await client.get(
        f"/subcontractor-contracts/{taseron_sozlesmesi}", headers=admin_headers
    )).json()
    ek = next(k for k in detay["items"] if k["code"] == "99.001")
    assert ek["group"] is None
```

- [ ] **Adım 2: Koştur, KIRMIZI gör**
- [ ] **Adım 3: Uygula** — grup, `source_contract_item_id` → `group.name` üzerinden
  türer; bağsız kalemde `group: null`
- [ ] **Adım 4: Koştur, YEŞİL gör**
- [ ] **Adım 5: Commit** — `feat(contracts): taşeron kalem uçları + işverenden yükleme`

---

### Task C12 — DELETE uçları + silme korkulukları ⚠️ RİSKLİ

**Dosyalar:** Değiştir `router.py`, `subcontractors.py`, `subcontracts.py`,
`service.py`, `app/modules/sites/guards.py`, `app/modules/sites/service.py`,
`app/modules/sites/repository.py` · Test `tests/contracts/test_delete.py`

**Arayüzler:**
- Üretir: `DELETE /subcontractors/{id}`, `DELETE /subcontractor-contracts/{id}`,
  `DELETE /subcontractor-contracts/items/{id}`,
  `DELETE /contracts/employer/groups/{id}`, `DELETE /contracts/employer/items/{id}`;
  `sites.repository.site_has_contracts(session, site_id) -> bool`

Spec §7 okunur. **Hepsi `_ADMIN`.**

- [ ] **Adım 1: Testi yaz**

```python
@pytest.mark.asyncio
async def test_proje_muduru_silemez(client, project_manager_headers, taseron_sozlesmesi):
    """Kalıcı karar 2: full silmeyi KAPSAMAZ. Bu BEKLENEN davranış."""
    yanit = await client.delete(
        f"/subcontractor-contracts/{taseron_sozlesmesi}", headers=project_manager_headers
    )
    assert yanit.status_code == 403


@pytest.mark.asyncio
async def test_kendi_taslagini_silebilir(client, project_manager_headers, kendi_taslagi):
    yanit = await client.delete(
        f"/subcontractor-contracts/{kendi_taslagi}", headers=project_manager_headers
    )
    assert yanit.status_code == 204


@pytest.mark.asyncio
async def test_sozlesmesi_olan_taseron_silinemez(client, admin_headers, taseron, taseron_sozlesmesi):
    yanit = await client.delete(f"/subcontractors/{taseron}", headers=admin_headers)
    assert yanit.status_code == 409
    assert "önce sözleşmeleri silin" in yanit.json()["detail"]


@pytest.mark.asyncio
async def test_sozlesmeli_santiye_silinemez(client, admin_headers, santiye, santiye_sozlesmesi):
    yanit = await client.delete(f"/sites/{santiye}", headers=admin_headers)
    assert yanit.status_code == 409


@pytest.mark.asyncio
async def test_sozlesme_kalemi_silinince_boq_satiri_kalir(
    client, admin_headers, dagitimli_proje, santiye, sozlesme_kalemi
):
    silme = await client.delete(
        f"/contracts/employer/items/{sozlesme_kalemi}", headers=admin_headers
    )
    assert silme.status_code == 204
    boq = (await client.get(f"/sites/{santiye}/boq", headers=admin_headers)).json()
    assert len(boq["groups"][0]["items"]) == 1
    assert boq["groups"][0]["items"][0]["contract_item_id"] is None


@pytest.mark.asyncio
async def test_dolu_grup_silinemez(client, admin_headers, grup_dolu):
    yanit = await client.delete(f"/contracts/employer/groups/{grup_dolu}", headers=admin_headers)
    assert yanit.status_code == 409
```

- [ ] **Adım 2: Koştur, KIRMIZI gör**
- [ ] **Adım 3: Uygula** — `sites/guards.py`'ye `SITE_HAS_CONTRACTS` eklenir,
  `sites` silme yolundaki mevcut üç kontrolün (bölüm / iş kalemi / blok) yanına
  dördüncüsü konur (`sites.repository.site_has_contracts`). `can_delete`
  (`app/core/access.py`) taşeron sözleşmesi için kullanılır — `created_by` +
  `is_draft` alanları C1'de bu yüzden var.
- [ ] **Adım 4: Koştur, YEŞİL gör** — mevcut `sites` silme testleri de koşturulur
- [ ] **Adım 5: Commit** — `feat(contracts): DELETE uçları ve silme korkulukları`

---

### Task C13 — Denetim günlüğü

**Dosyalar:** Değiştir `app/modules/audit/messages.py`, `router.py`
· Test `tests/contracts/test_audit.py`

Spec §8 okunur.

- [ ] **Adım 1: Testi yaz**

```python
from sqlalchemy import func, select

from app.modules.audit.models import AuditLog


async def _audit_sayisi(db_session):
    return await db_session.scalar(select(func.count()).select_from(AuditLog))


@pytest.mark.asyncio
async def test_okuma_denetim_yazmaz(client, admin_headers, db_session, sozlesmeli_proje):
    once = await _audit_sayisi(db_session)
    await client.get(f"/projects/{sozlesmeli_proje}/contract", headers=admin_headers)
    assert await _audit_sayisi(db_session) == once


@pytest.mark.asyncio
async def test_dagilim_kaydi_denetime_yazar(
    client, admin_headers, db_session, sozlesmeli_proje, santiye, sozlesme_kalemi
):
    once = await _audit_sayisi(db_session)
    await client.put(
        f"/projects/{sozlesmeli_proje}/contract/distribution",
        json={"allocations": [
            {"contract_item_id": str(sozlesme_kalemi), "site_id": str(santiye), "quantity": 10}
        ]},
        headers=admin_headers,
    )
    assert await _audit_sayisi(db_session) == once + 1


@pytest.mark.asyncio
async def test_taseron_sozlesmesi_olusturma_denetime_yazar(
    client, admin_headers, db_session, proje, taseron
):
    once = await _audit_sayisi(db_session)
    await client.post(
        f"/projects/{proje}/subcontractor-contracts",
        json={"is_draft": True, "subcontractor_id": str(taseron)},
        headers=admin_headers,
    )
    assert await _audit_sayisi(db_session) == once + 1
```

`AuditLog` model adı `app/modules/audit/models.py`'den **doğrulanır**.

- [ ] **Adım 2: Koştur, KIRMIZI gör**
- [ ] **Adım 3: Uygula** — spec §8'deki 7 mesaj ailesi; mevcut adlandırma deseni;
  her yazma ucuna `record_audit` çağrısı
- [ ] **Adım 4: Koştur, YEŞİL gör**
- [ ] **Adım 5: Commit** — `feat(contracts): denetim günlüğü mesajları`

---

### Task C14 — `openapi.json` + tam kapı koşusu

**Dosyalar:** `openapi.json` (üretilir, **commit edilmez**)

- [ ] **Adım 1: Tam test koşusu**

```bash
createdb p5_test
TEST_DATABASE_URL="postgresql+asyncpg://furkanilgen@localhost:5432/p5_test" .venv/bin/pytest -q
dropdb p5_test
```

- [ ] **Adım 2: Lint + biçim**

```bash
.venv/bin/ruff check app tests && .venv/bin/ruff format --check app tests
```

- [ ] **Adım 3: Migration turu (yerel DB)** — §0.3'teki üç komut, açık revizyon id'siyle

- [ ] **Adım 4: `openapi.json` üret ve gözle doğrula**

```bash
.venv/bin/python -c "import json;from app.main import app;print(json.dumps(app.openapi(),ensure_ascii=False,indent=2))" > openapi.json
grep -c '"/contracts' openapi.json
grep -c '"/subcontractor' openapi.json
```

Spec §6'daki **her uç** çıktıda görünmelidir; eksik varsa task geri açılır.

- [ ] **Adım 5: Kapanış kontrol listesi (§3) doğrulanır ve commit**

```bash
git add -A ':!openapi.json'
git commit -m "chore(contracts): P5 kapanış — tam kapı koşusu"
```

---

## 3. "Bitti" tanımı

- [ ] 5 yeni tablo + 2 yeni kolon + **tek** migration; upgrade→downgrade→upgrade temiz
- [ ] Spec §6'daki uçların tamamı; hepsi izin + proje görünürlüğü kapısından geçiyor
- [ ] Modül sayısı **18**, izin satırı **144**, parity testleri yeşil
- [ ] Görünmeyen kayıt 404'ü var olmayan kimlikten **ayırt edilemez** (test var)
- [ ] Taslak/yayın kural ayrımı test edilmiş; şantiye zorunlu **değil** (K4)
- [ ] Dağılım ucu atomik; aşım 422; bağ kaldırma satırı silmiyor
- [ ] Silme yalnız `admin` + taslak istisnası; 4 bağlı-kayıt korkuluğu
- [ ] `ruff` temiz, tam `pytest` yeşil
- [ ] `openapi.json` üretildi (commit edilmedi)
- [ ] **Push/PR/merge/deploy YAPILMADI** — karar kullanıcıda

## 4. Riskli task'lar

| Task | Risk | Azaltma |
|---|---|---|
| C1 | Migration/enum; ikinci upgrade patlar | §0.3 açık revizyon turu, §0.4 `DROP TYPE` |
| C2 | 17→18 geçişi dağınık testleri kırar | Adım 1'de `grep` ile **tamamı** bulunur |
| C8 | Atomiklik + grup çözümü + aşım | Önce tüm doğrulama, sonra yazma; 5 ayrı test + mutasyon denetimi |
| C12 | `sites` silme yoluna dokunuluyor | Mevcut üç korkuluğun testleri de koşturulur |

## 5. Frontend'e devredilen (bu planın DIŞI)

* `Sözleşmeler` · `Ekran 14` · `Taşeron Sözleşme Detay` · `Form - Sözleşme Oluştur` ·
  `İşveren Sözleşme - Poz Dağılımı` ekranları
* BFF `ALLOWED_ROOTS`'a `contracts`, `subcontractors`, `subcontractor-contracts`
  (eklenmezse modül **yalnız canlıda** 404 verir — "zaten var" varsayma, grep'le)
* **İşveren sözleşmesi poz ekleme formu mockup'ı kullanıcıdan istenecek** (spec §13.2)
