"""🔴 MU-3E ÇİFT SAYIM BEKÇİSİ — taşeron satırı bordro fişine GİRMEZ.

## Kusurun şekli

`payroll_lines`ta taşeron işçisinin satırı VARDIR ve tutarları HESAPLANIR
(BY 186-189 onları tabloda gösterir), ama durumu `excluded`tır: ücreti
bordrodan ÖDENMEZ, taşerona **hakediş üzerinden** ödenir (K2). O hakediş
**MU-3D'de ZATEN FİŞLENİYOR** (`subcontractor_progress_payment` → `740` gider
+ `320` cari).

`summary.py` iki taban tanımlar ve MALİYET tabanı `excluded` satırı İÇERİR.
Bordro fişi o tabandan kurulsaydı aynı emek İKİ KEZ gider yazılırdı: bir kez
`730`e (bordrodan), bir kez `740`a (hakedişten).

🔴 **Ve fiş yine DENGELİ olurdu.** Taşeronun brütü de neti de kesintisi de
tutarlıdır; borç ve alacak yine eşitlenir ve mizan DOĞRU görünür. Bu yüzden
bekçi sonucun kendisini değil, **DEĞİŞMEMESİ gerekeni** ölçer — MU-3C'nin
`test_ODEME_FISI_GIDER_ve_HASILAT_hesaplarina_DOKUNMAZ` deseninin kardeşi.

## Neden SGK tabanı da kullanılamaz

`sgk.build_sgk_summary` taşeron satırını BİLEREK içerir ve bu DOĞRUDUR: SGK
bildirimi bir ÖDEME değil bir BİLDİRİMDİR. Doğru bir SGK bildirimi ile doğru
bir yevmiye fişi **aynı küme üzerinde tanımlı değildir** ve bu fark burada
SAYIYLA çakılır: iki yüzey arasındaki sapma bir kusur değil, bir OLGUDUR ve
sessizce kapanırsa çift sayım geri gelir.
"""

from decimal import Decimal

from app.modules.payroll import service
from app.modules.payroll.models import PayrollLineStatus, PayrollPeriodStatus
from tests.modules.payroll._mu3e import (
    GIDER_BACAGI,
    KOD_GIDER,
    KOD_PERSONEL_BORC,
    TASERON_BRUT,
    TOPLAM_BRUT,
    TOPLAM_NET,
    bordro_fisi,
    hesap_neti,
    satirlar,
)

#: 🔴 Taşeron satırı ŞİRKET satırıyla AYNI oran setindedir (`SGK_4A` — brütü de
#: aynı, 9.000). İşveren yükü bu yüzden BİREBİR aynıdır: 1.845 + 180 + 90.
TASERON_ISVEREN_YUKU = Decimal("2115.00")

#: 🔴 MALİYET tabanı seçilseydi `730` bu olurdu. Sabit ELLE yazılır ve üründen
#: türetilmez: `summary.build_period_summary` çağrılsaydı test, kaçındığı
#: kusuru üreten kodun kendisine sorardı.
YANLIS_GIDER_BACAGI = GIDER_BACAGI + TASERON_BRUT + TASERON_ISVEREN_YUKU

#: Taşeron hakedişinin gider hesabı (MU-3D). Bordro ORAYA HİÇ yazmamalıdır.
KOD_TASERON_GIDERI = "740"


async def _onayla(db_session, kaydeden, donem) -> None:
    await service.compute_period(db_session, donem.id)
    while donem.status is not PayrollPeriodStatus.approved:
        await service.approve_period(db_session, kaydeden, donem.id)


async def test_TASERON_satiri_GIDER_bacagina_GIRMEZ(db_session, donem, dort_tip, kaydeden) -> None:
    """🔴 KABUL KAPISI — `730`, MALİYET tabanı kadar DEĞİL ÖDEME tabanı kadardır.

    İki iddia birlikte durur: doğru sayı TUTAR **ve** yanlış sayı TUTMAZ.
    Yalnız birincisi yazılsaydı `YANLIS_GIDER_BACAGI` sabiti bir gün doğru
    sayıya eşitlenebilir ve kimse fark etmezdi.
    """
    await _onayla(db_session, kaydeden, donem)

    assert await hesap_neti(db_session, KOD_GIDER) == GIDER_BACAGI
    assert GIDER_BACAGI != YANLIS_GIDER_BACAGI, (
        "iki taban aynı sayıyı üretiyor — kurulumda `excluded` satır YOK, "
        "bekçi hiçbir şeyi ölçmüyor"
    )
    assert await hesap_neti(db_session, KOD_GIDER) != YANLIS_GIDER_BACAGI, (
        f"ÇİFT SAYIM: `{KOD_GIDER}` MALİYET tabanından kurulmuş — taşeron emeği "
        f"hem bordrodan hem taşeron hakedişinden ({KOD_TASERON_GIDERI}) gider yazar"
    )


async def test_BORDRO_FISI_TASERON_GIDER_hesabina_DOKUNMAZ(
    db_session, donem, dort_tip, kaydeden
) -> None:
    """🔴 Bordro `740`a HİÇ yazmaz — o hesap taşeron hakedişinindir (MU-3D).

    Kurulumda taşeron satırı GERÇEKTEN vardır (aşağıda çakılır), yani bu iddia
    boş bir kümede kolayca yeşil kalmaz.
    """
    await _onayla(db_session, kaydeden, donem)

    taseron_satirlari = [
        satir
        for satir in await satirlar(db_session, donem.id)
        if satir.status is PayrollLineStatus.excluded
    ]
    assert taseron_satirlari, "kurulumda `excluded` satır YOK — bekçi ölçmüyor"
    assert sum(satir.gross_amount for satir in taseron_satirlari) == TASERON_BRUT

    assert await hesap_neti(db_session, KOD_TASERON_GIDERI) == Decimal("0.00"), (
        f"bordro fişi `{KOD_TASERON_GIDERI}` hesabına yazdı — taşeron maliyeti "
        "hakediş fişiyle ÇİFT SAYILIR"
    )


async def test_PERSONELE_BORC_TASERONU_ICERMEZ(db_session, donem, dort_tip, kaydeden) -> None:
    """`335` yalnız ÖDENECEK neti taşır.

    Taşeronun neti buraya girseydi şirket, hiç ödemeyeceği bir personel borcu
    taşır ve bilanço yükümlülüğü şişerdi — bir hakediş borcu (`320`) ile bir
    personel borcu (`335`) aynı anda aynı emeği gösterirdi.
    """
    await _onayla(db_session, kaydeden, donem)
    entry = await bordro_fisi(db_session, donem.id)
    assert entry is not None

    assert -await hesap_neti(db_session, KOD_PERSONEL_BORC) == TOPLAM_NET


async def test_SGK_TABANI_ile_FIS_TABANI_AYRISIR_ve_FARK_TASERONDUR(
    db_session, donem, dort_tip, kaydeden
) -> None:
    """🔴 İKİ YÜZEY, İKİ KÜME — ve fark TAM OLARAK taşeron brütüdür.

    SGK ekranı bir BİLDİRİMDİR ve taşeronu sayar; yevmiye fişi bir ÖDEME
    tahakkukudur ve saymaz. Bu sapma bir kusur DEĞİLDİR ve sessizce
    kapatılırsa çift sayım geri gelir — bu yüzden farkın BÜYÜKLÜĞÜ çakılır,
    yalnız "eşit değil" denmez.
    """
    await _onayla(db_session, kaydeden, donem)
    ozet = await service.sgk_summary(db_session, donem.id)

    assert ozet.sgk_base_total == TOPLAM_BRUT + TASERON_BRUT
    assert ozet.sgk_base_total - TOPLAM_BRUT == TASERON_BRUT, (
        "SGK tabanı ile fiş tabanı arasındaki fark taşeron brütü DEĞİL — "
        "iki yüzeyden biri kümesini değiştirmiş"
    )
    # Fişin tabanı SGK'nınkinden KÜÇÜKTÜR; tersi olsaydı fiş, bildirilmeyen
    # bir emeği gider yazıyor demektir.
    assert TOPLAM_BRUT < ozet.sgk_base_total
