"""FIN-1 K8 — E10:69-90'in dort KPI karti. DORDU DE TUREVDIR.

## 🔴 KARTLAR ORTUSUR VE BU BIR KUSUR DEGIL, TANIMDIR

Portfoydeki bir cek AYNI ANDA "bu ay vadeli"dir. Mockup da bunu boyle sayar:
E10:73 `8 adet` + E10:78 `5 adet` ile E10:83 `3 adet` birbirinden BAGIMSIZ
kumelerdir. Kartlarin toplaminin portfoye esit olmasini bekleyen bir test
YAZILMAZ; tersine, ortusmeyi KANITLAYAN bir bekci yazilir
(`test_ozet_kartlari_ORTUSUR`).

| kart | mockup | kume |
|---|---|---|
| `portfolio_received` | E10:71 `Portfoydeki Cek` | `direction=received` **ve** `status=portfolio` |
| `issued` | E10:76 `Verilen Cek` | `direction=issued` **ve** `status=portfolio` |
| `due_this_month` | E10:81 `Bu Ay Vadeli` | `status=portfolio` **ve** vade TAKVIM AYI icinde |
| `returned_cancelled` | E10:86 `Iade / Iptal` | `status IN (returned, cancelled)` |

## Neden "Bu Ay Vadeli" TAKVIM AYIDIR, "bugunden 30 gun" DEGIL

K8 acikca boyle der. Ayrica iki tanim ayin ortasinda AYNI sonucu verir ve fark
yalnizca ay sinirinda gorunur — yani "30 gun" yazilsaydi kusur ayda bir gun
ortaya cikar ve kimse bagintiyi kuramazdi. Pencere `derive.month_bounds`tan
gelir; ikinci bir yerde hesaplansaydi kart ile rozet (`is_due`) ayrisirdi.

## TEK SORGU

Dort kartin sekiz sayisi (dort tutar + dort adet) TEK `SELECT`te, `FILTER`
yantumceleriyle uretilir. Kart basina ayri sorgu yazilsaydi kapsam suzgeci dort
kez tekrarlanir ve biri unutuldugunda YALNIZ o kart sizdirirdi.

🔴 Toplamlar `coalesce(..., 0)` ile **0**dir, NULL DEGIL: kayitsiz bir kumede
`SUM()` NULL doner ve kart "₺" yaninda bosluk basardi (`paid_sum` dersi).
"""

import uuid
from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.treasury.instruments import derive, repository
from app.modules.treasury.instruments.schemas import (
    FinancialInstrumentSummaryCard,
    FinancialInstrumentSummaryResponse,
)
from app.modules.treasury.models import (
    FinancialInstrument,
    FinancialInstrumentDirection,
    FinancialInstrumentStatus,
)

__all__ = ["build_summary"]

ZERO = Decimal("0.00")


def _tutar(kosul: ColumnElement[bool]):
    """Kosula uyan satirlarin tutar toplami; kayit yoksa **0**."""
    return func.coalesce(func.sum(FinancialInstrument.amount).filter(kosul), 0)


def _adet(kosul: ColumnElement[bool]):
    """E10:73 `8 adet` — adet AYRI bir olcudur, `items` uzunlugundan turemez.

    Kart TUM kumeyi sayar, liste ise yalniz SAYFAYI dondurur; ikisi esitken
    yazilan bir test hicbir sey kanitlamaz (BOR-TEMIZ'in "iki sayac ayri
    seydir" kanonu).
    """
    return func.count().filter(kosul)


async def build_summary(
    session: AsyncSession, project_ids: Sequence[uuid.UUID], *, as_of: date
) -> FinancialInstrumentSummaryResponse:
    """Dort kart, TEK sorgu, kapsam suzgeci ICERIDE.

    `as_of` disaridan gelir (`derive.as_of_today()`): fonksiyonun icinde
    okunsaydi ay siniri testleri gercek takvime bagimli olur ve YALNIZ ayin son
    gunu kirmizi olabilecek bir bekci yazilirdi.
    """
    portfoyde = FinancialInstrument.status == FinancialInstrumentStatus.portfolio
    alinan = FinancialInstrument.direction == FinancialInstrumentDirection.received
    verilen = FinancialInstrument.direction == FinancialInstrumentDirection.issued
    ay_basi, ay_sonu = derive.month_bounds(as_of)
    bu_ay = portfoyde & FinancialInstrument.due_date.between(ay_basi, ay_sonu)
    iade_iptal = FinancialInstrument.status.in_(
        (FinancialInstrumentStatus.returned, FinancialInstrumentStatus.cancelled)
    )

    kosullar = {
        "portfolio_received": portfoyde & alinan,
        "issued": portfoyde & verilen,
        "due_this_month": bu_ay,
        "returned_cancelled": iade_iptal,
    }

    stmt = select(
        *[_tutar(kosul) for kosul in kosullar.values()],
        *[_adet(kosul) for kosul in kosullar.values()],
        # 🔴 Kapsam suzgeci `WHERE`dedir, kart kosullarinda DEGIL: kart basina
        # tekrarlansaydi biri unutuldugunda YALNIZ o kart sizdirirdi.
    ).where(repository.scope_clause(project_ids))

    satir = (await session.execute(stmt)).one()
    tutarlar = satir[: len(kosullar)]
    adetler = satir[len(kosullar) :]
    kartlar = {
        # 🔴 `quantize` SART: `coalesce(sum, 0)` bos kumede TAMSAYI 0 doner ve
        # kart "0" basardi — dolu kart ise "300.00". Iki farkli olcek istemciye
        # gidince bicimlendirme kaydi ve fark YALNIZ bos ayda gorunurdu.
        ad: FinancialInstrumentSummaryCard(amount=Decimal(tutar).quantize(ZERO), count=adet)
        for ad, tutar, adet in zip(kosullar, tutarlar, adetler, strict=True)
    }
    return FinancialInstrumentSummaryResponse(**kartlar, as_of=as_of)
