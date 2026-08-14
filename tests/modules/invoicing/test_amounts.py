"""FAT-1 T2 — para çekirdeği (`invoicing/amounts.py`, spec §5 · K3-K5).

Bu dosya faturanın TEK para kaynağını kilitler. Uçlar (T3/T4) kendi toplamını
hesaplamayacağı için burada kanıtlanan davranış, mali tablonun tamamının
sözleşmesidir.

Kanıtlanan dört şey:

1. **Adım sırası** (§5'in yedi adımı) — kesinti matrahı `subtotal`, KDV matrahı
   `tax_base`, tevkifat matrahı `vat_amount`tır. Sıra bozulursa aynı fatura
   farklı para üretir.
2. **K3(a)** — TEK KDV oranlı faturada sonuç, mockup tfoot'unun yazdığı
   "subtotal → tax_base → × oran" formülüyle **birebir** aynıdır. Bu, naif bir
   satır-bazlı yuvarlamanın (her satırın KDV'sini ayrı yuvarlayıp toplamanın)
   YAKALANMADIĞI yerdir: 3 × 0,10₺ @ %15 satır-bazlı yuvarlamada 0,06₺,
   başlık formülünde 0,05₺ verir.
3. **K3(b)** — İKİ farklı oranlı faturada satır dağıtımının toplamı başlık
   `vat_amount`ına **kuruşu kuruşuna** eşittir. Yuvarlama artığı ne kaybolur ne
   uydurulur (artığın nereye gittiği `amounts` docstring'inde kararlaştırıldı).
4. **K5** — her ara adım `ROUND_HALF_UP`; modülde kayan nokta YOKTUR (AST bekçisi).
"""

import ast
from decimal import Decimal
from pathlib import Path

from app.modules.invoicing import amounts
from app.modules.invoicing.amounts import LineInput, compute, line_total, round_money


def _kalem(miktar: str, fiyat: str, kdv: str) -> LineInput:
    return LineInput(quantity=Decimal(miktar), unit_price=Decimal(fiyat), vat_rate=Decimal(kdv))


# --------------------------------------------------------------------------- #
# §5 — yedi adım, sırayla
# --------------------------------------------------------------------------- #


def test_yedi_adim_mockup_sirasiyla_kosar():
    """FGI:163-186 tfoot sırası: ara toplam → kesintiler → matrah → KDV →
    tevkifat → ödenecek toplam."""
    sonuc = compute(
        [_kalem("10", "1000.00", "20"), _kalem("2", "2500.00", "20")],
        advance_rate=Decimal("20"),
        retention_rate=Decimal("5"),
        withholding_rate=Decimal("20"),
    )
    assert sonuc.subtotal == Decimal("15000.00")  # 10.000 + 5.000
    assert sonuc.advance_amount == Decimal("3000.00")  # subtotal × %20
    assert sonuc.retention_amount == Decimal("750.00")  # subtotal × %5
    assert sonuc.tax_base == Decimal("11250.00")  # 15.000 − 3.000 − 750
    assert sonuc.vat_amount == Decimal("2250.00")  # matrah × %20
    assert sonuc.withholding_amount == Decimal("450.00")  # KDV × %20 (K4)
    assert sonuc.total == Decimal("13050.00")  # 11.250 + 2.250 − 450


def test_kesinti_matrahi_subtotaldir_tax_base_degil():
    """2. ve 3. adım `subtotal`den hesaplanır. Kesintiler zincirleme (önce avans,
    kalandan teminat) uygulansaydı teminat 750 değil 600 çıkardı."""
    sonuc = compute(
        [_kalem("1", "15000.00", "20")],
        advance_rate=Decimal("20"),
        retention_rate=Decimal("5"),
    )
    assert sonuc.retention_amount == Decimal("750.00")
    assert sonuc.advance_amount == Decimal("3000.00")


def test_kdv_matrahi_tax_basedir_subtotal_degil():
    """5. adım `tax_base` üzerinden koşar: kesinti öncesi tutardan hesaplansaydı
    KDV 3.000 çıkar ve fatura fazla vergi tahakkuk ettirirdi."""
    sonuc = compute(
        [_kalem("1", "15000.00", "20")],
        advance_rate=Decimal("20"),
        retention_rate=Decimal("5"),
    )
    assert sonuc.vat_amount == Decimal("2250.00")


def test_tevkifat_kdv_uzerinden_hesaplanir_ve_totaldan_dusulur():
    """K4 — FGE:181→185. Tevkifat matrahı KDV'dir (matrah ya da toplam değil) ve
    `total`DAN DÜŞÜLÜR (eklenmez)."""
    sonuc = compute([_kalem("1", "1000.00", "20")], withholding_rate=Decimal("20"))
    assert sonuc.vat_amount == Decimal("200.00")
    assert sonuc.withholding_amount == Decimal("40.00")  # 200 × %20
    assert sonuc.total == Decimal("1160.00")  # 1000 + 200 − 40


def test_toplam_yedi_adimin_esitligini_korur():
    sonuc = compute(
        [_kalem("3", "133.33", "20"), _kalem("7", "19.99", "10")],
        advance_rate=Decimal("12.50"),
        retention_rate=Decimal("3.75"),
        withholding_rate=Decimal("40"),
    )
    assert sonuc.total == sonuc.tax_base + sonuc.vat_amount - sonuc.withholding_amount
    assert sonuc.tax_base == sonuc.subtotal - sonuc.advance_amount - sonuc.retention_amount


def test_oran_none_ile_sifir_ayni_tutari_verir():
    """Oran NULL "işaretlenmemiş kesinti"dir (FK:223/229/235 checkbox'ları) ve
    tutarı 0'dır — `advance_amount` kolonu NOT NULL olduğu için NULL tutar
    ÜRETİLMEZ."""
    bos = compute([_kalem("1", "100.00", "20")])
    sifir = compute(
        [_kalem("1", "100.00", "20")],
        advance_rate=Decimal("0"),
        retention_rate=Decimal("0"),
        withholding_rate=Decimal("0"),
    )
    assert bos == sifir
    assert bos.advance_amount == Decimal("0.00")


# --------------------------------------------------------------------------- #
# K3 — çok oranlı KDV
# --------------------------------------------------------------------------- #


def test_k3a_tek_oranli_fatura_baslik_formuluyle_birebir():
    """K3(a) — TEK oranda sonuç `round(tax_base × oran / 100)`tur.

    Sayılar bilerek naif uygulamayı ele verecek biçimde seçildi: her satırın
    KDV'si AYRI yuvarlanıp toplansaydı 3 × round(0,015) = 0,06₺ çıkardı;
    başlık formülü round(0,045) = 0,05₺ verir. İkisi aynı olsaydı bu test
    hiçbir şey kanıtlamazdı.
    """
    kalemler = [_kalem("1", "0.10", "15") for _ in range(3)]
    sonuc = compute(kalemler)
    assert sonuc.subtotal == Decimal("0.30")
    assert sonuc.tax_base == Decimal("0.30")
    assert sonuc.vat_amount == round_money(sonuc.tax_base * Decimal("15") / Decimal("100"))
    assert sonuc.vat_amount == Decimal("0.05")


def test_k3a_kesintili_tek_oranli_fatura_da_baslik_formuluyle_birebir():
    kalemler = [_kalem("1", "33.33", "20"), _kalem("1", "33.33", "20"), _kalem("1", "33.34", "20")]
    sonuc = compute(kalemler, advance_rate=Decimal("10"), retention_rate=Decimal("5"))
    assert sonuc.subtotal == Decimal("100.00")
    assert sonuc.tax_base == Decimal("85.00")
    assert sonuc.vat_amount == round_money(sonuc.tax_base * Decimal("20") / Decimal("100"))


def test_k3b_iki_oranli_faturada_satir_dagitimi_kurusuna_kadar_toplanir():
    """K3(b) — artık ne kaybolur ne uydurulur.

    Başlık `vat_amount`ı ORAN GRUPLARININ toplamıdır; satır payları o toplamın
    tam bölünmesidir. İki iddia da eşitliktir: satır KDV payları `vat_amount`a,
    satır tutarları `subtotal`e kuruşu kuruşuna toplanır.
    """
    kalemler = [_kalem("1", "33.33", "20"), _kalem("1", "33.33", "20"), _kalem("1", "33.34", "10")]
    sonuc = compute(kalemler, advance_rate=Decimal("10"), retention_rate=Decimal("5"))

    assert sum(sonuc.line_totals) == sonuc.subtotal
    assert sum(sonuc.line_vat_amounts) == sonuc.vat_amount
    assert sum(sonuc.line_tax_bases) == sonuc.tax_base
    # Karma oranda sonuç TEK oranın formülüyle aynı OLAMAZ — aksi hâlde satır
    # bazlı oranın hiç okunmadığı anlamına gelirdi.
    assert sonuc.vat_amount != round_money(sonuc.tax_base * Decimal("20") / Decimal("100"))


def test_artik_en_buyuk_kesirli_paya_gider_ve_belirlenimcidir():
    """Artığın YERİ kararlaştırılmıştır (bkz. `amounts` docstring'i): en büyük
    kesirli artığa, eşitlikte İLK satıra. Rastgele/son satıra atma seçilseydi
    aynı fatura iki koşuda farklı satır dağılımı verirdi."""
    kalemler = [_kalem("1", "33.33", "20"), _kalem("1", "33.33", "20"), _kalem("1", "33.34", "20")]
    sonuc = compute(kalemler, advance_rate=Decimal("10"), retention_rate=Decimal("5"))
    # 85,00 matrah üç satıra: 28,3305 / 28,3305 / 28,339 → tabanlar 28,33 ×3,
    # artık 0,01 en büyük kesire (üçüncü satır) gider.
    assert sonuc.line_tax_bases == (Decimal("28.33"), Decimal("28.33"), Decimal("28.34"))
    assert sum(sonuc.line_tax_bases) == Decimal("85.00")


def test_satir_kdv_paylari_oranlarina_gore_ayrisir():
    sonuc = compute([_kalem("1", "100.00", "20"), _kalem("1", "100.00", "1")])
    assert sonuc.vat_amount == Decimal("21.00")
    assert sonuc.line_vat_amounts == (Decimal("20.00"), Decimal("1.00"))


# --------------------------------------------------------------------------- #
# Sıfır / sınır
# --------------------------------------------------------------------------- #


def test_kalemsiz_fatura_sifir_uretir_ve_sifira_bolmez():
    sonuc = compute([])
    assert sonuc.subtotal == Decimal("0.00")
    assert sonuc.tax_base == Decimal("0.00")
    assert sonuc.vat_amount == Decimal("0.00")
    assert sonuc.total == Decimal("0.00")
    assert sonuc.line_totals == ()


def test_bedelsiz_kalemlerde_subtotal_sifir_kdv_sifir():
    """K3'ün sıfıra bölme ayağı: `tax_base / subtotal` payı `subtotal = 0`
    olduğunda hesaplanamaz. Kalem VARDIR ama tutarı yoktur."""
    sonuc = compute(
        [_kalem("5", "0.00", "20"), _kalem("3", "0.00", "10")],
        advance_rate=Decimal("20"),
        withholding_rate=Decimal("20"),
    )
    assert sonuc.subtotal == Decimal("0.00")
    assert sonuc.vat_amount == Decimal("0.00")
    assert sonuc.line_vat_amounts == (Decimal("0.00"), Decimal("0.00"))
    assert sonuc.total == Decimal("0.00")


def test_tam_kesinti_matrahi_sifirlar_kdv_de_sifirdir():
    sonuc = compute(
        [_kalem("1", "1000.00", "20")],
        advance_rate=Decimal("60"),
        retention_rate=Decimal("40"),
    )
    assert sonuc.tax_base == Decimal("0.00")
    assert sonuc.vat_amount == Decimal("0.00")
    assert sonuc.total == Decimal("0.00")


# --------------------------------------------------------------------------- #
# K5 — yuvarlama ve kayan nokta yasağı
# --------------------------------------------------------------------------- #


def test_satir_tutari_iki_haneye_half_up_yuvarlanir():
    """Miktar Numeric(14,3), fiyat Numeric(18,2) — çarpım 5 haneli olabilir ama
    kolon 2 hanelidir. `ROUND_DOWN` olsaydı 0,015 → 0,01 olurdu."""
    assert line_total(Decimal("1.5"), Decimal("0.01")) == Decimal("0.02")
    assert line_total(Decimal("2.5"), Decimal("0.01")) == Decimal("0.03")
    assert compute([_kalem("1.5", "0.01", "20")]).subtotal == Decimal("0.02")


def test_kesinti_tutari_half_up_yuvarlanir():
    """0,10 × %25 = 0,025 → HALF_UP 0,03. `ROUND_DOWN`/bankacı yuvarlaması
    0,02 verirdi."""
    sonuc = compute([_kalem("1", "0.10", "20")], advance_rate=Decimal("25"))
    assert sonuc.advance_amount == Decimal("0.03")


def test_tevkifat_half_up_yuvarlanir():
    sonuc = compute([_kalem("1", "0.50", "10")], withholding_rate=Decimal("50"))
    assert sonuc.vat_amount == Decimal("0.05")
    assert sonuc.withholding_amount == Decimal("0.03")  # 0,025 → HALF_UP


def test_round_money_half_up_ve_iki_hane():
    assert round_money(Decimal("0.005")) == Decimal("0.01")
    assert round_money(Decimal("0.015")) == Decimal("0.02")
    assert round_money(Decimal("2.344")) == Decimal("2.34")
    assert round_money(Decimal("2.345")) == Decimal("2.35")
    assert round_money(Decimal("7")).as_tuple().exponent == -2


def test_tum_ciktilar_iki_haneli_decimaldir():
    sonuc = compute(
        [_kalem("3.333", "7.77", "18"), _kalem("1.001", "0.03", "8")],
        advance_rate=Decimal("7.5"),
        retention_rate=Decimal("2.5"),
        withholding_rate=Decimal("30"),
    )
    degerler = (
        sonuc.subtotal,
        sonuc.advance_amount,
        sonuc.retention_amount,
        sonuc.tax_base,
        sonuc.vat_amount,
        sonuc.withholding_amount,
        sonuc.total,
        *sonuc.line_totals,
        *sonuc.line_tax_bases,
        *sonuc.line_vat_amounts,
    )
    assert all(isinstance(deger, Decimal) for deger in degerler)
    assert all(deger.as_tuple().exponent == -2 for deger in degerler)


def test_amounts_modulunde_kayan_nokta_YOK():
    """K5 bekçisi. Tek bir `float()` çağrısı ya da `0.01` gibi bir kayan nokta
    değişmezi para hesabını sessizce yanlış yapar (`0.1 + 0.2 != 0.3`) ve bunu
    yalnız kuruş farkı olarak, aylar sonra mali tabloda gösterir. Bekçi METİN
    ARAMASI DEĞİL AST'dir: yorum satırındaki bir örnek testi kırmasın, ama
    `Decimal(0.1)` gibi gizli bir kayan nokta kaçmasın.
    """
    kaynak = Path(amounts.__file__).read_text(encoding="utf-8")
    agac = ast.parse(kaynak)
    kayan_sabitler = [
        dugum
        for dugum in ast.walk(agac)
        if isinstance(dugum, ast.Constant) and isinstance(dugum.value, float)
    ]
    kayan_cagrilar = [
        dugum for dugum in ast.walk(agac) if isinstance(dugum, ast.Name) and dugum.id == "float"
    ]
    assert not kayan_sabitler, "amounts.py'de kayan nokta değişmezi var"
    assert not kayan_cagrilar, "amounts.py'de `float` kullanımı var"


def test_compute_girdi_kalemlerini_DEGISTIRMEZ():
    """Saflık: hesap girdi nesnelerine yazmaz (`line_total` alanını kalemin
    üstüne iliştirmek cazip ama T3'ün ORM satırlarını sessizce kirletirdi)."""
    kalemler = [_kalem("2", "10.00", "20")]
    once = (kalemler[0].quantity, kalemler[0].unit_price, kalemler[0].vat_rate)
    compute(kalemler, advance_rate=Decimal("10"))
    assert (kalemler[0].quantity, kalemler[0].unit_price, kalemler[0].vat_rate) == once
