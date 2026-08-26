"""mu3b fatura posting rules tohumu

MU-3B — fatura ailesinin BELGE → HESAP eslemesi. MU-3A `posting_rules` tablosunu
acti ama BILEREK HICBIR SATIR TOHUMLAMADI (hicbir kodun okumadigi olu veri
uretirdi); bu migration onu dolduran ILK koddur.

🔴 **BU MIGRATION CANLIDA ACILISTA KOSAR.** `Dockerfile` `alembic upgrade head &&
uvicorn …` calistirir; burada patlayan bir satir `&&`yi kisa devre yaptirir ve
uvicorn HIC BASLAMAZ (tam kesinti). Bu yuzden `upgrade`de **`raise` YOKTUR**:
eksik hesap kodu WARNING duser ve migration BASARIYLA biter. Eksik eslemenin
bedeli zaten fail-closed'dir — `post_document` cozemedigi rolde **422** verir ve
fisi YARIM YAZMAZ (`posting/guards.py`).

## 🔴 KARAR-1 ve KARAR-2 TAM OLARAK BU SATIRLARDA YASAR

* **KARAR-1 · NORMAL TICARI REJIM** — `740` Hizmet Uretim Maliyeti / `600` Yurt
  Ici Satislar. Yillara yaygin rejim (`170`/`350`) SECILMEDI; o hesaplar TDHP
  tohumunda VARDIR ama bu karar altinda OLU HESAPTIR ve hicbir kural onlari
  gostermez.
* **KARAR-2 · CARI ANA HESAP** — `320` Saticilar / `120` Alicilar. Alt hesap
  (`320.04`) ACILMAZ, MU-4'e kaldi. ⚠️ `Ekran 8` mockup'i `120.01`/`320.04`
  cizer; bu KULLANICI TARAFINDAN ONAYLANMIS mockup sapmasidir.

⚠️ **MU-4 MAYINI:** `320.04` acildigi an `320`e bakan kural
`validation.leaf_blockers`tan **422** alir (yaprak hesap kurali). Istenen budur —
sessizce cift sayan bir mizan yerine gurultulu bir durma. MU-4 o gun BU TABLONUN
SATIRINI gunceller; kod degismez, migration'a gerek yoktur.

## Roller neden YONE gore ayrisir

`posting_rules`in anahtari `(source_type, role_key)`dir ve iki fatura YONU AYNI
`source_type`i (`invoice`) paylasir — cunku uye = TABLO ve ikisi de `invoices`
satiridir. Ortak bir `counterparty` rolu secilseydi giden faturanin `120`si ile
gelen faturanin `320`si TEK bir kural satirina sigmaz, biri otekini ezerdi.

## 🔴 K1 — VERI KOPYALANIR, UYGULAMA KODU IMPORT EDILMEZ

`app.modules.invoicing.posting.INVOICE_POSTING_RULES` IMPORT EDILMEZ: uygulanmis
bir migration DONMUS olmalidir, uygulama kodu zamanla degisir (`e5f6a7b8c9d0` K1
emsali). Asagidaki `SEED_RULES` ondan satir satir birebir kopyalanmistir; iki
katmanin ayni oldugunu `tests/modules/invoicing/test_mu3b_posting_rules.py`
iddia eder.

## 🔴 K6 — IDEMPOTENS

`ON CONFLICT (source_type, role_key) DO NOTHING` (`uq_posting_rules_source_role`).
Kullanici bir rolu kendi hesabina yonlendirdiyse USTUNE YAZILMAZ; `DO UPDATE`
yazilsaydi duzeltme her deploy'da varsayilana donerdi. Ayrica yarim kalmis bir
deploy'dan sonra ikinci `upgrade` PATLAMAZ — bu yalniz canlida hayat kurtarir.

`account_id` bir ALT SORGUDAN (`chart_of_accounts.code`) gelir: kodlar TDHP
tohumunda (`e5f6a7b8c9d0`) UNIQUE'tir ama `id`leri O migration `uuid4` ile
uretmistir, yani buraya sabit olarak yazilamaz.

## DOWNGRADE

Yalniz BU migration'in tohumladigi `(source_type, role_key)` ciftleri silinir;
kullanicinin actigi hicbir kural satirina dokunulmaz. `posting_rules`a giden FK
yoktur (fisler hesaba baglanir, kurala degil), bu yuzden veri kapisi GEREKMEZ.

Elle yazilmistir (autogenerate DEGIL) — repo deseni.

Revision ID: c0d1e2f3a4b5
Revises: b9c0d1e2f3a4
Create Date: 2026-08-26

"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c0d1e2f3a4b5"
down_revision: str | Sequence[str] | None = "b9c0d1e2f3a4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")

SOURCE_TYPE = "invoice"

#: 🔴 DONMUS KOPYA — `invoicing.posting.INVOICE_POSTING_RULES` ile birebir ayni
#: sira ve icerik: (rol, hesap kodu).
SEED_RULES: tuple[tuple[str, str], ...] = (
    ("expense", "740"),
    ("payable", "320"),
    ("receivable", "120"),
    ("revenue", "600"),
    ("vat_input", "191"),
    ("vat_output", "391"),
    ("withholding_payable", "360"),
    ("withholding_receivable", "136"),
)


def upgrade() -> None:
    bind = op.get_bind()

    # 🔴 `INSERT … SELECT`: `account_id` kodun ALT SORGUSUNDAN gelir. Hesabi
    #    bulunmayan rol icin SATIR URETILMEZ (ve `raise` EDILMEZ — acilis yolu).
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
            "MU-3B: fatura eslemesi EKSIK kuruldu — hesap plani kodu bulunamayan "
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
