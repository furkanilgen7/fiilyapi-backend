"""HZ-1 T5 — `GET /treasury/cash-flow` (spec §4 uç 10, E9:90-106).

Nakit akışı **bakiyenin zaman serisidir**: aynı ödemeler, aynı yön kuralı (K2),
yalnız güne göre kovalanmış. Dört sınıf kusur ölçülür:

1. **YÖN (K2/K4).** İşaret bağlı faturanın `direction`'ından gelir. Takas
   edilirse iki toplam yer değiştirir ve grafik yine "bir şey" çizer —
   yanlış olduğu anlaşılmaz. Bu yüzden testler İKİ YÖNÜ BİRDEN kurar.
2. **NULL YUTMASI.** 🔴 Boş ayda seri BOŞ, toplamlar **`0`** olmalıdır.
   `coalesce` olmasaydı `SUM()` NULL döner ve kart "₺" yanında boşluk basardı.
3. **AY PENCERESİ.** Sınırlar `DISPLAY_TIMEZONE`dedir ve KAPALIDIR; komşu
   ayların ilk/son günleri ayrı ayrı sınanır.
4. **N+1.** Sorgu sayısı GÜN sayısından bağımsızdır.

🔴 **KAPSAM KARARI (gerekçesi `cash_flow.py` docstring'inde):** bu uç proje
süzgeci UYGULAMAZ. Seri, kullanıcının aynı ekranda zaten okuduğu ŞİRKET GENELİ
hesap bakiyelerinin (K3, uç 1) türevidir; süzülseydi grafik kartlarla
çelişirdi. `test_kapsam_suzgeci_UYGULANMAZ` bu kararı çiviler.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezone import today
from app.modules.invoicing.models import InvoiceDirection, InvoiceStatus
from app.modules.treasury import cash_flow
from tests.conftest import test_engine

pytestmark = pytest.mark.asyncio

YOL = "/treasury/cash-flow"
YIL = 2026
AY = 5


@contextmanager
def _sorgu_sayaci() -> Iterator[list[str]]:
    ifadeler: list[str] = []

    def kaydet(conn, cursor, statement, parameters, context, executemany) -> None:  # noqa: ANN001
        ifadeler.append(" ".join(statement.split()))

    event.listen(test_engine.sync_engine, "before_cursor_execute", kaydet)
    try:
        yield ifadeler
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", kaydet)


async def _akis(client: AsyncClient, headers: dict[str, str], **params) -> dict:
    resp = await client.get(YOL, headers=headers, params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


# --- Kapı ------------------------------------------------------------------


async def test_yetkisiz_403(client: AsyncClient, yetkisiz_headers: dict[str, str]) -> None:
    resp = await client.get(YOL, headers=yetkisiz_headers)
    assert resp.status_code == 403, resp.text


async def test_view_seviyesi_okur(client: AsyncClient, pm_headers: dict[str, str]) -> None:
    resp = await client.get(YOL, headers=pm_headers)
    assert resp.status_code == 200, resp.text


async def test_kimliksiz_401(client: AsyncClient) -> None:
    assert (await client.get(YOL)).status_code == 401


# --- Parametre doğrulaması -------------------------------------------------


@pytest.mark.parametrize("month", [0, 13, -1])
async def test_ay_araligi_disi_422(
    client: AsyncClient, admin_headers: dict[str, str], month: int
) -> None:
    resp = await client.get(YOL, headers=admin_headers, params={"year": YIL, "month": month})
    assert resp.status_code == 422, resp.text


@pytest.mark.parametrize("year", [1999, 2201])
async def test_yil_araligi_disi_422(
    client: AsyncClient, admin_headers: dict[str, str], year: int
) -> None:
    """Dar aralık (`2000-2200`, `timesheet`/`equipment` emsali): serbest bir yıl
    değeri, ay sınırı hesabını anlamsız tarihlere taşırdı."""
    resp = await client.get(YOL, headers=admin_headers, params={"year": year, "month": AY})
    assert resp.status_code == 422, resp.text


async def test_varsayilan_icinde_bulunulan_ay(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    """Parametresiz istek `DISPLAY_TIMEZONE`deki bu ayı döner ve ECHO eder."""
    bugun = today()
    veri = await _akis(client, admin_headers)
    assert (veri["year"], veri["month"]) == (bugun.year, bugun.month)


# --- Boş ay ----------------------------------------------------------------


async def test_bos_ayda_seri_BOS_toplamlar_SIFIR(
    client: AsyncClient, seeded_db: AsyncSession, admin_headers: dict[str, str]
) -> None:
    """🔴 NULL DEĞİL SIFIR. Toplam sorgusu ödeme bulamayınca `SUM()` NULL döner;
    `coalesce` olmasaydı yanıt şeması ya 500 verir ya `null` basardı."""
    veri = await _akis(client, admin_headers, year=YIL, month=AY)
    assert veri["series"] == []
    assert Decimal(veri["inflow_total"]) == Decimal("0")
    assert Decimal(veri["outflow_total"]) == Decimal("0")


# --- Yön -------------------------------------------------------------------


async def test_iki_yon_ayri_kovalarda(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers,
    fatura_fabrikasi,
    hesap_fabrikasi,
    fatura_odemesi,
) -> None:
    """🔴 K2: GİDEN faturaya yapılan ödeme **giriş**, GELEN faturaya yapılan
    ödeme **çıkış**tır. İşaret takası bu testte İKİ alanı birden bozar."""
    hesap = await hesap_fabrikasi()
    giden = await fatura_fabrikasi(direction=InvoiceDirection.outgoing, total="900.00")
    gelen = await fatura_fabrikasi(
        direction=InvoiceDirection.incoming, status=InvoiceStatus.approved, total="900.00"
    )
    await fatura_odemesi(giden, hesap, "500.00", paid_on=date(YIL, AY, 10))
    await fatura_odemesi(gelen, hesap, "300.00", paid_on=date(YIL, AY, 10))

    veri = await _akis(client, admin_headers, year=YIL, month=AY)
    assert veri["series"] == [
        {"day": f"{YIL}-{AY:02d}-10", "inflow": "500.00", "outflow": "300.00"}
    ]
    assert Decimal(veri["inflow_total"]) == Decimal("500.00")
    assert Decimal(veri["outflow_total"]) == Decimal("300.00")


async def test_ayni_gun_TEK_kovada_toplanir(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers,
    fatura_fabrikasi,
    hesap_fabrikasi,
    fatura_odemesi,
) -> None:
    """Gruplama `paid_on` üzerindedir; düşseydi her ödeme ayrı kova olurdu."""
    hesap = await hesap_fabrikasi()
    giden = await fatura_fabrikasi(direction=InvoiceDirection.outgoing, total="900.00")
    await fatura_odemesi(giden, hesap, "0.01", paid_on=date(YIL, AY, 3))
    await fatura_odemesi(giden, hesap, "0.02", paid_on=date(YIL, AY, 3))
    veri = await _akis(client, admin_headers, year=YIL, month=AY)
    assert len(veri["series"]) == 1
    # Kuruş toplamı TAM: kayan noktaya düşen bir uygulama 0.030000000000000002 üretir.
    assert Decimal(veri["series"][0]["inflow"]) == Decimal("0.03")


async def test_gunler_ARTAN_sirada(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers,
    fatura_fabrikasi,
    hesap_fabrikasi,
    fatura_odemesi,
) -> None:
    """Seri TARİH SIRASINDA gelir — grafik onu soldan sağa çizer.

    Günler bilerek TERS sırada yazılır ve sayıları çoktur (25): tek bir
    `GROUP BY`ın satırları "genelde" ekleme sırasında dönmesine güvenilemez;
    planlayıcı satır sayısı arttıkça hash toplamaya geçer ve sıra keyfîleşir.
    Az sayıda satırla yazılmış bir test, kayıp bir `ORDER BY`ı GÖREMEZ.
    """
    hesap = await hesap_fabrikasi()
    giden = await fatura_fabrikasi(direction=InvoiceDirection.outgoing, total="9000.00")
    for gun in range(25, 0, -1):
        await fatura_odemesi(giden, hesap, "10.00", paid_on=date(YIL, AY, gun))
    veri = await _akis(client, admin_headers, year=YIL, month=AY)
    assert [k["day"] for k in veri["series"]] == [
        f"{YIL}-{AY:02d}-{gun:02d}" for gun in range(1, 26)
    ]


async def test_yalniz_CIKIS_olan_gunde_giris_SIFIR(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers,
    fatura_fabrikasi,
    hesap_fabrikasi,
    fatura_odemesi,
) -> None:
    """🔴 TEK YÖNLÜ GÜN — `CASE`in `else_`ini kaybeden uygulamayı öldüren test.

    `else_` yazılmazsa eşleşmeyen satır NULL üretir, `SUM` NULL'ları yutar ve
    yalnız ÇIKIŞ içeren bir günün GİRİŞİ `0` değil **null** olur. İki yönü de
    aynı güne koyan bir test bunu ASLA göremez — bu yüzden gün tek yönlüdür.
    """
    hesap = await hesap_fabrikasi()
    gelen = await fatura_fabrikasi(
        direction=InvoiceDirection.incoming, status=InvoiceStatus.approved, total="900.00"
    )
    await fatura_odemesi(gelen, hesap, "70.00", paid_on=date(YIL, AY, 6))
    veri = await _akis(client, admin_headers, year=YIL, month=AY)
    kova = veri["series"][0]
    assert kova["inflow"] is not None
    assert Decimal(kova["inflow"]) == Decimal("0")
    assert Decimal(kova["outflow"]) == Decimal("70.00")


async def test_yalniz_GIRIS_olan_gunde_cikis_SIFIR(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers,
    fatura_fabrikasi,
    hesap_fabrikasi,
    fatura_odemesi,
) -> None:
    """`_cikis_tutari`nin aynı kusuru — iki bacak AYRI AYRI sınanır."""
    hesap = await hesap_fabrikasi()
    giden = await fatura_fabrikasi(direction=InvoiceDirection.outgoing, total="900.00")
    await fatura_odemesi(giden, hesap, "70.00", paid_on=date(YIL, AY, 6))
    kova = (await _akis(client, admin_headers, year=YIL, month=AY))["series"][0]
    assert kova["outflow"] is not None
    assert Decimal(kova["outflow"]) == Decimal("0")
    assert Decimal(kova["inflow"]) == Decimal("70.00")


@pytest.mark.parametrize(
    ("ay", "tasan_gun"),
    [
        (4, date(YIL, 5, 1)),  # 30 günlük ay
        (2, date(YIL, 3, 1)),  # 28 günlük ay
        (2, date(YIL, 3, 3)),  # `ilk + 30 gün` yazan uygulamanın tam sızıntısı
    ],
)
async def test_AY_UZUNLUGU_sabit_degil(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers,
    fatura_fabrikasi,
    hesap_fabrikasi,
    fatura_odemesi,
    ay: int,
    tasan_gun: date,
) -> None:
    """🔴 Ay sonu SABİT BİR SAYI DEĞİLDİR (28/29/30/31).

    `ilk + 30 gün` yazan bir uygulama Mayıs ve Aralık'ta DOĞRU sonuç verir —
    yani 31 günlük aylarla yazılmış bir test onu göremez. Nisan'da 1 Mayıs'ı,
    Şubat'ta 1-3 Mart'ı içeri alır ve o günlerin parası yanlış aya yazılır.
    """
    hesap = await hesap_fabrikasi()
    giden = await fatura_fabrikasi(direction=InvoiceDirection.outgoing, total="900.00")
    await fatura_odemesi(giden, hesap, "10.00", paid_on=tasan_gun)
    veri = await _akis(client, admin_headers, year=YIL, month=ay)
    assert veri["series"] == []
    assert Decimal(veri["inflow_total"]) == Decimal("0")


# --- Ay penceresi ----------------------------------------------------------


@pytest.mark.parametrize(
    ("gun", "icerde"),
    [
        (date(YIL, AY - 1, 30), False),
        (date(YIL, AY, 1), True),
        (date(YIL, AY, 31), True),
        (date(YIL, AY + 1, 1), False),
    ],
)
async def test_ay_sinirlari_KAPALI(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers,
    fatura_fabrikasi,
    hesap_fabrikasi,
    fatura_odemesi,
    gun: date,
    icerde: bool,
) -> None:
    """Ayın ilk ve son günü DAHİL, komşu ayların günleri HARİÇ.

    Son gün "bir sonraki ayın 1'inden bir gün önce" olarak bulunur
    (`invoicing.summary.current_month_bounds` dersi): `month + 1` aritmetiği
    Aralık'ta yılı taşırdı.
    """
    hesap = await hesap_fabrikasi()
    giden = await fatura_fabrikasi(direction=InvoiceDirection.outgoing, total="900.00")
    await fatura_odemesi(giden, hesap, "10.00", paid_on=gun)
    veri = await _akis(client, admin_headers, year=YIL, month=AY)
    assert bool(veri["series"]) is icerde


async def test_aralik_ayinda_yil_TASMAZ(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers,
    fatura_fabrikasi,
    hesap_fabrikasi,
    fatura_odemesi,
) -> None:
    """Aralık penceresi 31 Aralık'ta biter; `month + 1` yazan bir uygulama
    burada ya çöker ya 1 Ocak'ı içeri alır."""
    hesap = await hesap_fabrikasi()
    giden = await fatura_fabrikasi(direction=InvoiceDirection.outgoing, total="900.00")
    await fatura_odemesi(giden, hesap, "10.00", paid_on=date(YIL, 12, 31))
    await fatura_odemesi(giden, hesap, "20.00", paid_on=date(YIL + 1, 1, 1))
    veri = await _akis(client, admin_headers, year=YIL, month=12)
    assert len(veri["series"]) == 1
    assert Decimal(veri["inflow_total"]) == Decimal("10.00")


# --- Toplamlar seriyle TUTARLI --------------------------------------------


async def test_toplamlar_SERININ_toplamidir(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers,
    fatura_fabrikasi,
    hesap_fabrikasi,
    fatura_odemesi,
) -> None:
    """İki ayrı sorgu (seri + toplam) AYNI süzgeç gövdesinden geçer.

    Süzgeç kopyası açılsaydı grafik ile altındaki iki rakam (E9:104-105)
    zamanla ayrışır ve hangisinin doğru olduğu anlaşılamazdı.
    """
    hesap = await hesap_fabrikasi()
    giden = await fatura_fabrikasi(direction=InvoiceDirection.outgoing, total="9000.00")
    gelen = await fatura_fabrikasi(
        direction=InvoiceDirection.incoming, status=InvoiceStatus.approved, total="9000.00"
    )
    for gun in (2, 9, 17):
        await fatura_odemesi(giden, hesap, "100.00", paid_on=date(YIL, AY, gun))
        await fatura_odemesi(gelen, hesap, "40.00", paid_on=date(YIL, AY, gun))
    veri = await _akis(client, admin_headers, year=YIL, month=AY)
    assert Decimal(veri["inflow_total"]) == sum(
        (Decimal(k["inflow"]) for k in veri["series"]), Decimal("0")
    )
    assert Decimal(veri["outflow_total"]) == sum(
        (Decimal(k["outflow"]) for k in veri["series"]), Decimal("0")
    )
    assert Decimal(veri["inflow_total"]) == Decimal("300.00")
    assert Decimal(veri["outflow_total"]) == Decimal("120.00")


# --- Sıralama garantisi (kara kutuyla ULAŞILAMAZ) --------------------------


async def test_seri_sorgusu_ORDER_BY_TASIR() -> None:
    """🔴 Kayıp bir `ORDER BY` uçtan KANITLANAMAZ.

    PostgreSQL sıralamasız bir `GROUP BY`ı küçük kümede `GroupAggregate` ile
    çözer ve satırları yine artan verir — 25 günlük bir kara kutu testi bile
    yeşil kalır (ölçüldü: mutasyon HAYATTA KALDI). Garanti ancak ifadenin
    KENDİSİNDE denetlenebilir; bu yüzden `series_statement` dışa açıktır.
    """
    sql = str(cash_flow.series_statement(date(YIL, AY, 1), date(YIL, AY, 31)))
    assert "ORDER BY" in sql
    assert "GROUP BY" in sql


# --- Kapsam kararı ---------------------------------------------------------


async def test_kapsam_suzgeci_UYGULANMAZ(
    client: AsyncClient,
    seeded_db: AsyncSession,
    kapsamli_muhasebe_headers,
    fatura_fabrikasi,
    hesap_fabrikasi,
    fatura_odemesi,
    gorunen_proje,
    gorunmeyen_proje,
) -> None:
    """🔴 BİLİNÇLİ KARAR (çivi testi, "unutulmuş süzgeç" DEĞİL).

    Nakit akışı ŞİRKET GENELİ hesapların hareketidir ve aynı kullanıcı aynı
    ekranda bu hesapların TAM bakiyesini zaten okur (K3, uç 1). Süzülseydi
    grafik kartlarla çelişirdi; üstelik seri kimlik SIZDIRMAZ (yalnız günlük
    toplam). `upcoming-payments` bunun TERSİDİR — orada her satır karşı taraf +
    evrak + tutar taşır, o yüzden orası SÜZÜLÜR.
    """
    hesap = await hesap_fabrikasi()
    gorunmeyen_fatura = await fatura_fabrikasi(
        direction=InvoiceDirection.outgoing, total="900.00", project=gorunmeyen_proje
    )
    await fatura_odemesi(gorunmeyen_fatura, hesap, "250.00", paid_on=date(YIL, AY, 8))
    veri = await _akis(client, kapsamli_muhasebe_headers, year=YIL, month=AY)
    assert Decimal(veri["inflow_total"]) == Decimal("250.00")


# --- N+1 -------------------------------------------------------------------


async def test_N_ARTI_1_YAPMAZ(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers,
    fatura_fabrikasi,
    hesap_fabrikasi,
    fatura_odemesi,
) -> None:
    """Sorgu sayısı GÜN sayısından bağımsız — gün başına döngü kuran uygulama
    (31 sorgu) burada patlar."""
    hesap = await hesap_fabrikasi()
    giden = await fatura_fabrikasi(direction=InvoiceDirection.outgoing, total="90000.00")
    await fatura_odemesi(giden, hesap, "10.00", paid_on=date(YIL, AY, 1))
    with _sorgu_sayaci() as az:
        assert len((await _akis(client, admin_headers, year=YIL, month=AY))["series"]) == 1
    for gun in range(2, 21):
        await fatura_odemesi(giden, hesap, "10.00", paid_on=date(YIL, AY, gun))
    with _sorgu_sayaci() as cok:
        assert len((await _akis(client, admin_headers, year=YIL, month=AY))["series"]) == 20
    assert len(cok) == len(az), f"az={len(az)} çok={len(cok)}"
