"""Sunucu tarafi numara ureticileri: `SAT-YYYY-NNNN` / `SP-YYYY-NNNN` (§7 S6).

Kullanici karari: IKI desen de DORT haneli sifir dolgulu ve YIL BAZLI siradir
(SIP mockup'undaki uc hane cizim artefaktidir). Numarayi ISTEMCI GONDEREMEZ —
uclar (T2/T3) bu modulu cagirir.

YARIS KOSULU (bu modulun asil sebebi)
-------------------------------------
Naif uygulama "SELECT max(...) + 1"dir ve iki es zamanli istek AYNI numarayi
uretir: ikisi de digerinin HENUZ COMMIT ETMEDIGI satiri goremez. Sonuc, UQ
kisiti sayesinde sessiz bir cift kayit degil ama gorunur bir 500'dur.

Cozum ISLEM OMURLU DANISMA KILIDIDIR (`pg_advisory_xact_lock`): kilit
(dizi, yil) ciftine baglanir, transaction commit/rollback ile KENDILIGINDEN
birakilir ve ikinci istek birincinin commit'ini bekler. `SELECT … FOR UPDATE`
burada ISE YARAMAZDI: kilitlenecek SATIR henuz yoktur (yilin ilk numarasi) ve
"olmayan satiri" kilitlemek Postgres'te mumkun degildir — TB1'in dagitim
kilidi mevcut bir sozlesme satirini kilitledigi icin oradaki desen dogrudan
tasinamadi. Ayri bir Postgres `SEQUENCE` de tercih edilmedi: yil basinda
sifirlanmasi elle mudahale ister ve rollback'te bosluk birakir.

Kilit ANAHTARI iki `int`tir: `(dizi anahtari, yil)`. Dizi anahtarlari sabittir
ve DEGISTIRILMEMELIDIR — degisirse eski surumle yeni surum ayni anda kosarken
farkli kilitler alip yarisi geri getirirler.
"""

from datetime import date

from sqlalchemy import Integer, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.modules.procurement.models import PurchaseOrder, PurchaseRequest

REQUEST_NUMBER_PREFIX = "SAT"
ORDER_NUMBER_PREFIX = "SP"

# EN AZ genislik — tavan DEGIL: 9999. kayittan sonra numara `…-10000` olarak
# UZAR. Basa donmek UQ ihlali demek olurdu.
SEQUENCE_WIDTH = 4

# Danisma kilidi anahtar uzayi (sabit, degistirilmez — bkz. modul docstring'i).
_REQUEST_LOCK_KEY = 82501
_ORDER_LOCK_KEY = 82502


async def generate_request_number(session: AsyncSession, *, year: int | None = None) -> str:
    """Talep numarasi uretir: `SAT-2026-0001`."""
    return await _next_number(
        session,
        prefix=REQUEST_NUMBER_PREFIX,
        column=PurchaseRequest.request_no,
        lock_key=_REQUEST_LOCK_KEY,
        year=year,
    )


async def generate_order_number(session: AsyncSession, *, year: int | None = None) -> str:
    """Siparis numarasi uretir: `SP-2026-0001`."""
    return await _next_number(
        session,
        prefix=ORDER_NUMBER_PREFIX,
        column=PurchaseOrder.order_no,
        lock_key=_ORDER_LOCK_KEY,
        year=year,
    )


async def _next_number(
    session: AsyncSession,
    *,
    prefix: str,
    column: InstrumentedAttribute[str],
    lock_key: int,
    year: int | None,
) -> str:
    effective_year = year if year is not None else date.today().year

    # Kilit ONCE alinir: okuma ile yazma arasina baska bir islem giremesin.
    # `_xact_` sonekli surum transaction sonunda KENDILIGINDEN birakilir —
    # elle `unlock` cagrisi unutulursa baglanti havuzunda sizinti olurdu.
    await session.execute(select(func.pg_advisory_xact_lock(lock_key, effective_year)))

    pattern = f"{prefix}-{effective_year}-"
    # Sira numarasi METINDIR; `max(request_no)` METIN siralamasi yapardi ve
    # `…-9999` ile `…-10000` karsilastirmasinda 9999'u buyuk sayardi (yeni
    # numara `…-10000` olur, UQ patlar). Bu yuzden sonek SAYIYA cevrilir.
    #
    # Suzgec `LIKE` degil REGEX'tir: cast, yalnizca tamamen rakamdan olusan
    # sonekleri gormeli — elle girilmis bir `SAT-2026-A1` kaydi (bugun mumkun
    # degil, yarin bir ice aktarim ucu ile mumkun olabilir) sorguyu patlatmasin.
    sequence = cast(func.substr(column, len(pattern) + 1), Integer)
    last = await session.scalar(
        select(func.max(sequence)).where(column.op("~")(f"^{pattern}[0-9]+$"))
    )

    return f"{prefix}-{effective_year}-{(last or 0) + 1:0{SEQUENCE_WIDTH}d}"
