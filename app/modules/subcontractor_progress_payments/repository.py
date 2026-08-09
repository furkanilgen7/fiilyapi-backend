"""Taşeron hakedişi okuma/yazma sorguları (T2).

`progress_payments/repository.py` deseninin aynısı: filtreler SQL düzeyinde
uygulanır, kapsam (`visible_project_ids`) HER ZAMAN çağıran servisten gelir —
bu modül KENDİSİ görünürlük kararı VERMEZ (spec §9.0 iki katman kuralı).

Tek yapısal fark: sayaç ve "açık hakediş" kilidi PROJE değil **SÖZLEŞME**
kapsamlıdır (spec §2, mockup #47/#48).
"""

import uuid
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.contracts.models import SubcontractorContract, SubcontractorContractItem
from app.modules.projects.models import Project
from app.modules.sites.models import Section, Site
from app.modules.subcontractor_progress_payments.models import (
    SubcontractorPaymentStatus,
    SubcontractorProgressPayment,
)

# "Açık" hakediş: henüz sonuçlanmamış taslak veya onay bekleyen (spec §5) —
# aynı sözleşmede ikincisi açılamaz.
OPEN_STATUSES = (SubcontractorPaymentStatus.draft, SubcontractorPaymentStatus.pending_approval)

# Kümülatif muhasebeye giren durumlar (kota tavanı §4, avans zinciri §3).
COMPLETED_STATUSES = (SubcontractorPaymentStatus.approved, SubcontractorPaymentStatus.paid)

PaymentRow = tuple[SubcontractorProgressPayment, SubcontractorContract, Project]


async def get_payment(
    session: AsyncSession, payment_id: uuid.UUID
) -> SubcontractorProgressPayment | None:
    """`lines` `lazy="selectin"` olduğu için ek sorgu YOK."""
    return await session.get(SubcontractorProgressPayment, payment_id)


async def get_payment_locked(
    session: AsyncSession, payment_id: uuid.UUID
) -> SubcontractorProgressPayment | None:
    """`SELECT … FOR UPDATE`. `populate_existing=True` ZORUNLUDUR (işveren

    `get_payment_locked` gerekçesinin aynısı): kimlik haritasındaki ESKİ nesne
    dönerse kilit alınmış ama DURUM eski değerinden okunmuş olur — var gibi
    görünen, aslında olmayan bir koruma.
    """
    return await session.get(
        SubcontractorProgressPayment, payment_id, with_for_update=True, populate_existing=True
    )


async def get_contract_locked(
    session: AsyncSession, contract_id: uuid.UUID
) -> SubcontractorContract | None:
    """`sequence_no` üretimi + açık-hakediş kontrolünün dayandığı kilit satırı.

    Aynı sözleşmede iki eşzamanlı `POST` burada sıraya girer; ikisi de aynı
    `sequence_no`'yu üretemez ve açık-hakediş kontrolünü aynı anda geçemez.
    """
    stmt = (
        select(SubcontractorContract)
        .where(SubcontractorContract.id == contract_id)
        .with_for_update(of=SubcontractorContract)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_open_payment(
    session: AsyncSession, contract_id: uuid.UUID
) -> SubcontractorProgressPayment | None:
    """`get_contract_locked` ile AYNI transaction'da, kilit ALINDIKTAN SONRA
    çağrılmalıdır — aksi hâlde iki eşzamanlı `POST` bu kontrolü boşken geçebilir."""
    stmt = select(SubcontractorProgressPayment).where(
        SubcontractorProgressPayment.contract_id == contract_id,
        SubcontractorProgressPayment.status.in_(OPEN_STATUSES),
    )
    return (await session.execute(stmt)).scalars().first()


async def get_next_sequence_no(session: AsyncSession, contract_id: uuid.UUID) -> int:
    """SÖZLEŞME içi maks+1 (işverendeki proje içi sayacın karşılığı, spec §2)."""
    stmt = select(func.max(SubcontractorProgressPayment.sequence_no)).where(
        SubcontractorProgressPayment.contract_id == contract_id
    )
    return ((await session.execute(stmt)).scalar_one_or_none() or 0) + 1


async def get_section_with_site(
    session: AsyncSession, section_id: uuid.UUID
) -> tuple[Section, Site] | None:
    """Bölüm + şantiyesi TEK sorguda — `section_id` sahiplik kontrolü (spec §8 S2)."""
    stmt = (
        select(Section, Site).join(Site, Site.id == Section.site_id).where(Section.id == section_id)
    )
    row = (await session.execute(stmt)).first()
    return (row[0], row[1]) if row is not None else None


async def get_contract_items_by_ids(
    session: AsyncSession, item_ids: list[uuid.UUID]
) -> dict[uuid.UUID, SubcontractorContractItem]:
    """Satır yazma/tazeleme yolunun TOPLU kalem çekimi — satır başına sorgu YOK."""
    if not item_ids:
        return {}
    stmt = select(SubcontractorContractItem).where(SubcontractorContractItem.id.in_(item_ids))
    return {item.id: item for item in (await session.execute(stmt)).scalars().all()}


async def get_contract_amount(session: AsyncSession, contract_id: uuid.UUID) -> Decimal:
    """Sözleşme bedeli = `Σ quantity × unit_price` (spec §3 avans tavanı).

    Taşeron sözleşmesinde `amount` KOLONU YOKTUR (K3 türev ilkesi, `contracts`
    modülünün kararı) — bedel her okuyuşta kalemlerden türer.

    Fiyatsız kalem (`unit_price IS NULL`) toplama GİRMEZ: "girilmedi ≠ 0 TL"
    kuralı burada da geçerlidir; NULL'u 0 saymak tavanı SESSİZCE düşürürdü.
    """
    return (await get_contract_amounts(session, [contract_id])).get(contract_id, Decimal("0.00"))


async def get_contract_amounts(
    session: AsyncSession, contract_ids: list[uuid.UUID]
) -> dict[uuid.UUID, Decimal]:
    """`get_contract_amount`ın TOPLU hâli — liste ucu sözleşme başına sorgu KOŞMAZ."""
    if not contract_ids:
        return {}
    stmt = (
        select(
            SubcontractorContractItem.contract_id,
            func.sum(SubcontractorContractItem.quantity * SubcontractorContractItem.unit_price),
        )
        .where(
            SubcontractorContractItem.contract_id.in_(contract_ids),
            SubcontractorContractItem.unit_price.is_not(None),
        )
        .group_by(SubcontractorContractItem.contract_id)
    )
    rows = (await session.execute(stmt)).all()
    return {row[0]: Decimal(row[1] or 0) for row in rows}


async def list_completed_payments(
    session: AsyncSession,
    contract_id: uuid.UUID,
    *,
    before_sequence_no: int | None = None,
    exclude_payment_id: uuid.UUID | None = None,
) -> list[SubcontractorProgressPayment]:
    """Tamamlanmış (`approved|paid`) hakedişler, sıra ARTAN. **İKİ MODLU TEK sorgu**
    (işveren `list_completed_payments` deseninin birebiri, kapsamı SÖZLEŞME):

    * `before_sequence_no=N` → **sıra tabanlı**: avans mahsubu zinciri (spec §3)
      buradan okur — N'inci hakedişin kalan tavanı kendinden ÖNCEKİLERİN
      kurtardığına bağlıdır.
    * `exclude_payment_id=X` → **sırasız TAM küme** (kendisi hariç): kota tavanı
      (spec §4) buradan okur. Kota bir TOPLAM kısıtıdır, kronolojik değildir —
      sıraya bağlansaydı onay sırasını değiştirmek tavanı aşmanın meşru bir yolu
      olurdu (işveren H6 denetimi K1).
    """
    stmt = select(SubcontractorProgressPayment).where(
        SubcontractorProgressPayment.contract_id == contract_id,
        SubcontractorProgressPayment.status.in_(COMPLETED_STATUSES),
    )
    if before_sequence_no is not None:
        stmt = stmt.where(SubcontractorProgressPayment.sequence_no < before_sequence_no)
    if exclude_payment_id is not None:
        stmt = stmt.where(SubcontractorProgressPayment.id != exclude_payment_id)
    result = await session.execute(stmt.order_by(SubcontractorProgressPayment.sequence_no))
    return list(result.scalars().all())


async def list_completed_payments_by_contracts(
    session: AsyncSession, contract_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[SubcontractorProgressPayment]]:
    """Liste ucunun N+1 çözümü (işveren `…_by_projects` deseni): birden çok
    sözleşmenin tamamlanmış hakedişleri TEK sorguda, `sequence_no` ARTAN sırada.

    Kapsam süzgeci ÇAĞIRANDAN gelen kimlik listesindedir — görünmeyen sözleşmenin
    satırı hiç ÇEKİLMEZ (spec §9.0).
    """
    if not contract_ids:
        return {}
    stmt = (
        select(SubcontractorProgressPayment)
        .where(
            SubcontractorProgressPayment.contract_id.in_(contract_ids),
            SubcontractorProgressPayment.status.in_(COMPLETED_STATUSES),
        )
        .order_by(
            SubcontractorProgressPayment.contract_id,
            SubcontractorProgressPayment.sequence_no,
        )
    )
    grouped: dict[uuid.UUID, list[SubcontractorProgressPayment]] = {}
    for payment in (await session.execute(stmt)).scalars().all():
        grouped.setdefault(payment.contract_id, []).append(payment)
    return grouped


async def list_cost_payments_by_projects(
    session: AsyncSession, project_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[SubcontractorProgressPayment]]:
    """P10 maliyet çekirdeğinin toplu okuması: birden çok PROJENİN maliyete giren
    (`approved|paid`) hakedişleri TEK sorguda (`lines` `selectin` ile yüklenir).

    `…_by_contracts`in kardeşi, kapsamı SÖZLEŞME değil PROJEdir: E4 kart listesi
    proje başına toplam ister ve proje başına sorgu koşmak yasaktır (spec §4).
    Süzgeç SQL'dedir — istenmeyen projenin satırı hiç ÇEKİLMEZ.
    """
    if not project_ids:
        return {}
    stmt = (
        select(SubcontractorProgressPayment)
        .where(
            SubcontractorProgressPayment.project_id.in_(project_ids),
            SubcontractorProgressPayment.status.in_(COMPLETED_STATUSES),
        )
        .order_by(
            SubcontractorProgressPayment.project_id,
            SubcontractorProgressPayment.sequence_no,
        )
    )
    grouped: dict[uuid.UUID, list[SubcontractorProgressPayment]] = {}
    for payment in (await session.execute(stmt)).scalars().all():
        grouped.setdefault(payment.project_id, []).append(payment)
    return grouped


def _list_stmt(
    visible_project_ids: list[uuid.UUID],
    *,
    project_id: uuid.UUID | None,
    site_id: uuid.UUID | None,
    period_year: int | None,
    period_month: int | None,
    status_filter: SubcontractorPaymentStatus | None,
    q: str | None,
):
    """Liste ve sayaç sorgusunun PAYLAŞTIĞI `WHERE` gövdesi (L83-101 filtreleri).

    İki sorgu ayrı süzgeç kopyası taşısaydı, `total` ile `items` zamanla farklı
    kümeleri sayardı — sayfalamanın en sinsi hatası.

    `site_id` (TB2/U2) hakediş tablosundan DEĞİL, zaten kurulu olan sözleşme
    join'inden okunur: hakedişin şantiye kolonu YOKTUR, bağ sözleşmededir. Eşitlik
    süzgeci `site_id IS NULL` (proje geneli) sözleşmeleri kendiliğinden eler —
    şantiye sekmesi proje geneli hakedişleri GÖSTERMEZ (SD S5 tek-anlamlılık).
    """
    stmt = (
        select(SubcontractorProgressPayment, SubcontractorContract, Project)
        .join(
            SubcontractorContract,
            SubcontractorContract.id == SubcontractorProgressPayment.contract_id,
        )
        .join(Project, Project.id == SubcontractorProgressPayment.project_id)
        .where(SubcontractorProgressPayment.project_id.in_(visible_project_ids))
    )
    if project_id is not None:
        stmt = stmt.where(SubcontractorProgressPayment.project_id == project_id)
    if site_id is not None:
        stmt = stmt.where(SubcontractorContract.site_id == site_id)
    if period_year is not None:
        stmt = stmt.where(SubcontractorProgressPayment.period_year == period_year)
    if period_month is not None:
        stmt = stmt.where(SubcontractorProgressPayment.period_month == period_month)
    if status_filter is not None:
        stmt = stmt.where(SubcontractorProgressPayment.status == status_filter)
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(
            or_(
                SubcontractorContract.subcontractor_name.ilike(pattern),
                SubcontractorContract.contract_no.ilike(pattern),
            )
        )
    return stmt


async def list_payments(
    session: AsyncSession,
    visible_project_ids: list[uuid.UUID],
    *,
    project_id: uuid.UUID | None,
    site_id: uuid.UUID | None,
    period_year: int | None,
    period_month: int | None,
    status_filter: SubcontractorPaymentStatus | None,
    q: str | None,
    limit: int,
    offset: int,
) -> list[PaymentRow]:
    if not visible_project_ids:
        return []
    stmt = _list_stmt(
        visible_project_ids,
        project_id=project_id,
        site_id=site_id,
        period_year=period_year,
        period_month=period_month,
        status_filter=status_filter,
        q=q,
    ).order_by(
        Project.code,
        SubcontractorContract.created_at,
        SubcontractorProgressPayment.sequence_no,
    )
    result = await session.execute(stmt.limit(limit).offset(offset))
    return [(row[0], row[1], row[2]) for row in result.all()]


async def list_payments_for_summary(
    session: AsyncSession,
    visible_project_ids: list[uuid.UUID],
    *,
    project_id: uuid.UUID | None,
    site_id: uuid.UUID | None,
    period_year: int | None,
    period_month: int | None,
    status_filter: SubcontractorPaymentStatus | None,
    q: str | None,
) -> list[PaymentRow]:
    """KPI şeridinin (T4) kümesi: `list_payments` ile AYNI `WHERE` gövdesi,
    SAYFALAMA YOK.

    Sayfalanmış küme üzerinden KPI hesaplansaydı kartlar yalnız görünen sayfayı
    özetlerdi — "Toplam Hakediş" adının tersi. Süzgeç kopyası da AÇILMAZ
    (`_list_stmt` paylaşılır): KPI şeridi ile altındaki tablo aynı kümeyi
    göstermek ZORUNDADIR.
    """
    if not visible_project_ids:
        return []
    stmt = _list_stmt(
        visible_project_ids,
        project_id=project_id,
        site_id=site_id,
        period_year=period_year,
        period_month=period_month,
        status_filter=status_filter,
        q=q,
    )
    result = await session.execute(stmt)
    return [(row[0], row[1], row[2]) for row in result.all()]


async def count_payments(
    session: AsyncSession,
    visible_project_ids: list[uuid.UUID],
    *,
    project_id: uuid.UUID | None,
    site_id: uuid.UUID | None,
    period_year: int | None,
    period_month: int | None,
    status_filter: SubcontractorPaymentStatus | None,
    q: str | None,
) -> int:
    if not visible_project_ids:
        return 0
    inner = _list_stmt(
        visible_project_ids,
        project_id=project_id,
        site_id=site_id,
        period_year=period_year,
        period_month=period_month,
        status_filter=status_filter,
        q=q,
    ).with_only_columns(SubcontractorProgressPayment.id)
    stmt = select(func.count()).select_from(inner.subquery())
    return int((await session.execute(stmt)).scalar_one())
