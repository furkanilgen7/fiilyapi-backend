"""santiye formu genislemesi — sites 22 kolon + sections.manager_user_id

Mockup `Form - Santiye Ekle.dc.html` icin `sites` tablosuna 22 kolon,
`sections` tablosuna `manager_user_id` eklenir (spec §3.0, §11.1).

HICBIR YENI KOLON `NOT NULL` + VARSAYILANSIZ DEGILDIR. Gerekce TASLAK
destegidir: "Taslak Kaydet" yarim doldurulmus formu kaydeder, yani mockup'ta
zorunlu (*) isaretli alanlar (sef, il/ilce, insaat alani, tarihler) bile DB'de
bos durabilmelidir. Zorunluluk YALNIZ uygulama katmaninda, YALNIZ taslak-disi
POST'ta uygulanir (spec §5.1). Ikincil fayda: mevcut satirlar kirilmaz.

`uq_sites_project_code` DEGISTIRILMEZ (spec §3.2/§11.3): kod uretimi sirket
geneli tekil, kisit proje ici tekil kalir. Mevcut ad-turevi kodlari (`A-BLOK`)
`SNT-` desenine ceviren HICBIR `UPDATE` yazilmaz — kod evrakta referanstir.

Silme uclari migration GEREKTIRMEZ: `sites.id`'yi hedefleyen dort `CASCADE` FK
oldugu gibi kalir, koruma servis katmanindadir (spec §11.1).

Revision ID: a7c9e1f3b5d2
Revises: f1b2c3d4e5a6
Create Date: 2026-07-30 11:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7c9e1f3b5d2"
down_revision: str | Sequence[str] | None = "f1b2c3d4e5a6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FACILITY_COLUMNS = (
    "has_closed_warehouse",
    "has_open_storage",
    "has_cold_storage",
    "has_site_office",
    "has_canteen",
    "has_changing_room_wc",
    "has_dormitory",
    "has_infirmary",
)

NULLABLE_SITE_COLUMNS = (
    ("safety_officer_name", sa.String(length=200)),
    ("neighborhood", sa.String(length=150)),
    ("parcel", sa.String(length=50)),
    ("gps_coordinates", sa.String(length=50)),
    ("land_area_m2", sa.Numeric(precision=12, scale=2)),
    ("floor_info", sa.String(length=100)),
    ("budget", sa.Numeric(precision=18, scale=2)),
    ("electricity_subscription_no", sa.String(length=50)),
    ("water_subscription_no", sa.String(length=50)),
    ("planned_worker_count", sa.Integer()),
)

BOOLEAN_SITE_COLUMNS = ("safety_officer_is_outsourced", *FACILITY_COLUMNS, "is_draft")

USER_FK_COLUMNS = (
    ("sites", "site_manager_user_id", "fk_sites_site_manager_user_id"),
    ("sites", "safety_officer_user_id", "fk_sites_safety_officer_user_id"),
    ("sections", "manager_user_id", "fk_sections_manager_user_id"),
)


def upgrade() -> None:
    for column, type_ in NULLABLE_SITE_COLUMNS:
        op.add_column("sites", sa.Column(column, type_, nullable=True))

    # NOT NULL yalniz sunucu varsayilanli Boolean'larda: mevcut satirlar `false`
    # olur, yeni satirlar da (mockup on-isaretleri UYGULANMAZ — spec §14.2).
    for column in BOOLEAN_SITE_COLUMNS:
        op.add_column(
            "sites",
            sa.Column(column, sa.Boolean(), nullable=False, server_default=sa.text("false")),
        )

    # Kullanici FK'leri: `SET NULL` — kullanici silinse de ad anlik goruntusu KALIR.
    for table, column, _fk_name in USER_FK_COLUMNS:
        op.add_column(table, sa.Column(column, postgresql.UUID(as_uuid=True), nullable=True))

    for table, column, fk_name in USER_FK_COLUMNS:
        op.create_index(f"ix_{table}_{column}", table, [column])
        op.create_foreign_key(fk_name, table, "users", [column], ["id"], ondelete="SET NULL")

    op.create_check_constraint(
        "ck_sites_safety_officer",
        "sites",
        "NOT (safety_officer_is_outsourced AND safety_officer_user_id IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_sites_safety_officer", "sites", type_="check")

    for table, column, fk_name in USER_FK_COLUMNS:
        op.drop_constraint(fk_name, table, type_="foreignkey")
        op.drop_index(f"ix_{table}_{column}", table_name=table)
        op.drop_column(table, column)

    for column in BOOLEAN_SITE_COLUMNS:
        op.drop_column("sites", column)

    for column, _type in NULLABLE_SITE_COLUMNS:
        op.drop_column("sites", column)
