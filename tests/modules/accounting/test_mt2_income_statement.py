"""MT-2 T7 — `GET /income-statement`: yevmiyeden türeyen Gelir Tablosu.

Mockup: `projedesign/Ekran 11 - Mali Tablo.dc.html` GT:86-147 (ayrı bir
"Gelir Tablosu" dosyası YOKTUR; tablo bu ekranın sol kartıdır).

🔴 **HEPSİ HTTP UCUNDAN geçer**; iki istisna vardır ve ikisi de BİLİNÇLİDİR:
sorgu SAYISI ölçümü ve SQL SINIF SÜZGECİ bekçisi çekirdek `Select`e doğrudan
gider — **iki katman birbirini maskeler** (MT-1 T6 kanonu) ve yalnız uçtan
ölçen bir test o sınıfı GÖREMEZ. Haritanın kendi bekçileri ise DB'siz
`test_mt1_statement_map.py`dedir (T3).

## Ölçülen kusur sınıfları

1. **Kalem izolasyonu** — para BU satıra düştü mü, yoksa harita onu komşuya mı
   yolladı? Altı kalem AYRI AYRI kanıtlanır; toplu bir "toplam tuttu" iddiası
   tamamen yanlış bir eşlemede bile YEŞİL kalırdı.
2. 🔴 **K7 yansıtma** — `710`+`711` fişinde `Malzeme Giderleri` **`0` BASMAZ**.
   Bekçi olmasaydı üretimde sekiz gider kalemi birden sessizce sıfırlanırdı.
3. 🔴 **`0`ın İKİ ANLAMI** — "hiç hareket yok" ile "hareketler birbirini
   götürdü" ayırt edilir; ayıran şey `account_codes`tur.
4. 🔴 **Çapraz tablo** — `DÖNEM KARI` ile Bilanço'nun `Dönem Net Kârı`
   AYRIŞAMAZ (aynı `period_profit()`, TEK KOPYA).
5. **Pencere sınırları** — `year_start` ve `month_end` **TAM O GÜN** içeridedir
   (MU-2 T6 dersi: `<`→`<=` mutasyonunu 31 testin hiçbiri görmemişti çünkü
   hiçbiri SINIR GÜNÜNÜ kullanmıyordu).

## 🔴 "AYNI YEŞİL İKİ ANLAM TAŞIR" — burada bir kez daha

`total_revenue − total_expense == period_profit` iddiası **satır eşlemesi
tamamen yanlış olsa bile YEŞİL kalır**: iki taraf da aynı `nets` kümesinden
türer. Bu dosyada o test VARDIR ama adı ne iddia ettiğini söyler
(`_YAPISAL_KIMLIK_esleme_bekcisi_DEGIL`) ve eşlemenin bekçisi kalem izolasyon
testleridir.
"""

from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounting import income_statement, statement_map
from app.modules.accounting.models import ChartAccount, JournalEntryStatus
from tests.modules.accounting._income_statement import (
    _T,
    AY,
    YIL,
    YOL,
    _bolum,
    _kalem,
    _sorgu_sayaci,
    _tablo,
    _tum_kalemler,
    _tutar,
)

SINIR_BASI = date(YIL, 1, 1)
SINIR_SONU = date(YIL, 7, 31)


async def _karsi(hesap_fabrikasi):  # noqa: ANN001, ANN202
    """Fişin BİLANÇO bacağı — `320 Satıcılar`.

    🔴 Karşı bacak bilinçli olarak SINIF 3'tedir: dengeli bir fişin iki bacağı
    AYNI tabloya düşseydi birbirini götürür ve bekçi kaldırılsa bile test yeşil
    kalırdı (MT-1'in `120`/`600` dersi). İki bacağın FARKLI tablolara düşmesi
    ayrışma noktasıdır.
    """
    return await hesap_fabrikasi("320", name="Satıcılar", account_type=_T.liability)


# --------------------------------------------------------------------------- #
# 1. Kapılar
# --------------------------------------------------------------------------- #


async def test_yetkisiz_rol_403(client: AsyncClient, yetkisiz_headers: dict[str, str]) -> None:
    """`site_chief` — `accounting=_N`: okumada bile 403."""
    resp = await client.get(YOL, params={"year": YIL, "month": AY}, headers=yetkisiz_headers)
    assert resp.status_code == 403, resp.text


async def test_kimliksiz_401(client: AsyncClient) -> None:
    resp = await client.get(YOL, params={"year": YIL, "month": AY})
    assert resp.status_code == 401, resp.text


@pytest.mark.parametrize("rol", ["system_admin", "patron", "accounting", "project_manager"])
async def test_okuma_yetkili_dort_rol_200(
    client: AsyncClient, seeded_db: AsyncSession, user_factory, rol: str
) -> None:
    """🔴 Kapı `accounting` iznidir ve `view` YETER — yeni izin modülü
    AÇILMADI, matris DEĞİŞMEDİ (mizan/bilanço/nakit akışı emsali).

    Dört rol AYRI AYRI koşar: toplu bir "muhasebe görebiliyor" iddiası,
    `project_manager`ı (yalnız `_V` seviyesi) kaybeden bir bağımlılık
    değişimini göremezdi.
    """
    await user_factory(email=f"{rol}@gelirtablosu.co", password="parola1234", role_key=rol)
    giris = await client.post(
        "/auth/login", json={"email": f"{rol}@gelirtablosu.co", "password": "parola1234"}
    )
    assert giris.status_code == 200, giris.text
    baslik = {"Authorization": f"Bearer {giris.json()['access_token']}"}
    resp = await client.get(YOL, params={"year": YIL, "month": AY}, headers=baslik)
    assert resp.status_code == 200, resp.text


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"year": YIL},
        {"month": AY},
        {"year": 1999, "month": AY},
        {"year": 2101, "month": AY},
        {"year": YIL, "month": 0},
        {"year": YIL, "month": 13},
    ],
)
async def test_year_ve_month_ZORUNLU_ve_BANTLI_422(
    client: AsyncClient, muhasebe_headers: dict[str, str], params: dict
) -> None:
    """🔴 VARSAYILAN YOL YOKTUR (TB5 yerel-takvim kusuru): sunucunun "bugün"ünü
    okuyan bir varsayılan, TR gecesinde bir gün ve ayın ilk gecesinde bir AY
    geride kalır; kullanıcı hangi tabloya baktığını bilemez.

    Bant `accounting_periods` CHECK'leriyle BİREBİR — takvimin iki uçta farklı
    aralık kabul etmesi, kapatılabilen ama tablosu alınamayan bir dönem
    üretirdi. Sınırlar KAPALIDIR: `2100` ve `12` GEÇERLİDİR (aşağıda).
    """
    resp = await client.get(YOL, params=params, headers=muhasebe_headers)
    assert resp.status_code == 422, resp.text


@pytest.mark.parametrize(("year", "month"), [(2000, 1), (2100, 12)])
async def test_bant_SINIRLARI_kapalidir_200(
    client: AsyncClient, muhasebe_headers: dict[str, str], year: int, month: int
) -> None:
    """`lt`/`gt` yazılsaydı `2100` yılının ya da Aralık ayının gelir tablosu HİÇ
    alınamazdı."""
    resp = await client.get(YOL, params={"year": year, "month": month}, headers=muhasebe_headers)
    assert resp.status_code == 200, resp.text


async def test_donem_KILIDI_okumayi_engellemez(
    client: AsyncClient, muhasebe_headers: dict[str, str], donem_fabrikasi
) -> None:
    """🔴 Dönem kilidi HİÇ okunmaz: okumalar denetlenmez (WORKFLOW kuralı) ve
    kapalı bir dönemin gelir tablosu ile açığınki arasında fark YOKTUR. Mockup
    da rozet çizmiyor."""
    await donem_fabrikasi(YIL, AY)
    resp = await client.get(YOL, params={"year": YIL, "month": AY}, headers=muhasebe_headers)
    assert resp.status_code == 200, resp.text


# --------------------------------------------------------------------------- #
# 2. Yapı — mockup GT:93-143 BİREBİR
# --------------------------------------------------------------------------- #


async def test_bos_defterde_IKI_bolum_ALTI_kalem_ve_hepsi_SIFIR(
    client: AsyncClient, muhasebe_headers: dict[str, str]
) -> None:
    """🔴 K1: yapı VERİDEN bağımsızdır. Hareketsiz kalem `0` basar, `null`
    DEĞİL ve listeden DÜŞMEZ — aksi hâlde ekranın satır sayısı veriye göre
    oynardı ve mockup'ın 6 satırı bazen 3 olurdu.

    `Brüt Satış Kârı` / `Faaliyet Kârı` gibi TDHP ara toplamları YOKTUR:
    mockup onları çizmiyor ve icat edilmiş bir kalem tasarım otoritesini aşar.
    """
    govde = await _tablo(client, muhasebe_headers)
    assert govde["year"] == YIL and govde["month"] == AY
    assert [b["key"] for b in govde["sections"]] == ["revenue", "expenses"]
    assert [b["title"] for b in govde["sections"]] == ["GELİRLER", "GİDERLER"]
    assert [b["subtotal_label"] for b in govde["sections"]] == ["Toplam Gelir", "Toplam Gider"]
    assert [k["label"] for k in govde["sections"][0]["lines"]] == ["İş Hasılatı", "Diğer Gelirler"]
    assert [k["label"] for k in govde["sections"][1]["lines"]] == [
        "Malzeme Giderleri",
        "İşçilik Giderleri",
        "Taşeron Ödemeleri",
        "Genel Giderler",
    ]
    assert govde["profit_label"] == "DÖNEM KARI"  # GT:141
    for anahtar in _tum_kalemler():
        assert _tutar(govde, anahtar) == Decimal("0")
        assert _kalem(govde, anahtar)["account_codes"] == []
    assert Decimal(govde["total_revenue"]) == Decimal("0")
    assert Decimal(govde["total_expense"]) == Decimal("0")
    assert Decimal(govde["period_profit"]) == Decimal("0")


async def test_ARA_TOPLAM_kalemlerinden_hesaplanir(
    client: AsyncClient,
    muhasebe_headers: dict[str, str],
    hesap_fabrikasi,
    fis_fabrikasi,
) -> None:
    """K15: ara toplam mockup'tan KOPYALANMAZ, kalemlerden toplanır — böylece
    "ara toplam ≠ bileşenleri" hâli yapısal olarak imkânsızdır."""
    karsi = await _karsi(hesap_fabrikasi)
    satis = await hesap_fabrikasi("600", account_type=_T.revenue)
    diger = await hesap_fabrikasi("649", account_type=_T.revenue)
    malzeme = await hesap_fabrikasi("710", account_type=_T.expense)
    await fis_fabrikasi([(karsi, "1000.00", "0"), (satis, "0", "1000.00")])
    await fis_fabrikasi([(karsi, "250.00", "0"), (diger, "0", "250.00")])
    await fis_fabrikasi([(malzeme, "400.00", "0"), (karsi, "0", "400.00")])

    govde = await _tablo(client, muhasebe_headers)
    gelirler = _bolum(govde, "revenue")
    giderler = _bolum(govde, "expenses")
    assert (
        Decimal(gelirler["subtotal"])
        == sum((Decimal(k["amount"]) for k in gelirler["lines"]), Decimal("0"))
        == Decimal("1250.00")
    )
    assert (
        Decimal(giderler["subtotal"])
        == sum((Decimal(k["amount"]) for k in giderler["lines"]), Decimal("0"))
        == Decimal("400.00")
    )
    assert Decimal(govde["total_revenue"]) == Decimal("1250.00")
    assert Decimal(govde["total_expense"]) == Decimal("400.00")


# --------------------------------------------------------------------------- #
# 3. 🔴 KALEM İZOLASYONU — para BU satıra düştü mü?
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("kod", "tur", "kalem"),
    [
        ("600", _T.revenue, "construction_revenue"),  # GT:98
        ("649", _T.revenue, "other_revenue"),  # GT:103
        ("671", _T.revenue, "other_revenue"),  # 67 → Diğer Gelirler
        ("710", _T.expense, "material_costs"),  # GT:116
        ("790", _T.expense, "material_costs"),  # 79 (7/B) → Malzeme
        ("720", _T.expense, "labor_costs"),  # GT:121
        ("730", _T.expense, "labor_costs"),  # 73 → İşçilik
        ("740", _T.expense, "subcontractor_costs"),  # GT:126 — K3
        ("770", _T.expense, "general_expenses"),  # GT:131
        ("620", _T.expense, "general_expenses"),  # 62 → Genel (ara toplam icat YOK)
        ("660", _T.expense, "general_expenses"),  # 66 finansman → Genel
    ],
)
async def test_KALEM_IZOLASYONU_para_BU_satira_duser(
    client: AsyncClient,
    muhasebe_headers: dict[str, str],
    hesap_fabrikasi,
    fis_fabrikasi,
    kod: str,
    tur,  # noqa: ANN001
    kalem: str,
) -> None:
    """🔴 Eşlemenin ASIL bekçisi. Tek yönlü bir fişle para bir hesaba konur ve
    ÜÇ şey birden iddia edilir:

    1. tutar TAM O KALEMDE görünür (ve POZİTİFTİR — gelir de gider de),
    2. öteki BEŞ kalem `0` kalır (harita onu komşuya yollamadı),
    3. `account_codes` hesabı LİSTELER — satırın hangi hesaplardan geldiğinin
       tek kanıtı budur ve `Genel Giderler` kovasını şeffaf kılar.

    Toplu bir "toplam tuttu" iddiası üçünü de kaçırırdı: `72`yi `general_
    expenses`e bağlayan bir yazım hatasında `Toplam Gider` YİNE doğru çıkardı.
    """
    karsi = await _karsi(hesap_fabrikasi)
    hesap = await hesap_fabrikasi(kod, account_type=tur)
    gelir_mi = tur is _T.revenue
    satirlar = (
        [(karsi, "700.00", "0"), (hesap, "0", "700.00")]
        if gelir_mi
        else [(hesap, "700.00", "0"), (karsi, "0", "700.00")]
    )
    await fis_fabrikasi(satirlar)

    govde = await _tablo(client, muhasebe_headers)
    assert _tutar(govde, kalem) == Decimal("700.00")
    assert _kalem(govde, kalem)["account_codes"] == [kod]
    for oteki in _tum_kalemler():
        if oteki == kalem:
            continue
        assert _tutar(govde, oteki) == Decimal("0"), f"{oteki} kirlendi"
        assert _kalem(govde, oteki)["account_codes"] == []


async def test_K2_SATIS_INDIRIMI_hasilati_DUSURUR(
    client: AsyncClient,
    muhasebe_headers: dict[str, str],
    hesap_fabrikasi,
    fis_fabrikasi,
) -> None:
    """🔴 K2: grup `61` (`610 Satıştan İadeler`) `İş Hasılatı` kalemine NEGATİF
    katkı verir. Mockup ayrı bir "İndirimler" satırı ÇİZMİYOR ve icat edilmez;
    indirim hasılattan düşer. Ayrı bir kaleme konsaydı `Toplam Gelir` iadeleri
    GELİR sayardı.
    """
    karsi = await _karsi(hesap_fabrikasi)
    satis = await hesap_fabrikasi("600", account_type=_T.revenue)
    iade = await hesap_fabrikasi("610", account_type=_T.expense)
    await fis_fabrikasi([(karsi, "1000.00", "0"), (satis, "0", "1000.00")])
    await fis_fabrikasi([(iade, "150.00", "0"), (karsi, "0", "150.00")])

    govde = await _tablo(client, muhasebe_headers)
    assert _tutar(govde, "construction_revenue") == Decimal("850.00")
    assert _kalem(govde, "construction_revenue")["account_codes"] == ["600", "610"]
    assert _tutar(govde, "general_expenses") == Decimal("0")


# --------------------------------------------------------------------------- #
# 4. 🔴 K7 — YANSITMA BEKÇİSİ
# --------------------------------------------------------------------------- #


async def test_K7_YANSITMA_bekcisi_710_arti_711_fisinde_MALZEME_SIFIR_BASMAZ(
    client: AsyncClient,
    muhasebe_headers: dict[str, str],
    hesap_fabrikasi,
    fis_fabrikasi,
) -> None:
    """🔴 **BU DİLİMİN EN SİNSİ KUSURU.**

    `711 Direkt İlk Madde ve Malzeme Yansıtma Hesabı` `revenue` türündedir
    (ALACAK yönlü) ve KENDİ grubundadır (`71`). Kalem grup olarak toplansaydı
    `710` (borç 900) ile `711` (alacak 900) birbirini götürür ve
    `Malzeme Giderleri` **`0`** basardı — kullanıcı 900 beklerken. Sekiz grupta
    birden olurdu (`70`-`78` + `79`).

    Karar (K7): gider kalemleri yansıtmayı DIŞLAR → satır **BRÜT** gideri
    gösterir. Netleşme `DÖNEM KARI`da, `period_profit()` içinde olur.

    Mutasyon: `_dagit`in `is_cost_reflection` dalı kaldırılırsa satır `0` olur
    ve bu test KIRMIZI'ya döner.
    """
    karsi = await _karsi(hesap_fabrikasi)
    gider = await hesap_fabrikasi("710", account_type=_T.expense)
    yansitma = await hesap_fabrikasi("711", account_type=_T.revenue)
    stok = await hesap_fabrikasi("151", account_type=_T.asset)
    # (1) maliyet kaydı, (2) dönem sonu yansıtma (7/A kapanışı)
    await fis_fabrikasi([(gider, "900.00", "0"), (karsi, "0", "900.00")])
    await fis_fabrikasi([(stok, "900.00", "0"), (yansitma, "0", "900.00")])

    govde = await _tablo(client, muhasebe_headers)
    assert _tutar(govde, "material_costs") == Decimal("900.00"), "yansıtma satırı sıfırladı"
    assert _kalem(govde, "material_costs")["account_codes"] == ["710"], (
        "yansıtma hesabı kod listesine de girmemeli — tutara girmediği hâlde listelenmesi "
        "satırın 900'ü iki hesaptan topladığını iddia ederdi"
    )
    # 🔴 Netleşme `DÖNEM KARI`dadır: `period_profit()` `711`i SAYAR.
    assert Decimal(govde["period_profit"]) == Decimal("0")
    # 🔴 Ve bu yüzden iki taraf AYRIŞIR — bilinçli, `CashFlowStatement`in dört
    # alanı emsal: fark GÖRÜNÜR kalsın diye üç alan da döner.
    assert Decimal(govde["total_revenue"]) - Decimal(govde["total_expense"]) == Decimal("-900.00")


@pytest.mark.parametrize(
    ("gider_kod", "yansitma_kod", "kalem"),
    [
        ("720", "721", "labor_costs"),
        ("740", "741", "subcontractor_costs"),
        ("770", "771", "general_expenses"),
        ("790", "798", "material_costs"),
    ],
)
async def test_K7_yansitma_bekcisi_OTEKI_gruplarda_da_tutar(
    client: AsyncClient,
    muhasebe_headers: dict[str, str],
    hesap_fabrikasi,
    fis_fabrikasi,
    gider_kod: str,
    yansitma_kod: str,
    kalem: str,
) -> None:
    """Kusur `71`e özgü DEĞİLDİR — dört kalemin dördü de aynı tuzağı taşır.
    Yalnız `710`/`711` ile yazılmış bir bekçi, `741`i unutan bir kümede
    `Taşeron Ödemeleri`nin sıfırlandığını göremezdi."""
    karsi = await _karsi(hesap_fabrikasi)
    gider = await hesap_fabrikasi(gider_kod, account_type=_T.expense)
    yansitma = await hesap_fabrikasi(yansitma_kod, account_type=_T.revenue)
    await fis_fabrikasi([(gider, "500.00", "0"), (karsi, "0", "500.00")])
    await fis_fabrikasi([(karsi, "500.00", "0"), (yansitma, "0", "500.00")])

    govde = await _tablo(client, muhasebe_headers)
    assert _tutar(govde, kalem) == Decimal("500.00")
    assert _kalem(govde, kalem)["account_codes"] == [gider_kod]


async def test_SIFIRIN_IKI_ANLAMI_account_codes_ile_AYIRT_EDILIR(
    client: AsyncClient,
    muhasebe_headers: dict[str, str],
    hesap_fabrikasi,
    fis_fabrikasi,
) -> None:
    """🔴 `0` İKİ ANLAMLIDIR: (a) hiç hareket yok, (b) hareketler birbirini
    götürdü. Ayırt eden bekçi yoksa üretimde sessizce yanlış tablo basılır.

    Ayıran şey `account_codes`tur: boşsa (a), doluysa (b). Bu ayrım `_bos_kalem`
    tuzağının (bilanço dersi) gelir tablosu karşılığıdır.
    """
    karsi = await _karsi(hesap_fabrikasi)
    gider = await hesap_fabrikasi("710", account_type=_T.expense)
    # 🔴 İKİSİ DE GİDER hesabıdır (`712` yansıtma DEĞİL, fark hesabıdır) →
    # aynı kaleme düşer ve birbirini götürür.
    fark = await hesap_fabrikasi("712", account_type=_T.expense)
    await fis_fabrikasi([(gider, "300.00", "0"), (karsi, "0", "300.00")])
    await fis_fabrikasi([(karsi, "300.00", "0"), (fark, "0", "300.00")])

    govde = await _tablo(client, muhasebe_headers)
    assert _tutar(govde, "material_costs") == Decimal("0")
    assert _kalem(govde, "material_costs")["account_codes"] == ["710", "712"], (
        "hareket VARDI ama net sıfır — kod listesi boş kalsaydı kullanıcı 'hiç malzeme "
        "gideri yok' sanırdı"
    )
    assert _kalem(govde, "labor_costs")["account_codes"] == []


# --------------------------------------------------------------------------- #
# 5. 🔴 K6 — grup `69` HİÇBİR YERDE sayılmaz
# --------------------------------------------------------------------------- #


async def test_K6_69_grubu_ne_KALEME_ne_DONEM_KARINA_girer(
    client: AsyncClient,
    muhasebe_headers: dict[str, str],
    hesap_fabrikasi,
    fis_fabrikasi,
) -> None:
    """🔴 K6: `690 Dönem Kârı veya Zararı` bir KAPANIŞ AKTARIM hesabıdır.
    `600`in bakiyesi oraya taşınırsa kâr hem `600`den hem `690`dan sayılır ve
    İKİ KATINA çıkardı.

    Ayrışma noktası: kapanış fişinin İKİ bacağı da SINIF 6'dadır (`600`/`690`).
    Karşı bacağı bilançoda olan bir kurulum, `690` sayılsa bile toplamı
    değiştirmezdi ve bekçi kör kalırdı.
    """
    karsi = await _karsi(hesap_fabrikasi)
    satis = await hesap_fabrikasi("600", account_type=_T.revenue)
    kapanis = await hesap_fabrikasi("690", account_type=_T.revenue)
    await fis_fabrikasi([(karsi, "2000.00", "0"), (satis, "0", "2000.00")])
    await fis_fabrikasi([(satis, "2000.00", "0"), (kapanis, "0", "2000.00")])

    govde = await _tablo(client, muhasebe_headers)
    # `600` kapandı (net 0), `690` HİÇ sayılmadı → her şey sıfır.
    for anahtar in _tum_kalemler():
        assert _tutar(govde, anahtar) == Decimal("0"), f"{anahtar} `690`dan beslendi"
    assert _kalem(govde, "general_expenses")["account_codes"] == [], "`690` yedeğe sızdı"
    assert _kalem(govde, "construction_revenue")["account_codes"] == ["600"]
    assert Decimal(govde["period_profit"]) == Decimal("0"), "kâr İKİ KEZ sayıldı"


# --------------------------------------------------------------------------- #
# 6. 🔴 ÇAPRAZ TABLO — Bilanço ile AYRIŞAMAZ
# --------------------------------------------------------------------------- #


async def test_CAPRAZ_TABLO_donem_kari_BILANCONUNKIYLE_birebir(
    client: AsyncClient,
    muhasebe_headers: dict[str, str],
    hesap_fabrikasi,
    fis_fabrikasi,
) -> None:
    """🔴 `/income-statement?year=Y&month=12` `DÖNEM KARI` ==
    `/balance-sheet?as_of=Y-12-31` `Dönem Net Kârı`.

    İkisi `statement_map.period_profit()`in TEK kopyasından gelir; ayrı bir
    formül yazılsaydı iki ekran farklı kâr basar ve hiçbir kolon farkı bunu ele
    VERMEZDİ. Kurulum bilinçli olarak KARMAŞIKTIR (gelir + gider + yansıtma +
    önceki yıl) — tek bir satış fişiyle iki uygulama tesadüfen aynı sayıyı
    verirdi.
    """
    karsi = await _karsi(hesap_fabrikasi)
    satis = await hesap_fabrikasi("600", account_type=_T.revenue)
    gider = await hesap_fabrikasi("710", account_type=_T.expense)
    yansitma = await hesap_fabrikasi("711", account_type=_T.revenue)
    stok = await hesap_fabrikasi("151", account_type=_T.asset)
    await fis_fabrikasi(
        [(karsi, "5000.00", "0"), (satis, "0", "5000.00")], entry_date=date(YIL, 3, 15)
    )
    await fis_fabrikasi(
        [(gider, "1800.00", "0"), (karsi, "0", "1800.00")], entry_date=date(YIL, 11, 2)
    )
    await fis_fabrikasi(
        [(stok, "1800.00", "0"), (yansitma, "0", "1800.00")], entry_date=date(YIL, 12, 31)
    )
    # ÖNCEKİ YIL — gelir tablosunun penceresine GİRMEZ, bilançonun `Geçmiş
    # Yıllar Kârları` kalemine gider. İki uç bu satırda ayrışırsa pencere
    # semantiği kaymış demektir.
    await fis_fabrikasi(
        [(karsi, "999.00", "0"), (satis, "0", "999.00")], entry_date=date(YIL - 1, 6, 1)
    )

    gelir_tablosu = await _tablo(client, muhasebe_headers, year=YIL, month=12)
    bl = await client.get(
        "/balance-sheet", params={"as_of": f"{YIL}-12-31"}, headers=muhasebe_headers
    )
    assert bl.status_code == 200, bl.text
    bilanco_kar = next(
        satir
        for bolum in bl.json()["liabilities"]["sections"]
        for satir in bolum["lines"]
        if satir["key"] == statement_map.PERIOD_PROFIT_LINE
    )
    assert Decimal(gelir_tablosu["period_profit"]) == Decimal(bilanco_kar["amount"])
    assert Decimal(gelir_tablosu["period_profit"]) == Decimal("5000.00")


async def test_YAPISAL_KIMLIK_esleme_bekcisi_DEGIL(
    client: AsyncClient,
    muhasebe_headers: dict[str, str],
    hesap_fabrikasi,
    fis_fabrikasi,
) -> None:
    """🔴 **BU TEST BİR EŞLEME BEKÇİSİ DEĞİLDİR ve adı bunu söyler.**

    `total_revenue − total_expense == period_profit` iddiası, satır eşlemesi
    TAMAMEN yanlış olsa bile yeşil kalır: iki taraf da aynı `nets` kümesinden
    türer. Yine de yazılıdır çünkü YAPISAL bir kimliği kilitler — yansıtma
    YOKKEN iki hesabın ayrışması bir işaret/pencere hatası demektir.

    Eşlemenin gerçek bekçisi `test_KALEM_IZOLASYONU_*`tır.
    """
    karsi = await _karsi(hesap_fabrikasi)
    satis = await hesap_fabrikasi("600", account_type=_T.revenue)
    gider = await hesap_fabrikasi("740", account_type=_T.expense)
    await fis_fabrikasi([(karsi, "3000.00", "0"), (satis, "0", "3000.00")])
    await fis_fabrikasi([(gider, "1250.00", "0"), (karsi, "0", "1250.00")])

    govde = await _tablo(client, muhasebe_headers)
    assert Decimal(govde["total_revenue"]) == Decimal("3000.00")
    assert Decimal(govde["total_expense"]) == Decimal("1250.00")
    assert Decimal(govde["period_profit"]) == Decimal("1750.00")
    assert Decimal(govde["total_revenue"]) - Decimal(govde["total_expense"]) == Decimal(
        govde["period_profit"]
    )


# --------------------------------------------------------------------------- #
# 7. 🔴 PENCERE SINIRLARI — TAM O GÜN
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("gun", "iceride"),
    [
        (date(YIL - 1, 12, 31), False),  # yıl başından BİR GÜN önce
        (SINIR_BASI, True),  # 🔴 `year_start` TAM O GÜN
        (SINIR_SONU, True),  # 🔴 `month_end` TAM O GÜN
        (date(YIL, 8, 1), False),  # ayın sonundan BİR GÜN sonra
    ],
)
async def test_PENCERE_SINIRLARI_tam_o_gun_iceridedir(
    client: AsyncClient,
    muhasebe_headers: dict[str, str],
    hesap_fabrikasi,
    fis_fabrikasi,
    gun: date,
    iceride: bool,
) -> None:
    """🔴 MU-2 T6 dersi: `<`→`<=` mutasyonunu 31 testin hiçbiri GÖRMEMİŞTİ
    çünkü hiçbiri SINIR GÜNÜNÜ kullanmıyordu. Dört gün de tek tek koşar.

    Pencere BİRİKİMLİDİR (GT:90 `Ocak – Temmuz 2026`) ve bilançonun `as_of`
    NOKTA-ZAMANI burada yanlış olurdu: `31 Aralık 2025` fişinin bu yılın
    cirosuna girmemesi bunun kanıtıdır.
    """
    karsi = await _karsi(hesap_fabrikasi)
    satis = await hesap_fabrikasi("600", account_type=_T.revenue)
    await fis_fabrikasi([(karsi, "640.00", "0"), (satis, "0", "640.00")], entry_date=gun)

    govde = await _tablo(client, muhasebe_headers)
    beklenen = Decimal("640.00") if iceride else Decimal("0")
    assert _tutar(govde, "construction_revenue") == beklenen
    assert Decimal(govde["period_profit"]) == beklenen


async def test_SUBAT_artik_yil_son_gunu_iceridedir(
    client: AsyncClient,
    muhasebe_headers: dict[str, str],
    hesap_fabrikasi,
    fis_fabrikasi,
) -> None:
    """`month_end` `calendar.monthrange`ten gelir; 28'e çakılmış bir uygulama
    2028'de 29 Şubat'ın cirosunu sessizce düşürürdü."""
    karsi = await _karsi(hesap_fabrikasi)
    satis = await hesap_fabrikasi("600", account_type=_T.revenue)
    await fis_fabrikasi(
        [(karsi, "77.00", "0"), (satis, "0", "77.00")], entry_date=date(2028, 2, 29)
    )

    govde = await _tablo(client, muhasebe_headers, year=2028, month=2)
    assert _tutar(govde, "construction_revenue") == Decimal("77.00")


@pytest.mark.parametrize(
    ("durum", "sayilir"),
    [
        (JournalEntryStatus.posted, True),
        (JournalEntryStatus.reversed, True),
        (JournalEntryStatus.draft, False),
    ],
)
async def test_POSTING_STATUSES_draft_GIRMEZ_reversed_GIRER(
    client: AsyncClient,
    muhasebe_headers: dict[str, str],
    hesap_fabrikasi,
    fis_fabrikasi,
    durum: JournalEntryStatus,
    sayilir: bool,
) -> None:
    """K3'ün en sinsi tuzağı: kayıtlaştırılmış fiş defterden ÇIKMAZ, yalnız ters
    kaydıyla NÖTRLENİR. `posting_filter()` İTHAL EDİLİR, yeniden yazılmaz."""
    karsi = await _karsi(hesap_fabrikasi)
    satis = await hesap_fabrikasi("600", account_type=_T.revenue)
    await fis_fabrikasi([(karsi, "310.00", "0"), (satis, "0", "310.00")], status=durum)

    govde = await _tablo(client, muhasebe_headers)
    assert _tutar(govde, "construction_revenue") == (Decimal("310.00") if sayilir else Decimal("0"))


async def test_KURUS_hassasiyeti_korunur_YUVARLAMA_YOK(
    client: AsyncClient,
    muhasebe_headers: dict[str, str],
    hesap_fabrikasi,
    fis_fabrikasi,
) -> None:
    """MT-K2: uç YUVARLAMAZ. Yuvarlasaydı ara toplamlar bileşenlerinden sapardı
    ve oran/marj (frontend'in hesapladığı) sistematik olarak kayardı."""
    karsi = await _karsi(hesap_fabrikasi)
    satis = await hesap_fabrikasi("600", account_type=_T.revenue)
    gider = await hesap_fabrikasi("740", account_type=_T.expense)
    await fis_fabrikasi([(karsi, "1000.33", "0"), (satis, "0", "1000.33")])
    await fis_fabrikasi([(gider, "0.67", "0"), (karsi, "0", "0.67")])

    govde = await _tablo(client, muhasebe_headers)
    assert _tutar(govde, "construction_revenue") == Decimal("1000.33")
    assert _tutar(govde, "subcontractor_costs") == Decimal("0.67")
    assert Decimal(govde["period_profit"]) == Decimal("999.66")


# --------------------------------------------------------------------------- #
# 8. 🔴 ÇEKİRDEK `Select` bekçileri — uçtan GÖRÜNMEZLER
# --------------------------------------------------------------------------- #


async def test_N_ARTI_1_YOK_kac_hesap_olursa_olsun_TEK_sorgu(
    seeded_db: AsyncSession, hesap_fabrikasi, fis_fabrikasi
) -> None:
    """Hesap sayısından bağımsız TEK sorgu. Ölçüm tahmine değil
    `before_cursor_execute` sayacına dayanır (`_balance_sheet.py` emsali)."""
    karsi = await _karsi(hesap_fabrikasi)
    for kod, tur in (
        ("600", _T.revenue),
        ("649", _T.revenue),
        ("710", _T.expense),
        ("720", _T.expense),
        ("740", _T.expense),
        ("770", _T.expense),
    ):
        hesap = await hesap_fabrikasi(kod, account_type=tur)
        await fis_fabrikasi([(hesap, "100.00", "0"), (karsi, "0", "100.00")])

    with _sorgu_sayaci() as ifadeler:
        await income_statement.build_income_statement(seeded_db, year=YIL, month=AY)
    secmeler = [i for i in ifadeler if i.upper().startswith("SELECT")]
    assert len(secmeler) == 1, secmeler


async def test_SQL_katmani_YALNIZ_sinif_6_ve_7yi_CEKER(
    seeded_db: AsyncSession, hesap_fabrikasi, fis_fabrikasi
) -> None:
    """🔴 **İKİ KATMAN BİRBİRİNİ MASKELER** (MT-1 T6 kanonu): sınıf süzgeci hem
    SQL'de hem `income_statement_line_for`da vardır. SQL'dekini kaldırmak HTTP
    ucundan HİÇBİR fark üretmez — Python katmanı bilanço hesaplarını yine eler
    ve uç testleri yeşil kalır; ama sorgu ~200 hesabın tamamını çeker.

    Bu yüzden bekçi çekirdek `Select`e İNER ve satırları doğrudan sayar.
    """
    karsi = await _karsi(hesap_fabrikasi)
    kasa = await hesap_fabrikasi("100", account_type=_T.asset)
    satis = await hesap_fabrikasi("600", account_type=_T.revenue)
    await fis_fabrikasi([(kasa, "500.00", "0"), (satis, "0", "500.00")])
    await fis_fabrikasi([(karsi, "500.00", "0"), (kasa, "0", "500.00")])

    kayitlar = (
        (await seeded_db.execute(income_statement.select_income_statement_rows(YIL, AY)))
        .mappings()
        .all()
    )
    assert [k["code"] for k in kayitlar] == ["600"], (
        "SQL sınıf 1-5'i ELEMEDİ — Python katmanı bunu maskeler ve uç yeşil kalırdı"
    )


async def test_hic_yevmiye_satiri_OLMAYAN_hesap_sorguya_GIRMEZ(
    seeded_db: AsyncSession, hesap_fabrikasi
) -> None:
    """`join` INNER'dır ve bu DOĞRUDUR: hareketsiz hesabın katkısı `0`dır.
    Kalem yine de `0` basar (yapı sabittir) — kalem sayısı hesaplara değil
    mockup'a bağlıdır."""
    await hesap_fabrikasi("600", account_type=_T.revenue)
    kayitlar = (
        (await seeded_db.execute(income_statement.select_income_statement_rows(YIL, AY)))
        .mappings()
        .all()
    )
    assert kayitlar == []
    # Hesap DB'de gerçekten var — bekçi boş bir tabloyu ölçmüyor.
    assert (
        await seeded_db.execute(select(ChartAccount).where(ChartAccount.code == "600"))
    ).scalar_one_or_none() is not None
