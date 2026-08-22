"""Onay motorunun veri erisimi. Is kurali YOKTUR — o `service.py`dedir."""

import uuid

from sqlalchemy import Select, and_, distinct, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.approvals import documents
from app.modules.approvals.models import (
    ApprovalChain,
    ApprovalDocumentType,
    ApprovalRole,
    ApprovalStep,
    UserApprovalRole,
)
from app.modules.users.models import User

__all__ = [
    "assignment_page",
    "chain_steps",
    "get_chain",
    "get_chain_for_update",
    "pending_page",
    "replace_user_approval_roles",
    "steps_of_chains",
    "user_approval_roles",
    "user_names",
]


async def get_chain(
    session: AsyncSession, document_type: ApprovalDocumentType, document_id: uuid.UUID
) -> ApprovalChain | None:
    return await session.scalar(
        select(ApprovalChain).where(
            ApprovalChain.document_type == document_type,
            ApprovalChain.document_id == document_id,
        )
    )


async def get_chain_for_update(
    session: AsyncSession, document_type: ApprovalDocumentType, document_id: uuid.UUID
) -> ApprovalChain | None:
    """🔴 EŞİK = KİLİT. Zincir satiri TUM DENETIMLERDEN ONCE kilitlenir.

    `populate_existing=True` sarttir: satir session'da ZATEN yuklüyse
    `with_for_update` tek basina TAZE degeri geri yazmaz ve kilit alinmis olmasina
    ragmen BAYAT alanlarla karar verilir.

    Kilit SIRASI tum uclarda SABITTIR: sozlesme -> evrak -> zincir. Cagiran (T3)
    evrak satirini KENDI kilitler; motor yalniz zinciri kilitler ve sirayi bozmaz
    (deadlock).
    """
    return await session.scalar(
        select(ApprovalChain)
        .where(
            ApprovalChain.document_type == document_type,
            ApprovalChain.document_id == document_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )


async def chain_steps(session: AsyncSession, chain_id: uuid.UUID) -> list[ApprovalStep]:
    return list(
        (
            await session.execute(
                select(ApprovalStep)
                .where(ApprovalStep.chain_id == chain_id)
                .order_by(ApprovalStep.step_no)
            )
        )
        .scalars()
        .all()
    )


async def steps_of_chains(session: AsyncSession, chain_ids: list[uuid.UUID]) -> list[ApprovalStep]:
    """Sayfadaki TUM zincirlerin adimlari TEK sorguda (N+1 yok)."""
    if not chain_ids:
        return []
    return list(
        (
            await session.execute(
                select(ApprovalStep)
                .where(ApprovalStep.chain_id.in_(chain_ids))
                .order_by(ApprovalStep.chain_id, ApprovalStep.step_no)
            )
        )
        .scalars()
        .all()
    )


async def user_names(session: AsyncSession, user_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    """Ad cozumlemesi TEK sorguda: satir basina kullanici cekmek N+1'in ta kendisi."""
    if not user_ids:
        return {}
    rows = await session.execute(select(User.id, User.full_name).where(User.id.in_(user_ids)))
    return {satir.id: satir.full_name for satir in rows}


async def user_approval_roles(session: AsyncSession, user_id: uuid.UUID) -> list[ApprovalRole]:
    rows = await session.execute(
        select(UserApprovalRole.approval_role)
        .where(UserApprovalRole.user_id == user_id)
        .order_by(UserApprovalRole.approval_role)
    )
    return list(rows.scalars().all())


async def replace_user_approval_roles(
    session: AsyncSession, user_id: uuid.UUID, roles: list[ApprovalRole]
) -> None:
    """TAM KUME degistirir (kanon): once hepsi silinir, sonra verilenler yazilir.

    Kismi ekleme/cikarma ucu ACILMADI — iki ayri ucun birlestirilmesi gereken
    "son durum" ekranda kurulur ve iki istek arasinda kalan yari hâl gorunurdu.
    """
    mevcut = (
        await session.execute(select(UserApprovalRole).where(UserApprovalRole.user_id == user_id))
    ).scalars()
    for satir in mevcut:
        await session.delete(satir)
    await session.flush()
    for rol in roles:
        session.add(UserApprovalRole(user_id=user_id, approval_role=rol))
    await session.flush()


async def assignment_page(
    session: AsyncSession, *, limit: int, offset: int
) -> tuple[list[User], int, dict[uuid.UUID, list[ApprovalRole]]]:
    """EN AZ BIR onay rolu tasiyan kullanicilar + atamalari (UC sabit sorgu).

    Onay rolu OLMAYAN kullanicilar burada DONMEZ: bu uc "atamalar" listesidir,
    kullanici katalogu degil (o `GET /users`tir).
    """
    total = await session.scalar(select(func.count(distinct(UserApprovalRole.user_id))))
    users = list(
        (
            await session.execute(
                select(User)
                .join(UserApprovalRole, UserApprovalRole.user_id == User.id)
                .distinct()
                .order_by(User.full_name, User.id)
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    atamalar: dict[uuid.UUID, list[ApprovalRole]] = {user.id: [] for user in users}
    if users:
        rows = await session.execute(
            select(UserApprovalRole)
            .where(UserApprovalRole.user_id.in_(list(atamalar)))
            .order_by(UserApprovalRole.approval_role)
        )
        for satir in rows.scalars():
            atamalar[satir.user_id].append(satir.approval_role)
    return users, total or 0, atamalar


def _pending_filter(
    actor_id: uuid.UUID,
    roles: list[ApprovalRole],
    admin_document_types: list[ApprovalDocumentType],
    visible_project_ids: list[uuid.UUID],
) -> tuple[Select, Select]:
    """Kullaniciya DUSEN siradaki adimlarin ortak suzgeci.

    Bekci 5 ve 6 SQL'e cevrilir; ekranda gosterilen kume ile ucta gecen kume
    AYNI kuraldan turemek zorundadir, yoksa kutuda gorunen bir satir tiklaninca
    403 verirdi.

    🔴 DORDUNCU KOSUL PROJE KAPSAMIDIR (T4, IDOR). Gövde ile SAYIM ayni
    `kosullar` demetinden turer: `total` suzgecin DISINDA kalsaydi kullanici
    GOREMEDIGI kayitlari sayardi (BOR-TEMIZ kanonu) — "items bos ama total > 0"
    hâli sahte-yesildir ve sayfalayici bos sayfalar uretirdi.
    """
    siradaki = (
        select(
            ApprovalStep.chain_id.label("chain_id"),
            func.min(ApprovalStep.step_no).label("step_no"),
        )
        .where(ApprovalStep.decided_at.is_(None))
        .group_by(ApprovalStep.chain_id)
        .subquery()
    )
    benim_kararim = select(ApprovalStep.chain_id).where(ApprovalStep.decided_by_user_id == actor_id)
    kosullar = (
        ApprovalStep.approval_role.in_(roles),
        # Bekci 5 — kendi evraki (admin istisnasiyla).
        or_(
            ApprovalChain.created_by_user_id.is_distinct_from(actor_id),
            ApprovalChain.document_type.in_(admin_document_types),
        ),
        # Bekci 6 — gorevler ayriligi (admin ISTISNASI YOK).
        ApprovalChain.id.not_in(benim_kararim),
        # 🔴 IDOR — evragin PROJESI aktorun gordukleri arasinda mi (T4).
        documents.visible_document_clause(visible_project_ids),
    )
    govde = (
        select(ApprovalChain, ApprovalStep)
        .join(siradaki, siradaki.c.chain_id == ApprovalChain.id)
        .join(
            ApprovalStep,
            and_(
                ApprovalStep.chain_id == ApprovalChain.id,
                ApprovalStep.step_no == siradaki.c.step_no,
            ),
        )
        .where(*kosullar)
    )
    sayim = (
        select(func.count())
        .select_from(ApprovalChain)
        .join(siradaki, siradaki.c.chain_id == ApprovalChain.id)
        .join(
            ApprovalStep,
            and_(
                ApprovalStep.chain_id == ApprovalChain.id,
                ApprovalStep.step_no == siradaki.c.step_no,
            ),
        )
        .where(*kosullar)
    )
    return govde, sayim


async def pending_page(
    session: AsyncSession,
    *,
    actor_id: uuid.UUID,
    roles: list[ApprovalRole],
    admin_document_types: list[ApprovalDocumentType],
    visible_project_ids: list[uuid.UUID],
    limit: int,
    offset: int,
) -> tuple[list[tuple[ApprovalChain, ApprovalStep]], int]:
    govde, sayim = _pending_filter(actor_id, roles, admin_document_types, visible_project_ids)
    total = await session.scalar(sayim)
    rows = await session.execute(
        govde.order_by(ApprovalChain.created_at, ApprovalChain.id).limit(limit).offset(offset)
    )
    return [(chain, step) for chain, step in rows.all()], total or 0
