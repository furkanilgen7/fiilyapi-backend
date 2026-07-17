from sqlalchemy import select, text

from app.core.permissions import AccessLevel
from app.modules.roles.models import Module, Role, RolePermission
from app.modules.roles.seed_data import seed_reference_data

EXPECTED_ROLE_KEYS = {
    "system_admin",
    "patron",
    "site_chief",
    "field_engineer",
    "hr_manager",
    "accounting",
    "project_manager",
    "procurement",
}

EXPECTED_MODULE_KEYS = {
    "dashboard",
    "approvals",
    "site_diary",
    "timesheet",
    "personnel",
    "payroll",
    "inventory",
    "procurement",
    "progress_payments",
    "accounting",
    "treasury",
    "settings",
    "user_management",
}


async def _level_of(session, role_key: str, module_key: str) -> AccessLevel:
    stmt = (
        select(RolePermission.access_level)
        .join(Role, Role.id == RolePermission.role_id)
        .join(Module, Module.id == RolePermission.module_id)
        .where(Role.key == role_key, Module.key == module_key)
    )
    return (await session.execute(stmt)).scalar_one()


async def test_seeds_eight_roles(seeded_db):
    keys = set((await seeded_db.execute(select(Role.key))).scalars())
    assert keys == EXPECTED_ROLE_KEYS


async def test_seeds_thirteen_modules(seeded_db):
    keys = set((await seeded_db.execute(select(Module.key))).scalars())
    assert keys == EXPECTED_MODULE_KEYS


async def test_matrix_is_complete(seeded_db):
    """8 rol × 13 modül = 104 hücre; hiçbiri eksik olamaz."""
    rows = (await seeded_db.execute(select(RolePermission))).scalars().all()
    assert len(rows) == 104


async def test_system_admin_has_admin_level_everywhere(seeded_db):
    for module_key in EXPECTED_MODULE_KEYS:
        assert await _level_of(seeded_db, "system_admin", module_key) == AccessLevel.admin


async def test_patron_cannot_access_settings(seeded_db):
    """Spec §5.2: Patron'un Ayarlar erişimi yok — mockup çelişkisi İzin Matrisi lehine çözüldü."""
    assert await _level_of(seeded_db, "patron", "settings") == AccessLevel.none
    assert await _level_of(seeded_db, "patron", "user_management") == AccessLevel.none


async def test_patron_has_full_but_not_admin_on_payroll(seeded_db):
    """Patron silemez — full, admin değil."""
    assert await _level_of(seeded_db, "patron", "payroll") == AccessLevel.full


async def test_site_chief_can_only_draft_progress_payments(seeded_db):
    assert await _level_of(seeded_db, "site_chief", "progress_payments") == AccessLevel.draft


async def test_field_engineer_can_only_view_timesheet(seeded_db):
    """Saha Mühendisi puantajı görür ama giremez — Şantiye Şefi'nden tek farkı budur."""
    assert await _level_of(seeded_db, "field_engineer", "timesheet") == AccessLevel.view
    assert await _level_of(seeded_db, "site_chief", "timesheet") == AccessLevel.full


async def test_hr_manager_is_confined_to_people_modules(seeded_db):
    for module_key in ("personnel", "payroll", "timesheet"):
        assert await _level_of(seeded_db, "hr_manager", module_key) == AccessLevel.full
    for module_key in ("accounting", "treasury", "inventory", "site_diary"):
        assert await _level_of(seeded_db, "hr_manager", module_key) == AccessLevel.none


async def test_reseed_after_permissions_wiped_restores_full_matrix(db_session):
    """roles/modules mevcutken role_permissions bosaltilip yeniden seed edilirse
    104 izin satirinin tamami geri gelmeli - kismi/basarisiz bir onceki calistirma
    sonrasi operasyonel yeniden calistirmayi simule eder."""
    await seed_reference_data(db_session)

    await db_session.execute(RolePermission.__table__.delete())
    await db_session.flush()
    remaining = (await db_session.execute(select(RolePermission))).scalars().all()
    assert len(remaining) == 0

    await seed_reference_data(db_session)

    rows = (await db_session.execute(select(RolePermission))).scalars().all()
    assert len(rows) == 104

    role_count = (await db_session.execute(select(Role))).scalars().all()
    module_count = (await db_session.execute(select(Module))).scalars().all()
    assert len(role_count) == 8
    assert len(module_count) == 13


async def test_reseed_from_fully_seeded_state_is_a_noop(seeded_db):
    """Tamamen seed edilmis bir DB'ye tekrar seed_reference_data cagirmak
    UNIQUE(role_id, module_id) ihlali firlatmamali ve satir sayisi degismemeli."""
    await seed_reference_data(seeded_db)

    roles = (await seeded_db.execute(select(Role))).scalars().all()
    modules = (await seeded_db.execute(select(Module))).scalars().all()
    permissions = (await seeded_db.execute(select(RolePermission))).scalars().all()

    assert len(roles) == 8
    assert len(modules) == 13
    assert len(permissions) == 104


async def test_users_table_exists_in_test_schema(seeded_db):
    """users modeli hicbir yerde import edilmezse Base.metadata bu tabloyu bilmez ve
    create_all onu sessizce atlar. Bu test, semanin users tablosunu gercekten
    icerdigini dogrudan introspection ile kanitlar."""
    result = await seeded_db.execute(text("SELECT to_regclass('public.users')"))
    assert result.scalar_one() is not None
