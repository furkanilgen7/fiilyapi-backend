"""p5 sozlesmeler

contract_status/payment_period enum'lari + project_contracts.status +
subcontractors + employer_contract_groups/items + boq_items.contract_item_id
(kismi benzersiz indeks) + subcontractor_contracts/items + izin modulu
(contracts satiri + 8 role_permissions, Task C2 / spec §5).

Revision ID: e9e8e6a52f96
Revises: a7c9e1f3b5d2
Create Date: 2026-07-30 22:22:09.316347

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e9e8e6a52f96"
down_revision: str | Sequence[str] | None = "a7c9e1f3b5d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

contract_status_enum = sa.Enum("active", "completed", "on_hold", name="contract_status")
payment_period_enum = sa.Enum("monthly", "biweekly", "on_completion", name="payment_period")

# Bu migration app.modules.roles.seed_data'yi kasitli olarak import ETMEZ:
# uygulanmis bir migration donmus olmalidir, uygulama kodu zamanla degisir.
# Asagidaki veriler seed_data.py'daki MODULES/MATRIX'ten birebir kopyalanmistir;
# esitligi tests/modules/test_seed_migration_matches_seed_data.py dogrular.

MODULE_KEY = "contracts"
MODULE_NAME = "Sözleşmeler"
MODULE_GROUP = "MALI"
MODULE_SORT_ORDER = 18

# contracts son siraya eklendigi icin baska hicbir modul kaymaz (boq'daki gibi).
SORT_ORDER_UPDATES: dict[str, int] = {}

# downgrade()'in geri yazacagi degerler — kaydirma olmadigi icin bos.
PREVIOUS_SORT_ORDERS: dict[str, int] = {}

# Sutun sirasi — asagidaki MATRIX satiri bu sirayla okunur (seed_data.ROLE_ORDER).
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

# spec §5: system_admin=admin, patron=full, site_chief/field_engineer/hr_manager/
# procurement=none (projects=_LIM olan roller taseron birim fiyatlarini gormemeli),
# accounting=view/finance, project_manager=full.
MATRIX: dict[str, list[tuple[str, str]]] = {
    MODULE_KEY: [
        ("admin", "all"),
        ("full", "all"),
        ("none", "all"),
        ("none", "all"),
        ("none", "all"),
        ("view", "finance"),
        ("full", "all"),
        ("none", "all"),
    ],
}

# Canli DB'de satirlar kismen mevcut olabilir (elle mudahale, yarim kalmis kosu):
# her yazma idempotent, boylece yeniden calistirma UNIQUE kisitini ihlal etmez.
_INSERT_MODULE = sa.text(
    'INSERT INTO modules (id, key, name, "group", sort_order) '
    "VALUES (CAST(:id AS uuid), :key, :name, CAST(:group AS module_group), :sort_order) "
    "ON CONFLICT (key) DO NOTHING"
)

# role_id/module_id canli ortamda calisma aninda okunur: ilk seed migration'i
# UUID'leri uuid4() ile uretti, dolayisiyla sabit kodlanamazlar.
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


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()

    # 1. Enum'lar
    contract_status_enum.create(bind, checkfirst=True)
    payment_period_enum.create(bind, checkfirst=True)

    # 2. project_contracts.status
    op.add_column(
        "project_contracts",
        sa.Column(
            "status",
            postgresql.ENUM(name="contract_status", create_type=False),
            server_default="active",
            nullable=False,
        ),
    )

    # 3. subcontractors
    op.create_table(
        "subcontractors",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("tax_number", sa.String(length=11), nullable=True),
        sa.Column("contact_person", sa.String(length=200), nullable=True),
        sa.Column("phone", sa.String(length=30), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_subcontractors_tax_number",
        "subcontractors",
        ["tax_number"],
        unique=True,
        postgresql_where=sa.text("tax_number IS NOT NULL"),
    )
    op.create_index("ix_subcontractors_name", "subcontractors", ["name"])

    # 4. employer_contract_groups / employer_contract_items
    op.create_table(
        "employer_contract_groups",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["project_id"], ["project_contracts.project_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_employer_contract_groups_project_id", "employer_contract_groups", ["project_id"]
    )

    op.create_table(
        "employer_contract_items",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("group_id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("unit", sa.String(length=50), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=18, scale=2), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["project_id"], ["project_contracts.project_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["group_id"], ["employer_contract_groups.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "code", name="uq_employer_contract_items_project_code"),
        sa.CheckConstraint("quantity > 0", name="ck_employer_contract_items_quantity_positive"),
        sa.CheckConstraint("unit_price >= 0", name="ck_employer_contract_items_unit_price_nonneg"),
    )
    op.create_index(
        "ix_employer_contract_items_project_id", "employer_contract_items", ["project_id"]
    )
    op.create_index("ix_employer_contract_items_group_id", "employer_contract_items", ["group_id"])

    # 5. boq_items.contract_item_id + kismi benzersiz indeks
    op.add_column(
        "boq_items",
        sa.Column("contract_item_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_boq_items_contract_item_id",
        "boq_items",
        "employer_contract_items",
        ["contract_item_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_boq_items_contract_item_id", "boq_items", ["contract_item_id"])
    op.create_index(
        "uq_boq_items_contract_item_site",
        "boq_items",
        ["contract_item_id", "site_id"],
        unique=True,
        postgresql_where=sa.text("contract_item_id IS NOT NULL"),
    )

    # 6. subcontractor_contracts / subcontractor_contract_items
    op.create_table(
        "subcontractor_contracts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("site_id", sa.UUID(), nullable=True),
        sa.Column("subcontractor_id", sa.UUID(), nullable=True),
        sa.Column("subcontractor_name", sa.String(length=200), nullable=True),
        sa.Column("work_category", sa.String(length=100), nullable=True),
        sa.Column("contract_no", sa.String(length=100), nullable=True),
        sa.Column("signature_date", sa.Date(), nullable=True),
        sa.Column("is_notarized", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("late_penalty_daily", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column(
            "advance_pct",
            sa.Numeric(precision=5, scale=2),
            server_default=sa.text("10"),
            nullable=False,
        ),
        sa.Column(
            "retainage_pct",
            sa.Numeric(precision=5, scale=2),
            server_default=sa.text("5"),
            nullable=False,
        ),
        sa.Column(
            "payment_period",
            postgresql.ENUM(name="payment_period", create_type=False),
            server_default="monthly",
            nullable=False,
        ),
        sa.Column("payment_term_days", sa.Integer(), server_default="30", nullable=False),
        sa.Column(
            "materials_by_contractor",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "subcontractor_files_own_sgk",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("vat_withholding", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="contract_status", create_type=False),
            server_default="active",
            nullable=False,
        ),
        sa.Column("is_draft", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
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
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["subcontractor_id"], ["subcontractors.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "advance_pct BETWEEN 0 AND 100 AND retainage_pct BETWEEN 0 AND 100",
            name="ck_subcontract_pct_range",
        ),
        sa.CheckConstraint("payment_term_days >= 0", name="ck_subcontract_payment_term"),
    )
    op.create_index(
        "ix_subcontractor_contracts_project_id", "subcontractor_contracts", ["project_id"]
    )
    op.create_index("ix_subcontractor_contracts_site_id", "subcontractor_contracts", ["site_id"])
    op.create_index(
        "uq_subcontractor_contracts_contract_no",
        "subcontractor_contracts",
        ["contract_no"],
        unique=True,
        postgresql_where=sa.text("contract_no IS NOT NULL"),
    )

    op.create_table(
        "subcontractor_contract_items",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("contract_id", sa.UUID(), nullable=False),
        sa.Column("source_contract_item_id", sa.UUID(), nullable=True),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("unit", sa.String(length=50), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=18, scale=2), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["contract_id"], ["subcontractor_contracts.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_contract_item_id"],
            ["employer_contract_items.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "contract_id", "code", name="uq_subcontractor_contract_items_contract_code"
        ),
        sa.CheckConstraint(
            "quantity > 0", name="ck_subcontractor_contract_items_quantity_positive"
        ),
        sa.CheckConstraint(
            "unit_price IS NULL OR unit_price >= 0",
            name="ck_subcontractor_contract_items_unit_price_nonneg",
        ),
    )
    op.create_index(
        "ix_subcontractor_contract_items_contract_id",
        "subcontractor_contract_items",
        ["contract_id"],
    )
    op.create_index(
        "ix_subcontractor_contract_items_source_contract_item_id",
        "subcontractor_contract_items",
        ["source_contract_item_id"],
    )

    # 7. Izin modulu: contracts satiri (18.) + 8 role_permissions (spec §5, Task C2)
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


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(_DELETE_PERMISSIONS.bindparams(key=MODULE_KEY))
    op.execute(_DELETE_MODULE.bindparams(key=MODULE_KEY))
    _apply_sort_orders(PREVIOUS_SORT_ORDERS)

    op.drop_index(
        "ix_subcontractor_contract_items_source_contract_item_id",
        table_name="subcontractor_contract_items",
    )
    op.drop_index(
        "ix_subcontractor_contract_items_contract_id",
        table_name="subcontractor_contract_items",
    )
    op.drop_table("subcontractor_contract_items")

    op.drop_index("uq_subcontractor_contracts_contract_no", table_name="subcontractor_contracts")
    op.drop_index("ix_subcontractor_contracts_site_id", table_name="subcontractor_contracts")
    op.drop_index("ix_subcontractor_contracts_project_id", table_name="subcontractor_contracts")
    op.drop_table("subcontractor_contracts")

    op.drop_index("uq_boq_items_contract_item_site", table_name="boq_items")
    op.drop_index("ix_boq_items_contract_item_id", table_name="boq_items")
    op.drop_constraint("fk_boq_items_contract_item_id", "boq_items", type_="foreignkey")
    op.drop_column("boq_items", "contract_item_id")

    op.drop_index("ix_employer_contract_items_group_id", table_name="employer_contract_items")
    op.drop_index("ix_employer_contract_items_project_id", table_name="employer_contract_items")
    op.drop_table("employer_contract_items")

    op.drop_index("ix_employer_contract_groups_project_id", table_name="employer_contract_groups")
    op.drop_table("employer_contract_groups")

    op.drop_index("ix_subcontractors_name", table_name="subcontractors")
    op.drop_index("uq_subcontractors_tax_number", table_name="subcontractors")
    op.drop_table("subcontractors")

    op.drop_column("project_contracts", "status")

    bind = op.get_bind()
    payment_period_enum.drop(bind, checkfirst=True)
    contract_status_enum.drop(bind, checkfirst=True)
