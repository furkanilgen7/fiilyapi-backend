"""`statement_map` PAYLASILAN CEKIRDEGI — üç tablonun da okuduğu tek katman.

🔴 **SAF** kalır (`codes.py` emsali): DB bilmez, Pydantic bilmez, `today` bilmez.
Girdisi bir hesap KODU, çıktısı bir kalem ANAHTARIDIR.

Burada YALNIZ **birden fazla tablonun** okuduğu şeyler durur:

* `group_of()` — üçü de aynı iki haneli grubu türetir;
* `StatementLine` / `StatementSection` / `StatementSide` — üçünün de iskelet
  yapı taşları;
* `INCOME_STATEMENT_CLASSES` / `EXCLUDED_INCOME_STATEMENT_GROUPS` +
  `period_profit()` — 🔴 gelir tablosunun BOTTOM LINE'ı, ama Bilanço'nun
  `Dönem Net Kârı` (BL:83) ve `Geçmiş Yıllar Kârları` (BL:82) kalemleri de
  AYNI formülden gelir. İki kopya kaçınılmaz olarak ayrışırdı, bu yüzden
  formül burada TEK KOPYADIR ve iki yaprak modül de onu ithal eder.

Yaprak modüller (`balance_sheet_map` · `cash_flow_map` ·
`income_statement_map`) YALNIZ buraya bağlıdır; birbirlerini ithal etmezler.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

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
