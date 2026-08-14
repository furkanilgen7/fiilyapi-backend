"""mk2 ekipman belgeleri

MK-2 T4 — ekipman belgeleri (backend spec
`docs/superpowers/specs/2026-08-14-mk2-kira-hakedisi-design.md` §2.3, §4, K7).

İki yeni tablo:
  1. `equipment_document_types` — katalog, SEED 6 sabit tip (M2:134-159'un altı
     slotu). CRUD ucu YOKTUR (İK-1 `personnel_document_types` emsali).
  2. `equipment_documents` — belge kaydı. Dosya baytları (`content`) BURADA
     tutulur, İK-1'in `document_id` → genel `documents` arşivi bağlantısı
     BİLİNÇLİ OLARAK KULLANILMAZ: o arşiv `project_id`yi ZORUNLU tutar ve
     ekipmanın `site_id`si NULL olabilir (K4 "Depoda") — her ekipman belgesinin
     bir projeye bağlanabileceği garanti değildir (model docstring'inde
     ayrıntılı gerekçe). Doğrulama/saklama TEKNİĞİ (uzantı beyaz listesi, boyut
     tavanı, `nosniff`) yine de BC/İK-1'den BİREBİR alınır — yalnız tablo AYRIDIR.

İzin modülü AÇILMAZ: `equipment` MK-1'de açıldı, bu migration izin satırı YAZMAZ.

Elle yazılmıştır (autogenerate DEĞİL) — repo deseni.

Revision ID: f9a0b1c2d3e4
Revises: e8f9a0b1c2d3
Create Date: 2026-08-14

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f9a0b1c2d3e4"
down_revision: str | Sequence[str] | None = "e8f9a0b1c2d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# M2:134-159 sırasıyla — zorunlu ikisi ÖNCE (İSG mevzuatı), sonra opsiyoneller.
DOCUMENT_TYPE_SEED = (
    {
        "code": "invoice_or_contract",
        "name": "Fatura / Kira Sözleşmesi",
        "is_required": True,
        "sort_order": 1,
    },
    {
        "code": "periodic_inspection",
        "name": "Periyodik Muayene Raporu",
        "is_required": True,
        "sort_order": 2,
    },
    {
        "code": "ce_certificate",
        "name": "CE Belgesi / Uygunluk",
        "is_required": False,
        "sort_order": 3,
    },
    {"code": "manual", "name": "Kullanım Kılavuzu", "is_required": False, "sort_order": 4},
    {
        "code": "insurance_policy",
        "name": "Sigorta Poliçesi",
        "is_required": False,
        "sort_order": 5,
    },
    {
        "code": "delivery_photos",
        "name": "Teslim Fotoğrafları",
        "is_required": False,
        "sort_order": 6,
    },
)


def upgrade() -> None:
    """Upgrade schema."""
    # 1. equipment_document_types — katalog. CRUD ucu YOK, seed 6 sabit tip.
    op.create_table(
        "equipment_document_types",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("is_required", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_equipment_document_types_code"),
    )

    document_type_table = sa.table(
        "equipment_document_types",
        sa.column("id", sa.UUID()),
        sa.column("code", sa.String()),
        sa.column("name", sa.String()),
        sa.column("is_required", sa.Boolean()),
        sa.column("sort_order", sa.Integer()),
    )
    op.bulk_insert(
        document_type_table,
        [{**row, "id": uuid.uuid4()} for row in DOCUMENT_TYPE_SEED],
    )

    # 2. equipment_documents — belge kaydı. `content` bytea BURADA (migration
    #    docstring'indeki gerekçe: genel `documents` arşivi `project_id`
    #    zorunlu tutar, ekipmanın site_id'si NULL olabilir).
    op.create_table(
        "equipment_documents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("equipment_id", sa.UUID(), nullable=False),
        sa.Column("type_id", sa.UUID(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        # K7 — onaylı sapma: mockup slotunda tarih alanı YOK ama periyodik
        # muayene/sigorta poliçesi süreli belgelerdir (güvenlik yüzeyi).
        sa.Column("valid_until", sa.Date(), nullable=True),
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
        sa.CheckConstraint("size_bytes >= 0", name="ck_equipment_documents_size_non_negative"),
        # CASCADE: ekipman silinemez zaten (RESTRICT'li çalışma/yakıt/kira
        # kayıtları varsa), ama silinebildiği teorik durumda belgesi yetim kalmaz.
        sa.ForeignKeyConstraint(["equipment_id"], ["equipment.id"], ondelete="CASCADE"),
        # RESTRICT: kullanımda olan katalog tipi silinemez (CRUD ucu zaten yok).
        sa.ForeignKeyConstraint(["type_id"], ["equipment_document_types.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_equipment_documents_equipment_id", "equipment_documents", ["equipment_id"])
    op.create_index("ix_equipment_documents_type_id", "equipment_documents", ["type_id"])
    op.create_index("ix_equipment_documents_valid_until", "equipment_documents", ["valid_until"])
    op.create_index(
        "ix_equipment_documents_equipment_type",
        "equipment_documents",
        ["equipment_id", "type_id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_equipment_documents_equipment_type", table_name="equipment_documents")
    op.drop_index("ix_equipment_documents_valid_until", table_name="equipment_documents")
    op.drop_index("ix_equipment_documents_type_id", table_name="equipment_documents")
    op.drop_index("ix_equipment_documents_equipment_id", table_name="equipment_documents")
    op.drop_table("equipment_documents")

    op.drop_table("equipment_document_types")
