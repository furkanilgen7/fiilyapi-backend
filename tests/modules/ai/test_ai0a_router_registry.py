"""AI-0a T1 bekçileri — router kaydı ve **SIRASI**.

🔴 **Bu dosya var olmayan bir kapıyı kuruyor.** Ölçüldü: `tests/contract/
test_openapi_contract_baseline.py` deponun en güçlü backend bekçisidir ama T1'e
**yapısal olarak KÖRDÜR** — `_DUMP_KWARGS` `sort_keys=True` taşır, dolayısıyla
router sırası tamamen bozulsa bile hem sayaç (234/342) hem kanonik `sha256[:12]`
BİREBİR AYNI kalır. Sıra bir davranıştır ve bugüne kadar hiçbir kapı onu
bekçilemiyordu.

Buradaki iki bekçi:

* **B1c — kayıt TAMLIĞI.** `app/modules/**` altında modül düzeyinde tanımlı HER
  `APIRouter`, uygulamanın rota ağacından erişilebilir olmalıdır. Bu, `ROUTERS`tan
  bir router düşürme mutasyonunu öldüren tek testtir; kaynağı dosya sistemi olduğu
  için `ROUTERS`ın kendisinden bağımsızdır.
* **B1b — router-ARASI gölgeleme.** Üç literal/parametre çifti. İlk ikisinin adı
  konmuş bekçisi vardı (`test_mk2_*`), **üçüncüsünün (`/personnel/document-types`)
  YOKTU** — burada kapanıyor.
"""

import importlib
import pathlib
import pkgutil

from fastapi import APIRouter, FastAPI
from fastapi.routing import _IncludedRouter
from starlette.routing import Match

from app import modules as app_modules
from app.core.router_registry import ROUTERS
from app.main import app
from app.modules.equipment.document_router import router as equipment_document_router
from app.modules.equipment.rental_router import router as equipment_rental_router
from app.modules.equipment.router import router as equipment_router
from app.modules.personnel.document_type_router import router as personnel_document_type_router
from app.modules.personnel.router import router as personnel_router

# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------


def _erisilebilir_routerlar(uygulama: FastAPI) -> set[int]:
    """Rota ağacından erişilebilen TÜM router'ların kimlikleri (iç içe dahil).

    🔴 Özyineleme şart: tek seviyeli bir sayım bu depoda yanlıştır —
    `site_diary/router.py` iki, `subcontractor_progress_payments/router.py` bir
    alt-router include eder ve 9 rota yalnız özyinelemeyle görünür.
    """
    bulunan: set[int] = set()

    def gez(rotalar) -> None:
        for rota in rotalar:
            if isinstance(rota, _IncludedRouter):
                bulunan.add(id(rota.original_router))
                gez(rota.original_router.routes)

    gez(uygulama.routes)
    return bulunan


def _modul_duzeyinde_tanimli_routerlar() -> dict[int, set[str]]:
    """`app/modules/**` altındaki her modülün modül düzeyi `APIRouter` nesneleri."""
    tanimli: dict[int, set[str]] = {}
    kok = pathlib.Path(app_modules.__file__).parent
    for modul in pkgutil.walk_packages([str(kok)], prefix="app.modules."):
        if modul.ispkg:
            continue
        yuklenen = importlib.import_module(modul.name)
        for ad, deger in vars(yuklenen).items():
            if isinstance(deger, APIRouter):
                tanimli.setdefault(id(deger), set()).add(f"{modul.name}:{ad}")
    return tanimli


def _kazanan_router(uygulama: FastAPI, yol: str, metot: str = "GET") -> APIRouter | None:
    """Starlette'in eşleme algoritmasını birebir koşar: İLK FULL eşleşme kazanır.

    Bu ölçüm HTTP'ye, kimliğe ve seed verisine ihtiyaç duymaz — sırayı doğrudan
    okur. Kimlikli bir çağrı 401'de durur ve sırayı hiç sınamaz.
    """
    kapsam = {
        "type": "http",
        "method": metot,
        "path": yol,
        "root_path": "",
        "headers": [],
        "query_string": b"",
    }
    for rota in uygulama.routes:
        eslesme, _ = rota.matches(kapsam)
        if eslesme == Match.FULL and isinstance(rota, _IncludedRouter):
            return rota.original_router
    return None


# ---------------------------------------------------------------------------
# B1c — kayıt TAMLIĞI (mutasyon: ROUTERS'tan bir router düşür)
# ---------------------------------------------------------------------------


def test_B1c_tanimli_her_router_uygulamadan_ERISILEBILIR() -> None:
    """`ROUTERS`tan bir router düşürmek bu testi KIRMIZI yapar.

    Kaynak dosya sistemidir, `ROUTERS` değil — yani liste ile gerçeklik
    ayrıştığında bekçi konuşur. Sözleşme kapısı bu mutasyonu görür ama T1'in
    kendi kapısı yoktu; bu o kapıdır.
    """
    tanimli = _modul_duzeyinde_tanimli_routerlar()
    erisilebilir = _erisilebilir_routerlar(app)
    eksik = {
        kimlik: sorted(adlar) for kimlik, adlar in tanimli.items() if kimlik not in erisilebilir
    }
    assert not eksik, (
        "Şu router'lar tanımlı ama uygulamanın rota ağacında YOK — `ROUTERS`a "
        f"eklenmemişler ya da düşürülmüşler: {sorted(eksik.values())}"
    )


def test_B1c_pozitif_kontrol_dusurulen_router_YAKALANIR() -> None:
    """Pozitif kontrol: bekçi gerçekten ayrışmayı görüyor mu?

    Bir router'ı düşürerek kurulan uygulamada aynı ölçüt **eksik** rapor etmeli.
    Bu olmadan yukarıdaki test "her zaman yeşil" olabilir ve kimse fark etmez.
    """
    eksiltilmis = FastAPI()
    for router in ROUTERS:
        if router is personnel_document_type_router:
            continue
        eksiltilmis.include_router(router)
    tanimli = _modul_duzeyinde_tanimli_routerlar()
    erisilebilir = _erisilebilir_routerlar(eksiltilmis)
    eksik = {kimlik for kimlik in tanimli if kimlik not in erisilebilir}
    assert id(personnel_document_type_router) in eksik


def test_B1c_ROUTERS_duz_bir_router_demetidir() -> None:
    """🔴 `ROUTERS` `(router, kwargs)` çiftine ÇEVRİLEMEZ.

    Gerekçe ölçülmüş: üç mevcut test gezgini rota ağacını
    `_IncludedRouter.original_router.routes` üzerinden geziyor ve o ağaç ORİJİNAL
    yolu verir, ETKİN yolu değil. Bugün doğru çalışıyorlar çünkü hiçbir include
    `prefix=` taşımıyor. Demet prefix kazanırsa o gezginler SESSİZCE yanlış yol
    ölçmeye başlar — hata vermezler.
    """
    assert all(isinstance(router, APIRouter) for router in ROUTERS)


# ---------------------------------------------------------------------------
# B1b — router-ARASI gölgeleme (mutasyon: sırayı ters çevir)
# ---------------------------------------------------------------------------

#: (yol, kazanması GEREKEN router, gölgeleyecek router)
GOLGELEME_CIFTLERI = [
    ("/equipment/rental-invoices", equipment_rental_router, equipment_router),
    ("/equipment/document-types", equipment_document_router, equipment_router),
    # 🔴 Bu üçüncü çiftin bugüne kadar adı konmuş bir bekçisi YOKTU.
    ("/personnel/document-types", personnel_document_type_router, personnel_router),
]


def test_B1b_uc_golgeleme_ciftinin_UCU_DE_dogru_routera_gider() -> None:
    for yol, beklenen, _ in GOLGELEME_CIFTLERI:
        kazanan = _kazanan_router(app, yol)
        assert kazanan is beklenen, (
            f"{yol} yanlış router'a düştü. Kayıt sırası bozulmuş: literal yol bir "
            "yol parametresi sanılıyor ve uç 422 dönerdi."
        )


def test_B1b_pozitif_kontrol_sira_TERS_cevrilince_golgeleme_OLUSUR() -> None:
    """Mutasyonu testin İÇİNDE koşar: sıra bozulunca gölgeleyen router kazanmalı.

    Bu olmadan yukarıdaki test "yol zaten hep doğru router'a gidiyor" diye eşdeğer
    olabilirdi — gölgelemenin gerçekten mümkün olduğunu burada kanıtlıyoruz.
    """
    for yol, beklenen, golgeleyen in GOLGELEME_CIFTLERI:
        sirali = list(ROUTERS)
        i, j = sirali.index(beklenen), sirali.index(golgeleyen)
        sirali[i], sirali[j] = sirali[j], sirali[i]
        bozuk = FastAPI()
        for router in sirali:
            bozuk.include_router(router)
        assert _kazanan_router(bozuk, yol) is golgeleyen, (
            f"{yol}: sıra ters çevrildiğinde gölgeleme OLUŞMADI — bekçi bir şey "
            "bekçilemiyor olabilir (eşdeğer mutant)."
        )
