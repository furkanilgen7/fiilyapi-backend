"""P-KK — paylaşım DENGE çekirdeği: oturumsuz, yetkisiz, saf.

`cost_summary.py` ↔ `costs.py` ayrımının aynısı: burası formüllerin TEK yeridir
ve veritabanına, kimliğe, ORM'a DOKUNMAZ; oturuma dokunan orkestrasyon
`land_share.py`dadır. Böylece yuvarlama kuralları uç kurmadan sınanabilir.

🔴 Tüm oran/para hesabı `Decimal` ile yapılır — float bu dosyada YOKTUR.
"""

from decimal import ROUND_HALF_UP, Decimal

from app.modules.projects.land_share_schemas import (
    LandShareCountBalance,
    LandShareValueBalance,
)

__all__ = [
    "LAND_SHARE_VALUE_TOLERANCE_PCT",
    "count_balance",
    "expected_counts",
    "value_balance",
]

# 🔴 EŞİK TEK YERDE YAŞAR (K3). Yanıt bu sabiti `tolerance_pct` olarak geri
# döndürür ki frontend kopyalamak zorunda kalmasın: bir eşik iki yerde yaşarsa
# zamanla ayrışır ve iki ekran aynı sapmaya farklı yanıt verir.
#
# ⚠️ Değer kullanıcıya SORULMADI; yönetim varsayılanıdır ve açık borçtur.
LAND_SHARE_VALUE_TOLERANCE_PCT = Decimal("1.0")

_HUNDRED = Decimal("100")
_PCT = Decimal("0.01")
_MONEY = Decimal("0.01")
_WHOLE = Decimal("1")


def _round_pct(value: Decimal) -> Decimal:
    return value.quantize(_PCT, rounding=ROUND_HALF_UP)


def _round_money(value: Decimal) -> Decimal:
    return value.quantize(_MONEY, rounding=ROUND_HALF_UP)


def expected_counts(total_unit_count: int, our_share_pct: Decimal) -> tuple[int, int]:
    """Sözleşme oranından BEKLENEN ünite adetleri — YUVARLAMA TEK YERDE.

    Arsa sahibi tarafı `toplam − biz` ile TÜRETİLİR, ayrı yuvarlanmaz. İki
    tarafı bağımsız yuvarlamak toplamı bozar: 42 ünite %55/%45'te
    `round(23,1)=23` ve `round(18,9)=19` bugün 42 verir ama 7 ünitede
    `round(3,85)=4` + `round(3,15)=3` = 7 iken 101 üniteli bir projede
    `round(55,55)=56` + `round(45,45)=45` = 101 yerine 101 çıkmaz — kural
    tutarsızdır. Türetme bu sınıfı bütünüyle kapatır.

    Yerleşik `round()` KULLANILMAZ: o yarıyı ÇİFTE yuvarlar (banker's rounding,
    `round(4.5) == 4`) ve projenin geri kalanı ROUND_HALF_UP kullanır. İki
    yuvarlama kuralı aynı ekranda iki farklı "beklenen adet" üretirdi.
    """
    ours = int(
        (Decimal(total_unit_count) * our_share_pct / _HUNDRED).quantize(
            _WHOLE, rounding=ROUND_HALF_UP
        )
    )
    return ours, total_unit_count - ours


def count_balance(
    *,
    total_unit_count: int,
    our_assigned_count: int,
    owner_assigned_count: int,
    our_share_pct: Decimal,
) -> LandShareCountBalance:
    """`Ünite Sayısı Dengesi` kartı (mockup: "23 gereken · 20 atanan · 3 eksik").

    Atanmamış adet TÜREVDİR (`toplam − biz − arsa`): ayrıca sayılsaydı üç kümenin
    toplamı toplam üniteden kayabilirdi.
    """
    our_expected, owner_expected = expected_counts(total_unit_count, our_share_pct)
    return LandShareCountBalance(
        total_unit_count=total_unit_count,
        our_expected_count=our_expected,
        owner_expected_count=owner_expected,
        our_assigned_count=our_assigned_count,
        owner_assigned_count=owner_assigned_count,
        unassigned_count=total_unit_count - our_assigned_count - owner_assigned_count,
        # İŞARETLİ: artı = eksik atama, eksi = fazla atama.
        our_missing_count=our_expected - our_assigned_count,
        owner_missing_count=owner_expected - owner_assigned_count,
    )


def value_balance(
    *, our_value: Decimal, owner_value: Decimal, our_share_pct: Decimal
) -> LandShareValueBalance:
    """`Değer Dengesi (Rayiç)` kartı — adet dengesinden BAĞIMSIZ hesaplanır.

    Payda ATANMIŞ değerdir: atanmamış ünitenin rayici gerçekleşen oranı
    seyreltmemelidir (o ünite henüz kimsenin payı değildir).

    🔴 SIFIRA BÖLME: payda 0 ise dört alan `None` döner, `0` DEĞİL. Sıfır sapma
    ("tam dengede") ile hesaplanamaz sapma ("rayiç girilmemiş") aynı şey
    değildir; `0` dönmek ekrana yeşil onay bastırırdı.

    Arsa yüzdesi `100 − biz` ile TÜRETİLİR (adet tarafındaki gerekçenin aynısı):
    iki yüzdeyi ayrı yuvarlamak toplamı %100,01 yapabilirdi.
    """
    assigned_total = _round_money(our_value + owner_value)
    if assigned_total <= 0:
        return LandShareValueBalance(
            our_value=_round_money(our_value),
            owner_value=_round_money(owner_value),
            assigned_value_total=assigned_total,
            our_actual_pct=None,
            owner_actual_pct=None,
            deviation_pct=None,
            tolerance_pct=LAND_SHARE_VALUE_TOLERANCE_PCT,
            is_within_tolerance=None,
        )

    our_actual = _round_pct(our_value / assigned_total * _HUNDRED)
    deviation = _round_pct(our_actual - our_share_pct)
    return LandShareValueBalance(
        our_value=_round_money(our_value),
        owner_value=_round_money(owner_value),
        assigned_value_total=assigned_total,
        our_actual_pct=our_actual,
        owner_actual_pct=_HUNDRED - our_actual,
        deviation_pct=deviation,
        tolerance_pct=LAND_SHARE_VALUE_TOLERANCE_PCT,
        # `<=`: eşiğin TAM üstü hâlâ "uygun"dur. `<` yazmak %1,00 sapmayı
        # kırmızıya düşüren sessiz bir sınır hatası olurdu.
        is_within_tolerance=abs(deviation) <= LAND_SHARE_VALUE_TOLERANCE_PCT,
    )
