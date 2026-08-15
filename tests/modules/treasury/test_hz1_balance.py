"""HZ-1 T2 — bakiye çekirdeğinin (K2) TEK KAYNAK davranışı.

Spec: `docs/superpowers/specs/2026-08-14-hz1-hazine-cekirdegi-design.md` §3 K2.

    bakiye(hesap) = opening_balance
                  + Σ payments.amount  (bağlı fatura direction = outgoing)
                  − Σ payments.amount  (bağlı fatura direction = incoming)

NEDEN BU TESTLER: bakiye SAKLANMADIĞI için hiçbir kolon onu doğrulamaz —
formülün doğruluğunun tek kanıtı buradaki iddialardır. Üç sınıf kusur ölçülür:

1. **YÖN** — işaretlerin takası (`outgoing` ↔ `incoming`) bakiyeyi sessizce
   ters çevirir; kart yine bir sayı basar, yanlış olduğu anlaşılmaz.
   `test_karisik_iki_yon_ve_coklu_hesap` bu mutasyonu öldürmek için yazıldı:
   tek yönlü veriyle kurulmuş bir test işaret takasını GÖREMEZ.
2. **NULL YUTMASI** — ödemesi olmayan hesapta `SUM()` NULL döner; `coalesce`
   olmasaydı `opening_balance + NULL = NULL` olur ve kart BOŞ basardı.
   Bu yüzden ödemesiz hesap ayrı bir testtir, "0 gelir" varsayılmaz.
3. **N+1** — 1 hesap ile 20 hesabın SORGU SAYISI ölçülerek karşılaştırılır.
   Tahmine değil `before_cursor_execute` sayacına dayanır (TB3/`test_summary`
   emsali): hesap başına döngü kuran bir uygulama testi geçemez.

Kuruş hassasiyeti ayrıca sınanır: `Decimal("0.01")` toplamları TAM çıkmalıdır.
Kayan noktaya düşen bir uygulama `0.30000000000000004` üretir ve toplamlar
zamanla kayar.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.invoicing.models import (
    Invoice,
    InvoiceDirection,
    InvoiceDocumentType,
    InvoiceStatus,
)
from app.modules.treasury import balance
from app.modules.treasury.models import BankAccount, BankAccountType, Payment, PaymentMethodKind
from tests._iban import tr_iban
from tests.conftest import test_engine

pytestmark = pytest.mark.asyncio


@contextmanager
def _sorgu_sayaci() -> Iterator[list[str]]:
    """Sürücüye giden HER ifadeyi toplar — N+1 iddiasının ÖLÇÜM aracı.

    `tests/progress_payments/test_summary.py`deki `before_cursor_execute`
    deseninin birebir aynısı.
    """
    ifadeler: list[str] = []

    def kaydet(conn, cursor, statement, parameters, context, executemany) -> None:  # noqa: ANN001
        ifadeler.append(" ".join(statement.split()))

    event.listen(test_engine.sync_engine, "before_cursor_execute", kaydet)
    try:
        yield ifadeler
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", kaydet)


@pytest.fixture
async def kullanici_id(seeded_db: AsyncSession, user_factory) -> uuid.UUID:
    user = await user_factory(
        email="hazine@fiil.co", password="parola1234", role_key="system_admin"
    )
    return user.id


@pytest.fixture
def hesap_fabrikasi(seeded_db: AsyncSession):
    sayac = {"n": 0}

    async def _create(opening_balance: str = "0.00") -> BankAccount:
        sayac["n"] += 1
        account = BankAccount(
            bank_name=f"Test Bank {sayac['n']}",
            account_type=BankAccountType.checking,
            iban=tr_iban(sayac["n"]),
            opening_balance=Decimal(opening_balance),
        )
        seeded_db.add(account)
        await seeded_db.flush()
        return account

    return _create


@pytest.fixture
def odeme_fabrikasi(seeded_db: AsyncSession, kullanici_id: uuid.UUID):
    """Faturayı İSTENEN YÖNDE kurar ve ona bir ödeme satırı bağlar.

    Fatura `total`i bilinçli olarak yüksek tutulur: bu dilim aşırı tahsilat
    denetimini (K6, T4'ün işi) DEĞİL, yalnız toplama/çıkarma yönünü ölçer.
    """
    sayac = {"n": 0}

    async def _create(
        account: BankAccount,
        amount: str,
        direction: InvoiceDirection,
        paid_on: date = date(2026, 8, 14),
    ) -> Payment:
        sayac["n"] += 1
        invoice = Invoice(
            direction=direction,
            invoice_no=f"HZ{sayac['n']:09d}",
            document_type=InvoiceDocumentType.einvoice,
            status=InvoiceStatus.sent,
            issue_date=date(2026, 8, 1),
            party_name="Test Karşı Taraf",
            subtotal=Decimal("1000000.00"),
            advance_amount=Decimal("0.00"),
            retention_amount=Decimal("0.00"),
            tax_base=Decimal("1000000.00"),
            vat_amount=Decimal("0.00"),
            withholding_amount=Decimal("0.00"),
            total=Decimal("1000000.00"),
            created_by_id=kullanici_id,
        )
        seeded_db.add(invoice)
        await seeded_db.flush()
        payment = Payment(
            invoice_id=invoice.id,
            bank_account_id=account.id,
            method=PaymentMethodKind.transfer,
            amount=Decimal(amount),
            paid_on=paid_on,
            created_by_id=kullanici_id,
        )
        seeded_db.add(payment)
        await seeded_db.flush()
        return payment

    return _create


# --- 1. NULL yutması: ödemesiz hesap ---


async def test_odemesiz_hesap_acilis_bakiyesini_doner(
    seeded_db: AsyncSession, hesap_fabrikasi
) -> None:
    """Ödemesi olmayan hesapta `SUM()` NULL'dır.

    `coalesce` olmasaydı bakiye NULL dönerdi (0 değil!) ve kart tamamen BOŞ
    basardı — "sıfır bakiye" ile "bakiye yok" ayırt edilemezdi.
    """
    hesap = await hesap_fabrikasi(opening_balance="12500.75")

    bakiyeler = await balance.balances_for(seeded_db, [hesap.id])

    assert bakiyeler[hesap.id] == Decimal("12500.75")
    assert bakiyeler[hesap.id] is not None


async def test_acilis_bakiyesi_sifir_olan_odemesiz_hesap_sifir_doner(
    seeded_db: AsyncSession, hesap_fabrikasi
) -> None:
    hesap = await hesap_fabrikasi(opening_balance="0.00")

    bakiyeler = await balance.balances_for(seeded_db, [hesap.id])

    assert bakiyeler[hesap.id] == Decimal("0.00")


# --- 2. Yön: giden EKLENİR, gelen ÇIKARILIR ---


async def test_giden_fatura_odemeleri_eklenir(
    seeded_db: AsyncSession, hesap_fabrikasi, odeme_fabrikasi
) -> None:
    """GİDEN fatura = bizim kestiğimiz fatura → tahsilat → hesaba GİRİŞ."""
    hesap = await hesap_fabrikasi(opening_balance="1000.00")
    await odeme_fabrikasi(hesap, "250.00", InvoiceDirection.outgoing)
    await odeme_fabrikasi(hesap, "125.50", InvoiceDirection.outgoing)

    bakiyeler = await balance.balances_for(seeded_db, [hesap.id])

    assert bakiyeler[hesap.id] == Decimal("1375.50")


async def test_gelen_fatura_odemeleri_cikarilir(
    seeded_db: AsyncSession, hesap_fabrikasi, odeme_fabrikasi
) -> None:
    """GELEN fatura = bize kesilen fatura → ödeme → hesaptan ÇIKIŞ."""
    hesap = await hesap_fabrikasi(opening_balance="1000.00")
    await odeme_fabrikasi(hesap, "250.00", InvoiceDirection.incoming)
    await odeme_fabrikasi(hesap, "125.50", InvoiceDirection.incoming)

    bakiyeler = await balance.balances_for(seeded_db, [hesap.id])

    assert bakiyeler[hesap.id] == Decimal("624.50")


async def test_odemeler_bakiyeyi_negatife_dusurebilir(
    seeded_db: AsyncSession, hesap_fabrikasi, odeme_fabrikasi
) -> None:
    """Çıkış açılışı aşarsa bakiye NEGATİFTİR — sıfıra kırpılmaz.

    Kırpılsaydı hesabın gerçekten eksiye düştüğü (yanlış hesaba yazılmış bir
    ödeme) gizlenirdi.
    """
    hesap = await hesap_fabrikasi(opening_balance="100.00")
    await odeme_fabrikasi(hesap, "350.00", InvoiceDirection.incoming)

    bakiyeler = await balance.balances_for(seeded_db, [hesap.id])

    assert bakiyeler[hesap.id] == Decimal("-250.00")


# --- 3. Karışık: İKİ YÖN + ÇOKLU HESAP (yön takası mutasyonunu öldüren test) ---


async def test_karisik_iki_yon_ve_coklu_hesap(
    seeded_db: AsyncSession, hesap_fabrikasi, odeme_fabrikasi
) -> None:
    """Her hesap KENDİ rakamını alır ve iki yön aynı hesapta netleşir.

    🔴 Bu test yön takası mutasyonunun ölüm yeridir: iki hesabın net yönü
    BİRBİRİNİN TERSİ seçildi (A artıda, B eksidedir). İşaretler takas
    edilirse iki iddia da kırmızıya döner. Tek yönlü ya da simetrik veriyle
    kurulmuş bir test takası göremezdi.
    """
    a = await hesap_fabrikasi(opening_balance="1000.00")
    b = await hesap_fabrikasi(opening_balance="1000.00")
    bos = await hesap_fabrikasi(opening_balance="500.00")

    # A: +800 −300 → 1500
    await odeme_fabrikasi(a, "800.00", InvoiceDirection.outgoing)
    await odeme_fabrikasi(a, "300.00", InvoiceDirection.incoming)
    # B: +100 −700 → 400
    await odeme_fabrikasi(b, "100.00", InvoiceDirection.outgoing)
    await odeme_fabrikasi(b, "700.00", InvoiceDirection.incoming)

    bakiyeler = await balance.balances_for(seeded_db, [a.id, b.id, bos.id])

    assert bakiyeler[a.id] == Decimal("1500.00")
    assert bakiyeler[b.id] == Decimal("400.00")
    # Başka hesabın ödemesi bu hesaba SIZMAZ.
    assert bakiyeler[bos.id] == Decimal("500.00")


async def test_baska_hesabin_odemesi_bakiyeye_karismaz(
    seeded_db: AsyncSession, hesap_fabrikasi, odeme_fabrikasi
) -> None:
    """Gruplama `bank_account_id` üzerindedir; kaldırılırsa toplam tüm
    hesaplara dağılır ve her kart aynı sayıyı basar."""
    a = await hesap_fabrikasi(opening_balance="0.00")
    b = await hesap_fabrikasi(opening_balance="0.00")
    await odeme_fabrikasi(a, "999.00", InvoiceDirection.outgoing)

    bakiyeler = await balance.balances_for(seeded_db, [a.id, b.id])

    assert bakiyeler[a.id] == Decimal("999.00")
    assert bakiyeler[b.id] == Decimal("0.00")


# --- 4. `opening_balance` değişince bakiye kendiliğinden değişir (uç 4) ---


async def test_acilis_bakiyesi_degisince_bakiye_yeniden_turetilir(
    seeded_db: AsyncSession, hesap_fabrikasi, odeme_fabrikasi
) -> None:
    """K2'nin asıl vaadi: saklanan bir bakiye YOK, elle düzeltme anında yansır."""
    hesap = await hesap_fabrikasi(opening_balance="1000.00")
    await odeme_fabrikasi(hesap, "200.00", InvoiceDirection.outgoing)
    onceki = await balance.balances_for(seeded_db, [hesap.id])
    assert onceki[hesap.id] == Decimal("1200.00")

    hesap.opening_balance = Decimal("5000.00")
    await seeded_db.flush()

    sonraki = await balance.balances_for(seeded_db, [hesap.id])
    assert sonraki[hesap.id] == Decimal("5200.00")


# --- 5. Kuruş hassasiyeti: Decimal, kayan nokta YOK ---


async def test_kurus_toplamlari_tam_cikar(
    seeded_db: AsyncSession, hesap_fabrikasi, odeme_fabrikasi
) -> None:
    """`0.01` üç kez toplanınca TAM `0.03` olmalıdır.

    Kayan noktaya düşen bir uygulama `0.030000000000000002` üretir; iddia
    `Decimal` eşitliği olduğu için bu KIRMIZI verir.
    """
    hesap = await hesap_fabrikasi(opening_balance="0.00")
    for _ in range(3):
        await odeme_fabrikasi(hesap, "0.01", InvoiceDirection.outgoing)

    bakiyeler = await balance.balances_for(seeded_db, [hesap.id])

    assert bakiyeler[hesap.id] == Decimal("0.03")
    assert isinstance(bakiyeler[hesap.id], Decimal)


async def test_kurus_farki_yon_ile_birlikte_korunur(
    seeded_db: AsyncSession, hesap_fabrikasi, odeme_fabrikasi
) -> None:
    hesap = await hesap_fabrikasi(opening_balance="0.01")
    await odeme_fabrikasi(hesap, "0.02", InvoiceDirection.outgoing)
    await odeme_fabrikasi(hesap, "0.01", InvoiceDirection.incoming)

    bakiyeler = await balance.balances_for(seeded_db, [hesap.id])

    assert bakiyeler[hesap.id] == Decimal("0.02")


# --- 6. 🔴 N+1 ÖLÇÜMÜ ---


async def test_bir_hesap_ile_yirmi_hesabin_sorgu_sayisi_esittir(
    seeded_db: AsyncSession, hesap_fabrikasi, odeme_fabrikasi
) -> None:
    """1 hesap X sorgu / 20 hesap X sorgu — SAYI EŞİT OLMALI.

    Hesap başına döngü kuran bir uygulama 20 hesapta 20 kat sorgu üretir;
    tahminle değil `before_cursor_execute` sayacıyla ölçülür.
    """
    tek = await hesap_fabrikasi(opening_balance="10.00")
    await odeme_fabrikasi(tek, "5.00", InvoiceDirection.outgoing)

    with _sorgu_sayaci() as ifadeler:
        await balance.balances_for(seeded_db, [tek.id])
    tek_sorgu = len(ifadeler)

    coklu = [await hesap_fabrikasi(opening_balance="10.00") for _ in range(20)]
    for hesap in coklu:
        await odeme_fabrikasi(hesap, "5.00", InvoiceDirection.outgoing)

    with _sorgu_sayaci() as ifadeler:
        bakiyeler = await balance.balances_for(seeded_db, [h.id for h in coklu])
    coklu_sorgu = len(ifadeler)

    assert tek_sorgu == coklu_sorgu, f"N+1: 1 hesap {tek_sorgu}, 20 hesap {coklu_sorgu} sorgu"
    assert tek_sorgu == 1, f"tek sorguluk API bekleniyordu, {tek_sorgu} ifade koştu"
    # Ölçüm doğru şeyi ölçüyor mu: 20 hesabın hepsi gerçekten hesaplandı.
    assert len(bakiyeler) == 20
    assert all(v == Decimal("15.00") for v in bakiyeler.values())


async def test_bos_hesap_listesi_hic_sorgu_kosmaz(seeded_db: AsyncSession) -> None:
    """Boş liste `IN ()` üretmez; erken döner."""
    with _sorgu_sayaci() as ifadeler:
        bakiyeler = await balance.balances_for(seeded_db, [])

    assert bakiyeler == {}
    assert ifadeler == []


# --- 7. Liste ucunun (T3) okuyacağı toplu `Select` ---


async def test_select_accounts_with_balance_satir_ve_bakiye_doner(
    seeded_db: AsyncSession, hesap_fabrikasi, odeme_fabrikasi
) -> None:
    """Uç 1 hesap satırını ve bakiyeyi TEK sorguda alır.

    Ayrı bir bakiye sorgusu koşulsaydı liste ucu N+1'e döner ve ikinci bir
    formül yazma baskısı doğardı.
    """
    hesap = await hesap_fabrikasi(opening_balance="100.00")
    await odeme_fabrikasi(hesap, "40.00", InvoiceDirection.outgoing)
    odemesiz = await hesap_fabrikasi(opening_balance="7.00")

    with _sorgu_sayaci() as ifadeler:
        sonuc = (await seeded_db.execute(balance.select_accounts_with_balance())).all()

    assert len(ifadeler) == 1, f"tek sorgu bekleniyordu, {len(ifadeler)} ifade koştu"
    bakiyeler = {satir[0].id: satir[1] for satir in sonuc}
    assert bakiyeler[hesap.id] == Decimal("140.00")
    assert bakiyeler[odemesiz.id] == Decimal("7.00")
