"""ok1a onay zinciri motoru

UC yeni tablo (`user_approval_roles` / `approval_chains` / `approval_steps`),
IKI yeni enum (`approval_role` / `approval_document_type`) ve `company`ye TEK
ADDITIVE kolon (`approval_threshold_try`) — OK-1A sozlesmesi Y0/Y9.

IZIN MIGRATION'I YOKTUR: `approvals` ("Onay Kutusu", ModuleGroup.GENEL) izin
modulu seed'de ZATEN VARDIR ve matris satiri da mevcuttur (`roles/seed_data.py`)
— yeni modul ACILMAZ, `seed_data.py` DEGISMEZ.

## Neden `approval_chains.document_id` FK DEGIL

Zincir UC AYRI evrak ailesine baglanir (taseron hakedisi · satinalma talebi ·
isveren hakedisi) ve Postgres'te cok-bicimli bir FK yoktur. Butunluk uygulama
katmanindadir; `uq_approval_chains_document` ise bir evragin AYNI ANDA EN FAZLA
BIR acik zinciri olmasini DB duzeyinde zorlar.

## Neden `amount_snapshot` NULLABLE, `threshold_snapshot` DEGIL

Ikisi de MK-2 N-carpanli snapshot kanonu geregi vardir: adim listesi
`amount >= threshold` karsilastirmasinin turevidir ve HER IKI carpan da donar.
Fark, "bilinmeyen"in temsilindedir: tutarin BELIRLENEMEDIGI hâller gercektir
(fiyatsiz kalem · satirsiz hakedis · `contract_amount IS NULL`) ve o hâlde
yazilacak her sayi YALAN olurdu. `0` yazilsaydi "eksik veri" ile "sifir tutar"
denetim yuzeyinde ayirt edilemezdi — SA'da esigi FIILEN atlatan kusurun sinifi.
Esik ise her zaman bilinir (kolonun `server_default`i vardir), bu yuzden NOT NULL.

## Kullanici silinince ne olur

* `user_approval_roles` -> **CASCADE**: atama bir IZ degil YETKILENDIRMEDIR.
* `approval_chains.created_by_user_id` ve `approval_steps.decided_by_user_id`
  -> **SET NULL**: onay bir OLGUDUR, aktoru silinse de iz AYAKTA kalir.
* `approval_steps.chain_id` -> **CASCADE**: ret zinciri siler, adimlar da gider
  (K2 "tum onaylar silinir").

## `company.approval_threshold_try`

`server_default='500000.00'` ZORUNLUDUR: canlida `company` satiri ZATEN vardir
ve varsayilansiz bir NOT NULL kolon `ALTER TABLE`i patlatirdi (acilista
`alembic upgrade head && uvicorn ...` -> `&&` kisa devre -> TAM KESINTI).
Sayinin Python tarafindaki tek kaynagi
`approvals.definitions.DEFAULT_APPROVAL_THRESHOLD_TRY`dir; buraya KOPYALANIR
ve ITHAL EDILMEZ, cunku migration gecmisi DONMUS olmalidir.

Elle yazilmistir (autogenerate DEGIL) — repo deseni.

Revision ID: f1a2b3c4d5e6
Revises: e9f0a1b2c3d4
Create Date: 2026-08-21

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f1a2b3c4d5e6"
down_revision: str | Sequence[str] | None = "e9f0a1b2c3d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Degerler `roles/seed_data.py` ROLES anahtarlariyla BIREBIR aynidir (R1).
approval_role_enum = sa.Enum(
    "site_chief",
    "project_manager",
    "accounting",
    "patron",
    "procurement",
    name="approval_role",
)
approval_document_type_enum = sa.Enum(
    "subcontractor_progress_payment",
    "purchase_request",
    "progress_payment",
    name="approval_document_type",
)

NEW_ENUMS = (approval_role_enum, approval_document_type_enum)

#: 🔴 KOPYADIR, ITHAL DEGIL (modul docstring'i): migration gecmisi donmustur.
DEFAULT_THRESHOLD_SQL = "500000.00"


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()

    # 1. Yeni enum tipleri.
    for enum_type in NEW_ENUMS:
        enum_type.create(bind, checkfirst=True)

    # 2. user_approval_roles — kullanici <-> ONAY ROLU (COK-A-COK, K1).
    op.create_table(
        "user_approval_roles",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "approval_role",
            postgresql.ENUM(name="approval_role", create_type=False),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "approval_role", name="uq_user_approval_roles_user_role"),
    )
    # FK'ler otomatik indeks URETMEZ; her onay kontrolu bu sutundan gecer.
    op.create_index("ix_user_approval_roles_user_id", "user_approval_roles", ["user_id"])

    # 3. approval_chains — evragin ACILMIS zincir ornegi.
    op.create_table(
        "approval_chains",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "document_type",
            postgresql.ENUM(name="approval_document_type", create_type=False),
            nullable=False,
        ),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("threshold_snapshot", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("amount_snapshot", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_type", "document_id", name="uq_approval_chains_document"),
    )
    op.create_index(
        "ix_approval_chains_created_by_user_id", "approval_chains", ["created_by_user_id"]
    )

    # 4. approval_steps — sira + rol + karar damgasi.
    op.create_table(
        "approval_steps",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("chain_id", sa.UUID(), nullable=False),
        sa.Column("step_no", sa.Integer(), nullable=False),
        sa.Column(
            "approval_role",
            postgresql.ENUM(name="approval_role", create_type=False),
            nullable=False,
        ),
        sa.Column("decided_by_user_id", sa.UUID(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["chain_id"], ["approval_chains.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["decided_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chain_id", "step_no", name="uq_approval_steps_chain_step_no"),
    )
    op.create_index("ix_approval_steps_chain_id", "approval_steps", ["chain_id"])

    # 5. Esik ayari — ADDITIVE kolon, `server_default` ZORUNLU (docstring).
    op.add_column(
        "company",
        sa.Column(
            "approval_threshold_try",
            sa.Numeric(precision=18, scale=2),
            server_default=sa.text(DEFAULT_THRESHOLD_SQL),
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()

    op.drop_column("company", "approval_threshold_try")

    op.drop_index("ix_approval_steps_chain_id", table_name="approval_steps")
    op.drop_table("approval_steps")

    op.drop_index("ix_approval_chains_created_by_user_id", table_name="approval_chains")
    op.drop_table("approval_chains")

    op.drop_index("ix_user_approval_roles_user_id", table_name="user_approval_roles")
    op.drop_table("user_approval_roles")

    # 🔴 Enum tipleri tablolarla birlikte SILINMEZ — acikca dusurulur, yoksa
    # ikinci `upgrade` "type already exists" ile patlar (d4e5f6a7b8c9 dersi) ve
    # bu YALNIZ CANLIDA gorulur: konteyner acilista `alembic upgrade head &&
    # uvicorn ...` kosar, `&&` kisa devre yapar, uvicorn HIC BASLAMAZ.
    for enum_type in NEW_ENUMS:
        enum_type.drop(bind, checkfirst=False)
