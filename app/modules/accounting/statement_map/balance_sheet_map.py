"""Bilanço iskeleti + grup→kalem haritası (mockup BL:44-88 BİREBİR).

🔴 Paylaşılan her şey `core.py`dedir; bu dosya YALNIZ bilançoya özgü olanı
taşır. `INCOME_STATEMENT_CLASSES` buradan okunur ama BURADA TANIMLANMAZ:
`period_profit()` ile aynı kümeyi kullanmak zorundadır, iki kopya ayrışırdı.
"""

from .core import (
    INCOME_STATEMENT_CLASSES,
    StatementLine,
    StatementSection,
    StatementSide,
    group_of,
)

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
