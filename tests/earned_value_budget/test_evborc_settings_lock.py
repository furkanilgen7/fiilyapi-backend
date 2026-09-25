"""EV-BORC (b) — ayar PUT'unun şantiye satırı kilidi GEREKLİ mi? ÖLÇÜM + bekçi.

B3.0 ayar PUT'una `sites … FOR UPDATE` getirdi (tamamlanmaya karşı durumu kilit altında
yeniden okumak için). Soru: daraltılabilir mi (FOR SHARE / kilitsiz)? Cevap HAYIR, çünkü
kilit İKİNCİ bir iş de görüyor: TAM DEĞİŞTİRME yazmalarını (ayar satırı + tatiller + paçal)
sıraya sokar. Kilitsiz iki eşzamanlı İLK kayıt `ev_site_settings` PK'sında çakışır →
IntegrityError (500). FOR SHARE da yetmez: paylaşımlı kilitler birbirini BEKLETMEZ.

Senaryo: oturum 1 ayarları kaydeder (COMMIT yok, kilit tutulur); oturum 2 aynı anda kaydeder.
* Kilitli (bugünkü kod): oturum 2 `sites … FOR UPDATE`de BEKLER, 1 commit edince temiz yazar.
* POZİTİF KONTROL (kilit `lock=False`): oturum 2 bekleyemez, satır çakışır → IntegrityError.
Kontrol kırmızıya dönerse senaryo artık yarışı üretmiyor demektir (üstteki yeşil boştur).
Bariyer: `pg_stat_activity` bekleyen SORGUSU (PLN-B0 dersi 9); emsal `test_b30_relock_guard`.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.modules.earned_value import access, settings_service
from app.modules.earned_value.models import EvHoliday
from app.modules.earned_value.schemas_settings import SettingsSave
from app.modules.users.models import User
from tests.earned_value.test_settings import body
from tests.earned_value_budget.test_budget_concurrency import (
    _BEKLEME_SINIRI,
    _KESISME_PAYI,
    _bekleyen_sorgu,
    _Ortam,
    _sonlandir,
    _yaris_ortami,
)

pytestmark = pytest.mark.asyncio

_GOVDE = SettingsSave.model_validate(
    body(
        week_start_dow=0,
        holidays=[{"date_from": "2026-05-19", "date_to": "2026-05-19", "note": "Bayram"}],
    )
)


async def _kaydet(ortam: _Ortam, session) -> None:  # noqa: ANN001
    actor = await session.get(User, ortam.actor_id)
    await settings_service.save_settings(session, ortam.site_id, _GOVDE, actor)


async def _ikinci(ortam: _Ortam) -> None:
    async with ortam.Session() as session:
        await _kaydet(ortam, session)
        await session.commit()


async def _yaris(ortam: _Ortam, *, bekle: bool) -> tuple[str, BaseException | None]:
    task: asyncio.Task[None] | None = None
    bekleyen = ""
    async with ortam.Session() as birinci:
        try:
            await _kaydet(ortam, birinci)
            task = asyncio.create_task(_ikinci(ortam))
            if bekle:
                bekleyen = await _bekleyen_sorgu(ortam)
                await asyncio.sleep(_KESISME_PAYI)
                assert not task.done(), "ikinci kayıt birinci commit edilmeden BİTTİ"
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


async def _tatil_sayisi(ortam: _Ortam) -> int:
    async with ortam.Session() as session:
        return await session.scalar(
            select(func.count()).select_from(EvHoliday).where(EvHoliday.site_id == ortam.site_id)
        )


async def test_EVBORC_concurrent_settings_saves_are_serialized_by_site_lock() -> None:
    async with _yaris_ortami() as ortam:
        bekleyen, hata = await _yaris(ortam, bekle=True)

        assert "FROM sites" in bekleyen and "FOR UPDATE" in bekleyen, bekleyen
        assert hata is None, f"ikinci kayıt başarısız: {hata!r}"
        assert await _tatil_sayisi(ortam) == 1


async def test_EVBORC_KONTROL_without_site_lock_first_concurrent_save_collides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POZİTİF KONTROL: durum kontrolü AYNI, kilit YOK → ikinci kayıt PK'da çakışır (500)."""
    original = access.assert_site_writable

    async def _kilitsiz(session, site_id, *, message, lock=True):  # noqa: ANN001, ANN202, ARG001
        await original(session, site_id, message=message, lock=False)

    monkeypatch.setattr(settings_service, "assert_site_writable", _kilitsiz)
    async with _yaris_ortami() as ortam:
        _, hata = await _yaris(ortam, bekle=False)

        assert isinstance(hata, IntegrityError), f"kilitsiz de temiz geçti: {hata!r}"
