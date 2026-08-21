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

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, time, timedelta
from decimal import Decimal

import pytest
from fastapi.routing import APIRoute
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezone import DISPLAY_TIMEZONE, today
from app.main import app
from app.modules.invoicing.models import InvoiceDirection, InvoiceStatus
from app.modules.payroll.models import PayrollLineStatus, PayrollPeriodStatus
from app.modules.subcontractor_progress_payments.models import SubcontractorPaymentStatus
from app.modules.treasury import upcoming
from tests.conftest import test_engine

pytestmark = pytest.mark.asyncio

YOL = "/treasury/upcoming-payments"


def _gun(offset: int):
    """Bugünden `offset` gün sonrası — pencere sınırlarının TEK kaynağı."""
    return today() + timedelta(days=offset)


def _onay_zamani(gun) -> datetime:  # noqa: ANN001
    """Hakedişin `approved_at` damgası: TR gününün ÖĞLE vakti.

    Gün başı/sonu seçilseydi UTC'ye çevrildiğinde komşu güne düşer ve vade
    hesabı bir gün kayardı — testin kendisi tuzağa düşerdi.
    """
    return datetime.combine(gun, time(12, 0), tzinfo=DISPLAY_TIMEZONE)


@contextmanager
def _sorgu_sayaci() -> Iterator[list[str]]:
    """Sürücüye giden HER ifadeyi toplar (`test_hz1_balance.py` deseni)."""
    ifadeler: list[str] = []

    def kaydet(conn, cursor, statement, parameters, context, executemany) -> None:  # noqa: ANN001
        ifadeler.append(" ".join(statement.split()))

    event.listen(test_engine.sync_engine, "before_cursor_execute", kaydet)
    try:
        yield ifadeler
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", kaydet)


async def _liste(client: AsyncClient, headers: dict[str, str], **params) -> list[dict]:
    resp = await client.get(YOL, headers=headers, params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()["items"]


def _bordro(items: list[dict]) -> list[dict]:
    """Yanıttaki BORDRO satırları — `source_type` **DEĞERİ** ile süzülür.

    🔴 **K1.1 — SAHTE-YEŞİL TUZAĞI.** "Bordro satırı gelmedi" biçimindeki her
    negatif iddia, kaynak henüz HİÇ yokken de KENDİLİĞİNDEN geçer ve hiçbir şeyi
    bekçilemez. Süzgeç bu yüzden `len(items) == 0` gibi zayıf bir iddiaya değil
    ALT KÜMENİN KENDİSİNE bakar: pozitif testler alt kümenin tek elemanını ve
    tutarını çakar, negatif testler ise yanında DAİMA listeye girmesi gereken
    ikinci bir dönem/evrak taşır — böylece "hiç satır üretilmiyor" hâli ile
    "doğru satır süzülüyor" hâli birbirinden ayrılır.

    Karşılaştırma STRING iledir, `UpcomingSourceType.payroll` ile değil: üye T2'de
    açılacaktır ve şimdiden içe aktarılsaydı testler `ImportError`la kırmızı
    olurdu — yani bekçi, iddiasını hiç ölçmeden kırmızı kalırdı (fixture/import
    hatası bekçilik DEĞİLDİR).
    """
    return [satir for satir in items if satir["source_type"] == "payroll"]


# --- Rota sırası -----------------------------------------------------------


def _kayitli_yollar() -> list[str]:
    """Uygulamanın TÜM yolları, KAYIT SIRASINDA.

    ⚠️ `app.routes` YETMEZ: bu FastAPI sürümü `include_router`ı tembel bir
    `_IncludedRouter` sarmalayıcısı olarak tutar ve düz listede yalnız
    doğrudan dekoratörle tanımlanmış yollar (`/health`) görünür. Sarmalayıcı
    açılmasaydı bekçi HER ZAMAN "yol kayıtlı değil" derdi — yani gerçek sırayı
    hiç ölçmeden kırmızı kalırdı.
    """

    def gez(rotalar) -> list[str]:  # noqa: ANN001
        toplanan: list[str] = []
        for rota in rotalar:
            if isinstance(rota, APIRoute):
                toplanan.append(rota.path)
            elif type(rota).__name__ == "_IncludedRouter":
                toplanan += gez(rota.original_router.routes)
        return toplanan

    return gez(app.routes)


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


# --- Sıralama --------------------------------------------------------------


async def test_vadeye_gore_ARTAN_siralama(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers,
    fatura_fabrikasi,
    taseron_hakedisi_fabrikasi,
) -> None:
    """E9:113/117/121 satır sırası vadeye göre artan; İKİ KAYNAK İÇ İÇE geçer.

    Kaynak kaynak sıralansaydı (önce faturalar, sonra hakedişler) en acil borç
    listenin ortasında kalırdı.
    """
    await fatura_fabrikasi(
        direction=InvoiceDirection.incoming, status=InvoiceStatus.approved, due_date=_gun(5)
    )
    await taseron_hakedisi_fabrikasi(approved_at=_onay_zamani(_gun(0)), payment_term_days=1)
    await fatura_fabrikasi(
        direction=InvoiceDirection.incoming, status=InvoiceStatus.approved, due_date=_gun(3)
    )
    items = await _liste(client, admin_headers)
    assert [s["days_remaining"] for s in items] == [1, 3, 5]


# --- K10 -------------------------------------------------------------------


async def test_K10_aciliyet_alani_ACILMAZ(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers,
    fatura_fabrikasi,
    bordro_donemi_fabrikasi,
) -> None:
    """🔴 Renk/aciliyet SUNUCUDA üretilmez (SA "EN HIZLI rozeti" kanonu).

    E9'un kodlaması kendi içinde tutarsızdır (2 gün turuncu, 3 gün KIRMIZI,
    7 gün yeşil); sunucu bir eşik uydurursa mockup'ın hangi yarısının doğru
    olduğuna karar vermiş olur.

    🔴 **TB8: bekçi BORDRO satırını da kapsar.** Alan kümesi satır BAŞINA
    denetlenir, yalnız ilk satırda değil: yeni kaynak kendi zarfını üretir ve
    oraya `urgency`/`period_label` gibi bir alan eklemek (ya da bir alanı
    düşürmek) mevcut iddianın altından kaçardı. Bordro satırı `counterparty`yi
    **`None`** taşır ama alanı YİNE DE taşır — kaynağa göre şekil değiştiren bir
    zarf, istemcide kaynak başına ayrı bir okuma yolu doğururdu.
    """
    await fatura_fabrikasi(
        direction=InvoiceDirection.incoming, status=InvoiceStatus.approved, due_date=_gun(2)
    )
    await bordro_donemi_fabrikasi(year=2026, month=7, payment_due_date=_gun(3))
    items = await _liste(client, admin_headers)
    assert len(_bordro(items)) == 1, items
    for satir in items:
        for yasak in ("urgency", "color", "severity", "badge", "level"):
            assert yasak not in satir
        assert set(satir) == {
            "source_type",
            "source_id",
            "counterparty",
            "document_no",
            "due_date",
            "days_remaining",
            "amount",
        }


# --- Kapsam (IDOR) ---------------------------------------------------------


async def test_gorunmeyen_projenin_faturasi_SIZMAZ(
    client: AsyncClient,
    seeded_db: AsyncSession,
    kapsamli_muhasebe_headers,
    admin_headers,
    fatura_fabrikasi,
    gorunen_proje,
    gorunmeyen_proje,
) -> None:
    """🔴 K3 hesabı şirket geneli yapar; KAYNAKLAR proje kapsamlıdır.

    Süzgeç `invoicing.repository.scope_clause`tır — ikinci bir görünürlük
    tanımı yazılsaydı liste ucu ile bu uç zamanla ayrışırdı.
    """
    await fatura_fabrikasi(
        direction=InvoiceDirection.incoming,
        status=InvoiceStatus.approved,
        due_date=_gun(2),
        project=gorunen_proje,
        party_name="Görünen",
    )
    await fatura_fabrikasi(
        direction=InvoiceDirection.incoming,
        status=InvoiceStatus.approved,
        due_date=_gun(3),
        project=gorunmeyen_proje,
        party_name="Görünmeyen",
    )
    kisitli = await _liste(client, kapsamli_muhasebe_headers)
    assert [s["counterparty"] for s in kisitli] == ["Görünen"]
    tam = await _liste(client, admin_headers)
    assert len(tam) == 2


async def test_projesiz_fatura_GORUNUR(
    client: AsyncClient,
    seeded_db: AsyncSession,
    kapsamli_muhasebe_headers,
    fatura_fabrikasi,
    gorunen_proje,
    gorunmeyen_proje,
) -> None:
    """`project_id` NULL = ŞİRKET GENELİ fatura; modül izniyle görünür
    (`invoicing`in kendi kuralı, burada ikinci kez KARAR VERİLMEZ)."""
    await fatura_fabrikasi(
        direction=InvoiceDirection.incoming,
        status=InvoiceStatus.approved,
        due_date=_gun(2),
        project=None,
    )
    assert len(await _liste(client, kapsamli_muhasebe_headers)) == 1


async def test_gorunmeyen_projenin_hakedisi_SIZMAZ(
    client: AsyncClient,
    seeded_db: AsyncSession,
    kapsamli_muhasebe_headers,
    admin_headers,
    taseron_hakedisi_fabrikasi,
    gorunen_proje,
    gorunmeyen_proje,
) -> None:
    """Hakedişin `project_id`si NOT NULL'dır — "şirket geneli" hâli YOKTUR."""
    await taseron_hakedisi_fabrikasi(
        project=gorunen_proje,
        approved_at=_onay_zamani(_gun(0)),
        payment_term_days=1,
        subcontractor_name="Görünen Taşeron",
    )
    await taseron_hakedisi_fabrikasi(
        project=gorunmeyen_proje,
        approved_at=_onay_zamani(_gun(0)),
        payment_term_days=2,
        subcontractor_name="Görünmeyen Taşeron",
    )
    kisitli = await _liste(client, kapsamli_muhasebe_headers)
    assert [s["counterparty"] for s in kisitli] == ["Görünen Taşeron"]
    assert len(await _liste(client, admin_headers)) == 2


async def test_KAPSAM_bordro_satiri_PAYROLL_izni_ister(
    client: AsyncClient,
    seeded_db: AsyncSession,
    pm_headers,
    kapsamli_pm_headers,
    kapsamli_muhasebe_headers,
    admin_headers,
    bordro_donemi_fabrikasi,
    fatura_fabrikasi,
    taseron_hakedisi_fabrikasi,
    gorunen_proje,
    gorunmeyen_proje,
) -> None:
    """🔴 IDOR — bordro satırının görünürlüğü PROJE kapsamı DEĞİL, MODÜL iznidir.

    `PayrollPeriod`da `project_id` **YOKTUR** (ölçüldü): dönem şirket
    genelindedir, yani iki mevcut kaynağın proje süzgeci buraya UYGULANAMAZ.
    Süzgeç yazılmazsa satır HERKESE açılır ve matris burada AYRIŞIR:

        `"treasury": [_A, _F, _N, _N, _N, _F, _V, _N]`
        `"payroll":  [_A, _F, _N, _N, _F, _F, _N, _N]`

    `project_manager` bu ucu OKUR (`treasury=_V`) ama bordroya **HİÇ** erişimi
    yoktur (`payroll=_N`). Süzgeç düşerse bir proje müdürü şirketin AYLIK TOPLAM
    PERSONEL MALİYETİNİ okur — bu ucun sızdırdığı en hassas tek sayıdır.
    `admin_headers` bunu ASLA gösteremez (`payroll=_A`).

    🔴 **Kapı FAZLA GENİŞ de kapanmamalıdır.** `kapsamli_pm_headers`
    `kapsamli_muhasebe_headers`in ikizidir — proje kapsamları AYNIDIR, tek fark
    `payroll` iznidir. PM'in fatura ve hakediş satırlarını GÖRMEYE DEVAM ettiği
    ayrıca çakılır: `payroll` iznini ucun TAMAMINA uygulayan (ör. 403 döndüren
    ya da listeyi boşaltan) bir uygulama, iki çalışan kaynağı da susturur ve o
    kusur yalnız bu iddiayla yakalanır.
    """
    donem = await bordro_donemi_fabrikasi(
        year=2026,
        month=7,
        payment_due_date=_gun(3),
        lines=((PayrollLineStatus.approved, "892000.00"),),
    )
    await fatura_fabrikasi(
        direction=InvoiceDirection.incoming,
        status=InvoiceStatus.approved,
        due_date=_gun(2),
        project=None,
        party_name="Şirket Geneli",
    )
    await taseron_hakedisi_fabrikasi(
        project=gorunen_proje,
        approved_at=_onay_zamani(_gun(0)),
        payment_term_days=1,
        subcontractor_name="Görünen Taşeron",
    )

    # 1) Kapsamsız PM — bordroyu GÖRMEZ, şirket geneli faturayı görmeye devam eder.
    pm_items = await _liste(client, pm_headers)
    assert _bordro(pm_items) == [], pm_items
    assert "invoice" in {satir["source_type"] for satir in pm_items}

    # 2) Kapsamlı PM — muhasebenin İKİZİ; tek fark `payroll` izni.
    kapsamli_pm_items = await _liste(client, kapsamli_pm_headers)
    assert _bordro(kapsamli_pm_items) == [], kapsamli_pm_items
    assert {satir["source_type"] for satir in kapsamli_pm_items} == {
        "invoice",
        "subcontractor_progress_payment",
    }

    # 3) Muhasebe (`payroll=_F`) — AYNI kapsam, bordro satırı GÖRÜNÜR.
    muhasebe_items = await _liste(client, kapsamli_muhasebe_headers)
    muhasebe_bordro = _bordro(muhasebe_items)
    assert len(muhasebe_bordro) == 1, muhasebe_items
    assert muhasebe_bordro[0]["source_id"] == str(donem.id)
    assert Decimal(muhasebe_bordro[0]["amount"]) == Decimal("892000.00")
    assert {satir["source_type"] for satir in muhasebe_items} == {
        "invoice",
        "subcontractor_progress_payment",
        "payroll",
    }


# --- N+1 -------------------------------------------------------------------


async def test_N_ARTI_1_YAPMAZ(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers,
    fatura_fabrikasi,
    taseron_hakedisi_fabrikasi,
    bordro_donemi_fabrikasi,
) -> None:
    """🔴 Sorgu sayısı SATIR SAYISINDAN bağımsızdır — tahmin değil ÖLÇÜM.

    Hakediş tutarı `amounts.bulk_calculations`tan gelir (iki toplu sorgu);
    hakediş başına `calculation_for` çağıran bir uygulama burada patlar.

    🔴 **TB8: ölçüm ÜÇÜNCÜ kaynağı da kapsar** ve tuzak burada daha derindir.
    Bordronun tutarı bir kolon değil `Σ net_amount` TÜREVİDİR; en kolay
    uygulama dönem başına satırları çekmek ya da `summary.build_period_summary`i
    dönem başına çağırmaktır — ikisi de dönem sayısıyla büyür. Sorgu, dönem
    başına DEĞİL, `GROUP BY payroll_period_id` ile TEK seferde kurulmalıdır.

    On dönemin (yıl, ay)'ı FARKLI olmak zorundadır
    (`uq_payroll_periods_year_month`); fabrika bunu sayaçtan üretir.
    """
    await fatura_fabrikasi(
        direction=InvoiceDirection.incoming, status=InvoiceStatus.approved, due_date=_gun(1)
    )
    await taseron_hakedisi_fabrikasi(approved_at=_onay_zamani(_gun(0)), payment_term_days=1)
    await bordro_donemi_fabrikasi(payment_due_date=_gun(1))
    with _sorgu_sayaci() as az:
        assert len(await _liste(client, admin_headers)) == 3
    for _ in range(9):
        await fatura_fabrikasi(
            direction=InvoiceDirection.incoming, status=InvoiceStatus.approved, due_date=_gun(1)
        )
        await taseron_hakedisi_fabrikasi(approved_at=_onay_zamani(_gun(0)), payment_term_days=1)
        await bordro_donemi_fabrikasi(payment_due_date=_gun(1))
    with _sorgu_sayaci() as cok:
        items = await _liste(client, admin_headers)
    assert len(items) == 30
    assert len(_bordro(items)) == 10, items
    assert len(cok) == len(az), f"az={len(az)} çok={len(cok)}"
