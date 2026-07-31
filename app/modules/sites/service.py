import uuid
from types import SimpleNamespace

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    DuplicateError,
    NotFoundError,
    RelatedRecordsExistError,
    SiteValidationError,
)
from app.core.timezone import today

# Denetim METINLERI merkezidir (`audit/messages.py`): f-string ne servise ne
# router'a gomulur. Silme ve yayin metinleri BURADA kurulur, cunku gereken
# baglam (silinmeden onceki ad, `is_draft`in ONCEKI degeri) yalniz servis
# katmaninda vardir.
from app.modules.audit import messages
from app.modules.projects.models import Project

# Gorunurluk suzgeci P1'den GELIR (spec §5.2). Burada kopya bir erisim mantigi
# yazilmaz: iki ayri suzgec zamanla ayrisir ve ayrisan taraf sessiz bir yetki
# sizintisi olur.
from app.modules.projects.service import visible_projects
from app.modules.sites import guards, repository
from app.modules.sites.models import Section, SectionStatus, Site, SiteStatus
from app.modules.sites.schemas import (
    CountPlaceholder,
    MetricPlaceholder,
    SectionCreate,
    SectionListResponse,
    SectionResponse,
    SectionStatusCounts,
    SectionUpdate,
    SiteCard,
    SiteCounts,
    SiteCreate,
    SiteDetailResponse,
    SiteFacilities,
    SiteFacilitiesInput,
    SiteListResponse,
    SiteListTotals,
    SiteProjectSummary,
    SiteSectionInput,
    SiteUpdate,
)
from app.modules.users.models import User

# Spec §3: bos durum alanlari ve bagli olduklari dilim anahtarlari. Bunlar
# MODUL ANAHTARIDIR, kullaniciya gosterilecek metin degil (B6 §2.3).
_PROGRESS_PAYMENTS = "progress_payments"
_TIMESHEET = "timesheet"
_SUBCONTRACTS = "subcontracts"
_PROJECT_COSTS = "project_costs"
_CONTRACTS = "contracts"
_BOQ = "boq"

# Santiye kodu oneki (spec §3.2, mockup satir 67 yer tutucusu `SNT-2026-003`).
_SITE_CODE_PREFIX = "SNT"

# ISG "Dış Kaynak — OSGB" secilince `safety_officer_name`e yazilan SABIT etiket
# (spec §3.3). Bu bir HATA METNI degil bir VERI DEGERIDIR, bu yuzden `guards.py`de
# degil burada durur. OSGB FIRMA ADI alani ICAT EDILMEZ: mockup'ta boyle bir input
# yoktur; OSGB sozlesmesi gercek bir kartoteks ihtiyacina donusurse Alt-Proje 3
# (firmalar) isidir.
_OUTSOURCED_SAFETY_OFFICER_LABEL = "Dış Kaynak — OSGB"


def _metric(pending_module: str) -> MetricPlaceholder:
    return MetricPlaceholder(pending_module=pending_module)


def _count(pending_module: str) -> CountPlaceholder:
    return CountPlaceholder(pending_module=pending_module)


async def _next_site_code(session: AsyncSession) -> str:
    """SNT-{YYYY}-{NNN} uretir (spec §3.2): o yilin en buyuk sirasi + 1, 3 hane, 1'den.

    `projects.service._next_project_code` deseninin birebiri:

    * **Sayimla DEGIL maksimum+1** — silinen kod yeniden kullanilmaz.
    * **Kapsam SIRKET GENELI**: sorgu `project_id` suzgeci TASIMAZ. Iki farkli
      projede ayni `SNT-2026-003` kullaniciyi yaniltir; kod evrakta kurumsal
      kimlik gibi okunur.
    * Sayisal soneki ayristirilamayan kodlar (canlidaki ad-turevi `A-BLOK`,
      `MERKEZ`) sessizce ATLANIR — hata uretmez, sayaci kaydirmaz. Bu kodlara
      hicbir `UPDATE` yazilmaz, yerlerinde kalirlar.

    Yaris durumunda `uq_sites_project_code` ihlali mevcut IntegrityError -> 409
    isleyicisine dusar; otomatik yeniden deneme YAPILMAZ (spec §8.3).
    """
    prefix = f"{_SITE_CODE_PREFIX}-{today().year}-"
    codes = await repository.list_codes_with_prefix(session, prefix)
    max_seq = 0
    for code in codes:
        suffix = code[len(prefix) :]
        if suffix.isdigit():
            max_seq = max(max_seq, int(suffix))
    return f"{prefix}{max_seq + 1:03d}"


def _remaining_days(site: Site) -> int | None:
    """Spec §4.2. `completed` veya `end_date` yoksa null; gecmisse NEGATIF.

    Kirpma YAPILMAZ: gecikmeyi 0'a yuvarlamak backend'in gercegi bastirmasidir,
    gecikmeyi kirmizi gostermek frontend'in isidir.
    """
    if site.status is SiteStatus.completed or site.end_date is None:
        return None
    return (site.end_date - today()).days


def _resolve_city(site: Site, project: Project) -> tuple[str | None, bool]:
    """Spec §4.3: santiye sehri bossa PROJENIN sehri doldurulur ve bayraklanir.

    Boylece frontend "Kuyubasi Mah. Ankara" satirini her zaman basabilir, null
    dallanmasi tasimaz. Ikisi de bossa devralma YOKTUR — bayrak false kalir.
    """
    if site.city:
        return site.city, False
    if project.city:
        return project.city, True
    return None, False


def _section_counts(sections: list[Section]) -> SectionStatusCounts:
    return SectionStatusCounts(
        planned=sum(1 for s in sections if s.status is SectionStatus.planned),
        active=sum(1 for s in sections if s.status is SectionStatus.active),
        completed=sum(1 for s in sections if s.status is SectionStatus.completed),
    )


def _facilities(site: Site) -> SiteFacilities:
    """DB'deki 8 duz Boolean kolonu API'nin GRUPLU sozlesmesine cevirir (§4.1).

    Donusum SERVIS katmanindadir: sema kendi basina DB bilmez.
    """
    return SiteFacilities(
        closed_warehouse=site.has_closed_warehouse,
        open_storage=site.has_open_storage,
        cold_storage=site.has_cold_storage,
        site_office=site.has_site_office,
        canteen=site.has_canteen,
        changing_room_wc=site.has_changing_room_wc,
        dormitory=site.has_dormitory,
        infirmary=site.has_infirmary,
    )


def to_section(section: Section) -> SectionResponse:
    return SectionResponse(
        id=section.id,
        code=section.code,
        name=section.name,
        status=section.status,
        manager_user_id=section.manager_user_id,
        manager_name=section.manager_name,
        start_date=section.start_date,
        end_date=section.end_date,
        sort_order=section.sort_order,
        progress_pct=_metric(_PROGRESS_PAYMENTS),
        boq_item_count=_count(_BOQ),
        budget=_metric(_BOQ),
        worker_count=_count(_TIMESHEET),
    )


def _card_fields(site: Site, project: Project) -> dict:
    city, city_inherited = _resolve_city(site, project)
    return {
        "id": site.id,
        "code": site.code,
        "name": site.name,
        "status": site.status,
        "address": site.address,
        "city": city,
        "city_inherited": city_inherited,
        "site_manager_name": site.site_manager_name,
        "start_date": site.start_date,
        "end_date": site.end_date,
        "delivery_date": site.delivery_date,
        "remaining_days": _remaining_days(site),
        "section_count": len(site.sections),
        "worker_count": _count(_TIMESHEET),
        "progress_pct": _metric(_PROGRESS_PAYMENTS),
        # --- Santiye formu genislemesi (§6.2): YALNIZ EKLEME ---
        "is_draft": site.is_draft,
        "site_manager_user_id": site.site_manager_user_id,
        "safety_officer_user_id": site.safety_officer_user_id,
        "safety_officer_name": site.safety_officer_name,
        "safety_officer_is_outsourced": site.safety_officer_is_outsourced,
        "neighborhood": site.neighborhood,
        "parcel": site.parcel,
        "gps_coordinates": site.gps_coordinates,
        "land_area_m2": site.land_area_m2,
        "construction_area_m2": site.construction_area_m2,
        "floor_info": site.floor_info,
        "budget": site.budget,
        "facilities": _facilities(site),
        "electricity_subscription_no": site.electricity_subscription_no,
        "water_subscription_no": site.water_subscription_no,
        "planned_worker_count": site.planned_worker_count,
    }


def to_card(site: Site, project: Project) -> SiteCard:
    return SiteCard(**_card_fields(site, project))


def to_detail(site: Site, project: Project) -> SiteDetailResponse:
    sections = list(site.sections)
    return SiteDetailResponse(
        **_card_fields(site, project),
        project=SiteProjectSummary.model_validate(project),
        section_status_counts=_section_counts(sections),
        sections=[to_section(s) for s in sections],
        total_progress_payment=_metric(_PROGRESS_PAYMENTS),
        contract_amount=_metric(_CONTRACTS),
    )


def _totals() -> SiteListTotals:
    """Alt KPI seridi — bu dilimde TAMAMI yer tutucu (spec §4.1)."""
    return SiteListTotals(
        total_progress_payment=_metric(_PROGRESS_PAYMENTS),
        subcontractor_count=_count(_SUBCONTRACTS),
        active_worker_count=_count(_TIMESHEET),
        average_margin=_metric(_PROJECT_COSTS),
    )


def _site_counts(sites: list[Site]) -> SiteCounts:
    return SiteCounts(
        all=len(sites),
        active=sum(1 for s in sites if s.status is SiteStatus.active),
        on_hold=sum(1 for s in sites if s.status is SiteStatus.on_hold),
        completed=sum(1 for s in sites if s.status is SiteStatus.completed),
        # §5.2: TEK ekleme. Taslaklar durum sayaclarindan DUSULMEZ — durumlari
        # ne ise o sayilir; bu sayac ayrica artar.
        draft=sum(1 for s in sites if s.is_draft),
    )


# --- Gorunurluk (spec §5.2) ---

# 404 GOVDESI DE AYIRT EDICI OLMAMALIDIR. Durum kodunun 404 olmasi tek basina
# yetmez: gorunmeyen bir projedeki GERCEK santiye icin "Proje bulunamadı",
# var olmayan santiye icin "Şantiye bulunamadı" donerse, elinde bir UUID olan
# kullanici kaydin hala var oldugunu ve baska bir projeye ait oldugunu ayirt
# edebilir. Bu yuzden ISTENEN kaynagin mesaji zincir boyunca TASINIR: santiye
# ucunda hem "yok" hem "gormuyorsun" ayni cevabi verir.
#
# Metinler T5'te `guards.py`'ye TASINDI (spec §7.2 tablosu tek yerde durur);
# burada yalniz yerel takma adlar kalir — iki kopya metin zamanla ayrisir.
_PROJECT_MISSING = guards.PROJECT_MISSING
_SITE_MISSING = guards.SITE_MISSING
_SECTION_MISSING = guards.SECTION_MISSING


async def _visible_project(
    session: AsyncSession, actor: User, project_id: uuid.UUID, missing: str = _PROJECT_MISSING
) -> Project:
    """Kullanici projeyi goremiyorsa 404 — 403 DEGIL: varligin kendisi sizdirilmaz."""
    visible = await visible_projects(session, actor)
    project = next((p for p in visible if p.id == project_id), None)
    if project is None:
        raise NotFoundError(missing)
    return project


async def _visible_site(
    session: AsyncSession, actor: User, site_id: uuid.UUID, missing: str = _SITE_MISSING
) -> tuple[Site, Project]:
    """Santiye -> proje cozumu, ardindan ayni gorunurluk suzgeci."""
    site = await repository.get_site(session, site_id)
    if site is None:
        raise NotFoundError(missing)
    project = await _visible_project(session, actor, site.project_id, missing)
    return site, project


async def _visible_section(
    session: AsyncSession, actor: User, section_id: uuid.UUID
) -> tuple[Section, Site]:
    """Bolum -> santiye -> proje. EN KOLAY ATLANACAK GUVENLIK NOKTASI (spec §5.2):
    bolum kimligi ile dolayli erisim de proje suzgecinden gecmek zorundadir."""
    section = await repository.get_section(session, section_id)
    if section is None:
        raise NotFoundError(_SECTION_MISSING)
    site, _ = await _visible_site(session, actor, section.site_id, _SECTION_MISSING)
    return section, site


# --- Okuma uclari ---


async def list_sites_overview(
    session: AsyncSession, actor: User, project_id: uuid.UUID
) -> SiteListResponse:
    project = await _visible_project(session, actor, project_id)
    sites = await repository.list_sites_for_project(session, project_id)
    return SiteListResponse(
        counts=_site_counts(sites),
        items=[to_card(site, project) for site in sites],
        totals=_totals(),
    )


async def get_site_detail(
    session: AsyncSession, actor: User, site_id: uuid.UUID
) -> SiteDetailResponse:
    site, project = await _visible_site(session, actor, site_id)
    return to_detail(site, project)


async def list_sections_for_site(
    session: AsyncSession, actor: User, site_id: uuid.UUID
) -> SectionListResponse:
    site, _ = await _visible_site(session, actor, site_id)
    sections = await repository.list_sections(session, site.id)
    return SectionListResponse(
        counts=_section_counts(sections), items=[to_section(s) for s in sections]
    )


# --- Yazma uclari ---


async def _resolve_user_name(session: AsyncSession, user_id: uuid.UUID) -> str:
    """Verilen kullanicinin `full_name` anlik goruntusunu doner (spec §9).

    Yok ya da pasifse 422 — 404 DEGIL: istenen kaynak santiyedir, kullanici
    burada bir ALAN DEGERIDIR. 404 donmek "bu UUID'li kullanici yok" bilgisini
    santiye ucundan sizdirmak olurdu.

    IZINLI (`on_leave`) personel ATANABILIR: gerekcesi
    `repository.get_assignable_user` docstring'inde (karar 2026-07-30).
    """
    user = await repository.get_assignable_user(session, user_id)
    if user is None:
        raise SiteValidationError(guards.USER_NOT_FOUND)
    return user.full_name


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


def _merged_for_validation(site: Site, changes: dict) -> SimpleNamespace:
    """Mevcut satir + patch = dogrulamanin gordugu kayit (§5.3).

    Yalniz patch'i dogrulamak yanlis olurdu: `end_date` gonderilip `start_date`
    satirda duruyorsa ters tarih araligi FARK EDILMEDEN gecerdi. Yalniz satiri
    dogrulamak da yanlis olurdu: yayina gecirirken eksik alani AYNI istekte
    gonderen kullanici haksiz yere reddedilirdi.

    `sections` bilincli olarak BOSTUR: bolumler PATCH govdesinde YOKTUR (§7.3),
    mevcut bolumleri yeniden dogrulamak ise bu istegin isi degildir.
    """
    merged = {field: changes.get(field, getattr(site, field)) for field in _VALIDATED_FIELDS}
    return SimpleNamespace(**merged, sections=[])


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
    guards.validate_site(_merged_for_validation(site, changes), is_draft=not is_publishing)
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
        merged = _merged_for_validation(site, changes)
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


async def create_section(
    session: AsyncSession, actor: User, site_id: uuid.UUID, data: SectionCreate
) -> Section:
    site, _ = await _visible_site(session, actor, site_id)
    # FK verilmisse ad govdedeki serbest metnin UZERINE yazilir (create_site ile
    # ayni kural): ad FK'nin turevidir, ikinci bir gercek kaynak degildir.
    manager_name = data.manager_name
    if data.manager_user_id is not None:
        manager_name = await _resolve_user_name(session, data.manager_user_id)
    section = Section(
        site_id=site.id,
        code=data.code,
        name=data.name,
        status=data.status,
        manager_user_id=data.manager_user_id,
        manager_name=manager_name,
        start_date=data.start_date,
        end_date=data.end_date,
        sort_order=data.sort_order,
    )
    session.add(section)
    await session.flush()
    await session.refresh(section)
    return section


async def update_section(
    session: AsyncSession, actor: User, section_id: uuid.UUID, data: SectionUpdate
) -> Section:
    section, _ = await _visible_section(session, actor, section_id)
    changes = data.model_dump(exclude_unset=True)
    if changes.get("manager_user_id") is not None:
        changes["manager_name"] = await _resolve_user_name(session, changes["manager_user_id"])
    for field, value in changes.items():
        setattr(section, field, value)
    await session.flush()
    await session.refresh(section)
    return section


# --- Silme uclari (spec §7.1) ---


async def delete_site(session: AsyncSession, actor: User, site_id: uuid.UUID) -> str:
    """Spec §7.1. **CASCADE'i ENGELLEMEK bu fonksiyonun TEK isidir.**

    `sites.id`'yi hedefleyen DORT FK'nin da `ON DELETE CASCADE` oldugu koddan
    dogrulandi (`sections`, `boq_groups`, `boq_items`, `blocks`). Yani DB
    KENDILIGINDEN KORUMAZ: asagidaki uc kontrol kaldirilirsa tek bir istek
    bolumleri, poz gruplarini, poz kalemlerini ve bloklari SESSIZCE yok eder ve
    bu GERI ALINAMAZ. `delete_block` (`units/service.py:307`) deseninin
    birebiridir, tek farkla: orada DB'de `RESTRICT` ikinci katman olarak vardi,
    BURADA YOKTUR — servis korkulugu TEK savunmadir.

    Sira sabittir ve ILK ENGELDE DURUR: bolum -> poz -> blok. Kullaniciya tek,
    eyleme donuk mesaj verilir; uc engeli birden listelemek onu ayni formda uc
    kez geri gonderirdi.

    Taslak santiye icin AYRICALIK YOKTUR: bolumlu bir taslak da 409 doner.
    "Taslak zaten yarim, gitsin" kisayolu taslak/yayin ayrimini silme
    guvenliginin onune gecirirdi.

    Donen deger: DENETIM METNI. Metin `session.delete`ten ONCE kurulur
    (`units/service.py:327` dersi) — satir gittikten sonra `project.name` ve
    `site.name` guvenilir okunamaz ve denetim satiri bos adla yazilirdi, yani
    silinen kaydin NE OLDUGU tamamen kaybolurdu.

    Engellenen silme (409) denetime HICBIR SEY yazmaz: bu fonksiyon istisna
    atarak doner, metin hic kurulmaz. Denetim gerceklesen olayi kaydeder,
    denemeyi degil.
    """
    site, project = await _visible_site(session, actor, site_id)
    if await repository.site_has_sections(session, site.id):
        raise RelatedRecordsExistError(guards.SITE_HAS_SECTIONS)
    if await repository.site_has_boq(session, site.id):
        raise RelatedRecordsExistError(guards.SITE_HAS_BOQ)
    if await repository.site_has_blocks(session, site.id):
        raise RelatedRecordsExistError(guards.SITE_HAS_BLOCKS)
    if await repository.site_has_contracts(session, site.id):
        raise RelatedRecordsExistError(guards.SITE_HAS_CONTRACTS)
    if await repository.site_has_progress_payment_lines(session, site.id):
        raise RelatedRecordsExistError(guards.SITE_HAS_PROGRESS_PAYMENTS)
    detail = messages.site_deleted(project.name, site.name)
    await session.delete(site)
    await session.flush()
    return detail


async def delete_section(session: AsyncSession, actor: User, section_id: uuid.UUID) -> str:
    """Spec §7.1. Bolum silme KOSULSUZDUR — uydurma bir engel yazilmaz.

    Kod tabaninda `sections.id`'yi hedefleyen HICBIR FK yoktur (dogrulandi):
    bolumun bugun bagli alt kaydi OLAMAZ. `delete_site`in uc korkulugunun bir
    benzerini buraya "ihtiyatli olsun diye" eklemek, var olmayan bir bagi
    kullaniciya kural gibi gostermek olurdu.

    # P5 notu: `boq_groups.section_id` gelirse buraya `section_has_boq`
    # korkulugu EKLENMELIDIR (spec §7.1 acik talebi). O bag acildigi anda bu
    # fonksiyon kosulsuz olmaktan cikar; korkuluksuz birakilirsa bolum silmek
    # poz gruplarini sessizce goturur.

    Gorunurluk suzgeci ONCE kosar (`_visible_section`: bolum -> santiye ->
    proje): gorunmeyen bolum 404 `Bölüm bulunamadı` doner ve govdesi var
    olmayan UUID'ninkiyle BIREBIR AYNIDIR.

    Kalan bolumlerin `sort_order` degerleri YENIDEN NUMARALANMAZ (davranis
    kilidi): silme, dokunulmayan satirlarin sirasini degistirmez.

    Donen deger: DENETIM METNI — `delete_site` ile ayni gerekce, metin satir yok
    olmadan ONCE kurulur.
    """
    section, site = await _visible_section(session, actor, section_id)
    detail = messages.section_deleted(site.name, section.name)
    await session.delete(section)
    await session.flush()
    return detail
