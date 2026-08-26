"""🔴 MU-3E — TOHUM ile ÜRÜN DEMETİNİN İKİ KATMAN EŞİTLİĞİ + migration semantiği.

Migration `SEED_RULES`u `payroll.posting.PAYROLL_POSTING_RULES`ten **elle
kopyalar** (uygulanmış bir migration DONMUŞ olmalıdır, K1). İki katmanın
ayrıştığını hiçbir kolon farkı ele vermez: canlıda kural satırı ESKİ hesabı
gösterir, kod YENİSİNİ anlatır ve mizan sessizce yanlış hesaba dolar. Bu
yüzden eşitlik AST ile iddia edilir — migration İMPORT EDİLMEZ.

## 🔴 BU AİLEDE `ALTER TYPE` YOKTUR — ve bu ölçülür

MU-3B/C/D'nin tersine burada enum'a üye EKLENMEZ: `payroll_period`
`JournalSourceType`ta MU-3A'dan beri VARDIR. Dolayısıyla MU-3D'nin "ADD VALUE
ile tohum AYRI migration olmak zorundadır" tuzağı buraya UĞRAMAZ ve tohum TEK
migration'dır. Aşağıdaki `test_UYE_MU3A_DAN_BERI_VAR_ALTER_TYPE_GEREKMEZ`
bunu bir varsayım olarak değil bir ÖLÇÜM olarak tutar: üye bir gün
sonradan-eklenen bir üyeye dönüşürse bu migration canlıda `unsafe use of new
value` ile patlar ve **uvicorn HİÇ BAŞLAMAZ**.
"""

import ast
import uuid
from pathlib import Path

import asyncpg

from app.modules.accounting.models import JournalSourceType
from app.modules.payroll.posting import PAYROLL_POSTING_RULES
from tests.modules.accounting._mu1_migration import (
    BACKEND_DIR,
    _asyncpg_dsn,
    _drop_scratch_database,
    _run_alembic,
)

SEED_REVISION = "f4a5b6c7d8e9"
PARENT_REVISION = "a4b5c6d7e8f9"
MIGRATION_PATH = Path("alembic") / "versions" / "f4a5b6c7d8e9_mu3e_bordro_posting_rules_tohumu.py"
SOURCE_ENUM = "journal_source_type"

URUN_DEMETLERI: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    (JournalSourceType.payroll_period.value, PAYROLL_POSTING_RULES),
)


def _migration_seed_rules():
    """`SEED_RULES` demetini AST'den okur — migration IMPORT EDİLMEZ."""
    agac = ast.parse((BACKEND_DIR / MIGRATION_PATH).read_text())
    for dugum in agac.body:
        hedef = getattr(dugum, "target", None) or getattr(dugum, "targets", [None])[0]
        if isinstance(hedef, ast.Name) and hedef.id == "SEED_RULES":
            return ast.literal_eval(dugum.value)
    raise AssertionError("migration'da `SEED_RULES` bulunamadı")


def test_migration_tohumu_URUN_demetiyle_BIREBIR_ayni():
    """🔴 İKİ KATMAN EŞİTLİĞİ — rol SIRASI dahil."""
    assert _migration_seed_rules() == URUN_DEMETLERI


def test_BORDRO_ailesi_DORT_bacaklidir():
    """Demet ELLE yazılır: üründen türetilseydi kendi kendini doğrulardı."""
    assert PAYROLL_POSTING_RULES == (
        ("personnel_expense", "730"),
        ("personnel_payable", "335"),
        ("tax_payable", "360"),
        ("social_security_payable", "361"),
    )


def test_KDV_ROLU_TANIMSIZDIR():
    yasak = {"vat_input", "vat_output", "vat"}
    roller = {rol for rol, _kod in PAYROLL_POSTING_RULES}
    assert not (roller & yasak), f"bordro ailesinde KDV rolü TANIMLI: {roller & yasak}"


def test_KARAR_1_yillara_yaygin_rejim_YOK_ve_KARAR_2_alt_hesap_ACILMAZ():
    kodlar = {kod for _rol, kod in PAYROLL_POSTING_RULES}
    assert not (kodlar & {"170", "350"}), "KARAR-1: yıllara yaygın hesap SEÇİLMİŞ"
    assert not (kodlar & {"320", "120"}), (
        "bordro CARİ hesaba yazıyor — MU-4'ün `320.04` mayını bu aileyi ETKİLEMEMELİDİR"
    )
    for kod in kodlar:
        assert "." not in kod, f"alt hesap kodu tohumlanmış ({kod})"


def test_UYE_MU3A_DAN_BERI_VAR_ALTER_TYPE_GEREKMEZ():
    """🔴 Migration'da `ALTER TYPE` OLMAMALIDIR — ve olmadığı ölçülür.

    Üye tipin İLK yaratılışında vardır. Bir gün `ADD VALUE` ile eklenen bir
    üyeye dönüşürse ve tohum aynı migration'da kalırsa Postgres `unsafe use of
    new value` verir — **yalnız canlıda**, `Dockerfile`ın `&&` zinciri patlar
    ve uvicorn hiç başlamaz.
    """
    # 🔴 Yalnız KOŞAN KOD taranır. Ham metin taransaydı migration'ın kendi
    #    docstring'i (tuzağı ANLATIYOR) testi kırmızıya çevirirdi — bir bekçi,
    #    kendi gerekçesini yazmayı yasaklayamaz.
    kaynak = (BACKEND_DIR / MIGRATION_PATH).read_text()
    agac = ast.parse(kaynak)
    govdeler = [
        ast.get_source_segment(kaynak, dugum)
        for dugum in agac.body
        if isinstance(dugum, ast.FunctionDef) and dugum.name in {"upgrade", "downgrade"}
    ]
    assert len(govdeler) == 2, "migration'da `upgrade`/`downgrade` bulunamadı"
    for govde in govdeler:
        assert "ALTER TYPE" not in govde.upper(), (
            "tohum migration'ı enum DEĞİŞTİRİYOR — `ADD VALUE` ile değerin "
            "KULLANIMI aynı işlemde HATADIR ve bu YALNIZ CANLIDA görülür"
        )
    assert JournalSourceType.payroll_period.value in [uye.value for uye in JournalSourceType]


async def _scratch() -> str:
    database = f"mu3e_seed_{uuid.uuid4().hex[:8]}"
    admin = await asyncpg.connect(_asyncpg_dsn("postgres"))
    try:
        await admin.execute(f'CREATE DATABASE "{database}"')
    finally:
        await admin.close()
    return database


async def _kural_kodlari(conn: asyncpg.Connection, source_type: str):
    return await conn.fetch(
        "SELECT r.role_key, h.code FROM posting_rules r "
        "JOIN chart_of_accounts h ON h.id = r.account_id "
        "WHERE r.source_type::text = $1 ORDER BY r.role_key",
        source_type,
    )


async def test_TOHUM_migrationin_URETTIGI_semada_olculur_ve_GERI_ALINABILIR():
    """🔴 Tohum, `create_all` şemasında DEĞİL migration'ın ürettiği şemada ölçülür.

    Ayrıca ölçülen üç şey: (a) `upgrade` dört kuralı da kurar, (b) `downgrade`
    YALNIZ bu migration'ın tohumladıklarını siler, (c) ikinci `upgrade`
    `ON CONFLICT DO NOTHING` sayesinde PATLAMAZ (K6 idempotens).
    """
    database = await _scratch()
    try:
        _run_alembic("upgrade", PARENT_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            oncesi = await _kural_kodlari(conn, JournalSourceType.payroll_period.value)
            assert oncesi == [], "kural MU-3E'den ÖNCE de vardı — test bir şey ölçmüyor"
        finally:
            await conn.close()

        _run_alembic("upgrade", SEED_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            for source_type, kurallar in URUN_DEMETLERI:
                satirlar = await _kural_kodlari(conn, source_type)
                assert sorted((r["role_key"], r["code"]) for r in satirlar) == sorted(kurallar)
        finally:
            await conn.close()

        _run_alembic("downgrade", PARENT_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _kural_kodlari(conn, JournalSourceType.payroll_period.value) == []
        finally:
            await conn.close()

        # K6 — idempotens: yeniden kurulur ve İKİNCİ kez de patlamaz.
        _run_alembic("upgrade", SEED_REVISION, database=database)
        _run_alembic("downgrade", PARENT_REVISION, database=database)
        _run_alembic("upgrade", SEED_REVISION, database=database)
    finally:
        await _drop_scratch_database(database)
