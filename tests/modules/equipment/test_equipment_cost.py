"""MK-1 T2 — makine maliyet ÇEKİRDEĞİ (`cost.py`) saf fonksiyonları.

Spec: `docs/superpowers/specs/2026-08-13-mk1-makine-cekirdegi-design.md`
(K16 · K18 · K19). DB YOKTUR: `payroll/compute.py` emsali — türev TEK
KAYNAKTAN, router'dan bağımsız sınanır.

**PARA sınıfı.** Her beklenti ya bir mockup satırından ya da bağlanmış bir
karardan gelir; hiçbir sayı "makul göründüğü için" yazılmamıştır.
"""

from decimal import Decimal

import pytest

from app.modules.equipment import cost
from app.modules.equipment.models import EquipmentRatePeriod

# 🔴 K18 mockup doğrulaması — DÖRT ekipmanda birden `DAILY_HOURS = 10`.
# (M1 günlük kira ↔ M3 satır saati ve satır maliyeti)
#   ad, günlük kira, ay içi saat, M3 satır maliyeti, türeyen saatlik bedel
MOCKUP_GUNLUK_KIRA = (
    ("Tower Crane TC-48", Decimal("3200"), Decimal("186"), Decimal("59520"), Decimal("320")),
    ("Ekskavatör CAT 320", Decimal("2800"), Decimal("152"), Decimal("42560"), Decimal("280")),
    ("Damperli Kamyon", Decimal("1400"), Decimal("168"), Decimal("23520"), Decimal("140")),
    ("Kompresör SC-200", Decimal("650"), Decimal("144"), Decimal("9360"), Decimal("65")),
)

# 🔴 K19 mockup doğrulaması — M4 günlük yakıt tablosunun DÖRT satırı.
# `liters × unit_price` TAM SAYIYA, ROUND_HALF_UP.
MOCKUP_YAKIT_SATIRLARI = (
    (Decimal("45"), Decimal("39.70"), Decimal("1787")),  # 1.786,5 → yukarı
    (Decimal("62"), Decimal("39.70"), Decimal("2461")),  # 2.461,4 → aşağı
    (Decimal("38"), Decimal("39.70"), Decimal("1509")),  # 1.508,6 → yukarı
    (Decimal("14"), Decimal("39.70"), Decimal("556")),  # 555,8 → yukarı
)


class TestDailyHoursMockupDogrulamasi:
    """`DAILY_HOURS = 10` sabiti tersine mühendisliğin ÜRÜNÜDÜR; bu sınıf onu
    dört ekipmanda birden kilitler. Sabit değişirse dördü de kırmızıya döner."""

    @pytest.mark.parametrize(
        ("ad", "gunluk_kira", "saat", "beklenen_maliyet", "beklenen_saatlik"),
        MOCKUP_GUNLUK_KIRA,
        ids=[satir[0] for satir in MOCKUP_GUNLUK_KIRA],
    )
    def test_gunluk_kiradan_m3_satir_maliyeti_yeniden_uretilir(
        self,
        ad: str,
        gunluk_kira: Decimal,
        saat: Decimal,
        beklenen_maliyet: Decimal,
        beklenen_saatlik: Decimal,
    ) -> None:
        assert (
            cost.hourly_rate(rate_amount=gunluk_kira, rate_period=EquipmentRatePeriod.daily)
            == beklenen_saatlik
        )
        assert (
            cost.compute_cost(
                hours=saat,
                rate_amount=gunluk_kira,
                rate_period=EquipmentRatePeriod.daily,
            )
            == beklenen_maliyet
        )

    def test_daily_hours_sabiti_ondur(self) -> None:
        """Sabitin kendisi de kayıtlıdır: dolaylı doğrulama yetmez, çünkü
        `hourly_rate` bozulsa da bölme tesadüfen tutabilirdi."""
        assert cost.DAILY_HOURS == Decimal("10")


class TestSaatlikBedel:
    def test_hourly_donemde_bedel_oldugu_gibi_alinir(self) -> None:
        assert cost.hourly_rate(
            rate_amount=Decimal("320"), rate_period=EquipmentRatePeriod.hourly
        ) == Decimal("320")

    def test_monthly_donemde_paydayi_kapasite_verir(self) -> None:
        """K7: kapasite VERİDİR — 200 varsayılan ama ekipmana göre değişir."""
        assert cost.hourly_rate(
            rate_amount=Decimal("64000"),
            rate_period=EquipmentRatePeriod.monthly,
            monthly_capacity_hours=200,
        ) == Decimal("320")
        assert cost.hourly_rate(
            rate_amount=Decimal("64000"),
            rate_period=EquipmentRatePeriod.monthly,
            monthly_capacity_hours=100,
        ) == Decimal("640")


class TestFailClosedMaliyet:
    """K16 — hesaplanamayan maliyet UYDURULMAZ: `None`, 0 DEĞİL."""

    def test_rate_amount_yoksa_none(self) -> None:
        assert (
            cost.compute_cost(
                hours=Decimal("186"),
                rate_amount=None,
                rate_period=EquipmentRatePeriod.daily,
            )
            is None
        )

    def test_rate_period_yoksa_none(self) -> None:
        assert (
            cost.compute_cost(hours=Decimal("186"), rate_amount=Decimal("3200"), rate_period=None)
            is None
        )

    def test_monthly_iken_kapasite_yoksa_none(self) -> None:
        assert (
            cost.compute_cost(
                hours=Decimal("186"),
                rate_amount=Decimal("64000"),
                rate_period=EquipmentRatePeriod.monthly,
                monthly_capacity_hours=None,
            )
            is None
        )

    def test_monthly_iken_kapasite_sifirsa_none(self) -> None:
        """Sıfıra bölme 0 maliyet basmaz — "bedava çalıştı" bir yalandır."""
        assert (
            cost.compute_cost(
                hours=Decimal("186"),
                rate_amount=Decimal("64000"),
                rate_period=EquipmentRatePeriod.monthly,
                monthly_capacity_hours=0,
            )
            is None
        )

    def test_sifir_saat_maliyeti_sifirdir_none_degil(self) -> None:
        """🔴 AYRIM: bedeli BİLİNEN bir makinenin 0 saati GERÇEK bir 0'dır
        (M3 Forklift satırı: 0 saat → ₺0). Fail-closed yalnız BİLİNMEYEN
        için `None` döner; bilinen sıfırı `None`a çevirmek de bir yalandır."""
        assert cost.compute_cost(
            hours=Decimal("0"),
            rate_amount=Decimal("3200"),
            rate_period=EquipmentRatePeriod.daily,
        ) == Decimal("0")


class TestYakitTutariYuvarlamasi:
    """K19 — `amount` kolon DEĞİLDİR, `liters × unit_price`ten türer."""

    @pytest.mark.parametrize(
        ("litre", "birim_fiyat", "beklenen"),
        MOCKUP_YAKIT_SATIRLARI,
        ids=[str(satir[0]) for satir in MOCKUP_YAKIT_SATIRLARI],
    )
    def test_m4_dort_satir(self, litre: Decimal, birim_fiyat: Decimal, beklenen: Decimal) -> None:
        assert cost.fuel_amount(liters=litre, unit_price=birim_fiyat) == beklenen

    def test_yarim_yukari_yuvarlanir_bankaci_yuvarlamasi_degil(self) -> None:
        """Python `Decimal` varsayılanı `ROUND_HALF_EVEN`dir ve 1.786,5'i
        1.786'ya indirirdi — M4:1.787 ile çelişir, her ay sistematik kayıp."""
        assert cost.quantize_money(Decimal("1786.5")) == Decimal("1787")
        assert cost.quantize_money(Decimal("2.5")) == Decimal("3")
        assert cost.quantize_money(Decimal("3.5")) == Decimal("4")


class TestParaTipi:
    """K19 — `float` YASAK: her çıktı `Decimal`dir."""

    def test_ciktilar_decimaldir(self) -> None:
        maliyet = cost.compute_cost(
            hours=Decimal("186"),
            rate_amount=Decimal("3200"),
            rate_period=EquipmentRatePeriod.daily,
        )
        assert type(maliyet) is Decimal
        assert type(cost.fuel_amount(liters=Decimal("45"), unit_price=Decimal("39.70"))) is Decimal
        assert (
            type(
                cost.hourly_rate(rate_amount=Decimal("3200"), rate_period=EquipmentRatePeriod.daily)
            )
            is Decimal
        )

    def test_daily_hours_float_degildir(self) -> None:
        assert type(cost.DAILY_HOURS) is Decimal
