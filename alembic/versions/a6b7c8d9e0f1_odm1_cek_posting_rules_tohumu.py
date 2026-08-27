"""odm1 cek posting rules tohumu

ODM-1 — CEK/SENET ara hesaplarinin BELGE → HESAP eslemesi. IKI aileye birden
satir ekler ve ikisi de AYNI iki hesabi (`101`/`103`) gosterir:

    payment              + instrument_receivable → 101 · instrument_payable → 103
    financial_instrument   instrument_receivable → 101 · instrument_payable → 103
                         + bank → 102 · cash → 100

## 🔴 NEDEN IKI AILE

Bir cek IKI olaydan gecer ve ikisi de AYRI birer belgedir:

    (1) odeme yazilir   B 101 Alinan Cekler   ·  A 120 Alicilar   → `payment`
    (2) cek tahsil olur B 102 Bankalar        ·  A 101 Alinan Cekler
                                                              → `financial_instrument`

Ilk bacak ODEMENIN fisidir (tutar `payments.amount`, kaynak `payments.id`) ve
`payment` ailesinde YASAR: MU-3C'nin nakit bacagi bagli odemede `102`/`100`
YERINE `101`/`103`e kayar. Ikinci bacak CEKIN kendi belgesidir
(`financial_instruments.id`) ve ara hesabi KAPATIR.

Tek aileye sigdirilsaydi `uq_journal_entries_source` `(source_type, source_id)`
uzerinde tekil oldugu icin ikinci fis birinci fisin damgasina carpardi.

## 🔴 `payment` ailesinin ESKI DORT SATIRI DEGISMEZ

`102`/`100`/`320`/`120` MU-3C'nin (`d1e2f3a4b5c6`) tohumudur ve BURADA NE
GUNCELLENIR NE SILINIR. Bagsiz odeme eskisi gibi `102`/`100`e yazilir; ara
hesap YALNIZCA `payments.financial_instrument_id IS NOT NULL` iken secilir
(D1: tetikleyici BAGDIR, `method='cheque'` ETIKETI DEGIL).

## 🔴 CIFT SAYIM YOK — bu tohumda `740`/`600` YOKTUR

Gider/hasilat faturanin fisindedir (MU-3B), cari kapanisi odemenin fisindedir
(MU-3C). Cek tahsili yalnizca paranin YERINI degistirir. Sonuc hesaplari bu
ailelerde TANIMLI DEGILDIR, yani `post_document` onlari COZEMEZ — cift sayim
tip/veri duzeyinde imkansizdir, bir kod nezaketi degil.

`120`/`320` de `financial_instrument` ailesinde YOKTUR: cari ZATEN odeme
fisinde kapanmistir, burada yeniden kapatilsaydi alacak IKI KEZ kapanirdi.

## 🔴 BU MIGRATION CANLIDA ACILISTA KOSAR

`Dockerfile` `alembic upgrade head && uvicorn ...` calistirir; burada patlayan
bir satir `&&`yi kisa devre yaptirir ve uvicorn HIC BASLAMAZ (tam kesinti). Bu
yuzden `upgrade`de **`raise` YOKTUR**: eksik hesap kodu WARNING duser ve
migration BASARIYLA biter. Eksik eslemenin bedeli zaten fail-closed'dir —
`post_document` cozemedigi rolde **422** verir ve fisi YARIM YAZMAZ.

`101 Alinan Cekler` ve `103 Verilen Cekler ve Odeme Emirleri (-)` TDHP
tohumunda (`e5f6a7b8c9d0`) VARDIR — bu migration hesap ACMAZ.

## 🔴 ONCEKI REVIZYON `f5a6b7c8d9e0` OLMAK ZORUNDA

Asagidaki INSERT `CAST('financial_instrument' AS journal_source_type)` yazar,
yani enum uyesini KULLANIR. `ADD VALUE` ile ayni islemde olsaydi Postgres
`unsafe use of new value` verirdi (MU-3D `b7c8d9e0f1a2` dersi) ve bu YALNIZ
CANLIDA gorulurdu.

## 🔴 K1 — VERI KOPYALANIR, UYGULAMA KODU IMPORT EDILMEZ

`treasury.posting.PAYMENT_POSTING_RULES` ve
`treasury.instruments.posting.INSTRUMENT_POSTING_RULES` IMPORT EDILMEZ:
uygulanmis bir migration DONMUS olmalidir. Asagidaki `SEED_RULES` onlardan
satir satir birebir kopyalanmistir; iki katmanin ayni oldugunu
`tests/modules/treasury/test_mu3c_posting_rules.py` AST ile iddia eder.

## 🔴 K6 — IDEMPOTENS

`ON CONFLICT (source_type, role_key) DO NOTHING` (`uq_posting_rules_source_role`).
Kullanici bir rolu kendi hesabina yonlendirdiyse USTUNE YAZILMAZ.

## DOWNGRADE — YALNIZ EKLEDIGINI GERI ALIR

`payment` ailesinde SADECE `instrument_receivable`/`instrument_payable`
silinir; MU-3C'nin dort satirina ve MU-3B'nin fatura eslemesine DOKUNULMAZ.
Kapisiz bir `DELETE FROM posting_rules WHERE source_type = 'payment'` canlida
odeme fislemesini SESSIZCE 422 vermeye baslatirdi.

🔴 Enum uyesi burada geri ALINMAZ (Postgres uye SILEMEZ) — o is `f5a6b7c8d9e0`
downgrade'inindir ve tipi bastan kurar.

Elle yazilmistir (autogenerate DEGIL) — repo deseni.

Revision ID: a6b7c8d9e0f1
Revises: f5a6b7c8d9e0
Create Date: 2026-08-27

"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a6b7c8d9e0f1"
down_revision: str | Sequence[str] | None = "f5a6b7c8d9e0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")

#: 🔴 DONMUS KOPYA — `(source_type, ((rol, hesap kodu), ...))`.
#: `payment` satirlari `treasury.posting.PAYMENT_POSTING_RULES`in BU DILIMDE
#: EKLENEN iki satiridir (dordu MU-3C'de tohumlandi, tekrar edilmez);
#: `financial_instrument` satirlari
#: `treasury.instruments.posting.INSTRUMENT_POSTING_RULES`in TAMAMIDIR.
SEED_RULES: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    (
        "payment",
        (
            ("instrument_payable", "103"),
            ("instrument_receivable", "101"),
        ),
    ),
    (
        "financial_instrument",
        (
            ("bank", "102"),
            ("cash", "100"),
            ("instrument_payable", "103"),
            ("instrument_receivable", "101"),
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
                "ODM-1: `%s` eslemesi EKSIK kuruldu — hesap plani kodu bulunamayan "
                "roller: %s. `post_document` bu rollerde 422 verir ve fisi YARIM "
                "YAZMAZ; canlidaki bedeli, cekli odemenin KAYDEDILEMEMESI ve cek "
                "durum gecisinin 422 vermesidir. Eksik hesaplar acilip kurallar "
                "elle eklenmelidir.",
                source_type,
                ", ".join(sorted(eksik)),
            )


def downgrade() -> None:
    bind = op.get_bind()
    # 🔴 YALNIZ BU MIGRATION'IN TOHUMLADIGI `(source_type, role_key)` ciftleri.
    for source_type, kurallar in reversed(SEED_RULES):
        bind.execute(
            sa.text(
                "DELETE FROM posting_rules "
                "WHERE source_type = CAST(:source_type AS journal_source_type) "
                "  AND role_key = ANY(CAST(:roles AS text[]))"
            ),
            {"source_type": source_type, "roles": [rol for rol, _kod in kurallar]},
        )
