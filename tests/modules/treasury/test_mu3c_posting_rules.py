"""MU-3C — `posting_rules` TOHUMU: iki katman eşitliği + migration davranışı.

## Neden İKİ KATMAN

`d1e2f3a4b5c6` migration'ı `app.modules.treasury.posting`i BİLEREK IMPORT
ETMEZ (K1 kanonu: uygulanmış bir migration DONMUŞ olmalıdır, uygulama kodu
zamanla değişir) ve eşlemeyi DONMUŞ BİR KOPYA olarak taşır. Bedeli, iki metnin
sessizce ayrışabilmesidir: ürün demeti `102`yi `101`e çevirse bile migration
eski kodu tohumlar ve CANLI, kodun anlattığından BAŞKA bir hesaba fiş atardı.
Bu dosya o bedeli ödettirir (MU-3B deseni).

🔴 Bu dosya migration'ı kendi TEK KULLANIMLIK veritabanında koşar; `.env` ve
`TEST_DATABASE_URL` veritabanı ELLENMEZ.
"""

import ast
import uuid
from pathlib import Path

import asyncpg

from app.modules.invoicing.posting import INVOICE_POSTING_RULES
from app.modules.treasury.posting import PAYMENT_POSTING_RULES
from tests.modules.accounting._mu1_migration import (
    BACKEND_DIR,
    _asyncpg_dsn,
    _drop_scratch_database,
    _run_alembic,
)

MU3C_SEED_REVISION = "d1e2f3a4b5c6"
MU3B_SEED_REVISION = "c0d1e2f3a4b5"
MIGRATION_PATH = Path("alembic") / "versions" / "d1e2f3a4b5c6_mu3c_odeme_posting_rules_tohumu.py"


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
    """🔴 İKİ KATMAN EŞİTLİĞİ — sıra dahil."""
    assert _migration_seed_rules() == PAYMENT_POSTING_RULES


def test_CIFT_SAYIM_YOK_gider_ve_hasilat_rolleri_ODEME_ailesinde_TANIMSIZ():
    """🔴 BU DİLİMİN EN AĞIR VERİ İDDİASI.

    Ödeme fişi cariyi kapatır; gider/hasılat MU-3B'de ZATEN yazılmıştır.
    `740`/`600` (ve öteki sonuç hesapları) bu ailede TANIMLI OLSAYDI bir bacak
    onlara düşebilir, fiş yine dengeli kalır ve mizan DOĞRU görünürdü — kusuru
    hiçbir kolon farkı ele vermezdi. Fail-closed olan taraf tanımsızlıktır:
    `post_document` çözemediği rolde **422** verir.
    """
    kodlar = {kod for _rol, kod in PAYMENT_POSTING_RULES}

    assert "740" not in kodlar, "ÇİFT SAYIM: ödeme fişi gidere dokunuyor"
    assert "600" not in kodlar, "ÇİFT SAYIM: ödeme fişi hasılata dokunuyor"
    # Kalan bacaklar YALNIZ nakit + cari.
    assert kodlar == {"100", "102", "120", "320"}


def test_KARAR_1_ve_2_demette_CAKILI():
    """KARAR-1: `170`/`350` ÖLÜ hesaptır. KARAR-2: alt hesap AÇILMAZ."""
    esleme = dict(PAYMENT_POSTING_RULES)

    assert esleme["receivable"] == "120"
    assert esleme["payable"] == "320"
    assert esleme["bank"] == "102"
    assert esleme["cash"] == "100"
    assert "170" not in esleme.values(), "KARAR-1 ihlali: yıllara yaygın rejim ölü hesaptır"
    assert "350" not in esleme.values(), "KARAR-1 ihlali: yıllara yaygın rejim ölü hesaptır"
    assert not any("." in kod for kod in esleme.values()), (
        "KARAR-2 ihlali: alt hesap AÇILMAZ (MU-4); `320.04` açıldığı an "
        "`320`e bakan kural 422 verir"
    )


def test_CEK_ARA_HESAPLARI_101_ve_103_TOHUMLANMAZ():
    """🔴 Çek/senet geçişleri fiş ATMAZ — ara hesap da AÇILMAZ.

    `101 Alınan Çekler` / `103 Verilen Çekler` TDHP tohumunda VARDIR ama bu
    ailede bir role bağlanmaz: bu ürünün nakit tanımı `treasury/balance.py`dir
    ve portföyü SAYMAZ. Bağlansaydı nakit mutabakatı yapısal olarak kırılırdı.
    """
    kodlar = {kod for _rol, kod in PAYMENT_POSTING_RULES}

    assert "101" not in kodlar
    assert "103" not in kodlar


async def test_migration_TOHUMLAR_ve_IKINCI_upgrade_PATLAMAZ():
    """🔴 K6 — IDEMPOTENS. `Dockerfile` her açılışta `alembic upgrade head` koşar.

    Yarım kalmış bir deploy'dan sonraki ikinci `upgrade` patlasaydı `&&` kısa
    devre yapar ve uvicorn HİÇ BAŞLAMAZDI (tam kesinti).
    """
    database = f"mu3c_seed_{uuid.uuid4().hex[:8]}"
    admin = await asyncpg.connect(_asyncpg_dsn("postgres"))
    try:
        await admin.execute(f'CREATE DATABASE "{database}"')
    finally:
        await admin.close()

    try:
        _run_alembic("upgrade", MU3C_SEED_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            satirlar = await conn.fetch(
                "SELECT r.role_key, c.code FROM posting_rules r "
                "JOIN chart_of_accounts c ON c.id = r.account_id "
                "WHERE r.source_type = 'payment' ORDER BY r.role_key"
            )
            assert [(s["role_key"], s["code"]) for s in satirlar] == sorted(
                PAYMENT_POSTING_RULES
            ), "tohum eksik ya da BAŞKA hesaba bağlandı"
        finally:
            await conn.close()

        # İkinci tur — `ON CONFLICT DO NOTHING` yoksa BURADA patlar.
        _run_alembic("downgrade", MU3B_SEED_REVISION, database=database)
        _run_alembic("upgrade", MU3C_SEED_REVISION, database=database)
        _run_alembic("upgrade", MU3C_SEED_REVISION, database=database)

        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            adet = await conn.fetchval(
                "SELECT count(*) FROM posting_rules WHERE source_type = 'payment'"
            )
            assert adet == len(PAYMENT_POSTING_RULES), "tekrar koşan tohum satır ÇOĞALTTI"
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


async def test_downgrade_FATURA_ailesine_DOKUNMAZ():
    """Downgrade YALNIZ kendi tohumunu siler.

    Kapısız bir `DELETE FROM posting_rules` MU-3B'nin fatura eşlemesini de
    süpürür ve canlıda fatura fişlemesi SESSİZCE 422 vermeye başlardı.
    """
    database = f"mu3c_seed_{uuid.uuid4().hex[:8]}"
    admin = await asyncpg.connect(_asyncpg_dsn("postgres"))
    try:
        await admin.execute(f'CREATE DATABASE "{database}"')
    finally:
        await admin.close()

    try:
        _run_alembic("upgrade", MU3C_SEED_REVISION, database=database)
        _run_alembic("downgrade", MU3B_SEED_REVISION, database=database)

        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM posting_rules WHERE source_type = 'payment'"
                )
                == 0
            )
            assert await conn.fetchval(
                "SELECT count(*) FROM posting_rules WHERE source_type = 'invoice'"
            ) == len(INVOICE_POSTING_RULES), "downgrade FATURA eşlemesini de sildi"
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)
