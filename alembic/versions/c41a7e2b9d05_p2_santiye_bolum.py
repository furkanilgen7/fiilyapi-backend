"""p2 santiye bolum

site_status/section_status enum'lari + sites/sections tablolari + "sites" izin
modulu (8 rol izin satiri + sonraki moduller icin sort_order kaydirmasi).

Revision ID: c41a7e2b9d05
Revises: b7fcd67bde1e
Create Date: 2026-07-27 10:00:00.000000

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c41a7e2b9d05"
down_revision: str | Sequence[str] | None = "b7fcd67bde1e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

site_status_enum = sa.Enum("active", "on_hold", "completed", name="site_status")
section_status_enum = sa.Enum("planned", "active", "completed", name="section_status")

# Bu migration app.modules.roles.seed_data'yi kasitli olarak import ETMEZ:
# uygulanmis bir migration donmus olmalidir, uygulama kodu zamanla degisir.
# Asagidaki veriler seed_data.py'daki MODULES/MATRIX'ten birebir kopyalanmistir;
# esitligi tests/modules/test_seed_migration_matches_seed_data.py dogrular.

MODULE_KEY = "sites"
MODULE_NAME = "Şantiyeler"
MODULE_GROUP = "GENEL"
MODULE_SORT_ORDER = 4

# sites 4'e girdigi icin (spec §5.1: projects=3'un hemen ardi) sonrasindaki tum
# moduller birer kayar — 4 sirasi b7fcd67bde1e sonrasi site_diary'de dolu.
SORT_ORDER_UPDATES: dict[str, int] = {
    "site_diary": 5,
    "timesheet": 6,
    "personnel": 7,
    "payroll": 8,
    "inventory": 9,
    "procurement": 10,
    "progress_payments": 11,
    "accounting": 12,
    "invoicing": 13,
    "treasury": 14,
    "settings": 15,
    "user_management": 16,
}

# downgrade()'in geri yazacagi degerler (b7fcd67bde1e sonrasi bileske).
PREVIOUS_SORT_ORDERS: dict[str, int] = {
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

# spec §5.1 + kullanici karari 2026-07-28. Taban profil projects satiridir;
# TEK FARK Satinalma (son sutun): projects=none iken sites=view/limited.
# Bilincli istisna — kullanici onayli, tutarlilik adina geri alinmamalidir.
MATRIX: dict[str, list[tuple[str, str]]] = {
    MODULE_KEY: [
        ("admin", "all"),
        ("full", "all"),
        ("view", "limited"),
        ("view", "limited"),
        ("view", "limited"),
        ("view", "finance"),
        ("full", "all"),
        ("view", "limited"),
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
    # Azalan sort_order'dan basla: modules.sort_order uzerinde benzersizlik kisiti
    # olmasa da artan sirada kaydirmak gecici cakisma uretir; azalan sira guvenli.
    for key, sort_order in sorted(orders.items(), key=lambda item: -item[1]):
        op.execute(_UPDATE_SORT_ORDER.bindparams(key=key, sort_order=sort_order))


def _seed_sites_module() -> None:
    _apply_sort_orders(SORT_ORDER_UPDATES)
    op.execute(
        _INSERT_MODULE.bindparams(
            id=str(uuid.uuid4()),
            key=MODULE_KEY,
            name=MODULE_NAME,
            group=MODULE_GROUP,
            sort_order=MODULE_SORT_ORDER,
        )
    )
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


def _unseed_sites_module() -> None:
    op.execute(_DELETE_PERMISSIONS.bindparams(key=MODULE_KEY))
    op.execute(_DELETE_MODULE.bindparams(key=MODULE_KEY))
    _apply_sort_orders(PREVIOUS_SORT_ORDERS)


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    site_status_enum.create(bind, checkfirst=True)
    section_status_enum.create(bind, checkfirst=True)

    op.create_table(
        "sites",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="site_status", create_type=False),
            server_default="active",
            nullable=False,
        ),
        sa.Column("address", sa.String(length=300), nullable=True),
        sa.Column("city", sa.String(length=100), nullable=True),
        sa.Column("site_manager_name", sa.String(length=200), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("delivery_date", sa.Date(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "code", name="uq_sites_project_code"),
    )
    op.create_index("ix_sites_project_id", "sites", ["project_id"])

    op.create_table(
        "sections",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("site_id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=True),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="section_status", create_type=False),
            server_default="planned",
            nullable=False,
        ),
        sa.Column("manager_name", sa.String(length=200), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sections_site_id", "sections", ["site_id"])
    # Kismi benzersiz indeks: kodsuz bolumler coklanabilir (spec §2.2).
    op.create_index(
        "uq_sections_site_code",
        "sections",
        ["site_id", "code"],
        unique=True,
        postgresql_where=sa.text("code IS NOT NULL"),
    )

    _seed_sites_module()


def downgrade() -> None:
    """Downgrade schema."""
    _unseed_sites_module()

    op.drop_index("uq_sections_site_code", table_name="sections")
    op.drop_index("ix_sections_site_id", table_name="sections")
    op.drop_table("sections")
    op.drop_index("ix_sites_project_id", table_name="sites")
    op.drop_table("sites")

    section_status_enum.drop(op.get_bind(), checkfirst=True)
    site_status_enum.drop(op.get_bind(), checkfirst=True)
