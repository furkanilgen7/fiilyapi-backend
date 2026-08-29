"""AI-0a T2 bekçileri — okuma düzlemi (`build_read_plane`).

B1 (GET KÜME eşitliği) · B2 (handler KÜME eşitliği + alan istisnası) · B5
(`get_current_user` override EDİLMEMİŞ).

🔴 **Hiçbir bekçi SAYI kilitlemez.** "140 GET" bir ölçümdür, bir ölçüt değildir:
yeni bir GET eklendiğinde sayı bekçisi kırmızı olur ve şef onu "güncelleme
ritüeliyle" yeşile çevirir — hiçbir şey bekçilenmemiş olur. Küme eşitliği ise
yeni GET'i kendiliğinden iki tarafa da yazar ve YALNIZ gerçek ayrışmada konuşur.
"""

from typing import Annotated

import httpx
import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.routing import APIRoute, iter_route_contexts
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.errors import NotFoundError, PermissionLockedError
from app.main import app
from app.modules.ai.db import ai_engine, get_ai_readonly_db
from app.modules.ai.readplane import build_read_plane

# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------


def _operasyon_kumesi(uygulama: FastAPI) -> set[tuple[str, str]]:
    """Uygulamanın `APIRoute` operasyonları: {(metot, etkin yol)}.

    🔴 `iter_route_contexts` ŞART. `[r for r in app.routes if isinstance(r, APIRoute)]`
    pinli fastapi 0.141.1'de **1** döndürür (yalnız satır-içi `/health`) çünkü
    include edilen router'lar `_IncludedRouter` ara katmanında tembel durur. O naif
    sayımla kurulan her iddia sessizce yanlış olur.
    """
    kume: set[tuple[str, str]] = set()
    for baglam in iter_route_contexts(uygulama.routes):
        if isinstance(baglam.original_route, APIRoute):
            for metot in baglam.methods or set():
                kume.add((metot, baglam.path))
    return kume


def _get_kumesi(uygulama: FastAPI) -> set[tuple[str, str]]:
    return {(m, y) for m, y in _operasyon_kumesi(uygulama) if m in {"GET", "HEAD"}}


# ---------------------------------------------------------------------------
# B1 — GET KÜMESİ eşitliği
# ---------------------------------------------------------------------------


def test_B1_okuma_duzlemi_operasyon_kumesi_ana_appin_GET_kumesine_ESITTIR() -> None:
    duzlem = build_read_plane(app)
    assert _operasyon_kumesi(duzlem) == _get_kumesi(app)


def test_B1_pozitif_kontrol_saglam_kume_BOS_DEGIL_ve_health_ICINDE() -> None:
    """Boş küme == boş küme de bir eşitliktir; testin anlamlı olduğunu kanıtlar.

    `/health` özellikle aranır: `main.py`de satır-içi tanımlıdır ve `ROUTERS`ta
    YOKTUR. Okuma düzlemi registry'den türetilseydi burada sessizce kaybolurdu —
    bu satır o tasarım hatasını yakalayan tek satırdır.
    """
    duzlem = build_read_plane(app)
    kume = _operasyon_kumesi(duzlem)
    assert len(kume) > 100
    assert ("GET", "/health") in kume


def test_B1_yazma_operasyonlari_okuma_dulzeminde_VAR_OLMAZ() -> None:
    """Reddedilmezler — hiç bulunmazlar. Kapı D'nin rota tarafı."""
    duzlem = build_read_plane(app)
    yazma = {(m, y) for m, y in _operasyon_kumesi(duzlem) if m not in {"GET", "HEAD"}}
    assert yazma == set()
    # Pozitif kontrol: ana app'te bu yazma uçları GERÇEKTEN var (aksi hâlde
    # yukarıdaki boş küme hiçbir şey kanıtlamazdı).
    assert ("POST", "/projects") in _operasyon_kumesi(app)


async def test_B1_yazma_metodu_405_doner_403_DEGIL() -> None:
    """Gövde okunmadan, kimlik sorulmadan reddedilir: rota yok, metot yok."""
    duzlem = build_read_plane(app)
    tasima = httpx.ASGITransport(app=duzlem, raise_app_exceptions=True)
    async with httpx.AsyncClient(transport=tasima, base_url="http://okuma") as istemci:
        yanit = await istemci.post("/projects", json={"kod": "X"})
        assert yanit.status_code == 405
        # Pozitif kontrol: aynı yolun GET'i vardır (405 "yol yok"tan gelmiyor).
        assert (await istemci.get("/projects")).status_code == 401


def test_B1_mutasyon_bir_router_dusurulurse_KUME_AYRISIR() -> None:
    """Mutasyon testin içinde: eksik router'la kurulmuş bir app'in okuma düzlemi
    ana app'in GET kümesine eşit OLMAMALI. Bu, B1'in eşdeğer olmadığının kanıtı."""
    from app.core.router_registry import ROUTERS
    from app.modules.personnel.document_type_router import router as dusurulen

    eksik_app = FastAPI()
    for router in ROUTERS:
        if router is dusurulen:
            continue
        eksik_app.include_router(router)
    assert _operasyon_kumesi(build_read_plane(eksik_app)) != _get_kumesi(app)


# ---------------------------------------------------------------------------
# B2 — istisna handler KÜMESİ (S28: 29 vs 3)
# ---------------------------------------------------------------------------


def test_B2_handler_KUMESI_ana_app_ile_ESITTIR() -> None:
    duzlem = build_read_plane(app)
    assert set(duzlem.exception_handlers) == set(app.exception_handlers)


def test_B2_pozitif_kontrol_ciplak_FastAPI_kumesi_EKSIKTIR() -> None:
    """Ölçülmüş olgu: `include_router` handler TAŞIMAZ.

    Çıplak bir `FastAPI()` ile ana app arasındaki fark gerçekten büyükse
    yukarıdaki eşitlik anlamlıdır; fark sıfır olsaydı test hiçbir şey
    bekçilemiyor olurdu.
    """
    ciplak = set(FastAPI().exception_handlers)
    assert len(set(app.exception_handlers) - ciplak) >= 20
    assert NotFoundError in set(app.exception_handlers)
    assert NotFoundError not in ciplak


async def test_B2_alan_istisnasi_okuma_dulzeminde_DOGRU_KODU_doner() -> None:
    """`NotFoundError` 404, `PermissionLockedError` kendi kodu — 500 DEĞİL.

    Handler'lar kaydedilmezse `ASGITransport(raise_app_exceptions=True)` altında
    istisna executor'a fırlar: ekran "kayıt bulunamadı" derken AI "sistem hatası"
    der. Sonda `raise_app_exceptions=True` bilerek: yutulan bir istisna testi
    sessizce geçiremesin.
    """
    duzlem = build_read_plane(app)
    sonda = APIRouter()

    @sonda.get("/_sonda/bulunamadi")
    async def _bulunamadi() -> dict:
        raise NotFoundError("kayıt bulunamadı")

    @sonda.get("/_sonda/kilitli")
    async def _kilitli() -> dict:
        raise PermissionLockedError("kilitli")

    duzlem.include_router(sonda)

    tasima = httpx.ASGITransport(app=duzlem, raise_app_exceptions=True)
    async with httpx.AsyncClient(transport=tasima, base_url="http://okuma") as istemci:
        bulunamadi = await istemci.get("/_sonda/bulunamadi")
        assert bulunamadi.status_code == 404, bulunamadi.text
        assert bulunamadi.json()["detail"] == "kayıt bulunamadı"
        kilitli = await istemci.get("/_sonda/kilitli")
        assert kilitli.status_code == 403, kilitli.text


async def test_B2_mutasyon_handler_kaydedilmezse_istisna_FIRLAR() -> None:
    """`register_exception_handlers(read_plane)` satırı silinseydi ne olurdu.

    Aynı sondayı handler'sız bir uygulamada koşuyoruz: 404 yerine ham istisna
    gelir. Bu, B2'nin eşdeğer mutant taşımadığının kanıtıdır.
    """
    handlersiz = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    sonda = APIRouter()

    @sonda.get("/_sonda/bulunamadi")
    async def _bulunamadi() -> dict:
        raise NotFoundError("kayıt bulunamadı")

    handlersiz.include_router(sonda)
    tasima = httpx.ASGITransport(app=handlersiz, raise_app_exceptions=True)
    async with httpx.AsyncClient(transport=tasima, base_url="http://okuma") as istemci:
        with pytest.raises(NotFoundError):
            await istemci.get("/_sonda/bulunamadi")


def test_B2_limiter_ve_middleware_PARITESI() -> None:
    duzlem = build_read_plane(app)
    assert duzlem.state.limiter is app.state.limiter
    assert [m.cls for m in duzlem.user_middleware] == [m.cls for m in app.user_middleware]


# ---------------------------------------------------------------------------
# B5 — `get_current_user` override EDİLMEMİŞ
# ---------------------------------------------------------------------------


def test_B5_dependency_overrides_TAM_OLARAK_get_db_TEKIDIR() -> None:
    """🔴 `get_current_user` override EDİLMEZ — AI'ın kendi kimliği YOKTUR (K1/T1).

    Sözlüğün tamamı iddia edilir, yalnız `get_current_user`ın yokluğu değil:
    buraya sızacak HERHANGİ bir override (örn. bir izin bağımlılığı) yetki
    modelini sessizce deler.
    """
    duzlem = build_read_plane(app)
    assert duzlem.dependency_overrides == {get_db: get_ai_readonly_db}
    assert get_current_user not in duzlem.dependency_overrides


async def test_B5_pozitif_kontrol_kimliksiz_istek_401_alir() -> None:
    """Kimlik kapısı okuma düzleminde GERÇEKTEN koşuyor.

    `get_current_user` override edilseydi bu 200 olurdu; sözlük iddiası yapısal,
    bu ise davranışsal kanıttır.
    """
    duzlem = build_read_plane(app)
    tasima = httpx.ASGITransport(app=duzlem, raise_app_exceptions=True)
    async with httpx.AsyncClient(transport=tasima, base_url="http://okuma") as istemci:
        assert (await istemci.get("/projects")).status_code == 401
        assert (await istemci.get("/auth/me")).status_code == 401
        # …ama kapısız uç çalışıyor: 401 "her şey kırık"tan gelmiyor.
        saglik = await istemci.get("/health")
        assert saglik.status_code == 200 and saglik.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# B4 — `ai_engine` ≠ ana engine, iddia REQUEST'İN İÇİNDEN kurulur
# ---------------------------------------------------------------------------


async def test_B4_get_db_okuma_dulzeminde_SALT_OKUNUR_motora_cozulur() -> None:
    """🔴 Beş sessiz varyantın hepsini bir arada öldüren tek ölçüm.

    İddia modül düzeyinde (`ai_engine is not engine`) DEĞİL, **isteğin içinden**
    kurulur: `dependency_overrides` yanlış monte edilmiş bir düzlemde 200 döner,
    uç çalışır, hata çıkmaz — ama session ANA (yazılabilir) havuzdan gelir. Farkı
    yalnız `session.bind` kimliği gösterir.

    Sonda hiç SQL koşmaz: `AsyncSession` bağlanmadan da `bind`ını bilir, bu yüzden
    test DB bağlantısı açmaz ve xdist işçi veritabanına dokunmaz.
    """
    from app.core.db import engine as ana_engine

    duzlem = build_read_plane(app)
    sonda = APIRouter()

    @sonda.get("/_sonda/bind")
    async def _bind(session: Annotated[AsyncSession, Depends(get_db)]) -> dict:
        return {"bind": id(session.bind)}

    duzlem.include_router(sonda)
    tasima = httpx.ASGITransport(app=duzlem, raise_app_exceptions=True)
    async with httpx.AsyncClient(transport=tasima, base_url="http://okuma") as istemci:
        yanit = await istemci.get("/_sonda/bind")
    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["bind"] == id(ai_engine), (
        "Okuma düzlemi ANA motoru kullanıyor — `dependency_overrides` sessizce "
        "etkisiz. Bkz. readplane.py §2 (beş sessiz varyant)."
    )
    assert ai_engine is not ana_engine


async def test_B4_mutasyon_rota_nesnesi_KOPYALANIRSA_override_SESSIZCE_dusuyor() -> None:
    """Beş sessiz varyantın her birini ayrı ayrı koşar ve hepsinin ETKİSİZ
    olduğunu kanıtlar. Biri "etkili" çıkarsa readplane.py'nin gerekçesi çürümüştür
    ve tasarım yeniden ölçülmelidir.

    ⚠️ Varyantların hiçbiri hata vermez, hiçbiri 404 dönmez: 200 döner ve
    bağımlılığı ANA app'ten çözer. Sessizliğin kendisi ölçülüyor.
    """
    import copy

    def dep_ana() -> str:
        return "ANA"

    kaynak_router = APIRouter()

    @kaynak_router.get("/_sonda/ov")
    def _ov(deger: Annotated[str, Depends(dep_ana)]) -> dict:
        return {"deger": deger}

    def kaynak_app() -> FastAPI:
        a = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
        a.include_router(kaynak_router)
        return a

    def v_ham_extend(ana: FastAPI, alt: FastAPI) -> None:
        alt.router.routes.extend(ana.routes)

    def v_copy_extend(ana: FastAPI, alt: FastAPI) -> None:
        alt.router.routes.extend([copy.copy(r) for r in ana.routes])

    def v_atama(ana: FastAPI, alt: FastAPI) -> None:
        alt.router.routes = list(ana.routes)

    def v_orijinal_append(ana: FastAPI, alt: FastAPI) -> None:
        for baglam in iter_route_contexts(ana.routes):
            if isinstance(baglam.original_route, APIRoute):
                alt.router.routes.append(baglam.original_route)

    def v_copy_append(ana: FastAPI, alt: FastAPI) -> None:
        for baglam in iter_route_contexts(ana.routes):
            if isinstance(baglam.original_route, APIRoute):
                alt.router.routes.append(copy.copy(baglam.original_route))

    def e_include(ana: FastAPI, alt: FastAPI) -> None:
        taze = APIRouter()
        for baglam in iter_route_contexts(ana.routes):
            rota = baglam.original_route
            if isinstance(rota, APIRoute) and (baglam.methods or set()) <= {"GET", "HEAD"}:
                taze.routes.append(rota)
        alt.include_router(taze)

    async def cagir(alt: FastAPI) -> str:
        tasima = httpx.ASGITransport(app=alt, raise_app_exceptions=True)
        async with httpx.AsyncClient(transport=tasima, base_url="http://t") as istemci:
            yanit = await istemci.get("/_sonda/ov")
            assert yanit.status_code == 200, yanit.text
            return yanit.json()["deger"]

    sessiz_varyantlar = {
        "ham _IncludedRouter extend": v_ham_extend,
        "copy.copy(_IncludedRouter) extend": v_copy_extend,
        "routes = list(...) atama": v_atama,
        "orijinal APIRoute append": v_orijinal_append,
        "copy.copy(APIRoute) append": v_copy_append,
    }
    for ad, kur in sessiz_varyantlar.items():
        alt = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
        alt.dependency_overrides[dep_ana] = lambda: "OVERRIDE"
        kur(kaynak_app(), alt)
        assert await cagir(alt) == "ANA", (
            f"{ad}: override BEKLENMEDİK ŞEKİLDE etkili oldu — readplane.py §2'deki "
            "ölçüm çürüdü, tasarım gerekçesi yeniden yazılmalı."
        )

    # Pozitif kontrol: seçilen tasarım (`include_router`) override'ı ETKİLİ kılar.
    alt = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    alt.dependency_overrides[dep_ana] = lambda: "OVERRIDE"
    e_include(kaynak_app(), alt)
    assert await cagir(alt) == "OVERRIDE"


# ---------------------------------------------------------------------------
# Yapısal kör nokta bekçileri (readplane.py §3 ve §5)
# ---------------------------------------------------------------------------


def test_dusuk_oncelikli_rota_listesi_BOS_olmali() -> None:
    """🔴 `iter_route_contexts` `_low_priority_routes`u KAPSAMAZ.

    Bugün 41 router'ın hepsinde boş. Dolarsa oradaki GET'ler okuma düzleminde
    SESSİZCE kaybolurdu; `build_read_plane` bu yüzden patlar ve bu test o
    patlamanın bugün gerekmediğini kayda geçirir.
    """
    from app.modules.ai.readplane import _dogrula_dusuk_oncelikli_rota_yok, _tum_routerlar

    _dogrula_dusuk_oncelikli_rota_yok(app)
    routerlar = _tum_routerlar(app)
    assert len(routerlar) >= 38  # 38 üst seviye + 3 iç içe
    assert all(not getattr(r, "_low_priority_routes", None) for r in routerlar)


def test_mutasyon_prefixli_include_DUZ_TASIMAYI_patlatir() -> None:
    """`build_read_plane`in 'önek kayıt anında çakılır' varsayımı bekçili mi?

    Prefix'li bir include eklendiğinde rotaların ETKİN yolu KENDİ yolundan ayrışır
    ve düz taşıma sessizce yanlış yol üretirdi. Fonksiyon bunun yerine patlamalı.
    """
    from app.core.router_registry import ROUTERS

    prefixli = FastAPI()
    for router in ROUTERS:
        prefixli.include_router(router)
    prefixli.include_router(ROUTERS[0], prefix="/v2")
    with pytest.raises(RuntimeError, match="ETKİN yolu"):
        build_read_plane(prefixli)
