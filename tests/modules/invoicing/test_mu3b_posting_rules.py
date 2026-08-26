"""MU-3B — `posting_rules` TOHUMU: iki katman eşitliği + migration davranışı.

## Neden İKİ KATMAN

`c0d1e2f3a4b5` migration'ı `app.modules.invoicing.posting`i BİLEREK IMPORT
ETMEZ (K1 kanonu: uygulanmış bir migration DONMUŞ olmalıdır, uygulama kodu
zamanla değişir) ve eşlemeyi DONMUŞ BİR KOPYA olarak taşır. Bedeli, iki metnin
sessizce ayrışabilmesidir: ürün demeti `740`ı `170`e çevirse bile migration eski
kodu tohumlar ve CANLI, kodun anlattığından BAŞKA bir hesaba fiş atardı. Bu
dosya o bedeli ödettirir (`test_mu_seed_iki_katman_esitligi.py` deseni).

🔴 Bu dosya migration'ı kendi TEK KULLANIMLIK veritabanında koşar; `.env` ve
`TEST_DATABASE_URL` veritabanı ELLENMEZ.
"""

import ast
import uuid
from pathlib import Path

import asyncpg

from app.modules.invoicing.posting import INVOICE_POSTING_RULES
from tests.modules.accounting._mu1_migration import (
    BACKEND_DIR,
    _asyncpg_dsn,
    _drop_scratch_database,
    _run_alembic,
)

MU3B_SEED_REVISION = "c0d1e2f3a4b5"
MIGRATION_PATH = Path("alembic") / "versions" / "c0d1e2f3a4b5_mu3b_fatura_posting_rules_tohumu.py"


def _migration_seed_rules() -> tuple[tuple[str, str], ...]:
    """`SEED_RULES` demetini AST'den okur — migration IMPORT EDİLMEZ.

    Import edilseydi `alembic.op` bağlamı olmadan modül yan etkileri koşar ve
    test, ölçtüğü şeyin dışında bir sebeple kırılabilirdi.
    """
    agac = ast.parse((BACKEND_DIR / MIGRATION_PATH).read_text())
    for dugum in agac.body:
        hedefler = getattr(dugum, "target", None) or getattr(dugum, "targets", [None])[0]
        if isinstance(hedefler, ast.Name) and hedefler.id == "SEED_RULES":
            return tuple(tuple(ast.literal_eval(dugum.value)))
    raise AssertionError("migration'da `SEED_RULES` bulunamadı")


def test_migration_tohumu_URUN_demetiyle_BIREBIR_ayni():
    """🔴 İKİ KATMAN EŞİTLİĞİ — sıra dahil.

    Sıra da iddiadır: iki liste aynı çiftleri farklı sırada taşısaydı bir
    okuyucu "kopya" olduklarına güvenemez, her satırı elle karşılaştırırdı.
    """
    assert _migration_seed_rules() == INVOICE_POSTING_RULES


def test_KARAR_1_ve_2_demette_CAKILI():
    """🔴 Ürün kararları BURADA çakılır — kod okunarak değil, iddia edilerek.

    KARAR-1: `740`/`600` (yıllara yaygın `170`/`350` DEĞİL).
    KARAR-2: `320`/`120` ANA hesap (alt hesap `320.04` AÇILMAZ, MU-4'e kaldı).
    """
    esleme = dict(INVOICE_POSTING_RULES)

    assert esleme["expense"] == "740"
    assert esleme["revenue"] == "600"
    assert esleme["payable"] == "320"
    assert esleme["receivable"] == "120"
    assert "170" not in esleme.values(), "KARAR-1 ihlali: yıllara yaygın rejim ölü hesaptır"
    assert "350" not in esleme.values(), "KARAR-1 ihlali: yıllara yaygın rejim ölü hesaptır"
    assert not any("." in kod for kod in esleme.values()), (
        "KARAR-2 ihlali: alt hesap AÇILMAZ (MU-4); `320.04` açıldığı an "
        "`320`e bakan kural 422 verir"
    )


async def test_migration_TOHUMLAR_ve_IKINCI_upgrade_PATLAMAZ():
    """🔴 K6 — IDEMPOTENS. `Dockerfile` her açılışta `alembic upgrade head` koşar.

    Yarım kalmış bir deploy'dan sonraki ikinci `upgrade` patlasaydı `&&` kısa
    devre yapar ve uvicorn HİÇ BAŞLAMAZDI (tam kesinti).
    """
    database = f"mu3b_seed_{uuid.uuid4().hex[:8]}"
    admin = await asyncpg.connect(_asyncpg_dsn("postgres"))
    try:
        await admin.execute(f'CREATE DATABASE "{database}"')
    finally:
        await admin.close()

    try:
        _run_alembic("upgrade", MU3B_SEED_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            satirlar = await conn.fetch(
                "SELECT r.role_key, c.code FROM posting_rules r "
                "JOIN chart_of_accounts c ON c.id = r.account_id "
                "WHERE r.source_type = 'invoice' ORDER BY r.role_key"
            )
            assert [(s["role_key"], s["code"]) for s in satirlar] == sorted(
                INVOICE_POSTING_RULES
            ), "tohum eksik ya da BAŞKA hesaba bağlandı"
        finally:
            await conn.close()

        # İkinci tur — `ON CONFLICT DO NOTHING` yoksa BURADA patlar.
        _run_alembic("downgrade", "b9c0d1e2f3a4", database=database)
        _run_alembic("upgrade", MU3B_SEED_REVISION, database=database)
        _run_alembic("upgrade", MU3B_SEED_REVISION, database=database)

        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            adet = await conn.fetchval(
                "SELECT count(*) FROM posting_rules WHERE source_type = 'invoice'"
            )
            assert adet == len(INVOICE_POSTING_RULES), "tekrar koşan tohum satır ÇOĞALTTI"
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


async def test_downgrade_YALNIZ_kendi_tohumunu_siler():
    """Kullanıcının açtığı kural satırı downgrade'de KAYBOLMAZ.

    Kapısız bir `DELETE FROM posting_rules` (a477fdf00fdf'in süpürme deseni)
    burada YANLIŞTIR: kullanıcının başka bir aileye ya da başka bir role
    yazdığı eşleme bu migration'ın malı değildir.
    """
    database = f"mu3b_seed_{uuid.uuid4().hex[:8]}"
    admin = await asyncpg.connect(_asyncpg_dsn("postgres"))
    try:
        await admin.execute(f'CREATE DATABASE "{database}"')
    finally:
        await admin.close()

    try:
        _run_alembic("upgrade", MU3B_SEED_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            hesap_id = await conn.fetchval("SELECT id FROM chart_of_accounts WHERE code = '102'")
            await conn.execute(
                "INSERT INTO posting_rules (id, source_type, role_key, account_id) "
                "VALUES ($1, 'payment', 'bank', $2)",
                uuid.uuid4(),
                hesap_id,
            )
        finally:
            await conn.close()

        _run_alembic("downgrade", "b9c0d1e2f3a4", database=database)

        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM posting_rules WHERE source_type = 'invoice'"
                )
                == 0
            )
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM posting_rules WHERE source_type = 'payment'"
                )
                == 1
            ), "downgrade kullanıcının kendi kural satırını SİLDİ"
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)
