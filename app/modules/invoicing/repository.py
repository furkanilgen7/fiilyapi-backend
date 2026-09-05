"""Fatura veri erişimi (T3) — yalnız SQL, yetki/kapsam KARARI yok.

Kapsam kararı (`visible_projects`) bu katmanda DEĞİL `service.py`dedir
(`procurement/repository.py` deseninin kardeşi); buraya yalnız çözülmüş proje
kimlikleri gelir.

Liste ve sayım AYNI süzgeç yardımcısını paylaşır: kopya açılsaydı `total` ile
gösterilen tablo zamanla ayrışırdı (FY sayfalaması "eksik kayıt" gösterirdi).

## 🔴 KAPSAMIN ÜÇÜNCÜ HÂLİ: `project_id IS NULL`

`purchase_requests`te proje ZORUNLUDUR, faturada DEĞİLDİR: şirket geneli fatura
(kira, genel gider) hiçbir projeye ait olmayabilir. Süzgeç bu yüzden
`IS NULL OR IN (görünenler)` biçimindedir (`equipment.site_id` emsali,
`repository.py:81`). Yalnız `IN` yazılsaydı projesiz faturalar HERKESTEN
gizlenir ve hiçbir ekranda görünmezlerdi — yazılabilen ama okunamayan bir kayıt
sınıfı doğardı.

## Kilit (spec §8)

`get_invoice(..., for_update=True)` satırı `with_for_update` +
`populate_existing` ile kilitler. `populate_existing` ŞARTTIR: kimlik haritası
bayat bir nesne taşıyorsa `session.get` onu SORGUSUZ döndürür ve kilit HİÇ
ALINMAZ — TOCTOU penceresi sessizce açık kalırdı.
"""

import uuid
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy import ColumnElement, Select, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.invoicing.models import (
    Invoice,
    InvoiceDirection,
    InvoiceLine,
    InvoiceStatus,
)

__all__ = [
    "DirectionAggregate",
    "aggregate_by_direction",
    "count_invoices",
    "delete_lines",
    "get_invoice",
    "invoice_no_exists",
    "list_invoices",
    "load_lines",
]


class DirectionAggregate(NamedTuple):
    """Bir YÖNÜN toplamı — özet ucunun (T4) tek satır tipi.

    Üç ölçü BİRLİKTE döner çünkü hepsi AYNI satır kümesinden gelir: ayrı
    sorgulara bölünselerdi araya giren bir yazma yüzünden adet ile tutar
    ayrışabilir ve kart "18 fatura · ₺0" gibi imkânsız bir çift gösterebilirdi.
    """

    amount: Decimal
    count: int
    vat_amount: Decimal


def _like_escape(deger: str) -> str:
    """LIKE joker karakterlerini KAÇIRIR (`inventory.repository` deseni).

    Kaçırılmazsa arama kutusuna `%` yazan kullanıcı TÜM faturaları, `_` yazan
    ise beklemediği satırları görür. Kaçış karakterinin kendisi ÖNCE kaçırılır.
    """
    return deger.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def scope_clause(project_ids: list[uuid.UUID]):
    """Görünürlük süzgeci — modül docstring'indeki üçüncü hâl dahil.

    PUBLIC: `service` tekil erişimde de bunu kullanır ki liste ile detay ASLA
    ayrışmasın (bir faturanın listede görünüp detayında 404 vermesi ya da tersi
    imkânsız olsun).
    """
    return Invoice.project_id.is_(None) | Invoice.project_id.in_(project_ids)


def _filtered(
    stmt: Select,
    project_ids: list[uuid.UUID],
    *,
    direction: InvoiceDirection | None,
    status: InvoiceStatus | None,
    project_id: uuid.UUID | None,
    site_id: uuid.UUID | None,
    q: str | None,
    date_from: date | None,
    date_to: date | None,
) -> Select:
    """FY filtre çubuğu + KAPSAM (spec §7 md.1). Süzgeçler AND'lidir.

    Kapsam süzgeci HER ZAMAN uygulanır ve kullanıcının verdiği `project_id`
    onun YERİNE değil ÜSTÜNE geçer: görünmeyen bir proje kimliği verildiğinde
    kesişim BOŞTUR, yani sızıntı olmaz.

    `q` FATURA NUMARASI ve TARAF ADI üzerinde kısmi arar (FY:94 `Fatura ara...`);
    FY satırı ikisini de basar ve tek alanda aramak kullanıcıyı "fatura yok"
    sanısına düşürürdü.

    Tarih aralığı KAPALIDIR (`>= date_from`, `<= date_to`): kullanıcı "18
    Temmuz'a kadar" derken o günü DIŞARIDA bırakmayı kastetmez.
    """
    stmt = stmt.where(scope_clause(project_ids))
    if direction is not None:
        stmt = stmt.where(Invoice.direction == direction)
    if status is not None:
        stmt = stmt.where(Invoice.status == status)
    if project_id is not None:
        stmt = stmt.where(Invoice.project_id == project_id)
    if site_id is not None:
        stmt = stmt.where(Invoice.site_id == site_id)
    if date_from is not None:
        stmt = stmt.where(Invoice.issue_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(Invoice.issue_date <= date_to)
    if q:
        desen = f"%{_like_escape(q)}%"
        stmt = stmt.where(
            Invoice.invoice_no.ilike(desen, escape="\\")
            | Invoice.party_name.ilike(desen, escape="\\")
        )
    return stmt


async def list_invoices(
    session: AsyncSession,
    project_ids: list[uuid.UUID],
    *,
    direction: InvoiceDirection | None = None,
    status: InvoiceStatus | None = None,
    project_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    q: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int,
    offset: int,
) -> list[Invoice]:
    """Sıralama DB'de: EN YENİ fatura üstte (FY tablosu tarihe göre azalan).

    İkinci ölçüt (`id`) olmasaydı aynı tarihli iki fatura her istekte farklı
    sırada gelir ve sayfalar arasında satır kaybolup tekrarlanabilirdi.
    """
    stmt = _filtered(
        select(Invoice),
        project_ids,
        direction=direction,
        status=status,
        project_id=project_id,
        site_id=site_id,
        q=q,
        date_from=date_from,
        date_to=date_to,
    )
    stmt = stmt.order_by(Invoice.issue_date.desc(), Invoice.id).limit(limit).offset(offset)
    return list((await session.execute(stmt)).scalars().all())


async def count_invoices(
    session: AsyncSession,
    project_ids: list[uuid.UUID],
    *,
    direction: InvoiceDirection | None = None,
    status: InvoiceStatus | None = None,
    project_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    q: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> int:
    """Sayım liste ile AYNI süzgeçten geçer — `total` tabloyla ayrışmasın."""
    stmt = _filtered(
        select(func.count()).select_from(Invoice),
        project_ids,
        direction=direction,
        status=status,
        project_id=project_id,
        site_id=site_id,
        q=q,
        date_from=date_from,
        date_to=date_to,
    )
    return (await session.execute(stmt)).scalar_one()


async def get_invoice(
    session: AsyncSession, invoice_id: uuid.UUID, *, for_update: bool = False
) -> Invoice | None:
    """Tekil okuma; `for_update` satırı KİLİTLER (spec §8, modül docstring'i)."""
    if not for_update:
        return await session.get(Invoice, invoice_id)
    return await session.get(Invoice, invoice_id, with_for_update=True, populate_existing=True)


async def list_invoices_by_no(session: AsyncSession, invoice_no: str) -> list[Invoice]:
    """URL-4: numaraya UYAN TUM faturalar — `direction` SUZULMEZ.

    🔴 Suzmek belirsizligi GORUNMEZ kilardi: `uq_invoices_no_direction` yon
    basina tekildir, yani ayni numara iki yonde birden bulunabilir. Cagiran
    (`visible_invoice`) once GORUNURLUK suzgecini uygular, SONRA kalan sayiya
    bakar (0 -> 404, 1 -> doner, 2 -> 409).

    Sira `direction, id` ile DETERMINISTIKTIR: 409 firlatilmadan once liste
    uzunlugu okunur, yani sira bir SECIME donusmez — ama testin ve gunlugun
    tekrarlanabilir olmasi icin yine de sabitlenir.
    """
    stmt = (
        select(Invoice)
        .where(Invoice.invoice_no == invoice_no)
        .order_by(Invoice.direction, Invoice.id)
    )
    return list((await session.execute(stmt)).scalars().all())


async def load_lines(session: AsyncSession, invoice_id: uuid.UUID) -> list[InvoiceLine]:
    """Kalemler HER ZAMAN `sort_order` sırasında okunur.

    Sırasız okuma Postgres'te fiziksel satır sırasına düşer ve bir REPLACE'ten
    sonra kullanıcının girdiği sıra karışır (SA/T3 dersi).
    """
    stmt = (
        select(InvoiceLine)
        .where(InvoiceLine.invoice_id == invoice_id)
        .order_by(InvoiceLine.sort_order, InvoiceLine.id)
    )
    return list((await session.execute(stmt)).scalars().all())


async def delete_lines(session: AsyncSession, invoice_id: uuid.UUID) -> None:
    """Toptan yazımın silme ayağı — TEK ifade (`DELETE … WHERE invoice_id = …`).

    Satır satır `session.delete` çağrılsaydı 40 kalemlik bir faturada 40 tur
    dönerdi; kilit sırası da bozulmazdı ama gereksiz gidiş-geliş yaratırdı.
    """
    await session.execute(delete(InvoiceLine).where(InvoiceLine.invoice_id == invoice_id))


_SIFIR = Decimal("0")


async def aggregate_by_direction(
    session: AsyncSession,
    project_ids: list[uuid.UUID],
    *,
    conditions: Sequence[ColumnElement[bool]] = (),
) -> dict[InvoiceDirection, DirectionAggregate]:
    """Özet ucunun (T4) TEK toplama yardımcısı — YÖNE göre gruplar.

    🔴 **Kapsam süzgeci burada da zorunludur** ve imzadan çıkarılamaz:
    `project_ids` konumsal bir parametredir, çağıran onu vermeyi "unutamaz".
    Süzgeç düşseydi özet, liste ucunun sakladığı tutarı sızdıran bir yan kapı
    olurdu — IDOR'un sayısal hâli.

    Beş KPI üç çağrıyla üretilir (yön başına ayrı sorgu AÇILMAZ): sorgu sayısı
    YÖN ya da DURUM sayısından bağımsızdır, yani N+1 yoktur.

    `coalesce` ŞARTTIR: boş kümede `sum()` NULL döner ve kart "₺0,00" yerine
    boş basılırdı (SA'nın NULL-EŞİK dersinin görüntü tarafı).
    """
    stmt = (
        select(
            Invoice.direction,
            func.coalesce(func.sum(Invoice.total), _SIFIR),
            func.count(),
            func.coalesce(func.sum(Invoice.vat_amount), _SIFIR),
        )
        .where(scope_clause(project_ids), *conditions)
        .group_by(Invoice.direction)
    )
    return {
        direction: DirectionAggregate(amount=amount, count=adet, vat_amount=vat)
        for direction, amount, adet, vat in (await session.execute(stmt)).all()
    }


async def invoice_no_exists(
    session: AsyncSession, direction: InvoiceDirection, invoice_no: str
) -> bool:
    """`uq_invoices_no_direction` ön denetimi — tekillik YÖN İÇİNDEDİR.

    Global sorgulansaydı bir satıcının `FIL…` serisi bizim numaramızı bloklardı
    (T1 gerekçesi). Yarış durumunda UQ ikinci katman olarak kalır.
    """
    stmt = (
        select(func.count())
        .select_from(Invoice)
        .where(Invoice.direction == direction, Invoice.invoice_no == invoice_no)
    )
    return bool((await session.execute(stmt)).scalar_one())
