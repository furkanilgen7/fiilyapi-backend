"""Kapsam maskesinin UÇLARA bağlanması — `core/scoped_route.py`.

## Neden ROTA düzeyinde, uç uç DEĞİL

Altı modülde **66 uç** var. Her ucu tek tek maskelemek ("dönüşü `maskele()` ile
sar") çalışırdı ama bir ucu UNUTMAK sessiz bir para sızıntısıdır ve unutulan uç
hiçbir yerde kırmızı vermezdi. Rota sınıfı tek noktadır: routerdaki HER uç,
sonradan eklenenler DÂHİL, maskeden geçer. Unutulacak bir şey yoktur.

## Bekçiler

Burada mekanizma ölçülür (kapsam okunuyor mu, maske uygulanıyor mu, yazma
uçları bozulmuyor mu). Modüllerin GERÇEK uçlarındaki sızıntı ayrı bir
davranış bekçisindedir.
"""

from decimal import Decimal
from typing import Annotated

import pytest
from fastapi import APIRouter, FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel

from app.core.field_scope import Gorunurluk
from app.core.scoped_route import kapsam_rotasi

pytestmark = pytest.mark.asyncio

_MODUL = "boq"


class _Yanit(BaseModel):
    ad: str
    fiyat: Annotated[Decimal | None, Gorunurluk.para] = None
    metraj: Annotated[Decimal | None, Gorunurluk.operasyonel] = None


def _uygulama(kapsam_saglayici) -> FastAPI:
    """Kapsam okuma yolu TAKLİT EDİLİR; burada ölçülen şey BAĞLANTIDIR."""
    router = APIRouter(route_class=kapsam_rotasi(_MODUL, kapsam_saglayici))

    @router.get("/kart", response_model=_Yanit)
    async def kart() -> _Yanit:
        return _Yanit(ad="A Blok", fiyat=Decimal("500"), metraj=Decimal("12"))

    @router.post("/kart", response_model=_Yanit)
    async def yaz() -> _Yanit:
        return _Yanit(ad="A Blok", fiyat=Decimal("500"), metraj=Decimal("12"))

    app = FastAPI()
    app.include_router(router)
    return app


async def _oku(app: FastAPI, yol: str = "/kart", metod: str = "get") -> dict:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        resp = await getattr(client, metod)(yol)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_ALL_kapsaminda_hicbir_alan_gizlenmez() -> None:
    """🔴 POZİTİF KONTROL."""
    from app.core.access import Scope

    govde = await _oku(_uygulama(lambda *_a, **_k: Scope.all))
    assert govde["fiyat"] == "500"
    assert govde["metraj"] == "12"


async def test_LIMITED_kapsaminda_PARA_alani_gizlenir() -> None:
    from app.core.access import Scope

    govde = await _oku(_uygulama(lambda *_a, **_k: Scope.limited))
    assert govde["fiyat"] is None, "para sızdı"
    assert govde["metraj"] == "12", "operasyonel alan yanlışlıkla gizlendi"
    assert govde["ad"] == "A Blok", "kimlik gizlendi"


async def test_FINANCE_kapsaminda_OPERASYONEL_alan_gizlenir() -> None:
    from app.core.access import Scope

    govde = await _oku(_uygulama(lambda *_a, **_k: Scope.finance))
    assert govde["metraj"] is None
    assert govde["fiyat"] == "500"


async def test_YAZMA_ucu_da_maskeden_gecer() -> None:
    """🔴 Yazma ucunun yanıtı OKUMA ucuyla AYNI zarfı taşımalıdır — `boq`un
    `item_response` docstring'indeki kanonun aynısı. Yalnız GET'i maskeleyen bir
    kurulum, PATCH yanıtından tutarı sızdırırdı."""
    from app.core.access import Scope

    govde = await _oku(_uygulama(lambda *_a, **_k: Scope.limited), metod="post")
    assert govde["fiyat"] is None


async def test_kapsam_MODUL_ANAHTARIYLA_sorulur() -> None:
    """Maske aktörün O MODÜLDEKİ kapsamını okumalıdır; sabit bir modül adı
    kullansaydı bütün modüller aynı kapsamla maskelenirdi."""
    from app.core.access import Scope

    sorulan: list[str] = []

    def saglayici(modul_key: str, *_a, **_k) -> Scope:
        sorulan.append(modul_key)
        return Scope.all

    await _oku(_uygulama(saglayici))
    assert sorulan == [_MODUL]


# --------------------------------------------------------------------------- #
# GERÇEK sağlayıcı — kapsam bağımlılıktan ROTAYA nasıl taşınır
# --------------------------------------------------------------------------- #


async def test_kapsam_BAGIMLILIKTAN_rotaya_TASINIR() -> None:
    """🔴 ÖLÇÜLMEDEN KABUL EDİLMEYECEK VARSAYIM.

    Kapsam DB'den okunur ve bunu yapabilecek tek yer bir `Depends`tir (orada
    `session` ve `user` vardır). Rota sarmalayıcısının ise o değerlere doğrudan
    erişimi YOKTUR. Köprü bir `ContextVar`dır ve çalışması, FastAPI'nin
    bağımlılıkları uç fonksiyonuyla AYNI görev bağlamında çözmesine dayanır.

    Bu dayanak bir VARSAYIMDIR; doğru olduğunu burada ÖLÇERİZ. Yanlış olsaydı
    maske sessizce `all` görür ve HİÇBİR ŞEY gizlemezdi — üstelik testlerin
    çoğu yine yeşil kalırdı.
    """
    from fastapi import Depends

    from app.core.access import Scope
    from app.core.scoped_route import kapsam_bagimligi_kur, kapsamdan_oku

    async def _sahte_kapsam() -> Scope:
        return Scope.limited

    router = APIRouter(route_class=kapsam_rotasi(_MODUL, kapsamdan_oku))

    @router.get(
        "/kart", response_model=_Yanit, dependencies=[Depends(kapsam_bagimligi_kur(_sahte_kapsam))]
    )
    async def kart() -> _Yanit:
        return _Yanit(ad="A Blok", fiyat=Decimal("500"), metraj=Decimal("12"))

    app = FastAPI()
    app.include_router(router)

    govde = await _oku(app)
    assert govde["fiyat"] is None, "ContextVar köprüsü ÇALIŞMADI — maske `all` gördü"
    assert govde["metraj"] == "12"


async def test_kapsam_bagimliligi_YOKSA_maske_HICBIR_SEY_gizlemez() -> None:
    """🔴 Köprü kurulmamış bir routerda varsayılan `all` olmalıdır.

    Fail-OPEN bilinçlidir: kapsam okunamadığında ekranı BOŞALTMAK, bir yapılandırma
    eksiğini kullanıcıya veri kaybı olarak gösterirdi. Güvenliği sağlayan şey bu
    varsayılan değil, her modülün köprüyü kurduğunu çakan AYRI bekçidir.
    """
    from app.core.scoped_route import kapsamdan_oku

    router = APIRouter(route_class=kapsam_rotasi(_MODUL, kapsamdan_oku))

    @router.get("/kart", response_model=_Yanit)
    async def kart() -> _Yanit:
        return _Yanit(ad="A Blok", fiyat=Decimal("500"), metraj=Decimal("12"))

    app = FastAPI()
    app.include_router(router)

    govde = await _oku(app)
    assert govde["fiyat"] == "500"
