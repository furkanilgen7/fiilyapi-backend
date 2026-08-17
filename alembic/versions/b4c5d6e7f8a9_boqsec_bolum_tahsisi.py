"""boqsec is kalemlerinin bolumlere miktar tahsisi

BOQ-SEC — `boq_item_section_allocations` tablosu.

--------------------------------------------------------------------------
NICIN BU MIGRATION VAR
--------------------------------------------------------------------------
Kullanici: "santiyedeki bolumlere girince is kalemleri gozukmuyor." Kok bir
kusur DEGIL, kullanicinin 2026-07-30'da kendi verdigi ERTELEME kararidir
(`boq/models.py` BoqGroup docstring: "sozlesme/bolum baglari bu dilimde
ACILMAZ"). Karar 2026-08-17'de ACILDI.

--------------------------------------------------------------------------
🔴 NEDEN `boq_items.section_id` DEGIL
--------------------------------------------------------------------------
Bir poz BIRDEN COK boluma pay edilebilir (1.200 m³ betonun 400'u "Kat 6-10",
300'u "Kat 11-15", 500'u atanmamis). Tekil bir FK kolonu bunu MODELLEYEMEZ ve
migration ikinci kez acilmak zorunda kalirdi. Mockup'in
`section-form/BoqAssignmentCard.tsx:13-21`de cizdigi "Santiye Kotasi / Bu
Bolume" ikilisi tam olarak bu tahsis modelidir.

--------------------------------------------------------------------------
🔴 `section_id` CASCADE — YEDI FK'LIK EMSALDEN BILINCLI SAPMA
--------------------------------------------------------------------------
Repoda `sections.id`'yi hedefleyen yedi FK vardir ve YEDISI DE `SET NULL`
("bolum silinse de kayit ayakta kalir, bilgi alanidir"). Burada dogru olan
CASCADE'dir cunku tahsis satirinin BAGIMSIZ VARLIGI YOKTUR. Ayrica `SET NULL`
teknik olarak da imkansizdir: kolon NOT NULL'dur ve NOT NULL bir kolona SET
NULL calisma aninda FK hatasi verir; nullable yapilsaydi sahipsiz tahsis
satirlari birikir ve pozun kotasini hicbir ekranda gorunmeden bloke ederdi.
CASCADE veri kaybi DEGILDIR: poz satiri ve `quantity`si aynen durur.

--------------------------------------------------------------------------
🔴 TOPLAM INVARIANTI DB'DE DEGIL — KILITLE
--------------------------------------------------------------------------
`SUM(quantity) <= boq_items.quantity` satirlar ARASI bir kisittir, CHECK'e
sigmaz. Servis katmani poz satirini `SELECT ... FOR UPDATE` ile kilitleyip
kontrol eder (EŞİK = KİLİT). Bu tablodaki `CHECK (quantity > 0)` yalniz TEK
SATIR duzeyindeki kurali (sifir tahsis satir olarak tutulmaz) zorlar.

--------------------------------------------------------------------------
🔴 UQ DEFERRABLE INITIALLY DEFERRED
--------------------------------------------------------------------------
`site_planning`in `uq_site_plan_rows_...` deseni: DEGISTIRME (replace) ucu tek
istekte bir satiri silip baskasini onun anahtarina tasiyabilir. Anlik kontrolde
INSERT, DELETE'ten once flush edildigi icin istek haksiz yere cakisma alirdi.
Ertelenmis kontrol GERCEK cakismayi hala yakalar.

--------------------------------------------------------------------------
VERI
--------------------------------------------------------------------------
Geriye donuk doldurma YOKTUR (KK-B2, kullanici: "su ana kadar herhangi bir poz
yok"). Tablo bos kurulur; hicbir mevcut satir okunmaz ya da yazilmaz. Yine de
`boq_items` bos VARSAYIMI koda GOMULMEZ — migration mevcut satirlarin sayisina
bakmaz, davranisi veriden bagimsizdir.

`transaction_per_migration=True`'ya DOKUNULMADI; bu migration hicbir enum
yaratmaz/degistirmez, PG surum tuzagi yuzeyi yoktur.

Elle yazilmistir (autogenerate DEGIL) — repo deseni.

Revision ID: b4c5d6e7f8a9
Revises: b3c4d5e6f7a8
Create Date: 2026-08-17

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b4c5d6e7f8a9"
down_revision: str | Sequence[str] | None = "b3c4d5e6f7a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "boq_item_section_allocations"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("boq_item_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("section_id", sa.UUID(as_uuid=True), nullable=False),
        # `boq_items.quantity` ile AYNI tip — olcek farki bir invariant kacagidir.
        sa.Column("quantity", sa.Numeric(14, 3), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["boq_item_id"],
            ["boq_items.id"],
            name="fk_boq_item_section_allocations_item",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["section_id"],
            ["sections.id"],
            name="fk_boq_item_section_allocations_section",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "boq_item_id",
            "section_id",
            name="uq_boq_item_section_allocations_item_section",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.CheckConstraint("quantity > 0", name="ck_boq_item_section_allocations_qty_positive"),
    )
    op.create_index(f"ix_{TABLE}_boq_item_id", TABLE, ["boq_item_id"])
    op.create_index(f"ix_{TABLE}_section_id", TABLE, ["section_id"])


def downgrade() -> None:
    op.drop_index(f"ix_{TABLE}_section_id", table_name=TABLE)
    op.drop_index(f"ix_{TABLE}_boq_item_id", table_name=TABLE)
    op.drop_table(TABLE)
