"""p1 proje cekirdegi

Proje tipi enum'u + yeni sutunlar + 3 tip uzanti tablosu (project_investment,
project_land_share, land_share_shareholder) + "projects" izin modulu (8 rol
izin satiri + sonraki moduller icin sort_order kaydirmasi).

Revision ID: b7fcd67bde1e
Revises: 578d2211a14f
Create Date: 2026-07-26 11:29:57.311028

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7fcd67bde1e"
down_revision: str | Sequence[str] | None = "578d2211a14f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

project_type_enum = sa.Enum("taahhut", "kendi_yatirim", "kat_karsiligi", name="project_type")

# Bu migration app.modules.roles.seed_data'yi kasitli olarak import ETMEZ:
# uygulanmis bir migration donmus olmalidir, uygulama kodu zamanla degisir.
# Asagidaki veriler seed_data.py'daki MODULES/MATRIX'ten birebir kopyalanmistir;
# esitligi tests/modules/test_seed_migration_matches_seed_data.py dogrular.

MODULE_KEY = "projects"
MODULE_NAME = "Projeler"
MODULE_GROUP = "GENEL"
MODULE_SORT_ORDER = 3

# projects 3'e girdigi icin sonrasindaki tum moduller birer kayar.
SORT_ORDER_UPDATES: dict[str, int] = {
    "site_diary": 4,
    "timesheet": 5,
    "personnel": 6,
    "payroll": 7,
    "inventory": 8,
    "procurement": 9,
    "progress_payments": 10,
    "accounting": 11,
    "invoicing": 12,
    "treasury": 13,
    "settings": 14,
    "user_management": 15,
}

# downgrade()'in geri yazacagi degerler (578d2211a14f sonrasi bileske).
PREVIOUS_SORT_ORDERS: dict[str, int] = {
    "site_diary": 3,
    "timesheet": 4,
    "personnel": 5,
    "payroll": 6,
    "inventory": 7,
    "procurement": 8,
    "progress_payments": 9,
    "accounting": 10,
    "invoicing": 11,
    "treasury": 12,
    "settings": 13,
    "user_management": 14,
}

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

# dashboard satirinin aynisi (seed_data.MATRIX["projects"] ile birebir;
# esitligi tests/modules/test_seed_migration_matches_seed_data.py dogrular).
MATRIX: dict[str, list[tuple[str, str]]] = {
    MODULE_KEY: [
        ("admin", "all"),
        ("full", "all"),
        ("view", "limited"),
        ("view", "limited"),
        ("view", "limited"),
        ("view", "finance"),
        ("full", "all"),
        ("none", "all"),
    ],
}

_INSERT_MODULE = sa.text(
    'INSERT INTO modules (id, key, name, "group", sort_order) '
    "VALUES (CAST(:id AS uuid), :key, :name, CAST(:group AS module_group), :sort_order) "
    "ON CONFLICT (key) DO NOTHING"
)

_INSERT_PERMISSION = sa.text(
    "INSERT INTO role_permissions (id, role_id, module_id, access_level, scope) "
    "SELECT CAST(:id AS uuid), r.id, m.id, "
    "CAST(:access_level AS access_level), CAST(:scope AS scope) "
    "FROM roles r, modules m "
    "WHERE r.key = :role_key AND m.key = :module_key "
    "ON CONFLICT ON CONSTRAINT uq_role_module DO NOTHING"
)

_UPDATE_SORT_ORDER = sa.text("UPDATE modules SET sort_order = :sort_order WHERE key = :key")

_DELETE_PERMISSIONS = sa.text(
    "DELETE FROM role_permissions WHERE module_id IN (SELECT id FROM modules WHERE key = :key)"
)

_DELETE_MODULE = sa.text("DELETE FROM modules WHERE key = :key")


def _apply_sort_orders(orders: dict[str, int]) -> None:
    for key, sort_order in orders.items():
        op.execute(_UPDATE_SORT_ORDER.bindparams(key=key, sort_order=sort_order))


def _seed_projects_module() -> None:
    op.execute(
        _INSERT_MODULE.bindparams(
            id=str(uuid.uuid4()),
            key=MODULE_KEY,
            name=MODULE_NAME,
            group=MODULE_GROUP,
            sort_order=MODULE_SORT_ORDER,
        )
    )
    _apply_sort_orders(SORT_ORDER_UPDATES)
    for role_key, (access_level, scope) in zip(ROLE_ORDER, MATRIX[MODULE_KEY], strict=True):
        op.execute(
            _INSERT_PERMISSION.bindparams(
                id=str(uuid.uuid4()),
                role_key=role_key,
                module_key=MODULE_KEY,
                access_level=access_level,
                scope=scope,
            )
        )


def _unseed_projects_module() -> None:
    op.execute(_DELETE_PERMISSIONS.bindparams(key=MODULE_KEY))
    op.execute(_DELETE_MODULE.bindparams(key=MODULE_KEY))
    _apply_sort_orders(PREVIOUS_SORT_ORDERS)


def upgrade() -> None:
    """Upgrade schema."""
    project_type_enum.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "projects",
        sa.Column("project_type", project_type_enum, server_default="taahhut", nullable=False),
    )
    op.add_column("projects", sa.Column("category", sa.String(length=100), nullable=True))
    op.add_column("projects", sa.Column("city", sa.String(length=100), nullable=True))
    op.add_column("projects", sa.Column("start_date", sa.Date(), nullable=True))
    op.add_column("projects", sa.Column("end_date", sa.Date(), nullable=True))
    op.add_column("projects", sa.Column("contract_no", sa.String(length=100), nullable=True))
    op.add_column(
        "projects", sa.Column("contract_amount", sa.Numeric(precision=18, scale=2), nullable=True)
    )
    op.add_column("projects", sa.Column("employer_name", sa.String(length=200), nullable=True))

    op.create_table(
        "project_investment",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("sales_target", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("land_cost", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("project_id"),
    )
    op.create_table(
        "project_land_share",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("landowner_name", sa.String(length=200), nullable=False),
        sa.Column("our_share_pct", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("owner_share_pct", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("contract_no", sa.String(length=100), nullable=True),
        sa.Column("notary_date", sa.Date(), nullable=True),
        sa.Column("land_area_m2", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("construction_area_m2", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("delivery_date", sa.Date(), nullable=True),
        sa.Column("daily_penalty", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("guarantee_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.CheckConstraint("our_share_pct + owner_share_pct = 100", name="ck_land_share_pct_total"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("project_id"),
    )
    op.create_table(
        "land_share_shareholder",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("share_pct", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_land_share_shareholder_project_id", "land_share_shareholder", ["project_id"]
    )

    _seed_projects_module()


def downgrade() -> None:
    """Downgrade schema."""
    _unseed_projects_module()

    op.drop_index("ix_land_share_shareholder_project_id", table_name="land_share_shareholder")
    op.drop_table("land_share_shareholder")
    op.drop_table("project_land_share")
    op.drop_table("project_investment")
    op.drop_column("projects", "employer_name")
    op.drop_column("projects", "contract_amount")
    op.drop_column("projects", "contract_no")
    op.drop_column("projects", "end_date")
    op.drop_column("projects", "start_date")
    op.drop_column("projects", "city")
    op.drop_column("projects", "category")
    op.drop_column("projects", "project_type")
    project_type_enum.drop(op.get_bind(), checkfirst=True)
