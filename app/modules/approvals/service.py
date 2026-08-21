"""Onay zinciri MOTORU — kurulum, onay, ret ve ayar (sozlesme Y1-Y3, Y5).

## BEKCI SIRASI (Y2) — baglayicidir

1. evrak satiri `FOR UPDATE`  — **CAGIRANIN isi** (T3). Kilit sirasi tum uclarda
   SABITTIR: sozlesme -> evrak -> zincir (deadlock).
2. zincir satiri `FOR UPDATE` — `repository.get_chain_for_update`.
3. zincir acik mi / adim SIRADAKI adim mi  -> **409**
4. aktor adimin onay rolunu tasiyor mu     -> **403**
5. 🔴 KENDI EVRAKI                          -> **403**, TEK ISTISNA: aktorun
   EVRAGIN izin modulunde `AccessLevel.admin` seviyesi varsa GECER ve denetim
   metni "vekaleten" isareti tasir.
6. 🔴 GOREVLER AYRILIGI                     -> **403**. Burada admin ISTISNASI
   YOKTUR: K1 istisnayi yalniz "kendi evraki"na verdi. Bekci 5 ile 6 ayni anda
   gecerliyse **5 ONCE** atesler.

## Denetim satirini KIM yazar

Motor satiri YAZMAZ; hazir METNI dondurur ve `record_audit` cagrisini ROUTER
yapar (`units/service.py` · B5 deseni). Gerekce: (a) metin, zincir silinmeden
(rette) ve adim damgalanirken ancak MOTORDA kurulabilir; (b) uc ayri evrak
router'i ayni metni uc kez kurmak zorunda kalmamalidir; (c) `ip_address` istekle
gelir ve motora tasinmasi katman yonunu tersine cevirirdi.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import AccessLevel, satisfies
from app.core.errors import ApprovalNotAllowedError, ApprovalValidationError, ConflictError
from app.core.text import FREE_TEXT_MAX_LENGTH
from app.modules.approvals import definitions, guards, repository
from app.modules.approvals.models import (
    ApprovalChain,
    ApprovalDocumentType,
    ApprovalRole,
    ApprovalStep,
)
from app.modules.audit import messages
from app.modules.company import repository as company_repository
from app.modules.roles.repository import get_permission
from app.modules.users.models import User

__all__ = [
    "ChainDecision",
    "PendingChainView",
    "PendingStepView",
    "approve_next_step",
    "assignment_page",
    "create_chain",
    "get_threshold",
    "pending_for_user",
    "reject_chain",
    "replace_user_roles",
    "set_threshold",
    "user_approval_roles",
]


@dataclass(frozen=True)
class ChainDecision:
    """Bir adim kararinin SONUCU — hem onay hem ret bunu doner.

    🔴 KANON E: cevap OLGUYU tasir, KARARI degil. `audit_detail` bir olgudur
    (ne oldu), `is_complete` de oyle (zincir bitti mi) — cagiran evrak ailesi
    kendi durum makinesini bu olgulardan KENDISI turetir.
    """

    chain_id: uuid.UUID
    step_no: int
    approval_role: ApprovalRole
    is_complete: bool
    on_behalf: bool
    audit_detail: str


@dataclass(frozen=True)
class PendingStepView:
    step_no: int
    approval_role: ApprovalRole
    decided_at: datetime | None
    decided_by_name: str | None


@dataclass(frozen=True)
class PendingChainView:
    chain_id: uuid.UUID
    document_type: ApprovalDocumentType
    document_id: uuid.UUID
    created_by_name: str | None
    created_at: datetime
    threshold_snapshot: Decimal
    amount_snapshot: Decimal | None
    current_step_no: int
    steps: list[PendingStepView]


# --------------------------------------------------------------------------- #
# Esik ayari (K3)
# --------------------------------------------------------------------------- #


async def get_threshold(session: AsyncSession) -> Decimal:
    """Esigin TEK okuma yolu — `procurement` de buradan okur (R6)."""
    company = await company_repository.get_or_create_singleton(session)
    return company.approval_threshold_try


async def set_threshold(session: AsyncSession, value: Decimal) -> Decimal:
    company = await company_repository.get_or_create_singleton(session)
    company.approval_threshold_try = value
    await session.flush()
    return company.approval_threshold_try


# --------------------------------------------------------------------------- #
# Onay rolu atamalari (K1)
# --------------------------------------------------------------------------- #


async def user_approval_roles(session: AsyncSession, user_id: uuid.UUID) -> list[ApprovalRole]:
    return await repository.user_approval_roles(session, user_id)


async def replace_user_roles(
    session: AsyncSession, user_id: uuid.UUID, roles: list[ApprovalRole]
) -> list[ApprovalRole]:
    """Tekrarlar SESSIZCE tekillestirilir: atama bir KUMEDIR, ayni rolu iki kez
    gondermek bir hata degil sadece gereksiz bir tekrardir."""
    tekil: list[ApprovalRole] = []
    for rol in roles:
        if rol not in tekil:
            tekil.append(rol)
    await repository.replace_user_approval_roles(session, user_id, tekil)
    return await repository.user_approval_roles(session, user_id)


async def assignment_page(session: AsyncSession, *, limit: int, offset: int):
    return await repository.assignment_page(session, limit=limit, offset=offset)


# --------------------------------------------------------------------------- #
# Zincir kurulumu (Y1)
# --------------------------------------------------------------------------- #


async def create_chain(
    session: AsyncSession,
    *,
    document_type: ApprovalDocumentType,
    document_id: uuid.UUID,
    amount: Decimal | None,
    created_by_user_id: uuid.UUID,
) -> ApprovalChain:
    """Evrak onaya gonderilirken zinciri kurar ve IKI CARPANI da DONDURUR.

    `amount` **BRUT** tutardir (R5) ve `None` "belirlenemedi" demektir; ikisinin
    de anlamini `definitions.step_roles` tasir. Cagiran (T3) tutari kendi evrak
    ailesinden hesaplar — motor evrak modullerini ITHAL ETMEZ, yoksa uc ayri
    aile bu modulde birbirine dugumlenirdi.
    """
    if await repository.get_chain(session, document_type, document_id) is not None:
        raise ConflictError(guards.CHAIN_ALREADY_EXISTS)

    threshold = await get_threshold(session)
    chain = ApprovalChain(
        document_type=document_type,
        document_id=document_id,
        threshold_snapshot=threshold,
        amount_snapshot=amount,
        created_by_user_id=created_by_user_id,
        created_at=datetime.now(UTC),
    )
    session.add(chain)
    await session.flush()
    for sira, rol in enumerate(definitions.step_roles(document_type, amount, threshold), start=1):
        session.add(ApprovalStep(chain_id=chain.id, step_no=sira, approval_role=rol))
    await session.flush()
    return chain


# --------------------------------------------------------------------------- #
# Bekciler (Y2)
# --------------------------------------------------------------------------- #


async def _load_locked_chain(
    session: AsyncSession, document_type: ApprovalDocumentType, document_id: uuid.UUID
) -> ApprovalChain:
    chain = await repository.get_chain_for_update(session, document_type, document_id)
    if chain is None:
        raise ConflictError(guards.NO_OPEN_CHAIN)
    return chain


def _current_step(steps: list[ApprovalStep], step_no: int | None) -> ApprovalStep:
    """Bekci 3 — zincir acik mi, istenen adim SIRADAKI adim mi.

    `step_no` ISTEGE BAGLIDIR ama verildiginde bir IYIMSER KILITTIR: ekranin
    gordugu adim artik siradaki degilse (baskasi ilerletmis) istek 409 alir ve
    kullanici yanlis adimi onaylamis olmaz.
    """
    bekleyen = [adim for adim in steps if adim.decided_at is None]
    if not bekleyen:
        raise ConflictError(guards.CHAIN_COMPLETED)
    siradaki = bekleyen[0]
    if step_no is not None and step_no != siradaki.step_no:
        raise ConflictError(guards.STEP_NOT_CURRENT)
    return siradaki


async def _has_document_admin(
    session: AsyncSession, actor: User, document_type: ApprovalDocumentType
) -> bool:
    """`admin` seviyesi EVRAGIN izin modulunde aranir (`definitions`).

    `full` YETMEZ (`access.satisfies`): `patron` sistem rolü `full`dur ve
    istisna ona acilsaydi "tek kisilik ekipte kilitlenmeyi onle" gerekcesi,
    kendi evragini onaylayan ikinci bir sinifa donusurdu.
    """
    permission = await get_permission(
        session, actor.role_id, definitions.DOCUMENT_PERMISSION_MODULE[document_type]
    )
    return permission is not None and satisfies(permission.access_level, AccessLevel.admin)


async def _assert_can_decide(
    session: AsyncSession,
    actor: User,
    chain: ApprovalChain,
    steps: list[ApprovalStep],
    current: ApprovalStep,
) -> bool:
    """Bekci 4-5-6. Doner: karar "vekaleten" mi verildi.

    Ret de bir KARARDIR ve AYNI huniden gecer: ayri birakilsaydi evragin sahibi
    kendi evragini REDDEDEREK zinciri silebilir ve onay izini yok edebilirdi.
    """
    roller = await repository.user_approval_roles(session, actor.id)
    if current.approval_role not in roller:
        raise ApprovalNotAllowedError(guards.APPROVAL_ROLE_MISSING)

    on_behalf = False
    if chain.created_by_user_id == actor.id:
        if not await _has_document_admin(session, actor, chain.document_type):
            raise ApprovalNotAllowedError(guards.OWN_DOCUMENT)
        on_behalf = True

    if any(adim.decided_by_user_id == actor.id for adim in steps):
        raise ApprovalNotAllowedError(guards.SEPARATION_OF_DUTIES)
    return on_behalf


# --------------------------------------------------------------------------- #
# Onay / ret
# --------------------------------------------------------------------------- #


async def approve_next_step(
    session: AsyncSession,
    *,
    actor: User,
    document_type: ApprovalDocumentType,
    document_id: uuid.UUID,
    step_no: int | None = None,
) -> ChainDecision:
    chain = await _load_locked_chain(session, document_type, document_id)
    steps = await repository.chain_steps(session, chain.id)
    current = _current_step(steps, step_no)
    on_behalf = await _assert_can_decide(session, actor, chain, steps, current)

    current.decided_by_user_id = actor.id
    current.decided_at = datetime.now(UTC)
    await session.flush()

    return ChainDecision(
        chain_id=chain.id,
        step_no=current.step_no,
        approval_role=current.approval_role,
        is_complete=all(adim.decided_at is not None for adim in steps),
        on_behalf=on_behalf,
        audit_detail=messages.approval_step_approved(
            document_type.value,
            current.step_no,
            len(steps),
            current.approval_role.value,
            on_behalf=on_behalf,
        ),
    )


def _clean_reason(reason: str | None) -> str:
    """Gerekce ZORUNLU metindir (K2); tavan PAYLASILAN sabittendir.

    Module ayri bir sayi yazilsaydi alanin bir giris noktasi kapiyi atlatirdi
    (BC dersi) — tavan `core/text.py::FREE_TEXT_MAX_LENGTH`tir.
    """
    temiz = (reason or "").strip()
    if not temiz:
        raise ApprovalValidationError(guards.REJECT_REASON_REQUIRED)
    if len(temiz) > FREE_TEXT_MAX_LENGTH:
        raise ApprovalValidationError(guards.REJECT_REASON_TOO_LONG)
    return temiz


async def reject_chain(
    session: AsyncSession,
    *,
    actor: User,
    document_type: ApprovalDocumentType,
    document_id: uuid.UUID,
    reason: str | None,
) -> ChainDecision:
    """RET TERMINALDIR (K2): zincir SATIRI SILINIR, adimlar CASCADE ile gider.

    Gerekce dogrulamasi bekcilerden SONRA kosar: yetkisi olmayan birine once
    "gerekce yaz" demek, asil engeli (bu adim ona kapali) gizlerdi.
    """
    chain = await _load_locked_chain(session, document_type, document_id)
    steps = await repository.chain_steps(session, chain.id)
    current = _current_step(steps, None)
    on_behalf = await _assert_can_decide(session, actor, chain, steps, current)
    temiz = _clean_reason(reason)

    detail = messages.approval_chain_rejected(
        document_type.value,
        current.step_no,
        len(steps),
        current.approval_role.value,
        temiz,
        on_behalf=on_behalf,
    )
    sonuc = ChainDecision(
        chain_id=chain.id,
        step_no=current.step_no,
        approval_role=current.approval_role,
        is_complete=False,
        on_behalf=on_behalf,
        audit_detail=detail,
    )
    await session.delete(chain)
    # Adimlar DB'de CASCADE ile gider; session'daki kopyalari da BIRAKILIR ki
    # sonraki bir autoflush olmayan satirlara UPDATE denemesin.
    for adim in steps:
        session.expunge(adim)
    await session.flush()
    return sonuc


# --------------------------------------------------------------------------- #
# Onay kutusu (Y7 — satir zenginlestirmesi T4'te)
# --------------------------------------------------------------------------- #


async def _admin_document_types(session: AsyncSession, actor: User) -> list[ApprovalDocumentType]:
    """Bekci 5'in istisnasinin SQL karsiligi. Sorgu sayisi IZIN MODULU sayisi
    kadardir (bugun iki) — SATIR SAYISINDAN bagimsizdir."""
    seviyeler: dict[str, bool] = {}
    tipler: list[ApprovalDocumentType] = []
    for tip, modul in definitions.DOCUMENT_PERMISSION_MODULE.items():
        if modul not in seviyeler:
            permission = await get_permission(session, actor.role_id, modul)
            seviyeler[modul] = permission is not None and satisfies(
                permission.access_level, AccessLevel.admin
            )
        if seviyeler[modul]:
            tipler.append(tip)
    return tipler


async def pending_for_user(
    session: AsyncSession, actor: User, *, limit: int, offset: int
) -> tuple[list[PendingChainView], int, list[ApprovalRole]]:
    """Kullaniciya DUSEN siradaki adimlar + aktorun ONAY ROLLERI.

    🔴 KANON E: `can_approve` gibi bir KARAR ALANI YOKTUR. Yanit adimin rolunu,
    sirasini ve durumunu verir; aktorun rolleri de ayrica doner ve kararı EKRAN
    birlestirir.

    🔴 N+1 YOK: sorgu sayisi SATIR SAYISINDAN bagimsizdir (sayim · sayfa ·
    adimlar · adlar + sabit sayida izin sorgusu).

    ⚠️ KAPSAM DISI (T4): satir basligi/alt basligi, brut-net tutar ikilisi ve
    `projects.service.visible_projects` uzerinden proje gorunurlugu suzgeci.
    Bugun evraklarin hicbiri zincire BAGLI DEGILDIR (o T3'tur), dolayisiyla
    ortada suzulecek gercek bir evrak yoktur; ustelik satirin kendisi zaten
    "bu adim SANA dustu" olgusuyla sinirlidir.
    """
    roller = await repository.user_approval_roles(session, actor.id)
    if not roller:
        return [], 0, []

    admin_tipleri = await _admin_document_types(session, actor)
    rows, total = await repository.pending_page(
        session,
        actor_id=actor.id,
        roles=roller,
        admin_document_types=admin_tipleri,
        limit=limit,
        offset=offset,
    )
    chain_ids = [chain.id for chain, _ in rows]
    steps = await repository.steps_of_chains(session, chain_ids)

    kimlikler: set[uuid.UUID] = set()
    for chain, _ in rows:
        if chain.created_by_user_id is not None:
            kimlikler.add(chain.created_by_user_id)
    for adim in steps:
        if adim.decided_by_user_id is not None:
            kimlikler.add(adim.decided_by_user_id)
    adlar = await repository.user_names(session, kimlikler)

    adim_haritasi: dict[uuid.UUID, list[PendingStepView]] = {}
    for adim in steps:
        adim_haritasi.setdefault(adim.chain_id, []).append(
            PendingStepView(
                step_no=adim.step_no,
                approval_role=adim.approval_role,
                decided_at=adim.decided_at,
                decided_by_name=adlar.get(adim.decided_by_user_id)
                if adim.decided_by_user_id
                else None,
            )
        )

    return (
        [
            PendingChainView(
                chain_id=chain.id,
                document_type=chain.document_type,
                document_id=chain.document_id,
                created_by_name=adlar.get(chain.created_by_user_id)
                if chain.created_by_user_id
                else None,
                created_at=chain.created_at,
                threshold_snapshot=chain.threshold_snapshot,
                amount_snapshot=chain.amount_snapshot,
                current_step_no=current.step_no,
                steps=adim_haritasi.get(chain.id, []),
            )
            for chain, current in rows
        ],
        total,
        roller,
    )
