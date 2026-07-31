"""P3.1 — blok/unite alan tamamlama: 21 kolon + 1 UNIQUE + 10 CHECK

`blocks` +13 kolon (BE 71-102), `units` +8 kolon (UE 66-94). Spec §3.1 / §4.1.

HICBIR KOLON `NOT NULL` DEGILDIR (spec §10.3): gerekce canli veri degil, TASLAK
DESTEGIDIR — mockup'taki kirmizi `*` yalniz UI ipucudur.

VERI GECISI YOKTUR (spec §10.4, karar 8): `blocks.code` backfill'i yazilmaz;
canli bloklarin kodu `NULL` dogar, `NULL` kalir ve bir sonraki `PATCH` sirasinda
uretilir.

TUZAK — `status` / `sales_status` varsayilanlari IKI ADIMDA konur:
`ALTER TABLE ... ADD COLUMN ... DEFAULT 'x'` Postgres'te MEVCUT SATIRLARI DA
doldurur ve "mevcut satirlar degismez" kuralini sessizce ihlal ederdi. Bu yuzden
kolon once varsayilansiz eklenir, `SET DEFAULT` SONRA uygulanir: eski satirlar
`NULL` kalir, yeni satirlar varsayilani alir.

Enum tipleri R2'de (`c2d3e4f5a6b7`) olusturuldu; burada `create_type=False` ile
BAGLANIR — ikinci `CREATE TYPE` patlardi. `downgrade` tipleri DUSURMEZ, onlar
R2'nin sorumlulugudur.

`ck_units_floor` YOKTUR: kat metindir (karar 4).

GERI ALMA NOTU: `downgrade` 21 kolonu dusurur, dolayisiyla bu kolonlardaki
degerler KAYBOLUR. Bu bilinclidir.

Revision ID: c3d4e5f6a7b8
Revises: c2d3e4f5a6b7
Create Date: 2026-07-31 11:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: str | Sequence[str] | None = "c2d3e4f5a6b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enum(name: str, *labels: str) -> postgresql.ENUM:
    """R2'de olusturulmus tipe BAGLAN — yeniden olusturma (spec §10.2/R3)."""
    return postgresql.ENUM(*labels, name=name, create_type=False)


def _block_columns() -> tuple[sa.Column, ...]:
    """Her cagrida YENI Column nesneleri: `sa.Column` bir kez bir tabloya
    baglandiktan sonra yeniden kullanilamaz."""
    return (
        sa.Column("code", sa.String(length=20), nullable=True),
        sa.Column("basement_floor_count", sa.Integer(), nullable=True),
        sa.Column("floor_count", sa.Integer(), nullable=True),
        sa.Column(
            "roof_type", _enum("block_roof_type", "none", "duplex", "terrace"), nullable=True
        ),
        sa.Column("units_per_floor", sa.Integer(), nullable=True),
        sa.Column(
            "ground_floor_usage",
            _enum("block_ground_usage", "commercial", "apartment", "common"),
            nullable=True,
        ),
        sa.Column("shop_count", sa.Integer(), nullable=True),
        sa.Column("construction_area_m2", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("elevator_count", sa.Integer(), nullable=True),
        sa.Column(
            "parking_type", _enum("block_parking_type", "closed", "open", "none"), nullable=True
        ),
        sa.Column("estimated_delivery_date", sa.Date(), nullable=True),
        sa.Column(
            "status", _enum("block_status", "planning", "construction", "completed"), nullable=True
        ),
        sa.Column("notes", sa.String(length=500), nullable=True),
    )


def _unit_columns() -> tuple[sa.Column, ...]:
    return (
        sa.Column("floor", sa.String(length=20), nullable=True),
        sa.Column(
            "facing",
            _enum("unit_facing", "south", "southwest", "east", "north", "west"),
            nullable=True,
        ),
        sa.Column("balcony_area_m2", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("bathroom_count", sa.Integer(), nullable=True),
        sa.Column(
            "parking_right", _enum("unit_parking_right", "none", "one_closed", "two"), nullable=True
        ),
        sa.Column("min_sale_price", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("vat_rate", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column(
            "sales_status",
            _enum("unit_sales_status", "listed", "reserved", "sold", "closed"),
            nullable=True,
        ),
    )


BLOCK_CHECKS = (
    ("ck_blocks_basement_floor_count", "basement_floor_count IS NULL OR basement_floor_count >= 0"),
    ("ck_blocks_floor_count", "floor_count IS NULL OR floor_count >= 0"),
    ("ck_blocks_units_per_floor", "units_per_floor IS NULL OR units_per_floor >= 0"),
    ("ck_blocks_shop_count", "shop_count IS NULL OR shop_count >= 0"),
    ("ck_blocks_construction_area", "construction_area_m2 IS NULL OR construction_area_m2 >= 0"),
    ("ck_blocks_elevator_count", "elevator_count IS NULL OR elevator_count >= 0"),
)

UNIT_CHECKS = (
    ("ck_units_balcony_area", "balcony_area_m2 IS NULL OR balcony_area_m2 >= 0"),
    ("ck_units_bathroom_count", "bathroom_count IS NULL OR bathroom_count >= 0"),
    ("ck_units_min_sale_price", "min_sale_price IS NULL OR min_sale_price >= 0"),
    ("ck_units_vat_rate", "vat_rate IS NULL OR (vat_rate >= 0 AND vat_rate <= 100)"),
)


def upgrade() -> None:
    for column in _block_columns():
        op.add_column("blocks", column)
    for column in _unit_columns():
        op.add_column("units", column)

    # Varsayilanlar AYRI adimda: `ADD COLUMN ... DEFAULT` mevcut satirlari da
    # doldururdu (bkz. modul docstring'i).
    op.execute("ALTER TABLE blocks ALTER COLUMN status SET DEFAULT 'construction'")
    op.execute("ALTER TABLE units ALTER COLUMN sales_status SET DEFAULT 'listed'")

    op.create_unique_constraint("uq_blocks_project_code", "blocks", ["project_id", "code"])
    for name, condition in BLOCK_CHECKS:
        op.create_check_constraint(name, "blocks", sa.text(condition))
    for name, condition in UNIT_CHECKS:
        op.create_check_constraint(name, "units", sa.text(condition))


def downgrade() -> None:
    for name, _ in UNIT_CHECKS:
        op.drop_constraint(name, "units", type_="check")
    for name, _ in BLOCK_CHECKS:
        op.drop_constraint(name, "blocks", type_="check")
    op.drop_constraint("uq_blocks_project_code", "blocks", type_="unique")

    for column in _unit_columns():
        op.drop_column("units", column.name)
    for column in _block_columns():
        op.drop_column("blocks", column.name)
    # Enum TIPLERI dusurulmez — R2'nin (`c2d3e4f5a6b7`) sorumlulugudur.
