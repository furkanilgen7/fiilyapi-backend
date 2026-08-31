"""🔴 MU-3D İŞ 2 — TAKAS: fatura fişlenince kaynak hakedişin fişi STORNO edilir.

## Kullanıcı kararı (SEÇENEK B) ne vaat ediyor

1. **Faturalanmayan** hakedişin gideri/hasılatı deftere GİRER (mizan taşeron
   maliyetini TAM gösterir).
2. **Faturalanan** hakediş İKİ KEZ yazılmaz.

Bu dosya iki vaadi de ölçer ve aralarındaki GEÇİŞİ de ölçer — asıl risk oradadır.

## 🔴 TETİKLEYİCİNİN YERİ İDDİANIN PARÇASIDIR

Storno faturanın OLUŞTURULMASINDA değil, faturanın KENDİ FİŞİNİN YAZILDIĞI
geçişte (`send`/`approve`) koşar. Ölçüldü: fatura `draft`/`pending` doğar ve
fişi ancak o geçişte yazılır. Oluşturmada storno atılsaydı, fatura
gönderilene kadar (ya da HİÇ gönderilmezse SONSUZA KADAR) ne hakediş ne fatura
defterde olurdu — yani kararın 1. vaadi delinirdi. `test_TASLAK_fatura_...`
tam olarak o dalı çakar.
"""

from datetime import date
from decimal import Decimal

from app.modules.accounting.models import JournalSourceType
from app.modules.invoicing import service as invoicing_service
from app.modules.invoicing import state_service as invoicing_state
from app.modules.invoicing.models import InvoiceDirection, InvoiceDocumentType, InvoiceStatus
from app.modules.invoicing.schemas import InvoiceCreate, InvoiceLineCreate
from app.modules.invoicing.transitions import InvoiceAction
from app.modules.progress_payments import transitions as isveren_transitions
from app.modules.progress_payments.transitions import PaymentAction
from app.modules.subcontractor_progress_payments import transitions as taseron_transitions
from tests.modules.posting._mu3d import (
    KOD_GIDER,
    KOD_IND_KDV,
    KOD_SATICILAR,
    aktor,
    canli_fis,
    esleme_kur,
    hesap_neti,
    isveren_hakedisi,
    taseron_hakedisi,
)

TARIH = date(2026, 7, 17)


async def _gelen_fatura(
    session,
    kullanici,
    *,
    kaynak_alani: str,
    kaynak_id,
    tutar: str,
    vat_rate: str = "20",
):
    """Kaynağa BAĞLI bir GELEN fatura — ÜRÜN yolundan (`create_invoice`).

    ORM ile yazılsaydı `_assert_references` ve tekillik indeksi hiç koşmaz ve
    test, ürünün bağlama yolunu değil kendi kurulumunu ölçerdi.
    """
    data = InvoiceCreate(
        direction=InvoiceDirection.incoming,
        invoice_no=f"AL-{kaynak_id.hex[:8].upper()}",
        document_type=InvoiceDocumentType.einvoice,
        issue_date=TARIH,
        party_name="Çelik Kalıp Ltd.",
        lines=[
            InvoiceLineCreate(
                description="Hakediş bedeli",
                quantity=Decimal("1"),
                unit="Ad",
                unit_price=Decimal(tutar),
                vat_rate=Decimal(vat_rate),
            )
        ],
        **{kaynak_alani: kaynak_id},
    )
    invoice, _mesaj = await invoicing_service.create_invoice(session, kullanici, data)
    return invoice


async def test_FATURALANMAYAN_hakedisin_gideri_DEFTERDE_KALIR(seeded_db, user_factory):
    """🔴 KARARIN 1. VAADİ. Bu, seçeneği B yapan şeyin ta kendisidir."""
    await esleme_kur(seeded_db)
    kullanici = await aktor(seeded_db, user_factory)
    payment, _c = await taseron_hakedisi(seeded_db, kullanici)
    await taseron_transitions.perform(seeded_db, kullanici, payment.id, PaymentAction.approve)

    assert await hesap_neti(seeded_db, KOD_GIDER) == Decimal("8500.00")
    assert await hesap_neti(seeded_db, KOD_SATICILAR) == Decimal("-8500.00")


async def test_TASLAK_fatura_hakedis_fisine_DOKUNMAZ(seeded_db, user_factory):
    """🔴 TETİKLEYİCİNİN YERİNİ ÇAKAN TEST.

    Fatura OLUŞTURULDU ama `pending` durumda — kendi fişi HENÜZ YAZILMADI.
    Storno burada atılsaydı gider defterden DÜŞER ve fatura hiç onaylanmazsa
    (ya da taslak silinirse) KALICI olarak kaybolurdu.
    """
    await esleme_kur(seeded_db)
    kullanici = await aktor(seeded_db, user_factory)
    payment, _c = await taseron_hakedisi(seeded_db, kullanici)
    await taseron_transitions.perform(seeded_db, kullanici, payment.id, PaymentAction.approve)

    invoice = await _gelen_fatura(
        seeded_db,
        kullanici,
        kaynak_alani="subcontractor_progress_payment_id",
        kaynak_id=payment.id,
        tutar="8500.00",
    )

    assert invoice.status is InvoiceStatus.pending, "gelen fatura `pending` DOĞMALIYDI"
    assert (
        await canli_fis(seeded_db, JournalSourceType.subcontractor_progress_payment, payment.id)
        is not None
    ), "TAKSLAK fatura hakediş fişini STORNO ETTİ — gider defterden düştü"
    assert await hesap_neti(seeded_db, KOD_GIDER) == Decimal("8500.00")


async def test_FATURA_ONAYLANINCA_hakedis_fisi_STORNO_edilir_ve_GIDER_TEK_KEZ_sayilir(
    seeded_db, user_factory
):
    """🔴 KARARIN 2. VAADİ — ve bu dilimin ÇİFT SAYIM KAPISI.

    Takas sonrası `740`ın neti DEĞİŞMEMELİDİR: hakediş fişi netlenir
    (`posted + reversed = 0`), faturanın fişi aynı tutarı yazar.

    🔴 Tutarın AYNI olması bir tesadüf değil, `posting_base`in tanımının
    sonucudur: hakediş tabanı `brüt − avans − teminat`tır ve `invoices.tax_base`
    de öyledir. Taban `gross` seçilseydi net `advance + retention` kadar
    KAYARDI ve hiçbir kolon farkı bunu ele vermezdi.
    """
    await esleme_kur(seeded_db)
    kullanici = await aktor(seeded_db, user_factory)
    payment, _c = await taseron_hakedisi(seeded_db, kullanici)
    await taseron_transitions.perform(seeded_db, kullanici, payment.id, PaymentAction.approve)
    once = await hesap_neti(seeded_db, KOD_GIDER)

    invoice = await _gelen_fatura(
        seeded_db,
        kullanici,
        kaynak_alani="subcontractor_progress_payment_id",
        kaynak_id=payment.id,
        tutar="8500.00",
    )
    await invoicing_state.perform_transition(
        seeded_db, kullanici, invoice.id, InvoiceAction.approve
    )

    # Hakediş fişi STORNOLANDI.
    assert (
        await canli_fis(seeded_db, JournalSourceType.subcontractor_progress_payment, payment.id)
        is None
    ), "hakediş fişi STORNO EDİLMEDİ — gider İKİ KEZ sayılıyor"
    # Faturanın KENDİ fişi YAZILDI.
    assert await canli_fis(seeded_db, JournalSourceType.invoice, invoice.id) is not None

    # 🔴 GİDER TEK KEZ: net DEĞİŞMEDİ.
    assert await hesap_neti(seeded_db, KOD_GIDER) == once == Decimal("8500.00"), (
        "TAKAS gideri kaydırdı — hakediş tabanı ile faturanın `tax_base`i AYRIŞTI"
    )
    # 🔴 KDV yalnız FATURADA doğar (hakediş fişi KDV'sizdi).
    assert await hesap_neti(seeded_db, KOD_IND_KDV) == Decimal("1700.00")


async def test_ISVEREN_hakedisinde_de_TAKAS_calisir_ve_HASILAT_TEK_KEZ_sayilir(
    seeded_db, user_factory
):
    """Aynı kural AYNANIN öteki yüzünde: GİDEN fatura, hasılat + alacak."""
    from app.modules.invoicing.models import InvoiceStatus as _S
    from tests.modules.posting._mu3d import KOD_SATIS

    await esleme_kur(seeded_db)
    kullanici = await aktor(seeded_db, user_factory)
    payment, _contract, _project = await isveren_hakedisi(seeded_db, kullanici)
    await isveren_transitions.perform(seeded_db, kullanici, payment.id, PaymentAction.approve)
    once = await hesap_neti(seeded_db, KOD_SATIS)
    assert once == Decimal("-45000.00")

    data = InvoiceCreate(
        direction=InvoiceDirection.outgoing,
        document_type=InvoiceDocumentType.einvoice,
        issue_date=TARIH,
        party_name="Güneşkent İnşaat A.Ş.",
        progress_payment_id=payment.id,
        lines=[
            InvoiceLineCreate(
                description="Hakediş bedeli",
                quantity=Decimal("1"),
                unit="Ad",
                unit_price=Decimal("45000.00"),
                vat_rate=Decimal("20"),
            )
        ],
    )
    invoice, _m = await invoicing_service.create_invoice(seeded_db, kullanici, data)
    assert invoice.status is _S.draft

    await invoicing_state.perform_transition(seeded_db, kullanici, invoice.id, InvoiceAction.send)

    assert await canli_fis(seeded_db, JournalSourceType.progress_payment, payment.id) is None
    assert await hesap_neti(seeded_db, KOD_SATIS) == once, "HASILAT İKİ KEZ sayıldı"


async def test_ITIRAZ_EDILEN_fatura_hakedis_fisine_DOKUNMAZ(seeded_db, user_factory):
    """🔴 `dispute` `POSTING_ACTIONS`ta DEĞİLDİR.

    İtiraz edilen fatura hiç fişlenmez ve `vat_return` de onu saymaz;
    dolayısıyla hakediş fişi de DOKUNULMADAN kalmalıdır. Storno atılsaydı,
    itiraz edilmiş bir fatura yüzünden GERÇEK bir gider defterden düşerdi.
    """
    await esleme_kur(seeded_db)
    kullanici = await aktor(seeded_db, user_factory)
    payment, _c = await taseron_hakedisi(seeded_db, kullanici)
    await taseron_transitions.perform(seeded_db, kullanici, payment.id, PaymentAction.approve)

    invoice = await _gelen_fatura(
        seeded_db,
        kullanici,
        kaynak_alani="subcontractor_progress_payment_id",
        kaynak_id=payment.id,
        tutar="8500.00",
    )
    await invoicing_state.perform_transition(
        seeded_db, kullanici, invoice.id, InvoiceAction.dispute
    )

    assert (
        await canli_fis(seeded_db, JournalSourceType.subcontractor_progress_payment, payment.id)
        is not None
    ), "itiraz edilen fatura hakediş fişini STORNO ETTİ"
    assert await hesap_neti(seeded_db, KOD_GIDER) == Decimal("8500.00")


async def test_KAYNAKSIZ_fatura_HICBIR_hakedisi_STORNOLAMAZ(seeded_db, user_factory):
    """Çoğunluk hâli — `reverse_source_entry` `False` döner ve HİÇBİR ŞEY yapmaz."""
    await esleme_kur(seeded_db)
    kullanici = await aktor(seeded_db, user_factory)
    payment, _c = await taseron_hakedisi(seeded_db, kullanici)
    await taseron_transitions.perform(seeded_db, kullanici, payment.id, PaymentAction.approve)

    data = InvoiceCreate(
        direction=InvoiceDirection.incoming,
        invoice_no="AL-BAGIMSIZ-1",
        document_type=InvoiceDocumentType.einvoice,
        issue_date=TARIH,
        party_name="Bağımsız Tedarikçi",
        lines=[
            InvoiceLineCreate(
                description="Malzeme",
                quantity=Decimal("1"),
                unit="Ad",
                unit_price=Decimal("500.00"),
                vat_rate=Decimal("20"),
            )
        ],
    )
    invoice, _m = await invoicing_service.create_invoice(seeded_db, kullanici, data)
    await invoicing_state.perform_transition(
        seeded_db, kullanici, invoice.id, InvoiceAction.approve
    )

    assert (
        await canli_fis(seeded_db, JournalSourceType.subcontractor_progress_payment, payment.id)
        is not None
    ), "kaynağa bağlı OLMAYAN fatura bir hakediş fişini stornoladı"


# --------------------------------------------------------------------------- #
# 🔴 KRIT-HAKEDIS K3 — TAKASTAN SONRA GERİ ALIP YENİDEN ONAYLAMA
# --------------------------------------------------------------------------- #


async def test_TAKASTAN_SONRA_unapprove_YENIDEN_approve_HASILATI_IKI_KEZ_YAZMAZ(
    seeded_db, user_factory
):
    """🔴 K3 — faturalanmış hakedişin onayı geri alınıp yeniden verilirse ÇİFT KAYIT.

    Ölçülen zincir:

        approve        → hakediş fişi CANLI (600 = −45.000)
        fatura `send`  → İŞ 2 takası: hakediş fişi `reversed`, fatura fişi CANLI
        unapprove      → `reverse_progress_payment` CANLI fiş BULAMAZ (`False`)
        approve        → `post_document` idempotanlık dalına DÜŞMEZ (canlı fiş
                         yok) ve YENİ bir canlı hakediş fişi yazar

    Sonuç: faturanın fişi + yeni hakediş fişi AYNI hasılatı İKİ KEZ taşır.
    Mizan denktir (her fiş kendi içinde dengeli), yani DENKLİK bu kusuru
    GÖRMEZ — ölçülmesi gereken şey `600`ün NETİDİR.
    """
    from tests.modules.posting._mu3d import KOD_ALICILAR, KOD_SATIS

    await esleme_kur(seeded_db)
    kullanici = await aktor(seeded_db, user_factory)
    payment, _contract, _project = await isveren_hakedisi(seeded_db, kullanici)
    await isveren_transitions.perform(seeded_db, kullanici, payment.id, PaymentAction.approve)

    data = InvoiceCreate(
        direction=InvoiceDirection.outgoing,
        document_type=InvoiceDocumentType.einvoice,
        issue_date=TARIH,
        party_name="Güneşkent İnşaat A.Ş.",
        progress_payment_id=payment.id,
        lines=[
            InvoiceLineCreate(
                description="Hakediş bedeli",
                quantity=Decimal("1"),
                unit="Ad",
                unit_price=Decimal("45000.00"),
                vat_rate=Decimal("20"),
            )
        ],
    )
    invoice, _m = await invoicing_service.create_invoice(seeded_db, kullanici, data)
    await invoicing_state.perform_transition(seeded_db, kullanici, invoice.id, InvoiceAction.send)

    takas_sonrasi_satis = await hesap_neti(seeded_db, KOD_SATIS)
    assert takas_sonrasi_satis == Decimal("-45000.00")

    await isveren_transitions.perform(seeded_db, kullanici, payment.id, PaymentAction.unapprove)
    await isveren_transitions.perform(seeded_db, kullanici, payment.id, PaymentAction.approve)

    assert await hesap_neti(seeded_db, KOD_SATIS) == takas_sonrasi_satis, (
        "ÇİFT HASILAT: faturalanmış hakediş yeniden onaylanınca ikinci bir CANLI "
        "fiş yazdı; faturanın fişi zaten defterdeydi"
    )
    assert await hesap_neti(seeded_db, KOD_ALICILAR) == Decimal("54000.00"), (
        "ÇİFT ALACAK: `120` faturanın KDV'li totalinden fazlasını taşıyor"
    )
    assert await canli_fis(seeded_db, JournalSourceType.invoice, invoice.id) is not None
    assert await canli_fis(seeded_db, JournalSourceType.progress_payment, payment.id) is None, (
        "faturalanmış hakediş yeniden onaylanınca KENDİ fişini yeniden yazdı"
    )


async def test_TASERON_ikizinde_de_TAKAS_GERI_DONUSU_GIDERI_IKI_KEZ_YAZMAZ(seeded_db, user_factory):
    """🔴 K3'ün AYNADAKİ hâli — kusur ÜÇ ailede de AYNIYDI (ölçüldü).

    Fiş yazma kancası üç ailede de tek kalıptır; kapı tek kopyadır ama
    ÇAĞRISI üç yerdedir, dolayısıyla üç yerde de çakılır (§5-20: çağrı yeri de
    mutanttır).
    """
    await esleme_kur(seeded_db)
    kullanici = await aktor(seeded_db, user_factory)
    payment, _c = await taseron_hakedisi(seeded_db, kullanici)
    await taseron_transitions.perform(seeded_db, kullanici, payment.id, PaymentAction.approve)

    invoice = await _gelen_fatura(
        seeded_db,
        kullanici,
        kaynak_alani="subcontractor_progress_payment_id",
        kaynak_id=payment.id,
        tutar="8500.00",
    )
    await invoicing_state.perform_transition(
        seeded_db, kullanici, invoice.id, InvoiceAction.approve
    )
    takas_sonrasi = await hesap_neti(seeded_db, KOD_GIDER)
    assert takas_sonrasi == Decimal("8500.00")

    await taseron_transitions.perform(seeded_db, kullanici, payment.id, PaymentAction.unapprove)
    await taseron_transitions.perform(seeded_db, kullanici, payment.id, PaymentAction.approve)

    assert await hesap_neti(seeded_db, KOD_GIDER) == takas_sonrasi, (
        "ÇİFT GİDER: faturalanmış taşeron hakedişi yeniden onaylanınca ikinci bir CANLI fiş yazdı"
    )
    assert (
        await canli_fis(seeded_db, JournalSourceType.subcontractor_progress_payment, payment.id)
        is None
    )


async def test_KIRA_hakedisinde_de_TAKAS_GERI_DONUSU_GIDERI_IKI_KEZ_YAZMAZ(seeded_db, user_factory):
    """🔴 K3'ün ÜÇÜNCÜ ailedeki hâli: `reject_invoice` → yeniden `approve_invoice`."""
    from app.modules.equipment import rental_service
    from tests.modules.posting._mu3d import kira_hakedisi

    await esleme_kur(seeded_db)
    kullanici = await aktor(seeded_db, user_factory)
    kira, _supplier = await kira_hakedisi(seeded_db)
    await rental_service.approve_invoice(seeded_db, kullanici, kira.id)

    invoice = await _gelen_fatura(
        seeded_db,
        kullanici,
        kaynak_alani="equipment_rental_invoice_id",
        kaynak_id=kira.id,
        tutar="100000.00",
    )
    await invoicing_state.perform_transition(
        seeded_db, kullanici, invoice.id, InvoiceAction.approve
    )
    takas_sonrasi = await hesap_neti(seeded_db, KOD_GIDER)
    assert takas_sonrasi == Decimal("100000.00")

    await rental_service.reject_invoice(seeded_db, kullanici, kira.id)
    await rental_service.approve_invoice(seeded_db, kullanici, kira.id)

    assert await hesap_neti(seeded_db, KOD_GIDER) == takas_sonrasi, (
        "ÇİFT GİDER: faturalanmış kira hakedişi yeniden onaylanınca ikinci bir CANLI fiş yazdı"
    )
    assert await canli_fis(seeded_db, JournalSourceType.equipment_rental_invoice, kira.id) is None


async def test_FATURASI_SILINMIS_hakedis_yeniden_onaylandiginda_FIS_YAZAR(seeded_db, user_factory):
    """🔴 KAPININ TERS YÖNÜ — yeni kapı MEŞRU yeniden fişlemeyi ENGELLEMEZ.

    Faturası HİÇ FİŞLENMEMİŞ (taslak) bir hakedişte `unapprove` gerçek bir
    storno yazar ve yeniden onay fişi GERİ GETİRMELİDİR. Bu test olmadan
    `source_replaced_by_invoice`i DAİMA `True` döndüren bir mutant sağ kalırdı
    ve ürün, geri alınan her hakedişi kalıcı olarak FİŞSİZ bırakırdı.
    """
    await esleme_kur(seeded_db)
    kullanici = await aktor(seeded_db, user_factory)
    payment, _c = await taseron_hakedisi(seeded_db, kullanici)
    await taseron_transitions.perform(seeded_db, kullanici, payment.id, PaymentAction.approve)

    # Fatura VAR ama `pending` — kendi fişi HENÜZ YAZILMADI, takas olmadı.
    await _gelen_fatura(
        seeded_db,
        kullanici,
        kaynak_alani="subcontractor_progress_payment_id",
        kaynak_id=payment.id,
        tutar="8500.00",
    )

    await taseron_transitions.perform(seeded_db, kullanici, payment.id, PaymentAction.unapprove)
    assert (
        await canli_fis(seeded_db, JournalSourceType.subcontractor_progress_payment, payment.id)
        is None
    ), "gerçek storno yazılmadı"
    assert await hesap_neti(seeded_db, KOD_GIDER) == Decimal("0.00")

    await taseron_transitions.perform(seeded_db, kullanici, payment.id, PaymentAction.approve)

    assert (
        await canli_fis(seeded_db, JournalSourceType.subcontractor_progress_payment, payment.id)
        is not None
    ), "yeni kapı MEŞRU yeniden fişlemeyi de engelledi — gider kalıcı olarak kayboldu"
    assert await hesap_neti(seeded_db, KOD_GIDER) == Decimal("8500.00")
