"""MK-1 T2 — yakıt tüketimi / kullanım ÇEKİRDEĞİ (`consumption.py`).

Spec: `docs/superpowers/specs/2026-08-13-mk1-makine-cekirdegi-design.md`
(K7 · K16 · K17 · K19). DB YOKTUR.

🔴 Bu dosyanın ASIL işi **dört fail-closed `None` yolunu** kilitlemektir: her
biri ayrı testle ve MAKİNE-OKUNUR bir gerekçeyle. Uydurma bir 0 ya da uydurma
bir "normal" rozeti, eksik veriyi "sorun yok" gibi gösterirdi.
"""

from decimal import Decimal

import pytest

from app.modules.equipment import consumption
from app.modules.equipment.models import EquipmentNormUnit

# 🔴 K7 mockup doğrulaması — M3 kullanım yüzdesi sütunu, payda 200 (BEŞ satır).
MOCKUP_KULLANIM = (
    ("Tower Crane TC-48", Decimal("186"), 200, Decimal("93.0")),
    ("Ekskavatör CAT 320", Decimal("152"), 200, Decimal("76.0")),
    ("Beton Pompası BP-36", Decimal("42"), 200, Decimal("21.0")),
    ("Damperli Kamyon", Decimal("168"), 200, Decimal("84.0")),
    ("Kompresör SC-200", Decimal("144"), 200, Decimal("72.0")),
)

# M4 "Ekipman Bazlı Tüketim" bloğu — litre / saat → fiili tüketim ve norm.
# (Damperli Kamyon KASTEN yok: `lt_km`dir, aşağıda fail-closed testinde.)
MOCKUP_TUKETIM = (
    ("Tower Crane TC-48", Decimal("840"), Decimal("186"), Decimal("4.5")),
    ("Ekskavatör CAT 320", Decimal("1140"), Decimal("152"), Decimal("7.5")),
    ("Kompresör SC-200", Decimal("240"), Decimal("144"), Decimal("1.7")),
)


class TestKullanimYuzdesiMockupDogrulamasi:
    """K7 — payda VERİDİR (`monthly_capacity_hours`), koda gömülü değil."""

    @pytest.mark.parametrize(
        ("ad", "saat", "kapasite", "beklenen"),
        MOCKUP_KULLANIM,
        ids=[satir[0] for satir in MOCKUP_KULLANIM],
    )
    def test_m3_bes_rozet(self, ad: str, saat: Decimal, kapasite: int, beklenen: Decimal) -> None:
        sonuc = consumption.compute_usage(hours=saat, monthly_capacity_hours=kapasite)
        assert sonuc.usage_pct == beklenen
        assert sonuc.usage_reason is None

    def test_kapasite_ekipman_basina_degisir(self) -> None:
        """Vinç ile el aleti aynı kapasitede değildir: 186 saat, 300 kapasite."""
        assert consumption.compute_usage(
            hours=Decimal("186"), monthly_capacity_hours=300
        ).usage_pct == Decimal("62.0")


class TestFiiliTuketimMockupDogrulamasi:
    @pytest.mark.parametrize(
        ("ad", "litre", "saat", "beklenen"),
        MOCKUP_TUKETIM,
        ids=[satir[0] for satir in MOCKUP_TUKETIM],
    )
    def test_m4_litre_bolu_saat(
        self, ad: str, litre: Decimal, saat: Decimal, beklenen: Decimal
    ) -> None:
        assert consumption.actual_consumption(total_liters=litre, total_hours=saat) == beklenen

    def test_filo_ortalamasi_m4_kpi(self) -> None:
        """M4:39 `Lt/Saat Ortalama` = 2.840 / 428 = 6,6 — aynı formül, filo
        düzeyinde. (Toplamların KENDİSİ satırlardan türer — K15, T5'in işi.)"""
        assert consumption.actual_consumption(
            total_liters=Decimal("2840"), total_hours=Decimal("428")
        ) == Decimal("6.6")


class TestSapmaEsikleri:
    """K17 — eşikler TEK YERDE: `dev ≤ 0` normal · `0 < dev < 10` warning ·
    `dev ≥ 10` critical. Sınırların dördü de kilitli."""

    @pytest.mark.parametrize(
        ("sapma", "beklenen"),
        (
            (Decimal("-30.0"), consumption.ConsumptionStatus.normal),
            (Decimal("0"), consumption.ConsumptionStatus.normal),  # SINIR: 0 normaldir
            (Decimal("0.1"), consumption.ConsumptionStatus.warning),  # SINIR: 0+ε
            (Decimal("9.9"), consumption.ConsumptionStatus.warning),  # SINIR: 10−ε
            (Decimal("10.0"), consumption.ConsumptionStatus.critical),  # SINIR: 10 kritiktir
            (Decimal("120.0"), consumption.ConsumptionStatus.critical),
        ),
    )
    def test_sinirlar(self, sapma: Decimal, beklenen: consumption.ConsumptionStatus) -> None:
        assert consumption.consumption_status(sapma) is beklenen

    def test_sapma_none_ise_rozet_de_none(self) -> None:
        """🔴 KARAR: spec rozetin `None` sapmadaki değerini YAZMIYOR. "normal"
        basmak, hesaplanamayan tüketimi "sorun yok" diye damgalamak olurdu —
        fail-closed ruhu gereği rozet de `None` kalır."""
        assert consumption.consumption_status(None) is None

    def test_m4_iki_uyari_rozeti(self) -> None:
        """M4: 4,5 vs norm 4,2 → sarı · 3,7 vs norm 3,2 → kırmızı."""
        sari = consumption.deviation_pct(actual=Decimal("4.5"), norm=Decimal("4.2"))
        assert sari == Decimal("7.1")
        assert consumption.consumption_status(sari) is consumption.ConsumptionStatus.warning

        kirmizi = consumption.deviation_pct(actual=Decimal("3.7"), norm=Decimal("3.2"))
        assert kirmizi == Decimal("15.6")
        assert consumption.consumption_status(kirmizi) is consumption.ConsumptionStatus.critical

    def test_normun_altinda_kalan_tuketim_normaldir(self) -> None:
        """M4: 7,5 vs 7,8 ve 1,7 vs 1,8 — ikisi de ✓ Normal."""
        for fiili, norm in ((Decimal("7.5"), Decimal("7.8")), (Decimal("1.7"), Decimal("1.8"))):
            sapma = consumption.deviation_pct(actual=fiili, norm=norm)
            assert sapma < 0
            assert consumption.consumption_status(sapma) is consumption.ConsumptionStatus.normal


class TestDortFailClosedYol:
    """🔴 K16 — DÖRT `None` yolu, her biri makine-okunur bir gerekçeyle."""

    def test_1_lt_km_normunda_sapma_hesaplanmaz(self) -> None:
        """Kilometre/odometre verisi HİÇBİR ekranda girilmiyor. Saatten
        uydurma bir Lt/km üretmek yanlış bir "anormal tüketim" alarmı doğururdu
        (M4 Damperli Kamyon satırı)."""
        sonuc = consumption.evaluate_consumption(
            total_liters=Decimal("620"),
            total_hours=Decimal("168"),
            norm_consumption=Decimal("3.2"),
            norm_unit=EquipmentNormUnit.lt_km,
        )
        assert sonuc.deviation_pct is None
        assert sonuc.deviation_reason == consumption.REASON_NO_DISTANCE_DATA
        assert sonuc.deviation_reason == "no_distance_data"
        assert sonuc.status is None

    def test_2_norm_yoksa_sapma_none(self) -> None:
        sonuc = consumption.evaluate_consumption(
            total_liters=Decimal("840"),
            total_hours=Decimal("186"),
            norm_consumption=None,
            norm_unit=EquipmentNormUnit.lt_hour,
        )
        assert sonuc.actual == Decimal("4.5")  # fiili tüketim BİLİNİYOR
        assert sonuc.deviation_pct is None
        assert sonuc.deviation_reason == consumption.REASON_NO_NORM
        assert sonuc.status is None

    def test_2b_sifir_norm_da_olcut_yoklugudur(self) -> None:
        """Sıfır norm bir ölçüt DEĞİLDİR: sapma sonsuza giderdi. Sapmasız her
        `None` bir GEREKÇE taşır — gerekçesiz `None` ekranda "hesaplanamadı"
        derken niçinini söyleyemezdi."""
        for gecersiz_norm in (Decimal("0"), Decimal("-1")):
            sonuc = consumption.evaluate_consumption(
                total_liters=Decimal("840"),
                total_hours=Decimal("186"),
                norm_consumption=gecersiz_norm,
                norm_unit=EquipmentNormUnit.lt_hour,
            )
            assert sonuc.deviation_pct is None
            assert sonuc.deviation_reason == consumption.REASON_NO_NORM

    def test_3_calisma_saati_sifirsa_fiili_tuketim_none(self) -> None:
        """Sıfıra bölmede 0 basmak "hiç yakmadı" derdi — oysa yakıt alınmış,
        çalışma kaydı girilmemiştir."""
        sonuc = consumption.evaluate_consumption(
            total_liters=Decimal("840"),
            total_hours=Decimal("0"),
            norm_consumption=Decimal("4.2"),
            norm_unit=EquipmentNormUnit.lt_hour,
        )
        assert sonuc.actual is None
        assert sonuc.deviation_pct is None
        assert sonuc.deviation_reason == consumption.REASON_NO_WORK_HOURS
        assert sonuc.status is None

    def test_4_kapasite_sifirsa_kullanim_yuzdesi_none(self) -> None:
        sonuc = consumption.compute_usage(hours=Decimal("186"), monthly_capacity_hours=0)
        assert sonuc.usage_pct is None
        assert sonuc.usage_reason == consumption.REASON_NO_CAPACITY_HOURS

    def test_gerekceler_farklidir(self) -> None:
        """Dört gerekçe AYRI olmalı: tek bir "hesaplanamadı" dizgesi, hangi
        verinin eksik olduğunu ekranda kaybederdi."""
        gerekceler = {
            consumption.REASON_NO_DISTANCE_DATA,
            consumption.REASON_NO_NORM,
            consumption.REASON_NO_WORK_HOURS,
            consumption.REASON_NO_CAPACITY_HOURS,
        }
        assert len(gerekceler) == 4

    def test_hicbir_yerde_uydurma_sifir_basilmaz(self) -> None:
        """Tüm veri eksikken hiçbir alan 0 DEĞİL `None` döner."""
        sonuc = consumption.evaluate_consumption(
            total_liters=Decimal("0"),
            total_hours=Decimal("0"),
            norm_consumption=None,
            norm_unit=None,
        )
        assert (sonuc.actual, sonuc.deviation_pct, sonuc.status) == (None, None, None)
        assert sonuc.deviation_reason is not None


class TestBasariliYol:
    def test_gerekce_yalniz_hesaplanamayan_durumda_dolar(self) -> None:
        sonuc = consumption.evaluate_consumption(
            total_liters=Decimal("840"),
            total_hours=Decimal("186"),
            norm_consumption=Decimal("4.2"),
            norm_unit=EquipmentNormUnit.lt_hour,
        )
        assert sonuc.actual == Decimal("4.5")
        assert sonuc.deviation_pct == Decimal("7.1")
        assert sonuc.deviation_reason is None
        assert sonuc.status is consumption.ConsumptionStatus.warning


class TestOranTipi:
    """K19 — oranlar bir ondalıklı `Decimal`dir, `float` DEĞİL."""

    def test_ciktilar_decimaldir(self) -> None:
        assert (
            type(
                consumption.actual_consumption(
                    total_liters=Decimal("840"), total_hours=Decimal("186")
                )
            )
            is Decimal
        )
        assert (
            type(consumption.deviation_pct(actual=Decimal("4.5"), norm=Decimal("4.2"))) is Decimal
        )
        assert (
            type(
                consumption.compute_usage(
                    hours=Decimal("186"), monthly_capacity_hours=200
                ).usage_pct
            )
            is Decimal
        )

    def test_bir_ondalik(self) -> None:
        assert (
            str(
                consumption.actual_consumption(
                    total_liters=Decimal("840"), total_hours=Decimal("186")
                )
            )
            == "4.5"
        )
        assert (
            str(
                consumption.compute_usage(
                    hours=Decimal("186"), monthly_capacity_hours=200
                ).usage_pct
            )
            == "93.0"
        )
