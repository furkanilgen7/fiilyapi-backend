"""HZ-1 T5 — `GET /treasury/upcoming-payments` (spec §4 uç 9, E9:109-125).

Bu uç HİÇBİR ŞEY YAZMAZ; bütün riski **hangi satırın listeye girdiği** ve
**kimin göreceğidir**. Dört sınıf kusur ölçülür:

1. **KAYNAK SEÇİMİ (K9).** Üç kaynak çizilidir ve TB8'den beri ÜÇÜ DE üretilir
   (fatura · taşeron hakedişi · bordro dönemi). Yanlış durumdaki
   (taslak/ihtilaflı/ödenmiş) ya da tam ödenmiş bir evrakın listeye sızması
   ekranda "ödenecek" görünen ama ödenmeyecek bir para üretir. Bordroda ek
   olarak vadenin TAAHHÜT olup olmadığı ölçülür: `payment_due_date` yalnız
   `approved` dönemde kilitlidir.
2. **PENCERE.** `days` bir SINIRDIR: tavanı aşan istek sessizce kırpılırsa
   kullanıcı 90 gün ister, 90 gün gördüğünü sanır. Sınır günleri (bugün ·
   bugün+`days` · bugün+`days`+1) ayrı ayrı sınanır.
3. **KAPSAM (IDOR).** Hesap şirket genelidir (K3) ama fatura/hakediş KAYNAKLARI
   proje kapsamı taşır. Süzgeç düşerse `treasury=_V` olan proje müdürü,
   göremediği projenin karşı tarafını ve tutarını okur. Taşıyıcı
   `kapsamli_muhasebe_headers`tir — `admin_headers` (`projects=_A`) süzgeci
   ATLADIĞI için sızıntıyı göstermez. Bordronun kapsamı AYRIDIR (`project_id`
   kolonu yoktur): kapı `payroll` iznidir ve taşıyıcısı `pm_headers`tır —
   `project_manager` bu ucu okur (`treasury=_V`) ama `payroll=_N`dir.
4. **N+1.** Üç kaynağın 1'er satırı ile 10'ar satırının (3 → 30 satır) SORGU
   SAYISI ölçülür; satır ya da dönem başına hesap çeken bir uygulama testi
   geçemez.

🔴 **K10 ayrıca sınanır:** yanıtta `urgency`/`color`/`severity` gibi bir alan
BULUNMAMALIDIR. E9'un renk kodlaması kendi içinde tutarsızdır (2 gün→turuncu,
3 gün→kırmızı, 7 gün→yeşil); sunucu yalnız `days_remaining` sayısını verir.
"""

from datetime import datetime, time
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezone import DISPLAY_TIMEZONE, today
from app.modules.invoicing.models import InvoiceDirection, InvoiceStatus
from app.modules.subcontractor_progress_payments.models import SubcontractorPaymentStatus
from app.modules.treasury import upcoming
from tests.modules.treasury._hz1_upcoming import (
    YOL,
    _gun,
    _kayitli_yollar,
    _liste,
    _onay_zamani,
)

pytestmark = pytest.mark.asyncio


# --- Rota sırası -----------------------------------------------------------


async def test_rota_sirasi_treasury_literal_UUID_SANILMAZ() -> None:
    """🔴 `/treasury/upcoming-payments` ve `/treasury/cash-flow` LİTERALDİR.

    Bir gün `/treasury/{...}` biçiminde bir yol açılır ve bu ikisinden ÖNCE
    kaydedilirse literal segment bir UUID sanılıp 422'ye düşer (MK-2 dersi,
    `main.py:94-104`). Bekçi hem yolların VARLIĞINI hem de sıralarını iddia eder.
    """
    yollar = _kayitli_yollar()
    literaller = [YOL, "/treasury/cash-flow"]
    for literal in literaller:
        assert literal in yollar, f"{literal} kayıtlı değil"
    for indeks, yol in enumerate(yollar):
        if yol.startswith("/treasury/{"):
            for literal in literaller:
                assert yollar.index(literal) < indeks, f"{yol} literalleri yutuyor"


# --- Kapı ------------------------------------------------------------------


async def test_yetkisiz_403(client: AsyncClient, yetkisiz_headers: dict[str, str]) -> None:
    """`site_chief` (`treasury=_N`) okumada bile 403 alır."""
    resp = await client.get(YOL, headers=yetkisiz_headers)
    assert resp.status_code == 403, resp.text


async def test_view_seviyesi_okur(client: AsyncClient, pm_headers: dict[str, str]) -> None:
    """`project_manager` (`treasury=_V`) — uç `view`dır, `full` DEĞİL."""
    resp = await client.get(YOL, headers=pm_headers)
    assert resp.status_code == 200, resp.text


async def test_kimliksiz_401(client: AsyncClient) -> None:
    resp = await client.get(YOL)
    assert resp.status_code == 401, resp.text


# --- `days` penceresi ------------------------------------------------------


@pytest.mark.parametrize("istenen", [None, 1, 30, 90])
async def test_days_ve_as_of_ECHO_edilir(
    client: AsyncClient, admin_headers: dict[str, str], istenen: int | None
) -> None:
    """E9:110 `(7 Gün)` — varsayılan **7**dir ve İSTENEN değer geri basılır.

    Sabit 7 basan bir uygulama ekranın başlığını yalan çıkarırdı (kullanıcı 30
    gün ister, kart "7 Gün" yazardı). `as_of` da BUGÜNdür: `days_remaining`
    ancak onunla doğrulanabilir; pencerenin SONU basılsaydı istemcinin kendi
    hesabı sunucununkiyle tutmazdı.
    """
    params = {} if istenen is None else {"days": istenen}
    resp = await client.get(YOL, headers=admin_headers, params=params)
    assert resp.status_code == 200, resp.text
    veri = resp.json()
    assert veri["days"] == (7 if istenen is None else istenen)
    assert veri["as_of"] == today().isoformat()


@pytest.mark.parametrize("days", [0, -1, 91, 365])
async def test_days_sinir_disi_422_KIRPILMAZ(
    client: AsyncClient, admin_headers: dict[str, str], days: int
) -> None:
    """🔴 Tavan aşımı **422**dir, sessiz kırpma DEĞİL (TB3 kanonu).

    Kırpılsaydı kullanıcı 365 gün ister, 90 gün görür ve eksik listeyi tam
    sanardı.
    """
    resp = await client.get(YOL, headers=admin_headers, params={"days": days})
    assert resp.status_code == 422, resp.text


@pytest.mark.parametrize("days", [1, 90])
async def test_days_sinirlari_kabul(
    client: AsyncClient, admin_headers: dict[str, str], days: int
) -> None:
    resp = await client.get(YOL, headers=admin_headers, params={"days": days})
    assert resp.status_code == 200, resp.text


# --- Kaynak 1: fatura ------------------------------------------------------


async def test_gelen_onayli_fatura_listelenir(
    client: AsyncClient, seeded_db: AsyncSession, admin_headers, fatura_fabrikasi
) -> None:
    """E9:121 `Yılmaz Elektrik – Fatura` satırının kaynağı."""
    await fatura_fabrikasi(
        direction=InvoiceDirection.incoming,
        status=InvoiceStatus.approved,
        total="475600.00",
        due_date=_gun(3),
        party_name="Yılmaz Elektrik",
    )
    items = await _liste(client, admin_headers)
    assert len(items) == 1
    satir = items[0]
    assert satir["source_type"] == "invoice"
    assert satir["counterparty"] == "Yılmaz Elektrik"
    assert satir["due_date"] == _gun(3).isoformat()
    assert satir["days_remaining"] == 3
    assert Decimal(satir["amount"]) == Decimal("475600.00")


async def test_giden_fatura_LISTELENMEZ(
    client: AsyncClient, seeded_db: AsyncSession, admin_headers, fatura_fabrikasi
) -> None:
    """🔴 Giden fatura bizim ALACAĞIMIZDIR — "Yaklaşan **Ödemeler**"e girmez.

    Yön süzgeci düşseydi kart, tahsil edeceğimiz parayı ödeyeceğimiz para gibi
    gösterir ve nakit ihtiyacını iki kat şişirirdi.
    """
    await fatura_fabrikasi(
        direction=InvoiceDirection.outgoing,
        status=InvoiceStatus.sent,
        due_date=_gun(3),
    )
    assert await _liste(client, admin_headers) == []


@pytest.mark.parametrize("status", [InvoiceStatus.pending, InvoiceStatus.disputed])
async def test_onaylanmamis_gelen_fatura_LISTELENMEZ(
    client: AsyncClient, seeded_db: AsyncSession, admin_headers, fatura_fabrikasi, status
) -> None:
    """`pending` henüz kabul edilmemiştir, `disputed` itiraz edilmiştir.

    İkisi de ÖDENECEK para değildir; durum süzgeci `approved`tır ve bu değer
    `InvoiceStatus`tan OKUNMUŞTUR, tahmin edilmemiştir.
    """
    await fatura_fabrikasi(direction=InvoiceDirection.incoming, status=status, due_date=_gun(3))
    assert await _liste(client, admin_headers) == []


async def test_vadesiz_fatura_LISTELENMEZ(
    client: AsyncClient, seeded_db: AsyncSession, admin_headers, fatura_fabrikasi
) -> None:
    """`due_date` NULL = vade BİLİNMİYOR. Bilinmeyen bir vade pencereye
    yerleştirilemez; "bugün" varsayılsaydı vadesiz her fatura acil görünürdü."""
    await fatura_fabrikasi(
        direction=InvoiceDirection.incoming, status=InvoiceStatus.approved, due_date=None
    )
    assert await _liste(client, admin_headers) == []


async def test_tam_odenmis_fatura_LISTELENMEZ(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers,
    fatura_fabrikasi,
    hesap_fabrikasi,
    fatura_odemesi,
) -> None:
    """Σ payments = total → borç KAPANMIŞTIR (K5'in toplamı, ikinci formül yok)."""
    invoice = await fatura_fabrikasi(
        direction=InvoiceDirection.incoming,
        status=InvoiceStatus.approved,
        total="1000.00",
        due_date=_gun(2),
    )
    hesap = await hesap_fabrikasi()
    await fatura_odemesi(invoice, hesap, "1000.00")
    assert await _liste(client, admin_headers) == []


async def test_kismen_odenmis_faturada_tutar_KALANDIR(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers,
    fatura_fabrikasi,
    hesap_fabrikasi,
    fatura_odemesi,
) -> None:
    """🔴 Satırın tutarı `total − Σ payments`tır, `total` DEĞİL.

    `total` basılsaydı yarısı ödenmiş bir fatura nakit ihtiyacını iki katı
    gösterirdi — ve hiçbir kolon farkı bunu ele vermezdi (`paid_amount` yok).
    """
    invoice = await fatura_fabrikasi(
        direction=InvoiceDirection.incoming,
        status=InvoiceStatus.approved,
        total="1000.00",
        due_date=_gun(2),
    )
    hesap = await hesap_fabrikasi()
    await fatura_odemesi(invoice, hesap, "400.00")
    items = await _liste(client, admin_headers)
    assert len(items) == 1
    assert Decimal(items[0]["amount"]) == Decimal("600.00")


# --- Pencere sınırları -----------------------------------------------------


@pytest.mark.parametrize(
    ("offset", "beklenen"),
    [(-1, 0), (0, 1), (7, 1), (8, 0)],
)
async def test_pencere_sinirlari(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers,
    fatura_fabrikasi,
    offset: int,
    beklenen: int,
) -> None:
    """Sınırlar KAPALI (`bugün` ve `bugün+days` DAHİL), taşanlar dışarıda.

    🔴 **VADESİ GEÇMİŞ (offset=-1) DIŞARIDADIR** — bilinçli ve DAR karar:
    kartın adı "Yaklaşan Ödemeler"dir ve mockup negatif bir "kalan gün"
    ÇİZMEZ. Geçmişi içeri almak pencerenin alt sınırını SINIRSIZ yapardı
    (bir yıl önce vadesi dolmuş her fatura "yaklaşan" sayılırdı). Gecikmiş
    borç takibi ayrı bir yüzeydir ve çizilmemiştir (HZ-3 borcu).
    """
    await fatura_fabrikasi(
        direction=InvoiceDirection.incoming,
        status=InvoiceStatus.approved,
        due_date=_gun(offset),
    )
    assert len(await _liste(client, admin_headers)) == beklenen


async def test_days_penceresi_genisletir(
    client: AsyncClient, seeded_db: AsyncSession, admin_headers, fatura_fabrikasi
) -> None:
    """Varsayılanın DIŞINDA kalan satır `days=30` ile içeri girer."""
    await fatura_fabrikasi(
        direction=InvoiceDirection.incoming,
        status=InvoiceStatus.approved,
        due_date=_gun(20),
    )
    assert await _liste(client, admin_headers) == []
    assert len(await _liste(client, admin_headers, days=30)) == 1


async def test_days_remaining_negatif_OLMAZ(
    client: AsyncClient, seeded_db: AsyncSession, admin_headers, fatura_fabrikasi
) -> None:
    """Pencerenin alt sınırı bugündür → alan hiçbir zaman negatif dönmez."""
    for offset in (0, 1, 5):
        await fatura_fabrikasi(
            direction=InvoiceDirection.incoming,
            status=InvoiceStatus.approved,
            due_date=_gun(offset),
        )
    items = await _liste(client, admin_headers)
    assert [s["days_remaining"] for s in items] == [0, 1, 5]


# --- Kaynak 2: taşeron hakedişi -------------------------------------------


async def test_onayli_hakedis_listelenir(
    client: AsyncClient, seeded_db: AsyncSession, admin_headers, taseron_hakedisi_fabrikasi
) -> None:
    """E9:113 `Akın İnşaat – Hakediş #47` satırının kaynağı.

    Vade `approved_at` + sözleşmenin `payment_term_days`ıdır: hakedişte vade
    KOLONU YOKTUR, ama sözleşmede ödeme vadesi (gün) VARDIR — bu bir türetimdir,
    icat değil (bordroda böyle bir dayanak yoktur, K9).
    """
    await taseron_hakedisi_fabrikasi(
        approved_at=_onay_zamani(_gun(0)),
        payment_term_days=2,
        subcontractor_name="Akın İnşaat",
        sequence_no=47,
        line_amounts=("1016800.00",),
    )
    items = await _liste(client, admin_headers)
    assert len(items) == 1
    satir = items[0]
    assert satir["source_type"] == "subcontractor_progress_payment"
    assert satir["counterparty"] == "Akın İnşaat"
    assert satir["document_no"] == "47"
    assert satir["days_remaining"] == 2
    assert Decimal(satir["amount"]) == Decimal("1016800.00")


@pytest.mark.parametrize(
    "status",
    [
        SubcontractorPaymentStatus.draft,
        SubcontractorPaymentStatus.pending_approval,
        SubcontractorPaymentStatus.paid,
    ],
)
async def test_onaysiz_ve_odenmis_hakedis_LISTELENMEZ(
    client: AsyncClient, seeded_db: AsyncSession, admin_headers, taseron_hakedisi_fabrikasi, status
) -> None:
    """Yalnız `approved` = onaylı ve HENÜZ ÖDENMEMİŞ.

    `paid` çıkarılmasaydı ödenmiş her hakediş vadesi boyunca listede kalır,
    `draft` girseydi hiç onaylanmamış bir taslak nakit planına girerdi.
    """
    await taseron_hakedisi_fabrikasi(
        approved_at=_onay_zamani(_gun(0)), payment_term_days=2, status=status
    )
    assert await _liste(client, admin_headers) == []


async def test_onay_damgasi_olmayan_hakedis_LISTELENMEZ(
    client: AsyncClient, seeded_db: AsyncSession, admin_headers, taseron_hakedisi_fabrikasi
) -> None:
    """`approved_at` NULL → vade HESAPLANAMAZ (vadesiz fatura ile aynı kural)."""
    await taseron_hakedisi_fabrikasi(approved_at=None, payment_term_days=2)
    assert await _liste(client, admin_headers) == []


async def test_onay_saati_TR_GUNUNE_cevrilir(
    client: AsyncClient, seeded_db: AsyncSession, admin_headers, taseron_hakedisi_fabrikasi
) -> None:
    """🔴 `approved_at` `timestamptz`tir; günü TR takviminde okunmalıdır.

    Gece TR 01:00'de onaylanan bir hakediş UTC'de BİR ÖNCEKİ güne düşer.
    Çevrim yapılmasaydı vade bir gün geri kayar ve satır pencerenin ALTINA
    (vadesi geçmiş sayılıp) düşerek listeden TAMAMEN kaybolurdu — ekranda
    ödenmesi gereken bir borç hiç görünmezdi.

    ⚠️ Öğle vaktiyle kurulmuş bir test bu kusuru GÖREMEZ (ölçüldü: mutasyon
    hayatta kalıyordu); saat bilerek gecenin ilk saatidir.
    """
    await taseron_hakedisi_fabrikasi(
        approved_at=datetime.combine(_gun(0), time(1, 0), tzinfo=DISPLAY_TIMEZONE),
        payment_term_days=0,
    )
    items = await _liste(client, admin_headers)
    assert len(items) == 1
    assert items[0]["due_date"] == _gun(0).isoformat()
    assert items[0]["days_remaining"] == 0


async def test_vade_ifadesi_SAAT_DILIMI_cevirir() -> None:
    """🔴 KARA KUTUYLA ULAŞILAMAYAN garanti — SQL'in kendisinde denetlenir.

    `cast(timestamptz AS date)` PostgreSQL'de OTURUMUN `TimeZone` ayarını
    kullanır. Geliştirme makinesinde bu ayar TR olduğu için açık çevrim
    kaldırılsa bile uçtan yazılmış test YEŞİL kalır (ölçüldü: mutasyon hayatta
    kaldı); kusur yalnız CI ve Railway'de (UTC) ortaya çıkar ve orada bir
    hakediş listeden sessizce düşer. Bu yüzden ifade dışa açıktır ve saat
    dilimi çevrimi burada iddia edilir.
    """
    sql = str(upcoming.progress_payment_due_expression())
    assert "timezone(" in sql
    assert "payment_term_days" in sql


async def test_hakedis_tutari_NET_TIR_brut_degil(
    client: AsyncClient, seeded_db: AsyncSession, admin_headers, taseron_hakedisi_fabrikasi
) -> None:
    """🔴 Ödenecek para NET'tir (E15 tfoot'u): brüt + KDV − avans − teminat.

    Brüt basılsaydı kesintili her hakediş fazla, KDV'li her hakediş eksik
    görünürdü. Yüzdeler bilerek SIFIRDAN FARKLIDIR ki iki sayı ayrışsın.
    """
    await taseron_hakedisi_fabrikasi(
        approved_at=_onay_zamani(_gun(0)),
        payment_term_days=1,
        vat_pct="20",
        advance_pct="10",
        retainage_pct="5",
        line_amounts=("1000.00",),
    )
    items = await _liste(client, admin_headers)
    # brüt 1000 + KDV 200 − avans 100 − teminat 50 = 1050
    assert Decimal(items[0]["amount"]) == Decimal("1050.00")


async def test_faturalanmis_hakedis_CIFT_SAYILMAZ(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers,
    taseron_hakedisi_fabrikasi,
    fatura_fabrikasi,
) -> None:
    """🔴 ÇİFT SAYIM KAPISI: hakediş faturalandıysa ödenecek olan FATURADIR.

    İkisi de listelenseydi aynı borç iki satır ve iki tutar üretir, nakit
    ihtiyacı sessizce iki katına çıkardı.
    """
    hakedis = await taseron_hakedisi_fabrikasi(
        approved_at=_onay_zamani(_gun(0)), payment_term_days=2, line_amounts=("1000.00",)
    )
    await fatura_fabrikasi(
        direction=InvoiceDirection.incoming,
        status=InvoiceStatus.approved,
        total="1000.00",
        due_date=_gun(3),
        source_payment=hakedis,
    )
    items = await _liste(client, admin_headers)
    assert [s["source_type"] for s in items] == ["invoice"]
