"""P3.1 — `unit_kind` enum genislemesi (izole revizyon)

`unit_kind` enum'una `office`, `warehouse`, `parking` eklenir (UE 74: Daire ·
Dukkan/Ticari · Ofis · Depo · Otopark, spec §4.3). `ALTER TYPE ... ADD VALUE`
ayni islem icinde kullanilamadigi ve GERI ALINAMADIGI icin tip TAKAS edilir;
`f1b2c3d4e5a6` deseni birebir uygulanir. Mevcut satirlarin hicbiri degismez.

Bu revizyonda BASKA HICBIR SEY yoktur — yedi yeni enum tipi ve 21 kolonluk sema
genislemesi ayri revizyonlardadir (`d1a2b3c4e5f6` dersi: enum takasi izole edilir).
Takas `units` tablosunu yeniden yazar (kilit penceresi), bu da tek basina
kosmasinin bir sebebidir (spec §10.4).

GERI ALMA NOTU: `downgrade`, `office` / `warehouse` / `parking` degerini tasiyan
unite VARSA `USING` cevriminde basarisiz olur. Bu BILINCLIDIR — sessiz veri kaybi
yerine hata verilir; bu uniteler once baska bir turu donusturulmelidir.

Revision ID: c1d2e3f4a5b6
Revises: d2a32dcae735
Create Date: 2026-07-31 10:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c1d2e3f4a5b6"
down_revision: str | Sequence[str] | None = "d2a32dcae735"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_LABELS = "'apartment', 'shop', 'office', 'warehouse', 'parking'"
_OLD_LABELS = "'apartment', 'shop'"


def upgrade() -> None:
    """Uc yeni degeri iceren tipe takas et (spec §4.3)."""
    op.execute(f"CREATE TYPE unit_kind_new AS ENUM ({_NEW_LABELS})")
    op.execute(
        "ALTER TABLE units ALTER COLUMN unit_kind TYPE unit_kind_new "
        "USING unit_kind::text::unit_kind_new"
    )
    op.execute("DROP TYPE unit_kind")
    op.execute("ALTER TYPE unit_kind_new RENAME TO unit_kind")


def downgrade() -> None:
    """Ters takas. Yeni degerleri tasiyan satir varsa `USING` cevrimi PATLAR (bilincli)."""
    op.execute(f"CREATE TYPE unit_kind_old AS ENUM ({_OLD_LABELS})")
    op.execute(
        "ALTER TABLE units ALTER COLUMN unit_kind TYPE unit_kind_old "
        "USING unit_kind::text::unit_kind_old"
    )
    op.execute("DROP TYPE unit_kind")
    op.execute("ALTER TYPE unit_kind_old RENAME TO unit_kind")
