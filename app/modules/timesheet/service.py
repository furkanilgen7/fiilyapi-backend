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

## Gün KİLİDİ (PLN-B2.1, B2-6) — onay akışı DEĞİL, port

Rapor onayı o tarihe kadar günlüğü VE puantajı kilitler (planlama spec §2). Karar
çekirdeğin değil kayıtlı modülündür (`app.core.day_hooks`, kayıt yoksa no-op).
🔴 Port YALNIZ GERÇEKTEN DEĞİŞEN günleri sorar (`_changed_days`): gövde haftanın
TAM kümesidir, yani kilitli bir günü içeren haftanın kilitsiz bir gününü
düzeltmek, kilitli günü AYNEN geri göndermeyi gerektirir — bütün hafta sorulsaydı
kilitli tek gün bütün haftayı dondururdu.

## Onay akışı YOKTUR (spec §7 S3)

Mockup'ta yalnız "Haftayı Kaydet" vardır (E5 76). `submit`/`approve` geçişi, durum
kolonu ya da kilitleme AÇILMAZ — denetim izi yeterlidir. Sonraki okuyucu buraya
durum makinesi EKLEMESİN.
"""

import uuid
from datetime import date
from typing import NamedTuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import day_hooks
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


def _assert_in_section_filter(cell: TimesheetCellInput, section: Section | None) -> None:
    """Süzgeç verildiyse hücre O BÖLÜME ait olmalı — 422 (`_assert_week` ikizi).

    Süzgeç kaydetme kapsamını daraltır; kapsamın dışına düşen bir hücre sessizce
    yazılsaydı bir sonraki süzgeçli kaydetme onu ne günceller ne siler — hücre
    kendi bölümünün ekranında hiç görünmeden orada kalırdı.
    """
    if section is None:
        return
    if cell.section_id != section.id:
        raise SiteValidationError(guards.SECTION_FILTER_MISMATCH)


async def _plan(
    session: AsyncSession,
    site: Site,
    data: TimesheetWeekSave,
    *,
    iso_year: int,
    iso_week: int,
    section: Section | None,
) -> _Plan:
    cells: dict[tuple[uuid.UUID, date], TimesheetCellInput] = {}
    for cell in data.cells:
        _assert_week(cell, iso_year, iso_week)
        _assert_in_section_filter(cell, section)
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


def _assert_odenebilir_personel(existing: list[TimesheetEntry], plan: _Plan) -> None:
    """🔴 PASİF/TASLAK personel kapısı — kullanıcı kararı 2026-09-19, seçenek (b).

    Bordro `is_active`/`is_draft` süzer (`payroll.compute_flow`); puantaj
    süzmüyordu ve bordronun ASLA ödemeyeceği kişiye adam-gün yazılabiliyordu.

    ## Neden DÜZ bir süzgeç DEĞİL

    Bu uç bir GÖVDE DEĞİŞTİRME ucudur ve gövde kapsamın TAM kümesidir. Düz
    süzgeç, sonradan pasifleşen bir personeli içeren GEÇMİŞ haftayı tümüyle
    422'ye çevirir ve o hafta bir daha DÜZENLENEMEZDİ — aynı haftadaki BAŞKA
    kişinin saatini düzeltmek bile imkânsızlaşırdı. Üstelik ürün bu kayıtları
    KORUMAYI seçmiştir (`personnel.models`: *"Silme YOKTUR"*).

    Kapı bu yüzden DEĞİŞİME bağlıdır: hücre yeni ya da farklıysa reddedilir,
    dokunulmamışsa geçer. Gövdeden ÇIKARMAK (silme) da serbesttir — yanlışlıkla
    yazılmış bir kaydın düzeltilebilmesi için o yol açık kalmalıdır.

    🔴 "Farklı" ÜÇ eksende ölçülür (`hours` · `code` · `section_id`) — `_apply`
    tam olarak bu üç alanı yazar. Yalnız `hours` karşılaştırılsaydı saatli bir
    hücreyi KODLUYA çevirmek ya da başka bölüme taşımak kapıdan sızardı.
    """
    by_key = {guards.cell_key(row.personnel_id, row.work_date): row for row in existing}
    for key, cell in plan.cells.items():
        person = plan.personnel[cell.personnel_id]
        if person.is_active and not person.is_draft:
            continue
        row = by_key.get(key)
        if (
            row is not None
            and row.hours == cell.hours
            and row.code == cell.code
            and row.section_id == cell.section_id
        ):
            continue
        raise SiteValidationError(guards.personnel_not_payable(person.full_name))


def _changed_days(existing: list[TimesheetEntry], plan: _Plan) -> set[date]:
    """Gelen ≠ mevcut olan günler: yeni hücre · silinen hücre · `_apply`ın yazdığı
    ÜÇ eksenden (`hours` · `code` · `section_id`) birinde fark
    (`_assert_odenebilir_personel` ile AYNI eksenler)."""
    by_key = {guards.cell_key(row.personnel_id, row.work_date): row for row in existing}
    changed: set[date] = set()
    for key, cell in plan.cells.items():
        row = by_key.get(key)
        if (
            row is None
            or row.hours != cell.hours
            or row.code != cell.code
            or row.section_id != cell.section_id
        ):
            changed.add(cell.work_date)
    changed.update(row.work_date for key, row in by_key.items() if key not in plan.cells)
    return changed


async def save_week(
    session: AsyncSession,
    actor: User,
    context: SiteContext,
    data: TimesheetWeekSave,
    *,
    iso_year: int,
    iso_week: int,
    section: Section | None = None,
) -> int:
    """**Hafta**+şantiye kapsamını gövdeye eşitler; yazılan hücre sayısını döner.

    Kapsam kararı (404) kilitten ÖNCE verilmiştir (`visible_site`, router'da):
    görünmeyen şantiyenin satırları boşuna kilitlenmez.

    🔴 `section` VERİLİRSE kapsam O BÖLÜME daralır — kilit de silme de. Okuma ucu
    bölüm süzerken yazma ucu süzmeseydi, süzgeçli bir ızgarayı gönderen istemci
    aynı haftadaki DİĞER bölümlerin hücrelerini geri alınamaz biçimde silerdi
    (`repository.locked_week_entries` + `_apply` aynı listeyi kullanır).
    """
    site = context.site
    plan = await _plan(session, site, data, iso_year=iso_year, iso_week=iso_week, section=section)

    existing = await repository.locked_week_entries(
        session,
        site.id,
        iso_year=iso_year,
        iso_week=iso_week,
        section_id=None if section is None else section.id,
    )
    await _assert_person_days_free(session, site, plan)
    # Kapsam okunduktan SONRA koşar: "değişti mi" sorusu MEVCUT satırları ister.
    _assert_odenebilir_personel(existing, plan)
    await day_hooks.assert_days_unlocked(session, site.id, _changed_days(existing, plan))

    # --- Buradan itibaren yazma; dogrulama YOK (yukaridaki sira kisiti). ---
    yeniler, silinecekler = _apply(site, existing, plan, actor)
    await repository.delete_entries(session, silinecekler)
    session.add_all(yeniler)
    await session.flush()
    return len(plan.cells)
