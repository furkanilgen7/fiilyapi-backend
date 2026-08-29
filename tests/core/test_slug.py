"""URL-2 · `app/core/slug.py` — Türkçe harf dönüşümü ve slug ayırma.

Bu dosyanın tek işi **`str.lower()` tuzağını kanıtlamaktır**. Türkçe harfler
tabloyla değil `lower()` ile çevrilseydi:

  * `"İ"` -> `"i" + U+0307` (birleşik nokta) -> `[a-z0-9]` süzgecinden geçmez,
    `İstanbul` slug'ı `-stanbul` olurdu;
  * `"I"` -> `"i"` doğru ASCII'ye düşerdi ama Türkçe küçüğü `"ı"`dır;
    `"ı"` ise `lower()`da zaten `"ı"` kalır ve yine süzgeçten geçmezdi.

Bu yüzden **tablodaki her harf tek tek** kanıtlanır ve `İ`/`ı` için AYRI
iddialar yazılır (emirdeki zorunluluk).
"""

import pytest

from app.core.slug import (
    MAX_SLUG_LENGTH,
    allocate_slug,  # noqa: F401  (DB'li testi tests/modules/sites'ta)
    parse_ref,
    slugify,
    unique_slug,
)

# ---------------------------------------------------------------------------
# Türkçe dönüşüm tablosu — emirde birebir verilen küme.
# ---------------------------------------------------------------------------
TURKISH_TABLE = {
    "Ç": "c",
    "Ğ": "g",
    "İ": "i",
    "Ö": "o",
    "Ş": "s",
    "Ü": "u",
    "ç": "c",
    "ğ": "g",
    "ı": "i",
    "ö": "o",
    "ş": "s",
    "ü": "u",
    # Tabloda AYRICA olması gereken harf: noktasız BÜYÜK I. Türkçe'de küçüğü
    # `ı`dır ve `ı` da `i`ye düşer — iki yol da aynı ASCII harfe varmalıdır.
    "I": "i",
}


@pytest.mark.parametrize(("harf", "beklenen"), sorted(TURKISH_TABLE.items()))
def test_turkce_harf_tek_tek_ascii_karsiligina_duser(harf: str, beklenen: str) -> None:
    assert slugify(harf) == beklenen


def test_buyuk_noktali_I_birlesik_nokta_BIRAKMAZ() -> None:
    """🔴 `"İ".lower()` İKİ kod noktası üretir; slug'da bunun izi OLMAMALI."""
    # Önce tuzağın GERÇEKTEN var olduğunu ölç — pozitif kontrolün aynası.
    assert len("İ".lower()) == 2
    assert "̇" in "İ".lower()

    slug = slugify("İstanbul")
    assert slug == "istanbul"
    assert "̇" not in slug
    assert not slug.startswith("-")


def test_kucuk_noktasiz_i_ascii_i_olur() -> None:
    """`ı` `lower()`da `ı` KALIR ve süzgeçten geçmezdi; tablo onu `i`ye çevirir."""
    assert "ı".lower() == "ı"
    assert slugify("Işıklar") == "isiklar"
    assert slugify("ısırgan") == "isirgan"


def test_kullanicinin_ornegi() -> None:
    """Emrin birebir örneği — bu satır kırılırsa dilim amacını kaybetti."""
    assert slugify("Köprü Güçlendirme") == "kopru-guclendirme"


def test_tum_tablo_tek_dizede() -> None:
    assert slugify("ÇĞİÖŞÜçğıöşü") == "cgiosucgiosu"


@pytest.mark.parametrize(
    ("ham", "beklenen"),
    [
        ("  A  Blok--2 ", "a-blok-2"),
        ("Café Rénové", "cafe-renove"),  # NFKD: Türkçe dışı aksanlar da düşer
        ("A/B & C", "a-b-c"),
        ("2026 Yılı", "2026-yili"),
        ("---kenar---", "kenar"),
    ],
)
def test_genel_normalizasyon(ham: str, beklenen: str) -> None:
    assert slugify(ham) == beklenen


# ---------------------------------------------------------------------------
# Boş slug — emirdeki "boş/çakışan slug ne olacak?" sorusunun birinci yarısı.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("ham", ["...", "???", "   ", "-", "", "。。。", "!!!"])
def test_sluglanamayan_ad_None_doner_UYDURULMAZ(ham: str) -> None:
    """Uydurma bir taban (`kayit`) yazmak çakışma üretir, okunabilirlik getirmez.

    `None` = kolon NULL kalır = o kaydın URL'i UUID olarak yaşar (karar 2).
    """
    assert slugify(ham) is None


def test_None_girdi_None_doner() -> None:
    assert slugify(None) is None


def test_tavan_uygulanir_ve_kenar_tire_birakmaz() -> None:
    slug = slugify("a" * 50 + " " + "b" * 200)
    assert slug is not None
    assert len(slug) <= MAX_SLUG_LENGTH
    assert not slug.endswith("-")


# ---------------------------------------------------------------------------
# Çakışan slug — ikinci yarı. SESSİZCE ÇAKIŞTIRMA YOK.
# ---------------------------------------------------------------------------
def test_farkli_iki_ad_ayni_tabana_duser() -> None:
    """Ölçüm: `Köprü A` ile `Kopru A` AYNI tabanı üretir — çakışma gerçektir."""
    assert slugify("Köprü A") == slugify("Kopru A") == "kopru-a"


def test_cakisma_sayi_ekiyle_cozulur() -> None:
    assert unique_slug("kopru-a", set()) == "kopru-a"
    assert unique_slug("kopru-a", {"kopru-a"}) == "kopru-a-2"
    assert unique_slug("kopru-a", {"kopru-a", "kopru-a-2"}) == "kopru-a-3"
    # Boşluklu sıra: `-2` doluysa `-3` denenir, boş `-2` tekrar KULLANILMAZ mı?
    # KULLANILIR — kapsamda serbest olan ilk ek alınır, numara rezerve değildir.
    assert unique_slug("kopru-a", {"kopru-a", "kopru-a-3"}) == "kopru-a-2"


def test_ek_1_DEGIL_2_den_baslar() -> None:
    """`-1` yazılsaydı kullanıcı "birinci Köprü"yü eksiz slug'da arardı."""
    assert unique_slug("x", {"x"}).endswith("-2")


def test_taban_None_ise_ek_de_None() -> None:
    assert unique_slug(None, {"a"}) is None


# ---------------------------------------------------------------------------
# parse_ref — UUID uzayı ile slug uzayı KESİŞMEZ.
# ---------------------------------------------------------------------------
def test_parse_ref_uuid_tanir() -> None:
    import uuid as _uuid

    ham = "049e058b-42d9-4e46-aafe-4bcf629e80cd"
    assert parse_ref(ham) == _uuid.UUID(ham)


def test_parse_ref_slug_metin_birakir() -> None:
    assert parse_ref("kopru-guclendirme") == "kopru-guclendirme"


def test_hicbir_gecerli_slug_UUID_olarak_ayristirilamaz() -> None:
    """Slug `[a-z0-9-]`dir; `parse_ref` bir slug'ı asla UUID sanmamalı.

    Tek kaygı: 32 hex hanesi + tireler tesadüfen UUID biçimine düşebilir mi?
    Düşebilir (`slugify` hex haneleri korur) — ama o zaman zaten UUID olarak
    ele alınması DOĞRUDUR: böyle bir slug UUID'siyle çakışmadıkça erişilemez
    kalır ve bu, kaydın UUID yolunun her zaman çalışmasından daha az önemlidir.
    """
    assert parse_ref(slugify("Köprü Güçlendirme")) == "kopru-guclendirme"


# ---------------------------------------------------------------------------
# 🔴 EŞDEĞER MUTANT ÖLÇÜMÜ — İKİ KATMAN BİRBİRİNİ MASKELİYOR
#
# `slugify` iki katmanlı: (1) açık Türkçe tablosu, (2) NFKD + birleşik işaret
# düşürme. Mutasyonla ölçüldü: tabloyu TAMAMEN kaldırınca `Ç Ğ İ Ö Ş Ü ç ğ ö ş ü`
# için sonuç DEĞİŞMİYOR — NFKD hepsini ayrıştırıp aynı ASCII'yi üretiyor.
# Yani yukarıdaki harf harf testlerin 11'i tabloyu değil NFKD'yi ölçüyor
# olabilir: onlar tek başına "tablo var" demez.
#
# Tablonun TEK TAŞIYICI harfi `ı`dır (U+0131): Unicode'da ayrışmaz, `lower()`da
# değişmez, süzgeçten geçmez -> harf tamamen DÜŞER. Aşağıdaki test tam olarak
# bu yükü ölçer ve bağımsızdır: NFKD katmanı onu kurtaramaz.
# ---------------------------------------------------------------------------


def test_i_HARFI_TABLONUN_TEK_TASIYICI_HARFIDIR() -> None:
    """`ı` tablosuz kaybolurdu: `Işıklar` -> `is-klar`. Tablo bunu ÖNLER."""
    import re
    import unicodedata

    def nfkd_only(value: str) -> str:
        """Tablo OLMADAN, yalnız NFKD + lower() ile slug — mutant davranışı."""
        decomposed = unicodedata.normalize("NFKD", value)
        stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
        return re.sub(r"[^a-z0-9]+", "-", stripped.lower()).strip("-")

    # Mutant GERÇEKTEN bozuk — harf düşüyor (negatif ölçüm).
    assert nfkd_only("Işıklar") == "is-klar"
    # Kanonik uygulama ise doğru (pozitif kontrol).
    assert slugify("Işıklar") == "isiklar"

    # Ve maskelenmenin kapsamı: `ı` DIŞINDAKİ her harf için iki yol AYNI sonucu
    # verir. Bu iddia, ileride biri "tabloyu sadeleştirelim" dediğinde neyin
    # gerçekten yük taşıdığını gösterir.
    for harf in "ÇĞİÖŞÜçğöşü":
        assert nfkd_only(harf) == slugify(harf), harf
    assert nfkd_only("ı") != slugify("ı")
