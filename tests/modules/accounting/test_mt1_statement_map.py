"""MT-1 T3 — `statement_map.py`: TDHP grubu → mali tablo kalemi haritası.

Mockup'lar: `Mali Tablo - Bilanço.dc.html` (BL) · `Mali Tablo - Nakit
Akışı.dc.html` (NA) · `Muhasebe - Hesap Planı.dc.html` (HP).

🔴 **BU DOSYA HTTP UCUNDAN GEÇMEZ ve bu bir istisna DEĞİL, modülün TANIMIDIR:**
`statement_map` SAF bir modüldür (`codes.py` emsali) — DB, Pydantic, `today()`
bilmez. Girdisi bir hesap KODU, çıktısı bir kalem ANAHTARIDIR. Uçtan geçen
iddialar T4/T5'tedir.

## Neden ayrı bir harita modülü

Ölçüldü: repoda kod-aralığı eşleme tablosu **HİÇ YOKTU**; `codes.py` yalnız
`class_code()` (ilk hane) ve `level()` verir. Bilanço, Nakit Akışı **ve ileride
Gelir Tablosu** aynı eşlemeye ihtiyaç duyar; üç yerde ayrı ayrı yazılsaydı biri
`19`u aktifte, öteki pasifte sayar ve `AKTİF ≠ PASİF` çıkardı.

## 🔴 Anahtar İKİ HANELİ GRUPTUR, ilk hane değil

Mockup'ın kalemleri (`Kasa ve Bankalar` · `Ticari Alacaklar` · `Stoklar`) tek
haneyle ayrılamaz: üçü de SINIF 1'dedir (HP:69). `codes.class_code()` bu iş için
yetersizdir ve DEĞİŞTİRİLMEZ — burada kendi türeticisi vardır.

## Ölçülen kusur sınıfları

1. **Görünmezlik** — haritaya girmeyen bir hesap sessizce düşerse `AKTİF ≠ PASİF`
   olur ve kullanıcı sebebini GÖREMEZ. Her kod bir kaleme düşmek zorundadır.
2. **KDV netleştirme** — `19x` (İndirilecek) aktifte, `39x` (Hesaplanan) pasifte
   AYRI kalır. Netleştirme bir mali tablo kararıdır ve mockup söylemiyor.
3. **Çift sayım** — `59` grubu (Dönem Net Kârı) bilanço GÖVDESİNE girmez;
   `Dönem Net Kârı` DAİMA `6xx`/`7xx`ten türer.
4. **Kâr formülünün ayrışma noktası** — `62x Satışların Maliyeti` SINIF 6'dadır
   ama bir GİDERDİR. "Sınıf 6 = gelir" varsayan bir formül onu kâra EKLER.
"""

import ast
import inspect
from decimal import Decimal
from pathlib import Path

import pytest

from app.modules.accounting import statement_map

# --------------------------------------------------------------------------- #
# 0. Saflik — `codes.py` emsali
# --------------------------------------------------------------------------- #


def test_modul_SAFTIR_db_pydantic_takvim_bilmez():
    """🔴 `codes.py` emsali: harita bir METİN dönüşümüdür.

    SQLAlchemy/Pydantic ithal edilseydi modül DB oturumuna ve şema sürümüne
    bağlanır, Gelir Tablosu dilimi onu bağımsız test edemezdi. `datetime`
    yasağı ayrıca K6 (yerel takvim) bekçisinin kardeşidir.
    """
    kaynak = Path(inspect.getsourcefile(statement_map)).read_text(encoding="utf-8")
    agac = ast.parse(kaynak)
    ithal: set[str] = set()
    for dugum in ast.walk(agac):
        if isinstance(dugum, ast.Import):
            ithal.update(ad.name.split(".")[0] for ad in dugum.names)
        elif isinstance(dugum, ast.ImportFrom) and dugum.module:
            ithal.add(dugum.module.split(".")[0])
    for yasak in ("sqlalchemy", "pydantic", "fastapi", "datetime", "app"):
        assert yasak not in ithal, f"saf modül {yasak} ithal ediyor"


# --------------------------------------------------------------------------- #
# 1. `group_of` — UC KOD BICIMI DE calisir
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("code", "beklenen"),
    [
        pytest.param("10", "10", id="grup-NN"),
        pytest.param("100", "10", id="ana-hesap-NNN"),
        pytest.param("120.01", "12", id="alt-hesap-NNN.NN"),
        pytest.param("257", "25", id="kontra-hesap"),
        pytest.param("391", "39", id="hesaplanan-kdv"),
    ],
)
def test_group_of_UC_BICIMDE_de_calisir(code: str, beklenen: str):
    """🔴 `codes.py` üç biçim tanımlar (`NN` · `NNN` · `NNN.NN`) ve haritanın
    anahtarı ÜÇÜNDE DE aynı iki haneyi vermek zorundadır — `120.01` bir yerde
    `12`, başka yerde `120` çıksaydı alt hesabı olan her kalem sessizce
    ikiye bölünürdü."""
    assert statement_map.group_of(code) == beklenen


def test_group_of_gecersiz_kodu_REDDEDER():
    """Kural ihlali HATA olarak çıkar (`codes._require_valid` deseni):
    sessizce `""` dönseydi geçersiz kod bir "grup" gibi haritada dolaşırdı."""
    for kod in ("1", "0120", "1200", "120.01.001", ""):
        with pytest.raises(ValueError):
            statement_map.group_of(kod)


# --------------------------------------------------------------------------- #
# 2. Bilanco yapisi — mockup BL:44-88 birebir
# --------------------------------------------------------------------------- #


def test_bilanco_IKI_TARAF_ve_bes_bolum_basligi_mockup_ile_birebir():
    """Mockup BL:46 (`AKTİF (Varlıklar)`) · BL:68 (`PASİF (Kaynaklar)`) ·
    bölüm bantları BL:50, 56, 72, 77, 80 · genel toplamlar BL:60, 85."""
    aktif, pasif = statement_map.BALANCE_SHEET_SIDES
    assert (aktif.key, aktif.title, aktif.total_label) == (
        "assets",
        "AKTİF (Varlıklar)",
        "AKTİF TOPLAM",
    )
    assert (pasif.key, pasif.title, pasif.total_label) == (
        "liabilities",
        "PASİF (Kaynaklar)",
        "PASİF TOPLAM",
    )
    assert [b.title for b in aktif.sections] == ["I. DÖNEN VARLIKLAR", "II. DURAN VARLIKLAR"]
    assert [b.title for b in pasif.sections] == [
        "I. KISA VADELİ YÜKÜMLÜLÜKLER",
        "II. UZUN VADELİ YÜKÜMLÜLÜKLER",
        "III. ÖZKAYNAKLAR",
    ]
    assert [b.subtotal_label for b in aktif.sections] == [
        "Dönen Varlıklar Toplamı",
        "Duran Varlıklar Toplamı",
    ]
    assert [b.subtotal_label for b in pasif.sections] == [
        "Kısa Vadeli Yük. Toplamı",
        "Uzun Vadeli Yük. Toplamı",
        "Özkaynaklar Toplamı",
    ]


def test_bilanco_ONUC_kalem_ve_etiketler_mockup_ile_birebir():
    """🔴 Kalem SAYISI bağlayıcıdır (4+2 / 3+1+3): mockup 13 satır çizer ve
    icat edilmiş bir 14. kalem tasarım otoritesini aşardı. Eşleşmeyen gruplar
    bu yüzden mevcut `Diğer …` kalemlerine düşer (aşağıda ayrı test)."""
    aktif, pasif = statement_map.BALANCE_SHEET_SIDES
    assert [[k.label for k in b.lines] for b in aktif.sections] == [
        ["Kasa ve Bankalar", "Ticari Alacaklar", "Stoklar", "Diğer Dönen Varlıklar"],
        ["Maddi Duran Varlıklar (net)", "Diğer Duran Varlıklar"],
    ]
    assert [[k.label for k in b.lines] for b in pasif.sections] == [
        ["Ticari Borçlar", "Vergi Borçları", "Diğer Kısa Vadeli Borçlar"],
        ["Uzun Vadeli Krediler"],
        ["Sermaye", "Geçmiş Yıllar Kârları", "Dönem Net Kârı"],
    ]


def test_bilanco_kalem_anahtarlari_TEKILDIR():
    """Anahtar iki kalemde tekrarlansaydı toplayıcı ikisini tek kovaya döker ve
    fark yalnız o iki kalem birlikte doluyken görünürdü."""
    anahtarlar = [
        k.key
        for taraf in statement_map.BALANCE_SHEET_SIDES
        for b in taraf.sections
        for k in b.lines
    ]
    assert len(anahtarlar) == len(set(anahtarlar)) == 13


# --------------------------------------------------------------------------- #
# 3. 🔴 MT-K1 CAPALARI — olculmus yedi baglayici eslesme
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("code", "kalem", "gerekce"),
    [
        pytest.param("100", "cash", "HP:76 Kasa → BL:51", id="100-kasa"),
        pytest.param("102", "cash", "HP:90 Bankalar → BL:51", id="102-bankalar"),
        pytest.param("120", "trade_receivables", "HP:101 Alıcılar → BL:52", id="120-alicilar"),
        pytest.param("127", "trade_receivables", "HP:108 → BL:52", id="127-diger-ticari"),
        pytest.param("150", "inventory", "HP:119 İlk Madde → BL:53", id="150-stok"),
        pytest.param("191", "other_current_assets", "HP:126 İndirilecek KDV → BL:54", id="191-kdv"),
        pytest.param("252", "tangible_assets", "HP:138 Binalar → BL:57", id="252-binalar"),
        pytest.param("254", "tangible_assets", "HP:145 Taşıtlar → BL:57", id="254-tasit"),
        pytest.param("257", "tangible_assets", "HP:152 Amortisman → BL:57", id="257-amortisman"),
        pytest.param("320", "trade_payables", "HP:164 Satıcılar → BL:73", id="320-saticilar"),
        pytest.param("360", "tax_payables", "HP:171 Ödenecek Vergi → BL:74", id="360-vergi"),
        pytest.param("391", "tax_payables", "HP:178 Hesaplanan KDV → BL:74", id="391-hesaplanan"),
    ],
)
def test_MTK1_capalari_hesap_plani_mockupundan(code: str, kalem: str, gerekce: str):
    """🔴 Bu on iki kod hesap planı mockup'ında FİİLEN çizilidir ve bilanço
    rakamlarını üretirler:

    * `100`+`102` = 284.800 + 3.964.700 = **4.249.500** = BL:51
    * `120`+`127` = 8.400.000 + 124.200 = **8.524.200** = BL:52
    * `252`+`254`−`257` = 2.400.000 + 1.840.000 − 620.000 = **3.620.000** = BL:57
    * `320` = **2.184.000** = BL:73
    * `360`+`391` = 284.000 + 412.000 = **696.000** = BL:74

    🔴 `191` **aktifte**, `391` **pasifte** kalır — KDV NETLEŞTİRİLMEZ.
    """
    assert statement_map.balance_sheet_line_for(code, credit_natured=False) == kalem, gerekce


def test_101_ALINAN_CEKLER_grup_10a_yani_KASA_VE_BANKALARa_duser():
    """🔴 ÖLÇÜLMÜŞ MOCKUP TUTARSIZLIĞI (MT-K1/3) — TDHP grubu KAZANIR.

    `101 Alınan Çekler` (HP:83, 3.610.000) TDHP'de grup `10` (Hazır Değerler)
    içindedir. Ama mockup'ın `Kasa ve Bankalar` rakamı (4.249.500 = 100 + 102)
    onu **içermiyor** ve `Diğer Dönen Varlıklar` (768.520 = 191) de içermiyor —
    yani mockup'ta **HİÇBİR SATIRA girmiyor**. Bir hesabın hiçbir kaleme
    düşmemesi `AKTİF ≠ PASİF` demektir; kod kazanır, rakam göstermeliktir
    (KURALLAR §9).

    ⚠️ Açık borç: kalem etiketi (`Kasa ve Bankalar`) çeki kapsamıyor;
    `Hazır Değerler` daha doğru olurdu — yönetim kararı.
    """
    assert statement_map.balance_sheet_line_for("101", credit_natured=False) == "cash"


# --------------------------------------------------------------------------- #
# 4. Kapsayicilik — hicbir hesap GORUNMEZ olmaz
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("hane", ["1", "2", "3", "4", "5"])
def test_bilanco_siniflarinin_HER_grubu_ACIKCA_haritalidir(hane: str):
    """🔴 `10`–`59` arasındaki HER grup açık bir girdi taşır — hiçbiri sınıf
    yedeğine düşmez. Yedek yalnız TDHP dışı gruplar (`8x`/`9x`) içindir; bir
    bilanço grubunun oraya düşmesi "haritayı tamamlamayı unuttuk" demektir ve
    kalem etiketi sessizce yanlış olurdu.

    `59` tek istisnadır ve AÇIKÇA dışlanmıştır (bkz. çift sayım testi)."""
    for birim in range(10):
        grup = f"{hane}{birim}"
        if grup == "59":
            continue
        assert grup in statement_map.BALANCE_SHEET_GROUPS, f"{grup} haritada yok"


def test_HARITAYA_girmeyen_grup_DIGER_kalemine_duser_ve_GORUNUR_kalir():
    """🔴 MT-K1'in en sert kuralı: sessizce düşen hesap `AKTİF ≠ PASİF` yapar
    ve kullanıcı SEBEBİNİ göremez.

    Nazım hesaplar (`9x`) ve TDHP'de karşılığı olmayan `8x` grubu bilançoda
    kendi kalemine sahip değildir; borç bakiyeli olanı `Diğer Dönen Varlıklar`a,
    alacak bakiyeli olanı `Diğer Kısa Vadeli Borçlar`a düşer. Taraf, hesabın
    DOĞAL BAKİYE yönünden okunur — böylece nazım hesapların borçlu/alacaklı
    çifti iki tarafa eşit dağılır ve denge KORUNUR."""
    for grup in ("80", "85", "90", "99"):
        kod = f"{grup}0"
        assert (
            statement_map.balance_sheet_line_for(kod, credit_natured=False)
            == "other_current_assets"
        )
        assert (
            statement_map.balance_sheet_line_for(kod, credit_natured=True)
            == "other_short_term_liabilities"
        )


def test_haritadaki_HER_kalem_anahtari_gercek_bir_kalemdir():
    """Harita bir yazım hatası yüzünden var olmayan bir kaleme işaret etseydi o
    gruptaki bütün para sessizce kaybolurdu."""
    gecerli = {
        k.key
        for taraf in statement_map.BALANCE_SHEET_SIDES
        for b in taraf.sections
        for k in b.lines
    }
    for grup, kalem in statement_map.BALANCE_SHEET_GROUPS.items():
        assert kalem in gecerli, f"{grup} → {kalem} diye bir kalem yok"


def test_HER_grubun_bir_KAYNAK_NOTU_vardir():
    """🔴 "Uydurma yok": her girdi TDHP grup adını ve bağlandığı mockup satırını
    taşır. Notsuz bir girdi, sonraki dilimin "bu neden burada?" sorusunu
    cevapsız bırakır ve harita gözden geçirilemez hâle gelir."""
    for grup in statement_map.BALANCE_SHEET_GROUPS:
        not_metni = statement_map.GROUP_SOURCE_NOTES.get(grup)
        assert not_metni and len(not_metni) > 5, f"{grup} kaynak notsuz"


# --------------------------------------------------------------------------- #
# 5. 🔴 CIFT SAYIM YASAGI — `59` grubu govdeye GIRMEZ
# --------------------------------------------------------------------------- #


def test_59_grubu_bilanco_GOVDESINE_girmez():
    """🔴 MT-K1/2: `Dönem Net Kârı` satırı DAİMA `6xx`/`7xx`ten türer (MT-K3).
    `59` grubu (`590 Dönem Net Kârı` / `591 Dönem Net Zararı`) bir KAPANIŞ
    hesabıdır; üründe kapanış akışı YOKTUR.

    İkisi birden sayılsaydı kapanış fişi atılmış bir dönemde kâr İKİ KEZ
    görünürdü. Dışlama AÇIKTIR: `None` döner, sessizce bir kaleme sızmaz."""
    for kod in ("59", "590", "591", "590.01"):
        assert statement_map.balance_sheet_line_for(kod, credit_natured=True) is None
        assert statement_map.balance_sheet_line_for(kod, credit_natured=False) is None
    assert "59" not in statement_map.BALANCE_SHEET_GROUPS


def test_gelir_tablosu_siniflari_bilanco_GOVDESINE_girmez():
    """`6xx`/`7xx` gövdeye girmez; `Dönem Net Kârı` kalemine TÜRETİLEREK girer.
    Gövdeye de konsaydı aynı para hem kalem hem kâr olarak sayılırdı."""
    for kod in ("600", "621", "730", "760", "69", "790"):
        assert statement_map.balance_sheet_line_for(kod, credit_natured=False) is None
        assert statement_map.balance_sheet_line_for(kod, credit_natured=True) is None


# --------------------------------------------------------------------------- #
# 6. 🔴 MT-K3 — `period_profit()` TEK KAYNAK
# --------------------------------------------------------------------------- #


def test_period_profit_gelir_ARTI_gider_EKSI():
    """`net = Σborç − Σalacak`. Gelir hesabı ALACAK bakiyelidir (net negatif),
    gider hesabı BORÇ (net pozitif). `Σ(alacak − borç) = −Σnet` ikisini de doğru
    yönde toplar.

    `600` 1.000 gelir, `730` 400 gider → kâr **600**."""
    kar = statement_map.period_profit({"600": Decimal("-1000.00"), "730": Decimal("400.00")})
    assert kar == Decimal("600.00")


def test_period_profit_BILANCO_hesaplarini_HIC_saymaz():
    """Bilanço hesabı kâra girseydi `Dönem Net Kârı` satırı aktif/pasif
    toplamlarıyla ÇAKIŞIR ve denge her fişte kayardı."""
    kar = statement_map.period_profit(
        {
            "100": Decimal("50000.00"),
            "320": Decimal("-20000.00"),
            "500": Decimal("-8000.00"),
            "590": Decimal("-1234.00"),
            "600": Decimal("-1000.00"),
        }
    )
    assert kar == Decimal("1000.00")


def test_period_profit_AYRISMA_NOKTASI_sinif_6_giderleri():
    """🔴 PARA FORMÜLÜ AYRIŞMA NOKTASI (WORKFLOW §Ortak).

    "SINIF 6 = gelir, SINIF 7 = gider" varsayan bir formül `621 Satılan
    Mamüllerin Maliyeti`ni **gelir** sayar ve kârı iki kat şişirir. TDHP'de
    SINIF 6 hem geliri (`60x`, `64x`) hem gideri (`62x`, `63x`, `66x`) taşır.

    Doğru formül türü HİÇ okumaz, yalnız `alacak − borç` toplar:
    `600` 10.000 gelir, `621` 6.000 gider → kâr **4.000**
    (sınıf-tabanlı yanlış formül **16.000** verirdi)."""
    kar = statement_map.period_profit({"600": Decimal("-10000"), "621": Decimal("6000")})
    assert kar == Decimal("4000")


def test_K6_period_profit_69_KAPANIS_grubunu_SAYMAZ():
    """🔴 MT-2/K6: `690`/`692` bir KAPANIŞ AKTARIM hesabıdır. Kapanış fişi
    atılmış bir dönemde kâr hem kaynak `6xx`/`7xx` hesaplarından hem `69`dan
    sayılır ve İKİ KATINA çıkardı — bilançodaki `59` kuralının kardeşi.

    🔴 Kural `period_profit()`te yaşadığı için BİLANÇONUN `Dönem Net Kârı` ve
    `Geçmiş Yıllar Kârları` kalemlerini de kapsar. Ayrışma noktası: `69`
    TEK BAŞINA verildiğinde sonuç `0` olmalıdır — `6x` sınıfına bakan bir
    yazım `10000` döndürürdü.

    Mutasyon: `EXCLUDED_INCOME_STATEMENT_GROUPS` kontrolü kaldırılırsa KIRMIZI.
    """
    assert statement_map.period_profit({"690": Decimal("-10000.00")}) == Decimal("0")
    assert statement_map.period_profit({"692": Decimal("10000.00")}) == Decimal("0")
    # Kapanış fişi: `600` bakiyesi `690`a aktarılır. Kâr YALNIZ `600`den sayılır.
    kapanis = {"600": Decimal("-10000.00"), "690": Decimal("10000.00")}
    assert statement_map.period_profit(kapanis) == Decimal("10000.00")


def test_period_profit_KURUS_hassasiyetini_korur():
    """Kuruş ayrışma noktası: kayan nokta devreye girseydi `0.1 + 0.2` kusuru
    kârı 1 kuruş kaydırır ve bilanço dengesi kırılırdı (MT-K2 — uç YUVARLAMAZ)."""
    kar = statement_map.period_profit(
        {"600": Decimal("-0.10"), "601": Decimal("-0.20"), "730": Decimal("0.01")}
    )
    assert kar == Decimal("0.29")
    assert isinstance(kar, Decimal)


def test_period_profit_BOS_deftere_SIFIR_doner():
    """Hiç hesabı olmayan bir dönem `None`/hata değil `0` döner (MT-K11)."""
    assert statement_map.period_profit({}) == Decimal("0")


def test_period_profit_TUR_ve_KONTRA_bilmez_YAPISAL_YASAK():
    """🔴 Para formülünün İKİNCİ katmanı (yapısal yasak, WORKFLOW §Ortak).

    Formül `SIGN`/`account_type`/`is_contra` OKUMAZ. Okusaydı yanlış TÜR seçilen
    bir hesap (ör. `600` yanlışlıkla `expense` işaretlenmiş) kârın işaretini
    ters çevirirdi; `alacak − borç` toplamı buna KARŞI BAĞIŞIKTIR.

    Değer testi tek başına yetmez: iki uygulama pozitif kârda aynı sonucu verir,
    ayrışma ancak yanlış türle görünür — bu yüzden GÖVDE de denetlenir.

    🔴 Denetim AST tabanlıdır, düz metin grep DEĞİL: docstring bu adları
    UYARI olarak anar (`SIGN[account_type]` kullanan bir uygulama…) ve metin
    taraması onu yanlış alarm sayardı — `test_local_calendar_guard.py`nin AST
    tercihiyle aynı gerekçe."""
    govde = ast.parse(inspect.getsource(statement_map.period_profit)).body[0]
    assert isinstance(govde, ast.FunctionDef)
    kullanilan = {
        dugum.id if isinstance(dugum, ast.Name) else dugum.attr
        for dugum in ast.walk(govde)
        if isinstance(dugum, ast.Name | ast.Attribute)
    }
    for yasak in ("SIGN", "account_type", "is_contra", "ChartAccountType", "balance"):
        assert yasak not in kullanilan, f"period_profit {yasak} okuyor"


# --------------------------------------------------------------------------- #
# 7. Nakit akis haritasi — KK-2
# --------------------------------------------------------------------------- #


def test_nakit_akis_UC_bolum_ve_yedi_kalem_mockup_ile_birebir():
    """Mockup NA:69 (A) · NA:82 (B) · NA:91 (C); ara toplamlar NA:77, 86, 95."""
    bolumler = statement_map.CASH_FLOW_SECTIONS
    assert [b.key for b in bolumler] == ["operating", "investing", "financing"]
    assert [b.title for b in bolumler] == [
        "A. İŞLETME FAALİYETLERİNDEN NAKİTLER",
        "B. YATIRIM FAALİYETLERİNDEN NAKİTLER",
        "C. FİNANSMAN FAALİYETLERİNDEN NAKİTLER",
    ]
    assert [b.subtotal_label for b in bolumler] == [
        "İşletme Faaliyetleri Net Nakit",
        "Yatırım Faaliyetleri Net Nakit",
        "Finansman Faaliyetleri Net Nakit",
    ]
    assert [[k.label for k in b.lines] for b in bolumler] == [
        [
            "Müşterilerden Tahsilat",
            "Tedarikçilere Ödeme",
            "Personele Ödeme",
            "Vergi Ödemesi",
            "Diğer Nakit Çıkışları",
        ],
        ["Ekipman Alımı"],
        ["Kredi Geri Ödemesi"],
    ]


@pytest.mark.parametrize(
    ("code", "bolum", "kalem"),
    [
        pytest.param("120", "operating", "customer_collections", id="12x-isletme"),
        pytest.param("600", "operating", "customer_collections", id="60x-isletme"),
        pytest.param("320", "operating", "supplier_payments", id="32x-isletme"),
        pytest.param("730", "operating", "personnel_payments", id="73x-isletme"),
        pytest.param("760", "operating", "other_operating", id="76x-isletme"),
        pytest.param("360", "operating", "tax_payments", id="36x-vergi"),
        pytest.param("391", "operating", "tax_payments", id="39x-vergi"),
        pytest.param("191", "operating", "tax_payments", id="19x-vergi"),
        pytest.param("252", "investing", "equipment_purchase", id="25x-yatirim"),
        pytest.param("300", "financing", "loan_repayment", id="30x-finansman"),
        pytest.param("400", "financing", "loan_repayment", id="40x-finansman"),
        pytest.param("500", "financing", "loan_repayment", id="50x-finansman"),
    ],
)
def test_KK2_karsi_hesap_siniflandirmasi(code: str, bolum: str, kalem: str):
    """🔑 KK-2 (kullanıcı kararı): nakit akışı YEVMİYEDEN türer ve sınıflandırma
    KARŞI HESABIN kod aralığından yapılır — `treasury.payments`ten TÜRETİLMEZ,
    çünkü bilanço ile nakit akışı TEK tabandan gelmelidir.

    Emirde verilen dört kural: `12x/60x → İŞLETME` · `32x/73x/76x → İŞLETME` ·
    `25x → YATIRIM` · `30x/40x → FİNANSMAN`."""
    assert statement_map.cash_flow_line_for(code) == (bolum, kalem)


def test_grup_10_karsi_bacak_OLARAK_disarida():
    """🔴 Kasa→banka transferi bir nakit AKIŞI DEĞİLDİR: iki bacak da grup
    `10`dadır, net nakit değişimi SIFIRDIR. Sınıflandırıcı grup `10`u dışlar
    (`None`), yoksa aynı hareket hem giriş hem çıkış olarak basılır ve A/B/C
    ara toplamları şişerdi."""
    for kod in ("10", "100", "101", "102", "102.01"):
        assert statement_map.cash_flow_line_for(kod) is None


def test_nakit_akis_haritasi_TUM_gruplari_kapsar():
    """🔴 Karşı bacağı haritada olmayan bir hareket sessizce düşerse
    A+B+C ≠ (kapanış − açılış) olur ve fark hiçbir yerde görünmez.

    Grup `10` DIŞINDA `11`–`99` arasındaki her grup bir kaleme düşmek
    zorundadır."""
    for grup in range(11, 100):
        kod = f"{grup}0"
        assert statement_map.cash_flow_line_for(kod) is not None, f"{grup} sınıflandırılamıyor"


def test_nakit_akis_kalem_anahtarlari_TEKILDIR():
    anahtarlar = [k.key for b in statement_map.CASH_FLOW_SECTIONS for k in b.lines]
    assert len(anahtarlar) == len(set(anahtarlar)) == 7


def test_nakit_akis_haritasi_gercek_kalemlere_isaret_eder():
    gecerli = {(b.key, k.key) for b in statement_map.CASH_FLOW_SECTIONS for k in b.lines}
    for grup in range(11, 100):
        hedef = statement_map.cash_flow_line_for(f"{grup}0")
        assert hedef in gecerli, f"{grup} → {hedef} diye bir kalem yok"


# --------------------------------------------------------------------------- #
# 8. MT-2 T3 — GELIR TABLOSU haritasi (DB'siz, UCTAN BAGIMSIZ)
# --------------------------------------------------------------------------- #
#
# 🔴 Bu bolum bilinerek HTTP ucundan GECMEZ. Olculmus kanon (MT-1 T6):
# **iki katman birbirini maskeler** — harita dogru ama sorgu eksikse uc testi
# YINE YESIL kalir ve haritanin kendi kusuru gorunmez. Alt katmanin KENDI
# bekcisi burada durur.


def test_gelir_tablosu_IKI_bolum_ve_ALTI_kalem_mockup_ile_birebir():
    """🔴 K1: **2 bölüm · 6 kalem · 2 ara toplam · 1 genel toplam.**

    TDHP'nin `Brüt Satış Kârı` / `Faaliyet Kârı` basamakları YAZILMAZ — mockup
    (GT:93-143) onları çizmiyor ve icat edilmiş bir kalem tasarım otoritesini
    aşar (bilanço 13 kalemde durdu).
    """
    bolumler = statement_map.INCOME_STATEMENT_SECTIONS
    assert [b.key for b in bolumler] == ["revenue", "expenses"]
    assert [b.title for b in bolumler] == ["GELİRLER", "GİDERLER"]
    assert [b.subtotal_label for b in bolumler] == ["Toplam Gelir", "Toplam Gider"]
    assert [(k.key, k.label) for k in bolumler[0].lines] == [
        ("construction_revenue", "İş Hasılatı"),  # GT:98
        ("other_revenue", "Diğer Gelirler"),  # GT:103
    ]
    assert [(k.key, k.label) for k in bolumler[1].lines] == [
        ("material_costs", "Malzeme Giderleri"),  # GT:116
        ("labor_costs", "İşçilik Giderleri"),  # GT:121
        ("subcontractor_costs", "Taşeron Ödemeleri"),  # GT:126
        ("general_expenses", "Genel Giderler"),  # GT:131
    ]
    assert statement_map.INCOME_STATEMENT_PROFIT_LABEL == "DÖNEM KARI"  # GT:141
    assert statement_map.INCOME_STATEMENT_EXPENSE_SECTION == bolumler[1].key


def test_gelir_tablosu_kalem_anahtarlari_TEKILDIR():
    """İki bölüm aynı anahtarı taşısaydı tutar sözlüğü onları birleştirir ve
    para yanlış satıra düşerdi (bilanço emsali)."""
    anahtarlar = [k.key for b in statement_map.INCOME_STATEMENT_SECTIONS for k in b.lines]
    assert len(anahtarlar) == len(set(anahtarlar)) == 6


@pytest.mark.parametrize(
    ("grup", "kalem"),
    [
        ("60", "construction_revenue"),
        ("61", "construction_revenue"),
        ("62", "general_expenses"),
        ("63", "general_expenses"),
        ("64", "other_revenue"),
        ("65", "general_expenses"),
        ("66", "general_expenses"),
        ("67", "other_revenue"),
        ("68", "general_expenses"),
        ("70", "general_expenses"),
        ("71", "material_costs"),
        ("72", "labor_costs"),
        ("73", "labor_costs"),
        ("74", "subcontractor_costs"),
        ("75", "general_expenses"),
        ("76", "general_expenses"),
        ("77", "general_expenses"),
        ("78", "general_expenses"),
        ("79", "material_costs"),
    ],
)
def test_K2_her_grup_AYRI_AYRI_dogru_kaleme_duser(grup: str, kalem: str):
    """🔴 K2 eşlemesinin TAMAMI — grup başına AYRI iddia.

    Toplu bir "hepsi haritalı" iddiası, `72`yi `general_expenses`e bağlayan bir
    yazım hatasını GÖREMEZDİ: harita yine tam olurdu. Üç kod biçimi de aynı
    kaleme düşer (`NN` · `NNN` · `NNN.NN`).
    """
    assert statement_map.INCOME_STATEMENT_GROUPS[grup] == kalem
    assert statement_map.income_statement_line_for(grup) == kalem
    assert statement_map.income_statement_line_for(f"{grup}0") == kalem
    assert statement_map.income_statement_line_for(f"{grup}0.01") == kalem


@pytest.mark.parametrize("hane", ["6", "7"])
def test_gelir_tablosu_siniflarinin_HER_grubu_ACIKCA_haritalidir(hane: str):
    """🔴 Görünmezlik yasağı: `6x`/`7x` her grup AÇIK bir girdi taşır, yedeğe
    düşmez. Yedeğe düşen bir grup `Genel Giderler`e sızar ve etiketi sessizce
    yanlış olur. `69` tek istisnadır ve AÇIKÇA dışlanmıştır."""
    for birim in range(10):
        grup = f"{hane}{birim}"
        if grup in statement_map.EXCLUDED_INCOME_STATEMENT_GROUPS:
            continue
        assert grup in statement_map.INCOME_STATEMENT_GROUPS, f"{grup} haritada yok"


def test_gelir_tablosu_haritasi_gercek_kalemlere_isaret_eder():
    """Yazım hatası var olmayan bir kaleme işaret etseydi o gruptaki bütün para
    sessizce kaybolurdu."""
    gecerli = {k.key for b in statement_map.INCOME_STATEMENT_SECTIONS for k in b.lines}
    for grup, kalem in statement_map.INCOME_STATEMENT_GROUPS.items():
        assert kalem in gecerli, f"{grup} → {kalem} diye bir kalem yok"
    assert statement_map._INCOME_STATEMENT_FALLBACK in gecerli


def test_gelir_tablosu_HER_grubun_bir_KAYNAK_NOTU_vardir():
    """Notsuz girdi yasaktır: "bu neden burada?" cevapsız kalırsa harita gözden
    geçirilemez. `69` da notludur — DIŞLANDIĞI oraya yazılıdır."""
    for grup in list(statement_map.INCOME_STATEMENT_GROUPS) + sorted(
        statement_map.EXCLUDED_INCOME_STATEMENT_GROUPS
    ):
        not_metni = statement_map.INCOME_STATEMENT_SOURCE_NOTES.get(grup)
        assert not_metni and len(not_metni) > 5, f"{grup} kaynak notsuz"


@pytest.mark.parametrize("kod", ["100", "12", "191", "320", "500", "590", "580.01"])
def test_bilanco_hesaplari_gelir_tablosuna_GIRMEZ(kod: str):
    """🔴 `balance_sheet_line_for`ün AYNADAKİ karşılığı: orada `6x`/`7x` `None`
    döner, burada `1x`-`5x`. İki fonksiyon birlikte tüm kod uzayını tam olarak
    BİR KEZ kaplar; biri gevşerse aynı para iki tabloda birden sayılır."""
    assert statement_map.income_statement_line_for(kod) is None


def test_K6_69_grubu_gelir_tablosuna_GIRMEZ():
    """🔴 K6: `690`/`692` bir KAPANIŞ AKTARIM hesabıdır. Yedeğe düşseydi
    `Genel Giderler` kapanış fişini gider sayar ve dönem kârı İKİ KEZ
    hesaplanırdı — `59`un bilanço tarafındaki kuralının KARDEŞİ.

    Mutasyon: `EXCLUDED_INCOME_STATEMENT_GROUPS`tan `69` çıkarılırsa bu test
    KIRMIZI olur (`general_expenses` döner)."""
    for kod in ("69", "690", "692", "690.01"):
        assert statement_map.income_statement_line_for(kod) is None
    assert "69" not in statement_map.INCOME_STATEMENT_GROUPS


def test_K6_69_hesap_planina_TOHUMLANMAZ_degisim_pratikte_NO_OP():
    """🔴 K6(c): dışlama canlıdaki bilançonun formülünü değiştirir ama pratikte
    NO-OP'tur — `69` grubu hesap planına HİÇ tohumlanmaz, dolayısıyla bugünkü
    hiçbir defterde `69` bakiyesi olamaz.

    Kanıt tohumun KENDİSİNDEN okunur, docstring'den değil."""
    from app.modules.accounting import chart_seed_data

    kodlar = [h.code for h in chart_seed_data.CHART_ACCOUNTS]
    assert kodlar, "tohum listesi boş — bekçi kör kalırdı"
    assert [k for k in kodlar if k.startswith("69")] == []
    # Kardeşi de yok: `59` aynı gerekçeyle tohumlanmaz.
    assert [k for k in kodlar if k.startswith("59")] == []


@pytest.mark.parametrize(
    "kod", ["701", "711", "721", "731", "741", "751", "761", "771", "781", "798"]
)
def test_K7_YANSITMA_hesaplari_ISARETLENIR(kod: str):
    """🔴 K7: 7/A yansıtma hesapları `revenue` türündedir (ALACAK yönlü) ve
    KENDİ gider grubundadır. Gider kalemi grup olarak toplansaydı `710`+`711`
    birbirini götürür ve satır `0` basardı — sekiz grupta birden.

    Alt hesap da işaretlenir: eşleme `code[:3]` üzerinden yapılır."""
    assert statement_map.is_cost_reflection(kod) is True
    assert statement_map.is_cost_reflection(f"{kod}.01") is True


@pytest.mark.parametrize("kod", ["700", "710", "712", "720", "730", "740", "790", "799", "600"])
def test_K7_yansitma_OLMAYAN_hesaplar_isaretlenmez(kod: str):
    """Ayrışma noktası: `710` ile `711` YAN YANA durur ve yalnız ikincisi
    yansıtmadır. Grup düzeyinde bakan bir kural ikisini de eler ve satırı
    tümüyle boşaltırdı."""
    assert statement_map.is_cost_reflection(kod) is False


def test_K7_yansitma_kumesi_hesap_planindaki_REVENUE_tipli_sinif_7_ile_BIREBIR():
    """🔴 Küme uydurulmadı: tohumlanan hesap planında SINIF 7'nin `revenue`
    türündeki hesaplarının TAMAMI budur. Tohuma yeni bir yansıtma eklenirse bu
    test kırmızı olur ve küme güncellenir — sessizce sıfırlanan bir gider
    kalemi yerine."""
    from app.modules.accounting import chart_seed_data
    from app.modules.accounting.models import ChartAccountType

    tohumdaki = {
        h.code
        for h in chart_seed_data.CHART_ACCOUNTS
        if h.code[0] == "7" and h.account_type is ChartAccountType.revenue
    }
    assert tohumdaki == statement_map.COST_REFLECTION_ACCOUNTS


def test_gecersiz_kod_gelir_tablosu_yolunda_da_REDDEDILIR():
    """Sessizce `None` dönseydi geçersiz bir kod "bilanço hesabı" sayılır ve
    parası hiçbir tabloda görünmezdi (`group_of` kanonu)."""
    for kod in ("", "7", "abc", "0700"):
        with pytest.raises(ValueError):
            statement_map.income_statement_line_for(kod)
        with pytest.raises(ValueError):
            statement_map.is_cost_reflection(kod)
