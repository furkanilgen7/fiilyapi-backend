"""PARA-GERCEK — KİRA ailesinin `pay` kapısını kuran yardımcı.

Kardeş iki hakediş ailesi `tests/_para_gercek.py`yi kullanır; kira ailesi ORADA
DEĞİLDİR ve olmamalıdır — o modül hakedişin `advance_pct`/`retainage_pct`
kolonlarından oran okur ve brütü `calculations.gross_total(payment.lines)` ile
satırlardan TÜRETİR. Kira ailesinde ikisi de YANLIŞTIR:

* avans/teminat kesintisi bu ailede **YOKTUR** (`rental_posting` §1),
* brüt satırlardan türemez, **`invoice_amount` KOLONUDUR** — `our_total`
  (satırların `saat × bedel` çapraz kontrolü) bir DOĞRULAMA büyüklüğüdür,
  ödenecek tutar değil ve fişin tabanı da odur değildir (`rental_posting:24`).

Ortak olan tek şey paranın kendisidir: ödeme yazımı (`odeme_yaz`) ve banka
hesabı `tests/_para_gercek.py`den AYNEN kullanılır, ikinci kopya yazılmaz.
"""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.equipment.models import EquipmentRentalInvoice
from app.modules.invoicing import amounts as invoice_amounts
from app.modules.invoicing.models import (
    Invoice,
    InvoiceDirection,
    InvoiceDocumentType,
    InvoiceStatus,
)
from app.modules.treasury.models import FinancialInstrumentStatus, PaymentMethodKind
from app.modules.users.models import User
from tests._para_gercek import odeme_yaz


async def kira_faturasi_kes(
    session: AsyncSession,
    rental_invoice_id: uuid.UUID,
    *,
    brut: Decimal | None = None,
    status: InvoiceStatus | None = None,
    document_type: InvoiceDocumentType = InvoiceDocumentType.einvoice,
    kaynaga_bagla: bool = True,
    kalemsiz: bool = False,
    direction: InvoiceDirection | None = None,
) -> Invoice:
    """Kira hakedişine bağlı fatura — para kolonları ÜRÜNÜN motorundan.

    Brüt varsayılanı kira hakedişinin `invoice_amount`ıdır; yani testteki iki
    sayı ZORLA eşitlenmez, kullanıcının gerçekten keseceği faturanın aynısı
    kurulur (kanon: *bir bekçi, ölçtüğü yolu kendisi kuruyorsa hiçbir şey
    ölçmüyordur*).

    KDV oranı hakedişin KENDİ `vat_rate` kolonundandır. `advance_rate` ve
    `retention_rate` BİLEREK verilmez: bu ailede öyle bir kesinti yoktur ve
    olmayan bir kesintiyi hesaplayan kurulum, okuyucuya var olmayan bir modeli
    varmış gibi gösterirdi.

    Bozuk hâller de kurulabilir ve bu ZORUNLUDUR: `kalemsiz=True` → `total=0`,
    `direction=` → yönü paranın akışına TERS kurar, `kaynaga_bagla=False` →
    fatura hakedişe hiç bağlanmaz.
    """
    hakedis = await session.get(EquipmentRentalInvoice, rental_invoice_id)
    assert hakedis is not None, "kurulum: kira hakedişi bulunamadı"
    tutar = brut if brut is not None else hakedis.invoice_amount
    assert tutar is not None, "kurulum: `invoice_amount` NULL, brüt açıkça verilmeli"

    kalemler = (
        []
        if kalemsiz
        else [
            invoice_amounts.LineInput(
                quantity=Decimal("1"), unit_price=tutar, vat_rate=hakedis.vat_rate
            )
        ]
    )
    hesap = invoice_amounts.compute(kalemler)

    kullanici = (await session.execute(select(User).limit(1))).scalars().first()
    assert kullanici is not None, "Test kurulumunda kullanıcı yok"
    # Kira firması BİZE fatura keser → `incoming`; giriş durumu `pending`.
    yon = direction if direction is not None else InvoiceDirection.incoming
    varsayilan = InvoiceStatus.pending if yon is InvoiceDirection.incoming else InvoiceStatus.draft
    fatura = Invoice(
        direction=yon,
        invoice_no=f"KPG{uuid.uuid4().hex[:11].upper()}",
        document_type=document_type,
        status=status if status is not None else varsayilan,
        issue_date=date(2026, 1, 15),
        due_date=date(2026, 3, 1),
        party_name="PARA-GERCEK Kiralama",
        subtotal=hesap.subtotal,
        advance_amount=hesap.advance_amount,
        retention_amount=hesap.retention_amount,
        tax_base=hesap.tax_base,
        vat_amount=hesap.vat_amount,
        withholding_amount=hesap.withholding_amount,
        total=hesap.total,
        created_by_id=kullanici.id,
    )
    if kaynaga_bagla:
        fatura.equipment_rental_invoice_id = rental_invoice_id
    session.add(fatura)
    await session.flush()
    return fatura


async def kira_parasini_yatir(
    session: AsyncSession,
    rental_invoice_id: uuid.UUID,
    *,
    evrak_durumu: FinancialInstrumentStatus | None = None,
    fark: Decimal = Decimal("0.00"),
    method: PaymentMethodKind | None = None,
    brut: Decimal | None = None,
) -> Decimal:
    """Fatura keser ve `total`in TAMAMINI (`fark` sapmasıyla) yatırır.

    Eşik faturanın `total`idir (`invoice_amount` DEĞİL): `fark=Decimal("-0.01")`
    sınırın ALTINI, `0` TAM EŞİTİ kurar.
    """
    fatura = await kira_faturasi_kes(session, rental_invoice_id, brut=brut)
    tutar = fatura.total + fark
    await odeme_yaz(session, fatura, tutar=tutar, evrak_durumu=evrak_durumu, method=method)
    return tutar
