"""p11 takvim/gantt: sections.depends_on_section_id + section_milestones

Iki sema degisikligi (P11 spec §2, plan T1):

1. `sections.depends_on_section_id` — SELF-FK, NULLABLE, `ondelete="SET NULL"`
   + `ix_sections_depends_on_section_id`. Form 115-117 TEK oncul select cizer;
   coklu bagimlilik CIZILMEMISTIR, ara tablo ACILMAZ. Bag yalniz BILGIDIR
   (Gantt baglanti cizgisi): tarih kisiti DB'de de uygulamada da ZORLANMAZ.
   `SET NULL` cunku oncul silinince bagimli bolum silinmemeli, yalnizca bagi
   kopmalidir — `CASCADE` burada veri kaybi olurdu.

2. YENI `section_milestones` — `id` · `section_id` FK→sections CASCADE ·
   `title` String(200) · `milestone_date` Date · `sort_order`. Bolum silinince
   kilometre taslari da duser (bagimsiz yasami yoktur).
   DURUM KOLONU YOKTUR (spec §6 S2): "Tamamlandi" tarih TUREVIDIR.

ACILMAYANLAR (kalici kararlar, spec §4/§6): `progress_pct` ilerleme kolonu (S1 —
kaynak tanimsiz) · `include_in_timeline` (S5 — form artefakti) · milestone durum
kolonu (S2) · coklu bagimlilik tablosu (S3). Enum YOK, izin modulu YOK
(`projects:view` okur, `sites` yazar).

`ADD COLUMN ... DEFAULT` kullanilmaz — kolon nullable ve varsayilansizdir, mevcut
satirlara dokunulmaz (c3d4e5f6a7b8 dersi).

GERI ALMA NOTU: `downgrade` tabloyu ve kolonu dusurur; girilmis kilometre taslari
ve bagimlilik atamalari KAYBOLUR. Bu bilinclidir.

Elle yazilmistir (autogenerate DEGIL) — repo deseni.

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-08-11

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d0e1f2a3b4c5"
down_revision: str | Sequence[str] | None = "c9d0e1f2a3b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # --- 1. sections.depends_on_section_id (self-FK) ---
    op.add_column("sections", sa.Column("depends_on_section_id", sa.UUID(), nullable=True))
    # Ad, Postgres'in kendi uretecegi adin AYNISIDIR: model tarafinda FK adsizdir,
    # `alembic check` ad farkina takilmaz (c9d0e1f2a3b4 deseni).
    op.create_foreign_key(
        "sections_depends_on_section_id_fkey",
        "sections",
        "sections",
        ["depends_on_section_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_sections_depends_on_section_id", "sections", ["depends_on_section_id"])

    # --- 2. section_milestones ---
    op.create_table(
        "section_milestones",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("section_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("milestone_date", sa.Date(), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(["section_id"], ["sections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_section_milestones_section_id", "section_milestones", ["section_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_section_milestones_section_id", table_name="section_milestones")
    op.drop_table("section_milestones")

    op.drop_index("ix_sections_depends_on_section_id", table_name="sections")
    op.drop_constraint("sections_depends_on_section_id_fkey", "sections", type_="foreignkey")
    op.drop_column("sections", "depends_on_section_id")
