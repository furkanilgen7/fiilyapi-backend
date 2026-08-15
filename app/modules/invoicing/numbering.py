"""Giden fatura numarası: `FIL` + yıl + 6 hane, AYRAÇSIZ (FAT-1 spec §4).

    FIL2026000184        (FY:111 · FGI:62)

⚠️ `procurement/numbering.py`nin `SAT-2026-0001` biçiminden İKİ farkı vardır ve
ikisi de mockup'tan okunur: **tire YOKTUR** ve **genişlik 6'dır**. Seri kökü
(`FIL`) hiçbir ayar ekranında çizilmediği için MODÜL SABİTİDİR — ayar yapılmaz.

YARIŞ KOŞULU (bu modülün asıl sebebi — SA docstring'inden birebir)
------------------------------------------------------------------
Naif uygulama "SELECT max(...) + 1"dir ve iki eş zamanlı istek AYNI numarayı
üretir: ikisi de diğerinin HENÜZ COMMIT ETMEDİĞİ satırı göremez. Çözüm İŞLEM
ÖMÜRLÜ DANIŞMA KİLİDİDİR (`pg_advisory_xact_lock`): kilit (dizi, yıl) çiftine
bağlanır, transaction commit/rollback ile KENDİLİĞİNDEN bırakılır ve ikinci
istek birincinin commit'ini bekler. `SELECT … FOR UPDATE` burada İŞE YARAMAZDI:
kilitlenecek SATIR henüz yoktur (yılın ilk numarası).

Kilit anahtarı SABİTTİR ve DEĞİŞTİRİLMEZ: değişirse eski sürümle yeni sürüm
aynı anda koşarken farklı kilitler alıp yarışı geri getirirler. 82501/82502
satınalmanındır; fatura 82601'i alır — paylaşılsalardı fatura kesen bir istek
ilgisiz bir satınalma talebini boşuna bekletirdi.

METİN SIRALAMASI TUZAĞI (ayraçsızlıkla BÜYÜR)
---------------------------------------------
Sıra numarası METİNDİR; `max(invoice_no)` metin sıralaması yapardı ve
`FIL2026999999` ile `FIL20261000000` karşılaştırmasında 999999'u büyük sayardı.
Üretici 999999'da SAPLANIR, her yeni fatura `uq_invoices_no_direction` ihlaliyle
500 verirdi. Bu yüzden sonek SAYIYA cast edilir. `SEQUENCE_WIDTH = 6` bir TAVAN
DEĞİL en az genişliktir: 999999'dan sonra numara 7 haneye UZAR (başa dönmek UQ
ihlali demek olurdu).

YALNIZ GİDEN (§4 / S5)
----------------------
Gelen faturanın numarası SATICININDIR ve istemciden gelir. İki sonucu vardır:
(1) `direction=incoming` ile çağrı HATADIR — sessizce bir `FIL…` üretmek gerçek
belgeyle bağı koparırdı; (2) sayaç sorgusu **yön süzgeçlidir** — bir satıcının
`FIL2026005000` numaralı gelen faturası sayacı ileri itseydi 4999 giden numara
sessizce ATLANIRDI ve tekillik yön içinde olduğu için hiçbir kısıt bunu
yakalamazdı.
"""

from sqlalchemy import Integer, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezone import today
from app.modules.invoicing.models import Invoice, InvoiceDirection

__all__ = ["INVOICE_NUMBER_PREFIX", "SEQUENCE_WIDTH", "generate_invoice_number"]

INVOICE_NUMBER_PREFIX = "FIL"

# EN AZ genişlik — tavan DEĞİL (bkz. modül docstring'i).
SEQUENCE_WIDTH = 6

# Danışma kilidi anahtarı (sabit, değiştirilmez — bkz. modül docstring'i).
_INVOICE_LOCK_KEY = 82601

INCOMING_NUMBER_NOT_GENERATED = "Gelen fatura numarası sunucu tarafından üretilmez"


async def generate_invoice_number(
    session: AsyncSession, direction: InvoiceDirection, *, year: int | None = None
) -> str:
    """Giden fatura numarası üretir: `FIL2026000001`.

    `direction` bir kolaylık parametresi DEĞİLDİR: çağıranı yön hakkında
    düşünmeye zorlar. Gelen fatura için çağrı `ValueError`dır — bu bir kullanıcı
    hatası değil PROGRAMLAMA hatasıdır (uç zaten istemciden numara ister), o
    yüzden `DomainError` türevi değildir ve 422'ye çevrilmez.
    """
    if direction is not InvoiceDirection.outgoing:
        raise ValueError(INCOMING_NUMBER_NOT_GENERATED)

    effective_year = year if year is not None else today().year

    # Kilit ÖNCE alınır: okuma ile yazma arasına başka bir işlem giremesin.
    # `_xact_` sonekli sürüm transaction sonunda KENDİLİĞİNDEN bırakılır.
    await session.execute(select(func.pg_advisory_xact_lock(_INVOICE_LOCK_KEY, effective_year)))

    pattern = f"{INVOICE_NUMBER_PREFIX}{effective_year}"
    # Süzgeç `LIKE` değil REGEX'tir: cast yalnızca tamamen rakamdan oluşan
    # sonekleri görmeli — gelen fatura serisi ELLE girildiği için `FIL2026-A1`
    # gibi bir kayıt bugün de mümkündür ve sorguyu patlatmamalıdır.
    sequence = cast(func.substr(Invoice.invoice_no, len(pattern) + 1), Integer)
    last = await session.scalar(
        select(func.max(sequence)).where(
            Invoice.direction == InvoiceDirection.outgoing,
            Invoice.invoice_no.op("~")(f"^{pattern}[0-9]+$"),
        )
    )

    return f"{pattern}{(last or 0) + 1:0{SEQUENCE_WIDTH}d}"
