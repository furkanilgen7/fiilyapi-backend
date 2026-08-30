"""PARA-GERCEK — `mark-paid` kapısının ARKASINDAKİ parayı kuran ORTAK yardımcı.

Kapı şunu ister: hakedişin **bağlayıcı faturası** olsun ve o faturaya yazılmış
**nakde geçmiş** ödemeler faturanın `total`ini karşılasın.

## 🔴 FATURA, ÜRÜNÜN KENDİ PARA MOTORUNDAN GEÇER (denetim bulgusu 2)

İlk hâlinde `fatura_kes` para kolonlarını ELLE dolduruyordu
(`subtotal = tax_base = total = tutar`, tüm oranlar 0). Yani kapının
karşılaştırdığı iki sayı testte ZORLA eşitleniyordu ve
`invoicing.amounts.compute` HİÇ çağrılmıyordu. Sonuç: kapının kesintili bir
hakedişte ULAŞILAMAZ olduğu (eşik hakediş netiydi, ödeme tavanı fatura
`total`i) **dört kapıdan da yeşil geçti**.

Bu, bu turda doğan kanonun vahşi doğada görülmesidir: **bir bekçi, ölçtüğü
yolu KENDİSİ kuruyorsa hiçbir şey ölçmüyordur.**

Artık fatura, kullanıcının yapacağı şeyin aynısıyla kurulur: hakedişin BRÜTÜ
tek kalem olarak, hakedişin KENDİ oranlarıyla (`vat_pct` · `advance_pct` ·
`retainage_pct`) `invoicing.amounts.compute`a verilir ve dönen yedi alan
kolonlara birebir yazılır. Oranlar sıfırlanmaz — fixture'ın kesintileri
(avans %10 · teminat %5 · KDV %20) faturaya AYNEN taşınır.
"""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.invoicing import amounts as invoice_amounts
from app.modules.invoicing.models import (
    Invoice,
    InvoiceDirection,
    InvoiceDocumentType,
    InvoiceStatus,
)
from app.modules.progress_payments import calculations
from app.modules.progress_payments.models import ProgressPayment
from app.modules.subcontractor_progress_payments.models import SubcontractorProgressPayment
from app.modules.treasury.models import (
    BankAccount,
    BankAccountType,
    FinancialInstrument,
    FinancialInstrumentDirection,
    FinancialInstrumentKind,
    FinancialInstrumentStatus,
    Payment,
    PaymentMethodKind,
)
from app.modules.users.models import User

#: Hakediş ailesi → (faturanın YÖNÜ, faturadaki kaynak KOLONU).
#:
#: 🔴 Yön UYDURULMADI, üründen okundu: işveren hakedişini biz faturalarız
#: (`outgoing`, para bize GELİR), taşeron bize fatura keser (`incoming`, para
#: bizden ÇIKAR). `treasury.payments_service._UYUMLU_YON` de aynı ikiliyi
#: kullanır ve çek yönünü buna göre denetler.
_AILE = {
    False: (InvoiceDirection.outgoing, "progress_payment_id"),
    True: (InvoiceDirection.incoming, "subcontractor_progress_payment_id"),
}

#: Fatura yönü → o yöne bağlanabilecek çek/senedin YÖNÜ (FIN-PAY K3). Ürün bu
#: eşlemeyi `_UYUMLU_YON`da uygular ve uymayan bağı **422** ile reddeder.
_EVRAK_YONU = {
    InvoiceDirection.outgoing: FinancialInstrumentDirection.received,
    InvoiceDirection.incoming: FinancialInstrumentDirection.issued,
}


async def _hakedis(session: AsyncSession, payment_id: uuid.UUID, *, taseron: bool):
    model = SubcontractorProgressPayment if taseron else ProgressPayment
    payment = await session.get(model, payment_id)
    assert payment is not None, "kurulum: hakediş bulunamadı"
    return payment


async def hakedis_bruttu(session: AsyncSession, payment_id: uuid.UUID, *, taseron: bool) -> Decimal:
    """Hakedişin BRÜTÜ — ürünün tek toplama kopyasından (`calculations.gross_total`)."""
    payment = await _hakedis(session, payment_id, taseron=taseron)
    return calculations.gross_total(payment.lines)


async def _banka_hesabi(session: AsyncSession) -> BankAccount:
    """Testin ödemesini yazacağı hesap; varsa YENİDEN AÇILMAZ."""
    mevcut = (
        await session.execute(select(BankAccount).where(BankAccount.bank_name == "PARA-GERCEK"))
    ).scalar_one_or_none()
    if mevcut is not None:
        return mevcut
    hesap = BankAccount(
        bank_name="PARA-GERCEK",
        account_type=BankAccountType.checking,
        opening_balance=Decimal("0.00"),
    )
    session.add(hesap)
    await session.flush()
    return hesap


async def fatura_kes(
    session: AsyncSession,
    payment_id: uuid.UUID,
    *,
    taseron: bool,
    brut: Decimal | None = None,
    status: InvoiceStatus | None = None,
    document_type: InvoiceDocumentType = InvoiceDocumentType.einvoice,
    kaynaga_bagla: bool = True,
    due_date: date | None = date(2026, 3, 1),
) -> Invoice:
    """Hakedişe bağlı fatura — para kolonları ÜRÜNÜN motorundan (bulgu 2).

    Oranlar hakedişin KENDİ kolonlarından okunur; kesintiler faturaya AYNEN
    taşınır. Böylece `total`, kullanıcının gerçekten keseceği faturanınkiyle
    aynı sayıdır ve kapı gerçek koşulda ölçülür.

    Varsayılan durum yönün GİRİŞ durumudur: gelen fatura `pending`, giden
    `draft` (`InvoiceStatus` K2).
    """
    yon, kaynak_kolonu = _AILE[taseron]
    payment = await _hakedis(session, payment_id, taseron=taseron)
    tutar = brut if brut is not None else calculations.gross_total(payment.lines)

    hesap = invoice_amounts.compute(
        [
            invoice_amounts.LineInput(
                quantity=Decimal("1"), unit_price=tutar, vat_rate=payment.vat_pct
            )
        ],
        advance_rate=payment.advance_pct,
        retention_rate=payment.retainage_pct,
        withholding_rate=None,
    )

    kullanici = (await session.execute(select(User).limit(1))).scalars().first()
    assert kullanici is not None, "Test kurulumunda kullanıcı yok"
    varsayilan = InvoiceStatus.pending if yon is InvoiceDirection.incoming else InvoiceStatus.draft
    fatura = Invoice(
        direction=yon,
        invoice_no=f"PG{uuid.uuid4().hex[:12].upper()}",
        document_type=document_type,
        status=status if status is not None else varsayilan,
        issue_date=date(2026, 1, 15),
        due_date=due_date,
        party_name="PARA-GERCEK Taraf",
        subtotal=hesap.subtotal,
        advance_rate=payment.advance_pct,
        advance_amount=hesap.advance_amount,
        retention_rate=payment.retainage_pct,
        retention_amount=hesap.retention_amount,
        tax_base=hesap.tax_base,
        vat_amount=hesap.vat_amount,
        withholding_amount=hesap.withholding_amount,
        total=hesap.total,
        created_by_id=kullanici.id,
    )
    if kaynaga_bagla:
        setattr(fatura, kaynak_kolonu, payment_id)
    session.add(fatura)
    await session.flush()
    return fatura


async def odeme_yaz(
    session: AsyncSession,
    fatura: Invoice,
    *,
    taseron: bool,
    tutar: Decimal,
    evrak_durumu: FinancialInstrumentStatus | None = None,
    method: PaymentMethodKind | None = None,
) -> Payment:
    """Faturaya `tutar` kadar ödeme yazar.

    `evrak_durumu`:

    * **`None`** → çek/senet BAĞI YOKTUR. Varsayılan `method` bu hâlde
      `transfer`dır, yani para indi demektir. 🔴 `method=cheque` ile ÇAĞRILIRSA
      kapı bunu SAYMAZ (`gate_realized_condition` fail-closed dalı) — bekçisi
      ayrı bir testtir.
    * **dolu** → o durumda bir çek AÇILIR ve ödeme ona BAĞLANIR. `portfolio`
      verildiğinde para henüz hareket etmemiştir.
    """
    hesap = await _banka_hesabi(session)
    kullanici = (await session.execute(select(User).limit(1))).scalars().first()
    assert kullanici is not None

    evrak_id = None
    if evrak_durumu is not None:
        evrak = FinancialInstrument(
            instrument_kind=FinancialInstrumentKind.cheque,
            direction=_EVRAK_YONU[_AILE[taseron][0]],
            serial_no=uuid.uuid4().hex[:10],
            drawer_name="PARA-GERCEK Keşideci",
            issue_date=date(2026, 1, 15),
            due_date=date(2026, 3, 15),
            amount=tutar,
            status=evrak_durumu,
        )
        session.add(evrak)
        await session.flush()
        evrak_id = evrak.id

    if method is None:
        method = PaymentMethodKind.cheque if evrak_durumu else PaymentMethodKind.transfer

    odeme = Payment(
        invoice_id=fatura.id,
        bank_account_id=hesap.id,
        method=method,
        financial_instrument_id=evrak_id,
        amount=tutar,
        paid_on=date(2026, 2, 1),
        created_by_id=kullanici.id,
    )
    session.add(odeme)
    await session.flush()
    return odeme


async def parayi_yatir(
    session: AsyncSession,
    payment_id: uuid.UUID,
    *,
    taseron: bool,
    evrak_durumu: FinancialInstrumentStatus | None = None,
    fark: Decimal = Decimal("0.00"),
    method: PaymentMethodKind | None = None,
    status: InvoiceStatus | None = None,
) -> Decimal:
    """Fatura keser ve `total`in TAMAMINI (`fark` sapmasıyla) yatırır.

    🔴 Eşik FATURANIN `total`idir (hakediş neti DEĞİL) — gerekçe
    `treasury/realized.py` docstring'inde. `fark=Decimal("-0.01")` sınırın
    ALTINI, `0` TAM EŞİTİ kurar.
    """
    fatura = await fatura_kes(session, payment_id, taseron=taseron, status=status)
    tutar = fatura.total + fark
    await odeme_yaz(
        session, fatura, taseron=taseron, tutar=tutar, evrak_durumu=evrak_durumu, method=method
    )
    return tutar
