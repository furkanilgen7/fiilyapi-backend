"""İK-2.2 — migration tur dönüşü: `a2b3c4d5e6f7` upgrade → downgrade → upgrade.

Emsal: `test_ik2_migration_round.py`. Bu dilim YENİ TABLO açmaz; MEVCUT
`leave_status` enum'una tek bir üye ekler (`withdrawn`) — ve enum değişimi
Postgres'te tam olarak burada ısırır:

🔴 **1. İkinci upgrade "already exists" ile patlayabilir.** Downgrade tipi eski
hâline geri kurmazsa (ya da yarım kurarsa) ikinci `upgrade` canlıda düşer. Tur
dönüşü bunu yakalar.

🔴 **2. `server_default` dönüşümü OTOMATİK DEĞİLDİR.** `leave_requests.status`
kolonu `'pending'::leave_status` varsayılanı taşır. Naif downgrade dizisi
(`ALTER TYPE … RENAME` → `CREATE TYPE` → `ALTER COLUMN … TYPE … USING`)
**ÖLÇÜLDÜ** ve şu hatayla PATLAR:

    ERROR: default for column "status" cannot be cast automatically to type leave_status

Doğru dizi `DROP DEFAULT` → dönüştür → `SET DEFAULT`tur. `test_..._server_default`
o düzeltmenin bekçisidir: varsayılan downgrade sonrası KORUNMUŞ olmalı, yoksa
`INSERT … (status kolonu yok)` yapan her yol NOT NULL ihlaline düşer.

🔴 **3. Geri dönüş VERİ KAYBETMEZ, DURUR.** `withdrawn` taşıyan satır varken
downgrade sessizce geçemez (MT-1 `equity` veri kapısı emsali): satırı
`rejected`e çevirmek "İK reddetti" der ve YALAN söyler; silmek ise talebin var
olduğu bilgisini yok ederdi.

Revizyonlara AÇIKÇA çıkılır; `head`/`-1` KULLANILMAZ (WORKFLOW §4).
"""

import os
import subprocess
import sys
import uuid
from pathlib import Path

import asyncpg
import pytest

from app.core.config import settings

BACKEND_DIR = Path(__file__).parents[2]
ALEMBIC_CMD = (sys.executable, "-m", "alembic")

PARENT_REVISION = "f1a2b3c4d5e6"  # OK-1A onay zinciri motoru
IK22_REVISION = "a2b3c4d5e6f7"

ENUM_NAME = "leave_status"
ESKI_ETIKETLER = ["pending", "approved", "rejected"]
YENI_ETIKETLER = ["pending", "approved", "rejected", "withdrawn"]
STATUS_DEFAULT = "'pending'::leave_status"

#: MT-1 / MU-seed emsalinin kanon cümlesi — veri kapısı duran her migration bunu
#: yazar; canlıda operatör hatayı görüp NE YAPACAĞINI anlasın diye SABİTTİR.
VERI_KAPISI_ISARETI = "downgrade durduruldu"


def _asyncpg_dsn(database: str) -> str:
    base = settings.test_database_url.replace("postgresql+asyncpg://", "postgresql://")
    return base.rsplit("/", 1)[0] + f"/{database}"


def _run_alembic(*args: str, database: str) -> subprocess.CompletedProcess[str]:
    result = _run_alembic_expecting_failure(*args, database=database)
    if result.returncode != 0:
        pytest.fail(f"alembic {' '.join(args)} basarisiz:\n{result.stdout}\n{result.stderr}")
    return result


def _run_alembic_expecting_failure(*args: str, database: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "DATABASE_URL": _asyncpg_dsn(database)}
    return subprocess.run(
        [*ALEMBIC_CMD, *args],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )


async def _enum_labels(conn: asyncpg.Connection, name: str) -> list[str]:
    """SIRA DAHİL okur (`enum_range` `enumsortorder`u izler) — üyenin SONA
    eklendiği ancak böyle kanıtlanır."""
    return list(await conn.fetchval(f"SELECT enum_range(NULL::{name})::text[]"))


async def _column_default(conn: asyncpg.Connection, table: str, column: str) -> str | None:
    return await conn.fetchval(
        "SELECT column_default FROM information_schema.columns "
        "WHERE table_name = $1 AND column_name = $2",
        table,
        column,
    )


async def _current_revision(conn: asyncpg.Connection) -> str | None:
    return await conn.fetchval("SELECT version_num FROM alembic_version")


async def _create_scratch_database() -> str:
    database = f"ik22_t1_{uuid.uuid4().hex[:8]}"
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


async def _talep_yaz(conn: asyncpg.Connection, durum: str) -> None:
    """MİNİMUM FK zinciri, DOĞRUDAN SQL ile: personel + (SEED'li) izin tipi + talep.

    ORM kullanılmaz — bu test şemayı sınar, uygulamayı değil; modeller ile
    migration'ın ayrıştığı bir dünyada ORM üzerinden yazmak o ayrışmayı GİZLERDİ.
    `leave_types` satırları `b2c3d4e5f6a7` SEED'inden gelir, ayrıca yazılmaz.
    """
    personel_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO personnel (id, full_name, source) VALUES ($1, $2, 'company')",
        personel_id,
        "Geri Cekme Personeli",
    )
    await conn.execute(
        "INSERT INTO leave_requests "
        "(id, personnel_id, leave_type_id, start_date, end_date, days, status) "
        "SELECT $1, $2, lt.id, DATE '2026-09-01', DATE '2026-09-03', 3, $3::leave_status "
        "FROM leave_types lt ORDER BY lt.sort_order LIMIT 1",
        uuid.uuid4(),
        personel_id,
        durum,
    )


async def test_upgrade_downgrade_upgrade_round_trip():
    """Tur dönüşü + enum SIRASI + `server_default` KORUNUMU."""
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", IK22_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _enum_labels(conn, ENUM_NAME) == YENI_ETIKETLER
            assert await _column_default(conn, "leave_requests", "status") == STATUS_DEFAULT
            assert await _current_revision(conn) == IK22_REVISION
        finally:
            await conn.close()

        _run_alembic("downgrade", PARENT_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _enum_labels(conn, ENUM_NAME) == ESKI_ETIKETLER, (
                "downgrade `withdrawn` uyesini DUSURMEDI — Postgres enum'dan uye "
                "silemez, tip BASTAN kurulmalidir"
            )
            # 🔴 ÖLÇÜLMÜŞ TUZAK: naif `RENAME + CREATE + ALTER COLUMN TYPE` dizisi
            # "default for column status cannot be cast automatically" ile PATLAR;
            # `DROP DEFAULT` -> donustur -> `SET DEFAULT` yapilmak zorundadir. Bu
            # iddia o duzeltmenin ayakta kaldiginin bekcisidir: varsayilan
            # dusurulup GERI KONMAZSA `status`suz her INSERT NOT NULL'a carpar.
            assert await _column_default(conn, "leave_requests", "status") == STATUS_DEFAULT, (
                "downgrade `status` kolonunun server_default'unu KAYBETTI"
            )
            # Tablolar ve OK-1A semasi AYAKTA kalmali — bu dilim tablo dusurmez.
            assert await conn.fetchval("SELECT to_regclass('public.leave_requests') IS NOT NULL")
            assert await conn.fetchval("SELECT to_regclass('public.approval_chains') IS NOT NULL")
            assert await _current_revision(conn) == PARENT_REVISION
        finally:
            await conn.close()

        # Ikinci upgrade: "type/value already exists" ile PATLAMAMALI.
        _run_alembic("upgrade", IK22_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _enum_labels(conn, ENUM_NAME) == YENI_ETIKETLER
            assert await _column_default(conn, "leave_requests", "status") == STATUS_DEFAULT
            assert await _current_revision(conn) == IK22_REVISION
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


async def test_upgrade_MEVCUT_talepleri_BOZMAZ():
    """Var olan `pending`/`approved`/`rejected` satırlar upgrade'den sağ çıkar.

    Enum'a üye eklemek mevcut satırlara dokunmamalı; dokunuyorsa (ör. tip
    yeniden kurulurken `USING` ifadesi yanlışsa) canlı izin geçmişi kayardı.
    """
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", PARENT_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            for durum in ESKI_ETIKETLER:
                await _talep_yaz(conn, durum)
        finally:
            await conn.close()

        _run_alembic("upgrade", IK22_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            kalanlar = await conn.fetch(
                "SELECT status::text AS status FROM leave_requests ORDER BY status::text"
            )
            assert sorted(row["status"] for row in kalanlar) == sorted(ESKI_ETIKETLER)
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


async def test_downgrade_WITHDRAWN_satiri_varken_SESSIZCE_gecmez():
    """🔴 VERİ KAPISI — geri dönüş veri KAYBETMEZ, DURUR (MT-1 `equity` emsali).

    Üç üyeli tipe dönerken `withdrawn` taşıyan satır DÖNÜŞTÜRÜLEMEZ:

    * `rejected`e çevirmek denetim günlüğüne göre YALAN olurdu ("İK reddetti"
      diye okunur, oysa kişi kendisi vazgeçti),
    * `pending`e çevirmek geri çekilmiş talebi İK'nın onay kuyruğuna GERİ SOKAR,
    * satırı silmek talebin var olduğu bilgisini yok eder.

    Migration bu yüzden AÇIK bir hatayla durur ve şema BOZULMADAN kalır —
    yarım kalmış bir downgrade, duran downgrade'den kötüdür.
    """
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", IK22_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            await _talep_yaz(conn, "withdrawn")
        finally:
            await conn.close()

        sonuc = _run_alembic_expecting_failure("downgrade", PARENT_REVISION, database=database)
        assert sonuc.returncode != 0, (
            "`withdrawn` satiri varken downgrade SESSIZCE gecti — veri kaybi/yalan "
            "riski:\n" + sonuc.stdout + sonuc.stderr
        )
        cikti = sonuc.stdout + sonuc.stderr
        assert VERI_KAPISI_ISARETI in cikti, (
            "downgrade durdu ama SEBEBI anlasilmiyor — operatör canlida ne "
            f"yapacagini bilemez:\n{cikti}"
        )

        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            # Şema BOZULMADAN kaldı.
            assert await _current_revision(conn) == IK22_REVISION
            assert await _enum_labels(conn, ENUM_NAME) == YENI_ETIKETLER
            assert await _column_default(conn, "leave_requests", "status") == STATUS_DEFAULT
            assert await conn.fetchval("SELECT count(*) FROM leave_requests") == 1
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)
