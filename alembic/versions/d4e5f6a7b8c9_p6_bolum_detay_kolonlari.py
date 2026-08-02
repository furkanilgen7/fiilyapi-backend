"""P6 T1 — `sections` yeni kolonlar + `section_status`'a `on_hold`

`Form - Bolum Ekle` mockup'inin istedigi 7 kolon `sections`'a eklenir (spec §3)
ve `section_status` enum'una `on_hold` ("Beklemede", Form 71) girer (spec §4).

HICBIR YENI KOLON `NOT NULL` DEGILDIR — `is_draft` haric (spec §3, kalici karar 4).
Gerekce TASLAK destegidir: "Taslak Kaydet" yarim doldurulmus formu kaydeder, yani
mockup'taki kirmizi `*` yalniz UI ipucudur; zorunluluk UYGULAMA katmaninda,
yalniz taslak-disi POST'ta uygulanir. DB'de zorunluluk = taslak yok demektir.

`budget_amount` (Form 110) ELLE girilir — §7 S2a kullanici karari. Model bugune
kadar "bolum bedeli BOQ turevidir" diyordu ama BOQ-bolum bagi KAPALI (kalici
karar 1), dolayisiyla turetilemez. Bag acildiginda kolon turev degere cevrilir.

ENUM TUZAGI: `section_status` icin `ALTER TYPE ... ADD VALUE` kullanilir (spec §4)
— ucuz ve mevcut satirlara dokunmaz, ama GERI ALINAMAZ. Bu yuzden `downgrade`
tipi YENIDEN YARATIR: yeni tip -> kolonu tasi -> eski tipi `DROP TYPE`. `DROP TYPE`
unutulursa ikinci `upgrade` "type already exists" ile patlar.
Ayni tuzak `section_type` icin de gecerlidir: `ENUM` tipi kolonla birlikte
SILINMEZ, `downgrade` onu acikca dusurur.

Downgrade'de ONCE `on_hold` satirlari `planned`'a dusurulur, SONRA tip degistirilir
— sira ters olursa `USING` cevrimi gecersiz deger yuzunden patlar
(`f1b2c3d4e5a6` dersi).

GERI ALMA NOTU: `downgrade` 7 kolonu dusurur, dolayisiyla bu kolonlardaki degerler
KAYBOLUR. Bu bilinclidir.

Revision ID: d4e5f6a7b8c9
Revises: f2a3b4c5d6e7
Create Date: 2026-08-02 10:00:00.000000

RE-PARENT NOTU (2026-08-02): Bu revizyon once `c3d4e5f6a7b8`ye bagliydi. P8
(`f2a3b4c5d6e7`) AYNI ebeveyne baglanip ONCE merge edilip CANLIYA cikinca zincir
CATALLANDI (iki head). Ebeveyn P8e cevrildi.

Neden SART: `Dockerfile:22` -> `CMD alembic upgrade head && uvicorn ...`.
Konteyner ACILISTA migration kosar; iki head varken `upgrade head` "multiple
heads" ile CIKAR, `&&` kisa devre yapar, uvicorn HIC BASLAMAZ — canli uygulama
tamamen duser. Bu yalniz yerel bir rahatsizlik degildir.

Tablo cakismasi YOK: P6 `sections`a kolon ekler, P8 uc yeni tablo acar.

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: str | Sequence[str] | None = "f2a3b4c5d6e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Etiket sirasi spec §3 tablosundan BIREBIR: Temel & Altyapi / Kaba Insaat /
# Ince Isler / Cephe & Cati / Mekanik-Elektrik / Peyzaj / Teslimat & Kabul.
SECTION_TYPE_LABELS: tuple[str, ...] = (
    "foundation_infra",
    "structural",
    "finishing",
    "facade_roof",
    "mep",
    "landscape",
    "handover",
)

# `on_hold` `active`'ten SONRA gelir (Form 71 sirasi), yani upgrade sonrasi sira
# `planned · active · on_hold · completed`. Downgrade'de yeniden yaratilan tip:
SECTION_STATUS_OLD = ("planned", "active", "completed")

DEPUTY_FK = "fk_sections_deputy_manager_user_id"
DEPUTY_INDEX = "ix_sections_deputy_manager_user_id"

CHECKS = (
    (
        "ck_sections_planned_worker_count",
        "planned_worker_count IS NULL OR planned_worker_count >= 0",
    ),
    ("ck_sections_budget_amount", "budget_amount IS NULL OR budget_amount >= 0"),
)


def upgrade() -> None:
    # 1) Enum genislemesi. PG 12+ `ADD VALUE`'yu islem icinde kabul eder; yeni
    #    deger AYNI islemde KULLANILAMAZ — asagida kullanilmiyor.
    op.execute("ALTER TYPE section_status ADD VALUE IF NOT EXISTS 'on_hold' AFTER 'active'")

    # 2) Yeni enum tipi. `create_type=False` ile kolona baglanacagi icin ONCE
    #    acikca yaratilir; aksi halde `add_column` ikinci kez yaratmaya calisirdi.
    sa.Enum(*SECTION_TYPE_LABELS, name="section_type").create(op.get_bind(), checkfirst=False)

    op.add_column(
        "sections",
        sa.Column(
            "section_type",
            postgresql.ENUM(*SECTION_TYPE_LABELS, name="section_type", create_type=False),
            nullable=True,
        ),
    )
    op.add_column("sections", sa.Column("description", sa.Text(), nullable=True))
    op.add_column(
        "sections",
        sa.Column("deputy_manager_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "sections", sa.Column("deputy_manager_name", sa.String(length=200), nullable=True)
    )
    op.add_column("sections", sa.Column("planned_worker_count", sa.Integer(), nullable=True))
    op.add_column(
        "sections", sa.Column("budget_amount", sa.Numeric(precision=18, scale=2), nullable=True)
    )
    # Tek `NOT NULL`: sunucu varsayilani `false`, yani mevcut satirlar YAYINDA sayilir.
    op.add_column(
        "sections",
        sa.Column("is_draft", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )

    # `SET NULL` — kullanici silinse de `deputy_manager_name` anlik goruntusu KALIR.
    op.create_index(DEPUTY_INDEX, "sections", ["deputy_manager_user_id"])
    op.create_foreign_key(
        DEPUTY_FK, "sections", "users", ["deputy_manager_user_id"], ["id"], ondelete="SET NULL"
    )

    for name, condition in CHECKS:
        op.create_check_constraint(name, "sections", sa.text(condition))


def downgrade() -> None:
    for name, _condition in CHECKS:
        op.drop_constraint(name, "sections", type_="check")

    op.drop_constraint(DEPUTY_FK, "sections", type_="foreignkey")
    op.drop_index(DEPUTY_INDEX, table_name="sections")

    for column in (
        "is_draft",
        "budget_amount",
        "planned_worker_count",
        "deputy_manager_name",
        "deputy_manager_user_id",
        "description",
        "section_type",
    ):
        op.drop_column("sections", column)

    # Kolon dustu ama TIP durur — acikca dusurulur, yoksa ikinci upgrade patlar.
    sa.Enum(*SECTION_TYPE_LABELS, name="section_type").drop(op.get_bind(), checkfirst=False)

    # Enum ters takasi: ONCE veri, SONRA tip (sira tersse `USING` cevrimi patlar).
    op.execute("UPDATE sections SET status = 'planned' WHERE status = 'on_hold'")
    labels = ", ".join(f"'{label}'" for label in SECTION_STATUS_OLD)
    op.execute(f"CREATE TYPE section_status_old AS ENUM ({labels})")
    op.execute("ALTER TABLE sections ALTER COLUMN status DROP DEFAULT")
    op.execute(
        "ALTER TABLE sections ALTER COLUMN status TYPE section_status_old "
        "USING status::text::section_status_old"
    )
    op.execute("DROP TYPE section_status")
    op.execute("ALTER TYPE section_status_old RENAME TO section_status")
    op.execute("ALTER TABLE sections ALTER COLUMN status SET DEFAULT 'planned'")
