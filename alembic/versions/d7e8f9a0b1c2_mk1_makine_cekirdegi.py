"""mk1 makine cekirdegi

Uc yeni tablo (`equipment` / `equipment_work_logs` / `equipment_fuel_logs`),
DOKUZ yeni enum ve 21. izin modulu ("equipment" satiri + 8 role_permissions)
— MK-1 spec §2, §5, §6, plan T1.

Izin modulu MIGRATION ISTER (BC/`documents` emsali): `seed_data.py`yi
degistirmek canlidaki MEVCUT kayitlara satir eklemez, yalnizca bos bir DB'nin
ilk kurulumunu etkiler.

`amount` KOLONU YOKTUR (spec §2.3): yakit tutari `liters × unit_price`
turevidir — P10 "tek formul" kanonu. Bakiye/kullanim/maliyet/sapma kolonlari da
yoktur; hepsi satirlardan turetilir (K15/K16/K17/K18).

Kapsam disi (spec §9, kasitli): kira hakedisi tablolari YOK (M5 para
tutarsizligi cozulmedi) · ekipman belge slotu YOK (mockup gecerlilik tarihi
cizmiyor) · bakim kaydi tablosu YOK (mockup yok) · `warehouse_id` YOK (K4).

Ornek makine SEED EDILMEZ: M1 kartlari mockup verisidir.

Elle yazilmistir (autogenerate DEGIL) — repo deseni.

Revision ID: d7e8f9a0b1c2
Revises: c5d6e7f8a9b0
Create Date: 2026-08-13

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d7e8f9a0b1c2"
down_revision: str | Sequence[str] | None = "c5d6e7f8a9b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# --------------------------------------------------------------------------- #
# Enum'lar (spec §5) — DOKUZU DA YENI.
# --------------------------------------------------------------------------- #

equipment_category_enum = sa.Enum(
    "crane",
    "machinery",
    "truck",
    "concrete",
    "compressor",
    "hand_tool",
    name="equipment_category",
)
equipment_status_enum = sa.Enum("working", "maintenance", "broken", "idle", name="equipment_status")
equipment_ownership_enum = sa.Enum("owned", "rented", name="equipment_ownership")
equipment_financing_enum = sa.Enum("cash", "bank_loan", "leasing", name="equipment_financing")
equipment_rate_period_enum = sa.Enum("hourly", "daily", "monthly", name="equipment_rate_period")
equipment_fuel_type_enum = sa.Enum(
    "diesel", "gasoline", "electric", "none", name="equipment_fuel_type"
)
equipment_norm_unit_enum = sa.Enum("lt_hour", "lt_km", name="equipment_norm_unit")
equipment_maintenance_period_enum = sa.Enum(
    "hours_250", "hours_500", "hours_1000", "monthly", name="equipment_maintenance_period"
)
work_log_type_enum = sa.Enum("worked", "breakdown", name="work_log_type")

NEW_ENUMS = (
    equipment_category_enum,
    equipment_status_enum,
    equipment_ownership_enum,
    equipment_financing_enum,
    equipment_rate_period_enum,
    equipment_fuel_type_enum,
    equipment_norm_unit_enum,
    equipment_maintenance_period_enum,
    work_log_type_enum,
)

# --------------------------------------------------------------------------- #
# Izin modulu (spec §6) — `documents` (b8c9d0e1f2a3) emsalinin birebiri.
# --------------------------------------------------------------------------- #

# Bu migration app.modules.roles.seed_data'yi kasitli olarak import ETMEZ:
# uygulanmis bir migration donmus olmalidir, uygulama kodu zamanla degisir.
# Asagidaki veriler seed_data.py'daki MODULES/MATRIX'ten birebir kopyalanmistir;
# esitligi tests/modules/test_seed_migration_matches_seed_data.py dogrular.

MODULE_KEY = "equipment"
MODULE_NAME = "Makine & Ekipman"
MODULE_GROUP = "SAHA"
MODULE_SORT_ORDER = 21

# equipment son siraya eklendigi icin baska hicbir modul kaymaz
# (boq 17 / contracts 18 / sales 19 / documents 20 deseni).
SORT_ORDER_UPDATES: dict[str, int] = {}

# downgrade()'in geri yazacagi degerler — kaydirma olmadigi icin bos.
PREVIOUS_SORT_ORDERS: dict[str, int] = {}

# Sutun sirasi — asagidaki MATRIX satiri bu sirayla okunur (seed_data.ROLE_ORDER).
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

# spec §6: system_admin=admin, patron=full, site_chief=full (makineyi sahada o
# kullanir), field_engineer=view, hr_manager=none, accounting=full (varlik +
# maliyet), project_manager=full, procurement=view.
MATRIX: dict[str, list[tuple[str, str]]] = {
    MODULE_KEY: [
        ("admin", "all"),
        ("full", "all"),
        ("full", "all"),
        ("view", "all"),
        ("none", "all"),
        ("full", "all"),
        ("full", "all"),
        ("view", "all"),
    ],
}

# Canli DB'de satirlar kismen mevcut olabilir (elle mudahale, yarim kalmis kosu):
# her yazma idempotent, boylece yeniden calistirma UNIQUE kisitini ihlal etmez.
_INSERT_MODULE = sa.text(
    'INSERT INTO modules (id, key, name, "group", sort_order) '
    "VALUES (CAST(:id AS uuid), :key, :name, CAST(:group AS module_group), :sort_order) "
    "ON CONFLICT (key) DO NOTHING"
)

# role_id/module_id canli ortamda calisma aninda okunur: ilk seed migration'i
# UUID'leri uuid4() ile uretti, dolayisiyla sabit kodlanamazlar.
_INSERT_PERMISSION = sa.text(
    "INSERT INTO role_permissions (id, role_id, module_id, access_level, scope) "
    "SELECT CAST(:id AS uuid), r.id, m.id, "
    "CAST(:access_level AS access_level), CAST(:scope AS scope) "
    "FROM roles r, modules m "
    "WHERE r.key = :role_key AND m.key = :module_key "
    "ON CONFLICT ON CONSTRAINT uq_role_module DO NOTHING"
)

_UPDATE_SORT_ORDER = sa.text("UPDATE modules SET sort_order = :sort_order WHERE key = :key")

_DELETE_PERMISSIONS = sa.text(
    "DELETE FROM role_permissions WHERE module_id IN (SELECT id FROM modules WHERE key = :key)"
)

_DELETE_MODULE = sa.text("DELETE FROM modules WHERE key = :key")


def _apply_sort_orders(orders: dict[str, int]) -> None:
    for key, sort_order in orders.items():
        op.execute(_UPDATE_SORT_ORDER.bindparams(key=key, sort_order=sort_order))


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()

    # 1. Dokuz yeni enum tipi.
    for enum_type in NEW_ENUMS:
        enum_type.create(bind, checkfirst=True)

    # 2. equipment — kart. `supplier_id`/`site_id`/`operator_id` UCU DE SET NULL:
    #    tedarikci, santiye ya da personel kaydi kalksa makine ve maliyet
    #    gecmisi AYAKTA kalir. `is_draft` YOKTUR (M2'de taslak butonu yok).
    op.create_table(
        "equipment",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "category",
            postgresql.ENUM(name="equipment_category", create_type=False),
            nullable=False,
        ),
        # K1: marka ve model AYRI kolon (M1:94 karti yalniz markayi basiyor).
        sa.Column("brand", sa.String(length=100), nullable=True),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("serial_no", sa.String(length=100), nullable=True),
        sa.Column("plate_no", sa.String(length=30), nullable=True),
        sa.Column("model_year", sa.Integer(), nullable=True),
        sa.Column(
            "ownership",
            postgresql.ENUM(name="equipment_ownership", create_type=False),
            server_default=sa.text("'owned'::equipment_ownership"),
            nullable=False,
        ),
        # K2: nullable — kosullu zorunluluk SERVISTEDIR, DB CHECK'i degil.
        sa.Column("purchase_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("purchase_date", sa.Date(), nullable=True),
        # M2:100 uc secenek basiyor ama SERBEST TAMSAYI (enum degil).
        sa.Column("depreciation_years", sa.Integer(), nullable=True),
        # K3: satici ve kiralama firmasi TEK kolon — SA'nin `suppliers` tablosu.
        sa.Column("supplier_id", sa.UUID(), nullable=True),
        sa.Column(
            "financing",
            postgresql.ENUM(name="equipment_financing", create_type=False),
            nullable=True,
        ),
        sa.Column("market_value", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("rate_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column(
            "rate_period",
            postgresql.ENUM(name="equipment_rate_period", create_type=False),
            nullable=True,
        ),
        # K4: NULL = "Depoda (Atanmadi)". `warehouse_id` ACILMAZ.
        sa.Column("site_id", sa.UUID(), nullable=True),
        sa.Column("operator_id", sa.UUID(), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(name="equipment_status", create_type=False),
            server_default=sa.text("'working'::equipment_status"),
            nullable=False,
        ),
        sa.Column("status_note", sa.Text(), nullable=True),
        sa.Column("status_expected_date", sa.Date(), nullable=True),
        sa.Column(
            "fuel_type",
            postgresql.ENUM(name="equipment_fuel_type", create_type=False),
            nullable=True,
        ),
        # K5: SAYI + ayri birim enum'u (metin DEGIL).
        sa.Column("norm_consumption", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column(
            "norm_unit",
            postgresql.ENUM(name="equipment_norm_unit", create_type=False),
            nullable=True,
        ),
        sa.Column(
            "maintenance_period",
            postgresql.ENUM(name="equipment_maintenance_period", create_type=False),
            nullable=True,
        ),
        # K7: kullanim %'sinin PAYDASI VERIDIR, koda gomulmez. Varsayilan 200,
        # M3 rozetlerinden tersine muhendislikle dogrulandi.
        sa.Column(
            "monthly_capacity_hours",
            sa.Integer(),
            server_default=sa.text("200"),
            nullable=False,
        ),
        # K8: YALNIZ bir isaret — sabit kiymet modulu YOK, yan etki uydurulmaz.
        sa.Column("is_company_asset", sa.Boolean(), server_default=sa.text("true"), nullable=False),
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
        sa.CheckConstraint(
            "purchase_amount IS NULL OR purchase_amount >= 0",
            name="ck_equipment_purchase_amount_non_negative",
        ),
        sa.CheckConstraint(
            "market_value IS NULL OR market_value >= 0",
            name="ck_equipment_market_value_non_negative",
        ),
        sa.CheckConstraint(
            "rate_amount IS NULL OR rate_amount >= 0",
            name="ck_equipment_rate_amount_non_negative",
        ),
        sa.CheckConstraint(
            "norm_consumption IS NULL OR norm_consumption > 0",
            name="ck_equipment_norm_consumption_positive",
        ),
        sa.CheckConstraint(
            "monthly_capacity_hours >= 0", name="ck_equipment_monthly_capacity_non_negative"
        ),
        sa.CheckConstraint(
            "depreciation_years IS NULL OR depreciation_years > 0",
            name="ck_equipment_depreciation_years_positive",
        ),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["operator_id"], ["personnel.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_equipment_category", "equipment", ["category"])
    op.create_index("ix_equipment_site_id", "equipment", ["site_id"])
    op.create_index("ix_equipment_status", "equipment", ["status"])

    # 3. equipment_work_logs — M3. `equipment_id` RESTRICT: maliyet izi olan
    #    ekipman silinemez (`payroll_lines`→`personnel` emsali). UQ YOKTUR:
    #    ayni gun birden cok vardiya/ariza kaydi olabilir (tavan K12, serviste
    #    KILITLI olarak denetlenir).
    op.create_table(
        "equipment_work_logs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("equipment_id", sa.UUID(), nullable=False),
        sa.Column("work_date", sa.Date(), nullable=False),
        # K9: kaydin KENDI santiyesi — tarihsel atama izi burada yasar.
        sa.Column("site_id", sa.UUID(), nullable=True),
        # Ariza kaydinda operator YOKTUR (M3:280).
        sa.Column("operator_id", sa.UUID(), nullable=True),
        sa.Column(
            "record_type",
            postgresql.ENUM(name="work_log_type", create_type=False),
            server_default=sa.text("'worked'::work_log_type"),
            nullable=False,
        ),
        sa.Column("start_time", sa.Time(), nullable=True),
        sa.Column("end_time", sa.Time(), nullable=True),
        # K11: SUNUCU HESABI — istemcinin gonderdigi `hours` 422'dir.
        sa.Column("hours", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.UUID(), nullable=True),
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
        sa.CheckConstraint("hours >= 0 AND hours <= 24", name="ck_equipment_work_logs_hours_range"),
        # K11: iki zaman alani BIRLIKTE ya hic verilmez ya ikisi de verilir.
        sa.CheckConstraint(
            "(start_time IS NULL) = (end_time IS NULL)",
            name="ck_equipment_work_logs_time_pair",
        ),
        sa.ForeignKeyConstraint(["equipment_id"], ["equipment.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["operator_id"], ["personnel.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_equipment_work_logs_equipment_id", "equipment_work_logs", ["equipment_id"])
    op.create_index("ix_equipment_work_logs_work_date", "equipment_work_logs", ["work_date"])
    op.create_index("ix_equipment_work_logs_site_id", "equipment_work_logs", ["site_id"])
    op.create_index("ix_equipment_work_logs_record_type", "equipment_work_logs", ["record_type"])

    # 4. equipment_fuel_logs — M4. `amount` KOLONU YOKTUR (turev).
    #    `unit_price` SATIR BAZLIDIR (K13): donem sabiti olsaydi gecmis
    #    kayitlarin tutari bugunku fiyatla degisirdi.
    op.create_table(
        "equipment_fuel_logs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("equipment_id", sa.UUID(), nullable=False),
        sa.Column("fuel_date", sa.Date(), nullable=False),
        sa.Column("site_id", sa.UUID(), nullable=True),
        sa.Column("liters", sa.Numeric(precision=10, scale=2), nullable=False),
        # DORT ondalik: litre fiyati kurusun altinda kotalanir (M4:111).
        sa.Column("unit_price", sa.Numeric(precision=10, scale=4), nullable=False),
        # K14: "Giren" ROL degil KULLANICIDIR — rol kullanicidan turer.
        sa.Column("entered_by_id", sa.UUID(), nullable=True),
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
        sa.CheckConstraint("liters > 0", name="ck_equipment_fuel_logs_liters_positive"),
        sa.CheckConstraint("unit_price > 0", name="ck_equipment_fuel_logs_unit_price_positive"),
        sa.ForeignKeyConstraint(["equipment_id"], ["equipment.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["entered_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_equipment_fuel_logs_equipment_id", "equipment_fuel_logs", ["equipment_id"])
    op.create_index("ix_equipment_fuel_logs_fuel_date", "equipment_fuel_logs", ["fuel_date"])
    op.create_index("ix_equipment_fuel_logs_site_id", "equipment_fuel_logs", ["site_id"])

    # 5. Izin modulu: equipment satiri (21.) + 8 role_permissions (spec §6).
    op.execute(
        _INSERT_MODULE.bindparams(
            id=str(uuid.uuid4()),
            key=MODULE_KEY,
            name=MODULE_NAME,
            group=MODULE_GROUP,
            sort_order=MODULE_SORT_ORDER,
        )
    )
    _apply_sort_orders(SORT_ORDER_UPDATES)

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


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()

    op.execute(_DELETE_PERMISSIONS.bindparams(key=MODULE_KEY))
    op.execute(_DELETE_MODULE.bindparams(key=MODULE_KEY))
    _apply_sort_orders(PREVIOUS_SORT_ORDERS)

    op.drop_index("ix_equipment_fuel_logs_site_id", table_name="equipment_fuel_logs")
    op.drop_index("ix_equipment_fuel_logs_fuel_date", table_name="equipment_fuel_logs")
    op.drop_index("ix_equipment_fuel_logs_equipment_id", table_name="equipment_fuel_logs")
    op.drop_table("equipment_fuel_logs")

    op.drop_index("ix_equipment_work_logs_record_type", table_name="equipment_work_logs")
    op.drop_index("ix_equipment_work_logs_site_id", table_name="equipment_work_logs")
    op.drop_index("ix_equipment_work_logs_work_date", table_name="equipment_work_logs")
    op.drop_index("ix_equipment_work_logs_equipment_id", table_name="equipment_work_logs")
    op.drop_table("equipment_work_logs")

    op.drop_index("ix_equipment_status", table_name="equipment")
    op.drop_index("ix_equipment_site_id", table_name="equipment")
    op.drop_index("ix_equipment_category", table_name="equipment")
    op.drop_table("equipment")

    # Enum tipleri tablolarla birlikte SILINMEZ — DOKUZU DA acikca dusurulur,
    # yoksa ikinci `upgrade` "type already exists" ile patlar (d4e5f6a7b8c9 dersi).
    for enum_type in NEW_ENUMS:
        enum_type.drop(bind, checkfirst=False)
