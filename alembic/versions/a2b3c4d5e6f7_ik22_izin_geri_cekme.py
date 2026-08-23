"""ik22 izin geri cekme

İK-2.2 — `leave_status` enum'una **`withdrawn`** uyesi. Kullanici karari
(2026-08-22): self izin kullanicisi KENDI bekleyen talebini GERI CEKEBILMELI.
Secilen yol SILME DEGIL **durum gecisidir** (`pending -> withdrawn`): denetim izi
kalir, izin istatistigi bozulmaz ve DELETE'in yetki kapisi GEVSETILMEZ.

Yeni tablo/kolon YOKTUR — tek degisiklik enum uyesidir.

## 🔴 `ALTER TYPE … ADD VALUE` + `transaction_per_migration=True` (OLCULDU)

`alembic/env.py:121` `transaction_per_migration=True`dir ve bu migration bunu
DEGISTIRMEZ. Sonuc: bu migration KENDI islemindedir ve `leave_status` tipi cok
daha once (`b2c3d4e5f6a7`) BASKA bir islemde yaratilmistir.

Postgres 17 gevsemesinin kapsami YEREL PG 18.4'te birebir olculdu:

  * `CREATE TYPE` + `ADD VALUE` + yeni degeri KULLANMA **ayni islemde** → SERBEST,
  * tip DAHA ONCE yaratilmissa `ADD VALUE` + KULLANMA ayni islemde → **HATA**
    (`unsafe use of new value "withdrawn" of enum type ...`).

Yani bu migration `withdrawn` degerini KULLANAMAZ (backfill/UPDATE YOK) ve bu
kisit YEREL PG 18'de DE gecerlidir — kusur CI'daki PG 16'ya birakilmaz, yerel
tur da yakalar. Migration zaten yalnizca uye EKLER.

`IF NOT EXISTS`: yarim kalmis bir turdan sonra tekrar kosulmayi guvenli kilar.
Deger SONA eklenir; `enum_range` sirasi migration testinde kilitlidir ve
`LeaveStatus` enum siniftaki uye sirasiyla eslesir.

## 🔴 DOWNGRADE — `server_default` TUZAGI (OLCULDU, MT-1 deseni AYNEN YETMEZ)

Postgres bir enum'dan uye SILEMEZ; tip bastan kurulur (`c8d9e0f1a2b3` MT-1
emsali). AMA MT-1'in kolonunda (`chart_of_accounts.account_type`) **sunucu
varsayilani YOKTU**; burada VAR:

    leave_requests.status DEFAULT 'pending'::leave_status

`ALTER TYPE … RENAME` varsayilan ifadesini ESKI tipe bagli birakir ve ardindan
gelen `ALTER COLUMN … TYPE` su hatayla PATLAR (yerel PG 18.4'te fiilen olculdu):

    ERROR: default for column "status" cannot be cast automatically to type leave_status

Bu yuzden sira ZORUNLU olarak: `DROP DEFAULT` → tipi cevir → `SET DEFAULT`.
Atlanirsa `alembic-cycle` kapisi (`upgrade head` → `downgrade -1` → `upgrade
head`) KIRMIZI olur; kacsaydi canlida `Dockerfile:22`nin `alembic upgrade head
&& uvicorn …` zinciri kisa devre yapar ve uvicorn HIC BASLAMAZDI.

`ix_leave_requests_status` indeksini `ALTER COLUMN … TYPE` sirasinda Postgres'in
KENDISI yeniden kurar — elle drop/create GEREKMEZ.

## 🔴 DOWNGRADE VERI KAYBETMEZ, DURUR

`withdrawn` tasiyan satir varsa geri donus imkansizdir. Sessizce `pending`e
cevirmek geri cekilmis bir talebi ONAY KUYRUGUNA GERI SOKAR (İZ 46 "Bekleyen
Talep" sayaci kirlenir) ve `rejected`a cevirmek olmayan bir red karari
uydururdu. Migration bu yuzden acik bir hatayla durur.

Elle yazilmistir (autogenerate DEGIL) — repo deseni.

Revision ID: a2b3c4d5e6f7
Revises: f1a2b3c4d5e6
Create Date: 2026-08-22

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a2b3c4d5e6f7"
down_revision: str | Sequence[str] | None = "f1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENUM_NAME = "leave_status"
NEW_MEMBER = "withdrawn"

#: Downgrade'in geri donecegi İK-2 kumesi — SIRA KORUNUR, `enum_range` onu doner.
LEGACY_LABELS = ("pending", "approved", "rejected")

#: Enum'u tasiyan TEK kolon (olculdu: `grep -rn "leave_status"` → yalniz burasi).
TABLE_NAME = "leave_requests"
COLUMN_NAME = "status"
COLUMN_DEFAULT = "pending"


def upgrade() -> None:
    """Upgrade schema."""
    # 🔴 Yeni deger BU migration'da KULLANILMAZ (backfill/UPDATE YOK) — kullanilsaydi
    #    `unsafe use of new value` ile patlardi (yukaridaki olcum).
    op.execute(f"ALTER TYPE {ENUM_NAME} ADD VALUE IF NOT EXISTS '{NEW_MEMBER}'")


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()

    # 🔴 VERI KAPISI — `withdrawn` tasiyan satir varken geri donus IMKANSIZDIR.
    kalan = bind.execute(
        sa.text(f"SELECT count(*) FROM {TABLE_NAME} WHERE {COLUMN_NAME}::text = '{NEW_MEMBER}'")
    ).scalar_one()
    if kalan:
        raise RuntimeError(
            f"downgrade durduruldu: {kalan} izin talebi '{NEW_MEMBER}' durumunda. "
            "Once bu taleplerin durumu elle karara baglanmalidir — otomatik donusum "
            "geri cekilmis talebi onay kuyruguna geri sokar ya da olmayan bir red "
            "karari uydururdu."
        )

    etiketler = ", ".join(f"'{etiket}'" for etiket in LEGACY_LABELS)
    # 🔴 SIRA ZORUNLU: varsayilan ONCE dusurulur, yoksa `ALTER COLUMN … TYPE`
    #    "default for column cannot be cast automatically" ile patlar (olculdu).
    op.execute(f"ALTER TABLE {TABLE_NAME} ALTER COLUMN {COLUMN_NAME} DROP DEFAULT")
    op.execute(f"ALTER TYPE {ENUM_NAME} RENAME TO {ENUM_NAME}_ik22_old")
    op.execute(f"CREATE TYPE {ENUM_NAME} AS ENUM ({etiketler})")
    op.execute(
        f"ALTER TABLE {TABLE_NAME} "
        f"ALTER COLUMN {COLUMN_NAME} TYPE {ENUM_NAME} "
        f"USING {COLUMN_NAME}::text::{ENUM_NAME}"
    )
    op.execute(
        f"ALTER TABLE {TABLE_NAME} ALTER COLUMN {COLUMN_NAME} "
        f"SET DEFAULT '{COLUMN_DEFAULT}'::{ENUM_NAME}"
    )
    op.execute(f"DROP TYPE {ENUM_NAME}_ik22_old")
