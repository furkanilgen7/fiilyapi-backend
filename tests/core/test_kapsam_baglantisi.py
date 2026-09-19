"""Kapsam kısıtı OLAN bir izinle korunan HER router maskeye BAĞLI olmalıdır.

## Neden ayrı bir bekçi

Maske İKİ parçadan oluşur ve ikisi de gereklidir:

1. `route_class=kapsam_rotasi(anahtar, kapsamdan_oku)` — dönen modeli maskeler,
2. `dependencies=[kapsam_kapisi(anahtar)]` — aktörün kapsamını köprüye yazar.

🔴 **Biri eksikse maske SESSİZCE `all` görür** ve hiçbir şey gizlemez. Hiçbir
test kırmızıya dönmez, çünkü yanıt "doğru" görünür — yalnız kısıt yoktur.
Bu, sahte-yeşilin tam tanımıdır.

## 🔴 Bu bekçi MODÜL ADINDAN DEĞİL, KULLANILAN İZİNDEN yürür

Önceki hâli `app.modules.<matris anahtarı>.router` yolunu deniyordu ve bu
varsayım ÜRÜNDE YANLIŞTI: izin modülü ile python paketi 1:1 DEĞİLDİR.
`units` paketi `projects` iznini (spec §8: yeni izin modülü açılmaz),
`customers` paketi `sales` iznini, `documents/link_router` dört ayrı sahibin
iznini kullanır. Hiçbiri bir matris anahtarı olmadığı için bekçi onları HİÇ
GÖRMEDİ ve `units` routerı (15 uç) aylarca maskesiz kaldı: `projects=limited`
olan rol ünite satış bedelini, maliyetini ve beklenen kârını tam gördü.

Bu yüzden tarama TERS YÖNDEN kurulur:

    her APIRouter → `require_permission` bağımlılıklarındaki izin anahtarları
                  → anahtar matriste KISITLI ise köprü ŞARTTIR

Router bulmak için `app.modules` ağacının TAMAMI `pkgutil` ile gezilir. Elle
yazılmış bir dosya haritası (eski `_ROUTER_MODULLERI`) tam da bu kusuru
üretmişti; ayrıca içe aktarma hatası artık YUTULMAZ — yutulsaydı yeniden
adlandırılan bir modül sessizce taranmamış olurdu ve bekçi yeşil kalırdı.

## 🔴 Bekçi bağımlılığın VARLIĞINA değil KİMLİĞİNE bakar

Eski hâli yalnız `if not router.dependencies:` diyordu. Kısıtlı modüllerin
routerları zaten `require_permission` taşır, yani liste ASLA boş olmaz — köprü
tamamen silinse bile bekçi geçerdi (ölçüldü). Artık üç şey ayrı ayrı çakılır:

* `kapsam_kapisi` kapanışının KENDİSİ (kapanış `functools.wraps` sayesinde
  `__wrapped__` üzerinden `kapsam_kapisi.<locals>._cozucu` diye kimliklenir) ve
  onun `module_key` serbest değişkeni — yanlış anahtarla kurulmuş köprü (örn.
  BOQ routerında `kapsam_kapisi("sales")`) yakalanır,
* `_KapsamRotasi.__init__` kapanışındaki `modul_key`,
* aynı kapanıştaki `saglayici` — `kapsamdan_oku` YERİNE sabit `Scope.all`
  döndüren bir sağlayıcı konursa maske ölür ama sınıf adı aynı kalırdı.

Kapanış okuma "içeriden" bir ölçümdür ve kırılgan görünebilir; alternatifi
(kaynak metninde `kapsam_kapisi(` aramak) DAHA kırılgandır: yorum satırındaki
bir örneği gerçek sanır, `functools.partial` ya da sarmalayıcı ile kurulmuş
gerçek bir köprüyü kaçırır ve hiçbir MUTASYONU yakalamaz. Kapanışın kimliğini
ölçmek, çalışan nesneyi ölçmektir. Bu üç mutasyonun üçünü de çakan pozitif/
negatif çift `test_bekci_EKSIK_ve_YANLIS_kopruleri_CAKAR`dadır.

## Birden çok kısıtlı izin kullanan router

`route_class` TEK kapsam anahtarı taşır; dört sahibin uçlarını tek routerda
toplayan `documents/link_router` gibi bir router tek anahtara BAĞLANAMAZ. Bu
hâlde şart değişir: böyle bir router MASKELENECEK ALAN DÖNDÜRMEMELİDİR. Bu da
elle yazılmış bir muafiyet listesi DEĞİL, ölçülen bir koşuldur — o routerın
yanıt şemalarına bir `Decimal` eklendiği gün bekçi kırmızıya döner ve mimari
karar (uç başına kapsam) o gün gerçekten zorunlu olur.
"""

import importlib
import pkgutil
from decimal import Decimal

from fastapi import APIRouter
from fastapi.routing import APIRoute
from pydantic import BaseModel

import app.modules
from app.core.access import Scope
from app.core.field_scope import Gorunurluk
from app.core.permissions import kapsam_kapisi, require_permission
from app.core.scoped_route import kapsam_rotasi, kapsamdan_oku
from app.modules.roles.seed_data import MATRIX

#: Kapanış kimlikleri. `require_permission`/`kapsam_kapisi` iç fonksiyon
#: döndürür; `__qualname__` o fabrikadan çıktığının kanıtıdır.
_IZIN_KAPANISI = "require_permission.<locals>._check"
_KAPSAM_KAPANISI = "kapsam_kapisi.<locals>._cozucu"


def _kisitli_moduller() -> set[str]:
    """Matriste `all` OLMAYAN bir kapsam taşıyan izin modülleri."""
    return {
        modul
        for modul, hucreler in MATRIX.items()
        if any(scope is not Scope.all for _lvl, scope in hucreler)
    }


def _kapanis(fn) -> dict:
    """Bir kapanışın serbest değişkenleri (ad → değer)."""
    # `strict=True`: serbest değişken adları ile hücreler BİREBİR eşleşir;
    # eşleşmiyorsa kapanış yapısı hakkındaki varsayımımız çürümüştür ve
    # sessizce kısa bir sözlük üretmek bekçiyi KÖR bırakırdı.
    return dict(
        zip(
            fn.__code__.co_freevars,
            (c.cell_contents for c in fn.__closure__ or ()),
            strict=True,
        )
    )


def _izin_anahtari(bagimlilik) -> str | None:
    """Bu bağımlılık `require_permission(...)` mı? Öyleyse izin modülü anahtarı."""
    fn = getattr(bagimlilik, "dependency", None)
    if getattr(fn, "__qualname__", "") != _IZIN_KAPANISI:
        return None
    return _kapanis(fn).get("module_key")


def _kapsam_kapisi_anahtari(bagimlilik) -> str | None:
    """Bu bağımlılık `kapsam_kapisi(...)` mı? Öyleyse köprünün yazdığı anahtar.

    `kapsam_bagimligi_kur` `functools.wraps(cozucu)` kullandığı için sarmalayıcı
    `__qualname__`i ÇÖZÜCÜDEN devralır; kimliği `__wrapped__` üzerinden okumak
    hem sarmalayıcıyı hem çözücüyü tek seferde doğrular.
    """
    fn = getattr(bagimlilik, "dependency", None)
    cozucu = getattr(fn, "__wrapped__", None)
    if cozucu is None or getattr(cozucu, "__qualname__", "") != _KAPSAM_KAPANISI:
        return None
    return _kapanis(cozucu).get("module_key")


def _kullanilan_izinler(router: APIRouter) -> set[str]:
    """Routerın (router düzeyi + uç düzeyi) `require_permission` anahtarları."""
    bagimliliklar = list(router.dependencies)
    for rota in router.routes:
        if isinstance(rota, APIRoute):
            bagimliliklar.extend(rota.dependencies)
    return {anahtar for b in bagimliliklar if (anahtar := _izin_anahtari(b))}


def _rota_sinifi_bilgisi(router: APIRouter) -> tuple[str | None, object]:
    """`kapsam_rotasi` fabrikasından çıkan sınıfın (modül anahtarı, sağlayıcı)sı."""
    sinif = router.route_class
    if getattr(sinif, "__name__", "") != "_KapsamRotasi":
        return None, None
    kapanis = _kapanis(sinif.__init__)
    return kapanis.get("modul_key"), kapanis.get("saglayici")


def _siniflandirma_gerektirir(annotation) -> bool:
    """Anlamı belirsiz — yani maskelenebilir — bir tip mi?

    `tests/core/test_para_alani_siniflandirmasi.py`deki kardeşinin aynı ölçütü;
    KOPYA BİLİNÇLİDİR: iki bekçi birbirinin özel yardımcısını ithal etseydi biri
    yeniden yazıldığında öteki sessizce ölürdü.
    """
    metin = str(annotation)
    return "Decimal" in metin or "Placeholder" in metin


def _etiketli(alan) -> bool:
    return any(isinstance(meta, Gorunurluk) for meta in getattr(alan, "metadata", ()))


def _maskelenecek_alanlar(sema: type[BaseModel], gorulen: set[type] | None = None) -> list[str]:
    """Şema ağacındaki maskelenebilir alanlar (`Schema.alan` biçiminde).

    İÇ İÇE İNER: `maskele()` de iner ve yüzeysel bakan bir ölçüm
    `UnitListResponse` gibi tamamı sarmalanmış bir zarfı "para yok" sanardı.
    """
    gorulen = set() if gorulen is None else gorulen
    if sema in gorulen:
        return []
    gorulen.add(sema)
    bulunan: list[str] = []
    for ad, alan in sema.model_fields.items():
        if _siniflandirma_gerektirir(alan.annotation) or _etiketli(alan):
            bulunan.append(f"{sema.__name__}.{ad}")
        for ic in _ic_semalar(alan.annotation):
            bulunan.extend(_maskelenecek_alanlar(ic, gorulen))
    for ad, alan in sema.model_computed_fields.items():
        if _siniflandirma_gerektirir(alan.return_type):
            bulunan.append(f"{sema.__name__}.{ad}")
    return bulunan


def _ic_semalar(annotation) -> list[type[BaseModel]]:
    """Bir tip ifadesinin İÇİNDEKİ pydantic şemaları (list[X], X | None, dict[...])."""
    bulunan: list[type[BaseModel]] = []
    yigin = [annotation]
    while yigin:
        tip = yigin.pop()
        if isinstance(tip, type) and issubclass(tip, BaseModel):
            bulunan.append(tip)
            continue
        yigin.extend(getattr(tip, "__args__", ()))
    return bulunan


def _router_yanit_semalari(router: APIRouter) -> list[type[BaseModel]]:
    semalar = []
    for rota in router.routes:
        model = getattr(rota, "response_model", None)
        if isinstance(model, type) and issubclass(model, BaseModel):
            semalar.append(model)
    return semalar


def _kopru_sorunlari(router: APIRouter, kisitli: set[str]) -> list[str]:
    """Bu router maskeye BAĞLI MI? Bağlı değilse okunur gerekçe listesi.

    Testlerin ölçtüğü ASIL birim budur: üretimdeki routerlara da, sentetik
    mutantlara da AYNI fonksiyon uygulanır (bkz. pozitif/negatif çift).
    """
    izinler = _kullanilan_izinler(router) & kisitli
    if not izinler:
        return []

    if len(izinler) > 1:
        # Tek `route_class` tek anahtar taşır — bu router bağlanamaz. Şart
        # değişir: maskelenecek alan DÖNDÜRMEMELİDİR (gerekçe modül docstring'i).
        sizan = sorted(
            {a for s in _router_yanit_semalari(router) for a in _maskelenecek_alanlar(s)}
        )
        if sizan:
            return [
                f"birden çok KISITLI izin kullanıyor {sorted(izinler)} — tek kapsam "
                f"anahtarına bağlanamaz, ama maskelenecek alan DÖNDÜRÜYOR: {sizan}"
            ]
        return []

    (anahtar,) = izinler
    sorunlar: list[str] = []

    rota_anahtari, saglayici = _rota_sinifi_bilgisi(router)
    if rota_anahtari is None:
        sorunlar.append(f"route_class=kapsam_rotasi({anahtar!r}, kapsamdan_oku) YOK")
    else:
        if rota_anahtari != anahtar:
            sorunlar.append(
                f"route_class YANLIS anahtarla kurulmus: {rota_anahtari!r} (beklenen {anahtar!r})"
            )
        if saglayici is not kapsamdan_oku:
            sorunlar.append(
                f"route_class saglayicisi `kapsamdan_oku` DEGIL ({saglayici!r}) — "
                "kopru okunmuyor, maske sabit bir kapsam goruyor"
            )

    kapi_anahtarlari = {a for b in router.dependencies if (a := _kapsam_kapisi_anahtari(b))}
    if not kapi_anahtarlari:
        sorunlar.append(f"dependencies=[kapsam_kapisi({anahtar!r})] YOK")
    elif kapi_anahtarlari != {anahtar}:
        sorunlar.append(
            f"kapsam_kapisi YANLIS anahtarla kurulmus: {sorted(kapi_anahtarlari)} "
            f"(beklenen {anahtar!r})"
        )
    return sorunlar


def _tum_routerlar() -> dict[int, tuple[str, APIRouter]]:
    """`app.modules` ağacındaki HER modül düzeyi `APIRouter`.

    🔴 İçe aktarma hatası YUTULMAZ: yutulsaydı yeniden adlandırılan ya da
    bozulan bir modül sessizce taranmaz ve bekçi yeşil kalırdı.
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
    assert not hatalar, f"Router taramasında içe aktarma HATASI (bekçi kör kalırdı): {hatalar}"
    return bulunan


def test_KISITLI_izinle_korunan_her_router_MASKEYE_BAGLIDIR() -> None:
    kisitli = _kisitli_moduller()
    eksik: dict[str, list[str]] = {}
    for ad, router in sorted(_tum_routerlar().values()):
        sorunlar = _kopru_sorunlari(router, kisitli)
        if sorunlar:
            eksik[ad] = sorunlar
    assert not eksik, (
        "Kapsam kısıtı OLAN bir izinle korunan router maskeye bağlı DEĞİL — maske "
        f"sessizce `all` görür ve hiçbir şey gizlemez: {eksik}"
    )


def test_bekci_IZIN_ANAHTARINDAN_yurur_MODUL_ADINDAN_degil() -> None:
    """🔴 POZİTİF KONTROL — bekçinin kör noktasının KENDİSİNİ ölçer.

    Bekçi router dosyalarını `app.modules.<matris anahtarı>.router` diye arasaydı
    yeşil kalır ama `units`/`customers` gibi BAŞKA pakette yaşayıp kısıtlı bir
    iznin arkasına saklanan routerları hiç görmezdi. Bu test taramanın gerçekten
    böyle bir routerı bulduğunu ve onun köprüyü kurduğunu çakar; tarama yeniden
    ad tabanlı hâle getirilirse burası kırmızıya döner.
    """
    kisitli = _kisitli_moduller()
    yabanci = {
        ad: izinler
        for ad, router in _tum_routerlar().values()
        if (izinler := _kullanilan_izinler(router) & kisitli)
        and not any(ad.startswith(f"app.modules.{izin}.") for izin in izinler)
    }
    assert yabanci, (
        "Kendi paketi DIŞINDAKİ bir izne bağlı hiç router bulunamadı — tarama "
        "büyük olasılıkla yine modül ADINDAN yürüyor ve kör."
    )
    assert "app.modules.units.router.router" in yabanci, (
        f"`units` routerı (izin modülü `projects`) taramada YOK: {sorted(yabanci)}"
    )


def test_bekci_EKSIK_ve_YANLIS_kopruleri_CAKAR() -> None:
    """🔴 POZİTİF/NEGATİF ÇİFT — bekçinin kendisini mutasyonla ölçer.

    Dört mutantın dördü de eski bekçiden GEÇİYORDU (ölçüldü). Pozitif kontrol
    olmasaydı "her routerı reddet" hâli de yeşil kalırdı; bu yüzden DOĞRU kurulmuş
    router da aynı fonksiyondan geçirilir ve SIFIR sorun vermesi şart koşulur.
    """
    from app.core.access import AccessLevel

    kisitli = {"boq"}
    izin = require_permission("boq", AccessLevel.view)

    def _router(**kwargs) -> APIRouter:
        r = APIRouter(dependencies=[izin, *kwargs.pop("ekstra", ())], **kwargs)

        @r.get("/x")
        async def _uc() -> None: ...

        return r

    dogru = _router(route_class=kapsam_rotasi("boq", kapsamdan_oku), ekstra=[kapsam_kapisi("boq")])
    assert _kopru_sorunlari(dogru, kisitli) == [], "POZİTİF KONTROL: doğru router reddedildi"

    # MUT-1 — köprü bağımlılığı silinmiş; `dependencies` yine de BOŞ DEĞİL.
    mut1 = _router(route_class=kapsam_rotasi("boq", kapsamdan_oku))
    assert _kopru_sorunlari(mut1, kisitli), "MUT-1 (kapsam_kapisi YOK) yakalanmadı"

    # MUT-2 — köprü YANLIŞ anahtarla kurulmuş: aktörün `sales` kapsamı okunur,
    # `boq` kapsamı hiç sorulmaz.
    mut2 = _router(route_class=kapsam_rotasi("boq", kapsamdan_oku), ekstra=[kapsam_kapisi("sales")])
    assert _kopru_sorunlari(mut2, kisitli), "MUT-2 (yanlış anahtar) yakalanmadı"

    # MUT-3 — sağlayıcı sabitlenmiş: sınıf adı aynı, maske ÖLÜ.
    mut3 = _router(
        route_class=kapsam_rotasi("boq", lambda *a, **k: Scope.all),
        ekstra=[kapsam_kapisi("boq")],
    )
    assert _kopru_sorunlari(mut3, kisitli), "MUT-3 (sağlayıcı sabitlenmiş) yakalanmadı"

    # MUT-4 — rota sınıfı hiç kurulmamış.
    mut4 = _router(ekstra=[kapsam_kapisi("boq")])
    assert _kopru_sorunlari(mut4, kisitli), "MUT-4 (route_class YOK) yakalanmadı"

    # MUT-5 — rota sınıfı BAŞKA modülün anahtarıyla kurulmuş.
    mut5 = _router(route_class=kapsam_rotasi("sales", kapsamdan_oku), ekstra=[kapsam_kapisi("boq")])
    assert _kopru_sorunlari(mut5, kisitli), "MUT-5 (route_class yanlış anahtar) yakalanmadı"


def test_COK_ANAHTARLI_router_maskelenecek_alan_DONDURMEZ() -> None:
    """🔴 POZİTİF/NEGATİF ÇİFT — çok anahtarlı routerın şartını ölçer.

    Tek `route_class` tek anahtar taşır; dört sahibin uçlarını toplayan bir
    router bağlanamaz. Muafiyet ELLE YAZILMAZ: koşul "maskelenecek alan
    döndürmemek"tir ve bir `Decimal` eklendiği gün kırmızıya döner.
    """
    from app.core.access import AccessLevel

    kisitli = {"boq", "sales"}

    class Kimlik(BaseModel):
        ad: str

    class Para(BaseModel):
        tutar: Decimal

    def _cok_anahtarli(model: type[BaseModel]) -> APIRouter:
        r = APIRouter()

        _boq = require_permission("boq", AccessLevel.view)
        _sales = require_permission("sales", AccessLevel.view)

        @r.get("/a", response_model=model, dependencies=[_boq])
        async def _a() -> None: ...

        @r.get("/b", response_model=model, dependencies=[_sales])
        async def _b() -> None: ...

        return r

    assert _kopru_sorunlari(_cok_anahtarli(Kimlik), kisitli) == [], (
        "POZİTİF KONTROL: maskelenecek alanı OLMAYAN çok anahtarlı router reddedildi"
    )
    assert _kopru_sorunlari(_cok_anahtarli(Para), kisitli), (
        "Çok anahtarlı router bir PARA alanı döndürüyor ama bekçi geçirdi"
    )


def test_KISITLI_modul_listesi_BOS_DEGILDIR() -> None:
    """🔴 POZİTİF KONTROL — matris tamamen `all`a çökerse üstteki bekçiler hiçbir
    şey taramadan yeşil kalır ve kapsam disiplini sessizce ölürdü."""
    kisitli = _kisitli_moduller()
    assert len(kisitli) >= 6, f"Beklenenden az kısıtlı modül: {sorted(kisitli)}"


def test_router_taramasi_BOS_DEGILDIR() -> None:
    """🔴 POZİTİF KONTROL — `pkgutil` hiçbir şey bulamazsa (paket yolu değişir,
    içe aktarma kırılır) ana bekçi sıfır router gezip yeşil kalırdı."""
    routerlar = _tum_routerlar()
    assert len(routerlar) >= 20, f"Tarama yalnız {len(routerlar)} router buldu — kör olabilir"
    kisitli = _kisitli_moduller()
    korunan = [ad for ad, r in routerlar.values() if _kullanilan_izinler(r) & kisitli]
    assert len(korunan) >= 8, f"Kısıtlı izinle korunan router sayısı şüpheli az: {korunan}"
