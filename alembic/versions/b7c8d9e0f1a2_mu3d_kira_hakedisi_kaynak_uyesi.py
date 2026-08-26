"""mu3d kira hakedisi kaynak uyesi

MU-3D — `journal_source_type` enum'una **`equipment_rental_invoice`** uyesi.

MU-3A bu uyeyi BILEREK acmamisti ("uye ICAT EDILMEZ, fislendigi dilimde
`ALTER TYPE` ile eklenir"); fislendigi dilim budur.

Yeni tablo/kolon YOKTUR — tek degisiklik enum uyesidir. Oteki iki hakedis
ailesi (`progress_payment` / `subcontractor_progress_payment`) MU-3A'nin
`CREATE TYPE`inda ZATEN vardir ve burada TEKRAR EKLENMEZ.

## 🔴 NEDEN AYRI BIR MIGRATION (OLCULDU — IK-2.2 emsali `a2b3c4d5e6f7`)

`alembic/env.py` `transaction_per_migration=True`dir. Postgres 17 gevsemesinin
kapsami olculdu:

  * `CREATE TYPE` + `ADD VALUE` + yeni degeri KULLANMA **ayni islemde** → SERBEST,
  * tip DAHA ONCE yaratilmissa `ADD VALUE` + KULLANMA ayni islemde → **HATA**
    (`unsafe use of new value "..." of enum type ...`).

`journal_source_type` cok daha once (`a2d6b11efdcf`, MU-3A) BASKA bir islemde
yaratilmistir. Bu yuzden `posting_rules` tohumu — ki `INSERT`inde
`CAST('equipment_rental_invoice' AS journal_source_type)` yazar, yani degeri
KULLANIR — bu migration'a KONULAMAZ ve BIR SONRAKI revizyondadir
(`a4b5c6d7e8f9`). Ikisi birlestirilseydi canli acilis `alembic upgrade head &&
uvicorn` zincirinde PATLAR ve uygulama HIC ACILMAZDI.

Bu kisit YEREL PG 18'de DE gecerlidir — kusur CI'daki PG 16'ya birakilmaz.

`IF NOT EXISTS`: yarim kalmis bir turdan sonra tekrar kosulmayi guvenli kilar.
Deger SONA eklenir; `enum_range` sirasi migration testinde KILITLIDIR ve
`JournalSourceType` sinifindaki uye sirasiyla eslesir.

## DOWNGRADE — tip BASTAN KURULUR

Postgres bir enum'dan uye SILEMEZ (MT-1 `c8d9e0f1a2b3` emsali). Once VERI
KAPISI kosar: uyeyi tasiyan bir fis ya da kural varken geri donus IMKANSIZDIR.

🔴 Downgrade ELLE kosulur, acilis yolunda DEGILDIR — orada `raise` DOGRUDUR.

🔴 `journal_source_type` IKI kolonda birden kullanilir (`journal_entries.
source_type` ve `posting_rules.source_type`); ikisi de tipe cevrilmelidir,
yoksa `DROP TYPE` "hala kullaniliyor" ile patlar. Ikisinde de SUNUCU
VARSAYILANI YOKTUR (olculdu) — IK-2.2'nin `server_default` tuzagi burada YOK.

Elle yazilmistir (autogenerate DEGIL) — repo deseni.

Revision ID: b7c8d9e0f1a2
Revises: d2e3f4a5b6c7
Create Date: 2026-08-26

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7c8d9e0f1a2"
down_revision: str | Sequence[str] | None = "d2e3f4a5b6c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENUM_NAME = "journal_source_type"
NEW_MEMBER = "equipment_rental_invoice"

#: 🔴 DOWNGRADE'in yeniden kuracagi tip — MU-3D ONCESI uye kumesi, SIRASIYLA.
PREVIOUS_MEMBERS: tuple[str, ...] = (
    "invoice",
    "payment",
    "payroll_period",
    "progress_payment",
    "subcontractor_progress_payment",
)

#: `(tablo, kolon)` — tipi kullanan HER yer. Biri atlanirsa `DROP TYPE` patlar.
USING_COLUMNS: tuple[tuple[str, str], ...] = (
    ("journal_entries", "source_type"),
    ("posting_rules", "source_type"),
)


def upgrade() -> None:
    # 🔴 Yeni deger BU migration'da KULLANILMAZ (tohum bir sonraki revizyonda) —
    #    kullanilsaydi `unsafe use of new value` ile patlardi.
    op.execute(f"ALTER TYPE {ENUM_NAME} ADD VALUE IF NOT EXISTS '{NEW_MEMBER}'")


def downgrade() -> None:
    bind = op.get_bind()

    # 🔴 VERI KAPISI — uyeyi tasiyan satir varken geri donus IMKANSIZDIR.
    for tablo, kolon in USING_COLUMNS:
        kalan = bind.execute(
            sa.text(f"SELECT count(*) FROM {tablo} WHERE {kolon}::text = :uye"),
            {"uye": NEW_MEMBER},
        ).scalar_one()
        if kalan:
            raise RuntimeError(
                f"downgrade durduruldu: `{tablo}.{kolon}` icinde {kalan} satir "
                f"'{NEW_MEMBER}' degerini tasiyor. Postgres enum'dan uye SILEMEZ; "
                "tip bastan kurulacagi icin bu satirlarin donusturulecegi bir "
                "deger YOKTUR. Once kira hakedisi fisleri stornolanip kayitlari "
                "elle karara baglanmalidir — otomatik donusum o fisleri baska bir "
                "belge ailesine yazmis gibi gosterirdi."
            )

    eski = ", ".join(f"'{uye}'" for uye in PREVIOUS_MEMBERS)
    op.execute(f"ALTER TYPE {ENUM_NAME} RENAME TO {ENUM_NAME}_old")
    op.execute(f"CREATE TYPE {ENUM_NAME} AS ENUM ({eski})")
    for tablo, kolon in USING_COLUMNS:
        op.execute(
            f"ALTER TABLE {tablo} ALTER COLUMN {kolon} "
            f"TYPE {ENUM_NAME} USING {kolon}::text::{ENUM_NAME}"
        )
    op.execute(f"DROP TYPE {ENUM_NAME}_old")
