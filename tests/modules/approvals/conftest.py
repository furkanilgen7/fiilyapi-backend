"""OK-1A — onay zinciri motorunun paylaşılan fixture'ları.

İzin matrisi (`roles/seed_data.py`, **`approvals`** — 2. modül, grup GENEL;
seed'de ZATEN VARDIR, matris DEĞİŞMEDİ):
system_admin=**_A** · patron=_F · site_chief=_OWN · field_engineer=_OWN ·
hr_manager=_OWN · accounting=_FIN · project_manager=_PRJ · procurement=_STK.

Yani `approvals: admin` kapısından **yalnız `system_admin`** geçer; ayar ve rol
atama uçlarının kapısı budur (sözleşme Y5).

🔴 ONAY ROLÜ ≠ SİSTEM ROLÜ. `user.role_id` sistem rolüdür (izin matrisini
belirler); `user_approval_roles` ise onay zincirinin adım rolüdür. Bir kullanıcı
BİRDEN ÇOK onay rolü taşıyabilir (K1) ve onay rolü taşımak hiçbir izin vermez.
Fixture'lar ikisini bilerek AYRI parametre olarak alır.
"""

import uuid
from collections.abc import Awaitable, Callable, Sequence

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.approvals.models import (
    ApprovalChain,
    ApprovalDocumentType,
    ApprovalRole,
    ApprovalStep,
    UserApprovalRole,
)
from app.modules.users.models import User

PAROLA = "parola1234"


@pytest.fixture
def aktor_fabrikasi(seeded_db: AsyncSession, user_factory) -> Callable[..., Awaitable[User]]:
    """Sistem rolü + onay rolleri AYRI verilir (modül docstring'i)."""

    async def _kur(
        email: str,
        *,
        role_key: str = "accounting",
        approval_roles: Sequence[ApprovalRole] = (),
        full_name: str = "Onay Aktörü",
    ) -> User:
        user = await user_factory(
            email=email, password=PAROLA, role_key=role_key, full_name=full_name
        )
        for rol in approval_roles:
            seeded_db.add(UserApprovalRole(user_id=user.id, approval_role=rol))
        await seeded_db.flush()
        return user

    return _kur


@pytest.fixture
def giris(client: AsyncClient) -> Callable[[str], Awaitable[dict[str, str]]]:
    async def _giris(email: str) -> dict[str, str]:
        resp = await client.post("/auth/login", json={"email": email, "password": PAROLA})
        assert resp.status_code == 200, resp.text
        return {"Authorization": f"Bearer {resp.json()['access_token']}"}

    return _giris


async def adim_rolleri(session: AsyncSession, chain_id: uuid.UUID) -> list[ApprovalRole]:
    """Zincirin adım rollerini `step_no` sırasıyla döner."""
    rows = (
        await session.execute(
            select(ApprovalStep)
            .where(ApprovalStep.chain_id == chain_id)
            .order_by(ApprovalStep.step_no)
        )
    ).scalars()
    return [row.approval_role for row in rows]


async def zincir_getir(
    session: AsyncSession, document_type: ApprovalDocumentType, document_id: uuid.UUID
) -> ApprovalChain | None:
    return await session.scalar(
        select(ApprovalChain).where(
            ApprovalChain.document_type == document_type,
            ApprovalChain.document_id == document_id,
        )
    )


# --------------------------------------------------------------------------- #
# T3 — evrak ailelerinin ORTAK yardimcilari
# --------------------------------------------------------------------------- #
#
# Bu üç yardımcı `tests/progress_payments/` · `tests/subcontractor_progress_
# payments/` · `tests/modules/procurement/` altındaki T3 dosyalarından
# İTHAL EDİLİR. pytest kardeş `conftest.py`leri otomatik yüklemez ama modül
# olarak ithal etmek serbesttir (`test_ok1a_chain_build.py` deseni) — üç ayrı
# kopya "onay rolü ver" yardımcısı doğsaydı biri değişip diğerleri unutulurdu.


async def onay_rolu_ver(session: AsyncSession, user: User, *roller: ApprovalRole) -> User:
    """Kullanıcıya ONAY ROLÜ verir — sistem rolüne DOKUNMAZ (K1).

    İkisi kasten ayrıdır: onay rolü hiçbir izin vermez, izin matrisi de hiçbir
    imza adaylığı vermez. Bir adımı onaylayacak aktörün İKİSİNE DE ihtiyacı
    vardır (uç kapısı + adım rolü) ve testler bunu ayrı ayrı kurar.
    """
    for rol in roller:
        session.add(UserApprovalRole(user_id=user.id, approval_role=rol))
    await session.flush()
    return user


async def kullanici(session: AsyncSession, email: str) -> User:
    """E-postadan kullanıcıyı çözer (headers fixture'ları kullanıcıyı döndürmez)."""
    return (await session.execute(select(User).where(User.email == email))).scalar_one()


async def adim_durumlari(session: AsyncSession, chain_id: uuid.UUID) -> list[bool]:
    """Adımların KARARA BAĞLANMIŞ olup olmadığı, `step_no` sırasıyla."""
    rows = (
        await session.execute(
            select(ApprovalStep)
            .where(ApprovalStep.chain_id == chain_id)
            .order_by(ApprovalStep.step_no)
        )
    ).scalars()
    return [row.decided_at is not None for row in rows]
