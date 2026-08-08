"""B1 — p3 units/blocks migration'inin upgrade → downgrade → upgrade tur donusu.

Neden ayri ve maliyetli bir test: Postgres'te `ENUM` tipi tabloyla birlikte
SILINMEZ. `downgrade()` icinde `DROP TYPE` unutulursa ilk tur sessizce gecer,
ikinci `upgrade` "type already exists" ile patlar — ve bu yalniz canlida gorulur
(plan §0 / spec §10.3). Bu yuzden downgrade sonrasi iki enum tipinin `pg_type`'da
KALMADIGI ayrica dogrulanir.

Test kendi TEK KULLANIMLIK veritabanini acar ve sonunda dusurur; `.env` ve
`TEST_DATABASE_URL` veritabani ELLENMEZ (plan §0.1). Alembic alt surecte
kosturulur cunku `alembic/env.py` kendi `asyncio.run()` dongusunu kurar ve
calisan bir pytest-asyncio dongusunun icinden cagrilamaz.
"""

import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import asyncpg
import pytest

from app.core.config import settings

BACKEND_DIR = Path(__file__).parents[3]
# Alembic `python -m alembic` ile cagrilir: yerelde `.venv/bin/python`, CI'da
# sistem Python'u — iki ortamda da AYNI yorumlayicinin ortami kullanilir.
# Sabit `.venv/bin/alembic` yolu CI'da YOKTUR (orada venv kurulmaz) ve testi
# yalniz CI'da kirardi.
ALEMBIC_CMD = (sys.executable, "-m", "alembic")

PARENT_REVISION = "e3a8b4a5b93b"
# Bu revizyona ACIKCA cikilir; `head` KULLANILMAZ. Sonraki dilimler revizyon
# ekledikce `head`/`-1` bu revizyonu degil onlari olcerdi.
UNITS_REVISION = "a4c7f1d2e8b3"
NEW_TABLES = ("blocks", "units")
NEW_ENUM_TYPES = ("unit_kind", "unit_owner_side")

# --- P3.1 ---
# `head` / `-1` KULLANILMAZ (plan §0.A.3): her revizyon ACIK id'siyle olculur.
P31_R1_PARENT = "d2a32dcae735"
P31_R1_REVISION = "c1d2e3f4a5b6"
UNIT_KIND_LABELS_BEFORE = ["apartment", "shop"]
UNIT_KIND_LABELS_AFTER = ["apartment", "shop", "office", "warehouse", "parking"]
# Takas sirasinda kullanilan gecici tip adlari downgrade/upgrade sonrasi KALMAMALIDIR.
UNIT_KIND_TEMP_TYPES = ("unit_kind_new", "unit_kind_old")

P31_R2_PARENT = P31_R1_REVISION
P31_R2_REVISION = "c2d3e4f5a6b7"
P31_R2_TYPE_LABELS = {
    "block_roof_type": ["none", "duplex", "terrace"],
    "block_ground_usage": ["commercial", "apartment", "common"],
    "block_parking_type": ["closed", "open", "none"],
    "block_status": ["planning", "construction", "completed"],
    "unit_facing": ["south", "southwest", "east", "north", "west"],
    "unit_parking_right": ["none", "one_closed", "two"],
    "unit_sales_status": ["listed", "reserved", "sold", "closed"],
}
P31_R2_TYPES = tuple(P31_R2_TYPE_LABELS)

P31_R3_PARENT = P31_R2_REVISION
P31_R3_REVISION = "c3d4e5f6a7b8"
P31_R3_BLOCK_COLUMNS = (
    "code",
    "basement_floor_count",
    "floor_count",
    "roof_type",
    "units_per_floor",
    "ground_floor_usage",
    "shop_count",
    "construction_area_m2",
    "elevator_count",
    "parking_type",
    "estimated_delivery_date",
    "status",
    "notes",
)
P31_R3_UNIT_COLUMNS = (
    "floor",
    "facing",
    "balcony_area_m2",
    "bathroom_count",
    "parking_right",
    "min_sale_price",
    "vat_rate",
    "sales_status",
)


def _asyncpg_dsn(database: str) -> str:
    """settings.test_database_url'i asyncpg'nin anladigi duz DSN'e cevirir."""
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
        timeout=180,
    )
    if result.returncode != 0:
        pytest.fail(f"alembic {' '.join(args)} basarisiz:\n{result.stdout}\n{result.stderr}")
    return result


async def _table_exists(conn: asyncpg.Connection, name: str) -> bool:
    return await conn.fetchval(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name = $1)",
        name,
    )


async def _type_exists(conn: asyncpg.Connection, name: str) -> bool:
    return await conn.fetchval("SELECT EXISTS (SELECT 1 FROM pg_type WHERE typname = $1)", name)


async def _constraint_exists(conn: asyncpg.Connection, table: str, name: str) -> bool:
    return await conn.fetchval(
        "SELECT EXISTS (SELECT 1 FROM pg_constraint "
        "WHERE conrelid = $1::regclass AND conname = $2)",
        table,
        name,
    )


async def _current_revision(conn: asyncpg.Connection) -> str | None:
    return await conn.fetchval("SELECT version_num FROM alembic_version")


async def _enum_labels(conn: asyncpg.Connection, name: str) -> list[str]:
    rows = await conn.fetch(
        "SELECT e.enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
        "WHERE t.typname = $1 ORDER BY e.enumsortorder",
        name,
    )
    return [row["enumlabel"] for row in rows]


async def _column_counts(conn: asyncpg.Connection) -> dict[str, int]:
    return {
        table: await conn.fetchval(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = $1",
            table,
        )
        for table in NEW_TABLES
    }


@asynccontextmanager
async def _temp_database(prefix: str) -> AsyncIterator[str]:
    """Tek kullanimlik yerel veritabani; basarisizlikta da dusurulur (plan §0.A.2)."""
    database = f"{prefix}_{uuid.uuid4().hex[:8]}"
    admin = await asyncpg.connect(_asyncpg_dsn("postgres"))
    try:
        await admin.execute(f'CREATE DATABASE "{database}"')
    finally:
        await admin.close()
    try:
        yield database
    finally:
        admin = await asyncpg.connect(_asyncpg_dsn("postgres"))
        try:
            await admin.execute(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
        finally:
            await admin.close()


@asynccontextmanager
async def _connect(database: str) -> AsyncIterator[asyncpg.Connection]:
    conn = await asyncpg.connect(_asyncpg_dsn(database))
    try:
        yield conn
    finally:
        await conn.close()


async def test_upgrade_downgrade_upgrade_round_trip():
    database = f"p3_units_mig_{uuid.uuid4().hex[:8]}"
    admin = await asyncpg.connect(_asyncpg_dsn("postgres"))
    try:
        await admin.execute(f'CREATE DATABASE "{database}"')
    finally:
        await admin.close()

    try:
        _run_alembic("upgrade", UNITS_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            for table in NEW_TABLES:
                assert await _table_exists(conn, table), f"{table} upgrade sonrasi yok"
            for enum_type in NEW_ENUM_TYPES:
                assert await _type_exists(conn, enum_type), f"{enum_type} upgrade sonrasi yok"
            assert await _current_revision(conn) == UNITS_REVISION
        finally:
            await conn.close()

        _run_alembic("downgrade", PARENT_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            for table in NEW_TABLES:
                assert not await _table_exists(conn, table), f"{table} downgrade sonrasi duruyor"
            # KRITIK: enum tipi tabloyla birlikte SILINMEZ; DROP TYPE unutulursa
            # ikinci upgrade patlar (spec §10.3).
            for enum_type in NEW_ENUM_TYPES:
                assert not await _type_exists(conn, enum_type), (
                    f"{enum_type} downgrade sonrasi pg_type'da duruyor"
                )
            assert await _current_revision(conn) == PARENT_REVISION
        finally:
            await conn.close()

        _run_alembic("upgrade", UNITS_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            for table in NEW_TABLES:
                assert await _table_exists(conn, table), f"{table} ikinci upgrade sonrasi yok"
            for enum_type in NEW_ENUM_TYPES:
                assert await _type_exists(conn, enum_type), (
                    f"{enum_type} ikinci upgrade sonrasi yok"
                )
            assert await _current_revision(conn) == UNITS_REVISION
        finally:
            await conn.close()
    finally:
        admin = await asyncpg.connect(_asyncpg_dsn("postgres"))
        try:
            await admin.execute(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
        finally:
            await admin.close()


# --- P3.1 / R1: `unit_kind` enum takasi (izole revizyon) ---


async def test_r1_upgrade_downgrade_upgrade():
    """R1 tur donusu: 2 etiket → 5 etiket → 2 etiket → 5 etiket."""
    async with _temp_database("p31_r1_mig") as database:
        _run_alembic("upgrade", P31_R1_PARENT, database=database)
        async with _connect(database) as conn:
            assert await _enum_labels(conn, "unit_kind") == UNIT_KIND_LABELS_BEFORE

        _run_alembic("upgrade", P31_R1_REVISION, database=database)
        async with _connect(database) as conn:
            assert await _enum_labels(conn, "unit_kind") == UNIT_KIND_LABELS_AFTER
            assert await _current_revision(conn) == P31_R1_REVISION

        _run_alembic("downgrade", P31_R1_PARENT, database=database)
        async with _connect(database) as conn:
            assert await _enum_labels(conn, "unit_kind") == UNIT_KIND_LABELS_BEFORE
            assert await _current_revision(conn) == P31_R1_PARENT

        # IKINCI upgrade: `DROP TYPE` unutulmussa burasi "type already exists" ile patlar.
        _run_alembic("upgrade", P31_R1_REVISION, database=database)
        async with _connect(database) as conn:
            assert await _enum_labels(conn, "unit_kind") == UNIT_KIND_LABELS_AFTER


async def test_r1_downgrade_eski_tipi_birakmaz():
    """Takasin gecici tipleri ne upgrade ne downgrade sonrasi `pg_type`'da kalir."""
    async with _temp_database("p31_r1_type") as database:
        _run_alembic("upgrade", P31_R1_REVISION, database=database)
        async with _connect(database) as conn:
            for temp_type in UNIT_KIND_TEMP_TYPES:
                assert not await _type_exists(conn, temp_type), (
                    f"{temp_type} upgrade sonrasi pg_type'da duruyor"
                )

        _run_alembic("downgrade", P31_R1_PARENT, database=database)
        async with _connect(database) as conn:
            for temp_type in UNIT_KIND_TEMP_TYPES:
                assert not await _type_exists(conn, temp_type), (
                    f"{temp_type} downgrade sonrasi pg_type'da duruyor"
                )
            assert await _type_exists(conn, "unit_kind")


async def test_r1_baska_sema_degisikligi_yok():
    """R1 IZOLEDIR: `units`/`blocks` kolon sayisi degismez (spec §10.2/R1)."""
    async with _temp_database("p31_r1_iso") as database:
        _run_alembic("upgrade", P31_R1_PARENT, database=database)
        async with _connect(database) as conn:
            before = {
                table: await conn.fetchval(
                    "SELECT count(*) FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = $1",
                    table,
                )
                for table in NEW_TABLES
            }

        _run_alembic("upgrade", P31_R1_REVISION, database=database)
        async with _connect(database) as conn:
            after = {
                table: await conn.fetchval(
                    "SELECT count(*) FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = $1",
                    table,
                )
                for table in NEW_TABLES
            }
        assert after == before


# --- P3.1 / R2: yedi yeni enum tipi (izole revizyon) ---


async def test_r2_yedi_tip_olusur():
    """R2 yedi tipi olusturur ve KOLON EKLEMEZ (spec §10.2/R2)."""
    async with _temp_database("p31_r2_mig") as database:
        _run_alembic("upgrade", P31_R2_PARENT, database=database)
        async with _connect(database) as conn:
            for enum_type in P31_R2_TYPES:
                assert not await _type_exists(conn, enum_type), f"{enum_type} R2 oncesi var"
            before = await _column_counts(conn)

        _run_alembic("upgrade", P31_R2_REVISION, database=database)
        async with _connect(database) as conn:
            for enum_type, labels in P31_R2_TYPE_LABELS.items():
                assert await _enum_labels(conn, enum_type) == labels
            assert await _current_revision(conn) == P31_R2_REVISION
            assert await _column_counts(conn) == before


async def test_r2_downgrade_yedi_tipi_de_dusurur():
    """`DROP TYPE` unutulan tek bir tip bile ikinci upgrade'i patlatir (plan §0.A.4)."""
    async with _temp_database("p31_r2_drop") as database:
        _run_alembic("upgrade", P31_R2_REVISION, database=database)
        _run_alembic("downgrade", P31_R2_PARENT, database=database)
        async with _connect(database) as conn:
            for enum_type in P31_R2_TYPES:
                assert not await _type_exists(conn, enum_type), (
                    f"{enum_type} downgrade sonrasi pg_type'da duruyor"
                )
            assert await _current_revision(conn) == P31_R2_PARENT


async def test_r2_ikinci_upgrade_patlamaz():
    async with _temp_database("p31_r2_twice") as database:
        _run_alembic("upgrade", P31_R2_REVISION, database=database)
        _run_alembic("downgrade", P31_R2_PARENT, database=database)
        _run_alembic("upgrade", P31_R2_REVISION, database=database)
        async with _connect(database) as conn:
            for enum_type in P31_R2_TYPES:
                assert await _type_exists(conn, enum_type), (
                    f"{enum_type} ikinci upgrade sonrasi yok"
                )


# --- P3.1 / R3: 21 kolon + 1 UNIQUE + CHECK'ler ---


async def _columns(conn: asyncpg.Connection, table: str) -> dict[str, str]:
    rows = await conn.fetch(
        "SELECT column_name, is_nullable FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = $1",
        table,
    )
    return {row["column_name"]: row["is_nullable"] for row in rows}


async def _seed_block_and_unit(conn: asyncpg.Connection) -> tuple[str, str]:
    """R3 ONCESI bir blok ve bir unite yazar; upgrade'in mevcut satirlari
    degistirmedigi boyle olculur (karar 8: veri migration'i YOKTUR)."""
    project_id = str(uuid.uuid4())
    site_id = str(uuid.uuid4())
    block_id = str(uuid.uuid4())
    unit_id = str(uuid.uuid4())
    await conn.execute(
        "INSERT INTO projects (id, code, name, budget, progress_pct) "
        "VALUES ($1::uuid, 'P-MIG-1', 'Migration Projesi', 0, 0)",
        project_id,
    )
    await conn.execute(
        "INSERT INTO sites (id, project_id, code, name) "
        "VALUES ($1::uuid, $2::uuid, 'SNT-MIG-1', 'Merkez')",
        site_id,
        project_id,
    )
    await conn.execute(
        "INSERT INTO blocks (id, project_id, site_id, name) "
        "VALUES ($1::uuid, $2::uuid, $3::uuid, 'A Blok')",
        block_id,
        project_id,
        site_id,
    )
    await conn.execute(
        "INSERT INTO units (id, project_id, block_id, unit_no, unit_kind) "
        "VALUES ($1::uuid, $2::uuid, $3::uuid, '1', 'apartment')",
        unit_id,
        project_id,
        block_id,
    )
    return block_id, unit_id


async def test_r3_upgrade_downgrade_upgrade():
    async with _temp_database("p31_r3_mig") as database:
        _run_alembic("upgrade", P31_R3_PARENT, database=database)
        async with _connect(database) as conn:
            block_before = await _columns(conn, "blocks")
            unit_before = await _columns(conn, "units")
            for column in P31_R3_BLOCK_COLUMNS:
                assert column not in block_before
            for column in P31_R3_UNIT_COLUMNS:
                assert column not in unit_before

        _run_alembic("upgrade", P31_R3_REVISION, database=database)
        async with _connect(database) as conn:
            blocks = await _columns(conn, "blocks")
            units = await _columns(conn, "units")
            # 21 kolonun TAMAMI nullable (plan §0.A.5).
            assert [blocks.get(c) for c in P31_R3_BLOCK_COLUMNS] == ["YES"] * 13
            assert [units.get(c) for c in P31_R3_UNIT_COLUMNS] == ["YES"] * 8
            assert await _constraint_exists(conn, "blocks", "uq_blocks_project_code")
            assert not await _constraint_exists(conn, "units", "ck_units_floor")
            assert await _current_revision(conn) == P31_R3_REVISION

        _run_alembic("downgrade", P31_R3_PARENT, database=database)
        async with _connect(database) as conn:
            blocks = await _columns(conn, "blocks")
            units = await _columns(conn, "units")
            for column in P31_R3_BLOCK_COLUMNS:
                assert column not in blocks, f"blocks.{column} downgrade sonrasi duruyor"
            for column in P31_R3_UNIT_COLUMNS:
                assert column not in units, f"units.{column} downgrade sonrasi duruyor"
            # Tipler R2'nin sorumlulugudur: R3 downgrade'i onlari DUSURMEZ.
            for enum_type in P31_R2_TYPES:
                assert await _type_exists(conn, enum_type)

        _run_alembic("upgrade", P31_R3_REVISION, database=database)
        async with _connect(database) as conn:
            assert set(P31_R3_BLOCK_COLUMNS) <= set(await _columns(conn, "blocks"))
            assert set(P31_R3_UNIT_COLUMNS) <= set(await _columns(conn, "units"))


async def test_r3_mevcut_satirlar_degismez():
    """Karar 8: canli satirlara dokunan veri migration'i YOKTUR.

    `status` / `sales_status` yalniz YENI satirlar icin varsayilan alir; mevcut
    satirlarda NULL kalirlar. Bu yuzden kolonlar ONCE varsayilansiz eklenir,
    varsayilan SONRA `SET DEFAULT` ile konur — `ADD COLUMN ... DEFAULT` mevcut
    satirlari da doldururdu.
    """
    async with _temp_database("p31_r3_data") as database:
        _run_alembic("upgrade", P31_R3_PARENT, database=database)
        async with _connect(database) as conn:
            block_id, unit_id = await _seed_block_and_unit(conn)
            block_before = dict(
                await conn.fetchrow("SELECT * FROM blocks WHERE id = $1::uuid", block_id)
            )
            unit_before = dict(
                await conn.fetchrow("SELECT * FROM units WHERE id = $1::uuid", unit_id)
            )

        _run_alembic("upgrade", P31_R3_REVISION, database=database)
        async with _connect(database) as conn:
            block_after = dict(
                await conn.fetchrow("SELECT * FROM blocks WHERE id = $1::uuid", block_id)
            )
            unit_after = dict(
                await conn.fetchrow("SELECT * FROM units WHERE id = $1::uuid", unit_id)
            )

        for column, value in block_before.items():
            assert block_after[column] == value, f"blocks.{column} degisti"
        for column, value in unit_before.items():
            assert unit_after[column] == value, f"units.{column} degisti"
        for column in P31_R3_BLOCK_COLUMNS:
            assert block_after[column] is None, f"blocks.{column} mevcut satirda NULL degil"
        for column in P31_R3_UNIT_COLUMNS:
            assert unit_after[column] is None, f"units.{column} mevcut satirda NULL degil"


# --- P9 / `units.shareholder_id` (izole revizyon) ---

P9_PARENT = "b8c9d0e1f2a3"
# `head` / `-1` KULLANILMAZ: revizyon ACIK id'siyle olculur (WORKFLOW §4).
P9_REVISION = "c9d0e1f2a3b4"
P9_COLUMN = "shareholder_id"
P9_INDEX = "ix_units_shareholder_id"
P9_FK = "units_shareholder_id_fkey"


async def _index_exists(conn: asyncpg.Connection, name: str) -> bool:
    return await conn.fetchval(
        "SELECT EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname = 'public' AND indexname = $1)",
        name,
    )


async def _fk_delete_rule(conn: asyncpg.Connection, name: str) -> str | None:
    """`confdeltype`: 'n' = SET NULL, 'r' = RESTRICT, 'c' = CASCADE, 'a' = NO ACTION."""
    return await conn.fetchval(
        # `::text` SART: asyncpg `"char"` tipini bytes olarak dondurur.
        "SELECT confdeltype::text FROM pg_constraint WHERE conname = $1 AND contype = 'f'",
        name,
    )


async def _seed_shareholder(conn: asyncpg.Connection, project_id: str) -> str:
    shareholder_id = str(uuid.uuid4())
    await conn.execute(
        "INSERT INTO land_share_shareholder (id, project_id, name, share_pct) "
        "VALUES ($1::uuid, $2::uuid, 'Hissedar A', 50)",
        shareholder_id,
        project_id,
    )
    return shareholder_id


async def test_p9_upgrade_downgrade_upgrade():
    """Tur donusu: kolon + indeks acilir, downgrade ikisini de dusurur, ikinci upgrade patlamaz."""
    async with _temp_database("p9_units_mig") as database:
        _run_alembic("upgrade", P9_PARENT, database=database)
        async with _connect(database) as conn:
            assert P9_COLUMN not in await _columns(conn, "units")
            assert not await _index_exists(conn, P9_INDEX)

        _run_alembic("upgrade", P9_REVISION, database=database)
        async with _connect(database) as conn:
            units = await _columns(conn, "units")
            # NULLABLE: paylasim kademeli girilir (spec §4.2).
            assert units.get(P9_COLUMN) == "YES"
            assert await _index_exists(conn, P9_INDEX)
            # SET NULL: proje silme kaskadinin DB emniyeti (spec §3).
            assert await _fk_delete_rule(conn, P9_FK) == "n"
            assert await _current_revision(conn) == P9_REVISION

        _run_alembic("downgrade", P9_PARENT, database=database)
        async with _connect(database) as conn:
            assert P9_COLUMN not in await _columns(conn, "units")
            assert not await _index_exists(conn, P9_INDEX)
            assert await _current_revision(conn) == P9_PARENT

        _run_alembic("upgrade", P9_REVISION, database=database)
        async with _connect(database) as conn:
            assert P9_COLUMN in await _columns(conn, "units")
            assert await _index_exists(conn, P9_INDEX)
            assert await _current_revision(conn) == P9_REVISION


async def test_p9_mevcut_uniteler_null_dogar_ve_hissedar_silinince_bosalir():
    """Veri gecisi YOKTUR: mevcut satir NULL kalir. Hissedar silinince FK SET NULL isler."""
    async with _temp_database("p9_units_data") as database:
        _run_alembic("upgrade", P9_PARENT, database=database)
        async with _connect(database) as conn:
            _, unit_id = await _seed_block_and_unit(conn)
            project_id = await conn.fetchval(
                "SELECT project_id FROM units WHERE id = $1::uuid", unit_id
            )

        _run_alembic("upgrade", P9_REVISION, database=database)
        async with _connect(database) as conn:
            assert (
                await conn.fetchval("SELECT shareholder_id FROM units WHERE id = $1::uuid", unit_id)
                is None
            )

            shareholder_id = await _seed_shareholder(conn, str(project_id))
            await conn.execute(
                "UPDATE units SET shareholder_id = $1::uuid WHERE id = $2::uuid",
                shareholder_id,
                unit_id,
            )
            await conn.execute(
                "DELETE FROM land_share_shareholder WHERE id = $1::uuid", shareholder_id
            )
            # RESTRICT olsaydi proje silme kaskadi RASTGELE kirilirdi (spec §3).
            assert (
                await conn.fetchval("SELECT shareholder_id FROM units WHERE id = $1::uuid", unit_id)
                is None
            )
