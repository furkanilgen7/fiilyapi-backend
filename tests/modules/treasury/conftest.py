"""HZ-1 T3 — banka hesabı uçlarının login/yetki fixture'ları.

`tests/modules/invoicing/conftest.py` deseninin kardeşi: kök `tests/conftest.py`de
hazır başlık fixture'ı YOKTUR, her test paketi kendi `_login`/`_auth` yardımcısını
kurar.

İzin matrisi (`roles/seed_data.py:196`, **`treasury`** — seed'de ZATEN VARDI,
matris DEĞİŞMEDİ):
`"treasury": [_A, _F, _N, _N, _N, _F, _V, _N]` yani
system_admin=**_A** · patron=_F · site_chief=**_N** · field_engineer=_N ·
hr_manager=_N · accounting=**_F** · project_manager=**_V** · procurement=_N.

Seviye sırası `none < view < draft < request < approve < full < admin`
(`app/core/access.py`). T3'ün üç kapısı buradan çıkar:

* okuma (`view`)   → PM · muhasebe · patron · sysadmin; şef/saha/İK/satınalma 403;
* yazma (`full`)   → muhasebe/patron/sysadmin; **PM yazamaz** (403);
* silme (`admin`)  → YALNIZ sysadmin — `full` silmeyi KAPSAMAZ, muhasebe 403 alır.

🔴 **K3: kapsam (proje/şantiye) fixture'ı YOKTUR** ve bu bir eksiklik değildir.
Banka hesabı ŞİRKET GENELİDİR (`suppliers`/`customers` emsali); `UserProjectAccess`
kurmak, olmayan bir süzgeci varmış gibi gösteren bir test üretirdi.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.contracts.models import SubcontractorContract, SubcontractorContractItem
from app.modules.invoicing.models import (
    Invoice,
    InvoiceDirection,
    InvoiceDocumentType,
    InvoiceStatus,
)
from app.modules.projects.models import Project
from app.modules.subcontractor_progress_payments.models import (
    SubcontractorPaymentStatus,
    SubcontractorProgressPayment,
    SubcontractorProgressPaymentLine,
)
from app.modules.treasury.models import BankAccount, BankAccountType, Payment, PaymentMethodKind
from app.modules.users.models import User, UserProjectAccess
from tests._iban import tr_iban


async def _login(client: AsyncClient, user_factory, role_key: str, email: str) -> str:
    await user_factory(email=email, password="parola1234", role_key=role_key)
    resp = await client.post("/auth/login", json={"email": email, "password": "parola1234"})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def admin_headers(
    client: AsyncClient, seeded_db: AsyncSession, user_factory
) -> dict[str, str]:
    """`system_admin` — `treasury=_A`: TEK DELETE geçen rol."""
    return _auth(await _login(client, user_factory, "system_admin", "admin@hazine.co"))


@pytest.fixture
async def muhasebe_headers(
    client: AsyncClient, seeded_db: AsyncSession, user_factory
) -> dict[str, str]:
    """`accounting` — `treasury=_F`: yazar ama SİLEMEZ (403)."""
    return _auth(await _login(client, user_factory, "accounting", "muhasebe@hazine.co"))


@pytest.fixture
async def pm_headers(client: AsyncClient, seeded_db: AsyncSession, user_factory) -> dict[str, str]:
    """`project_manager` — `treasury=_V`: okur, yazamaz (403)."""
    return _auth(await _login(client, user_factory, "project_manager", "pm@hazine.co"))


@pytest.fixture
async def yetkisiz_headers(
    client: AsyncClient, seeded_db: AsyncSession, user_factory
) -> dict[str, str]:
    """`site_chief` — `treasury=_N`: okumada bile 403."""
    return _auth(await _login(client, user_factory, "site_chief", "sef@hazine.co"))


@pytest.fixture
def hesap_fabrikasi(seeded_db: AsyncSession):
    """Hesabı DOĞRUDAN kurar — uçtan geçilmez.

    POST ucundan kurulsaydı liste/detay testleri POST'un doğruluğuna bağlanır ve
    tek bir kusur bütün dosyayı kırmızıya çevirirdi (`fatura_fabrikasi` dersi).
    """
    sayac = {"n": 0}

    async def _create(
        *,
        bank_name: str = "Ziraat Bank",
        account_type: BankAccountType = BankAccountType.checking,
        iban: str | None = None,
        display_name: str | None = None,
        opening_balance: str = "0.00",
        is_active: bool = True,
    ) -> BankAccount:
        sayac["n"] += 1
        account = BankAccount(
            bank_name=bank_name,
            account_type=account_type,
            # 🔴 `f"TR{n:024d}"` mod-97'yi GEÇMEZ: doğrudan model kurulumunda
            # pydantic koşmadığı için fixture bunu hiç fark etmezdi ve gerçekte
            # var olamayacak bir IBAN üretirdi (`tests/_iban.py`).
            iban=iban if iban is not None else tr_iban(sayac["n"]),
            display_name=display_name,
            opening_balance=Decimal(opening_balance),
            is_active=is_active,
        )
        seeded_db.add(account)
        await seeded_db.flush()
        return account

    return _create


@pytest.fixture
def odeme_fabrikasi(seeded_db: AsyncSession, user_factory):
    """Hesaba BAĞLI bir ödeme satırı kurar (fatura dahil).

    İki testin taşıyıcısıdır: türetilmiş bakiyenin uçtan görünmesi ve ödemesi
    olan hesabın DELETE'te **409** alması (ham FK 500'ü SIZMAZ).
    """
    sayac = {"n": 0}

    async def _create(
        account: BankAccount,
        amount: str,
        direction: InvoiceDirection = InvoiceDirection.outgoing,
    ) -> Payment:
        sayac["n"] += 1
        creator = (
            await seeded_db.execute(select(User).where(User.email == "odeme@hazine.co"))
        ).scalar_one_or_none() or await user_factory(
            email="odeme@hazine.co", password="parola1234", role_key="system_admin"
        )
        toplam = Decimal("1000000.00")
        invoice = Invoice(
            direction=direction,
            invoice_no=f"HZT3{sayac['n']:08d}",
            document_type=InvoiceDocumentType.einvoice,
            status=InvoiceStatus.sent,
            issue_date=date(2026, 8, 1),
            party_name="Test Karşı Taraf",
            subtotal=toplam,
            advance_amount=Decimal("0.00"),
            retention_amount=Decimal("0.00"),
            tax_base=toplam,
            vat_amount=Decimal("0.00"),
            withholding_amount=Decimal("0.00"),
            total=toplam,
            created_by_id=creator.id,
        )
        seeded_db.add(invoice)
        await seeded_db.flush()
        payment = Payment(
            invoice_id=invoice.id,
            bank_account_id=account.id,
            method=PaymentMethodKind.transfer,
            amount=Decimal(amount),
            paid_on=date(2026, 8, 14),
            created_by_id=creator.id,
        )
        seeded_db.add(payment)
        await seeded_db.flush()
        return payment

    return _create


@pytest.fixture
async def kullanici_kimligi(seeded_db: AsyncSession):
    async def _resolve(email: str) -> uuid.UUID:
        return (await seeded_db.execute(select(User).where(User.email == email))).scalar_one().id

    return _resolve


# --------------------------------------------------------------------------- #
# HZ-1 T4 — ödeme uçları (6, 7, 8)
#
# İzin kapısı burada **`invoicing`**tir, `treasury` DEĞİL (spec §4): ödeme bir
# FATURAYA kaydedilir ve faturanın kapsam süzgecinden geçer. Matris satırları
# BİREBİR AYNIDIR (`[_A, _F, _N, _N, _N, _F, _V, _N]`), yani yukarıdaki dört
# başlık fixture'ı ikisini de temsil eder — ayrı bir kullanıcı kümesi kurmak
# aynı seviyeleri ikinci kez üretirdi.
# --------------------------------------------------------------------------- #


@pytest.fixture
def fatura_fabrikasi(seeded_db: AsyncSession, user_factory):
    """Faturayı İSTENEN yön/durum/TOPLAM ile DOĞRUDAN kurar.

    Uçlardan geçilerek kurulamaz: `sent` durumuna ulaşmak FAT-1'in geçiş
    uçlarını gerektirir ve K5 testleri o uçların doğruluğuna bağlanırdı
    (`fatura_fabrikasi` dersi, `tests/modules/invoicing/conftest.py`).

    `total` AÇIKÇA verilir çünkü K6 eşiği tam olarak onunla karşılaştırılır;
    kalemlerden türetilseydi sınır testleri (`= total` · `total + 0.01`)
    `amounts.compute`un yuvarlamasına bağımlı hâle gelirdi.
    """
    sayac = {"n": 0}

    async def _create(
        *,
        direction: InvoiceDirection = InvoiceDirection.outgoing,
        status: InvoiceStatus = InvoiceStatus.sent,
        total: str = "1000.00",
        project=None,  # noqa: ANN001
        due_date: date | None = None,
        party_name: str = "Test Karşı Taraf",
        source_payment=None,  # noqa: ANN001
    ) -> Invoice:
        sayac["n"] += 1
        creator = (
            await seeded_db.execute(select(User).where(User.email == "fabrika@hazine.co"))
        ).scalar_one_or_none() or await user_factory(
            email="fabrika@hazine.co", password="parola1234", role_key="system_admin"
        )
        tutar = Decimal(total)
        invoice = Invoice(
            direction=direction,
            invoice_no=f"HZT4{sayac['n']:08d}",
            document_type=InvoiceDocumentType.einvoice,
            status=status,
            issue_date=date(2026, 8, 1),
            due_date=due_date,
            party_name=party_name,
            subcontractor_progress_payment_id=(
                None if source_payment is None else source_payment.id
            ),
            project_id=None if project is None else project.id,
            subtotal=tutar,
            advance_amount=Decimal("0.00"),
            retention_amount=Decimal("0.00"),
            tax_base=tutar,
            vat_amount=Decimal("0.00"),
            withholding_amount=Decimal("0.00"),
            total=tutar,
            created_by_id=creator.id,
        )
        seeded_db.add(invoice)
        await seeded_db.flush()
        return invoice

    return _create


@pytest.fixture
def fatura_odemesi(seeded_db: AsyncSession, user_factory):
    """Var olan bir faturaya ödeme satırı ekler (uç 8 ve K5 testlerinin girdisi).

    `odeme_fabrikasi`dan AYRIDIR: o hesabın bakiyesi için kendi faturasını
    üretir, bu ise VERİLEN faturaya bağlanır — K5 (Σ payments → durum) ancak
    fatura ile ödemenin aynı kayıt üzerinde buluşmasıyla sınanabilir.
    """

    async def _create(
        invoice: Invoice,
        account: BankAccount,
        amount: str,
        *,
        paid_on: date = date(2026, 8, 14),
    ) -> Payment:
        creator = (
            await seeded_db.execute(select(User).where(User.email == "fabrika@hazine.co"))
        ).scalar_one_or_none() or await user_factory(
            email="fabrika@hazine.co", password="parola1234", role_key="system_admin"
        )
        payment = Payment(
            invoice_id=invoice.id,
            bank_account_id=account.id,
            method=PaymentMethodKind.transfer,
            amount=Decimal(amount),
            paid_on=paid_on,
            created_by_id=creator.id,
        )
        seeded_db.add(payment)
        await seeded_db.flush()
        return payment

    return _create


# --------------------------------------------------------------------------- #
# HZ-1 T5 — türev uçlar (9, 10)
#
# 🔴 K3 BURADA GENİŞLER: banka HESABI şirket geneli olsa da `upcoming-payments`in
# KAYNAKLARI (fatura · taşeron hakedişi) proje kapsamı taşır. Bu yüzden T5 —
# T3'ün aksine — proje/erişim fixture'ları KURAR: kapsam süzgeci olmadan
# `treasury=_V` olan bir proje müdürü, göremediği projenin karşı tarafını,
# evrak numarasını ve tutarını okurdu.
# --------------------------------------------------------------------------- #


@pytest.fixture
async def gorunen_proje(seeded_db: AsyncSession, project_factory) -> Project:
    return await project_factory(code="HZ-P01", name="Güneşkent Konut")


@pytest.fixture
async def gorunmeyen_proje(seeded_db: AsyncSession, project_factory) -> Project:
    """`kapsamli_muhasebe_headers` kullanıcısına ASLA erişim verilmeyen proje."""
    return await project_factory(code="HZ-P02", name="Liman Altyapı")


@pytest.fixture
async def kapsamli_muhasebe_headers(
    client: AsyncClient,
    seeded_db: AsyncSession,
    user_factory,
    gorunen_proje: Project,
    gorunmeyen_proje: Project,
) -> dict[str, str]:
    """`accounting` (`treasury=_F`, `projects=_FIN`) — kapsamı YALNIZ `gorunen_proje`.

    IDOR testlerinin taşıyıcısı budur: `admin_headers` (`projects=_A`) kapsam
    süzgecini ATLADIĞI için sızıntıyı hiçbir zaman gösteremez.
    """
    email = "kapsamli@hazine.co"
    await user_factory(email=email, password="parola1234", role_key="accounting")
    user = (await seeded_db.execute(select(User).where(User.email == email))).scalar_one()
    seeded_db.add(
        UserProjectAccess(user_id=user.id, project_id=gorunen_proje.id, all_projects=False)
    )
    await seeded_db.flush()
    return _auth(await _login_mevcut(client, email))


async def _login_mevcut(client: AsyncClient, email: str) -> str:
    resp = await client.post("/auth/login", json={"email": email, "password": "parola1234"})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest.fixture
def taseron_hakedisi_fabrikasi(seeded_db: AsyncSession, project_factory, user_factory):
    """Proje + taşeron sözleşmesi + ONAYLI hakediş (satırlarıyla) — TEK yardımcı.

    `tests/subcontractor_progress_payments/conftest.py`nin ağır kurulumu (işveren
    poz grubu, sözleşme kalemleri, bölüm) BURADA GEREKMEZ: T5 yalnız hakedişin
    NET tutarını ve vadesini okur. Yüzdeler varsayılan olarak SIFIRDIR ki
    `net == brüt` olsun ve tutar iddiası hesabın yuvarlamasına değil satırlara
    bağlansın; yüzdeli senaryo (net ≠ brüt) AYRI bir testin işidir.
    """
    sayac = {"n": 0}

    async def _create(
        *,
        project: Project | None = None,
        approved_at: datetime | None = None,
        payment_term_days: int = 30,
        status: SubcontractorPaymentStatus = SubcontractorPaymentStatus.approved,
        subcontractor_name: str | None = "Akın İnşaat",
        vat_pct: str = "0",
        advance_pct: str = "0",
        retainage_pct: str = "0",
        line_amounts: tuple[str, ...] = ("1000.00",),
        sequence_no: int | None = None,
    ) -> SubcontractorProgressPayment:
        sayac["n"] += 1
        creator = (
            await seeded_db.execute(select(User).where(User.email == "hakedis@hazine.co"))
        ).scalar_one_or_none() or await user_factory(
            email="hakedis@hazine.co", password="parola1234", role_key="system_admin"
        )
        if project is None:
            project = await project_factory(code=f"HZ-T{sayac['n']:02d}")
        contract = SubcontractorContract(
            project_id=project.id,
            subcontractor_name=subcontractor_name,
            contract_no=f"HZ-TSZ-{sayac['n']:03d}",
            advance_pct=Decimal(advance_pct),
            retainage_pct=Decimal(retainage_pct),
            vat_pct=Decimal(vat_pct),
            payment_term_days=payment_term_days,
            created_by=creator.id,
        )
        seeded_db.add(contract)
        await seeded_db.flush()
        # Sözleşme BEDELİ kalemlerden türer (`amount` kolonu YOK) ve avans
        # mahsubunun TAVANI odur: kalemsiz bir sözleşmede bedel 0 olur, tavan
        # 0'a düşer ve avans kesintisi HİÇ uygulanmaz — net tutar testi o zaman
        # kesintisiz bir sayıyı doğrulamış olurdu.
        seeded_db.add(
            SubcontractorContractItem(
                contract_id=contract.id,
                code="S001",
                description="Sözleşme kalemi",
                unit="Ton",
                quantity=Decimal("1000.000"),
                unit_price=Decimal("1000.00"),
                sort_order=0,
            )
        )
        await seeded_db.flush()
        payment = SubcontractorProgressPayment(
            contract_id=contract.id,
            project_id=project.id,
            sequence_no=sayac["n"] if sequence_no is None else sequence_no,
            status=status,
            vat_pct=contract.vat_pct,
            advance_pct=contract.advance_pct,
            retainage_pct=contract.retainage_pct,
            approved_at=approved_at,
            created_by=creator.id,
        )
        seeded_db.add(payment)
        await seeded_db.flush()
        for index, tutar in enumerate(line_amounts):
            seeded_db.add(
                SubcontractorProgressPaymentLine(
                    payment_id=payment.id,
                    code=f"K{index + 1:03d}",
                    description=f"Kalem {index + 1}",
                    unit="Ton",
                    contract_unit_price=Decimal(tutar),
                    coefficient=Decimal("1.000"),
                    quantity=Decimal("1.000"),
                    sort_order=index,
                )
            )
        await seeded_db.flush()
        await seeded_db.refresh(payment)
        return payment

    return _create
