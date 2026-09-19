"""Kapsam maskesini UÇLARA bağlayan rota sınıfı (kullanıcı kararı 2026-09-19).

## Neden ROTA düzeyinde, uç uç DEĞİL

Kapsam kısıtı olan altı modülde **66 uç** vardır. Her ucun dönüşünü elle
`maskele()` ile sarmak da çalışırdı — ama bir ucu UNUTMAK sessiz bir para
sızıntısıdır ve unutulan uç hiçbir yerde kırmızı vermezdi. Üstelik sonradan
eklenen her yeni uç aynı tuzağı yeniden kurardı.

Rota sınıfı TEK NOKTADIR: routera bağlanan her uç, sonradan eklenenler DÂHİL,
maskeden geçer. Unutulacak bir şey yoktur.

## Nasıl çalışır

`APIRoute.__init__` uç fonksiyonunu alır; burada onu SARMALARIZ. Sarmalayıcı
önce asıl ucu çağırır, sonra dönen modeli `field_scope.maskele`den geçirir.

🔴 `functools.wraps` ŞARTTIR ve kozmetik DEĞİLDİR: FastAPI bağımlılık
enjeksiyonunu (`Depends`, yol/sorgu parametreleri) `inspect.signature` ile
çözer ve o da `__wrapped__` zincirini izler. `wraps` olmasaydı sarmalayıcının
`(*args, **kwargs)` imzası görünür ve **uçların tüm parametreleri kaybolurdu**.

🔴 Maske SERİLEŞTİRMEDEN ÖNCE, modelin KENDİSİNE uygulanır. Yanıt JSON'ı
sonradan ayrıştırılıp düzeltilseydi tip bilgisi kaybolur, `Decimal` metne döner
ve iç içe zarflar tanınamazdı.

## Yazma uçları da maskelenir

Bilinçlidir: `boq.item_response`in kanonu *"yazma ucunun yanıtı OKUMA ucuyla
AYNI zarfı taşımalıdır"* der. Yalnız `GET`i maskeleyen bir kurulum `PATCH`
yanıtından tutarı sızdırırdı.

## Kapsam SAĞLAYICI neden dışarıdan verilir

Kapsam okuma DB'ye gider (`RolePermission`). Sağlayıcıyı parametre yapmak hem
bu modülü `core`da bağımsız tutar hem de testin mekanizmayı DB'siz ölçmesini
sağlar — bekçi, ölçtüğü yolu kendisi kurmaz.
"""

import functools
import inspect
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from typing import Any

from fastapi import Request
from fastapi.routing import APIRoute
from pydantic import BaseModel

from app.core.access import Scope
from app.core.field_scope import maskele

__all__ = ["kapsam_bagimligi_kur", "kapsam_rotasi", "kapsamdan_oku"]

#: 🔴 BAĞIMLILIK → ROTA KÖPRÜSÜ.
#:
#: Kapsam DB'den okunur ve bunu yapabilecek tek yer bir `Depends`tir (orada
#: `session` ve `user` vardır); rota sarmalayıcısının o değerlere doğrudan
#: erişimi YOKTUR. Köprü budur ve çalışması FastAPI'nin bağımlılıkları uç
#: fonksiyonuyla AYNI görev bağlamında çözmesine dayanır — bu bir VARSAYIMDIR ve
#: `test_kapsam_BAGIMLILIKTAN_rotaya_TASINIR` onu ÖLÇER.
#:
#: Varsayılan `all`dır (fail-OPEN): köprü kurulmamış bir routerda ekranı
#: BOŞALTMAK, bir yapılandırma eksiğini kullanıcıya veri kaybı olarak
#: gösterirdi. Güvenliği sağlayan şey bu varsayılan değil, her kısıtlı modülün
#: köprüyü kurduğunu çakan ayrı bekçidir.
_KAPSAM: ContextVar[Scope] = ContextVar("_kapsam_maskesi", default=Scope.all)

#: `(modul_key, request) -> Scope` (eşzamansız da olabilir).
KapsamSaglayici = Callable[..., Scope | Awaitable[Scope]]


def kapsam_rotasi(modul_key: str, saglayici: KapsamSaglayici) -> type[APIRoute]:
    """`APIRouter(route_class=...)` için bir rota sınıfı üretir."""

    class _KapsamRotasi(APIRoute):
        def __init__(self, path: str, endpoint: Callable[..., Any], **kwargs: Any) -> None:
            super().__init__(path, _sarmala(endpoint, modul_key, saglayici), **kwargs)

    return _KapsamRotasi


def _sarmala(
    endpoint: Callable[..., Any], modul_key: str, saglayici: KapsamSaglayici
) -> Callable[..., Any]:
    imza = inspect.signature(endpoint)
    # `request` ZATEN varsa yeniden eklenmez; FastAPI aynı adı iki kez görürse
    # ikincisini yok sayar ve sarmalayıcı istek nesnesine ulaşamazdı.
    request_var = next((ad for ad, p in imza.parameters.items() if p.annotation is Request), None)

    @functools.wraps(endpoint)
    async def _sarili(*args: Any, **kwargs: Any) -> Any:
        sonuc = endpoint(*args, **kwargs)
        if inspect.isawaitable(sonuc):
            sonuc = await sonuc
        if not isinstance(sonuc, BaseModel):
            # Dosya indirme, `Response` dönen uçlar, düz liste vb. — maskelenecek
            # bir şema YOKTUR ve zorlamak `AttributeError` üretirdi.
            return sonuc
        kapsam = saglayici(modul_key, kwargs.get(request_var) if request_var else None)
        if inspect.isawaitable(kapsam):
            kapsam = await kapsam
        return maskele(sonuc, kapsam if isinstance(kapsam, Scope) else Scope.all)

    return _sarili


def kapsamdan_oku(_modul_key: str, _request: Any = None) -> Scope:
    """Rota sarmalayıcısının kullandığı GERÇEK sağlayıcı: köprüden okur."""
    return _KAPSAM.get()


def kapsam_bagimligi_kur(cozucu: Callable[..., Awaitable[Scope]]) -> Callable[..., Any]:
    """Kapsamı çözüp köprüye yazan bir `Depends` gövdesi üretir.

    `cozucu` ayrı tutulur ki bu modül `roles` deposunu İTHAL ETMESİN (`core`,
    ürün modüllerine bağımlı olmamalıdır) ve test mekanizmayı DB'siz ölçebilsin.
    """

    @functools.wraps(cozucu)
    async def _bagimlilik(*args: Any, **kwargs: Any) -> None:
        _KAPSAM.set(await cozucu(*args, **kwargs))

    return _bagimlilik
