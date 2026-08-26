"""mu3c odeme posting rules tohumu

MU-3C — odeme/tahsilat ailesinin BELGE → HESAP eslemesi. MU-3B fatura ailesini
tohumlamisti (`c0d1e2f3a4b5`); bu migration nakit bacagini ekler ve
`JournalSourceType.payment` uyesini ILK KEZ kullanilir hale getirir.

🔴 **BU MIGRATION CANLIDA ACILISTA KOSAR.** `Dockerfile` `alembic upgrade head &&
uvicorn …` calistirir; burada patlayan bir satir `&&`yi kisa devre yaptirir ve
uvicorn HIC BASLAMAZ (tam kesinti). Bu yuzden `upgrade`de **`raise` YOKTUR**:
eksik hesap kodu WARNING duser ve migration BASARIYLA biter. Eksik eslemenin
bedeli zaten fail-closed'dir — `post_document` cozemedigi rolde **422** verir ve
fisi YARIM YAZMAZ (`posting/guards.py`).

## 🔴 CIFT SAYIM YOK — bu tohumda `740`/`600` YOKTUR

Faturanin kendisi ZATEN fislenir (MU-3B). Odeme fisi carinin KAPANMASIDIR:

    B 102/100 Banka/Kasa  ·  A 120 Alicilar     (giden fatura → tahsilat)
    B 320 Saticilar       ·  A 102/100 Banka    (gelen fatura → odeme)

Gider/hasilat rolleri bu ailede TANIMLI DEGILDIR, yani `post_document` onlari
COZEMEZ — cift sayim tip/veri duzeyinde imkansizdir, bir kod nezaketi degil.

## 🔴 IKI NAKIT ROLU: `bank` (102) ve `cash` (100)

Ortak tek bir nakit rolu secilseydi `102 Bankalar` ile `100 Kasa` TEK bir kural
satirina sigmaz, kasadan yapilan her tahsilat bankaya yazilirdi — ve ikisi de
mizanda "Hazir Degerler" altinda toplandigi icin TOPLAM tutmaya devam eder,
yani kusur GORUNMEZDI. Rol secimi `BankAccount.account_type`tandir
(`treasury/posting.py::cash_role_for`).

## 🔴 `101 Alinan Cekler` / `103 Verilen Cekler` BILEREK YOKTUR

Cek/senet durum gecisleri MU-3C'de fis ATMAZ: bu urunun nakit tanimi
`treasury/balance.py`dir ve portfoyu SAYMAZ. Ara hesap acmak o tanimi
degistirmek demektir ve bir URUN KARARIDIR (gerekce `treasury/posting.py`
modul docstring'inde, olculmus uc madde).

## KARAR-2 · CARI ANA HESAP

`320` Saticilar / `120` Alicilar — MU-3B ile AYNI kodlar. Alt hesap (`320.04`)
ACILMAZ, MU-4'e kaldi. ⚠️ **MU-4 MAYINI:** `320.04` acildigi an `320`e bakan
kural `validation.leaf_blockers`tan **422** alir. MU-4 o gun BU TABLONUN
SATIRINI gunceller; kod degismez.

## 🔴 K1 — VERI KOPYALANIR, UYGULAMA KODU IMPORT EDILMEZ

`app.modules.treasury.posting.PAYMENT_POSTING_RULES` IMPORT EDILMEZ: uygulanmis
bir migration DONMUS olmalidir. Asagidaki `SEED_RULES` ondan satir satir birebir
kopyalanmistir; iki katmanin ayni oldugunu
`tests/modules/treasury/test_mu3c_posting_rules.py` AST ile iddia eder.

## 🔴 K6 — IDEMPOTENS

`ON CONFLICT (source_type, role_key) DO NOTHING` (`uq_posting_rules_source_role`).
Kullanici bir rolu kendi hesabina yonlendirdiyse USTUNE YAZILMAZ.

## DOWNGRADE

Yalniz BU migration'in tohumladigi `(payment, role_key)` ciftleri silinir;
kullanicinin actigi hicbir kural satirina dokunulmaz. `posting_rules`a giden FK
yoktur (fisler hesaba baglanir, kurala degil), bu yuzden veri kapisi GEREKMEZ.

Elle yazilmistir (autogenerate DEGIL) — repo deseni.

Revision ID: d1e2f3a4b5c6
Revises: c0d1e2f3a4b5
Create Date: 2026-08-26

"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d1e2f3a4b5c6"
down_revision: str | Sequence[str] | None = "c0d1e2f3a4b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")

SOURCE_TYPE = "payment"

#: 🔴 DONMUS KOPYA — `treasury.posting.PAYMENT_POSTING_RULES` ile birebir ayni
#: sira ve icerik: (rol, hesap kodu).
SEED_RULES: tuple[tuple[str, str], ...] = (
    ("bank", "102"),
    ("cash", "100"),
    ("payable", "320"),
    ("receivable", "120"),
)


def upgrade() -> None:
    bind = op.get_bind()

    # 🔴 `INSERT … SELECT`: `account_id` kodun ALT SORGUSUNDAN gelir. Hesabi
    #    bulunmayan rol icin SATIR URETILMEZ (ve `raise` EDILMEZ — acilis yolu).
    #    🔴 `CAST(:param AS tip)` — `:param::tip` yazimi SQLAlchemy'de bind
    #    parametresi olarak RENDER EDILMEZ ve asyncpg'ye literal `:param` gider.
    bind.execute(
        sa.text(
            "INSERT INTO posting_rules (id, source_type, role_key, account_id) "
            "SELECT gen_random_uuid(), CAST(:source_type AS journal_source_type), "
            "       kural.role_key, hesap.id "
            "FROM   (SELECT unnest(CAST(:roles AS text[]))        AS role_key, "
            "               unnest(CAST(:codes AS text[]))        AS code) AS kural "
            "JOIN   chart_of_accounts hesap ON hesap.code = kural.code "
            "ON CONFLICT (source_type, role_key) DO NOTHING"
        ),
        {
            "source_type": SOURCE_TYPE,
            "roles": [rol for rol, _kod in SEED_RULES],
            "codes": [kod for _rol, kod in SEED_RULES],
        },
    )

    # Eksik eslemeyi GURULTULU ama OLDURUCU OLMAYAN bicimde bildir.
    eksik = (
        bind.execute(
            sa.text(
                "SELECT unnest(CAST(:roles AS text[])) AS role_key "
                "EXCEPT "
                "SELECT role_key FROM posting_rules "
                "WHERE source_type = CAST(:source_type AS journal_source_type)"
            ),
            {"roles": [rol for rol, _kod in SEED_RULES], "source_type": SOURCE_TYPE},
        )
        .scalars()
        .all()
    )
    if eksik:
        logger.warning(
            "MU-3C: odeme eslemesi EKSIK kuruldu — hesap plani kodu bulunamayan "
            "roller: %s. `post_document` bu rollerde 422 verir ve fisi YARIM "
            "YAZMAZ; eksik hesaplar acilip kurallar elle eklenmelidir.",
            ", ".join(sorted(eksik)),
        )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "DELETE FROM posting_rules "
            "WHERE source_type = CAST(:source_type AS journal_source_type) "
            "  AND role_key = ANY(CAST(:roles AS text[]))"
        ),
        {"source_type": SOURCE_TYPE, "roles": [rol for rol, _kod in SEED_RULES]},
    )
