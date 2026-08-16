"""frm1 ekipman belge alanlari

FRM-1 (BOR-TEMIZ T2) — `equipment_documents` tablosuna üç künye alanı:

  * `document_no` — belge numarası (mockup biçimi `TC-48-MUA-2026`).
    **K1**: uzunluk EMSALLE bağlıdır — `contracts.contract_no`,
    `equipment.serial_no` ve `equipment_rental_invoices.invoice_no` hepsi
    `String(100)`; yeni bir uzunluk İCAT EDİLMEZ.
  * `issued_at` — düzenlenme tarihi.
  * `note` — serbest not.

**K6**: `issued_at` ve `note` adları personel tarafındaki karşılıklarıyla
(`personnel_documents.issued_at` / `.note`) BİREBİR aynıdır — eşanlamlı yeni ad
uydurulmaz.

Üçü de **nullable**'dır: mevcut satırlar dokunulmadan geçerli kalır, veri
dönüşümü YOKTUR ve hiçbir enum/`ALTER TYPE` içermez. Downgrade üç
`drop_column`dur — migration TAM geri alınabilir.

Elle yazılmıştır (autogenerate DEĞİL) — repo deseni.

Revision ID: d3e4f5a6b7c8
Revises: c8d9e0f1a2b3
Create Date: 2026-08-16

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d3e4f5a6b7c8"
down_revision: str | Sequence[str] | None = "c8d9e0f1a2b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "equipment_documents"


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(TABLE, sa.Column("document_no", sa.String(length=100), nullable=True))
    op.add_column(TABLE, sa.Column("issued_at", sa.Date(), nullable=True))
    op.add_column(TABLE, sa.Column("note", sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column(TABLE, "note")
    op.drop_column(TABLE, "issued_at")
    op.drop_column(TABLE, "document_no")
