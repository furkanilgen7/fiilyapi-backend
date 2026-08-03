"""Planlama YAZMA yolu (T3) — dört ucun DEĞİŞTİRME semantiği.

`read.py`nin kardeşidir ve aynı yön kuralına uyar: bu modül `service` +
`repository`yi çağırır, ikisi buradan hiçbir şey İMPORT ETMEZ (döngüsel import
doğmaz). Kapsam kararı (404) ve hafta korkuluğu (422) burada TEKRARLANMAZ —
router `service.assert_week_start` + `service.visible_site` ile çağırır.

## ⚠️ Kapsam sınırı — bu dosyanın en kritik kuralı

`timesheet/service.py`nin kuralının aynısı. Silme koşulları:

| Uç | Kapsam |
|---|---|
| `rows` | `site_id` |
| `cells` | satırın `site_id`si **VE** `plan_date ∈ [hafta başı, hafta sonu]` |
| `goals` | `site_id` **VE** `week_start` |
| `sprint` | `site_id` |

Koşulun herhangi bir parçası düşerse bir haftanın kaydetmesi komşu HAFTANIN ya da
komşu ŞANTİYENİN planını sessizce süpürür — geri alınamaz veri kaybı. Hücrede
`site_id` kolonu YOKTUR (spec §2), koşul satır üzerinden kurulur; bu yüzden
gövdedeki her `row_id`nin şantiyeye ait olduğu AYRICA doğrulanır.

## Sıra — ÖNCE TÜM DOĞRULAMALAR, SONRA TEK YAZMA

İkinci kayıtta patlayan istek birincisini session'a eklemiş OLMAMALIDIR (kısmi
yazma yok). Doğrulama fonksiyonları hiçbir şey yazmaz.

## Kilit

Her uç kapsamını `FOR UPDATE` ile kilitler (`repository.locked_*`): "değiştirme"
tek mantıksal işlemdir, iki eşzamanlı kaydetme kilitsiz yarışırsa ızgara ikisinin
de olmadığı bir hâlde kalır.
"""

import uuid
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import SiteValidationError
from app.modules.site_planning import guards, repository
from app.modules.site_planning.models import (
    PlanResourceKind,
    SitePlanCell,
    SitePlanGoal,
    SitePlanRow,
    SitePlanSprint,
)
from app.modules.site_planning.schemas import (
    SitePlanCellInput,
    SitePlanCellsSave,
    SitePlanGoalsSave,
    SitePlanRowsSave,
    SitePlanSprintSave,
)
from app.modules.site_planning.service import SiteContext
from app.modules.sites import repository as sites_repository
from app.modules.sites.models import Site

# --- Satırlar ---


async def _assert_sections(session: AsyncSession, site: Site, data: SitePlanRowsSave) -> None:
    """Bölüm satırın gruplama alanıdır ama SAHİPSİZ olamaz: satırın ŞANTİYESİNE
    ait olmalı. Yazmada 422'dir (okumadaki 404 değil): burada bölüm bir SÜZGEÇ
    değil gövdenin düzeltilebilir bir ALANIDIR (`timesheet` deseni)."""
    section_ids = {row.section_id for row in data.rows if row.section_id is not None}
    for section_id in section_ids:
        section = await sites_repository.get_section(session, section_id)
        if section is None or section.site_id != site.id:
            raise SiteValidationError(guards.SECTION_MISMATCH)


def _assert_row_shape(data: SitePlanRowsSave) -> None:
    """Gövdenin KENDİ İÇİNDE tutarlılığı — DB'ye hiç gitmeden.

    Tekillik kontrolü burada kritiktir: `UQ (site_id, kind, section_id, label)`
    Postgres'te `section_id IS NULL` dalında ÇALIŞMAZ (gerekçe
    `guards.DUPLICATE_ROW`), yani ekipman ve bölümsüz ekip satırlarının tek
    koruması bu döngüdür.
    """
    keys: set[tuple[str, uuid.UUID | None, str]] = set()
    ids: set[uuid.UUID] = set()
    for row in data.rows:
        if row.kind is PlanResourceKind.equipment and row.section_id is not None:
            raise SiteValidationError(guards.EQUIPMENT_ROW_HAS_SECTION)
        key = guards.row_key(row.kind.value, row.section_id, row.label)
        if key in keys:
            raise SiteValidationError(guards.DUPLICATE_ROW)
        keys.add(key)
        if row.id is not None:
            if row.id in ids:
                raise SiteValidationError(guards.DUPLICATE_ROW)
            ids.add(row.id)


async def save_rows(
    session: AsyncSession, context: SiteContext, data: SitePlanRowsSave
) -> list[SitePlanRow]:
    """Şantiyenin satır kümesini gövdeye eşitler; okuma sırasındaki satırları döner.

    Gövdede geçmeyen satır SİLİNİR ve hücreleri FK CASCADE ile düşer. `id`si olan
    satırın KİMLİĞİ korunur (sil + yeniden yaz DEĞİL): aksi hâlde her yeniden
    adlandırma o satırın tüm hücrelerini sessizce silerdi.
    """
    site = context.site
    _assert_row_shape(data)
    await _assert_sections(session, site, data)

    existing = await repository.locked_site_rows(session, site.id)
    by_id = {row.id: row for row in existing}
    if any(row.id is not None and row.id not in by_id for row in data.rows):
        # Var OLMAYAN kimlik ile BAŞKA şantiyenin satırı AYNI 422'yi alır.
        raise SiteValidationError(guards.ROW_UNKNOWN)

    # --- Buradan itibaren yazma; doğrulama YOK (yukarıdaki sıra kısıtı). ---
    kalanlar: set[uuid.UUID] = set()
    for giris in data.rows:
        row = by_id.get(giris.id) if giris.id is not None else None
        if row is None:
            row = SitePlanRow(
                site_id=site.id,
                # Kapsam alanı ŞANTİYEDEN kopyalanır, gövdeden ASLA.
                project_id=site.project_id,
            )
            session.add(row)
        else:
            kalanlar.add(row.id)
        row.kind = giris.kind
        row.section_id = giris.section_id
        row.label = giris.label.strip()
        row.planned_worker_count = giris.planned_worker_count
        row.sort_order = giris.sort_order

    await repository.delete_rows(session, [rid for rid in by_id if rid not in kalanlar])
    await session.flush()
    return [row for row, _ in await repository.plan_rows(session, site.id)]


# --- Hücreler ---


async def _assert_cell_rows(session: AsyncSession, site: Site, data: SitePlanCellsSave) -> None:
    """Gövdedeki her `row_id` bu ŞANTİYENİN satırı olmalı.

    Kapsam sınırının gövde tarafındaki yarısı: doğrulanmasaydı komşu şantiyenin
    satırına hücre yazılabilir ve kapsam sınırı gövdeden AŞILIRDI.
    """
    row_ids = {cell.row_id for cell in data.cells}
    if not row_ids:
        return
    site_rows = {row.id for row in await repository.locked_site_rows(session, site.id)}
    if row_ids - site_rows:
        raise SiteValidationError(guards.ROW_UNKNOWN)


def _assert_cell_shape(data: SitePlanCellsSave, week_start: date) -> None:
    start, end = repository.week_bounds(week_start)
    keys: set[tuple[uuid.UUID, date]] = set()
    for cell in data.cells:
        if not (start <= cell.plan_date <= end):
            raise SiteValidationError(guards.format_cell_out_of_week(cell.plan_date, start, end))
        key = guards.cell_key(cell.row_id, cell.plan_date)
        if key in keys:
            # Boş metinli hücreler de sayılır (gerekçe `guards.DUPLICATE_CELL`).
            raise SiteValidationError(guards.DUPLICATE_CELL)
        keys.add(key)


def _effective_cells(
    data: SitePlanCellsSave,
) -> dict[tuple[uuid.UUID, date], SitePlanCellInput]:
    """Metni boş olan hücre plana GİRMEZ (spec §2 "hücre yokluğu = plan yok").

    Boş metin bir SİLME talimatıdır: hücre etkin kümede olmadığı için DEĞİŞTİRME
    semantiği onu zaten kaldırır. Boş metinli bir satır yazmak "planlanmamış gün"
    ile "planı silinmiş gün"ü ayırt edilemez hâle getirirdi.
    """
    return {
        guards.cell_key(cell.row_id, cell.plan_date): cell
        for cell in data.cells
        if cell.text.strip()
    }


async def save_cells(
    session: AsyncSession, context: SiteContext, data: SitePlanCellsSave, week_start: date
) -> int:
    """Hafta + şantiye kapsamını gövdeye eşitler; yazılan hücre sayısını döner."""
    site = context.site
    _assert_cell_shape(data, week_start)
    await _assert_cell_rows(session, site, data)
    etkin = _effective_cells(data)

    existing = await repository.locked_week_cells(session, site.id, week_start)
    by_key = {guards.cell_key(cell.row_id, cell.plan_date): cell for cell in existing}

    # --- Buradan itibaren yazma. ---
    for key, giris in etkin.items():
        cell = by_key.get(key)
        if cell is None:
            session.add(
                SitePlanCell(
                    row_id=giris.row_id,
                    plan_date=giris.plan_date,
                    text=giris.text.strip(),
                    tag=giris.tag,
                )
            )
        else:
            cell.text = giris.text.strip()
            # Gönderilmeyen renk NULL'a düşer: hücre gövdedeki hâline EŞİTLENİR,
            # eski değer "sessizce" kalmaz.
            cell.tag = giris.tag

    await repository.delete_cells(
        session, [cell.id for key, cell in by_key.items() if key not in etkin]
    )
    await session.flush()
    return len(etkin)


# --- Hedefler ---


async def save_goals(
    session: AsyncSession, context: SiteContext, data: SitePlanGoalsSave, week_start: date
) -> int:
    """O haftanın hedef listesini gövdeye eşitler; hedef sayısını döner.

    `week_start` gövdede DEĞİL sorgu parametresindedir: iki kaynak olsaydı bir
    haftanın kaydetmesi gövdedeki tarihle başka bir haftaya taşabilirdi. Aynı
    gerekçeyle başka haftanın hedef kimliği 422'dir — kabul edilseydi hedef
    sessizce hafta değiştirir, eski listeden kaybolurdu.
    """
    site = context.site
    ids: set[uuid.UUID] = set()
    for goal in data.goals:
        if goal.id is not None:
            if goal.id in ids:
                raise SiteValidationError(guards.DUPLICATE_GOAL)
            ids.add(goal.id)

    existing = await repository.locked_week_goals(session, site.id, week_start)
    by_id = {goal.id: goal for goal in existing}
    if ids - set(by_id):
        raise SiteValidationError(guards.GOAL_UNKNOWN)

    # --- Buradan itibaren yazma. ---
    for giris in data.goals:
        goal = by_id.get(giris.id) if giris.id is not None else None
        if goal is None:
            goal = SitePlanGoal(
                site_id=site.id,
                project_id=site.project_id,
                week_start=week_start,
            )
            session.add(goal)
        goal.title = giris.title
        goal.note = giris.note
        goal.is_done = giris.is_done
        goal.status = giris.status
        goal.sort_order = giris.sort_order

    await repository.delete_goals(session, [gid for gid in by_id if gid not in ids])
    await session.flush()
    return len(data.goals)


# --- Sprint ---


async def save_sprint(
    session: AsyncSession, context: SiteContext, data: SitePlanSprintSave
) -> SitePlanSprint | None:
    """Aktif sprintin adını yazar; boş adda aktif sprinti KAPATIR.

    Kayıt SİLİNMEZ, `is_active` false'a çekilir: kısmi UQ yalnız aktifleri
    kısıtlar, geçmiş sprintler yan yana durabilir ve şeridin ne zaman
    boşaltıldığı denetim izinden okunabilir.

    Mevcut aktif satır YENİDEN KULLANILIR (kapat + yeni aç DEĞİL): aynı
    transaction içinde silinen/eklenen satır kısmi UQ üzerinde gereksiz yere
    yarışırdı.
    """
    site = context.site
    name = (data.name or "").strip()
    sprints = await repository.locked_site_sprints(session, site.id)
    active = next((s for s in sprints if s.is_active), None)

    if not name:
        if active is not None:
            active.is_active = False
            await session.flush()
        return None

    if active is None:
        active = SitePlanSprint(site_id=site.id, name=name, is_active=True)
        session.add(active)
    else:
        active.name = name
    await session.flush()
    return active
