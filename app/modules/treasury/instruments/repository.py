"""FIN-1 veri erisimi — yalniz SQL, karar yok.

Kapsam KARARI (`visible_projects`) bu katmanda DEGIL `service.py`dedir
(`invoicing/repository.py` deseninin kardesi); buraya yalniz cozulmus proje
kimlikleri gelir.

## 🔴 KAPSAMIN UCUNCU HALI: `project_id IS NULL`

Cekte proje ZORUNLU DEGILDIR (K1: "bilgi bagi", nullable): sirket geneli bir cek
hicbir projeye ait olmayabilir. Suzgec bu yuzden
`IS NULL OR IN (gorunenler)` bicimindedir (`invoicing.scope_clause` emsali).
Yalniz `IN` yazilsaydi projesiz cekler HERKESTEN gizlenir ve hicbir ekranda
gorunmezlerdi — yazilabilen ama okunamayan bir kayit sinifi dogardi.

## Liste ve sayim AYNI suzgecten gecer

Kopya acilsaydi `total` ile gosterilen tablo zamanla ayrisir ve sayfa cubugu
"eksik kayit" gosterirdi. `total` ayrica **yetki suzgecini SQL `COUNT`un
ICINDE** tasir; aksi halde kullanici goremedigi kayitlari SAYARDI.

## Siralama DETERMINISTIKTIR

`ORDER BY due_date, id`: ikincil anahtar (`id`) esitlik bozucudur ve
KALDIRILAMAZ. Ayni vadeli iki cek sayfa sinirinda oturuyorsa, esitlik bozucu
olmadan PostgreSQL sirasi kosudan kosuya degisebilir ve ayni kayit iki sayfada
birden ya da HIC gorunmezdi (BOR-TEMIZ dersi: bunu yalniz sorgu BICIMINE bakan
test yakalar, davranis testi yakalayamaz).

## Kilit

`get_instrument(..., for_update=True)` satiri `with_for_update` +
`populate_existing` ile kilitler. `populate_existing` SARTTIR: kimlik haritasi
bayat bir nesne tasiyorsa `session.get` onu SORGUSUZ dondurur ve **kilit HIC
ALINMAZ** — TOCTOU penceresi sessizce acik kalirdi.
"""

import uuid
from collections.abc import Sequence
from datetime import date

from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.treasury.models import (
    BankAccount,
    FinancialInstrument,
    FinancialInstrumentDirection,
    FinancialInstrumentKind,
    FinancialInstrumentStatus,
    Payment,
)

__all__ = [
    "count_instruments",
    "get_instrument",
    "list_instruments",
    "payments_with_accounts",
    "scope_clause",
]


def _like_escape(deger: str) -> str:
    """`%` ve `_` LIKE joker karakterleridir.

    Kacirilmazsa arama kutusuna `%` yazan kullanici TUM portfoyu, `_` yazan ise
    beklemedigi satirlari gorur. Kacis karakterinin KENDISI once kacirilir.
    """
    return deger.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def scope_clause(project_ids: Sequence[uuid.UUID]) -> ColumnElement[bool]:
    """Gorunurluk suzgeci — modul docstring'indeki ucuncu hal dahil.

    PUBLIC: `service` tekil erisimde de bunu kullanir ki liste ile detay ASLA
    ayrismasin (bir cekin listede gorunup detayinda 404 vermesi imkansiz olsun).
    """
    return FinancialInstrument.project_id.is_(None) | FinancialInstrument.project_id.in_(
        project_ids
    )


def _filtered(
    stmt: Select,
    project_ids: Sequence[uuid.UUID],
    *,
    direction: FinancialInstrumentDirection | None,
    instrument_kind: FinancialInstrumentKind | None,
    status: FinancialInstrumentStatus | None,
    project_id: uuid.UUID | None,
    due_before: date | None,
    due_after: date | None,
    q: str | None,
) -> Select:
    """E10 sekmeleri + suzgec cubugu. Suzgecler AND'lidir.

    Kapsam suzgeci HER ZAMAN uygulanir ve kullanicinin verdigi `project_id` onun
    YERINE degil USTUNE gecer: gorunmeyen bir proje kimligi verildiginde kesisim
    BOSTUR, yani sizinti olmaz.

    `q` KESIDECI ve CEK NO uzerinde kismi arar (emir K6). E10 satiri ikisini de
    basar ve tek alanda aramak kullaniciyi "kayit yok" sanisina dusururdu.

    Tarih araligi KAPALIDIR (`>= due_after`, `<= due_before`): kullanici "25
    Temmuz'a kadar" derken o gunu DISARIDA birakmayi kastetmez.
    """
    stmt = stmt.where(scope_clause(project_ids))
    if direction is not None:
        stmt = stmt.where(FinancialInstrument.direction == direction)
    if instrument_kind is not None:
        stmt = stmt.where(FinancialInstrument.instrument_kind == instrument_kind)
    if status is not None:
        stmt = stmt.where(FinancialInstrument.status == status)
    if project_id is not None:
        stmt = stmt.where(FinancialInstrument.project_id == project_id)
    if due_after is not None:
        stmt = stmt.where(FinancialInstrument.due_date >= due_after)
    if due_before is not None:
        stmt = stmt.where(FinancialInstrument.due_date <= due_before)
    if q:
        desen = f"%{_like_escape(q)}%"
        stmt = stmt.where(
            FinancialInstrument.serial_no.ilike(desen, escape="\\")
            | FinancialInstrument.drawer_name.ilike(desen, escape="\\")
        )
    return stmt


async def list_instruments(
    session: AsyncSession,
    project_ids: Sequence[uuid.UUID],
    *,
    direction: FinancialInstrumentDirection | None = None,
    instrument_kind: FinancialInstrumentKind | None = None,
    status: FinancialInstrumentStatus | None = None,
    project_id: uuid.UUID | None = None,
    due_before: date | None = None,
    due_after: date | None = None,
    q: str | None = None,
    limit: int,
    offset: int,
) -> Sequence[FinancialInstrument]:
    stmt = _filtered(
        select(FinancialInstrument),
        project_ids,
        direction=direction,
        instrument_kind=instrument_kind,
        status=status,
        project_id=project_id,
        due_before=due_before,
        due_after=due_after,
        q=q,
    )
    # 🔴 `FinancialInstrument.id` esitlik bozucudur ve KALDIRILAMAZ (modul
    # docstring'i). Vade birincil anahtardir: portfoy ekrani vadeye gore okunur.
    stmt = stmt.order_by(FinancialInstrument.due_date, FinancialInstrument.id)
    result = await session.execute(stmt.limit(limit).offset(offset))
    return result.scalars().all()


async def count_instruments(
    session: AsyncSession,
    project_ids: Sequence[uuid.UUID],
    *,
    direction: FinancialInstrumentDirection | None = None,
    instrument_kind: FinancialInstrumentKind | None = None,
    status: FinancialInstrumentStatus | None = None,
    project_id: uuid.UUID | None = None,
    due_before: date | None = None,
    due_after: date | None = None,
    q: str | None = None,
) -> int:
    stmt = _filtered(
        select(func.count()).select_from(FinancialInstrument),
        project_ids,
        direction=direction,
        instrument_kind=instrument_kind,
        status=status,
        project_id=project_id,
        due_before=due_before,
        due_after=due_after,
        q=q,
    )
    return (await session.execute(stmt)).scalar_one()


async def get_instrument(
    session: AsyncSession, instrument_id: uuid.UUID, *, for_update: bool = False
) -> FinancialInstrument | None:
    """Tekil satir. `for_update=True` DENETIMLERDEN ONCE kilit alir.

    `populate_existing=True` olmadan `session.get` bayat bir nesneyi SORGUSUZ
    dondurur ve `FOR UPDATE` hic kosmaz (`invoicing.get_invoice` dersi).
    """
    if not for_update:
        return await session.get(FinancialInstrument, instrument_id)
    stmt = (
        select(FinancialInstrument)
        .where(FinancialInstrument.id == instrument_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def payments_with_accounts(
    session: AsyncSession, instrument_id: uuid.UUID
) -> list[tuple[Payment, BankAccount]]:
    """🔴 ODM-1 D3 — enstrumana BAGLI odemeler, HESAPLARIYLA birlikte.

    Tahsil/odeme fisinin tutari `instrument.amount` DEGIL bu kumenin
    toplamidir: bag ISTEGE BAGLIDIR (FIN-1 K4) ve kismi tahsilat mumkundur,
    yani iki buyukluk mesru olarak AYRISABILIR. `instrument.amount`tan
    yazilsaydi `101`e giren ile cikan farklasir ve ara hesap HIC KAPANMAZDI.

    Hesap AYNI sorguda okunur (N+1 YOK) ve okunmak ZORUNDADIR: nakit bacaginin
    rolu ODEME BASINA o odemenin `bank_account.account_type`indan secilir
    (`treasury.posting.cash_role_for`) — kasadan ve bankadan bagli iki odeme
    karisiksa tek bir nakit rolu ikisini de bankaya yazar ve mizanda ikisi de
    "Hazir Degerler" altinda toplandigi icin TOPLAM tutmaya devam ederdi.

    Sira DETERMINISTIKTIR (`paid_on`, `id`): esitlik bozucu olmadan ayni gunlu
    iki odemenin bacak sirasi kosudan kosuya degisir ve fis satirlarinin
    `sort_order`i sabit kalmazdi.
    """
    stmt = (
        select(Payment, BankAccount)
        .join(BankAccount, BankAccount.id == Payment.bank_account_id)
        .where(Payment.financial_instrument_id == instrument_id)
        .order_by(Payment.paid_on, Payment.id)
    )
    return [(payment, account) for payment, account in (await session.execute(stmt)).all()]
