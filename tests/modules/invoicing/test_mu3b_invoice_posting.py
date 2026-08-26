"""MU-3B — FATURA AİLESİ FİŞLENİR + 🔴 **KDV ÇİFT-TABAN MUTABAKATI**.

Testler `invoicing.state_service.perform_transition`i DOĞRUDAN çağırır, uçtan
geçmez: ölçülen şey geçişin MALİ SONUCUDUR ve HTTP katmanı ona hiçbir şey
katmaz — uçtan geçilseydi kırmızı, yetki/kapsam kurulumunu da gösterir ve
kuralın kendisini bulanıklaştırırdı. (Uç zinciri `test_invoicing_state_api.py`de
zaten ölçülüdür.)

## 🔴 İŞ 3 — BU DOSYANIN EN AĞIR İDDİASI

MU-3B'den önce KDV'nin TEK kaynağı vardı: `vat_return` FATURADAN türetiyordu.
MU-3B `391`/`191`e fiş atmaya başlayınca aynı büyüklüğün İKİ kaynağı olur ve
ayrıştıkları **hiçbir kolon farkıyla görünmez** (bakiye SAKLANMAZ). Mutabakat
testi bu yüzden bir nezaket değil, bu dilimin kabul kapısıdır:

    vat_return.calculated_vat  ==  Σ(391 alacak − borç), POSTING_STATUSES
    vat_return.deductible_vat  ==  Σ(191 borç − alacak), POSTING_STATUSES

Örtüşmenin YAPISAL sebebi ikilidir ve ikisi de burada ayrıca ölçülür:

1. **Durum kümeleri BİREBİR AYNI.** `vat_return` giden tarafta `sent`+`collected`,
   gelen tarafta `approved` sayar; `posting.POSTING_ACTIONS` tam olarak o
   durumlara GÖTÜREN geçişleri fişler (`collected` `sent`ten geçer, yani fişi
   zaten kesilmiştir).
2. **KDV bacağı TAM `vat_amount`tır.** Tevkifat KDV'den DÜŞÜLMEZ, ayrı bacağa
   (`136`/`360`) gider — `vat_return` `withholding_rate`i HİÇ GÖRMEZ.

`POSTING_STATUSES` (`posted` + `reversed`) kullanılır, çıplak `posted` DEĞİL:
stornolanan fiş defterden çıkmaz, ters kaydıyla nötrlenir ve toplam yine tutar.
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AccountingValidationError, ConflictError
from app.modules.accounting.balance import posting_filter
from app.modules.accounting.models import (
    ChartAccount,
    JournalEntry,
    JournalEntryStatus,
    JournalLine,
    JournalSourceType,
)
from app.modules.accounting.vat_return import build_vat_return
from app.modules.invoicing import posting, state_service
from app.modules.invoicing.amounts import LineInput, compute
from app.modules.invoicing.models import (
    Invoice,
    InvoiceDirection,
    InvoiceDocumentType,
    InvoiceLine,
    InvoiceStatus,
)
from app.modules.invoicing.transitions import InvoiceAction
from app.modules.users.models import User

TARIH = date(2026, 7, 17)

#: Fişin bacaklarının düştüğü TDHP kodları — `posting.INVOICE_POSTING_RULES`in
#: DONMUŞ kopyası DEĞİL, iddianın kendisi: testler kodu üründen okusaydı bir
#: kural yanlış hesaba çevrildiğinde yeşil kalırlardı.
KOD_ALICILAR = "120"
KOD_DIGER_ALACAK = "136"
KOD_IND_KDV = "191"
KOD_SATICILAR = "320"
KOD_OD_VERGI = "360"
KOD_HES_KDV = "391"
KOD_SATIS = "600"
KOD_GIDER = "740"


async def _aktor(seeded_db: AsyncSession, kullanici_id: uuid.UUID) -> User:
    return await seeded_db.get(User, kullanici_id)


async def fatura_kur(
    seeded_db: AsyncSession,
    kullanici_id: uuid.UUID,
    *,
    direction: InvoiceDirection,
    kalemler: list[tuple[str, str, str]],
    advance_rate: Decimal | None = None,
    retention_rate: Decimal | None = None,
    withholding_rate: Decimal | None = None,
    issue_date: date = TARIH,
    invoice_no: str | None = None,
) -> Invoice:
    """Faturayı ORM ile kurar; para kolonlarını `amounts.compute` DOLDURUR.

    🔴 Tutarlar elle yazılmaz: ürün servisi de `compute`u kullanır ve elle
    yazılmış bir toplam, fişin ürünün para modeliyle değil TESTİN aritmetiğiyle
    tuttuğunu gösterirdi (sahte-yeşil).

    `kalemler` = `(miktar, birim fiyat, KDV oranı)` üçlüleri.
    """
    girdiler = [
        LineInput(quantity=Decimal(m), unit_price=Decimal(f), vat_rate=Decimal(o))
        for m, f, o in kalemler
    ]
    hesap = compute(
        girdiler,
        advance_rate=advance_rate,
        retention_rate=retention_rate,
        withholding_rate=withholding_rate,
    )
    invoice = Invoice(
        direction=direction,
        invoice_no=invoice_no or f"MU3B{uuid.uuid4().hex[:10].upper()}",
        document_type=InvoiceDocumentType.einvoice,
        status=(
            InvoiceStatus.draft if direction is InvoiceDirection.outgoing else InvoiceStatus.pending
        ),
        issue_date=issue_date,
        party_name="Çelik Holding A.Ş.",
        subtotal=hesap.subtotal,
        advance_rate=advance_rate,
        advance_amount=hesap.advance_amount,
        retention_rate=retention_rate,
        retention_amount=hesap.retention_amount,
        tax_base=hesap.tax_base,
        vat_amount=hesap.vat_amount,
        withholding_rate=withholding_rate,
        withholding_amount=hesap.withholding_amount,
        total=hesap.total,
        created_by_id=kullanici_id,
    )
    seeded_db.add(invoice)
    await seeded_db.flush()
    seeded_db.add_all(
        [
            InvoiceLine(
                invoice_id=invoice.id,
                sort_order=sira,
                description=f"Kalem {sira + 1}",
                quantity=girdi.quantity,
                unit_price=girdi.unit_price,
                vat_rate=girdi.vat_rate,
                line_total=hesap.line_totals[sira],
            )
            for sira, girdi in enumerate(girdiler)
        ]
    )
    await seeded_db.flush()
    return invoice


async def _gecis(seeded_db, kullanici_id, invoice: Invoice, action: InvoiceAction):
    return await state_service.perform_transition(
        seeded_db, await _aktor(seeded_db, kullanici_id), invoice.id, action
    )


async def _fis(seeded_db: AsyncSession, invoice: Invoice) -> JournalEntry | None:
    return (
        await seeded_db.execute(
            select(JournalEntry)
            .where(JournalEntry.source_type == JournalSourceType.invoice)
            .where(JournalEntry.source_id == invoice.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


async def _bacaklar(seeded_db: AsyncSession, entry: JournalEntry) -> list[tuple[str, str, str]]:
    """`(hesap kodu, borç, alacak)` — `sort_order` sırasında, metin olarak.

    Metin karşılaştırması ÖLÇEĞİ de kilitler: `Decimal("1000")` ile
    `Decimal("1000.00")` eşittir ama kuruş hanesi kaybolmuş bir tutar mali
    tabloda başka bir şeydir.
    """
    rows = (
        await seeded_db.execute(
            select(ChartAccount.code, JournalLine.debit, JournalLine.credit)
            .join(JournalLine, JournalLine.account_id == ChartAccount.id)
            .where(JournalLine.entry_id == entry.id)
            .order_by(JournalLine.sort_order)
        )
    ).all()
    return [(kod, str(borc), str(alacak)) for kod, borc, alacak in rows]


async def _hesap_neti(seeded_db: AsyncSession, kod: str, *, borc_yonlu: bool) -> Decimal:
    """🔴 YEVMİYEDEN türeyen büyüklük — `balance.posting_filter()` ile.

    `POSTING_STATUSES` (`posted` + `reversed`) kullanılır: stornolanan fiş
    defterden ÇIKMAZ, ters kaydıyla nötrlenir. Çıplak `status == posted`
    yazılsaydı bir storno turundan sonra toplam `−orijinal` kadar kayardı.
    """
    net = (
        await seeded_db.execute(
            select(func.coalesce(func.sum(JournalLine.debit) - func.sum(JournalLine.credit), 0))
            .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
            .join(ChartAccount, ChartAccount.id == JournalLine.account_id)
            .where(ChartAccount.code == kod)
            .where(posting_filter())
        )
    ).scalar_one()
    return Decimal(net) if borc_yonlu else -Decimal(net)


# --------------------------------------------------------------------------- #
# İŞ 2 — FİŞ NE ZAMAN DOĞAR
# --------------------------------------------------------------------------- #


async def test_GIDEN_fatura_SEND_ile_fislenir(seeded_db, kullanici_id, fatura_eslemesi):
    """🔴 Fatura KESİLDİĞİNDE hasılat doğar — tahsil edildiğinde değil."""
    invoice = await fatura_kur(
        seeded_db,
        kullanici_id,
        direction=InvoiceDirection.outgoing,
        kalemler=[("1", "1000.00", "20")],
    )

    await _gecis(seeded_db, kullanici_id, invoice, InvoiceAction.send)

    entry = await _fis(seeded_db, invoice)
    assert entry is not None, "giden fatura `send` sonrası FİŞSİZ kaldı"
    assert entry.status is JournalEntryStatus.posted  # KARAR-3
    assert entry.entry_date == TARIH
    assert await _bacaklar(seeded_db, entry) == [
        (KOD_ALICILAR, "1200.00", "0.00"),
        (KOD_SATIS, "0.00", "1000.00"),
        (KOD_HES_KDV, "0.00", "200.00"),
    ]


async def test_GELEN_fatura_APPROVE_ile_fislenir(seeded_db, kullanici_id, fatura_eslemesi):
    """🔴 KARAR-1: gider `740`a düşer — `170` (yıllara yaygın) SEÇİLMEDİ."""
    invoice = await fatura_kur(
        seeded_db,
        kullanici_id,
        direction=InvoiceDirection.incoming,
        kalemler=[("1", "1000.00", "20")],
    )

    await _gecis(seeded_db, kullanici_id, invoice, InvoiceAction.approve)

    entry = await _fis(seeded_db, invoice)
    assert entry is not None, "gelen fatura `approve` sonrası FİŞSİZ kaldı"
    assert await _bacaklar(seeded_db, entry) == [
        (KOD_GIDER, "1000.00", "0.00"),
        (KOD_IND_KDV, "200.00", "0.00"),
        (KOD_SATICILAR, "0.00", "1200.00"),
    ]


async def test_GELEN_fatura_DISPUTE_ile_FISLENMEZ(seeded_db, kullanici_id, fatura_eslemesi):
    """İtiraz altındaki faturanın indirim hakkı BELİRSİZDİR.

    `vat_return` de `disputed`ı SAYMAZ; fişlenseydi beyanname ile yevmiye
    ayrışır ve indirilecek KDV yevmiyede FAZLA görünürdü.
    """
    invoice = await fatura_kur(
        seeded_db,
        kullanici_id,
        direction=InvoiceDirection.incoming,
        kalemler=[("1", "1000.00", "20")],
    )

    await _gecis(seeded_db, kullanici_id, invoice, InvoiceAction.dispute)

    assert await _fis(seeded_db, invoice) is None
    assert await seeded_db.scalar(select(func.count()).select_from(JournalEntry)) == 0


async def test_MARK_COLLECTED_IKINCI_fis_URETMEZ(seeded_db, kullanici_id, fatura_eslemesi):
    """🔴 Tahsilat bir FATURA OLAYI DEĞİLDİR (nakit bacağı MU-3C'nin).

    Buradan da fiş atılsaydı aynı fatura İKİ KEZ hasılat yazardı.
    """
    invoice = await fatura_kur(
        seeded_db,
        kullanici_id,
        direction=InvoiceDirection.outgoing,
        kalemler=[("1", "1000.00", "20")],
    )
    await _gecis(seeded_db, kullanici_id, invoice, InvoiceAction.send)

    await _gecis(seeded_db, kullanici_id, invoice, InvoiceAction.mark_collected)

    assert await seeded_db.scalar(select(func.count()).select_from(JournalEntry)) == 1


async def test_TEVKIFAT_AYRI_bacaga_duser_KDV_bacagi_TAM_kalir(
    seeded_db,
    kullanici_id,
    fatura_eslemesi,
):
    """🔴 İŞ 3'ün YAPISAL AYAĞI: tevkifat KDV bacağından DÜŞÜLMEZ.

    Düşülseydi `391`/`191` beyannamenin (`withholding_rate`i hiç görmeyen)
    tutarından tevkifat kadar sapar ve farkı hiçbir kolon ele vermezdi.
    """
    invoice = await fatura_kur(
        seeded_db,
        kullanici_id,
        direction=InvoiceDirection.incoming,
        kalemler=[("1", "1000.00", "20")],
        withholding_rate=Decimal("50"),
    )

    await _gecis(seeded_db, kullanici_id, invoice, InvoiceAction.approve)

    entry = await _fis(seeded_db, invoice)
    assert await _bacaklar(seeded_db, entry) == [
        (KOD_GIDER, "1000.00", "0.00"),
        (KOD_IND_KDV, "200.00", "0.00"),  # TAM KDV
        (KOD_SATICILAR, "0.00", "1100.00"),
        (KOD_OD_VERGI, "0.00", "100.00"),
    ]


async def test_TEVKIFATSIZ_faturada_SIFIR_bacak_YAZILMAZ(
    seeded_db,
    kullanici_id,
    fatura_eslemesi,
):
    """`ck_journal_lines_single_side` `(0, 0)` satırını REDDEDER.

    Süzgeç olmasaydı tevkifatsız HER fatura DB kısıtına çarpar ve hiçbir fatura
    gönderilemezdi.
    """
    invoice = await fatura_kur(
        seeded_db,
        kullanici_id,
        direction=InvoiceDirection.outgoing,
        kalemler=[("1", "1000.00", "20")],
    )

    await _gecis(seeded_db, kullanici_id, invoice, InvoiceAction.send)

    entry = await _fis(seeded_db, invoice)
    assert len(await _bacaklar(seeded_db, entry)) == 3


async def test_ISTISNA_fatura_KDV_bacagi_ACMAZ(seeded_db, kullanici_id, fatura_eslemesi):
    """`vat_rate = 0` — istisna işlem. KDV bacağı YOKTUR, fiş İKİ bacaklıdır."""
    invoice = await fatura_kur(
        seeded_db,
        kullanici_id,
        direction=InvoiceDirection.outgoing,
        kalemler=[("1", "1000.00", "0")],
    )

    await _gecis(seeded_db, kullanici_id, invoice, InvoiceAction.send)

    entry = await _fis(seeded_db, invoice)
    assert await _bacaklar(seeded_db, entry) == [
        (KOD_ALICILAR, "1000.00", "0.00"),
        (KOD_SATIS, "0.00", "1000.00"),
    ]


async def test_ESLEME_YOKSA_422_ve_GECIS_de_GERI_ALINIR(seeded_db, kullanici_id):
    """🔴 `fatura_eslemesi` BİLEREK İSTENMEDİ — kural satırı YOK.

    Fişleme geçişin İÇİNDEDİR: 422 atarsa durum damgası da geri alınır ve
    "gönderilmiş ama fişsiz" bir fatura DOĞMAZ. Ayrı transaction'da koşsaydı
    fatura `sent` kalır, mali iz boş kalırdı.
    """
    invoice = await fatura_kur(
        seeded_db,
        kullanici_id,
        direction=InvoiceDirection.outgoing,
        kalemler=[("1", "1000.00", "20")],
    )

    with pytest.raises(AccountingValidationError):
        await _gecis(seeded_db, kullanici_id, invoice, InvoiceAction.send)

    assert await seeded_db.scalar(select(func.count()).select_from(JournalEntry)) == 0


async def test_KAPALI_doneme_kesilen_fatura_409_KARAR6(
    seeded_db,
    kullanici_id,
    fatura_eslemesi,
    donem_fabrikasi,
):
    """🔴 KARAR-6 — GERİYE DÖNÜK FİŞ YOK. Fiş `issue_date`e yazılır."""
    await donem_fabrikasi(2026, 6)
    invoice = await fatura_kur(
        seeded_db,
        kullanici_id,
        direction=InvoiceDirection.outgoing,
        kalemler=[("1", "1000.00", "20")],
        issue_date=date(2026, 6, 30),
    )

    with pytest.raises(ConflictError):
        await _gecis(seeded_db, kullanici_id, invoice, InvoiceAction.send)

    assert await seeded_db.scalar(select(func.count()).select_from(JournalEntry)) == 0


async def test_POSTING_ACTIONS_vat_return_kumesinden_TURETILEBILIR(seeded_db):
    """🔴 KÖR BEKÇİ ÖLÇÜLDÜ, SONRA KAPATILDI.

    `test_MARK_COLLECTED_IKINCI_fis_URETMEZ` `POSTING_ACTIONS`a `mark_collected`
    EKLENDİĞİNDE **KIRMIZI VERMİYOR** (mutasyonla ölçüldü): `post_document`
    idempotan olduğu için ikinci çağrı `created=False` döner ve fiş sayısı yine
    1 kalır. Yani o test SONUCU (tek fiş) ölçer, KÜMEYİ değil.

    Bu test kümenin KENDİSİNİ ölçer ve iki modülü birbirine bağlar: fişlenen
    geçişler, `vat_return`ün SAYDIĞI duruma İLK GİREN geçişlerdir — ne eksik
    (beyanda olup fişte olmayan) ne fazla (fişte olup beyanda olmayan). Küme
    elle yazılsaydı `vat_return` bir gün `disputed`ı saymaya başladığında bu
    dosya yeşil kalır ve indirilecek KDV sessizce ayrışırdı.
    """
    from app.modules.accounting.vat_return import INCOMING_STATUSES, OUTGOING_STATUSES
    from app.modules.invoicing.transitions import (
        INCOMING_TRANSITIONS,
        OUTGOING_TRANSITIONS,
    )

    def _giren(matris, sayilan) -> set:
        """Kaynağı SAYILMAYAN, hedefi SAYILAN geçişler — kümeye İLK GİRİŞ.

        Hedefi sayılan AMA kaynağı da sayılan geçiş (`sent → collected`) yeni
        bir mali olay DEĞİLDİR; fişlenseydi aynı fatura iki kez hasılat yazardı.
        """
        return {
            islem
            for (kaynak, islem), hedef in matris.items()
            if hedef in sayilan and kaynak not in sayilan
        }

    beklenen = _giren(OUTGOING_TRANSITIONS, OUTGOING_STATUSES) | _giren(
        INCOMING_TRANSITIONS, INCOMING_STATUSES
    )

    assert set(posting.POSTING_ACTIONS) == beklenen, (
        "fişlenen geçişler ile beyannamenin saydığı durumlar AYRIŞTI — "
        f"fişlenen={sorted(a.value for a in posting.POSTING_ACTIONS)} "
        f"beklenen={sorted(a.value for a in beklenen)}"
    )


# --------------------------------------------------------------------------- #
# 🔴 İŞ 3 — KDV ÇİFT-TABAN MUTABAKATI
# --------------------------------------------------------------------------- #

#: Mutabakatın ÖLÇÜLDÜĞÜ küme — TEK bir faturayla ölçülseydi yuvarlama artığı,
#: oran gruplaması ve tevkifat dalları hiç koşmazdı.
MUTABAKAT_KUMESI = (
    # (yön, kalemler, tevkifat, geçişler)
    (InvoiceDirection.outgoing, [("3", "0.10", "15")], None, (InvoiceAction.send,)),
    (
        InvoiceDirection.outgoing,
        [("1", "1000.00", "20"), ("2", "250.50", "10"), ("1", "400.00", "0")],
        None,
        (InvoiceAction.send,),
    ),
    (
        InvoiceDirection.outgoing,
        [("7", "133.33", "20")],
        Decimal("50"),
        (InvoiceAction.send, InvoiceAction.mark_collected),
    ),
    (InvoiceDirection.incoming, [("5", "99.99", "20")], None, (InvoiceAction.approve,)),
    (
        InvoiceDirection.incoming,
        [("1", "1234.56", "10"), ("3", "77.77", "20")],
        Decimal("20"),
        (InvoiceAction.approve,),
    ),
    # SAYILMAYANLAR — fişlenmemeli VE beyana girmemeli.
    (InvoiceDirection.incoming, [("1", "5000.00", "20")], None, (InvoiceAction.dispute,)),
    (InvoiceDirection.outgoing, [("1", "9000.00", "20")], None, ()),  # `draft` kalır
    (InvoiceDirection.incoming, [("1", "8000.00", "20")], None, ()),  # `pending` kalır
)


async def _mutabakat_kumesini_kur(seeded_db, kullanici_id) -> None:
    for yon, kalemler, tevkifat, gecisler in MUTABAKAT_KUMESI:
        invoice = await fatura_kur(
            seeded_db,
            kullanici_id,
            direction=yon,
            kalemler=kalemler,
            withholding_rate=tevkifat,
        )
        for action in gecisler:
            await _gecis(seeded_db, kullanici_id, invoice, action)


async def test_KDV_MUTABAKATI_beyanname_ile_yevmiye_BIREBIR_tutar(
    seeded_db,
    kullanici_id,
    fatura_eslemesi,
):
    """🔴 BU DİLİMİN KABUL KAPISI — iki taban BİREBİR (kuruş toleransı YOK).

    Tolerans girseydi her turda bir kuruş kaçak meşrulaşır ve fark yıl sonunda
    gözle görünür hâle gelirdi (HZ-1 K6 kanonu).
    """
    await _mutabakat_kumesini_kur(seeded_db, kullanici_id)

    beyan = await build_vat_return(seeded_db, year=2026, month=7)

    assert beyan.calculated_vat == await _hesap_neti(seeded_db, KOD_HES_KDV, borc_yonlu=False), (
        "HESAPLANAN KDV ayrıştı: beyanname faturadan, yevmiye fişten türüyor"
    )
    assert beyan.deductible_vat == await _hesap_neti(seeded_db, KOD_IND_KDV, borc_yonlu=True), (
        "İNDİRİLECEK KDV ayrıştı: beyanname faturadan, yevmiye fişten türüyor"
    )
    # Kümenin gerçekten para taşıdığını çakar: sıfır ↔ sıfır de "tutar"dı.
    assert beyan.calculated_vat > 0
    assert beyan.deductible_vat > 0


async def test_KDV_MUTABAKATI_matrah_da_tutar(
    seeded_db,
    kullanici_id,
    fatura_eslemesi,
):
    """Matrah ayağı: `600` alacağı beyannamenin vergili+istisna matrahı KADARDIR.

    KDV'nin tutması matrahın tuttuğunu GÖSTERMEZ (aynı KDV başka bir matrahtan
    da çıkabilirdi); `tax_base` bacağı bu yüzden ayrıca ölçülür.
    """
    await _mutabakat_kumesini_kur(seeded_db, kullanici_id)

    beyan = await build_vat_return(seeded_db, year=2026, month=7)

    beyan_matrahi = sum((satir.base for satir in beyan.taxable_rows), Decimal("0"))
    beyan_matrahi += beyan.exempt_base
    assert beyan_matrahi == await _hesap_neti(seeded_db, KOD_SATIS, borc_yonlu=False)
    assert beyan.deductions[0].base == await _hesap_neti(seeded_db, KOD_GIDER, borc_yonlu=True)


async def test_MUTABAKAT_STORNO_turundan_SONRA_da_tutar(
    seeded_db,
    kullanici_id,
    fatura_eslemesi,
):
    """🔴 `POSTING_STATUSES` ayağı: `reversed` fiş defterden ÇIKMAZ, NÖTRLENİR.

    Storno + yeniden fişleme turundan sonra bile iki taban tutmalıdır — aksi
    hâlde MU-3B'nin kısmi tekilliği (İŞ 1) KDV'yi ÇİFT SAYDIRIRDI.
    """
    from app.modules.accounting import state_service as journal_state
    from app.modules.accounting.transitions import JournalAction

    invoice = await fatura_kur(
        seeded_db,
        kullanici_id,
        direction=InvoiceDirection.outgoing,
        kalemler=[("1", "1000.00", "20")],
    )
    await _gecis(seeded_db, kullanici_id, invoice, InvoiceAction.send)
    entry = await _fis(seeded_db, invoice)

    await journal_state.perform_transition(
        seeded_db, await _aktor(seeded_db, kullanici_id), entry.id, JournalAction.reverse
    )

    beyan = await build_vat_return(seeded_db, year=2026, month=7)
    # Fatura hâlâ `sent`tir → beyanname 200,00 sayar; yevmiyede orijinal
    # nötrlenmiştir → 0. 🔴 İKİSİ AYRIŞTI ve bu BEKLENEN hâldir: belge yeniden
    # fişlenmeden mutabakat KURULMAZ (İŞ 1'in tam gerekçesi).
    assert beyan.calculated_vat == Decimal("200.00")
    assert await _hesap_neti(seeded_db, KOD_HES_KDV, borc_yonlu=False) == Decimal("0")

    # Belge yeniden fişlenir (İŞ 1) ve mutabakat GERİ GELİR.
    await posting.post_invoice(seeded_db, await _aktor(seeded_db, kullanici_id), invoice)

    assert beyan.calculated_vat == await _hesap_neti(seeded_db, KOD_HES_KDV, borc_yonlu=False)
