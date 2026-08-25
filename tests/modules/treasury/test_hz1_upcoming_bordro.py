"""HZ-1 T5 — üçüncü kaynak: BORDRO dönemi (TB8).

`test_hz1_upcoming.py`den TAŞINDI (800 satır tavanı); testler ve iddialar aynı.
Paylaşılan yardımcılar `_hz1_upcoming.py`dedir.
"""

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.payroll.models import PayrollLineStatus, PayrollPeriodStatus
from tests.modules.treasury._hz1_upcoming import (
    _bordro,
    _gun,
    _liste,
)

pytestmark = pytest.mark.asyncio


# --- Kaynak 3: bordro (TB8) ------------------------------------------------
#
# E9:116-119 ÜÇÜNCÜ satırı çizer: `Bordro – Temmuz` · `20 Temmuz · 3 gün kaldı`
# · `₺892.000`. Bu kaynağın "vade kolonu yok" gerekçesiyle üretilmemesi ÖLÇÜLEREK
# ÇÜRÜTÜLDÜ: `payroll_periods.payment_due_date` (`payroll/models.py:150`) VARDIR.
#
# 🔴 **ŞEF KARARI: listeye YALNIZ `status == approved` dönem girer.** Gerekçe
# ölçülmüştür: `payment_due_date` `draft`/`pending_approval`da serbestçe
# değişir, `approved`/`paid`de **409** verir (`payroll/router.py:173` →
# `service.update_period`). Yani vade ancak `approved`ta bir TAAHHÜTTÜR. Aynı
# şart iki mevcut kaynakta da vardır (`InvoiceStatus.approved` ·
# `SubcontractorPaymentStatus.approved`) — bu üçüncü kaynak için icat edilmiş
# bir kural DEĞİLDİR.
#
# 🔴 **Tutar KOLON DEĞİL TÜREVDİR** ve tek kaynağı `payroll/summary.py:111`dir:
# `Σ net_amount`, yalnız `PAYABLE_LINE_STATUSES` (`pending`/`approved`/`paid`)
# ve `net_amount IS NOT NULL`. `uncomputed` (S4) ve `excluded` (K2) KASTEN
# dışarıdadır.
# ---------------------------------------------------------------------------


async def test_onayli_bordro_donemi_listelenir(
    client: AsyncClient, seeded_db: AsyncSession, admin_headers, bordro_donemi_fabrikasi
) -> None:
    """🔴 E9:117 `Bordro – Temmuz` satırının kaynağı — BEŞ alanın HEPSİ çakılır.

    * `source_id` DÖNEMİN kimliğidir (satırın değil): ekranın tıklayacağı kayıt
      dönemdir, bordro satırı personel mahremiyeti taşır ve karta girmez.
    * `counterparty` **`None`**dır: E9:117 bir karşı taraf adı ÇİZMEZ ("Bordro –
      Temmuz"), oysa fatura satırı "Yılmaz Elektrik" basar. Buraya "Personel" ya
      da şirket adı gibi bir dolgu yazmak, mockup'ta olmayan bir kayıt adı
      uydurmak olurdu.
    * `document_no` `"2026-07"`dur, **"Temmuz" DEĞİL**: sunucu çeviri/biçim
      kararı ÜRETMEZ (`UpcomingPaymentItem` docstring kanonu) — ay adını
      istemci `source_type` ile birlikte kurar.
    * `amount` ÜÇ ödenebilir satırın TOPLAMIDIR (400.000 + 300.000 + 192.000):
      tek satırla ölçülseydi toplamanın kendisi hiç sınanmamış olurdu ve
      "ilk satırın netini bas" gibi bir uygulama testi geçerdi.
    """
    donem = await bordro_donemi_fabrikasi(
        year=2026,
        month=7,
        payment_due_date=_gun(3),
        status=PayrollPeriodStatus.approved,
        lines=(
            (PayrollLineStatus.pending, "400000.00"),
            (PayrollLineStatus.approved, "300000.00"),
            (PayrollLineStatus.paid, "192000.00"),
        ),
    )
    items = await _liste(client, admin_headers)
    bordro = _bordro(items)
    assert len(bordro) == 1, items
    satir = bordro[0]
    assert satir["source_id"] == str(donem.id)
    assert satir["counterparty"] is None
    assert satir["document_no"] == "2026-07"
    assert satir["due_date"] == _gun(3).isoformat()
    assert satir["days_remaining"] == 3
    assert Decimal(satir["amount"]) == Decimal("892000.00")


async def test_vadesiz_bordro_donemi_LISTELENMEZ(
    client: AsyncClient, seeded_db: AsyncSession, admin_headers, bordro_donemi_fabrikasi
) -> None:
    """🔴 NULL-EŞİK / fail-closed (SA kanonu): vadesi YOK = pencereye giremez.

    `payment_due_date` NULL bir `approved` dönem gerçektir — alan nullable'dır
    ve BY 63'te bilgi alanıdır, geçiş kapısı değildir. Bugün varsayılsaydı
    vadesi hiç girilmemiş her dönem listenin EN ÜSTÜNDE, en acil sırada
    görünürdü (vadesiz faturanın kuralıyla birebir aynı).

    Yanına VADELİ ikinci bir dönem konur: iddia "hiç bordro satırı yok"tan
    güçlüdür — süzgecin doğru olanı GEÇİRDİĞİ de aynı anda ölçülür (K1.1).
    """
    await bordro_donemi_fabrikasi(
        year=2026,
        month=6,
        payment_due_date=None,
        lines=((PayrollLineStatus.approved, "500000.00"),),
    )
    vadeli = await bordro_donemi_fabrikasi(
        year=2026, month=7, payment_due_date=_gun(2), lines=((PayrollLineStatus.approved, "1.00"),)
    )
    bordro = _bordro(await _liste(client, admin_headers))
    assert [satir["source_id"] for satir in bordro] == [str(vadeli.id)]


async def test_vadesi_gecmis_bordro_LISTELENMEZ(
    client: AsyncClient, seeded_db: AsyncSession, admin_headers, bordro_donemi_fabrikasi
) -> None:
    """Pencerenin alt sınırı BUGÜNdür → `days_remaining` bordroda da negatif olmaz.

    Geçmiş içeri alınsaydı alt sınır SINIRSIZ olurdu: yıllar önce ödenmemiş
    (ama `paid`e geçirilmemiş) her dönem "yaklaşan" sayılırdı.
    """
    await bordro_donemi_fabrikasi(year=2026, month=6, payment_due_date=_gun(-1))
    pencerede = await bordro_donemi_fabrikasi(year=2026, month=7, payment_due_date=_gun(1))
    bordro = _bordro(await _liste(client, admin_headers))
    assert [satir["source_id"] for satir in bordro] == [str(pencerede.id)]
    assert bordro[0]["days_remaining"] == 1


@pytest.mark.parametrize(
    ("offset", "iceride"),
    [(-1, False), (0, True), (7, True), (8, False)],
)
async def test_bordro_pencere_sinirlari(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers,
    bordro_donemi_fabrikasi,
    offset: int,
    iceride: bool,
) -> None:
    """Sınır günleri AÇIKÇA sınanır: `bugün` ve `bugün+days` İÇERİDE, taşan DIŞARIDA.

    Fatura kaynağının sınır testinin birebir kardeşidir. `>` yerine `>=` (ya da
    tersi) yazan bir uygulama yalnız sınır GÜNÜNDE hatalıdır ve sınır sınanmazsa
    kusur ayda bir gün, sessizce ortaya çıkardı (WORKFLOW "pencere sınırı testsiz
    kalır" kanonu).

    🔴 K1.1: DIŞARIDA beklenen iki hâl ("sayı 0 olsun") kaynak henüz hiç yokken
    de geçerdi. Bu yüzden her turda pencerenin İÇİNDE bir KONTROL dönemi durur
    ve iddia beklenen KİMLİK LİSTESİ üzerinden kurulur — dört tur da bugün
    kırmızıdır ve dördü de gerçekten bir şey bekçiler.
    """
    kontrol = await bordro_donemi_fabrikasi(year=2026, month=1, payment_due_date=_gun(1))
    sinir = await bordro_donemi_fabrikasi(year=2026, month=2, payment_due_date=_gun(offset))
    beklenen = [str(kontrol.id), str(sinir.id)] if iceride else [str(kontrol.id)]
    bordro = _bordro(await _liste(client, admin_headers))
    assert sorted(satir["source_id"] for satir in bordro) == sorted(beklenen)


async def test_ODENMIS_bordro_donemi_LISTELENMEZ(
    client: AsyncClient, seeded_db: AsyncSession, admin_headers, bordro_donemi_fabrikasi
) -> None:
    """🔴 `paid` dönemin borcu KAPANMIŞTIR — vadesi pencerede olsa bile girmez.

    Çıkarılmasaydı ödenmiş her bordro, vadesi geçene kadar listede kalır ve
    nakit ihtiyacını ödenmiş bir parayla şişirirdi (`paid` hakedişin kuralıyla
    aynı). Yanında `approved` bir dönem durur ki iddia gelen satırın KİMLİĞİNE
    kadar inebilsin.
    """
    await bordro_donemi_fabrikasi(
        year=2026, month=6, status=PayrollPeriodStatus.paid, payment_due_date=_gun(2)
    )
    onayli = await bordro_donemi_fabrikasi(
        year=2026, month=7, status=PayrollPeriodStatus.approved, payment_due_date=_gun(4)
    )
    bordro = _bordro(await _liste(client, admin_headers))
    assert len(bordro) == 1
    assert bordro[0]["source_id"] == str(onayli.id)


@pytest.mark.parametrize(
    "status", [PayrollPeriodStatus.draft, PayrollPeriodStatus.pending_approval]
)
async def test_TAAHHUT_EDILMEMIS_bordro_donemi_LISTELENMEZ(
    client: AsyncClient, seeded_db: AsyncSession, admin_headers, bordro_donemi_fabrikasi, status
) -> None:
    """🔴 ŞEF KARARI — vade ancak `approved`ta bir TAAHHÜTTÜR. Gerekçe ÖLÇÜLDÜ:

    `payroll/router.py:173` → `service.update_period` `payment_due_date`i
    `draft`/`pending_approval`da serbestçe değiştirir ve `approved`/`paid`de
    **409** verir. Yani onay öncesi vade her an kayabilir; kart onu basarsa
    ekran, hiç kimsenin taahhüt etmediği bir güne "3 gün kaldı" yazar.

    İkinci gerekçe TUTARDADIR: `draft` dönemde satırlar `uncomputed` olabilir ve
    `compute` yeniden koşarak netleri baştan yazabilir — o hâlde tutar da bir
    taahhüt değildir.

    Üçüncüsü EMSALDİR: iki mevcut kaynak da `approved` şartı taşır
    (`InvoiceStatus.approved` · `SubcontractorPaymentStatus.approved`) — bu şart
    bordro için İCAT EDİLMEMİŞTİR.
    """
    await bordro_donemi_fabrikasi(year=2026, month=6, status=status, payment_due_date=_gun(2))
    onayli = await bordro_donemi_fabrikasi(
        year=2026, month=7, status=PayrollPeriodStatus.approved, payment_due_date=_gun(4)
    )
    bordro = _bordro(await _liste(client, admin_headers))
    assert [satir["source_id"] for satir in bordro] == [str(onayli.id)]


async def test_tutar_YALNIZ_odenebilir_satirlarin_toplami(
    client: AsyncClient, seeded_db: AsyncSession, admin_headers, bordro_donemi_fabrikasi
) -> None:
    """🔴 ÇİFT SAYIM KAPISININ BORDRO HÂLİ — `excluded` satır bordrodan ÖDENMEZ.

    Küme `payroll/summary.py:45`ten OKUNUR, tahmin edilmez:
    `PAYABLE_LINE_STATUSES = {pending, approved, paid}`.

    * `uncomputed` (S4): ücreti tanımsız personelin `net`i **`null`**dur —
      "0 ödenecek" ile "hesaplanamadı" aynı şey değildir, satır hiçbir toplama
      girmez.
    * `excluded` (K2): TAŞERON personelinin satırıdır. Neti bordrodan DEĞİL,
      taşeron HAKEDİŞİNDEN ödenir — bu uçta hakediş kaynağı da listelendiği için
      toplama katılsaydı aynı para İKİ KEZ sayılırdı. Tutarı bilerek **999,00**
      gibi ayırt edici bir sayıdır: 100/200/300 ile aynı büyüklükte olsaydı
      yanlış toplam başka bir yanlış toplamla maskelenebilirdi.

    Beklenen: 100 + 200 + 300 = **600,00** (999 ve `null` DIŞARIDA).
    """
    await bordro_donemi_fabrikasi(
        year=2026,
        month=7,
        payment_due_date=_gun(3),
        lines=(
            (PayrollLineStatus.pending, "100.00"),
            (PayrollLineStatus.approved, "200.00"),
            (PayrollLineStatus.paid, "300.00"),
            (PayrollLineStatus.uncomputed, None),
            (PayrollLineStatus.excluded, "999.00"),
        ),
    )
    bordro = _bordro(await _liste(client, admin_headers))
    assert len(bordro) == 1
    assert Decimal(bordro[0]["amount"]) == Decimal("600.00")


@pytest.mark.parametrize(
    ("lines", "ad"),
    [
        (
            (
                (PayrollLineStatus.uncomputed, None),
                (PayrollLineStatus.excluded, "999.00"),
            ),
            "yalniz_odenmeyen_satirlar",
        ),
        ((), "hic_satir_yok"),
    ],
)
async def test_odenebilir_toplami_SIFIR_olan_donem_LISTELENMEZ(
    client: AsyncClient, seeded_db: AsyncSession, admin_headers, bordro_donemi_fabrikasi, lines, ad
) -> None:
    """Ödenebilir toplamı 0 olan dönem GÜRÜLTÜDÜR — faturanın `kalan > 0` kardeşi.

    "₺0 · 3 gün kaldı" satırı kullanıcıya ödenecek bir para varmış gibi görünür,
    tıklanır ve hiçbir şey bulunmaz. İki hâl de ölçülür: yalnız ödenmeyen
    satırlar (`uncomputed`/`excluded`) ve HİÇ satır olmaması (dönem açılmış ama
    `compute` hiç koşmamış).

    Yanında ödenebilir bir dönem durur: iddia böylece "bordro kaynağı hiç
    üretilmiyor" ile karışmaz (K1.1).
    """
    await bordro_donemi_fabrikasi(year=2026, month=6, payment_due_date=_gun(2), lines=lines)
    dolu = await bordro_donemi_fabrikasi(
        year=2026,
        month=7,
        payment_due_date=_gun(4),
        lines=((PayrollLineStatus.approved, "10.00"),),
    )
    bordro = _bordro(await _liste(client, admin_headers))
    assert [satir["source_id"] for satir in bordro] == [str(dolu.id)], ad
