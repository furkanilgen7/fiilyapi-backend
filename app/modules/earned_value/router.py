"""Adam-saat butcesi uclari (BUT ekrani) — `/sites/{site_id}/earned-value/budget…`.

Kapilar `access.py` (VIEW/WRITE/APPROVE). Her yazma TEK denetim olayi yazar; GET'ler
ve kalici olmayan onizleme yazmaz. Yazma uclari guncel butce gorunumunu doner.
Kurallar servis katmanindadir (`budget_service`, `budget_ops`) ve burada TEKRARLANMAZ.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.openapi import COMMON_ERROR_RESPONSES
from app.core.ratelimit import client_ip
from app.modules.audit.models import AuditAction
from app.modules.audit.service import record_audit
from app.modules.earned_value import audit_messages as msg
from app.modules.earned_value import budget_ops as ops
from app.modules.earned_value import budget_present as present
from app.modules.earned_value import budget_repository as repo
from app.modules.earned_value import budget_service as svc
from app.modules.earned_value.access import APPROVE, VIEW, WRITE, SiteContext, visible_site
from app.modules.earned_value.schemas_budget import (
    AmbiguousItemOut,
    BudgetView,
    CandidateOut,
    DistributionsBody,
    FillOut,
    FreezeBody,
    GroupDisciplinesBody,
    ItemPatch,
    LeavesPatch,
    PreviewBody,
    PreviewOut,
    RevisionDiffOut,
    RevisionOut,
    ScheduleOut,
    SuggestionsOut,
    WindowsBody,
)
from app.modules.users.models import User

router = APIRouter(tags=["earned-value"], responses=COMMON_ERROR_RESPONSES)

_BASE = "/sites/{site_id}/earned-value/budget"
_User = Annotated[User, Depends(get_current_user)]
_Db = Annotated[AsyncSession, Depends(get_db)]


async def _audit(session: AsyncSession, request: Request, user: User, detail: str) -> None:
    await record_audit(
        session,
        action=AuditAction.update,
        detail=detail,
        actor_user_id=user.id,
        ip_address=client_ip(request),
    )


async def _view(session: AsyncSession, ctx: SiteContext) -> BudgetView:
    return await present.budget_view(session, await svc.load_state(session, ctx))


def _candidate(c: ops.Candidate) -> CandidateOut:
    return CandidateOut(
        catalog_item_id=c.item.id,
        name=c.item.name,
        uom=c.item.uom,
        standard_unit_mhr=c.item.standard_unit_mhr,
        discipline_id=c.item.discipline_id,
        match=c.match,  # type: ignore[arg-type]
    )


@router.get(_BASE, response_model=BudgetView, dependencies=[VIEW])
async def get_budget(
    site_id: uuid.UUID,
    user: _User,
    session: _Db,
    revision_id: Annotated[uuid.UUID | None, Query()] = None,
) -> BudgetView:
    """Butce agaci (L1 disiplin · L2 BOQ grubu · L3 is tipi · L4 kalem × bolum) + ozet.

    Varsayilan revizyon: taslak varsa taslak, yoksa aktif. Hic revizyon yoksa CANLI BOQ'tan
    bos bir taslak gorunumu (`revision: null`, `editable: true`) — ilk yazma Rev 0'i acar.
    Dondurma engelleri/uyarilari yalniz duzenlenebilir gorunumde doner (frontend istegi 1).
    """
    ctx = await visible_site(session, user, site_id)
    return await present.budget_view(session, await svc.load_state(session, ctx, revision_id))


@router.get(f"{_BASE}/revisions", response_model=list[RevisionOut], dependencies=[VIEW])
async def list_budget_revisions(site_id: uuid.UUID, user: _User, session: _Db) -> list[RevisionOut]:
    ctx = await visible_site(session, user, site_id)
    return [
        await present.revision_out(session, r)
        for r in await repo.list_revisions(session, ctx.site.id)
    ]


@router.post(
    f"{_BASE}/revisions",
    response_model=RevisionOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[WRITE],
)
async def open_budget_draft(
    request: Request, site_id: uuid.UUID, user: _User, session: _Db
) -> RevisionOut:
    """ "Taslak revizyon ac": aktifin girdileri yeni taslaga kopyalanir. Taslak varken 409."""
    ctx = await visible_site(session, user, site_id)
    rev = await svc.open_draft(session, ctx, user)
    await _audit(
        session, request, user, msg.draft_opened(ctx.project.name, ctx.site.name, rev.number)
    )
    return await present.revision_out(session, rev)


@router.delete(
    f"{_BASE}/revisions/{{revision_id}}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[APPROVE],
)
async def delete_budget_draft(
    request: Request, site_id: uuid.UUID, revision_id: uuid.UUID, user: _User, session: _Db
) -> Response:
    """Yalniz TASLAK silinir (onay duzeyi); donmus revizyon 409."""
    ctx = await visible_site(session, user, site_id)
    rev = await svc.delete_draft(session, ctx, revision_id)
    await _audit(
        session, request, user, msg.draft_deleted(ctx.project.name, ctx.site.name, rev.number)
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    f"{_BASE}/revisions/{{revision_id}}/diff", response_model=RevisionDiffOut, dependencies=[VIEW]
)
async def get_budget_revision_diff(
    site_id: uuid.UUID, revision_id: uuid.UUID, user: _User, session: _Db
) -> RevisionDiffOut:
    """Onceki DONMUS revizyona gore yaprak farki (yeni / cikan / miktar / oran)."""
    ctx = await visible_site(session, user, site_id)
    return await present.diff_out(session, await ops.diff(session, ctx, revision_id))


@router.put(f"{_BASE}/group-disciplines", response_model=BudgetView, dependencies=[WRITE])
async def put_group_disciplines(
    request: Request, site_id: uuid.UUID, body: GroupDisciplinesBody, user: _User, session: _Db
) -> BudgetView:
    """BOQ grubu → disiplin eslemesi (K2) — KISMI: yalniz listelenen gruplar; null kaldirir."""
    ctx = await visible_site(session, user, site_id)
    pairs = [(p.boq_group_id, p.discipline_id) for p in body.items]
    count = await svc.set_group_disciplines(session, ctx, user, pairs)
    await _audit(
        session, request, user, msg.group_disciplines_saved(ctx.project.name, ctx.site.name, count)
    )
    return await _view(session, ctx)


@router.patch(f"{_BASE}/items/{{boq_item_id}}", response_model=BudgetView, dependencies=[WRITE])
async def patch_budget_item(
    request: Request,
    site_id: uuid.UUID,
    boq_item_id: uuid.UUID,
    body: ItemPatch,
    user: _User,
    session: _Db,
) -> BudgetView:
    """Is tipi (L3) kendi/taseron + dogrudan/dolayli + katalog bagi (K3)."""
    ctx = await visible_site(session, user, site_id)
    changes = body.model_dump(include=body.model_fields_set)
    item = await svc.patch_item(session, ctx, user, boq_item_id, changes)
    await _audit(
        session, request, user, msg.item_settings_saved(ctx.project.name, ctx.site.name, item.code)
    )
    return await _view(session, ctx)


@router.patch(f"{_BASE}/leaves", response_model=BudgetView, dependencies=[WRITE])
async def patch_budget_leaves(
    request: Request, site_id: uuid.UUID, body: LeavesPatch, user: _User, session: _Db
) -> BudgetView:
    """Yaprak orani (+kaynak) ve ezmeleri — tekil ya da TOPLU ("secili satirlara toplu oran")."""
    ctx = await visible_site(session, user, site_id)
    changes = [
        svc.LeafChange(
            lf.boq_item_id,
            lf.section_id,
            lf.model_dump(include=lf.model_fields_set - {"boq_item_id", "section_id"}),
        )
        for lf in body.leaves
    ]
    count = await svc.patch_leaves(session, ctx, user, changes)
    await _audit(session, request, user, msg.leaves_saved(ctx.project.name, ctx.site.name, count))
    return await _view(session, ctx)


@router.get(
    f"{_BASE}/items/{{boq_item_id}}/suggestions", response_model=SuggestionsOut, dependencies=[VIEW]
)
async def get_budget_item_suggestions(
    site_id: uuid.UUID, boq_item_id: uuid.UUID, user: _User, session: _Db
) -> SuggestionsOut:
    """Oran onerisi popover'i: katalog adaylari (bagli · tam · kismi). Gecmis B3'te dolar."""
    ctx = await visible_site(session, user, site_id)
    cands = await ops.suggestions(session, ctx, boq_item_id)
    return SuggestionsOut(catalog=[_candidate(c) for c in cands], history=[])


@router.post(f"{_BASE}/fill-from-catalog", response_model=FillOut, dependencies=[WRITE])
async def fill_budget_from_catalog(
    request: Request, site_id: uuid.UUID, user: _User, session: _Db
) -> FillOut:
    """ "Katalogdan oner (bosları doldur)" (B1-4; frontend istegi 3)."""
    ctx = await visible_site(session, user, site_id)
    result = await ops.fill_from_catalog(session, ctx, user)
    if result.filled_leaf_count:
        await _audit(
            session,
            request,
            user,
            msg.filled_from_catalog(ctx.project.name, ctx.site.name, result.filled_leaf_count),
        )
    return FillOut(
        filled_item_count=result.filled_item_count,
        filled_leaf_count=result.filled_leaf_count,
        ambiguous_count=len(result.ambiguous),
        unmatched_count=result.unmatched_count,
        ambiguous=[
            AmbiguousItemOut(
                boq_item_id=item.item_id,
                code=item.code,
                description=item.description,
                candidates=[_candidate(c) for c in cands],
            )
            for item, cands in result.ambiguous
        ],
    )


@router.put(f"{_BASE}/distributions", response_model=BudgetView, dependencies=[WRITE])
async def put_budget_distributions(
    request: Request, site_id: uuid.UUID, body: DistributionsBody, user: _User, session: _Db
) -> BudgetView:
    """Disiplin basina dagilim tipi (B1-2) — KISMI upsert."""
    ctx = await visible_site(session, user, site_id)
    pairs = [(p.discipline_id, p.distribution) for p in body.items]
    count = await svc.put_distributions(session, ctx, user, pairs)
    await _audit(
        session, request, user, msg.distributions_saved(ctx.project.name, ctx.site.name, count)
    )
    return await _view(session, ctx)


@router.put(f"{_BASE}/windows", response_model=BudgetView, dependencies=[WRITE])
async def put_budget_windows(
    request: Request, site_id: uuid.UUID, body: WindowsBody, user: _User, session: _Db
) -> BudgetView:
    """Disiplin × bolum pencere EZMELERI — TAM DEGISTIRME (B1-3)."""
    ctx = await visible_site(session, user, site_id)
    rows = [(w.discipline_id, w.section_id, w.start_date, w.end_date) for w in body.windows]
    count = await svc.put_windows(session, ctx, user, rows)
    await _audit(session, request, user, msg.windows_saved(ctx.project.name, ctx.site.name, count))
    return await _view(session, ctx)


@router.get(f"{_BASE}/schedule", response_model=ScheduleOut, dependencies=[VIEW])
async def get_budget_schedule(
    site_id: uuid.UUID,
    user: _User,
    session: _Db,
    revision_id: Annotated[uuid.UUID | None, Query()] = None,
) -> ScheduleOut:
    """Adim 2 Gantt: bolumler, disiplin × bolum cubuklari, tatiller."""
    ctx = await visible_site(session, user, site_id)
    state = await svc.load_state(session, ctx, revision_id)
    boq = await repo.load_boq(session, ctx.site.id)
    cal = await repo.load_calendar(session, ctx.site.id)
    return present.schedule_out(state.tree, boq.sections, cal.weekly_off_days, cal.holidays)


@router.post(f"{_BASE}/preview", response_model=PreviewOut, dependencies=[VIEW])
async def preview_budget(
    site_id: uuid.UUID, body: PreviewBody, user: _User, session: _Db
) -> PreviewOut:
    """KALICI OLMAYAN egri onizlemesi (frontend istegi 2): govdedeki dagilim/pencere ezmeleri
    kaydedilmeden uygulanir. Donmus revizyon snapshot egrisinden gelir (K8)."""
    ctx = await visible_site(session, user, site_id)
    result = await ops.preview(
        session,
        ctx,
        body.revision_id,
        {p.discipline_id: p.distribution for p in body.distributions},
        {(w.discipline_id, w.section_id): (w.start_date, w.end_date) for w in body.windows},
    )
    return present.preview_out(result)


@router.post(f"{_BASE}/freeze", response_model=RevisionOut, dependencies=[APPROVE])
async def freeze_budget(
    request: Request, site_id: uuid.UUID, body: FreezeBody, user: _User, session: _Db
) -> RevisionOut:
    """Baseline dondur (K8): engel varsa 422; taslak → aktif, onceki aktif → arsiv."""
    ctx = await visible_site(session, user, site_id)
    rev = await ops.freeze(session, ctx, user, body.name, body.description)
    await _audit(
        session,
        request,
        user,
        msg.revision_frozen(ctx.project.name, ctx.site.name, rev.number, rev.name),
    )
    return await present.revision_out(session, rev)
