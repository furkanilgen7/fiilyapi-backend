"""`app/core/iban.py` — IBAN biçim + mod-97 doğrulamasının BİRİM testleri.

## Neden ortak bir modül (ve neden testi burada)

Canlı smoke'ta `POST /bank-accounts` gövdesine `BUNUBIRIBANDEGIL!!` gönderildi ve
**201** döndü: ne uzunluk, ne ülke kodu, ne sağlama vardı. `TR` + 24 sıfır da
kabul edildi. Alan bir PARA yüzeyidir — ödeme talimatı buradan çıkar.

Kolon İKİ yerdedir (`bank_accounts.iban` · `personnel.iban`) ve giriş noktası
DÖRTtür (iki Create + iki Update). Kural her birine ayrı ayrı yazılsaydı biri
güncellenip öteki unutulur ve kapı o uçtan atlatılırdı (`app/core/text.py`
emsali). Bu yüzden kural TEK yerdedir ve birim testi de o tek yerdedir; uç
testleri yalnız BAĞLANMIŞ olduğunu kanıtlar.

## Kalıcı kararlar

* `None` GEÇER — kolon her iki tabloda da nullable'dır ve öyle KALIR. Kasa
  satırında IBAN yoktur (E9:83), personelde ise elden ödeme meşrudur.
* Boş/yalnız boşluk → `None`. Boş metin saklansaydı `uq_bank_accounts_iban`
  kısmi indeksi onu "dolu" sayar ve İKİNCİ boş-IBAN'lı kasa 409 alırdı.
* Saklama biçimi NORMALİZEDİR (boşluksuz, BÜYÜK harf): aynı IBAN iki kayıtta
  iki türlü durmasın.
"""

import pytest

from app.core.iban import IBAN_INVALID, normalize_iban, validate_iban

# ISO 13616'nın referans TR örneği — mod-97 sağlaması 1'dir.
GECERLI = "TR330006100519786457841326"


# --------------------------------------------------------------------------- #
# normalize_iban — biçime BAKMAZ, yalnız sıkıştırır/büyütür
# --------------------------------------------------------------------------- #


def test_normalize_none_none_dondurur() -> None:
    assert normalize_iban(None) is None


@pytest.mark.parametrize("bos", ["", "   ", "\t\n"])
def test_normalize_bos_deger_NULL_olur(bos: str) -> None:
    """Boş metin saklanmaz: kısmi UNIQUE indeksi onu "dolu" sayardı."""
    assert normalize_iban(bos) is None


def test_normalize_bosluklari_atar_ve_buyutur() -> None:
    assert normalize_iban("tr33 0006 1005 1978 6457 8413 26") == GECERLI


# --------------------------------------------------------------------------- #
# validate_iban — NULL'ı geçirir, dolu değeri SINAR
# --------------------------------------------------------------------------- #


def test_validate_none_gecer_alan_ZORUNLU_DEGIL() -> None:
    assert validate_iban(None) is None


@pytest.mark.parametrize("bos", ["", "   "])
def test_validate_bos_deger_NULL_olur(bos: str) -> None:
    assert validate_iban(bos) is None


def test_validate_gecerli_iban_NORMALIZE_edilmis_doner() -> None:
    assert validate_iban("tr33 0006 1005 1978 6457 8413 26") == GECERLI


def test_validate_mod97_bozuk_reddeder() -> None:
    """🔴 Bu testin taşıyıcısı SAĞLAMADIR: değer 26 hanelidir, `TR` ile başlar ve
    biçim regex'ini GEÇER — yalnız mod-97 onu yakalar."""
    bozuk = "TR340006100519786457841326"  # yalnız sağlama hanesi 33→34
    with pytest.raises(ValueError, match=IBAN_INVALID):
        validate_iban(bozuk)


def test_validate_canli_smokeun_degeri_reddedilir() -> None:
    """Canlıda **201** alan gövde (yönetim smoke'u) — kusurun kendisi."""
    with pytest.raises(ValueError, match=IBAN_INVALID):
        validate_iban("BUNUBIRIBANDEGIL!!")


def test_validate_TR_ve_24_sifir_reddedilir() -> None:
    """Canlıda kabul edilen ikinci değer: biçim doğru, sağlama YANLIŞ."""
    with pytest.raises(ValueError, match=IBAN_INVALID):
        validate_iban("TR000000000000000000000000")


@pytest.mark.parametrize(
    "kisa",
    [
        "TR00",  # ülke + sağlama var, BBAN yok
        "TR3300061005",  # 12 hane — asgari 15'in altında
    ],
)
def test_validate_cok_kisa_reddeder(kisa: str) -> None:
    with pytest.raises(ValueError, match=IBAN_INVALID):
        validate_iban(kisa)


def test_validate_TR_uzunlugu_26_degilse_reddeder() -> None:
    """🔴 Ülkeye özgü uzunluk AYRI bir kapıdır: aşağıdaki değer mod-97'yi GEÇER
    ama TR'de 26 hane olmalıdır (ISO 13616 kayıt defteri). Yalnız sağlamaya
    bakılsaydı 27 haneli bir "TR" IBAN'ı ödeme talimatına girerdi."""
    # 27 hane, mod-97 == 1 (aşağıdaki testte sağlaması ayrıca kanıtlanır).
    uzun = "TR0400061005197864578413260"
    with pytest.raises(ValueError, match=IBAN_INVALID):
        validate_iban(uzun)


def test_TR_uzunluk_testinin_degeri_MOD97yi_GECER() -> None:
    """Üstteki testin gerçekten UZUNLUK kapısını sınadığının kanıtı.

    Değer sağlamadan da düşseydi test yeşil kalır ama TR uzunluk kuralı hiç
    denenmemiş olurdu (sahte bekçi).
    """
    from app.core.iban import _mod97  # noqa: PLC0415

    assert _mod97("TR0400061005197864578413260") == 1


def test_validate_ulke_kodu_rakamla_baslayamaz() -> None:
    with pytest.raises(ValueError, match=IBAN_INVALID):
        validate_iban("1233 0006 1005 1978 6457 8413 26")


def test_validate_saglama_hanesi_harf_olamaz() -> None:
    with pytest.raises(ValueError, match=IBAN_INVALID):
        validate_iban("TRAB0006100519786457841326")


def test_validate_34_uzeri_reddeder() -> None:
    """ISO 13616 azamisi 34'tür; şema `max_length=34` ile de sınırlar ama kural
    şemadan BAĞIMSIZ olarak burada da durmalıdır (savunma derinliği)."""
    with pytest.raises(ValueError, match=IBAN_INVALID):
        validate_iban("TR" + "0" * 40)
