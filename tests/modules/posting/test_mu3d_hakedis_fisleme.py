"""🔴 MU-3D İŞ 1 — ÜÇ HAKEDİŞ AİLESİ FİŞLENİR (KDV'SİZ) + KARAR-5 STORNO.

Bacak ŞEKLİ ve TUTARI birlikte ölçülür: yalnız "fiş doğdu mu" sorulsaydı,
tutarı yanlış hesaplayan ya da bacakları TERS yazan bir kod yeşil kalırdı — ve
fiş yine DENGELİ göründüğü için hiçbir toplam bunu ele vermezdi.
"""

from decimal import Decimal

import pytest

from app.core.errors import AccountingValidationError
from app.modules.accounting.models import JournalEntryStatus, JournalSourceType
from app.modules.equipment import rental_service
from app.modules.equipment.models.enums import RentalInvoiceStatus
from app.modules.progress_payments import transitions as isveren_transitions
from app.modules.progress_payments.models import ProgressPaymentStatus
from app.modules.progress_payments.transitions import PaymentAction
from app.modules.subcontractor_progress_payments import transitions as taseron_transitions
from app.modules.subcontractor_progress_payments.models import SubcontractorPaymentStatus
from tests.modules.posting._mu3d import (
    KOD_ALICILAR,
    KOD_GIDER,
    KOD_SATICILAR,
    KOD_SATIS,
    aktor,
    bacaklar,
    bugun,
    canli_fis,
    esleme_kur,
    isveren_hakedisi,
    kira_hakedisi,
    taseron_hakedisi,
)

# --------------------------------------------------------------------------- #
# AİLE 1 — İŞVEREN HAKEDİŞİ (alacak + hasılat)
# --------------------------------------------------------------------------- #


async def test_ISVEREN_hakedisi_ONAYLANINCA_alacak_ve_HASILAT_yazar(seeded_db, user_factory):
    """🔴 Bu aile öteki ikisinin AYNASIDIR — kararın metni *"gider"* der ama
    işverene KESTİĞİMİZ hakediş bir ALACAK ve bir HASILAT doğurur.

    Taban `brüt − avans − teminat`tır ve `invoices.tax_base` ile AYNI şekildedir
    (İŞ 2'nin takası buna dayanır). Kurulum:

        brüt      = 600 × 100 × 1.000 =  60.000,00
        avans     = %20                =  12.000,00  (tavan 5.000.000×%20 içinde)
        teminat   = %5                 =   3.000,00
        TABAN                          =  45.000,00
    """
    await esleme_kur(seeded_db)
    kullanici = await aktor(seeded_db, user_factory)
    payment, _contract, _project = await isveren_hakedisi(seeded_db, kullanici)

    await isveren_transitions.perform(seeded_db, kullanici, payment.id, PaymentAction.approve)

    assert payment.status is ProgressPaymentStatus.approved, "onay GERÇEKLEŞMEDİ"
    fis = await canli_fis(seeded_db, JournalSourceType.progress_payment, payment.id)
    assert fis is not None, "onaylanan işveren hakedişi FİŞSİZ kaldı"
    assert fis.status is JournalEntryStatus.posted, "KARAR-3: fiş `posted` DOĞAR"
    # 🔴 ONAY GÜNÜ — dönem (`2026/07`) DEĞİL.
    assert fis.entry_date == bugun()
    assert fis.source_id == payment.id

    assert await bacaklar(seeded_db, fis) == [
        (KOD_ALICILAR, "45000.00", "0.00"),
        (KOD_SATIS, "0.00", "45000.00"),
    ]
    # 🔴 KDV bacağı YOKTUR — beyanname yalnız `invoices`tan türer.
    assert fis.total_debit == fis.total_credit == Decimal("45000.00")


async def test_ISVEREN_hakedisinde_UNAPPROVE_fisi_STORNO_eder_ve_NET_SIFIRLANIR(
    seeded_db, user_factory
):
    """🔴 KARAR-5. Onay geri çekilince kayıt kümülatif kümeden ÇIKAR; fişi
    ayakta bırakmak onaylı olmayan bir hakedişin hasılatını mizanda tutmak
    olurdu.

    Net `posted + reversed` üzerinden ölçülür (`balance.posting_filter`): storno
    defterden ÇIKMAZ, ters kaydıyla nötrlenir.
    """
    from tests.modules.posting._mu3d import hesap_neti

    await esleme_kur(seeded_db)
    kullanici = await aktor(seeded_db, user_factory)
    payment, _c, _p = await isveren_hakedisi(seeded_db, kullanici)
    await isveren_transitions.perform(seeded_db, kullanici, payment.id, PaymentAction.approve)
    assert await hesap_neti(seeded_db, KOD_ALICILAR) == Decimal("45000.00")

    await isveren_transitions.perform(seeded_db, kullanici, payment.id, PaymentAction.unapprove)

    assert payment.status is ProgressPaymentStatus.pending_approval
    assert await canli_fis(seeded_db, JournalSourceType.progress_payment, payment.id) is None, (
        "CANLI fiş DURUYOR — storno yazılmadı"
    )
    assert await hesap_neti(seeded_db, KOD_ALICILAR) == Decimal("0.00"), "STORNO NET'İ SIFIRLAMADI"
    assert await hesap_neti(seeded_db, KOD_SATIS) == Decimal("0.00")


async def test_ISVEREN_hakedisi_STORNO_sonrasi_YENIDEN_fislenir(seeded_db, user_factory):
    """Tekillik CANLI fişlerle sınırlıdır (MU-3B): geri çekilen hakediş yeniden
    onaylanabilir ve YENİ bir fiş doğar. Tam tekillikte bir daha HİÇ
    fişlenemezdi ve mizan KALICI olarak eksik kalırdı."""
    await esleme_kur(seeded_db)
    kullanici = await aktor(seeded_db, user_factory)
    payment, _c, _p = await isveren_hakedisi(seeded_db, kullanici)
    await isveren_transitions.perform(seeded_db, kullanici, payment.id, PaymentAction.approve)
    ilk = await canli_fis(seeded_db, JournalSourceType.progress_payment, payment.id)
    await isveren_transitions.perform(seeded_db, kullanici, payment.id, PaymentAction.unapprove)
    await isveren_transitions.perform(seeded_db, kullanici, payment.id, PaymentAction.approve)

    ikinci = await canli_fis(seeded_db, JournalSourceType.progress_payment, payment.id)
    assert ikinci is not None and ikinci.id != ilk.id, "yeniden onay YENİ fiş üretmedi"


async def test_SATIRSIZ_hakedis_FISLENMEZ_ama_ONAY_gecer(seeded_db, user_factory):
    """🔴 Taban sıfırsa fiş HİÇ AÇILMAZ ve onay BLOKLANMAZ.

    `(0, 0)` bacağı `ck_journal_lines_single_side`ı ihlal eder ve satırsız fiş
    K1'in `MIN_LINES_REQUIRED` engelinden **422** alırdı — o 422 kullanıcının
    ONAYINI bloklardı. Satırı doldurulmamış hakediş NORMAL bir hâldir.
    """
    await esleme_kur(seeded_db)
    kullanici = await aktor(seeded_db, user_factory)
    payment, _c, _p = await isveren_hakedisi(seeded_db, kullanici, miktar="600")
    payment.lines = []
    await seeded_db.flush()

    await isveren_transitions.perform(seeded_db, kullanici, payment.id, PaymentAction.approve)

    assert payment.status is ProgressPaymentStatus.approved
    assert await canli_fis(seeded_db, JournalSourceType.progress_payment, payment.id) is None


async def test_ESLEME_YOKSA_422_ve_ONAY_da_GERI_ALINIR(seeded_db, user_factory):
    """🔴 FAIL-CLOSED. `esleme_kur` BİLEREK çağrılmaz.

    Fiş yazılamazsa geçiş de GERİ ALINIR — "onaylı ama fişsiz" bir hakediş
    DOĞMAZ. Bu dal ölçülmeseydi eksik eşleme sessizce fişsiz onaylar üretirdi.
    """
    kullanici = await aktor(seeded_db, user_factory)
    payment, _c, _p = await isveren_hakedisi(seeded_db, kullanici)

    with pytest.raises(AccountingValidationError) as hata:
        await isveren_transitions.perform(seeded_db, kullanici, payment.id, PaymentAction.approve)
    assert "hesap eşlemesi" in str(hata.value)


# --------------------------------------------------------------------------- #
# AİLE 2 — TAŞERON HAKEDİŞİ (gider + cari borç)
# --------------------------------------------------------------------------- #


async def test_TASERON_hakedisi_ONAYLANINCA_gider_ve_CARI_BORC_yazar(seeded_db, user_factory):
    """Kurulum: brüt = 10 × 1.000 = 10.000; avans %10 = 1.000; teminat %5 = 500.

    🔴 Sözleşme bedeli KALEMLERDEN türer (`10.000 × 1.000 = 10.000.000`), bir
    kolon DEĞİLDİR — avans tavanı (`%10 = 1.000.000`) bu yüzden bağlayıcı
    olmaz ve tam kesinti uygulanır.

        TABAN = 10.000 − 1.000 − 500 = 8.500,00
    """
    await esleme_kur(seeded_db)
    kullanici = await aktor(seeded_db, user_factory)
    payment, _contract = await taseron_hakedisi(seeded_db, kullanici)

    await taseron_transitions.perform(seeded_db, kullanici, payment.id, PaymentAction.approve)

    assert payment.status is SubcontractorPaymentStatus.approved
    fis = await canli_fis(seeded_db, JournalSourceType.subcontractor_progress_payment, payment.id)
    assert fis is not None, "onaylanan taşeron hakedişi FİŞSİZ kaldı"
    assert fis.entry_date == bugun()
    assert await bacaklar(seeded_db, fis) == [
        (KOD_GIDER, "8500.00", "0.00"),
        (KOD_SATICILAR, "0.00", "8500.00"),
    ]


async def test_TASERON_hakedisinde_UNAPPROVE_STORNO_yazar(seeded_db, user_factory):
    """KARAR-5 — kardeş ailedeki ile AYNI kural, AYRI kod yolu."""
    await esleme_kur(seeded_db)
    kullanici = await aktor(seeded_db, user_factory)
    payment, _contract = await taseron_hakedisi(seeded_db, kullanici)
    await taseron_transitions.perform(seeded_db, kullanici, payment.id, PaymentAction.approve)

    await taseron_transitions.perform(seeded_db, kullanici, payment.id, PaymentAction.unapprove)

    assert (
        await canli_fis(seeded_db, JournalSourceType.subcontractor_progress_payment, payment.id)
        is None
    )


# --------------------------------------------------------------------------- #
# AİLE 3 — MAKİNE KİRA HAKEDİŞİ (gider + cari borç, taban DONMUŞ kolon)
# --------------------------------------------------------------------------- #


async def test_KIRA_hakedisi_ONAYLANINCA_gider_ve_CARI_BORC_yazar(seeded_db, user_factory):
    """🔴 Taban `invoice_amount`tır (KDV HARİÇ) — `payable_total` DEĞİL.

    `payable_total` KDV'yi İÇERİR (`100.000 × %20 = 20.000` → `120.000`);
    o yazılsaydı beyanname ile yevmiye SESSİZCE ayrışırdı. Bu yüzden tutar
    `120000.00` DEĞİL `100000.00` olmalıdır ve bu iddia bu dilimin en ucuz
    kırılma noktasıdır.
    """
    await esleme_kur(seeded_db)
    kullanici = await aktor(seeded_db, user_factory)
    invoice, _supplier = await kira_hakedisi(seeded_db)

    await rental_service.approve_invoice(seeded_db, kullanici, invoice.id)

    assert invoice.status is RentalInvoiceStatus.approved
    fis = await canli_fis(seeded_db, JournalSourceType.equipment_rental_invoice, invoice.id)
    assert fis is not None, "onaylanan kira hakedişi FİŞSİZ kaldı"
    assert await bacaklar(seeded_db, fis) == [
        (KOD_GIDER, "100000.00", "0.00"),
        (KOD_SATICILAR, "0.00", "100000.00"),
    ], "taban KDV'Lİ okunmuş olabilir (`payable_total` = 120.000)"


async def test_KIRA_hakedisinde_TASLAKTAN_ilk_adim_FIS_YAZMAZ(seeded_db, user_factory):
    """🔴 `/approve` bir TEK ADIM İLERLETİCİDİR.

    `draft` üzerinde çağrıldığında kayıt yalnız `pending_verification`a taşınır
    ve HİÇBİR ŞEY damgalanmaz. Kanca uca bağlansaydı DOĞRULANMAMIŞ bir kira
    bedeli deftere girerdi — ve durum ekranda hâlâ "Doğrulama Bekliyor"
    görünürdü.
    """
    await esleme_kur(seeded_db)
    kullanici = await aktor(seeded_db, user_factory)
    invoice, _s = await kira_hakedisi(seeded_db, status=RentalInvoiceStatus.draft)

    await rental_service.approve_invoice(seeded_db, kullanici, invoice.id)

    assert invoice.status is RentalInvoiceStatus.pending_verification
    assert (
        await canli_fis(seeded_db, JournalSourceType.equipment_rental_invoice, invoice.id) is None
    )

    # İKİNCİ adım `approved`a taşır VE fişi YAZAR.
    await rental_service.approve_invoice(seeded_db, kullanici, invoice.id)
    assert invoice.status is RentalInvoiceStatus.approved
    assert (
        await canli_fis(seeded_db, JournalSourceType.equipment_rental_invoice, invoice.id)
        is not None
    )


async def test_KIRA_hakedisinde_TUTAR_GIRILMEMISSE_fis_ACILMAZ(seeded_db, user_factory):
    """🔴 `invoice_amount IS NULL` "girilmedi"dir, sıfır DEĞİL (NULL-EŞİK kanonu).

    Sıfır sayılsaydı `(0, 0)` bacağı DB kısıtını ihlal eder, K1 **422** verir ve
    o 422 kullanıcının ONAYINI bloklardı.
    """
    await esleme_kur(seeded_db)
    kullanici = await aktor(seeded_db, user_factory)
    invoice, _s = await kira_hakedisi(seeded_db, invoice_amount=None)

    await rental_service.approve_invoice(seeded_db, kullanici, invoice.id)

    assert invoice.status is RentalInvoiceStatus.approved, "onay BLOKLANDI"
    assert (
        await canli_fis(seeded_db, JournalSourceType.equipment_rental_invoice, invoice.id) is None
    )


async def test_KIRA_hakedisinde_REJECT_fisi_STORNO_eder(seeded_db, user_factory):
    """KARAR-5 — bu ailede geri alma `approved → pending_verification`tır."""
    await esleme_kur(seeded_db)
    kullanici = await aktor(seeded_db, user_factory)
    invoice, _s = await kira_hakedisi(seeded_db)
    await rental_service.approve_invoice(seeded_db, kullanici, invoice.id)
    assert await canli_fis(seeded_db, JournalSourceType.equipment_rental_invoice, invoice.id)

    await rental_service.reject_invoice(seeded_db, kullanici, invoice.id)

    assert invoice.status is RentalInvoiceStatus.pending_verification
    assert (
        await canli_fis(seeded_db, JournalSourceType.equipment_rental_invoice, invoice.id) is None
    )


async def test_ODEME_damgasi_IKINCI_bir_fis_URETMEZ(seeded_db, user_factory):
    """🔴 ÇİFT SAYIM KAPISI — `mark-paid`/`pay` bir TAHSİLAT/ÖDEMEDİR.

    Nakit bacağı (`102`/`100`) Hazine diliminindir (MU-3C). Buradan fiş
    atılsaydı aynı hakediş İKİ KEZ gider/hasılat yazardı.
    """
    from sqlalchemy import func, select

    from app.modules.accounting.models import JournalEntry

    await esleme_kur(seeded_db)
    kullanici = await aktor(seeded_db, user_factory)
    invoice, _s = await kira_hakedisi(seeded_db)
    await rental_service.approve_invoice(seeded_db, kullanici, invoice.id)

    once = (await seeded_db.execute(select(func.count()).select_from(JournalEntry))).scalar_one()
    await rental_service.pay_invoice(seeded_db, kullanici, invoice.id)
    sonra = (await seeded_db.execute(select(func.count()).select_from(JournalEntry))).scalar_one()

    assert sonra == once, "ödeme damgası YENİ bir fiş üretti — çift sayım"
