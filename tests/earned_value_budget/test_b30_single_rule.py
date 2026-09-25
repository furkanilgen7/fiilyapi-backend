"""PLN-B3.0 — "tamamlanmış şantiye salt okunur" TEK yardımcıdır ve durumu VERİTABANINDAN okur.

Uç bağımlılığı (`completed_site_guard`) erken 409'u verir; ama servisler uçsuz da
çağrılabilir (port, iş, test) ve bağımlılığın gördüğü `ctx.site` isteğin başında yüklenmiş
bir KOPYADIR. Bu yüzden her yazma servisi `access.assert_site_writable`ı çağırır: şantiye
satırını `FOR UPDATE` kilitler ve `status`u kilit ALTINDA sütun sorgusuyla yeniden okur.

Bayat kopya burada TEK oturumda kurulur: `UPDATE … synchronize_session=False` veritabanını
`completed` yapar, kimlik haritasındaki `Site` nesnesi `active` kalır. Durumu nesneden (ya da
`session.get`/`select(Site)` ile kimlik haritasından) okuyan bir yardımcı bu vakaları
YEŞİL geçemez. Gerçek eşzamanlı hâli `test_b30_relock_guard.py` çakar.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select, update

from app.core.errors import ConflictError
from app.modules.earned_value import budget_ops as ops
from app.modules.earned_value import budget_service as svc
from app.modules.earned_value import diary_adapter as adp
from app.modules.earned_value import guards, settings_service
from app.modules.earned_value.access import SiteContext, assert_site_writable
from app.modules.earned_value.models import EvRevision
from app.modules.earned_value.schemas_settings import SettingsSave
from app.modules.sites.models import Site, SiteStatus
from app.modules.users.models import User

from .conftest import DAY

pytestmark = pytest.mark.asyncio


async def _bayat_tamamla(seeded_db, site: Site) -> None:  # noqa: ANN001
    """Veritabanı `completed`, bellekteki nesne `active` (bayat bağlam)."""
    await seeded_db.execute(
        update(Site)
        .where(Site.id == site.id)
        .values(status=SiteStatus.completed)
        .execution_options(synchronize_session=False)
    )
    assert site.status is SiteStatus.active, "kurgu bozuk: nesne bayat kalmalıydı"


async def _aktor(seeded_db) -> User:  # noqa: ANN001
    user = await seeded_db.scalar(select(User).limit(1))
    assert user is not None
    return user


async def _revizyon_sayisi(seeded_db, site: Site) -> int:  # noqa: ANN001
    return len(
        (await seeded_db.execute(select(EvRevision.id).where(EvRevision.site_id == site.id))).all()
    )


async def test_B30_helper_reads_status_from_db_not_identity_map(seeded_db, santiye) -> None:
    await assert_site_writable(seeded_db, santiye.id, message="x")  # aktif: geçer
    await _bayat_tamamla(seeded_db, santiye)
    with pytest.raises(ConflictError) as exc:
        await assert_site_writable(seeded_db, santiye.id, message="ekran metni")
    assert str(exc.value) == "ekran metni"


@pytest.mark.parametrize("lock", [True, False], ids=["kilitli", "kilitsiz"])
async def test_B30_helper_lock_flag_both_reread(seeded_db, santiye, lock) -> None:
    await _bayat_tamamla(seeded_db, santiye)
    with pytest.raises(ConflictError):
        await assert_site_writable(seeded_db, santiye.id, message="m", lock=lock)


async def test_B30_budget_writes_use_db_status_with_stale_ctx(
    seeded_db, admin, santiye, proje, boq, disiplinler
) -> None:
    """Bayat `ctx` (active) ile her bütçe servis girişi yine 409 — durum kilit altında okunur."""
    actor = await _aktor(seeded_db)
    ctx = SiteContext(site=santiye, project=proje)
    kab, _ = disiplinler
    await _bayat_tamamla(seeded_db, santiye)
    girisler = {
        "group-disciplines": lambda: svc.set_group_disciplines(
            seeded_db, ctx, actor, [(boq["g1"].id, kab.id)]
        ),
        "taslak-ac": lambda: svc.open_draft(seeded_db, ctx, actor),
        "fill": lambda: ops.fill_from_catalog(seeded_db, ctx, actor),
        "freeze": lambda: ops.freeze(seeded_db, ctx, actor, None, None),
    }
    for ad, cagri in girisler.items():
        with pytest.raises(ConflictError) as exc:
            await cagri()
        assert str(exc.value) == guards.SITE_COMPLETED_BUDGET_READ_ONLY, ad
    assert await _revizyon_sayisi(seeded_db, santiye) == 0


async def test_B30_settings_service_refuses_completed_site(seeded_db, admin, santiye) -> None:
    actor = await _aktor(seeded_db)
    current = await settings_service.get_settings(seeded_db, santiye.id)
    data = SettingsSave.model_validate_json(
        current.model_dump_json(include=set(SettingsSave.model_fields))
    )
    await _bayat_tamamla(seeded_db, santiye)
    with pytest.raises(ConflictError) as exc:
        await settings_service.save_settings(seeded_db, santiye.id, data, actor)
    assert str(exc.value) == guards.SITE_COMPLETED_READ_ONLY


async def test_B30_day_adapter_writes_refuse_completed_site(seeded_db, admin, santiye) -> None:
    actor = await _aktor(seeded_db)
    await _bayat_tamamla(seeded_db, santiye)
    with pytest.raises(ConflictError) as exc:
        await adp.save_allocation(seeded_db, santiye.id, DAY, actor, [], [], None)
    assert str(exc.value) == guards.SITE_COMPLETED_DAY_READ_ONLY
    with pytest.raises(ConflictError) as exc:
        await adp.unlock_day(seeded_db, santiye.id, DAY, actor, "gerekçe")
    assert str(exc.value) == guards.SITE_COMPLETED_DAY_READ_ONLY
