"""Kapsam kısıtı OLAN her modülde para/metraj alanları AÇIKÇA sınıflandırılmalıdır.

## Bu bekçi neyi mümkün kılıyor

`core/field_scope.py` sınıflandırılmamış alanı **kimlik** sayar (fail-OPEN) ve
bunun gerekçesi o modülün docstring'indedir: fail-closed olsaydı yeni eklenen
her operasyonel alan sessizce gizlenir, ekran kimsenin fark etmediği bir yerde
boşalırdı.

Fail-open'ı güvenli kılan şey varsayılan DEĞİL **BU TESTTİR**: sınıflandırılmamış
bir `Decimal`/`MetricPlaceholder` alanı CANLIYA ÇIKAMAZ, burada durur.

## 🔴 Kapsam listesi MATRİSTEN TÜRETİLİR

Modüller elle yazılsaydı, matrise yeni bir `limited` hücresi ekleyen kişi bu
listeyi güncellemek ZORUNDA olmazdı ve o modülün para alanları bekçisiz kalırdı.
Şimdi matrise kısıt eklemek, sınıflandırmayı da ZORUNLU kılar.

## Neden `Decimal` ve `MetricPlaceholder`

İkisi de ANLAMI belirsiz olan tiplerdir: bir `Decimal` tutar da olabilir metraj
da; bir `MetricPlaceholder` bütçe de taşır ilerleme yüzdesi de. `str`/`bool`/
`uuid`/`date` alanları apaçık kimliktir ve etiketlenmeleri yalnız gürültü olurdu.
"""

import importlib
import inspect

from pydantic import BaseModel

from app.core.access import Scope
from app.core.field_scope import Gorunurluk
from app.modules.roles.seed_data import MATRIX

#: İstek (request) gövdeleri kapsam dışıdır: maske YANIT yolunda çalışır.
_ISTEK_EKI = ("Create", "Update", "Input", "Save", "Replace")

#: 🔴 ZARF SINIFLARININ KENDİSİ taranmaz. `MetricPlaceholder.value` bir kolonu
#: değil bir KABI temsil eder: aynı zarf bir yerde bütçe (para), başka yerde
#: ilerleme yüzdesi (operasyonel) taşır. Anlam KULLANIM YERİNDE belirlenir ve
#: orada etiketlenir; zarfı etiketlemek tüm kullanımları tek kovaya çökertirdi.
_ZARF_SINIFLARI = {"MetricPlaceholder", "CountPlaceholder"}

#: Modül anahtarı → şema modülleri. Çoğu 1:1'dir; `projects` ikinci bir şema
#: dosyası taşır (`land_share_schemas`) ve o da yanıt üretir.
_EK_SEMA_MODULLERI = {"projects": ("land_share_schemas",)}


def _kisitli_moduller() -> list[str]:
    """Matriste `all` OLMAYAN bir kapsam taşıyan modüller."""
    return sorted(
        modul
        for modul, hucreler in MATRIX.items()
        if any(scope is not Scope.all for _lvl, scope in hucreler)
    )


def _yanit_semalari(modul_key: str):
    adlar = ("schemas", *_EK_SEMA_MODULLERI.get(modul_key, ()))
    for alt in adlar:
        try:
            mod = importlib.import_module(f"app.modules.{modul_key}.{alt}")
        except ModuleNotFoundError:
            continue
        for ad, obj in vars(mod).items():
            if not (inspect.isclass(obj) and issubclass(obj, BaseModel)):
                continue
            if obj.__module__ != mod.__name__ or any(ek in ad for ek in _ISTEK_EKI):
                continue
            if ad in _ZARF_SINIFLARI or ad.startswith("_"):
                # 🔴 ÖZEL (alt çizgili) sınıflar taranmaz: bunlar istek
                #    gövdelerinin ortak tabanıdır (`_SaleFormFields` →
                #    `UnitSaleCreate`/`Update`). Bu bir BOŞLUK AÇMAZ: pydantic'in
                #    `model_fields`i MİRASI DA İÇERİR, yani bir yanıt şeması
                #    böyle bir tabandan para alanı miras alırsa o alan SOMUT
                #    yanıt sınıfında taranır ve yine yakalanır.
                continue
            yield f"{modul_key}.{ad}", obj


def _siniflandirma_gerektirir(annotation) -> bool:
    metin = str(annotation)
    return "Decimal" in metin or "MetricPlaceholder" in metin


def _etiketli(alan) -> bool:
    return any(isinstance(meta, Gorunurluk) for meta in alan.metadata)


def test_KISITLI_modullerde_her_para_alani_SINIFLANDIRILMISTIR() -> None:
    eksik: dict[str, list[str]] = {}
    for modul_key in _kisitli_moduller():
        for sema_adi, sema in _yanit_semalari(modul_key):
            alanlar = [
                ad
                for ad, alan in sema.model_fields.items()
                if _siniflandirma_gerektirir(alan.annotation) and not _etiketli(alan)
            ]
            if alanlar:
                eksik[sema_adi] = alanlar
    assert not eksik, (
        "Sınıflandırılmamış para/metraj alanı var — `field_scope` bunları KİMLİK "
        "sayar ve `limited` kapsamında SIZDIRIR. Her birini "
        "`Annotated[..., Gorunurluk.para]` ya da `Gorunurluk.operasyonel` ile "
        f"etiketleyin: {eksik}"
    )


def test_KISITLI_modul_listesi_BOS_DEGILDIR() -> None:
    """🔴 POZİTİF KONTROL — matris tamamen `all`a çökerse üstteki bekçi hiçbir
    şey taramadan yeşil kalırdı ve sınıflandırma disiplini sessizce ölürdü."""
    kisitli = _kisitli_moduller()
    assert kisitli, "Matriste kapsam kısıtı KALMADI — bekçi artık hiçbir şey taramıyor."
    assert len(kisitli) >= 6, f"Beklenenden az kısıtlı modül: {kisitli}"
