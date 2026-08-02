"""p8 unite satisi

customers + unit_sales + sale_installments tablolari, alti yeni enum
(customer_type / sale_type / unit_sale_status / deed_condition /
payment_plan_type / installment_payment_method) ve 19. izin modulu
("sales" satiri + 8 role_permissions, P8 spec §2/§8 S1 / Task T1).

Elle yazilmistir (autogenerate DEGIL) — repo deseni.

Revision ID: f2a3b4c5d6e7
Revises: c3d4e5f6a7b8
Create Date: 2026-08-02

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f2a3b4c5d6e7"
down_revision: str | Sequence[str] | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

customer_type_enum = sa.Enum("person", "company", name="customer_type")
sale_type_enum = sa.Enum("sale", "reservation", "pre_contract", name="sale_type")
# DIKKAT: `unit_sales_status` (unitenin vitrin durumu, c2d3e4f5a6b7) ile AYRI bir
# tiptir — buradaki `unit_sale_status` satis KAYDININ durumudur.
unit_sale_status_enum = sa.Enum(
    "reservation", "active", "deed_transferred", "cancelled", name="unit_sale_status"
)
deed_condition_enum = sa.Enum(
    "full_payment", "after_down_payment", "at_contract", name="deed_condition"
)
payment_plan_type_enum = sa.Enum(
    "cash", "down_payment_installments", "bank_loan", "barter", name="payment_plan_type"
)
installment_payment_method_enum = sa.Enum(
    "transfer", "cash", "cheque", "auto_payment", name="installment_payment_method"
)

# Bu migration app.modules.roles.seed_data'yi kasitli olarak import ETMEZ:
# uygulanmis bir migration donmus olmalidir, uygulama kodu zamanla degisir.
# Asagidaki veriler seed_data.py'daki MODULES/MATRIX'ten birebir kopyalanmistir;
# esitligi tests/modules/test_seed_migration_matches_seed_data.py dogrular.

MODULE_KEY = "sales"
MODULE_NAME = "Satış Yönetimi"
MODULE_GROUP = "MALI"
MODULE_SORT_ORDER = 19

# sales son siraya eklendigi icin baska hicbir modul kaymaz (boq/contracts gibi).
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

# spec §8 S1: `contracts` satiriyla birebir ayni — site_chief/field_engineer/
# hr_manager/procurement=none (satis bedeli ve alici kimligi saha rollerine
# kapali), accounting=view/finance (tahsilati izler, satis acmaz),
# project_manager=full (ayri satis muduru rolu yok).
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
    customer_type_enum.create(bind, checkfirst=True)
    sale_type_enum.create(bind, checkfirst=True)
    unit_sale_status_enum.create(bind, checkfirst=True)
    deed_condition_enum.create(bind, checkfirst=True)
    payment_plan_type_enum.create(bind, checkfirst=True)
    installment_payment_method_enum.create(bind, checkfirst=True)

    # 2. customers
    op.create_table(
        "customers",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "customer_type",
            postgresql.ENUM(name="customer_type", create_type=False),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("national_id", sa.String(length=11), nullable=True),
        sa.Column("tax_number", sa.String(length=11), nullable=True),
        sa.Column("phone", sa.String(length=20), nullable=True),
        sa.Column("email", sa.String(length=254), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
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
    # Kismi benzersiz indeksler: NULL'lar coklanabilir, dolu degerler benzersiz.
    op.create_index(
        "uq_customers_national_id",
        "customers",
        ["national_id"],
        unique=True,
        postgresql_where=sa.text("national_id IS NOT NULL"),
    )
    op.create_index(
        "uq_customers_tax_number",
        "customers",
        ["tax_number"],
        unique=True,
        postgresql_where=sa.text("tax_number IS NOT NULL"),
    )
    op.create_index("ix_customers_name", "customers", ["name"])

    # 3. unit_sales
    op.create_table(
        "unit_sales",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("unit_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("customer_id", sa.UUID(), nullable=False),
        sa.Column(
            "sale_type", postgresql.ENUM(name="sale_type", create_type=False), nullable=False
        ),
        sa.Column(
            "status", postgresql.ENUM(name="unit_sale_status", create_type=False), nullable=False
        ),
        sa.Column("list_price_snapshot", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("discount_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("sale_price", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("vat_pct", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("advisor_user_id", sa.UUID(), nullable=True),
        sa.Column("advisor_name", sa.String(length=200), nullable=True),
        sa.Column("reservation_deposit", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("reservation_due_date", sa.Date(), nullable=True),
        sa.Column(
            "deed_condition",
            postgresql.ENUM(name="deed_condition", create_type=False),
            nullable=True,
        ),
        sa.Column("planned_deed_date", sa.Date(), nullable=True),
        sa.Column("delivery_date", sa.Date(), nullable=True),
        sa.Column(
            "has_condominium_easement",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("has_mortgage", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("late_fee_monthly_pct", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column(
            "payment_plan_type",
            postgresql.ENUM(name="payment_plan_type", create_type=False),
            nullable=True,
        ),
        sa.Column("down_payment", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("installment_count", sa.Integer(), nullable=True),
        sa.Column("first_installment_date", sa.Date(), nullable=True),
        sa.Column("term_interest_pct", sa.Numeric(precision=5, scale=2), nullable=True),
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
        sa.ForeignKeyConstraint(["unit_id"], ["units.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["advisor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("sale_price >= 0", name="ck_unit_sales_sale_price"),
        sa.CheckConstraint(
            "list_price_snapshot IS NULL OR list_price_snapshot >= 0",
            name="ck_unit_sales_list_price_snapshot",
        ),
        sa.CheckConstraint(
            "discount_amount IS NULL OR discount_amount >= 0",
            name="ck_unit_sales_discount_amount",
        ),
        sa.CheckConstraint(
            "vat_pct IS NULL OR (vat_pct >= 0 AND vat_pct <= 100)", name="ck_unit_sales_vat_pct"
        ),
        sa.CheckConstraint(
            "reservation_deposit IS NULL OR reservation_deposit >= 0",
            name="ck_unit_sales_reservation_deposit",
        ),
        sa.CheckConstraint(
            "down_payment IS NULL OR down_payment >= 0", name="ck_unit_sales_down_payment"
        ),
        sa.CheckConstraint(
            "installment_count IS NULL OR installment_count >= 0",
            name="ck_unit_sales_installment_count",
        ),
        sa.CheckConstraint(
            "term_interest_pct IS NULL OR term_interest_pct >= 0",
            name="ck_unit_sales_term_interest_pct",
        ),
        sa.CheckConstraint(
            "late_fee_monthly_pct IS NULL OR late_fee_monthly_pct >= 0",
            name="ck_unit_sales_late_fee_monthly_pct",
        ),
    )
    op.create_index("ix_unit_sales_unit_id", "unit_sales", ["unit_id"])
    op.create_index("ix_unit_sales_project_id", "unit_sales", ["project_id"])
    op.create_index("ix_unit_sales_customer_id", "unit_sales", ["customer_id"])
    op.create_index("ix_unit_sales_status", "unit_sales", ["status"])
    # Unite basina en cok BIR acik kayit; iptal edilenler kisiti serbest birakir.
    op.create_index(
        "uq_unit_sales_open_unit",
        "unit_sales",
        ["unit_id"],
        unique=True,
        postgresql_where=sa.text("status <> 'cancelled'"),
    )

    # 4. sale_installments
    op.create_table(
        "sale_installments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("sale_id", sa.UUID(), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=50), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column(
            "payment_method",
            postgresql.ENUM(name="installment_payment_method", create_type=False),
            nullable=True,
        ),
        sa.Column(
            "paid_amount",
            sa.Numeric(precision=18, scale=2),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["sale_id"], ["unit_sales.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sale_id", "sequence_no", name="uq_sale_installments_sale_sequence"),
        sa.CheckConstraint("sequence_no >= 0", name="ck_sale_installments_sequence_no"),
        sa.CheckConstraint("amount >= 0", name="ck_sale_installments_amount"),
        sa.CheckConstraint("paid_amount >= 0", name="ck_sale_installments_paid_amount"),
    )
    op.create_index("ix_sale_installments_sale_id", "sale_installments", ["sale_id"])

    # 5. Izin modulu: sales satiri (19.) + 8 role_permissions (spec §8 S1)
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

    op.drop_index("ix_sale_installments_sale_id", table_name="sale_installments")
    op.drop_table("sale_installments")

    op.drop_index("uq_unit_sales_open_unit", table_name="unit_sales")
    op.drop_index("ix_unit_sales_status", table_name="unit_sales")
    op.drop_index("ix_unit_sales_customer_id", table_name="unit_sales")
    op.drop_index("ix_unit_sales_project_id", table_name="unit_sales")
    op.drop_index("ix_unit_sales_unit_id", table_name="unit_sales")
    op.drop_table("unit_sales")

    op.drop_index("ix_customers_name", table_name="customers")
    op.drop_index("uq_customers_tax_number", table_name="customers")
    op.drop_index("uq_customers_national_id", table_name="customers")
    op.drop_table("customers")

    bind = op.get_bind()
    installment_payment_method_enum.drop(bind, checkfirst=True)
    payment_plan_type_enum.drop(bind, checkfirst=True)
    deed_condition_enum.drop(bind, checkfirst=True)
    unit_sale_status_enum.drop(bind, checkfirst=True)
    sale_type_enum.drop(bind, checkfirst=True)
    customer_type_enum.drop(bind, checkfirst=True)
