"""Teklif alt-kaynagi (TEK) — talebin altinda, TEK karsilastirma yaniti.

Yazma yalniz `quote_wait`te aciktir (409); **OKUMA kisitlanmaz** — siparise
donmus bir talebin karsilastirma gecmisi silinmez, yalnizca degistirilemez.

"EN IYI FIYAT" rozeti TOPLAM maliyetten hesaplanir (siparis tutariyla AYNI
formul): birim fiyata bakilsaydi nakliyesi haric ucuz gorunen teklif yanlislikla
one cikardi.
"""

import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ProcurementValidationError
from app.modules.audit import messages
from app.modules.procurement import guards, repository, transitions
from app.modules.procurement.models import (
    PurchaseQuote,
    PurchaseRequest,
    PurchaseRequestStatus,
)
from app.modules.procurement.schemas import (
    PurchaseQuoteCard,
    PurchaseQuoteCreate,
    PurchaseQuoteListResponse,
    PurchaseQuoteResponse,
    PurchaseQuoteUpdate,
)
from app.modules.procurement.service.core import _strip
from app.modules.procurement.service.suppliers import get_supplier


async def _assert_quote_wait(request: PurchaseRequest) -> None:
    """Teklif YAZIMI yalniz `quote_wait`te acik — aksi **409**.

    OKUMA kisitlanmaz: siparise donmus bir talebin karsilastirma gecmisi
    silinmez, yalnizca degistirilemez.
    """
    if request.status is not PurchaseRequestStatus.quote_wait:
        raise ConflictError(guards.REQUEST_NOT_QUOTE_WAIT)


async def _visible_quote(
    session: AsyncSession, request: PurchaseRequest, quote_id: uuid.UUID
) -> PurchaseQuote:
    """Yol CAPRAZININ tek kapisi: teklif BU talebin altinda degilse **404**.

    Var olmayan teklif ile baska talebin teklifi AYNI govdeyi alir — ayri
    mesajlar teklifin nerede oldugunu ele verirdi (ST §4b kanonu).
    """
    quote = await repository.get_quote_in_request(session, request.id, quote_id)
    if quote is None:
        raise NotFoundError(guards.QUOTE_MISSING)
    return quote


def _assert_shipping_rule(shipping_included: bool, shipping_cost: Decimal | None) -> None:
    """TEK 90'in iki hali. **BIRLESIK degerler uzerinde kosar** (PATCH tuzagi):
    govde yalniz `shipping_cost` tasiyip `shipping_included` DB'de `true`
    kalabilir — yalniz govdeye bakan bir kural ihlali sessizce gecirirdi."""
    if shipping_included and shipping_cost is not None:
        raise ProcurementValidationError(guards.QUOTE_SHIPPING_CONFLICT)


async def _quote_response(session: AsyncSession, quote: PurchaseQuote) -> PurchaseQuoteResponse:
    supplier = await get_supplier(session, quote.supplier_id)
    return PurchaseQuoteResponse(
        **{
            alan: getattr(quote, alan)
            for alan in (
                "id",
                "request_id",
                "supplier_id",
                "unit_price",
                "delivery_time",
                "warranty_note",
                "payment_terms",
                "shipping_included",
                "shipping_cost",
                "is_selected",
                "created_at",
            )
        },
        supplier_name=supplier.name,
    )


async def list_quotes(session: AsyncSession, request: PurchaseRequest) -> PurchaseQuoteListResponse:
    """TEK karsilastirma yaniti: kartlar + TOPLAM MALIYET + "EN IYI FIYAT".

    Iki sorgu kosar ve sayisi TEKLIF SAYISINDAN BAGIMSIZDIR: teklifler+
    tedarikciler (JOIN) ve talebin toplam miktari.

    Rozet TOPLAM maliyetten hesaplanir (`transitions.order_total_from_quote` —
    siparis tutariyla AYNI formul): birim fiyata bakilsaydi nakliyesi haric
    ucuz gorunen teklif yanlislikla one cikardi.
    """
    quantity_total = await repository.request_quantity_total(session, request.id)
    rows = await repository.list_quotes(session, request.id)

    kartlar = [
        PurchaseQuoteCard(
            **_quote_fields(row[0]),
            supplier_name=row.supplier_name,
            total_cost=transitions.order_total_from_quote(
                row[0].unit_price, quantity_total, row[0].shipping_included, row[0].shipping_cost
            ),
            # Gecici deger: en dusuk toplam bilinmeden karar verilemez.
            is_best_price=False,
        )
        for row in rows
    ]
    if kartlar:
        en_dusuk = min(kart.total_cost for kart in kartlar)
        # Beraberlikte HEPSI rozetlenir — birini keyfi secmek yaniltici olurdu.
        kartlar = [
            kart.model_copy(update={"is_best_price": kart.total_cost == en_dusuk})
            for kart in kartlar
        ]

    return PurchaseQuoteListResponse(
        items=kartlar, total=len(kartlar), request_quantity_total=quantity_total
    )


def _quote_fields(quote: PurchaseQuote) -> dict:
    return {
        alan: getattr(quote, alan)
        for alan in (
            "id",
            "request_id",
            "supplier_id",
            "unit_price",
            "delivery_time",
            "warranty_note",
            "payment_terms",
            "shipping_included",
            "shipping_cost",
            "is_selected",
            "created_at",
        )
    }


async def create_quote(
    session: AsyncSession, request: PurchaseRequest, data: PurchaseQuoteCreate
) -> tuple[PurchaseQuoteResponse, str]:
    """Sira: durum (409) → tedarikci referansi (404) → yazma.

    Tedarikci `get_supplier` ile cozulur (**404**, govde ici varlik referansi
    kanonu). Once yazilip FK'ye birakilsaydi kullanici "Veri butunlugu hatasi"
    (409) gorur ve hangi alani duzeltecegini bilemezdi.
    """
    await _assert_quote_wait(request)
    supplier = await get_supplier(session, data.supplier_id)

    quote = PurchaseQuote(
        request_id=request.id,
        supplier_id=supplier.id,
        unit_price=data.unit_price,
        delivery_time=data.delivery_time.strip(),
        warranty_note=_strip(data.warranty_note),
        payment_terms=data.payment_terms,
        shipping_included=data.shipping_included,
        shipping_cost=data.shipping_cost,
    )
    session.add(quote)
    await session.flush()
    return await _quote_response(session, quote), messages.purchase_quote_created(
        request.request_no, supplier.name
    )


async def update_quote(
    session: AsyncSession,
    request: PurchaseRequest,
    quote_id: uuid.UUID,
    data: PurchaseQuoteUpdate,
) -> tuple[PurchaseQuoteResponse, str]:
    """Kismi guncelleme; yalniz `quote_wait`te (409).

    Nakliye kurali BIRLESIK degerlerde kosar (`_assert_shipping_rule`) ve
    YAZIMDAN ONCEDIR: ihlal hicbir alani degistirmeden reddedilir.
    """
    await _assert_quote_wait(request)
    quote = await _visible_quote(session, request, quote_id)
    verilen = data.model_dump(exclude_unset=True)

    shipping_included = verilen.get("shipping_included", quote.shipping_included)
    shipping_cost = verilen.get("shipping_cost", quote.shipping_cost)
    if shipping_included is None:
        # `null` gonderilen bool alan mevcut degeri KORUR (NOT NULL kolon).
        shipping_included = quote.shipping_included
    _assert_shipping_rule(shipping_included, shipping_cost)

    for alan in ("unit_price", "delivery_time", "payment_terms", "shipping_included"):
        if verilen.get(alan) is not None:
            setattr(quote, alan, verilen[alan])
    for alan in ("warranty_note", "shipping_cost"):
        if alan in verilen:
            setattr(quote, alan, verilen[alan])
    if isinstance(quote.delivery_time, str):
        quote.delivery_time = quote.delivery_time.strip()

    await session.flush()
    yanit = await _quote_response(session, quote)
    return yanit, messages.purchase_quote_updated(request.request_no, yanit.supplier_name)


async def delete_quote(session: AsyncSession, request: PurchaseRequest, quote_id: uuid.UUID) -> str:
    """Yalniz `quote_wait`te (409). Denetim metni satir YOK OLMADAN ONCE kurulur."""
    await _assert_quote_wait(request)
    quote = await _visible_quote(session, request, quote_id)
    supplier = await get_supplier(session, quote.supplier_id)
    detail = messages.purchase_quote_deleted(request.request_no, supplier.name)
    await session.delete(quote)
    await session.flush()
    return detail
