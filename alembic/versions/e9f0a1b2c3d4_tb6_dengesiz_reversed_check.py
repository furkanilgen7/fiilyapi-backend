"""tb6 dengesiz reversed fis check

TB6 T2 — `journal_entries` denge CHECK'i `POSTING_STATUSES`in TAMAMINI kapsar.

## Kapatilan delik

`ck_journal_entries_posted_balanced` yalnizca `status <> 'posted'` diyordu. Ama
`balance.POSTING_STATUSES` = `posted` **+ `reversed`**tir ve deftere (mizan,
bilanco, gelir tablosu, nakit akisi) **ikisi de girer**. Yani **dengesiz bir
`reversed` fis DB'ye yasal olarak girebiliyordu** ve girdiginde mali tablolarin
`is_balanced` gostergesi sessizce `False` doner, denge kalici olarak kayardi.

## 🔴 MEVCUT VERI OLCUMU (uygulamadan ONCE)

Bu migration bir CHECK EKLER; ihlal eden TEK BIR SATIR varsa `ALTER TABLE`
patlar ve `Dockerfile` acilista `alembic upgrade head && uvicorn ...` kostugu
icin **uvicorn HIC BASLAMAZ (tam kesinti)**. Bu yuzden constraint eklenmeden
ONCE ihlal SAYILIR ve varsa acik bir mesajla durulur — ham bir
`CheckViolationError` yerine ne oldugu okunabilir olsun diye.

Yapisal olarak ihlal BEKLENMEZ ve gerekcesi olculmustur:

* `reversed`a giden TEK yol `state_service.perform_transition`dir ve matris
  yalnizca `posted → reversed` gecisini tanir (`transitions.py`);
* `posted` olabilmenin sarti ESKI CHECK'ti (denge) ve gecis toplamlara
  DOKUNMAZ;
* baslik toplamlari yalnizca `service.apply_totals`tan yazilir, o da yalnizca
  `draft` fise (`assert_lines_editable`).

Yani uygulama uzerinden dengesiz bir `reversed` satir URETILEMEZ; delik ancak
dogrudan SQL ile kullanilabilirdi. Sayim yine de kosar: "yapisal olarak
imkansiz" bir olcum degildir.

## Kisit ADI da degisti

`ck_journal_entries_posted_balanced` → `ck_journal_entries_posting_balanced`:
eski ad artik YALAN soyluyordu (kisit `posted`i degil, DEFTERE GIRENLERI
bagliyor). Downgrade eski adi ve eski daraligi geri getirir.

Elle yazilmistir (autogenerate DEGIL) — repo deseni.

Revision ID: e9f0a1b2c3d4
Revises: d8e9f0a1b2c3
Create Date: 2026-08-19

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e9f0a1b2c3d4"
down_revision: str | Sequence[str] | None = "d8e9f0a1b2c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "journal_entries"
OLD_NAME = "ck_journal_entries_posted_balanced"
NEW_NAME = "ck_journal_entries_posting_balanced"

#: 🔴 SQL BURAYA KOPYALANIR ve `models.POSTING_BALANCED_CHECK`ten ITHAL EDILMEZ:
#: migration gecmisi DONMUS olmalidir. Modelden okunsaydi, kume ileride
#: degistiginde bu migration GERIYE DONUK baska bir sey basar ve zincir
#: yeniden kosuldugunda farkli bir semaya varirdi. Ikisinin BUGUN esit oldugunu
#: `test_tb6_reversed_balanced_check` ayrica iddia eder.
OLD_SQL = "status <> 'posted' OR total_debit = total_credit"
NEW_SQL = "status NOT IN ('posted', 'reversed') OR total_debit = total_credit"

#: Ihlal sayimi — kisit eklenmeden once kosar (modul docstring'i).
COUNT_SQL = sa.text(
    "SELECT count(*) FROM journal_entries "
    "WHERE status IN ('posted', 'reversed') AND total_debit <> total_credit"
)


def upgrade() -> None:
    ihlal = op.get_bind().execute(COUNT_SQL).scalar_one()
    if ihlal:
        raise RuntimeError(
            f"TB6 T2: {ihlal} adet DENGESIZ deftere-giren fis var "
            "(status IN ('posted','reversed') AND total_debit <> total_credit). "
            "CHECK eklenemez — once bu satirlar duzeltilmelidir."
        )

    op.drop_constraint(OLD_NAME, TABLE, type_="check")
    op.create_check_constraint(NEW_NAME, TABLE, sa.text(NEW_SQL))


def downgrade() -> None:
    op.drop_constraint(NEW_NAME, TABLE, type_="check")
    op.create_check_constraint(OLD_NAME, TABLE, sa.text(OLD_SQL))
