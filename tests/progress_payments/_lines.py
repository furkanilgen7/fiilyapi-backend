"""Hakediş SATIR ucu testlerinin PAYLAŞILAN kurulumu.

`test_lines.py` 800 satır tavanını aşınca bölündü (`_journal.py` emsali):
yardımcılar KOPYALANMADI, buraya alındı — iki kopya olsaydı biri güncellenip
öveki kalır ve iki dosya AYNI ismi taşıyan FARKLI gövdelerle koşardı.

Hiçbir testin iddiası bu bölmeyle değişmedi.
"""

import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.models import BoqItem
from app.modules.contracts.models import EmployerContractItem
from app.modules.progress_payments.models import (
    ProgressPaymentLine,
)
from app.modules.sites.models import Site


def _satir(item_id, site_id, quantity: str, coefficient: str | None = None) -> dict:
    govde = {
        "contract_item_id": str(item_id),
        "site_id": str(site_id),
        "quantity": quantity,
    }
    if coefficient is not None:
        govde["coefficient"] = coefficient
    return govde


async def _satir_sayisi(session: AsyncSession, payment_id: uuid.UUID) -> int:
    stmt = select(func.count()).where(ProgressPaymentLine.payment_id == payment_id)
    return (await session.execute(stmt)).scalar_one()


async def _kotayi_dusur(
    session: AsyncSession, item: EmployerContractItem, site: Site, yeni_kota: str
) -> None:
    """Dağıtım sonradan revize edilmiş gibi (kalem, şantiye) kotasını düşürür —
    H5 denetimi O1'in senaryosu."""
    stmt = select(BoqItem).where(BoqItem.contract_item_id == item.id, BoqItem.site_id == site.id)
    boq = (await session.execute(stmt)).scalar_one()
    boq.quantity = Decimal(yeni_kota)
    await session.flush()
