"""EV-BORC-5 (1) — rapor ONAYI şantiye satırı kilidiyle sıraya girer: ÖLÇÜM + bekçi.

Çürütme bulgusu: `report_daily.approve` servis içi kilit almıyordu (uç bağımlılığı kilitsiz
erken kontroldür). İki eşzamanlı onay aynı sürümü (`max+1`) hesaplar; ikincisi
`uq_ev_report_snapshots_ver`e çarpar (HTTP'de genel 409 "Veri bütünlüğü hatası").

Kurgu: tek kullanımlık yarış DB'si + donmuş baseline + puantaj (`test_evborc_day_allocation_lock`
zemini) + GÖNDERİLMİŞ günlük. Oturum 1 onaylar (COMMIT yok), oturum 2 aynı günü onaylar.
* Kilitli (bugünkü kod): 2 `sites … FOR UPDATE`de BEKLER; 1 commit edince sürüm 2 yazar.
* POZİTİF KONTROL (kilitsiz): 2 beklemez → iki oturum da sürüm 1 → UQ çakışması.
Bariyer: `pg_stat_activity` bekleyen SORGUSU (PLN-B0 ders 9).
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.modules.earned_value import access, report_daily
from app.modules.earned_value.models import EvReportSnapshot
from app.modules.site_diary.models import DiaryStatus, SiteDiaryEntry
from app.modules.users.models import User
from tests.earned_value_budget.test_budget_concurrency import (
    _BEKLEME_SINIRI,
    _KESISME_PAYI,
    _bekleyen_sorgu,
    _Ortam,
    _sonlandir,
    _yaris_ortami,
)
from tests.earned_value_budget.test_evborc_day_allocation_lock import DAY, _zemin

pytestmark = pytest.mark.asyncio


async def _gunluk(ortam: _Ortam) -> None:
    async with ortam.Session() as s:
        s.add(
            SiteDiaryEntry(
                site_id=ortam.site_id,
                project_id=ortam.project_id,
                entry_date=DAY,
                status=DiaryStatus.submitted,
                created_by=ortam.actor_id,
            )
        )
        await s.commit()


async def _onayla(ortam: _Ortam, session) -> None:  # noqa: ANN001
    actor = await session.get(User, ortam.actor_id)
    await report_daily.approve(session, ortam.site_id, DAY, actor)


async def _yaris(ortam: _Ortam, *, bekle: bool) -> tuple[str, BaseException | None]:
    await _zemin(ortam)
    await _gunluk(ortam)

    async def _ikinci() -> None:
        async with ortam.Session() as session:
            await _onayla(ortam, session)
            await session.commit()

    task: asyncio.Task[None] | None = None
    bekleyen = ""
    async with ortam.Session() as birinci:
        try:
            await _onayla(ortam, birinci)
            task = asyncio.create_task(_ikinci())
            if bekle:
                bekleyen = await _bekleyen_sorgu(ortam)
                await asyncio.sleep(_KESISME_PAYI)
                assert not task.done(), "ikinci onay birinci commit edilmeden BİTTİ"
            else:
                await asyncio.sleep(_KESISME_PAYI)
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


async def _surumler(ortam: _Ortam) -> list[int]:
    async with ortam.Session() as session:
        rows = await session.scalars(
            select(EvReportSnapshot.version)
            .where(EvReportSnapshot.site_id == ortam.site_id, EvReportSnapshot.report_date == DAY)
            .order_by(EvReportSnapshot.version)
        )
        return list(rows)


async def test_EVBORC5_concurrent_approvals_are_serialized_by_site_lock() -> None:
    async with _yaris_ortami() as ortam:
        bekleyen, hata = await _yaris(ortam, bekle=True)

        assert "FROM sites" in bekleyen and "FOR UPDATE" in bekleyen, bekleyen
        assert hata is None, f"ikinci onay başarısız: {hata!r}"
        assert await _surumler(ortam) == [1, 2]  # B3-5: yeniden onay YENİ sürüm


async def test_EVBORC5_KONTROL_without_site_lock_approvals_collide(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POZİTİF KONTROL: durum kontrolü AYNI, kilit YOK → iki onay da sürüm 1 → UQ çakışması."""
    original = access.assert_site_writable

    async def _kilitsiz(session, site_id, *, message, lock=True):  # noqa: ANN001, ANN202, ARG001
        await original(session, site_id, message=message, lock=False)

    monkeypatch.setattr(report_daily, "assert_site_writable", _kilitsiz)
    async with _yaris_ortami() as ortam:
        _, hata = await _yaris(ortam, bekle=False)

        assert isinstance(hata, IntegrityError), f"kilitsiz de temiz geçti: {hata!r}"
        assert await _surumler(ortam) == [1]


async def test_EVBORC5_approve_rereads_status_from_db_not_stale_context(
    seeded_db, santiye, admin
) -> None:
    """Uç bağımlılığı kilitsiz ve istek başındaki `ctx.site`e bakar; servis DB'den kilit altında
    yeniden okumalı. Bayat bağlam (DB `completed`, nesne `active`) → onay 409 (baseline/günlük
    GEREKMEZ: kural servisin ilk satırıdır)."""
    from app.core.errors import ConflictError
    from app.modules.earned_value import guards
    from tests.earned_value_budget.test_b30_single_rule import _aktor, _bayat_tamamla

    await _bayat_tamamla(seeded_db, santiye)
    with pytest.raises(ConflictError) as exc:
        await report_daily.approve(seeded_db, santiye.id, DAY, await _aktor(seeded_db))
    assert str(exc.value) == guards.SITE_COMPLETED_BUDGET_READ_ONLY
