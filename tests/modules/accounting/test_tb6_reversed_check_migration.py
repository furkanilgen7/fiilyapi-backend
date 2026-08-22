"""TB6 T2 — denge CHECK'ini genisleten migration turu (`e9f0a1b2c3d4`).

## 🔴 NEDEN AYRI BIR TUR DONUSU TESTI

`Dockerfile` acilista `alembic upgrade head && uvicorn ...` kosar; migration
patlarsa `&&` kisa devre yapar ve **uvicorn HIC BASLAMAZ (tam kesinti)**.
Downgrade eski kisiti geri kurmazsa ikinci `upgrade` de patlar
("constraint already exists"). Bu yuzden tur `upgrade → downgrade → upgrade`
olarak KOSULUR, iddia edilmez.

## 🔴 MIGRATION ARTIK HIC DURMAZ — OLCULEN SEY BUDUR

Migration'in ILK hâli kisiti eklemeden ONCE ihlal sayiyor, sayim sifir degilse
`RuntimeError` firlatiyordu; bu dosyanin eski hâli de "kirli DB'de upgrade ACIK
MESAJLA DURUR" diye o davranisa bekcilik ediyordu. **O IDDIA GERI ALINDI:**
durmak, tam olarak kacinilmak istenen kesintinin TA KENDISIYDI (tek ihlal satiri
uvicorn'u hic baslatmazdi). Yeni davranis `ADD CONSTRAINT ... NOT VALID` +
KOSULLU `VALIDATE`tir ve bu dosya artik su dort olguyu FIILEN kurar:

1. **kirli DB'de `upgrade` BASARIYLA biter** — revizyon ilerler, kisit
   `convalidated = f` olarak durur, WARNING satiri deploy gunlugune duser ve
   **yalniz SATIR SAYISI yazar** (tutar/kimlik/tarih SIZMAZ — ayri bekci);
2. **`NOT VALID` iken YENI ihlal REDDEDILIR** (`23514`) — bu dilimin KALBI:
   `NOT VALID` "hicbir seyi engellemez" DEGILDIR, yalniz GECMIS satirlari
   taramaz; INSERT ve UPDATE tam enforce edilir;
3. **temiz DB'de kisit TAM DOGRULANMIS biter** (`convalidated = t`) — duz
   `ADD CONSTRAINT` ile ayni guvence;
4. **kirli DB'de `downgrade` PATLAMAZ** — eski kisit TARANARAK geri gelir cunku
   yeninin GEVSEK bir alt kumesidir.

## 🔴 KOSULLU `VALIDATE`IN IKI PREMISI TESTE BAGLIDIR

Migration "sayim 0 ise `VALIDATE` patlayamaz" diyor. Bu bir SAV degil, iki
olcuye dayanir ve ikisi de burada, GERCEK Postgres uzerinde, `status ×
total_debit × total_credit` truth-table'i uzerinde kosar
(`test_KAPSAMA_ve_SAYIM_DENKLIGI_gercek_SQL_ile_olculur`):

* **kapsama**: `NEW`in reddettigi kume `OLD`unkini ORTER → eski kisiti dusurmek
  hicbir sey kaybettirmez;
* **denklik**: `COUNT_SQL`in yuklemi ile `NEW`in RED kumesi BIREBIR aynidir →
  "sayim 0" gercekten "VALIDATE patlayamaz" demektir.

SQL ifadeleri migration modulunden **ITHAL EDILIR** (`OLD_SQL`/`NEW_SQL`/
`COUNT_SQL`), elle KOPYALANMAZ: kopyalansaydi migration degistiginde test onunla
birlikte kaymaz ve bekcilik etmezdi.

⚠️ CHECK semantigi: ifade **FALSE** ise satir reddedilir, **NULL GECER.** Test
bunu `IS FALSE` / `IS NOT FALSE` ile modeller; `NOT (...)` ile modellenseydi
NULL'lar sessizce yanlis tarafa duser ve sahte yesil verirdi.

Test kendi TEK KULLANIMLIK veritabanini acar ve sonunda dusurur; `.env` ve
`TEST_DATABASE_URL` veritabani ELLENMEZ (`test_mt1_ozkaynak_kontra_migration`
deseni). Revizyonlara ACIKCA cikilir; `head` / `-1` KULLANILMAZ.
"""

import importlib.util
import itertools
import os
import subprocess
import sys
import uuid
from decimal import Decimal
from pathlib import Path

import asyncpg
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.accounting import balance
from app.modules.accounting.models import BALANCE_ENFORCED_STATUSES, POSTING_BALANCED_CHECK
from app.modules.accounting.numbering import format_entry_no

BACKEND_DIR = Path(__file__).parents[3]
ALEMBIC_CMD = (sys.executable, "-m", "alembic")

#: 🔴 EBEVEYN revizyon. Adi `PARENT_REVISION` DEGIL: re-parent sonrasi bu sabit
#: FIS-NO'nun id'sini tutuyor ve eski ad YALAN soylerdi (P6 emsali:
#: `PARENT_REVISION`). `tests/modules/treasury/test_fin1_migration.py`deki
#: ayni isimli sabit FIN-1'IN KENDI testidir, o DOKUNULMADI.
PARENT_REVISION = "f150c0117e42"
TB6_REVISION = "e9f0a1b2c3d4"

TABLE = "journal_entries"
OLD_NAME = "ck_journal_entries_posted_balanced"
NEW_NAME = "ck_journal_entries_posting_balanced"

#: PG'nin CHECK ihlali sinifi. Tek elemanli ama TUPLE'dir (`test_tb6_reversed_
#: balanced_check` ile AYNI kanon, PG 18/16 farki): sinif kodu surume gore
#: genislerse burasi OLCULEREK buyutulur, ata sinifa GEVSETILMEZ.
CHECK_VIOLATION = ("23514",)

MIGRATION_PATH = (
    BACKEND_DIR / "alembic" / "versions" / "e9f0a1b2c3d4_tb6_dengesiz_reversed_check.py"
)


def _load_migration_module():
    """Migration modulunu ADIYLA yukler — `alembic/versions` bir paket DEGILDIR."""
    spec = importlib.util.spec_from_file_location("tb6_mig", MIGRATION_PATH)
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


MIG = _load_migration_module()

#: 🔴 ITHAL, KOPYA DEGIL. Elle kopyalansalardi migration'in SQL'i degistiginde
#: test ESKI metni olcmeye devam eder ve bekci sessizce olurdu.
OLD_SQL = MIG.OLD_SQL
NEW_SQL = MIG.NEW_SQL

#: `COUNT_SQL` bir SELECT'tir; bekcilik edilecek olan onun YUKLEMIDIR. Yuklem
#: metinden SOKULUR (yine kopyalanmaz): `WHERE`den sonrasi.
COUNT_PREDICATE = str(MIG.COUNT_SQL).split(" WHERE ", 1)[1]

# --------------------------------------------------------------------------- #
# Kirli satirin degerleri — ayni zamanda SIZINTI BEKCISININ nisan tahtasi
# --------------------------------------------------------------------------- #
KIRLI_TARIH = "2026-07-17"
KIRLI_YIL = 2026
KIRLI_BORC = Decimal("500.00")
KIRLI_ALACAK = Decimal("0.00")

#: 🔴 FIS-NO RE-PARENT SONRASI ZORUNLU. Ebeveyn artik `f150c0117e42` ve o
#: migration `journal_entries.entry_no`yu **NOT NULL + UNIQUE** yapar. Bu dosya
#: fisleri HAM SQL ile yazar (servis katmani HIC devrede degil), yani sunucunun
#: uretecisi kosmaz -> numarayi testin KENDISI vermek zorundadir. Verilmeseydi
#: INSERT'ler `23502` ile patlar ve `NOT VALID` bekcileri `23514` bekledigi icin
#: **YANLIS SEBEPLE** kirmiziya donerdi (sahte-yesilin aynadaki hâli).
#:
#: 🔴 UNIQUE **kolonun genelindedir** (`uq_journal_entries_entry_no`), yil bazli
#: DEGIL -> sayac global ve monotondur. Bicim `numbering.format_entry_no`tan
#: ITHAL EDILIR, elle yazilmaz: FIS-NO bicimi TEK yerde kurar (backfill, uretici
#: ve testler ayni kurali okur); burada kopyalansaydi `SEQUENCE_WIDTH` degisimi
#: bu dosyayi sessizce ayristirirdi.
_entry_no_sayaci = itertools.count(1)


def _yeni_entry_no() -> str:
    return format_entry_no(KIRLI_YIL, next(_entry_no_sayaci))


_INSERT_SQL = (
    "INSERT INTO journal_entries "
    "(id, entry_date, period_year, period_month, description, status, "
    " total_debit, total_credit, created_by_id, entry_no) "
    f"VALUES (gen_random_uuid(), DATE '{KIRLI_TARIH}', {KIRLI_YIL}, 7, 'TB6 mig probu', "
    "$1::journal_entry_status, $2::numeric, $3::numeric, $4, $5)"
)


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
    database = f"accounting_tb6_{uuid.uuid4().hex[:8]}"
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
    return await conn.fetchval(
        "INSERT INTO users (id, email, password_hash, full_name, title, role_id, status) "
        "SELECT gen_random_uuid(), 'tb6@mig.co', 'x', 'TB6', 'Test', id, 'active' "
        "FROM roles LIMIT 1 RETURNING id"
    )


async def _fis_yaz(
    conn: asyncpg.Connection,
    kullanici_id: uuid.UUID,
    *,
    status: str,
    borc: Decimal,
    alacak: Decimal,
) -> uuid.UUID:
    return await conn.fetchval(
        _INSERT_SQL + " RETURNING id", status, borc, alacak, kullanici_id, _yeni_entry_no()
    )


async def _kirli_db_kur(database: str) -> uuid.UUID:
    """FIN-1'e cikar ve ESKI kisitin (yasal olarak) gecirdigi dengesiz bir
    `reversed` satir birakir — TB6'nin kapattigi delik tam olarak budur."""
    _run_alembic("upgrade", PARENT_REVISION, database=database)
    conn = await asyncpg.connect(_asyncpg_dsn(database))
    try:
        kullanici_id = await _kullanici_yaz(conn)
        return await _fis_yaz(
            conn, kullanici_id, status="reversed", borc=KIRLI_BORC, alacak=KIRLI_ALACAK
        )
    finally:
        await conn.close()


async def _reddedilir(conn: asyncpg.Connection, sql: str, *args: object) -> None:
    """Yazma `23514` ile ve ADI GECEN kisit yuzunden reddedilmelidir."""
    with pytest.raises(asyncpg.PostgresError) as hata:
        await conn.execute(sql, *args)
    assert hata.value.sqlstate in CHECK_VIOLATION, hata.value
    assert NEW_NAME in str(hata.value), hata.value


# --------------------------------------------------------------------------- #
# Sembolik katman — migration'in SQL'i ile modelin SQL'i BUGUN ESITTIR
# --------------------------------------------------------------------------- #


def test_migration_parent_is_the_expected_revision():
    """Iki head = canlida deploy kilitlenmesi (`alembic upgrade head` patlar).

    🔴 **UYARLANDI (OK-1A T2).** Eski hâlin ikinci iddiasi
    `script.get_heads() == [TB6_REVISION]` idi, yani "TB6 head'dir". Bu iddia
    TB6'nin uzerine BIR MIGRATION DAHA indigi anda kirilir ve OK-1A'da kirildi
    — ama kirilma bir KUSURU degil, ZAMANIN GECMESINI gosteriyordu.

    Korunmasi gereken invariant "TB6 head'dir" DEGIL, **"head TEKTIR"**dir:
    canliyi kilitleyen sey cift head'tir. Yeni hâl bunu iddia eder ve ustune
    TB6'nin zincirde HALA DURDUGUNU (head'in atalari arasinda oldugunu)
    ekler — yani bu dilimin migration'i sessizce zincir disi kalmaz.

    Ebeveyn iddiasi (`down_revision == PARENT_REVISION`) AYNEN korundu: TB6'nin
    kendi baglantisi bu dilimin sorumlulugudur ve re-parent gerekirse burasi
    yine kirilir.
    """
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(str(BACKEND_DIR / "alembic.ini")))
    assert script.get_revision(TB6_REVISION).down_revision == PARENT_REVISION

    heads = list(script.get_heads())
    assert len(heads) == 1, f"tek head bekleniyordu: {heads}"
    ataler = {rev.revision for rev in script.iterate_revisions(heads[0], "base")}
    assert TB6_REVISION in ataler, "TB6 migration'i zincirden dusmus"


def test_migration_SQL_i_modelin_SQL_i_ile_AYNI():
    """🔴 Migration modelden ITHAL ETMEZ (gecmis donmus olmalidir) — o hâlde
    ikisinin BUGUN esit oldugu AYRICA olculur. Ayrisirlarsa `create_all` ile
    kurulan test semasi ile `alembic upgrade` ile kurulan canli sema FARKLI
    davranir ve suite bunu HIC gormez."""
    assert MIG.NEW_SQL == POSTING_BALANCED_CHECK
    assert MIG.NEW_NAME == NEW_NAME
    assert MIG.OLD_NAME == OLD_NAME
    assert MIG.TABLE == TABLE
    for durum in BALANCE_ENFORCED_STATUSES:
        assert f"'{durum}'" in MIG.NEW_SQL
    assert {d.value for d in balance.POSTING_STATUSES} == set(BALANCE_ENFORCED_STATUSES)


# --------------------------------------------------------------------------- #
# Kosullu VALIDATE'in IKI PREMISI — gercek Postgres uzerinde truth-table
# --------------------------------------------------------------------------- #

#: `status` gercek tabloda NOT NULL'dir; NULL yine de olculur cunku premis
#: NULL'lar icin de tutmak ZORUNDADIR (kolon ileride nullable olursa bekci
#: kendiliginden konusur). `total_debit`/`total_credit` de bugun NOT NULL.
DURUMLAR: tuple[str | None, ...] = ("posted", "reversed", "draft", None)
TUTARLAR: tuple[str | None, ...] = ("100.00", "200.00", None)

#: 4 × 3 × 3 = 36 kombinasyon (sefin 27'lik olcumunun UST kumesi).
KOMBINASYON_SAYISI = len(DURUMLAR) * len(TUTARLAR) * len(TUTARLAR)

#: Sefin gercek Postgres uzerinde olctugu sayilar — suite'e KILITLENIR.
YENI_RED_SAYISI = 4
ESKI_RED_SAYISI = 2


def _literal(deger: str | None, tip: str) -> str:
    return f"CAST(NULL AS {tip})" if deger is None else f"CAST('{deger}' AS {tip})"


def _truth_table_sql() -> str:
    satirlar = ", ".join(
        f"({_literal(durum, 'text')}, {_literal(borc, 'numeric')}, {_literal(alacak, 'numeric')})"
        for durum in DURUMLAR
        for borc in TUTARLAR
        for alacak in TUTARLAR
    )
    return f"""
        WITH kombinasyon(status, total_debit, total_credit) AS (VALUES {satirlar})
        SELECT
            count(*) AS toplam,
            count(*) FILTER (WHERE ({OLD_SQL}) IS FALSE) AS eski_red,
            count(*) FILTER (WHERE ({NEW_SQL}) IS FALSE) AS yeni_red,
            count(*) FILTER (
                WHERE ({OLD_SQL}) IS FALSE AND ({NEW_SQL}) IS NOT FALSE
            ) AS kapsama_ihlali,
            count(*) FILTER (
                WHERE (({COUNT_PREDICATE}) IS TRUE) IS DISTINCT FROM (({NEW_SQL}) IS FALSE)
            ) AS uyumsuzluk
        FROM kombinasyon
    """


async def test_KAPSAMA_ve_SAYIM_DENKLIGI_gercek_SQL_ile_olculur(db_session: AsyncSession) -> None:
    """🔴 KOSULLU `VALIDATE`IN IKI DAYANAGI — ikisi de burada olculur.

    (a) **KAPSAMA**: `OLD`un reddettigi her satiri `NEW` de reddeder
        (`kapsama_ihlali = 0`). Bu tutmasaydi eski kisiti dusurmek bir seyi
        KAYBETTIRIRDI ve migration sessizce gevserdi.
    (b) **DENKLIK**: `COUNT_SQL`in yuklemi ile `NEW`in RED kumesi BIREBIR
        aynidir (`uyumsuzluk = 0`). Bu tutmasaydi "sayim 0" -> "VALIDATE
        guvenli" cikarimi COKERDI: sayim goremedigi bir satir yuzunden
        `VALIDATE` patlar, migration coker, uvicorn hic baslamazdi.

    Ayrica sefin sayilari kilitlenir: yeni kisit 4, eski kisit 2 satir reddeder
    — yani yeni kisit KESIN OLARAK daha gucludur.

    ⚠️ Yuklemler `NOT (...)` ile DEGIL `IS FALSE` / `IS NOT FALSE` ile
    modellenir: CHECK yalniz FALSE'ta reddeder, NULL GECER.
    """
    satir = (await db_session.execute(sa.text(_truth_table_sql()))).one()

    assert satir.toplam == KOMBINASYON_SAYISI
    assert satir.kapsama_ihlali == 0, "NEW, OLD'un reddettigi bir satiri KACIRIYOR"
    assert satir.uyumsuzluk == 0, "COUNT_SQL ile CHECK'in RED kumesi AYRISTI"
    assert satir.yeni_red == YENI_RED_SAYISI
    assert satir.eski_red == ESKI_RED_SAYISI
    assert satir.yeni_red > satir.eski_red


# --------------------------------------------------------------------------- #
# Gercek zincir — TEMIZ veritabani
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_upgrade_downgrade_upgrade_round_trip():
    """Kisit ADI da degisti: downgrade eskisini geri kurmazsa ikinci upgrade
    `drop_constraint` asamasinda "does not exist" ile patlar.

    🔴 Ayrica: TEMIZ bir veritabaninda kisit **TAM DOGRULANMIS** biter
    (`convalidated = t`) ve bunu `VALIDATE_LOG_PREFIX` satiri deploy gunlugune
    soyler. `NOT VALID` eklemek TEK BASINA bir gevsemedir; onu geri alan sey
    kosullu `VALIDATE`tir ve HER IKI upgrade'den sonra da olculur.
    """
    database = await _create_scratch_database()
    try:
        sonuc = _run_alembic("upgrade", TB6_REVISION, database=database)
        assert MIG.VALIDATE_LOG_PREFIX in _cikti(sonuc)
        assert MIG.SKIP_VALIDATE_LOG_PREFIX not in _cikti(sonuc)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _current_revision(conn) == TB6_REVISION
            yeni = await _constraint_sql(conn, NEW_NAME)
            assert yeni is not None
            # PG kisit metnini yeniden yazar; kume uyeligi yine de okunabilir.
            assert "reversed" in yeni and "posted" in yeni
            assert await _constraint_sql(conn, OLD_NAME) is None
            assert await _convalidated(conn, NEW_NAME) is True
        finally:
            await conn.close()

        _run_alembic("downgrade", PARENT_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _current_revision(conn) == PARENT_REVISION
            eski = await _constraint_sql(conn, OLD_NAME)
            assert eski is not None
            assert "reversed" not in eski
            assert await _constraint_sql(conn, NEW_NAME) is None
            # Downgrade duz `ADD CONSTRAINT` kurar: taranir ve dogrulanmis biter.
            assert await _convalidated(conn, OLD_NAME) is True
        finally:
            await conn.close()

        sonuc = _run_alembic("upgrade", TB6_REVISION, database=database)
        assert MIG.VALIDATE_LOG_PREFIX in _cikti(sonuc)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _current_revision(conn) == TB6_REVISION
            assert await _constraint_sql(conn, NEW_NAME) is not None
            assert await _convalidated(conn, NEW_NAME) is True
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


# --------------------------------------------------------------------------- #
# Gercek zincir — KIRLI veritabani (dengesiz `reversed` satir VAR)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_KIRLI_DB_de_upgrade_BASARIYLA_KOSAR_ve_VALIDATE_ATLANIR():
    """🔴 ESKI IDDIA GERI ALINDI: kirli DB'de migration ARTIK DURMAZ.

    Onceki hâli `returncode != 0` ve "sema FIN-1'de kaldi" iddia ediyordu. O
    davranis `Dockerfile`in `alembic upgrade head && uvicorn ...` zincirinde
    **TEK ihlal satiri yuzunden TAM KESINTI** demekti. Yeni davranis: kisit
    `NOT VALID` girer, sayim kilit altinda kosar, ihlal varsa `VALIDATE`
    ATLANIR ve migration BASARIYLA biter.

    🔴 SIZINTI BEKCISI: deploy gunlugu MALI VERI SIZDIRMAZ. Satir SAYISI
    yazilir; fisin TUTARI, KIMLIGI ve TARIHI yazilmaz.
    """
    database = await _create_scratch_database()
    try:
        kirli_id = await _kirli_db_kur(database)

        sonuc = _run_alembic("upgrade", TB6_REVISION, database=database)
        assert sonuc.returncode == 0
        cikti = _cikti(sonuc)

        # Atlama SESSIZ DEGIL: greplenebilir imza + satir sayisi.
        assert MIG.SKIP_VALIDATE_LOG_PREFIX in cikti
        assert "1 adet DENGESIZ" in cikti
        assert MIG.VALIDATE_LOG_PREFIX not in cikti

        # 🔴 SIZINTI BEKCISI — bu uc deger gunluge ASLA dusmez.
        for sizinti in (str(KIRLI_BORC), "500", str(kirli_id), KIRLI_TARIH):
            assert sizinti not in cikti, f"deploy gunlugune mali veri sizdi: {sizinti}"

        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            # Yarim gecis YOK: revizyon ilerledi.
            assert await _current_revision(conn) == TB6_REVISION
            assert await _constraint_sql(conn, NEW_NAME) is not None
            assert await _constraint_sql(conn, OLD_NAME) is None
            # VALIDATE atlandi -> kisit gecmis satirlar icin DOGRULANMAMIS.
            assert await _convalidated(conn, NEW_NAME) is False

            # Migration VERIYE DOKUNMAZ: kirli satir AYNEN durur.
            satir = await conn.fetchrow(
                "SELECT status::text AS status, total_debit, total_credit "
                "FROM journal_entries WHERE id = $1",
                kirli_id,
            )
            assert satir is not None
            assert satir["status"] == "reversed"
            assert satir["total_debit"] == KIRLI_BORC
            assert satir["total_credit"] == KIRLI_ALACAK
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


@pytest.mark.asyncio
async def test_KIRLI_DB_de_NOT_VALID_KISIT_YENI_IHLALI_REDDEDER():
    """🔴 BU DILIMIN KALBI — `NOT VALID` "hicbir seyi engellemez" DEGILDIR.

    `NOT VALID`in tek gevsemesi MEVCUT satirlari TARAMAMASIDIR; INSERT ve
    UPDATE'ler TAM enforce edilir. Bu olculmezse dilim "kisit eklendi ama
    ise yaramiyor" diye yanlis okunur ve delik acik sanilir.

    Ayni testte SINIRLAR da olculur: kisit storno akisini TIKAMAZ (dengeli
    `reversed` GECER) ve taslagi BAGLAMAZ (dengesiz `draft` GECER).
    """
    database = await _create_scratch_database()
    try:
        kirli_id = await _kirli_db_kur(database)
        _run_alembic("upgrade", TB6_REVISION, database=database)

        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _convalidated(conn, NEW_NAME) is False
            kullanici_id = await conn.fetchval("SELECT id FROM users LIMIT 1")

            # 1) Dengesiz `reversed` INSERT -> RED. TB6'nin kapattigi delik.
            await _reddedilir(
                conn,
                _INSERT_SQL,
                "reversed",
                Decimal("500.00"),
                Decimal("0.00"),
                kullanici_id,
                _yeni_entry_no(),
            )
            # 2) Dengesiz `posted` INSERT -> RED (eski kisitin kapsami KAYBOLMADI).
            await _reddedilir(
                conn,
                _INSERT_SQL,
                "posted",
                Decimal("500.00"),
                Decimal("0.00"),
                kullanici_id,
                _yeni_entry_no(),
            )

            # 3) Dengeli `reversed` GECER — storno akisi TIKANMAZ.
            temiz_id = await _fis_yaz(
                conn,
                kullanici_id,
                status="reversed",
                borc=Decimal("500.00"),
                alacak=Decimal("500.00"),
            )
            # 4) Dengesiz `draft` GECER — yarim fis KAYDEDILEBILIR.
            await _fis_yaz(
                conn,
                kullanici_id,
                status="draft",
                borc=Decimal("500.00"),
                alacak=Decimal("0.00"),
            )

            # 5) TEMIZ satiri ihlale ceviren UPDATE -> RED.
            await _reddedilir(
                conn,
                "UPDATE journal_entries SET total_credit = 0 WHERE id = $1",
                temiz_id,
            )
            # 6) 🔴 KIRLI satira DOKUNAN UPDATE de RED: `NOT VALID` mevcut
            #    satirlara KALICI muafiyet VERMEZ, yalniz taramayi atlar.
            await _reddedilir(
                conn,
                "UPDATE journal_entries SET description = 'dokunuldu' WHERE id = $1",
                kirli_id,
            )
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


@pytest.mark.asyncio
async def test_KIRLI_DB_de_downgrade_PATLAMAZ_eski_kisit_TARANARAK_geri_gelir():
    """Geri donus yolu kirli veriyle de ACIK olmak ZORUNDA.

    `downgrade` eski kisiti duz `ADD CONSTRAINT` ile kurar, yani TABLOYU
    TARAR. Dengesiz `reversed` satir eski kisiti GECER (`status <> 'posted'`
    dogrudur) — bu yuzden tarama patlamaz ve eski kisit DOGRULANMIS
    (`convalidated = t`) biter. Tutmasaydi kirli bir canlida geri donus
    imkânsiz olurdu.
    """
    database = await _create_scratch_database()
    try:
        kirli_id = await _kirli_db_kur(database)
        _run_alembic("upgrade", TB6_REVISION, database=database)

        sonuc = _run_alembic("downgrade", PARENT_REVISION, database=database)
        assert sonuc.returncode == 0

        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _current_revision(conn) == PARENT_REVISION
            assert await _constraint_sql(conn, NEW_NAME) is None
            assert await _constraint_sql(conn, OLD_NAME) is not None
            assert await _convalidated(conn, OLD_NAME) is True
            # Kirli satir hâlâ yerinde: downgrade de VERIYE DOKUNMAZ.
            assert (
                await conn.fetchval("SELECT count(*) FROM journal_entries WHERE id = $1", kirli_id)
                == 1
            )
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)
