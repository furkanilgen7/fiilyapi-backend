"""HZ-1 T5 — `GET /treasury/upcoming-payments` (spec §4 uç 9, E9:109-125).

Bu uç HİÇBİR ŞEY YAZMAZ; bütün riski **hangi satırın listeye girdiği** ve
**kimin göreceğidir**. Dört sınıf kusur ölçülür:

1. **KAYNAK SEÇİMİ (K9).** Üç kaynak çizilidir, bugün İKİSİ vardır. Yanlış
   durumdaki (taslak/ihtilaflı/ödenmiş) ya da tam ödenmiş bir evrakın listeye
   sızması ekranda "ödenecek" görünen ama ödenmeyecek bir para üretir.
2. **PENCERE.** `days` bir SINIRDIR: tavanı aşan istek sessizce kırpılırsa
   kullanıcı 90 gün ister, 90 gün gördüğünü sanır. Sınır günleri (bugün ·
   bugün+`days` · bugün+`days`+1) ayrı ayrı sınanır.
3. **KAPSAM (IDOR).** Hesap şirket genelidir (K3) ama KAYNAKLAR proje kapsamı
   taşır. Süzgeç düşerse `treasury=_V` olan proje müdürü, göremediği projenin
   karşı tarafını ve tutarını okur. Taşıyıcı `kapsamli_muhasebe_headers`tir —
   `admin_headers` (`projects=_A`) süzgeci ATLADIĞI için sızıntıyı göstermez.
4. **N+1.** 1 satır ile 20 satırın SORGU SAYISI ölçülür; satır başına hesap
   çeken bir uygulama testi geçemez.

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
    client: AsyncClient, seeded_db: AsyncSession, admin_headers, fatura_fabrikasi
) -> None:
    """🔴 Renk/aciliyet SUNUCUDA üretilmez (SA "EN HIZLI rozeti" kanonu).

    E9'un kodlaması kendi içinde tutarsızdır (2 gün turuncu, 3 gün KIRMIZI,
    7 gün yeşil); sunucu bir eşik uydurursa mockup'ın hangi yarısının doğru
    olduğuna karar vermiş olur.
    """
    await fatura_fabrikasi(
        direction=InvoiceDirection.incoming, status=InvoiceStatus.approved, due_date=_gun(2)
    )
    satir = (await _liste(client, admin_headers))[0]
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


# --- N+1 -------------------------------------------------------------------


async def test_N_ARTI_1_YAPMAZ(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers,
    fatura_fabrikasi,
    taseron_hakedisi_fabrikasi,
) -> None:
    """🔴 Sorgu sayısı SATIR SAYISINDAN bağımsızdır — tahmin değil ÖLÇÜM.

    Hakediş tutarı `amounts.bulk_calculations`tan gelir (iki toplu sorgu);
    hakediş başına `calculation_for` çağıran bir uygulama burada patlar.
    """
    await fatura_fabrikasi(
        direction=InvoiceDirection.incoming, status=InvoiceStatus.approved, due_date=_gun(1)
    )
    await taseron_hakedisi_fabrikasi(approved_at=_onay_zamani(_gun(0)), payment_term_days=1)
    with _sorgu_sayaci() as az:
        assert len(await _liste(client, admin_headers)) == 2
    for _ in range(9):
        await fatura_fabrikasi(
            direction=InvoiceDirection.incoming, status=InvoiceStatus.approved, due_date=_gun(1)
        )
        await taseron_hakedisi_fabrikasi(approved_at=_onay_zamani(_gun(0)), payment_term_days=1)
    with _sorgu_sayaci() as cok:
        assert len(await _liste(client, admin_headers)) == 20
    assert len(cok) == len(az), f"az={len(az)} çok={len(cok)}"
