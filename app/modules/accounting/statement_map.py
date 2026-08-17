"""TDHP grubu → mali tablo kalemi haritası (MT-1 T3) — 🔴 **SAF** modül.

`codes.py` emsali: bu dosya **DB bilmez, Pydantic bilmez, `today` bilmez**.
Girdisi bir hesap KODU, çıktısı bir kalem ANAHTARIDIR. Böyle olması bilinçlidir
— Bilanço (`balance_sheet.py`), Nakit Akış Tablosu (`cash_flow_statement.py`)
**ve ileride Gelir Tablosu** aynı eşlemeyi okur; üç yerde ayrı ayrı yazılsaydı
biri `19`u aktifte, öteki pasifte sayar ve **`AKTİF ≠ PASİF`** çıkardı.

Ölçülen gerçek: repoda kod-aralığı eşleme tablosu **HİÇ YOKTU**. `codes.py`
yalnız `class_code()` (ilk hane) ve `level()` verir. 🔄 (MU-SEED T5) Hesap planı
artık `e5f6a7b8c9d0` migration'ıyla tohumlanır — 56 grup (`NN`) + 260 ana hesap
(`NNN`), 316 satır — ama bu tohum bir HARİTA YAZMAZ, yalnız kod/ad/tür/kontra
taşır. Harita hâlâ hiçbir kayıttan türetilemez — TDHP'den YAZILMAK zorundadır.

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
    "COST_REFLECTION_ACCOUNTS",
    "EXCLUDED_BALANCE_SHEET_GROUPS",
    "EXCLUDED_INCOME_STATEMENT_GROUPS",
    "GROUP_SOURCE_NOTES",
    "INCOME_STATEMENT_CLASSES",
    "INCOME_STATEMENT_EXPENSE_SECTION",
    "INCOME_STATEMENT_GROUPS",
    "INCOME_STATEMENT_PROFIT_LABEL",
    "INCOME_STATEMENT_SECTIONS",
    "INCOME_STATEMENT_SOURCE_NOTES",
    "PERIOD_PROFIT_LINE",
    "RETAINED_EARNINGS_LINE",
    "StatementLine",
    "StatementSection",
    "StatementSide",
    "balance_sheet_line_for",
    "cash_flow_line_for",
    "group_of",
    "income_statement_line_for",
    "is_cost_reflection",
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

#: 🔴 Gelir tablosuna da `period_profit()`e de HİÇ girmeyen gruplar (MT-2/K6).
#: `690 Dönem Kârı veya Zararı` / `692 Dönem Net Kârı veya Zararı` bir KAPANIŞ
#: AKTARIM hesabıdır: `6xx`/`7xx` bakiyeleri oraya taşınır. Sayılsaydı aynı kâr
#: hem kaynak hesaplardan hem aktarım hesabından İKİ KEZ toplanırdı — `59` için
#: bilanço tarafında zaten var olan kuralın gelir tablosu KARDEŞİDİR ve o kural
#: `59`suz bırakıldığında burada ASİMETRİ oluşturuyordu.
#:
#: 🔴 Kural `period_profit()`i de kapsar, yani BİLANÇONUN `Dönem Net Kârı` ve
#: `Geçmiş Yıllar Kârları` kalemlerini de değiştirir — iki tablo aynı formülü
#: paylaştığı için başka türlüsü ayrışma üretirdi. Pratikte NO-OP'tur: `69`
#: hesap planına TOHUMLANMAZ (`chart_seed_data.py` modül docstring'i, K3) ve
#: kullanıcı da açamaz çünkü kapanış akışı üründe YOKTUR. Bakiyesi olan bir
#: `69` hesabı artık bilançoda `is_balanced=False` ile GÖRÜNÜR olur — `59`un
#: bugünkü davranışıyla birebir aynı, sessiz bir çift sayım yerine.
EXCLUDED_INCOME_STATEMENT_GROUPS: frozenset[str] = frozenset({"69"})

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
    okunur ve hesabın **ETKİN** bakiye yönünü söyler — yani `is_contra` DÂHİL
    (`(is_contra ? −1 : +1) × SIGN[tür] < 0`). Ham `SIGN` verilseydi kontra
    işaretli bir nazım hesap PASİF kaleme düşer ama katkısı `+net` olurdu ve
    denge iki katı tutar kayardı (T7 final review bulgusu, M3).

    Enum'u burada ithal etmek modülün saflığını bozardı; çağıran bu tek biti
    hesaplar (`balance_sheet._etkin_yon`).
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

    🔴 **Grup `69` DIŞLANIR (MT-2/K6).** `690`/`692` bir KAPANIŞ AKTARIM
    hesabıdır: `6xx`/`7xx` bakiyeleri oraya taşınır. Sayılsaydı kapanış fişi
    atılmış bir dönemde kâr İKİ KEZ toplanırdı — bilançodaki `59` kuralının
    (MT-K1/2) gelir tablosu KARDEŞİ. Kural BU fonksiyonda yaşar, dolayısıyla
    Bilanço'nun `Dönem Net Kârı` ve `Geçmiş Yıllar Kârları` kalemlerini de
    kapsar; iki tablo aynı formülü paylaşmasaydı ayrışırlardı.

    Para `Decimal`dir; kayan nokta hiçbir aşamada devreye girmez.
    """
    toplam = _ZERO
    for code, net in nets.items():
        grup = group_of(code)
        # 🔴 MT-2/K6: `69` KAPANIŞ AKTARIM grubudur ve buradan da DIŞLANIR.
        # `690`/`692`ye kapanış fişi atılırsa aynı kâr hem kaynak `6xx`/`7xx`
        # hesaplarından hem aktarım hesabından İKİ KEZ sayılırdı. Bilanço
        # tarafında `59` için ZATEN var olan kuralın kardeşidir; ikisi ayrı
        # kalsaydı asimetri sessiz bir çift sayım bırakırdı. Değişim canlıda
        # NO-OP'tur (`69` tohumlanmaz) ama kural ARTIK YAZILIDIR.
        if grup[0] in INCOME_STATEMENT_CLASSES and grup not in EXCLUDED_INCOME_STATEMENT_GROUPS:
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


# --------------------------------------------------------------------------- #
# Gelir tablosu iskeleti — mockup GT:93-143 BİREBİR (MT-2 T1)
# --------------------------------------------------------------------------- #
#
# 🔴 **ARA TOPLAM İCAT EDİLMEZ.** TDHP'nin `Brüt Satış Kârı` / `Faaliyet Kârı`
# basamakları BU TABLODA YOKTUR çünkü mockup onları ÇİZMİYOR. Kalem sayısı
# bağlayıcıdır (bilanço 13'te durdu, K15) ve icat edilmiş bir basamak tasarım
# otoritesini aşardı: **2 bölüm · 6 kalem · 2 ara toplam · 1 genel toplam.**

INCOME_STATEMENT_SECTIONS: tuple[StatementSection, ...] = (
    StatementSection(
        key="revenue",
        title="GELİRLER",  # GT:95
        subtotal_label="Toplam Gelir",  # GT:108
        lines=(
            StatementLine("construction_revenue", "İş Hasılatı"),  # GT:98
            StatementLine("other_revenue", "Diğer Gelirler"),  # GT:103
        ),
    ),
    StatementSection(
        key="expenses",
        title="GİDERLER",  # GT:113
        subtotal_label="Toplam Gider",  # GT:136
        lines=(
            StatementLine("material_costs", "Malzeme Giderleri"),  # GT:116
            StatementLine("labor_costs", "İşçilik Giderleri"),  # GT:121
            StatementLine("subcontractor_costs", "Taşeron Ödemeleri"),  # GT:126
            StatementLine("general_expenses", "Genel Giderler"),  # GT:131
        ),
    ),
)

#: 🔴 GİDER bölümünün anahtarı. Bölümün İŞARET SÖZLEŞMESİ buradan okunur:
#: gelir kalemleri `Σ(alacak − borç)`, gider kalemleri `Σ(borç − alacak)`
#: basar ve doğru işlenmiş bir defterde İKİSİ DE POZİTİFTİR (mockup'ın altı
#: satırının hepsi pozitif). Bölüm SIRASINDAN (`sections[1]`) okuyan bir yazım,
#: bir gün üçüncü bölüm eklenirse sessizce yanlış işaret basardı.
INCOME_STATEMENT_EXPENSE_SECTION = "expenses"

#: Genel toplamın etiketi (GT:141). Değeri hiçbir kalemden değil
#: `period_profit()`ten gelir — Bilanço'nun `Dönem Net Kârı` satırıyla (BL:83)
#: BİREBİR aynı formüldür ve iki uç ayrışamaz.
INCOME_STATEMENT_PROFIT_LABEL = "DÖNEM KARI"

INCOME_STATEMENT_GROUPS: dict[str, str] = {
    # --- GELİRLER ---
    "60": "construction_revenue",
    "61": "construction_revenue",
    "64": "other_revenue",
    "67": "other_revenue",
    # --- GİDERLER ---
    "62": "general_expenses",
    "63": "general_expenses",
    "65": "general_expenses",
    "66": "general_expenses",
    "68": "general_expenses",
    "70": "general_expenses",
    "71": "material_costs",
    "72": "labor_costs",
    "73": "labor_costs",
    "74": "subcontractor_costs",
    "75": "general_expenses",
    "76": "general_expenses",
    "77": "general_expenses",
    "78": "general_expenses",
    "79": "material_costs",
}

#: 🔴 Haritasız kalan `6x`/`7x` grubu için YEDEK kalem — görünmezlik yasağı
#: (`_CASH_FLOW_FALLBACK` kardeşi). `69` DIŞINDA delik yoktur, yani bu dal bugün
#: erişilmezdir; yine de durur çünkü haritaya bir gün yeni bir grup girmezse
#: parası `Toplam Gider`den SESSİZCE düşer ve `DÖNEM KARI` (period_profit) onu
#: saymaya devam ederdi — kullanıcı farkın sebebini hiçbir satırda göremezdi.
_INCOME_STATEMENT_FALLBACK = "general_expenses"

#: 🔴 7/A YANSITMA hesapları — `chart_seed_data.py`de **`revenue`** türündedir
#: (ALACAK yönlü) ve KENDİ gider grubunda dururlar. Gider kalemi grup olarak
#: toplansaydı `710` (borç) ile `711` (alacak) BİRBİRİNİ GÖTÜRÜR ve kalem `0`
#: basardı — sekiz grupta birden. Bu yüzden gider kalemleri onları DIŞLAR ve
#: satır BRÜT gideri gösterir (MT-2/K7). Netleşme `DÖNEM KARI`da,
#: `period_profit()` içinde olur ve o formül DEĞİŞMEZ.
#:
#: Eşleme ANA HESAP kodundan (`code[:3]`) yapılır, tam eşitlikten değil: alt
#: hesap (`711.01`) kullanıcı tarafından açılabilir ve tam eşitlik onu kaçırır.
#: `account_type` OKUNMAZ — yanlış TÜR işaretlenmiş tek bir hesap, sekiz gider
#: kalemini birden sessizce sıfırlardı; TDHP'nin kod düzeni ise sabittir.
COST_REFLECTION_ACCOUNTS: frozenset[str] = frozenset(
    {"701", "711", "721", "731", "741", "751", "761", "771", "781", "798"}
)

INCOME_STATEMENT_SOURCE_NOTES: dict[str, str] = {
    # --- SINIF 6 ---
    "60": "TDHP 60 Brüt Satışlar — GT:98 İş Hasılatı (mockup 24.870.500)",
    "61": "TDHP 61 Satış İndirimleri (-) — GT:98; borç bakiyesi hasılatı DÜŞÜRÜR (K2)",
    "62": "TDHP 62 Satışların Maliyeti — GT:131 Genel Giderler; mockup ayrı satır ÇİZMİYOR "
    "ve `Brüt Satış Kârı` basamağı İCAT EDİLMEZ",
    "63": "TDHP 63 Faaliyet Giderleri — GT:131 Genel Giderler",
    "64": "TDHP 64 Diğer Faaliyetlerden Olağan Gelir ve Kârlar — GT:103 Diğer Gelirler",
    "65": "TDHP 65 Diğer Faaliyetlerden Olağan Gider ve Zararlar — GT:131",
    "66": "TDHP 66 Finansman Giderleri — GT:131; mockup ayrı `Finansman` satırı çizmiyor",
    "67": "TDHP 67 Olağandışı Gelir ve Kârlar — GT:103 Diğer Gelirler (mockup 124.200)",
    "68": "TDHP 68 Olağandışı Gider ve Zararlar — GT:131",
    "69": "TDHP 69 Dönem Net Kârı/Zararı — 🔴 HİÇBİR kaleme girmez ve `period_profit()`e de "
    "girmez (K6): kapanış AKTARIM hesabı, çift sayım yasağı. `59`un kardeşi",
    # --- SINIF 7 ---
    "70": "TDHP 70 Maliyet Muhasebesi Bağlantı Hesapları — GT:131; `701` yansıtma DIŞLANIR",
    "71": "TDHP 71 Direkt İlk Madde ve Malzeme Giderleri — GT:116 Malzeme Giderleri "
    "(mockup 12.480.000); `711` yansıtma DIŞLANIR (K7)",
    "72": "TDHP 72 Direkt İşçilik Giderleri — GT:121 İşçilik Giderleri; `721` DIŞLANIR",
    "73": "TDHP 73 Genel Üretim Giderleri — GT:121 İşçilik Giderleri; `731` DIŞLANIR",
    "74": "TDHP 74 Hizmet Üretim Maliyeti — GT:126 Taşeron Ödemeleri. 🔴 TDHP'de 'taşeron' "
    "grubu YOKTUR (`101 Alınan Çekler` tuzağının kardeşi); inşaatta taşeron işi hizmet "
    "üretim maliyetidir ve `74` başka hiçbir satıra doğal düşmez. Satırı boş bırakıp `0` "
    "bastırmak İKİ ANLAMLI `0` üretirdi. `741` DIŞLANIR",
    "75": "TDHP 75 Araştırma ve Geliştirme Giderleri — GT:131; `751` DIŞLANIR",
    "76": "TDHP 76 Pazarlama, Satış ve Dağıtım Giderleri — GT:131; `761` DIŞLANIR",
    "77": "TDHP 77 Genel Yönetim Giderleri — GT:131 Genel Giderler; `771` DIŞLANIR",
    "78": "TDHP 78 Finansman Giderleri (7/B) — GT:131; `781` DIŞLANIR",
    "79": "TDHP 79 Gider Çeşitleri (7/B) — GT:116 Malzeme Giderleri; 7/B'nin `790 İlk Madde "
    "ve Malzeme Giderleri` karşılığı 7/A'nın `710`udur. `798` yansıtma DIŞLANIR",
}


def is_cost_reflection(code: str) -> bool:
    """Hesap bir 7/A YANSITMA hesabı mı? — gider kalemleri bunları DIŞLAR (K7).

    🔴 Kural GİDER kalemlerine özgüdür, `period_profit()`e DEĞİL: yansıtma
    hesabı gerçek bir alacak bakiyesidir ve dönem kârının netleşmesinde
    SAYILMAK zorundadır. İki yerde birden dışlansaydı maliyet iki kez düşerdi.
    """
    group_of(code)  # geçersiz kod GÜRÜLTÜLÜ patlar (`balance_sheet_line_for` deseni)
    return code[:3] in COST_REFLECTION_ACCOUNTS


def income_statement_line_for(code: str) -> str | None:
    """Hesap kodunun düşeceği gelir tablosu KALEMİ; `None` = tabloya GİRMEZ.

    `None` dönen İKİ hâl vardır ve ikisi de AÇIK bir karardır:

    * **`1x`–`5x`** — bilanço hesapları. `balance_sheet_line_for`ün AYNADAKİ
      karşılığıdır: orada `6x`/`7x` `None` döner, burada tersi. İki fonksiyon
      birlikte TÜM kod uzayını tam olarak BİR KEZ kaplar.
    * **`69`** — kapanış aktarım grubu (K6). Yedek kaleme düşseydi
      `Genel Giderler` kapanış fişini gider sayardı.

    Onun dışında her `6x`/`7x` grubu bir kaleme düşer; haritada delik yoktur ve
    olsa bile `_INCOME_STATEMENT_FALLBACK` onu GÖRÜNÜR tutar.
    """
    grup = group_of(code)
    if grup[0] not in INCOME_STATEMENT_CLASSES or grup in EXCLUDED_INCOME_STATEMENT_GROUPS:
        return None
    return INCOME_STATEMENT_GROUPS.get(grup, _INCOME_STATEMENT_FALLBACK)
