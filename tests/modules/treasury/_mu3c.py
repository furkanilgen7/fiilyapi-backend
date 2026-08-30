"""MU-3C testlerinin ORTAK kurulumu — fixture DEĞİL, düz yardımcılar.

🔴 **Neden fixture değil:** `tests/modules/treasury/conftest.py` `hesap_fabrikasi`
adını ZATEN kullanıyor ve o bir **banka hesabı** (`bank_accounts`) fabrikasıdır;
muhasebenin hesap planı fabrikası (`tests/modules/accounting/conftest.py`) AYNI
adı taşır. İkisi bir arada dışa vurulamaz — MU-3B bu sorunu yaşamadı çünkü
`invoicing` paketinde çakışan bir ad yoktu. Düz fonksiyonlar hem çakışmayı
çözer hem de dört test dosyasının AYNI kurulumu paylaşmasını sağlar (kopya
kurulum bir gün ayrışır ve biri kuralı değil kurulumunu ölçer).

Kurulum canlıda `d1e2f3a4b5c6` (+ MU-3B'nin `c0d1e2f3a4b5`) migration'larının
tohumladığı satırların KARŞILIĞIDIR; test kümesi migration koşmaz
(`Base.metadata.create_all`), bu yüzden fişleme ölçen HER test onu kurmak
zorundadır. Eksik olduğunda `create_payment` **422** verir — fail-closed olan
taraf budur.
"""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounting.balance import posting_filter
from app.modules.accounting.chart_seed_data import CHART_ACCOUNTS
from app.modules.accounting.models import (
    ChartAccount,
    JournalEntry,
    JournalLine,
    JournalSourceType,
)
from app.modules.invoicing.models import (
    Invoice,
    InvoiceDirection,
    InvoiceDocumentType,
    InvoiceLine,
    InvoiceStatus,
)
from app.modules.invoicing.posting import INVOICE_POSTING_RULES
from app.modules.posting.models import PostingRule
from app.modules.treasury.instruments.posting import INSTRUMENT_POSTING_RULES
from app.modules.treasury.models import BankAccount, BankAccountType
from app.modules.treasury.posting import PAYMENT_POSTING_RULES
from app.modules.users.models import User

#: Fişin bacaklarının düştüğü TDHP kodları — ÜRÜN demetinden okunmaz, iddianın
#: KENDİSİDİR (MU-3B deseni): testler kodu üründen okusaydı bir kural yanlış
#: hesaba çevrildiğinde yeşil kalırlardı.
KOD_KASA = "100"
KOD_BANKA = "102"
KOD_ALINAN_CEK = "101"
KOD_VERILEN_CEK = "103"
KOD_ALICILAR = "120"
KOD_SATICILAR = "320"
KOD_SATIS = "600"
KOD_GIDER = "740"
KOD_HES_KDV = "391"
KOD_IND_KDV = "191"

TARIH = date(2026, 7, 17)

_TOHUM = {satir.code: satir for satir in CHART_ACCOUNTS}


async def tdhp_hesabi(session: AsyncSession, code: str) -> ChartAccount:
    """Hesap planı kaydını TDHP tohumunun ALANLARIYLA kurar.

    🔴 `account_type`/`is_contra` elle YAZILMAZ: `600`ü `expense` sayan bir
    kurulum `balance.SIGN`ın işaretini sessizce ters çevirir ve mutabakat testi
    YANLIŞ bir büyüklükle tutardı.
    """
    kart = _TOHUM[code]
    account = ChartAccount(
        code=kart.code,
        name=kart.name,
        account_type=kart.account_type,
        is_contra=kart.is_contra,
    )
    session.add(account)
    await session.flush()
    return account


async def esleme_kur(session: AsyncSession) -> dict[str, ChartAccount]:
    """MU-3B + MU-3C + ODM-1 `posting_rules` ÜRÜN eşlemesinin TAMAMI.

    İKİSİ birden kurulur ve bu ŞARTTIR: mutabakat testi faturanın fişi ile
    ödemenin fişini AYNI veri kümesinde ister — `120`yi açan MU-3B, kapatan
    MU-3C'dir ve tek başına hiçbiri cariyi netlemez.

    Eşleme ÜRÜN demetlerinden kurulur; testte elle yazılsaydı üründeki demet
    bozulduğunda bu kurulum yeşil kalırdı.
    """
    aile_kurallari = (
        (JournalSourceType.invoice, INVOICE_POSTING_RULES),
        (JournalSourceType.payment, PAYMENT_POSTING_RULES),
        # 🔴 ODM-1 — ÇEK/SENET ailesi de kurulur ve kurulmak ZORUNDADIR: `101`e
        #    GİREN ödeme fişi ile onu ÇIKARAN tahsil fişi AYNI veri kümesinde
        #    ölçülür. Yalnız `payment` kurulsaydı tahsil geçişi `post_document`in
        #    eksik eşleme dalından 422 alır ve kırmızı, ölçülen kuralı değil
        #    KURULUMU gösterirdi.
        (JournalSourceType.financial_instrument, INSTRUMENT_POSTING_RULES),
    )
    hesaplar: dict[str, ChartAccount] = {}
    for _source_type, kurallar in aile_kurallari:
        for _role_key, kod in kurallar:
            if kod not in hesaplar:
                hesaplar[kod] = await tdhp_hesabi(session, kod)
    for source_type, kurallar in aile_kurallari:
        for role_key, kod in kurallar:
            session.add(
                PostingRule(
                    source_type=source_type,
                    role_key=role_key,
                    account_id=hesaplar[kod].id,
                )
            )
    await session.flush()
    return hesaplar


async def aktor(session: AsyncSession, user_factory, email: str = "mu3c@hazine.co") -> User:
    """`system_admin` — `projects=_A` olduğu için kapsam süzgecini ATLAR.

    Kapsam denetimi bu dilimin konusu değildir ve `test_hz1_payments_api.py`de
    zaten ölçülüdür; buraya taşınsaydı kırmızı, kuralı değil yetki kurulumunu
    gösterirdi.
    """
    mevcut = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if mevcut is not None:
        return mevcut
    return await user_factory(email=email, password="parola1234", role_key="system_admin")


async def banka_hesabi(
    session: AsyncSession,
    *,
    account_type: BankAccountType = BankAccountType.checking,
    opening_balance: str = "0.00",
) -> BankAccount:
    """Banka ya da KASA hesabı. IBAN yok (kısmi tekillik NULL'ları çoklar)."""
    account = BankAccount(
        bank_name="Ziraat Bank",
        account_type=account_type,
        iban=None,
        display_name="Merkez Kasa" if account_type is BankAccountType.cash else None,
        opening_balance=Decimal(opening_balance),
    )
    session.add(account)
    await session.flush()
    return account


async def fatura(
    session: AsyncSession,
    creator: User,
    *,
    direction: InvoiceDirection,
    total: str,
    tax_base: str | None = None,
    vat_amount: str = "0.00",
    status: InvoiceStatus | None = None,
    issue_date: date = TARIH,
    document_type: InvoiceDocumentType = InvoiceDocumentType.einvoice,
) -> Invoice:
    """Faturayı DOĞRUDAN kurar; para kolonları AÇIKÇA verilir.

    `amounts.compute` çağrılmaz: bu dilimin ölçtüğü büyüklük ödemenin tutarıdır
    ve faturanın aritmetiği MU-3B'de zaten ölçülüdür. `total` açık verilir çünkü
    K6 eşiği (aşırı tahsilat) tam olarak onunla karşılaştırılır.
    """
    tutar = Decimal(total)
    matrah = Decimal(tax_base) if tax_base is not None else tutar
    invoice = Invoice(
        direction=direction,
        invoice_no=f"MU3C{uuid.uuid4().hex[:10].upper()}",
        document_type=document_type,
        status=(
            status
            if status is not None
            else (
                InvoiceStatus.draft
                if direction is InvoiceDirection.outgoing
                else InvoiceStatus.pending
            )
        ),
        issue_date=issue_date,
        party_name="Çelik Holding A.Ş.",
        subtotal=matrah,
        advance_amount=Decimal("0.00"),
        retention_amount=Decimal("0.00"),
        tax_base=matrah,
        vat_amount=Decimal(vat_amount),
        withholding_amount=Decimal("0.00"),
        total=tutar,
        created_by_id=creator.id,
    )
    session.add(invoice)
    await session.flush()
    # 🔴 TEK KALEM ŞART: `send`/`approve` K6 kapısı (`validation.gate_blockers`)
    # kalemsiz faturayı **422** ile durdurur. Kalemsiz kurulsaydı fişleme dalına
    # HİÇ ULAŞILAMAZ ve kırmızı, ölçülen kuralı değil kurulumu gösterirdi.
    # Kalemin tutarı fişe GİRMEZ (K7: fiş faturanın DONMUŞ kolonlarından okur).
    session.add(
        InvoiceLine(
            invoice_id=invoice.id,
            sort_order=0,
            description="Kalem 1",
            quantity=Decimal("1"),
            unit_price=matrah,
            vat_rate=Decimal("0"),
            line_total=matrah,
        )
    )
    await session.flush()
    return invoice


async def bacaklar(session: AsyncSession, entry: JournalEntry) -> list[tuple[str, str, str]]:
    """`(hesap kodu, borç, alacak)` — `sort_order` sırasında, METİN olarak.

    Metin karşılaştırması ÖLÇEĞİ de kilitler: `Decimal("1000")` ile
    `Decimal("1000.00")` eşittir ama kuruş hanesi kaybolmuş bir tutar mali
    tabloda başka bir şeydir.
    """
    rows = (
        await session.execute(
            select(ChartAccount.code, JournalLine.debit, JournalLine.credit)
            .join(JournalLine, JournalLine.account_id == ChartAccount.id)
            .where(JournalLine.entry_id == entry.id)
            .order_by(JournalLine.sort_order)
        )
    ).all()
    return [(kod, str(borc), str(alacak)) for kod, borc, alacak in rows]


async def hesap_neti(
    session: AsyncSession, kod: str, *, ay: tuple[int, int] | None = None
) -> Decimal:
    """🔴 YEVMİYEDEN türeyen HAM net: `Σ borç − Σ alacak`.

    `ay` verilirse `entry_date` O AYA daraltılır. 🔴 Bu parametre bir kolaylık
    DEĞİL, ölçülmüş bir kör nokta kapatmasıdır: `/treasury/cash-flow` AYLIK bir
    büyüklüktür ve KÜMÜLATİF bir netle karşılaştırılırsa, veri tek aya sığdığı
    sürece TUTAR — `entry_date`i `paid_on` yerine BUGÜNE yazan bir mutant
    (M4) o karşılaştırmayı KIRMIYORDU. Pencere iki tarafta da AYNI olmalıdır.

    `balance.posting_filter()` kullanılır, yani `posted` **+ `reversed`**:
    stornolanan fiş defterden ÇIKMAZ, ters kaydıyla nötrlenir. Çıplak
    `status == posted` yazılsaydı bir storno turundan sonra toplam
    `−orijinal` kadar kayardı.

    İşaret dönüşümü (`balance.SIGN`) UYGULANMAZ: mutabakat aktif/pasif
    sunumunu değil, defterin ham hareketini karşılaştırır.
    """
    net = (
        await session.execute(
            select(func.coalesce(func.sum(JournalLine.debit) - func.sum(JournalLine.credit), 0))
            .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
            .join(ChartAccount, ChartAccount.id == JournalLine.account_id)
            .where(ChartAccount.code == kod)
            .where(posting_filter())
            .where(*_ay_kosullari(ay))
        )
    ).scalar_one()
    return Decimal(net)


def _ay_kosullari(ay: tuple[int, int] | None):
    """Ay penceresi — `cash_flow.month_bounds` ile AYNI KAYNAKTAN.

    İkinci bir sınır aritmetiği yazılsaydı (Aralık taşması · ay uzunlukları)
    test ile ürün farklı pencereler kurar ve mutabakat sınır günlerinde
    sessizce ayrışırdı.
    """
    if ay is None:
        return ()
    from app.modules.treasury.cash_flow import month_bounds

    ilk, son = month_bounds(*ay)
    return (JournalEntry.entry_date >= ilk, JournalEntry.entry_date <= son)


async def canli_fis(
    session: AsyncSession, source_type: JournalSourceType, source_id: uuid.UUID
) -> JournalEntry | None:
    """Belgenin CANLI fişi (`reversed` OLMAYAN). Ürün deposundan geçilmez.

    `posting.repository.entry_for_source` çağrılsaydı test, ölçtüğü şeyin
    (fişin varlığı) tanımını ÜRÜNDEN alır ve o süzgeç bozulduğunda yeşil
    kalırdı.
    """
    from app.modules.accounting.models import JournalEntryStatus

    return (
        await session.execute(
            select(JournalEntry)
            .where(JournalEntry.source_type == source_type)
            .where(JournalEntry.source_id == source_id)
            .where(JournalEntry.status != JournalEntryStatus.reversed)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
