"""st merkez depo adi kismi tekil indeks

Kayit 193. `uq_warehouses_site_name` Postgres'in varsayilan `NULLS DISTINCT`
semantigi yuzunden MERKEZ dalinda (`site_id IS NULL`) FIILEN ISLEMEZ: coklu
NULL birbirinden farkli sayilir, dolayisiyla iki merkez depo AYNI adi
tasiyabilir.

Bu bosluk ST T1'de BILEREK kapsam disi birakilmis ve `models.py` ile
`guards.py` docstring'lerine "BILINEN SINIR" diye YAZILMISTI; merkez dalindaki
tekillik tamamen servis korkuluguna (`service._assert_warehouse_name_free`)
birakilmisti.

🔴 Korkuluk TEK KATMANDIR: iki es zamanli istek ikisi de "ad bos" okur ve
   ikisi de yazar. KARDES DAL (santiyeli depo) bu yarista DB tarafindan
   korunurken merkez dali korunmuyordu — asimetri kusurun kendisidir.

Cozum KISMI TEKIL INDEKStir; deponun `customers.national_id` ve
`subcontractor_progress_payments.slug` icin zaten kullandigi desen.
Servis korkulugu KALKMAZ: kullaniciya anlamli 409 metnini o uretir
(`DUPLICATE_WAREHOUSE_NAME`), DB ikinci katmandir (`IntegrityError` -> 409).

## 🔴 CANLIDA MEVCUT CIFT KAYIT OLABILIR

Indeks `CREATE UNIQUE INDEX` ile acilir ve canlida ayni adli iki merkez depo
VARSA migration PATLAR. Bu BILINCLIDIR ve sessiz bir birlestirmeye tercih
edilmistir: hangi deponun kalacagi ve hareketlerinin nereye tasinacagi bir VERI
karari olup migration'in verebilecegi bir karar DEGILDIR. Patlarsa operator
cakisan kayitlari elle ayirir ve migration yeniden kosulur.

⚠️ `document_folders` AYNI bosluga sahiptir (models.py docstring'i de bunu
   soyler) ve bu migration'da DOKUNULMAMISTIR — ayri bir dilimin isidir.

Revision ID: a1b2c3d4e5f7
Revises: f3a7c9e1d5b2
"""

import sqlalchemy as sa

from alembic import op

revision = "a1b2c3d4e5f7"
down_revision = "f3a7c9e1d5b2"
branch_labels = None
depends_on = None

INDEX_NAME = "uq_warehouses_central_name"


def upgrade() -> None:
    op.create_index(
        INDEX_NAME,
        "warehouses",
        ["name"],
        unique=True,
        postgresql_where=sa.text("site_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="warehouses")
