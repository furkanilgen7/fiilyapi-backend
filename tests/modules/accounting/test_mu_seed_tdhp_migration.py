"""MU-SEED T4 — TDHP tohum migration'inin (`e5f6a7b8c9d0`) tur donusu + veri kapisi.

🔴 **NEDEN AYRI BIR MIGRATION TESTI ZORUNLU.** `tests/conftest.py:57-61` semayi
`Base.metadata.create_all` ile kurar ve **`alembic upgrade` HIC KOSMAZ**. Yani
normal suite migration'i TAMAMEN BEKCISIZ birakir: `upgrade()`in INSERT'i
patlasa da, `downgrade()`in veri kapisi hic yazilmamis olsa da yesil kalirdi.
Kusur YALNIZ CANLIDA gorunurdu — `Dockerfile:22` acilista
`alembic upgrade head && uvicorn …` kosar ve patlayan bir satir `&&`yi kisa
devre yaptirip uvicorn'u HIC BASLATMAZ (**tam kesinti**).

Bu dosya emsali `test_mt1_ozkaynak_kontra_migration.py`dir: kendi **TEK
KULLANIMLIK** veritabanini `asyncpg` ile acar, alembic'i **alt surecte**
`DATABASE_URL` override'iyla kosturur ve sonunda DB'yi duurur. `.env` ve
`TEST_DATABASE_URL` veritabani **ELLENMEZ** (`.env` UZAK Railway'i gosterir).

Revizyonlara **ACIKCA** cikilir; `head` / `-1` KULLANILMAZ — arada baska bir
dilim merge edilirse testin sessizce baska bir seyi olcmesi engellenir.

⚠️ PG SURUM TUZAGI: yerel 18, CI 16 — surume ozgu SQLSTATE/hata sinifi iddia
edilmez; `returncode != 0` + mesaj icerigi yeterlidir.
⚠️ Alt surecte alembic kostugu icin bu dosya YAVASTIR (emsal gibi 300s timeout).
"""

import os
import subprocess
import sys
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path

import asyncpg
import pytest

from app.core.config import settings

BACKEND_DIR = Path(__file__).parents[3]
ALEMBIC_CMD = (sys.executable, "-m", "alembic")

# 🔴 ACIK revizyon id'leri — `head` / `-1` YOK.
MU_SEED_REVISION = "e5f6a7b8c9d0"
PREV_REVISION = "d3e4f5a6b7c8"

TABLE = "chart_of_accounts"

#: T3'un donmus `SEED_ACCOUNTS` demetiyle ayni sayim: 56 grup (`NN`) + 260 ana
#: hesap (`NNN`). Sayi BILEREK sabittir: bir satirin sessizce dusmesi/eklenmesi
#: hesap plani ekranini ve bilancoyu ayni anda kaydirir.
BEKLENEN_SATIR = 316

#: `(-)` son ekli, kendi sinifindan DUSULEN hesaplar (`257 Birikmis
#: Amortismanlar (-)` gibi). MT-1'in `is_contra` bayragi.
BEKLENEN_KONTRA = 34

#: Kullanicinin KENDI actigi, tohumda BULUNMAYAN bir kod (downgrade'den sag
#: cikmasi gerekir).
KULLANICI_KODU = "999"

#: Downgrade'in dokunmamasi gereken komsu tablolar.
KOMSU_TABLOLAR = ("journal_entries", "journal_lines", "accounting_periods", "users")


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


async def _create_scratch_database() -> str:
    database = f"accounting_museed_{uuid.uuid4().hex[:8]}"
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


async def _current_revision(conn: asyncpg.Connection) -> str | None:
    return await conn.fetchval("SELECT version_num FROM alembic_version")


async def _hesap_sayisi(conn: asyncpg.Connection) -> int:
    return await conn.fetchval(f"SELECT count(*) FROM {TABLE}")


async def _kontra_sayisi(conn: asyncpg.Connection) -> int:
    return await conn.fetchval(f"SELECT count(*) FROM {TABLE} WHERE is_contra")


async def _hesap(conn: asyncpg.Connection, code: str) -> asyncpg.Record | None:
    return await conn.fetchrow(
        f"SELECT code, name, account_type::text AS account_type, is_contra "
        f"FROM {TABLE} WHERE code = $1",
        code,
    )


async def _dengeli_fis_yaz(conn: asyncpg.Connection, *, borc_kodu: str, alacak_kodu: str) -> None:
    """K7 kapisini kuran veri: tohum hesabina bagli DENGELI, `posted` bir fis.

    `ck_journal_entries_posted_balanced` yuzunden fis dengeli olmak ZORUNDADIR;
    `ck_journal_lines_single_side` yuzunden her satir tek taraflidir.
    `created_by_id` bir kullanici ister, kullanici da bir rol — ikisi de ham
    SQL ile acilir (roller `a477fdf00fdf` tarafindan zaten tohumlanmistir).
    """
    role_id = await conn.fetchval("SELECT id FROM roles LIMIT 1")
    assert role_id is not None, "roller tohumlanmamis — `a477fdf00fdf` kosmamis olabilir"

    user_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO users (id, email, password_hash, full_name, title, role_id, status) "
        "VALUES ($1, $2, 'x', 'T4 Muhasebeci', '', $3, 'active')",
        user_id,
        f"t4-{user_id.hex[:8]}@ornek.test",
        role_id,
    )

    entry_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO journal_entries (id, entry_date, period_year, period_month, description, "
        "status, total_debit, total_credit, created_by_id) "
        "VALUES ($1, DATE '2026-08-16', 2026, 8, 'T4 kapi fisi', 'posted', 100, 100, $2)",
        entry_id,
        user_id,
    )
    borc_id = await conn.fetchval(f"SELECT id FROM {TABLE} WHERE code = $1", borc_kodu)
    alacak_id = await conn.fetchval(f"SELECT id FROM {TABLE} WHERE code = $1", alacak_kodu)
    await conn.execute(
        "INSERT INTO journal_lines (id, entry_id, sort_order, account_id, debit, credit) "
        "VALUES ($1, $2, 0, $3, 100, 0), ($4, $2, 1, $5, 0, 100)",
        uuid.uuid4(),
        entry_id,
        borc_id,
        uuid.uuid4(),
        alacak_id,
    )


@pytest.fixture(scope="module")
async def tohumlu_db() -> AsyncGenerator[str, None]:
    """`upgrade e5f6a7b8c9d0` kosmus, SALT OKUNUR paylasilan tek kullanimlik DB.

    Yalniz DB'yi DEGISTIRMEYEN iddialar bunu paylasir; mutasyon yapan her test
    kendi scratch DB'sini acar (testler birbirini kirletemez).
    """
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", MU_SEED_REVISION, database=database)
        yield database
    finally:
        await _drop_scratch_database(database)


# --------------------------------------------------------------------------- #
# 1-2 — zincirin kendisi
# --------------------------------------------------------------------------- #


def test_alembic_has_single_head():
    """Iki head = canlida deploy kilitlenmesi (`alembic upgrade head` patlar).

    🔴 `DATABASE_URL` override'i BURADA DA verilir. `heads` bugun bir baglanti
    acmiyor ama `.env` UZAK Railway'i gosteriyor ve alembic'in bir alt
    komutunun ileride motor kurmasi hicbir uyari vermeden CANLIYA baglanmak
    demektir (MU-1'de bir kez yasandi). Kural tek cumledir: **hicbir alembic
    komutu override'siz kosmaz.**
    """
    result = subprocess.run(
        [*ALEMBIC_CMD, "heads"],
        cwd=BACKEND_DIR,
        env={**os.environ, "DATABASE_URL": _asyncpg_dsn("postgres")},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    heads = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(heads) == 1, f"tek head bekleniyordu, cikti:\n{result.stdout}"


def test_migration_parent_is_the_expected_revision():
    """🔴 Ebeveyn `d3e4f5a6b7c8`dir. Paralel bir dalda baska bir migration merge
    olursa **re-parent SART** (P8/TH dersi: re-parent unutulursa canli hic
    acilmaz); bu sabit o unutmanin tek bekcisidir — sabit ve migration BIRLIKTE
    guncellenir."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(str(BACKEND_DIR / "alembic.ini")))
    revision = script.get_revision(MU_SEED_REVISION)
    assert revision.down_revision == PREV_REVISION


# --------------------------------------------------------------------------- #
# 3-5 — upgrade sonrasi tohumun icerigi (salt okunur)
# --------------------------------------------------------------------------- #


async def test_upgrade_tam_sayim_ve_kontra_sayimi(tohumlu_db: str) -> None:
    """316 satir · 34 kontra — TAM SAYIM bilerek sabittir.

    Bir satirin sessizce dusmesi hesap plani ekraninda bos bir kod birakir;
    sessizce eklenmesi ise bilancoyu kaydirir. Kontra sayimi ayri olcuulur
    cunku `is_contra` yanlis basilirsa toplamlar EKSILMESI gerekirken EKLENIR.
    """
    conn = await asyncpg.connect(_asyncpg_dsn(tohumlu_db))
    try:
        assert await _current_revision(conn) == MU_SEED_REVISION
        assert await _hesap_sayisi(conn) == BEKLENEN_SATIR
        assert await _kontra_sayisi(conn) == BEKLENEN_KONTRA
    finally:
        await conn.close()


async def test_257_kontra_ve_501_kontra_DEGIL(tohumlu_db: str) -> None:
    """🔴 KONTRA BAYRAGININ IKI YONU DE OLCULUR — ne eksik ne fazla.

    `257 Birikmis Amortismanlar (-)` `liability` + `is_contra = true`tur:
    `Maddi Duran Varliklar (net)` satirindan DUSULMEK zorundadir.

    `501 Odenmemis Sermaye (-)` ise adinda `(-)` TASIDIGI HALDE kontra DEGILDIR
    — o `equity` sinifinin kendi icinde eksi bakiyeli bir kalemdir. Olculmus
    gerekce: `501` kontra isaretlenseydi ozkaynak toplaminda isareti bir kez
    daha donerdi ve `Sermaye` kalemi 6.000 yerine **14.000** cikardi. Yani
    `(-)` son eki TEK BASINA kontra kanidi DEGILDIR.
    """
    conn = await asyncpg.connect(_asyncpg_dsn(tohumlu_db))
    try:
        amortisman = await _hesap(conn, "257")
        assert amortisman is not None
        assert amortisman["account_type"] == "liability"
        assert amortisman["is_contra"] is True

        odenmemis = await _hesap(conn, "501")
        assert odenmemis is not None
        assert odenmemis["account_type"] == "equity"
        assert odenmemis["is_contra"] is False, (
            "`501 Odenmemis Sermaye (-)` kontra isaretlenmis — Sermaye kalemi "
            "6.000 yerine 14.000 cikar"
        )
    finally:
        await conn.close()


async def test_500_equity_ve_621_expense_SINIFTAN_TURETILMEZ(tohumlu_db: str) -> None:
    """🔴 K5 — HESAP TURU KOD SINIFINDAN TURETILEMEZ, satir satir tasinir.

    `500 Sermaye` `equity`dir (MT-1/KK-1'in acti gi besinci uye); `liability`
    olsaydi bilanco `III. OZKAYNAKLAR` bolumunu `I. KISA VADELI`den ayiramazdi.

    `621 Satilan Ticari Mallar Maliyeti (-)` ise `expense`tir — ve SINIF 6 hem
    geliri (`600 Yurt Ici Satislar` → `revenue`) hem gideri tasir. "Ilk hane 6
    ise gelirdir" gibi bir turetim gelir tablosunu ters cevirirdi.
    """
    conn = await asyncpg.connect(_asyncpg_dsn(tohumlu_db))
    try:
        sermaye = await _hesap(conn, "500")
        assert sermaye is not None
        assert sermaye["account_type"] == "equity"

        maliyet = await _hesap(conn, "621")
        assert maliyet is not None
        assert maliyet["account_type"] == "expense", (
            "SINIF 6 hem geliri hem gideri tasir — tur sinifin ilk hanesinden TURETILEMEZ"
        )

        satis = await _hesap(conn, "600")
        assert satis is not None
        assert satis["account_type"] == "revenue"
    finally:
        await conn.close()


# --------------------------------------------------------------------------- #
# 6 — upgrade → downgrade → upgrade turu
# --------------------------------------------------------------------------- #


async def test_upgrade_downgrade_upgrade_round_trip() -> None:
    """🔴 IKINCI `upgrade` PATLAMAZ.

    `ON CONFLICT (code) DO NOTHING` + "yalniz tohum kodlarini sil" ikilisi bu
    turu kapatir. Downgrade tohumu birakip gitseydi ikinci upgrade sessizce
    gecerdi (idempotens sayesinde) ama SATIR SAYISI kayardi; upgrade
    idempotent olmasaydi yarim kalmis bir deploy'un ardindan gelen ikinci
    `alembic upgrade head` unique ihlaliyle patlar ve uvicorn HIC baslamazdi.
    """
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", MU_SEED_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _hesap_sayisi(conn) == BEKLENEN_SATIR
        finally:
            await conn.close()

        _run_alembic("downgrade", PREV_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _current_revision(conn) == PREV_REVISION
            assert await _hesap_sayisi(conn) == 0, "downgrade tohumu birakmis"
            for komsu in KOMSU_TABLOLAR:
                assert await conn.fetchval("SELECT to_regclass($1) IS NOT NULL", f"public.{komsu}")
        finally:
            await conn.close()

        # 🔴 ASIL IDDIA: ikinci upgrade PATLAMADAN gecer ve sayim geri gelir.
        _run_alembic("upgrade", MU_SEED_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _current_revision(conn) == MU_SEED_REVISION
            assert await _hesap_sayisi(conn) == BEKLENEN_SATIR
            assert await _kontra_sayisi(conn) == BEKLENEN_KONTRA
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


# --------------------------------------------------------------------------- #
# 7 — K6 ustune yazmama, MIGRATION yolundan
# --------------------------------------------------------------------------- #


async def test_kullanicinin_kendi_actigi_tohum_kodunun_USTUNE_YAZILMAZ() -> None:
    """🔴 K6 — `ON CONFLICT DO NOTHING`, `DO UPDATE` DEGIL; ve iddia MIGRATION
    yolundan gecer (uygulama servisinden degil).

    Kullanici `100`u kendi adiyla/turuyle acmissa `alembic upgrade` onu
    EZMEMELIDIR: `DO UPDATE` yazilsaydi kullanicinin duzelttigi ad/tur/kontra
    HER deploy'da TDHP varsayilanina donerdi ve bunu kimse fark etmezdi.
    Ayrica cift satir da dogmamalidir — toplam yine 316'dir.
    """
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", MU_SEED_REVISION, database=database)
        _run_alembic("downgrade", PREV_REVISION, database=database)

        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            await conn.execute(
                f"INSERT INTO {TABLE} (id, code, name, account_type, is_contra) "
                f"VALUES ($1, '100', 'Merkez Kasasi', 'liability', true)",
                uuid.uuid4(),
            )
        finally:
            await conn.close()

        _run_alembic("upgrade", MU_SEED_REVISION, database=database)

        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            kasa = await _hesap(conn, "100")
            assert kasa is not None
            assert kasa["name"] == "Merkez Kasasi", (
                "kullanicinin adi TDHP varsayilaniyla EZILDI — ON CONFLICT DO UPDATE olmus olabilir"
            )
            assert kasa["account_type"] == "liability"
            assert kasa["is_contra"] is True
            assert await conn.fetchval(f"SELECT count(*) FROM {TABLE} WHERE code = '100'") == 1
            assert await _hesap_sayisi(conn) == BEKLENEN_SATIR
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


# --------------------------------------------------------------------------- #
# 8 — K7 VERI KAPISI
# --------------------------------------------------------------------------- #


async def test_downgrade_fis_satiri_varken_DURUR_ve_semayi_BOZMAZ() -> None:
    """🔴 K7 — YARIM DOWNGRADE, TAM DOWNGRADE'DEN DAHA KOTUDUR.

    `journal_lines.account_id` RESTRICT'tir: fis satiri tasiyan bir tohum
    hesabini korukorune silmek ham bir FK hatasi verir ve migration YARIM
    kalirdi (bir kismi silinmis hesap plani + kaymis `alembic_version`).
    Downgrade bu yuzden ONCE SORAR ve `RuntimeError` ile DURUR.

    Iddia iki parcalidir: (1) `returncode != 0`, (2) sema BOZULMADAN kalir —
    `alembic_version` hala `e5f6a7b8c9d0` VE hesap sayisi hala 316 (TEK SATIR
    bile silinmemis).

    ⚠️ Surume ozgu SQLSTATE iddia edilmez (yerel PG 18 / CI PG 16).
    """
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", MU_SEED_REVISION, database=database)

        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            await _dengeli_fis_yaz(conn, borc_kodu="100", alacak_kodu="600")
        finally:
            await conn.close()

        sonuc = _run_alembic_expecting_failure("downgrade", PREV_REVISION, database=database)
        assert sonuc.returncode != 0, (
            "fis satiri olan tohum hesabi varken downgrade SESSIZCE gecti:\n" + sonuc.stdout
        )
        assert "downgrade durduruldu" in (sonuc.stdout + sonuc.stderr)

        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _current_revision(conn) == MU_SEED_REVISION
            assert await _hesap_sayisi(conn) == BEKLENEN_SATIR, (
                "kapi devreye girdi ama satirlarin bir kismi ZATEN silinmis — yarim downgrade"
            )
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


# --------------------------------------------------------------------------- #
# 9 — downgrade yalniz TOHUMU siler
# --------------------------------------------------------------------------- #


async def test_downgrade_yalniz_tohumu_siler_kullanici_hesabi_SAG_KALIR() -> None:
    """🔴 Downgrade `DELETE FROM chart_of_accounts` YAZMAZ.

    Emsal `a477fdf00fdf`in kapisiz `DELETE FROM roles` supurmesi BURADA
    yanlistir: kullanicinin kendi actigi `999` bu migration'in mali degildir ve
    silinmesi geri alinamaz bir veri kaybi olurdu. Komsu tablolarin da ayakta
    kaldigi olculur — bu dilim yalniz `chart_of_accounts` SATIRLARINA dokunur,
    hicbir seyi DROP ETMEZ.
    """
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", MU_SEED_REVISION, database=database)

        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            await conn.execute(
                f"INSERT INTO {TABLE} (id, code, name, account_type) "
                f"VALUES ($1, $2, 'Ozel Santiye Hesabi', 'expense')",
                uuid.uuid4(),
                KULLANICI_KODU,
            )
            assert await _hesap_sayisi(conn) == BEKLENEN_SATIR + 1
        finally:
            await conn.close()

        _run_alembic("downgrade", PREV_REVISION, database=database)

        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            kullanici_hesabi = await _hesap(conn, KULLANICI_KODU)
            assert kullanici_hesabi is not None, (
                "kullanicinin kendi actigi hesap downgrade'de SILINDI — veri kaybi"
            )
            assert kullanici_hesabi["name"] == "Ozel Santiye Hesabi"
            assert await _hesap_sayisi(conn) == 1
            for komsu in KOMSU_TABLOLAR:
                assert await conn.fetchval("SELECT to_regclass($1) IS NOT NULL", f"public.{komsu}")
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)
