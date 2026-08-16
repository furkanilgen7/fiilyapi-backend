"""MT-1 T2 — `equity` enum üyesi + `is_contra` kolonu: model katmanı + migration turu.

🔑 **KULLANICI KARARI (2026-08-16, KK-1 — TAM TDHP UYUMU).** MU-1 `models.py:152`
*"Beşinci üye İCAT EDİLMEZ"* kanonunu yazmıştı; bu dilim onu **bilinçli olarak
iptal eder**. Gerekçe: Bilanço'nun `III. ÖZKAYNAKLAR` bölümü (BL:80-84) dört
üyeli enum'la ifade edilemiyor — `500 Sermaye` bir yükümlülük DEĞİLDİR ve
`liability` sayılması hesap planı ekranında yanlış rozet basardı. Aynı kararla
`is_contra` kolonu da açıldı: `257 Birikmiş Amortismanlar (-)` `Maddi Duran
Varlıklar (net)` satırından **DÜŞÜLMEK** zorundadır (BL:57 = 2.400.000 +
1.840.000 − 620.000 = 3.620.000) ve `(-)` son eki bir SUNUM kuralı olarak
kalsaydı sunucu netlemeyi hiç yapamazdı.

## 🔴 NEDEN AYRI BİR TUR DÖNÜŞÜ TESTİ

Postgres'te **`ALTER TYPE … ADD VALUE` GERİ ALINAMAZ.** `DROP TYPE` ile
düşürüp yeniden kurmak zorunludur; downgrade bunu yapmazsa ikinci `upgrade`
"type already exists" / "value already exists" ile patlar ve bu **YALNIZ
CANLIDA** görülür: `Dockerfile` açılışta `alembic upgrade head` koşar, patlarsa
uvicorn hiç başlamaz (**tam kesinti**). Emsal `d4e5f6a7b8c9` ve
`test_mu2_periods_migration.py`.

## 🔴 `sign_case()` `else_` DALI YOK — `SIGN` eksikse **NULL**

`balance.py:151-160` `else_` dalını BİLEREK yazmamıştır. Enum'a beşinci üye
eklenip `SIGN`a eklenmezse `CASE` hiçbir dala düşmez, **NULL** üretir ve
`Numeric` alan `None` olarak Pydantic'e gider. Bu dosya kusuru **fiilen kurar**
(`SIGN`dan `equity` çıkarılır) ve NULL'ın DOĞDUĞUNU ölçer — "girdi var" demek
"bekçilik ediyor" demek değildir.

Test kendi TEK KULLANIMLIK veritabanını açar ve sonunda düşürür; `.env` ve
`TEST_DATABASE_URL` veritabanı ELLENMEZ. Alembic alt süreçte koşturulur
(`alembic/env.py` kendi `asyncio.run()` döngüsünü kurar — MU-1/MU-2 deseni).

⚠️ PG SÜRÜM TUZAĞI: yerel 18, CI 16 — sürüme özgü SQLSTATE iddia edilmez.
"""

import os
import subprocess
import sys
import uuid
from pathlib import Path

import asyncpg
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.accounting import balance
from app.modules.accounting.models import ChartAccount, ChartAccountType, JournalEntryStatus

BACKEND_DIR = Path(__file__).parents[3]
ALEMBIC_CMD = (sys.executable, "-m", "alembic")

# Revizyonlara AÇIKÇA çıkılır; `head` / `-1` KULLANILMAZ.
MU2_REVISION = "c7d8e9f0a1b2"
MT1_REVISION = "c8d9e0f1a2b3"

TABLE = "chart_of_accounts"
ENUM = "chart_account_type"
COLUMN = "is_contra"

#: KK-1 sonrası KAPALI küme. Sıra ÖNEMLİDİR: `ALTER TYPE … ADD VALUE` üyeyi
#: SONA ekler, `enum_range` da o sırayı döner.
EXPECTED_ENUM_LABELS = ["asset", "liability", "revenue", "expense", "equity"]

#: Downgrade'in geri döneceği MU-1 kümesi — dört üye.
MU2_ENUM_LABELS = ["asset", "liability", "revenue", "expense"]

HESAP_YOLU = "/chart-of-accounts"


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


async def _enum_labels(conn: asyncpg.Connection, name: str) -> list[str]:
    return await conn.fetchval("SELECT enum_range(NULL::" + name + ")::text[]")


async def _column_exists(conn: asyncpg.Connection, table: str, column: str) -> bool:
    return await conn.fetchval(
        "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
        "WHERE table_name = $1 AND column_name = $2)",
        table,
        column,
    )


async def _current_revision(conn: asyncpg.Connection) -> str | None:
    return await conn.fetchval("SELECT version_num FROM alembic_version")


async def _create_scratch_database() -> str:
    database = f"accounting_mt1_{uuid.uuid4().hex[:8]}"
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


# --------------------------------------------------------------------------- #
# Model katmani — enum
# --------------------------------------------------------------------------- #


def test_account_type_enum_has_equity_member():
    """🔑 KK-1: `equity` üyesi AÇILDI (MU-1'in "beşinci üye icat edilmez"
    kanonunun BİLİNÇLİ iptali). Sıra kilitlidir çünkü `ALTER TYPE … ADD VALUE`
    üyeyi SONA ekler ve DB'deki sıra buradan doğrulanır."""
    assert [e.value for e in ChartAccountType] == EXPECTED_ENUM_LABELS


def test_account_type_still_has_no_other_invented_members():
    """İptal `equity` ile SINIRLIDIR. `memorandum`/`cost`/`contra`/`other` gibi
    bir ALTINCI üye hâlâ açılmaz: kontra bir TÜR değil, `is_contra` bayrağıdır
    ve nazım hesapların hiçbir ekranda karşılığı yoktur."""
    values = {e.value for e in ChartAccountType}
    for yasak in ("memorandum", "cost", "contra", "other", "class", "nazim"):
        assert yasak not in values, yasak


# --------------------------------------------------------------------------- #
# Model katmani — SIGN sozlugu ve NULL kanıtı
# --------------------------------------------------------------------------- #


def test_SIGN_her_hesap_turunu_kapsar():
    """🔴 `SIGN` sözlüğü enum'la BİREBİR olmak zorundadır: eksik bir üye
    `sign_case()`te (`else_` dalı YOK) NULL üretir."""
    assert set(balance.SIGN) == set(ChartAccountType)


def test_equity_isareti_EKSIDIR():
    """Özkaynak hesabı ALACAK bakiyelidir (`500 Sermaye`): ham `net`i negatiftir
    ve ekranda POZİTİF basılmalıdır — `liability`/`revenue` ile aynı işaret."""
    assert balance.SIGN[ChartAccountType.equity] == -1


async def test_sign_case_SIGN_girisi_silininde_NULL_uretir(
    seeded_db: AsyncSession, hesap_fabrikasi, fis_fabrikasi, monkeypatch
) -> None:
    """🔴 BU DİLİMİN EN SESSİZ TUZAĞININ KANITI — mutasyon testin İÇİNDE.

    `sign_case()`in `else_` dalı bilinçli olarak yoktur (`balance.py:151-160`).
    `SIGN`dan `equity` çıkarılırsa `CASE` hiçbir dala düşmez ve `NULL` döner;
    `balances_for()` sözlüğünde `Decimal` yerine `None` belirir ve yanıt şeması
    onu okurken gürültülü biçimde patlar.

    "Girdi eklendi" ile "girdi bekçilik ediyor" AYNI ŞEY DEĞİLDİR: bu test
    kusuru FİİLEN kurar ve NULL'ın doğduğunu ÖLÇER.
    """
    sermaye = await hesap_fabrikasi("500", name="Sermaye", account_type=ChartAccountType.equity)
    kasa = await hesap_fabrikasi("100", name="Kasa", account_type=ChartAccountType.asset)
    await fis_fabrikasi([(kasa, "8000.00", "0"), (sermaye, "0", "8000.00")])

    saglam = await balance.balances_for(seeded_db, [sermaye.id])
    assert saglam[sermaye.id] is not None
    assert saglam[sermaye.id] == 8000

    eksik = {t: i for t, i in balance.SIGN.items() if t is not ChartAccountType.equity}
    monkeypatch.setattr(balance, "SIGN", eksik)
    bozuk = await balance.balances_for(seeded_db, [sermaye.id])
    assert bozuk[sermaye.id] is None, (
        "SIGN'dan `equity` çıkarılınca sign_case() NULL üretmeliydi — "
        "`else_` dalı sessizce eklenmiş olabilir"
    )


async def test_ozkaynak_hesabinin_bakiyesi_HTTP_ucundan_POZITIF(
    client: AsyncClient, muhasebe_headers: dict[str, str], hesap_fabrikasi, fis_fabrikasi
) -> None:
    """🔴 Şema katmanı bekçisi: iddia **uçtan** geçer (MU-1 §3 dersi).

    `500 Sermaye` alacak bakiyelidir (ham `net` = −8.000) ve hesap planı
    ekranında `8.000` basar — `320 Satıcılar` ile aynı davranış (HP:164).
    `SIGN[equity]` eksik olsaydı bu uç `null` basar ya da 500 verirdi.
    """
    sermaye = await hesap_fabrikasi("500", name="Sermaye", account_type=ChartAccountType.equity)
    kasa = await hesap_fabrikasi("100", name="Kasa", account_type=ChartAccountType.asset)
    await fis_fabrikasi(
        [(kasa, "8000.00", "0"), (sermaye, "0", "8000.00")],
        status=JournalEntryStatus.posted,
    )

    resp = await client.get(f"{HESAP_YOLU}/{sermaye.id}", headers=muhasebe_headers)
    assert resp.status_code == 200, resp.text
    govde = resp.json()
    assert govde["account_type"] == "equity"
    assert govde["balance"] == "8000.00"


# --------------------------------------------------------------------------- #
# Model katmani — is_contra kolonu
# --------------------------------------------------------------------------- #


def test_is_contra_kolonu_NOT_NULL_ve_varsayilani_FALSE():
    """🔑 KK-1: kolon `Boolean NOT NULL DEFAULT false`.

    Nullable olsaydı `NULL` bir üçüncü hâl üretir ve `(-1 if is_contra else +1)`
    çarpanı Python'da `None`u "yanlış" sayarken SQL'de NULL yayardı. Sunucu
    varsayılanı ŞARTTIR: ORM dışı her yazma yolu (migration data-fix, elle SQL)
    aksi hâlde NOT NULL ihlali alırdı.
    """
    kolon = ChartAccount.__table__.columns[COLUMN]
    assert not kolon.nullable
    assert kolon.default.arg is False
    assert kolon.server_default is not None


def test_chart_account_kolonlari_tam_sayim():
    """BİLEREK tam sayım: `is_contra` DIŞINDA yeni bir kolon sessizce eklenemesin
    (MU-1'in kolon sayımının MT-1 hâli)."""
    assert set(ChartAccount.__table__.columns.keys()) == {
        "id",
        "code",
        "name",
        "account_type",
        "is_active",
        "is_contra",
        "created_at",
        "updated_at",
    }


async def test_is_contra_UCTAN_yazilir_ve_okunur(
    client: AsyncClient, muhasebe_headers: dict[str, str]
) -> None:
    """🔴 Şema katmanı kör noktası (MU-1 §3): kolonu modele eklemek YETMEZ —
    `POST`/`PATCH` gövdesinde ve yanıtta da bulunmalıdır, yoksa `257`yi kontra
    işaretlemenin HİÇBİR yolu olmaz ve bilanço netlemesi ölü kod kalır.

    Varsayılan `false`tur: gövdede hiç geçmeyen bir hesap kontra DEĞİLDİR.
    """
    varsayilan = await client.post(
        HESAP_YOLU,
        json={"code": "252", "name": "Binalar", "account_type": "asset"},
        headers=muhasebe_headers,
    )
    assert varsayilan.status_code == 201, varsayilan.text
    assert varsayilan.json()["is_contra"] is False

    kontra = await client.post(
        HESAP_YOLU,
        json={
            "code": "257",
            "name": "Birikmiş Amortismanlar (-)",
            "account_type": "liability",
            "is_contra": True,
        },
        headers=muhasebe_headers,
    )
    assert kontra.status_code == 201, kontra.text
    assert kontra.json()["is_contra"] is True

    hesap_id = varsayilan.json()["id"]
    yama = await client.patch(
        f"{HESAP_YOLU}/{hesap_id}", json={"is_contra": True}, headers=muhasebe_headers
    )
    assert yama.status_code == 200, yama.text
    assert yama.json()["is_contra"] is True

    listeleme = await client.get(HESAP_YOLU, headers=muhasebe_headers)
    assert listeleme.status_code == 200, listeleme.text
    assert all("is_contra" in satir for satir in listeleme.json()["items"])


# --------------------------------------------------------------------------- #
# Migration tur donusu
# --------------------------------------------------------------------------- #


def test_alembic_has_single_head():
    """İki head = canlıda deploy kilitlenmesi (`alembic upgrade head` patlar).

    🔴 `DATABASE_URL` override'ı BURADA DA verilir. `heads` komutu bugün bir
    bağlantı açmıyor ama `.env` UZAK Railway'i gösteriyor ve alembic'in bir
    alt komutunun ileride motor kurması hiçbir uyarı vermeden canlıya bağlanmak
    demektir (MU-1'de bir kez yaşandı). Kural tek cümledir: **hiçbir alembic
    komutu override'sız koşmaz.**"""
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
    assert len(heads) == 1, f"tek head bekleniyordu, çıktı:\n{result.stdout}"


def test_migration_parent_is_the_expected_revision():
    """🔴 Ebeveyn `c7d8e9f0a1b2` (MU-2). Arada başka bir dilim merge edilirse
    re-parent ŞART — bu sabit ve migration BİRLİKTE güncellenir (P8/TH dersi)."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(str(BACKEND_DIR / "alembic.ini")))
    revision = script.get_revision(MT1_REVISION)
    assert revision.down_revision == MU2_REVISION


async def test_upgrade_downgrade_upgrade_round_trip():
    """🔴 **`ALTER TYPE … ADD VALUE` GERİ ALINAMAZ.**

    Downgrade tipi yeniden kurmak (dört üyeli hâle) zorundadır. Kurmazsa ikinci
    `upgrade` "already exists" ile patlar ve bu YALNIZ CANLIDA görülür —
    konteyner açılışta `alembic upgrade head` koşar, patlarsa uvicorn hiç
    başlamaz (tam kesinti).
    """
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", MT1_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _enum_labels(conn, ENUM) == EXPECTED_ENUM_LABELS
            assert await _column_exists(conn, TABLE, COLUMN)
            assert await _current_revision(conn) == MT1_REVISION
        finally:
            await conn.close()

        _run_alembic("downgrade", MU2_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            # 🔴 Kalan bir `equity` etiketi İKİNCİ upgrade'i patlatırdı.
            assert await _enum_labels(conn, ENUM) == MU2_ENUM_LABELS, (
                "`equity` downgrade'de kalmış — ALTER TYPE ADD VALUE geri alınamaz, "
                "tip yeniden KURULMALIYDI"
            )
            assert not await _column_exists(conn, TABLE, COLUMN)
            # Komşu tablolar AYAKTA: bu dilim yalnız `chart_of_accounts`a dokunur.
            for komsu in ("journal_entries", "journal_lines", "accounting_periods", "users"):
                assert await conn.fetchval("SELECT to_regclass($1) IS NOT NULL", f"public.{komsu}")
            assert await _current_revision(conn) == MU2_REVISION
        finally:
            await conn.close()

        # 🔴 ASIL İDDİA: ikinci upgrade PATLAMADAN geçer.
        _run_alembic("upgrade", MT1_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _enum_labels(conn, ENUM) == EXPECTED_ENUM_LABELS
            assert await _column_exists(conn, TABLE, COLUMN)
            assert await _current_revision(conn) == MT1_REVISION
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


async def test_db_level_equity_degeri_KABUL_EDILIR_ve_is_contra_varsayilani_false():
    """🔴 `server_default` FİİLEN çalışıyor mu — ham SQL ile `is_contra` HİÇ
    verilmeden INSERT edilir. Yalnız Python tarafı `default=` verilseydi ORM
    dışı her yazma yolu NOT NULL ihlali alırdı.

    Aynı satır `account_type = 'equity'`i de sınar: enum'a değer eklenmemişse
    INSERT `invalid input value for enum` ile düşer.
    """
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", MT1_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            await conn.execute(
                "INSERT INTO chart_of_accounts (id, code, name, account_type) "
                "VALUES ($1, '500', 'Sermaye', 'equity')",
                uuid.uuid4(),
            )
            row = await conn.fetchrow(
                "SELECT account_type::text AS account_type, is_contra, is_active "
                "FROM chart_of_accounts WHERE code = '500'"
            )
            assert row["account_type"] == "equity"
            assert row["is_contra"] is False
            assert row["is_active"] is True
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


async def test_downgrade_EQUITY_satiri_varken_SESSIZCE_gecmez():
    """🔴 Downgrade veri KAYBETMEZ, DURUR.

    Dört üyeli tipe dönerken `equity` taşıyan satırlar dönüştürülemez. Sessizce
    `liability`ye çevirmek hesap planı ekranında yanlış rozet basar ve bilanço
    `III. ÖZKAYNAKLAR` bölümünü `I. KISA VADELİ`ye taşırdı — para tablosu YALAN
    söylerdi. Migration bu yüzden AÇIK bir hatayla durur.
    """
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", MT1_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            await conn.execute(
                "INSERT INTO chart_of_accounts (id, code, name, account_type) "
                "VALUES ($1, '500', 'Sermaye', 'equity')",
                uuid.uuid4(),
            )
        finally:
            await conn.close()

        sonuc = _run_alembic_expecting_failure("downgrade", MU2_REVISION, database=database)
        assert sonuc.returncode != 0, (
            "equity satırı varken downgrade sessizce geçti — veri kaybı riski:\n" + sonuc.stdout
        )

        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            # Şema BOZULMADAN kaldı: yarım kalmış bir downgrade daha kötüdür.
            assert await _current_revision(conn) == MT1_REVISION
            assert await _enum_labels(conn, ENUM) == EXPECTED_ENUM_LABELS
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)
