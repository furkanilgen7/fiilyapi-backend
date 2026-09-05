"""BC-3 sahip kayıt defteri — dört sahibin TEK tanım noktası.

Servis ve router bu tanımlar üzerinden PARAMETRİKTİR: görünürlük, `project_id`
türetme, izin anahtarı, rota kökü ve denetim etiketi burada durur. Dört sahip
için dört ayrı servis/router yazılsaydı IDOR kapısı ve kapsam eşitliği dört kez
kopyalanırdı — *"aynı korumanın ikinci kopyası bekçi değil, eşdeğer mutant
yatağıdır"*.

## `project_id` türetme zinciri (dördü de NOT NULL — ölçüldü, NULL yol YOK)

| sahip | zincir |
|---|---|
| `sections` | `sections.site_id` → `sites.project_id` |
| `units` | `units.project_id` (bileşik FK ile bloğa bağlı) |
| `unit_sales` | `unit_sales.project_id` |
| `subcontractor_contracts` | `subcontractor_contracts.project_id` |

`site_id` yalnız bilgi amaçlıdır ve NULL olabilir (taşeron sözleşmesi K4
"proje geneli") — uydurma şantiye ATANMAZ. Türetme SUNUCUDADIR; hiçbir uç
gövdeden `project_id` almaz (`documents.project_id` NOT NULL kalır).

## İzin anahtarı — YENİ MODÜL AÇILMADI

Dört sahibin dördünün de izin anahtarı zaten var; bağ uçları sahibin kendi
kapısından geçer (equipment belgelerinin `equipment` iznini kullanması emsali):
okuma `view`, yazmanın tamamı `full`. Bağı silmek arşivdeki dosyayı SİLMEZ;
dosya silme `documents` modülünün `admin` kapısındadır.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import NamedTuple

from sqlalchemy import Select, func, select
from sqlalchemy.orm import InstrumentedAttribute

from app.modules.contracts.models import SubcontractorContract
from app.modules.documents import link_guards as guards
from app.modules.documents.models.links import (
    EntityDocumentScope,
    SectionDocument,
    SubcontractorContractDocument,
    UnitDocument,
    UnitSaleDocument,
)
from app.modules.sales.models import UnitSale
from app.modules.sites.models import Section, Site
from app.modules.units.models import Block, Unit


class OwnerContext(NamedTuple):
    """Sahipten türetilen kapsam: proje (NOT NULL) + şantiye (NULL olabilir) +
    denetim satırı için görünen ad."""

    project_id: uuid.UUID
    site_id: uuid.UUID | None
    display: str


@dataclass(frozen=True)
class OwnerSpec:
    """Bir sahibin bağ tanımı. `context_stmt(owner_id)` üç kolon döndüren bir
    SELECT üretir: `(project_id, site_id, display)`; satır yoksa sahip YOKTUR."""

    key: str
    scope: EntityDocumentScope
    link_model: type
    owner_column: InstrumentedAttribute
    route_root: str
    permission_module: str
    owner_missing: str
    label: str
    context_stmt: Callable[[uuid.UUID], Select]


def _section_context(owner_id: uuid.UUID) -> Select:
    return (
        select(Site.project_id, Section.site_id, Section.name)
        .join(Site, Site.id == Section.site_id)
        .where(Section.id == owner_id)
    )


def _unit_context(owner_id: uuid.UUID) -> Select:
    return (
        select(Unit.project_id, Block.site_id, Unit.unit_no)
        .join(Block, Block.id == Unit.block_id)
        .where(Unit.id == owner_id)
    )


def _unit_sale_context(owner_id: uuid.UUID) -> Select:
    return (
        select(UnitSale.project_id, Block.site_id, Unit.unit_no)
        .join(Unit, Unit.id == UnitSale.unit_id)
        .join(Block, Block.id == Unit.block_id)
        .where(UnitSale.id == owner_id)
    )


def _subcontractor_contract_context(owner_id: uuid.UUID) -> Select:
    # Sözleşme no da taşeron adı da nullable (taslak); denetim satırı boş
    # kalmasın diye ikisi de yoksa "-" basılır.
    return select(
        SubcontractorContract.project_id,
        SubcontractorContract.site_id,
        func.coalesce(
            SubcontractorContract.contract_no, SubcontractorContract.subcontractor_name, "-"
        ),
    ).where(SubcontractorContract.id == owner_id)


SECTION = OwnerSpec(
    key="section",
    scope=EntityDocumentScope.section,
    link_model=SectionDocument,
    owner_column=SectionDocument.section_id,
    route_root="/sections",
    permission_module="sites",
    owner_missing=guards.SECTION_MISSING,
    label="Bölüm",
    context_stmt=_section_context,
)

UNIT = OwnerSpec(
    key="unit",
    scope=EntityDocumentScope.unit,
    link_model=UnitDocument,
    owner_column=UnitDocument.unit_id,
    route_root="/units",
    permission_module="projects",
    owner_missing=guards.UNIT_MISSING,
    label="Ünite",
    context_stmt=_unit_context,
)

UNIT_SALE = OwnerSpec(
    key="unit_sale",
    scope=EntityDocumentScope.unit_sale,
    link_model=UnitSaleDocument,
    owner_column=UnitSaleDocument.unit_sale_id,
    route_root="/sales",
    permission_module="sales",
    owner_missing=guards.SALE_MISSING,
    label="Satış",
    context_stmt=_unit_sale_context,
)

SUBCONTRACTOR_CONTRACT = OwnerSpec(
    key="subcontractor_contract",
    scope=EntityDocumentScope.subcontractor_contract,
    link_model=SubcontractorContractDocument,
    owner_column=SubcontractorContractDocument.subcontractor_contract_id,
    route_root="/subcontractor-contracts",
    permission_module="contracts",
    owner_missing=guards.CONTRACT_MISSING,
    label="Taşeron sözleşmesi",
    context_stmt=_subcontractor_contract_context,
)

#: Rota kayıt sırası = bu demet. Dördü de farklı kökte olduğu için aralarında
#: sıra tuzağı YOKTUR (ölçüldü: kökler `/sections` · `/units` · `/sales` ·
#: `/subcontractor-contracts`).
OWNER_SPECS: tuple[OwnerSpec, ...] = (SECTION, UNIT, UNIT_SALE, SUBCONTRACTOR_CONTRACT)

#: `scope` → spec. Katalog ve bağ tablosu aynı bölmeyi kullandığı için tek
#: anahtar yeter; her `EntityDocumentScope` üyesinin bir sahibi VARDIR (bekçi
#: testi bunu ölçer).
SPEC_BY_SCOPE: dict[EntityDocumentScope, OwnerSpec] = {s.scope: s for s in OWNER_SPECS}
