"""PLN-B1.3 — santiye EV ayarlari (AYP): GET varsayilan + PUT TAM DEGISTIRME + dogrulama.

Spec: PLANLAMA-SPEC §3.8 K1 (santiye kapsami, sirket katmani yok) · K5 (Pazartesi) ·
K6 (tolerans 2,0) · K7 (baslangic/bitis ALAN DEGIL) · K19 (gunluk ucuncu esik) ·
K25 (pacal tek olcu) · §3.7 S5 (n. hafta kurali YOK) · S6 (gunluk bantlar).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.models import BoqItem
from app.modules.earned_value import defaults, guards
from app.modules.earned_value.models import EvCompositeMetric, EvHoliday, EvSiteSettings
from app.modules.sites.guards import SITE_MISSING
from app.modules.sites.models import Site

from .conftest import LoginFn, audit_details, settings_url


def body(**overrides) -> dict:
    """Gecerli tam govde (mockup AYP ornegi, K5 Pazartesi ile)."""
    base = {
        "week_start_dow": 4,
        "weekly_off_days": [6],
        "standard_daily_hours": "9",
        "tolerance_points": "2.0",
        "pf_bands": {
            "daily": {"red_below": "0.95", "green_from": "0.95", "high_above": "1.05"},
            "weekly": {"red_below": "0.95", "green_from": "1.00"},
        },
        "holidays": [],
        "composite_metrics": [],
    }
    return {**base, **overrides}


def bands(daily=("0.95", "0.95", "1.05"), weekly=("0.95", "1.00")) -> dict:
    return {
        "daily": dict(zip(("red_below", "green_from", "high_above"), daily, strict=True)),
        "weekly": dict(zip(("red_below", "green_from"), weekly, strict=True)),
    }


def pacal(name: str, numerator: list[BoqItem], denominator: BoqItem, measure="spent") -> dict:
    return {
        "name": name,
        "measure": measure,
        "numerator_item_ids": [str(i.id) for i in numerator],
        "denominator_item_id": str(denominator.id),
    }


def _loc_fields(resp) -> set[str]:
    return {str(err["loc"][-1]) for err in resp.json()["detail"]}


# ------------------------------------------------------------------- GET


async def test_satir_yoksa_varsayilanlar_is_default_true(
    client: AsyncClient, admin, santiye: Site
) -> None:
    resp = await client.get(settings_url(santiye.id), headers=admin)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["is_default"] is True
    assert data["week_start_dow"] == defaults.WEEK_START_DOW == 0  # K5 Pazartesi
    assert data["weekly_off_days"] == [6]  # S5 Pazar
    assert Decimal(data["standard_daily_hours"]) == Decimal("9")
    assert Decimal(data["tolerance_points"]) == Decimal("2.0")  # K6
    daily = {k: Decimal(v) for k, v in data["pf_bands"]["daily"].items()}
    assert daily == {
        "red_below": Decimal("0.95"),
        "green_from": Decimal("0.95"),
        "high_above": Decimal("1.05"),
    }
    weekly = {k: Decimal(v) for k, v in data["pf_bands"]["weekly"].items()}
    assert weekly == {"red_below": Decimal("0.95"), "green_from": Decimal("1.00")}
    assert data["holidays"] == [] and data["composite_metrics"] == []
    assert data["updated_at"] is None and data["updated_by"] is None
    # K7: baslangic/bitis ayar degildir.
    assert "start_date" not in data and "end_date" not in data


async def test_get_audit_yazmaz(
    client: AsyncClient, admin, santiye: Site, seeded_db: AsyncSession
) -> None:
    before = len(await audit_details(seeded_db))
    await client.get(settings_url(santiye.id), headers=admin)
    assert len(await audit_details(seeded_db)) == before


# ------------------------------------------------------------------- PUT


async def test_put_yazar_get_ile_ayni_govdeyi_doner_ve_audit_yazar(
    client: AsyncClient,
    login: LoginFn,
    santiye: Site,
    kalemler: list[BoqItem],
    seeded_db: AsyncSession,
) -> None:
    headers = await login("field_engineer")  # DRAFT = WRITE yeter (B1-8)
    kalip, demir, beton = kalemler
    payload = body(
        weekly_off_days=[6, 5],
        holidays=[
            {"date_from": "2026-10-29", "date_to": "2026-10-29", "note": "Cumhuriyet Bayramı"},
            {"date_from": "2026-05-26", "date_to": "2026-05-30", "note": "Kurban Bayramı"},
        ],
        composite_metrics=[
            pacal("1 m³ beton başına a-s", [kalip, demir, beton], beton),
            pacal("Beton bütçe", [beton], beton, measure="budget"),
        ],
    )
    resp = await client.put(settings_url(santiye.id), json=payload, headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["is_default"] is False
    assert data["week_start_dow"] == 4
    assert data["weekly_off_days"] == [5, 6]  # sirali
    assert [h["date_from"] for h in data["holidays"]] == ["2026-05-26", "2026-10-29"]
    assert data["holidays"][0]["note"] == "Kurban Bayramı"
    assert [m["name"] for m in data["composite_metrics"]] == [
        "1 m³ beton başına a-s",
        "Beton bütçe",
    ]
    first = data["composite_metrics"][0]
    assert first["measure"] == "spent"
    assert first["numerator_item_ids"] == [str(kalip.id), str(demir.id), str(beton.id)]
    assert first["denominator_item_id"] == str(beton.id)
    assert data["updated_by"]["full_name"] == "Kişi field_engineer"
    assert data["updated_at"] is not None

    again = await client.get(settings_url(santiye.id), headers=headers)
    assert again.json() == data

    details = await audit_details(seeded_db)
    assert "Planlama ayarları kaydedildi: Güneşkent Konut · A-Blok Şantiyesi" in details


async def test_ikinci_put_govdeden_cikani_siler_baska_santiyeye_dokunmaz(
    client: AsyncClient,
    admin,
    santiye: Site,
    ikinci_santiye: Site,
    kalemler: list[BoqItem],
    seeded_db: AsyncSession,
) -> None:
    kalip, _, beton = kalemler
    other = body(holidays=[{"date_from": "2026-01-01", "date_to": "2026-01-01", "note": "Y"}])
    assert (await client.put(settings_url(ikinci_santiye.id), json=other, headers=admin)).is_success

    first = body(
        holidays=[
            {"date_from": "2026-05-01", "date_to": "2026-05-01", "note": "İşçi"},
            {"date_from": "2026-08-30", "date_to": "2026-08-30", "note": "Zafer"},
        ],
        composite_metrics=[pacal("A", [kalip], beton), pacal("B", [beton], beton)],
    )
    assert (await client.put(settings_url(santiye.id), json=first, headers=admin)).is_success

    second = body(
        holidays=[{"date_from": "2026-08-30", "date_to": "2026-08-30", "note": "Zafer"}],
        composite_metrics=[pacal("B", [beton], beton)],
    )
    resp = await client.put(settings_url(santiye.id), json=second, headers=admin)
    assert resp.status_code == 200, resp.text
    assert [h["note"] for h in resp.json()["holidays"]] == ["Zafer"]
    assert [m["name"] for m in resp.json()["composite_metrics"]] == ["B"]

    def count(model, site: Site):
        return select(func.count()).select_from(model).where(model.site_id == site.id)

    assert (await seeded_db.execute(count(EvHoliday, santiye))).scalar_one() == 1
    assert (await seeded_db.execute(count(EvCompositeMetric, santiye))).scalar_one() == 1
    # Baska santiye: satiri ve tatili yerinde.
    assert (await seeded_db.execute(count(EvHoliday, ikinci_santiye))).scalar_one() == 1
    assert await seeded_db.get(EvSiteSettings, ikinci_santiye.id) is not None

    third = body()
    resp = await client.put(settings_url(santiye.id), json=third, headers=admin)
    assert resp.json()["holidays"] == [] and resp.json()["composite_metrics"] == []


async def test_pacal_payinda_tekrar_eden_kalem_tek_terime_iner(
    client: AsyncClient, admin, santiye: Site, kalemler: list[BoqItem]
) -> None:
    kalip, _, beton = kalemler
    payload = body(composite_metrics=[pacal("A", [kalip, kalip, beton], beton)])
    resp = await client.put(settings_url(santiye.id), json=payload, headers=admin)
    assert resp.status_code == 200, resp.text
    ids = resp.json()["composite_metrics"][0]["numerator_item_ids"]
    assert ids == [str(kalip.id), str(beton.id)]


# ------------------------------------------------------------ dogrulama (422)


@pytest.mark.parametrize(
    ("pf", "message"),
    [
        (bands(daily=("0.96", "0.95", "1.05")), guards.DAILY_BANDS_ORDER),
        (bands(daily=("0.95", "1.06", "1.05")), guards.DAILY_BANDS_ORDER),
        (bands(weekly=("0.95", "0.90")), guards.WEEKLY_BANDS_ORDER),
    ],
    ids=["gunluk-kirmizi>yesil", "gunluk-yesil>yuksek", "haftalik-kirmizi>yesil"],
)
async def test_bant_sirasi_bozuksa_422(
    client: AsyncClient, admin, santiye: Site, pf: dict, message: str
) -> None:
    resp = await client.put(settings_url(santiye.id), json=body(pf_bands=pf), headers=admin)
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == message


async def test_bant_sinirlari_esit_olabilir(client: AsyncClient, admin, santiye: Site) -> None:
    pf = bands(daily=("1.00", "1.00", "1.00"), weekly=("1.00", "1.00"))
    resp = await client.put(settings_url(santiye.id), json=body(pf_bands=pf), headers=admin)
    assert resp.status_code == 200, resp.text


async def test_butun_gunler_tatilse_422(client: AsyncClient, admin, santiye: Site) -> None:
    payload = body(weekly_off_days=[0, 1, 2, 3, 4, 5, 6])
    resp = await client.put(settings_url(santiye.id), json=payload, headers=admin)
    assert resp.status_code == 422
    assert resp.json()["detail"] == guards.ALL_DAYS_OFF


async def test_hic_tatil_gunu_olmayabilir(client: AsyncClient, admin, santiye: Site) -> None:
    resp = await client.put(settings_url(santiye.id), json=body(weekly_off_days=[]), headers=admin)
    assert resp.status_code == 200 and resp.json()["weekly_off_days"] == []


async def test_tatil_bitisi_baslangictan_once_422(
    client: AsyncClient, admin, santiye: Site
) -> None:
    holidays = [{"date_from": "2026-05-30", "date_to": "2026-05-26", "note": ""}]
    resp = await client.put(settings_url(santiye.id), json=body(holidays=holidays), headers=admin)
    assert resp.status_code == 422
    assert resp.json()["detail"] == guards.HOLIDAY_RANGE_INVALID


@pytest.mark.parametrize(
    "second",
    [("2026-05-30", "2026-06-02"), ("2026-05-27", "2026-05-28"), ("2026-05-20", "2026-05-26")],
    ids=["son-gun-ortak", "icinde", "ilk-gun-ortak"],
)
async def test_cakisan_tatiller_422(
    client: AsyncClient, admin, santiye: Site, second: tuple[str, str]
) -> None:
    holidays = [
        {"date_from": "2026-05-26", "date_to": "2026-05-30", "note": "Kurban"},
        {"date_from": second[0], "date_to": second[1], "note": "X"},
    ]
    resp = await client.put(settings_url(santiye.id), json=body(holidays=holidays), headers=admin)
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == guards.HOLIDAY_RANGE_OVERLAP


async def test_bitisik_tatiller_cakisma_sayilmaz(client: AsyncClient, admin, santiye: Site) -> None:
    holidays = [
        {"date_from": "2026-05-31", "date_to": "2026-05-31", "note": "B"},
        {"date_from": "2026-05-26", "date_to": "2026-05-30", "note": "A"},
    ]
    resp = await client.put(settings_url(santiye.id), json=body(holidays=holidays), headers=admin)
    assert resp.status_code == 200, resp.text


async def test_pacal_baska_santiyenin_kalemi_422(
    client: AsyncClient,
    admin,
    santiye: Site,
    kalemler: list[BoqItem],
    yabanci_kalem: BoqItem,
    seeded_db: AsyncSession,
) -> None:
    beton = kalemler[2]
    for metric in (pacal("pay", [yabanci_kalem], beton), pacal("payda", [beton], yabanci_kalem)):
        resp = await client.put(
            settings_url(santiye.id), json=body(composite_metrics=[metric]), headers=admin
        )
        assert resp.status_code == 422, resp.text
        assert resp.json()["detail"] == guards.COMPOSITE_ITEM_FOREIGN
    assert await seeded_db.get(EvSiteSettings, santiye.id) is None


async def test_pacal_olmayan_kalem_ayni_422(
    client: AsyncClient, admin, santiye: Site, kalemler: list[BoqItem]
) -> None:
    metric = {
        "name": "X",
        "measure": "earned",
        "numerator_item_ids": [str(uuid.uuid4())],
        "denominator_item_id": str(kalemler[0].id),
    }
    resp = await client.put(
        settings_url(santiye.id), json=body(composite_metrics=[metric]), headers=admin
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == guards.COMPOSITE_ITEM_FOREIGN


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"standard_daily_hours": "0.5"}, "standard_daily_hours"),
        ({"standard_daily_hours": "16.5"}, "standard_daily_hours"),
        ({"tolerance_points": "-0.1"}, "tolerance_points"),
        ({"week_start_dow": 7}, "week_start_dow"),
        ({"week_start_dow": -1}, "week_start_dow"),
        ({"weekly_off_days": [7]}, 0),
        ({"start_date": "2026-01-01"}, "start_date"),  # K7
        ({"holiday_rules": [{"nth_week": 2, "dow": 5}]}, "holiday_rules"),  # S5
    ],
)
async def test_tek_alan_sinirlari_422_alan_adli(
    client: AsyncClient, admin, santiye: Site, overrides: dict, field
) -> None:
    resp = await client.put(settings_url(santiye.id), json=body(**overrides), headers=admin)
    assert resp.status_code == 422, resp.text
    assert str(field) in _loc_fields(resp)


async def test_sinir_degerleri_kabul(client: AsyncClient, admin, santiye: Site) -> None:
    for hours in ("1", "16"):
        payload = body(standard_daily_hours=hours, tolerance_points="0", week_start_dow=6)
        resp = await client.put(settings_url(santiye.id), json=payload, headers=admin)
        assert resp.status_code == 200, resp.text
        assert Decimal(resp.json()["standard_daily_hours"]) == Decimal(hours)


async def test_pacal_payi_bos_olamaz(
    client: AsyncClient, admin, santiye: Site, kalemler: list[BoqItem]
) -> None:
    metric = pacal("A", [], kalemler[0])
    resp = await client.put(
        settings_url(santiye.id), json=body(composite_metrics=[metric]), headers=admin
    )
    assert resp.status_code == 422
    assert "numerator_item_ids" in _loc_fields(resp)


# ------------------------------------------------------------ kapsam (IDOR)


@pytest.mark.parametrize("method", ["get", "put"])
async def test_gorunmeyen_santiye_olmayanla_ayni_404(
    client: AsyncClient,
    login: LoginFn,
    gorunmeyen_santiye: Site,
    seeded_db: AsyncSession,
    method: str,
) -> None:
    headers = await login("project_manager")  # F: kapiyi gecer, kapsam proje ile sinirli
    kwargs = {"json": body()} if method == "put" else {}
    hidden = await getattr(client, method)(
        settings_url(gorunmeyen_santiye.id), headers=headers, **kwargs
    )
    missing = await getattr(client, method)(settings_url(uuid.uuid4()), headers=headers, **kwargs)
    assert hidden.status_code == missing.status_code == 404
    assert hidden.json() == missing.json() == {"detail": SITE_MISSING}
    assert await seeded_db.get(EvSiteSettings, gorunmeyen_santiye.id) is None
