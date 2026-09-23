"""FAT1 T3 — `ck_invoices_amounts_non_negative` genisletme migration'i
(`ca36b2e59ee3`). Envanter kaydi #56.

## 🔴 NEDEN AYRI BIR TUR DONUSU TESTI

`Dockerfile` acilista `alembic upgrade head && uvicorn ...` kosar; migration
patlarsa `&&` kisa devre yapar ve **uvicorn HIC BASLAMAZ (tam kesinti)**.
Bu yuzden tur `upgrade -> downgrade -> upgrade` olarak KOSULUR (TB6 deseni,
`e9f0a1b2c3d4`), iddia edilmez.

## 🔴 BEKCI KOR OLMASIN — kaydin ana bulgusu

`tests/modules/invoicing/test_invoicing_migration.py`deki `CONSTRAINTS` demeti
yalniz kisit ADLARINI sayar (`ck_invoices_amounts_non_negative` bugun de
listede DURUR — ad DEGISMEDI). Ad sayan bir bekci `tax_base` unutulsa bile
YESIL kalirdi. Bu dosya bekciligi METNE ve DAVRANISA baglar:

1. `test_migration_SQL_i_modelin_SQL_i_ile_AYNI` — migration'in `NEW_SQL`i ile
   `Invoice` modelindeki `AMOUNTS_NON_NEGATIVE_CHECK` sabiti BIREBIR ayni mi
   (metin ayrisirsa `create_all` ile kurulan test semasi ile `alembic upgrade`
   ile kurulan canli sema FARKLI davranir ve suite bunu HIC gormez);
2. `test_KIRLI_DB_de_NOT_VALID_KISIT_YENI_negatif_tax_base_INSERT_ini_REDDEDER`
   — dogrudan negatif `tax_base` INSERT edip `IntegrityError`/`CheckViolationError`
   bekler (davranis testi, mutasyona dayanikli: kisitten `tax_base` bacagi
   sokulursa bu test YANLIS SEBEPLE degil DOGRU SEBEPLE kirmizi olur).

Test kendi TEK KULLANIMLIK veritabanini acar ve sonunda dusurur; `.env` ve
`TEST_DATABASE_URL` veritabani ELLENMEZ (TB6/MU2 deseni). Revizyonlara ACIKCA
cikilir; `head` / `-1` KULLANILMAZ.
"""

import importlib.util
import os
import subprocess
import sys
import uuid
from pathlib import Path

import asyncpg
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.invoicing.models import AMOUNTS_NON_NEGATIVE_CHECK

BACKEND_DIR = Path(__file__).parents[3]
ALEMBIC_CMD = (sys.executable, "-m", "alembic")

#: 🔴 EBEVEYN revizyon — `alembic heads` bugun bunu gosteriyor (izin kapsami
#: dilimi). Re-parent gerekirse bu sabit ve migration'in `down_revision`i
#: BIRLIKTE guncellenir.
PARENT_REVISION = "b2c3d4e5f8a1"
MIG_REVISION = "ca36b2e59ee3"

TABLE = "invoices"
NAME = "ck_invoices_amounts_non_negative"

#: PG'nin CHECK ihlali sinifi (TB6/MK-2 emsali) — TEK elemanli ama TUPLE'dir.
CHECK_VIOLATION = ("23514",)

MIGRATION_PATH = (
    BACKEND_DIR / "alembic" / "versions" / "ca36b2e59ee3_fat1t3_invoices_tax_base_non_negative.py"
)


def _load_migration_module():
    """Migration modulunu ADIYLA yukler — `alembic/versions` bir paket DEGILDIR."""
    spec = importlib.util.spec_from_file_location("fat1t3_mig", MIGRATION_PATH)
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


MIG = _load_migration_module()

#: 🔴 ITHAL, KOPYA DEGIL — elle kopyalansaydi migration'in SQL'i degistiginde
#: test ESKI metni olcmeye devam eder ve bekci sessizce olurdu.
OLD_SQL = MIG.OLD_SQL
NEW_SQL = MIG.NEW_SQL

#: `COUNT_SQL` bir SELECT'tir; bekcilik edilecek olan onun YUKLEMIDIR.
COUNT_PREDICATE = str(MIG.COUNT_SQL).split(" WHERE ", 1)[1]


def _asyncpg_dsn(database: str) -> str:
    base = settings.test_database_url.replace("postgresql+asyncpg://", "postgresql://")
    return base.rsplit("/", 1)[0] + f"/{database}"


def _run_alembic(*args: str, database: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "DATABASE_URL": _asyncpg_dsn(database)}
    result = subprocess.run(
        [*ALEMBIC_CMD, *args],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        pytest.fail(f"alembic {' '.join(args)} basarisiz:\n{result.stdout}\n{result.stderr}")
    return result


def _cikti(result: subprocess.CompletedProcess[str]) -> str:
    """Alembic INFO'yu stdout'a, WARNING'i stderr'e yazar — ikisi de okunur."""
    return result.stdout + result.stderr


async def _constraint_sql(conn: asyncpg.Connection, name: str) -> str | None:
    return await conn.fetchval(
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = $1", name
    )


async def _convalidated(conn: asyncpg.Connection, name: str) -> bool | None:
    """`f` = kisit GECMIS satirlar icin dogrulanmamis; ileriye donuk enforce EDER."""
    return await conn.fetchval("SELECT convalidated FROM pg_constraint WHERE conname = $1", name)


async def _current_revision(conn: asyncpg.Connection) -> str | None:
    return await conn.fetchval("SELECT version_num FROM alembic_version")


async def _create_scratch_database() -> str:
    database = f"invoicing_fat1t3_{uuid.uuid4().hex[:8]}"
    admin = await asyncpg.connect(_asyncpg_dsn("postgres"))
    try:
        await admin.execute(f'CREATE DATABASE "{database}"')
    finally:
        await admin.close()
    return database


async def _drop_scratch_database(database: str) -> None:
    admin = await asyncpg.connect(_asyncpg_dsn("postgres"))
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
    finally:
        await admin.close()


async def _kullanici_yaz(conn: asyncpg.Connection) -> uuid.UUID:
    """`created_by_id` RESTRICT FK — gercek bir kullanici SART."""
    role_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO roles (id, key, name, emoji, description, is_system) "
        "VALUES ($1, $2, 'Muhasebe', '#', 'test', false)",
        role_id,
        f"role_{uuid.uuid4().hex[:8]}",
    )
    user_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO users (id, email, password_hash, full_name, title, role_id, status) "
        "VALUES ($1, $2, 'x', 'FAT1T3 Test', 'Muhasebe', $3, 'active')",
        user_id,
        f"{uuid.uuid4().hex[:8]}@fiil.test",
        role_id,
    )
    return user_id


_INSERT_SQL = (
    "INSERT INTO invoices (id, direction, invoice_no, document_type, status, issue_date, "
    "party_name, subtotal, advance_amount, retention_amount, tax_base, vat_amount, "
    "withholding_amount, total, created_by_id) "
    "VALUES (gen_random_uuid(), 'outgoing', $1, 'einvoice', 'draft', DATE '2026-09-23', "
    "'FAT1T3 Test', $2, 0, 0, $3, $4, 0, $5, $6)"
)


async def _fatura_yaz(
    conn: asyncpg.Connection,
    kullanici_id: uuid.UUID,
    invoice_no: str,
    *,
    subtotal: str = "1000",
    tax_base: str = "1000",
    vat_amount: str = "200",
    total: str = "1200",
) -> None:
    await conn.execute(_INSERT_SQL, invoice_no, subtotal, tax_base, vat_amount, total, kullanici_id)


async def _reddedilir(conn: asyncpg.Connection, sql: str, *args: object) -> None:
    """Yazma `23514` ile ve ADI GECEN kisit yuzunden reddedilmelidir."""
    with pytest.raises(asyncpg.PostgresError) as hata:
        await conn.execute(sql, *args)
    assert hata.value.sqlstate in CHECK_VIOLATION, hata.value
    assert NAME in str(hata.value), hata.value


# --------------------------------------------------------------------------- #
# Sembolik katman — migration'in SQL'i ile modelin SQL'i BUGUN ESITTIR
# --------------------------------------------------------------------------- #


def test_migration_parent_is_the_expected_revision():
    """Iki head = canlida deploy kilitlenmesi (`alembic upgrade head` patlar).
    Korunmasi gereken invariant "head TEKTIR"dir; migration'in kendisi de
    zincirde (head'in atalari arasinda) durmalidir."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(str(BACKEND_DIR / "alembic.ini")))
    assert script.get_revision(MIG_REVISION).down_revision == PARENT_REVISION

    heads = list(script.get_heads())
    assert len(heads) == 1, f"tek head bekleniyordu: {heads}"
    ataler = {rev.revision for rev in script.iterate_revisions(heads[0], "base")}
    assert MIG_REVISION in ataler, "FAT1T3 migration'i zincirden dusmus"


def test_migration_SQL_i_modelin_SQL_i_ile_AYNI():
    """🔴 KAYIT #56'NIN KALBI. Migration modelden ITHAL ETMEZ (gecmis donmus
    olmalidir) — ikisinin BUGUN esit oldugu AYRICA olculur. Ayrisirlarsa
    `create_all` ile kurulan test semasi ile `alembic upgrade` ile kurulan
    canli sema FARKLI davranir ve suite bunu HIC gormez.

    `tax_base` metinde GERCEKTEN VAR mi — bekcinin ADA degil METNE bakan
    yarisi budur (ad-sayan `CONSTRAINTS` demeti bu unutmayi ASLA yakalamazdi).
    """
    assert MIG.NEW_SQL == AMOUNTS_NON_NEGATIVE_CHECK
    assert "tax_base >= 0" in MIG.NEW_SQL
    assert MIG.NAME == NAME
    assert MIG.TABLE == TABLE
    # Eski metin tax_base'i KAPSAMAZ — genisleme gercekten ORAYA eklendi.
    assert "tax_base" not in MIG.OLD_SQL


# --------------------------------------------------------------------------- #
# Kosullu VALIDATE'in IKI PREMISI — gercek Postgres uzerinde truth-table
# --------------------------------------------------------------------------- #

#: Para kolonlarindan ikisi (tax_base + toplam bir kontrol kolonu) uzerinde
#: pozitif/negatif/NULL kombinasyonlari; digerleri sabit (0) tutulur ki
#: sadece `tax_base` bacaginin ETKISI olculsun.
DEGERLER: tuple[str | None, ...] = ("100.00", "-1.00", None)
KOMBINASYON_SAYISI = len(DEGERLER) * len(DEGERLER)


def _literal(deger: str | None) -> str:
    return "CAST(NULL AS numeric)" if deger is None else f"CAST('{deger}' AS numeric)"


def _truth_table_sql() -> str:
    satirlar = ", ".join(
        f"({_literal(tb)}, {_literal(tot)})" for tb in DEGERLER for tot in DEGERLER
    )
    # Sabit kolonlar (0) OLD/NEW'in her ikisi icin de GECER kilinir ki yalniz
    # tax_base/total bacaklarinin etkisi olculsun.
    old_expr = (
        OLD_SQL.replace("subtotal", "CAST(0 AS numeric)")
        .replace("advance_amount", "CAST(0 AS numeric)")
        .replace("retention_amount", "CAST(0 AS numeric)")
        .replace("vat_amount", "CAST(0 AS numeric)")
        .replace("withholding_amount", "CAST(0 AS numeric)")
        .replace("total", "total_kol")
    )
    new_expr = (
        NEW_SQL.replace("subtotal", "CAST(0 AS numeric)")
        .replace("advance_amount", "CAST(0 AS numeric)")
        .replace("retention_amount", "CAST(0 AS numeric)")
        .replace("vat_amount", "CAST(0 AS numeric)")
        .replace("withholding_amount", "CAST(0 AS numeric)")
        .replace("tax_base", "tax_base_kol")
        .replace("total", "total_kol")
    )
    return f"""
        WITH kombinasyon(tax_base_kol, total_kol) AS (VALUES {satirlar})
        SELECT
            count(*) AS toplam,
            count(*) FILTER (WHERE ({old_expr}) IS FALSE) AS eski_red,
            count(*) FILTER (WHERE ({new_expr}) IS FALSE) AS yeni_red,
            count(*) FILTER (
                WHERE ({old_expr}) IS FALSE AND ({new_expr}) IS NOT FALSE
            ) AS kapsama_ihlali
        FROM kombinasyon
    """


async def test_KAPSAMA_gercek_SQL_ile_olculur(db_session: AsyncSession) -> None:
    """🔴 KOSULLU `VALIDATE`IN DAYANAGI: `OLD`un reddettigi her satiri `NEW`
    de reddeder (`kapsama_ihlali = 0`). Bu tutmasaydi eski kisiti dusurmek bir
    seyi KAYBETTIRIRDI ve migration sessizce gevserdi. `NEW` ayrica
    `tax_base < 0` satirlarini da reddeder -> `yeni_red > eski_red`.

    ⚠️ CHECK semantigi: ifade FALSE ise satir reddedilir, NULL GECER — bu
    yuzden `IS FALSE` / `IS NOT FALSE` kullanilir, `NOT (...)` DEGIL.
    """
    satir = (await db_session.execute(sa.text(_truth_table_sql()))).one()

    assert satir.toplam == KOMBINASYON_SAYISI
    assert satir.kapsama_ihlali == 0, "NEW, OLD'un reddettigi bir satiri KACIRIYOR"
    assert satir.yeni_red > satir.eski_red, "NEW en az bir ek satiri (negatif tax_base) reddetmeli"


# --------------------------------------------------------------------------- #
# Gercek zincir — TEMIZ veritabani
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_upgrade_downgrade_upgrade_round_trip():
    """TEMIZ bir veritabaninda kisit TAM DOGRULANMIS biter (`convalidated =
    t`) ve bunu `VALIDATE_LOG_PREFIX` satiri deploy gunlugune soyler."""
    database = await _create_scratch_database()
    try:
        sonuc = _run_alembic("upgrade", MIG_REVISION, database=database)
        assert MIG.VALIDATE_LOG_PREFIX in _cikti(sonuc)
        assert MIG.SKIP_VALIDATE_LOG_PREFIX not in _cikti(sonuc)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _current_revision(conn) == MIG_REVISION
            metin = await _constraint_sql(conn, NAME)
            assert metin is not None
            assert "tax_base" in metin
            assert await _convalidated(conn, NAME) is True
        finally:
            await conn.close()

        _run_alembic("downgrade", PARENT_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _current_revision(conn) == PARENT_REVISION
            metin = await _constraint_sql(conn, NAME)
            assert metin is not None
            assert "tax_base" not in metin
            # Downgrade duz `ADD CONSTRAINT` kurar: taranir ve dogrulanmis biter.
            assert await _convalidated(conn, NAME) is True
        finally:
            await conn.close()

        sonuc = _run_alembic("upgrade", MIG_REVISION, database=database)
        assert MIG.VALIDATE_LOG_PREFIX in _cikti(sonuc)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _current_revision(conn) == MIG_REVISION
            metin = await _constraint_sql(conn, NAME)
            assert metin is not None and "tax_base" in metin
            assert await _convalidated(conn, NAME) is True
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


@pytest.mark.asyncio
async def test_TEMIZ_DB_de_negatif_tax_base_INSERT_REDDEDILIR_pozitif_GECER():
    """DAVRANIS TESTI — kisit metnini okumaz, dogrudan yazar. Bu, kayit #56'nin
    onerdigi 'negatif tax_base INSERT edip IntegrityError bekle' testidir."""
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", MIG_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            kullanici_id = await _kullanici_yaz(conn)

            # Pozitif tax_base GECER.
            await _fatura_yaz(conn, kullanici_id, "FIL2026000900")

            # 🔴 Negatif tax_base REDDEDILIR — kayit #56'nin kapattigi delik.
            await _reddedilir(
                conn,
                _INSERT_SQL,
                "FIL2026000901",
                "1000",
                "-1",
                "200",
                "1200",
                kullanici_id,
            )
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


# --------------------------------------------------------------------------- #
# Gercek zincir — KIRLI veritabani (negatif tax_base'li satir ONCEDEN VAR)
# --------------------------------------------------------------------------- #


async def _kirli_db_kur(database: str) -> tuple[uuid.UUID, str]:
    """PARENT'e cikar ve ESKI kisitin (yasal olarak) gecirdigi negatif
    `tax_base`li bir fatura birakir — kaydin kapattigi delik tam olarak budur.
    ESKI kisit `tax_base`e HIC bakmiyordu, bu yuzden bu INSERT PARENT'te
    GECER."""
    _run_alembic("upgrade", PARENT_REVISION, database=database)
    conn = await asyncpg.connect(_asyncpg_dsn(database))
    try:
        kullanici_id = await _kullanici_yaz(conn)
        invoice_no = "FIL2026000800"
        await _fatura_yaz(conn, kullanici_id, invoice_no, tax_base="-500")
        return kullanici_id, invoice_no
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_KIRLI_DB_de_upgrade_BASARIYLA_KOSAR_ve_VALIDATE_ATLANIR():
    """Kirli DB'de migration DURMAZ: kisit `NOT VALID` girer, sayim kilit
    altinda kosar, ihlal varsa `VALIDATE` ATLANIR ve migration BASARIYLA
    biter (uygulama ACILIR). 🔴 SIZINTI BEKCISI: deploy gunlugu mali veri
    (tutar/kimlik/tarih) SIZDIRMAZ, yalniz satir SAYISI yazar."""
    database = await _create_scratch_database()
    try:
        kullanici_id, invoice_no = await _kirli_db_kur(database)

        sonuc = _run_alembic("upgrade", MIG_REVISION, database=database)
        assert sonuc.returncode == 0
        cikti = _cikti(sonuc)

        assert MIG.SKIP_VALIDATE_LOG_PREFIX in cikti
        assert "1 adet negatif" in cikti
        assert MIG.VALIDATE_LOG_PREFIX not in cikti

        # 🔴 SIZINTI BEKCISI — bu degerler gunluge ASLA dusmez.
        for sizinti in ("-500", invoice_no):
            assert sizinti not in cikti, f"deploy gunlugune mali veri sizdi: {sizinti}"

        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _current_revision(conn) == MIG_REVISION
            assert await _constraint_sql(conn, NAME) is not None
            # VALIDATE atlandi -> kisit gecmis satirlar icin DOGRULANMAMIS.
            assert await _convalidated(conn, NAME) is False

            # Migration VERIYE DOKUNMAZ: kirli satir AYNEN durur.
            deger = await conn.fetchval(
                "SELECT tax_base FROM invoices WHERE invoice_no = $1", invoice_no
            )
            assert str(deger) == "-500.00"
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


@pytest.mark.asyncio
async def test_KIRLI_DB_de_NOT_VALID_KISIT_YENI_negatif_tax_base_INSERT_ini_REDDEDER():
    """🔴 BU DILIMIN KALBI — `NOT VALID` "hicbir seyi engellemez" DEGILDIR.
    Tek gevsemesi MEVCUT satirlari TARAMAMASIDIR; YENI INSERT/UPDATE'ler TAM
    enforce edilir. Bu olculmezse "kisit eklendi ama ise yaramiyor" diye
    yanlis okunur ve delik acik sanilir."""
    database = await _create_scratch_database()
    try:
        kullanici_id, _kirli_no = await _kirli_db_kur(database)
        _run_alembic("upgrade", MIG_REVISION, database=database)

        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _convalidated(conn, NAME) is False

            # 1) YENI negatif tax_base INSERT -> RED.
            await _reddedilir(
                conn,
                _INSERT_SQL,
                "FIL2026000801",
                "1000",
                "-1",
                "200",
                "1200",
                kullanici_id,
            )
            # 2) YENI pozitif tax_base INSERT -> GECER.
            await _fatura_yaz(conn, kullanici_id, "FIL2026000802")

            # 3) KIRLI satira DOKUNAN UPDATE de RED: `NOT VALID` mevcut
            #    satirlara KALICI muafiyet VERMEZ, yalniz taramayi atlar.
            await _reddedilir(
                conn,
                "UPDATE invoices SET note = 'dokunuldu' WHERE invoice_no = $1",
                _kirli_no,
            )
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


@pytest.mark.asyncio
async def test_KIRLI_DB_de_downgrade_PATLAMAZ_eski_kisit_TARANARAK_geri_gelir():
    """Geri donus yolu kirli veriyle de ACIK olmak ZORUNDA. `downgrade` eski
    kisiti duz `ADD CONSTRAINT` ile kurar (TABLOYU TARAR). Negatif `tax_base`li
    kirli satir ESKI kisiti GECER (tax_base hic sorgulanmaz) — tarama patlamaz
    ve eski kisit DOGRULANMIS (`convalidated = t`) biter."""
    database = await _create_scratch_database()
    try:
        _kullanici_id, invoice_no = await _kirli_db_kur(database)
        _run_alembic("upgrade", MIG_REVISION, database=database)

        sonuc = _run_alembic("downgrade", PARENT_REVISION, database=database)
        assert sonuc.returncode == 0

        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _current_revision(conn) == PARENT_REVISION
            assert await _constraint_sql(conn, NAME) is not None
            assert await _convalidated(conn, NAME) is True
            # Kirli satir hala yerinde: downgrade de VERIYE DOKUNMAZ.
            deger = await conn.fetchval(
                "SELECT tax_base FROM invoices WHERE invoice_no = $1", invoice_no
            )
            assert str(deger) == "-500.00"
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)
