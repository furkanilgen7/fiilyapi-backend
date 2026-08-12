"""ik1 personel belge

İK-1 T1 — personel kartı genişletme + belge takibi (backend spec
`docs/superpowers/specs/2026-08-12-ik1-personel-belge-design.md` §1, §2, §5).

Üç parça:
  1. `personnel` tablosuna 20 YENİ NULLABLE kolon (spec §5 K3: taslak-yayın
     zorunluluğu SERVİS katmanında uygulanır, bu migration yalnız DB izin
     verir) + `tc_no` UNIQUE indeks (NULL'lar `NULLS DISTINCT` sayesinde
     serbesttir — iki taslak kayıt TCKN'siz bir arada durabilir).
  2. `personnel_document_types` katalog tablosu + SEED (6 sabit tip, spec §2).
     CRUD ucu YOKTUR (yönetimi ayarlar dilimine ertelendi).
  3. `personnel_documents` — belge takip kaydı. `type_id` XOR `free_label`
     CHECK'i zorunlu (katalogdan seçim YA DA serbest etiket). `document_id`
     BC-2 pilotu: dosya baytları `documents` arşivine yazılır, bu kayıt yalnız
     künyeye bağlanır (SET NULL — dosyasız kayıt da meşru).

Dört yeni enum tipi (`gender` / `marital_status` / `wage_type` /
`payment_method`) — `worker_source` PAYLAŞILAN tiptir, buradan DÜŞÜRÜLMEZ.

Elle yazılmıştır (autogenerate DEĞİL) — repo deseni.

Revision ID: a1b2c3d4e5f6
Revises: f3a4b5c6d7e8
Create Date: 2026-08-12

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "f3a4b5c6d7e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

gender_enum = sa.Enum("male", "female", name="gender")
marital_status_enum = sa.Enum("single", "married", name="marital_status")
wage_type_enum = sa.Enum("daily", "monthly", "hourly", name="wage_type")
payment_method_enum = sa.Enum("bank", "cash", "mixed", name="payment_method")

# `worker_source` BU LISTEDE YOK — paylaşılan tip, bu migration'ın sahipliğinde
# değil (santiye günlüğü dilimi b5c6d7e8f9a0'da yaratıldı).
NEW_ENUMS = (
    gender_enum,
    marital_status_enum,
    wage_type_enum,
    payment_method_enum,
)

# Seed sırası PE mockup B1-B3 ✱ + BT tip dağılımı (spec §2) — sabit UUID
# DEĞİLDİR, `uuid.uuid4()` ile üretilir; downgrade'de tablo tamamen düştüğü
# için ikinci upgrade'de çakışma riski yoktur.
DOCUMENT_TYPE_SEED = (
    {"name": "Kimlik Fotokopisi", "is_mandatory": True, "validity_months": None, "sort_order": 1},
    {"name": "Sağlık Raporu", "is_mandatory": True, "validity_months": 12, "sort_order": 2},
    {
        "name": "İSG Eğitim Sertifikası",
        "is_mandatory": True,
        "validity_months": 36,
        "sort_order": 3,
    },
    {"name": "Mesleki Yeterlilik", "is_mandatory": False, "validity_months": None, "sort_order": 4},
    {"name": "Operatör/Ehliyet", "is_mandatory": False, "validity_months": None, "sort_order": 5},
    {"name": "İş Sözleşmesi", "is_mandatory": False, "validity_months": None, "sort_order": 6},
)


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()

    # 1. Yeni enum tipleri.
    for enum_type in NEW_ENUMS:
        enum_type.create(bind, checkfirst=True)

    # 2. `personnel` karti genislemesi — HEPSI nullable (spec §5 K3).
    op.add_column("personnel", sa.Column("tc_no", sa.String(length=11), nullable=True))
    op.add_column("personnel", sa.Column("birth_date", sa.Date(), nullable=True))
    op.add_column(
        "personnel",
        sa.Column("gender", postgresql.ENUM(name="gender", create_type=False), nullable=True),
    )
    op.add_column(
        "personnel",
        sa.Column(
            "marital_status",
            postgresql.ENUM(name="marital_status", create_type=False),
            nullable=True,
        ),
    )
    op.add_column("personnel", sa.Column("phone", sa.String(length=30), nullable=True))
    op.add_column("personnel", sa.Column("email", sa.String(length=255), nullable=True))
    op.add_column("personnel", sa.Column("address", sa.Text(), nullable=True))
    op.add_column(
        "personnel", sa.Column("emergency_contact_name", sa.String(length=200), nullable=True)
    )
    op.add_column(
        "personnel", sa.Column("emergency_contact_phone", sa.String(length=30), nullable=True)
    )
    op.add_column("personnel", sa.Column("hire_date", sa.Date(), nullable=True))
    op.add_column(
        "personnel",
        sa.Column("wage_type", postgresql.ENUM(name="wage_type", create_type=False), nullable=True),
    )
    op.add_column(
        "personnel", sa.Column("wage_amount", sa.Numeric(precision=12, scale=2), nullable=True)
    )
    op.add_column(
        "personnel",
        sa.Column(
            "payment_method",
            postgresql.ENUM(name="payment_method", create_type=False),
            nullable=True,
        ),
    )
    op.add_column("personnel", sa.Column("iban", sa.String(length=34), nullable=True))
    op.add_column("personnel", sa.Column("sgk_no", sa.String(length=20), nullable=True))
    op.add_column("personnel", sa.Column("assigned_project_id", sa.UUID(), nullable=True))
    op.add_column("personnel", sa.Column("assigned_section_id", sa.UUID(), nullable=True))
    op.add_column(
        "personnel",
        sa.Column("is_draft", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )

    op.create_unique_constraint("uq_personnel_tc_no", "personnel", ["tc_no"])
    op.create_foreign_key(
        "fk_personnel_assigned_project_id",
        "personnel",
        "projects",
        ["assigned_project_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_personnel_assigned_section_id",
        "personnel",
        "sections",
        ["assigned_section_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_personnel_assigned_project_id", "personnel", ["assigned_project_id"])
    op.create_index("ix_personnel_assigned_section_id", "personnel", ["assigned_section_id"])

    # 3. personnel_document_types — katalog. CRUD ucu YOK, seed 6 sabit tip.
    op.create_table(
        "personnel_document_types",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("is_mandatory", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("validity_months", sa.Integer(), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_personnel_document_types_name"),
    )

    document_type_types = sa.table(
        "personnel_document_types",
        sa.column("id", sa.UUID()),
        sa.column("name", sa.String()),
        sa.column("is_mandatory", sa.Boolean()),
        sa.column("validity_months", sa.Integer()),
        sa.column("sort_order", sa.Integer()),
    )
    op.bulk_insert(
        document_type_types,
        [{**row, "id": uuid.uuid4()} for row in DOCUMENT_TYPE_SEED],
    )

    # 4. personnel_documents — belge takip kaydi.
    op.create_table(
        "personnel_documents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("personnel_id", sa.UUID(), nullable=False),
        sa.Column("type_id", sa.UUID(), nullable=True),
        sa.Column("free_label", sa.String(length=150), nullable=True),
        sa.Column("document_id", sa.UUID(), nullable=True),
        sa.Column("issued_at", sa.Date(), nullable=True),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
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
            "(type_id IS NOT NULL AND free_label IS NULL) OR "
            "(type_id IS NULL AND free_label IS NOT NULL)",
            name="ck_personnel_document_type_xor_label",
        ),
        sa.ForeignKeyConstraint(["personnel_id"], ["personnel.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["type_id"], ["personnel_document_types.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_personnel_documents_personnel_id", "personnel_documents", ["personnel_id"])
    op.create_index("ix_personnel_documents_valid_until", "personnel_documents", ["valid_until"])
    op.create_index(
        "ix_personnel_documents_personnel_type",
        "personnel_documents",
        ["personnel_id", "type_id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()

    op.drop_index("ix_personnel_documents_personnel_type", table_name="personnel_documents")
    op.drop_index("ix_personnel_documents_valid_until", table_name="personnel_documents")
    op.drop_index("ix_personnel_documents_personnel_id", table_name="personnel_documents")
    op.drop_table("personnel_documents")

    op.drop_table("personnel_document_types")

    op.drop_index("ix_personnel_assigned_section_id", table_name="personnel")
    op.drop_index("ix_personnel_assigned_project_id", table_name="personnel")
    op.drop_constraint("fk_personnel_assigned_section_id", "personnel", type_="foreignkey")
    op.drop_constraint("fk_personnel_assigned_project_id", "personnel", type_="foreignkey")
    op.drop_constraint("uq_personnel_tc_no", "personnel", type_="unique")

    op.drop_column("personnel", "is_draft")
    op.drop_column("personnel", "assigned_section_id")
    op.drop_column("personnel", "assigned_project_id")
    op.drop_column("personnel", "sgk_no")
    op.drop_column("personnel", "iban")
    op.drop_column("personnel", "payment_method")
    op.drop_column("personnel", "wage_amount")
    op.drop_column("personnel", "wage_type")
    op.drop_column("personnel", "hire_date")
    op.drop_column("personnel", "emergency_contact_phone")
    op.drop_column("personnel", "emergency_contact_name")
    op.drop_column("personnel", "address")
    op.drop_column("personnel", "email")
    op.drop_column("personnel", "phone")
    op.drop_column("personnel", "marital_status")
    op.drop_column("personnel", "gender")
    op.drop_column("personnel", "birth_date")
    op.drop_column("personnel", "tc_no")

    # Enum tipleri tablolarla birlikte SILINMEZ — acikca dusurulur, yoksa ikinci
    # `upgrade` "type already exists" ile patlar (d4e5f6a7b8c9 dersi).
    # `worker_source` BURADA YOK — paylasilan tip, dusurulmez.
    for enum_type in NEW_ENUMS:
        enum_type.drop(bind, checkfirst=False)
