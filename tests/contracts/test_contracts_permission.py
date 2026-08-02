import pytest

from app.core.access import AccessLevel, Scope
from app.modules.roles.seed_data import MATRIX, MODULES, ROLE_ORDER, seed_reference_data


def test_contracts_modulu_matriste_var():
    anahtarlar = [m["key"] for m in MODULES]
    assert "contracts" in anahtarlar
    assert len(MODULES) == 19


def test_contracts_satiri_dogru_rollere_kapali():
    hucreler = dict(zip(ROLE_ORDER, MATRIX["contracts"], strict=True))
    # Bu modülün var oluş sebebi: projects=_LIM olan roller taşeron
    # birim fiyatlarını GÖRMEMELİ (spec §5).
    for rol in ("site_chief", "field_engineer", "hr_manager", "procurement"):
        assert hucreler[rol][0] == AccessLevel.none
    assert hucreler["system_admin"][0] == AccessLevel.admin
    assert hucreler["patron"][0] == AccessLevel.full
    assert hucreler["project_manager"][0] == AccessLevel.full
    assert hucreler["accounting"] == (AccessLevel.view, Scope.finance)


@pytest.mark.asyncio
async def test_seed_152_izin_satiri_uretir(db_session):
    from sqlalchemy import func, select

    from app.modules.roles.models import RolePermission

    # NOT: brief taslağı bu satırı içermiyordu; db_session (seeded_db değil)
    # kendiliğinden seed edilmediği için testin amacına (152 satır üretimini
    # doğrulamak) ulaşması için seed_reference_data burada açıkça çağrılır.
    await seed_reference_data(db_session)

    toplam = await db_session.scalar(select(func.count()).select_from(RolePermission))
    assert toplam == 8 * 19
