"""EV-BORC-9: Planlama Paneli disiplin tablosunun `non_direct` satırı mockup'a uyar.

Spec: PLANLAMA-SPEC.md S32 (kullanıcı 2026-09-26) — ad "Genel / Dolaylı · bütçe dışı"
(`Planlama - Panel.dc.html` Ö:542) + alt etikette dolaylı kalem adları, BOQ sırasında.

Kurgu: `conftest.py`nin `boq`/`disiplinler` fikstürü yalnız İKİ kalem taşır (I1 KAB/own
"Beton", I2 DUV/subcon "Tuğla") — ikisi de DİREKT kalır (bütçe > 0, filtreli disiplin
satırları boşalmaz — bkz. `report_panel._empty` benzeri "seçilen filtrede kalem yok"
korumasi). Dolaylı (is_direct=False) kalem fikstürde YOK; bu testte KENDİ kalemlerimizi
ekliyoruz, fikstür DEĞİŞTİRİLMEDİ:
  I3  g1 (KAB/own)    "01.002 Mobilizasyon"      sort_order=2, is_direct=False
  I4  g1 (KAB/own)    "01.003 Mobilizasyon"      sort_order=3, is_direct=False (AD TEKRARI)
  I5  g2 (DUV/subcon) "02.002 Şantiye temizliği" sort_order=2, is_direct=False

BOQ sırası: disiplin (KAB sort=1 → DUV sort=2) → grup → kalem (sort_order, code).
Beklenen dolaylı ad listesi (filtresiz): ["Mobilizasyon", "Şantiye temizliği"] — I3 önce
(KAB), I4'ün tekrar eden "Mobilizasyon"u tekilleştirilir, sonra I5 (DUV).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.boq.models import BoqItem
from app.modules.earned_value.report_panel import NON_DIRECT_ROW_NAME

from .conftest import DAY
from .test_budget_api import _map, _rates, _url

D = Decimal


def _panel_url(site) -> str:  # noqa: ANN001
    return f"/sites/{site.id}/earned-value/panel"


async def _get_panel(client, headers, site, **params):  # noqa: ANN001, ANN003, ANN202
    resp = await client.get(
        _panel_url(site), headers=headers, params={"date": DAY.isoformat(), **params}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.fixture
async def dolayli_kalemler(seeded_db, santiye, boq):  # noqa: ANN001, ANN201
    """I1/I2 direkt kalır; üç YENİ kalem (I3, I4, I5) dolaylı — I4 I3 ile ad tekrarlı."""
    i3 = BoqItem(
        site_id=santiye.id,
        group_id=boq["g1"].id,
        code="01.002",
        description="Mobilizasyon",
        unit="ay",
        quantity=D(1),
        unit_price=D(0),
        sort_order=2,
    )
    i4 = BoqItem(
        site_id=santiye.id,
        group_id=boq["g1"].id,
        code="01.003",
        description="Mobilizasyon",  # I3 ile AYNI ad — tekilleştirme testi
        unit="ay",
        quantity=D(1),
        unit_price=D(0),
        sort_order=3,
    )
    i5 = BoqItem(
        site_id=santiye.id,
        group_id=boq["g2"].id,
        code="02.002",
        description="Şantiye temizliği",
        unit="ay",
        quantity=D(1),
        unit_price=D(0),
        sort_order=2,
    )
    seeded_db.add_all([i3, i4, i5])
    await seeded_db.flush()
    return {"i3": i3, "i4": i4, "i5": i5}


@pytest.fixture
async def dolayli_baseline(client, admin, santiye, boq, disiplinler, dolayli_kalemler) -> None:
    await _map(client, santiye, admin, boq, disiplinler)
    await _rates(client, santiye, admin, boq)
    for item in dolayli_kalemler.values():
        resp = await client.patch(
            _url(santiye, f"/items/{item.id}"), headers=admin, json={"is_direct": False}
        )
        assert resp.status_code == 200, resp.text
    resp = await client.post(_url(santiye, "/freeze"), headers=admin, json={})
    assert resp.status_code == 200, resp.text


def _non_direct_row(panel: dict) -> dict:
    row = next(r for r in panel["rows"] if r["scope"] == "non_direct")
    return row


async def test_non_direct_row_name_matches_mockup(
    client, admin, santiye, boq, disiplinler, dolayli_baseline
) -> None:
    panel = await _get_panel(client, admin, santiye)
    row = _non_direct_row(panel)
    assert row["name"] == NON_DIRECT_ROW_NAME == "Genel / Dolaylı · bütçe dışı"


async def test_non_direct_row_lists_indirect_item_names_in_boq_order_deduped(
    client, admin, santiye, boq, disiplinler, dolayli_baseline
) -> None:
    panel = await _get_panel(client, admin, santiye)
    row = _non_direct_row(panel)
    assert row["indirect_item_names"] == ["Mobilizasyon", "Şantiye temizliği"]


async def test_other_rows_have_empty_indirect_item_names(
    client, admin, santiye, boq, disiplinler, dolayli_baseline
) -> None:
    panel = await _get_panel(client, admin, santiye)
    others = [r for r in panel["rows"] if r["scope"] != "non_direct"]
    assert others  # en az bir satır var (overall vb.)
    assert all(r["indirect_item_names"] == [] for r in others)


async def test_indirect_item_names_consistent_with_contractor_filter(
    client, admin, santiye, boq, disiplinler, dolayli_baseline
) -> None:
    own = await _get_panel(client, admin, santiye, contractor_type="own")
    assert _non_direct_row(own)["indirect_item_names"] == ["Mobilizasyon"]
    subcon = await _get_panel(client, admin, santiye, contractor_type="subcon")
    assert _non_direct_row(subcon)["indirect_item_names"] == ["Şantiye temizliği"]
