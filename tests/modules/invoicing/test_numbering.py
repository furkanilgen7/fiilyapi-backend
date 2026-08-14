"""FAT-1 T2 — giden fatura numarası (`invoicing/numbering.py`, spec §4).

Biçim `SAT-YYYY-NNNN`den FARKLIDIR: **tire YOKTUR ve genişlik 6'dır** →
`FIL2026000184` (FY:111, FGI:62). Ayraçsızlık metin sıralaması tuzağını
büyütür — bu yüzden `procurement/numbering.py`nin sonek-SAYIYA-cast deseni
birebir taşınır ve `test_METIN_SIRALAMASI_TUZAGI_kisa_numarayi_buyuk_saymaz`
onu kilitler (İKİ satırla; tek satırlı bir kurulum kusuru göremez).

İkinci ve yalnız burada geçerli olan kural: sayaç **yalnız giden faturalara
bakar.** Gelen faturanın numarası SATICININDIR (§4/S5) ve bir satıcının `FIL`
ile başlayan serisi bizim sayacımızı ileri itmemelidir — `uq_invoices_no_direction`
tekilliği de yön içindedir, yani böyle bir kayma sessizce numara ATLATIR.
"""

import asyncio
import uuid
from datetime import date
from decimal import Decimal

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.db import Base
from app.modules.invoicing import numbering
from app.modules.invoicing.models import (
    Invoice,
    InvoiceDirection,
    InvoiceDocumentType,
    InvoiceStatus,
)
from app.modules.invoicing.numbering import (
    INVOICE_NUMBER_PREFIX,
    SEQUENCE_WIDTH,
    generate_invoice_number,
)
from app.modules.procurement.numbering import (
    _ORDER_LOCK_KEY,
    _REQUEST_LOCK_KEY,
)


def _invoice_values(
    *,
    invoice_no: str,
    user_id: uuid.UUID,
    direction: InvoiceDirection = InvoiceDirection.outgoing,
    issue_date: date = date(2026, 8, 14),
) -> dict[str, object]:
    return {
        "direction": direction,
        "invoice_no": invoice_no,
        "document_type": InvoiceDocumentType.einvoice,
        "status": InvoiceStatus.draft,
        "issue_date": issue_date,
        "party_name": "Güneşkent Gayrimenkul A.Ş.",
        "subtotal": Decimal("0.00"),
        "advance_amount": Decimal("0.00"),
        "retention_amount": Decimal("0.00"),
        "tax_base": Decimal("0.00"),
        "vat_amount": Decimal("0.00"),
        "withholding_amount": Decimal("0.00"),
        "total": Decimal("0.00"),
        "created_by_id": user_id,
    }


async def _add_invoice(session: AsyncSession, **kwargs: object) -> Invoice:
    invoice = Invoice(**_invoice_values(**kwargs))  # type: ignore[arg-type]
    session.add(invoice)
    await session.flush()
    return invoice


@pytest.fixture
async def numara_ortami(db_session: AsyncSession, user_factory):
    user = await user_factory(
        email=f"{uuid.uuid4().hex[:8]}@ornek.test", password="x", role_key="system_admin"
    )
    return db_session, user


# --------------------------------------------------------------------------- #
# Biçim
# --------------------------------------------------------------------------- #


async def test_yilin_ilk_numarasi_bir_ile_baslar(numara_ortami):
    session, _ = numara_ortami
    assert await generate_invoice_number(session, InvoiceDirection.outgoing, year=2026) == (
        "FIL2026000001"
    )


async def test_bicim_ayracsiz_ve_alti_hane(numara_ortami):
    """⚠️ `SAT-2026-0001`den FARKLI: tire YOK, genişlik 6 (FY:111 `FIL2026000184`)."""
    session, user = numara_ortami
    await _add_invoice(session, invoice_no="FIL2026000183", user_id=user.id)
    numara = await generate_invoice_number(session, InvoiceDirection.outgoing, year=2026)
    assert numara == "FIL2026000184"
    assert "-" not in numara
    assert len(numara) == 13
    assert (INVOICE_NUMBER_PREFIX, SEQUENCE_WIDTH) == ("FIL", 6)


async def test_sira_mevcut_en_buyuk_numaradan_devam_eder(numara_ortami):
    session, user = numara_ortami
    for numara in ("FIL2026000001", "FIL2026000007", "FIL2026000003"):
        await _add_invoice(session, invoice_no=numara, user_id=user.id)
    # EN BÜYÜK + 1 — "satır sayısı + 1" olsaydı 000004 dönüp UQ'yu ihlal ederdi.
    assert await generate_invoice_number(session, InvoiceDirection.outgoing, year=2026) == (
        "FIL2026000008"
    )


async def test_yil_sinirinda_sira_sifirlanir(numara_ortami):
    session, user = numara_ortami
    await _add_invoice(
        session,
        invoice_no="FIL2025000042",
        user_id=user.id,
        issue_date=date(2025, 12, 31),
    )
    assert await generate_invoice_number(session, InvoiceDirection.outgoing, year=2026) == (
        "FIL2026000001"
    )
    assert await generate_invoice_number(session, InvoiceDirection.outgoing, year=2025) == (
        "FIL2025000043"
    )


async def test_yil_verilmezse_bugunun_yili_kullanilir(numara_ortami):
    session, _ = numara_ortami
    bugun = date.today().year
    assert await generate_invoice_number(session, InvoiceDirection.outgoing) == (
        f"FIL{bugun}000001"
    )


# --------------------------------------------------------------------------- #
# Metin sıralaması tuzağı — dolgu bir TAVAN DEĞİLDİR
# --------------------------------------------------------------------------- #


async def test_dolgu_icinde_hane_atlayisi_dogru_siralanir(numara_ortami):
    session, user = numara_ortami
    await _add_invoice(session, invoice_no="FIL2026009999", user_id=user.id)
    assert await generate_invoice_number(session, InvoiceDirection.outgoing, year=2026) == (
        "FIL2026010000"
    )


async def test_dolgu_genisligi_asilinca_numara_UZAR(numara_ortami):
    """6 hane bir TAVAN değil, en az genişliktir: 999999'dan sonra numara 7
    haneye uzar ve yine TEKİLDİR (başa dönüp UQ'yu ihlal etmez)."""
    session, user = numara_ortami
    await _add_invoice(session, invoice_no="FIL2026999999", user_id=user.id)
    assert await generate_invoice_number(session, InvoiceDirection.outgoing, year=2026) == (
        "FIL20261000000"
    )


async def test_METIN_SIRALAMASI_TUZAGI_kisa_numarayi_buyuk_saymaz(numara_ortami):
    """🔴 Sonek cast'ının fiilen ısırdığı yer — İKİ SATIR ŞARTTIR.

    Tek satırlı bir kurulum bu kusuru GÖRMEZ (mutasyon denetiminde fiilen
    görülmedi: cast kaldırıldığında `test_dolgu_genisligi_asilinca_numara_UZAR`
    yeşil kaldı, çünkü tek satırda metin `max`i de aynı satırı seçer).
    Kusur ancak dolgu genişliğinin İKİ YANINDAN birer kayıt varken doğar:
    metin sıralaması `"999999" > "1000000"` der (ilk karakter `9` > `1`),
    üretici 999999'da SAPLANIR ve `FIL20261000000`ı yeniden üretip
    `uq_invoices_no_direction` ihlaliyle 500 verir — üstelik bu ancak
    milyonuncu faturada, yani yalnız canlıda görülürdü.
    """
    session, user = numara_ortami
    await _add_invoice(session, invoice_no="FIL2026999999", user_id=user.id)
    await _add_invoice(session, invoice_no="FIL20261000000", user_id=user.id)
    assert await generate_invoice_number(session, InvoiceDirection.outgoing, year=2026) == (
        "FIL20261000001"
    )


async def test_rakam_disi_sonek_sorguyu_patlatmaz(numara_ortami):
    """Süzgeç `LIKE` değil REGEX'tir: cast yalnızca tamamen rakamdan oluşan
    sonekleri görmeli. Gelen fatura serisi ELLE girildiği için `FIL2026-A1`
    gibi bir kayıt bugün de mümkündür."""
    session, user = numara_ortami
    await _add_invoice(
        session,
        invoice_no="FIL2026-A1",
        user_id=user.id,
        direction=InvoiceDirection.incoming,
    )
    assert await generate_invoice_number(session, InvoiceDirection.outgoing, year=2026) == (
        "FIL2026000001"
    )


# --------------------------------------------------------------------------- #
# Yalnız GİDEN
# --------------------------------------------------------------------------- #


async def test_gelen_fatura_icin_numara_URETILMEZ(numara_ortami):
    """§4/S5 — gelen faturanın numarası satıcınındır ve istemciden gelir.
    Sessizce bir `FIL…` üretmek gerçek belgeyle bağı koparırdı."""
    session, _ = numara_ortami
    with pytest.raises(ValueError, match=numbering.INCOMING_NUMBER_NOT_GENERATED):
        await generate_invoice_number(session, InvoiceDirection.incoming, year=2026)


async def test_GELEN_faturanin_FIL_serisi_sayaci_ILERI_ITMEZ(numara_ortami):
    """🔴 Sayaç yön süzgeçlidir. Bir satıcının `FIL2026005000` numaralı gelen
    faturası sayacı ileri itseydi 4999 giden numara sessizce ATLANIRDI —
    tekillik yön içinde olduğu için hiçbir kısıt bunu yakalamazdı."""
    session, user = numara_ortami
    await _add_invoice(
        session,
        invoice_no="FIL2026005000",
        user_id=user.id,
        direction=InvoiceDirection.incoming,
    )
    assert await generate_invoice_number(session, InvoiceDirection.outgoing, year=2026) == (
        "FIL2026000001"
    )


def test_kilit_anahtari_sabittir_ve_SA_ile_CAKISMAZ():
    """§4 — 82501/82502 satınalmanındır. Aynı anahtar paylaşılsaydı fatura
    kesen bir istek, ilgisiz bir satınalma talebini gereksiz yere bekletirdi
    (ve tersi)."""
    assert numbering._INVOICE_LOCK_KEY == 82601
    assert numbering._INVOICE_LOCK_KEY not in {_REQUEST_LOCK_KEY, _ORDER_LOCK_KEY}


# --------------------------------------------------------------------------- #
# Yarış koşulu — GERÇEK eş zamanlılık (paylaşılan test oturumu YETMEZ)
# --------------------------------------------------------------------------- #


def _asyncpg_dsn(database: str) -> str:
    base = settings.test_database_url.replace("postgresql+asyncpg://", "postgresql://")
    return base.rsplit("/", 1)[0] + f"/{database}"


def _sqlalchemy_dsn(database: str) -> str:
    return settings.test_database_url.rsplit("/", 1)[0] + f"/{database}"


async def _create_scratch_database() -> str:
    database = f"invoicing_no_{uuid.uuid4().hex[:8]}"
    admin = await asyncpg.connect(_asyncpg_dsn("postgres"))
    try:
        await admin.execute(f'CREATE DATABASE "{database}"')
    finally:
        await admin.close()
    return database


async def _drop_scratch_database(database: str) -> None:
    admin = await asyncpg.connect(_asyncpg_dsn("postgres"))
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
    finally:
        await admin.close()


async def test_eszamanli_uretim_ayni_numarayi_vermez():
    """İKİ AYRI BAĞLANTI aynı anda numara ister.

    Kilit YOKSA ikisi de commit edilmemiş durumu okur, ikisi de
    `FIL2026000001` döner ve ikincisi `uq_invoices_no_direction` ihlaliyle 500
    üretir. Kilit VARSA ikinci üretim birincinin commit'ini BEKLER (aşağıda
    `not done` ile ölçülür) ve 000002 alır.

    Paylaşılan `db_session` fixture'ı bunu ÖLÇEMEZ: tek bağlantı + savepoint
    olduğu için gerçek eş zamanlılık yoktur. Tek kullanımlık bir veritabanı
    açılır (`.env`/`TEST_DATABASE_URL` veritabanı ELLENMEZ).
    """
    database = await _create_scratch_database()
    engine = create_async_engine(_sqlalchemy_dsn(database))
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        raw = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            role_id, user_id = uuid.uuid4(), uuid.uuid4()
            await raw.execute(
                "INSERT INTO roles (id, key, name, emoji, description, is_system) "
                "VALUES ($1, 'fat_yaris', 'FAT Rol', '', '', false)",
                role_id,
            )
            await raw.execute(
                "INSERT INTO users (id, email, password_hash, full_name, title, role_id, "
                "status, token_version) "
                "VALUES ($1, 'fatura-yaris@ornek.test', 'x', 'FAT', '', $2, 'active', 0)",
                user_id,
                role_id,
            )
        finally:
            await raw.close()

        Session = async_sessionmaker(engine, expire_on_commit=False)

        async def _uret_ve_yaz(session: AsyncSession) -> str:
            numara = await generate_invoice_number(session, InvoiceDirection.outgoing, year=2026)
            await _add_invoice(session, invoice_no=numara, user_id=user_id)
            await session.commit()
            return numara

        async with Session() as birinci, Session() as ikinci:
            ilk_numara = await generate_invoice_number(
                birinci, InvoiceDirection.outgoing, year=2026
            )
            await _add_invoice(birinci, invoice_no=ilk_numara, user_id=user_id)

            # İkinci oturum HENÜZ commit edilmemiş birincinin üstüne biner.
            gorev = asyncio.create_task(_uret_ve_yaz(ikinci))
            await asyncio.sleep(0.3)
            assert not gorev.done(), (
                "ikinci üretim beklemedi — kilit yok, iki istek aynı numarayı alır"
            )

            await birinci.commit()
            ikinci_numara = await asyncio.wait_for(gorev, timeout=10)

        assert ilk_numara == "FIL2026000001"
        assert ikinci_numara == "FIL2026000002"
    finally:
        await engine.dispose()
        await _drop_scratch_database(database)
