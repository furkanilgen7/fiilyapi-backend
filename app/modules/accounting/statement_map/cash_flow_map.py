"""Nakit akış iskeleti + karşı hesap grubu→(bölüm, kalem) haritası (NA:64-104).

🔴 Paylaşılan her şey `core.py`dedir; bu dosya YALNIZ nakit akışına özgü olanı
taşır.
"""

from .core import (
    StatementLine,
    StatementSection,
    group_of,
)

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
