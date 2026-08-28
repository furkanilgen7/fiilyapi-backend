"""Puantaj kapsam kararları + toplu DEĞİŞTİRME (spec §3, §7 S4).

İKİ KATMANLI koruma (`site_diary/service.py` deseninin birebiri): `timesheet`
izni router'da YETKİYİ verir (saha mühendisi `view` → PUT'ta 403), bu modül
`projects.service.visible_projects` ile KAPSAMI belirler. Görünmeyen projedeki
GERÇEK şantiye ile var OLMAYAN kimlik AYIRT EDİLEMEZ 404 döner.

## ⚠️ Kapsam sınırı — bu dosyanın en kritik kuralı

Silme koşulu `site_id = <şantiye> AND work_date ∈ [haftanın Pazartesisi,
haftanın Pazarı]` üçlüsüdür ve tek yerden (`repository.week_bounds`) gelir.

🔴 **PUAN-SAAT: kapsam AYDAN HAFTAYA DARALDI.** Ekran artık haftalık kaydeder
(mockup E5 76 "Haftayı Kaydet"). Koşul ay kapsamında bırakılsaydı **bir haftayı
kaydetmek ayın geri kalanını SİLERDİ** — geri alınamaz veri kaybı. Koşulun
herhangi bir parçası düşerse aynı felaket komşu hafta ya da komşu şantiye için
doğar. Bekçi: `tests/timesheet/test_week_save.py`, POZİTİF KONTROLÜYLE birlikte
(aynı ayın başka bir haftasındaki hücre HAYATTA KALMALIDIR — yoksa "her şeyi
silen" bozuk bir uç da testi yeşil geçerdi).

## Sıra — ÖNCE TÜM DOĞRULAMALAR, SONRA TEK YAZMA

`site_diary/lines.py` kuralının aynısı: ikinci hücrede patlayan istek birincisini
session'a eklemiş OLMAMALIDIR (kısmi yazma yok).

## Onay akışı YOKTUR (spec §7 S3)

Mockup'ta yalnız "Haftayı Kaydet" vardır (E5 76). `submit`/`approve` geçişi, durum
kolonu ya da kilitleme AÇILMAZ — denetim izi yeterlidir. Sonraki okuyucu buraya
durum makinesi EKLEMESİN.
"""

import uuid
from datetime import date
from typing import NamedTuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, DuplicateError, NotFoundError, SiteValidationError
from app.modules.personnel.models import Personnel
from app.modules.projects.models import Project
from app.modules.projects.service import visible_projects
from app.modules.sites import repository as sites_repository
from app.modules.sites.models import Section, Site
from app.modules.timesheet import guards, repository
from app.modules.timesheet.models import TimesheetEntry
from app.modules.timesheet.schemas import TimesheetCellInput, TimesheetWeekSave
from app.modules.users.models import User

PERMISSION_MODULE = "timesheet"
"""Seed'de HAZIR (satır 171): şef `full`, saha mühendisi `view`. Matris DEĞİŞMEZ."""


class SiteContext(NamedTuple):
    """Kapsam süzgecinden geçmiş şantiye + projesi."""

    site: Site
    project: Project


# --- Kapsam ---


async def visible_site(session: AsyncSession, actor: User, site_id: uuid.UUID) -> SiteContext:
    """Şantiye → proje. Görünmeyen projenin şantiyesi ile var olmayan şantiye AYNI
    404 gövdesini döner; metin `sites` modülünün TEK cümlesidir (kopya üretilmez)."""
    site = await sites_repository.get_site(session, site_id)
    if site is None:
        raise NotFoundError(guards.SITE_MISSING)
    visible = await visible_projects(session, actor)
    project = next((p for p in visible if p.id == site.project_id), None)
    if project is None:
        raise NotFoundError(guards.SITE_MISSING)
    return SiteContext(site=site, project=project)


async def visible_section(
    session: AsyncSession, site: Site, section_id: uuid.UUID | None
) -> Section | None:
    """Okuma süzgecinin bölümü (ŞP 99). Başka şantiyenin bölümü **404**tür.

    Boş matris dönmek, kullanıcıya "o bölümde kimse çalışmamış" YALANINI
    söylerdi; var olmayan bölümle aynı 404 ise kimlik varlığını sızdırmaz.
    """
    if section_id is None:
        return None
    section = await sites_repository.get_section(session, section_id)
    if section is None or section.site_id != site.id:
        raise NotFoundError(guards.SECTION_MISSING)
    return section


# --- Gövde doğrulaması (hiçbir şey YAZMAZ) ---


class _Plan(NamedTuple):
    """Doğrulaması BİTMİŞ kaydetme planı — henüz hiçbir şey yazılmadı."""

    cells: dict[tuple[uuid.UUID, date], TimesheetCellInput]
    personnel: dict[uuid.UUID, Personnel]


def _assert_week(cell: TimesheetCellInput, iso_year: int, iso_week: int) -> None:
    """Hücre kaydedilen HAFTANIN içinde mi? Değilse 422 — sessizce yazılmaz.

    Saat/kod ikilisinin doğrulaması burada YOKTUR: onu `TimesheetCellInput`
    şeması alan yoluyla birlikte reddeder, asıl bekçi ise DB CHECK'idir.
    """
    start, end = repository.week_bounds(iso_year, iso_week)
    if not (start <= cell.work_date <= end):
        raise SiteValidationError(
            guards.format_out_of_week(cell.work_date, iso_year, iso_week, start, end)
        )


async def _assert_sections(session: AsyncSession, site: Site, section_ids: set[uuid.UUID]) -> None:
    """Bölüm bilgi alanıdır ama SAHİPSİZ olamaz: hücrenin ŞANTİYESİNE ait olmalı.

    Yazmada 422'dir (okumadaki 404 değil): burada bölüm bir SÜZGEÇ değil gövdenin
    düzeltilebilir bir ALANIDIR (`site_diary` `SECTION_MISMATCH` deseni).
    """
    if not section_ids:
        return
    for section_id in section_ids:
        section = await sites_repository.get_section(session, section_id)
        if section is None or section.site_id != site.id:
            raise SiteValidationError(guards.SECTION_MISMATCH)


async def _plan(
    session: AsyncSession, site: Site, data: TimesheetWeekSave, *, iso_year: int, iso_week: int
) -> _Plan:
    cells: dict[tuple[uuid.UUID, date], TimesheetCellInput] = {}
    for cell in data.cells:
        _assert_week(cell, iso_year, iso_week)
        key = guards.cell_key(cell.personnel_id, cell.work_date)
        if key in cells:
            # Kismi UQ ihlali GOVDE ICINDE yakalanir; `IntegrityError` emniyet agi kalir.
            raise DuplicateError(guards.DUPLICATE_CELL)
        cells[key] = cell

    personnel = await repository.get_personnel_by_ids(
        session, [cell.personnel_id for cell in data.cells]
    )
    if any(cell.personnel_id not in personnel for cell in data.cells):
        # Var OLMAYAN personel ile silinmis kayit AYNI 422'yi alir.
        raise SiteValidationError(guards.PERSONNEL_UNKNOWN)

    await _assert_sections(
        session, site, {cell.section_id for cell in data.cells if cell.section_id is not None}
    )
    return _Plan(cells=cells, personnel=personnel)


async def _assert_person_days_free(session: AsyncSession, site: Site, plan: _Plan) -> None:
    """UQ (personnel_id, work_date) — kişi bir günde TEK şantiyededir (spec §2).

    Dönem kapsamındaki satırlar kilitlidir; BAŞKA şantiyedeki satırlar değildir,
    bu yüzden burası bir yarış penceresi bırakır. Pencere `IntegrityError` → 409
    handler'ıyla kapanır; buradaki açık SELECT'in işi kullanıcıya HANGİ personelin
    HANGİ günü çakıştığını söylemektir.
    """
    conflicts = await repository.conflicting_entries(
        session, list(plan.cells), exclude_site_id=site.id
    )
    if not conflicts:
        return
    first = min(conflicts, key=lambda entry: (entry.work_date, str(entry.personnel_id)))
    personnel = plan.personnel[first.personnel_id]
    raise ConflictError(guards.person_day_conflict(personnel.full_name, first.work_date))


# --- Yazma ---


def _apply(
    site: Site, existing: list[TimesheetEntry], plan: _Plan, actor: User
) -> tuple[list[TimesheetEntry], list[uuid.UUID]]:
    """DEĞİŞTİRME: mevcut hücre GÜNCELLENİR, eksik olan silinir, yeni olan eklenir.

    Mevcut satırın KİMLİĞİ korunur (sil + yeniden yaz DEĞİL): aksi hâlde her
    kaydetme `created_by`yi ve kaydın yaşını sıfırlar, üstelik aynı transaction
    içinde silinen ve eklenen satır UQ üzerinde gereksiz yere yarışırdı.
    """
    by_key = {guards.cell_key(row.personnel_id, row.work_date): row for row in existing}
    yeniler: list[TimesheetEntry] = []

    for key, cell in plan.cells.items():
        row = by_key.get(key)
        if row is None:
            yeniler.append(
                TimesheetEntry(
                    personnel_id=cell.personnel_id,
                    site_id=site.id,
                    # Kapsam alani SANTIYEDEN kopyalanir, govdeden ASLA.
                    project_id=site.project_id,
                    section_id=cell.section_id,
                    work_date=cell.work_date,
                    hours=cell.hours,
                    code=cell.code,
                    created_by=actor.id,
                )
            )
        else:
            # Hucre govdedeki haline ESITLENIR: saatli hucre kodluya (ya da tersi)
            # cevrildiginde eski alan NULL'a duser, "sessizce" kalmaz — kalsaydi
            # DB'nin saat-XOR-kod CHECK'i satiri reddederdi.
            row.hours = cell.hours
            row.code = cell.code
            row.section_id = cell.section_id

    silinecekler = [row.id for key, row in by_key.items() if key not in plan.cells]
    return yeniler, silinecekler


async def save_week(
    session: AsyncSession,
    actor: User,
    context: SiteContext,
    data: TimesheetWeekSave,
    *,
    iso_year: int,
    iso_week: int,
) -> int:
    """**Hafta**+şantiye kapsamını gövdeye eşitler; yazılan hücre sayısını döner.

    Kapsam kararı (404) kilitten ÖNCE verilmiştir (`visible_site`, router'da):
    görünmeyen şantiyenin satırları boşuna kilitlenmez.
    """
    site = context.site
    plan = await _plan(session, site, data, iso_year=iso_year, iso_week=iso_week)

    existing = await repository.locked_week_entries(
        session, site.id, iso_year=iso_year, iso_week=iso_week
    )
    await _assert_person_days_free(session, site, plan)

    # --- Buradan itibaren yazma; dogrulama YOK (yukaridaki sira kisiti). ---
    yeniler, silinecekler = _apply(site, existing, plan, actor)
    await repository.delete_entries(session, silinecekler)
    session.add_all(yeniler)
    await session.flush()
    return len(plan.cells)
