"""Santiye yazma uclari: `create_site` (POST) + `update_site` (PATCH)."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DuplicateError

# Denetim METINLERI merkezidir (`audit/messages.py`): f-string ne servise ne
# router'a gomulur. Silme ve yayin metinleri BURADA kurulur, cunku gereken
# baglam (silinmeden onceki ad, `is_draft`in ONCEKI degeri) yalniz servis
# katmaninda vardir.
from app.modules.audit import messages
from app.modules.sites import guards, repository
from app.modules.sites.models import Section, Site
from app.modules.sites.schemas import (
    SiteCreate,
    SiteFacilitiesInput,
    SiteSectionInput,
    SiteUpdate,
)
from app.modules.sites.service.codes import _next_site_code
from app.modules.sites.service.visibility import _visible_project, _visible_site
from app.modules.sites.service.writes_common import _merged_for_validation, _resolve_user_name
from app.modules.users.models import User

# ISG "Dış Kaynak — OSGB" secilince `safety_officer_name`e yazilan SABIT etiket
# (spec §3.3). Bu bir HATA METNI degil bir VERI DEGERIDIR, bu yuzden `guards.py`de
# degil burada durur. OSGB FIRMA ADI alani ICAT EDILMEZ: mockup'ta boyle bir input
# yoktur; OSGB sozlesmesi gercek bir kartoteks ihtiyacina donusurse Alt-Proje 3
# (firmalar) isidir.
_OUTSOURCED_SAFETY_OFFICER_LABEL = "Dış Kaynak — OSGB"


def _apply_facilities(site: Site, facilities: SiteFacilitiesInput) -> None:
    """GRUPLU API sozlesmesini SEKIZ duz Boolean kolona yazar (spec §4.1).

    Donusum SERVIS katmanindadir (`_facilities` okuma yonunun aynasi): sema
    kendi basina DB bilmez, model kendi basina API sozlesmesini bilmez.
    """
    site.has_closed_warehouse = facilities.closed_warehouse
    site.has_open_storage = facilities.open_storage
    site.has_cold_storage = facilities.cold_storage
    site.has_site_office = facilities.site_office
    site.has_canteen = facilities.canteen
    site.has_changing_room_wc = facilities.changing_room_wc
    site.has_dormitory = facilities.dormitory
    site.has_infirmary = facilities.infirmary


async def _resolve_safety_officer(
    session: AsyncSession, user_id: uuid.UUID | None, is_outsourced: bool
) -> str | None:
    """ISG uzmani adinin anlik goruntusu (spec §3.3).

    Uc gecerli dal vardir: sistem kullanicisi · dis kaynak (OSGB) · HICBIRI.
    Karsilikli dislama `guards.validate_site`te (ve DB `CHECK`'inde) tutulur,
    burada TEKRARLANMAZ.
    """
    if user_id is not None:
        return await _resolve_user_name(session, user_id)
    if is_outsourced:
        return _OUTSOURCED_SAFETY_OFFICER_LABEL
    return None


async def _resolve_section_manager_names(
    session: AsyncSession, sections: list[SiteSectionInput]
) -> list[str | None]:
    """Bolum seflerinin ad anlik goruntulerini HICBIR SEY YAZILMADAN ONCE cozer.

    Bu cagri 422 (`Seçilen kullanıcı bulunamadı`) uretebilir, dolayisiyla adim 3'e
    (kullanici cozumu) aittir, adim 6'ya (yazma) DEGIL. Yazma dongusunun icinde
    kalsaydi santiye satiri ve onceki bolumler session'a girmis olurdu ve kismi
    yazimin geri alinmasi TEK BASINA istek transaction'ina kalirdi; §8.2'nin
    "dogrulama yazmadan ONCE, tek seferde" kurali servis katmaninda da gecerlidir.
    """
    return [
        await _resolve_user_name(session, row.manager_user_id)
        if row.manager_user_id is not None
        else None
        for row in sections
    ]


def _write_sections(
    session: AsyncSession,
    site: Site,
    sections: list[SiteSectionInput],
    manager_names: list[str | None],
) -> None:
    """Form ici bolum satirlarini yazar. `sort_order` DIZI SIRASINDAN atanir (§6.1).

    Dogrulama ve kullanici cozumu BURADA yapilmaz: `guards.validate_site` tum
    satirlari, `_resolve_section_manager_names` ise tum sefleri HICBIR SEY
    yazilmadan once denetledi (§8.2). Bu ayrim atomikligin ta kendisidir — satir
    yazarken dogrulamak, ilk hatada onceki satirlari session'a girmis halde
    birakirdi. Bu yuzden fonksiyon `async` bile DEGILDIR: icinde bekleyen tek bir
    G/C islemi kalmamistir.
    """
    for index, (row, manager_name) in enumerate(zip(sections, manager_names, strict=True)):
        session.add(
            Section(
                site_id=site.id,
                code=row.code,
                name=row.name,
                manager_user_id=row.manager_user_id,
                manager_name=manager_name,
                start_date=row.start_date,
                end_date=row.end_date,
                sort_order=index,
            )
        )


async def create_site(
    session: AsyncSession, actor: User, project_id: uuid.UUID, data: SiteCreate
) -> Site:
    """Spec §8.1'in dokuz adimi, O SIRAYLA.

    ATOMIKLIK (§8.2): `get_db` istek basina TEK transaction acar; herhangi bir
    adimda istisna -> rollback -> HICBIR satir yazilmaz. Kismi basari mumkun
    degildir: santiye yazilip bolum patlarsa santiye de geri alinir. Bunun sarti
    dogrulamanin ve kullanici cozumunun YAZMADAN ONCE bitmis olmasidir; bu yuzden
    1-4 arasi adimlarda `session.add` YOKTUR.
    """
    # 1. Gorunur proje suzgeci -> yoksa 404 (govde ayirt edici DEGIL).
    await _visible_project(session, actor, project_id)
    # 2. Taslak-farkindalikli dogrulama (santiye + TUM bolum satirlari) -> 422.
    guards.validate_site(data, is_draft=data.is_draft)
    # 3. Sef/ISG kullanici cozumu -> 422. FK doluysa ad anlik goruntusu govdedeki
    #    serbest metnin UZERINE yazilir (`projects.employer_name` deseni).
    site_manager_name = data.site_manager_name
    if data.site_manager_user_id is not None:
        site_manager_name = await _resolve_user_name(session, data.site_manager_user_id)
    safety_officer_name = await _resolve_safety_officer(
        session, data.safety_officer_user_id, data.safety_officer_is_outsourced
    )
    #    Bolum sefleri de BURADA cozulur (yazma dongusunde DEGIL): 422 ureten her
    #    adim, ilk `session.add`den once bitmis olmalidir.
    section_manager_names = await _resolve_section_manager_names(session, data.sections)
    # 4. Kod uretimi (bossa) + cakisma on-kontrolu -> 409 alanina ozel Turkce mesajla.
    code = data.code or await _next_site_code(session)
    if await repository.get_site_by_code(session, project_id, code) is not None:
        raise DuplicateError(guards.DUPLICATE_SITE_CODE)
    # 5. Santiye satiri.
    site = Site(
        project_id=project_id,
        code=code,
        name=data.name,
        status=data.status,
        site_manager_user_id=data.site_manager_user_id,
        site_manager_name=site_manager_name,
        safety_officer_user_id=data.safety_officer_user_id,
        safety_officer_name=safety_officer_name,
        safety_officer_is_outsourced=data.safety_officer_is_outsourced,
        city=data.city,
        neighborhood=data.neighborhood,
        parcel=data.parcel,
        address=data.address,
        gps_coordinates=data.gps_coordinates,
        land_area_m2=data.land_area_m2,
        construction_area_m2=data.construction_area_m2,
        floor_info=data.floor_info,
        start_date=data.start_date,
        end_date=data.end_date,
        delivery_date=data.delivery_date,
        budget=data.budget,
        electricity_subscription_no=data.electricity_subscription_no,
        water_subscription_no=data.water_subscription_no,
        planned_worker_count=data.planned_worker_count,
        is_draft=data.is_draft,
    )
    _apply_facilities(site, data.facilities)
    session.add(site)
    await session.flush()
    # 6-7. Bolumler + tek flush (benzersizlik ihlali -> 409 emniyet agi).
    _write_sections(session, site, data.sections, section_manager_names)
    await session.flush()
    await session.refresh(site)
    return site


# `guards.validate_site`in okudugu alanlar (`_SiteLike`). PATCH bunlarin BIRLESIK
# degerini kurar: gonderilen alan patch'ten, gonderilmeyen MEVCUT SATIRDAN gelir.
_VALIDATED_FIELDS = (
    "name",
    "site_manager_user_id",
    "site_manager_name",
    "safety_officer_user_id",
    "safety_officer_is_outsourced",
    "city",
    "construction_area_m2",
    "start_date",
    "end_date",
)


async def update_site(
    session: AsyncSession, actor: User, site_id: uuid.UUID, data: SiteUpdate
) -> tuple[Site, str]:
    """PATCH GEVSEK, YAYIN SIKI (§5.3, §11.3/3).

    Zorunluluk dogrulamasi burada KOSMAZ — kossaydi canlidaki sefsiz/il bilgisi
    olmayan eski santiyeler duzenlenemez hale gelirdi ve kullanici yalnizca adi
    degistirmek isterken "Şantiye şefi seçiniz." duvarina carpardi. Tek istisna
    `is_draft: true -> false` gecisidir: orada BIRLESIK kayit uzerinde tum
    kurallar kosar ve gecmezse satir TASLAK KALIR.

    Denetim metnini de DONER (`units.update_unit` deseni): yayina gecis olup
    olmadigi yalniz BURADA bilinir — router `is_draft`in ONCEKI degerini goremez,
    dolayisiyla ayrimi disariya tasimak "Şantiye güncellendi" ile "yayına alındı"
    satirlarini birbirine karistirirdi.
    """
    site, _ = await _visible_site(session, actor, site_id)
    # `facilities` DISARIDA BIRAKILIR: gruplu sozlesmenin duz kolon karsiligi yok,
    # duz `setattr` ORM nesnesine BASIBOS bir oznitelik yazar ve DB'ye hicbir sey
    # gitmez — hata da vermez. Sessiz veri kaybi sinifi; asagida acikca eslenir.
    changes = data.model_dump(exclude_unset=True, exclude={"facilities"})
    # Yayina gecis YALNIZCA taslak bir satir icin tanimlidir; `false -> false`
    # bir gecis degildir ve zorunluluk kurallarini tetiklemez.
    is_publishing = site.is_draft and changes.get("is_draft") is False
    guards.validate_site(
        _merged_for_validation(site, changes, _VALIDATED_FIELDS, sections=[]),
        is_draft=not is_publishing,
    )
    # Kod cakismasi ON KONTROLU — POST'takiyle AYNI Turkce mesaj (karar 2026-07-30).
    # Onceden bu dal `uq_sites_project_code` -> IntegrityError'a dusuyor ve genel
    # "Veri bütünlüğü hatası" doniyordu; kullanici hangi ALANIN sorunlu oldugunu
    # goremiyordu. `exclude_site_id` sarttir: kendi kodunu yeniden gondermek
    # cakisma DEGILDIR, aksi hâlde formun tum alanlarini birlikte gonderen her
    # PATCH 409 verirdi. Kisit YARIS DURUMU emniyet agi olarak KALIR (§8.3).
    if "code" in changes and changes["code"] != site.code:
        clash = await repository.get_site_by_code(
            session, site.project_id, changes["code"], exclude_site_id=site.id
        )
        if clash is not None:
            raise DuplicateError(guards.DUPLICATE_SITE_CODE)
    # Kullanici cozumu YAZMADAN ONCE: gecersiz kullanici hicbir alani degistirmez.
    if changes.get("site_manager_user_id") is not None:
        changes["site_manager_name"] = await _resolve_user_name(
            session, changes["site_manager_user_id"]
        )
    if "safety_officer_user_id" in changes or "safety_officer_is_outsourced" in changes:
        merged = _merged_for_validation(site, changes, _VALIDATED_FIELDS, sections=[])
        changes["safety_officer_name"] = await _resolve_safety_officer(
            session, merged.safety_officer_user_id, merged.safety_officer_is_outsourced
        )
    for field, value in changes.items():
        setattr(site, field, value)
    if data.facilities is not None:
        _apply_facilities(site, data.facilities)
    await session.flush()
    await session.refresh(site)
    detail = (
        messages.site_published(site.name) if is_publishing else messages.site_updated(site.name)
    )
    return site, detail
