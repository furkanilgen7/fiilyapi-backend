from sqlalchemy import select

from app.core.permissions import AccessLevel
from app.modules.roles.models import Module, Role, RolePermission

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
