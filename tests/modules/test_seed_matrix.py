from sqlalchemy import select, text

from app.core.access import AccessLevel, satisfies
from app.modules.roles.models import Module, ModuleGroup, Role, RolePermission
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
    "projects",
    "sites",
    "site_diary",
    "timesheet",
    "personnel",
    "payroll",
    "inventory",
    "procurement",
    "progress_payments",
    "accounting",
    "invoicing",
    "treasury",
    "settings",
    "user_management",
    "boq",
    "contracts",
    "sales",
    "documents",
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


async def test_seeds_twenty_modules(seeded_db):
    keys = set((await seeded_db.execute(select(Module.key))).scalars())
    assert keys == EXPECTED_MODULE_KEYS


async def test_matrix_is_complete(seeded_db):
    """8 rol × 20 modül = 160 hücre; hiçbiri eksik olamaz."""
    rows = (await seeded_db.execute(select(RolePermission))).scalars().all()
    assert len(rows) == 160


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
    160 izin satirinin tamami geri gelmeli - kismi/basarisiz bir onceki calistirma
    sonrasi operasyonel yeniden calistirmayi simule eder."""
    await seed_reference_data(db_session)

    await db_session.execute(RolePermission.__table__.delete())
    await db_session.flush()
    remaining = (await db_session.execute(select(RolePermission))).scalars().all()
    assert len(remaining) == 0

    await seed_reference_data(db_session)

    rows = (await db_session.execute(select(RolePermission))).scalars().all()
    assert len(rows) == 160

    role_count = (await db_session.execute(select(Role))).scalars().all()
    module_count = (await db_session.execute(select(Module))).scalars().all()
    assert len(role_count) == 8
    assert len(module_count) == 20


async def test_invoicing_module_is_in_mali_group_between_accounting_and_treasury(seeded_db):
    """Fatura Yönetimi, Muhasebe'den ayrı bir ana menü maddesidir (mockup sidebar sırası)."""
    stmt = select(Module.key, Module.group, Module.sort_order).where(
        Module.key.in_(("accounting", "invoicing", "treasury"))
    )
    by_key = {row.key: row for row in (await seeded_db.execute(stmt)).all()}

    assert by_key["invoicing"].group == ModuleGroup.MALI
    assert by_key["accounting"].sort_order < by_key["invoicing"].sort_order
    assert by_key["invoicing"].sort_order < by_key["treasury"].sort_order


async def test_invoicing_permissions_follow_accounting_row(seeded_db):
    """En az ayrıcalık: muhasebe tam, PM görüntüle, saha rolleri yok."""
    assert await _level_of(seeded_db, "accounting", "invoicing") == AccessLevel.full
    assert await _level_of(seeded_db, "system_admin", "invoicing") == AccessLevel.admin
    assert await _level_of(seeded_db, "patron", "invoicing") == AccessLevel.full
    assert await _level_of(seeded_db, "project_manager", "invoicing") == AccessLevel.view
    for role_key in ("site_chief", "field_engineer", "hr_manager", "procurement"):
        assert await _level_of(seeded_db, role_key, "invoicing") == AccessLevel.none


async def test_module_sort_orders_are_unique_and_contiguous(seeded_db):
    """invoicing/projects/sites/boq araya girince sonraki moduller kayar; boşluk/çakışma olmaz."""
    orders = sorted((await seeded_db.execute(select(Module.sort_order))).scalars())
    assert orders == list(range(1, 21))


async def test_users_table_exists_in_test_schema(seeded_db):
    """users modeli hicbir yerde import edilmezse Base.metadata bu tabloyu bilmez ve
    create_all onu sessizce atlar. Bu test, semanin users tablosunu gercekten
    icerdigini dogrudan introspection ile kanitlar."""
    result = await seeded_db.execute(text("SELECT to_regclass('public.users')"))
    assert result.scalar_one() is not None


async def test_projects_module_row_and_sort(seeded_db):
    """projects: GENEL grubunda, approvals ile site_diary arasında (spec §4)."""
    modules = (await seeded_db.execute(select(Module))).scalars().all()
    by_key = {m.key: m for m in modules}
    assert by_key["projects"].group is ModuleGroup.GENEL
    assert by_key["projects"].name == "Projeler"
    assert by_key["approvals"].sort_order < by_key["projects"].sort_order
    assert by_key["projects"].sort_order < by_key["site_diary"].sort_order


async def test_projects_permissions_match_dashboard_row(seeded_db):
    """projects satiri dashboard satirinin aynisidir (spec §4 gerekce)."""
    for role_key in (
        "system_admin",
        "patron",
        "site_chief",
        "field_engineer",
        "hr_manager",
        "accounting",
        "project_manager",
        "procurement",
    ):
        assert await _level_of(seeded_db, role_key, "projects") == await _level_of(
            seeded_db, role_key, "dashboard"
        )


async def test_procurement_cannot_see_projects(seeded_db):
    assert await _level_of(seeded_db, "procurement", "projects") == AccessLevel.none


async def test_sites_module_row_and_sort(seeded_db):
    """sites: GENEL grubunda, projects ile site_diary arasında (spec §5.1)."""
    modules = (await seeded_db.execute(select(Module))).scalars().all()
    by_key = {m.key: m for m in modules}
    assert by_key["sites"].group is ModuleGroup.GENEL
    assert by_key["sites"].name == "Şantiyeler"
    assert by_key["projects"].sort_order < by_key["sites"].sort_order
    assert by_key["sites"].sort_order < by_key["site_diary"].sort_order


async def test_sites_permissions_match_projects_row_except_procurement(seeded_db):
    """sites satiri projects satirini izler; TEK istisna Satinalma (asagida)."""
    for role_key in EXPECTED_ROLE_KEYS - {"procurement"}:
        assert await _level_of(seeded_db, role_key, "sites") == await _level_of(
            seeded_db, role_key, "projects"
        )


async def test_procurement_sees_sites_but_not_projects(seeded_db):
    """Kullanici onayli BILINCLI istisna (2026-07-28): Satinalma projeyi gormez
    ama santiyeleri goruntuleyebilir. Tutarsiz gorunur, kasitlidir."""
    assert await _level_of(seeded_db, "procurement", "projects") == AccessLevel.none
    assert await _level_of(seeded_db, "procurement", "sites") == AccessLevel.view


async def test_project_manager_can_create_sites(seeded_db):
    """Proje Muduru santiye/bolum acabilmeli (spec §5.1 gerekce)."""
    assert await _level_of(seeded_db, "project_manager", "sites") == AccessLevel.full


async def test_procurement_and_site_chief_cannot_write_sites(seeded_db):
    """Ikisi de santiye TANIMLAMAZ: view seviyesi yazma uclarini acmaz (spec §5.1)."""
    for role_key in ("procurement", "site_chief"):
        assert await _level_of(seeded_db, role_key, "sites") == AccessLevel.view


async def test_boq_module_row_and_sort(seeded_db):
    """boq: GENEL grubunda, matrisin son (17.) satiri (spec §4)."""
    modules = (await seeded_db.execute(select(Module))).scalars().all()
    by_key = {m.key: m for m in modules}
    assert by_key["boq"].group is ModuleGroup.GENEL
    assert by_key["boq"].name == "İş Kalemleri"
    assert by_key["boq"].sort_order == 17


async def test_site_chief_can_see_boq_but_field_engineer_cannot(seeded_db):
    """Spec §4 kullanici karari: 'santiye sefi gorsun de saha muhendisi gormesin'.

    `sites` satirinda bu iki rol birebir ayni (_LIM, _LIM) oldugu icin ayrim
    ancak ayri `boq` modulu ile mumkun — bu testin varligi o kararin kanitidir.
    """
    assert await _level_of(seeded_db, "site_chief", "boq") == AccessLevel.view
    assert await _level_of(seeded_db, "field_engineer", "boq") == AccessLevel.none


async def test_boq_permissions_match_sites_row_except_field_engineer_and_hr(seeded_db):
    """boq satiri temel olarak sites satirini izler; bilincli istisnalar (spec §4):
    field_engineer ve hr_manager gormez. procurement 2026-07-30 kullanici karariyla
    artik sites satirindan SAPMIYOR (view/limited) — istisna listesinden cikarildi."""
    exceptions = {"field_engineer", "hr_manager"}
    for role_key in EXPECTED_ROLE_KEYS - exceptions:
        assert await _level_of(seeded_db, role_key, "boq") == await _level_of(
            seeded_db, role_key, "sites"
        )


async def test_contracts_view_implies_progress_payments_view(seeded_db):
    """Çapraz-modül değişmezi (H9 denetim Y1): `contracts >= view` olan HİÇBİR

    rol `progress_payments < view` olamaz.

    Gerekçe: `EmployerContractDetail.progress_payment_summary`
    (`contracts/service.py`) hakedişin kümülatif brüt/avans/teminat/net
    finansallarını `contracts` kapısının (`_VIEW`/`_FULL`) ARKASINDA gömer —
    `progress_payments` kapısından hiç geçmeden. Bu güvenli tek şart matrisi
    ihlal etmemesidir: bugün 8 rolün hiçbiri ihlal etmiyor (`router.py:69-74`
    yorumundaki iddianın kanıtı budur), ama bu test yoksa gelecekte İzin
    Matrisi ekranından bir role `contracts=view` + `progress_payments=none`
    verilirse, o rol `progress_payments` izni olmadan E14 detayı üzerinden
    hakediş finansallarını okuyabilir hale gelir ve hiçbir test kırmızıya
    dönmez.
    """
    for role_key in EXPECTED_ROLE_KEYS:
        contracts_level = await _level_of(seeded_db, role_key, "contracts")
        progress_payments_level = await _level_of(seeded_db, role_key, "progress_payments")
        if satisfies(contracts_level, AccessLevel.view):
            assert satisfies(progress_payments_level, AccessLevel.view), (
                f"{role_key}: contracts={contracts_level} ama "
                f"progress_payments={progress_payments_level} — gömülü özet izin "
                "arka kapısı açıyor"
            )


async def test_sales_module_row_and_sort(seeded_db):
    """sales: MALI grubunda, 19. sirada (P8 spec §8 S1 — mevcut sira KAYDIRILMAZ).

    Artik EN SON degildir: `documents` 20. sira olarak arkasina eklendi (belge
    cekirdegi spec §6). Sira sabiti acikca yazilir ki bir sonraki modul sona
    eklendiginde bu test sessizce kaymasin."""
    modules = (await seeded_db.execute(select(Module))).scalars().all()
    by_key = {m.key: m for m in modules}
    assert by_key["sales"].group is ModuleGroup.MALI
    assert by_key["sales"].name == "Satış Yönetimi"
    assert by_key["sales"].sort_order == 19


async def test_sales_permissions_match_contracts_row(seeded_db):
    """sales satiri contracts satirinin aynisidir (P8 spec §8 S1 gerekce)."""
    for role_key in EXPECTED_ROLE_KEYS:
        assert await _level_of(seeded_db, role_key, "sales") == await _level_of(
            seeded_db, role_key, "contracts"
        )


async def test_field_roles_cannot_see_sales(seeded_db):
    """Satis bedeli ve alici kimligi saha/IK/satinalma rollerine KAPALI."""
    for role_key in ("site_chief", "field_engineer", "hr_manager", "procurement"):
        assert await _level_of(seeded_db, role_key, "sales") == AccessLevel.none
    assert await _level_of(seeded_db, "accounting", "sales") == AccessLevel.view
    assert await _level_of(seeded_db, "project_manager", "sales") == AccessLevel.full
    assert await _level_of(seeded_db, "system_admin", "sales") == AccessLevel.admin


async def test_documents_module_row_and_sort(seeded_db):
    """documents: MALI grubunda, en sonda (belge cekirdegi spec §6 / §7 S2)."""
    modules = (await seeded_db.execute(select(Module))).scalars().all()
    by_key = {m.key: m for m in modules}
    assert by_key["documents"].group is ModuleGroup.MALI
    assert by_key["documents"].name == "Belgeler"
    assert by_key["documents"].sort_order == 20
    assert by_key["documents"].sort_order == max(m.sort_order for m in modules)


async def test_documents_permissions_match_spec_row(seeded_db):
    """Arsiv ORTAK hafizadir: hicbir rol `none` degil (contracts/sales'ten ayrim).

    Saha (sef + saha muhendisi) ve muhasebe YAZAR; IK, proje muduru ve satinalma
    yalniz OKUR; silme yalniz system_admin'dedir.
    """
    beklenen = {
        "system_admin": AccessLevel.admin,
        "patron": AccessLevel.full,
        "site_chief": AccessLevel.full,
        "field_engineer": AccessLevel.full,
        "hr_manager": AccessLevel.view,
        "accounting": AccessLevel.full,
        "project_manager": AccessLevel.view,
        "procurement": AccessLevel.view,
    }
    for role_key, level in beklenen.items():
        assert await _level_of(seeded_db, role_key, "documents") == level
        assert level is not AccessLevel.none
