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
from app.modules.payroll import compute, income_tax, posting, service
from app.modules.payroll.models import (
    PayrollLine,
    PayrollLineStatus,
    PayrollPeriodStatus,
    PayrollRate,
)
from app.modules.payroll.tax_bracket_seed_data import (
    MINIMUM_WAGE_GROSS_2026,
    TAX_BRACKETS_2026_WAGE,
)
from app.modules.site_diary.models import WorkerSource
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
from tests.modules.payroll.conftest import AY, SERBEST, SGK_4A, YIL


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
        posting.totals_for(satir_listesi, {}, None)


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
    assert posting.lines_for(posting.totals_for([], {}, None)) == []
    sonuc = await posting.post_payroll_period(db_session, kaydeden, donem, [], {}, None)
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

    async def izle(session, actor, period, lines, rates, minimum_wage_gross):
        cagrilar.append(period.status.value)
        return await gercek(session, actor, period, lines, rates, minimum_wage_gross)

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


# --- 🔴 ORAN SETİ compute ile approve ARASINDA DEĞİŞİRSE (kayıt 221) ---------
#
# `_stamp_share` damgayı KESİNTİNİN KALANI olarak kurar:
#     damga = deduction_amount − rate_share(brüt, sgk%) − rate_share(brüt, işsizlik%)
#             − income_tax_amount
# `deduction_amount` ve `income_tax_amount` compute anında DONDURULMUŞTUR ama
# iki `rate_share` CANLI orandan türer. Oran seti compute ile approve arasında
# değişirse farkın TAMAMI damga payına yazılır.
#
# 🔴 Belirti mizanda GÖRÜNMEZ: fiş cebirsel olarak DENGELİ kalır
# (Σalacak = net + deduction + işveren = brüt + işveren), yalnız `360 Ödenecek
# Vergi ve Fonlar` ile `361 Ödenecek Sosyal Güvenlik Kesintileri` ARASINDAKİ
# dağılım kayar. Hiçbir kapı kırmızıya dönmez — bu dosyanın kendi docstring'i
# tam da bu kusur sınıfını tarif eder ("361'e yazılması gerekeni 360'a yazan
# bir kusur da yeşil kalırdı").
#
# `rates.py` kapısı yalnız ONAYLANMIŞ/ÖDENMİŞ dönem VARSA oran değişimini
# kapatır; taslak dönem serbesttir, yani bu pencere CANLIDA AÇIKTIR.
#
# Oranları satıra dondurmak ÇÖZÜM DEĞİLDİR: `models.py:194` K1 kararı
# "kesinti oranları satıra KOPYALANMAZ, tek gerçek kaynak `payroll_rates`" der
# ve dondurmak migration isterdi. Onarım FAIL-CLOSED bir sınır kontrolüdür.


async def test_ORAN_SETI_HESAPTAN_SONRA_DEGISIRSE_FAIL_CLOSED(
    db_session, donem, dort_tip, kaydeden, oranlar
) -> None:
    """Donmuş kesinti ile canlı oran ayrışırsa fiş YAZILMAZ (422)."""
    await service.compute_period(db_session, donem.id)
    satir_listesi = await satirlar(db_session, donem.id)

    # Fiş YAZILABİLİR olmalı — pozitif kontrol (kapı her şeyi reddetmiyor).
    oran_haritasi = {r.personnel_source: r for r in oranlar}
    posting.totals_for(satir_listesi, oran_haritasi, MINIMUM_WAGE_GROSS_2026)

    # Şimdi oran seti compute'tan SONRA değişsin (SGK işçi payı %14 -> %10).
    # `intern`/`freelance` oranı ZATEN 0'dır ve `ck_payroll_rates_non_negative`
    # negatife inmeyi reddeder — yalnız sıfırdan büyük oran kaydırılır.
    for r in oranlar:
        if r.sgk_employee_pct > Decimal("4"):
            r.sgk_employee_pct = r.sgk_employee_pct - Decimal("4")
    await db_session.flush()

    with pytest.raises(PayrollValidationError):
        posting.totals_for(
            satir_listesi, {r.personnel_source: r for r in oranlar}, MINIMUM_WAGE_GROSS_2026
        )


async def test_ORAN_ARTISI_da_yakalanir(db_session, donem, dort_tip, kaydeden, oranlar) -> None:
    """Kayma İKİ YÖNDE de yakalanır — yalnız negatif damga değil, ŞİŞMİŞ damga da.

    Oran DÜŞERSE kalan büyür (damga tavanı aşılır), ARTARSA kalan küçülür ve
    negatife düşer. Tek yönlü bir kontrol kusurun yarısını kaçırırdı.
    """
    await service.compute_period(db_session, donem.id)
    satir_listesi = await satirlar(db_session, donem.id)

    for r in oranlar:
        r.sgk_employee_pct = r.sgk_employee_pct + Decimal("3")
    await db_session.flush()

    with pytest.raises(PayrollValidationError):
        posting.totals_for(
            satir_listesi, {r.personnel_source: r for r in oranlar}, MINIMUM_WAGE_GROSS_2026
        )


# --- 🔴 kayıt 24 — TAVAN İSTİSNAYI GÖRMÜYORDU (kısmen açık kalan bacak) -----
#
# `_stamp_share`in eski tavanı çıplak `stamp_tax_pct × brüt`tü ve `compute`un
# dilimli rejimde uyguladığı asgari ücret damga istisnasını (DVK (II) IV/34,
# `income_tax.stamp_tax_exemption`) HİÇ görmüyordu. Oran seti compute ile
# approve ARASINDA DÜŞERSE (kalan büyür) bu, gerçek beklenen değerin tam
# istisna tutarı kadar (2026: 250,70 TL) ÜSTÜNE kadar sessizce geçiyordu —
# `test_ORAN_SETI_HESAPTAN_SONRA_DEGISIRSE_FAIL_CLOSED`in kapıyı GEÇİRDİĞİNİ
# ölçtüğü "büyük" kaymalar (−4 puan) hâlâ yakalanıyordu, ama istisnanın
# ölçüsündeki KÜÇÜK kaymalar hiçbir kapıya çarpmadan geçiyordu.


async def test_TAVAN_ISTISNAYI_GORMEYINCE_TAM_ISTISNALI_SATIRDA_HAYALET_DAMGA_GECIYORDU(
    db_session, donem, dort_tip, kaydeden, oranlar
) -> None:
    """Brüt 9.000 (`dort_tip`in şirket satırı) asgari ücretin ALTINDADIR:
    ham damga 68,31 istisnanın (250,70) İÇİNDE erir, gerçek beklenen **0,00**dır.

    SGK işçi oranı compute'tan SONRA yalnız 0,5 puan düşerse (14 → 13,5) kalan
    45,00'a sıçrar. Eski çıplak tavan (68,32) bunu GEÇİRİRDİ — 45,00 TL'lik
    tam bir HAYALET damga 422'siz `360`a yazılırdı.
    """
    await service.compute_period(db_session, donem.id)
    satir_listesi = await satirlar(db_session, donem.id)

    sirket_orani = next(r for r in oranlar if r.personnel_source is WorkerSource.company)
    sirket_orani.sgk_employee_pct = sirket_orani.sgk_employee_pct - Decimal("0.5")
    await db_session.flush()

    with pytest.raises(PayrollValidationError):
        posting.totals_for(
            satir_listesi, {r.personnel_source: r for r in oranlar}, MINIMUM_WAGE_GROSS_2026
        )


def test_TAVAN_ISTISNAYI_GORMEYINCE_KISMEN_ISTISNALI_SATIRDA_da_HAYALET_DAMGA_GECIYORDU() -> None:
    """kayıt 24'ün ikinci bacağı: TAM istisnalı olmayan (brüt asgari ücretin
    üstünde) bir satırda da AYNI boşluk vardı, tek fark payın küçük olmasıydı.

    Brüt 50.000: ham damga 379,50, istisna 250,70, gerçek beklenen **128,80**.
    SGK işçi oranı 14 → 13,75'e (yalnız 0,25 puan) düşerse kalan 253,80'e
    sıçrar — eski çıplak tavanın (379,51) HÂLÂ ALTINDADIR, yani eski kapı bunu
    hiç YAKALAMAZDI; gerçek beklenenden (128,80) 125,00 TL fazla damga
    sessizce `360`a yazılırdı.

    Bu test DB'siz, saf `compute`/`posting` fonksiyonlarını doğrudan çağırır —
    ölçülen tek şey iki fonksiyonun ANLAŞMASI, dönem/fiş akışı değil.
    """
    brackets = tuple(
        income_tax.TaxBracket(ordinal=ordinal, upper_bound=upper_bound, rate_pct=rate_pct)
        for ordinal, upper_bound, rate_pct in TAX_BRACKETS_2026_WAGE
    )
    tax_ctx = compute.TaxContext(
        month=AY,
        prior_cumulative_base=Decimal("0.00"),
        brackets=brackets,
        minimum_wage_gross=MINIMUM_WAGE_GROSS_2026,
    )
    compute_anindaki_oran = PayrollRate(year=YIL, personnel_source=WorkerSource.company, **SGK_4A)
    gross = Decimal("50000.00")
    ded = compute.employee_deductions(gross, compute_anindaki_oran, tax_ctx)
    assert ded is not None
    assert ded.stamp_tax == Decimal("128.80"), "ön koşul: gerçek beklenen damga bu testte sabit"

    line = PayrollLine(
        personnel_source=WorkerSource.company,
        status=PayrollLineStatus.pending,
        gross_amount=gross,
        net_amount=gross - ded.total,
        deduction_amount=ded.total,
        income_tax_amount=ded.income_tax,
    )
    onay_anindaki_oran = PayrollRate(
        year=YIL,
        personnel_source=WorkerSource.company,
        **{**SGK_4A, "sgk_employee_pct": Decimal("13.750")},
    )

    with pytest.raises(PayrollValidationError):
        posting.totals_for(
            [line], {WorkerSource.company: onay_anindaki_oran}, MINIMUM_WAGE_GROSS_2026
        )


def test_ASGARI_UCRET_YOKKEN_DILIMLI_rejimde_FAIL_CLOSED_kapanir() -> None:
    """kayıt 24'ün fail-closed dalının KENDİ bekçisi (2026-09-23).

    `_expected_stamp_tax` dilimli rejimde (`income_tax_pct is None`) damga
    istisnasını asgari ücretten türetir; asgari ücret satırı YOKSA beklenen
    damgayı HESAPLAYAMAZ ve fişlemeyi reddeder. Bu dal bir onarım turunda
    yazılmıştı ama hiçbir test onu DOĞRUDAN ölçmüyordu: tek dolaylı tanığı
    `test_payroll_approval_concurrency.py`nin asgari ücret seed'i EKSİK olan
    kurulumuydu — o eksik giderilince dal bekçisiz kaldı (ölçüldü).

    🔴 Kapının DAR olması da bu testin iddiasıdır: DÜZ oran rejiminde
    (`income_tax_pct` dolu) istisna kavramı yoktur, asgari ücret GEREKMEZ ve
    kapı koşmamalıdır. İkinci iddia bu daralmanın pozitif kontrolüdür — kapı
    rejim ayrımını kaybederse (ör. koşulsuz `raise`) o iddia kırmızı olur.
    """
    dilimli_oran = PayrollRate(year=YIL, personnel_source=WorkerSource.company, **SGK_4A)
    line = PayrollLine(
        personnel_source=WorkerSource.company,
        status=PayrollLineStatus.pending,
        gross_amount=Decimal("9000.00"),
        net_amount=Decimal("7650.00"),
        deduction_amount=Decimal("1350.00"),
        income_tax_amount=Decimal("0.00"),
    )

    with pytest.raises(PayrollValidationError):
        posting._expected_stamp_tax(line, dilimli_oran, None)

    duz_oran = PayrollRate(year=YIL, personnel_source=WorkerSource.company, **SERBEST)
    assert posting._expected_stamp_tax(line, duz_oran, None) == Decimal("0.00"), (
        "DÜZ oran rejiminde damga oranı 0 ise beklenen damga da 0'dır ve asgari "
        "ücret HİÇ sorulmaz — kapı bu rejimde koşmamalıdır"
    )
