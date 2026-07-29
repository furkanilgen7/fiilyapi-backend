"""p1.1a proje formu semasi (rev.2)

`employers` + `project_contracts` tablolari, `price_index_type` enum'u,
`projects` yeni sutunlari (employer_id, parcel, address, dort butce kalemi,
is_draft), `sites.construction_area_m2` ve `employer_name` -> `employers`
veri gocu (spec §2.2–§2.6). API uclari B3–B6'dadir; bu revizyon yalniz semadir.

Revision ID: e2b3c4d5f6a7
Revises: d1a2b3c4e5f6
Create Date: 2026-07-29 12:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e2b3c4d5f6a7"
down_revision: str | Sequence[str] | None = "d1a2b3c4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

price_index_type_enum = sa.Enum(
    "ufe", "tufe", "construction_cost", "fixed_coefficient", name="price_index_type"
)

# Her farkli (kirpilmis) employer_name icin bir employers satiri (spec §2.3 veri gocu).
_INSERT_EMPLOYERS = sa.text(
    "INSERT INTO employers (id, name, tax_number, contact_person, is_active, "
    "created_at, updated_at) "
    "SELECT gen_random_uuid(), s.name, NULL, NULL, true, now(), now() "
    "FROM (SELECT DISTINCT btrim(employer_name) AS name FROM projects "
    "WHERE employer_name IS NOT NULL AND btrim(employer_name) <> '') s"
)

# Projelerin employer_id'sini bagla. Bos/NULL employer_name -> employer_id NULL kalir.
_LINK_EMPLOYERS = sa.text(
    "UPDATE projects p SET employer_id = e.id FROM employers e "
    "WHERE e.name = btrim(p.employer_name) "
    "AND p.employer_name IS NOT NULL AND btrim(p.employer_name) <> ''"
)


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    price_index_type_enum.create(bind, checkfirst=True)

    op.create_table(
        "employers",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("tax_number", sa.String(length=11), nullable=True),
        sa.Column("contact_person", sa.String(length=200), nullable=True),
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
    # Kismi benzersiz indeks: VKN opsiyonel, coklu NULL serbest (spec §2.2).
    op.create_index(
        "uq_employers_tax_number",
        "employers",
        ["tax_number"],
        unique=True,
        postgresql_where=sa.text("tax_number IS NOT NULL"),
    )
    op.create_index("ix_employers_name", "employers", ["name"])

    op.create_table(
        "project_contracts",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("contract_no", sa.String(length=100), nullable=True),
        sa.Column("signature_date", sa.Date(), nullable=True),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column(
            "advance_pct",
            sa.Numeric(precision=5, scale=2),
            server_default=sa.text("20"),
            nullable=False,
        ),
        sa.Column(
            "retainage_pct",
            sa.Numeric(precision=5, scale=2),
            server_default=sa.text("5"),
            nullable=False,
        ),
        sa.Column(
            "vat_pct",
            sa.Numeric(precision=5, scale=2),
            server_default=sa.text("20"),
            nullable=False,
        ),
        sa.Column("late_penalty_daily", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column(
            "has_price_escalation",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "index_type",
            postgresql.ENUM(name="price_index_type", create_type=False),
            nullable=True,
        ),
        sa.Column("base_index_value", sa.Numeric(precision=12, scale=3), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("project_id"),
        sa.CheckConstraint(
            "advance_pct BETWEEN 0 AND 100 "
            "AND retainage_pct BETWEEN 0 AND 100 "
            "AND vat_pct BETWEEN 0 AND 100",
            name="ck_contract_pct_range",
        ),
        sa.CheckConstraint(
            "has_price_escalation = true OR (index_type IS NULL AND base_index_value IS NULL)",
            name="ck_contract_escalation",
        ),
    )

    # projects yeni sutunlari. NOT NULL kalemler server_default ile eklenir ki
    # mevcut satirlar 0/false alsin (spec §2.3, §7.5 — eski satirlar dagitilmaz).
    op.add_column("projects", sa.Column("employer_id", sa.UUID(), nullable=True))
    op.add_column("projects", sa.Column("parcel", sa.String(length=50), nullable=True))
    op.add_column("projects", sa.Column("address", sa.String(length=300), nullable=True))
    for column in ("budget_material", "budget_labor", "budget_subcontractor", "budget_overhead"):
        op.add_column(
            "projects",
            sa.Column(
                column,
                sa.Numeric(precision=18, scale=2),
                server_default=sa.text("0"),
                nullable=False,
            ),
        )
    op.add_column(
        "projects",
        sa.Column("is_draft", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.create_foreign_key(
        "fk_projects_employer_id",
        "projects",
        "employers",
        ["employer_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    # sites toplamali sutun (spec §2.6) — additive + nullable.
    op.add_column(
        "sites",
        sa.Column("construction_area_m2", sa.Numeric(precision=12, scale=2), nullable=True),
    )

    # Veri gocu: employer_name -> employers, ardindan employer_id bagla.
    op.execute(_INSERT_EMPLOYERS)
    op.execute(_LINK_EMPLOYERS)


def downgrade() -> None:
    """Downgrade schema. employer_name KORUNUR (hic dokunulmadi), veri kaybi yok."""
    op.drop_column("sites", "construction_area_m2")

    op.drop_constraint("fk_projects_employer_id", "projects", type_="foreignkey")
    op.drop_column("projects", "is_draft")
    op.drop_column("projects", "budget_overhead")
    op.drop_column("projects", "budget_subcontractor")
    op.drop_column("projects", "budget_labor")
    op.drop_column("projects", "budget_material")
    op.drop_column("projects", "address")
    op.drop_column("projects", "parcel")
    op.drop_column("projects", "employer_id")

    op.drop_table("project_contracts")
    op.drop_index("ix_employers_name", table_name="employers")
    op.drop_index("uq_employers_tax_number", table_name="employers")
    op.drop_table("employers")

    price_index_type_enum.drop(op.get_bind(), checkfirst=True)
