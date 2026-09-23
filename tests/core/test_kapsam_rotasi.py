"""Kapsam maskesinin UÇLARA bağlanması — `core/scoped_route.py`.

## Neden ROTA düzeyinde, uç uç DEĞİL

Kısıtlı modüllerde onlarca uç var. Her ucu tek tek maskelemek ("dönüşü
`maskele()` ile sar") çalışırdı ama bir ucu UNUTMAK sessiz bir para sızıntısıdır
ve unutulan uç hiçbir yerde kırmızı vermezdi. Rota sınıfı tek noktadır:
routerdaki HER uç, sonradan eklenenler DÂHİL, maskeden geçer.

🔴 *"Unutulacak bir şey yoktur"* CÜMLESİ BURADA YAZIYORDU VE YANLIŞTI: gövdesini
kendi üreten uçlar (dosya indirme, `Response`, `list[...]`) sarmalayıcıya bir
`BaseModel` vermez ve MASKESİZ geçer. Gerekçesi `core/scoped_route.py::_sarili`
içindedir, bekçisi `tests/core/test_kapsam_kacak_uclar.py`.

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


async def test_MASKELEYEN_kapsam_YAZMA_ucunde_403_alir() -> None:
    """🔴 BU TEST BİR İDDİANIN ÖLÇÜLMESİNDEN DOĞDU (2026-09-20).

    Önceki hâli `test_YAZMA_ucu_da_maskeden_gecer` idi ve şunu savunuyordu:
    *"yazma ucunun yanıtı okuma ucuyla aynı zarfı taşımalı; yalnız GET'i
    maskeleyen bir kurulum PATCH yanıtından tutarı sızdırırdı."* Gerekçe
    ÖLÇÜLDÜ ve fazla genişti: aynı depo o bileşimi (maskeleyen kapsam + yazan
    seviye) `roles/service.py::update_permission` ile ZATEN yasaklıyor, yani
    "PATCH yanıtından sızma" senaryosunun bir AKTÖRÜ yoktu.

    İddia kapatılırken seçim maskelemek DEĞİL **kapıyı kapatmak** oldu: maske
    bir GÖSTERİM aracıdır, yazma bir YETKİ sorusudur. Maskelenmiş bir aktörün
    yazma ucuna girip *"maskelenmiş bir yanıt"* alması, kaydı DEĞİŞTİRDİKTEN
    sonra ne yazdığını göremediği bir hâl üretirdi — bu, sızıntıdan daha kötü
    bir yarı-durumdur.

    Uçtan uca ikizi: `tests/core/test_kapsam_yazma_kapisi.py` (gerçek rol,
    gerçek uç).
    """
    from app.core.access import Scope

    transport = ASGITransport(app=_uygulama(lambda *_a, **_k: Scope.limited))
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        resp = await client.post("/kart")

    assert resp.status_code == 403, resp.text


async def test_POZITIF_KONTROL_ALL_kapsaminda_YAZMA_ucu_CALISIR() -> None:
    """🔴 Üstteki kapı *"her yazmayı reddet"* hâline gelirse burası kırmızı olur."""
    from app.core.access import Scope

    govde = await _oku(_uygulama(lambda *_a, **_k: Scope.all), metod="post")
    assert govde["fiyat"] == "500"


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


# --------------------------------------------------------------------------- #
# ContextVar SIZINTISI — istekten isteğe taşınma
# --------------------------------------------------------------------------- #


async def test_kapsam_BIR_SONRAKI_ISTEGE_SIZMAZ() -> None:
    """🔴 ÖLÇÜLMÜŞ KUSUR (2026-09-19 denetimi) — köprü değeri TEMİZLENMİYORDU.

    `ContextVar.set()` çağrıldığı BAĞLAMI kalıcı olarak değiştirir. İstekler ayrı
    task'larda koşarsa bu zararsızdır; ama **HTTP keep-alive bağlantısındaki
    ardışık istekler AYNI task'ta koşar** (ve `httpx.ASGITransport` ile koşan her
    test de öyle). Yani bir istekte yazılan kapsam, köprüsü olmayan bir sonraki
    isteğe TAŞINIYORDU.

    Ölçüldü (onarım öncesi):
        B (köprü yok) → 500   · A (limited) → None · B (yine köprü yok) → None
    yani A'nın `limited`i B'ye sızdı.

    🔴 Bugün her kısıtlı router köprü taşıdığı için değer her istekte ÜZERİNE
    yazılıyordu, yani kusur fiilen zararsızdı. Ama bir MAYINDI: köprüsü unutulan
    bir router, belgelenen fail-open `all`a değil ÖNCEKİ İSTEĞİN kapsamına
    düşerdi — `limited` de olabilir `all` da, yani davranış BELİRSİZDİ. Ayrıca
    `BackgroundTasks` yanıttan sonra aynı bağlamda koşar.

    ⚠️ Bu kusur, üç bağımsız çürütücünün İKİSİ tarafından "çürütüldü" sayılmıştı;
    ölçüm onları yanlışladı. Çoğunluk oyu bir ölçüm değildir.
    """
    from fastapi import Depends

    from app.core.access import Scope
    from app.core.scoped_route import kapsam_bagimligi_kur, kapsamdan_oku

    async def _limited() -> Scope:
        return Scope.limited

    kopru_var = APIRouter(route_class=kapsam_rotasi("boq", kapsamdan_oku))

    @kopru_var.get(
        "/kopru-var",
        response_model=_Yanit,
        dependencies=[Depends(kapsam_bagimligi_kur(_limited))],
    )
    async def kv() -> _Yanit:
        return _Yanit(ad="A", fiyat=Decimal("500"), metraj=Decimal("12"))

    # Köprüsü OLMAYAN, ama maskeli bir router: varsayılanı `all` OLMALIDIR.
    kopru_yok = APIRouter(route_class=kapsam_rotasi("sales", kapsamdan_oku))

    @kopru_yok.get("/kopru-yok", response_model=_Yanit)
    async def ky() -> _Yanit:
        return _Yanit(ad="B", fiyat=Decimal("500"), metraj=Decimal("12"))

    app = FastAPI()
    app.include_router(kopru_var)
    app.include_router(kopru_yok)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        once = (await client.get("/kopru-yok")).json()
        maskeli = (await client.get("/kopru-var")).json()
        sonra = (await client.get("/kopru-yok")).json()

    assert once["fiyat"] == "500", "kurulum: köprüsüz router zaten maskeliymiş"
    assert maskeli["fiyat"] is None, "kurulum: köprülü router maskelemedi"
    assert sonra["fiyat"] == "500", (
        "🔴 KAPSAM SIZDI: köprülü istekte yazılan kapsam, köprüsüz bir sonraki "
        "isteğe taşındı. ContextVar `reset` edilmiyor."
    )
