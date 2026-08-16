"""MT-1 T4 — `GET /balance-sheet` (Bilanço): nokta-zaman, iki taraf, 13 kalem.

Mockup: `projedesign/Mali Tablo - Bilanço.dc.html` (94 satır).

🔴 **HEPSİ HTTP UCUNDAN geçer** (MU-1 §3 dersi): modeli doğrudan kurup
`session.add()` yapan bir test yetki kapısını, `Query` aralık denetimini ve
yanıt şemasını **ASLA** sınamaz. Tek istisna KURULUM fabrikalarıdır
(`hesap_fabrikasi`, `fis_fabrikasi`); iddia edilen her davranış uçtan ölçülür.
Sorgu SAYISI ölçümü çekirdek fonksiyona doğrudan gider (HTTP katmanı kendi
oturum/izin sorgularını ekler ve N+1 sinyalini boğardı).

🔴 **HİÇBİR FIXTURE MOCKUP RAKAMLARINI KOPYALAMAZ (MT-K4/K15).** Mockup'ın
sayıları göstermeliktir ve kendi içinde ÇELİŞİR; buradaki tutarlar testin kendi
aritmetiğidir. Mockup'tan alınan şey YAPI'dır: hangi hesap hangi kaleme düşer.

## Dönem modeli NOKTA-ZAMANDIR

Mockup BL:37 üç ayrı **tek gün** sunuyor (`31 Temmuz 2026` / `30 Haziran 2026` /
`31 Aralık 2025`). Mizanın `year`+`month` birikimli aralığından **FARKLIDIR**:
bilanço `entry_date <= as_of` KÜMÜLATİF NET'tir, önceki yıllar dâhil.

🔴 Tek istisna `Dönem Net Kârı`dır: onun penceresi `year-01-01 <= entry_date <=
as_of` (yılbaşından bugüne). İki pencerenin SINIRLARI ayrı ayrı testlidir —
MU-2'nin T6 dersi (`<` → `<=` mutasyonunu hiçbir test görmemişti) bu dilimde
İKİ KEZ ısırabilirdi.

## Ölçülen kusur sınıfları

1. **`as_of` sınır günü** — `entry_date == as_of` İÇERİDE.
2. **`year-01-01` sınırı** — önceki yılın kârı `Geçmiş Yıllar Kârları`ndadır,
   `Dönem Net Kârı`nda DEĞİL.
3. **`is_balanced` ÖLÇÜLÜR, varsayılmaz** — dengesiz bir `reversed` fiş DB'ye
   girebilir (`ck_journal_entries_posted_balanced` yalnız `posted`ı bağlar).
4. **Kontra netleme** — `257` kaleminden DÜŞÜLÜR; kaldırılırsa denge iki katı
   tutar kayar.
5. **Çift sayım** — `59` grubu gövdeye girmez.
6. **KDV netleştirme yasağı** — `191` aktifte, `391` pasifte.

⚠️ Dosya 800 satır tavanını aşınca BÖLÜNDÜ (`_journal.py` emsali): `Dönem Net
Kârı`, denge, para ve N+1 iddiaları `test_mt1_balance_sheet_kalemler.py`dedir;
kurulum yardımcıları `_balance_sheet.py`de PAYLAŞILIR (kopyalanmadı).
Hiçbir testin iddiası bu bölmeyle değişmedi.
"""

from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient

from tests.modules.accounting._balance_sheet import (
    _T,
    AS_OF,
    YOL,
    _bilanco,
    _bolum,
    _kalem,
    _tutar,
)

# --------------------------------------------------------------------------- #
# 1. Kapılar — izin ve `as_of` bandı
# --------------------------------------------------------------------------- #


async def test_yetkisiz_rol_403(client: AsyncClient, yetkisiz_headers: dict[str, str]) -> None:
    """`site_chief` (`accounting=_N`) okumada bile 403 alır."""
    resp = await client.get(YOL, params={"as_of": AS_OF}, headers=yetkisiz_headers)
    assert resp.status_code == 403, resp.text


async def test_view_seviyesi_YETER(client: AsyncClient, pm_headers: dict[str, str]) -> None:
    """`project_manager` (`accounting=_V`) bilançoyu OKUYABİLİR — bir rapordur."""
    resp = await client.get(YOL, params={"as_of": AS_OF}, headers=pm_headers)
    assert resp.status_code == 200, resp.text


async def test_kimliksiz_401(client: AsyncClient) -> None:
    resp = await client.get(YOL, params={"as_of": AS_OF})
    assert resp.status_code == 401, resp.text


@pytest.mark.parametrize(
    "params",
    [
        pytest.param({}, id="as_of-yok"),
        pytest.param({"as_of": "1999-12-31"}, id="alt-sinir-disi"),
        pytest.param({"as_of": "2101-01-01"}, id="ust-sinir-disi"),
        pytest.param({"as_of": "2026-13-01"}, id="gecersiz-ay"),
        pytest.param({"as_of": "bugun"}, id="tarih-degil"),
    ],
)
async def test_as_of_bandi_422(
    client: AsyncClient, muhasebe_headers: dict[str, str], params: dict
) -> None:
    """🔴 `as_of` ZORUNLUDUR — sunucunun "bugün"ü HİÇ okunmaz (TB5 kusuru
    yapısal olarak imkânsız). Bant `accounting_periods`in yıl CHECK'iyle
    (2000-2100) tutarlıdır: mizanın `_YEAR`/`_MONTH` bantları bir TARİH alanında
    kullanılamaz, bu yüzden burada ayrı yazılır."""
    resp = await client.get(YOL, params=params, headers=muhasebe_headers)
    assert resp.status_code == 422, resp.text


@pytest.mark.parametrize("as_of", ["2000-01-01", "2100-12-31"])
async def test_as_of_bant_SINIRLARI_dahildir(
    client: AsyncClient, muhasebe_headers: dict[str, str], as_of: str
) -> None:
    """Bandın uçları KAPALIDIR — `le`/`ge` yerine `lt`/`gt` yazılsaydı `2100`
    yılının bilançosu hiç alınamazdı."""
    resp = await client.get(YOL, params={"as_of": as_of}, headers=muhasebe_headers)
    assert resp.status_code == 200, resp.text


# --------------------------------------------------------------------------- #
# 2. Yapı — mockup BL:44-88 birebir, boş defterde de TAM
# --------------------------------------------------------------------------- #


async def test_bos_defterde_ONUC_kalem_de_SIFIR_basar_null_DEGIL(
    client: AsyncClient, muhasebe_headers: dict[str, str]
) -> None:
    """🔴 MT-K11: boş taraf `0` basar, `null` DEĞİL — ve iddia **HTTP ucundan**
    geçer (şema katmanı kör noktası). `null` dönseydi ekranın her aritmetiği ve
    genel toplam satırı `null` yayardı.

    ⚠️ Ölçek (`0` mı `0.00` mı) BİLEREK iddia edilmez: `Decimal` metni ondalık
    ölçeği taşır ve boş toplam `Decimal("0")`tır — mizanın `totals`ı da (MU-2)
    aynı biçimi basar. Değer eşitliği iddia edilir, gösterim frontend'e aittir
    (MT-K2: uç YUVARLAMAZ, biçimlemez de)."""
    govde = await _bilanco(client, muhasebe_headers)

    assert govde["as_of"] == AS_OF
    assert govde["is_balanced"] is True
    kalemler = [
        s for t in ("assets", "liabilities") for b in govde[t]["sections"] for s in b["lines"]
    ]
    assert len(kalemler) == 13
    for satir in kalemler:
        assert satir["amount"] is not None, satir["key"]
        assert Decimal(satir["amount"]) == 0, satir["key"]
        assert satir["account_codes"] == []
        assert satir["group_codes"] == []
    for taraf in ("assets", "liabilities"):
        assert govde[taraf]["total"] is not None
        assert Decimal(govde[taraf]["total"]) == 0
        for bolum in govde[taraf]["sections"]:
            assert bolum["subtotal"] is not None
            assert Decimal(bolum["subtotal"]) == 0


async def test_bolum_ve_kalem_etiketleri_mockup_ile_birebir(
    client: AsyncClient, muhasebe_headers: dict[str, str]
) -> None:
    """Etiketler SUNUCUDAN gelir (mizan/KDV emsali): istemci hangi tabloyu
    gördüğünü kendi sabitlerinden değil yanıttan okur."""
    govde = await _bilanco(client, muhasebe_headers)

    assert govde["assets"]["title"] == "AKTİF (Varlıklar)"  # BL:46
    assert govde["assets"]["total_label"] == "AKTİF TOPLAM"  # BL:60
    assert govde["liabilities"]["title"] == "PASİF (Kaynaklar)"  # BL:68
    assert govde["liabilities"]["total_label"] == "PASİF TOPLAM"  # BL:85
    assert [b["title"] for b in govde["assets"]["sections"]] == [
        "I. DÖNEN VARLIKLAR",  # BL:50
        "II. DURAN VARLIKLAR",  # BL:56
    ]
    assert [b["title"] for b in govde["liabilities"]["sections"]] == [
        "I. KISA VADELİ YÜKÜMLÜLÜKLER",  # BL:72
        "II. UZUN VADELİ YÜKÜMLÜLÜKLER",  # BL:77
        "III. ÖZKAYNAKLAR",  # BL:80
    ]
    assert _kalem(govde, "tangible_assets")["label"] == "Maddi Duran Varlıklar (net)"  # BL:57
    assert _kalem(govde, "period_profit")["label"] == "Dönem Net Kârı"  # BL:83


# --------------------------------------------------------------------------- #
# 3. 🔴 NOKTA-ZAMAN PENCERESİ — sınır günü AÇIKÇA kullanılır
# --------------------------------------------------------------------------- #


async def test_as_of_GUNU_DAHILDIR_sinir_gunu(
    client: AsyncClient, muhasebe_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    """🔴 MU-2 T6 DERSİ: pencere sınırı testsiz kalırsa `<=` → `<` mutasyonunu
    HİÇBİR test görmez. Burada fişin tarihi TAM `as_of` günüdür.

    `<` yazılsaydı 31 Temmuz'da kesilen bir fiş 31 Temmuz bilançosunda
    görünmez, ertesi gün belirir — ve kullanıcı sebebini asla anlayamazdı."""
    kasa = await hesap_fabrikasi("100", name="Kasa", account_type=_T.asset)
    sermaye = await hesap_fabrikasi("500", name="Sermaye", account_type=_T.equity)
    await fis_fabrikasi(
        [(kasa, "1500.00", "0"), (sermaye, "0", "1500.00")], entry_date=date(2026, 7, 31)
    )

    govde = await _bilanco(client, muhasebe_headers, as_of="2026-07-31")
    assert _tutar(govde, "cash") == Decimal("1500.00")
    assert _tutar(govde, "paid_in_capital") == Decimal("1500.00")
    assert govde["is_balanced"] is True


async def test_as_of_SONRASI_fis_HARICTIR(
    client: AsyncClient, muhasebe_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    """Ertesi günün fişi DIŞARIDADIR — sınırın öteki yüzü."""
    kasa = await hesap_fabrikasi("100", name="Kasa", account_type=_T.asset)
    sermaye = await hesap_fabrikasi("500", name="Sermaye", account_type=_T.equity)
    await fis_fabrikasi(
        [(kasa, "1500.00", "0"), (sermaye, "0", "1500.00")], entry_date=date(2026, 8, 1)
    )

    govde = await _bilanco(client, muhasebe_headers, as_of="2026-07-31")
    assert _tutar(govde, "cash") == Decimal("0.00")


async def test_pencere_KUMULATIFTIR_onceki_yillar_da_sayilir(
    client: AsyncClient, muhasebe_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    """🔴 Bilanço bir ANLIK GÖRÜNTÜDÜR, mizanın birikimli ARALIĞI değil:
    `2024`te açılan kasa `2026` bilançosunda DURUR.

    Mizanın `year_start` açılış penceresi buraya uygulansaydı geçmiş yılların
    bütün varlıkları sıfırlanır ve `AKTİF ≠ PASİF` olurdu."""
    kasa = await hesap_fabrikasi("100", name="Kasa", account_type=_T.asset)
    sermaye = await hesap_fabrikasi("500", name="Sermaye", account_type=_T.equity)
    await fis_fabrikasi(
        [(kasa, "4000.00", "0"), (sermaye, "0", "4000.00")], entry_date=date(2024, 3, 5)
    )
    await fis_fabrikasi(
        [(kasa, "1000.00", "0"), (sermaye, "0", "1000.00")], entry_date=date(2026, 2, 9)
    )

    govde = await _bilanco(client, muhasebe_headers)
    assert _tutar(govde, "cash") == Decimal("5000.00")
    assert _tutar(govde, "paid_in_capital") == Decimal("5000.00")


# --------------------------------------------------------------------------- #
# 4. 🔴 MT-K1 haritası — hangi hesap hangi kaleme düşer
# --------------------------------------------------------------------------- #


async def test_MTK1_capalari_UCTAN_dogrulanir(
    client: AsyncClient, muhasebe_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    """🔴 Yedi çapanın hepsi tek kurulumda: `10` → Kasa ve Bankalar · `12` →
    Ticari Alacaklar · `15` → Stoklar · `19` → Diğer Dönen Varlıklar ·
    `32` → Ticari Borçlar · `36`+`39` → Vergi Borçları · `25` → MDV (net).

    🔴 `101 Alınan Çekler` de `Kasa ve Bankalar`a düşer: mockup onu HİÇBİR
    satıra koymamış (ölçülmüş tutarsızlık) ama TDHP grubu KAZANIR — hiçbir
    hesap görünmez olamaz.

    Tutarlar testin kendisine aittir; mockup rakamları KOPYALANMAZ (MT-K4).
    """
    kasa = await hesap_fabrikasi("100", name="Kasa", account_type=_T.asset)
    cek = await hesap_fabrikasi("101", name="Alınan Çekler", account_type=_T.asset)
    alicilar = await hesap_fabrikasi("120", name="Alıcılar", account_type=_T.asset)
    stok = await hesap_fabrikasi("150", name="İlk Madde", account_type=_T.asset)
    indirilecek = await hesap_fabrikasi("191", name="İndirilecek KDV", account_type=_T.asset)
    saticilar = await hesap_fabrikasi("320", name="Satıcılar", account_type=_T.liability)
    odenecek = await hesap_fabrikasi("360", name="Ödenecek Vergi", account_type=_T.liability)
    hesaplanan = await hesap_fabrikasi("391", name="Hesaplanan KDV", account_type=_T.liability)

    await fis_fabrikasi(
        [
            (kasa, "300.00", "0"),
            (cek, "700.00", "0"),
            (alicilar, "1200.00", "0"),
            (stok, "900.00", "0"),
            (indirilecek, "100.00", "0"),
            (saticilar, "0", "1600.00"),
            (odenecek, "0", "500.00"),
            (hesaplanan, "0", "1100.00"),
        ]
    )
    govde = await _bilanco(client, muhasebe_headers)

    assert _tutar(govde, "cash") == Decimal("1000.00")  # 100 + 101
    assert _tutar(govde, "trade_receivables") == Decimal("1200.00")
    assert _tutar(govde, "inventory") == Decimal("900.00")
    assert _tutar(govde, "other_current_assets") == Decimal("100.00")  # 191
    assert _tutar(govde, "trade_payables") == Decimal("1600.00")
    assert _tutar(govde, "tax_payables") == Decimal("1600.00")  # 360 + 391
    assert govde["is_balanced"] is True
    assert sorted(_kalem(govde, "cash")["account_codes"]) == ["100", "101"]
    assert _kalem(govde, "cash")["group_codes"] == ["10"]


async def test_KDV_NETLESTIRILMEZ_191_aktifte_391_pasifte(
    client: AsyncClient, muhasebe_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    """🔴 MT-K1/1: netleştirme bir MALİ TABLO KARARIDIR ve mockup söylemiyor.

    Netleştirilseydi eşit tutarlı bir dönemde iki kalem de sıfırlanır, KDV
    pozisyonu ekrandan tümüyle kaybolurdu."""
    indirilecek = await hesap_fabrikasi("191", name="İndirilecek KDV", account_type=_T.asset)
    hesaplanan = await hesap_fabrikasi("391", name="Hesaplanan KDV", account_type=_T.liability)
    await fis_fabrikasi([(indirilecek, "750.00", "0"), (hesaplanan, "0", "750.00")])

    govde = await _bilanco(client, muhasebe_headers)
    assert _tutar(govde, "other_current_assets") == Decimal("750.00")
    assert _tutar(govde, "tax_payables") == Decimal("750.00")
    assert Decimal(govde["assets"]["total"]) == Decimal("750.00")


async def test_KONTRA_hesap_kaleminden_DUSULUR(
    client: AsyncClient, muhasebe_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    """🔑 KK-1'in ASIL gerekçesi: `257 Birikmiş Amortismanlar (-)` `Maddi Duran
    Varlıklar (net)` kaleminden DÜŞÜLÜR (BL:57 "net" ibaresi).

    🔴 Kontra netleme kaldırılırsa kalem `2 × amortisman` kadar kayar (burada
    2 × 400 = 800) ve `is_balanced` FALSE olur — kusur görünür kalır, sessizce
    yutulmaz."""
    binalar = await hesap_fabrikasi("252", name="Binalar", account_type=_T.asset)
    tasit = await hesap_fabrikasi("254", name="Taşıtlar", account_type=_T.asset)
    amortisman = await hesap_fabrikasi(
        "257", name="Birikmiş Amortismanlar (-)", account_type=_T.liability, is_contra=True
    )
    giderler = await hesap_fabrikasi("770", name="Genel Yönetim Gid.", account_type=_T.expense)
    sermaye = await hesap_fabrikasi("500", name="Sermaye", account_type=_T.equity)

    await fis_fabrikasi(
        [(binalar, "1000.00", "0"), (tasit, "600.00", "0"), (sermaye, "0", "1600.00")]
    )
    await fis_fabrikasi([(giderler, "400.00", "0"), (amortisman, "0", "400.00")])

    govde = await _bilanco(client, muhasebe_headers)
    assert _tutar(govde, "tangible_assets") == Decimal("1200.00")  # 1000 + 600 − 400
    # Amortisman gideri kârı düşürür: 0 gelir − 400 gider = −400.
    assert _tutar(govde, "period_profit") == Decimal("-400.00")
    assert govde["is_balanced"] is True
    assert sorted(_kalem(govde, "tangible_assets")["account_codes"]) == ["252", "254", "257"]


async def test_KONTRA_isaretlenmemis_hesap_DENGEYI_bozar_ve_GORUNUR(
    client: AsyncClient, muhasebe_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    """🔴 `is_contra` bir VERİ kararıdır ve yanlış girilirse sunucu bunu
    GİZLEMEZ: `257` kontra işaretlenmezse alacak bakiyesi kaleme EKLENİR,
    `AKTİF TOPLAM` iki katı amortisman kadar şişer ve `is_balanced` FALSE olur.

    Alternatif tasarım (işareti hep "düş" saymak) veri hatasını sessizce
    yutardı; `is_balanced`in tek işi tam olarak bunu görünür kılmaktır."""
    binalar = await hesap_fabrikasi("252", name="Binalar", account_type=_T.asset)
    amortisman = await hesap_fabrikasi(
        "257", name="Birikmiş Amortismanlar (-)", account_type=_T.liability, is_contra=False
    )
    giderler = await hesap_fabrikasi("770", name="Genel Yönetim Gid.", account_type=_T.expense)
    sermaye = await hesap_fabrikasi("500", name="Sermaye", account_type=_T.equity)

    await fis_fabrikasi([(binalar, "1000.00", "0"), (sermaye, "0", "1000.00")])
    await fis_fabrikasi([(giderler, "400.00", "0"), (amortisman, "0", "400.00")])

    govde = await _bilanco(client, muhasebe_headers)
    assert _tutar(govde, "tangible_assets") == Decimal("1400.00")
    assert govde["is_balanced"] is False


async def test_KONTRA_KURALI_hesabin_DOGAL_YONU_ile_kalemin_TARAFI_karsilastirilir(
    client: AsyncClient, muhasebe_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    """🔴 T7 FINAL REVIEW BULGUSU — `is_contra`nın kuralı `(-)` SON EKİ DEĞİLDİR.

    Doğru kural tek cümledir:

    > `is_contra = True` ⟺ hesabın **doğal bakiye yönü** (`SIGN[account_type]`),
    > düştüğü **kalemin tarafının TERSİDİR**.

    `(-)` son ekine bakan bir kural YANLIŞTIR ve `257` dışındaki her kontra
    hesapta işareti ters çevirir:

    | Hesap | Tür | Kalem tarafı | Doğru `is_contra` |
    |---|---|---|---|
    | `257 Birikmiş Amortismanlar (-)` | `liability` (alacak) | AKTİF | **True** |
    | `501 Ödenmemiş Sermaye (-)` | `equity` (alacak) | PASİF | **False** |
    | `580 Geçmiş Yıllar Zararları (-)` | `equity` (alacak) | PASİF | **False** |

    `501`/`580` borç bakiyelidir ve `SIGN[equity] = −1` onları ZATEN negatife
    çevirir — kontra işaretlenirlerse iki kez çevrilir ve sermayeyi DÜŞÜRECEK
    yerde ARTIRIRLAR. Bu kurulumda ölçüldü: yanlış işaretleme `Sermaye`yi
    6.000 yerine 14.000 basar ve `is_balanced` FALSE olur.

    Bu test o iki hesabı DOĞRU (kontrasız) hâlleriyle kurar ve dengenin
    korunduğunu kanıtlar — `257`nin testi ayrıdır."""
    kasa = await hesap_fabrikasi("100", name="Kasa", account_type=_T.asset)
    sermaye = await hesap_fabrikasi("500", name="Ödenmiş Sermaye", account_type=_T.equity)
    odenmemis = await hesap_fabrikasi(
        "501", name="Ödenmemiş Sermaye (-)", account_type=_T.equity, is_contra=False
    )
    zarar = await hesap_fabrikasi(
        "580", name="Geçmiş Yıllar Zararları (-)", account_type=_T.equity, is_contra=False
    )

    await fis_fabrikasi(
        [(kasa, "6000.00", "0"), (odenmemis, "4000.00", "0"), (sermaye, "0", "10000.00")]
    )
    await fis_fabrikasi([(zarar, "1500.00", "0"), (kasa, "0", "1500.00")])

    govde = await _bilanco(client, muhasebe_headers)
    assert _tutar(govde, "cash") == Decimal("4500.00")  # 6000 − 1500
    assert _tutar(govde, "paid_in_capital") == Decimal("6000.00")  # 10000 − 4000
    assert _tutar(govde, "retained_earnings") == Decimal("-1500.00")  # zarar DÜŞER
    assert govde["is_balanced"] is True


async def test_KONTRA_kurali_HARITASIZ_hesabin_TARAFINI_da_belirler(
    client: AsyncClient, muhasebe_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    """🔴 T7 FINAL REVIEW BULGUSU (M3) — yedek kalemin TARAFI `is_contra`yı da
    okumak zorundadır.

    Haritasız (`8x`/`9x`) bir hesabın hangi `Diğer …` kalemine düşeceği, ETKİN
    yönünden (`is_contra × SIGN`) okunur. Yalnız `SIGN`a bakılsaydı kontra
    işaretli bir nazım hesap PASİF kaleme düşer ama katkısı `+net` olurdu —
    denge iki katı tutar kayardı ve sebebi hiçbir kalemde görünmezdi.

    Kurulum: `901` `liability` + kontra → etkin yön BORÇ → AKTİF yedeğine
    düşer ve `+net` katkı verir."""
    kasa = await hesap_fabrikasi("100", name="Kasa", account_type=_T.asset)
    nazim = await hesap_fabrikasi(
        "901", name="Nazım (kontra)", account_type=_T.liability, is_contra=True
    )
    await fis_fabrikasi([(nazim, "800.00", "0"), (kasa, "0", "800.00")])

    govde = await _bilanco(client, muhasebe_headers)
    assert _tutar(govde, "cash") == Decimal("-800.00")
    assert _tutar(govde, "other_current_assets") == Decimal("800.00")
    assert _kalem(govde, "other_short_term_liabilities")["account_codes"] == []
    assert govde["is_balanced"] is True


async def test_HARITASIZ_grup_DIGER_kalemine_duser_ve_kodu_GORUNUR(
    client: AsyncClient, muhasebe_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    """🔴 MT-K1'in en sert kuralı: sessizce düşen hesap `AKTİF ≠ PASİF` yapar ve
    kullanıcı SEBEBİNİ göremez.

    Nazım hesaplar (`900`/`901`) bilançoda kendi kalemine sahip değildir; borçlu
    olan `Diğer Dönen Varlıklar`a, alacaklı olan `Diğer Kısa Vadeli Borçlar`a
    düşer, `account_codes`ta GÖRÜNÜR ve denge KORUNUR."""
    borclu = await hesap_fabrikasi("900", name="Borçlu Nazım", account_type=_T.asset)
    alacakli = await hesap_fabrikasi("901", name="Alacaklı Nazım", account_type=_T.liability)
    await fis_fabrikasi([(borclu, "2500.00", "0"), (alacakli, "0", "2500.00")])

    govde = await _bilanco(client, muhasebe_headers)
    assert _tutar(govde, "other_current_assets") == Decimal("2500.00")
    assert _tutar(govde, "other_short_term_liabilities") == Decimal("2500.00")
    assert _kalem(govde, "other_current_assets")["account_codes"] == ["900"]
    assert _kalem(govde, "other_short_term_liabilities")["account_codes"] == ["901"]
    assert govde["is_balanced"] is True


async def test_OZKAYNAK_kalemleri_ayrisir(
    client: AsyncClient, muhasebe_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    """🔑 KK-1: `equity` türü olmadan `500`/`570` `liability` sayılır ve
    `III. ÖZKAYNAKLAR` bölümü `I. KISA VADELİ`den ayrılamazdı."""
    kasa = await hesap_fabrikasi("100", name="Kasa", account_type=_T.asset)
    sermaye = await hesap_fabrikasi("500", name="Ödenmiş Sermaye", account_type=_T.equity)
    gecmis = await hesap_fabrikasi("570", name="Geçmiş Yıllar Kârları", account_type=_T.equity)
    await fis_fabrikasi(
        [(kasa, "3000.00", "0"), (sermaye, "0", "2000.00"), (gecmis, "0", "1000.00")]
    )

    govde = await _bilanco(client, muhasebe_headers)
    assert _tutar(govde, "paid_in_capital") == Decimal("2000.00")
    assert _tutar(govde, "retained_earnings") == Decimal("1000.00")
    ozkaynak = _bolum(govde, "liabilities", "equity")
    assert Decimal(ozkaynak["subtotal"]) == Decimal("3000.00")
