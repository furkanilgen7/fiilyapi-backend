"""MU-1 T3a — kod dilbilgisinin (K4) SAF davranışı.

Spec: `docs/superpowers/specs/2026-08-15-mu1-muhasebe-cekirdegi-design.md` §1a, §3a.

`codes.py` DB bilmez, `today` bilmez: tamamen metin üzerinde çalışır ve bu
yüzden burada oturum/istemci fixture'ı YOKTUR. Kilitlenen dört karar:

1. **Kapalı biçim kümesi** — `NN` · `NNN` · `NNN.NN`. İlk hane `0` OLAMAZ
   (sınıfsız hesap yoktur) ve **`NNN.NN.NNN` (üçüncü kırılım) hiçbir mockup'ta
   YOKTUR → yapısal olarak reddedilir**. Regex gevşetilirse mizanın (MU-2) hiç
   görmediği bir düzey doğar.
2. **Sınıf bir KAYIT DEĞİLDİR** (HP:69,135,161,187 bantlarında kod sütunu yok):
   kodun ilk hanesinden TÜRETİLİR ve `parent_code("12")` **`None`**dır.
3. **K15 — satırlar kazanır:** HP:187 bandı `SINIF 5` yazar ama altındaki kodlar
   `600`/`730`/`760`tır. `class_code` bant etiketini DEĞİL kodu okur → `6`/`7`.
4. **Hiyerarşi kodun İÇİNDEDİR** (`parent_id` FK YOKTUR): `120.01` → `120` →
   `12` → yok.
"""

import pytest

from app.modules.accounting import codes

# --- 1. Biçim: kabul edilenler ---


@pytest.mark.parametrize("code", ["10", "12", "15", "19", "99"])
def test_grup_kodu_gecerlidir(code: str) -> None:
    """HP:72,97,115 — `NN` bir KAYITTIR (grup), yalnız bazı sütunları render edilmez."""
    assert codes.is_valid(code) is True
    assert codes.level(code) == codes.GROUP_LEVEL


@pytest.mark.parametrize("code", ["100", "101", "191", "257", "600", "730", "760"])
def test_ana_hesap_kodu_gecerlidir(code: str) -> None:
    assert codes.is_valid(code) is True
    assert codes.level(code) == codes.MAIN_LEVEL


@pytest.mark.parametrize("code", ["120.01", "320.04", "153.01"])
def test_alt_hesap_kodu_gecerlidir(code: str) -> None:
    """E8:112,120,128,136,144,152 — defterin HER satırı bu derinliktedir."""
    assert codes.is_valid(code) is True
    assert codes.level(code) == codes.SUB_LEVEL


# --- 2. Biçim: reddedilenler ---


@pytest.mark.parametrize(
    "code",
    [
        "1",  # sınıf KAYIT DEĞİLDİR
        "0",
        "01",  # ilk hane 0 olamaz
        "012",
        "0120.01",
        "1200",  # dört hane yok
        "120.1",  # kırılım İKİ hanedir
        "120.001",
        "120.01.001",  # 🔴 ÜÇÜNCÜ KIRILIM AÇILMAZ
        "12.01",  # grubun altına doğrudan alt hesap açılmaz
        "12A",
        "",
        " 120",
        "120 ",
        "120.",
        ".01",
    ],
)
def test_gecersiz_kod_reddedilir(code: str) -> None:
    """🔴 Üçüncü kırılım ve sınıf kodu BURADA ölür.

    `120.01.001` kabul edilseydi mizanın hiç görmediği bir düzey doğar; `1`
    kabul edilseydi bant etiketi bir KAYDA dönüşür ve HP:69'un kodsuz bandı
    kendisiyle çelişirdi.
    """
    assert codes.is_valid(code) is False
    with pytest.raises(ValueError):
        codes.level(code)


# --- 3. Sınıf kodu — K15: satırlar kazanır ---


@pytest.mark.parametrize(
    ("code", "beklenen"),
    [
        ("10", "1"),
        ("100", "1"),
        ("120.01", "1"),
        ("257", "2"),
        ("320", "3"),
        ("600", "6"),  # 🔴 HP:187 bandı "SINIF 5" der — bant YANLIŞTIR
        ("730", "7"),
        ("760", "7"),
    ],
)
def test_sinif_kodu_KODDAN_turer_banttan_degil(code: str, beklenen: str) -> None:
    """🔴 K15 + HP:126 tutarsızlığı: `191` görsel olarak `15 Stoklar` bandının
    altındadır ama grubu KODDAN gelir (`19`), yerleşimden değil."""
    assert codes.class_code(code) == beklenen


def test_191_grubu_yerlesimden_degil_koddan_okunur() -> None:
    """HP:126 mockup iç tutarsızlığı — ebeveyn `19`dur, `15` DEĞİL."""
    assert codes.parent_code("191") == "19"


# --- 4. Ebeveyn: hiyerarşi kodun İÇİNDE ---


@pytest.mark.parametrize(
    ("code", "beklenen"),
    [
        ("120.01", "120"),
        ("320.04", "320"),
        ("100", "10"),
        ("257", "25"),
        ("760", "76"),
    ],
)
def test_ebeveyn_kodu_bir_duzey_yukaridir(code: str, beklenen: str) -> None:
    assert codes.parent_code(code) == beklenen


@pytest.mark.parametrize("code", ["10", "12", "76"])
def test_grubun_ebeveyni_YOKTUR_cunku_sinif_kayit_degildir(code: str) -> None:
    """🔴 `parent_code("12")` `"1"` DÖNMEZ: sınıf bir kayıt değildir ve dönseydi
    servis var olmayan bir ebeveyni aramaya kalkardı."""
    assert codes.parent_code(code) is None


# --- 5. Çocuk öneki — alt düzey aramasının TEK yazımı ---


@pytest.mark.parametrize(("code", "beklenen"), [("12", "12"), ("120", "120")])
def test_cocuk_oneki_alt_duzeyleri_kapsar(code: str, beklenen: str) -> None:
    """Önek kendisiyle başlayan TÜM torunları da kapsar: `12` → `120`,`127`,`120.01`.

    Torunlar dışlansaydı, çocuğu silinmiş ama torunu duran bir grup "yaprak"
    sanılır ve fiş satırı ona kesilebilirdi.
    """
    assert codes.child_prefix(code) == beklenen


def test_en_alt_duzeyin_cocuk_oneki_YOKTUR() -> None:
    """`NNN.NN` altına bir şey açılamaz (üçüncü kırılım yok) → `None`.

    `"120.01"` dönseydi çağıran boş dönecek bir LIKE sorgusu koşardı; `None`
    çağırana "hiç sorma" der.
    """
    assert codes.child_prefix("120.01") is None


def test_desen_sabiti_dogrudan_kullanilabilir() -> None:
    """Şema (`schemas.py`) aynı deseni Pydantic `pattern`ı olarak kullanır —
    ikinci bir regex yazılsaydı biri gevşetilip öteki unutulurdu."""
    import re

    assert re.match(codes.ACCOUNT_CODE_PATTERN, "120.01")
    assert re.match(codes.ACCOUNT_CODE_PATTERN, "120.01.001") is None
