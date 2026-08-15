"""MU-2 T4 — `GET /trial-balance` (Mizan): üç pencere, altı kolon, denge iddiası.

Mockup: `projedesign/Muhasebe - Mizan.dc.html` (178 satır).

🔴 **HEPSİ HTTP UCUNDAN geçer** (MU-1 dersi): modeli doğrudan kurup
`session.add()` yapan bir test yetki kapısını, `Query` aralık denetimini ve yanıt
şemasını **ASLA** sınamaz. Tek istisna KURULUM fabrikalarıdır
(`hesap_fabrikasi`, `fis_fabrikasi`); iddia edilen her davranış uçtan ölçülür.
Sorgu SAYISI ölçümü çekirdek fonksiyona doğrudan gider (HTTP katmanı kendi
sorgularını — oturum/izin — ekler ve N+1 sinyalini boğardı).

## Ölçülen kusur sınıfları

1. 🔴 **BRÜT ≠ NET ayrışma noktası** (`test_donem_hareketi_BRUTTUR_*`). Dönem
   hareketini yanlışlıkla NET yazan bir uygulama, yalnız TEK TARAFLI hareketi
   olan hesaplarda doğru sonuç verir ve öteki testlerin hepsini geçer. Ayrışma
   ancak aynı hesapta HEM borç HEM alacak varken görünür (mockup satır 85-86:
   Kasa `2.640.000` **ve** `2.535.200` — ikisi birden doludur).
2. 🔴 **Üç pencerenin sınırları.** Önceki yıl → yalnız AÇILIŞ; aralık içi →
   yalnız DÖNEM; seçilen aydan sonrası → HİÇBİRİ. Üçü ayrı testtir.
3. 🔴 **Ay sonu aritmetiği.** Ayın son günü İÇERİDE, ertesi ayın 1'i DIŞARIDA;
   Şubat ve ARTIK YIL (2028-02-29) ayrıca sınanır (`calendar.monthrange`).
4. 🔴 **`POSTING_STATUSES`** — `draft` GİRMEZ, `reversed` GİRER (çift ters kayıt
   kanonu, `balance.py`).
5. 🔴 **`SIGN` MİZANDA KULLANILMAZ** — `320` Satıcılar (pasif) ALACAK kolonuna
   düşer (mockup satır 128). `balance_column()` uygulansaydı sayı pozitife döner
   ve BORÇ kolonuna yazılırdı.
6. **N+1** — hesap sayısından bağımsız TEK sorgu, `before_cursor_execute` ile
   ÖLÇÜLÜR (`test_mu1_balance.py` emsali).
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounting import trial_balance
from app.modules.accounting.models import ChartAccountType, JournalEntryStatus
from tests.conftest import test_engine

YOL = "/trial-balance"

PARA_ALANLARI = (
    "opening_debit",
    "opening_credit",
    "period_debit",
    "period_credit",
    "closing_debit",
    "closing_credit",
)


@contextmanager
def _sorgu_sayaci() -> Iterator[list[str]]:
    """Sürücüye giden HER ifadeyi toplar (`test_mu1_balance.py` deseni)."""
    ifadeler: list[str] = []

    def kaydet(conn, cursor, statement, parameters, context, executemany) -> None:  # noqa: ANN001
        ifadeler.append(" ".join(statement.split()))

    event.listen(test_engine.sync_engine, "before_cursor_execute", kaydet)
    try:
        yield ifadeler
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", kaydet)


async def _mizan(client: AsyncClient, headers: dict[str, str], **params) -> dict:
    sorgu = {"year": 2026, "month": 7, **params}
    resp = await client.get(YOL, params=sorgu, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _satir(govde: dict, code: str) -> dict:
    eslesen = [s for s in govde["rows"] if s["account_code"] == code]
    assert eslesen, f"{code} satırı yanıtta yok: {[s['account_code'] for s in govde['rows']]}"
    return eslesen[0]


async def _kasa_ve_satici(hesap_fabrikasi):  # noqa: ANN001, ANN202
    kasa = await hesap_fabrikasi("100", name="Kasa", account_type=ChartAccountType.asset)
    satici = await hesap_fabrikasi("320", name="Satıcılar", account_type=ChartAccountType.liability)
    return kasa, satici


# --------------------------------------------------------------------------- #
# 1. Kapılar — izin ve aralık denetimi
# --------------------------------------------------------------------------- #


async def test_yetkisiz_rol_403(client: AsyncClient, yetkisiz_headers: dict[str, str]) -> None:
    """`site_chief` (`accounting=_N`) okumada bile 403 alır."""
    resp = await client.get(YOL, params={"year": 2026, "month": 7}, headers=yetkisiz_headers)
    assert resp.status_code == 403, resp.text


async def test_view_seviyesi_YETER(client: AsyncClient, pm_headers: dict[str, str]) -> None:
    """`project_manager` (`accounting=_V`) mizanı OKUYABİLİR — mizan bir rapordur."""
    resp = await client.get(YOL, params={"year": 2026, "month": 7}, headers=pm_headers)
    assert resp.status_code == 200, resp.text


async def test_kimliksiz_401(client: AsyncClient) -> None:
    resp = await client.get(YOL, params={"year": 2026, "month": 7})
    assert resp.status_code == 401, resp.text


@pytest.mark.parametrize(
    "params",
    [
        pytest.param({"month": 7}, id="year-yok"),
        pytest.param({"year": 2026}, id="month-yok"),
        pytest.param({"year": 1999, "month": 7}, id="year-alt-sinir"),
        pytest.param({"year": 2101, "month": 7}, id="year-ust-sinir"),
        pytest.param({"year": 2026, "month": 0}, id="month-alt-sinir"),
        pytest.param({"year": 2026, "month": 13}, id="month-ust-sinir"),
    ],
)
async def test_aralik_disi_ve_eksik_parametre_422(
    client: AsyncClient, pm_headers: dict[str, str], params: dict
) -> None:
    """🔴 `year`/`month` ZORUNLUDUR — böylece sunucunun "bugün"üne HİÇ ihtiyaç
    olmaz ve TB5'in yerel-takvim kusuru bu uçta YAPISAL OLARAK imkânsızdır."""
    resp = await client.get(YOL, params=params, headers=pm_headers)
    assert resp.status_code == 422, resp.text


# --------------------------------------------------------------------------- #
# 2. 🔴 Üç pencerenin AYRIMI
# --------------------------------------------------------------------------- #


async def test_onceki_yil_fisi_YALNIZ_acilisa_girer(
    client: AsyncClient, pm_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    """Açılış = `entry_date < {year}-01-01`. Dönem hareketine SIZMAZ."""
    kasa, satici = await _kasa_ve_satici(hesap_fabrikasi)
    await fis_fabrikasi(
        [(kasa, "180000.00", "0.00"), (satici, "0.00", "180000.00")],
        entry_date=date(2025, 12, 31),
    )

    govde = await _mizan(client, pm_headers)

    satir = _satir(govde, "100")
    assert Decimal(satir["opening_debit"]) == Decimal("180000.00")
    assert Decimal(satir["opening_credit"]) == Decimal("0.00")
    assert Decimal(satir["period_debit"]) == Decimal("0.00")
    assert Decimal(satir["period_credit"]) == Decimal("0.00")
    assert Decimal(satir["closing_debit"]) == Decimal("180000.00")


async def test_aralik_ici_fis_YALNIZ_donem_hareketine_girer(
    client: AsyncClient, pm_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    """Dönem = `{year}-01-01 … {year}-{month} son günü`. Açılışa SIZMAZ."""
    kasa, satici = await _kasa_ve_satici(hesap_fabrikasi)
    await fis_fabrikasi(
        [(kasa, "1000.00", "0.00"), (satici, "0.00", "1000.00")],
        entry_date=date(2026, 3, 15),
    )

    satir = _satir(await _mizan(client, pm_headers), "100")

    assert Decimal(satir["opening_debit"]) == Decimal("0.00")
    assert Decimal(satir["opening_credit"]) == Decimal("0.00")
    assert Decimal(satir["period_debit"]) == Decimal("1000.00")
    assert Decimal(satir["closing_debit"]) == Decimal("1000.00")


async def test_secilen_aydan_SONRAKI_fis_HICBIR_kolona_girmez(
    client: AsyncClient, pm_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    """🔴 Aralık BİRİKİMLİDİR ama SAĞDAN KAPALIDIR: Ağustos fişi Temmuz mizanında
    ne açılışta ne dönemde ne kapanışta görünür."""
    kasa, satici = await _kasa_ve_satici(hesap_fabrikasi)
    await fis_fabrikasi(
        [(kasa, "5000.00", "0.00"), (satici, "0.00", "5000.00")],
        entry_date=date(2026, 8, 1),
    )

    govde = await _mizan(client, pm_headers)

    assert govde["rows"] == [], f"aralık dışı fiş satır üretti: {govde['rows']}"


async def test_secilen_YILIN_1_OCAGI_ACILISA_DEGIL_yalniz_DONEME_girer(
    client: AsyncClient, pm_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    """🔴 T6 mutasyon boşluğu: açılış penceresi SAĞDAN AÇIKTIR (`<`), kapalı DEĞİL.

    `entry_date < year_start` yerine `<=` yazan bir uygulama seçilen yılın
    **1 Ocak** fişini HEM açılışa HEM döneme sayar: kapanış (`açılış + borç −
    alacak`) o tutarı ÇİFT gösterir ve `is_balanced` yine `True` kaldığı için
    hiçbir banner uyarmaz. Öteki pencere testlerinin hiçbiri bu günü kullanmaz
    (`2025-12-31` · `2026-03-15` · `2026-08-01`), bu yüzden mutasyon T6'ya kadar
    **hayatta kaldı** — sınır günü AYRICA ölçülmek zorundadır.
    """
    kasa, satici = await _kasa_ve_satici(hesap_fabrikasi)
    await fis_fabrikasi(
        [(kasa, "100.00", "0.00"), (satici, "0.00", "100.00")],
        entry_date=date(2026, 1, 1),
    )

    satir = _satir(await _mizan(client, pm_headers), "100")

    assert Decimal(satir["opening_debit"]) == Decimal("0.00")
    assert Decimal(satir["opening_credit"]) == Decimal("0.00")
    assert Decimal(satir["period_debit"]) == Decimal("100.00")
    assert Decimal(satir["closing_debit"]) == Decimal("100.00")


async def test_birikimli_aralik_ocaktan_secilen_aya_kadar_TOPLAR(
    client: AsyncClient, pm_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    """Mockup satır 45: `Ocak–Temmuz 2026` — dönem TEK AY DEĞİL, yılbaşından
    seçilen ayın sonuna kadar olan ARALIKTIR."""
    kasa, satici = await _kasa_ve_satici(hesap_fabrikasi)
    for ay in (1, 4, 7):
        await fis_fabrikasi(
            [(kasa, "100.00", "0.00"), (satici, "0.00", "100.00")],
            entry_date=date(2026, ay, 10),
        )

    satir = _satir(await _mizan(client, pm_headers), "100")

    assert Decimal(satir["period_debit"]) == Decimal("300.00")


# --------------------------------------------------------------------------- #
# 3. 🔴🔴 BRÜT vs NET — bu dosyanın en kritik testi
# --------------------------------------------------------------------------- #


async def test_donem_hareketi_BRUTTUR_iki_taraf_da_dolar_kapanis_TEK_taraflidir(
    client: AsyncClient, pm_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    """🔴 MOCKUP SATIR 83-88 (Kasa) BİREBİR — para formülünün AYRIŞMA NOKTASI.

    Açılış `180.000` / `—` (NET, tek taraf), dönem `2.640.000` **ve**
    `2.535.200` (BRÜT, İKİ TARAF DA DOLU), kapanış `284.800` / `—` (NET).

    Aritmetik: `180.000 + (2.640.000 − 2.535.200) = 284.800` ✅

    Dönem hareketini NET yazan bir uygulama burada `104.800 / 0` basar ve
    ölür — ama tek taraflı hareketi olan hesaplarla kurulmuş her test onu
    GEÇİRİRDİ.
    """
    kasa, satici = await _kasa_ve_satici(hesap_fabrikasi)
    await fis_fabrikasi(
        [(kasa, "180000.00", "0.00"), (satici, "0.00", "180000.00")],
        entry_date=date(2025, 12, 31),
    )
    await fis_fabrikasi(
        [(kasa, "2640000.00", "0.00"), (satici, "0.00", "2640000.00")],
        entry_date=date(2026, 2, 10),
    )
    await fis_fabrikasi(
        [(satici, "2535200.00", "0.00"), (kasa, "0.00", "2535200.00")],
        entry_date=date(2026, 5, 20),
    )

    satir = _satir(await _mizan(client, pm_headers), "100")

    assert Decimal(satir["opening_debit"]) == Decimal("180000.00")
    assert Decimal(satir["opening_credit"]) == Decimal("0.00")
    # 🔴 İKİSİ BİRDEN dolu — brütlük iddiası budur.
    assert Decimal(satir["period_debit"]) == Decimal("2640000.00")
    assert Decimal(satir["period_credit"]) == Decimal("2535200.00")
    # 🔴 Kapanış NET ve TEK TARAFLI.
    assert Decimal(satir["closing_debit"]) == Decimal("284800.00")
    assert Decimal(satir["closing_credit"]) == Decimal("0.00")


async def test_pasif_hesap_kapanista_ALACAK_kolonuna_duser(
    client: AsyncClient, pm_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    """🔴 MOCKUP SATIR 121-128 (`320` Satıcılar) — `SIGN` MİZANDA KULLANILMAZ.

    `−840.000 + (6.120.000 − 7.464.000) = −2.184.000` → **Alacak** `2.184.000`.

    `balance_column()`/`SIGN` uygulansaydı pasif hesabın ham negatif neti
    pozitife döner ve sayı **Borç** kolonuna yazılırdı — mockup satır 127-128 ile
    doğrudan çelişirdi.
    """
    kasa, satici = await _kasa_ve_satici(hesap_fabrikasi)
    await fis_fabrikasi(
        [(kasa, "840000.00", "0.00"), (satici, "0.00", "840000.00")],
        entry_date=date(2025, 11, 30),
    )
    await fis_fabrikasi(
        [(satici, "6120000.00", "0.00"), (kasa, "0.00", "6120000.00")],
        entry_date=date(2026, 3, 1),
    )
    await fis_fabrikasi(
        [(kasa, "7464000.00", "0.00"), (satici, "0.00", "7464000.00")],
        entry_date=date(2026, 6, 1),
    )

    satir = _satir(await _mizan(client, pm_headers), "320")

    assert Decimal(satir["opening_debit"]) == Decimal("0.00")
    assert Decimal(satir["opening_credit"]) == Decimal("840000.00")
    assert Decimal(satir["period_debit"]) == Decimal("6120000.00")
    assert Decimal(satir["period_credit"]) == Decimal("7464000.00")
    assert Decimal(satir["closing_debit"]) == Decimal("0.00")
    assert Decimal(satir["closing_credit"]) == Decimal("2184000.00")


async def test_neti_SIFIR_olan_hesabin_IKI_kolonu_da_sifirdir(
    client: AsyncClient, pm_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    """Mockup satır 133-134 (`391` açılışı): net 0 → İKİ kolon da boş basar.

    Sıfır "borç tarafına" yazılsaydı tfoot toplamı sahte biçimde şişerdi.
    """
    kasa, satici = await _kasa_ve_satici(hesap_fabrikasi)
    await fis_fabrikasi(
        [(kasa, "500.00", "0.00"), (satici, "0.00", "500.00")], entry_date=date(2025, 5, 1)
    )
    await fis_fabrikasi(
        [(satici, "500.00", "0.00"), (kasa, "0.00", "500.00")], entry_date=date(2025, 6, 1)
    )

    satir = _satir(await _mizan(client, pm_headers, include_empty=True), "100")

    assert Decimal(satir["opening_debit"]) == Decimal("0.00")
    assert Decimal(satir["opening_credit"]) == Decimal("0.00")


async def test_hicbir_para_alani_None_DEGIL(
    client: AsyncClient, pm_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    """Boş taraf `0`dır, `null` DEĞİL — `—` bir SUNUM kararıdır (frontend'in işi).

    `null` dönseydi frontend'in her aritmetiği (ve tfoot toplamı) patlardı.
    """
    kasa, satici = await _kasa_ve_satici(hesap_fabrikasi)
    await fis_fabrikasi([(kasa, "1.00", "0.00"), (satici, "0.00", "1.00")])

    govde = await _mizan(client, pm_headers)

    for satir in govde["rows"]:
        for alan in PARA_ALANLARI:
            assert satir[alan] is not None, f"{satir['account_code']}.{alan} null döndü"
    for alan in PARA_ALANLARI:
        assert govde["totals"][alan] is not None


# --------------------------------------------------------------------------- #
# 4. 🔴 Ay sonu sınırı — `calendar.monthrange`
# --------------------------------------------------------------------------- #


async def test_ayin_SON_gunu_iceride_ertesi_ayin_BIRI_disarida(
    client: AsyncClient, pm_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    """31 Temmuz İÇERİDE, 1 Ağustos DIŞARIDA — sınır DAHİLDİR."""
    kasa, satici = await _kasa_ve_satici(hesap_fabrikasi)
    await fis_fabrikasi(
        [(kasa, "31.00", "0.00"), (satici, "0.00", "31.00")], entry_date=date(2026, 7, 31)
    )
    await fis_fabrikasi(
        [(kasa, "99.00", "0.00"), (satici, "0.00", "99.00")], entry_date=date(2026, 8, 1)
    )

    satir = _satir(await _mizan(client, pm_headers), "100")

    assert Decimal(satir["period_debit"]) == Decimal("31.00")


@pytest.mark.parametrize(
    ("year", "son_gun", "ertesi"),
    [
        pytest.param(2026, date(2026, 2, 28), date(2026, 3, 1), id="subat-28"),
        pytest.param(2028, date(2028, 2, 29), date(2028, 3, 1), id="artik-yil-29"),
    ],
)
async def test_subat_ve_ARTIK_YIL_son_gunu_dogru_bulunur(
    client: AsyncClient,
    pm_headers: dict[str, str],
    hesap_fabrikasi,
    fis_fabrikasi,
    year: int,
    son_gun: date,
    ertesi: date,
) -> None:
    """🔴 `calendar.monthrange` bekçisi: 28 sabitlenmiş bir uygulama 2028'de
    29 Şubat'ı DIŞARIDA bırakır ve o günün cirosu mizandan kaybolurdu."""
    kasa, satici = await _kasa_ve_satici(hesap_fabrikasi)
    await fis_fabrikasi([(kasa, "29.00", "0.00"), (satici, "0.00", "29.00")], entry_date=son_gun)
    await fis_fabrikasi([(kasa, "77.00", "0.00"), (satici, "0.00", "77.00")], entry_date=ertesi)

    satir = _satir(await _mizan(client, pm_headers, year=year, month=2), "100")

    assert Decimal(satir["period_debit"]) == Decimal("29.00")
    assert Decimal(satir["closing_debit"]) == Decimal("29.00")


# --------------------------------------------------------------------------- #
# 5. 🔴 `POSTING_STATUSES` — draft GİRMEZ, reversed GİRER
# --------------------------------------------------------------------------- #


async def test_taslak_fis_HICBIR_kolona_girmez(
    client: AsyncClient, pm_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    """`draft` sayılsaydı yarım bırakılmış her fiş mizanı kirletirdi."""
    kasa, satici = await _kasa_ve_satici(hesap_fabrikasi)
    await fis_fabrikasi(
        [(kasa, "1000.00", "0.00"), (satici, "0.00", "1000.00")],
        status=JournalEntryStatus.draft,
        entry_date=date(2026, 4, 1),
    )
    await fis_fabrikasi(
        [(kasa, "1000.00", "0.00"), (satici, "0.00", "1000.00")],
        status=JournalEntryStatus.draft,
        entry_date=date(2025, 4, 1),
    )

    govde = await _mizan(client, pm_headers)

    assert govde["rows"] == [], f"taslak fiş mizana sızdı: {govde['rows']}"


async def test_reversed_fis_kolonlara_GIRER(
    client: AsyncClient, pm_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    """🔴 `reversed` DÜŞMEZ: kayıtlaştırılmış fiş defterden ÇIKMAZ, yalnız ters
    kaydıyla nötrlenir. Düşseydi storno ÇİFT ters kayıt üretirdi."""
    kasa, satici = await _kasa_ve_satici(hesap_fabrikasi)
    await fis_fabrikasi(
        [(kasa, "1000.00", "0.00"), (satici, "0.00", "1000.00")],
        status=JournalEntryStatus.reversed,
        entry_date=date(2026, 4, 1),
    )

    satir = _satir(await _mizan(client, pm_headers), "100")

    assert Decimal(satir["period_debit"]) == Decimal("1000.00")
    assert Decimal(satir["closing_debit"]) == Decimal("1000.00")


# --------------------------------------------------------------------------- #
# 6. Denge iddiası (mockup satır 54-57 banner'ı)
# --------------------------------------------------------------------------- #


async def test_dengeli_defterde_is_balanced_TRUE(
    client: AsyncClient, pm_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    """Her fiş dengeliyse kapanış borç toplamı = kapanış alacak toplamı."""
    kasa, satici = await _kasa_ve_satici(hesap_fabrikasi)
    await fis_fabrikasi(
        [(kasa, "840000.00", "0.00"), (satici, "0.00", "840000.00")],
        entry_date=date(2025, 12, 1),
    )
    await fis_fabrikasi(
        [(kasa, "12000.50", "0.00"), (satici, "0.00", "12000.50")], entry_date=date(2026, 6, 1)
    )

    govde = await _mizan(client, pm_headers)

    assert govde["is_balanced"] is True
    assert Decimal(govde["totals"]["closing_debit"]) == Decimal(govde["totals"]["closing_credit"])
    assert Decimal(govde["totals"]["closing_debit"]) == Decimal("852000.50")


async def test_DENGESIZ_defterde_is_balanced_FALSE(
    client: AsyncClient, pm_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    """🔴 ÖLÇÜM: dengesizlik KURULABİLİR — `ck_journal_entries_posted_balanced`
    yalnız **`status = 'posted'`** için koşar (`status <> 'posted' OR
    total_debit = total_credit`). `reversed` bir fiş tek bacaklı olabilir ve
    CHECK'i geçer.

    Bu, `is_balanced`in bir SÜS olmadığının kanıtıdır: her zaman `True` döndüren
    bir uygulama burada ölür.
    """
    kasa, _ = await _kasa_ve_satici(hesap_fabrikasi)
    await fis_fabrikasi(
        [(kasa, "500.00", "0.00")],
        status=JournalEntryStatus.reversed,
        entry_date=date(2026, 5, 5),
    )

    govde = await _mizan(client, pm_headers)

    assert govde["is_balanced"] is False
    assert Decimal(govde["totals"]["closing_debit"]) == Decimal("500.00")
    assert Decimal(govde["totals"]["closing_credit"]) == Decimal("0.00")


# --------------------------------------------------------------------------- #
# 7. `include_empty` · sıralama · toplamlar
# --------------------------------------------------------------------------- #


async def test_hareketsiz_hesap_VARSAYILANDA_listelenmez(
    client: AsyncClient, pm_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    """Üç pencerenin HİÇBİRİNDE hareketi olmayan hesap mizanı şişirmez —
    mockup'ın 8 satırının hepsi hareketlidir (satır 80-159)."""
    kasa, satici = await _kasa_ve_satici(hesap_fabrikasi)
    await hesap_fabrikasi("191", name="İndirilecek KDV")
    await fis_fabrikasi([(kasa, "10.00", "0.00"), (satici, "0.00", "10.00")])

    kodlar = [s["account_code"] for s in (await _mizan(client, pm_headers))["rows"]]

    assert kodlar == ["100", "320"]


async def test_donem_neti_SIFIR_olan_HAREKETLI_hesap_VARSAYILANDA_da_LISTELENIR(
    client: AsyncClient, pm_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    """🔴 T6 mutasyon boşluğu: varsayılan süzgecin ÜÇ koşulu da GEREKLİDİR.

    Süzgeç `or_(açılış != 0, dönem_borç != 0, dönem_alacak != 0)`tir. Yalnız
    KAPANIŞA (`açılış + borç − alacak`) bakan bir uygulama, borcu alacağına
    EŞİT olan HAREKETLİ bir hesabı mizandan sessizce düşürür: hesap ay içinde
    para görmüştür ama satırı hiç basılmaz.

    `test_neti_SIFIR_olan_hesabin_IKI_kolonu_da_sifirdir` bu deliği KAPATMAZ —
    o test `include_empty=True` ile çağırır ve süzgeç o yolda hiç koşmaz. Bu
    yüzden kapanışa-indirgeyen mutasyon T6'ya kadar **hayatta kaldı**.
    """
    kasa, satici = await _kasa_ve_satici(hesap_fabrikasi)
    await fis_fabrikasi(
        [(kasa, "500.00", "0.00"), (satici, "0.00", "500.00")], entry_date=date(2026, 5, 1)
    )
    await fis_fabrikasi(
        [(satici, "500.00", "0.00"), (kasa, "0.00", "500.00")], entry_date=date(2026, 6, 1)
    )

    govde = await _mizan(client, pm_headers)

    assert [s["account_code"] for s in govde["rows"]] == ["100", "320"], (
        "dönem neti SIFIR olan HAREKETLİ hesap varsayılan mizandan düştü — "
        "süzgeç kapanışa indirgenmiş olabilir"
    )
    satir = _satir(govde, "100")
    assert Decimal(satir["period_debit"]) == Decimal("500.00")
    assert Decimal(satir["period_credit"]) == Decimal("500.00")
    assert Decimal(satir["closing_debit"]) == Decimal("0.00")
    assert Decimal(satir["closing_credit"]) == Decimal("0.00")


async def test_include_empty_true_ile_hareketsiz_hesap_ALTI_KOLONU_SIFIR_gelir(
    client: AsyncClient, pm_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    kasa, satici = await _kasa_ve_satici(hesap_fabrikasi)
    await hesap_fabrikasi("191", name="İndirilecek KDV")
    await fis_fabrikasi([(kasa, "10.00", "0.00"), (satici, "0.00", "10.00")])

    govde = await _mizan(client, pm_headers, include_empty=True)

    satir = _satir(govde, "191")
    for alan in PARA_ALANLARI:
        assert Decimal(satir[alan]) == Decimal("0.00"), f"191.{alan} = {satir[alan]}"
    assert [s["account_code"] for s in govde["rows"]] == ["100", "191", "320"]


async def test_siralama_hesap_kodu_ARTAN(
    client: AsyncClient, pm_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    """Mizan hesap planının sırasını izler; azalan sıra tekdüzen hesap planını
    baştan aşağı okunamaz hâle getirirdi."""
    satici = await hesap_fabrikasi("320", name="Satıcılar", account_type=ChartAccountType.liability)
    for kod in ("730", "100", "391", "120"):
        hesap = await hesap_fabrikasi(kod)
        await fis_fabrikasi(
            [(hesap, "1.00", "0.00"), (satici, "0.00", "1.00")], entry_date=date(2026, 2, 2)
        )

    kodlar = [s["account_code"] for s in (await _mizan(client, pm_headers))["rows"]]

    assert kodlar == ["100", "120", "320", "391", "730"]


async def test_toplamlar_SATIRLARIN_toplamina_esittir(
    client: AsyncClient, pm_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    """tfoot YAPISI: altı kolonun her biri AYRI toplanır (mockup satır 161-171).

    🔴 K15: mockup'ın tfoot RAKAMLARI satırlarıyla çelişir (göstermelik) —
    satırlar kazanır, tfoot'tan yalnız YAPI alınır.
    """
    kasa, satici = await _kasa_ve_satici(hesap_fabrikasi)
    await fis_fabrikasi(
        [(kasa, "700.00", "0.00"), (satici, "0.00", "700.00")], entry_date=date(2025, 9, 9)
    )
    await fis_fabrikasi(
        [(kasa, "250.25", "0.00"), (satici, "0.00", "250.25")], entry_date=date(2026, 1, 9)
    )
    await fis_fabrikasi(
        [(satici, "100.00", "0.00"), (kasa, "0.00", "100.00")], entry_date=date(2026, 2, 9)
    )

    govde = await _mizan(client, pm_headers)

    for alan in PARA_ALANLARI:
        beklenen = sum(Decimal(s[alan]) for s in govde["rows"])
        assert Decimal(govde["totals"][alan]) == beklenen, alan
    assert govde["year"] == 2026
    assert govde["month"] == 7


async def test_sayfalama_ZARFI_YOKTUR(
    client: AsyncClient, pm_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    """🔴 K7 zarfı KULLANILMAZ: tfoot GENEL TOPLAM tüm kümeyi kapsamak
    zorundadır; sayfalanmış bir mizanda toplam ve `is_balanced` anlamsızlaşır."""
    kasa, satici = await _kasa_ve_satici(hesap_fabrikasi)
    await fis_fabrikasi([(kasa, "1.00", "0.00"), (satici, "0.00", "1.00")])

    govde = await _mizan(client, pm_headers)

    assert set(govde) == {"year", "month", "is_balanced", "rows", "totals"}


# --------------------------------------------------------------------------- #
# 8. 🔴 N+1 ÖLÇÜMÜ
# --------------------------------------------------------------------------- #


async def test_hesap_sayisindan_BAGIMSIZ_tek_sorgu(
    seeded_db: AsyncSession, hesap_fabrikasi, fis_fabrikasi
) -> None:
    """2 hesap X sorgu / 22 hesap X sorgu — SAYI EŞİT ve **1** olmalı.

    Hesap başına döngü kuran bir uygulama 200 satırlık tekdüzen hesap planında
    patlardı; tahminle değil `before_cursor_execute` sayacıyla ölçülür.
    """
    kasa, satici = await _kasa_ve_satici(hesap_fabrikasi)
    await fis_fabrikasi(
        [(kasa, "5.00", "0.00"), (satici, "0.00", "5.00")], entry_date=date(2026, 3, 3)
    )

    with _sorgu_sayaci() as ifadeler:
        az = await trial_balance.build_trial_balance(
            seeded_db, year=2026, month=7, include_empty=False
        )
    az_sorgu = len(ifadeler)

    for n in range(20):
        hesap = await hesap_fabrikasi(f"1{n:02d}.01")
        await fis_fabrikasi(
            [(hesap, "5.00", "0.00"), (satici, "0.00", "5.00")], entry_date=date(2026, 3, 3)
        )

    with _sorgu_sayaci() as ifadeler:
        cok = await trial_balance.build_trial_balance(
            seeded_db, year=2026, month=7, include_empty=False
        )
    cok_sorgu = len(ifadeler)

    assert az_sorgu == 1, f"tek sorgu bekleniyordu, {az_sorgu} ifade koştu"
    assert az_sorgu == cok_sorgu, f"N+1: 2 hesap {az_sorgu}, 22 hesap {cok_sorgu} sorgu"
    assert len(az.rows) == 2
    assert len(cok.rows) == 22


def test_ay_sonu_saf_aritmetiktir(monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 `month_end` sunucunun "bugün"üne DOKUNMAZ — saf fonksiyondur.

    Aynı girdi her koşuda aynı çıktıyı verir; TB5'in yerel-takvim kusuru burada
    yapısal olarak imkânsızdır.
    """
    assert trial_balance.month_end(2026, 7) == date(2026, 7, 31)
    assert trial_balance.month_end(2026, 2) == date(2026, 2, 28)
    assert trial_balance.month_end(2028, 2) == date(2028, 2, 29)
    assert trial_balance.month_end(2026, 12) == date(2026, 12, 31)
    assert trial_balance.year_start(2026) == date(2026, 1, 1)
