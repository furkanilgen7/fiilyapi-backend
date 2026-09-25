"""EV-BORC (b) — gün dağıtımının şantiye satırı kilidi GEREKLİ: ÖLÇÜM + bekçi (CEO kararı).

Dağıtım kaydı TAM DEĞİŞTİRMEDİR (günün kodları/satırları silinir, yenileri eklenir). DELETE
başka transaction'ın commit edilmemiş eklemelerini göremez; kilitsiz iki eşzamanlı kayıt
`ev_day_codes` PK'sında (site, gün, kod) çakışır → IntegrityError (500). `sites … FOR UPDATE`
ikinciyi BEKLETİR; FOR SHARE yetmezdi (paylaşımlı kilitler birbirini bekletmez).

Kurgu: tek kullanımlık yarış DB'si + DONMUŞ baseline (bölüm + kalem + oran + freeze) +
puantaj (Ali 9 sa). Oturum 1 dağıtımı kaydeder (COMMIT yok); oturum 2 aynı anda kaydeder.
* Kilitli (bugünkü kod): 2 `sites … FOR UPDATE`de BEKLER, 1 commit edince temiz yazar.
* POZİTİF KONTROL (`lock=False`): 2 kilitte beklemez, PK satırında (INSERT) bekler → PK
  çakışması → IntegrityError. Bariyer bu beklemeyi ölçer (FIX-B2: uyku zamanlamaya bağlıydı).
Emsal ve bariyer: `test_evborc_settings_lock.py`, `test_b30_relock_guard.py` (PLN-B0 ders 9).
"""

from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.modules.boq.models import BoqItem, BoqItemSectionAllocation
from app.modules.earned_value import access, diary_adapter
from app.modules.earned_value import budget_ops as ops
from app.modules.earned_value import budget_service as svc
from app.modules.earned_value.access import SiteContext
from app.modules.earned_value.models import EvDayCode
from app.modules.personnel.models import Personnel
from app.modules.projects.models import Project
from app.modules.site_diary.models import WorkerSource
from app.modules.sites.models import Section, Site
from app.modules.timesheet.models import TimesheetEntry
from app.modules.users.models import User
from tests.earned_value_budget.test_budget_concurrency import (
    _BEKLEME_SINIRI,
    _KESISME_PAYI,
    _bekleyen_sorgu,
    _Ortam,
    _sonlandir,
    _yaris_ortami,
)

pytestmark = pytest.mark.asyncio

DAY = date(2026, 5, 5)


async def _zemin(ortam: _Ortam) -> tuple[str, Personnel]:
    """Donmuş baseline + puantaj — COMMIT'li. (yaprak kimliği, personel) döner."""
    async with ortam.Session() as s:
        actor = await s.get(User, ortam.actor_id)
        site = await s.get(Site, ortam.site_id)
        project = await s.get(Project, ortam.project_id)
        assert actor and site and project
        section = Section(
            site_id=site.id,
            name="A Blok",
            start_date=date(2026, 5, 4),
            end_date=date(2026, 5, 15),
            planned_worker_count=5,
            sort_order=1,
        )
        s.add(section)
        item = BoqItem(
            site_id=site.id,
            group_id=ortam.group_ids[0],
            code="01.001",
            description="Beton",
            unit="m3",
            quantity=Decimal(10),
            unit_price=Decimal(0),
            sort_order=1,
        )
        ali = Personnel(
            full_name="Ali Usta",
            trade="Kalıpçı",
            source=WorkerSource.company,
            is_active=True,
            is_draft=False,
        )
        s.add_all([item, ali])
        await s.flush()
        # Kalemin TAMAMI bölüme tahsisli → tek yaprak (kalem × bölüm), pencere bölümden.
        s.add(
            BoqItemSectionAllocation(
                boq_item_id=item.id, section_id=section.id, quantity=Decimal(10)
            )
        )
        s.add(
            TimesheetEntry(
                personnel_id=ali.id,
                site_id=site.id,
                project_id=project.id,
                work_date=DAY,
                hours=Decimal(9),
                created_by=actor.id,
            )
        )
        ctx = SiteContext(site=site, project=project)
        await svc.set_group_disciplines(s, ctx, actor, [(ortam.group_ids[0], ortam.discipline_id)])
        await svc.patch_leaves(
            s, ctx, actor, [svc.LeafChange(item.id, section.id, {"unit_mhr": Decimal(2)})]
        )
        await ops.freeze(s, ctx, actor, None, None)
        await s.commit()
        return f"l:{item.id}:{section.id}", ali


async def _kaydet(ortam: _Ortam, session, leaf: str, ali: Personnel) -> None:  # noqa: ANN001
    actor = await session.get(User, ortam.actor_id)
    await diary_adapter.save_allocation(
        session,
        ortam.site_id,
        DAY,
        actor,
        [(leaf, "direct")],
        [diary_adapter.CellIn("personnel", ali.id, leaf, Decimal(9))],
        None,
    )


async def _yaris(ortam: _Ortam) -> tuple[str, BaseException | None]:
    leaf, ali = await _zemin(ortam)

    async def _ikinci() -> None:
        async with ortam.Session() as session:
            await _kaydet(ortam, session, leaf, ali)
            await session.commit()

    task: asyncio.Task[None] | None = None
    bekleyen = ""
    async with ortam.Session() as birinci:
        try:
            await _kaydet(ortam, birinci, leaf, ali)
            task = asyncio.create_task(_ikinci())
            # FIX-B2: bariyer İKİ yolda da ölçülür (kilitli: `sites FOR UPDATE`; kilitsiz:
            # UQ/PK satırında bekleyen INSERT). Uyku DEĞİL — kilitsiz yolda uyku yetmezse
            # ikinci oturum okumayı birincinin commit'inden SONRA yapar ve temiz geçerdi.
            bekleyen = await _bekleyen_sorgu(ortam)
            await asyncio.sleep(_KESISME_PAYI)
            assert not task.done(), "ikinci kayıt birinci commit edilmeden BİTTİ"
            await birinci.commit()
        except BaseException:
            await birinci.rollback()
            await _sonlandir(task)
            raise
    assert task is not None
    try:
        await asyncio.wait_for(task, _BEKLEME_SINIRI)
    except (IntegrityError, TimeoutError) as exc:
        return bekleyen, exc
    return bekleyen, None


async def _kod_sayisi(ortam: _Ortam) -> int:
    async with ortam.Session() as session:
        return await session.scalar(
            select(func.count())
            .select_from(EvDayCode)
            .where(EvDayCode.site_id == ortam.site_id, EvDayCode.day == DAY)
        )


async def test_EVBORC_concurrent_day_allocations_are_serialized_by_site_lock() -> None:
    async with _yaris_ortami() as ortam:
        bekleyen, hata = await _yaris(ortam)

        assert "FROM sites" in bekleyen and "FOR UPDATE" in bekleyen, bekleyen
        assert hata is None, f"ikinci dağıtım başarısız: {hata!r}"
        assert await _kod_sayisi(ortam) == 1


async def test_EVBORC_KONTROL_without_site_lock_concurrent_allocations_collide(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POZİTİF KONTROL: durum kontrolü AYNI, kilit YOK → ikinci kayıt PK'da çakışır (500)."""
    original = access.assert_site_writable

    async def _kilitsiz(session, site_id, *, message, lock=True):  # noqa: ANN001, ANN202, ARG001
        await original(session, site_id, message=message, lock=False)

    monkeypatch.setattr(diary_adapter, "assert_site_writable", _kilitsiz)
    async with _yaris_ortami() as ortam:
        bekleyen, hata = await _yaris(ortam)

        # ikinci oturum sürümü/satırı OKUDU ve birincinin satırında bekliyor → çakışma kesin
        assert bekleyen.startswith("INSERT INTO ev_day_codes"), bekleyen
        assert isinstance(hata, IntegrityError), f"kilitsiz de temiz geçti: {hata!r}"
