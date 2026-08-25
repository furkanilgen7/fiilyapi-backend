"""B8 toplu ünite üretimi testlerinin PAYLAŞILAN kurulumu.

`test_units_bulk.py` 800 satır tavanını aşınca bölündü (`_journal.py` emsali):
yardımcılar KOPYALANMADI, buraya alındı — iki kopya olsaydı biri güncellenip
öteki kalır ve iki dosya AYNI ismi taşıyan FARKLI gövdelerle koşardı.

Hiçbir testin iddiası bu bölmeyle değişmedi.
"""

import uuid
from decimal import Decimal

from sqlalchemy import func, select

from app.modules.units.models import Unit, UnitFacing
from app.modules.units.schemas import (
    UnitBulkCreate,
    UnitBulkSlot,
    UnitKind,
)

# TU govdesi TEK yerde durur (`test_units_bulk_preview.py`): T10'un asil iddiasi
# "onizleme ile uretim AYNI govdeden AYNI sonucu verir"dir ve govde kopyalanirsa
# biri degistiginde digeri sessizce bayatlar — iddia da bosa duser.

_ANY_BLOCK = uuid.uuid4()

# TU 107-133 "Kat Sablonu" tablosunun UC SATIRI, mockup'tan BIREBIR. Onizleme
# beklentileri (TU 159-165) bu veriden turedigi icin sayilar burada TEK yerde
# durur; testte tekrar edilirse biri degistiginde digeri sessizce bayatlar.
_TU_SLOTS = (
    UnitBulkSlot(
        sequence=1,
        layout="3+1",
        gross_area_m2=Decimal("148"),
        net_area_m2=Decimal("128"),
        facing=UnitFacing.south,
        list_price=Decimal("1280000"),
    ),
    UnitBulkSlot(
        sequence=2,
        layout="2+1",
        gross_area_m2=Decimal("112"),
        net_area_m2=Decimal("96"),
        facing=UnitFacing.east,
        list_price=Decimal("940000"),
    ),
    UnitBulkSlot(
        sequence=3,
        layout="3+1",
        gross_area_m2=Decimal("148"),
        net_area_m2=Decimal("128"),
        facing=UnitFacing.west,
        list_price=Decimal("1240000"),
    ),
)


def _bulk(**kwargs) -> UnitBulkCreate:
    payload: dict = {
        "block_id": _ANY_BLOCK,
        "unit_kind": UnitKind.apartment,
        "start_floor": 1,
        "end_floor": 1,
        "units_per_floor": 1,
    }
    payload.update(kwargs)
    return UnitBulkCreate(**payload)


async def _count_units_in_block(session, block_id: uuid.UUID) -> int:
    result = await session.execute(
        select(func.count()).select_from(Unit).where(Unit.block_id == block_id)
    )
    return int(result.scalar_one())
