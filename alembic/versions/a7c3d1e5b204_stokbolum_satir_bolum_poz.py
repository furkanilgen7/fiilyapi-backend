"""stokbolum satir bolum ve poz atfi

STOK-BOLUM T1 — `stock_entry_lines`a IKI ADDITIVE nullable FK:
`section_id` (→ `sections`) ve `boq_item_id` (→ `boq_items`).

## 🔴 ETIKET SATIR BAZINDADIR (kullanici karari 2026-08-29)

Kolonlar BASLIGA (`stock_entries`) DEGIL SATIRA konur: tek bir sarf fisi ayni
gun farkli malzemeleri farkli pozlara cikarabilir (hem `C-01` demirine hem
`B-01` kalibina). Baslikta olsaydi kullanici fisi bolmek zorunda kalirdi.

## 🔴 BAKIYE TANIMI DEGISMEZ — "STOK DEPODA DURUR, BOLUM TUKETIR"

Bolume ayri depo ACILMAZ ve `inventory/balance.py` bir satir bile degismez.
Bu iki kolon bir ATIF/KIRILIM alanidir, bakiyenin BOYUTU degildir. Bakiye
depo duzeyinde kalir; bolum kirilimi ayri bir uctan (`GET /sections/{id}/stock`)
turetilir.

## 🔴 IKISI DE NULLABLE — ve bu ZORUNLU

Merkez depoya alim, depolar arasi transfer ve sayim duzeltmesi gibi
hareketlerin bolumu YOKTUR. Zorunlu yapmak canlidaki tum mevcut akislari
422'ye dusururdu ve geriye donuk 6 canli hareketi yazilamaz kilardi.

## `ON DELETE` deseni `site_diary_lines`tan OLCULDU

* `boq_item_id` → **SET NULL**: `site_diary_lines.boq_item_id` ile BIREBIR —
  poz dusurulse de o gunun/hareketin kaydi ayakta kalir. CASCADE bir poz
  silindiginde STOK HAREKETI SATIRINI silerdi, yani bakiyeyi degistirirdi.
  🔴 Bu, bakiyenin bir BOQ kaydina bagli olarak yok olmasi demek olurdu.
* `section_id` → **SET NULL**: `sections.id`yi hedefleyen FK'larda olculen
  ayrim "bilgi bagi olan kayitlar SET NULL, bolumun BIR PARCASI olan kayitlar
  CASCADE"dir (`boq_item_section_allocations` docstring'i). Stok hareketi
  satiri bolumun bir parcasi DEGILDIR — bolum silinse de malzeme cikisi
  olmustur ve bakiyeye girmistir.

## `NOT VALID` / sayim deseni BURADA GEREKMEZ — olculdu

`NOT VALID` yalniz `CHECK`/`FK` icindir ve MEVCUT satirlarin ihlal edebilecegi
bir kisit varsa anlamlidir. Burada iki kolon da YENI acilir ve tum mevcut
satirlarda NULL'dur; FK NULL satiri hic denetlemez. Yani ihlal kumesi
YAPISAL OLARAK BOSTUR, sayilacak bir sey yoktur. (`stock_entries.
purchase_order_id` emsali, `f3a4b5c6d7e8` §7 — o da sayimsiz eklendi.)

Elle yazilmistir (autogenerate DEGIL) — repo deseni.

Revision ID: a7c3d1e5b204
Revises: ca19424d7118
Create Date: 2026-08-29

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a7c3d1e5b204"
down_revision: str | Sequence[str] | None = "ca19424d7118"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("stock_entry_lines", sa.Column("section_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_stock_entry_lines_section_id",
        "stock_entry_lines",
        "sections",
        ["section_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_stock_entry_lines_section_id", "stock_entry_lines", ["section_id"])

    op.add_column("stock_entry_lines", sa.Column("boq_item_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_stock_entry_lines_boq_item_id",
        "stock_entry_lines",
        "boq_items",
        ["boq_item_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_stock_entry_lines_boq_item_id", "stock_entry_lines", ["boq_item_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_stock_entry_lines_boq_item_id", table_name="stock_entry_lines")
    op.drop_constraint("fk_stock_entry_lines_boq_item_id", "stock_entry_lines", type_="foreignkey")
    op.drop_column("stock_entry_lines", "boq_item_id")

    op.drop_index("ix_stock_entry_lines_section_id", table_name="stock_entry_lines")
    op.drop_constraint("fk_stock_entry_lines_section_id", "stock_entry_lines", type_="foreignkey")
    op.drop_column("stock_entry_lines", "section_id")
