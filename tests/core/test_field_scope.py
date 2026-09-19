"""Alan düzeyinde kapsam maskesi — `limited` ve `finance` (kullanıcı kararı 2026-09-19).

## Neden ALAN düzeyinde

`require_permission` bir UCU kapatır; bu ise bir ALANI kapatır — ayrım
`core/permissions.can_read`in docstring'inde zaten yazılıydı, bu modül onu
KAPSAMA bağlar.

## Üç kova, iki maske

* **kimlik** — id, ad, kod, durum, tarih. HİÇBİR kapsamda gizlenmez. Bu kova
  olmasaydı `finance` birebir uygulandığında muhasebe projenin ADINI bile
  göremez ve her muhasebe ekranı kullanılamaz hâle gelirdi (ölçüldü, kullanıcı
  kararı bu yüzden "kimlik + para").
* **para** — `limited` GİZLER, `finance` gösterir.
* **operasyonel** — `finance` GİZLER, `limited` gösterir.

İki maske birbirinin AYNASIDIR; testler bunu iki yönlü çakar.

## 🔴 Maske MUTASYON YAPMAZ

Yeni nesne döner. Kaynak nesne değiştirilseydi aynı yanıt zarfını paylaşan bir
başka çağrı (ör. önbellek, toplu üretim) sessizce maskelenmiş veri görürdü.
"""

import uuid
from decimal import Decimal
from typing import Annotated

import pytest
from pydantic import BaseModel, computed_field

from app.core.access import Scope
from app.core.field_scope import Gorunurluk, maskele

_PARA = Gorunurluk.para
_OP = Gorunurluk.operasyonel


class _Kalem(BaseModel):
    id: uuid.UUID
    ad: str
    birim_fiyat: Annotated[Decimal | None, _PARA] = None
    miktar: Annotated[Decimal | None, _OP] = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def tutar(self) -> Decimal | None:
        if self.birim_fiyat is None or self.miktar is None:
            return None
        return self.birim_fiyat * self.miktar


class _Grup(BaseModel):
    ad: str
    toplam: Annotated[Decimal | None, _PARA] = None
    isci_sayisi: Annotated[int | None, _OP] = None
    kalemler: list[_Kalem] = []


def _kalem(**kw) -> _Kalem:
    return _Kalem(
        id=uuid.uuid4(), ad="Beton", birim_fiyat=Decimal("100"), miktar=Decimal("3"), **kw
    )


def _grup() -> _Grup:
    return _Grup(ad="Kaba Yapı", toplam=Decimal("300"), isci_sayisi=7, kalemler=[_kalem()])


# --------------------------------------------------------------------------- #
# `all` — hiçbir şey gizlenmez (POZİTİF KONTROL)
# --------------------------------------------------------------------------- #


def test_ALL_kapsaminda_HICBIR_alan_gizlenmez() -> None:
    """🔴 Bu test olmadan maske "her şeyi gizle" hâline gelse de öteki testler
    yeşil kalırdı."""
    grup = _grup()
    sonuc = maskele(grup, Scope.all)

    assert sonuc.toplam == Decimal("300")
    assert sonuc.isci_sayisi == 7
    assert sonuc.kalemler[0].birim_fiyat == Decimal("100")
    assert sonuc.kalemler[0].miktar == Decimal("3")


# --------------------------------------------------------------------------- #
# `limited` — PARA gizli
# --------------------------------------------------------------------------- #


def test_LIMITED_para_alanlarini_gizler_operasyoneli_BIRAKIR() -> None:
    sonuc = maskele(_grup(), Scope.limited)

    assert sonuc.toplam is None, "para gizlenmedi"
    assert sonuc.isci_sayisi == 7, "operasyonel alan YANLIŞLIKLA gizlendi"
    assert sonuc.ad == "Kaba Yapı", "kimlik alanı gizlendi"


def test_LIMITED_ic_ice_semalara_da_INER() -> None:
    """🔴 Yüzeysel bir maske listenin İÇİNDEKİ tutarı sızdırırdı — BOQ'ta
    grup toplamı gizlenip kalem birim fiyatı açıkta kalırdı."""
    sonuc = maskele(_grup(), Scope.limited)

    assert sonuc.kalemler[0].birim_fiyat is None
    assert sonuc.kalemler[0].miktar == Decimal("3")


def test_LIMITED_TUREV_alan_da_DUSER() -> None:
    """`tutar` bir `computed_field`tır: girdisi maskelenince kendiliğinden
    `None` olmalıdır. Türev maskelenmeseydi birim fiyat gizlenirken tutar
    açıkta kalır ve bölmeyle geri hesaplanabilirdi."""
    sonuc = maskele(_grup(), Scope.limited)

    assert sonuc.kalemler[0].tutar is None


# --------------------------------------------------------------------------- #
# `finance` — OPERASYONEL gizli (limited'in AYNASI)
# --------------------------------------------------------------------------- #


def test_FINANCE_operasyoneli_gizler_PARAYI_BIRAKIR() -> None:
    sonuc = maskele(_grup(), Scope.finance)

    assert sonuc.isci_sayisi is None, "operasyonel detay gizlenmedi"
    assert sonuc.toplam == Decimal("300"), "para YANLIŞLIKLA gizlendi"


def test_FINANCE_KIMLIK_alanlarini_GIZLEMEZ() -> None:
    """🔴 KARARIN ÇEKİRDEĞİ — birebir "yalnız para" uygulansaydı muhasebe
    projenin ADINI göremez ve ekran kullanılamaz olurdu."""
    sonuc = maskele(_grup(), Scope.finance)

    assert sonuc.ad == "Kaba Yapı"
    assert sonuc.kalemler[0].ad == "Beton"
    assert sonuc.kalemler[0].id is not None


# --------------------------------------------------------------------------- #
# Değişmezlik
# --------------------------------------------------------------------------- #


def test_maske_KAYNAGI_DEGISTIRMEZ() -> None:
    """Kaynak değişseydi aynı zarfı paylaşan başka bir çağrı sessizce
    maskelenmiş veri görürdü."""
    grup = _grup()
    maskele(grup, Scope.limited)

    assert grup.toplam == Decimal("300")
    assert grup.kalemler[0].birim_fiyat == Decimal("100")


@pytest.mark.parametrize("kapsam", [Scope.all, Scope.limited, Scope.finance])
def test_maske_YENI_nesne_doner(kapsam: Scope) -> None:
    grup = _grup()
    assert maskele(grup, kapsam) is not grup


# --------------------------------------------------------------------------- #
# ZARFLI alanlar — `None` DEĞİL, "izin yok" hâli
# --------------------------------------------------------------------------- #


class _Zarf(BaseModel):
    """`MetricPlaceholder`ın davranışını taklit eden asgari zarf."""

    available: bool = False
    value: Decimal | None = None

    def kisitli(self) -> "_Zarf":
        return _Zarf(available=False, value=None)


class _Kart(BaseModel):
    ad: str
    butce: Annotated[_Zarf, _PARA]
    ilerleme: Annotated[_Zarf, _OP]


def test_ZARFLI_alan_NONE_yerine_KISITLI_hale_cekilir() -> None:
    """🔴 Zarflı alanı `None` yapmak ŞEMAYI KIRARDI (alan zorunlu bir nesnedir)
    ve ekran "veri yok" ile "yetkin yok"u ayırt edemezdi.

    Ürünün bu ayrım için ZATEN kanonik bir hâli var (`MetricPlaceholder`in
    üçüncü hâli, kullanıcı kararı 2026-08-27): `available=False` +
    `pending_module is None` = *"rolün izni yok"*. Maske onu ÜRETİR, yeniden
    icat etmez.
    """
    kart = _Kart(
        ad="A Blok",
        butce=_Zarf(available=True, value=Decimal("500")),
        ilerleme=_Zarf(available=True, value=Decimal("42")),
    )

    sinirli = maskele(kart, Scope.limited)
    assert sinirli.butce is not None, "zarf None'a çekildi — şema kırılırdı"
    assert sinirli.butce.available is False
    assert sinirli.butce.value is None
    # operasyonel zarf DOKUNULMAZ
    assert sinirli.ilerleme.available is True
    assert sinirli.ilerleme.value == Decimal("42")

    mali = maskele(kart, Scope.finance)
    assert mali.ilerleme.available is False, "operasyonel zarf kısıtlanmadı"
    assert mali.butce.value == Decimal("500"), "para zarfı YANLIŞLIKLA kısıtlandı"


# --------------------------------------------------------------------------- #
# İKİ KOVADAN türeyen alan — HER İKİ maske de gizler
# --------------------------------------------------------------------------- #


class _IkiKova(BaseModel):
    """Bazı değerler hem paradan hem operasyonelden türer."""

    ad: str
    # `Σ(metraj × birim fiyat)` — girdilerinden BİRİ gizlenince değer anlamsızdır.
    genel_toplam: Annotated[Decimal | None, _PARA, _OP] = Decimal("5000")
    yalniz_para: Annotated[Decimal | None, _PARA] = Decimal("100")
    yalniz_op: Annotated[Decimal | None, _OP] = Decimal("12")


def test_IKI_KOVALI_alan_HER_IKI_kapsamda_da_gizlenir() -> None:
    """🔴 KULLANICI KARARI 2026-09-19 — BOQ `finance` tutarsızlığının onarımı.

    BOQ'ta satır tutarları `quantity` (operasyonel) gizlenince türev olarak
    düşüyordu, ama `grand_total` DÜZ bir `para` alanı olduğu ve serviste maskeden
    ÖNCE hesaplandığı için GERÇEK kalıyordu. Sonuç: muhasebenin ekranında hiçbir
    satır tutara katkı vermezken altta gerçek bir genel toplam yazılıydı —
    üstelik `quantity = amount / unit_price` ile gizlenen metraj GERİ
    HESAPLANABİLİYORDU.

    Doğru model: bu değer İKİ girdiden türer (`Σ metraj × birim fiyat`), yani
    girdilerinden HERHANGİ BİRİ gizlendiğinde değer anlamını yitirir. Alan bu
    yüzden İKİ kova birden taşır ve her iki maske de onu düşürür.

    🔴 Alternatif ("iki kovadan hangisi baskın" diye tek kova seçmek) YANLIŞTI:
    hangi kovayı seçersek seçelim öteki kapsamda tutarsızlık kalırdı.
    """
    kayit = _IkiKova(ad="A Blok")

    sinirli = maskele(kayit, Scope.limited)
    assert sinirli.genel_toplam is None, "`limited` iki kovalı alanı gizlemedi"
    assert sinirli.yalniz_op == Decimal("12"), "operasyonel alan yanlışlıkla gizlendi"

    mali = maskele(kayit, Scope.finance)
    assert mali.genel_toplam is None, "`finance` iki kovalı alanı gizlemedi"
    assert mali.yalniz_para == Decimal("100"), "para alanı yanlışlıkla gizlendi"


def test_IKI_KOVALI_alan_ALL_kapsaminda_DURUR() -> None:
    """🔴 POZİTİF KONTROL — iki kova taşımak "her zaman gizli" demek DEĞİLDİR."""
    sonuc = maskele(_IkiKova(ad="A Blok"), Scope.all)

    assert sonuc.genel_toplam == Decimal("5000")
