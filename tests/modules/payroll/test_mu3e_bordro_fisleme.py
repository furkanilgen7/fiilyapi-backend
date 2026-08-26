"""🔴 MU-3E — BORDRO TAHAKKUK FİŞİ: bacaklar · fişin doğduğu an · fail-closed.

Bu dosya fişin ŞEKLİNİ ve TUTARINI birlikte ölçer. Yalnız şekil ölçülseydi
(`{730, 335, 360, 361}` bacağı var mı) tutarları yer değiştiren bir eşleme
hatası yeşil kalırdı; yalnız toplam ölçülseydi (fiş dengede mi) `361`e
yazılması gerekeni `360`a yazan bir kusur da yeşil kalırdı — fiş yine dengeli
olurdu ve mizanın toplamı TUTMAYA DEVAM EDERDİ.

Sayıların nereden geldiği `_mu3e.py`nin docstring'indedir.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core.errors import ConflictError, PayrollValidationError
from app.modules.accounting.models import (
    AccountingPeriod,
    AccountingPeriodStatus,
    JournalEntry,
    JournalEntryStatus,
    JournalSourceType,
)
from app.modules.payroll import posting, service
from app.modules.payroll.models import PayrollLineStatus, PayrollPeriodStatus
from tests.modules.payroll._mu3e import (
    GIDER_BACAGI,
    KOD_GIDER,
    KOD_PERSONEL_BORC,
    KOD_SGK_BORC,
    KOD_VERGI_BORC,
    SGK_BACAGI,
    TOPLAM_NET,
    VERGI_BACAGI,
    bacaklar,
    bordro_fisi,
    satirlar,
)


async def _onayla(db_session, kaydeden, donem, adim: int = 2):
    """Dönemi `compute` + N adım onayla ilerletir.

    `compute` dönemi `draft → pending_approval`a KENDİLİĞİNDEN taşır (T6), yani
    `approved`a TEK bir `approve_period` yeter. İkinci bir adım isteyen çağıran
    olmadığı için varsayılan 2 DEĞİL 1 olmalıydı — ama `dort_tip`in tüm
    satırları hesaplanabilir olmayabilir, bu yüzden adım sayısı ölçülür:
    dönem `approved` olana kadar (en çok `adim` kez) ilerletilir.
    """
    await service.compute_period(db_session, donem.id)
    for _ in range(adim):
        if donem.status is PayrollPeriodStatus.approved:
            break
        await service.approve_period(db_session, kaydeden, donem.id)
    return donem


async def test_ONAY_dort_bacakli_fis_keser_ve_TUTARLAR_birebir(
    db_session, donem, dort_tip, kaydeden
) -> None:
    """🔴 BU DİLİMİN KABUL KAPISI — bacaklar VE tutarlar birebir.

    Sıra da SABİTTİR (borç önce): fiş satırları `sort_order`a düşer ve iki
    koşuda farklı dizilmiş bir defter satırı üretilemez.
    """
    await _onayla(db_session, kaydeden, donem)

    entry = await bordro_fisi(db_session, donem.id)
    assert entry is not None, "dönem onaylandı ama FİŞ YAZILMADI"
    assert entry.status is JournalEntryStatus.posted, "KARAR-3: fiş `posted` DOĞAR"
    assert await bacaklar(db_session, entry) == [
        (KOD_GIDER, str(GIDER_BACAGI), "0.00"),
        (KOD_PERSONEL_BORC, "0.00", str(TOPLAM_NET)),
        (KOD_VERGI_BORC, "0.00", str(VERGI_BACAGI)),
        (KOD_SGK_BORC, "0.00", str(SGK_BACAGI)),
    ]
    assert entry.total_debit == entry.total_credit == GIDER_BACAGI


async def test_FIS_AYIN_SON_GUNUNE_yazilir_onay_gunune_DEGIL(
    db_session, donem, dort_tip, kaydeden
) -> None:
    """🔴 `entry_date` = ayın son günü (`approved_at.date()` DEĞİL).

    İki şey birden bekçilenir: (a) tahakkukun muhasebe tarihi dönemin AYIDIR,
    (b) `timestamptz` üzerinde ham `.date()` çağıran YEREL TAKVİM KAÇAĞI
    (TR = UTC+3) buraya YAPISAL OLARAK giremez — ortada dönüştürülecek bir
    zaman damgası yoktur.

    `period_year`/`period_month` de ayrıca ölçülür: `ck_journal_entries_period_
    matches_date` onları zaten bağlar ama mizanın süzdüğü kolonlar BUNLARDIR.
    """
    await _onayla(db_session, kaydeden, donem)
    entry = await bordro_fisi(db_session, donem.id)

    assert (entry.entry_date.year, entry.entry_date.month) == (donem.year, donem.month)
    assert entry.entry_date.day == 31, "Temmuz'un son günü 31'dir — ay sonu SEÇİLMEMİŞ"
    assert (entry.period_year, entry.period_month) == (donem.year, donem.month)
    assert donem.approved_at is not None, "onay damgası basılmadı — kurulum yanlış"


async def test_ILK_ADIM_pending_approval_FIS_YAZMAZ(db_session, donem, dort_tip, kaydeden) -> None:
    """🔴 Kanca GEÇİŞE değil HEDEF DURUMA bağlıdır.

    `approve_period` TEK ADIM ilerletir (S8). `action is approve` gibi bir
    koşul yazılsaydı `draft → pending_approval` adımında da fiş kesilir ve
    ONAYLANMAMIŞ bir bordro mizana girerdi.

    🔴 **KURULUM SATIRLI OLMAK ZORUNDA — ilk yazımda DEĞİLDİ ve mutant SAĞ
    KALDI.** Test önce `compute`suz koşuyordu; satır olmadığı için
    `post_payroll_period` zaten `None` dönüyor ve kanca NEREYE bağlanırsa
    bağlansın hiçbir şey yazılmıyordu. Yani iddia doğruydu ama HİÇBİR ŞEYİ
    BEKÇİLEMİYORDU (ölçüldü: kancayı `if True:` yapan mutant 24/24 YEŞİL
    geçti).

    `compute` dönemi kendiliğinden `pending_approval`a taşır (T6), bu yüzden
    "satırlı ama `draft`" hâli ELLE kurulur. Fixture'ların durumu doğrudan
    yazması bu depoda yerleşik bir kurulum desenidir (`fatura_fabrikasi`).
    """
    await service.compute_period(db_session, donem.id)
    donem.status = PayrollPeriodStatus.draft
    await db_session.flush()

    sonuc, _ = await service.approve_period(db_session, kaydeden, donem.id)

    assert sonuc.period_status is PayrollPeriodStatus.pending_approval
    assert sonuc.approved > 0, "kurulumda onaylanacak satır YOK — bekçi yine kör olurdu"
    assert await bordro_fisi(db_session, donem.id) is None, (
        "ONAYLANMAMIŞ dönem fişlendi — kanca hedef duruma değil eyleme bağlanmış"
    )


async def test_PAY_ucu_IKINCI_fis_URETMEZ(db_session, donem, dort_tip, kaydeden) -> None:
    """🔴 `pay` PARA TAŞIMAZ (banka hesabı almaz, `payments` satırı yazmaz).

    Nakit bacağı BELGEYE bağlanır (MU-3C kanonu) ve ortada belge yoktur.
    Buradan fiş atılsaydı `post_document` idempotanlık dalına düşer ve
    SESSİZCE hiçbir şey yazmazdı — yanlış kancanın bedeli bir hata değil bir
    SESSİZLİKTİR. Bu yüzden fiş SAYISI ölçülür, varlığı değil.
    """
    await _onayla(db_session, kaydeden, donem)
    once = await db_session.scalar(select(func.count()).select_from(JournalEntry))
    assert once == 1, "kurulum tek fiş yazmadı — bekçi hiçbir şeyi ölçmüyor olurdu"

    await service.pay_period(db_session, donem.id)

    sonra = await db_session.scalar(select(func.count()).select_from(JournalEntry))
    assert sonra == once, "`pay` fiş kesti — nakit bacağının üç girdisi de YOKTUR"


async def test_BILESENI_EKSIK_satir_FAIL_CLOSED_ve_YARIM_FIS_YAZILMAZ(
    db_session, donem, dort_tip, kaydeden
) -> None:
    """🔴 IK3-GV ÖNCESİ satır (`income_tax_amount IS NULL`) fişlenemez.

    Böyle bir satırın neti `335`e girer ama vergisi `360`a giremez — fiş
    DENGESİZ olurdu. Eksiği 0 saymak, bilinmeyen bir vergiyi "vergi yok" diye
    deftere yazmak olurdu (NULL-EŞİK kanonu).

    🔴 **Hiçbir fiş satırı yazılmaz.** `post_document` bacakları YAZDIKTAN
    sonra patlayan bir kod, aynı 422'yi verir ama transaction'ın geri
    alınmasına GÜVENİYOR olurdu; burada yazımın hiç BAŞLAMADIĞI ölçülür.

    ⚠️ Dönemin durum damgasının geri alınması ÇAĞIRANIN transaction
    sınırındadır (router) ve bu testte ölçülemez: `db_session.rollback()` bu
    kümede `compute`u da geri alır ve iddia BOŞA ÇIKARDI. Damganın fişle AYNI
    transaction'da yazıldığı `approve_period`in kod yapısıyla sabittir
    (arada `commit` YOKTUR).
    """
    await service.compute_period(db_session, donem.id)
    hedef = next(
        satir
        for satir in await satirlar(db_session, donem.id)
        if satir.status is PayrollLineStatus.pending
    )
    hedef.income_tax_amount = None
    await db_session.flush()

    with pytest.raises(PayrollValidationError):
        await service.approve_period(db_session, kaydeden, donem.id)

    assert await db_session.scalar(select(func.count()).select_from(JournalEntry)) == 0, (
        "YARIM FİŞ yazılmış — fail-closed kapısı bacak yazımından SONRAYA düşmüş"
    )


async def test_ORAN_SETI_YOKSA_da_FAIL_CLOSED(db_session, donem, dort_tip, kaydeden) -> None:
    """ŞEF KARARI 2'nin fişleme ayağı: primi BİLİNMEYEN satır fişe giremez.

    Oranı 0 saymak `730`u ve `361`i sistematik olarak EKSİK gösterirdi ve fiş
    yine DENGELİ olurdu — mizan doğru görünürdü.
    """
    await service.compute_period(db_session, donem.id)
    satir_listesi = await satirlar(db_session, donem.id)
    with pytest.raises(PayrollValidationError):
        posting.totals_for(satir_listesi, {})


async def test_KAPALI_MUHASEBE_DONEMI_409_ve_ONAY_GERCEKLESMEZ(
    db_session, donem, dort_tip, kaydeden
) -> None:
    """🔴 KARAR-6'nın ayağı — kapalı ayın mizanı sessizce oynamaz.

    Fiş ayın SON GÜNÜNE yazılır; o ayın muhasebe dönemi kapalıysa
    `post_document` **409** verir ve onay GERÇEKLEŞMEZ.
    """
    db_session.add(
        AccountingPeriod(
            year=donem.year,
            month=donem.month,
            status=AccountingPeriodStatus.closed,
            closed_at=datetime.now(UTC),
            closed_by_id=kaydeden.id,
        )
    )
    await db_session.flush()
    await service.compute_period(db_session, donem.id)

    with pytest.raises(ConflictError):
        await service.approve_period(db_session, kaydeden, donem.id)


async def test_SIFIR_TUTARLI_donem_FIS_ACMAZ_422_de_VERMEZ(db_session, donem, kaydeden) -> None:
    """Ödenebilir satırı OLMAYAN dönem `None` döner — 422 DEĞİL.

    422 kullanıcının ONAYINI bloklardı ve satırsız bir dönem normal hâldir
    (`invoicing.posting`in "toplamı sıfır fatura" dalıyla aynı gerekçe).
    """
    assert posting.lines_for(posting.totals_for([], {})) == []
    sonuc = await posting.post_payroll_period(db_session, kaydeden, donem, [], {})
    assert sonuc is None


async def test_IKINCI_ONAY_IKINCI_fis_URETMEZ(db_session, donem, dort_tip, kaydeden) -> None:
    """İdempotanlık — üçüncü `approve` 409'dur ama fiş sayısı da ölçülür.

    `post_document`in idempotanlık dalı SESSİZDİR; sayı ölçülmeseydi ikinci
    bir fişin doğmadığını hiçbir iddia söylemezdi.
    """
    await _onayla(db_session, kaydeden, donem)
    # Üçüncü çağrı 409'dur (`approved → paid` bu uçtan basılmaz) ve DB'ye
    # hiçbir şey yazmadan patlar; `rollback` ÇAĞRILMAZ — bu kümede o, testin
    # kendi kurulumunu da geri alır ve aşağıdaki sayım BOŞA ÇIKARDI.
    with pytest.raises(ConflictError):
        await service.approve_period(db_session, kaydeden, donem.id)

    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(JournalEntry)
            .where(JournalEntry.source_type == JournalSourceType.payroll_period)
        )
        == 1
    )


def test_KDV_ROLU_bordro_ailesinde_TANIMSIZDIR() -> None:
    """Bordro KDV TAŞIMAZ — rol tanımlı olmadığı için `post_document` çözemez.

    Bir kod dalı değil, bir VERİ olgusudur: KDV bacağı yazmak tip düzeyinde
    imkânsızdır.
    """
    roller = {rol for rol, _kod in posting.PAYROLL_POSTING_RULES}
    assert not (roller & {"vat_input", "vat_output", "vat"})


def test_KARAR_1_ve_KARAR_2_bordro_ailesinde_de_TUTAR() -> None:
    """`170`/`350` ÖLÜ · alt hesap AÇILMAZ · CARİ hesap bu ailede HİÇ GEÇMEZ."""
    kodlar = {kod for _rol, kod in posting.PAYROLL_POSTING_RULES}
    assert not (kodlar & {"170", "350"}), "KARAR-1: yıllara yaygın rejim seçilmiş"
    assert not (kodlar & {"320", "120"}), (
        "bordro CARİ hesaba yazıyor — personele borç `335`tir, satıcıya borç DEĞİL"
    )
    for kod in kodlar:
        assert "." not in kod, f"KARAR-2: alt hesap kodu tohumlanmış ({kod})"


def test_ROL_ADLARI_OTEKI_AILELERINKIYLE_CAKISMAZ() -> None:
    """🔴 `expense`/`payable` adları KULLANILMADI ve bu bilinçlidir.

    Öteki ailelerin `expense` rolü `740`ı, `payable` rolü `320`yi gösterir;
    bu aileninkiler `730` ve `335`tir. `posting_rules`ın anahtarı
    `(source_type, role_key)` olduğu için teknik bir çakışma OLMAZDI — ama
    aynı ad okuyucuya AYNI hesabı gösterdiklerini İMA EDERDİ.
    """
    from app.modules.invoicing.posting import INVOICE_POSTING_RULES

    bordro = {rol for rol, _kod in posting.PAYROLL_POSTING_RULES}
    fatura = {rol for rol, _kod in INVOICE_POSTING_RULES}
    assert not (bordro & fatura)
    assert Decimal("0") == Decimal("0.00")  # ölçek eşitliği: sabitler kuruşlu yazılır


async def test_FISLEME_YOLU_TAM_BIR_KEZ_CAGRILIR(
    db_session, donem, dort_tip, kaydeden, monkeypatch
) -> None:
    """🔴 EKSİK BEKÇİ — MUTASYON TURUNDA BULUNDU (sahte-yeşilin 9. hâli).

    İki mutant hiçbir testi kırmadan sağ kaldı ve ikisi de AYNI körlükten
    besleniyordu: **`post_document` İDEMPOTANDIR.**

    * kanca `if True:` yapıldı (her onay adımında koşar) → 24/24 YEŞİL;
    * kanca `pay_period`e de eklendi → 24/24 YEŞİL.

    İkincisinde dönemin CANLI fişi zaten vardır, çağrı idempotanlık dalına
    düşer ve **SESSİZCE hiçbir şey yazmaz.** Fiş SAYAN her test yeşil kalır;
    "yanlış kancanın bedeli bir hata değil bir SESSİZLİKTİR" tam olarak budur.

    Sayının ölçemediğini ölçen tek şey ÇAĞRININ KENDİSİDİR: fişleme yolu
    dönem başına TAM BİR KEZ ve YALNIZ `approved` hedefinde denenmelidir.

    🔴 Yama `service.approvals`ın GÖRDÜĞÜ ada yapılır (`approvals.posting.
    post_payroll_period`), `payroll.posting`e değil: modül nesnesi paylaşıldığı
    için ikisi aynı yere düşer, ama niyet çağıranın yolunu ölçmektir.
    """
    from app.modules.payroll.service import approvals

    cagrilar: list[str] = []
    gercek = posting.post_payroll_period

    async def izle(session, actor, period, lines, rates):
        cagrilar.append(period.status.value)
        return await gercek(session, actor, period, lines, rates)

    monkeypatch.setattr(approvals.posting, "post_payroll_period", izle)

    await service.compute_period(db_session, donem.id)
    while donem.status is not PayrollPeriodStatus.approved:
        await service.approve_period(db_session, kaydeden, donem.id)
    await service.pay_period(db_session, donem.id)

    assert cagrilar == [PayrollPeriodStatus.approved.value], (
        "FİŞLEME YOLU yanlış sayıda/yerde denendi. Her fazladan çağrı bir ÇİFT "
        "SAYIM ADAYIDIR ve idempotanlık onu SESSİZCE yutar — fiş sayan hiçbir "
        f"test bunu göremez. çağrılar={cagrilar}"
    )
