"""İK-3 T3 — özet kartlarının İKİ AYRI TABANI (BY 69-93 + BG 44-49).

Bu dosyanın tek derdi şudur: **ödeme tabanı ile maliyet tabanı aynı küme
DEĞİLDİR** ve bunun testle kanıtlanması gerekir.

* **K2 (spec §6/2):** taşeron satırı `excluded`tır; `net`i "Toplam Net
  Ödenecek" / "Banka" / "Elden" kartlarına **KARIŞMAZ** ama **maliyete GİRER**
  (BY 186-189 satırı tabloda görünür). Emsal: P10'da kart tabanı=harcanan,
  kâr tabanı=bütçe — iki taban ayrı tutulur.
* **S4 (spec §6/3):** ücreti tanımsız personelin satırı `uncomputed`tır, brütü
  `null`dur; hiçbir toplama girmez ve **AYRI SAYILIR** (İK-2'nin
  `unknown_entitlement_personnel` emsali) — sessiz atlama yoktur (WORKFLOW §3).

Beklenen sayılar ORANLARDAN türetilir, **BY/BG tutarlarından DEĞİL**: spec S1
gereği açıkça yazılı oran kazanır, mockup tutarları temsilîdir ve kendi
aritmetiklerine uymaz (BG 892.000, SGK 82'nin EKSİK 148.800'üne dayanıyor —
bizim toplam maliyetimiz kasten DAHA BÜYÜK çıkar, spec §7).
"""

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.modules.payroll import payable, service, summary
from app.modules.payroll.models import PayrollLine, PayrollLineStatus
from tests.modules.payroll.conftest import satir_of

pytestmark = pytest.mark.asyncio


async def _ozet(session, donem):
    await service.compute_period(session, donem.id)
    lines = list(
        (
            await session.execute(
                select(PayrollLine).where(PayrollLine.payroll_period_id == donem.id)
            )
        )
        .scalars()
        .all()
    )
    rates = await service.rates_by_source(session, donem.year)
    return summary.build_period_summary(lines, rates)


async def test_odeme_kartlari_taseron_netini_ICERMEZ(db_session, donem, dort_tip):
    """🔴 K2 — taşeronun 6.681,69 neti ödeme kartlarının HİÇBİRİNE girmez.

    Ödenebilir taban: şirket 6.681,69 + serbest 10.000,00 + stajyer 7.500,00.
    Taşeron da hesabı YAPILMIŞ bir satırdır (BY 189: net 19.336 basılıdır) —
    yani toplamdan düşmesi "hesaplanamadı" değil, K2 kararıdır.
    """
    ozet = await _ozet(db_session, donem)

    assert ozet.net_total == Decimal("25150.00")
    assert ozet.net_personnel_count == 3
    assert ozet.bank_total == Decimal("25150.00")
    assert ozet.cash_total == Decimal("0.00")


async def test_maliyet_tabani_taseronu_ICERIR(db_session, donem, dort_tip):
    """🔴 K2'nin öteki yarısı — taşeron satırı MALİYETE girer (spec §2 K2).

    Brüt tabanı dört satırı da kapsar: 9.000 + 9.000 + 12.500 + 7.500 = 38.000.
    Taşeron çıkarılsaydı işveren maliyeti 9.000'lik brüt + primi kadar EKSİK
    görünürdü — ödeme tabanıyla maliyet tabanı aynı sanılırsa olan tam budur.
    """
    ozet = await _ozet(db_session, donem)

    assert ozet.gross_total == Decimal("38000.00")
    assert ozet.excluded_count == 1


async def test_toplam_maliyet_UC_isveren_kalemini_de_toplar(db_session, donem, dort_tip):
    """🔴 spec §7 — `toplam_maliyet = brüt + (SGK %20,5 + işsizlik %2 + kısa çalışma %1)`.

    Şirket + taşeron 4a rejiminde %23,5 işveren yükü taşır; serbest meslek ve
    stajyer setinde işveren oranları sıfırdır (S2).

        38.000,00 + (9.000 × %23,5) × 2 = 38.000,00 + 4.230,00 = 42.230,00

    Yalnız SGK işveren payı toplansaydı 38.000 + 3.690 = 41.690,00 çıkardı —
    **540,00 ₺ eksik**. BY 92'nin "SGK işveren payı dahil" etiketi mockup'tan
    alınır, HESAP spec'ten: etiket ile formül aynı şey değildir.
    """
    ozet = await _ozet(db_session, donem)

    assert ozet.total_employer_cost == Decimal("42230.00")
    # BG 47 "SGK İşveren" sütunu YALNIZ SGK işveren payıdır — toplam maliyetin
    # üç kaleminden biri; ikisi karıştırılmasın diye ayrı ayrı sınanır.
    assert ozet.sgk_employer_total == Decimal("3690.00")
    assert ozet.total_employer_cost != ozet.gross_total + ozet.sgk_employer_total


async def test_uncomputed_satir_toplamlara_girmez_ve_AYRI_sayilir(db_session, donem, dort_tip):
    """🔴 S4 fail-closed — `null` brüt toplama karışmaz, görünür bir sayaçla raporlanır."""
    ozet = await _ozet(db_session, donem)

    assert ozet.uncomputed_count == 1
    assert ozet.line_count == 5
    # Ödenebilir + hesaplanamayan + dışlanan = tüm satırlar; hiçbiri sessizce kaybolmaz.
    assert ozet.net_personnel_count + ozet.uncomputed_count + ozet.excluded_count == ozet.line_count


async def test_banka_elden_yuzdeleri_NET_uzerinden_hesaplanir(db_session, donem, dort_tip):
    """BY 79/87 yüzdeleri (%71,5 · %28,5) ödeme tabanının PAYIDIR, brütün değil."""
    ozet = await _ozet(db_session, donem)

    assert ozet.bank_pct == Decimal("100.0")
    assert ozet.cash_pct == Decimal("0.0")
    assert ozet.bank_personnel_count == 3
    assert ozet.cash_personnel_count == 0


async def test_odenebilir_satir_yoksa_yuzde_UYDURULMAZ(db_session, donem, oranlar):
    """Ödeme tabanı boşken yüzde `null`dur — 0 basmak "hepsi banka" yalanı olurdu."""
    ozet = await _ozet(db_session, donem)

    assert ozet.net_total == Decimal("0.00")
    assert ozet.bank_pct is None
    assert ozet.cash_pct is None


async def test_orani_kaybolan_satirin_maliyeti_UYDURULMAZ(db_session, donem, oranlar, dort_tip):
    """Oran seti pasifleşirse maliyet BİLİNMEZ olur — 0 sayılmaz, ayrı sayılır.

    SA kanonunun kardeşi (fail-closed): hesaplanmış bir brüt var ama işveren
    yükü artık okunamıyorsa toplama 0 yazmak maliyeti sistematik olarak KÜÇÜK
    gösterirdi. Satır maliyet toplamından düşer ve `unknown_cost_count`ta
    görünür.
    """
    await service.compute_period(db_session, donem.id)
    for rate in oranlar:
        rate.is_active = False
    await db_session.flush()

    lines = list(
        (
            await db_session.execute(
                select(PayrollLine).where(PayrollLine.payroll_period_id == donem.id)
            )
        )
        .scalars()
        .all()
    )
    rates = await service.rates_by_source(db_session, donem.year)
    ozet = summary.build_period_summary(lines, rates)

    assert ozet.unknown_cost_count == 4
    assert ozet.total_employer_cost == Decimal("0.00")
    assert ozet.sgk_employer_total == Decimal("0.00")


# --- TB8: SÜRÜKLENME BEKÇİSİ ----------------------------------------------


async def test_SQL_ve_PYTHON_odenebilir_toplami_AYRISMAZ(db_session, donem, dort_tip):
    """🔴 İKİ GERÇEK KAYNAK BEKÇİSİ — `payable.py` (SQL) ile `summary.py` (Python).

    Ödenebilir net toplam artık İKİ yerden okunuyor ve ikisi de para basıyor:

    * `summary.build_period_summary(...).net_total` → bordro ekranının BY 69
      kartı (satırlar bellekte, Python'da toplanır);
    * `payable.payable_net_totals_by_period()` → hazine kartının
      `upcoming-payments` satırı (dönem sayısından bağımsız TEK gruplu sorgu;
      dönem başına satır çekmek `test_N_ARTI_1_YAPMAZ`ın ölçtüğü N+1'dir).

    Kural TEK cümledir: **AYNI veri üzerinde AYNI sayı.** Ayrışırlarsa hiçbir
    kolon farkı ele vermez (toplam saklanmaz, ikisi de türevdir) ve kullanıcı
    aynı dönem için hazinede başka, bordroda başka bir tutar görür. Küme zaten
    `PAYABLE_LINE_STATUSES`ten İTHAL edilir; bu bekçi ithalin sürdüğünü ve iki
    yolun aynı satırları saydığını ÖLÇER.

    Veri gerçektir (`compute_period` üretir) ve BEŞ satır durumunun HEPSİNİ
    taşır: `compute` `pending`/`uncomputed`/`excluded` üretir, kalan ikisi
    (`approved`/`paid`) elle çakılır. Dört durum ölçülseydi `paid` satırı SQL
    tarafında unutulan bir uygulama bu bekçiden geçerdi.

    Beklenen toplam AÇIKÇA yazılır: yalnız eşitlik iddia edilseydi iki yol da
    0,00 dönerek testi geçerdi (sahte yeşil).
    """
    await service.compute_period(db_session, donem.id)
    satirlar = list(
        (
            await db_session.execute(
                select(PayrollLine).where(PayrollLine.payroll_period_id == donem.id)
            )
        )
        .scalars()
        .all()
    )
    satir_of(satirlar, dort_tip["sirket"].id).status = PayrollLineStatus.approved
    satir_of(satirlar, dort_tip["serbest"].id).status = PayrollLineStatus.paid
    await db_session.flush()
    assert {satir.status for satir in satirlar} == set(PayrollLineStatus)

    odenebilir = payable.payable_net_totals_by_period()
    sql_toplam = (
        await db_session.execute(
            select(odenebilir.c.payable_net).where(odenebilir.c.payroll_period_id == donem.id)
        )
    ).scalar_one()

    rates = await service.rates_by_source(db_session, donem.year)
    python_toplam = summary.build_period_summary(satirlar, rates).net_total

    # şirket 7.650,00 (approved) + serbest 10.000,00 (paid) + stajyer 7.500,00 (pending)
    # — taşeron `excluded` ve ücretsiz `uncomputed` İKİ YOLDA DA dışarıdadır.
    assert python_toplam == Decimal("25150.00")
    assert Decimal(sql_toplam) == python_toplam
