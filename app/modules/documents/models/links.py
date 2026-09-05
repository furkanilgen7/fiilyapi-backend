"""BC-3 — belge ↔ varlık bağı: paylaşılan slot kataloğu + sahip-başına bağ tabloları.

## Şekil: BC-2 PİLOTU genişletildi — FK `documents`ta DEĞİL, SAHİP tarafındadır

`personnel_documents` (İK-1) ve `leave_requests` (İK-2) emsali: dosya baytları
BC arşivine (`documents` + `document_blobs`) yazılır, sahip tarafındaki kayıt
künyeye `document_id` → `documents.id` **SET NULL** ile bağlanır. Polimorfik
`owner_type`/`owner_id` çifti **yazılmadı** (yönetim kararı, BC-3 emri §1):
bu depoda üçüncü bir bağlama deseni "aynı korumanın ikinci kopyası"dır.

Dört sahip, dördü de mockup'ta **sabit, adlandırılmış, çoklu** slot çizer
(ölçüldü 2026-09-04): `Form - Bolum Ekle` 3 · `Form - Unite Ekle` 3 ·
`Form - Daire Satisi` 6 (2 zorunlu) · `Form - Sözleşme Oluştur` 6 (2 zorunlu,
başlığı "Yeni **Taşeron** Sözleşmesi" → `subcontractor_contracts`). Tek FK
(`leave_requests` biçimi) 6 slotu taşıyamazdı; sabit slot + katalog
`equipment_documents`/`equipment_document_types` deseninin birebiridir.

## Katalog TEK tablodur, dört değil

`personnel_document_types` ve `equipment_document_types` zaten var; dört tane
daha açmak altı neredeyse aynı katalog demekti. `entity_document_types`
`scope` ile bölümlenir. `scope` burada bir **bağlama ayracı DEĞİL**, katalog
bölmesidir — bağ hâlâ sahip tablosundaki gerçek, tipli FK'dir.

🔴 **Yanlış kapsamın tipi DB'de İMKÂNSIZDIR** (`fk_units_block_project`
emsali, `units/models.py`): katalogda `UNIQUE(id, scope)`, her bağ tablosunda
CHECK ile kendi sabitine çakılı bir `scope` kolonu ve bileşik FK
`(type_id, scope) → entity_document_types(id, scope)`. Servis katmanı ayrıca
temiz bir 422 verir (personel XOR'unun "üç kat" deseni); DB ikinci kattır.

## 🔴 TEK `Enum` NESNESİ — `ENTITY_DOCUMENT_SCOPE`

Beş tablo aynı PG tipini paylaşır. `accounting.JOURNAL_SOURCE_TYPE` kanonu: her
kolonda ayrı `Enum(..., name="entity_document_scope")` kurulsaydı
`Base.metadata.create_all` tipi iki kez yaratmaya çalışır ve tüm küme
`type "entity_document_scope" already exists` ile düşerdi.

## `document_id` ADI — bu depoda İKİ farklı anlam taşır, bu tablolar BİRİNCİSİDİR

* **arşivdeki DOSYA** (FK'lı): `personnel_documents.document_id`,
  `leave_requests.document_id` ve BURADAKİ dört bağ tablosu. Tablo adının
  kendisi (`*_documents`) anlamı taşır.
* **onaylanan İŞ BELGESİ** (FK'sız UUID + `document_type` enum'u):
  `approvals.document_id` — hakediş, talep vb. kimliği; kasıtlı olarak FK
  değildir (`approvals/models.py` "Neden `document_id` FK DEĞİL").
Beşinci bir eşanlamlı ad (`file_id`, `archive_id`) ikiliği **büyütürdü**;
pilotla birebir aynı ad üçüncü tutarlı kullanımdır.

## Alan kararları (ölçülmüş)

* `type_id` **NOT NULL / RESTRICT** — `free_label` XOR'u YOK: slotlar sabittir
  (equipment emsali), personelin serbest etiketi burada karşılıksızdır.
* `document_id` **nullable / SET NULL** — pilotun birebiri: arşiv kaydı
  silinse de slot satırı (ve künye meta verisi) KALIR, "belge vardı, dosyası
  silindi" bilgisi kaybolmaz.
* `UNIQUE(sahip, type_id)` **YOK**, yalnız indeks — "Görseller / Render" slotu
  kendi etiketiyle çoğuldur; iki emsal de indeks kullanır.
* `issued_at` / `valid_until` / `note` — adlar personel/ekipman tarafıyla
  **BİREBİR** (FRM-1 K6: eşanlamlı yeni ad uydurulmaz). Mockup dört formda da
  tarih alanı çizmiyor ama "SGK Borcu Yoktur Yazısı · *Son 30 gün içinde
  alınmış*" ve "Teminat Mektubu" süreli belgelerdir (equipment K7 gerekçesi);
  üçü de nullable, zorunlu KILINMAZ. Varlığa özgü başka meta veri mockup'ta
  YOKTUR → icat edilmedi.
* `project_id` bağ tablosuna **KOPYALANMAZ**: sahipten türetilir (bölüm→şantiye
  →proje · ünite→proje · satış→proje · taşeron sözleşmesi→proje), dördü de
  NOT NULL zincirdir. `documents.project_id` NOT NULL **kalır**.
"""

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class EntityDocumentScope(str, enum.Enum):
    """Slot kataloğunun bölmesi = bağ tablosunun sahibi (BC-3 emri §2, ölçülmüş).

    `project_contract` (işveren sözleşmesi) BİLEREK YOKTUR: `Ekran 14` bir
    "Belgeler" sekmesi çizer ama slot listesi çizilmemiştir; ölçülemeyen slot
    uydurulmaz. Geldiğinde additive bir üye + bir bağ tablosuyla eklenir
    (enum genişletmesi tip TAKASIYLA yapılır, `UnitKind` notu).
    """

    section = "section"
    unit = "unit"
    unit_sale = "unit_sale"
    subcontractor_contract = "subcontractor_contract"


#: 🔴 TEK paylaşılan `Enum` nesnesi — beş tablonun `scope` kolonu BUNU kullanır
#: (gerekçe modül docstring'inde; `JOURNAL_SOURCE_TYPE` kanonu).
ENTITY_DOCUMENT_SCOPE = Enum(EntityDocumentScope, name="entity_document_scope")


class EntityDocumentType(Base):
    """Slot kataloğu — dört sahibin 18 sabit slotu (3+3+6+6), `scope` ile bölümlü.

    `equipment_document_types`in kolon kümesi (`code` · `name` · `is_required` ·
    `sort_order`) + `scope`. `code` sahibe göre tekildir (`UNIQUE(scope, code)`):
    frontend ikon/ipucu haritası bir ADA değil KODA bağlanır, ad değişse de
    haritalama kırılmaz. Mockup'ın ipucu satırı ("Bu faza ait çizimler") UI
    metnidir, kolon açılmadı (equipment emsalinde de yoktur).

    `UNIQUE(id, scope)` bileşik FK'nin hedefidir (modül docstring'i). CRUD ucu
    AÇILMAZ (İK-1/MK-2 emsali) — seed migration'da, yönetimi ayarlar dilimine
    ertelidir.

    ## 🟡 KAYDA GEÇMİŞ İKİ SINIR (bugün zararsız, yarın ısırabilir)

    **`is_required` DEKORATİFTİR.** Kolon mockup'ın `*` işaretini taşır ve
    uçlardan okunur, ama SUNUCU hiçbir yerde ZORLAMAZ: zorunlu slotu boş olan
    bir satış kaydı normal kaydedilir. En yakın emsal (`equipment`) en azından
    bir `missing` sayacı üretir; burada o da yoktur — "eksik zorunlu belge"
    sorusu bugün HİÇBİR uçta cevaplanmıyor. Zorlamak mı yoksa yalnız saymak mı
    gerektiği bir ÜRÜN kararıdır ve kullanıcıya sorulmuştur.

    **Slot kimlikleri ORTAMA GÖRE FARKLIDIR.** `id` seed sırasında
    `uuid.uuid4()` ile migration KOŞMA ANINDA üretilir → CI, yerel ve Railway
    aynı slot için FARKLI UUID taşır. Bugün zararsızdır çünkü her eşleme
    `(scope, code)` üzerinden yapılır (`code` UNIQUE'tir). 🔴 Ama `type_id`
    değeri GÖMÜLÜ bir fikstür/tohum/test verisi bu varsayımı SESSİZCE kırar;
    kimlik gerektiğinde `code`dan çözülmelidir.
    """

    __tablename__ = "entity_document_types"
    __table_args__ = (
        UniqueConstraint("scope", "code", name="uq_entity_document_types_scope_code"),
        UniqueConstraint("id", "scope", name="uq_entity_document_types_id_scope"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scope: Mapped[EntityDocumentScope] = mapped_column(ENTITY_DOCUMENT_SCOPE, nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    is_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


def _scope_default(scope: EntityDocumentScope) -> str:
    return f"'{scope.value}'::entity_document_scope"


def _link_table_args(table: str, owner_column: str, scope: EntityDocumentScope) -> tuple:
    """Dört bağ tablosunun ORTAK kısıt kümesi — dört kez elle yazılıp ayrışmasın.

    * `ck_<tablo>_scope`: `scope` kolonu kendi sabitine ÇAKILIDIR.
    * `fk_<tablo>_type_scope`: bileşik FK — yanlış bölmenin tipi DB'de imkânsız.
    * `ix_<tablo>_owner_type`: `(sahip, type_id)` — iki emsalin liste indeksi.
    """
    return (
        CheckConstraint(f"scope = '{scope.value}'", name=f"ck_{table}_scope"),
        ForeignKeyConstraint(
            ["type_id", "scope"],
            ["entity_document_types.id", "entity_document_types.scope"],
            name=f"fk_{table}_type_scope",
            ondelete="RESTRICT",
        ),
        Index(f"ix_{table}_owner_type", owner_column, "type_id"),
    )


class _EntityDocumentColumns:
    """Dört bağ tablosunun ORTAK kolonları (mixin). Sahip FK'si her sınıfta AÇIKÇA
    yazılır — CASCADE hedefi ve adı tabloya özgüdür, gizlenmez."""

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    type_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    # SET NULL: BC arşiv kaydı silinse de slot satırı kalır (BC-2 pilotu).
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    issued_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SectionDocument(_EntityDocumentColumns, Base):
    """Bölüm belgesi — `Form - Bolum Ekle` "📎 Bölüm Belgeleri" (3 slot).

    `project_id` türevi: `sections.site_id` (NOT NULL) → `sites.project_id`
    (NOT NULL). CASCADE: bölüm silinirse (`DELETE /sections/{id}`, admin) slot
    satırları da gider; arşivdeki dosya KALIR (bağ silinir, belge silinmez).
    """

    __tablename__ = "section_documents"
    __table_args__ = _link_table_args(
        "section_documents", "section_id", EntityDocumentScope.section
    )

    section_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sections.id", ondelete="CASCADE"), nullable=False
    )
    scope: Mapped[EntityDocumentScope] = mapped_column(
        ENTITY_DOCUMENT_SCOPE,
        nullable=False,
        default=EntityDocumentScope.section,
        server_default=text(_scope_default(EntityDocumentScope.section)),
    )


class UnitDocument(_EntityDocumentColumns, Base):
    """Ünite belgesi — `Form - Unite Ekle` "📎 Ünite Belgeleri" (3 slot).

    `project_id` türevi: `units.project_id` (NOT NULL, bileşik FK ile bloğa
    bağlı). Satış belgelerinden AYRIDIR (`UnitSaleDocument`): kümeler kesişmez.
    """

    __tablename__ = "unit_documents"
    __table_args__ = _link_table_args("unit_documents", "unit_id", EntityDocumentScope.unit)

    unit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("units.id", ondelete="CASCADE"), nullable=False
    )
    scope: Mapped[EntityDocumentScope] = mapped_column(
        ENTITY_DOCUMENT_SCOPE,
        nullable=False,
        default=EntityDocumentScope.unit,
        server_default=text(_scope_default(EntityDocumentScope.unit)),
    )


class UnitSaleDocument(_EntityDocumentColumns, Base):
    """Satış belgesi — `Form - Daire Satisi` "📎 Satış Belgeleri" (6 slot, 2 zorunlu).

    `project_id` türevi: `unit_sales.project_id` (NOT NULL, doğrudan kolon).
    """

    __tablename__ = "unit_sale_documents"
    __table_args__ = _link_table_args(
        "unit_sale_documents", "unit_sale_id", EntityDocumentScope.unit_sale
    )

    unit_sale_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("unit_sales.id", ondelete="CASCADE"), nullable=False
    )
    scope: Mapped[EntityDocumentScope] = mapped_column(
        ENTITY_DOCUMENT_SCOPE,
        nullable=False,
        default=EntityDocumentScope.unit_sale,
        server_default=text(_scope_default(EntityDocumentScope.unit_sale)),
    )


class SubcontractorContractDocument(_EntityDocumentColumns, Base):
    """Taşeron sözleşmesi belgesi — `Form - Sözleşme Oluştur` (6 slot, 2 zorunlu).

    `project_id` türevi: `subcontractor_contracts.project_id` (NOT NULL).
    `site_id` ise NULL olabilir (K4 "proje geneli") ve NULL BIRAKILIR — uydurma
    şantiye atanmaz. İşveren sözleşmesi (`project_contracts`) kapsam DIŞIDIR
    (`EntityDocumentScope` docstring'i).
    """

    __tablename__ = "subcontractor_contract_documents"
    __table_args__ = _link_table_args(
        "subcontractor_contract_documents",
        "subcontractor_contract_id",
        EntityDocumentScope.subcontractor_contract,
    )

    subcontractor_contract_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("subcontractor_contracts.id", ondelete="CASCADE"),
        nullable=False,
    )
    scope: Mapped[EntityDocumentScope] = mapped_column(
        ENTITY_DOCUMENT_SCOPE,
        nullable=False,
        default=EntityDocumentScope.subcontractor_contract,
        server_default=text(_scope_default(EntityDocumentScope.subcontractor_contract)),
    )
