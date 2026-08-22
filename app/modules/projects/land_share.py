"""P-KK — kat karşılığı paylaşım özeti + ünite listesi (iki OKUMA ucunun gövdesi).

## Neden `land_share_balance.py`dan ayrı

`cost_summary.py` ↔ `costs.py` ayrımının aynısı: `land_share_balance` SAF hesap
çekirdeğidir (oturumsuz, yetkisiz sınanabilir); burası oturuma, görünürlük
süzgecine ve şemalara dokunan ORKESTRASYON katmanıdır. Formüller BURADA YENİDEN
YAZILMAZ; her oran çekirdekten çağrılır.

## Görünürlük

Kapsam kapısı `service._visible_project`tir — TEK kimlik-ile-erişim kapısı
(P1 spec §5.6), `cost_summary` ile AYNI çağrı. Görünmeyen proje ile var olmayan
proje AYIRT EDİLEMEZ 404 verir. Kat karşılığı kaydı OLMAYAN proje de 404 alır,
boş özet DEĞİL: boş özet ekrana "%0/%0 paylaşım" bastırır ve kullanıcı veriyi
kaybettiğini sanardı.

## N+1 (WORKFLOW §4)

Yanıt SABİT sayıda sorgu koşar; ünite sayısı sorgu sayısını BÜYÜTMEZ:

1. görünür projeler (`land_share` + `shareholders` `lazy="selectin"` ile
   birlikte gelir — hissedar adı için EK sorgu YOKTUR)
2. bloklar + şantiye adı (tek JOIN)
3. üniteler (tek sorgu)
4. açık satışlar + müşteri adı (tek JOIN) — yalnız ünite listesi ucunda

Ünite başına `session.get(LandShareShareholder, ...)` 400 ünitede 400 gidiş-
dönüş demekti. Aynı gerekçeyle alıcı adı da tek JOIN'den gelir.

## Async tuzağı (P11 kanonu)

Bu modül ORM koleksiyonlarına yalnız `await`li bir çağrının DÖNÜŞÜNDEN sonra
dokunur ve `project.shareholders`/`project.land_share` `lazy="selectin"`dir —
tembel yükleme senkron bağlamda tetiklenmez (`MissingGreenlet` → 500).

## Çelişkili veri: `owner_side=contractor` iken `shareholder_id` dolu

KARAR: **ünite `owner_side`ına göre sayılır, hissedar dağılımına GİRMEZ.**

`units/batch.py` bu bileşimi yazma yolunda zaten 422 ile reddeder ve taraf
değişince hissedarı aynı istekte temizler; yani çelişki ancak elle/eski veriden
gelebilir. Sayımı `shareholder_id`ye dayandırmak "bizim pay" ünitesini arsa
sahibinin hissedar dağılımına sokardı ve `our_side.unit_count` ile hissedar
toplamı aynı üniteyi İKİ KEZ sayardı. `owner_side` otoritedir; hissedar
dağılımı YALNIZ `landowner` satırlarını toplar.

Ünite LİSTESİ ise `shareholder_name`i OLDUĞU GİBİ basar — ekranın görevi veriyi
düzeltmek değil göstermektir; çelişki ancak görünürse düzeltilebilir.
"""

import uuid
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.modules.projects import land_share_balance as balance
from app.modules.projects import service, unit_sides
from app.modules.projects.land_share_schemas import (
    LandShareBalance,
    LandShareContract,
    LandShareOurSide,
    LandShareOwnerSide,
    LandSharePartition,
    LandShareShareholderRow,
    LandShareSummaryResponse,
    LandShareUnitListResponse,
    LandShareUnitRow,
)
from app.modules.projects.models import Project
from app.modules.units import repository as units_repository
from app.modules.units.models import Unit, UnitSalesStatus
from app.modules.units.schemas import UnitOwnerSideFilter
from app.modules.units.summary import VALUE_BASIS_BY_TYPE, basis_value
from app.modules.users.models import User

# Görünmeyen proje ile kat karşılığı OLMAYAN proje AYNI metni almaz: birincisi
# varlığı sızdırmama kuralıdır (`_visible_project`), ikincisi görünen bir
# projenin gerçek durumudur ve kullanıcıya söylenebilir.
LAND_SHARE_MISSING = "Bu proje kat karşılığı değil, paylaşım özeti yok"

_MONEY = Decimal("0.01")


def _sum_values(units: list[Unit], basis) -> Decimal:  # noqa: ANN001 - UnitValueBasis
    """NULL rayiç 0 SAYILIR (`units/summary._sum` ile aynı kural) ve toplama
    `Decimal` ile yapılır — float ASLA."""
    total = sum(
        (value for value in (basis_value(u, basis) for u in units) if value is not None),
        Decimal("0"),
    )
    return total.quantize(_MONEY, rounding=ROUND_HALF_UP)


def _contract(project: Project) -> LandShareContract:
    land_share = project.land_share
    assert land_share is not None  # noqa: S101 - çağıran 404 kapısını geçti
    return LandShareContract(
        landowner_name=land_share.landowner_name,
        our_share_pct=land_share.our_share_pct,
        owner_share_pct=land_share.owner_share_pct,
        contract_no=land_share.contract_no,
        notary_date=land_share.notary_date,
        land_area_m2=land_share.land_area_m2,
        construction_area_m2=land_share.construction_area_m2,
        delivery_date=land_share.delivery_date,
        daily_penalty=land_share.daily_penalty,
        guarantee_amount=land_share.guarantee_amount,
    )


def _our_side(units: list[Unit], basis) -> LandShareOurSide:  # noqa: ANN001
    """Satış kırılımı YALNIZ bizim tarafta (arsa sahibi ünitelerini kendi satar).

    `available_count` yalnız `listed` sayar; `closed` ve NULL hiçbir sayaca
    girmez — uydurulmuş durum atanmaz. `remaining_value` ise tüm satılmamış
    stoku kapsar (`value_total − sold_value`), rezerve dahil: mockup "23 ünite,
    8 satıldı → Kalan Stok 15 ünite" der.
    """
    value_total = _sum_values(units, basis)
    sold = [u for u in units if u.sales_status is UnitSalesStatus.sold]
    sold_value = _sum_values(sold, basis)
    return LandShareOurSide(
        unit_count=len(units),
        value_total=value_total,
        sold_count=len(sold),
        reserved_count=sum(1 for u in units if u.sales_status is UnitSalesStatus.reserved),
        available_count=sum(1 for u in units if u.sales_status is UnitSalesStatus.listed),
        sold_value=sold_value,
        remaining_value=value_total - sold_value,
    )


def _shareholder_rows(
    project: Project, landowner_units: list[Unit], basis
) -> list[LandShareShareholderRow]:  # noqa: ANN001
    """Hissedar dağılımı — hissedarı OLMAYAN arsa ünitesi hiçbir satıra girmez.

    Sıra `Project.shareholders`ten gelir (`order_by=name`, `lazy="selectin"`):
    ikinci bir sıralama kuralı icat edilmez. Ünitesi olmayan hissedar da LİSTEDE
    KALIR (0 ünite) — mockup üç hissedarı her hâlükârda basar.

    `share_pct` OLDUĞU GİBİ döner; toplamı 100 değilse uç düzeltmez.
    """
    by_shareholder: dict[uuid.UUID, list[Unit]] = defaultdict(list)
    for unit in landowner_units:
        if unit.shareholder_id is not None:
            by_shareholder[unit.shareholder_id].append(unit)
    return [
        LandShareShareholderRow(
            shareholder_id=row.id,
            name=row.name,
            share_pct=row.share_pct,
            unit_count=len(by_shareholder.get(row.id, [])),
            value_total=_sum_values(by_shareholder.get(row.id, []), basis),
        )
        for row in project.shareholders
    ]


async def _land_share_project(session: AsyncSession, actor: User, project_id: uuid.UUID) -> Project:
    project = await service._visible_project(session, actor, project_id)
    if project.land_share is None:
        raise NotFoundError(LAND_SHARE_MISSING)
    return project


async def get_summary(
    session: AsyncSession, actor: User, project_id: uuid.UUID
) -> LandShareSummaryResponse:
    """`GET /projects/{id}/land-share/summary` — üç mockup'ın üst bloklarının kaynağı."""
    project = await _land_share_project(session, actor, project_id)
    units = await units_repository.list_units_for_project(session, project.id)
    basis = VALUE_BASIS_BY_TYPE[project.project_type]

    # Üç küme AYRIKTIR ve toplamları TÜM üniteye eşittir: atanmamış üniteler
    # (`owner_side IS NULL`) ne bizim paya ne arsa payına sayılır. Ayrımın kendisi
    # `unit_sides`tedir — E4 kartının taraf sayaçları ile AYNI yüklemi kullanır,
    # aksi hâlde kart ve bu uç aynı proje için farklı sayı söyleyebilirdi.
    sides = unit_sides.partition(units)

    our_side = _our_side(sides.ours, basis)
    owner_value = _sum_values(sides.owner, basis)
    return LandShareSummaryResponse(
        project_id=project.id,
        project_name=project.name,
        contract=_contract(project),
        totals=LandSharePartition(unit_count=len(units), value_total=_sum_values(units, basis)),
        our_side=our_side,
        owner_side=LandShareOwnerSide(unit_count=len(sides.owner), value_total=owner_value),
        shareholders=_shareholder_rows(project, sides.owner, basis),
        unassigned=LandSharePartition(
            unit_count=len(sides.unassigned), value_total=_sum_values(sides.unassigned, basis)
        ),
        balance=LandShareBalance(
            count_balance=balance.count_balance(
                total_unit_count=len(units),
                our_assigned_count=len(sides.ours),
                owner_assigned_count=len(sides.owner),
                our_share_pct=project.land_share.our_share_pct,
            ),
            value_balance=balance.value_balance(
                our_value=our_side.value_total,
                owner_value=owner_value,
                our_share_pct=project.land_share.our_share_pct,
            ),
        ),
    )


def _matches(unit: Unit, block_name: str, side: UnitOwnerSideFilter | None, q: str | None) -> bool:
    """Süzgeçler YALNIZ listeyi daraltır; `summary` daima projenin tamamını sayar.

    `unassigned` sütunda saklanan bir durum DEĞİL yalnızca sorgu dilidir, bu
    yüzden `UnitOwnerSideFilter` kullanılır (`units` modülüyle AYNI süzgeç
    sözlüğü — ikinci bir filtre dili icat edilmez).
    """
    if side is UnitOwnerSideFilter.unassigned:
        if not unit_sides.is_unassigned(unit):
            return False
    elif side is not None and (
        unit_sides.is_unassigned(unit) or unit.owner_side.value != side.value
    ):
        return False
    if q is not None:
        needle = q.casefold()
        if needle not in unit.unit_no.casefold() and needle not in block_name.casefold():
            return False
    return True


async def list_units(
    session: AsyncSession,
    actor: User,
    project_id: uuid.UUID,
    *,
    owner_side: UnitOwnerSideFilter | None = None,
    block_id: uuid.UUID | None = None,
    q: str | None = None,
    limit: int,
    offset: int,
) -> LandShareUnitListResponse:
    """`GET /projects/{id}/land-share/units` — mockup'ın orta tablosu, SAYFALI.

    Sayfalama süzgeçten SONRA uygulanır ve `total` süzgeçlenmiş kümenin
    boyutudur (sayfalamadan önce) — `ProjectListResponse` ile aynı sözleşme.

    Kesme Python'da yapılır çünkü satırlar ZATEN tek sorguda gelen listeden
    türer (`units` modülünün her okuma ucuyla aynı desen); ikinci bir sıralama/
    sayfalama kuralı SQL'e yazılsaydı iki uç aynı üniteyi farklı sırada
    gösterebilirdi.
    """
    project = await _land_share_project(session, actor, project_id)
    blocks = await units_repository.list_blocks_for_project(session, project.id)
    units = await units_repository.list_units_for_project(session, project.id)
    block_names = {block.id: block.name for block, _ in blocks}
    # Hissedar adları EK SORGU AÇMADAN gelir: koleksiyon görünürlük sorgusuyla
    # zaten yüklendi (`lazy="selectin"`).
    shareholder_names = {row.id: row.name for row in project.shareholders}
    # Alıcı adı (mockup "Hissedar / Alıcı" sütunu) TEK JOIN'den — ünite başına
    # satış sorgusu 400 ünitede 400 gidiş-dönüş demekti.
    buyers = {
        sale.unit_id: customer.name
        for sale, customer in await units_repository.list_open_sales_for_project(
            session, project.id
        )
    }

    selected = [
        unit
        for unit in units
        if (block_id is None or unit.block_id == block_id)
        and _matches(unit, block_names.get(unit.block_id, ""), owner_side, q)
    ]
    return LandShareUnitListResponse(
        items=[
            LandShareUnitRow(
                unit_id=unit.id,
                block_id=unit.block_id,
                block_name=block_names.get(unit.block_id, ""),
                unit_no=unit.unit_no,
                unit_kind=unit.unit_kind,
                layout=unit.layout,
                floor=unit.floor,
                gross_area_m2=unit.gross_area_m2,
                appraisal_value=unit.appraisal_value,
                owner_side=unit.owner_side,
                shareholder_id=unit.shareholder_id,
                # OLDUĞU GİBİ basılır — çelişkili satır (bkz. dosya başlığı)
                # ancak görünürse düzeltilebilir.
                shareholder_name=(
                    shareholder_names.get(unit.shareholder_id)
                    if unit.shareholder_id is not None
                    else None
                ),
                buyer_name=buyers.get(unit.id),
                sales_status=unit.sales_status,
            )
            for unit in selected[offset : offset + limit]
        ],
        total=len(selected),
        limit=limit,
        offset=offset,
    )
