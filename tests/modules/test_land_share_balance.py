"""P-KK T3/T6 — paylaşım DENGE çekirdeği (oturumsuz, yetkisiz, saf).

Bu dosya `land_share_balance`i veritabanına HİÇ dokunmadan ölçer: denge iki
ayrı hesaptır (adet · değer) ve ikisinin de ayrışma noktaları sabit bir beklenen
sayı yazarak değil, KÜMEYİ KURUP sonucu türeterek çakılır (MT-2 kanonu:
"%100 kapsam doğruluk kanıtı değildir").

Aranan ayrışmalar:

1. **Yuvarlama toplamı** — iki tarafın beklenen adedi TOPLAMI toplam üniteyi
   vermek zorunda. Tek sayı testi bunu görmez: `round(42×0,55)=23` ve
   `round(42×0,45)=19` bugün toplamı tutturur, ama 7/33/101 gibi sayılarda iki
   ayrı yuvarlama 43 üretir. Bu yüzden `owner = toplam − our` TEK yuvarlamayla
   türer ve bekçi bunu tüm aralıkta çakar.
2. **Sıfıra bölme** — atanmış değer toplamı 0 ise sapma HESAPLANAMAZ. `None`
   döner, `0` DEĞİL: sıfır sapma ile hesaplanamaz sapma aynı şey değildir ve
   "0" ekrana "✓ denge uygun" bastırırdı.
"""

from decimal import Decimal

import pytest

from app.modules.projects import land_share_balance as balance

_HUNDRED = Decimal("100")


# --- Adet dengesi: yuvarlama TEK yerde (K2) ---


@pytest.mark.parametrize("total", [0, 1, 2, 3, 7, 33, 41, 42, 101, 999])
@pytest.mark.parametrize("our_pct", ["0.00", "45.00", "50.00", "55.00", "66.67", "100.00"])
def test_expected_counts_always_sum_to_total(total: int, our_pct: str) -> None:
    """🔴 Toplam bekçisi: 42 ünite %55/%45 → 23+19=42 olmalı, 43 DEĞİL.

    İki tarafı ayrı ayrı yuvarlamak (`round(n×our)` + `round(n×owner)`) tek bir
    örnekte doğru görünüp başka bir sayıda toplamı bir fazla verir. Bekçi bu
    yüzden tek örneğe değil çapraz kümeye bakar.
    """
    ours, owner = balance.expected_counts(total, Decimal(our_pct))

    assert ours + owner == total
    assert ours >= 0
    assert owner >= 0


def test_expected_counts_matches_mockup_arithmetic() -> None:
    """Mockup `Form - Paylasim Girisi`: "42 ünite → Biz 23 · Arsa Sahibi 19"."""
    assert balance.expected_counts(42, Decimal("55.00")) == (23, 19)


def test_expected_counts_rounds_half_up_not_bankers() -> None:
    """`round()` yerleşiği YARIYI ÇİFTE yuvarlar (10×0,45=4,5 → 4).

    Para/pay hesabında proje boyunca ROUND_HALF_UP kullanılır; iki farklı
    yuvarlama kuralı aynı ekranda iki farklı "beklenen adet" üretirdi.
    """
    assert balance.expected_counts(10, Decimal("45.00")) == (5, 5)


# --- Değer dengesi: sapma + tolerans (K3) ---


def test_value_balance_matches_mockup_deviation() -> None:
    """Mockup: bize ₺26,4M / arsaya ₺21,1M → %55,6/%44,4, sapma %0,6, ✓ uygun."""
    result = balance.value_balance(
        our_value=Decimal("26400000.00"),
        owner_value=Decimal("21100000.00"),
        our_share_pct=Decimal("55.00"),
    )

    assert result.our_actual_pct == Decimal("55.58")
    assert result.owner_actual_pct == Decimal("44.42")
    assert result.deviation_pct == Decimal("0.58")
    assert result.is_within_tolerance is True
    assert result.tolerance_pct == balance.LAND_SHARE_VALUE_TOLERANCE_PCT


def test_value_balance_percentages_sum_to_hundred() -> None:
    """İki yüzde ayrı ayrı yuvarlanırsa toplam %100,01 çıkabilir — çıkmamalı."""
    result = balance.value_balance(
        our_value=Decimal("1.00"), owner_value=Decimal("2.00"), our_share_pct=Decimal("55.00")
    )

    assert result.our_actual_pct + result.owner_actual_pct == _HUNDRED


def test_value_balance_deviation_is_signed() -> None:
    """Sapma İŞARETLİDİR: eksik pay ile fazla pay aynı sayıya indirgenmez."""
    below = balance.value_balance(
        our_value=Decimal("40.00"), owner_value=Decimal("60.00"), our_share_pct=Decimal("55.00")
    )
    above = balance.value_balance(
        our_value=Decimal("70.00"), owner_value=Decimal("30.00"), our_share_pct=Decimal("55.00")
    )

    assert below.deviation_pct == Decimal("-15.00")
    assert above.deviation_pct == Decimal("15.00")


def test_value_balance_outside_tolerance_is_flagged() -> None:
    result = balance.value_balance(
        our_value=Decimal("60.00"), owner_value=Decimal("40.00"), our_share_pct=Decimal("55.00")
    )

    assert result.deviation_pct == Decimal("5.00")
    assert result.is_within_tolerance is False


def test_value_balance_tolerance_boundary_is_inclusive() -> None:
    """Eşiğin TAM üstü hâlâ "uygun"dur — `<` ile `<=` arasındaki kör nokta."""
    result = balance.value_balance(
        our_value=Decimal("56.00"), owner_value=Decimal("44.00"), our_share_pct=Decimal("55.00")
    )

    assert result.deviation_pct == balance.LAND_SHARE_VALUE_TOLERANCE_PCT
    assert result.is_within_tolerance is True


# --- Sıfıra bölme: hesaplanamaz ≠ sıfır ---


@pytest.mark.parametrize(
    ("our_value", "owner_value"),
    [(Decimal("0.00"), Decimal("0.00"))],
)
def test_value_balance_without_assigned_value_is_null_not_zero(
    our_value: Decimal, owner_value: Decimal
) -> None:
    """🔴 Atanmış rayiç değer toplamı 0 → sapma HESAPLANAMAZ.

    `0` dönmek ekrana "✓ değer dengesi uygun" bastırırdı; oysa hiçbir ünitenin
    rayiç değeri girilmemiş olabilir. `tolerance_pct` yine döner (frontend
    eşiği kopyalamasın diye), payda yokken bile.
    """
    result = balance.value_balance(
        our_value=our_value, owner_value=owner_value, our_share_pct=Decimal("55.00")
    )

    assert result.our_actual_pct is None
    assert result.owner_actual_pct is None
    assert result.deviation_pct is None
    assert result.is_within_tolerance is None
    assert result.tolerance_pct == balance.LAND_SHARE_VALUE_TOLERANCE_PCT
    assert result.assigned_value_total == Decimal("0.00")


def test_count_balance_missing_is_signed_and_sets_sum_to_total() -> None:
    """Üç kümenin (biz · arsa · atanmamış) toplamı toplam üniteye EŞİT."""
    result = balance.count_balance(
        total_unit_count=42,
        our_assigned_count=20,
        owner_assigned_count=16,
        our_share_pct=Decimal("55.00"),
    )

    assert result.our_expected_count == 23
    assert result.owner_expected_count == 19
    assert result.unassigned_count == 6
    assert result.our_missing_count == 3
    assert result.owner_missing_count == 3
    assert (
        result.our_assigned_count + result.owner_assigned_count + result.unassigned_count
        == result.total_unit_count
    )


def test_count_balance_surplus_is_negative() -> None:
    """Fazla atama EKSİ döner — "3 fazla" ile "3 eksik" aynı sayı olamaz."""
    result = balance.count_balance(
        total_unit_count=10,
        our_assigned_count=8,
        owner_assigned_count=2,
        our_share_pct=Decimal("55.00"),
    )

    assert result.our_expected_count == 6
    assert result.our_missing_count == -2
    assert result.owner_missing_count == 2
