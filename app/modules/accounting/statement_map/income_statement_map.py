"""Gelir tablosu iskeleti + grup→kalem haritası (mockup GT:93-143 BİREBİR).

🔴 Paylaşılan her şey `core.py`dedir; bu dosya YALNIZ gelir tablosuna özgü
olanı taşır. `DÖNEM KARI` satırının DEĞERİ burada DEĞİL, `core.period_profit()`
içindedir — Bilanço'nun `Dönem Net Kârı` kalemiyle birebir aynı formüldür.
"""

from .core import (
    EXCLUDED_INCOME_STATEMENT_GROUPS,
    INCOME_STATEMENT_CLASSES,
    StatementLine,
    StatementSection,
    group_of,
)

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

#: 🔴 **K7-b — aktarım çiftinin BORÇ bacağı** (final review CRITICAL-1). İkisi de
#: `expense` TÜRÜNDEDİR (`chart_seed_data.py:460` ve `:508`), yani bir GİDER
#: hesabı gibi GÖRÜNÜR — onları ayıran şey TÜRLERİ değil, bir MALİYET AKTARIM
#: bacağı olmalarıdır (`690`/`692`nin sınıf 7'deki kardeşi). Sayılsalardı:
#: `790`+`799` **ikisi de grup `79`da** → `Malzeme Giderleri` **İKİ KAT**;
#: `700`+`701` **iki bacak da sınıf 7'de** → `Genel Giderler` HİÇ VAR OLMAYAN
#: bir gider. 🔴 `period_profit()`e GİRMEZLER: orada çiftler zaten birbirini
#: götürür ve kâr DOĞRUDUR — bu bir **SATIR** kusuruydu, kâr kusuru değil.
COST_TRANSFER_ACCOUNTS: frozenset[str] = frozenset({"700", "799"})

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
    "70": "TDHP 70 Maliyet Muhasebesi Bağlantı Hesapları — GT:131; ÇİFTİN İKİ BACAĞI DA DIŞLANIR "
    "(`701` alacak + `700` borç, K7-b): ikisi de sınıf 7'de, sayılsalardı var olmayan "
    "gider doğardı",
    "71": "TDHP 71 Direkt İlk Madde ve Malzeme Giderleri — GT:116 Malzeme Giderleri "
    "(mockup 12.480.000); `711` yansıtma DIŞLANIR (K7). 7/A'da transfer bacağı `700`tadır",
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
    "ve Malzeme Giderleri` karşılığı 7/A'nın `710`udur. `798` (alacak) VE `799` (borç) DIŞLANIR "
    "(K7-b): `790`+`799` aynı grupta, sayılsalardı satır İKİ KAT basardı",
}


def is_cost_reflection(code: str) -> bool:
    """Hesap bir MALİYET AKTARIM hesabı mı? — gider kalemleri bunları DIŞLAR.

    İki küme birden okunur ve ikisi de aynı ailenin bacaklarıdır:

    * `COST_REFLECTION_ACCOUNTS` — çiftin **ALACAK** bacağı (`711`, `741`, …).
      Dışlanmasaydı `710`+`711` birbirini götürür, satır **`0`** basardı (K7).
    * `COST_TRANSFER_ACCOUNTS` — çiftin **BORÇ** bacağı (`700`, `799`).
      Dışlanmasaydı `790`+`799` aynı parayı **İKİ KAT** basar, `700` ise HİÇ
      VAR OLMAYAN bir gider yaratırdı (K7-b, final review CRITICAL-1).

    🔴 İkisi de TEK noktada birleşir. Ayrı ayrı sorulsaydı çağıran hangi
    bacağın hangi kümede olduğunu bilmek zorunda kalır ve bir sonraki dilim
    birini sormayı unuturdu.

    🔴 Kural GİDER kalemlerine özgüdür, `period_profit()`e DEĞİL: her iki bacak
    da gerçek bakiyelerdir ve dönem kârının netleşmesinde SAYILMAK zorundadır —
    orada zaten birbirlerini götürürler. İki yerde birden dışlansalardı maliyet
    iki kez düşerdi.
    """
    group_of(code)  # geçersiz kod GÜRÜLTÜLÜ patlar (`balance_sheet_line_for` deseni)
    return code[:3] in COST_REFLECTION_ACCOUNTS or code[:3] in COST_TRANSFER_ACCOUNTS


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
