"""MU-3D testlerinin ORTAK kurulumu — fixture DEĞİL, düz yardımcılar.

🔴 **Neden fixture değil:** bu dilim ÜÇ ayrı test paketinin nesnelerine dokunur
(`progress_payments` · `subcontractor_progress_payments` · `equipment`) ve o
paketlerin conftest'leri `hesap_fabrikasi`/`hakedis_fabrikasi` gibi ÇAKIŞAN
adlar taşır (MU-3C'nin `_mu3c.py`si aynı sebeple yazılmıştı). Düz fonksiyonlar
hem çakışmayı çözer hem de dört test dosyasının AYNI kurulumu paylaşmasını
sağlar — kopya kurulum bir gün ayrışır ve biri kuralı değil kurulumunu ölçer.

Kurulum canlıda `a4b5c6d7e8f9` (+ MU-3B'nin `c0d1e2f3a4b5` ve MU-3C'nin
`d1e2f3a4b5c6`) migration'larının tohumladığı satırların KARŞILIĞIDIR; test
kümesi migration koşmaz (`Base.metadata.create_all`), bu yüzden fişleme ölçen
HER test onu kurmak zorundadır. Eksik olduğunda ONAY **422** verir — fail-closed
olan taraf budur.
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
    JournalEntryStatus,
    JournalLine,
    JournalSourceType,
)
from app.modules.boq.models import BoqGroup, BoqItem
from app.modules.contracts.models import (
    EmployerContractGroup,
    EmployerContractItem,
    SubcontractorContract,
    SubcontractorContractItem,
)
from app.modules.equipment.models.enums import RentalInvoiceStatus
from app.modules.equipment.models.rental import EquipmentRentalInvoice
from app.modules.equipment.rental_posting import RENTAL_POSTING_RULES
from app.modules.invoicing.posting import INVOICE_POSTING_RULES
from app.modules.posting.models import PostingRule
from app.modules.procurement.models import PaymentTerms, Supplier
from app.modules.progress_payments.models import (
    ProgressPayment,
    ProgressPaymentLine,
    ProgressPaymentStatus,
)
from app.modules.progress_payments.posting import PROGRESS_PAYMENT_POSTING_RULES
from app.modules.projects.models import Project, ProjectContract
from app.modules.sites.models import Site
from app.modules.subcontractor_progress_payments.models import (
    SubcontractorPaymentStatus,
    SubcontractorProgressPayment,
    SubcontractorProgressPaymentLine,
)
from app.modules.subcontractor_progress_payments.posting import SUBCONTRACTOR_POSTING_RULES
from app.modules.users.models import User

#: Fişin bacaklarının düştüğü TDHP kodları — ÜRÜN demetinden okunmaz, iddianın
#: KENDİSİDİR (MU-3B/MU-3C deseni): testler kodu üründen okusaydı bir kural
#: yanlış hesaba çevrildiğinde YEŞİL kalırlardı.
KOD_ALICILAR = "120"
KOD_SATICILAR = "320"
KOD_SATIS = "600"
KOD_GIDER = "740"
KOD_HES_KDV = "391"
KOD_IND_KDV = "191"

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


#: 🔴 DÖRT AİLE BİRDEN kurulur ve bu ŞARTTIR: İŞ 2'nin takası (hakediş fişi
#: STORNO + fatura fişi YAZ) hakediş ile fatura eşlemesini AYNI veri kümesinde
#: ister. Yalnız hakediş kurulsaydı `send`/`approve` 422 alır ve takas dalına
#: HİÇ ULAŞILAMAZDI.
AILE_KURALLARI = (
    (JournalSourceType.invoice, INVOICE_POSTING_RULES),
    (JournalSourceType.progress_payment, PROGRESS_PAYMENT_POSTING_RULES),
    (JournalSourceType.subcontractor_progress_payment, SUBCONTRACTOR_POSTING_RULES),
    (JournalSourceType.equipment_rental_invoice, RENTAL_POSTING_RULES),
)


async def esleme_kur(session: AsyncSession) -> dict[str, ChartAccount]:
    """MU-3B + MU-3D `posting_rules` ÜRÜN eşlemesinin TAMAMI.

    Eşleme ÜRÜN demetlerinden kurulur; testte elle yazılsaydı üründeki demet
    bozulduğunda bu kurulum yeşil kalırdı.
    """
    hesaplar: dict[str, ChartAccount] = {}
    for _source_type, kurallar in AILE_KURALLARI:
        for _role_key, kod in kurallar:
            if kod not in hesaplar:
                hesaplar[kod] = await tdhp_hesabi(session, kod)
    for source_type, kurallar in AILE_KURALLARI:
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


async def aktor(session: AsyncSession, user_factory, email: str = "mu3d@hakedis.co") -> User:
    """`system_admin` — `projects=_A` olduğu için kapsam süzgecini ATLAR."""
    mevcut = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if mevcut is not None:
        return mevcut
    return await user_factory(email=email, password="parola1234", role_key="system_admin")


# --------------------------------------------------------------------------- #
# AİLE 1 — İŞVEREN HAKEDİŞİ
# --------------------------------------------------------------------------- #


async def isveren_hakedisi(
    session: AsyncSession,
    creator: User,
    *,
    kod: str = "MU3D-IS",
    contract_amount: str = "5000000",
    advance_pct: str = "20",
    retainage_pct: str = "5",
    miktar: str = "600",
    birim_fiyat: str = "100",
    sequence_no: int = 1,
    project: Project | None = None,
    contract: ProjectContract | None = None,
    site: Site | None = None,
    item: EmployerContractItem | None = None,
) -> tuple[ProgressPayment, ProjectContract, Project]:
    """`pending_approval` bir işveren hakedişi + tam nesne grafiği.

    🔴 `progress_payments.project_id` FK'si `project_contracts.project_id`ye
    gider: sözleşme SATIRI OLMADAN hakediş DOĞAMAZ.

    🔴 `_dagit` (BoQ kota satırı) ŞARTTIR: `transitions._revalidate_quota` onay
    anında kotayı yeniden doğrular ve kotasız kalem **422** alır — o 422
    fişleme dalına HİÇ ULAŞTIRMAZ ve kırmızı, ölçülen kuralı değil kurulumu
    gösterirdi.
    """
    if project is None:
        project = Project(code=kod, name=f"{kod} Projesi")
        session.add(project)
        await session.flush()
    if contract is None:
        contract = ProjectContract(
            project_id=project.id,
            contract_no=f"SZL-{kod}",
            amount=Decimal(contract_amount),
            advance_pct=Decimal(advance_pct),
            retainage_pct=Decimal(retainage_pct),
            vat_pct=Decimal("20"),
        )
        session.add(contract)
        await session.flush()
    if site is None:
        site = Site(project_id=project.id, code=f"SNT-{kod}", name=f"{kod} Şantiyesi")
        session.add(site)
        await session.flush()
    if item is None:
        group = EmployerContractGroup(project_id=project.id, name=f"{kod} Grubu", sort_order=1)
        session.add(group)
        await session.flush()
        item = EmployerContractItem(
            project_id=project.id,
            group_id=group.id,
            code="08.001",
            description="MU-3D pozu",
            unit="m³",
            quantity=Decimal("100000"),
            unit_price=Decimal(birim_fiyat),
            sort_order=1,
        )
        session.add(item)
        await session.flush()
        await _dagit(session, site, item, Decimal("100000"))

    payment = ProgressPayment(
        project_id=project.id,
        sequence_no=sequence_no,
        status=ProgressPaymentStatus.pending_approval,
        period_year=2026,
        period_month=7,
        vat_pct=contract.vat_pct,
        advance_pct=contract.advance_pct,
        retainage_pct=contract.retainage_pct,
        created_by=creator.id,
    )
    payment.lines = [
        ProgressPaymentLine(
            contract_item_id=item.id,
            site_id=site.id,
            code=item.code,
            description=item.description,
            unit=item.unit,
            contract_unit_price=item.unit_price,
            coefficient=Decimal("1.000"),
            quantity=Decimal(miktar),
            group_name="MU-3D Grubu",
        )
    ]
    session.add(payment)
    await session.flush()
    return payment, contract, project


async def _dagit(
    session: AsyncSession, site: Site, item: EmployerContractItem, quota: Decimal
) -> None:
    """Onay anındaki kota bekçisinin (`_revalidate_quota`) beklediği BoQ satırı."""
    group = (
        (await session.execute(select(BoqGroup).where(BoqGroup.site_id == site.id)))
        .scalars()
        .first()
    )
    if group is None:
        group = BoqGroup(site_id=site.id, name="MU-3D Dağıtım", sort_order=1)
        session.add(group)
        await session.flush()
    session.add(
        BoqItem(
            site_id=site.id,
            group_id=group.id,
            code=item.code,
            description=item.description,
            unit=item.unit,
            quantity=quota,
            unit_price=item.unit_price,
            contract_item_id=item.id,
        )
    )
    await session.flush()


# --------------------------------------------------------------------------- #
# AİLE 2 — TAŞERON HAKEDİŞİ
# --------------------------------------------------------------------------- #


async def taseron_hakedisi(
    session: AsyncSession,
    creator: User,
    *,
    kod: str = "MU3D-TS",
    birim_fiyat: str = "1000",
    miktar: str = "10",
    advance_pct: str = "10",
    retainage_pct: str = "5",
    sequence_no: int = 1,
    contract: SubcontractorContract | None = None,
) -> tuple[SubcontractorProgressPayment, SubcontractorContract]:
    """`pending_approval` bir taşeron hakedişi + tam nesne grafiği.

    🔴 Bu ailede BoQ kotası GEREKMEZ: kota `subcontractor_contract_items.
    quantity`den okunur (ölçüldü, `transitions._revalidate_quota`).
    """
    if contract is None:
        project = Project(code=kod, name=f"{kod} Projesi")
        session.add(project)
        await session.flush()
        # 🔴 `employer_contract_groups.project_id` FK'si `project_contracts.
        #    project_id`ye gider — sözleşme satırı ÖNCE flush EDİLMELİDİR.
        session.add(
            ProjectContract(
                project_id=project.id,
                contract_no=f"SZL-{kod}",
                amount=Decimal("11200000"),
            )
        )
        await session.flush()
        group = EmployerContractGroup(project_id=project.id, name=f"{kod} Grubu", sort_order=0)
        site = Site(project_id=project.id, code=f"SNT-{kod}", name=f"{kod} Şantiyesi")
        session.add_all([group, site])
        await session.flush()
        contract = SubcontractorContract(
            project_id=project.id,
            site_id=site.id,
            subcontractor_name="Çelik Kalıp Ltd.",
            contract_no=f"TSZ-{kod}",
            advance_pct=Decimal(advance_pct),
            retainage_pct=Decimal(retainage_pct),
            vat_pct=Decimal("20"),
            created_by=creator.id,
        )
        session.add(contract)
        await session.flush()
        employer_item = EmployerContractItem(
            project_id=project.id,
            group_id=group.id,
            code=f"{kod}.001",
            description="MU-3D taşeron pozu",
            unit="Ton",
            quantity=Decimal("10000"),
            unit_price=Decimal("25000"),
        )
        session.add(employer_item)
        await session.flush()
        session.add(
            SubcontractorContractItem(
                contract_id=contract.id,
                source_contract_item_id=employer_item.id,
                code=employer_item.code,
                description=employer_item.description,
                unit=employer_item.unit,
                quantity=Decimal("10000"),
                unit_price=Decimal(birim_fiyat),
                sort_order=0,
            )
        )
        await session.flush()
        await session.refresh(contract)

    payment = SubcontractorProgressPayment(
        contract_id=contract.id,
        project_id=contract.project_id,
        sequence_no=sequence_no,
        status=SubcontractorPaymentStatus.pending_approval,
        period_year=2026,
        period_month=7,
        vat_pct=contract.vat_pct,
        advance_pct=contract.advance_pct,
        retainage_pct=contract.retainage_pct,
        created_by=creator.id,
    )
    session.add(payment)
    await session.flush()
    kalem = sorted(contract.items, key=lambda satir: satir.sort_order)[0]
    session.add(
        SubcontractorProgressPaymentLine(
            payment_id=payment.id,
            contract_item_id=kalem.id,
            code=kalem.code,
            description=kalem.description,
            unit=kalem.unit,
            contract_unit_price=kalem.unit_price,
            coefficient=Decimal("1.000"),
            quantity=Decimal(miktar),
            sort_order=0,
        )
    )
    await session.flush()
    await session.refresh(payment)
    return payment, contract


# --------------------------------------------------------------------------- #
# AİLE 3 — MAKİNE KİRA HAKEDİŞİ
# --------------------------------------------------------------------------- #


async def kira_hakedisi(
    session: AsyncSession,
    *,
    invoice_amount: str | None = "100000.00",
    status: RentalInvoiceStatus = RentalInvoiceStatus.pending_verification,
    supplier: Supplier | None = None,
    period_month: int = 7,
) -> tuple[EquipmentRentalInvoice, Supplier]:
    """`pending_verification` bir kira hakedişi (bir `approve` ile `approved`).

    🔴 `invoice_amount=None` "girilmedi"dir, sıfır DEĞİL — o hâlde fiş HİÇ
    AÇILMAZ ve bu ayrıca ölçülür.
    """
    if supplier is None:
        supplier = Supplier(
            name=f"Akkaya Makine {uuid.uuid4().hex[:6]}", payment_terms=PaymentTerms.days_30
        )
        session.add(supplier)
        await session.flush()
    invoice = EquipmentRentalInvoice(
        supplier_id=supplier.id,
        period_year=2026,
        period_month=period_month,
        rate_period="hourly",
        invoice_amount=Decimal(invoice_amount) if invoice_amount is not None else None,
        vat_rate=Decimal("20.00"),
        status=status,
    )
    session.add(invoice)
    await session.flush()
    return invoice, supplier


# --------------------------------------------------------------------------- #
# ÖLÇÜM
# --------------------------------------------------------------------------- #


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


async def canli_fis(
    session: AsyncSession, source_type: JournalSourceType, source_id: uuid.UUID
) -> JournalEntry | None:
    """Belgenin CANLI fişi (`reversed` OLMAYAN). Ürün deposundan GEÇİLMEZ.

    `posting.repository.entry_for_source` çağrılsaydı test, ölçtüğü şeyin
    (fişin varlığı) tanımını ÜRÜNDEN alır ve o süzgeç bozulduğunda yeşil
    kalırdı.
    """
    return (
        await session.execute(
            select(JournalEntry)
            .where(JournalEntry.source_type == source_type)
            .where(JournalEntry.source_id == source_id)
            .where(JournalEntry.status != JournalEntryStatus.reversed)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


async def hesap_neti(
    session: AsyncSession, kod: str, *, ay: tuple[int, int] | None = None
) -> Decimal:
    """🔴 YEVMİYEDEN türeyen HAM net: `Σ borç − Σ alacak`.

    `balance.posting_filter()` kullanılır, yani `posted` **+ `reversed`**:
    stornolanan fiş defterden ÇIKMAZ, ters kaydıyla nötrlenir. Çıplak
    `status == posted` yazılsaydı bir storno turundan sonra toplam
    `−orijinal` kadar kayardı.

    `ay` verilirse `entry_date` O AYA daraltılır. 🔴 Bu bir kolaylık DEĞİL,
    ölçülmüş bir kör nokta kapatmasıdır: aylık bir büyüklüğü KÜMÜLATİF bir
    netle karşılaştıran mutabakat, veri tek aya sığdığı sürece TUTAR ve fişi
    yanlış güne yazan kusuru GÖREMEZ (MU-3C'nin M4 mutantı).
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
    """Ay penceresi — `vat_return.month_bounds` ile AYNI KAYNAKTAN.

    İkinci bir sınır aritmetiği yazılsaydı (Aralık taşması · ay uzunlukları)
    test ile ürün farklı pencereler kurar ve mutabakat sınır günlerinde
    sessizce ayrışırdı.
    """
    if ay is None:
        return ()
    from app.modules.accounting.vat_return import month_bounds

    ilk, son = month_bounds(*ay)
    return (JournalEntry.entry_date >= ilk, JournalEntry.entry_date <= son)


def bugun() -> date:
    """Fişin düştüğü gün — 🔴 **TR takvimiyle**, UTC ile DEĞİL.

    `datetime.now(UTC).date()` yazılsaydı bu yardımcı, ürünün TB5 bekçisiyle
    kapattığı kusurun TA KENDİSİNİ tekrarlar ve gece 00:00-03:00 arasında
    koşan bir tur, ürün DOĞRU davranırken KIRMIZI verirdi.
    """
    from app.core.timezone import today

    return today()
