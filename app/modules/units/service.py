import uuid
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    DuplicateError,
    NotFoundError,
    ProjectTypeMismatchError,
    RelatedRecordsExistError,
    UnitImportError,
    UnitValidationError,
)
from app.modules.projects.models import Project, ProjectType

# Gorunurluk suzgeci P1'DEN GELIR (spec §8): kopya bir erisim mantigi YAZILMAZ.
# Iki ayri suzgec zamanla ayrisir ve ayrisan taraf sessiz bir yetki sizintisi
# olur. Ayni desen P2 `sites/service.py:15` ve P4 `boq/service.py`'de de var.
from app.modules.projects.service import visible_projects
from app.modules.sites import repository as sites_repository
from app.modules.sites.models import Site
from app.modules.units import repository
from app.modules.units.bulk import generate_unit_numbers
from app.modules.units.importer import (
    IMPORT_ROW_ERRORS,
    MAX_REPORTED_ERRORS,
    ImportFileError,
    ImportRow,
    RowError,
    normalize_header,
    parse_units_file,
)
from app.modules.units.models import Block, Unit, UnitKind, UnitOwnerSide
from app.modules.units.schemas import (
    BlockCreate,
    BlockListResponse,
    BlockResponse,
    BlockUpdate,
    CountPlaceholder,
    MetricPlaceholder,
    UnitBlockGroup,
    UnitBulkCreate,
    UnitCreate,
    UnitImportResult,
    UnitImportRowError,
    UnitKindBreakdown,
    UnitListResponse,
    UnitOwnerSideFilter,
    UnitResponse,
    UnitSideSummary,
    UnitTotals,
    UnitUpdate,
    UnitValueBasis,
)
from app.modules.users.models import User

# 404 GOVDESI DE AYIRT EDICI OLMAMALIDIR (P2 `sites/service.py` dersi): gorunmeyen
# proje ile var olmayan proje ayni mesaji doner, aksi hâlde elinde UUID olan
# kullanici kaydin var oldugunu ve baskasina ait oldugunu ayirt edebilirdi.
_PROJECT_MISSING = "Proje bulunamadı"

# Spec §7.11 tablosundan BIREBIR alinmistir — yeniden yazilmaz. Mesaj sabitleri
# `boq/service.py` deseniyle modul duzeyindedir (ayri `errors.py` acilmaz: mevcut
# desen alan HATA SINIFLARINI `app/core/errors.py`'de, METINLERI servis modulunde
# tutar). Bu dilimde kullanilmayanlar (B7-B10) ilgili task'ta eklenecektir.
_BLOCK_MISSING = "Blok bulunamadı"
_UNIT_MISSING = "Ünite bulunamadı"
_SITE_MISSING = "Şantiye bulunamadı"
_DUPLICATE_BLOCK = "Bu blok adı bu projede zaten kullanılıyor"
_DUPLICATE_UNIT = "Bu ünite numarası bu blokta zaten kullanılıyor"
_BLOCK_HAS_UNITS = "Bu blokta ünite var, önce üniteleri silin"
_BULK_NUMBERS_TAKEN = "Üretilecek ünite numaralarından bazıları blokta zaten var"
_NO_SITE_FOR_BLOCK = "Blok tanımlamadan önce projeye şantiye eklenmelidir"
_SITE_REQUIRED = "Birden fazla şantiye var, blok için şantiye seçilmelidir"
_OWNER_SIDE_NOT_ALLOWED = "Ünite payı yalnızca kat karşılığı projelerde belirlenebilir"
_NET_GT_GROSS = "Net alan brüt alandan büyük olamaz"

# Spec §6.1: bu dilimde YAZILMAYAN turev alanlarin bagli oldugu modul anahtarlari.
# Kullaniciya gosterilecek metin degil, B6 yer tutucu sozlesmesindeki anahtardir.
_UNIT_SALES = "unit_sales"
_SHAREHOLDER_UNITS = "shareholder_units"
_PROJECT_COSTS = "project_costs"

_MONEY = Decimal("0.01")
_HUNDRED = Decimal("100")

# Toplu uretim cakismasinda hata mesajinda listelenecek numara adedi (spec §7.7).
# 500 numarayi tek satira dizmek mesaji okunamaz kilar; ilk 20 kullaniciya
# hangi araligi duzeltecegini gostermeye yeter.
_MAX_CONFLICT_NUMBERS = 20

# Taraf ozetlerinin SABIT sirasi (spec §5.3): ucu de her zaman doner, unite
# olmasa bile. Ekran "henuz paylasilmadi" durumunu `None` grubundan basar.
_SIDE_ORDER: tuple[UnitOwnerSide | None, ...] = (
    UnitOwnerSide.contractor,
    UnitOwnerSide.landowner,
    None,
)

# Spec §4.4: toplamlarin hangi sutundan hesaplandigi proje tipine baglidir.
_VALUE_BASIS_BY_TYPE = {
    ProjectType.kat_karsiligi: UnitValueBasis.appraisal_value,
    ProjectType.kendi_yatirim: UnitValueBasis.list_price,
    ProjectType.taahhut: UnitValueBasis.list_price,
}


def _quantize_money(value: Decimal) -> Decimal:
    return value.quantize(_MONEY, rounding=ROUND_HALF_UP)


def _metric(pending_module: str) -> MetricPlaceholder:
    return MetricPlaceholder(pending_module=pending_module)


def _count(pending_module: str) -> CountPlaceholder:
    return CountPlaceholder(pending_module=pending_module)


def _sum(values: list[Decimal | None]) -> Decimal:
    """NULL'lar 0 SAYILIR (spec §6.1) ve toplama Decimal ile yapilir — float ASLA."""
    return _quantize_money(sum((value for value in values if value is not None), Decimal("0")))


def _counts(units: list[Unit]) -> UnitKindBreakdown:
    return UnitKindBreakdown(
        apartment=sum(1 for u in units if u.unit_kind is UnitKind.apartment),
        shop=sum(1 for u in units if u.unit_kind is UnitKind.shop),
    )


def _basis_value(unit: Unit, basis: UnitValueBasis) -> Decimal | None:
    if basis is UnitValueBasis.appraisal_value:
        return unit.appraisal_value
    return unit.list_price


def to_block(block: Block, site_name: str, units: list[Unit]) -> BlockResponse:
    return BlockResponse(
        id=block.id,
        name=block.name,
        site_id=block.site_id,
        site_name=site_name,
        sort_order=block.sort_order,
        counts=_counts(units),
    )


def to_unit(unit: Unit, block_name: str) -> UnitResponse:
    """Satis alanlari (KY 275-277, KKP 91-92) P8/P9/P10'un isidir ve yer tutucu
    doner — `units`'te saklanmaz (spec §4.6)."""
    return UnitResponse(
        id=unit.id,
        block_id=unit.block_id,
        block_name=block_name,
        unit_no=unit.unit_no,
        unit_kind=unit.unit_kind,
        layout=unit.layout,
        gross_area_m2=unit.gross_area_m2,
        net_area_m2=unit.net_area_m2,
        list_price=unit.list_price,
        appraisal_value=unit.appraisal_value,
        owner_side=unit.owner_side,
        sort_order=unit.sort_order,
        sales_status=_metric(_UNIT_SALES),
        sale_price=_metric(_UNIT_SALES),
        buyer_name=_metric(_UNIT_SALES),
        shareholder=_metric(_SHAREHOLDER_UNITS),
        unit_cost=_metric(_PROJECT_COSTS),
    )


def _average(total: Decimal, count: int) -> Decimal | None:
    """Sifira bolme YOK: unitesi olmayan kumede ortalama `None`'dir, 0 degil."""
    if count == 0:
        return None
    return _quantize_money(total / Decimal(count))


def _side_summary(
    side: UnitOwnerSide | None, units: list[Unit], basis: UnitValueBasis, project_total: int
) -> UnitSideSummary:
    """KK 116-122 / KKP 161-168 tfoot toplami.

    `share_pct` ADET oranidir (spec §5.2): sozlesmedeki yuzde (P1) ile birebir
    tutmak ZORUNDA DEGILDIR ve sapma DOGRULANMAZ, yalnizca raporlanir.
    """
    selected = [u for u in units if u.owner_side is side]
    total_value = _sum([_basis_value(u, basis) for u in selected])
    share_pct = (
        _quantize_money(Decimal(len(selected)) * _HUNDRED / Decimal(project_total))
        if project_total
        else None
    )
    return UnitSideSummary(
        side=side,
        counts=_counts(selected),
        total_value=total_value,
        average_value=_average(total_value, len(selected)),
        share_pct=share_pct,
        sold=_count(_UNIT_SALES),
        reserved=_count(_UNIT_SALES),
        listed=_count(_UNIT_SALES),
    )


def _totals(units: list[Unit], basis: UnitValueBasis) -> UnitTotals:
    """Spec §7.4: toplamlar SUZGECTEN ETKILENMEZ — cagiran daima projenin TUM
    unitelerini verir (P1 `list_projects_overview` kuralinin birebir tekrari)."""
    total_value = _sum([_basis_value(u, basis) for u in units])
    return UnitTotals(
        counts=_counts(units),
        value_basis=basis,
        total_value=total_value,
        average_value=_average(total_value, len(units)),
        total_list_price=_sum([u.list_price for u in units]),
        total_appraisal_value=_sum([u.appraisal_value for u in units]),
        total_gross_area_m2=_sum([u.gross_area_m2 for u in units]),
        sides=[_side_summary(side, units, basis, len(units)) for side in _SIDE_ORDER],
        sold_units=_count(_UNIT_SALES),
        reserved_units=_count(_UNIT_SALES),
        available_units=_count(_UNIT_SALES),
        sales_revenue=_metric(_UNIT_SALES),
        average_sale_price=_metric(_UNIT_SALES),
    )


# --- Gorunurluk (spec §8) ---


async def _visible_project(
    session: AsyncSession, actor: User, project_id: uuid.UUID, missing: str = _PROJECT_MISSING
) -> Project:
    """Kullanici projeyi goremiyorsa 404 — 403 DEGIL: varligin kendisi sizdirilmaz."""
    visible = await visible_projects(session, actor)
    project = next((p for p in visible if p.id == project_id), None)
    if project is None:
        raise NotFoundError(missing)
    return project


# --- Okuma uclari (spec §7.1, §7.4) ---


async def _blocks_with_units(
    session: AsyncSession, project_id: uuid.UUID
) -> tuple[list[tuple[Block, str]], dict[uuid.UUID, list[Unit]], list[Unit]]:
    """Bloklar + unitelerin bloklara dagilmis hâli + duz unite listesi.

    Uniteler TEK sorguda cekilir (repository notu); dagitim Python'dadir.
    """
    blocks = await repository.list_blocks_for_project(session, project_id)
    units = await repository.list_units_for_project(session, project_id)
    by_block: dict[uuid.UUID, list[Unit]] = {block.id: [] for block, _ in blocks}
    for unit in units:
        by_block.setdefault(unit.block_id, []).append(unit)
    return blocks, by_block, units


async def list_blocks(
    session: AsyncSession, actor: User, project_id: uuid.UUID
) -> BlockListResponse:
    """Spec §7.1. Blok seciciler (unite formu, toplu uretim formu) bu ucu kullanir."""
    await _visible_project(session, actor, project_id)
    blocks, by_block, _ = await _blocks_with_units(session, project_id)
    return BlockListResponse(
        blocks=[to_block(block, site_name, by_block[block.id]) for block, site_name in blocks]
    )


def _matches(unit: Unit, kind: UnitKind | None, owner_side: UnitOwnerSideFilter | None) -> bool:
    if kind is not None and unit.unit_kind is not kind:
        return False
    if owner_side is None:
        return True
    if owner_side is UnitOwnerSideFilter.unassigned:
        return unit.owner_side is None
    return unit.owner_side is not None and unit.owner_side.value == owner_side.value


async def list_units(
    session: AsyncSession,
    actor: User,
    project_id: uuid.UUID,
    *,
    block_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    kind: UnitKind | None = None,
    owner_side: UnitOwnerSideFilter | None = None,
) -> UnitListResponse:
    """Spec §7.4. Suzgecler YALNIZ listeyi daraltir; `totals` daima projenin
    tamamini sayar. `site_id` suzgeci blok uzerinden calisir — `units`'te
    `site_id` sutunu YOKTUR (spec §4.0). Unitesi olmayan blok listede KALIR."""
    project = await _visible_project(session, actor, project_id)
    blocks, by_block, units = await _blocks_with_units(session, project_id)
    basis = _VALUE_BASIS_BY_TYPE[project.project_type]

    selected = [
        (block, site_name)
        for block, site_name in blocks
        if (block_id is None or block.id == block_id)
        and (site_id is None or block.site_id == site_id)
    ]
    groups = [
        UnitBlockGroup(
            block=to_block(block, site_name, by_block[block.id]),
            units=[
                to_unit(unit, block.name)
                for unit in by_block[block.id]
                if _matches(unit, kind, owner_side)
            ],
        )
        for block, site_name in selected
    ]
    return UnitListResponse(totals=_totals(units, basis), blocks=groups)


# --- Yazma yolu: ortak yardimcilar (spec §7.2, §7.3, §7.5, §7.6) ---


async def _visible_block(
    session: AsyncSession, actor: User, block_id: uuid.UUID
) -> tuple[Block, Project]:
    """Blok → proje → gorunurluk (spec §7.3).

    Gorunmeyen projenin blogu **404** doner, 403 DEGIL; ustelik var olmayan blok
    ile AYNI mesaji verir (IDOR-5/IDOR-7) — aksi hâlde elinde UUID olan kullanici
    kaydin var oldugunu ve baskasina ait oldugunu ayirt edebilirdi.
    """
    block = await repository.get_block(session, block_id)
    if block is None:
        raise NotFoundError(_BLOCK_MISSING)
    project = await _visible_project(session, actor, block.project_id, _BLOCK_MISSING)
    return block, project


async def _resolve_site(
    session: AsyncSession, project_id: uuid.UUID, site_id: uuid.UUID | None
) -> Site:
    """Spec §4.5 tablosunun BES satiri da burada karsilanir.

    | santiye sayisi | `site_id` | davranis |
    |---|---|---|
    | 1 | yok | otomatik atanir — mockup'ta secici YOK (KY 38 / KK 39) |
    | 1 | var | dogrulanir; projeye ait degilse 404 |
    | 0 | — | 422 |
    | >=2 | yok | 422 — otomatik atama yanlis veri uretirdi |
    | >=2 | var | dogrulanir |

    Sifir santiye kontrolu `site_id` kontrolunden ONCE gelir: spec tablosunun 3.
    satiri `site_id` sutununu "—" (fark etmez) olarak isaretler ve o durumda
    "once santiye ekleyin" mesaji kullaniciya yol gosterir.
    """
    sites = await sites_repository.list_sites_for_project(session, project_id)
    if not sites:
        raise UnitValidationError(_NO_SITE_FOR_BLOCK)
    if site_id is not None:
        site = next((s for s in sites if s.id == site_id), None)
        if site is None:
            raise NotFoundError(_SITE_MISSING)
        return site
    if len(sites) > 1:
        raise UnitValidationError(_SITE_REQUIRED)
    return sites[0]


async def _ensure_block_name_unique(
    session: AsyncSession,
    project_id: uuid.UUID,
    name: str,
    exclude_block_id: uuid.UUID | None = None,
) -> None:
    """`uq_blocks_project_name` — acik SELECT ile ONDEN (spec §4.3, P4 deseni)."""
    if await repository.get_block_by_name(session, project_id, name, exclude_block_id) is not None:
        raise DuplicateError(_DUPLICATE_BLOCK)


async def block_response(session: AsyncSession, block: Block) -> BlockResponse:
    site = await sites_repository.get_site(session, block.site_id)
    units = await repository.list_units_for_block(session, block.id)
    # `site` None olamaz: `site_id` NOT NULL + FK. `getattr` yalnizca tip
    # daraltmasi icindir, sessiz bir dusus degil.
    return to_block(block, site.name if site is not None else "", units)


# --- Blok yazma uclari (spec §7.2, §7.3) ---


async def create_block(
    session: AsyncSession, actor: User, project_id: uuid.UUID, data: BlockCreate
) -> Block:
    project = await _visible_project(session, actor, project_id)
    site = await _resolve_site(session, project.id, data.site_id)
    await _ensure_block_name_unique(session, project.id, data.name)
    block = Block(
        project_id=project.id, site_id=site.id, name=data.name, sort_order=data.sort_order
    )
    session.add(block)
    await session.flush()
    await session.refresh(block)
    return block


async def update_block(
    session: AsyncSession, actor: User, block_id: uuid.UUID, data: BlockUpdate
) -> Block:
    """Spec §7.3. `site_id` degistirilebilir (blok yanlis santiyeye acilmissa);

    yeni santiye AYNI projede olmali, degilse **404** (spec §4.5 son paragrafi ve
    plan B5 test 13). Spec §7.3'un hata listesinde bu durum icin "422" yaziyor —
    §4.5 ve plan 404 dedigi icin 404 uygulanmistir.
    """
    block, project = await _visible_block(session, actor, block_id)
    updates = data.model_dump(exclude_unset=True)
    if updates.get("site_id") is not None:
        site = await _resolve_site(session, project.id, updates["site_id"])
        updates["site_id"] = site.id
    else:
        # `site_id: null` gonderimi sutunu bosaltamaz (NOT NULL) — yok sayilir.
        updates.pop("site_id", None)
    if updates.get("name") is not None:
        await _ensure_block_name_unique(session, project.id, updates["name"], block.id)
    for field, value in updates.items():
        if value is not None:
            setattr(block, field, value)
    await session.flush()
    await session.refresh(block)
    return block


# --- Unite yazma uclari (spec §7.5, §7.6, §3.3) ---


async def _visible_unit(
    session: AsyncSession, actor: User, unit_id: uuid.UUID
) -> tuple[Unit, Project]:
    """Unite → proje → gorunurluk (spec §7.6). `_visible_block` ile ayni gerekce:

    gorunmeyen projenin unitesi 404 doner, 403 DEGIL, ve var olmayan unite ile
    AYNI mesaji verir (IDOR-4/IDOR-7).
    """
    unit = await repository.get_unit(session, unit_id)
    if unit is None:
        raise NotFoundError(_UNIT_MISSING)
    project = await _visible_project(session, actor, unit.project_id, _UNIT_MISSING)
    return unit, project


async def _ensure_unit_no_unique(
    session: AsyncSession,
    block_id: uuid.UUID,
    unit_no: str,
    exclude_unit_id: uuid.UUID | None = None,
) -> None:
    """`uq_units_block_no` — acik SELECT ile ONDEN (spec §4.3). A Blok "1" ile
    B Blok "1" ayni anda vardir (SY 76/106), bu yuzden kapsam bloktur."""
    if await repository.get_unit_by_no(session, block_id, unit_no, exclude_unit_id) is not None:
        raise DuplicateError(_DUPLICATE_UNIT)


async def _block_in_project(session: AsyncSession, project: Project, block_id: uuid.UUID) -> Block:
    """Spec §7.5 / IDOR-9: govdedeki `block_id` baska projenin blogu olabilir.

    Proje sinirini asan blok **404** doner (422 degil): blogun varligi da
    gizlidir — kullanici o projeyi hic goremiyor olabilir.
    """
    block = await repository.get_block(session, block_id)
    if block is None or block.project_id != project.id:
        raise NotFoundError(_BLOCK_MISSING)
    return block


def _ensure_owner_side_allowed(project: Project, owner_side: UnitOwnerSide | None) -> None:
    """Spec §3.3: `owner_side` YALNIZ `kat_karsiligi` projede dolu olabilir.

    DB `CHECK` ile zorlanamaz (`project_type` baska tabloda), bu yuzden tek yazma
    yolunda servis korkulugudur (P4 `BoqGroupSiteMismatchError` deseni). NULL her
    tipte serbesttir: paylasim noterden SONRA girilir (KKP 78, spec §5.3).
    """
    if owner_side is not None and project.project_type is not ProjectType.kat_karsiligi:
        raise ProjectTypeMismatchError(_OWNER_SIDE_NOT_ALLOWED)


def _ensure_net_le_gross(gross: Decimal | None, net: Decimal | None) -> None:
    """`ck_units_net_le_gross` DB'de de var; buradaki kontrol IntegrityError'in
    anlamsiz "Veri butunlugu hatasi" 409'una dusmemek icindir (spec §4.3, FDS 59)."""
    if gross is not None and net is not None and net > gross:
        raise UnitValidationError(_NET_GT_GROSS)


async def unit_response(session: AsyncSession, unit: Unit) -> UnitResponse:
    block = await repository.get_block(session, unit.block_id)
    # `block` None olamaz: `block_id` NOT NULL + FK. Kosul yalnizca tip
    # daraltmasi icindir, sessiz bir dusus degil.
    return to_unit(unit, block.name if block is not None else "")


async def create_unit(
    session: AsyncSession, actor: User, project_id: uuid.UUID, data: UnitCreate
) -> Unit:
    """Spec §7.5. `taahhut` projede unite tanimlamak SERBEST (§3.3 — kisit icat
    edilmez); iki fiyat sutunu da her tipte kabul edilir (§4.4)."""
    project = await _visible_project(session, actor, project_id)
    block = await _block_in_project(session, project, data.block_id)
    _ensure_owner_side_allowed(project, data.owner_side)
    _ensure_net_le_gross(data.gross_area_m2, data.net_area_m2)
    await _ensure_unit_no_unique(session, block.id, data.unit_no)
    unit = Unit(
        project_id=project.id,
        block_id=block.id,
        unit_no=data.unit_no,
        unit_kind=data.unit_kind,
        layout=data.layout,
        gross_area_m2=data.gross_area_m2,
        net_area_m2=data.net_area_m2,
        list_price=data.list_price,
        appraisal_value=data.appraisal_value,
        owner_side=data.owner_side,
        sort_order=data.sort_order,
    )
    session.add(unit)
    await session.flush()
    await session.refresh(unit)
    return unit


async def update_unit(
    session: AsyncSession, actor: User, unit_id: uuid.UUID, data: UnitUpdate
) -> Unit:
    """Spec §7.6. `exclude_unset` ayrimi kritiktir: GONDERILMEYEN alan degismez,
    `null` GONDERILEN alan bosalir (P1/P2/P4 deseni).

    Kurallar birlesmis (mevcut + gonderilen) deger uzerinde yeniden calisir:
    yalniz `net_area_m2` gonderen bir istek, mevcut `gross_area_m2` ile
    karsilastirilmazsa DB CHECK'ine duser ve kullanici anlamsiz bir 409 gorur.
    """
    unit, project = await _visible_unit(session, actor, unit_id)
    updates = data.model_dump(exclude_unset=True)

    target_block_id = unit.block_id
    if "block_id" in updates and updates["block_id"] is not None:
        target_block_id = (await _block_in_project(session, project, updates["block_id"])).id
    updates.pop("block_id", None)  # NOT NULL: `null` gonderimi sutunu bosaltamaz

    owner_side = updates["owner_side"] if "owner_side" in updates else unit.owner_side
    _ensure_owner_side_allowed(project, owner_side)
    gross = updates["gross_area_m2"] if "gross_area_m2" in updates else unit.gross_area_m2
    net = updates["net_area_m2"] if "net_area_m2" in updates else unit.net_area_m2
    _ensure_net_le_gross(gross, net)

    target_unit_no = updates.get("unit_no") or unit.unit_no
    if target_block_id != unit.block_id or target_unit_no != unit.unit_no:
        await _ensure_unit_no_unique(session, target_block_id, target_unit_no, unit.id)

    unit.block_id = target_block_id
    for field, value in updates.items():
        # NOT NULL sutunlar `null` ile bosaltilamaz; nullable olanlar bosaltilir.
        if value is None and field in ("unit_no", "unit_kind", "sort_order"):
            continue
        setattr(unit, field, value)
    await session.flush()
    await session.refresh(unit)
    return unit


# --- Silme uclari (spec §7.9) — VERI KAYBI SINIFI ---


async def delete_unit(session: AsyncSession, actor: User, unit_id: uuid.UUID) -> None:
    """Spec §7.9. Unite silme KOSULSUZDUR: P3'te uniteye baglanan hicbir tablo
    yoktur (spec §1.3). P8 (satis) geldiginde satisi olan unite icin korkuluk
    O DILIMDE eklenecektir — bugun var olmayan bir bag icin kontrol yazilmaz.

    Gorunurluk yine yukari cozumlenir: gorunmeyen projenin unitesi 404'tur ve
    var olmayan unite ile ayni mesaji verir (IDOR-6/IDOR-7).
    """
    unit, _ = await _visible_unit(session, actor, unit_id)
    await session.delete(unit)
    await session.flush()


async def delete_block(session: AsyncSession, actor: User, block_id: uuid.UUID) -> None:
    """Spec §7.9. CASCADE YOKTUR — bu fonksiyonun tek isi cascade'i ENGELLEMEKTIR.

    Blokta en az bir unite varsa silme 409 ile reddedilir. Uc katman birden
    korur ve UCU DE bilincli olarak yerinde birakilmistir:

    1. Buradaki `block_has_units` on kontrolu — kullaniciya Turkce, eyleme
       donuk mesaj verir ("once uniteleri silin").
    2. `units.block_id` uzerindeki `ON DELETE RESTRICT` (B1, spec §4.2) — servis
       atlanirsa DB reddeder; `IntegrityError → 409` handler'i yaris-durumu agidir.
    3. Modelde `relationship(cascade=...)` TANIMLI DEGIL — ORM'in kendiliginden
       unite silecek bir yolu yoktur.

    Mesajda unite ADEDI VERILMEZ (spec §7.9): kullanici sayiyi zaten GET ile
    goruyor, hata govdesi gorunurluk disi bilgi tasimaz.
    """
    block, _ = await _visible_block(session, actor, block_id)
    if await repository.block_has_units(session, block.id):
        raise RelatedRecordsExistError(_BLOCK_HAS_UNITS)
    await session.delete(block)
    await session.flush()


# --- Toplu uretim (spec §6.3, §7.7) — ATOMIKLIK SINIFI ---


async def bulk_create_units(
    session: AsyncSession, actor: User, project_id: uuid.UUID, data: UnitBulkCreate
) -> UnitListResponse:
    """Spec §7.7. HEP-YA-HIC: kismi yazma OLMAZ.

    Sira KATIDIR ve degistirilemez — her dogrulama ilk `session.add`'DEN ONCE
    biter, boylece reddedilen istek tek satir bile yazmaz:

    1. proje gorunurlugu (404) ve blogun bu projeye ait olmasi (404, IDOR-9)
    2. ortak varsayilanlarin alan kurallari (`net > brut` → 422); tekil POST ile
       AYNI kural, cunku ayni sutunlara yaziyoruz
    3. uretilecek numaralarin tamami (saf fonksiyon, DB'ye dokunmaz)
    4. blokta mevcut numaralarla kesisim — TEK `SELECT` (`existing_unit_nos`);
       kesisim bossa DEGILSE hicbir `INSERT` yapilmadan 409

    Ardindan tum satirlar tek `add_all` + tek `flush` ile yazilir. `get_db`
    istek basina tek transaction acar; bir istisna cikarsa rollback eder —
    dolayisiyla 4. adimdan sonra olusabilecek bir yaris durumu (ayni anda ayni
    numarayi yazan ikinci istek) `uq_units_block_no` ihlaline duser ve
    `IntegrityError → 409` handler'i TUM parti geri alinmis hâlde yanit verir.

    `owner_side` UYGULANMAZ: `UnitBulkCreate` semasinda boyle bir alan YOKTUR
    (spec §6.3) — uretilen tum uniteler pay atanmamis baslar (§5.3), bu da §3.3
    korkulugunu her proje tipinde yapisal olarak saglar.
    """
    project = await _visible_project(session, actor, project_id)
    block = await _block_in_project(session, project, data.block_id)
    _ensure_net_le_gross(data.gross_area_m2, data.net_area_m2)

    numbers = generate_unit_numbers(data)
    taken = await repository.existing_unit_nos(session, block.id, numbers)
    if taken:
        # Uretim sirasi KORUNUR (kume sirasi degil): kullanici hangi araligin
        # cakistigini ancak sirali listede gorebilir.
        conflicting = [number for number in numbers if number in taken]
        listed = ", ".join(conflicting[:_MAX_CONFLICT_NUMBERS])
        raise DuplicateError(f"{_BULK_NUMBERS_TAKEN}: {listed}")

    next_sort_order = await repository.max_sort_order(session, block.id) + 1
    session.add_all(
        [
            Unit(
                project_id=project.id,
                block_id=block.id,
                unit_no=number,
                unit_kind=data.unit_kind,
                layout=data.layout,
                gross_area_m2=data.gross_area_m2,
                net_area_m2=data.net_area_m2,
                list_price=data.list_price,
                appraisal_value=data.appraisal_value,
                sort_order=next_sort_order + offset,
            )
            for offset, number in enumerate(numbers)
        ]
    )
    await session.flush()
    return await list_units(session, actor, project_id)


# --- Excel ice aktarma (spec §6.4, §7.8) — HEP-YA-HIC + SATIR BAZLI RAPOR ---


def _row_error(error: RowError) -> UnitImportRowError:
    return UnitImportRowError(row=error.row, column=error.column, message=error.message)


def _raise_row_errors(errors: list[RowError]) -> None:
    """Spec §7.8: HICBIR satir yazilmaz, ama kullanici tum hatalari TEK seferde gorur.

    "Ilk hatada dur" 48 satirlik bir dosyayi 48 kez yuklemeye zorlardi; yarim
    yazma ise dosyayi duzeltip yeniden yuklemeyi imkânsiz kilardi (basarili
    satirlar artik cakisir). Ikisi birlikte uygulanir.
    """
    if not errors:
        return
    ordered = sorted(errors, key=lambda error: error.row)
    remaining = len(ordered) - MAX_REPORTED_ERRORS
    raise UnitImportError(
        IMPORT_ROW_ERRORS.format(count=len({error.row for error in ordered})),
        [_row_error(error).model_dump() for error in ordered[:MAX_REPORTED_ERRORS]],
        f"Ve {remaining} hata daha" if remaining > 0 else None,
    )


def _domain_row_errors(
    project: Project, rows: list[ImportRow], taken: dict[str, set[str]]
) -> list[RowError]:
    """Tekil `POST` ile AYNI alan kurallari, satir satir uygulanir.

    Bu kurallar bilerek `importer.py`'de DEGIL: `net > brut` ve `owner_side`
    korkulugu tek yazma yolunun kurallaridir (`_ensure_net_le_gross`,
    `_ensure_owner_side_allowed`) ve ice aktarma onlari KOPYALAMAZ, CAGIRIR.
    """
    errors: list[RowError] = []
    for row in rows:
        try:
            _ensure_net_le_gross(row.gross_area_m2, row.net_area_m2)
        except UnitValidationError as exc:
            errors.append(RowError(row.row, "Net m²", str(exc)))
        try:
            _ensure_owner_side_allowed(project, row.owner_side)
        except ProjectTypeMismatchError as exc:
            errors.append(RowError(row.row, "Pay", str(exc)))
        if row.unit_no in taken.get(normalize_header(row.block_name), set()):
            errors.append(RowError(row.row, "Ünite No", _DUPLICATE_UNIT))
    return errors


async def import_units(
    session: AsyncSession, actor: User, project_id: uuid.UUID, content: bytes
) -> UnitImportResult:
    """Spec §7.8. Dosya BELLEKTE islenir ve ATILIR — diske/S3'e/DB'ye yazilmaz.

    Sira KATIDIR (bulk ile ayni gerekce): her dogrulama ilk `session.add`'DEN
    ONCE biter, boylece reddedilen bir dosya tek satir bile — tek BLOK bile —
    yazmaz:

    1. proje gorunurlugu (404)
    2. dosya duzeyi kontroller (tip/boyut/satir sayisi/eksik baslik) → 422
    3. satir cozumleme hatalari (saf, DB'siz)
    4. alan kurallari + blokta mevcut `unit_no` (tek `SELECT`'ten gelen kume)
    5. yeni blok adlari icin §4.5 santiye kurali
    6. bloklar ve uniteler tek `add_all` + tek `flush`

    Blok adi NORMALLESTIRILEREK eslesir (`normalize_header`): dosyada "a blok"
    yazan kullanici mevcut "A Blok"a yazar. Aksi hâlde `uq_blocks_project_name`
    ihlaline dusup anlamsiz bir 409 alirdi.
    """
    project = await _visible_project(session, actor, project_id)
    try:
        rows, parse_errors = parse_units_file(content)
    except ImportFileError as exc:
        # Dosyanin TAMAMINI reddeden hata: satir listesi yok, tek Turkce mesaj.
        raise UnitValidationError(str(exc)) from exc
    _raise_row_errors(parse_errors)

    blocks = {
        normalize_header(block.name): block
        for block, _ in await repository.list_blocks_for_project(session, project.id)
    }
    units = await repository.list_units_for_project(session, project.id)
    by_block_id = {block.id: key for key, block in blocks.items()}
    taken: dict[str, set[str]] = {key: set() for key in blocks}
    for unit in units:
        taken[by_block_id[unit.block_id]].add(unit.unit_no)

    _raise_row_errors(_domain_row_errors(project, rows, taken))

    new_names = [row.block_name for row in rows if normalize_header(row.block_name) not in blocks]
    created_blocks: list[Block] = []
    if new_names:
        # Santiye TEK KEZ cozulur: dosyada santiye sutunu yoktur, dolayisiyla tum
        # yeni bloklar ayni §4.5 kuralina tabidir (cok santiyeli projede 422).
        site = await _resolve_site(session, project.id, None)
        for name in new_names:
            key = normalize_header(name)
            if key in blocks:
                continue
            block = Block(project_id=project.id, site_id=site.id, name=name)
            session.add(block)
            blocks[key] = block
            created_blocks.append(block)
        await session.flush()

    # Yeni satirlar blok icinde MEVCUTLARIN ARDINA eklenir (bulk ile ayni gerekce):
    # sifirdan baslasaydi yari dolu bir blokta eski ve yeni uniteler ic ice
    # gecerdi — `unit_no` metin oldugu icin ikincil sira "10 < 2" verir.
    next_sort: dict[str, int] = {}
    for unit in units:
        key = by_block_id[unit.block_id]
        next_sort[key] = max(next_sort.get(key, 0), int(unit.sort_order) + 1)

    new_units: list[Unit] = []
    for row in rows:
        key = normalize_header(row.block_name)
        offset = next_sort.get(key, 0)
        next_sort[key] = offset + 1
        new_units.append(
            Unit(
                project_id=project.id,
                block_id=blocks[key].id,
                unit_no=row.unit_no,
                unit_kind=row.unit_kind,
                layout=row.layout,
                gross_area_m2=row.gross_area_m2,
                net_area_m2=row.net_area_m2,
                list_price=row.list_price,
                appraisal_value=row.appraisal_value,
                owner_side=row.owner_side,
                sort_order=offset,
            )
        )
    session.add_all(new_units)
    await session.flush()
    return UnitImportResult(created=len(rows), blocks_created=len(created_blocks), errors=[])
