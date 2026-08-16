"""mt1 ozkaynak kontra

MT-1 T2 — `chart_account_type` enum'una **`equity`** uyesi + `chart_of_accounts`
tablosuna **`is_contra`** kolonu.

🔑 **KULLANICI KARARI (2026-08-16, MT-1/KK-1 — TAM TDHP UYUMU).** MU-1
`accounting/models.py` *"Besinci uye ICAT EDILMEZ"* ve *"`is_contra` kolonu
ACILMAZ"* kanonlarini yazmisti; bu migration ikisini de **bilincli olarak**
iptal eder. Gerekce olculmustur:

  * Bilanco'nun `III. OZKAYNAKLAR` bolumu (BL:80-84 — `Sermaye` ·
    `Gecmis Yillar Karlari` · `Donem Net Kari`) dort uyeli enum'la ifade
    edilemiyor. `500 Sermaye` `liability` sayilsaydi hesap plani ekraninda
    `Pasif` rozeti basar ve bilanco onu `I. KISA VADELI YUKUMLULUKLER`den
    ayiramazdi.
  * `Maddi Duran Varliklar (net)` kalemi (BL:57) `257 Birikmis Amortismanlar
    (-)`i FIILEN DUSMEK zorunda: 2.400.000 + 1.840.000 − 620.000 = 3.620.000.
    `(-)` son eki bir SUNUM kurali olarak kalsaydi sunucu netlemeyi hic
    yapamazdi.

🔴 `balance.SIGN` sozlugune `equity: -1` girisi AYNI DILIMDE eklendi.
`sign_case()`in `else_` dali BILEREK yoktur — eksik uye **NULL** uretir ve
bakiye alani `None` olarak Pydantic'e gider
(`test_sign_case_SIGN_girisi_silininde_NULL_uretir` bunu FIILEN kurar).

🔴 **`ALTER TYPE … ADD VALUE` GERI ALINAMAZ.** Postgres bir enum'dan deger
SILEMEZ. Bu yuzden `downgrade()` tipi bastan KURAR (dort uyeli hale): yeni tip
yaratilir, kolon `USING` ile ona cevrilir, eski tip dusurulur. Yapilmazsa
ikinci `upgrade` "enum label already exists" ile patlar ve bu **YALNIZ CANLIDA**
gorulur — `Dockerfile:22` acilista `alembic upgrade head && uvicorn …` kosar,
patlarsa `&&` kisa devre yapar ve uvicorn HIC BASLAMAZ (**tam kesinti**).
Emsal: `d4e5f6a7b8c9` dersi, `c7d8e9f0a1b2` (MU-2) enum dusurmesi.

🔴 **DOWNGRADE VERI KAYBETMEZ, DURUR.** `equity` tasiyan satir varsa donusum
imkansizdir; sessizce `liability`ye cevirmek hesap planinda yanlis rozet basar
ve bilanconun `III. OZKAYNAKLAR` bolumunu `I. KISA VADELI`ye tasirdi — para
tablosu YALAN soylerdi. Migration bu yuzden acik bir hatayla durur.

`ALTER TYPE … ADD VALUE` PG 12+'da islem blogu icinde YASALDIR (yeni deger AYNI
islemde KULLANILMADIGI surece). Yerel PG 18 / CI PG 16'nin ikisi de >= 12; bu
migration yeni degeri kullanmaz, yalnizca ekler.

`ALTER TABLE … ALTER COLUMN … TYPE` bagimli indeksi (`ix_chart_of_accounts_
account_type`) Postgres'in KENDISI yeniden kurar; elle drop/create GEREKMEZ.

Elle yazilmistir (autogenerate DEGIL) — repo deseni.

Revision ID: c8d9e0f1a2b3
Revises: c7d8e9f0a1b2
Create Date: 2026-08-16

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c8d9e0f1a2b3"
down_revision: str | Sequence[str] | None = "c7d8e9f0a1b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENUM_NAME = "chart_account_type"
NEW_MEMBER = "equity"

#: Downgrade'in geri donecegi MU-1 kumesi — SIRA KORUNUR, `enum_range` onu doner.
LEGACY_LABELS = ("asset", "liability", "revenue", "expense")


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Enum'a besinci uye. `IF NOT EXISTS` yarim kalmis bir turdan sonra
    #    tekrar kosulmayi guvenli kilar; deger SONA eklenir ve `enum_range`
    #    sirasi migration testinde kilitlidir.
    op.execute(f"ALTER TYPE {ENUM_NAME} ADD VALUE IF NOT EXISTS '{NEW_MEMBER}'")

    # 2. Kontra bayragi. 🔴 `server_default` SART: kolon NOT NULL dogar ve
    #    mevcut satirlarin hepsi `false` olur (hicbir hesap kendiliginden
    #    kontra DEGILDIR). Sunucu varsayilani olmadan ORM disi her yazma yolu
    #    (elle SQL, data-fix) NOT NULL ihlali alirdi.
    op.add_column(
        "chart_of_accounts",
        sa.Column(
            "is_contra",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()

    # 🔴 VERI KAPISI — `equity` tasiyan satir varken geri donus IMKANSIZDIR.
    #    Sessiz bir donusum (ör. `liability`) mali tabloyu yalanci yapar.
    kalan = bind.execute(
        sa.text(f"SELECT count(*) FROM chart_of_accounts WHERE account_type::text = '{NEW_MEMBER}'")
    ).scalar_one()
    if kalan:
        raise RuntimeError(
            f"downgrade durduruldu: {kalan} hesap '{NEW_MEMBER}' turunde. "
            "Once bu hesaplarin turu elle duzeltilmelidir — otomatik donusum "
            "bilancoyu sessizce bozardi."
        )

    op.drop_column("chart_of_accounts", "is_contra")

    # 🔴 ENUM YENIDEN KURULUR: Postgres bir enum'dan uye SILEMEZ, tip bastan
    #    yaratilir. Sira: eski tipi kenara al → yeni tipi kur → kolonu cevir →
    #    eskisini dusur. Bu adim atlanirsa ikinci `upgrade` "already exists"
    #    ile patlar ve yalniz CANLIDA gorulur.
    etiketler = ", ".join(f"'{etiket}'" for etiket in LEGACY_LABELS)
    op.execute(f"ALTER TYPE {ENUM_NAME} RENAME TO {ENUM_NAME}_mt1_old")
    op.execute(f"CREATE TYPE {ENUM_NAME} AS ENUM ({etiketler})")
    op.execute(
        "ALTER TABLE chart_of_accounts "
        f"ALTER COLUMN account_type TYPE {ENUM_NAME} "
        f"USING account_type::text::{ENUM_NAME}"
    )
    op.execute(f"DROP TYPE {ENUM_NAME}_mt1_old")
