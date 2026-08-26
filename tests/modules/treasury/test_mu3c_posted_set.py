"""🔴 MU-3C — **FİŞLENEN OLAY KÜMESİNİ** ölçen bekçi (SAHTE-YEŞİLİN 8. HÂLİ).

## Neden SAYIM YETMEZ

MU-3B'de ölçüldü: *"şu geçiş fazladan fiş üretmiyor"* diyen bir test,
fişlenen eylem kümesine yeni bir üye eklendiğinde **KIRMIZIYA DÖNMEDİ** —
çünkü `post_document` idempotandır, ikinci çağrı `created=False` döner ve
FİŞ SAYISI yine 1 kalır. Test SONUCU ölçüyordu, KÜMEYİ değil.

MU-3C fişlenen olay kümesini GENİŞLETİYOR (ödeme yazımı) ve genişlememesi
gerekenler (çek/senet durum geçişleri · tahsilat damgası) tam olarak bu
dilimin çift sayım riskidir. Bu yüzden burada ölçülen şey **KÜMENİN
KENDİSİDİR** ve evren BAĞIMSIZ BİR KAYNAKTAN türetilir:

* çek/senet olayları `instruments.transitions.TRANSITIONS` tablosundan
  (elle yazılmış bir liste, tablo büyüdüğünde SESSİZCE eksik kalırdı);
* ödeme olayları `payments_service`in yazma uçlarından.

## Ölçüm: "yeni KAYNAK DAMGALI fiş doğdu mu"

Storno `source_type`/`source_id` TAŞIMAZ (`journal_entries` docstring'i:
taşısaydı `uq_journal_entries_source` orijinalle çakışırdı). Bu yüzden ölçüm
`source_type IS NOT NULL` olan YENİ fişler üzerindedir — silme yolunun ürettiği
storno bir "fişleme olayı" DEĞİLDİR ve karşılığı `test_mu3c_payment_posting.py`
::`test_ODEME_SILININCE_STORNO_yazilir_ve_net_TAM_sifirlanir`tedir.

## 🔴 MUTASYON KANITI (raporda sayıyla)

* `create_payment`ten `post_payment` çağrısı SİLİNİRSE → küme `payment` üyesini
  KAYBEDER → KIRMIZI.
* `instruments.service.change_status` fiş atmaya BAŞLARSA → küme yeni bir üye
  KAZANIR → KIRMIZI.

İkisi de programı GERÇEKTEN değiştirir (eşdeğer mutant değildir): biri yazılan
fişi yok eder, öteki yeni bir fiş yazar.
"""

from decimal import Decimal

from sqlalchemy import select

from app.modules.accounting.models import JournalEntry, JournalSourceType
from app.modules.invoicing.models import InvoiceDirection, InvoiceStatus
from app.modules.treasury import payments_service
from app.modules.treasury.instruments import service as instruments_service
from app.modules.treasury.instruments import transitions as instrument_transitions
from app.modules.treasury.models import (
    FinancialInstrument,
    FinancialInstrumentKind,
    Payment,
    PaymentMethodKind,
)
from app.modules.treasury.schemas import PaymentCreate
from tests.modules.treasury._mu3c import (
    TARIH,
    aktor,
    banka_hesabi,
    esleme_kur,
    fatura,
)

#: 🔴 EVRENİN ÖDEME AYAĞI — `payments_service`in İKİ yazma ucu. Adlar burada
#: sabittir çünkü bir uç KALDIRILIRSA test `AttributeError` ile patlamalıdır,
#: sessizce küçülen bir evrenle yeşil kalmamalıdır.
ODEME_OLAYLARI = ("payment.create", "payment.delete")


def _cek_olaylari() -> tuple[str, ...]:
    """Çek/senet olay evreni — `TRANSITIONS` TABLOSUNDAN türetilir.

    Elle yazılsaydı tabloya yeni bir geçiş eklendiğinde bu bekçi onu HİÇ
    denemez ve o geçiş fiş atmaya başlasa bile yeşil kalırdı.
    """
    return tuple(
        sorted(
            f"instrument.{yon.value}.{kaynak.value}->{hedef.value}"
            for yon, ciftler in instrument_transitions.TRANSITIONS.items()
            for kaynak, hedef in ciftler
        )
    )


async def _kaynak_damgalari(session) -> set[tuple[JournalSourceType, object]]:
    """Deftere düşmüş TÜM kaynak damgaları — storno (NULL damga) HARİÇ."""
    rows = (
        await session.execute(
            select(JournalEntry.source_type, JournalEntry.source_id).where(
                JournalEntry.source_type.is_not(None)
            )
        )
    ).all()
    return {(tur, kimlik) for tur, kimlik in rows}


async def test_FISLENEN_OLAY_KUMESI_bagimsiz_evrenden_TURETILIR(seeded_db, user_factory):
    """🔴 KÜMEYİ ölçer, SAYIYI değil. Evren `TRANSITIONS` + ödeme uçlarıdır.

    Her olay tek tek koşturulur ve *"yeni KAYNAK DAMGALI fiş doğdu mu"* sorusu
    ayrı ayrı sorulur. Sonuç bir KÜME olarak karşılaştırılır: tek bir sayı
    (toplam fiş adedi) karşılaştırılsaydı, bir olayın fiş atmaya başlaması
    başka bir olayınkiyle telafi edilebilirdi.
    """
    await esleme_kur(seeded_db)
    kullanici = await aktor(seeded_db, user_factory)
    account = await banka_hesabi(seeded_db)

    fisleyen: set[str] = set()
    denenen: list[str] = []

    # --- çek/senet: tablodan türeyen HER geçiş ---
    for yon, ciftler in instrument_transitions.TRANSITIONS.items():
        for kaynak, hedef in sorted(ciftler, key=lambda c: (c[0].value, c[1].value)):
            olay = f"instrument.{yon.value}.{kaynak.value}->{hedef.value}"
            denenen.append(olay)
            instrument = FinancialInstrument(
                instrument_kind=FinancialInstrumentKind.cheque,
                direction=yon,
                serial_no="0123456789",
                drawer_name="Güneşkent A.Ş.",
                issue_date=TARIH,
                due_date=TARIH,
                amount=Decimal("500.00"),
                status=kaynak,
            )
            seeded_db.add(instrument)
            await seeded_db.flush()

            once = await _kaynak_damgalari(seeded_db)
            await instruments_service.change_status(seeded_db, kullanici, instrument.id, hedef)
            if await _kaynak_damgalari(seeded_db) - once:
                fisleyen.add(olay)

    # --- ödeme yazımı ---
    denenen.append("payment.create")
    invoice = await fatura(
        seeded_db,
        kullanici,
        direction=InvoiceDirection.outgoing,
        total="1000.00",
        status=InvoiceStatus.sent,
    )
    once = await _kaynak_damgalari(seeded_db)
    payment, _ = await payments_service.create_payment(
        seeded_db,
        kullanici,
        invoice.id,
        PaymentCreate(
            bank_account_id=account.id,
            method=PaymentMethodKind.transfer,
            amount=Decimal("1000.00"),
            paid_on=TARIH,
        ),
    )
    if await _kaynak_damgalari(seeded_db) - once:
        fisleyen.add("payment.create")

    # --- ödeme silme (storno üretir, YENİ KAYNAK DAMGASI üretmez) ---
    denenen.append("payment.delete")
    once = await _kaynak_damgalari(seeded_db)
    await payments_service.delete_payment(seeded_db, kullanici, payment.id)
    if await _kaynak_damgalari(seeded_db) - once:
        fisleyen.add("payment.delete")

    # 🔴 Evrenin GERÇEKTEN denendiğini çakar: `TRANSITIONS` boşalsa ya da bir
    #    olay atlansa, aşağıdaki küme eşitliği yine tutabilirdi.
    assert sorted(denenen) == sorted(_cek_olaylari() + ODEME_OLAYLARI), (
        "evren eksik denendi — `TRANSITIONS` tablosu ile denenen olaylar AYRIŞTI"
    )
    assert fisleyen == {"payment.create"}, (
        "FİŞLENEN OLAY KÜMESİ DEĞİŞTİ. Nakdin tek tanımı `treasury/balance.py`dir "
        "ve o YALNIZ `payments`ı sayar; çek/senet geçişleri fiş atarsa nakit "
        "mutabakatı yapısal olarak kırılır (gerekçe `treasury/posting.py`). "
        f"fişleyen={sorted(fisleyen)}"
    )


async def test_HER_ODEME_SATIRININ_canli_fisi_VARDIR(seeded_db, user_factory):
    """🔴 KÜMENİN ÖTEKİ YÖNÜ: fişlenen ödemeler kümesi = TÜM ödemeler kümesi.

    Bağımsız kaynak `payments` tablosunun KENDİSİDİR. Bir yazma yolu fişlemeyi
    atlarsa (ya da ileride ikinci bir yazma ucu açılırsa) iki küme AYRIŞIR;
    fiş SAYISINI ölçen bir test bunu göremezdi çünkü sayı yine "ödeme sayısı
    kadar" görünebilirdi.
    """
    await esleme_kur(seeded_db)
    kullanici = await aktor(seeded_db, user_factory)
    account = await banka_hesabi(seeded_db)
    for tutar, yon, durum in (
        ("400.00", InvoiceDirection.outgoing, InvoiceStatus.sent),
        ("600.00", InvoiceDirection.incoming, InvoiceStatus.approved),
    ):
        invoice = await fatura(seeded_db, kullanici, direction=yon, total=tutar, status=durum)
        await payments_service.create_payment(
            seeded_db,
            kullanici,
            invoice.id,
            PaymentCreate(
                bank_account_id=account.id,
                method=PaymentMethodKind.transfer,
                amount=Decimal(tutar),
                paid_on=TARIH,
            ),
        )

    odemeler = set((await seeded_db.execute(select(Payment.id))).scalars().all())
    fislenen = set(
        (
            await seeded_db.execute(
                select(JournalEntry.source_id).where(
                    JournalEntry.source_type == JournalSourceType.payment
                )
            )
        )
        .scalars()
        .all()
    )

    assert odemeler, "kurulum ödeme YAZMADI — bekçi hiçbir şeyi ölçmüyor olurdu"
    assert fislenen == odemeler, (
        f"FİŞSİZ ödeme var: {sorted(odemeler - fislenen)} · "
        f"ödemesiz fiş var: {sorted(fislenen - odemeler)}"
    )
