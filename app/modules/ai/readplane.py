"""AI **okuma düzlemi**: ana uygulamanın yalnız GET uçlarını taşıyan türev uygulama.

AI-0a T2. Kapı D'nin rota tarafı: POST/PUT/PATCH/DELETE burada **reddedilmez, VAR
OLMAZ**. Yazma yüzeyi yoksa "yazma iznini atlatma" saldırısının hedefi de yoktur.

Bu dosyanın tamamı **ölçüme** dayanır; her tasarım kararının altında pinli ortamda
(fastapi 0.141.1 · starlette 1.6.0) alınmış bir ölçüm vardır.

---

## 1. Neden "budama" DEĞİL, "yeniden kayıt"

Naif tarif şudur: router'ları `include_router` ile yeniden monte et, sonra
`route.methods <= {"GET","HEAD"}` ile bud. **Pinli sürümde bu SESSİZCE ÇÖKER.**
Ölçüldü:

    app.routes toplam: 43 | tipler: {_IncludedRouter: 38, Route: 4, APIRoute: 1}

Yani `[r for r in app.routes if isinstance(r, APIRoute)]` **1** döndürür (yalnız
satır-içi `/health`). Naif budama "GET kümesi = {/health}" der, okuma düzlemi TEK
uçla açılır ve **hiçbir test kırmızı olmaz**. fastapi 0.141'de rotalar include
anında çözülmez; `_IncludedRouter` tembel bir ara katmandır.

Doğru rota tablosu `fastapi.routing.iter_route_contexts` ile çıkarılır: 346 bağlam
(342 `APIRoute` + 4 starlette `Route`), 234 yol / 342 operasyon, GET **140**.

## 2. Neden rota nesnelerini KOPYALAMIYORUZ — beş sessiz varyant

`dependency_overrides`ın etkili olması, rotanın hangi `dependency_overrides_provider`a
bağlı bir include bağlamından çözüldüğüne bağlıdır. `_RouterIncludeContext.for_include`
bu sağlayıcıyı **include anında** ebeveyn router'dan alır ve bağlama çakar.

Pinli 0.141.1'de ÖLÇÜLDÜ — aşağıdakilerin hepsi **200 döner, rota eşleşir, uç
çalışır**, ama bağımlılık ANA (yazılabilir) havuzdan çözülür; hata yok, uyarı yok:

    V2  sub.router.routes.extend(app.routes)                     -> override ETKİSİZ
    V3  sub.router.routes.extend([copy.copy(x) for x in ...])    -> override ETKİSİZ
    V5  sub.router.routes = list(app.routes)                     -> override ETKİSİZ
    V6  sub.router.routes.append(ctx.original_route)             -> override ETKİSİZ
    V7  sub.router.routes.append(copy.copy(ctx.original_route))  -> override ETKİSİZ

(İki varyant sessiz değil, gürültülü çöker: çözülmüş etkin rotayı `append` etmek
`AttributeError`, `copy.deepcopy` `RecursionError` verir.)

ETKİLİ olan tek şey **`include_router`dan geçmektir**:

    E1  sub.include_router(app.router)          -> override ETKİLİ (ama budamaz)
    E2  sub.include_router(orijinal APIRouter)  -> override ETKİLİ (ama budamaz)
    E3  taze APIRouter + include                -> override ETKİLİ  ← seçilen

## 3. Seçilen tasarım ve dayandığı olgu

Taze bir `APIRouter`a **orijinal `APIRoute` nesneleri** konur ve o router
`include_router` ile monte edilir. Bu hem budar hem override'ı etkili kılar ve
hiçbir rota özniteliğini elle kopyalamaz (kopyalama, unutulan tek bir kwarg'da
sözleşmeyi sessizce değiştirirdi).

Dayandığı olgu: **`APIRouter(prefix=...)` öneki rota KAYIT anında yola çakılır**,
include anında değil. Yani `equipment_router`ın rotası zaten `/equipment/{...}`
yolunu taşır ve düz taşınabilir. Bu varsayım her çağrıda `_dogrula_duz_tasima`
ile **fiilen doğrulanır**: bir include `prefix=` kazanırsa `ctx.path !=
rota.path` olur ve fonksiyon patlar (sessizce yanlış yol üretmez). Bugün ölçüldü:
38 include, `prefix=` taşıyan **0**.

## 4. Handler / limiter / middleware paritesi (S28)

Ölçüldü: ana app'te **29** istisna handler'ı, çıplak `FastAPI()`de **3**.
`include_router` bunları **taşımaz**. Depoda 174+ `raise NotFoundError` servis
katmanındadır; handler kaydedilmezse `NotFoundError` yakalanmaz ve
`ASGITransport(raise_app_exceptions=True)` altında istisna executor'a fırlar →
ekran "kayıt bulunamadı" derken AI "sistem hatası" der. Bu yüzden
`register_exception_handlers` + `state.limiter` + middleware paritesi ŞARTTIR.
Bekçi **sayı değil KÜME eşitliğidir**.

## 5. 🔴 BİLİNEN YAPISAL KÖR NOKTA — `_low_priority_routes`

`iter_route_contexts` **düşük öncelikli rotaları KAPSAMAZ**: onlar
`APIRouter._low_priority_routes` listesinde ayrı durur ve ayrı bir yoldan
(`_IncludedRouter.effective_low_priority_routes()`) çözülür. Yani o listede bir
GET yaşarsa okuma düzlemi onu **sessizce kaçırır**.

Bugün zararsız: 41 router'ın hepsinde liste BOŞ (ölçüldü) — bu listeyi yalnız
fastapi'nin frontend montaj yolu doldurur ve bu depoda öyle bir çağrı YOKTUR.
Yarın zararsız olmayabilir, bu yüzden **varsayım olarak bırakılmadı**:
`_dogrula_dusuk_oncelikli_rota_yok` her çağrıda kontrol eder ve doluysa PATLAR.
"""

from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute, _IncludedRouter, iter_route_contexts
from slowapi.errors import RateLimitExceeded

from app.core.db import get_db
from app.core.exception_handlers import register_exception_handlers
from app.core.ratelimit import limiter, rate_limit_exceeded_handler
from app.modules.ai.db import get_ai_readonly_db

#: Okuma düzlemine alınan metotlar. `HEAD` gövdesiz GET'tir ve starlette onu GET
#: rotasına otomatik ekler; ayırmak yapay bir fark üretirdi.
OKUMA_METOTLARI = frozenset({"GET", "HEAD"})


def _tum_routerlar(app: FastAPI) -> list[APIRouter]:
    """Uygulamanın rota ağacındaki TÜM router'ları (iç içe olanlar dahil) toplar.

    🔴 Tek seviyeli sayım bu depoda yanlıştır: `site_diary/router.py` iki,
    `subcontractor_progress_payments/router.py` bir alt-router include eder;
    toplam 9 rota yalnız özyinelemeyle görünür.
    """
    toplanan: list[APIRouter] = []

    def gez(rotalar) -> None:
        for rota in rotalar:
            if isinstance(rota, _IncludedRouter):
                toplanan.append(rota.original_router)
                gez(rota.original_router.routes)

    gez(app.routes)
    return toplanan


def _dogrula_dusuk_oncelikli_rota_yok(app: FastAPI) -> None:
    """§5'teki kör noktayı **varsayım** olmaktan çıkarır: doluysa patlar."""
    dolu = [
        r for r in [app.router, *_tum_routerlar(app)] if getattr(r, "_low_priority_routes", None)
    ]
    if dolu:
        raise RuntimeError(
            "Okuma düzlemi kurulamaz: `_low_priority_routes` DOLU. `iter_route_contexts` "
            "o listeyi kapsamaz, dolayısıyla oradaki GET uçları okuma düzleminde SESSİZCE "
            f"kaybolurdu. Dolu router sayısı: {len(dolu)}. Önce taşıma yolu yazılmalı."
        )


def _dogrula_duz_tasima(etkin_yol: str | None, rota: APIRoute) -> None:
    """§3'teki 'önek kayıt anında çakılır' olgusunu her rotada doğrular."""
    if etkin_yol != rota.path:
        raise RuntimeError(
            "Okuma düzlemi kurulamaz: rotanın ETKİN yolu ile KENDİ yolu ayrışıyor "
            f"({etkin_yol!r} != {rota.path!r}). Bu, bir `include_router(..., prefix=...)` "
            "eklendiği anlamına gelir; rotaları düz taşımak sessizce YANLIŞ yol üretirdi."
        )


def build_read_plane(source_app: FastAPI | None = None) -> FastAPI:
    """Ana uygulamanın GET uçlarını taşıyan salt-okunur türev uygulamayı kurar.

    Kaynak **`ROUTERS` değil, uygulamanın rota tablosudur**: `GET /health`
    `main.py`de satır-içi tanımlıdır ve registry onu yakalamaz — ama GET kümesinin
    içindedir. Registry'den üretilen bir okuma düzlemi onu sessizce kaçırırdı.
    """
    if source_app is None:  # tembel import: `app.main` bu modülü import etmiyor
        from app.main import app as source_app

    _dogrula_dusuk_oncelikli_rota_yok(source_app)

    # `openapi_url=None` → `/docs`, `/redoc`, `/openapi.json` hiç doğmaz. Okuma
    # düzlemi tarayıcıya değil, süreç-içi bir ASGI taşıyıcısına hizmet eder;
    # şema uçları yalnız gereksiz yüzeydir.
    okuma_duzlemi = FastAPI(
        title="FİİL Yapı ERP — AI okuma düzlemi",
        version=source_app.version,
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
    )

    # --- Parite (S28): handler + limiter + middleware ---------------------
    okuma_duzlemi.state.limiter = limiter
    okuma_duzlemi.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
    register_exception_handlers(okuma_duzlemi)
    # Middleware yığını ilk istekte kurulur; buraya kadar `user_middleware`
    # doğrudan genişletilebilir. Ana app'in listesi ne ise okuma düzlemininki de
    # odur — `_configure_cors`u yeniden çağırmak yerine kopyalanır ki ileride
    # eklenen HER middleware kendiliğinden parite kazansın.
    okuma_duzlemi.user_middleware.extend(source_app.user_middleware)

    # --- Rotalar: yalnız GET, orijinal nesneler, include üzerinden --------
    get_router = APIRouter()
    for baglam in iter_route_contexts(source_app.routes):
        rota = baglam.original_route
        if not isinstance(rota, APIRoute):
            # starlette `Route`ları (`/docs`, `/openapi.json`, …) fastapi'nin kendi
            # ürettiği şema uçlarıdır; okuma düzleminde karşılıkları yoktur.
            continue
        if not (baglam.methods or set()) <= OKUMA_METOTLARI:
            continue
        _dogrula_duz_tasima(baglam.path, rota)
        get_router.routes.append(rota)
    okuma_duzlemi.include_router(get_router)

    # --- Kapı D: her okuma salt-okunur havuzdan --------------------------
    # 🔴 `get_current_user` BİLEREK override EDİLMEZ: AI, kullanıcının KENDİ izin ve
    # rol kapsamıyla okur (K1). Buraya bir kimlik override'ı koymak, AI'a kendi
    # kimliğini vermek olurdu — tüm yetki modelinin çöktüğü nokta budur.
    okuma_duzlemi.dependency_overrides[get_db] = get_ai_readonly_db

    return okuma_duzlemi
