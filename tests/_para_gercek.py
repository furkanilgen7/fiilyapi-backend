"""PARA-GERCEK — `mark-paid` kapısının ARKASINDAKİ parayı kuran ORTAK yardımcı.

Kapı şunu ister: hakedişin **bağlayıcı faturasına** yazılmış ve **nakde geçmiş**
ödemeler, hakedişin NETİNİ karşılasın. Bu modül o zinciri (`hakediş ← fatura ←
ödeme`) test tarafında kurar.

🔴 **NET ÜRÜN KODUNDAN OKUNUR, testte yeniden hesaplanmaz** (`hakedis_neti`).
Elle bir sayı yazılsaydı hesap formülü değiştiği gün bu yardımcı sessizce yanlış
tutarı yatırır ve sınır testi (`tam eşit tutar GEÇER`) hiçbir şey ölçmezdi.

🔴 **`odeme_yaz` bilerek ORM düzeyindedir, uç üzerinden DEĞİL.** Sebep, kapının
kendi bekçisini kurmasını önlemektir: `POST /invoices/{id}/payments` ucu
`PAYMENT_EXCEEDS_TOTAL` gibi KENDİ kurallarını da uygular ve "eksik ödeme" /
"portföydeki çek" gibi hâlleri kurmak o kuralların etrafından dolaşmayı
gerektirirdi. Ucun GERÇEKTEN çalıştığı ayrıca ve AÇIKÇA
`tests/subcontractor_progress_payments/test_para_gercek.py::
test_UCTAN_UCA_gercek_uclarla_hakedis_odenebiliyor`de kanıtlanır — yani bu
yardımcı kolaylık, uçtan uca kanıt ise ayrı bir testtir.
"""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.invoicing.models import (
    Invoice,
    InvoiceDirection,
    InvoiceDocumentType,
    InvoiceStatus,
)
from app.modules.progress_payments import calculations
from app.modules.progress_payments import repository as pp_repository
from app.modules.progress_payments import service as pp_service
from app.modules.progress_payments.models import ProgressPayment
from app.modules.subcontractor_progress_payments import amounts as sub_amounts
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
#: eşlemeyi `_UYUMLU_YON`da uygular ve uymayan bağı **422** ile reddeder; test
#: kurulumu da aynı eşlemeye uymak ZORUNDADIR, yoksa kurduğu çek gerçek üründe
#: hiç bağlanamayacak bir çek olurdu.
_EVRAK_YONU = {
    InvoiceDirection.outgoing: FinancialInstrumentDirection.received,
    InvoiceDirection.incoming: FinancialInstrumentDirection.issued,
}


async def hakedis_neti(session: AsyncSession, payment_id: uuid.UUID, *, taseron: bool) -> Decimal:
    """Hakedişin NETİ — kapının baktığı sayının ta kendisi, ÜRÜN kodundan.

    Taşeron tarafında `amounts.calculation_for`, işveren tarafında
    `service.calculation_block` çağrılır; ikisi de ekranın gösterdiği net ile
    aynı tek kopyadır.
    """
    if taseron:
        payment = await session.get(SubcontractorProgressPayment, payment_id)
        assert payment is not None
        return (await sub_amounts.calculation_for(session, payment)).net

    payment = await session.get(ProgressPayment, payment_id)
    assert payment is not None
    contract = await pp_repository.get_contract_locked(session, payment.project_id)
    assert contract is not None
    prior = await pp_repository.list_completed_payments(
        session, payment.project_id, before_sequence_no=payment.sequence_no
    )
    advance = calculations.cumulative_state(prior, contract.amount).advance_recovered
    return pp_service.calculation_block(payment, contract, advance).net


async def _banka_hesabi(session: AsyncSession) -> BankAccount:
    """Testin ödemesini yazacağı hesap; varsa YENİDEN AÇILMAZ.

    Aynı oturumda iki kez çağrıldığında ikinci bir hesap açmak `uq_bank_accounts_iban`
    kısmi indeksine takılmazdı ama bakiye testleriyle aynı veritabanını paylaşan
    kurulumlarda gereksiz gürültü üretirdi.
    """
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
    tutar: Decimal,
    status: InvoiceStatus | None = None,
    document_type: InvoiceDocumentType = InvoiceDocumentType.einvoice,
) -> Invoice:
    """Hakedişe BAĞLI fatura. Varsayılan durum yönün GİRİŞ durumudur.

    Gelen fatura sisteme `pending` girer, giden `draft` (`InvoiceStatus` K2) —
    varsayılanlar bu yüzden yöne göredir, tek bir sabit değil.
    """
    yon, kaynak_kolonu = _AILE[taseron]
    kullanici = (await session.execute(select(User).limit(1))).scalars().first()
    assert kullanici is not None, "Test kurulumunda kullanıcı yok"
    varsayilan = InvoiceStatus.pending if yon is InvoiceDirection.incoming else InvoiceStatus.draft
    fatura = Invoice(
        direction=yon,
        invoice_no=f"PG{uuid.uuid4().hex[:12].upper()}",
        document_type=document_type,
        status=status if status is not None else varsayilan,
        issue_date=date(2026, 1, 15),
        party_name="PARA-GERCEK Taraf",
        subtotal=tutar,
        advance_amount=Decimal("0.00"),
        retention_amount=Decimal("0.00"),
        tax_base=tutar,
        vat_amount=Decimal("0.00"),
        withholding_amount=Decimal("0.00"),
        total=tutar,
        created_by_id=kullanici.id,
    )
    setattr(fatura, kaynak_kolonu, payment_id)
    session.add(fatura)
    await session.flush()
    return fatura


async def odeme_yaz(
    session: AsyncSession,
    payment_id: uuid.UUID,
    *,
    taseron: bool,
    tutar: Decimal,
    evrak_durumu: FinancialInstrumentStatus | None = None,
    fatura: Invoice | None = None,
) -> Payment:
    """Hakedişin faturasına `tutar` kadar ödeme yazar.

    `evrak_durumu`:

    * **`None`** → çek/senet BAĞI YOKTUR. Ürünün tanımına göre bu ödeme
      DOĞRUDAN nakittir (`cash_realized_condition` ilk dalı) — `method` etiketi
      ne olursa olsun (ODM-1 D1).
    * **dolu** → o durumda bir çek AÇILIR ve ödeme ona BAĞLANIR. `portfolio`
      verildiğinde para henüz hareket etmemiştir ve kapı bu ödemeyi SAYMAMALIDIR;
      `collected`/`paid` verildiğinde saymalıdır.
    """
    yon, _ = _AILE[taseron]
    fatura = (
        fatura
        if fatura is not None
        else await fatura_kes(session, payment_id, taseron=taseron, tutar=tutar)
    )
    hesap = await _banka_hesabi(session)
    kullanici = (await session.execute(select(User).limit(1))).scalars().first()
    assert kullanici is not None

    evrak_id = None
    if evrak_durumu is not None:
        evrak = FinancialInstrument(
            instrument_kind=FinancialInstrumentKind.cheque,
            direction=_EVRAK_YONU[yon],
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

    odeme = Payment(
        invoice_id=fatura.id,
        bank_account_id=hesap.id,
        # Etiket bilerek `cheque`tir: kapının `method`e DEĞİL BAĞA baktığını,
        # bağsız bir `cheque` ödemesinin de nakit sayıldığını görünür kılar.
        method=PaymentMethodKind.cheque if evrak_durumu else PaymentMethodKind.transfer,
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
) -> Decimal:
    """Netin TAMAMINI (`fark` kadar sapmayla) yatırır; yatırılan tutarı döner.

    `fark=Decimal("-0.01")` sınırın ALTINI, `0` TAM EŞİTİ kurar — G3'ün iki yarısı.
    """
    net = await hakedis_neti(session, payment_id, taseron=taseron)
    tutar = net + fark
    await odeme_yaz(session, payment_id, taseron=taseron, tutar=tutar, evrak_durumu=evrak_durumu)
    return tutar
