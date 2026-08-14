"""MK-2 T2 — kira hakedişi PARA çekirdeği (`rental.py`) saf fonksiyonları.

Spec: `docs/superpowers/specs/2026-08-14-mk2-kira-hakedisi-design.md`
(K1 · K3 · K4 · K6 · K10). DB YOKTUR: `cost.py` / `payroll/compute.py` emsali —
türev TEK KAYNAKTAN, router'dan bağımsız sınanır.

🔴 **§0 — mockup RAKAMLARI göstermeliktir.** M5'in ₺122.496 / ₺146.995 sayıları
iş kuralı kanıtı DEĞİLDİR ve burada BEKLENTİ olarak kullanılmaz. Kural mockup'ın
YAPISINDAN (sütun/etiket/durum) okunur. Yalnız MK-1'in dört ekipmanda birden
doğrulanmış `DAILY_HOURS = 10` sabiti geçerliliğini korur ve satır maliyetleri
(₺59.520 · ₺42.560 · ₺23.520) o sabitle yeniden ÜRETİLİR — kopyalanmaz.
"""

import uuid
from decimal import Decimal

import pytest

from app.modules.equipment import rental
from app.modules.equipment.models import EquipmentRatePeriod, RentalLineKind

# M5 tablosunun DÖRT satırı — YAPISI (tür · şantiye · saat sütunları) kanıttır.
GUNESKENT = uuid.uuid4()
LIMAN = uuid.uuid4()
CELIK_OSB = uuid.uuid4()

VINC = uuid.uuid4()
EKSKAVATOR = uuid.uuid4()
KAMYON = uuid.uuid4()


def _line(
    *,
    line_kind: RentalLineKind = RentalLineKind.rented,
    worked_hours: str = "0",
    breakdown_hours: str = "0",
    line_rate_amount: str | None = None,
    equipment_rate_amount: str | None = None,
    invoiced_hours: str | None = None,
    site_id: uuid.UUID | None = None,
    equipment_id: uuid.UUID | None = None,
    monthly_capacity_hours: int | None = None,
) -> rental.RentalLineInput:
    return rental.RentalLineInput(
        line_id=uuid.uuid4(),
        equipment_id=equipment_id or uuid.uuid4(),
        site_id=site_id,
        line_kind=line_kind,
        worked_hours=Decimal(worked_hours),
        breakdown_hours=Decimal(breakdown_hours),
        line_rate_amount=None if line_rate_amount is None else Decimal(line_rate_amount),
        equipment_rate_amount=(
            None if equipment_rate_amount is None else Decimal(equipment_rate_amount)
        ),
        invoiced_hours=None if invoiced_hours is None else Decimal(invoiced_hours),
        monthly_capacity_hours=monthly_capacity_hours,
    )


#: M5'in dört satırı — mockup'ın YAPISI. Kira B.F.'leri M1 kartlarının GÜNLÜK
#: bedelleridir (MK-1 `DAILY_HOURS = 10` zinciriyle saatliğe dönüşür).
def _m5_lines() -> tuple[rental.RentalLineInput, ...]:
    return (
        _line(  # M5:99-110 — Tower Crane, kiralık, 186 saat, B.F. 320/saat
            line_kind=RentalLineKind.rented,
            worked_hours="186",
            line_rate_amount="320",
            invoiced_hours="186",
            site_id=GUNESKENT,
            equipment_id=VINC,
        ),
        _line(  # M5:111-122 — Ekskavatör, kiralık, 152 saat, fatura 158 saat
            line_kind=RentalLineKind.rented,
            worked_hours="152",
            line_rate_amount="280",
            invoiced_hours="158",
            site_id=LIMAN,
            equipment_id=EKSKAVATOR,
        ),
        _line(  # M5:128-139 — arıza satırı: 38 saat, üstü çizili tutar
            line_kind=RentalLineKind.breakdown,
            worked_hours="0",
            breakdown_hours="38",
            line_rate_amount="320",
            site_id=GUNESKENT,
            equipment_id=VINC,
        ),
        _line(  # M5:140-151 — "Kendi" araç: tfoot'a KATILMAZ
            line_kind=RentalLineKind.owned,
            worked_hours="168",
            line_rate_amount="140",
            site_id=CELIK_OSB,
            equipment_id=KAMYON,
        ),
    )


# --------------------------------------------------------------------------- #
# K4 — saatlik bedelin KAYNAĞI ve fail-closed
# --------------------------------------------------------------------------- #


class TestEffectiveRate:
    def test_satirin_bedeli_ekipmaninkini_ezer(self) -> None:
        """M5:93 kira B.F. sütunu DÜZENLENEBİLİR bir input'tur: kullanıcının
        girdiği bedel ekipman kartındakinden önce gelir."""
        assert rental.effective_rate_amount(
            line_rate_amount=Decimal("320"), equipment_rate_amount=Decimal("999")
        ) == Decimal("320")

    def test_satir_bossa_ekipmanin_bedeline_dusulur(self) -> None:
        assert rental.effective_rate_amount(
            line_rate_amount=None, equipment_rate_amount=Decimal("280")
        ) == Decimal("280")

    def test_ikisi_de_yoksa_none(self) -> None:
        """🔴 MK-1 K16 fail-closed — 0 DEĞİL. 0 "bedava çalıştı" derdi."""
        assert (
            rental.effective_rate_amount(line_rate_amount=None, equipment_rate_amount=None) is None
        )

    def test_satirin_sifir_bedeli_gercek_bir_sifirdir(self) -> None:
        """Bilinen 0 bedel (bedelsiz tahsis) `None`a çevrilmez — `cost.py`nin
        "bilinen sıfırı yalana çevirme" ilkesi."""
        assert rental.effective_rate_amount(
            line_rate_amount=Decimal("0"), equipment_rate_amount=Decimal("320")
        ) == Decimal("0")


class TestOurAmount:
    @pytest.mark.parametrize(
        ("saat", "gunluk_bedel", "beklenen"),
        (
            (Decimal("186"), Decimal("3200"), Decimal("59520")),
            (Decimal("152"), Decimal("2800"), Decimal("42560")),
            (Decimal("168"), Decimal("1400"), Decimal("23520")),
        ),
    )
    def test_gunluk_donem_mk1_zincirinden_gecer(
        self, saat: Decimal, gunluk_bedel: Decimal, beklenen: Decimal
    ) -> None:
        """🔴 `DAILY_HOURS = 10` MK-2'de YENİDEN TANIMLANMAZ: dönüşüm
        `cost.py`den ithal edilir. Sabit orada değişirse bu test kırmızıya
        döner — iki modülde iki gün tanımı doğamaz."""
        assert (
            rental.compute_our_amount(
                worked_hours=saat,
                line_rate_amount=gunluk_bedel,
                equipment_rate_amount=None,
                rate_period=EquipmentRatePeriod.daily,
            )
            == beklenen
        )

    def test_saatlik_donem_dogrudan_carpar(self) -> None:
        assert rental.compute_our_amount(
            worked_hours=Decimal("186"),
            line_rate_amount=Decimal("320"),
            equipment_rate_amount=None,
            rate_period=EquipmentRatePeriod.hourly,
        ) == Decimal("59520")

    def test_aylik_donemde_payda_kapasitedir(self) -> None:
        """K7: payda VERİDİR (`monthly_capacity_hours`), koda gömülü sabit değil."""
        assert rental.compute_our_amount(
            worked_hours=Decimal("100"),
            line_rate_amount=Decimal("64000"),
            equipment_rate_amount=None,
            rate_period=EquipmentRatePeriod.monthly,
            monthly_capacity_hours=200,
        ) == Decimal("32000")

    def test_bedelsiz_satir_none_dondurur(self) -> None:
        """🔴 Fail-closed: satırda da ekipmanda da bedel yoksa maliyet `None`."""
        assert (
            rental.compute_our_amount(
                worked_hours=Decimal("186"),
                line_rate_amount=None,
                equipment_rate_amount=None,
                rate_period=EquipmentRatePeriod.daily,
            )
            is None
        )

    def test_aylik_donemde_kapasitesiz_satir_none_dondurur(self) -> None:
        assert (
            rental.compute_our_amount(
                worked_hours=Decimal("100"),
                line_rate_amount=Decimal("64000"),
                equipment_rate_amount=None,
                rate_period=EquipmentRatePeriod.monthly,
                monthly_capacity_hours=None,
            )
            is None
        )

    def test_bilinen_bedelde_sifir_saat_gercek_sifirdir(self) -> None:
        assert rental.compute_our_amount(
            worked_hours=Decimal("0"),
            line_rate_amount=Decimal("320"),
            equipment_rate_amount=None,
            rate_period=EquipmentRatePeriod.hourly,
        ) == Decimal("0")

    def test_para_tam_sayiya_round_half_up_yuvarlanir(self) -> None:
        """K10 — Python'un varsayılanı `ROUND_HALF_EVEN` olsaydı 100 → 100 yerine
        `cost.quantize_money` yukarı yuvarlar (M4 ₺1.787 dersi)."""
        assert rental.compute_our_amount(
            worked_hours=Decimal("1"),
            line_rate_amount=Decimal("100.5"),
            equipment_rate_amount=None,
            rate_period=EquipmentRatePeriod.hourly,
        ) == Decimal("101")


# --------------------------------------------------------------------------- #
# K1 — KDV zinciri
# --------------------------------------------------------------------------- #


class TestVatChain:
    def test_kdv_orani_KOLONDAN_okunur_iki_farkli_oranli_fatura(self) -> None:
        """🔴 K1 — oran VERİDİR, koda gömülü sabit DEĞİL (İK-3 `payroll_rates`
        dersi). Aynı matrah, İKİ farklı `vat_rate` → İKİ farklı KDV. Oran koda
        gömülü olsaydı bu iki iddiadan biri kaçınılmaz olarak kırılırdı."""
        matrah = Decimal("102080.00")
        assert rental.compute_vat_amount(invoice_amount=matrah, vat_rate=Decimal("20.00")) == (
            Decimal("20416")
        )
        assert rental.compute_vat_amount(invoice_amount=matrah, vat_rate=Decimal("8.00")) == (
            Decimal("8166")
        )

    def test_sifir_oran_gercek_sifirdir(self) -> None:
        """İstisna kapsamındaki fatura: %0 bilinen bir orandır, eksik veri değil."""
        assert rental.compute_vat_amount(
            invoice_amount=Decimal("1000"), vat_rate=Decimal("0")
        ) == Decimal("0")

    def test_matrah_yoksa_kdv_none(self) -> None:
        """🔴 Fail-closed: `invoice_amount` NULL (taslak) iken KDV 0 basmak
        "vergi yok" derdi."""
        assert rental.compute_vat_amount(invoice_amount=None, vat_rate=Decimal("20")) is None

    def test_payable_total_matrah_arti_kdv(self) -> None:
        """K1 — `payable_total = invoice_amount + vat_amount`, ikinci bir
        yuvarlama YOK: `payable − vat == matrah` kuruşuna kadar korunur
        (İK-3'ün "net FARKTIR" dersi)."""
        matrah = Decimal("90000.50")
        kdv = rental.compute_vat_amount(invoice_amount=matrah, vat_rate=Decimal("20.00"))
        toplam = rental.compute_payable_total(invoice_amount=matrah, vat_amount=kdv)
        # 18.000,10 → tam sayıya (K10); matrahın kuruşu toplamda KORUNUR.
        assert kdv == Decimal("18000")
        assert toplam == Decimal("108000.50")
        assert toplam - kdv == matrah

    def test_matrah_yoksa_payable_total_none(self) -> None:
        assert rental.compute_payable_total(invoice_amount=None, vat_amount=None) is None


# --------------------------------------------------------------------------- #
# K6 — fark ve rozet (sunucu damgası)
# --------------------------------------------------------------------------- #


class TestVariance:
    def test_esitlik_match(self) -> None:
        sonuc = rental.compute_line(
            _line(worked_hours="186", invoiced_hours="186", line_rate_amount="320"),
            rate_period=EquipmentRatePeriod.hourly,
        )
        assert sonuc.hours_variance == Decimal("0")
        assert sonuc.variance_status is rental.VarianceStatus.match

    def test_firma_fazla_fatura_ederse_over(self) -> None:
        """M5:122 — 152 çalışma, 158 fatura → firma LEHİNE fark."""
        sonuc = rental.compute_line(
            _line(worked_hours="152", invoiced_hours="158", line_rate_amount="280"),
            rate_period=EquipmentRatePeriod.hourly,
        )
        assert sonuc.hours_variance == Decimal("6")
        assert sonuc.variance_status is rental.VarianceStatus.over

    def test_firma_eksik_fatura_ederse_under(self) -> None:
        sonuc = rental.compute_line(
            _line(worked_hours="152", invoiced_hours="140", line_rate_amount="280"),
            rate_period=EquipmentRatePeriod.hourly,
        )
        assert sonuc.hours_variance == Decimal("-12")
        assert sonuc.variance_status is rental.VarianceStatus.under

    def test_fatura_saati_girilmemisse_unknown(self) -> None:
        """🔴 Fail-closed rozet: fark 0 basmak "eşleşiyor" damgası vurmak olurdu
        (F-P10 "rozet sunucu damgasıdır" kanonu)."""
        sonuc = rental.compute_line(
            _line(worked_hours="152", invoiced_hours=None, line_rate_amount="280"),
            rate_period=EquipmentRatePeriod.hourly,
        )
        assert sonuc.hours_variance is None
        assert sonuc.variance_status is rental.VarianceStatus.unknown

    def test_fark_odemeyi_bloke_etmez(self) -> None:
        """K6 — fark yalnız GÖRÜNÜR kılınır; toplamı hiçbir şekilde kısmaz."""
        toplamlar = rental.compute_invoice(
            invoice_amount=Decimal("100000.00"),
            vat_rate=Decimal("20.00"),
            rate_period=EquipmentRatePeriod.hourly,
            lines=(_line(worked_hours="152", invoiced_hours="158", line_rate_amount="280"),),
        )
        assert toplamlar.lines[0].variance_status is rental.VarianceStatus.over
        assert toplamlar.our_total == Decimal("42560")
        assert toplamlar.payable_total == Decimal("120000.00")


# --------------------------------------------------------------------------- #
# K3 — çift ödeme YAPISAL olarak imkânsız
# --------------------------------------------------------------------------- #


class TestLineKindTotals:
    def test_our_total_yalniz_rented_satirlardan_turer(self) -> None:
        """🔴 K3 — `owned` ve `breakdown` hiçbir ödenecek toplamın KAYNAĞI
        değildir (İK-3 K2 `excluded` deseni)."""
        toplamlar = rental.compute_invoice(
            invoice_amount=None,
            vat_rate=Decimal("20.00"),
            rate_period=EquipmentRatePeriod.hourly,
            lines=_m5_lines(),
        )
        assert toplamlar.our_total == Decimal("59520") + Decimal("42560")
        assert toplamlar.owned_total == Decimal("23520")
        assert toplamlar.excluded_breakdown_amount == Decimal("38") * Decimal("320")

    def test_owned_satiri_our_totala_hic_dokunmaz(self) -> None:
        """Aynı toplam, `owned` satır EKLENMEDEN de EKLENEREK de aynıdır."""
        rented = _line(worked_hours="186", line_rate_amount="320")
        owned = _line(line_kind=RentalLineKind.owned, worked_hours="168", line_rate_amount="140")
        yalniz = rental.compute_invoice(
            invoice_amount=None,
            vat_rate=Decimal("20.00"),
            rate_period=EquipmentRatePeriod.hourly,
            lines=(rented,),
        )
        birlikte = rental.compute_invoice(
            invoice_amount=None,
            vat_rate=Decimal("20.00"),
            rate_period=EquipmentRatePeriod.hourly,
            lines=(rented, owned),
        )
        assert yalniz.our_total == birlikte.our_total == Decimal("59520")

    def test_breakdown_satiri_our_totala_hic_dokunmaz(self) -> None:
        rented = _line(worked_hours="186", line_rate_amount="320")
        ariza = _line(
            line_kind=RentalLineKind.breakdown,
            worked_hours="0",
            breakdown_hours="38",
            line_rate_amount="320",
        )
        yalniz = rental.compute_invoice(
            invoice_amount=None,
            vat_rate=Decimal("20.00"),
            rate_period=EquipmentRatePeriod.hourly,
            lines=(rented,),
        )
        birlikte = rental.compute_invoice(
            invoice_amount=None,
            vat_rate=Decimal("20.00"),
            rate_period=EquipmentRatePeriod.hourly,
            lines=(rented, ariza),
        )
        assert yalniz.our_total == birlikte.our_total == Decimal("59520")
        assert birlikte.excluded_breakdown_amount == Decimal("12160")

    def test_ariza_tutari_ARIZA_saatinden_turer(self) -> None:
        """M5:128-139 arıza satırında çalışma sütunu "—", arıza sütunu 38'dir ve
        üstü çizili tutar o 38 saatin karşılığıdır. `worked_hours`tan türetilseydi
        hariç tutulan tutar sessizce 0 görünürdü."""
        toplamlar = rental.compute_invoice(
            invoice_amount=None,
            vat_rate=Decimal("20.00"),
            rate_period=EquipmentRatePeriod.daily,
            lines=(
                _line(
                    line_kind=RentalLineKind.breakdown,
                    worked_hours="0",
                    breakdown_hours="38",
                    line_rate_amount="3200",
                ),
            ),
        )
        assert toplamlar.excluded_breakdown_amount == Decimal("12160")
        assert toplamlar.our_total == Decimal("0")


class TestUnknownCounts:
    def test_bedelsiz_rented_satir_toplama_UYDURMA_0_ile_girmez(self) -> None:
        """MK-1 `summarize` kanonu: hesaplanamayan satır ATLANIR ama SESSİZ
        kalmaz — adetçe bildirilir, yoksa kullanıcı eksik parayı tam sanırdı."""
        toplamlar = rental.compute_invoice(
            invoice_amount=None,
            vat_rate=Decimal("20.00"),
            rate_period=EquipmentRatePeriod.hourly,
            lines=(
                _line(worked_hours="186", line_rate_amount="320"),
                _line(worked_hours="152"),  # bedelsiz → `None`
            ),
        )
        assert toplamlar.our_total == Decimal("59520")
        assert toplamlar.our_total_unknown_count == 1
        assert toplamlar.owned_total_unknown_count == 0

    def test_bedelsiz_owned_ve_breakdown_kendi_sayaclarina_yazilir(self) -> None:
        toplamlar = rental.compute_invoice(
            invoice_amount=None,
            vat_rate=Decimal("20.00"),
            rate_period=EquipmentRatePeriod.hourly,
            lines=(
                _line(line_kind=RentalLineKind.owned, worked_hours="168"),
                _line(line_kind=RentalLineKind.breakdown, worked_hours="0", breakdown_hours="38"),
            ),
        )
        assert toplamlar.our_total_unknown_count == 0
        assert toplamlar.owned_total_unknown_count == 1
        assert toplamlar.excluded_breakdown_unknown_count == 1


# --------------------------------------------------------------------------- #
# Proje bazlı dağılım (M5:177-193)
# --------------------------------------------------------------------------- #


class TestSiteDistribution:
    def test_dagilim_satirin_SITE_IDsinden_ve_yalniz_rentedtan_turer(self) -> None:
        """M5:177-193 iki kova basar (Güneşkent · Liman) — "Kendi" araç
        (Çelik OSB) ve arıza satırı dağılımda YOKTUR."""
        toplamlar = rental.compute_invoice(
            invoice_amount=None,
            vat_rate=Decimal("20.00"),
            rate_period=EquipmentRatePeriod.hourly,
            lines=_m5_lines(),
        )
        assert [(k.site_id, k.amount, k.hours) for k in toplamlar.site_distribution] == [
            (GUNESKENT, Decimal("59520"), Decimal("186")),
            (LIMAN, Decimal("42560"), Decimal("152")),
        ]
        assert toplamlar.site_distribution[0].equipment_ids == (VINC,)

    def test_ayni_santiyedeki_iki_makine_TEK_kovada_toplanir(self) -> None:
        toplamlar = rental.compute_invoice(
            invoice_amount=None,
            vat_rate=Decimal("20.00"),
            rate_period=EquipmentRatePeriod.hourly,
            lines=(
                _line(
                    worked_hours="186", line_rate_amount="320", site_id=GUNESKENT, equipment_id=VINC
                ),
                _line(
                    worked_hours="152",
                    line_rate_amount="280",
                    site_id=GUNESKENT,
                    equipment_id=EKSKAVATOR,
                ),
            ),
        )
        (kova,) = toplamlar.site_distribution
        assert kova.amount == Decimal("102080")
        assert kova.hours == Decimal("338")
        assert kova.equipment_ids == (VINC, EKSKAVATOR)

    def test_santiyesiz_satir_ATANMAMIS_kovasina_duser_ve_SONDA_durur(self) -> None:
        """`site_id IS NULL` için UYDURMA proje adı BASILMAZ; kova `None`
        anahtarlıdır ve listenin SONUNDA durur (adlı projeler önce)."""
        toplamlar = rental.compute_invoice(
            invoice_amount=None,
            vat_rate=Decimal("20.00"),
            rate_period=EquipmentRatePeriod.hourly,
            lines=(
                _line(worked_hours="10", line_rate_amount="320", site_id=None),
                _line(worked_hours="10", line_rate_amount="280", site_id=LIMAN),
            ),
        )
        assert [k.site_id for k in toplamlar.site_distribution] == [LIMAN, None]

    def test_hesaplanamayan_satir_kovada_ADETCE_bildirilir(self) -> None:
        toplamlar = rental.compute_invoice(
            invoice_amount=None,
            vat_rate=Decimal("20.00"),
            rate_period=EquipmentRatePeriod.hourly,
            lines=(
                _line(worked_hours="186", line_rate_amount="320", site_id=GUNESKENT),
                _line(worked_hours="50", site_id=GUNESKENT),
            ),
        )
        (kova,) = toplamlar.site_distribution
        assert kova.amount == Decimal("59520")
        assert kova.unknown_count == 1
        # Saat BİLİNEN bir olgudur: bedeli bilinmese de saat kaybolmaz.
        assert kova.hours == Decimal("236")


# --------------------------------------------------------------------------- #
# K10 — `Decimal`, asla `float`
# --------------------------------------------------------------------------- #


class TestNoFloat:
    def test_tum_para_ciktilari_decimaldir(self) -> None:
        toplamlar = rental.compute_invoice(
            invoice_amount=Decimal("122496.00"),
            vat_rate=Decimal("20.00"),
            rate_period=EquipmentRatePeriod.daily,
            lines=_m5_lines(),
        )
        para_alanlari = (
            toplamlar.our_total,
            toplamlar.owned_total,
            toplamlar.excluded_breakdown_amount,
            toplamlar.invoice_amount,
            toplamlar.vat_amount,
            toplamlar.payable_total,
            *(k.amount for k in toplamlar.site_distribution),
            *(k.hours for k in toplamlar.site_distribution),
        )
        for deger in para_alanlari:
            assert type(deger) is Decimal, deger

        for satir in toplamlar.lines:
            assert satir.our_amount is None or type(satir.our_amount) is Decimal
            assert satir.breakdown_amount is None or type(satir.breakdown_amount) is Decimal
            assert satir.hours_variance is None or type(satir.hours_variance) is Decimal

    def test_kaynak_dosyada_float_YOKTUR(self) -> None:
        """`float(...)` ya da `0.5` gibi bir literal, kuruşu sessizce kaydıran
        ikili kayan nokta aritmetiğini para zincirine sokardı."""
        import inspect

        kaynak = inspect.getsource(rental)
        assert "float(" not in kaynak
