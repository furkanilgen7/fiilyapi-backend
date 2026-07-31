"""Santiye yazma yolunun ORTAK korkuluklari ve Turkce hata metinleri (spec §5.1, §7.2).

`units/guards.py` deseninin birebiri: alan HATA SINIFLARI `app/core/errors.py`'de,
METINLER modul icinde sabit olarak durur. Kurallar burada TEK kopya durur; POST
(T6) ve PATCH'in yayina gecis dali (T7) KOPYALAMAZ, CAGIRIR — iki kopya zamanla
ayrisir ve ayrisan taraf sessiz bir veri hatasi olur.

## Tek cumlelik kural

**Tutarlilik kurallari HER ZAMAN kosar, zorunluluk kurallari YALNIZ
taslak-disinda.**

Yarim kalmis bir taslak asla GECERSIZ veri saklamaz (bitisi baslangictan onceki
bir santiye hicbir modda anlamli degildir), yalniz EKSIK veri saklar (sefi henuz
secilmemis olabilir). Ayrimi tersine cevirmek iki yonde de zarar verir:

* zorunlulugu taslakta da kosarsak "Taslak Kaydet" dugmesi islevsiz kalir;
* tutarliligi taslakta gevsetirsek DB'ye anlamsiz tarih araliklari sizar ve
  yayina gecis aninda kullaniciya ilk kez, baglamsiz bir hata olarak doner.

## Kosulmadigi yer

`PATCH /sites/{id}` bu dogrulamayi TAM olarak kosmaz (§0.3/3, §5.3): kosarsa
canlidaki sefsiz/il bilgisi olmayan eski santiyeler duzenlenemez hâle gelir ve
kullanici yalnizca adi degistirmek isterken "Şantiye şefi seçiniz." duvarina
carpar. PATCH'te yalniz tutarlilik kurallari, `is_draft: true -> false`
gecisinde ise BIRLESIK kayit uzerinde tum kurallar kosar.
"""

from typing import Protocol

from app.core.errors import SiteValidationError

# --- Spec §7.2 tablosundan BIREBIR alinmistir — yeniden yazilmaz. ---

# 404 govdeleri AYIRT EDICI OLMAMALIDIR: gorunmeyen bir projedeki GERCEK santiye
# ile var olmayan santiye AYNI mesaji doner, aksi hâlde elinde UUID olan kullanici
# kaydin hâlâ var oldugunu ve baska bir projeye ait oldugunu ayirt edebilirdi.
PROJECT_MISSING = "Proje bulunamadı"
SITE_MISSING = "Şantiye bulunamadı"
SECTION_MISSING = "Bölüm bulunamadı"

# Sef/ISG icin secilen kullanici yok veya pasif. 404 DEGIL 422: istenen kaynak
# santiyedir, kullanici degil — kullanici burada bir ALAN DEGERIDIR.
USER_NOT_FOUND = "Seçilen kullanıcı bulunamadı"

# 409 — kod cakismalari. Yeni istisna sinifi ACILMAZ: mevcut `DuplicateError`.
DUPLICATE_SITE_CODE = "Bu şantiye kodu bu projede zaten kullanılıyor"
DUPLICATE_SECTION_CODE = "Bu bölüm kodu bu şantiyede zaten kullanılıyor"

# 422 — zorunluluk kurallari (YALNIZ taslak-disinda; mockup satir 69/79/85/94/95).
SITE_MANAGER_REQUIRED = "Şantiye şefi seçiniz."
CITY_REQUIRED = "İl / ilçe zorunludur."
CONSTRUCTION_AREA_REQUIRED = "İnşaat alanı zorunludur."
DATES_REQUIRED = "Başlangıç ve planlanan bitiş tarihi zorunludur."

# 422 — tutarlilik kurallari (HER ZAMAN).
END_BEFORE_START = "Planlanan bitiş tarihi başlangıçtan önce olamaz."
SAFETY_OFFICER_CONFLICT = "İSG uzmanı ya sistem kullanıcısı ya dış kaynak (OSGB) olabilir."

# `{n}` 1-TABANLIDIR: kullanici 2. satiri goruyor, 1 indeksini degil.
SECTION_END_BEFORE_START = "{n}. bölüm: bitiş tarihi başlangıçtan önce olamaz."
SECTION_NAME_REQUIRED = "{n}. bölüm: bölüm adı zorunludur."

# 409 — silme korkuluklari (spec §7.1/§7.2). Yeni istisna sinifi ACILMAZ: mevcut
# `RelatedRecordsExistError`. `DeleteNotAllowedError` KULLANILMAZ — o YETKI
# engelidir (403), bu ise kaydin DURUMUNDAN dogan bir cakismadir (409).
#
# Metinlerde ADET VERILMEZ (`BLOCK_HAS_UNITS` dersi): kullanici sayiyi zaten GET
# ile goruyor, hata govdesi gorunurluk disi bilgi tasimaz. Metinler EYLEME
# DONUKTUR ("once ... silin"), cunku korkulugun tek amaci kullaniciyi silmeden
# vazgecirmek degil, dogru siraya yonlendirmektir.
SITE_HAS_SECTIONS = "Bu şantiyede bölüm var, önce bölümleri silin"
SITE_HAS_BOQ = "Bu şantiyede iş kalemi var, önce iş kalemlerini silin"
SITE_HAS_BLOCKS = "Bu şantiyede blok var, önce blokları silin"
# Alt-Proje 2 P5 (Sözleşmeler, task C12, spec §7) — dördüncü korkuluk:
# `subcontractor_contracts.site_id` FK'si RESTRICT'tir (DB seviyesinde de
# korunur), ama korkuluksuz bırakılırsa kullanıcı anlaşılmaz "Veri bütünlüğü
# hatası" (`IntegrityError` → 409) görür — diğer üç kontrolle AYNI eyleme
# dönük Türkçe metin burada erken karşılanır.
SITE_HAS_CONTRACTS = "Bu şantiyede taşeron sözleşmesi var, önce sözleşmeleri silin"

# GPS BICIM HATASI SABITI YOKTUR (§3.5 revize karari): sunucu GPS metnini
# dogrulamaz, dolayisiyla boyle bir hata uretmez.


class _SiteLike(Protocol):
    """`validate_site`'in okudugu alanlar.

    Ozellikle `SiteCreate`'e BAGLANMAZ: T7'de PATCH'in yayina gecis dali ayni
    kurallari BIRLESIK bir kayit (mevcut satir + patch) uzerinde kosturacak.
    Somut tipe baglamak orada ikinci bir kopya kural yazmayi zorunlu kilardi.
    """

    name: str
    site_manager_user_id: object
    site_manager_name: object
    safety_officer_user_id: object
    safety_officer_is_outsourced: bool
    city: object
    construction_area_m2: object
    start_date: object
    end_date: object


def _validate_sections(data: _SiteLike) -> None:
    """Bolum satirlari — TUTARLILIK, dolayisiyla taslakta da kosar.

    ILK hatada durur: cok satirli hata listesi URETILMEZ (§8.2). Form 2-5
    satirliktir; `UnitImportError`'in satir bazli raporu (yuzlerce satirlik Excel
    icin tasarlandi) burada kullaniciya yardim etmez, yalnizca govdeyi sisirir.
    """
    for index, section in enumerate(getattr(data, "sections", None) or [], start=1):
        if not (section.name or "").strip():
            raise SiteValidationError(SECTION_NAME_REQUIRED.format(n=index))
        if (
            section.start_date is not None
            and section.end_date is not None
            and section.end_date < section.start_date
        ):
            raise SiteValidationError(SECTION_END_BEFORE_START.format(n=index))


def validate_site(data: _SiteLike, *, is_draft: bool) -> None:
    """Spec §5.1 tablosunun 11 satirini uygular.

    1/4 numarali satirlar (ad bos olamaz, tutarlar >= 0) Pydantic'te durur ve
    burada TEKRARLANMAZ — iki kopya kural zamanla ayrisir.
    5 numarali satir (GPS) icin kural YOKTUR.
    """
    # --- Tutarlilik: HER ZAMAN ---
    if (
        data.start_date is not None
        and data.end_date is not None
        and data.end_date < data.start_date
    ):
        raise SiteValidationError(END_BEFORE_START)

    if data.safety_officer_is_outsourced and data.safety_officer_user_id is not None:
        raise SiteValidationError(SAFETY_OFFICER_CONFLICT)

    _validate_sections(data)

    # --- Zorunluluk: YALNIZ taslak-disinda ---
    if is_draft:
        return

    # Sef ya sistem kullanicisi ya da serbest metin olarak verilir (P1.1a mirasi
    # `site_manager_name` hâlâ gecerli bir giristir); ikisinden biri yeter.
    if data.site_manager_user_id is None and not (data.site_manager_name or "").strip():
        raise SiteValidationError(SITE_MANAGER_REQUIRED)

    if not (data.city or "").strip():
        raise SiteValidationError(CITY_REQUIRED)

    # ISG uzmani BILINCLI OLARAK burada yok: hicbir kosulda zorunlu degildir (§13/6).

    if data.construction_area_m2 is None:
        raise SiteValidationError(CONSTRUCTION_AREA_REQUIRED)

    if data.start_date is None or data.end_date is None:
        raise SiteValidationError(DATES_REQUIRED)
