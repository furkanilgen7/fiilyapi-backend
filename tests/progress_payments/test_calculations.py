"""Task H2 — hesap motoru saf fonksiyon testleri (spec §6, §8).

Altın sayılar E15 (151-172, 177-190) ve OLU (156, 122/126 K5 sapması) mockup
satırlarından; her test docstring'i kaynağı gösterir. DB/ORM yoktur — yalnız
`Decimal` girdi/çıktı.
"""

from datetime import date
from decimal import Decimal

from app.modules.progress_payments import calculations as calc


def test_e15_odeme_hesabi_altin():
    """E15 151-172: brüt 2.110.000 → KDV +422.000 → avans −422.000 →
    teminat −105.500 → net 2.004.500. advance_recovered=1.258.000 (E14 tutarlı)."""
    gross = Decimal("2110000")
    vat = calc.vat_amount(gross, Decimal("20"))
    assert vat == Decimal("422000.00")
    advance = calc.advance_deduction(gross, Decimal("20"), Decimal("11200000"), Decimal("1258000"))
    assert advance == Decimal("422000.00")  # tavan (2.240.000) henüz uzak
    retention = calc.retention_amount(gross, Decimal("5"))
    assert retention == Decimal("105500.00")
    assert calc.net_amount(gross, vat, advance, retention) == Decimal("2004500.00")


def test_avans_tavani_kismi():
    """Tavana 40.000 kala: kesinti %20·brüt DEĞİL, kalan 40.000."""
    advance = calc.advance_deduction(
        Decimal("2110000"), Decimal("20"), Decimal("11200000"), Decimal("2200000")
    )
    assert advance == Decimal("40000.00")


def test_avans_tavani_dolmus():
    advance = calc.advance_deduction(
        Decimal("2110000"), Decimal("20"), Decimal("11200000"), Decimal("2240000")
    )
    assert advance == Decimal("0.00")


def test_avans_tavani_asilmis_negatif_kalinti_sifirlanir():
    """Önceki kesintiler toplamı tavanı zaten geçmişse (teorik/aşım senaryosu):
    kalan negatif olamaz — max(...,0) ile 0'a kırpılır."""
    advance = calc.advance_deduction(
        Decimal("2110000"), Decimal("20"), Decimal("11200000"), Decimal("2300000")
    )
    assert advance == Decimal("0.00")


def test_katsayisiz_satir_olu_156():
    """OLU 156 (03.003, katsayı 1,000): 21.500 × 61,2 = 1.315.800 — iki kuralda da aynı."""
    assert calc.line_total(Decimal("21500"), Decimal("1.000"), Decimal("61.2")) == Decimal(
        "1315800.00"
    )


def test_katsayili_satir_kurus_k5():
    """K5 ONAYLI SAPMA: 1.850 × 1,142 = 2.112,70 (mockup 2.113'e yuvarlıyordu, OLU 122).
    2.112,70 × 1.320 = 2.788.764,00 (mockup 2.789.160 DEĞİL, OLU 126)."""
    assert calc.adjusted_unit_price(Decimal("1850"), Decimal("1.142")) == Decimal("2112.70")
    assert calc.line_total(Decimal("1850"), Decimal("1.142"), Decimal("1320")) == Decimal(
        "2788764.00"
    )


def test_katsayili_satir_kurus_olu_137_141():
    """OLU 137/141: 2.100×1,142=2.398,20 (mockup 2.398'e yuvarlıyordu) → 2.398,20×300=719.460,00
    (mockup 719.400 DEĞİL — K5 kuruş korunur)."""
    assert calc.adjusted_unit_price(Decimal("2100"), Decimal("1.142")) == Decimal("2398.20")
    assert calc.line_total(Decimal("2100"), Decimal("1.142"), Decimal("300")) == Decimal(
        "719460.00"
    )


def test_yuvarlama_sirasi_onemli():
    """Spec §6.1: line_total, quantize2 EDİLMİŞ adjusted_unit_price üstünden hesaplanır
    (ham çarpımdan değil) — mutasyon denetimi bu sırayı bozarak doğrulanır."""
    # 185 × 1.142 = 211.27 (tam) -> quantize2 -> 211.27; × 2880 = 608457.60
    assert calc.adjusted_unit_price(Decimal("185"), Decimal("1.142")) == Decimal("211.27")
    assert calc.line_total(Decimal("185"), Decimal("1.142"), Decimal("2880")) == Decimal(
        "608457.60"
    )


def test_yuvarlama_sirasi_ara_yuvarlamayla_ayirt_edilir():
    """Formül sırasının GERÇEK etkisi: 1,00 × 1,005 = 1,005 tam ortada — önce
    quantize2(1,005)=1,01'e yuvarlanır, SONRA ×1000 = 1.010,00. Ham çarpımı tek
    seferde yuvarlasaydık 1,005×1000=1.005,00 çıkardı (spec §6.1 sıra kuralı)."""
    assert calc.adjusted_unit_price(Decimal("1.00"), Decimal("1.005")) == Decimal("1.01")
    assert calc.line_total(Decimal("1.00"), Decimal("1.005"), Decimal("1000")) == Decimal("1010.00")


def test_miktar_sifir_satir_toplami_sifir():
    assert calc.line_total(Decimal("1850"), Decimal("1.142"), Decimal("0")) == Decimal("0.00")


def test_yuvarlama_round_half_up():
    """quantize2 kenarı: .005 yukarı yuvarlanır (banker's rounding DEĞİL)."""
    assert calc.quantize2(Decimal("2.005")) == Decimal("2.01")


def test_sure_pct_uc_dahil():
    """Kalıcı karar 9: (bugün − start + 1) / (end − start + 1) × 100."""
    p = calc.duration_pct(date(2026, 1, 1), date(2026, 1, 10), date(2026, 1, 5))
    assert p == Decimal("50.00")


def test_sure_pct_tarih_yoksa_none():
    assert calc.duration_pct(None, None, None) is None


def test_sure_pct_bugun_aralik_oncesi_sifira_kirpilir():
    p = calc.duration_pct(date(2026, 1, 10), date(2026, 1, 20), date(2026, 1, 1))
    assert p == Decimal("0.00")


def test_sure_pct_bugun_aralik_sonrasi_yuze_kirpilir():
    p = calc.duration_pct(date(2026, 1, 1), date(2026, 1, 10), date(2026, 2, 1))
    assert p == Decimal("100.00")
