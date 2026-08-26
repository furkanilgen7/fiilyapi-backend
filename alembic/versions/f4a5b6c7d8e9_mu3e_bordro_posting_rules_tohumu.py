"""mu3e bordro posting rules tohumu

MU-3E — BORDRO ailesinin BELGE → HESAP eslemesi. MU-3B faturayi
(`c0d1e2f3a4b5`), MU-3C odemeyi (`d1e2f3a4b5c6`), MU-3D uc hakedis ailesini
(`a4b5c6d7e8f9`) tohumlamisti; bu migration MU-3 zincirinin SON ailesini ekler.

🔴 **BU MIGRATION CANLIDA ACILISTA KOSAR.** `Dockerfile` `alembic upgrade head &&
uvicorn ...` calistirir; burada patlayan bir satir `&&`yi kisa devre yaptirir ve
uvicorn HIC BASLAMAZ (tam kesinti). Bu yuzden `upgrade`de **`raise` YOKTUR**:
eksik hesap kodu WARNING duser ve migration BASARIYLA biter. Eksik eslemenin
bedeli zaten fail-closed'dir — `post_document` cozemedigi rolde **422** verir.

## 🔴 NEDEN TEK MIGRATION (MU-3D IKIYE BOLUNMUSTU)

MU-3D'de `equipment_rental_invoice` uyesi ONCE bir `ALTER TYPE ... ADD VALUE`
migration'iyla acilmak zorundaydi: Postgres'te tip daha once yaratilmissa
`ADD VALUE` + degeri KULLANMA ayni islemde HATADIR (`unsafe use of new value`)
ve bu YALNIZ CANLIDA gorulurdu.

**Burada o bolme GEREKMEZ ve gerekcesi olculdu:** `payroll_period` uyesi
`JournalSourceType`ta MU-3A'dan BERI VARDIR (tipin ILK yaratilisinda, bir
`ADD VALUE` ile DEGIL). Asagidaki INSERT degeri kullanir ama tip bu islemde
degistirilmemistir — tuzak hic ugramaz.

## 🔴 CARI HESAP (KARAR-2) BU AILEDE YOKTUR

`320`/`120` hic gecmez: personele borc `335 Personele Borclar`tir, saticiya
borc degil. ⚠️ Dolayisiyla **MU-4 mayini bu aileyi ETKILEMEZ** — `320.04`
acildiginda guncellenecek bir satir burada YOKTUR.

## KARAR-4 · GIDER `730`, `720` DEGIL

`payroll_lines`ta `project_id`/`site_id` YOKTUR (olculdu) → direkt/endirekt
iscilik ayrimi YAPILAMAZ ve `720 Direkt Iscilik Giderleri` DAYANAKSIZ olurdu.
Sema bu dilimde genisletilmez (ayri bir urun karari).

## KARAR-1 · NORMAL TICARI REJIM

`170`/`350` (yillara yaygin insaat) SECILMEDI — seed'de vardir ama OLUDUR.

## 🔴 KDV ROLU YOKTUR — ve olmamalidir

Bordro KDV TASIMAZ. `vat_input`/`vat_output` bu ailede TANIMLI DEGILDIR, yani
`post_document` onlari COZEMEZ — bordroya KDV yazmak tip/veri duzeyinde
imkansizdir, bir kod nezaketi degil. Gerekce MU-3D ile ayni: `accounting.
vat_return` beyannameyi YALNIZ `invoices`tan turetir ve MU-3B'nin kabul kapisi
"beyanname == yevmiye" kimligini kurus toleransi olmadan iddia eder.

## 🔴 K1 — VERI KOPYALANIR, UYGULAMA KODU IMPORT EDILMEZ

`payroll.posting.PAYROLL_POSTING_RULES` IMPORT EDILMEZ: uygulanmis bir
migration DONMUS olmalidir. Asagidaki `SEED_RULES` ondan satir satir birebir
kopyalanmistir; iki katmanin ayni oldugunu
`tests/modules/posting/test_mu3e_posting_rules.py` AST ile iddia eder.

## 🔴 K6 — IDEMPOTENS

`ON CONFLICT (source_type, role_key) DO NOTHING` (`uq_posting_rules_source_role`).
Kullanici bir rolu kendi hesabina yonlendirdiyse USTUNE YAZILMAZ.

## DOWNGRADE

Yalniz BU migration'in tohumladigi `(source_type, role_key)` ciftleri silinir;
kullanicinin actigi hicbir kural satirina dokunulmaz.

Elle yazilmistir (autogenerate DEGIL) — repo deseni.

Revision ID: f4a5b6c7d8e9
Revises: a4b5c6d7e8f9
Create Date: 2026-08-26

"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f4a5b6c7d8e9"
down_revision: str | Sequence[str] | None = "a4b5c6d7e8f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")

#: 🔴 DONMUS KOPYA — `payroll.posting.PAYROLL_POSTING_RULES` ile birebir ayni
#: sira ve icerik: `source_type -> ((rol, hesap kodu), ...)`.
SEED_RULES: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    (
        "payroll_period",
        (
            ("personnel_expense", "730"),
            ("personnel_payable", "335"),
            ("tax_payable", "360"),
            ("social_security_payable", "361"),
        ),
    ),
)


def upgrade() -> None:
    bind = op.get_bind()

    for source_type, kurallar in SEED_RULES:
        # 🔴 `INSERT ... SELECT`: `account_id` kodun ALT SORGUSUNDAN gelir.
        #    Hesabi bulunmayan rol icin SATIR URETILMEZ (ve `raise` EDILMEZ).
        #    🔴 `CAST(:param AS tip)` — `:param::tip` yazimi SQLAlchemy'de bind
        #    parametresi olarak RENDER EDILMEZ ve asyncpg'ye literal `:param` gider.
        bind.execute(
            sa.text(
                "INSERT INTO posting_rules (id, source_type, role_key, account_id) "
                "SELECT gen_random_uuid(), CAST(:source_type AS journal_source_type), "
                "       kural.role_key, hesap.id "
                "FROM   (SELECT unnest(CAST(:roles AS text[]))  AS role_key, "
                "               unnest(CAST(:codes AS text[]))  AS code) AS kural "
                "JOIN   chart_of_accounts hesap ON hesap.code = kural.code "
                "ON CONFLICT (source_type, role_key) DO NOTHING"
            ),
            {
                "source_type": source_type,
                "roles": [rol for rol, _kod in kurallar],
                "codes": [kod for _rol, kod in kurallar],
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
                {"roles": [rol for rol, _kod in kurallar], "source_type": source_type},
            )
            .scalars()
            .all()
        )
        if eksik:
            logger.warning(
                "MU-3E: `%s` eslemesi EKSIK kuruldu — hesap plani kodu bulunamayan "
                "roller: %s. `post_document` bu rollerde 422 verir ve fisi YARIM "
                "YAZMAZ; bunun canlidaki bedeli, BORDRO ONAY UCUNUN 422 vermesi ve "
                "donemin ONAYLANAMAMASIDIR. Eksik hesaplar acilip kurallar elle "
                "eklenmelidir.",
                source_type,
                ", ".join(sorted(eksik)),
            )


def downgrade() -> None:
    bind = op.get_bind()
    for source_type, kurallar in reversed(SEED_RULES):
        bind.execute(
            sa.text(
                "DELETE FROM posting_rules "
                "WHERE source_type = CAST(:source_type AS journal_source_type) "
                "  AND role_key = ANY(CAST(:roles AS text[]))"
            ),
            {"source_type": source_type, "roles": [rol for rol, _kod in kurallar]},
        )
