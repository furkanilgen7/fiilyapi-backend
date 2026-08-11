"""P11 · Portfoy Gantt verisi — `GET /projects/timeline` (spec §3).

Ayri bir modul cunku bu, `sites` tablolarini okuyan TEK `projects` yuzeyidir:
bagimlilik `projects.service` yerine burada durur ve import yonu tek yonlu
kalir (`projects.timeline` -> `sites.models`; sites hicbir sey geri istemez).

Kapsam disi olanlar (spec §4, kullanici karari — icat yasagi):
- Ilerleme yuzdesi (S1): alan HIC ACILMAZ, pending zarfla bile donulmez.
- Ay izgarasi/zoom/gezinme (S4): uc parametre ALMAZ, istemci cizer.
- Gecikme vurgusu, kritik yol, baseline kiyasi: kaynak yok.
- PT 300-303 portfoy ozeti: dashboard isi.
"""

import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timezone
from app.modules.projects import service
from app.modules.projects.models import Project
from app.modules.projects.schemas import (
    ProjectTimelineResponse,
    TimelineMilestone,
    TimelineProject,
    TimelineSection,
)
from app.modules.sites.models import Section, Site
from app.modules.users.models import User


async def _sections_by_project(
    session: AsyncSession, project_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[Section]]:
    """Gorunur projelerin TUM bolumlerini TEK sorguda, proje kimligine gore
    gruplanmis dondurur.

    GORUNURLUK: guvenlik kapisi `service.visible_projects`tir; buradaki
    `Site.project_id.in_(...)` onun SQL'e inmis KAPSAM daraltmasidir —
    gorunmeyen projenin satirlari hic okunmaz (bellege alinan veri de yaniti
    besleyen kume kadar kalir). Yanita cikan kume ayrica gruplama anahtariyla
    sinirlidir: `get_timeline` yalnizca GORUNUR projenin kimligiyle sorgular.
    Iki korkuluk bilincli olarak ust ustedir.

    SIRA (santiye kodu, `sort_order`, `id`): santiye seviyesi Gantt'ta
    GORUNMEZ (spec §1) ama bolumler birden fazla santiyeden geldigi icin
    gruplama disi bir kirici sart. `id` son kirici olmasa `sort_order`
    esitliginde ayni veri iki istekte farkli sirayla donerdi.

    `Section.milestones` iliskisi `lazy="selectin"`tir: milestone'lar bu
    sorguya bagli TEK ek SELECT ile gelir, bolum basina sorgu ACILMAZ.
    """
    grouped: dict[uuid.UUID, list[Section]] = defaultdict(list)
    if not project_ids:
        return grouped
    stmt = (
        select(Site.project_id, Section)
        .join(Section, Section.site_id == Site.id)
        .where(Site.project_id.in_(project_ids))
        .order_by(Site.code, Section.sort_order, Section.id)
    )
    for project_id, section in (await session.execute(stmt)).all():
        grouped[project_id].append(section)
    return grouped


def _to_section(section: Section) -> TimelineSection:
    return TimelineSection(
        id=section.id,
        name=section.name,
        status=section.status,
        start_date=section.start_date,
        end_date=section.end_date,
        sort_order=section.sort_order,
        depends_on_section_id=section.depends_on_section_id,
        milestones=[TimelineMilestone.model_validate(m) for m in section.milestones],
    )


def _to_project(project: Project, sections: list[Section]) -> TimelineProject:
    return TimelineProject(
        id=project.id,
        code=project.code,
        name=project.name,
        status=project.status,
        start_date=project.start_date,
        end_date=project.end_date,
        contract_amount=project.contract_amount,
        sections=[_to_section(s) for s in sections],
    )


async def get_timeline(session: AsyncSession, actor: User) -> ProjectTimelineResponse:
    """Portfoy Gantt'i: gorunur projeler + bolumleri + milestone'lari + `today`.

    Gorunurluk `service.visible_projects` KAPISINDAN gecer — kopya bir erisim
    mantigi yazilmaz (spec §5.2, tek kaynak kurali). Proje sirasi o kapinin
    verdigi `code` siralamasidir.

    TASLAKLAR SUZULMEZ: `is_draft` bir gorunurluk kavrami degildir ve mockup'ta
    Gantt'tan haric tutma diye bir sey CIZILMEMISTIR (BE 237 kutusu icin de
    kolon acilmadi, spec §2). Suzmek icat olurdu; liste ucu de taslaklari
    dondurur ve sayar.
    """
    projects = await service.visible_projects(session, actor)
    sections = await _sections_by_project(session, [p.id for p in projects])
    return ProjectTimelineResponse(
        today=timezone.today(),
        items=[_to_project(p, sections.get(p.id, [])) for p in projects],
    )
