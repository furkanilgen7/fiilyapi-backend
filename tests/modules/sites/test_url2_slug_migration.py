"""URL-2 · `d2e4f6a8b0c1` — GERİ DOLDURMA ölçümü ve tur dönüşü.

Kolonlar NULLABLE açılır ama **mevcut satırlar geri doldurulmalıdır**: canlıda
2 proje, 4 şantiye, 4+ bölüm var ve URL-3 onların hepsinde okunabilir URL
bekliyor. Geri doldurma migration'ın İÇİNDEDİR (ayrı bir betik değil): kolon
açılıp veri sonradan doldurulsaydı deploy ile veri arasında slug'sız bir
pencere kalırdı.

🔴 **PATLAMAMA ŞARTI**: `Dockerfile` açılışı `alembic upgrade head && uvicorn`.
Bu satırda atılan bir istisna `&&`yi kısa devre yapar ve UVICORN HİÇ BAŞLAMAZ.
Bu yüzden çakışma `raise` değil SAYI EKİ ile çözülür; slug üretemeyen kayıt
atlanır. Bu testin merkezi iddiası budur: **migration çakışmalı veriyle de
başarıyla tamamlanır**.

Test kendi TEK KULLANIMLIK veritabanını açar ve sonunda düşürür.
"""

import os
import subprocess
import sys
import uuid
from pathlib import Path

import asyncpg
import pytest

from app.core.config import settings

BACKEND_DIR = Path(__file__).parents[3]
ALEMBIC_CMD = (sys.executable, "-m", "alembic")

# Revizyonlara AÇIKÇA çıkılır; `head`/`-1` KULLANILMAZ — sonraki dilimler
# revizyon ekledikçe bu test sessizce yanlış şeyi ölçerdi.
BEFORE_REVISION = "a7c3d1e5b204"
URL2_REVISION = "d2e4f6a8b0c1"

INDEXES = ("uq_projects_slug", "uq_sites_project_slug", "uq_sections_site_slug")


def _dsn(database: str) -> str:
    base = settings.test_database_url.replace("postgresql+asyncpg://", "postgresql://")
    return base.rsplit("/", 1)[0] + f"/{database}"


def _alembic(*args: str, database: str) -> None:
    result = subprocess.run(
        [*ALEMBIC_CMD, *args],
        cwd=BACKEND_DIR,
        env={**os.environ, "DATABASE_URL": _dsn(database)},
        capture_output=True,
        text=True,
        timeout=600,
    )
    if result.returncode != 0:
        pytest.fail(f"alembic {' '.join(args)} basarisiz:\n{result.stdout}\n{result.stderr}")


async def _scratch() -> str:
    database = f"url2_slug_{uuid.uuid4().hex[:8]}"
    admin = await asyncpg.connect(_dsn("postgres"))
    try:
        await admin.execute(f'CREATE DATABASE "{database}"')
    finally:
        await admin.close()
    return database


async def _drop(database: str) -> None:
    admin = await asyncpg.connect(_dsn("postgres"))
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
    finally:
        await admin.close()


async def _seed(conn: asyncpg.Connection) -> dict[str, uuid.UUID]:
    """URL-2 ÖNCESİ hâle, geri doldurmayı ZORLAYACAK veriyi yazar.

    Kasıtlı olarak: iki farklı ad AYNI tabana düşüyor (`Köprü A` / `Kopru A`),
    biri hiç slug'lanamıyor (`???`), ve iki AYRI projede AYNI şantiye adı var
    (kapsamın proje içi olduğunu kanıtlar: ikisi de EKSİZ slug almalı).
    """
    ids: dict[str, uuid.UUID] = {}

    async def project(key: str, name: str) -> uuid.UUID:
        pid = uuid.uuid4()
        await conn.execute(
            "INSERT INTO projects (id, code, name, status, budget, progress_pct) "
            "VALUES ($1, $2, $3, 'active', 0, 0)",
            pid,
            f"PRJ-{uuid.uuid4().hex[:8]}",
            name,
        )
        ids[key] = pid
        return pid

    p1 = await project("p_kopru", "Köprü A")
    await project("p_kopru_ascii", "Kopru A")
    p3 = await project("p_bos", "???")

    async def site(key: str, project_id: uuid.UUID, name: str) -> uuid.UUID:
        sid = uuid.uuid4()
        await conn.execute(
            "INSERT INTO sites (id, project_id, code, name, status) "
            "VALUES ($1, $2, $3, $4, 'active')",
            sid,
            project_id,
            f"SNT-{uuid.uuid4().hex[:8]}",
            name,
        )
        ids[key] = sid
        return sid

    s1 = await site("s_merkez_p1", p1, "Merkez Şantiye")
    await site("s_merkez_p3", p3, "Merkez Şantiye")
    await site("s_merkez_p1_ikinci", p1, "Merkez Santiye")

    for key, name in (("sec_ince", "İnce İşler"), ("sec_ince2", "Ince Isler")):
        sec_id = uuid.uuid4()
        await conn.execute(
            "INSERT INTO sections (id, site_id, name, status, sort_order) "
            "VALUES ($1, $2, $3, 'planned', 0)",
            sec_id,
            s1,
            name,
        )
        ids[key] = sec_id
    return ids


@pytest.mark.asyncio
async def test_geri_doldurma_cakismali_veriyle_de_TAMAMLANIR():
    database = await _scratch()
    try:
        _alembic("upgrade", BEFORE_REVISION, database=database)
        conn = await asyncpg.connect(_dsn(database))
        try:
            ids = await _seed(conn)
        finally:
            await conn.close()

        # 🔴 ÇEKİRDEK İDDİA: çakışmalı veri üzerinde migration PATLAMAZ.
        _alembic("upgrade", URL2_REVISION, database=database)

        conn = await asyncpg.connect(_dsn(database))
        try:
            assert await conn.fetchval("SELECT version_num FROM alembic_version") == URL2_REVISION

            async def slug_of(table: str, key: str) -> str | None:
                return await conn.fetchval(f"SELECT slug FROM {table} WHERE id = $1", ids[key])

            # 1. Türkçe dönüşüm migration'ın KENDİ kopyasında da doğru.
            assert await slug_of("projects", "p_kopru") == "kopru-a"
            # 2. Çakışma sayı ekiyle ÇÖZÜLDÜ, sessizce çakışmadı.
            assert await slug_of("projects", "p_kopru_ascii") == "kopru-a-2"
            # 3. Slug'lanamayan kayıt ATLANDI (NULL) — migration durmadı.
            assert await slug_of("projects", "p_bos") is None
            # 4. Şantiye kapsamı PROJE İÇİ: iki farklı projede EKSİZ aynı slug.
            assert await slug_of("sites", "s_merkez_p1") == "merkez-santiye"
            assert await slug_of("sites", "s_merkez_p3") == "merkez-santiye"
            # 5. AYNI proje içinde çakışan ikinci şantiye ek aldı.
            assert await slug_of("sites", "s_merkez_p1_ikinci") == "merkez-santiye-2"
            # 6. Bölüm kapsamı ŞANTİYE İÇİ.
            assert await slug_of("sections", "sec_ince") == "ince-isler"
            assert await slug_of("sections", "sec_ince2") == "ince-isler-2"

            for index in INDEXES:
                assert await conn.fetchval(
                    "SELECT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = $1)", index
                ), index

            # Kısmi indeks GERÇEKTEN kısmi: NULL slug ÇOKLANABİLİR olmalı.
            await conn.execute(
                "INSERT INTO projects (id, code, name, status, budget, progress_pct) "
                "VALUES ($1, $2, 'Ikinci Slugsuz', 'active', 0, 0)",
                uuid.uuid4(),
                f"PRJ-{uuid.uuid4().hex[:8]}",
            )
            # …ama DOLU slug çoklanamaz.
            with pytest.raises(asyncpg.UniqueViolationError):
                await conn.execute(
                    "INSERT INTO projects (id, code, slug, name, status, budget, progress_pct) "
                    "VALUES ($1, $2, 'kopru-a', 'Kopya', 'active', 0, 0)",
                    uuid.uuid4(),
                    f"PRJ-{uuid.uuid4().hex[:8]}",
                )
        finally:
            await conn.close()
    finally:
        await _drop(database)


@pytest.mark.asyncio
async def test_downgrade_ve_yeniden_upgrade_TEMIZ():
    """Tur dönüşü: indeksler düşmezse ikinci `upgrade` "already exists" ile patlar."""
    database = await _scratch()
    try:
        _alembic("upgrade", URL2_REVISION, database=database)
        _alembic("downgrade", BEFORE_REVISION, database=database)

        conn = await asyncpg.connect(_dsn(database))
        try:
            for index in INDEXES:
                assert not await conn.fetchval(
                    "SELECT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = $1)", index
                ), index
            for table in ("projects", "sites", "sections"):
                assert not await conn.fetchval(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = $1 AND column_name = 'slug')",
                    table,
                ), table
        finally:
            await conn.close()

        _alembic("upgrade", URL2_REVISION, database=database)
    finally:
        await _drop(database)


def test_alembic_tek_head():
    """İki head = canlıda `alembic upgrade head` patlar, uvicorn hiç başlamaz."""
    result = subprocess.run(
        [*ALEMBIC_CMD, "heads"], cwd=BACKEND_DIR, capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stderr
    heads = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(heads) == 1, f"tek head bekleniyordu:\n{result.stdout}"
