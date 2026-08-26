"""🔴 MU-3E MUTABAKAT — bordro yüzeyleri ile yevmiye BİREBİR tutar.

## Neden gerekli

Bordronun kendi özet/rapor uçları vardır (`summary` · `sgk_summary` ·
`payable`); yevmiyeye yazınca **İKİNCİ BİR KAYNAK** doğar.

🔑 **Kanon: aynı büyüklüğün iki kaynağı varsa, ayrıştıklarını HİÇBİR KOLON
FARKI ele vermez — çünkü bakiye SAKLANMAZ.** Ne `payroll_periods`ta bir
toplam kolonu vardır (kasten: "iki gerçek kaynak sessizce çelişirdi"), ne de
`chart_of_accounts`ta bir bakiye. İkisi de her okumada TÜRETİLİR ve
ayrıştıkları gün ekran ile mizan farklı para gösterir, kimse fark etmez.

## 🔴 MUTABAKAT KIRILIMLIDIR

Dört hesap AYRI AYRI ölçülür. Toplam ölçülseydi (`Σ borç == Σ alacak`) bir
EŞLEME hatası — `361`e yazılması gerekeni `360`a yazmak — fişi yine dengeli
bırakır ve YEŞİL KALIRDI. Dahası ikisi de mizanda "Kısa Vadeli Yabancı
Kaynaklar" altında toplandığı için mizanın alt toplamı da TUTMAYA DEVAM
EDERDİ; kusur hiçbir yerde görünmezdi.

## 🔴 PENCERE İKİ TARAFTA DA AYNIDIR

Yevmiye tarafı `entry_date` ile DÖNEMİN AYINA daraltılır. Aylık bir büyüklüğü
KÜMÜLATİF bir netle karşılaştıran bir mutabakat, veri tek aya sığdığı sürece
TUTAR ve fişi yanlış güne yazan kusuru GÖREMEZ (MU-3C'nin M4 mutantı).
Pencerenin GERÇEKTEN daralttığı `test_AYLIK_pencere_GERCEKTEN_daraltir`da
ayrıca çakılır.

## 🔴 MU-3D'NİN DERSİ: FIXTURE-KAPSAMLI MUTABAKAT GLOBAL KİMLİĞİ BEKÇİLEMEZ

Bir mutabakat testi yalnız kendi kurduğu satırları görür; yeni bir aile aynı
hesaba yazmaya başlayınca SESSİZ kalır. Bu yüzden KDV kimliği burada
bordronun VARLIĞINDA ayrıca ölçülür: bordro fişi `191`/`391`e dokunsaydı
`accounting.vat_return` ile yevmiye AYRIŞIRDI ve bunu MU-3B'nin kendi
mutabakatı GÖREMEZDİ (o kümede bordro YOKTUR).
"""

import datetime as _dt
from decimal import Decimal

from sqlalchemy import select

from app.modules.accounting.models import JournalEntry, JournalSourceType
from app.modules.accounting.vat_return import build_vat_return
from app.modules.payroll import payable, service
from app.modules.payroll.models import PayrollPeriodStatus
from tests.modules.payroll._mu3e import (
    GIDER_BACAGI,
    KOD_GIDER,
    KOD_PERSONEL_BORC,
    KOD_SGK_BORC,
    KOD_VERGI_BORC,
    SGK_BACAGI,
    TOPLAM_NET,
    VERGI_BACAGI,
    hesap_neti,
)

KOD_HES_KDV = "391"
KOD_IND_KDV = "191"


async def _onayla(db_session, kaydeden, donem) -> None:
    await service.compute_period(db_session, donem.id)
    while donem.status is not PayrollPeriodStatus.approved:
        await service.approve_period(db_session, kaydeden, donem.id)


def _ay(donem) -> tuple[int, int]:
    return (donem.year, donem.month)


async def test_MUTABAKAT_DORT_HESAP_ayri_ayri_tutar(db_session, donem, dort_tip, kaydeden) -> None:
    """🔴 BU DİLİMİN KABUL KAPISI — KIRILIMLI mutabakat, AYLIK pencerede.

    Pasif hesapların neti alacak yönlü, yani NEGATİFTİR (`Σ borç − Σ alacak`);
    işaret açıkça çevrilir ki bir yön hatası sessizce yutulmasın.
    """
    await _onayla(db_session, kaydeden, donem)
    ay = _ay(donem)

    assert await hesap_neti(db_session, KOD_GIDER, ay=ay) == GIDER_BACAGI
    assert -await hesap_neti(db_session, KOD_PERSONEL_BORC, ay=ay) == TOPLAM_NET
    assert -await hesap_neti(db_session, KOD_VERGI_BORC, ay=ay) == VERGI_BACAGI
    assert -await hesap_neti(db_session, KOD_SGK_BORC, ay=ay) == SGK_BACAGI
    # Küme GERÇEKTEN üç ayrı yükümlülük taşıyor: sıfır ↔ sıfır da "tutar"dı.
    assert TOPLAM_NET > 0
    assert VERGI_BACAGI > 0
    assert SGK_BACAGI > 0


async def test_MUTABAKAT_335_HAZINE_KARTIYLA_ayni_parayi_gosterir(
    db_session, donem, dort_tip, kaydeden
) -> None:
    """🔴 İKİ BAĞIMSIZ KAYNAK: `payable_net_sum` (SQL) ↔ `335` (yevmiye).

    `payroll.payable` hazine kartının (`upcoming-payments`) ödenecek bordro
    tutarını TEK SQL sorgusunda üretir; yevmiyedeki `335` bakiyesi ise
    Python'da kurulan fiş bacaklarından gelir. İkisi AYNI kararı (hangi satır
    ödenecek paraya girer) iki AYRI katmanda uygular ve bu yüzden gerçek bir
    çapraz kontroldür — biri `PAYABLE_LINE_STATUSES`ü SQL'de, öteki Python'da
    süzer.

    Ayrışsalardı hiçbir kolon farkı bunu ele vermezdi: ne dönemde bir toplam
    kolonu vardır, ne hesapta bir bakiye.
    """
    await _onayla(db_session, kaydeden, donem)

    # 🔴 ÜRÜNÜN KENDİ ALT SORGUSU kullanılır (`payable_net_totals_by_period`),
    #    çıplak `payable_net_sum()` DEĞİL: o, durum süzgecini TAŞIMAZ ve
    #    `excluded` taşeron satırının netini de toplar (ölçüldü: 32.800,00).
    #    Süzgeci testte elle yazmak, ölçülen kararın (hangi satır ödenecek
    #    paraya girer) İKİNCİ bir kopyasını üretir ve çapraz kontrolü
    #    anlamsızlaştırırdı.
    alt = payable.payable_net_totals_by_period()
    hazine_toplami = await db_session.scalar(
        select(alt.c.payable_net).where(alt.c.payroll_period_id == donem.id)
    )
    assert hazine_toplami == TOPLAM_NET, "kurulum beklenen neti üretmedi"
    assert -await hesap_neti(db_session, KOD_PERSONEL_BORC, ay=_ay(donem)) == hazine_toplami, (
        "HAZİNE KARTI ile YEVMİYE ayrıştı — ödenecek bordro parasının iki "
        "kaynağı farklı satır kümesi üzerinde tanımlı"
    )


async def test_MUTABAKAT_SGK_ISCI_KESINTISI_361_bacaginin_ICINDEDIR(
    db_session, donem, dort_tip, kaydeden
) -> None:
    """SGK ekranının işçi payları ile fişin `361` bacağı ARASINDAKİ bağ.

    🔴 İkisi EŞİT DEĞİLDİR ve olmamalıdır (kümeler farklı — taşeron; ayrıca
    `361` işveren payını da taşır). Ölçülen şey bir EŞİTLİK değil bir
    KAPSAMADIR: `361`, SGK ekranının SGK+işsizlik kalemlerinden küçük olamaz
    ve aradaki fark yalnız taşeron satırından gelebilir.

    Bu, bir "toplamlar tutuyor" testinin ölçemeyeceği şeyi ölçer: gelir
    vergisi ya da damga yanlışlıkla `361`e yazılsaydı bu iddia kırmızıya döner
    (fiş yine dengeli olurdu).
    """
    await _onayla(db_session, kaydeden, donem)
    ozet = await service.sgk_summary(db_session, donem.id)

    ekran_primi = (
        ozet.sgk_employee_total
        + ozet.unemployment_employee_total
        + ozet.sgk_employer_total
        + ozet.unemployment_employer_total
        + ozet.short_work_total
    )
    fis_361 = -await hesap_neti(db_session, KOD_SGK_BORC, ay=_ay(donem))

    assert fis_361 == SGK_BACAGI
    assert fis_361 < ekran_primi, (
        "`361` SGK ekranından KÜÇÜK değil — fişe taşeron satırı sızmış ya da "
        "prim DIŞI bir kalem (gelir vergisi / damga) `361`e yazılmış"
    )
    # Vergi kalemleri `361`e SIZMADI: `360` onları TAM taşıyor.
    assert -await hesap_neti(db_session, KOD_VERGI_BORC, ay=_ay(donem)) == ozet.income_tax_total


async def test_KDV_KIMLIGI_BORDRO_FISI_VARKEN_de_TUTAR(
    db_session, donem, dort_tip, kaydeden
) -> None:
    """🔴 MU-3D dersi — global bir kimlik, YENİ BİR AİLE gelince de tutmalıdır.

    Bordro KDV TAŞIMAZ. Bir gün `191`/`391` rolleri bu aileye tanımlanırsa
    `accounting.vat_return` (beyannameyi YALNIZ `invoices`tan türetir) ile
    yevmiye AYRIŞIR — ve MU-3B'nin kendi mutabakatı bunu GÖREMEZ, çünkü o
    kümede bordro YOKTUR.
    """
    await _onayla(db_session, kaydeden, donem)
    yil, ay = _ay(donem)
    beyan = await build_vat_return(db_session, year=yil, month=ay)

    assert beyan.calculated_vat == -await hesap_neti(db_session, KOD_HES_KDV, ay=(yil, ay))
    assert beyan.deductible_vat == await hesap_neti(db_session, KOD_IND_KDV, ay=(yil, ay))
    # Bordro fişi GERÇEKTEN yazıldı — sıfır ↔ sıfır da "tutar"dı.
    assert await hesap_neti(db_session, KOD_GIDER, ay=(yil, ay)) == GIDER_BACAGI
    assert beyan.calculated_vat == Decimal("0.00")
    assert beyan.deductible_vat == Decimal("0.00")


async def test_AYLIK_pencere_GERCEKTEN_daraltir(db_session, donem, dort_tip, kaydeden) -> None:
    """🔴 M4 MUTANT BEKÇİSİ — pencere bir no-op OLMAMALIDIR.

    Veri tek aya sığdığı sürece aylık ve kümülatif net AYNI çıkar; süzgeç
    kaldırılsa da yukarıdaki mutabakat testleri YEŞİL kalırdı. Burada fiş
    ELLE önceki aya taşınır ve iki pencerenin AYRIŞTIĞI çakılır.

    `period_year`/`period_month` de birlikte taşınır: `ck_journal_entries_
    period_matches_date` onları `entry_date` ile bağlar.
    """
    await _onayla(db_session, kaydeden, donem)
    yil, ay = _ay(donem)

    fis = (
        await db_session.execute(
            select(JournalEntry).where(
                JournalEntry.source_type == JournalSourceType.payroll_period,
                JournalEntry.source_id == donem.id,
            )
        )
    ).scalar_one()
    onceki = fis.entry_date.replace(day=1) - _dt.timedelta(days=1)
    fis.entry_date = onceki
    fis.period_year = onceki.year
    fis.period_month = onceki.month
    await db_session.flush()

    assert await hesap_neti(db_session, KOD_GIDER, ay=(yil, ay)) == Decimal("0.00"), (
        "AYLIK pencere DARALTMIYOR — mutabakat, fişi yanlış aya yazan kusuru göremez"
    )
    assert await hesap_neti(db_session, KOD_GIDER) == GIDER_BACAGI, (
        "kümülatif pencere de daralmış — süzgeç iki tarafa da sızmış"
    )
