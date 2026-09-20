"""Maskeden GEÇEN her yanıt şemasında para/metraj alanları AÇIKÇA sınıflandırılmalıdır.

## Bu bekçi neyi mümkün kılıyor

`core/field_scope.py` sınıflandırılmamış alanı **kimlik** sayar (fail-OPEN) ve
bunun gerekçesi o modülün docstring'indedir: fail-closed olsaydı yeni eklenen
her operasyonel alan sessizce gizlenir, ekran kimsenin fark etmediği bir yerde
boşalırdı.

Fail-open'ı güvenli kılan şey varsayılan DEĞİL **BU TESTTİR**: sınıflandırılmamış
bir `Decimal`/`MetricPlaceholder` alanı CANLIYA ÇIKAMAZ, burada durur.

## 🔴 Tarama kümesi ROTA TABLOSUNDAN türetilir — modül ADINDAN değil

Eski hâli `app.modules.<matris_anahtarı>.schemas` adını TAHMİN ediyor ve elle
yazılmış bir `_EK_SEMA_MODULLERI` sözlüğüyle yamanıyordu. Üç ayrı kör nokta
ÖLÇÜLDÜ (2026-09-19 denetimi) ve üçü de aynı kökten çıkıyordu — *tarama kümesi
maskenin gerçekte dokunduğu kümeyle AYNI DEĞİLDİ*:

1. **Yabancı modülden iç içe gelen şema görünmüyordu.** `ProgressPaymentSummary`
   `progress_payments`ta tanımlıdır ama `contracts` yanıtının İÇİNDE döner;
   `maskele()` iç içe `BaseModel`e İNER, yani maske oraya ULAŞIR — yalnız etiket
   yoktu ve yedi para alanı hiçbir kapsamda gizlenmiyordu.
2. **İkinci şema dosyaları elle sayılıyordu** (`land_share_schemas`). Elle yazılan
   liste çürür: yeni bir şema dosyası açan kişi burayı güncellemek ZORUNDA değildi.
3. **Modül anahtarı ≠ python paketi.** `units` paketi `projects` anahtarına
   hizmet eder ve ad tahmini onu hiç bulamazdı.

Şimdi küme şöyle türetilir: `router_registry.ROUTERS` → maskeli rota sınıfını
(`_KapsamRotasi`) taşıyan uçlar → o uçların `response_model`'i → oradan alan ve
türev tiplerinden ÖZYİNELİ inilerek ulaşılan HER şema, nerede tanımlı olursa
olsun. Bu tam olarak `field_scope._deger()`in yürüdüğü ağaçtır; bekçinin gördüğü
küme ile maskenin dokunduğu küme artık aynı şeyin iki okunuşudur.

Yan etkisi: istek (request) gövdeleri kendiliğinden dışarıda kalır — hiçbir
`response_model` onlara ulaşmaz. Eski `_ISTEK_EKI` ad süzgeci bu yüzden SİLİNDİ;
ad süzgeci bir yanıt şemasını yanlışlıkla muaf tutabilirdi, erişilebilirlik ise
tutamaz.

## 🔴 `str` ALANLAR BU BEKÇİNİN DIŞINDADIR — ÖLÇÜLDÜ, BUGÜN SIFIR ÖRNEK

2026-09-20'de şu iddia soruldu: *"Bir olgu serbest metne gömülürse (ör. bir
açıklama alanında tutar geçerse) ne maskelenir ne bekçi görür."*

**MEKANİZMA GERÇEK:** `_siniflandirma_gerektirir` yalnız `Decimal` ve
`MetricPlaceholder` arar; `field_scope._kovalar` etiketsiz alanı `kimlik` sayar;
dolayısıyla etiketsiz bir `str` maskeden AYNEN geçer (sentetik modelle ölçüldü:
`limited` kapsamda `mesaj="Fiyat: 860.000 TL"` sağ salim döndü).

**SONUÇ ÇÜRÜK:** maskeli yüzeyin 179 `str` alanı tek tek sınıflandırıldı.
Sunucunun bir tutarı biçimleyip bir yanıt şemasına gömdüğü **TEK** yer
`units/importer.py::UnitImportRowReport.messages`tir ve orası maskeli hiçbir rol
tarafından AÇILAMAZ (uç `projects >= full` ister; o seviyedeki üç rolün üçü de
`Scope.all` taşır). Üstelik gömülen tutar kullanıcının KENDİ yüklediği dosyadan
gelir, DB'den değil. `dict`/`Any` alanları: maskeli yüzeyde tek bir tane var ve
o bir sayaç sözlüğü. Etiketsiz `Decimal` sayısı: **sıfır**.

Yani bu, bir KUSUR değil bir SINIRDIR ve kaydı burada durur ki bir sonraki tur
aynı soruyu sıfırdan araştırmasın. Sınırın bir gün ısırması için şu ÜÇÜ birden
gerekir: (1) sunucu bir tutarı metne gömmeye başlar, (2) o alan maskeli bir
yanıt ağacına girer, (3) maskeleyen bir rol o ucu açabilir.

🔴 Bir "onarım" cazip görünür ama ÖLÇÜLDÜ ve YANLIŞTIR: metin alanını
`Annotated[str, Gorunurluk.para]` ile etiketlemek maskeyi ZORUNLU bir alana
`None` YAZDIRIR — `model_copy(update=...)` pydantic v2'de doğrulama KOŞTURMAZ,
yani nesne hatasız serileşir ve OpenAPI'de `string` (required) bildirilen alan
gövdede `null` taşır. Metin alanı maskelenecekse tipi de `str | None` olmalıdır;
bu bir sözleşme değişikliğidir.

## 🔴 TÜREV (computed_field) alanlar AYRI BİR SORU SORAR

`model_fields` pydantic v2'de `computed_field`'ları İÇERMEZ (ölçüldü:
`"line_total" in SubcontractorContractItemResponse.model_fields` → `False`).
Türevler bu yüzden yıllarca hiçbir bekçinin görmediği bir bölgedeydi.

Türev ETİKETLENEMEZ (bir kolon değil bir formüldür, maske ona yazamaz). O yüzden
bu dosya türeve başka bir soru sorar ve soru YAPISALDIR: *girdileri
maskelenebiliyorsa türev `None` DÖNEBİLİYOR MU?* Dönemiyorsa maske girdiyi
`None` yaptığı anda formül `None` ile aritmetik yapar ve uç 500 verir.

Kardeş bekçiyle ÇAKIŞMAZ: `test_field_scope.py::test_LIMITED_TUREV_alan_da_DUSER`
türevin fiilen ne DÖNDÜĞÜNÜ (davranış) ölçer, burası imzanın buna İZİN VERİP
vermediğini (yapı) ölçer. Davranış testi ancak o şema için elle bir örnek
kurulmuşsa çalışır ve bugün sentetik bir model üzerinde koşuyor; yapı testi için
şemanın VAR OLMASI yeter — ürüne yeni eklenen türevi ilk gören budur.
"""

import typing
from decimal import Decimal

from fastapi.routing import APIRoute
from pydantic import BaseModel, computed_field

from app.core.access import Scope
from app.core.field_scope import Gorunurluk
from app.core.router_registry import ROUTERS
from app.modules.roles.seed_data import MATRIX

#: 🔴 ZARF SINIFLARININ KENDİSİ taranmaz. `MetricPlaceholder.value` bir kolonu
#: değil bir KABI temsil eder: aynı zarf bir yerde bütçe (para), başka yerde
#: ilerleme yüzdesi (operasyonel) taşır. Anlam KULLANIM YERİNDE belirlenir ve
#: orada etiketlenir; zarfı etiketlemek tüm kullanımları tek kovaya çökertirdi.
#:
#: Rota tabanlı tarama zarfları artık iç içe şema olarak ULAŞIR (eski ad tabanlı
#: tarama da onları `vars(schemas)` üzerinden görüyordu), bu yüzden muafiyet
#: GEREKLİDİR — aksi hâlde bekçi `MetricPlaceholder.value`yu etiketsiz sanıp
#: her koşuda kırmızı verirdi.
_ZARF_SINIFLARI = {"MetricPlaceholder", "CountPlaceholder"}

#: PARA anlamı taşıyan alan adı parçaları — `int`/`float` bekçisi içindir
#: (aşağıdaki C bendi). `total` BİLEREK YOKTUR: bu depoda `total` neredeyse her
#: yerde sayfalama SAYACIDIR (`ProjectListResponse.total`), para değil.
_PARA_ADLARI = (
    "amount",
    "price",
    "cost",
    "tutar",
    "bedel",
    "fiyat",
    "maliyet",
    "revenue",
    "profit",
    "budget",
    "butce",
    "balance",
    "kurus",
)

#: SAYAÇ imzası taşıyan parçalar — para adı geçse bile alanı muaf tutar.
#: Gerekçe ölçümle geldi: `items_missing_price` "fiyat" kelimesini taşır ama
#: fiyatı EKSİK OLAN KALEM SAYISIDIR. Sayaç imzası para imzasını EZER.
_SAYAC_ADLARI = ("count", "adet", "sayi", "missing", "pending", "index", "order", "sort")


def _kisitli_moduller() -> set[str]:
    """Matriste `all` OLMAYAN bir kapsam taşıyan modüller."""
    return {
        modul
        for modul, hucreler in MATRIX.items()
        if any(scope is not Scope.all for _lvl, scope in hucreler)
    }


def _rotalar(router: object):
    """Bir routerın TÜM uçları — alt routerlara da iner.

    🔴 Düz `router.routes` YETMEZ: FastAPI 0.141'de `include_router` alt routerı
    `_IncludedRouter` nesnesi olarak SAKLAR, rotaları üst listeye DÜZLEŞTİRMEZ
    (ölçüldü: `app.routes` kayıtlı 361 ucun yalnız 1'ini gösteriyor). Bugün
    `router_registry.ROUTERS`ın hiçbir üyesi iç içe DEĞİL — ama biri yarın
    `include_router` ile birleştirilirse özyineleme olmadan o modülün uçları
    SESSİZCE taranmaz ve üç bekçi birden yeşil kalırdı.

    🔴 `original_router` üzerinden inilir, `routes`/`router` niteliği üzerinden
    DEĞİL: `_IncludedRouter` bu sürümde ikisini de TAŞIMIYOR (ölçüldü) ve
    `hasattr` tabanlı bir yürüyüş sessizce hiçbir şey bulmazdı.
    """
    for rota in getattr(router, "routes", ()):
        if isinstance(rota, APIRoute):
            yield rota
        elif hasattr(rota, "original_router"):
            yield from _rotalar(rota.original_router)
        elif hasattr(rota, "routes"):
            yield from _rotalar(rota)


def _maskeli_rotalar() -> list[APIRoute]:
    """Yanıtı `field_scope.maskele`den GEÇEN uçlar.

    Kimlik `kapsam_rotasi()` fabrikasının ürettiği sınıf adıdır — `scoped_route`
    ile aynı sözleşme (`test_kapsam_baglantisi.py` de bunu kullanır ve orada
    fabrikanın bu adı ürettiğini çakan bir pozitif kontrol vardır).
    """
    return [
        rota
        for router in ROUTERS
        for rota in _rotalar(router)
        if type(rota).__name__ == "_KapsamRotasi"
    ]


def _semalar_icinde(annotation) -> typing.Iterator[type[BaseModel]]:
    """Bir tip ifadesinin İÇİNDEKİ tüm `BaseModel` sınıfları.

    `list[X] | None`, `dict[str, X]`, `Annotated[X, ...]` gibi sarmalayıcıların
    hepsini `typing.get_args` ile açar — maske de (`_deger`) liste/sözlük/iç içe
    modelin hepsine iniyor, bekçi ondan DAR bir küme görmemelidir.
    """
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        yield annotation
        return
    for alt in typing.get_args(annotation):
        yield from _semalar_icinde(alt)


def _ulasilan_semalar() -> dict[str, type[BaseModel]]:
    """Maskeli uçlardan ÖZYİNELİ ulaşılan her şema: `tam.ad` → sınıf.

    Türevlerin dönüş tipinden de inilir: bir şemaya YALNIZCA bir `computed_field`
    üzerinden ulaşılıyorsa o da maskeden geçer ve taranmalıdır.
    """
    bulunan: dict[str, type[BaseModel]] = {}

    def ekle(sema: type[BaseModel]) -> None:
        ad = f"{sema.__module__}.{sema.__name__}"
        if ad in bulunan:
            return
        bulunan[ad] = sema
        for alan in sema.model_fields.values():
            for alt in _semalar_icinde(alan.annotation):
                ekle(alt)
        for turev in sema.model_computed_fields.values():
            for alt in _semalar_icinde(turev.return_type):
                ekle(alt)

    for rota in _maskeli_rotalar():
        if rota.response_model is None:
            continue
        for sema in _semalar_icinde(rota.response_model):
            ekle(sema)
    return bulunan


def _taranan_semalar() -> dict[str, type[BaseModel]]:
    return {
        ad: sema for ad, sema in _ulasilan_semalar().items() if sema.__name__ not in _ZARF_SINIFLARI
    }


def _siniflandirma_gerektirir(annotation) -> bool:
    """`Decimal` ve `MetricPlaceholder` ANLAMI belirsiz tiplerdir.

    Bir `Decimal` tutar da olabilir metraj da; bir `MetricPlaceholder` bütçe de
    taşır ilerleme yüzdesi de. `str`/`bool`/`uuid`/`date` alanları apaçık
    kimliktir ve etiketlenmeleri yalnız gürültü olurdu.
    """
    metin = str(annotation)
    return "Decimal" in metin or "MetricPlaceholder" in metin


def _etiketli(alan) -> bool:
    return any(isinstance(meta, Gorunurluk) for meta in alan.metadata)


def _para_adi_tasir(ad: str) -> bool:
    kucuk = ad.lower()
    if any(sayac in kucuk for sayac in _SAYAC_ADLARI):
        return False
    return any(para in kucuk for para in _PARA_ADLARI)


def _maskelenebilir_alt_agac(sema: type[BaseModel], gorulen: set[str] | None = None) -> bool:
    """Bu şemanın yanıt ALT AĞACINDA maskelenebilir (etiketli) bir alan var mı?

    Türev bekçisinin ön şartıdır. Yalnız şemanın KENDİ alanlarına bakmak yetmez:
    `BoqGroupResponse.group_total` kendi etiketli alanına değil, `items` içindeki
    `BoqItemResponse.unit_price`a dayanır. Alt ağacı gezmeseydik o türev haksız
    yere muaf tutulurdu.
    """
    if gorulen is None:
        gorulen = set()
    ad = f"{sema.__module__}.{sema.__name__}"
    if ad in gorulen:
        return False
    gorulen.add(ad)
    for alan in sema.model_fields.values():
        if _etiketli(alan):
            return True
        for alt in _semalar_icinde(alan.annotation):
            if _maskelenebilir_alt_agac(alt, gorulen):
                return True
    return False


def _None_donebilir(annotation) -> bool:
    """Dönüş tipi `None` değerine İZİN VERİYOR mu?

    `typing.get_args` ile ölçülür, metinde `"None"` ARANMAZ: `dict[str, None]`
    gibi bir tip metinde eşleşir ama `None` DÖNDÜREMEZ ve bekçi yalan söylerdi.
    """
    return type(None) in typing.get_args(annotation)


def test_MASKEDEN_gecen_her_para_alani_SINIFLANDIRILMISTIR() -> None:
    eksik: dict[str, list[str]] = {}
    for sema_adi, sema in _taranan_semalar().items():
        alanlar = [
            ad
            for ad, alan in sema.model_fields.items()
            if _siniflandirma_gerektirir(alan.annotation) and not _etiketli(alan)
        ]
        if alanlar:
            eksik[sema_adi] = alanlar
    assert not eksik, (
        "Sınıflandırılmamış para/metraj alanı var — `field_scope` bunları KİMLİK "
        "sayar ve `limited` kapsamında SIZDIRIR. Her birini "
        "`Annotated[..., Gorunurluk.para]` ya da `Gorunurluk.operasyonel` ile "
        f"etiketleyin: {eksik}"
    )


def test_MASKEDEN_gecen_her_TUREV_para_alani_None_DONEBILIR() -> None:
    """🔴 Maske kanonu: girdisi maskeliyse TÜREV DE `None` döner.

    Türev `None` DÖNEMEYEN bir imza taşıyorsa iki kötü sondan biri kesindir:
    ya formül `None` ile aritmetik yapıp ucu 500'e düşürür, ya da maskeli
    bileşeni sessizce `0` sayıp EKSİK bir toplamı GERÇEK gibi basar — ikincisi
    gizlemekten daha kötüdür, çünkü ekran yanlış bir sayıyı doğru gibi gösterir.
    """
    kirik: dict[str, str] = {}
    for sema_adi, sema in _taranan_semalar().items():
        if not sema.model_computed_fields:
            continue
        if not _maskelenebilir_alt_agac(sema):
            # Alt ağacında maskelenebilir HİÇBİR alan yoksa türev de asla
            # maskeli bir girdi görmez; `| None` istemek burada yalnız yanıt
            # sözleşmesini gereksizce gevşetirdi.
            continue
        for ad, turev in sema.model_computed_fields.items():
            if not _siniflandirma_gerektirir(turev.return_type):
                continue
            if not _None_donebilir(turev.return_type):
                kirik[f"{sema_adi}.{ad}"] = str(turev.return_type)
    assert not kirik, (
        "TÜREV alan `None` DÖNEMİYOR ama girdileri maskelenebilir — maske "
        "girdiyi `None` yaptığı anda bu formül ya 500 verir ya da maskeli "
        "bileşeni atlayıp EKSİK toplamı gerçek gibi basar. Dönüş tipini "
        f"`| None` yapın ve girdi `None` iken `None` döndürün: {kirik}"
    )


def test_MASKEDEN_gecen_TAMSAYI_para_alani_SINIFLANDIRILMISTIR() -> None:
    """`int`/`float` tipli PARA alanı da sınıflandırılmalıdır (örn. kuruş).

    🔴 Neden TÜM `int`/`float` değil de yalnız PARA ADI taşıyanlar: ölçüldü,
    maskeden geçen ağaçta 91 etiketsiz `int`/`float` alan var ve neredeyse
    hepsi apaçık kimlik ya da sayaçtır (`sort_order`, `total`, `*_count`).
    Hepsini zorunlu kılmak 91 gürültü etiketi üretirdi; gürültü bir bekçiyi
    öldürmenin en hızlı yoludur — insanlar onu susturmak için etiketi
    düşünmeden basar ve sınıflandırma anlamını yitirir.

    Sayaçların `finance` kapsamında gizlenmesi AYRI bir sorudur ve bir ürün
    kararı ister (`CountPlaceholder` zarfında `kisitli()` YOKTUR; etiketlense
    zorunlu alana `null` yazılır ve sözleşme kırılır). Bu dosya o kararı
    kendiliğinden vermez.
    """
    eksik: dict[str, list[str]] = {}
    for sema_adi, sema in _taranan_semalar().items():
        alanlar = [
            ad
            for ad, alan in sema.model_fields.items()
            if not _siniflandirma_gerektirir(alan.annotation)
            and any(tip in str(alan.annotation) for tip in ("int", "float"))
            and _para_adi_tasir(ad)
            and not _etiketli(alan)
        ]
        if alanlar:
            eksik[sema_adi] = alanlar
    assert not eksik, (
        "PARA adı taşıyan `int`/`float` alan sınıflandırılmamış — `Decimal` "
        "olmaması onu kimlik yapmaz, `limited` kapsamında aynen SIZAR: "
        f"{eksik}"
    )


# --- POZİTİF KONTROLLER -------------------------------------------------
#
# Üstteki üç bekçi de "hiçbir şey bulamadım" hâlinde yeşildir. Aşağıdakiler o
# hâli reddedilen hâlden AYIRIR: tarama kümesinin dolu olduğunu ve her kuralın
# sentetik bir ihlalde FİİLEN ateşlendiğini çakar.


def test_tarama_kumesi_matristeki_HER_kisitli_modulu_KAPSAR() -> None:
    """🔴 Tarama kümesi rota tablosundan türediği için bir modülün routerı
    maskeden çıkarsa bekçi SESSİZCE küçülür ve yine yeşil kalırdı. Bu kontrol
    küçülmeyi kırmızıya çevirir: matriste kısıtlı olan her modül maskeli en az
    bir uç TAŞIMALIDIR."""
    kisitli = _kisitli_moduller()
    assert kisitli, "Matriste kapsam kısıtı KALMADI — bekçi artık hiçbir şey taramıyor."

    # Uç fonksiyonunun tanımlandığı python paketi (`app.modules.<X>.router`)
    # modül anahtarını verir; `functools.wraps` sarmalayıcıda `__module__`u
    # ASIL uçtan korur (bkz. `scoped_route._sarmala`).
    kapsanan = {rota.endpoint.__module__.split(".")[2] for rota in _maskeli_rotalar()}
    assert not kisitli - kapsanan, (
        "Matriste kısıtlı bir modülün MASKELİ UCU YOK — o modülün yanıtları "
        f"hiç maskelenmiyor ve bu bekçinin taramasının da dışında: {kisitli - kapsanan}"
    )

    # 🔴 EŞİK SAYI YAZILMAZ ("en az 90 şema" gibi bir taban çürür ve gerçek
    #    küçülmeyi de gizler). Bunun yerine KURAL ölçülür: kısıtlı her modülün
    #    kendi şemalarından en az biri tarama kümesinde OLMALIDIR. Bir modülün
    #    uçları yanıt şeması döndürmeyi bırakırsa ya da `response_model` düşerse
    #    burası kırmızıya döner.
    tarananin_modulleri = {sema.__module__.split(".")[2] for sema in _taranan_semalar().values()}
    assert not kisitli - tarananin_modulleri, (
        "Kısıtlı bir modülün HİÇBİR şeması tarama kümesinde yok — o modülün "
        f"uçları yanıt şeması bildirmiyor olabilir: {kisitli - tarananin_modulleri}"
    )


def test_bekci_ETIKETSIZ_Decimali_yakalar_ETIKETLIYI_gecirir() -> None:
    """🔴 'Her şeyi kabul et' hâli de yeşil kalırdı: kuralın iki yönünü de çak."""
    assert _siniflandirma_gerektirir(Decimal | None)
    assert not _siniflandirma_gerektirir(str)

    class _Ornek(BaseModel):
        etiketsiz: Decimal
        etiketli: typing.Annotated[Decimal, Gorunurluk.para]

    assert not _etiketli(_Ornek.model_fields["etiketsiz"])
    assert _etiketli(_Ornek.model_fields["etiketli"])


def test_TUREV_bekcisi_maskelenemez_agacta_SUSAR_maskelenebilirde_KONUSUR() -> None:
    """🔴 Türev kuralının ön şartı ('alt ağaçta maskelenebilir alan var mı')
    yanlış kurulsaydı iki yönde de sessizce ölürdü: ya hiçbir türevi sormaz ya
    da maskesiz şemalardan gürültü üretirdi."""

    class _Maskesiz(BaseModel):
        adet: int

        @computed_field  # type: ignore[prop-decorator]
        @property
        def iki_kati(self) -> Decimal:
            return Decimal(self.adet * 2)

    class _Maskeli(BaseModel):
        birim_fiyat: typing.Annotated[Decimal | None, Gorunurluk.para]

        @computed_field  # type: ignore[prop-decorator]
        @property
        def tutar(self) -> Decimal:
            return self.birim_fiyat or Decimal("0")

    assert not _maskelenebilir_alt_agac(_Maskesiz)
    assert _maskelenebilir_alt_agac(_Maskeli)

    # İç içe: kök şemanın KENDİ alanı etiketsizdir, maskelenebilirlik ALT
    # ağaçtan gelir — `BoqGroupResponse.group_total` tam olarak bu şekildedir.
    class _Kok(BaseModel):
        satirlar: list[_Maskeli]

    assert _maskelenebilir_alt_agac(_Kok)

    assert not _None_donebilir(_Maskeli.model_computed_fields["tutar"].return_type)
    assert _None_donebilir(Decimal | None)


def test_TAMSAYI_para_sezgisi_SAYACLARI_muaf_tutar_PARAYI_yakalar() -> None:
    """🔴 Ad sezgisi iki yönde de ölçülür: sayaçları muaf tutmasaydı 8 sahte
    kırmızı üretirdi (`items_missing_price` fiyatı EKSİK kalem sayısıdır),
    parayı yakalamasaydı bekçi hiçbir şey bekçilemezdi."""
    assert _para_adi_tasir("price_kurus")
    assert _para_adi_tasir("unit_cost")
    assert _para_adi_tasir("total_amount")
    assert not _para_adi_tasir("items_missing_price")
    assert not _para_adi_tasir("total_item_count")
    assert not _para_adi_tasir("sort_order")
    assert not _para_adi_tasir("total")


def test_rota_ozyinelemesi_ALT_ROUTERLARA_iner() -> None:
    """🔴 `_rotalar` özyinelemesi kırılırsa (FastAPI sürümü alt routerı başka
    türlü saklarsa) tarama kümesi boşalır ve ÜÇ bekçi birden sessizce yeşile
    döner — bu, ÖLÇÜLMÜŞ bir tuzaktır: düz `app.routes` bu sürümde 361 ucun
    yalnız 1'ini gösteriyor, gerisi `_IncludedRouter` nesnelerinin içinde.

    Kontrol iki yönlüdür: iç içe bir router kurulur ve ucunun BULUNDUĞU çakılır;
    sonra aynı ucun DÜZ listede görünmediği çakılır — ikincisi olmasaydı test,
    özyineleme hiç çalışmasa bile (düzleştiren bir FastAPI sürümünde) yeşil kalır
    ve bizi yanlış güvende bırakırdı.

    🔴 Yol (`path`) DEĞİL UÇ FONKSİYONU aranır: `_IncludedRouter` öneki (`prefix`)
    geç uygular ve iç routerın rotası hâlâ önek SİZ yolunu taşır. Yol arasaydık
    test, özyineleme DOĞRU çalışırken bile kırmızı verirdi."""
    from fastapi import APIRouter

    ic = APIRouter()

    @ic.get("/derin")
    async def _derin() -> dict[str, str]:  # pragma: no cover - imza yeter
        return {}

    dis = APIRouter()
    dis.include_router(ic, prefix="/dis")

    uclar = {rota.endpoint for rota in _rotalar(dis)}
    assert _derin in uclar, f"Özyineleme alt routera inmedi: {uclar}"
    assert not [rota for rota in dis.routes if isinstance(rota, APIRoute)], (
        "Bu FastAPI sürümü alt routerı DÜZLEŞTİRİYOR — özyineleme artık hiçbir "
        "şey kanıtlamıyor, bekçinin bu kontrolü yeniden kurulmalı."
    )

    maskeli = _maskeli_rotalar()
    assert maskeli, "Hiç maskeli uç bulunamadı — tarama kümesi BOŞ."
    assert any(rota.response_model is not None for rota in maskeli)
