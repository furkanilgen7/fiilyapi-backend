"""§3.10 F0-8: tamamlanmış şantiyenin planlama ayarları SALT OKUNUR (PUT → 409)."""

from __future__ import annotations

from app.modules.sites.models import SiteStatus


async def test_F0_8_completed_site_settings_are_read_only(
    client, admin, seeded_db, santiye
) -> None:
    url = f"/sites/{santiye.id}/earned-value/settings"
    current = (await client.get(url, headers=admin)).json()
    body = {
        k: current[k]
        for k in (
            "week_start_dow",
            "weekly_off_days",
            "standard_daily_hours",
            "tolerance_points",
            "pf_bands",
            "holidays",
            "composite_metrics",
        )
    }
    assert (await client.put(url, headers=admin, json=body)).status_code == 200
    santiye.status = SiteStatus.completed
    await seeded_db.flush()
    resp = await client.put(url, headers=admin, json=body)
    assert resp.status_code == 409
    assert "salt okunur" in resp.json()["detail"]
    assert (await client.get(url, headers=admin)).status_code == 200  # okuma serbest
