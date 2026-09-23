"""ALAN düzeyinde kapsam maskesi — `limited` ve `finance` (kullanıcı kararı 2026-09-19).

## Bu modül neyin KARDEŞİ

`core/permissions.py` iki soruyu ayırır: `require_permission` bir **UCU**
kapatır, `can_read` bir **ALANI** kapatır. Bu modül üçüncüsüdür ve alan kapısını
aktörün o modüldeki **KAPSAMINA** (`RolePermission.scope`) bağlar.

## Üç kova

| kova | `all` | `limited` | `finance` |
|---|---|---|---|
| **kimlik** (id · ad · kod · durum · tarih) | görünür | görünür | görünür |
| **para** (tutar · bedel · bütçe · birim fiyat) | görünür | **GİZLİ** | görünür |
| **operasyonel** (metraj · ilerleme · sayaç · saha notu) | görünür | görünür | **GİZLİ** |

🔴 **`kimlik` kovası kararın ÇEKİRDEĞİDİR.** `finance` birebir *"yalnız para"*
olarak uygulansaydı muhasebe projenin ADINI bile göremezdi ve her muhasebe
ekranı kullanılamaz hâle gelirdi. Sınıflandırılmamış alan **kimlik sayılır**;
gerekçesi aşağıda.

## 🔴 Neden sınıflandırılmamış alan `kimlik` (fail-OPEN) — ve bunun bekçisi

Fail-closed (bilinmeyeni gizle) daha güvenli GÖRÜNÜR ama burada YANLIŞTIR: yeni
eklenen her operasyonel alan sessizce gizlenir ve ekran, kimsenin fark etmediği
bir yerde boşalırdı — kusur KULLANICIDA, üretim kodunda görünmeden ortaya çıkar.

Güvenliği sağlayan şey varsayılan DEĞİL, **BEKÇİDİR**: `tests/core/
test_para_alani_siniflandirmasi.py` her yanıt şemasındaki her `Decimal` alanının
AÇIKÇA sınıflandırılmış olmasını ŞART KOŞAR. Yani sınıflandırılmamış bir PARA
alanı canlıya çıkamaz — testte durur. Varsayılanın işi yalnız `str`/`bool`/`id`
gibi apaçık kimlik alanlarını etiketlemekten kurtarmaktır.

## Kullanımı

    from typing import Annotated
    from app.core.field_scope import Gorunurluk

    class BoqItemResponse(BaseModel):
        code: str                                               # kimlik (etiketsiz)
        quantity: Annotated[Decimal, Gorunurluk.operasyonel]    # metraj
        unit_price: Annotated[Decimal | None, Gorunurluk.para]  # PARA

Etiket `Annotated` metadata'sındadır ve **OpenAPI'ye SIZMAZ** (ölçüldü) — yani
sınıflandırma sözleşmeyi kirletmez.

## 🔴 TÜREV alanlar ETİKETLENMEZ

`amount = quantity × unit_price` gibi `computed_field`'lar bir kolonu değil bir
FORMÜLÜ temsil eder; maske onları doğrudan yazamaz (property'dir). Bunun yerine
türev, girdisi `None` olduğunda `None` DÖNMELİDİR — böylece maske kendiliğinden
yayılır. Türev maskelenmeseydi birim fiyat gizlenirken tutar açıkta kalır ve
bölmeyle geri hesaplanabilirdi.

## 🔴 Maske MUTASYON YAPMAZ

Her zaman YENİ nesne döner. Kaynak değiştirilseydi aynı zarfı paylaşan başka bir
çağrı (önbellek, toplu üretim) sessizce maskelenmiş veri görürdü.
"""

import enum
from typing import Any

from pydantic import BaseModel

from app.core.access import Scope

__all__ = ["Gorunurluk", "gizlenen_kova", "maskele"]


class Gorunurluk(str, enum.Enum):
    """Alanın hangi kovaya düştüğü. `kimlik` VARSAYILANDIR ve etiketlenmez."""

    kimlik = "kimlik"
    para = "para"
    operasyonel = "operasyonel"


#: Kapsam → o kapsamda GİZLENEN kova. `all` hiçbir şey gizlemez.
#:
#: 🔴 `.get()` ile okunur ve bilinmeyen kapsam HİÇBİR ŞEY GİZLEMEZ. Bu bilinçli
#: bir fail-OPEN'dır: `DROPPED_SCOPES` (own/project/stock) artık yazılamaz ama
#: canlıda migration öncesi bir satır kalırsa ekran BOŞALMAMALIDIR — o hâl bir
#: veri kalıntısıdır, bir yetki kararı değil.
_GIZLENEN: dict[Scope, Gorunurluk] = {
    Scope.limited: Gorunurluk.para,
    Scope.finance: Gorunurluk.operasyonel,
}


def gizlenen_kova(kapsam: Scope) -> Gorunurluk | None:
    """Bu kapsamda hangi kova gizlenir? `None` = hiçbiri."""
    return _GIZLENEN.get(kapsam)


def _kovalar(alan: Any) -> frozenset[Gorunurluk]:
    """Alanın kovaları — etiketsiz alan KİMLİKTİR (gerekçe modül docstring'inde).

    🔴 BİR ALAN BİRDEN ÇOK KOVA TAŞIYABİLİR (kullanıcı kararı 2026-09-19).
    Bazı değerler İKİ girdiden türer: BOQ'un genel toplamı `Σ(metraj × birim
    fiyat)`tır, yani girdilerinden HERHANGİ BİRİ gizlendiğinde değer anlamını
    yitirir. Böyle bir alan `Annotated[..., Gorunurluk.para, Gorunurluk.operasyonel]`
    yazılır ve HER İKİ maske de onu düşürür.

    Tek kova seçmek YANLIŞTI: hangisini seçersek seçelim öteki kapsamda
    tutarsızlık kalırdı — muhasebenin ekranında hiçbir satır tutara katkı
    vermezken altta gerçek bir genel toplam duruyordu ve gizlenen metraj
    `tutar / birim fiyat` ile geri hesaplanabiliyordu.
    """
    kovalar = frozenset(meta for meta in alan.metadata if isinstance(meta, Gorunurluk))
    return kovalar or frozenset({Gorunurluk.kimlik})


def _deger(deger: Any, gizle: Gorunurluk) -> Any:
    """İç içe şemalara ve listelere İNER — yüzeysel maske listenin İÇİNDEKİ
    tutarı sızdırırdı (BOQ'ta grup toplamı gizlenip kalem fiyatı açıkta kalırdı)."""
    if isinstance(deger, BaseModel):
        return _maskele(deger, gizle)
    if isinstance(deger, list):
        return [_deger(oge, gizle) for oge in deger]
    if isinstance(deger, tuple):
        return tuple(_deger(oge, gizle) for oge in deger)
    if isinstance(deger, dict):
        return {anahtar: _deger(oge, gizle) for anahtar, oge in deger.items()}
    return deger


def _gizle(mevcut: Any) -> Any:
    """Gizlenen alanın YERİNE ne yazılır.

    🔴 ZARFLI alan `None`a ÇEKİLMEZ: alan zorunlu bir nesnedir ve `None` yazmak
    ŞEMAYI KIRARDI; üstelik ekran *"veri yok"* ile *"yetkin yok"*u ayırt
    edemezdi. Ürünün bu ayrım için ZATEN kanonik bir hâli var
    (`MetricPlaceholder`in ÜÇÜNCÜ hâli, kullanıcı kararı 2026-08-27) ve zarf onu
    `kisitli()` ile KENDİSİ üretir — anlam zarfın yanında kalır, bu modül onu
    yeniden icat etmez ve `core`, bir ürün modülünü İTHAL ETMEZ.
    """
    kisitli = getattr(mevcut, "kisitli", None)
    return kisitli() if callable(kisitli) else None


def _maskele[TModel: BaseModel](model: TModel, gizle: Gorunurluk) -> TModel:
    yeni: dict[str, Any] = {}
    for ad, alan in type(model).model_fields.items():
        mevcut = getattr(model, ad)
        yeni[ad] = _gizle(mevcut) if gizle in _kovalar(alan) else _deger(mevcut, gizle)
    # `model_copy` YENİ nesne üretir ve türev alanlar (`computed_field`)
    # okunduklarında YENİ girdilerden yeniden hesaplanır — maske böylece
    # türevlere kendiliğinden yayılır.
    return model.model_copy(update=yeni)


def maskele[TModel: BaseModel](model: TModel, kapsam: Scope) -> TModel:
    """`kapsam`ın gizlediği kovayı `None`a çeker; YENİ nesne döner.

    `all` (ve bilinmeyen kapsam) için de YENİ nesne döner: çağıranın bazen aynı
    bazen farklı nesne alması, sessiz bir paylaşım kusurunun tohumudur.
    """
    gizle = gizlenen_kova(kapsam)
    if gizle is None:
        return model.model_copy()
    return _maskele(model, gizle)
