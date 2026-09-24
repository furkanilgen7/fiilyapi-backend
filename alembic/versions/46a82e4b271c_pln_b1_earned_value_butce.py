"""PLN-B1 — planlama (earned value) butce: 14 uzanti tablosu + `earned_value` izin modulu

PLANLAMA-SPEC §2.5, §2.7, §3.8 (K1–K4, K7–K10, K17, K25), §3.9 (B1-1…B1-10).
Cekirdek tablolara KOLON EKLENMEZ (§2.7); tablolar ve gerekceleri
`app/modules/earned_value/models.py` docstring'indedir.

Tablo DDL'i `alembic revision --autogenerate` ile uretildi ve elle duzeltildi:
(1) ayni enum tipi birden cok tabloda gectigi icin tipler basta BIR KEZ yaratilir,
kolonlar `create_type=False` ile baglanir (aksi hâlde ikinci `create_table`
"type already exists" ile duser); (2) autogenerate'in yakaladigi ILGISIZ bir surukleme
(`financial_instruments.created_at/updated_at` NOT NULL) bu migration'a ALINMADI —
bu dilimin konusu degil, raporda ayrica bildirildi.

Izin modulu kismi `b8a66b6fd431_boq_izin_modulu.py` deseninin birebiridir; seed_data'yi
import ETMEZ. Esitligi `tests/modules/test_seed_migration_matches_seed_data.py` cviler.

Revision ID: 46a82e4b271c
Revises: ca36b2e59ee3
Create Date: 2026-09-25

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "46a82e4b271c"
down_revision: str | Sequence[str] | None = "ca36b2e59ee3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_ENUMS = (
    sa.Enum("own", "subcon", name="ev_contractor_type"),
    sa.Enum("linear", "bell", "front", "back", name="ev_distribution"),
    sa.Enum("catalog", "history", "manual", name="ev_rate_source"),
    sa.Enum("draft", "active", "archived", name="ev_revision_status"),
    sa.Enum("spent", "earned", "budget", name="ev_composite_measure"),
)

# --- izin modulu (seed_data.MODULES / MATRIX'ten birebir kopya) -------------------

MODULE_KEY = "earned_value"
MODULE_NAME = "Planlama"
MODULE_GROUP = "SAHA"
MODULE_SORT_ORDER = 23

# earned_value son siraya eklendigi icin baska hicbir modul kaymaz.
SORT_ORDER_UPDATES: dict[str, int] = {}
PREVIOUS_SORT_ORDERS: dict[str, int] = {}

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

# §3.9 B1-8: [A, F, APR, DRF, N, V, F, N] — sef approve BILINCLI (dondurur, B3'te onaylar).
MATRIX: dict[str, list[tuple[str, str]]] = {
    MODULE_KEY: [
        ("admin", "all"),
        ("full", "all"),
        ("approve", "all"),
        ("draft", "all"),
        ("none", "all"),
        ("view", "all"),
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
_DELETE_PERMISSIONS = sa.text(
    "DELETE FROM role_permissions WHERE module_id IN (SELECT id FROM modules WHERE key = :key)"
)
_DELETE_MODULE = sa.text("DELETE FROM modules WHERE key = :key")


def _add_permission_module() -> None:
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


def _remove_permission_module() -> None:
    op.execute(_DELETE_PERMISSIONS.bindparams(key=MODULE_KEY))
    op.execute(_DELETE_MODULE.bindparams(key=MODULE_KEY))


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    for enum_type in NEW_ENUMS:
        enum_type.create(bind, checkfirst=True)

    op.create_table(
        "ev_disciplines",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("color", sa.String(length=7), nullable=False),
        sa.Column(
            "default_contractor_type",
            postgresql.ENUM(name="ev_contractor_type", create_type=False),
            nullable=False,
        ),
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
        sa.CheckConstraint("color ~ '^#[0-9A-Fa-f]{6}$'", name="ck_ev_disciplines_color_hex"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_ev_disciplines_code"),
    )
    op.create_table(
        "ev_catalog_items",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("discipline_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("uom", sa.String(length=50), nullable=False),
        sa.Column("standard_unit_mhr", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column(
            "default_contractor_type",
            postgresql.ENUM(name="ev_contractor_type", create_type=False),
            nullable=False,
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "standard_updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
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
        sa.CheckConstraint("standard_unit_mhr > 0", name="ck_ev_catalog_items_rate_positive"),
        sa.ForeignKeyConstraint(["discipline_id"], ["ev_disciplines.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "discipline_id", "name", "uom", name="uq_ev_catalog_items_disc_name_uom"
        ),
    )
    op.create_index(
        op.f("ix_ev_catalog_items_discipline_id"),
        "ev_catalog_items",
        ["discipline_id"],
        unique=False,
    )
    op.create_table(
        "ev_holidays",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("site_id", sa.UUID(), nullable=False),
        sa.Column("date_from", sa.Date(), nullable=False),
        sa.Column("date_to", sa.Date(), nullable=False),
        sa.Column("note", sa.String(length=200), server_default="", nullable=False),
        sa.CheckConstraint("date_to >= date_from", name="ck_ev_holidays_range"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ev_holidays_site_id"), "ev_holidays", ["site_id"], unique=False)
    op.create_table(
        "ev_revisions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("site_id", sa.UUID(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "status", postgresql.ENUM(name="ev_revision_status", create_type=False), nullable=False
        ),
        sa.Column("frozen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("frozen_by_user_id", sa.UUID(), nullable=True),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
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
        sa.CheckConstraint(
            "(status = 'draft') = (frozen_at IS NULL)", name="ck_ev_revisions_frozen_iff_not_draft"
        ),
        sa.CheckConstraint("number >= 0", name="ck_ev_revisions_number"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["frozen_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("site_id", "number", name="uq_ev_revisions_site_number"),
    )
    op.create_index(op.f("ix_ev_revisions_site_id"), "ev_revisions", ["site_id"], unique=False)
    op.create_index(
        "uq_ev_revisions_one_active",
        "ev_revisions",
        ["site_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "uq_ev_revisions_one_draft",
        "ev_revisions",
        ["site_id"],
        unique=True,
        postgresql_where=sa.text("status = 'draft'"),
    )
    op.create_table(
        "ev_site_settings",
        sa.Column("site_id", sa.UUID(), nullable=False),
        sa.Column("week_start_dow", sa.SmallInteger(), nullable=False),
        sa.Column("weekly_off_days", sa.SmallInteger(), nullable=False),
        sa.Column("standard_daily_hours", sa.Numeric(precision=4, scale=2), nullable=False),
        sa.Column("tolerance_points", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("daily_red_below", sa.Numeric(precision=5, scale=3), nullable=False),
        sa.Column("daily_green_from", sa.Numeric(precision=5, scale=3), nullable=False),
        sa.Column("daily_high_above", sa.Numeric(precision=5, scale=3), nullable=False),
        sa.Column("weekly_red_below", sa.Numeric(precision=5, scale=3), nullable=False),
        sa.Column("weekly_green_from", sa.Numeric(precision=5, scale=3), nullable=False),
        sa.Column("updated_by_user_id", sa.UUID(), nullable=True),
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
        sa.CheckConstraint(
            "daily_green_from >= daily_red_below AND daily_high_above >= daily_green_from",
            name="ck_ev_site_settings_daily_bands",
        ),
        sa.CheckConstraint(
            "standard_daily_hours >= 1 AND standard_daily_hours <= 16",
            name="ck_ev_site_settings_daily_hours",
        ),
        sa.CheckConstraint("tolerance_points >= 0", name="ck_ev_site_settings_tolerance"),
        sa.CheckConstraint("week_start_dow BETWEEN 0 AND 6", name="ck_ev_site_settings_week_start"),
        sa.CheckConstraint(
            "weekly_green_from >= weekly_red_below", name="ck_ev_site_settings_weekly_bands"
        ),
        sa.CheckConstraint(
            "weekly_off_days BETWEEN 0 AND 126", name="ck_ev_site_settings_off_days"
        ),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("site_id"),
    )
    op.create_table(
        "ev_baseline_leaves",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("revision_id", sa.UUID(), nullable=False),
        sa.Column("boq_item_id", sa.UUID(), nullable=False),
        sa.Column("boq_group_id", sa.UUID(), nullable=False),
        sa.Column("section_id", sa.UUID(), nullable=True),
        sa.Column("discipline_id", sa.UUID(), nullable=True),
        sa.Column("item_code", sa.String(length=50), nullable=False),
        sa.Column("item_description", sa.Text(), nullable=False),
        sa.Column("section_name", sa.String(length=150), nullable=True),
        sa.Column("uom", sa.String(length=50), nullable=False),
        sa.Column("planned_qty", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("unit_mhr", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column(
            "rate_source", postgresql.ENUM(name="ev_rate_source", create_type=False), nullable=True
        ),
        sa.Column(
            "contractor_type",
            postgresql.ENUM(name="ev_contractor_type", create_type=False),
            nullable=False,
        ),
        sa.Column("is_direct", sa.Boolean(), nullable=False),
        sa.Column(
            "distribution",
            postgresql.ENUM(name="ev_distribution", create_type=False),
            nullable=False,
        ),
        sa.Column("window_start", sa.Date(), nullable=True),
        sa.Column("window_end", sa.Date(), nullable=True),
        sa.Column("budget_mhr", sa.Numeric(precision=24, scale=8), nullable=False),
        sa.CheckConstraint(
            "(window_start IS NULL) = (window_end IS NULL)", name="ck_ev_baseline_leaves_window"
        ),
        sa.CheckConstraint("budget_mhr >= 0", name="ck_ev_baseline_leaves_budget"),
        sa.CheckConstraint("planned_qty >= 0", name="ck_ev_baseline_leaves_qty"),
        sa.ForeignKeyConstraint(["discipline_id"], ["ev_disciplines.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["revision_id"], ["ev_revisions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_ev_baseline_leaves_revision_id"),
        "ev_baseline_leaves",
        ["revision_id"],
        unique=False,
    )
    op.create_table(
        "ev_distributions",
        sa.Column("revision_id", sa.UUID(), nullable=False),
        sa.Column("discipline_id", sa.UUID(), nullable=False),
        sa.Column(
            "distribution",
            postgresql.ENUM(name="ev_distribution", create_type=False),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["discipline_id"], ["ev_disciplines.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["revision_id"], ["ev_revisions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("revision_id", "discipline_id"),
    )
    op.create_table(
        "ev_group_disciplines",
        sa.Column("revision_id", sa.UUID(), nullable=False),
        sa.Column("boq_group_id", sa.UUID(), nullable=False),
        sa.Column("discipline_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["boq_group_id"], ["boq_groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["discipline_id"], ["ev_disciplines.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["revision_id"], ["ev_revisions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("revision_id", "boq_group_id"),
    )
    op.create_index(
        op.f("ix_ev_group_disciplines_discipline_id"),
        "ev_group_disciplines",
        ["discipline_id"],
        unique=False,
    )
    op.create_table(
        "ev_windows",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("revision_id", sa.UUID(), nullable=False),
        sa.Column("discipline_id", sa.UUID(), nullable=False),
        sa.Column("section_id", sa.UUID(), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.CheckConstraint("end_date >= start_date", name="ck_ev_windows_range"),
        sa.ForeignKeyConstraint(["discipline_id"], ["ev_disciplines.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["revision_id"], ["ev_revisions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["section_id"], ["sections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_ev_windows_discipline_id"), "ev_windows", ["discipline_id"], unique=False
    )
    op.create_index(op.f("ix_ev_windows_revision_id"), "ev_windows", ["revision_id"], unique=False)
    op.create_index(op.f("ix_ev_windows_section_id"), "ev_windows", ["section_id"], unique=False)
    op.create_index(
        "uq_ev_windows_section",
        "ev_windows",
        ["revision_id", "discipline_id", "section_id"],
        unique=True,
        postgresql_where=sa.text("section_id IS NOT NULL"),
    )
    op.create_index(
        "uq_ev_windows_unsectioned",
        "ev_windows",
        ["revision_id", "discipline_id"],
        unique=True,
        postgresql_where=sa.text("section_id IS NULL"),
    )
    op.create_table(
        "ev_baseline_curve",
        sa.Column("leaf_id", sa.UUID(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("mhr", sa.Numeric(precision=24, scale=8), nullable=False),
        sa.CheckConstraint("mhr <> 0", name="ck_ev_baseline_curve_nonzero"),
        sa.ForeignKeyConstraint(["leaf_id"], ["ev_baseline_leaves.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("leaf_id", "day"),
    )
    op.create_table(
        "ev_composite_metrics",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("site_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column(
            "measure",
            postgresql.ENUM(name="ev_composite_measure", create_type=False),
            nullable=False,
        ),
        sa.Column("denominator_boq_item_id", sa.UUID(), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(["denominator_boq_item_id"], ["boq_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_ev_composite_metrics_denominator_boq_item_id"),
        "ev_composite_metrics",
        ["denominator_boq_item_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ev_composite_metrics_site_id"), "ev_composite_metrics", ["site_id"], unique=False
    )
    op.create_table(
        "ev_item_settings",
        sa.Column("revision_id", sa.UUID(), nullable=False),
        sa.Column("boq_item_id", sa.UUID(), nullable=False),
        sa.Column(
            "contractor_type",
            postgresql.ENUM(name="ev_contractor_type", create_type=False),
            nullable=True,
        ),
        sa.Column("is_direct", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("catalog_item_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(["boq_item_id"], ["boq_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["catalog_item_id"], ["ev_catalog_items.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["revision_id"], ["ev_revisions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("revision_id", "boq_item_id"),
    )
    op.create_table(
        "ev_leaf_settings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("revision_id", sa.UUID(), nullable=False),
        sa.Column("boq_item_id", sa.UUID(), nullable=False),
        sa.Column("section_id", sa.UUID(), nullable=True),
        sa.Column("unit_mhr", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column(
            "rate_source", postgresql.ENUM(name="ev_rate_source", create_type=False), nullable=True
        ),
        sa.Column(
            "contractor_type",
            postgresql.ENUM(name="ev_contractor_type", create_type=False),
            nullable=True,
        ),
        sa.Column("is_direct", sa.Boolean(), nullable=True),
        sa.CheckConstraint(
            "(unit_mhr IS NULL) = (rate_source IS NULL)", name="ck_ev_leaf_settings_rate_source"
        ),
        sa.CheckConstraint("unit_mhr IS NULL OR unit_mhr >= 0", name="ck_ev_leaf_settings_rate"),
        sa.ForeignKeyConstraint(["boq_item_id"], ["boq_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["revision_id"], ["ev_revisions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["section_id"], ["sections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_ev_leaf_settings_boq_item_id"), "ev_leaf_settings", ["boq_item_id"], unique=False
    )
    op.create_index(
        op.f("ix_ev_leaf_settings_revision_id"), "ev_leaf_settings", ["revision_id"], unique=False
    )
    op.create_index(
        op.f("ix_ev_leaf_settings_section_id"), "ev_leaf_settings", ["section_id"], unique=False
    )
    op.create_index(
        "uq_ev_leaf_settings_section",
        "ev_leaf_settings",
        ["revision_id", "boq_item_id", "section_id"],
        unique=True,
        postgresql_where=sa.text("section_id IS NOT NULL"),
    )
    op.create_index(
        "uq_ev_leaf_settings_unsectioned",
        "ev_leaf_settings",
        ["revision_id", "boq_item_id"],
        unique=True,
        postgresql_where=sa.text("section_id IS NULL"),
    )
    op.create_table(
        "ev_composite_metric_terms",
        sa.Column("metric_id", sa.UUID(), nullable=False),
        sa.Column("boq_item_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["boq_item_id"], ["boq_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["metric_id"], ["ev_composite_metrics.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("metric_id", "boq_item_id"),
    )

    _add_permission_module()


def downgrade() -> None:
    """Downgrade schema."""
    _remove_permission_module()
    op.drop_table("ev_composite_metric_terms")
    op.drop_index(
        "uq_ev_leaf_settings_unsectioned",
        table_name="ev_leaf_settings",
        postgresql_where=sa.text("section_id IS NULL"),
    )
    op.drop_index(
        "uq_ev_leaf_settings_section",
        table_name="ev_leaf_settings",
        postgresql_where=sa.text("section_id IS NOT NULL"),
    )
    op.drop_index(op.f("ix_ev_leaf_settings_section_id"), table_name="ev_leaf_settings")
    op.drop_index(op.f("ix_ev_leaf_settings_revision_id"), table_name="ev_leaf_settings")
    op.drop_index(op.f("ix_ev_leaf_settings_boq_item_id"), table_name="ev_leaf_settings")
    op.drop_table("ev_leaf_settings")
    op.drop_table("ev_item_settings")
    op.drop_index(op.f("ix_ev_composite_metrics_site_id"), table_name="ev_composite_metrics")
    op.drop_index(
        op.f("ix_ev_composite_metrics_denominator_boq_item_id"), table_name="ev_composite_metrics"
    )
    op.drop_table("ev_composite_metrics")
    op.drop_table("ev_baseline_curve")
    op.drop_index(
        "uq_ev_windows_unsectioned",
        table_name="ev_windows",
        postgresql_where=sa.text("section_id IS NULL"),
    )
    op.drop_index(
        "uq_ev_windows_section",
        table_name="ev_windows",
        postgresql_where=sa.text("section_id IS NOT NULL"),
    )
    op.drop_index(op.f("ix_ev_windows_section_id"), table_name="ev_windows")
    op.drop_index(op.f("ix_ev_windows_revision_id"), table_name="ev_windows")
    op.drop_index(op.f("ix_ev_windows_discipline_id"), table_name="ev_windows")
    op.drop_table("ev_windows")
    op.drop_index(op.f("ix_ev_group_disciplines_discipline_id"), table_name="ev_group_disciplines")
    op.drop_table("ev_group_disciplines")
    op.drop_table("ev_distributions")
    op.drop_index(op.f("ix_ev_baseline_leaves_revision_id"), table_name="ev_baseline_leaves")
    op.drop_table("ev_baseline_leaves")
    op.drop_table("ev_site_settings")
    op.drop_index(
        "uq_ev_revisions_one_draft",
        table_name="ev_revisions",
        postgresql_where=sa.text("status = 'draft'"),
    )
    op.drop_index(
        "uq_ev_revisions_one_active",
        table_name="ev_revisions",
        postgresql_where=sa.text("status = 'active'"),
    )
    op.drop_index(op.f("ix_ev_revisions_site_id"), table_name="ev_revisions")
    op.drop_table("ev_revisions")
    op.drop_index(op.f("ix_ev_holidays_site_id"), table_name="ev_holidays")
    op.drop_table("ev_holidays")
    op.drop_index(op.f("ix_ev_catalog_items_discipline_id"), table_name="ev_catalog_items")
    op.drop_table("ev_catalog_items")
    op.drop_table("ev_disciplines")

    bind = op.get_bind()
    for enum_type in reversed(NEW_ENUMS):
        enum_type.drop(bind, checkfirst=True)
