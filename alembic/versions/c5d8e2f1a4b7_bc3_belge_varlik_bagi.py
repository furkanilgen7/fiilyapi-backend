"""bc3 belge varlik bagi

BC-3 — belge ↔ varlık bağı (bölüm · ünite · satış · taşeron sözleşmesi).

Şekil BC-2 PİLOTUNUN genişletilmesidir (`personnel_documents` / `leave_requests`
emsali): FK `documents`ta DEĞİL, SAHİP tarafında durur — dosya BC arşivinde,
sahibin bağ satırı künyeye `document_id` → `documents.id` **SET NULL** ile
bağlanır. Polimorfik `owner_type`/`owner_id` çifti YAZILMADI (emir §1).

BEŞ yeni tablo + BİR yeni PG enum:
  1. `entity_document_scope` (enum: section · unit · unit_sale ·
     subcontractor_contract) — TEK tip, beş tablo paylaşır.
  2. `entity_document_types` — paylaşılan slot kataloğu, `scope` ile bölümlü.
     SEED **18 satır** (mockup'tan birebir: Bolum Ekle 3 · Unite Ekle 3 ·
     Daire Satisi 6 · Sözleşme Oluştur 6). CRUD ucu YOK (İK-1/MK-2 emsali).
     `UNIQUE(id, scope)` bileşik FK'nin hedefidir.
  3-6. `section_documents` · `unit_documents` · `unit_sale_documents` ·
     `subcontractor_contract_documents` — `→sahip CASCADE` · `→documents SET
     NULL` · `(type_id, scope) → entity_document_types(id, scope)` bileşik FK +
     `scope` kendi sabitine CHECK ile çakılı: yanlış bölmenin tipi DB'de
     imkânsızdır (`fk_units_block_project` emsali).

`documents.project_id` NOT NULL **KALIR**; türetme sunucuda (sahipten), bu
migration `documents` tablosuna DOKUNMAZ. İzin modülü AÇILMAZ: dört sahibin
anahtarı zaten var (`sites` · `projects` · `sales` · `contracts`).

Yeni tablo + seed olduğu için `NOT VALID`/sayım deseni gerekmez: mevcut satır
YOKTUR, hiçbir kısıt canlı veriye çarpamaz.

Elle yazılmıştır (autogenerate DEĞİL) — repo deseni.

Revision ID: c5d8e2f1a4b7
Revises: b4d7e1c9f2a3
Create Date: 2026-09-05

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c5d8e2f1a4b7"
down_revision: str | Sequence[str] | None = "b4d7e1c9f2a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENUM_NAME = "entity_document_scope"
SCOPES = ("section", "unit", "unit_sale", "subcontractor_contract")

#: Enum tablolarla birlikte YARATILMAZ/SİLİNMEZ — açıkça (İK-2 `leave_status`
#: deseni); kolonlar `create_type=False` ile başvurur.
scope_enum = sa.Enum(*SCOPES, name=ENUM_NAME)


def _scope_column_type() -> postgresql.ENUM:
    return postgresql.ENUM(name=ENUM_NAME, create_type=False)


# `is_required` = formdaki `*` işareti. İpucu satırları ("Bu faza ait çizimler")
# UI metnidir, kolon AÇILMADI (equipment emsali).
#: (scope, code, name, is_required, sort_order) — mockup sırasıyla.
SLOT_SEED: tuple[tuple[str, str, str, bool, int], ...] = (
    # Form - Bolum Ekle · "📎 Bölüm Belgeleri"
    ("section", "application_project", "Uygulama Projesi", False, 1),
    ("section", "quantity_takeoff", "Metraj Cetveli", False, 2),
    ("section", "hse_phase_plan", "İSG Faz Planı", False, 3),
    # Form - Unite Ekle · "📎 Ünite Belgeleri"
    ("unit", "floor_plan", "Kat Planı", False, 1),
    ("unit", "renders", "Görseller / Render", False, 2),
    ("unit", "condominium_deed", "Kat İrtifakı Tapusu", False, 3),
    # Form - Daire Satisi · "📎 Satış Belgeleri"
    ("unit_sale", "sales_contract", "Satış Sözleşmesi", True, 1),
    ("unit_sale", "buyer_id", "Alıcı Kimlik", True, 2),
    ("unit_sale", "down_payment_receipt", "Peşinat Dekontu", False, 3),
    ("unit_sale", "loan_approval", "Kredi Onay Yazısı", False, 4),
    ("unit_sale", "title_deed", "Tapu Senedi", False, 5),
    ("unit_sale", "handover_report", "Teslim Tutanağı", False, 6),
    # Form - Sözleşme Oluştur · "📎 Sözleşme Belgeleri" (Yeni Taşeron Sözleşmesi)
    ("subcontractor_contract", "signed_contract", "İmzalı Sözleşme", True, 1),
    ("subcontractor_contract", "guarantee_letter", "Teminat Mektubu", False, 2),
    ("subcontractor_contract", "sgk_clearance", "SGK Borcu Yoktur Yazısı", True, 3),
    ("subcontractor_contract", "tax_certificate", "Vergi Levhası & Sicil", False, 4),
    ("subcontractor_contract", "hse_commitment", "İş Güvenliği Taahhütnamesi", False, 5),
    ("subcontractor_contract", "unit_price_analysis", "Birim Fiyat Analizi", False, 6),
)

#: (tablo, sahip kolonu, sahip tablosu, scope sabiti) — dört bağ tablosu tek
#: döngüde kurulur ki dördü ayrışmasın.
LINK_TABLES: tuple[tuple[str, str, str, str], ...] = (
    ("section_documents", "section_id", "sections", "section"),
    ("unit_documents", "unit_id", "units", "unit"),
    ("unit_sale_documents", "unit_sale_id", "unit_sales", "unit_sale"),
    (
        "subcontractor_contract_documents",
        "subcontractor_contract_id",
        "subcontractor_contracts",
        "subcontractor_contract",
    ),
)


def _create_link_table(table: str, owner_column: str, owner_table: str, scope: str) -> None:
    op.create_table(
        table,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(owner_column, sa.UUID(), nullable=False),
        sa.Column(
            "scope",
            _scope_column_type(),
            server_default=sa.text(f"'{scope}'::{ENUM_NAME}"),
            nullable=False,
        ),
        sa.Column("type_id", sa.UUID(), nullable=False),
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
        sa.CheckConstraint(f"scope = '{scope}'", name=f"ck_{table}_scope"),
        # CASCADE: sahip silinirse bağ satırı da gider; arşivdeki dosya KALIR.
        sa.ForeignKeyConstraint([owner_column], [f"{owner_table}.id"], ondelete="CASCADE"),
        # SET NULL: BC-2 pilotu — arşiv kaydı silinse de slot satırı kalır.
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="SET NULL"),
        # Bileşik FK: yanlış bölmenin tipi DB'de imkânsız; RESTRICT: kullanımda
        # olan katalog tipi silinemez.
        sa.ForeignKeyConstraint(
            ["type_id", "scope"],
            ["entity_document_types.id", "entity_document_types.scope"],
            name=f"fk_{table}_type_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(f"ix_{table}_type_id", table, ["type_id"])
    op.create_index(f"ix_{table}_document_id", table, ["document_id"])
    op.create_index(f"ix_{table}_owner_type", table, [owner_column, "type_id"])


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    scope_enum.create(bind, checkfirst=True)

    # 1. entity_document_types — paylaşılan katalog, seed 18 sabit slot.
    op.create_table(
        "entity_document_types",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("scope", _scope_column_type(), nullable=False),
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
        sa.UniqueConstraint("scope", "code", name="uq_entity_document_types_scope_code"),
        sa.UniqueConstraint("id", "scope", name="uq_entity_document_types_id_scope"),
    )

    slot_table = sa.table(
        "entity_document_types",
        sa.column("id", sa.UUID()),
        sa.column("scope", _scope_column_type()),
        sa.column("code", sa.String()),
        sa.column("name", sa.String()),
        sa.column("is_required", sa.Boolean()),
        sa.column("sort_order", sa.Integer()),
    )
    op.bulk_insert(
        slot_table,
        [
            {
                "id": uuid.uuid4(),
                "scope": scope,
                "code": code,
                "name": name,
                "is_required": is_required,
                "sort_order": sort_order,
            }
            for scope, code, name, is_required, sort_order in SLOT_SEED
        ],
    )

    # 2-5. dört bağ tablosu.
    for table, owner_column, owner_table, scope in LINK_TABLES:
        _create_link_table(table, owner_column, owner_table, scope)


def downgrade() -> None:
    """Downgrade schema."""
    for table, _owner_column, _owner_table, _scope in reversed(LINK_TABLES):
        op.drop_index(f"ix_{table}_owner_type", table_name=table)
        op.drop_index(f"ix_{table}_document_id", table_name=table)
        op.drop_index(f"ix_{table}_type_id", table_name=table)
        op.drop_table(table)

    op.drop_table("entity_document_types")

    # Enum tipi tablolarla birlikte SİLİNMEZ — açıkça düşürülür, yoksa ikinci
    # `upgrade` "type already exists" ile patlar (İK-2 deseni).
    scope_enum.drop(op.get_bind(), checkfirst=False)
