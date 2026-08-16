"""MT-1 T5 — `GET /cash-flow-statement`: yevmiyeden türeyen A/B/C nakit akışı.

Mockup: `projedesign/Mali Tablo - Nakit Akışı.dc.html` (157 satır).

🔴 **YOL ADI `/treasury/cash-flow`DAN AYRIDIR VE BU BİLİNÇLİDİR.** Mevcut uç
(`treasury/router.py:279`) `payments`+`invoices`ten türeyen **GÜNLÜK giriş/çıkış
serisidir** ve F-HZ ekranında kullanılıyor. Bu uç **yevmiyeden** türeyen
işletme/yatırım/finansman tablosudur (KK-2). İkisi farklı sayı basar ve bu bir
kusur DEĞİLDİR — ayrım her iki docstring'e de yazılıdır (aşağıda testli).

🔴 **HEPSİ HTTP UCUNDAN geçer**; sorgu SAYISI ölçümü çekirdek fonksiyona
doğrudan gider. **Hiçbir fixture mockup rakamlarını KOPYALAMAZ** (MT-K4) —
mockup'ın A bölümü satırları `5.842.000` toplarken ara toplam `6.842.000`
basıyor (NA:71-78, 1.000.000 fark) ve `DÖNEM SONU NAKİT (A+B+C)` etiketi
`4.249.500` (= BL:51 kapanış nakdi) gösteriyor; ikisi de göstermeliktir.

## Dönem modeli BİRİKİMLİ ARALIK — mizanla AYNI pencere

Mockup NA:37: `Ocak–Temmuz 2026`.

    açılış nakdi : entry_date <  {year}-01-01                       → NET
    akış         : {year}-01-01 <= entry_date <= month_end(y, m)
    kapanış nakdi: entry_date <= month_end(y, m)                    → NET

## Akışın türetimi (yön kanıtı)

Dengeli bir fişte `Σ(borç − alacak) = 0`, dolayısıyla
`nakit değişimi = −Σ(nakit olmayan bacaklar) = Σ(alacak − borç)`.
Bu yüzden her NAKİT OLMAYAN bacak, sınıflandırıldığı kaleme `alacak − borç`
katkısı yapar ve toplamları TAM OLARAK nakit değişimine eşittir — dağıtım
(allocation) tahminine gerek YOKTUR.

🔴 Sonucu: kasa→banka transferinin (iki bacak da grup `10`) nakit olmayan
bacağı YOKTUR → hiçbir kaleme katkı vermez, ki net nakit değişimi de sıfırdır.

## Ölçülen kusur sınıfları

1. **Pencere sınırları** — `year-01-01` (açılış/akış ayrımı) ve `month_end`
   (ayın son günü İÇERİDE, ertesi ayın 1'i DIŞARIDA).
2. **Dört alan** — `net_change` (A+B+C) ile `closing_cash` AYRI ŞEYLERDİR;
   mockup ikisini tek satırda birleştirip çelişkiye düşmüştür.
3. **İç transfer** — grup `10` ↔ grup `10` akış ÜRETMEZ.
4. **`monthly_cash`** — akış değil **BAKİYE** serisidir (grafiğin adı
   "Aylık Nakit Pozisyonu", NA:109).
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounting import cash_flow_statement
from app.modules.accounting.models import ChartAccountType, JournalEntryStatus
from tests.conftest import test_engine

YOL = "/cash-flow-statement"

_T = ChartAccountType


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


async def _tablo(
    client: AsyncClient, headers: dict[str, str], year: int = 2026, month: int = 7
) -> dict:
    resp = await client.get(YOL, params={"year": year, "month": month}, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _kalem(govde: dict, key: str) -> dict:
    for bolum in govde["sections"]:
        for satir in bolum["lines"]:
            if satir["key"] == key:
                return satir
    raise AssertionError(f"{key} kalemi yanıtta yok")


def _tutar(govde: dict, key: str) -> Decimal:
    return Decimal(_kalem(govde, key)["amount"])


def _bolum(govde: dict, key: str) -> dict:
    for b in govde["sections"]:
        if b["key"] == key:
            return b
    raise AssertionError(f"{key} bölümü yanıtta yok")


async def _kasa(hesap_fabrikasi):  # noqa: ANN001, ANN202
    return await hesap_fabrikasi("100", name="Kasa", account_type=_T.asset)


# --------------------------------------------------------------------------- #
# 1. Kapılar
# --------------------------------------------------------------------------- #


async def test_yetkisiz_rol_403(client: AsyncClient, yetkisiz_headers: dict[str, str]) -> None:
    resp = await client.get(YOL, params={"year": 2026, "month": 7}, headers=yetkisiz_headers)
    assert resp.status_code == 403, resp.text


async def test_view_seviyesi_YETER(client: AsyncClient, pm_headers: dict[str, str]) -> None:
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
        pytest.param({"year": 1999, "month": 7}, id="year-alt"),
        pytest.param({"year": 2101, "month": 7}, id="year-ust"),
        pytest.param({"year": 2026, "month": 0}, id="month-alt"),
        pytest.param({"year": 2026, "month": 13}, id="month-ust"),
    ],
)
async def test_donem_bandi_422(
    client: AsyncClient, muhasebe_headers: dict[str, str], params: dict
) -> None:
    """🔴 `year`/`month` ZORUNLUDUR — sunucunun "bugün"ü HİÇ okunmaz. Bant mizan
    ve `accounting_periods` CHECK'leriyle BİREBİR.

    ⚠️ `/treasury/cash-flow` bu ikisini OPSİYONEL tutar ve içinde bulunulan aya
    düşer; bu uç DÜŞMEZ (TB5'in yerel takvim kusuru burada yapısal olarak
    imkânsız)."""
    resp = await client.get(YOL, params=params, headers=muhasebe_headers)
    assert resp.status_code == 422, resp.text


# --------------------------------------------------------------------------- #
# 2. Yapı — mockup NA:64-104 birebir, boş defterde de TAM
# --------------------------------------------------------------------------- #


async def test_bos_defterde_UC_bolum_YEDI_kalem_ve_DORT_alan_SIFIR(
    client: AsyncClient, muhasebe_headers: dict[str, str]
) -> None:
    """MT-K11: boş dönem `0` basar, `null` DEĞİL — iddia HTTP ucundan geçer."""
    govde = await _tablo(client, muhasebe_headers)

    assert (govde["year"], govde["month"]) == (2026, 7)
    assert [b["key"] for b in govde["sections"]] == ["operating", "investing", "financing"]
    kalemler = [s for b in govde["sections"] for s in b["lines"]]
    assert len(kalemler) == 7
    for satir in kalemler:
        assert satir["amount"] is not None, satir["key"]
        assert Decimal(satir["amount"]) == 0, satir["key"]
        assert satir["account_codes"] == []
    for alan in ("net_change", "opening_cash", "closing_cash"):
        assert govde[alan] is not None
        assert Decimal(govde[alan]) == 0, alan
    assert len(govde["monthly_cash"]) == 7
    assert all(Decimal(n["closing_cash"]) == 0 for n in govde["monthly_cash"])


async def test_bolum_ve_kalem_etiketleri_mockup_ile_birebir(
    client: AsyncClient, muhasebe_headers: dict[str, str]
) -> None:
    govde = await _tablo(client, muhasebe_headers)
    assert [b["title"] for b in govde["sections"]] == [
        "A. İŞLETME FAALİYETLERİNDEN NAKİTLER",  # NA:69
        "B. YATIRIM FAALİYETLERİNDEN NAKİTLER",  # NA:82
        "C. FİNANSMAN FAALİYETLERİNDEN NAKİTLER",  # NA:91
    ]
    assert [b["subtotal_label"] for b in govde["sections"]] == [
        "İşletme Faaliyetleri Net Nakit",  # NA:77
        "Yatırım Faaliyetleri Net Nakit",  # NA:86
        "Finansman Faaliyetleri Net Nakit",  # NA:95
    ]
    assert [s["label"] for s in _bolum(govde, "operating")["lines"]] == [
        "Müşterilerden Tahsilat",  # NA:71
        "Tedarikçilere Ödeme",  # NA:72
        "Personele Ödeme",  # NA:73
        "Vergi Ödemesi",  # NA:74
        "Diğer Nakit Çıkışları",  # NA:75
    ]
    assert _kalem(govde, "equipment_purchase")["label"] == "Ekipman Alımı"  # NA:84
    assert _kalem(govde, "loan_repayment")["label"] == "Kredi Geri Ödemesi"  # NA:93


# --------------------------------------------------------------------------- #
# 3. 🔴 KK-2 sınıflandırması — karşı hesabın kod aralığından
# --------------------------------------------------------------------------- #


async def test_KK2_siniflandirmasi_ve_YONLER(
    client: AsyncClient, muhasebe_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    """🔑 KK-2: sınıflandırma KARŞI HESABIN kod aralığından. Yön `alacak − borç`
    olduğu için tahsilat `+`, ödeme `−` çıkar (mockup NA:71-75 işaretleri).

    Beş A kalemi + B + C tek kurulumda; her biri AYRI bir karşı hesap grubudur.
    """
    kasa = await _kasa(hesap_fabrikasi)
    alicilar = await hesap_fabrikasi("120", name="Alıcılar", account_type=_T.asset)
    saticilar = await hesap_fabrikasi("320", name="Satıcılar", account_type=_T.liability)
    uretim = await hesap_fabrikasi("730", name="Genel Üretim Gid.", account_type=_T.expense)
    vergi = await hesap_fabrikasi("360", name="Ödenecek Vergi", account_type=_T.liability)
    pazarlama = await hesap_fabrikasi("760", name="Pazarlama Gid.", account_type=_T.expense)
    tasit = await hesap_fabrikasi("254", name="Taşıt Araçları", account_type=_T.asset)
    kredi = await hesap_fabrikasi("400", name="Banka Kredileri", account_type=_T.liability)

    await fis_fabrikasi([(kasa, "9000.00", "0"), (alicilar, "0", "9000.00")])
    await fis_fabrikasi([(saticilar, "4000.00", "0"), (kasa, "0", "4000.00")])
    await fis_fabrikasi([(uretim, "2500.00", "0"), (kasa, "0", "2500.00")])
    await fis_fabrikasi([(vergi, "600.00", "0"), (kasa, "0", "600.00")])
    await fis_fabrikasi([(pazarlama, "150.00", "0"), (kasa, "0", "150.00")])
    await fis_fabrikasi([(tasit, "1800.00", "0"), (kasa, "0", "1800.00")])
    await fis_fabrikasi([(kredi, "700.00", "0"), (kasa, "0", "700.00")])

    govde = await _tablo(client, muhasebe_headers)

    assert _tutar(govde, "customer_collections") == Decimal("9000.00")  # 12x
    assert _tutar(govde, "supplier_payments") == Decimal("-4000.00")  # 32x
    assert _tutar(govde, "personnel_payments") == Decimal("-2500.00")  # 73x
    assert _tutar(govde, "tax_payments") == Decimal("-600.00")  # 36x
    assert _tutar(govde, "other_operating") == Decimal("-150.00")  # 76x
    assert _tutar(govde, "equipment_purchase") == Decimal("-1800.00")  # 25x
    assert _tutar(govde, "loan_repayment") == Decimal("-700.00")  # 40x

    assert Decimal(_bolum(govde, "operating")["subtotal"]) == Decimal("1750.00")
    assert Decimal(_bolum(govde, "investing")["subtotal"]) == Decimal("-1800.00")
    assert Decimal(_bolum(govde, "financing")["subtotal"]) == Decimal("-700.00")
    assert Decimal(govde["net_change"]) == Decimal("-750.00")
    assert _kalem(govde, "customer_collections")["account_codes"] == ["120"]


async def test_KASA_BANKA_transferi_AKIS_URETMEZ(
    client: AsyncClient, muhasebe_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    """🔴 İç transfer bir nakit AKIŞI DEĞİLDİR: iki bacak da grup `10`dadır ve
    net nakit değişimi SIFIRDIR.

    Sınıflandırıcı grup `10`u karşı bacak olarak DIŞLAMASAYDI aynı hareket hem
    giriş hem çıkış olarak basılır, A bölümü şişer ve `net_change`
    `closing − opening`ten AYRIŞIRDI."""
    kasa = await _kasa(hesap_fabrikasi)
    banka = await hesap_fabrikasi("102", name="Bankalar", account_type=_T.asset)
    await fis_fabrikasi([(banka, "5000.00", "0"), (kasa, "0", "5000.00")])

    govde = await _tablo(client, muhasebe_headers)
    for satir in (s for b in govde["sections"] for s in b["lines"]):
        assert Decimal(satir["amount"]) == 0, satir["key"]
    assert Decimal(govde["net_change"]) == 0


async def test_NAKIT_DOKUNMAYAN_fis_hic_sayilmaz(
    client: AsyncClient, muhasebe_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    """🔴 T6 MUTASYON TURUNUN BULDUĞU KÖR NOKTA — AYRIŞMA NOKTASI şart.

    Vadeli satış fişi (`120`/`600`) nakit hareketi DEĞİLDİR. Ama ilk yazımda bu
    testin tek kurulumu O FİŞTİ ve `EXISTS` süzgeci kaldırıldığında **yeşil
    kaldı**: fişin iki bacağı da (`12` ve `60`) AYNI kaleme düşüyor, biri
    `−7000` öteki `+7000` katkı veriyor ve toplam DEĞİŞMİYOR. Dengeli bir fişin
    bacakları aynı kalemde her zaman birbirini götürür.

    Ayrışma ancak iki bacak **FARKLI BÖLÜMLERE** düştüğünde görünür: nakitsiz
    bir borç transferi (`320` borç / `400` alacak) `A` bölümünü `−5000`,
    `C` bölümünü `+5000` kaydırır — `net_change` yine `0` kaldığı için
    yalnız ARA TOPLAMLAR ele verir.

    *"Test var" ≠ "test bekçilik ediyor"nun nakit akışındaki hâli.*"""
    kasa = await _kasa(hesap_fabrikasi)
    alicilar = await hesap_fabrikasi("120", name="Alıcılar", account_type=_T.asset)
    satis = await hesap_fabrikasi("600", name="Yurt İçi Satışlar", account_type=_T.revenue)
    saticilar = await hesap_fabrikasi("320", name="Satıcılar", account_type=_T.liability)
    kredi = await hesap_fabrikasi("400", name="Banka Kredileri", account_type=_T.liability)

    await fis_fabrikasi([(alicilar, "7000.00", "0"), (satis, "0", "7000.00")])
    # 🔴 AYRIŞMA NOKTASI: nakitsiz, iki bacağı AYRI BÖLÜMDE olan fiş.
    await fis_fabrikasi([(saticilar, "5000.00", "0"), (kredi, "0", "5000.00")])
    await fis_fabrikasi([(kasa, "100.00", "0"), (alicilar, "0", "100.00")])

    govde = await _tablo(client, muhasebe_headers)
    assert _tutar(govde, "customer_collections") == Decimal("100.00")
    assert _tutar(govde, "supplier_payments") == Decimal("0")
    assert _tutar(govde, "loan_repayment") == Decimal("0")
    assert Decimal(_bolum(govde, "operating")["subtotal"]) == Decimal("100.00")
    assert Decimal(_bolum(govde, "financing")["subtotal"]) == Decimal("0")
    assert Decimal(govde["net_change"]) == Decimal("100.00")


async def test_SQL_katmani_grup_10u_KENDISI_eler(
    seeded_db: AsyncSession, hesap_fabrikasi, fis_fabrikasi
) -> None:
    """🔴 T6 MUTASYON TURUNUN BULDUĞU İKİNCİ KÖR NOKTA — SQL katmanı bekçisi.

    Grup `10`un karşı bacak olamayacağı İKİ katmanda birden korunur:
    (1) sorgunun `WHERE`ı grup `10` satırlarını ELER,
    (2) `statement_map.cash_flow_line_for()` grup `10`da `None` döner ve
        Python döngüsü satırı ATLAR.

    İkisi de tek başına yeterlidir — yani **SQL katmanı kaldırılınca HTTP
    ucundan HİÇBİR fark görünmez** (mutasyon turunda ölçüldü: 28/28 yeşil
    kaldı). Bu, MU-1'in "şema katmanı bekçileri suite'e görünmez" dersinin SQL
    kardeşidir: bir katman ötekini MASKELER.

    Bu yüzden SQL katmanının KENDİ bekçisi vardır ve iddia çekirdek `Select`e
    doğrudan gider — HTTP ucundan ölçülemez.
    """
    kasa = await _kasa(hesap_fabrikasi)
    banka = await hesap_fabrikasi("102", name="Bankalar", account_type=_T.asset)
    alicilar = await hesap_fabrikasi("120", name="Alıcılar", account_type=_T.asset)
    await fis_fabrikasi([(kasa, "300.00", "0"), (alicilar, "0", "300.00")])
    await fis_fabrikasi([(banka, "500.00", "0"), (kasa, "0", "500.00")])

    kayitlar = (
        (await seeded_db.execute(cash_flow_statement.select_cash_flow_lines(2026, 7)))
        .mappings()
        .all()
    )
    kodlar = [k["code"] for k in kayitlar]
    assert kodlar == ["120"], f"grup 10 satırları SQL'den geçti: {kodlar}"


async def test_COK_BACAKLI_fiste_nakit_olmayan_bacaklarin_TOPLAMI_dagitilir(
    client: AsyncClient, muhasebe_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    """🔴 Yön kanıtının ayrışma noktası: tek bir fişte İKİ FARKLI kaleme düşen
    karşı bacaklar.

    `320` 800 borç + `360` 200 borç ← `100` 1000 alacak. Tedarikçi kalemi −800,
    vergi kalemi −200 olmalı; toplam −1000 = nakit değişimi. "Fişin ilk karşı
    hesabını al" gibi bir kestirme, ikinci bacağı KAYBEDER ve
    `net_change ≠ closing − opening` olurdu."""
    kasa = await _kasa(hesap_fabrikasi)
    saticilar = await hesap_fabrikasi("320", name="Satıcılar", account_type=_T.liability)
    vergi = await hesap_fabrikasi("360", name="Ödenecek Vergi", account_type=_T.liability)
    await fis_fabrikasi(
        [(saticilar, "800.00", "0"), (vergi, "200.00", "0"), (kasa, "0", "1000.00")]
    )

    govde = await _tablo(client, muhasebe_headers)
    assert _tutar(govde, "supplier_payments") == Decimal("-800.00")
    assert _tutar(govde, "tax_payments") == Decimal("-200.00")
    assert Decimal(govde["net_change"]) == Decimal("-1000.00")
    assert Decimal(govde["closing_cash"]) == Decimal("-1000.00")


async def test_HARITASIZ_karsi_hesap_DIGER_kalemine_duser(
    client: AsyncClient, muhasebe_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    """🔴 Karşı bacağı sınıflandırılamayan bir hareket sessizce düşerse
    `A+B+C ≠ (kapanış − açılış)` olur ve fark HİÇBİR YERDE görünmez.
    Nazım/serbest sınıf hesapları `Diğer Nakit Çıkışları`na düşer."""
    kasa = await _kasa(hesap_fabrikasi)
    nazim = await hesap_fabrikasi("900", name="Borçlu Nazım", account_type=_T.asset)
    await fis_fabrikasi([(nazim, "450.00", "0"), (kasa, "0", "450.00")])

    govde = await _tablo(client, muhasebe_headers)
    assert _tutar(govde, "other_operating") == Decimal("-450.00")
    assert _kalem(govde, "other_operating")["account_codes"] == ["900"]
    assert Decimal(govde["net_change"]) == Decimal("-450.00")


# --------------------------------------------------------------------------- #
# 4. 🔴 PENCERE SINIRLARI — MU-2 T6 dersi
# --------------------------------------------------------------------------- #


async def test_ACILIS_SINIRI_yilin_ilk_gunu_DONEME_aittir(
    client: AsyncClient, muhasebe_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    """🔴 MU-2 T6'nın tam olarak kaçırdığı sınır: `{year}-01-01`.

    31 Aralık'ın hareketi AÇILIŞ NAKDİDİR (akışa girmez); 1 Ocak'ınki DÖNEME
    aittir. Sınır `<=` yapılsaydı 1 Ocak hem açılışa hem döneme sayılır,
    kapanış çift gösterirdi — ve hiçbir "denge" göstergesi bunu söylemezdi."""
    kasa = await _kasa(hesap_fabrikasi)
    alicilar = await hesap_fabrikasi("120", name="Alıcılar", account_type=_T.asset)

    await fis_fabrikasi(
        [(kasa, "2000.00", "0"), (alicilar, "0", "2000.00")], entry_date=date(2025, 12, 31)
    )
    await fis_fabrikasi(
        [(kasa, "300.00", "0"), (alicilar, "0", "300.00")], entry_date=date(2026, 1, 1)
    )

    govde = await _tablo(client, muhasebe_headers)
    assert Decimal(govde["opening_cash"]) == Decimal("2000.00")
    assert _tutar(govde, "customer_collections") == Decimal("300.00")
    assert Decimal(govde["net_change"]) == Decimal("300.00")
    assert Decimal(govde["closing_cash"]) == Decimal("2300.00")


async def test_KAPANIS_SINIRI_ayin_son_gunu_ICERIDE_ertesi_ayin_biri_DISARIDA(
    client: AsyncClient, muhasebe_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    """`month_end` `trial_balance`ten İTHAL EDİLİR (`calendar.monthrange`) —
    ikinci bir ay sonu aritmetiği yazılsaydı biri artık yılı kaçırırdı."""
    kasa = await _kasa(hesap_fabrikasi)
    alicilar = await hesap_fabrikasi("120", name="Alıcılar", account_type=_T.asset)

    await fis_fabrikasi(
        [(kasa, "500.00", "0"), (alicilar, "0", "500.00")], entry_date=date(2026, 7, 31)
    )
    await fis_fabrikasi(
        [(kasa, "900.00", "0"), (alicilar, "0", "900.00")], entry_date=date(2026, 8, 1)
    )

    govde = await _tablo(client, muhasebe_headers, month=7)
    assert _tutar(govde, "customer_collections") == Decimal("500.00")
    assert Decimal(govde["closing_cash"]) == Decimal("500.00")


async def test_SUBAT_ve_ARTIK_YIL_son_gunu(
    client: AsyncClient, muhasebe_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    """28 sabitlenmiş bir uygulama 2028'de 29 Şubat'ı dışarıda bırakır ve o
    günün nakit hareketi sessizce kaybolurdu."""
    kasa = await _kasa(hesap_fabrikasi)
    alicilar = await hesap_fabrikasi("120", name="Alıcılar", account_type=_T.asset)
    await fis_fabrikasi(
        [(kasa, "77.00", "0"), (alicilar, "0", "77.00")], entry_date=date(2028, 2, 29)
    )

    govde = await _tablo(client, muhasebe_headers, year=2028, month=2)
    assert _tutar(govde, "customer_collections") == Decimal("77.00")


# --------------------------------------------------------------------------- #
# 5. 🔴 DÖRT ALAN — mockup'ın çelişkisinin çözümü
# --------------------------------------------------------------------------- #


async def test_net_change_ile_closing_cash_AYRI_SEYLERDIR(
    client: AsyncClient, muhasebe_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    """🔴 MT-K4(b) — ölçülmüş mockup çelişkisi.

    Mockup'ın alt bandı `DÖNEM SONU NAKİT (A+B+C)` **diyor** ama değeri
    `4.249.500`, yani Bilanço'daki `Kasa ve Bankalar` (BL:51) ile BİREBİR aynı —
    bu KAPANIŞ NAKDİDİR. A+B+C ise `4.802.000`dir (NA:58 `Net Nakit Artışı`).
    İkisi ayrı şeydir ve mockup'ta **DÖNEM BAŞI NAKİT satırı EKSİKTİR**
    (türetilen açılış `−552.500` çıkar, imkânsız).

    Uç DÖRDÜNÜ DE döndürür; hangisinin basılacağına frontend karar verir
    (MU-2'nin `carried_forward`ı emsal).

    Kimlik: `closing_cash == opening_cash + net_change`."""
    kasa = await _kasa(hesap_fabrikasi)
    alicilar = await hesap_fabrikasi("120", name="Alıcılar", account_type=_T.asset)

    await fis_fabrikasi(
        [(kasa, "1000.00", "0"), (alicilar, "0", "1000.00")], entry_date=date(2025, 5, 5)
    )
    await fis_fabrikasi(
        [(kasa, "400.00", "0"), (alicilar, "0", "400.00")], entry_date=date(2026, 3, 3)
    )

    govde = await _tablo(client, muhasebe_headers)
    acilis = Decimal(govde["opening_cash"])
    degisim = Decimal(govde["net_change"])
    kapanis = Decimal(govde["closing_cash"])

    assert acilis == Decimal("1000.00")
    assert degisim == Decimal("400.00")
    assert kapanis == Decimal("1400.00")
    assert kapanis == acilis + degisim
    assert kapanis != degisim, "kapanış nakdi ile A+B+C aynı alan olamaz"


async def test_net_change_bolum_ARA_TOPLAMLARININ_toplamidir(
    client: AsyncClient, muhasebe_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    """🔴 K15: ara toplamlar HESAPLANIR, mockup'tan kopyalanmaz. Mockup'ın A
    bölümü satırları `5.842.000` toplarken ara toplam `6.842.000` basıyor
    (NA:71-78) — bu bir SUNUM göstermeliğidir, kural değil."""
    kasa = await _kasa(hesap_fabrikasi)
    alicilar = await hesap_fabrikasi("120", name="Alıcılar", account_type=_T.asset)
    tasit = await hesap_fabrikasi("254", name="Taşıtlar", account_type=_T.asset)
    kredi = await hesap_fabrikasi("400", name="Krediler", account_type=_T.liability)

    await fis_fabrikasi([(kasa, "3000.00", "0"), (alicilar, "0", "3000.00")])
    await fis_fabrikasi([(tasit, "1200.00", "0"), (kasa, "0", "1200.00")])
    await fis_fabrikasi([(kredi, "500.00", "0"), (kasa, "0", "500.00")])

    govde = await _tablo(client, muhasebe_headers)
    ara_toplamlar = sum(Decimal(b["subtotal"]) for b in govde["sections"])
    for bolum in govde["sections"]:
        assert Decimal(bolum["subtotal"]) == sum(Decimal(s["amount"]) for s in bolum["lines"])
    assert Decimal(govde["net_change"]) == ara_toplamlar == Decimal("1300.00")


# --------------------------------------------------------------------------- #
# 6. `monthly_cash` — AKIŞ değil BAKİYE serisi
# --------------------------------------------------------------------------- #


async def test_monthly_cash_AY_SONU_BAKIYESIDIR_kumulatif(
    client: AsyncClient, muhasebe_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    """🔴 Grafiğin adı `Aylık Nakit Pozisyonu`dur (NA:109), "akış" değil: her
    nokta o AYIN SONUNDAKİ nakit BAKİYESİDİR ve açılış nakdini de içerir.

    Aylık AKIŞ basan bir uygulama aynı veriyle bambaşka bir eğri çizerdi ve
    son noktası `closing_cash`e denk GELMEZDİ."""
    kasa = await _kasa(hesap_fabrikasi)
    alicilar = await hesap_fabrikasi("120", name="Alıcılar", account_type=_T.asset)

    await fis_fabrikasi(
        [(kasa, "100.00", "0"), (alicilar, "0", "100.00")], entry_date=date(2025, 11, 1)
    )
    await fis_fabrikasi(
        [(kasa, "20.00", "0"), (alicilar, "0", "20.00")], entry_date=date(2026, 2, 10)
    )
    await fis_fabrikasi(
        [(alicilar, "5.00", "0"), (kasa, "0", "5.00")], entry_date=date(2026, 4, 20)
    )

    govde = await _tablo(client, muhasebe_headers, month=5)
    seri = govde["monthly_cash"]
    assert [(n["year"], n["month"]) for n in seri] == [(2026, m) for m in range(1, 6)]
    assert [Decimal(n["closing_cash"]) for n in seri] == [
        Decimal("100.00"),  # Ocak: yalnız açılış
        Decimal("120.00"),  # Şubat: +20
        Decimal("120.00"),  # Mart: hareket yok, BAKİYE DURUR
        Decimal("115.00"),  # Nisan: −5
        Decimal("115.00"),  # Mayıs
    ]
    assert Decimal(seri[-1]["closing_cash"]) == Decimal(govde["closing_cash"])


async def test_monthly_cash_OCAKTAN_secilen_aya_kadar(
    client: AsyncClient, muhasebe_headers: dict[str, str]
) -> None:
    """Seri her zaman Ocak'tan başlar (NA:122-128 `Oca`…`Tem`) ve seçilen ayda
    biter: `month=1`de TEK nokta vardır."""
    tek = await _tablo(client, muhasebe_headers, month=1)
    assert [(n["year"], n["month"]) for n in tek["monthly_cash"]] == [(2026, 1)]
    tam = await _tablo(client, muhasebe_headers, month=12)
    assert len(tam["monthly_cash"]) == 12


# --------------------------------------------------------------------------- #
# 7. POSTING_STATUSES ve para
# --------------------------------------------------------------------------- #


async def test_draft_GIRMEZ_reversed_GIRER(
    client: AsyncClient, muhasebe_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    """`balance.POSTING_STATUSES` TEK KOPYA — `status == posted` burada da elle
    YAZILMAZ."""
    kasa = await _kasa(hesap_fabrikasi)
    alicilar = await hesap_fabrikasi("120", name="Alıcılar", account_type=_T.asset)

    await fis_fabrikasi(
        [(kasa, "999.00", "0"), (alicilar, "0", "999.00")], status=JournalEntryStatus.draft
    )
    await fis_fabrikasi(
        [(kasa, "250.00", "0"), (alicilar, "0", "250.00")], status=JournalEntryStatus.reversed
    )

    govde = await _tablo(client, muhasebe_headers)
    assert _tutar(govde, "customer_collections") == Decimal("250.00")
    assert Decimal(govde["closing_cash"]) == Decimal("250.00")


async def test_UC_YUVARLAMAZ_kurus_korunur(
    client: AsyncClient, muhasebe_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    """MT-K2: kuruş korunur; yuvarlayan bir uç `net_change`i ara toplamlardan
    ayrıştırırdı."""
    kasa = await _kasa(hesap_fabrikasi)
    alicilar = await hesap_fabrikasi("120", name="Alıcılar", account_type=_T.asset)
    saticilar = await hesap_fabrikasi("320", name="Satıcılar", account_type=_T.liability)

    await fis_fabrikasi([(kasa, "0.33", "0"), (alicilar, "0", "0.33")])
    await fis_fabrikasi([(saticilar, "0.34", "0"), (kasa, "0", "0.34")])

    govde = await _tablo(client, muhasebe_headers)
    assert _tutar(govde, "customer_collections") == Decimal("0.33")
    assert _tutar(govde, "supplier_payments") == Decimal("-0.34")
    assert Decimal(govde["net_change"]) == Decimal("-0.01")


# --------------------------------------------------------------------------- #
# 8. 🔴 `/treasury/cash-flow` ile KARIŞTIRILMAZ
# --------------------------------------------------------------------------- #


def test_IKI_NAKIT_AKISI_ucunun_farki_HER_IKI_docstringde_yazilidir():
    """🔴 "İki nakit akışı farklı sayı basıyor" kusurunun panzehiri.

    `/treasury/cash-flow` `payments`+`invoices`ten türeyen GÜNLÜK giriş/çıkış
    serisidir (F-HZ ekranı); `/cash-flow-statement` YEVMİYEDEN türeyen
    işletme/yatırım/finansman tablosudur (KK-2). Farkı okuyamayan biri
    hangisinin "doğru" olduğunu ASLA anlayamaz — bu yüzden ayrım İKİ dosyada da
    yazılı olmak ZORUNDADIR ve bu test bayatlamayı engeller."""
    from pathlib import Path

    from app.modules.accounting import cash_flow_statement as muhasebe_modulu
    from app.modules.treasury import cash_flow as hazine_modulu

    muhasebe = Path(muhasebe_modulu.__file__).read_text(encoding="utf-8")
    hazine = Path(hazine_modulu.__file__).read_text(encoding="utf-8")

    assert "/treasury/cash-flow" in muhasebe
    assert "cash-flow-statement" in hazine


async def test_yevmiyeden_turer_HAZINE_odemesi_SAYILMAZ(
    client: AsyncClient, muhasebe_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    """🔑 KK-2: `treasury.payments`ten TÜRETİLMEZ. Bilanço ile nakit akışı TEK
    tabandan gelmelidir — iki taban olsaydı `Kasa ve Bankalar` (BL:51) ile
    `DÖNEM SONU NAKİT` sessizce ayrışırdı.

    Yapısal kanıt: modül `treasury`yi HİÇ ithal etmez (döngüsüzlük ölçümü,
    `vat_return.py:92-98` emsali)."""
    import ast
    from pathlib import Path

    from app.modules.accounting import cash_flow_statement as modul

    agac = ast.parse(Path(modul.__file__).read_text(encoding="utf-8"))
    ithal: set[str] = set()
    for dugum in ast.walk(agac):
        if isinstance(dugum, ast.ImportFrom) and dugum.module:
            ithal.add(dugum.module)
        elif isinstance(dugum, ast.Import):
            ithal.update(a.name for a in dugum.names)
    assert not any("treasury" in m for m in ithal), ithal
    assert not any("invoicing" in m for m in ithal), ithal

    kasa = await _kasa(hesap_fabrikasi)
    alicilar = await hesap_fabrikasi("120", name="Alıcılar", account_type=_T.asset)
    await fis_fabrikasi([(kasa, "42.00", "0"), (alicilar, "0", "42.00")])
    govde = await _tablo(client, muhasebe_headers)
    assert Decimal(govde["closing_cash"]) == Decimal("42.00")


# --------------------------------------------------------------------------- #
# 9. N+1
# --------------------------------------------------------------------------- #


async def test_sorgu_sayisi_HESAP_ve_AY_sayisindan_bagimsizdir(
    seeded_db: AsyncSession, hesap_fabrikasi, fis_fabrikasi
) -> None:
    """🔴 `monthly_cash` 12 nokta için 12 sorgu koşan bir uygulama, bir de
    hesap başına döngüye girerse tekdüzen hesap planında patlardı. Ölçüm
    ÇEKİRDEK fonksiyona doğrudan yapılır."""
    kasa = await _kasa(hesap_fabrikasi)
    alicilar = await hesap_fabrikasi("120", name="Alıcılar", account_type=_T.asset)
    await fis_fabrikasi([(kasa, "10.00", "0"), (alicilar, "0", "10.00")])
    await seeded_db.flush()

    with _sorgu_sayaci() as az:
        await cash_flow_statement.build_cash_flow_statement(seeded_db, year=2026, month=1)

    for sira in range(1, 9):
        karsi = await hesap_fabrikasi(f"3{sira}0", name=f"Borç {sira}", account_type=_T.liability)
        await fis_fabrikasi(
            [(karsi, "5.00", "0"), (kasa, "0", "5.00")], entry_date=date(2026, sira, 15)
        )
    await seeded_db.flush()

    with _sorgu_sayaci() as cok:
        await cash_flow_statement.build_cash_flow_statement(seeded_db, year=2026, month=12)

    assert len(az) == len(cok), f"N+1: {len(az)} → {len(cok)}\n" + "\n".join(cok)
    assert len(cok) <= 2, "beklenenden fazla sorgu:\n" + "\n".join(cok)
