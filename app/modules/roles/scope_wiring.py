"""ATANABİLİR kapsam kümesini KODDAN türetir (kalan iş #4, 2026-09-23 ölçümü).

## Neden bu kapı gerekiyordu

`update_role_permission` (bkz. `service.py`) iki kapıya sahipti ve ikisi de
yalnız `Scope`a (kapsama) bakıyordu, `module_key`e (modüle) HİÇ bakmıyordu:
`DROPPED_SCOPES` kontrolü ve `gizlenen_kova(scope) is None` kontrolü. Sonuç:
kapsam maskesi yalnız ALTI izin modülünde (`boq · contracts · dashboard ·
projects · sales · sites`) gerçekten KABLOLUYDU ama İzin Matrisi ekranı ve bu
kapı `limited`/`finance`i ATANABİLİR sayıyordu. Ölçüldü: `payroll` hücresine
`view/limited` KABUL ediliyordu, `payroll` routerı düz `APIRoute`ydu ve
`PayrollLineResponse` para alanlarını tam değeriyle dönüyordu — yönetici ayrı
yetki verdiğini sanıyor, ikisi de her şeyi gösteriyordu.

## Neden `roles`te yaşıyor, `app/core/**`te DEĞİL

`app/core/**` bir ÜRÜN MODÜLÜNÜ İTHAL ETMEMELİDİR — bu depoda tekrarlanan bir
kural (bkz. `field_scope.py::_gizle`, `core` `MetricPlaceholder`i bile ithal
etmez, çağırana bırakır). Bu dosyanın işi TAM TERSİ yönde çalışır: `app.modules`
ağacındaki HER routerı gezip hangi modül anahtarlarının kapsam köprüsüne
(`route_class=kapsam_rotasi(...)` + `dependencies=[kapsam_kapisi(...)]`)
GERÇEKTEN bağlı olduğunu söyler — yani ürün paketlerinin (`app.modules.boq`,
`app.modules.sites`, …) İÇİNE bakar. `core/field_scope.py` ve
`core/scoped_route.py` genel MEKANİZMAYI sağlar ve HANGİ modülün onu
kullandığını bilmez/bilmemelidir; bu sorgu (`hangi modüller GERÇEKTEN kablolu`)
yapısal olarak bir ÜRÜN sorusudur — `roles/service.py`nin izin hücrelerini
yazarken zaten sorduğu "bu modülde kısıt uygulanıyor mu" sorusunun aynısı.
`roles` paketi zaten bir ürün modülüdür (izin MATRİSİNİ yönetir, DB'den her
modülü okur); bu dosya onun doğal bir uzantısıdır.

Döngüsel içe aktarma riski YOKTUR: tarama `importlib`/`pkgutil` ile ÇALIŞMA
ANINDA yapılır (yalnız `kablolu_moduller()` ÇAĞRILDIĞINDA), bu dosyanın İÇE
AKTARILMASI anında değil. `app.modules.boq` gibi bir paket, `roles/service.py`
dolayısıyla bu dosyayı import etmiş olsa bile modül YÜKLEME sırasında hiçbir
router taraması TETİKLENMEZ.

## Neden test dosyasından TAŞINDI, KOPYALANMADI

`tests/core/test_kapsam_baglantisi.py` aynı introspeksiyonu
(`_rota_sinifi_bilgisi` + `_kapsam_kapisi_anahtari` + `_tum_routerlar`) zaten
taşıyordu. İki ayrı kopya tutmak, `kapsam_rotasi`/`kapsam_kapisi`nin iç
kapanış yapısı değiştiğinde birinin güncellenip ötekinin unutulmasına — yani bu
depoda defalarca ölçülen "iki liste bir gün ayrışır" kusurunun aynısına — yol
açardı. Test artık bu modülden import eder; ölçüm tek yerde yaşar.

## VEYA (OR) semantiği, TÜMÜ (AND) DEĞİL — kendi kendini maskelemesin diye

Bir modül anahtarı birden çok router tarafından kullanılabilir (`sales` hem
`sales/router.py`de hem `customers/router.py`de, `projects` hem
`projects/router.py`de hem `units/router.py`de). `kablolu_moduller()` bir
anahtarı yalnız TÜM kullanan routerlar doğru kurulmuşsa kabul etseydi (AND),
ikinci bir router bozulduğunda anahtar kümeden DÜŞERDİ — ve
`tests/core/test_kapsam_baglantisi.py`deki router-başına bekçi o anahtarla hiç
çalışmaz, kırık router HİÇ raporlanmazdı (kendi kendini maskeleyen bir bekçi).
Bu yüzden VEYA seçildi: bir anahtar EN AZ BİR router onu doğru kurmuşsa kümeye
girer; kardeş router bozuksa router-başına bekçi onu KENDİ başına yakalamaya
devam eder.
"""

import functools
import importlib
import pkgutil
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter

import app.modules
from app.core.scoped_route import kapsamdan_oku

__all__ = [
    "kablolu_moduller",
    "kapanis",
    "kapsam_kapisi_anahtari",
    "rota_sinifi_bilgisi",
    "tum_routerlar",
]

#: `kapsam_kapisi(...)`ın döndürdüğü bağımlılığın kapanış kimliği. Sarmalayıcı
#: `functools.wraps(cozucu)` kullandığı için `__qualname__`i ÇÖZÜCÜDEN devralır;
#: kimliği `__wrapped__` üzerinden okumak hem sarmalayıcıyı hem çözücüyü tek
#: seferde doğrular (bkz. `app.core.permissions.kapsam_kapisi`).
_KAPSAM_KAPANISI = "kapsam_kapisi.<locals>._cozucu"


def kapanis(fn: Callable[..., Any]) -> dict[str, Any]:
    """Bir kapanışın (closure) serbest değişkenleri (ad → değer).

    `strict=True`: serbest değişken adları ile hücre içerikleri BİREBİR
    eşleşmezse kapanış yapısı hakkındaki varsayımımız çürümüştür; sessizce kısa
    bir sözlük üretmek taramayı KÖR bırakırdı.
    """
    return dict(
        zip(
            fn.__code__.co_freevars,
            (c.cell_contents for c in fn.__closure__ or ()),
            strict=True,
        )
    )


def rota_sinifi_bilgisi(router: APIRouter) -> tuple[str | None, object]:
    """`kapsam_rotasi(...)` fabrikasından çıkan sınıfın (modül anahtarı, sağlayıcı)sı.

    `route_class` bu fabrikanın ürettiği `_KapsamRotasi` sınıfı DEĞİLSE
    `(None, None)` döner.
    """
    sinif = router.route_class
    if getattr(sinif, "__name__", "") != "_KapsamRotasi":
        return None, None
    bilgi = kapanis(sinif.__init__)
    return bilgi.get("modul_key"), bilgi.get("saglayici")


def kapsam_kapisi_anahtari(bagimlilik: Any) -> str | None:
    """Bu bağımlılık `kapsam_kapisi(...)` mı? Öyleyse köprünün yazdığı anahtar."""
    fn = getattr(bagimlilik, "dependency", None)
    cozucu = getattr(fn, "__wrapped__", None)
    if cozucu is None or getattr(cozucu, "__qualname__", "") != _KAPSAM_KAPANISI:
        return None
    return kapanis(cozucu).get("module_key")


def tum_routerlar() -> dict[int, tuple[str, APIRouter]]:
    """`app.modules` ağacındaki HER modül düzeyi `APIRouter` (id() → (ad, router)).

    🔴 İçe aktarma hatası YUTULMAZ: yutulsaydı yeniden adlandırılan ya da
    bozulan bir modül sessizce taranmaz ve tarama yeşil kalırdı.
    """
    hatalar: list[str] = []
    bulunan: dict[int, tuple[str, APIRouter]] = {}
    for bilgi in pkgutil.walk_packages(app.modules.__path__, "app.modules."):
        try:
            mod = importlib.import_module(bilgi.name)
        except Exception as hata:  # noqa: BLE001 — gerekçe: sessiz atlama YASAK
            hatalar.append(f"{bilgi.name}: {type(hata).__name__}: {hata}")
            continue
        for ad, obj in vars(mod).items():
            if isinstance(obj, APIRouter):
                # Aynı router birden çok modülde ithal edilmiş olabilir; kimlik
                # `id()`dir, ad değil. İlk (alfabetik) ad raporlamada kullanılır.
                tam_ad = f"{mod.__name__}.{ad}"
                mevcut = bulunan.get(id(obj))
                if mevcut is None or tam_ad < mevcut[0]:
                    bulunan[id(obj)] = (tam_ad, obj)
    assert not hatalar, f"Router taramasında içe aktarma HATASI (tarama kör kalırdı): {hatalar}"
    return bulunan


def _router_kablolu_mu(router: APIRouter) -> str | None:
    """Bu routerın KENDİ kurulumu geçerli bir kapsam köprüsü mü? Öyleyse anahtarı döner."""
    rota_anahtari, saglayici = rota_sinifi_bilgisi(router)
    if rota_anahtari is None or saglayici is not kapsamdan_oku:
        return None
    kapi_anahtarlari = {a for b in router.dependencies if (a := kapsam_kapisi_anahtari(b))}
    if rota_anahtari not in kapi_anahtarlari:
        return None
    return rota_anahtari


@functools.lru_cache(maxsize=1)
def kablolu_moduller() -> frozenset[str]:
    """Kapsam köprüsü GERÇEKTEN kurulu olan izin modülü anahtarları.

    Elle liste TUTULMAZ: `app.modules` ağacındaki HER router `route_class`ı ve
    `dependencies`i ÜZERİNDEN geçilir — bir anahtar yalnız EN AZ BİR router onu
    doğru kurmuşsa kümeye girer (gerekçesi modül docstring'inde: VEYA, TÜMÜ
    değil).

    `functools.lru_cache(maxsize=1)`: router topolojisi işlem başına SABİTTİR
    (uygulama açılışında kurulur, istek başına değişmez); her
    `update_role_permission` çağrısında `app.modules` ağacının TAMAMINI yeniden
    gezmek gereksiz bir maliyettir. Test ortamında sınıf yeniden tanımlanmaz —
    yalnız gerçek testler `kablolu_moduller.cache_clear()` çağırıp sentetik bir
    router ekleyerek mekanizmayı izole ölçmek isterse önbellek temizlenebilir.
    """
    bulunan: set[str] = set()
    for _ad, router in tum_routerlar().values():
        anahtar = _router_kablolu_mu(router)
        if anahtar is not None:
            bulunan.add(anahtar)
    return frozenset(bulunan)
