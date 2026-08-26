"""mu3d hakedis posting rules tohumu

MU-3D — UC HAKEDIS AILESININ BELGE → HESAP eslemesi. MU-3B faturayi
(`c0d1e2f3a4b5`), MU-3C odemeyi (`d1e2f3a4b5c6`) tohumlamisti; bu migration
isveren hakedisi · taseron hakedisi · makine kira hakedisi ucunu birden ekler.

🔴 **BU MIGRATION CANLIDA ACILISTA KOSAR.** `Dockerfile` `alembic upgrade head &&
uvicorn ...` calistirir; burada patlayan bir satir `&&`yi kisa devre yaptirir ve
uvicorn HIC BASLAMAZ (tam kesinti). Bu yuzden `upgrade`de **`raise` YOKTUR**:
eksik hesap kodu WARNING duser ve migration BASARIYLA biter. Eksik eslemenin
bedeli zaten fail-closed'dir — `post_document` cozemedigi rolde **422** verir.

## 🔴 NEDEN AYRI BIR MIGRATION (b7c8d9e0f1a2'den SONRA)

`equipment_rental_invoice` uyesi bir onceki revizyonda `ALTER TYPE ... ADD VALUE`
ile eklenir. Postgres'te tip DAHA ONCE yaratilmissa `ADD VALUE` + degeri
KULLANMA **ayni islemde** HATADIR (`unsafe use of new value`). Asagidaki INSERT
`CAST('equipment_rental_invoice' AS journal_source_type)` yazar, yani degeri
KULLANIR — bu yuzden ikisi AYRI migration olmak ZORUNDADIR.

## 🔴 UYE = TABLO, UYE ≠ KAVRAM

"Hakedis" TEK bir uye DEGILDIR. Uc ayri uye vardir cunku uc ayri TABLO vardir;
tek uye olsaydi `source_id` uc farkli tablonun kimligini birden tasir ve "bu
kimlik hangi tabloda?" sorusu kolonlardan CEVAPLANAMAZDI.

## 🔴 ISVEREN AILESI OTEKI IKISININ AYNASIDIR

Kullanici kararinin metni "gider + cari borc" der; bu taseron ve kira icin
DOGRU, isveren hakedisi icin TERSTIR (olculdu). `progress_payments` bizim
isverene KESTIGIMIZ hakedistir → ALACAK (`120`) + HASILAT (`600`). Roller ters
tohumlansaydi mizan her isveren hakedisinde iki KAT tutar kadar oynar ve
faturanin stornosu hicbir seyi netlemezdi.

## 🔴 KDV ROLU YOKTUR — ve olmamalidir

Hakedis fisi KDV'SIZDIR (kullanici karari 2026-08-26). `vat_input`/`vat_output`
rolleri bu uc ailede TANIMLI DEGILDIR, yani `post_document` onlari COZEMEZ —
hakedise KDV yazmak tip/veri duzeyinde imkansizdir, bir kod nezaketi degil.
Gerekce: `accounting.vat_return` beyannameyi YALNIZ `invoices`tan turetir ve
MU-3B'nin kabul kapisi "beyanname == yevmiye" kimligini kurus toleransi olmadan
iddia eder; hakedise KDV bacagi yazilsaydi bu kimlik URETIMDE sessizce bozulurdu.

## KARAR-1 · NORMAL TICARI REJIM

`170`/`350` (yillara yaygin insaat) SECILMEDI — seed'de vardir ama OLUDUR.
`740` Hizmet Uretim Maliyeti / `600` Yurt Ici Satislar kullanilir.

## KARAR-2 · CARI ANA HESAP

`320` Saticilar / `120` Alicilar — MU-3B ve MU-3C ile AYNI kodlar. Alt hesap
(`320.04`) ACILMAZ, MU-4'e kaldi. ⚠️ **MU-4 MAYINI:** `320.04` acildigi an
`320`e bakan HER kural `validation.leaf_blockers`tan **422** alir. MU-4 o gun
BU TABLONUN SATIRLARINI gunceller; kod degismez.

## 🔴 K1 — VERI KOPYALANIR, UYGULAMA KODU IMPORT EDILMEZ

Uc urun demeti (`progress_payments.posting.PROGRESS_PAYMENT_POSTING_RULES`,
`subcontractor_progress_payments.posting.SUBCONTRACTOR_POSTING_RULES`,
`equipment.rental_posting.RENTAL_POSTING_RULES`) IMPORT EDILMEZ: uygulanmis bir
migration DONMUS olmalidir. Asagidaki `SEED_RULES` onlardan satir satir birebir
kopyalanmistir; iki katmanin ayni oldugunu
`tests/modules/posting/test_mu3d_posting_rules.py` AST ile iddia eder.

## 🔴 K6 — IDEMPOTENS

`ON CONFLICT (source_type, role_key) DO NOTHING` (`uq_posting_rules_source_role`).
Kullanici bir rolu kendi hesabina yonlendirdiyse USTUNE YAZILMAZ.

## DOWNGRADE

Yalniz BU migration'in tohumladigi `(source_type, role_key)` ciftleri silinir;
kullanicinin actigi hicbir kural satirina dokunulmaz.

Elle yazilmistir (autogenerate DEGIL) — repo deseni.

Revision ID: a4b5c6d7e8f9
Revises: b7c8d9e0f1a2
Create Date: 2026-08-26

"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a4b5c6d7e8f9"
down_revision: str | Sequence[str] | None = "b7c8d9e0f1a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")

#: 🔴 DONMUS KOPYA — uc urun demetiyle birebir ayni sira ve icerik:
#: `source_type -> ((rol, hesap kodu), ...)`.
SEED_RULES: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    ("progress_payment", (("receivable", "120"), ("revenue", "600"))),
    ("subcontractor_progress_payment", (("expense", "740"), ("payable", "320"))),
    ("equipment_rental_invoice", (("expense", "740"), ("payable", "320"))),
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
                "MU-3D: `%s` eslemesi EKSIK kuruldu — hesap plani kodu bulunamayan "
                "roller: %s. `post_document` bu rollerde 422 verir ve fisi YARIM "
                "YAZMAZ; bunun canlidaki bedeli, o ailenin ONAY UCUNUN 422 vermesi "
                "ve hakedisin ONAYLANAMAMASIDIR. Eksik hesaplar acilip kurallar "
                "elle eklenmelidir.",
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
