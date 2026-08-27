"""🔴 MU-3C — **FİŞLENEN OLAY KÜMESİNİ** ölçen bekçi (SAHTE-YEŞİLİN 8. HÂLİ).

## Neden SAYIM YETMEZ

MU-3B'de ölçüldü: *"şu geçiş fazladan fiş üretmiyor"* diyen bir test,
fişlenen eylem kümesine yeni bir üye eklendiğinde **KIRMIZIYA DÖNMEDİ** —
çünkü `post_document` idempotandır, ikinci çağrı `created=False` döner ve
FİŞ SAYISI yine 1 kalır. Test SONUCU ölçüyordu, KÜMEYİ değil.

MU-3C fişlenen olay kümesini GENİŞLETMİŞTİ (ödeme yazımı). 🔴 **ODM-1 onu bir
kez daha GENİŞLETİR ve bu dosya TERSİNE ÇEVRİLİR:** `collected`/`paid`
geçişleri artık kümenin ÜYESİDİR (`101`/`103` ara hesabı kapanır), ama
`returned`/`cancelled` **DEĞİLDİR** — onlar bağlı ödemelerin fişini STORNO eder
ve storno kaynak damgası TAŞIMAZ (D6). Kümenin bu dilimde ölçtüğü asıl şey
budur: dört terminal durumun İKİSİ fişler, İKİSİ fişlemez.

Ölçülen şey yine **KÜMENİN KENDİSİDİR** ve evren BAĞIMSIZ BİR KAYNAKTAN
türetilir:

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
* `change_status`ten `_post_transition` çağrısı SİLİNİRSE → küme İKİ üye
  KAYBEDER → KIRMIZI.
* `returned`/`cancelled` STORNO yerine YENİ FİŞ yazmaya başlarsa → küme İKİ üye
  KAZANIR → KIRMIZI.

Üçü de programı GERÇEKTEN değiştirir (eşdeğer mutant değildir).

## 🔴 KURULUMUN ZORUNLU AYAĞI: HER ENSTRÜMANIN BAĞLI ÖDEMESİ VAR

ODM-1 öncesi bu dosya enstrümanları ÖDEMESİZ kuruyordu. O kurulum bugün
SAHTE-YEŞİL üretirdi: bağlı ödemesi olmayan bir çekin tahsili `101`e girmiş bir
para bulamaz ve HİÇ FİŞ YAZMAZ (D3) — yani `_post_transition` tümüyle silinse
bile küme değişmezdi. Bu yüzden her geçiş, tutarı bilinen BAĞLI bir ödemeyle
kurulur ve `test_KURULUM_...` ayrıca çakar.
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
    FinancialInstrumentDirection,
    FinancialInstrumentKind,
    FinancialInstrumentStatus,
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

#: 🔴 ODM-1 — kümenin BEKLENEN hâli. Elle yazılır ve öyle KALMALIDIR: üründen
#: türetilseydi (ör. `posting.POSTING_STATUSES`ten) test, ölçtüğü kararı ölçtüğü
#: koddan okur ve o karar değiştiğinde SESSİZCE onunla birlikte değişirdi.
BEKLENEN_FISLEYEN = {
    "payment.create",
    "instrument.received.portfolio->collected",
    "instrument.issued.portfolio->paid",
}

#: Fatura yönü ↔ çek yönü — FIN-PAY K3'ün uyumlu çifti. Ters çift 422'dir, yani
#: kurulumun kendisi bu tabloya UYMAK ZORUNDADIR.
_FATURA_YONU = {
    FinancialInstrumentDirection.received: (InvoiceDirection.outgoing, InvoiceStatus.sent),
    FinancialInstrumentDirection.issued: (InvoiceDirection.incoming, InvoiceStatus.approved),
}

CEK_TUTARI = Decimal("500.00")


async def _bagli_cek(
    seeded_db,
    kullanici,
    account,
    *,
    yon: FinancialInstrumentDirection,
    kaynak,
) -> FinancialInstrument:
    """Bir çek + ona BAĞLI bir ödeme kurar.

    🔴 Ödeme `payments_service.create_payment`ten geçer, elle YAZILMAZ: fişi
    olmayan bir ödeme `101`e hiç para koymaz ve tahsil geçişi de çıkaracak bir
    şey bulamazdı — kurulum, ölçmek istediği dalı hiç açmamış olurdu.
    """
    yon_bilgisi, durum = _FATURA_YONU[yon]
    instrument = FinancialInstrument(
        instrument_kind=FinancialInstrumentKind.cheque,
        direction=yon,
        serial_no="0123456789",
        drawer_name="Güneşkent A.Ş.",
        issue_date=TARIH,
        due_date=TARIH,
        amount=CEK_TUTARI,
        status=FinancialInstrumentStatus.portfolio,
    )
    seeded_db.add(instrument)
    await seeded_db.flush()

    invoice = await fatura(
        seeded_db, kullanici, direction=yon_bilgisi, total=str(CEK_TUTARI), status=durum
    )
    await payments_service.create_payment(
        seeded_db,
        kullanici,
        invoice.id,
        PaymentCreate(
            bank_account_id=account.id,
            method=PaymentMethodKind.cheque,
            amount=CEK_TUTARI,
            paid_on=TARIH,
            financial_instrument_id=instrument.id,
        ),
    )
    # Kaynak durum tabloda `portfolio`dur; bağ kurulduktan SONRA damgalanır
    # (D4: terminal evraka ödeme bağlanamaz — kurulumun kendisi o kapıdan geçer).
    instrument.status = kaynak
    await seeded_db.flush()
    return instrument


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
            instrument = await _bagli_cek(seeded_db, kullanici, account, yon=yon, kaynak=kaynak)

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
    assert fisleyen == BEKLENEN_FISLEYEN, (
        "FİŞLENEN OLAY KÜMESİ DEĞİŞTİ. ODM-1'de fişleyen olaylar tam olarak "
        "şunlardır: ödeme yazımı (`101`/`103`e ya da nakde) ve çek/senedin "
        "TAHSİL/ÖDEME geçişi (`101`/`103`ü kapatır). `returned`/`cancelled` "
        "STORNO yazar, kaynak damgalı YENİ fiş DEĞİL (D6); ödeme silme de "
        "öyledir. Beklenen ile fark: "
        f"fazla={sorted(fisleyen - BEKLENEN_FISLEYEN)} · "
        f"eksik={sorted(BEKLENEN_FISLEYEN - fisleyen)}"
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
