"""odm1 cek kaynak uyesi

ODM-1 — `journal_source_type` enum'una **`financial_instrument`** uyesi.

MU-3C bu uyeyi BILEREK acmamisti: o gun nakdin tek tanimi `Σ payments`ti ve
cek portfoyu o formule terim KATMIYORDU, dolayisiyla bir cek fisi yevmiyeden
tureyen nakdi Hazine'nin kendi bakiyesinden AYIRIRDI. Ayni bolum dogrusunun
`101`/`103` ara hesaplari oldugunu ve bunun **bir URUN KARARI** oldugunu da
yaziyordu. ODM-1 o karardir: nakit tanimi `treasury/balance.py`de suzgec
kazanir (bagli odeme yalniz `collected`/`paid` iken nakit sayilir) ve ayrisma
YAPISAL OLARAK kapanir.

Yeni tablo/kolon YOKTUR — tek degisiklik enum uyesidir.

## 🔴 NEDEN AYRI BIR MIGRATION (OLCULDU — MU-3D emsali `b7c8d9e0f1a2`)

`alembic/env.py` `transaction_per_migration=True`dir. Postgres kapsami:

  * `CREATE TYPE` + `ADD VALUE` + yeni degeri KULLANMA **ayni islemde** → SERBEST,
  * tip DAHA ONCE yaratilmissa `ADD VALUE` + KULLANMA ayni islemde → **HATA**
    (`unsafe use of new value "..." of enum type ...`).

`journal_source_type` cok daha once (`a2d6b11efdcf`, MU-3A) BASKA bir islemde
yaratilmistir. Bu yuzden `posting_rules` tohumu — ki `INSERT`inde
`CAST('financial_instrument' AS journal_source_type)` yazar, yani degeri
KULLANIR — bu migration'a KONULAMAZ ve BIR SONRAKI revizyondadir
(`a6b7c8d9e0f1`). Ikisi birlestirilseydi canli acilis `alembic upgrade head &&
uvicorn` zincirinde PATLAR ve uygulama HIC ACILMAZDI.

`IF NOT EXISTS`: yarim kalmis bir turdan sonra tekrar kosulmayi guvenli kilar.
Deger SONA eklenir; `enum_range` sirasi migration testinde KILITLIDIR ve
`JournalSourceType` sinifindaki uye sirasiyla eslesir.

## DOWNGRADE — tip BASTAN KURULUR

🔴 Postgres bir enum'dan uye SILEMEZ. Bu yuzden `downgrade` uyeyi "dusurmez",
tipi ESKI uye kumesiyle BASTAN KURAR (MT-1 `c8d9e0f1a2b3` / MU-3D
`b7c8d9e0f1a2` emsali). Once VERI KAPISI kosar: uyeyi tasiyan bir fis ya da
kural varken geri donus IMKANSIZDIR.

🔴 Downgrade ELLE kosulur, acilis yolunda DEGILDIR — orada `raise` DOGRUDUR.

🔴 `journal_source_type` IKI kolonda birden kullanilir (`journal_entries.
source_type` ve `posting_rules.source_type`); ikisi de tipe cevrilmelidir,
yoksa `DROP TYPE` "hala kullaniliyor" ile patlar.

Elle yazilmistir (autogenerate DEGIL) — repo deseni.

Revision ID: f5a6b7c8d9e0
Revises: f4a5b6c7d8e9
Create Date: 2026-08-27

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f5a6b7c8d9e0"
down_revision: str | Sequence[str] | None = "f4a5b6c7d8e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENUM_NAME = "journal_source_type"
NEW_MEMBER = "financial_instrument"

#: 🔴 DOWNGRADE'in yeniden kuracagi tip — ODM-1 ONCESI uye kumesi, SIRASIYLA.
PREVIOUS_MEMBERS: tuple[str, ...] = (
    "invoice",
    "payment",
    "payroll_period",
    "progress_payment",
    "subcontractor_progress_payment",
    "equipment_rental_invoice",
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
                "deger YOKTUR. Once cek/senet fisleri stornolanip kayitlari elle "
                "karara baglanmalidir — otomatik donusum o fisleri baska bir "
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
