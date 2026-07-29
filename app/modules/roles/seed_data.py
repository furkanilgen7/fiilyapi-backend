"""Rol/modül/izin matrisinin başlangıç değerleri — spec §5.1 ve §5.2.

Bu yalnızca ilk kurulum değeridir. Kullanıcı İzin Matrisi ekranından her hücreyi
değiştirebilir; tek istisna system_admin rolüdür (kilitlenme koruması, spec §5.0).
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import AccessLevel, Scope
from app.modules.roles.models import Module, ModuleGroup, Role, RolePermission

ROLES: list[dict] = [
    {
        "key": "system_admin",
        "name": "Sistem Yöneticisi",
        "emoji": "🛡️",
        "is_system": True,
        "description": "Tüm modüller · Tüm projeler · Ayarlar · Kullanıcı yönetimi · Silme yetkisi",
    },
    {
        "key": "patron",
        "name": "Patron",
        "emoji": "👔",
        "is_system": True,
        "description": "Tüm modüller · Tüm projeler (ayarlar hariç)",
    },
    {
        "key": "site_chief",
        "name": "Şantiye Şefi",
        "emoji": "👷",
        "is_system": False,
        "description": "Günlük kayıt, puantaj, stok görüntüle",
    },
    {
        "key": "field_engineer",
        "name": "Saha Mühendisi",
        "emoji": "📐",
        "is_system": False,
        "description": "Günlük kayıt, hakediş taslağı, puantaj görüntüle",
    },
    {
        "key": "hr_manager",
        "name": "İK Müdürü",
        "emoji": "👥",
        "is_system": False,
        "description": "Personel, puantaj, bordro",
    },
    {
        "key": "accounting",
        "name": "Muhasebe",
        "emoji": "📒",
        "is_system": False,
        "description": "Yevmiye, bordro, hakediş onay, e-fatura",
    },
    {
        "key": "project_manager",
        "name": "Proje Müdürü",
        "emoji": "🏗",
        "is_system": False,
        "description": "Proje görünümü, raporlar, hakediş onay",
    },
    {
        "key": "procurement",
        "name": "Satınalma",
        "emoji": "🛒",
        "is_system": False,
        "description": "Stok, satınalma, teklif, tedarikçi",
    },
]

MODULES: list[dict] = [
    {"key": "dashboard", "name": "Gösterge Paneli", "group": ModuleGroup.GENEL, "sort_order": 1},
    {"key": "approvals", "name": "Onay Kutusu", "group": ModuleGroup.GENEL, "sort_order": 2},
    {"key": "projects", "name": "Projeler", "group": ModuleGroup.GENEL, "sort_order": 3},
    {"key": "sites", "name": "Şantiyeler", "group": ModuleGroup.GENEL, "sort_order": 4},
    {"key": "site_diary", "name": "Günlük Kayıt", "group": ModuleGroup.SAHA, "sort_order": 5},
    {"key": "timesheet", "name": "Puantaj", "group": ModuleGroup.SAHA, "sort_order": 6},
    {"key": "personnel", "name": "Personel", "group": ModuleGroup.SAHA, "sort_order": 7},
    {"key": "payroll", "name": "Bordro", "group": ModuleGroup.SAHA, "sort_order": 8},
    {
        "key": "inventory",
        "name": "Stok & Depo",
        "group": ModuleGroup.STOK_SATINALMA,
        "sort_order": 9,
    },
    {
        "key": "procurement",
        "name": "Satınalma & Teklif",
        "group": ModuleGroup.STOK_SATINALMA,
        "sort_order": 10,
    },
    {
        "key": "progress_payments",
        "name": "Hakedişler",
        "group": ModuleGroup.MALI,
        "sort_order": 11,
    },
    {"key": "accounting", "name": "Muhasebe", "group": ModuleGroup.MALI, "sort_order": 12},
    # Fatura Yönetimi, Muhasebe'nin altında değil ayrı bir ana menü maddesidir
    # (mockup: projedesign/Fatura Yönetimi.dc.html sidebar sırası).
    {"key": "invoicing", "name": "Fatura Yönetimi", "group": ModuleGroup.MALI, "sort_order": 13},
    {"key": "treasury", "name": "Hazine", "group": ModuleGroup.MALI, "sort_order": 14},
    {"key": "settings", "name": "Ayarlar", "group": ModuleGroup.SISTEM, "sort_order": 15},
    {
        "key": "user_management",
        "name": "Kullanıcı & Rol Yönetimi",
        "group": ModuleGroup.SISTEM,
        "sort_order": 16,
    },
    # spec §4 (2026-07-30, boq izin modulu design): ayri modul, "sites"
    # izniyle site_chief/field_engineer ayrilamadigi icin acildi. Ayarlar -
    # Izin Matrisi mockup'inda bu satir YOK — bilincli sapma, geri alinmaz.
    {"key": "boq", "name": "İş Kalemleri", "group": ModuleGroup.GENEL, "sort_order": 17},
]

# Kısayollar — matrisi okunur tutmak için.
_A = (AccessLevel.admin, Scope.all)  # ✓ Süper (silme dahil)
_F = (AccessLevel.full, Scope.all)  # ✓ Tam (silme hariç)
_N = (AccessLevel.none, Scope.all)  # —
_V = (AccessLevel.view, Scope.all)  # Görüntüle
_LIM = (AccessLevel.view, Scope.limited)  # Sınırlı
_FIN = (AccessLevel.view, Scope.finance)  # Mali
_OWN = (AccessLevel.view, Scope.own)  # Kendi
_PRJ = (AccessLevel.view, Scope.project)  # Proje
_STK = (AccessLevel.view, Scope.stock)  # Stok
_DRF = (AccessLevel.draft, Scope.project)  # Taslak
_REQ = (AccessLevel.request, Scope.all)  # Talep
_APR = (AccessLevel.approve, Scope.all)  # Onay

# Sütun sırası — MATRIX'teki her satır bu sırayla okunur.
ROLE_ORDER = [
    "system_admin",
    "patron",
    "site_chief",
    "field_engineer",
    "hr_manager",
    "accounting",
    "project_manager",
    "procurement",
]

# Spec §5.2 matrisi.
MATRIX: dict[str, list[tuple[AccessLevel, Scope]]] = {
    #                    sysadmin patron  şef    saha   İK     muhasebe  PM     satınalma
    "dashboard": [_A, _F, _LIM, _LIM, _LIM, _FIN, _F, _N],
    "approvals": [_A, _F, _OWN, _OWN, _OWN, _FIN, _PRJ, _STK],
    # dashboard satirinin aynisi: proje kartlari ayni gorunurluk yuzeyi,
    # asil suzgec user_project_access (spec §4).
    "projects": [_A, _F, _LIM, _LIM, _LIM, _FIN, _F, _N],
    # spec §5.1 + kullanici karari 2026-07-28. Taban profil projects satiridir;
    # TEK FARK Satinalma: projects=_N iken sites=_LIM. "Projeyi goremeyen ama
    # santiyesini goren rol" tutarsiz gorunur ama BILINCLI istisnadir ve kullanici
    # tarafindan onaylanmistir — tutarlilik adina geri alinmamalidir.
    # Bolum AYRI izin modulu degildir: bolum santiyenin ic kirilimidir, sites
    # izni ikisini de kapsar (spec §4).
    "sites": [_A, _F, _LIM, _LIM, _LIM, _FIN, _F, _LIM],
    "site_diary": [_A, _F, _F, _F, _N, _N, _V, _N],
    "timesheet": [_A, _F, _F, _V, _F, _V, _N, _N],
    "personnel": [_A, _F, _V, _V, _F, _F, _V, _N],
    "payroll": [_A, _F, _N, _N, _F, _F, _N, _N],
    "inventory": [_A, _F, _V, _V, _N, _N, _V, _F],
    "procurement": [_A, _F, _REQ, _REQ, _N, _N, _APR, _F],
    "progress_payments": [_A, _F, _DRF, _DRF, _N, _APR, _APR, _N],
    "accounting": [_A, _F, _N, _N, _N, _F, _V, _N],
    "invoicing": [_A, _F, _N, _N, _N, _F, _V, _N],
    "treasury": [_A, _F, _N, _N, _N, _F, _V, _N],
    "settings": [_A, _N, _N, _N, _N, _N, _N, _N],
    "user_management": [_A, _N, _N, _N, _N, _N, _N, _N],
    # spec §4 kullanici karari: site_chief=_LIM (gorur), field_engineer=_N
    # (gormez) — "sites" satirinda ikisi birebir ayni oldugu icin bu ayrim
    # ancak ayri modulle mumkun. accounting/project_manager seviyeleri
    # "sites" satirindan turetildi. procurement=_N GECICIDIR: kullaniciya
    # soruldu, cevap gelmedi (spec §4) — teyit bekliyor.
    "boq": [_A, _F, _LIM, _N, _N, _FIN, _F, _N],
}


async def seed_reference_data(session: AsyncSession) -> None:
    """Rolleri, modülleri ve izin matrisini yükler.

    Idempotent: hangi başlangıç durumundan çalıştırılırsa çalıştırılsın (boş DB,
    tamamen seed edilmiş DB, ya da roller/modüller var ama role_permissions boş)
    sonuçta 8 rol, 16 modül ve 128 izin satırı bulunur; mevcut satırlar
    üzerine yazılmaz ve `uq_role_module` UNIQUE kısıtı asla ihlal edilmez.
    """
    existing_role_rows = (await session.execute(select(Role))).scalars().all()
    roles_by_key: dict[str, Role] = {role.key: role for role in existing_role_rows}
    for row in ROLES:
        if row["key"] in roles_by_key:
            continue
        role = Role(**row)
        session.add(role)
        roles_by_key[row["key"]] = role

    existing_module_rows = (await session.execute(select(Module))).scalars().all()
    modules_by_key: dict[str, Module] = {module.key: module for module in existing_module_rows}
    for row in MODULES:
        if row["key"] in modules_by_key:
            continue
        module = Module(**row)
        session.add(module)
        modules_by_key[row["key"]] = module

    await session.flush()

    existing_permission_pairs = set(
        (await session.execute(select(RolePermission.role_id, RolePermission.module_id))).all()
    )

    for module_key, cells in MATRIX.items():
        module = modules_by_key.get(module_key)
        if module is None:
            continue
        # strict=True kasıtlı: matris satırı 8 hücreden azsa sessizce eksik izin
        # üretmek yerine burada patlar. Sessiz eksik izin ERP'de en tehlikeli hatadır.
        for role_key, (level, scope) in zip(ROLE_ORDER, cells, strict=True):
            role = roles_by_key.get(role_key)
            if role is None:
                continue
            if (role.id, module.id) in existing_permission_pairs:
                continue
            session.add(
                RolePermission(
                    role_id=role.id, module_id=module.id, access_level=level, scope=scope
                )
            )
    await session.flush()
