"""Kapsam maskesini UÇLARA bağlayan rota sınıfı (kullanıcı kararı 2026-09-19).

## Neden ROTA düzeyinde, uç uç DEĞİL

Kapsam kısıtı olan modüllerde onlarca uç vardır. Her ucun dönüşünü elle
`maskele()` ile sarmak da çalışırdı — ama bir ucu UNUTMAK sessiz bir para
sızıntısıdır ve unutulan uç hiçbir yerde kırmızı vermezdi. Üstelik sonradan
eklenen her yeni uç aynı tuzağı yeniden kurardı.

Rota sınıfı, dönüşü bir `BaseModel` OLAN her uç için tek noktadır: routera
bağlanan her uç, sonradan eklenenler DÂHİL, maskeden geçer.

🔴 **AMA "unutulacak bir şey yoktur" DEĞİLDİR** — eski docstring bunu iddia
ediyordu ve YANLIŞTI. Gövdesini kendi üreten uçlar (dosya indirme, `Response`,
`list[...]` dönenler) sarmalayıcıya `BaseModel` vermez ve MASKESİZ geçer; `GET
/sites/{site_id}/boq/export` tam da böyle, `boq=limited` rolüne birim fiyatı
xlsx olarak indiriyordu. Gerekçesi `_sarili` içindeki nottadır. Kural: böyle bir
uç maskeyi KENDİSİ uygular (`kapsamla_maskele`) ve
`tests/core/test_kapsam_kacak_uclar.py` unutulanı çakar.

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

__all__ = ["kapsam_bagimligi_kur", "kapsam_rotasi", "kapsamdan_oku", "kapsamla_maskele"]

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
            # 🔴 BU BİR DELİKTİR, zararsız bir ayrıntı DEĞİL.
            #
            # Eski yorum *"maskelenecek bir şema YOKTUR"* diyordu ve bu YANLIŞTI:
            # şema VARDIR, uç onu yalnızca bir `Response`un İÇİNE gömmüştür.
            # `GET /sites/{site_id}/boq/export` tam olarak bunu yapıyordu — ham
            # `BoqListResponse`ten xlsx üretip dönüyordu — ve `boq=limited` olan
            # rol (şantiye şefi, satınalma) ekranda `—` gördüğü birim fiyatı ve
            # tutarı aynı kapıdan (`boq:view`) dosya olarak İNDİRİYORDU.
            #
            # Burada maskelemeye ZORLAYAMAYIZ: elimizde baytlar vardır, alan
            # bilgisi yoktur; `Response`un içine geri girmek şemayı yeniden
            # kurmak demektir ve iki ayrı üretim yolu zamanla ayrışırdı. Bu
            # yüzden kural şudur:
            #
            #   **Gövdesini kendi üreten uç maskeyi KENDİSİ uygular**
            #   (`kapsamla_maskele`, aşağıda) ve `tests/core/
            #   test_kapsam_kacak_uclar.py` maskesiz kalan her gövdeli ucu çakar.
            #
            # Gövdesiz uçlar (204 DELETE) yapısal olarak güvenlidir: sızdıracak
            # bir gövdeleri yoktur.
            return sonuc
        kapsam = saglayici(modul_key, kwargs.get(request_var) if request_var else None)
        if inspect.isawaitable(kapsam):
            kapsam = await kapsam
        return maskele(sonuc, kapsam if isinstance(kapsam, Scope) else Scope.all)

    return _sarili


def kapsamdan_oku(_modul_key: str, _request: Any = None) -> Scope:
    """Rota sarmalayıcısının kullandığı GERÇEK sağlayıcı: köprüden okur."""
    return _KAPSAM.get()


def kapsamla_maskele[TModel: BaseModel](model: TModel, modul_key: str) -> TModel:
    """Gövdesini KENDİ üreten uçlar için ELLE maske (dosya indirme, xlsx, csv…).

    Rota sarmalayıcısı yalnız `BaseModel` dönüşlerini maskeler; bir `Response`un
    İÇİNE bakamaz (yukarıdaki nota bkz.). Dosya üreten uç bu yüzden modeli
    kitaba/CSV'ye çevirmeden ÖNCE buradan geçirir.

    🔴 `maskele(...)`yi doğrudan çağırmak yerine bu sarmalayıcı vardır ki
    "elle maskelenen uç" tek bir ADLA aranabilsin: `tests/core/
    test_kapsam_kacak_uclar.py`in izin listesi bu adı gerekçe olarak gösterir ve
    okuyan kişi iddiayı tek `grep`le doğrulayabilir.

    🔴 Kapsam BURADA okunur, çağıran ucun parametresinden DEĞİL: kapsamı uca
    parametre yapmak, onu yanlış modülün anahtarıyla çağırmayı mümkün kılardı.
    """
    return maskele(model, kapsamdan_oku(modul_key))


def kapsam_bagimligi_kur(cozucu: Callable[..., Awaitable[Scope]]) -> Callable[..., Any]:
    """Kapsamı çözüp köprüye yazan bir `Depends` gövdesi üretir.

    `cozucu` ayrı tutulur ki bu modül `roles` deposunu İTHAL ETMESİN (`core`,
    ürün modüllerine bağımlı olmamalıdır) ve test mekanizmayı DB'siz ölçebilsin.
    """

    @functools.wraps(cozucu)
    async def _bagimlilik(*args: Any, **kwargs: Any):
        # 🔴 `yield`li bağımlılık ve `reset` ŞARTTIR — ÖLÇÜLMÜŞ KUSUR (2026-09-19).
        #
        # `ContextVar.set()` çağrıldığı BAĞLAMI kalıcı değiştirir. İstekler ayrı
        # task'larda koşarsa zararsızdır; ama **HTTP keep-alive bağlantısındaki
        # ardışık istekler AYNI task'ta koşar** (ve `httpx.ASGITransport` ile
        # koşan her test de öyle). `reset` olmadan bir istekte yazılan kapsam,
        # köprüsü olmayan BİR SONRAKİ isteğe TAŞINIYORDU:
        #     B(köprüsüz)=500 · A(limited)=None · B(köprüsüz)=None   ← sızıntı
        #
        # Kusur fiilen zararsızdı (her kısıtlı router köprü taşır, değer her
        # istekte üzerine yazılır) ama bir MAYINDI: köprüsü unutulan bir router,
        # belgelenen fail-open `all`a değil ÖNCEKİ İSTEĞİN kapsamına düşerdi —
        # `limited` de olabilirdi `all` da, yani davranış BELİRSİZDİ. Ayrıca
        # `BackgroundTasks` yanıttan sonra aynı bağlamda koşar.
        #
        # `token` ile geri sarmak, `set` edilen değeri o isteğin ÖMRÜYLE
        # sınırlar. Teardown uç fonksiyonundan SONRA koştuğu için rota
        # sarmalayıcısı değeri hâlâ okuyabilir (bekçisi:
        # `test_kapsam_BIR_SONRAKI_ISTEGE_SIZMAZ`).
        token = _KAPSAM.set(await cozucu(*args, **kwargs))
        try:
            yield
        finally:
            _KAPSAM.reset(token)

    return _bagimlilik
