"""TDHP grubu → mali tablo kalemi haritası (MT-1 T3) — 🔴 **SAF** modül.

`codes.py` emsali: bu dosya **DB bilmez, Pydantic bilmez, `today` bilmez**.
Girdisi bir hesap KODU, çıktısı bir kalem ANAHTARIDIR. Böyle olması bilinçlidir
— Bilanço (`balance_sheet.py`), Nakit Akış Tablosu (`cash_flow_statement.py`)
**ve ileride Gelir Tablosu** aynı eşlemeyi okur; üç yerde ayrı ayrı yazılsaydı
biri `19`u aktifte, öteki pasifte sayar ve **`AKTİF ≠ PASİF`** çıkardı.

Ölçülen gerçek: repoda kod-aralığı eşleme tablosu **HİÇ YOKTU**. `codes.py`
yalnız `class_code()` (ilk hane) ve `level()` verir; hesap planı **seed'i de
yoktur**, yani taze bir veritabanında plan boştur ve harita hiçbir kayıttan
türetilemez — TDHP'den YAZILMAK zorundadır.

## 🔴 Anahtar İKİ HANELİ GRUPTUR, ilk hane DEĞİL

Mockup'ın kalemleri (`Kasa ve Bankalar` · `Ticari Alacaklar` · `Stoklar`) tek
haneyle ayrılamaz: üçü de SINIF 1'dedir (HP:69). `codes.class_code()` bu iş için
yetersizdir ve **DEĞİŞTİRİLMEZ** (mizan/hesap planı onu kendi anlamıyla
kullanıyor); burada kendi türeticisi vardır. Üç kod biçimi de (`NN` · `NNN` ·
`NNN.NN`) `code[:2]` ile aynı grubu verir.

## Üç bağlayıcı kural (MT-K1)

1. 🔴 **KDV NETLEŞTİRİLMEZ.** `19x` (İndirilecek) **aktifte**
   (`Diğer Dönen Varlıklar`), `39x` (Hesaplanan) **pasifte** (`Vergi Borçları`)
   kalır. Netleştirme bir mali tablo kararıdır ve mockup söylemiyor.
2. 🔴 **`59` grubu (Dönem Net Kârı) bilanço GÖVDESİNE girmez.** `Dönem Net Kârı`
   kalemi DAİMA `6xx`/`7xx`ten türer (`period_profit()`). `59` bir KAPANIŞ
   hesabıdır ve üründe kapanış akışı yoktur; ikisi birden sayılsaydı kapanış
   fişi atılmış bir dönemde kâr İKİ KEZ görünürdü.
3. 🔴 **`101 Alınan Çekler` ölçülmüş bir mockup tutarsızlığıdır.** TDHP'de grup
   `10`dadır ama mockup'ın `Kasa ve Bankalar` rakamı (4.249.500 = `100`+`102`)
   onu içermez ve `Diğer Dönen Varlıklar` (768.520 = `191`) de içermez — yani
   mockup'ta HİÇBİR satıra girmiyor. **TDHP grubu KAZANIR** (rakam
   göstermeliktir, KURALLAR §9): `101` → `Kasa ve Bankalar`.
   ⚠️ Açık borç: etiket çeki kapsamıyor, `Hazır Değerler` daha doğru olurdu.

## Görünmezlik yasağı

Haritaya girmeyen bir hesap **sessizce düşemez**: düşseydi `AKTİF ≠ PASİF` olur
ve kullanıcı sebebini GÖREMEZDİ. `10`–`58` arasındaki her grup AÇIKÇA
haritalıdır; TDHP dışı gruplar (`8x` serbest, `9x` nazım) doğal bakiye
yönlerine göre mockup'ın mevcut `Diğer …` kalemlerine düşer. Kalem SAYISI
(4+2 / 3+1+3 = 13) mockup'tan gelir ve **artırılmaz** — icat edilmiş bir 14.
kalem tasarım otoritesini aşardı.

## Kaynak notları

`GROUP_SOURCE_NOTES` her grubun TDHP adını ve bağlandığı mockup satırını taşır.
Notsuz girdi yasaktır: "bu neden burada?" sorusu cevapsız kalırsa harita gözden
geçirilemez ve bir sonraki dilim onu tahminle büyütür.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

__all__ = [
    "BALANCE_SHEET_GROUPS",
    "BALANCE_SHEET_SIDES",
    "CASH_FLOW_GROUPS",
    "CASH_FLOW_SECTIONS",
    "CASH_GROUP",
    "EXCLUDED_BALANCE_SHEET_GROUPS",
    "GROUP_SOURCE_NOTES",
    "INCOME_STATEMENT_CLASSES",
    "PERIOD_PROFIT_LINE",
    "RETAINED_EARNINGS_LINE",
    "StatementLine",
    "StatementSection",
    "StatementSide",
    "balance_sheet_line_for",
    "cash_flow_line_for",
    "group_of",
    "period_profit",
]

_ZERO = Decimal("0")


# --------------------------------------------------------------------------- #
# Grup türeticisi
# --------------------------------------------------------------------------- #


def group_of(code: str) -> str:
    """Hesap kodunun İKİ HANELİ TDHP grubu — `NN` · `NNN` · `NNN.NN` hepsinde.

    🔴 Geçersiz kodda `ValueError`: sessizce bir dilim döndürseydi (`"1"`,
    `""`) geçersiz bir kod haritada gerçek bir grup gibi dolaşır ve parası
    yanlış kaleme düşerdi. `codes._require_valid` deseninin kardeşidir; kural
    ihlali burada bir PROGRAMLAMA hatasıdır (kullanıcı girdisi şemada zaten
    reddedilir).
    """
    if len(code) < 2 or not code[:2].isdigit() or code[0] == "0":
        raise ValueError(f"invalid chart account code: {code!r}")
    if len(code) == 2:
        return code
    if len(code) == 3 and code.isdigit():
        return code[:2]
    if len(code) == 6 and code[3] == "." and code[:3].isdigit() and code[4:].isdigit():
        return code[:2]
    raise ValueError(f"invalid chart account code: {code!r}")


# --------------------------------------------------------------------------- #
# Yapı taşları
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class StatementLine:
    """Bir mali tablo KALEMİ — mockup'ın tek bir satırı."""

    key: str
    label: str


@dataclass(frozen=True)
class StatementSection:
    """Bölüm bandı + kalemleri + ara toplam (mockup BL:50 / NA:69 bantları).

    `code` yalnız nakit akışında doludur (`A`/`B`/`C`, NA:69/82/91); bilançonun
    bölüm harfleri `title`ın içindedir (`I. DÖNEN VARLIKLAR`). Harf BURADA
    durur, çağıranda `"ABC"[sıra]` gibi bir dizinle üretilmez — dördüncü bir
    bölüm eklenirse o yazım `IndexError` verirdi.
    """

    key: str
    title: str
    subtotal_label: str
    lines: tuple[StatementLine, ...]
    code: str = ""


@dataclass(frozen=True)
class StatementSide:
    """Bilançonun bir TARAFI — AKTİF ya da PASİF (mockup BL:44 / BL:66)."""

    key: str
    title: str
    total_label: str
    sections: tuple[StatementSection, ...]


# --------------------------------------------------------------------------- #
# Bilanço iskeleti — mockup BL:44-88 BİREBİR
# --------------------------------------------------------------------------- #

_ASSETS = StatementSide(
    key="assets",
    title="AKTİF (Varlıklar)",  # BL:46
    total_label="AKTİF TOPLAM",  # BL:60
    sections=(
        StatementSection(
            key="current_assets",
            title="I. DÖNEN VARLIKLAR",  # BL:50
            subtotal_label="Dönen Varlıklar Toplamı",  # BL:55
            lines=(
                StatementLine("cash", "Kasa ve Bankalar"),  # BL:51
                StatementLine("trade_receivables", "Ticari Alacaklar"),  # BL:52
                StatementLine("inventory", "Stoklar"),  # BL:53
                StatementLine("other_current_assets", "Diğer Dönen Varlıklar"),  # BL:54
            ),
        ),
        StatementSection(
            key="non_current_assets",
            title="II. DURAN VARLIKLAR",  # BL:56
            subtotal_label="Duran Varlıklar Toplamı",  # BL:59
            lines=(
                StatementLine("tangible_assets", "Maddi Duran Varlıklar (net)"),  # BL:57
                StatementLine("other_non_current_assets", "Diğer Duran Varlıklar"),  # BL:58
            ),
        ),
    ),
)

_LIABILITIES = StatementSide(
    key="liabilities",
    title="PASİF (Kaynaklar)",  # BL:68
    total_label="PASİF TOPLAM",  # BL:85
    sections=(
        StatementSection(
            key="short_term_liabilities",
            title="I. KISA VADELİ YÜKÜMLÜLÜKLER",  # BL:72
            subtotal_label="Kısa Vadeli Yük. Toplamı",  # BL:76
            lines=(
                StatementLine("trade_payables", "Ticari Borçlar"),  # BL:73
                StatementLine("tax_payables", "Vergi Borçları"),  # BL:74
                StatementLine("other_short_term_liabilities", "Diğer Kısa Vadeli Borçlar"),  # BL:75
            ),
        ),
        StatementSection(
            key="long_term_liabilities",
            title="II. UZUN VADELİ YÜKÜMLÜLÜKLER",  # BL:77
            subtotal_label="Uzun Vadeli Yük. Toplamı",  # BL:79
            lines=(StatementLine("long_term_loans", "Uzun Vadeli Krediler"),),  # BL:78
        ),
        StatementSection(
            key="equity",
            title="III. ÖZKAYNAKLAR",  # BL:80
            subtotal_label="Özkaynaklar Toplamı",  # BL:84
            lines=(
                StatementLine("paid_in_capital", "Sermaye"),  # BL:81
                StatementLine("retained_earnings", "Geçmiş Yıllar Kârları"),  # BL:82
                StatementLine("period_profit", "Dönem Net Kârı"),  # BL:83
            ),
        ),
    ),
)

#: Sıra mockup'ın ızgarasıyla aynıdır (BL:42 — AKTİF solda, PASİF sağda).
BALANCE_SHEET_SIDES: tuple[StatementSide, StatementSide] = (_ASSETS, _LIABILITIES)

#: 🔴 `Dönem Net Kârı` kaleminin anahtarı — hiçbir GRUP buraya haritalanmaz,
#: değeri `period_profit()`ten TÜRETİLİR (MT-K3).
PERIOD_PROFIT_LINE = "period_profit"

#: 🔴 `Geçmiş Yıllar Kârları` kaleminin anahtarı — İKİ kaynağı vardır ve ikisi
#: TOPLANIR: (a) `53`-`58` gruplarının GERÇEK bakiyesi, (b) ÖNCEKİ DÖNEMLERİN
#: `6xx`/`7xx` sonucu. (b) şarttır çünkü üründe kapanış akışı yoktur — gelir
#: tablosu hesapları `570`e hiç kapanmaz, bakiyeleri yıllar boyunca defterde
#: durur ve bir yere konulmazsa bilanço her yıl dönümünde dengesizleşir
#: (T7 final review bulgusu).
RETAINED_EARNINGS_LINE = "retained_earnings"


# --------------------------------------------------------------------------- #
# 🔴 TDHP grubu → bilanço kalemi
# --------------------------------------------------------------------------- #

BALANCE_SHEET_GROUPS: dict[str, str] = {
    # --- SINIF 1 — DÖNEN VARLIKLAR (HP:69) ---
    "10": "cash",
    "11": "other_current_assets",
    "12": "trade_receivables",
    "13": "other_current_assets",
    "14": "other_current_assets",
    "15": "inventory",
    "16": "other_current_assets",
    "17": "other_current_assets",
    "18": "other_current_assets",
    "19": "other_current_assets",
    # --- SINIF 2 — DURAN VARLIKLAR (HP:135) ---
    "20": "other_non_current_assets",
    "21": "other_non_current_assets",
    "22": "other_non_current_assets",
    "23": "other_non_current_assets",
    "24": "other_non_current_assets",
    "25": "tangible_assets",
    "26": "other_non_current_assets",
    "27": "other_non_current_assets",
    "28": "other_non_current_assets",
    "29": "other_non_current_assets",
    # --- SINIF 3 — KISA VADELİ YÜKÜMLÜLÜKLER (HP:161) ---
    "30": "other_short_term_liabilities",
    "31": "other_short_term_liabilities",
    "32": "trade_payables",
    "33": "other_short_term_liabilities",
    "34": "other_short_term_liabilities",
    "35": "other_short_term_liabilities",
    "36": "tax_payables",
    "37": "other_short_term_liabilities",
    "38": "other_short_term_liabilities",
    "39": "tax_payables",
    # --- SINIF 4 — UZUN VADELİ YÜKÜMLÜLÜKLER ---
    "40": "long_term_loans",
    "41": "long_term_loans",
    "42": "long_term_loans",
    "43": "long_term_loans",
    "44": "long_term_loans",
    "45": "long_term_loans",
    "46": "long_term_loans",
    "47": "long_term_loans",
    "48": "long_term_loans",
    "49": "long_term_loans",
    # --- SINIF 5 — ÖZKAYNAKLAR (🔴 `59` YOK — MT-K1/2) ---
    "50": "paid_in_capital",
    "51": "paid_in_capital",
    "52": "paid_in_capital",
    "53": "retained_earnings",
    "54": "retained_earnings",
    "55": "retained_earnings",
    "56": "retained_earnings",
    "57": "retained_earnings",
    "58": "retained_earnings",
}

#: 🔴 Gövdeye HİÇ girmeyen gruplar. `59` bir KAPANIŞ hesabıdır (`590` Dönem Net
#: Kârı / `591` Dönem Net Zararı) ve `Dönem Net Kârı` kalemi zaten `6xx`/`7xx`ten
#: türetilir — ikisi birden sayılsaydı kapanış fişi atılmış bir dönemde kâr İKİ
#: KEZ görünürdü (MT-K1/2, çift sayım yasağı).
EXCLUDED_BALANCE_SHEET_GROUPS: frozenset[str] = frozenset({"59"})

#: Gelir tablosu SINIFLARI: bilanço gövdesine girmez, `period_profit()`i besler.
INCOME_STATEMENT_CLASSES: frozenset[str] = frozenset({"6", "7"})

#: TDHP dışı gruplar (`8x` serbest · `9x` nazım) için kalemler. Taraf hesabın
#: DOĞAL BAKİYE yönünden okunur: nazım hesapların borçlu/alacaklı çifti böylece
#: iki tarafa EŞİT dağılır ve denge KORUNUR. Görünürlük yasası gereği bu
#: hesaplar bir kaleme düşer, kaybolmaz.
_UNMAPPED_LINES = {
    False: "other_current_assets",
    True: "other_short_term_liabilities",
}


GROUP_SOURCE_NOTES: dict[str, str] = {
    # --- SINIF 1 ---
    "10": "TDHP 10 Hazır Değerler — HP:72 bandı; 100+102 = 4.249.500 = BL:51 (101 dâhil, MT-K1/3)",
    "11": "TDHP 11 Menkul Kıymetler — bilançoda ayrı kalem yok → BL:54 Diğer Dönen Varlıklar",
    "12": "TDHP 12 Ticari Alacaklar — HP:97 bandı; 120+127 = 8.524.200 = BL:52",
    "13": "TDHP 13 Diğer Alacaklar — BL:54 Diğer Dönen Varlıklar",
    "14": "TDHP'de kullanılmayan grup — sınıf 1 olduğu için BL:54'e düşer, kaybolmaz",
    "15": "TDHP 15 Stoklar — HP:115 bandı; 150 İlk Madde ve Malzeme = 3.240.000 = BL:53",
    "16": "TDHP'de kullanılmayan grup — sınıf 1 olduğu için BL:54'e düşer, kaybolmaz",
    "17": "TDHP 17 Yıllara Yaygın İnşaat ve Onarım Maliyetleri — BL:54",
    "18": "TDHP 18 Gelecek Aylara Ait Giderler ve Gelir Tahakkukları — BL:54",
    "19": "TDHP 19 Diğer Dönen Varlıklar — HP:126 `191 İndirilecek KDV` = 768.520 = BL:54",
    # --- SINIF 2 ---
    "20": "TDHP'de kullanılmayan grup — sınıf 2 olduğu için BL:58'e düşer",
    "21": "TDHP'de kullanılmayan grup — sınıf 2 olduğu için BL:58'e düşer",
    "22": "TDHP 22 Ticari Alacaklar (uzun vadeli) — BL:58 Diğer Duran Varlıklar",
    "23": "TDHP 23 Diğer Alacaklar (uzun vadeli) — BL:58",
    "24": "TDHP 24 Mali Duran Varlıklar — BL:58",
    "25": "TDHP 25 Maddi Duran Varlıklar — HP:138/145/152; 2.400.000+1.840.000−620.000 = BL:57",
    "26": "TDHP 26 Maddi Olmayan Duran Varlıklar — BL:58",
    "27": "TDHP 27 Özel Tükenmeye Tabi Varlıklar — BL:58",
    "28": "TDHP 28 Gelecek Yıllara Ait Giderler ve Gelir Tahakkukları — BL:58",
    "29": "TDHP 29 Diğer Duran Varlıklar — BL:58 (mockup 240.000 basıyor)",
    # --- SINIF 3 ---
    "30": "TDHP 30 Mali Borçlar (kısa vadeli krediler) — BL:75 Diğer Kısa Vadeli Borçlar",
    "31": "TDHP'de kullanılmayan grup — sınıf 3 olduğu için BL:75'e düşer",
    "32": "TDHP 32 Ticari Borçlar — HP:164 `320 Satıcılar` = 2.184.000 = BL:73",
    "33": "TDHP 33 Diğer Borçlar (335 Personele Borçlar dâhil) — BL:75",
    "34": "TDHP 34 Alınan Avanslar — BL:75",
    "35": "TDHP 35 Yıllara Yaygın İnşaat ve Onarım Hakedişleri — BL:75",
    "36": "TDHP 36 Ödenecek Vergi ve Diğer Yükümlülükler — HP:171 `360` = 284.000 → BL:74",
    "37": "TDHP 37 Borç ve Gider Karşılıkları — BL:75",
    "38": "TDHP 38 Gelecek Aylara Ait Gelirler ve Gider Tahakkukları — BL:75",
    "39": "TDHP 39 Diğer KV Yabancı Kaynaklar — HP:178 `391 Hesaplanan KDV` = 412.000 → BL:74; "
    "🔴 KDV NETLEŞTİRİLMEZ, `19x` aktifte kalır",
    # --- SINIF 4 ---
    "40": "TDHP 40 Mali Borçlar (uzun vadeli krediler) — BL:78 Uzun Vadeli Krediler",
    "41": "TDHP'de kullanılmayan grup — sınıf 4 olduğu için BL:78'e düşer",
    "42": "TDHP 42 Ticari Borçlar (uzun vadeli) — mockup II. bölümde TEK kalem çiziyor → BL:78",
    "43": "TDHP 43 Diğer Borçlar (uzun vadeli) — BL:78",
    "44": "TDHP 44 Alınan Avanslar (uzun vadeli) — BL:78",
    "45": "TDHP'de kullanılmayan grup — sınıf 4 olduğu için BL:78'e düşer",
    "46": "TDHP'de kullanılmayan grup — sınıf 4 olduğu için BL:78'e düşer",
    "47": "TDHP 47 Borç ve Gider Karşılıkları (uzun vadeli) — BL:78",
    "48": "TDHP 48 Gelecek Yıllara Ait Gelirler ve Gider Tahakkukları — BL:78",
    "49": "TDHP 49 Diğer UV Yabancı Kaynaklar — BL:78",
    # --- SINIF 5 ---
    "50": "TDHP 50 Ödenmiş Sermaye — BL:81 Sermaye. ⚠️ `501 Ödenmemiş Sermaye (-)` KONTRA "
    "İŞARETLENMEZ: `equity` türü PASİF tarafta kalır, borç bakiyesi zaten düşer",
    "51": "TDHP'de kullanılmayan grup — sermaye ailesi → BL:81",
    "52": "TDHP 52 Sermaye Yedekleri — BL:81 Sermaye (mockup tek `Sermaye` kalemi çiziyor)",
    "53": "TDHP'de kullanılmayan grup — birikmiş sonuçlar ailesi → BL:82",
    "54": "TDHP 54 Kâr Yedekleri — BL:82 Geçmiş Yıllar Kârları",
    "55": "TDHP'de kullanılmayan grup — birikmiş sonuçlar ailesi → BL:82",
    "56": "TDHP'de kullanılmayan grup — birikmiş sonuçlar ailesi → BL:82",
    "57": "TDHP 57 Geçmiş Yıllar Kârları — BL:82 (mockup 3.369.520)",
    "58": "TDHP 58 Geçmiş Yıllar Zararları (-) — BL:82; borç bakiyesi işaretiyle DÜŞER",
}


def balance_sheet_line_for(code: str, *, credit_natured: bool) -> str | None:
    """Hesap kodunun düşeceği bilanço KALEMİ; `None` = gövdeye GİRMEZ.

    `None` dönen İKİ hâl vardır ve ikisi de AÇIK bir karardır, sessiz bir
    düşme DEĞİL:

    * **`6xx`/`7xx`** — gelir tablosu hesapları. `Dönem Net Kârı` kalemine
      `period_profit()` üzerinden TÜRETİLEREK girerler; gövdeye de konsalardı
      aynı para hem kalem hem kâr olarak sayılırdı.
    * **`59`** — kapanış hesabı (MT-K1/2 çift sayım yasağı).

    `credit_natured` YALNIZ haritada karşılığı olmayan gruplar (`8x`/`9x`) için
    okunur ve hesabın DOĞAL BAKİYE yönünü söyler (`balance.SIGN[tür] == -1`).
    Enum'u burada ithal etmek modülün saflığını bozardı; çağıran bu tek biti
    hesaplar.
    """
    grup = group_of(code)
    if grup[0] in INCOME_STATEMENT_CLASSES or grup in EXCLUDED_BALANCE_SHEET_GROUPS:
        return None
    kalem = BALANCE_SHEET_GROUPS.get(grup)
    if kalem is not None:
        return kalem
    return _UNMAPPED_LINES[credit_natured]


# --------------------------------------------------------------------------- #
# 🔑 MT-K3 — DÖNEM KÂRININ TEK KAYNAĞI
# --------------------------------------------------------------------------- #


def period_profit(nets: Mapping[str, Decimal]) -> Decimal:
    """Dönem net kârı — `Σ(alacak − borç)` = `−Σ net`, gelir tablosu sınıflarında.

    🔴 **BU FORMÜLÜN İKİNCİ BİR KOPYASI YAZILMAZ.** Gelir Tablosu dilimi bunu
    İTHAL EDER: Bilanço'nun `Dönem Net Kârı` satırı (BL:83) ile Gelir
    Tablosu'nun `DÖNEM KÂRI` satırı **birebir** aynı olmak zorundadır ve iki
    kopya kaçınılmaz olarak ayrışırdı ("aynı para formülü iki yerde YAŞAMAZ").

    Girdi `{hesap kodu: net}` sözlüğüdür; `net = Σborç − Σalacak` (ham nicelik,
    `balance.net_expression()` ile aynı yön). Pencereyi ÇAĞIRAN seçer — bilanço
    `year-01-01 ≤ entry_date ≤ as_of` aralığını verir.

    🔴 **TÜR ve KONTRA OKUNMAZ ve bu bir eksiklik DEĞİL, bekçidir.** Gelir
    hesabı ALACAK, gider hesabı BORÇ bakiyelidir; `alacak − borç` toplamı ikisini
    de doğru yönde toplar. `SIGN[account_type]` kullanan bir uygulama, yanlış TÜR
    işaretlenmiş bir hesapta kârın işaretini ters çevirirdi.

    **Ayrışma noktası (para formülü kanonu):** "SINIF 6 = gelir, SINIF 7 = gider"
    varsayan bir formül `621 Satılan Mamüllerin Maliyeti`ni GELİR sayar ve kârı
    şişirir — TDHP'de SINIF 6 hem geliri (`60x`, `64x`) hem gideri (`62x`, `63x`,
    `66x`) taşır. Bu uygulama sınıfı yalnız "gelir tablosu hesabı mı?" sorusu
    için okur, YÖN için değil.

    Para `Decimal`dir; kayan nokta hiçbir aşamada devreye girmez.
    """
    toplam = _ZERO
    for code, net in nets.items():
        if group_of(code)[0] in INCOME_STATEMENT_CLASSES:
            toplam -= net
    return toplam


# --------------------------------------------------------------------------- #
# Nakit akış iskeleti — mockup NA:64-104 BİREBİR
# --------------------------------------------------------------------------- #

CASH_FLOW_SECTIONS: tuple[StatementSection, ...] = (
    StatementSection(
        key="operating",
        code="A",
        title="A. İŞLETME FAALİYETLERİNDEN NAKİTLER",  # NA:69
        subtotal_label="İşletme Faaliyetleri Net Nakit",  # NA:77
        lines=(
            StatementLine("customer_collections", "Müşterilerden Tahsilat"),  # NA:71
            StatementLine("supplier_payments", "Tedarikçilere Ödeme"),  # NA:72
            StatementLine("personnel_payments", "Personele Ödeme"),  # NA:73
            StatementLine("tax_payments", "Vergi Ödemesi"),  # NA:74
            StatementLine("other_operating", "Diğer Nakit Çıkışları"),  # NA:75
        ),
    ),
    StatementSection(
        key="investing",
        code="B",
        title="B. YATIRIM FAALİYETLERİNDEN NAKİTLER",  # NA:82
        subtotal_label="Yatırım Faaliyetleri Net Nakit",  # NA:86
        lines=(StatementLine("equipment_purchase", "Ekipman Alımı"),),  # NA:84
    ),
    StatementSection(
        key="financing",
        code="C",
        title="C. FİNANSMAN FAALİYETLERİNDEN NAKİTLER",  # NA:91
        subtotal_label="Finansman Faaliyetleri Net Nakit",  # NA:95
        lines=(StatementLine("loan_repayment", "Kredi Geri Ödemesi"),),  # NA:93
    ),
)

#: 🔴 NAKDİN KENDİSİ. Kaynak grup budur (KK-2) ve aynı zamanda karşı bacak
#: olarak DIŞLANIR: kasa→banka transferinin iki bacağı da buradadır, net nakit
#: değişimi SIFIRDIR ve sınıflandırılsaydı aynı hareket hem giriş hem çıkış
#: olarak basılırdı.
CASH_GROUP = "10"

CASH_FLOW_GROUPS: dict[str, tuple[str, str]] = {
    # --- Müşterilerden Tahsilat: gelir döngüsü ---
    "12": ("operating", "customer_collections"),  # KK-2: 12x → İŞLETME
    "22": ("operating", "customer_collections"),
    "34": ("operating", "customer_collections"),
    "35": ("operating", "customer_collections"),
    "44": ("operating", "customer_collections"),
    "60": ("operating", "customer_collections"),  # KK-2: 60x → İŞLETME
    "61": ("operating", "customer_collections"),
    "64": ("operating", "customer_collections"),
    "67": ("operating", "customer_collections"),
    # --- Tedarikçilere Ödeme: tedarik/stok/üretim girdisi ---
    "15": ("operating", "supplier_payments"),
    "17": ("operating", "supplier_payments"),
    "32": ("operating", "supplier_payments"),  # KK-2: 32x → İŞLETME
    "42": ("operating", "supplier_payments"),
    "62": ("operating", "supplier_payments"),
    "71": ("operating", "supplier_payments"),
    "74": ("operating", "supplier_payments"),
    # --- Personele Ödeme ---
    "33": ("operating", "personnel_payments"),  # 335 Personele Borçlar
    "43": ("operating", "personnel_payments"),
    "72": ("operating", "personnel_payments"),  # Direkt İşçilik
    "73": ("operating", "personnel_payments"),  # KK-2: 73x → İŞLETME; HP:197 = NA:73
    # --- Vergi Ödemesi ---
    "19": ("operating", "tax_payments"),  # 191 İndirilecek KDV
    "36": ("operating", "tax_payments"),  # 360 Ödenecek Vergi ve Fonlar
    "39": ("operating", "tax_payments"),  # 391 Hesaplanan KDV
    # --- Diğer Nakit Çıkışları: işletmenin kalan her şeyi ---
    "13": ("operating", "other_operating"),
    "14": ("operating", "other_operating"),
    "16": ("operating", "other_operating"),
    "18": ("operating", "other_operating"),
    "23": ("operating", "other_operating"),
    "28": ("operating", "other_operating"),
    "31": ("operating", "other_operating"),
    "37": ("operating", "other_operating"),
    "38": ("operating", "other_operating"),
    "47": ("operating", "other_operating"),
    "48": ("operating", "other_operating"),
    "49": ("operating", "other_operating"),
    "63": ("operating", "other_operating"),
    "65": ("operating", "other_operating"),
    "66": ("operating", "other_operating"),  # faiz gideri: C bölümü ANAPARAYA ayrılmıştır
    "68": ("operating", "other_operating"),
    "69": ("operating", "other_operating"),
    "70": ("operating", "other_operating"),
    "75": ("operating", "other_operating"),
    "76": ("operating", "other_operating"),  # KK-2: 76x → İŞLETME; HP:204 = NA:75
    "77": ("operating", "other_operating"),
    "78": ("operating", "other_operating"),
    "79": ("operating", "other_operating"),
    # --- Yatırım: duran varlık hareketleri ---
    "11": ("investing", "equipment_purchase"),  # Menkul Kıymetler = yatırım
    "20": ("investing", "equipment_purchase"),
    "21": ("investing", "equipment_purchase"),
    "24": ("investing", "equipment_purchase"),
    "25": ("investing", "equipment_purchase"),  # KK-2: 25x → YATIRIM
    "26": ("investing", "equipment_purchase"),
    "27": ("investing", "equipment_purchase"),
    "29": ("investing", "equipment_purchase"),
    # --- Finansman: kredi anaparası + özkaynak hareketleri ---
    "30": ("financing", "loan_repayment"),  # KK-2: 30x → FİNANSMAN
    "40": ("financing", "loan_repayment"),  # KK-2: 40x → FİNANSMAN
    "41": ("financing", "loan_repayment"),
    "45": ("financing", "loan_repayment"),
    "46": ("financing", "loan_repayment"),
    "50": ("financing", "loan_repayment"),
    "51": ("financing", "loan_repayment"),
    "52": ("financing", "loan_repayment"),
    "53": ("financing", "loan_repayment"),
    "54": ("financing", "loan_repayment"),
    "55": ("financing", "loan_repayment"),
    "56": ("financing", "loan_repayment"),
    "57": ("financing", "loan_repayment"),
    "58": ("financing", "loan_repayment"),
    "59": ("financing", "loan_repayment"),
}

#: TDHP dışı gruplar (`8x` serbest · `9x` nazım): sınıflandırılamaz ama
#: GÖRÜNMEZ de olamaz — A bölümünün `Diğer Nakit Çıkışları` kalemine düşer.
#: Düşmeselerdi `A+B+C ≠ (kapanış − açılış)` olur ve fark hiçbir yerde
#: görünmezdi.
_CASH_FLOW_FALLBACK = ("operating", "other_operating")


def cash_flow_line_for(code: str) -> tuple[str, str] | None:
    """Karşı hesabın kodundan `(bölüm, kalem)`; grup `10`da **`None`**.

    🔑 KK-2 (kullanıcı kararı): nakit akışı YEVMİYEDEN türer ve sınıflandırma
    KARŞI HESABIN kod aralığından yapılır. `treasury.payments`ten türetilseydi
    Bilanço ile Nakit Akışı iki AYRI tabandan gelir ve `Kasa ve Bankalar` ile
    `DÖNEM SONU NAKİT` sessizce ayrışırdı.

    🔴 Grup `10` `None` döner: nakdin kendisi bir "karşı hesap" olamaz.
    Kasa→banka transferinde iki bacak da grup `10`dadır; sınıflandırılsalardı
    aynı hareket hem giriş hem çıkış olarak basılır ve ara toplamlar şişerdi.
    """
    grup = group_of(code)
    if grup == CASH_GROUP:
        return None
    return CASH_FLOW_GROUPS.get(grup, _CASH_FLOW_FALLBACK)
