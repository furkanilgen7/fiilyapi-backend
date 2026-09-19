"""Kapsam kısıtı OLAN her modülün routerı maskeye BAĞLI olmalıdır.

## Neden ayrı bir bekçi

Maske İKİ parçadan oluşur ve ikisi de gereklidir:

1. `route_class=kapsam_rotasi(...)` — dönen modeli maskeler,
2. `dependencies=[kapsam_kapisi(...)]` — aktörün kapsamını köprüye yazar.

🔴 **Biri eksikse maske SESSİZCE `all` görür** ve hiçbir şey gizlemez. Hiçbir
test kırmızıya dönmez, çünkü yanıt "doğru" görünür — yalnız kısıt yoktur.
Bu, sahte-yeşilin tam tanımıdır.

## 🔴 Modül listesi MATRİSTEN türetilir

Elle yazılsaydı, matrise `limited` ekleyen kişi bu listeyi güncellemek zorunda
olmaz ve o modül bekçisiz kalırdı.
"""

import importlib

from fastapi import APIRouter

from app.core.access import Scope
from app.core.scoped_route import kapsam_rotasi
from app.modules.roles.seed_data import MATRIX

#: Modül anahtarı → router nesnelerini taşıyan modüller. Bir modülün birden çok
#: routerı olabilir (`projects` ayrıca `employers_router` taşır) ve HEPSİ
#: bağlanmalıdır: bağlanmamış bir router maskesiz bir kapıdır.
_ROUTER_MODULLERI = {
    "projects": ("router",),
    "sites": ("router", "flat_list_router"),
}


def _kisitli_moduller() -> list[str]:
    return sorted(
        modul
        for modul, hucreler in MATRIX.items()
        if any(scope is not Scope.all for _lvl, scope in hucreler)
    )


def _routerlar(modul_key: str):
    for alt in _ROUTER_MODULLERI.get(modul_key, ("router",)):
        try:
            mod = importlib.import_module(f"app.modules.{modul_key}.{alt}")
        except ModuleNotFoundError:
            continue
        for ad, obj in vars(mod).items():
            if isinstance(obj, APIRouter):
                yield f"{modul_key}.{alt}.{ad}", obj


def _maskeli_rota_sinifi(router: APIRouter) -> bool:
    """Rota sınıfı `kapsam_rotasi` fabrikasından mı çıktı?"""
    return getattr(router.route_class, "__name__", "") == "_KapsamRotasi"


def test_KISITLI_modullerin_routerlari_MASKEYE_BAGLIDIR() -> None:
    eksik: dict[str, list[str]] = {}
    for modul_key in _kisitli_moduller():
        for ad, router in _routerlar(modul_key):
            sorunlar = []
            if not _maskeli_rota_sinifi(router):
                sorunlar.append("route_class=kapsam_rotasi(...) YOK")
            if not router.dependencies:
                sorunlar.append("dependencies=[kapsam_kapisi(...)] YOK")
            if sorunlar:
                eksik[ad] = sorunlar
    assert not eksik, (
        "Kapsam kısıtı olan modülün routerı maskeye bağlı DEĞİL — maske sessizce "
        f"`all` görür ve hiçbir şey gizlemez: {eksik}"
    )


def test_kapsam_rotasi_fabrikasi_TANINABILIR_sinif_uretir() -> None:
    """🔴 POZİTİF KONTROL — üstteki bekçi sınıf adını tanıyarak çalışır; fabrika
    adı değişirse bekçi HER routerı 'bağlı' sanıp sessizce ölürdü."""
    from app.core.scoped_route import kapsamdan_oku

    assert _maskeli_rota_sinifi(APIRouter(route_class=kapsam_rotasi("x", kapsamdan_oku)))
    assert not _maskeli_rota_sinifi(APIRouter())
