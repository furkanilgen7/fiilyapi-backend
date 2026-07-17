"""seed roller modul ve izinler

Revision ID: a477fdf00fdf
Revises: 9b06c643996e
Create Date: 2026-07-17 15:32:26.984536

"""
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a477fdf00fdf'
down_revision: str | Sequence[str] | None = '9b06c643996e'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Bu migration app.modules.roles.seed_data'yi kasitli olarak import ETMEZ:
# uygulanmis bir migration donmus olmalidir, uygulama kodu zamanla degisir.
# Asagidaki veriler seed_data.py'daki ROLES/MODULES/MATRIX'ten satir satir
# birebir kopyalanmistir (spec SS5.1 / SS5.2).

roles_table = sa.table(
    "roles",
    sa.column("id", postgresql.UUID(as_uuid=True)),
    sa.column("key", sa.String),
    sa.column("name", sa.String),
    sa.column("emoji", sa.String),
    sa.column("description", sa.Text),
    sa.column("is_system", sa.Boolean),
)

modules_table = sa.table(
    "modules",
    sa.column("id", postgresql.UUID(as_uuid=True)),
    sa.column("key", sa.String),
    sa.column("name", sa.String),
    sa.column(
        "group",
        sa.Enum("GENEL", "SAHA", "STOK_SATINALMA", "MALI", "SISTEM", name="module_group"),
    ),
    sa.column("sort_order", sa.Integer),
)

role_permissions_table = sa.table(
    "role_permissions",
    sa.column("id", postgresql.UUID(as_uuid=True)),
    sa.column("role_id", postgresql.UUID(as_uuid=True)),
    sa.column("module_id", postgresql.UUID(as_uuid=True)),
    sa.column(
        "access_level",
        sa.Enum(
            "none", "view", "draft", "request", "approve", "full", "admin", name="access_level"
        ),
    ),
    sa.column(
        "scope",
        sa.Enum("all", "own", "project", "finance", "stock", "limited", name="scope"),
    ),
)

ROLE_IDS = {
    key: uuid.uuid4()
    for key in (
        "system_admin",
        "patron",
        "site_chief",
        "field_engineer",
        "hr_manager",
        "accounting",
        "project_manager",
        "procurement",
    )
}
MODULE_IDS = {
    key: uuid.uuid4()
    for key in (
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
    )
}

# Sütun sırası — asağıdaki her MATRIX satırı bu sırayla okunur (seed_data.ROLE_ORDER).
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

# Spec §5.2 matrisi — seed_data.MATRIX ile birebir aynı (access_level, scope).
# Sütun sırası: sysadmin, patron, şef, saha, İK, muhasebe, PM, satınalma (ROLE_ORDER).
MATRIX: dict[str, list[tuple[str, str]]] = {
    "dashboard": [
        ("admin", "all"), ("full", "all"), ("view", "limited"), ("view", "limited"),
        ("view", "limited"), ("view", "finance"), ("full", "all"), ("none", "all"),
    ],
    "approvals": [
        ("admin", "all"), ("full", "all"), ("view", "own"), ("view", "own"),
        ("view", "own"), ("view", "finance"), ("view", "project"), ("view", "stock"),
    ],
    "site_diary": [
        ("admin", "all"), ("full", "all"), ("full", "all"), ("full", "all"),
        ("none", "all"), ("none", "all"), ("view", "all"), ("none", "all"),
    ],
    "timesheet": [
        ("admin", "all"), ("full", "all"), ("full", "all"), ("view", "all"),
        ("full", "all"), ("view", "all"), ("none", "all"), ("none", "all"),
    ],
    "personnel": [
        ("admin", "all"), ("full", "all"), ("view", "all"), ("view", "all"),
        ("full", "all"), ("full", "all"), ("view", "all"), ("none", "all"),
    ],
    "payroll": [
        ("admin", "all"), ("full", "all"), ("none", "all"), ("none", "all"),
        ("full", "all"), ("full", "all"), ("none", "all"), ("none", "all"),
    ],
    "inventory": [
        ("admin", "all"), ("full", "all"), ("view", "all"), ("view", "all"),
        ("none", "all"), ("none", "all"), ("view", "all"), ("full", "all"),
    ],
    "procurement": [
        ("admin", "all"), ("full", "all"), ("request", "all"), ("request", "all"),
        ("none", "all"), ("none", "all"), ("approve", "all"), ("full", "all"),
    ],
    "progress_payments": [
        ("admin", "all"), ("full", "all"), ("draft", "project"), ("draft", "project"),
        ("none", "all"), ("approve", "all"), ("approve", "all"), ("none", "all"),
    ],
    "accounting": [
        ("admin", "all"), ("full", "all"), ("none", "all"), ("none", "all"),
        ("none", "all"), ("full", "all"), ("view", "all"), ("none", "all"),
    ],
    "treasury": [
        ("admin", "all"), ("full", "all"), ("none", "all"), ("none", "all"),
        ("none", "all"), ("full", "all"), ("view", "all"), ("none", "all"),
    ],
    "settings": [
        ("admin", "all"), ("none", "all"), ("none", "all"), ("none", "all"),
        ("none", "all"), ("none", "all"), ("none", "all"), ("none", "all"),
    ],
    "user_management": [
        ("admin", "all"), ("none", "all"), ("none", "all"), ("none", "all"),
        ("none", "all"), ("none", "all"), ("none", "all"), ("none", "all"),
    ],
}


def upgrade() -> None:
    """Upgrade schema."""
    op.bulk_insert(
        roles_table,
        [
            {
                "id": ROLE_IDS["system_admin"],
                "key": "system_admin",
                "name": "Sistem Yöneticisi",
                "emoji": "🛡️",
                "description": (
                    "Tüm modüller · Tüm projeler · Ayarlar · Kullanıcı yönetimi · Silme yetkisi"
                ),
                "is_system": True,
            },
            {
                "id": ROLE_IDS["patron"],
                "key": "patron",
                "name": "Patron",
                "emoji": "👔",
                "description": "Tüm modüller · Tüm projeler (ayarlar hariç)",
                "is_system": True,
            },
            {
                "id": ROLE_IDS["site_chief"],
                "key": "site_chief",
                "name": "Şantiye Şefi",
                "emoji": "👷",
                "description": "Günlük kayıt, puantaj, stok görüntüle",
                "is_system": False,
            },
            {
                "id": ROLE_IDS["field_engineer"],
                "key": "field_engineer",
                "name": "Saha Mühendisi",
                "emoji": "📐",
                "description": "Günlük kayıt, hakediş taslağı, puantaj görüntüle",
                "is_system": False,
            },
            {
                "id": ROLE_IDS["hr_manager"],
                "key": "hr_manager",
                "name": "İK Müdürü",
                "emoji": "👥",
                "description": "Personel, puantaj, bordro",
                "is_system": False,
            },
            {
                "id": ROLE_IDS["accounting"],
                "key": "accounting",
                "name": "Muhasebe",
                "emoji": "📒",
                "description": "Yevmiye, bordro, hakediş onay, e-fatura",
                "is_system": False,
            },
            {
                "id": ROLE_IDS["project_manager"],
                "key": "project_manager",
                "name": "Proje Müdürü",
                "emoji": "🏗",
                "description": "Proje görünümü, raporlar, hakediş onay",
                "is_system": False,
            },
            {
                "id": ROLE_IDS["procurement"],
                "key": "procurement",
                "name": "Satınalma",
                "emoji": "🛒",
                "description": "Stok, satınalma, teklif, tedarikçi",
                "is_system": False,
            },
        ],
    )

    op.bulk_insert(
        modules_table,
        [
            {"id": MODULE_IDS["dashboard"], "key": "dashboard", "name": "Gösterge Paneli",
             "group": "GENEL", "sort_order": 1},
            {"id": MODULE_IDS["approvals"], "key": "approvals", "name": "Onay Kutusu",
             "group": "GENEL", "sort_order": 2},
            {"id": MODULE_IDS["site_diary"], "key": "site_diary", "name": "Günlük Kayıt",
             "group": "SAHA", "sort_order": 3},
            {"id": MODULE_IDS["timesheet"], "key": "timesheet", "name": "Puantaj",
             "group": "SAHA", "sort_order": 4},
            {"id": MODULE_IDS["personnel"], "key": "personnel", "name": "Personel",
             "group": "SAHA", "sort_order": 5},
            {"id": MODULE_IDS["payroll"], "key": "payroll", "name": "Bordro",
             "group": "SAHA", "sort_order": 6},
            {"id": MODULE_IDS["inventory"], "key": "inventory", "name": "Stok & Depo",
             "group": "STOK_SATINALMA", "sort_order": 7},
            {"id": MODULE_IDS["procurement"], "key": "procurement", "name": "Satınalma & Teklif",
             "group": "STOK_SATINALMA", "sort_order": 8},
            {"id": MODULE_IDS["progress_payments"], "key": "progress_payments",
             "name": "Hakedişler", "group": "MALI", "sort_order": 9},
            {"id": MODULE_IDS["accounting"], "key": "accounting", "name": "Muhasebe",
             "group": "MALI", "sort_order": 10},
            {"id": MODULE_IDS["treasury"], "key": "treasury", "name": "Hazine",
             "group": "MALI", "sort_order": 11},
            {"id": MODULE_IDS["settings"], "key": "settings", "name": "Ayarlar",
             "group": "SISTEM", "sort_order": 12},
            {"id": MODULE_IDS["user_management"], "key": "user_management",
             "name": "Kullanıcı & Rol Yönetimi", "group": "SISTEM", "sort_order": 13},
        ],
    )

    permission_rows = []
    for module_key, cells in MATRIX.items():
        for role_key, (access_level, scope) in zip(ROLE_ORDER, cells, strict=True):
            permission_rows.append(
                {
                    "id": uuid.uuid4(),
                    "role_id": ROLE_IDS[role_key],
                    "module_id": MODULE_IDS[module_key],
                    "access_level": access_level,
                    "scope": scope,
                }
            )
    op.bulk_insert(role_permissions_table, permission_rows)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM role_permissions")
    op.execute("DELETE FROM modules")
    op.execute("DELETE FROM roles")
