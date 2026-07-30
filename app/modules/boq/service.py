import uuid
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BoqGroupSiteMismatchError, DuplicateError, NotFoundError
from app.modules.boq import repository
from app.modules.boq.models import BoqGroup, BoqItem
from app.modules.boq.schemas import (
    BoqGroupCreate,
    BoqGroupResponse,
    BoqGroupUpdate,
    BoqItemCreate,
    BoqItemResponse,
    BoqItemUpdate,
    BoqListResponse,
    BoqTotals,
    MetricPlaceholder,
)

# Gorunurluk suzgeci P2'DEN GELIR (plan T3 notu): site->proje cozumu kopyalanmaz,
# `sites.service._visible_site` yeniden kullanilir. Ayni desen zaten
# `projects.service`'in `sites.service._next_site_code`'u yeniden
# kullanmasinda var (bkz. app/modules/projects/service.py).
from app.modules.sites.models import Site
from app.modules.sites.service import _visible_site
from app.modules.users.models import User

# Spec §5.4 Turkce hata metinleri. Grup/kalem "yok" ile "gorunmuyor" ayni
# mesaji doner (P2 §5.2 deseninin devami, bkz. sites.service _visible_section) —
# kaydin varligi sizdirilmaz.
_GROUP_MISSING = "İş kalemi grubu bulunamadı"
_ITEM_MISSING = "İş kalemi bulunamadı"
_GROUP_SITE_MISMATCH = "Grup bu şantiyeye ait değil"
_DUPLICATE_CODE = "Bu poz numarası bu şantiyede zaten kullanılıyor"

# Spec §3.2/§5.1: bu dilimde YAZILMAYAN turev alanlarin bagli oldugu modul
# anahtarlari. Kullaniciya gosterilecek metin degil, B6 sozlesmesindeki
# pending_module anahtaridir.
_CONTRACTS = "contracts"
_PROGRESS_PAYMENTS = "progress_payments"

_MONEY = Decimal("0.01")


def _quantize_money(value: Decimal) -> Decimal:
    return value.quantize(_MONEY, rounding=ROUND_HALF_UP)


def _metric(pending_module: str) -> MetricPlaceholder:
    return MetricPlaceholder(pending_module=pending_module)


def to_item(item: BoqItem) -> BoqItemResponse:
    return BoqItemResponse(
        id=item.id,
        code=item.code,
        description=item.description,
        unit=item.unit,
        quantity=item.quantity,
        unit_price=item.unit_price,
        progress_pct=_metric(_PROGRESS_PAYMENTS),
        sort_order=item.sort_order,
    )


def to_group(group: BoqGroup) -> BoqGroupResponse:
    return BoqGroupResponse(
        id=group.id,
        name=group.name,
        sort_order=group.sort_order,
        items=[to_item(item) for item in group.items],
    )


def _totals(groups: list[BoqGroupResponse]) -> BoqTotals:
    """Spec §5.1: `grand_total` GERCEK (gruplarin toplami), geri kalani yer
    tutucu. Toplama Decimal ile yapilir (float ASLA); bos BOQ "0.00" doner."""
    grand_total = _quantize_money(sum((group.group_total for group in groups), Decimal("0")))
    return BoqTotals(
        contract_total=_metric(_CONTRACTS),
        realized_total=_metric(_PROGRESS_PAYMENTS),
        remaining_total=_metric(_PROGRESS_PAYMENTS),
        revision_total=_metric(_CONTRACTS),
        grand_total=grand_total,
        grand_progress_pct=_metric(_PROGRESS_PAYMENTS),
    )


async def get_boq_export_for_site(
    session: AsyncSession, actor: User, site_id: uuid.UUID
) -> tuple[Site, BoqListResponse]:
    """Spec §5.1/§5.3 ortak okuma yolu. Gorunmeyen santiye 404 doner (P2 §5.2
    deseni), 403 degil — varligin kendisi sizdirilmaz. `Site` de donulur:
    T8 disa aktarim ucu dosya adi icin `site.code`'a ihtiyac duyar."""
    site, _ = await _visible_site(session, actor, site_id)
    groups = [to_group(group) for group in await repository.list_groups_for_site(session, site.id)]
    return site, BoqListResponse(totals=_totals(groups), groups=groups)


async def get_boq_for_site(
    session: AsyncSession, actor: User, site_id: uuid.UUID
) -> BoqListResponse:
    """Spec §5.1 okuma yolu — `get_boq_export_for_site`'in ince sarmalayicisi."""
    _, response = await get_boq_export_for_site(session, actor, site_id)
    return response


# --- Gorunurluk — yazma uclari icin yukari cozumleme (spec §5.5) ---


async def _visible_group(
    session: AsyncSession, actor: User, group_id: uuid.UUID
) -> tuple[BoqGroup, Site]:
    """Grup -> santiye -> proje. PATCH /boq/groups/{id} bu zincirden gecer;

    gorunmeyen kayit 404 doner, 403 DEGIL (P2 IDOR dersi, spec §5.5) — en kolay
    atlanan guvenlik noktasi budur.
    """
    group = await repository.get_group(session, group_id)
    if group is None:
        raise NotFoundError(_GROUP_MISSING)
    site, _ = await _visible_site(session, actor, group.site_id, _GROUP_MISSING)
    return group, site


async def _visible_item(
    session: AsyncSession, actor: User, item_id: uuid.UUID
) -> tuple[BoqItem, Site]:
    """Kalem -> santiye -> proje (item.site_id dogrudan tutulur, spec §5.5:

    "item→site→project"). Gorunmeyen kayit 404 doner, 403 DEGIL.
    """
    item = await repository.get_item(session, item_id)
    if item is None:
        raise NotFoundError(_ITEM_MISSING)
    site, _ = await _visible_site(session, actor, item.site_id, _ITEM_MISSING)
    return item, site


async def _ensure_group_in_site(session: AsyncSession, group_id: uuid.UUID, site: Site) -> BoqGroup:
    """Spec §3.3 invariant 1: kalemin baglandigi grubun site_id'si kalemin

    site_id'si ile ayni olmali. Grup hic yoksa da (spec §5.5 IDOR-2) ayni 422
    ile karsilanir — varliginin gizli tutulmasi gerekmez, cunku site zaten
    gorunurluk suzgecinden gecmis; yalnizca ait olmadigi bir grup enjekte
    edilmesi engellenir.
    """
    group = await repository.get_group(session, group_id)
    if group is None or group.site_id != site.id:
        raise BoqGroupSiteMismatchError(_GROUP_SITE_MISMATCH)
    return group


async def _ensure_code_unique(
    session: AsyncSession, site_id: uuid.UUID, code: str, exclude_item_id: uuid.UUID | None = None
) -> None:
    """Spec §3.3 invariant 2 / §5.4: (site_id, code) çakışması → 409, Türkçe

    mesaj. IntegrityError → 409 handler'ı yarış durumu emniyet ağı olarak KALIR
    (DuplicateError deseni, `projects.service.create_employer` emsali).
    """
    existing = await repository.get_item_by_code(session, site_id, code, exclude_item_id)
    if existing is not None:
        raise DuplicateError(_DUPLICATE_CODE)


# --- Yazma uclari (T5/T6) ---


async def create_group(
    session: AsyncSession, actor: User, site_id: uuid.UUID, data: BoqGroupCreate
) -> BoqGroup:
    site, _ = await _visible_site(session, actor, site_id)
    group = BoqGroup(site_id=site.id, name=data.name, sort_order=data.sort_order)
    session.add(group)
    await session.flush()
    await session.refresh(group)
    return group


async def create_item(
    session: AsyncSession, actor: User, site_id: uuid.UUID, data: BoqItemCreate
) -> BoqItem:
    """Spec §5.5 IDOR-2: govdedeki `group_id` baska santiyenin grubu olabilir —

    yol parametresi `site_id` ile karsi karsiya konur, uyusmazlik 422 doner.
    """
    site, _ = await _visible_site(session, actor, site_id)
    group = await _ensure_group_in_site(session, data.group_id, site)
    await _ensure_code_unique(session, site.id, data.code)
    item = BoqItem(
        site_id=site.id,
        group_id=group.id,
        code=data.code,
        description=data.description,
        unit=data.unit,
        quantity=data.quantity,
        unit_price=data.unit_price,
        sort_order=data.sort_order,
    )
    session.add(item)
    await session.flush()
    await session.refresh(item)
    return item


async def update_group(
    session: AsyncSession, actor: User, group_id: uuid.UUID, data: BoqGroupUpdate
) -> BoqGroup:
    group, _ = await _visible_group(session, actor, group_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(group, field, value)
    await session.flush()
    await session.refresh(group)
    return group


async def update_item(
    session: AsyncSession, actor: User, item_id: uuid.UUID, data: BoqItemUpdate
) -> BoqItem:
    """`group_id` verilirse spec §3.3 invariant 1/4 tekrar kontrol edilir

    (baska santiyenin grubuna tasima yasak); `code` degisirse §invariant 2
    tekrar kontrol edilir. `site_id` semada yok — tasima ucu kapali.
    """
    item, site = await _visible_item(session, actor, item_id)
    updates = data.model_dump(exclude_unset=True)
    if "group_id" in updates:
        await _ensure_group_in_site(session, updates["group_id"], site)
    if "code" in updates and updates["code"] != item.code:
        await _ensure_code_unique(session, site.id, updates["code"], exclude_item_id=item.id)
    for field, value in updates.items():
        setattr(item, field, value)
    await session.flush()
    await session.refresh(item)
    return item


async def delete_item(session: AsyncSession, actor: User, item_id: uuid.UUID) -> tuple[str, str]:
    """Kalemi siler; denetim satiri icin (code, description) doner.

    Kimlik silmeden ONCE okunur — sonra okunursa satir yoktur (users/roles
    silme uclarindaki desen). Gorunmeyen kayit `_visible_item` uzerinden 404
    doner, 403 DEGIL: var olmayan UUID ile ayirt edilemez olmasi gerekir.

    Satir silindikten sonra grubun `items` koleksiyonu ELDEN CIKARILIR
    (`expire`): koleksiyon zaten yuklenmisse silme onu BAYAT birakir ve ayni
    oturumda BOQ yeniden okundugunda kalem hâlâ listede gorunup `grand_total`
    degismemis gibi doner. `expire` IO yapmaz, yalnizca bir sonraki erisimde
    yeniden yuklenmesini saglar. Grubun kendisi SILINMEZ; santiye toplamlari
    kalan kalemlerden yeniden turedigi icin ayrica guncelleme gerekmez.
    """
    item, _ = await _visible_item(session, actor, item_id)
    identity = (item.code, item.description)
    group_id = item.group_id
    await session.delete(item)
    await session.flush()
    group = await repository.get_group(session, group_id)
    if group is not None:
        session.expire(group, ["items"])
    return identity
