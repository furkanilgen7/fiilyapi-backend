"""PLN-B3.0 — "durum kilit ALTINDA yeniden okunur" kuralının eşzamanlılık bekçisi.

Yarış: oturum 1 şantiyeyi "tamamlandı"ya çeker (satır kilidi tutulur, COMMIT yok); oturum 2
aynı anda bir bütçe yazması başlatır. Oturum 2'nin `ctx.site`i kilitten ÖNCE yüklenir →
`active` görür (READ COMMITTED). Doğru yardımcı `sites … FOR UPDATE`de bekler, oturum 1
commit edince durumu YENİDEN okur ve 409 döner. Bayat `ctx.site.status`a güvenen bir yazma
aynı kilitte bekleyip sonra tamamlanmış şantiyeye Rev 0 açardı.

Bariyer (emsal `test_budget_concurrency.py`, PLN-B0 dersi 9): yalnız "bekledi mi" değil
NEREDE beklediği ölçülür — `pg_stat_activity` (`datname` = bu dosyanın tek kullanımlık
veritabanı, `pid` ≠ gözlemci) bekleyen sorgusu `sites … FOR UPDATE` olmalı; ardından
`asyncio.sleep` + `not task.done()`.

POZİTİF KONTROL: `_writable_site` yerine kilidi AYNEN alan ama durumu `ctx.site.status`tan
okuyan bir mutant → aynı senaryoda oturum 2 yazmayı BAŞARIR. Kontrol kırmızıya dönerse
senaryo artık bayat okumayı üretmiyor demektir ve üstteki yeşil bir şey kanıtlamaz.

⚠️ FAT-1 dersi: HEM tek başına HEM dosya/paket bütün koşturulup raporlanır.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError
from app.modules.earned_value import budget_service as svc
from app.modules.earned_value import guards
from app.modules.earned_value.access import SiteContext
from app.modules.sites.models import Site, SiteStatus
from tests.earned_value_budget.test_budget_concurrency import (
    _BEKLEME_SINIRI,
    _KESISME_PAYI,
    _bekleyen_sorgu,
    _ilk_yazma,
    _Ortam,
    _revizyonlar,
    _sonlandir,
    _yaris_ortami,
)

pytestmark = pytest.mark.asyncio


async def _tamamla_kilitli(session: AsyncSession, site_id: uuid.UUID) -> None:
    """Oturum 1: şantiye satırını kilitle + `completed` yaz; COMMIT ETME."""
    site = await session.scalar(select(Site).where(Site.id == site_id).with_for_update())
    assert site is not None and site.status is SiteStatus.active
    site.status = SiteStatus.completed
    await session.flush()


async def _butce_yazmasi(ortam: _Ortam) -> uuid.UUID:
    async with ortam.Session() as session:
        rev_id = await _ilk_yazma(ortam, session, ortam.group_ids[0])
        await session.commit()
        return rev_id


async def _yaris(ortam: _Ortam) -> tuple[str, uuid.UUID | BaseException]:
    task: asyncio.Task[uuid.UUID] | None = None
    async with ortam.Session() as birinci:
        try:
            await _tamamla_kilitli(birinci, ortam.site_id)
            task = asyncio.create_task(_butce_yazmasi(ortam))
            bekleyen = await _bekleyen_sorgu(ortam)
            await asyncio.sleep(_KESISME_PAYI)
            assert not task.done(), "bütçe yazması tamamlama commit edilmeden BİTTİ — kesişmedi"
            await birinci.commit()
        except BaseException:
            await birinci.rollback()
            await _sonlandir(task)
            raise
    assert task is not None
    try:
        sonuc: uuid.UUID | BaseException = await asyncio.wait_for(task, _BEKLEME_SINIRI)
    except (ConflictError, TimeoutError) as exc:
        sonuc = exc
    return bekleyen, sonuc


def _kilit_bekliyor(bekleyen: str) -> bool:
    return "FROM sites" in bekleyen and "FOR UPDATE" in bekleyen


async def test_B30_write_racing_completion_rereads_status_under_lock() -> None:
    async with _yaris_ortami() as ortam:
        bekleyen, sonuc = await _yaris(ortam)

        assert _kilit_bekliyor(bekleyen), f"şantiye satırı kilidinde BEKLEMİYOR: {bekleyen}"
        assert isinstance(sonuc, ConflictError), (
            f"tamamlanmış şantiyeye bütçe yazıldı (bayat ctx ile yazma): {sonuc!r}"
        )
        assert str(sonuc) == guards.SITE_COMPLETED_BUDGET_READ_ONLY
        assert await _revizyonlar(ortam) == []


async def test_B30_KONTROL_stale_ctx_status_lets_write_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POZİTİF KONTROL: kilit AYNI, durum `ctx.site`ten (bayat) → yazma geçer."""

    async def _bayat(session: AsyncSession, ctx: SiteContext) -> None:
        await session.execute(select(Site.id).where(Site.id == ctx.site.id).with_for_update())
        if ctx.site.status is SiteStatus.completed:
            raise ConflictError(guards.SITE_COMPLETED_BUDGET_READ_ONLY)

    monkeypatch.setattr(svc, "_writable_site", _bayat)
    async with _yaris_ortami() as ortam:
        bekleyen, sonuc = await _yaris(ortam)

        assert _kilit_bekliyor(bekleyen), bekleyen
        assert isinstance(sonuc, uuid.UUID), (
            f"mutant da reddetti — senaryo bayat üretmiyor: {sonuc!r}"
        )
        assert await _revizyonlar(ortam) == [(0, "draft")]
