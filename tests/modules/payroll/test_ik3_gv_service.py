"""IK3-GV T5 — kümülatif matrah SNAPSHOT'ı, yıl sınırları ve K4 sayacı.

`compute.py` saf motoru `test_ik3_gv_income_tax.py`de sınandı. Burası AKIŞTIR:
kümülatif tabanın nereden geldiği, yıl değişince ne olduğu, sırasız dönemde ne
olduğu ve override yolunun otomatik yolla aynı sayıyı üretip üretmediği.

## 🔴 K1 — SNAPSHOT, `SUM` DEĞİL

Gerekçe ÖLÇÜLDÜ: `create_period` ay sırasını HİÇ zorlamaz ve onaylanan dönem
geri alınamaz (`transitions.py` tek yönlü, DELETE ucu yok). `SUM` yolu
seçilseydi sonradan açılan bir ay, ÖNCEDEN ONAYLANMIŞ sonraki ayların vergisini
geriye dönük değiştirir ama o ayların `deduction_amount`ı eski değeri taşırdı →
ödenmiş bir dönemin vergisi kalıcı ve **sessizce** yanlış.
`test_ONAYLANMIS_ay_sonradan_acilan_ay_yuzunden_DEGISMEZ` bunun bekçisidir.
"""

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.modules.payroll import service
from app.modules.payroll.models import (
    IncomeKind,
    PayrollLine,
    PayrollLineStatus,
    PayrollMinimumWage,
    PayrollPeriod,
    PayrollPeriodStatus,
    PayrollTaxBracket,
)
from app.modules.payroll.tax_bracket_seed_data import (
    MINIMUM_WAGE_GROSS_2026,
    TAX_BRACKETS_2026_WAGE,
)
from app.modules.personnel.models import WageType

from .conftest import YIL

pytestmark = pytest.mark.asyncio

#: 100.000 brüt aylıkçı: SGK %14 = 14.000 · işsizlik %1 = 1.000 → matrah 85.000.
AYLIK_BRUT = Decimal("100000.00")
AYLIK_MATRAH = Decimal("85000.00")


async def _donem(db_session, year: int, month: int) -> PayrollPeriod:
    period = PayrollPeriod(year=year, month=month)
    db_session.add(period)
    await db_session.flush()
    return period


async def _tarife_ekle(db_session, year: int, dilimler=TAX_BRACKETS_2026_WAGE) -> None:
    db_session.add_all(
        [
            PayrollTaxBracket(
                year=year,
                income_kind=IncomeKind.wage,
                ordinal=o,
                upper_bound=u,
                rate_pct=r,
            )
            for o, u, r in dilimler
        ]
    )
    db_session.add(PayrollMinimumWage(year=year, gross_amount=MINIMUM_WAGE_GROSS_2026))
    await db_session.flush()


async def _satir(db_session, period: PayrollPeriod, personnel_id) -> PayrollLine:
    return (
        await db_session.execute(
            select(PayrollLine).where(
                PayrollLine.payroll_period_id == period.id,
                PayrollLine.personnel_id == personnel_id,
            )
        )
    ).scalar_one()


@pytest.fixture
async def aylikci(personel_fabrikasi):
    return await personel_fabrikasi(
        "Kümülatif Kişi", wage_type=WageType.monthly, wage_amount=AYLIK_BRUT
    )


# --------------------------------------------------------------------------- #
# Kümülatif zincir
# --------------------------------------------------------------------------- #


async def test_kumulatif_taban_AYDAN_AYA_BIRIKIR_ve_dilim_atlatir(
    db_session, oranlar, aylikci, puantaj_fabrikasi
):
    """🔴 Ocak %15'ten başlar; Mart'ta kümülatif 190.000 eşiğini KESER.

    | ay | kümülatif | ayın vergisi (istisna öncesi) | istisna | yazılan |
    |---|---|---|---|---|
    | 1 |  85.000 | 12.750 | 4.211,325 |  8.538,68 |
    | 2 | 170.000 | 12.750 | 4.211,325 |  8.538,68 |
    | 3 | 255.000 | 16.000 | 4.211,325 | 11.788,68 |

    Mart'ın Ocak'tan BÜYÜK olması dilimli motorun çalıştığının kanıtıdır: aynı
    brüt, aynı istisna, farklı vergi. Ay-bazlı naif bir hesap üç ayda da
    8.538,68 üretirdi.
    """
    beklenen = {
        1: Decimal("8538.68"),
        2: Decimal("8538.68"),
        3: Decimal("11788.68"),
    }
    for ay, vergi in beklenen.items():
        period = await _donem(db_session, YIL, ay)
        await puantaj_fabrikasi(aylikci, [1, 2, 3], month=ay)
        await service.compute_period(db_session, period.id)

        satir = await _satir(db_session, period, aylikci.id)
        assert satir.tax_base_amount == AYLIK_MATRAH, f"{ay}. ay matrahı"
        assert satir.cumulative_tax_base == AYLIK_MATRAH * ay, f"{ay}. ay kümülatifi"
        assert satir.income_tax_amount == vergi, f"{ay}. ay vergisi"

    assert beklenen[3] > beklenen[1], "kümülatif dilim atlaması GÖRÜNMÜYOR"


async def test_ILK_AY_sifirdan_baslar_devir_YOKTUR(db_session, oranlar, aylikci, puantaj_fabrikasi):
    """Kümülatif kaynağı olmayan ilk ay (Ocak / yıl ortası giriş) → 0'dan başlar.

    K7 devir kolonu AÇIKTIR ama DOLDURULMAZ (varsayılan 0): devir GV GT 311
    md.21/5 uyarınca çalışanın talebine bağlıdır, otomatik DEĞİLDİR.
    """
    period = await _donem(db_session, YIL, 5)
    await puantaj_fabrikasi(aylikci, [1, 2, 3], month=5)
    await service.compute_period(db_session, period.id)

    satir = await _satir(db_session, period, aylikci.id)
    assert satir.cumulative_tax_base == AYLIK_MATRAH


async def test_K7_DEVIR_matrahi_YALNIZ_kendi_yilinda_uygulanir(
    db_session, oranlar, aylikci, puantaj_fabrikasi
):
    """🔴 Devir BİR YILA aittir — yıl niteleyicisi fail-closed'dur.

    Yıl niteleyicisi olmasaydı 2026'da girilen bir devir 2027'de de uygulanır ve
    "31 Aralık → 1 Ocak sıfırlanır" kuralını SESSİZCE bozardı. Kolon hiçbir
    uçtan doldurulmaz; burada doğrudan yazılarak davranışı çakılır.
    """
    aylikci.opening_tax_base = Decimal("150000.00")
    aylikci.opening_tax_base_year = YIL
    await db_session.flush()

    ocak = await _donem(db_session, YIL, 1)
    await puantaj_fabrikasi(aylikci, [1, 2, 3], month=1)
    await service.compute_period(db_session, ocak.id)
    assert (await _satir(db_session, ocak, aylikci.id)).cumulative_tax_base == Decimal("235000.00")

    # Yıl BAŞKA olsaydı devir YOK sayılır.
    aylikci.opening_tax_base_year = YIL - 1
    await db_session.flush()
    subat = await _donem(db_session, YIL, 2)
    await puantaj_fabrikasi(aylikci, [1, 2, 3], month=2)
    await service.compute_period(db_session, subat.id)
    # Şubat'ın tabanı Ocak'ın SNAPSHOT'ıdır (235.000) — devir ikinci kez
    # eklenmez, ama yıl uyuşmadığı için Ocak'ın kendi devri de yeniden
    # okunmaz. Şubat = 235.000 + 85.000.
    assert (await _satir(db_session, subat, aylikci.id)).cumulative_tax_base == Decimal("320000.00")


async def test_31_ARALIK_1_OCAK_SIFIRLANIR(db_session, oranlar, aylikci, puantaj_fabrikasi):
    """🔴 Kümülatif matrah YILLIKTIR — 1 Ocak'ta sıfırdan başlar (GVK m.103).

    Sıfırlanmasaydı ikinci yılın Ocak'ı en üst dilimden vergilenir ve hata her
    yıl BÜYÜRDÜ. Sorgu `PayrollPeriod.year == year` ile sınırlıdır; sınır
    kaldırılırsa bu test kırmızıya döner.
    """
    aralik = await _donem(db_session, YIL, 12)
    await puantaj_fabrikasi(aylikci, [1, 2, 3], month=12)
    await service.compute_period(db_session, aralik.id)
    assert (await _satir(db_session, aralik, aylikci.id)).cumulative_tax_base == AYLIK_MATRAH

    await _tarife_ekle(db_session, YIL + 1)
    ocak = await _donem(db_session, YIL + 1, 1)
    await puantaj_fabrikasi(aylikci, [1, 2, 3], month=1, year=YIL + 1)
    # Sonraki yılın oran seti de gerekir (S2) — `payroll_rates` yıllıktır.
    db_session.add_all(
        [
            type(oran)(
                year=YIL + 1,
                personnel_source=oran.personnel_source,
                sgk_employee_pct=oran.sgk_employee_pct,
                unemployment_employee_pct=oran.unemployment_employee_pct,
                income_tax_pct=oran.income_tax_pct,
                stamp_tax_pct=oran.stamp_tax_pct,
                sgk_employer_pct=oran.sgk_employer_pct,
                unemployment_employer_pct=oran.unemployment_employer_pct,
                short_work_pct=oran.short_work_pct,
            )
            for oran in oranlar
        ]
    )
    await db_session.flush()
    await service.compute_period(db_session, ocak.id)

    assert (await _satir(db_session, ocak, aylikci.id)).cumulative_tax_base == AYLIK_MATRAH


async def test_2025_DONEMI_2026_TARIFESINI_KULLANMAZ(
    db_session, oranlar, aylikci, puantaj_fabrikasi
):
    """🔴 Tarife DÖNEMİN YILINA aittir, bugünün yılına değil (S2 emsali).

    2025'e KASTEN farklı bir tarife (tek dilim, %10) konur: 2026 tarifesi
    kullanılsaydı vergi 8.538,68 çıkardı, 2025 tarifesiyle 8.500,00 −
    2.807,55 istisna = **5.692,45**.
    """
    await _tarife_ekle(db_session, YIL - 1, dilimler=((1, None, Decimal("10.000")),))
    db_session.add_all(
        [
            type(oran)(
                year=YIL - 1,
                personnel_source=oran.personnel_source,
                sgk_employee_pct=oran.sgk_employee_pct,
                unemployment_employee_pct=oran.unemployment_employee_pct,
                income_tax_pct=oran.income_tax_pct,
                stamp_tax_pct=oran.stamp_tax_pct,
                sgk_employer_pct=oran.sgk_employer_pct,
                unemployment_employer_pct=oran.unemployment_employer_pct,
                short_work_pct=oran.short_work_pct,
            )
            for oran in oranlar
        ]
    )
    await db_session.flush()

    period = await _donem(db_session, YIL - 1, 1)
    await puantaj_fabrikasi(aylikci, [1, 2, 3], month=1, year=YIL - 1)
    await service.compute_period(db_session, period.id)

    satir = await _satir(db_session, period, aylikci.id)
    # 85.000 × %10 = 8.500,00 · istisna 28.075,50 × %10 = 2.807,55
    assert satir.income_tax_amount == Decimal("5692.45")


async def test_TARIFESI_OLMAYAN_YIL_satiri_UNCOMPUTED_birakir(
    db_session, oranlar, aylikci, puantaj_fabrikasi
):
    """🔴🔴 K3 VARSAYILAN YOLU, SERVİS katmanında (2027).

    Oran seti VAR (kopyalanır) ama tarife YOK. Satır `uncomputed` kalır ve
    **hiçbir para alanı yazılmaz** — 0 vergi ASLA basılmaz. Bu yol testsiz
    kalsaydı 2027'nin ilk bordrosu herkesi vergisiz hesaplardı.
    """
    db_session.add_all(
        [
            type(oran)(
                year=YIL + 1,
                personnel_source=oran.personnel_source,
                sgk_employee_pct=oran.sgk_employee_pct,
                unemployment_employee_pct=oran.unemployment_employee_pct,
                income_tax_pct=oran.income_tax_pct,
                stamp_tax_pct=oran.stamp_tax_pct,
                sgk_employer_pct=oran.sgk_employer_pct,
                unemployment_employer_pct=oran.unemployment_employer_pct,
                short_work_pct=oran.short_work_pct,
            )
            for oran in oranlar
        ]
    )
    await db_session.flush()

    period = await _donem(db_session, YIL + 1, 1)
    await puantaj_fabrikasi(aylikci, [1, 2, 3], month=1, year=YIL + 1)
    await service.compute_period(db_session, period.id)

    satir = await _satir(db_session, period, aylikci.id)
    assert satir.status is PayrollLineStatus.uncomputed
    assert satir.gross_amount is None
    assert satir.net_amount is None
    assert satir.income_tax_amount is None
    assert satir.deduction_amount is None


# --------------------------------------------------------------------------- #
# 🔴 K1'in asıl gerekçesi: SNAPSHOT donmuş dönemi KORUR
# --------------------------------------------------------------------------- #


async def test_ONAYLANMIS_ay_sonradan_acilan_ay_yuzunden_DEGISMEZ(
    db_session, oranlar, aylikci, puantaj_fabrikasi
):
    """🔴🔴 K1'in ÖLÇÜLMÜŞ gerekçesi (KK-8: geçmiş dönemler donmuş kalır).

    Temmuz önce açılıp hesaplanır ve ONAYLANIR; SONRA Mart açılıp hesaplanır.
    `SUM` yolu seçilseydi Temmuz'un tabanı artık başka bir sayı olurdu ama
    satırdaki `deduction_amount` eski değeri taşırdı ve ASLA düzeltilemezdi
    (`transitions.py` tek yönlü, DELETE ucu yok) → ödenmiş bir dönemin vergisi
    kalıcı ve SESSİZCE yanlış.

    Snapshot yolunda Temmuz'un üç vergi kolonu da OLDUĞU GİBİ kalır ve Mart
    kendi doğru tabanından (0'dan) hesaplanır.
    """
    temmuz = await _donem(db_session, YIL, 7)
    await puantaj_fabrikasi(aylikci, [1, 2, 3], month=7)
    await service.compute_period(db_session, temmuz.id)
    temmuz_satiri = await _satir(db_session, temmuz, aylikci.id)
    donmus = (
        temmuz_satiri.tax_base_amount,
        temmuz_satiri.cumulative_tax_base,
        temmuz_satiri.income_tax_amount,
        temmuz_satiri.deduction_amount,
    )
    temmuz.status = PayrollPeriodStatus.approved
    await db_session.flush()

    mart = await _donem(db_session, YIL, 3)
    await puantaj_fabrikasi(aylikci, [1, 2, 3], month=3)
    await service.compute_period(db_session, mart.id)

    await db_session.refresh(temmuz_satiri)
    assert (
        temmuz_satiri.tax_base_amount,
        temmuz_satiri.cumulative_tax_base,
        temmuz_satiri.income_tax_amount,
        temmuz_satiri.deduction_amount,
    ) == donmus, "onaylanmış Temmuz, sonradan açılan Mart yüzünden DEĞİŞTİ"
    assert (await _satir(db_session, mart, aylikci.id)).cumulative_tax_base == AYLIK_MATRAH


# --------------------------------------------------------------------------- #
# 🔴 K4 — sırasız dönem: fail-closed SAYAÇ
# --------------------------------------------------------------------------- #


async def test_K4_eksik_onceki_ay_SAYACTA_gorunur(db_session, oranlar, aylikci, puantaj_fabrikasi):
    """🔴 Mart tek başına hesaplanırsa Ocak+Şubat sayaçta GÖRÜNÜR (2).

    409 ile REDDEDİLMEZ (yıl ortasında sisteme geçişi imkânsız kılardı) ama
    SESSİZ DE GEÇİLMEZ: "aynı yeşil iki anlam taşır" — doğru sırayla
    hesaplanmış bir dönem ile sırasız hesaplanmış bir dönem ayırt edilebilir
    olmalıdır. Hesap YAPILIR: satır `pending`tir.
    """
    mart = await _donem(db_session, YIL, 3)
    await puantaj_fabrikasi(aylikci, [1, 2, 3], month=3)
    sonuc = await service.compute_period(db_session, mart.id)

    assert sonuc.missing_prior_period_count == 2
    assert (await _satir(db_session, mart, aylikci.id)).status is PayrollLineStatus.pending


async def test_K4_TASLAK_onceki_ay_da_EKSIK_sayilir(
    db_session, oranlar, aylikci, puantaj_fabrikasi
):
    """🔴 `draft` bir önceki ay, HİÇ AÇILMAMIŞ ay kadar tehlikelidir.

    Taslak dönemin satırları henüz hesaplanmamış olabilir; matrahı kümülatife
    girmemiştir. Yalnız "dönem var mı" diye bakan bir sayaç bu durumu SESSİZCE
    geçerdi.
    """
    await _donem(db_session, YIL, 1)  # `draft`
    subat = await _donem(db_session, YIL, 2)
    subat.status = PayrollPeriodStatus.pending_approval
    await db_session.flush()

    mart = await _donem(db_session, YIL, 3)
    await puantaj_fabrikasi(aylikci, [1, 2, 3], month=3)
    sonuc = await service.compute_period(db_session, mart.id)

    assert sonuc.missing_prior_period_count == 1  # yalnız Ocak (`draft`)


async def test_K4_OCAK_hicbir_zaman_eksik_saymaz(db_session, oranlar, aylikci, puantaj_fabrikasi):
    """Ocak'tan önce ay YOKTUR — sayaç 0'dır, uydurma bir uyarı üretilmez."""
    ocak = await _donem(db_session, YIL, 1)
    await puantaj_fabrikasi(aylikci, [1, 2, 3], month=1)
    sonuc = await service.compute_period(db_session, ocak.id)

    assert sonuc.missing_prior_period_count == 0


# --------------------------------------------------------------------------- #
# #18 — `is_overridden` sonrası kümülatif · override ↔ otomatik mutabakatı
# --------------------------------------------------------------------------- #


async def test_OVERRIDE_edilen_ayin_matrahi_SONRAKI_aya_TASINIR(
    db_session, oranlar, aylikci, puantaj_fabrikasi, kaydeden
):
    """🔴 Ayrışma noktası #18: elle düzeltilen brüt kümülatife GİRER Mİ?

    Ocak'ın brütü 100.000'den 200.000'e çekilir → matrahı 85.000'den 170.000'e
    çıkar. Şubat'ın tabanı Ocak'ın SNAPSHOT'ından okunduğu için 170.000'den
    devam etmelidir. Okunmasaydı Şubat sessizce eksik vergilenir ve kullanıcının
    kendi düzeltmesi hiçbir yere yansımazdı.
    """
    from app.modules.payroll import schemas

    ocak = await _donem(db_session, YIL, 1)
    await puantaj_fabrikasi(aylikci, [1, 2, 3], month=1)
    await service.compute_period(db_session, ocak.id)
    ocak_satiri = await _satir(db_session, ocak, aylikci.id)

    await service.update_line(
        db_session,
        kaydeden.id,
        ocak_satiri.id,
        schemas.PayrollLineUpdate(gross_amount=Decimal("200000.00")),
    )
    await db_session.refresh(ocak_satiri)
    assert ocak_satiri.cumulative_tax_base == Decimal("170000.00")

    subat = await _donem(db_session, YIL, 2)
    await puantaj_fabrikasi(aylikci, [1, 2, 3], month=2)
    await service.compute_period(db_session, subat.id)

    assert (await _satir(db_session, subat, aylikci.id)).cumulative_tax_base == Decimal("255000.00")


async def test_OVERRIDE_yolu_ile_OTOMATIK_yol_AYNI_SAYIYI_uretir(
    db_session, oranlar, personel_fabrikasi, puantaj_fabrikasi, kaydeden
):
    """🔴 T4 kabul şartı — `deduction_and_net`in İKİ çağıranı ayrışmamalıdır.

    İki kişi, aynı ay, aynı brüt: biri puantajdan otomatik hesaplanır, ötekinin
    brütü elle aynı değere çekilir. Dört vergi alanının DÖRDÜ de eşit olmalıdır.
    Override kendi bağlamını kursaydı (ör. ayı 1 varsayarak) istisna farklı
    çıkar ve elle düzeltilen satırlar zamanla ayrı bir rejime kayardı.
    """
    from app.modules.payroll import schemas

    otomatik = await personel_fabrikasi(
        "Otomatik", wage_type=WageType.monthly, wage_amount=AYLIK_BRUT
    )
    elle = await personel_fabrikasi("Elle", wage_type=WageType.monthly, wage_amount=Decimal("1.00"))
    period = await _donem(db_session, YIL, 7)
    await puantaj_fabrikasi(otomatik, [1, 2, 3], month=7)
    await puantaj_fabrikasi(elle, [1, 2, 3], month=7)
    await service.compute_period(db_session, period.id)

    elle_satiri = await _satir(db_session, period, elle.id)
    await service.update_line(
        db_session,
        kaydeden.id,
        elle_satiri.id,
        schemas.PayrollLineUpdate(gross_amount=AYLIK_BRUT),
    )
    await db_session.refresh(elle_satiri)
    otomatik_satiri = await _satir(db_session, period, otomatik.id)

    for alan in ("tax_base_amount", "cumulative_tax_base", "income_tax_amount", "net_amount"):
        assert getattr(elle_satiri, alan) == getattr(otomatik_satiri, alan), alan


async def test_TARIFESIZ_YILDA_override_422(
    db_session, oranlar, aylikci, puantaj_fabrikasi, kaydeden
):
    """🔴 K3 fail-closed override yolunda da geçerlidir.

    0 vergiyle "düzeltilmiş" bir satır yazmak, kullanıcının elle girdiği brütü
    VERGİSİZ ödemek olurdu. Oran seti eksikliğinin (`RATE_MISSING`) kardeşi ama
    AYRI bir kusur sınıfı ve ayrı bir mesaj.
    """
    from app.core.errors import PayrollValidationError
    from app.modules.payroll import guards, schemas

    db_session.add_all(
        [
            type(oran)(
                year=YIL + 1,
                personnel_source=oran.personnel_source,
                sgk_employee_pct=oran.sgk_employee_pct,
                unemployment_employee_pct=oran.unemployment_employee_pct,
                income_tax_pct=oran.income_tax_pct,
                stamp_tax_pct=oran.stamp_tax_pct,
                sgk_employer_pct=oran.sgk_employer_pct,
                unemployment_employer_pct=oran.unemployment_employer_pct,
                short_work_pct=oran.short_work_pct,
            )
            for oran in oranlar
        ]
    )
    await db_session.flush()
    period = await _donem(db_session, YIL + 1, 1)
    await puantaj_fabrikasi(aylikci, [1, 2, 3], month=1, year=YIL + 1)
    await service.compute_period(db_session, period.id)
    satir = await _satir(db_session, period, aylikci.id)

    with pytest.raises(PayrollValidationError) as hata:
        await service.update_line(
            db_session,
            kaydeden.id,
            satir.id,
            schemas.PayrollLineUpdate(gross_amount=Decimal("50000.00")),
        )
    assert str(hata.value) == guards.TAX_BRACKETS_MISSING
