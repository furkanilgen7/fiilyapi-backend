"""URL-4 · `f3a7c9e1d5b2` — GERİ DOLDURMA ölçümü, tur dönüşü ve ZİNCİR SIRASI.

`tests/modules/sites/test_url2_slug_migration.py`nin ikizidir ve aynı gerekçeyle
vardır: **migration GÖVDESİ hiçbir API testinde YÜRÜTÜLMEZ.** Uygulama testleri
`Base.metadata.create_all` ile şemayı kurar; `upgrade()` içindeki geri doldurma
mantığı o yoldan HİÇ geçmez. Yani gövde tamamen kırık olsa da URL-4'ün 69 API
bekçisi yeşil kalırdı — ve kusur ilk kez CANLI DEPLOY'da görünürdü.

🔴 **PATLAMAMA ŞARTI**: `Dockerfile` açılışı `alembic upgrade head && uvicorn`.
Bu satırda atılan bir istisna `&&`yi kısa devre yapar ve UVICORN HİÇ BAŞLAMAZ.
Bu yüzden çakışma `raise` değil SAYI EKİ ile çözülür; slug üretemeyen kayıt
atlanır. Bu dosyanın merkezî iddiası budur.

## 🔴 ZİNCİR SIRASI — bu dosyanın URL-2'de OLMAYAN üçüncü iddiası

`subcontractor_progress_payments.slug`, `subcontractor_contracts.slug`ten TÜRER
(`SELECT sc.slug || '-' || sp.sequence_no`). Migration'daki `_TABLES` sırası
sözleşmeleri hakedişlerden ÖNCE koyar. Sıra bozulsaydı hakedişlerin HEPSİ NULL
kalırdı ve **hiçbir şey hata vermezdi** — sessiz, yarım bir göç.

Bugüne kadar bu bağımlılık yalnız ÇIKTIYLA (elle koşulan bir deploy günlüğü)
kanıtlıydı, KODLA değil. `test_ZINCIR_SIRASI_sozlesmeleri_hakedislerden_ONCE_doldurur`
onu koda bağlar: hem sonucu ölçer, hem de `_TABLES` sırasını doğrudan iddia eder.

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
# revizyon ekledikçe bu test sessizce yanlış şeyi ölçerdi (URL-2 kanonu).
BEFORE_REVISION = "c5d8e2f1a4b7"
URL4_REVISION = "f3a7c9e1d5b2"

TABLES = (
    "equipment",
    "personnel",
    "subcontractor_contracts",
    "progress_payments",
    "subcontractor_progress_payments",
    "equipment_rental_invoices",
)
INDEXES = tuple(f"uq_{table}_slug" for table in TABLES)


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
    database = f"url4_slug_{uuid.uuid4().hex[:8]}"
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
    """URL-4 ÖNCESİ hâle, geri doldurmayı ZORLAYACAK veriyi yazar.

    Kasıtlı olarak her tabloda ÜÇ hâl birden var: normal · ÇAKIŞAN · slug
    ÜRETİLEMEYEN. Ayrıca zincir için slug'lı ve slug'sız üst kayıtlar.
    """
    ids: dict[str, uuid.UUID] = {}

    role_id = await conn.fetchval("SELECT id FROM roles LIMIT 1")
    user_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO users (id, email, password_hash, full_name, title, role_id, status, "
        "token_version) VALUES ($1, $2, 'x', 'U', 'T', $3, 'active', 0)",
        user_id,
        f"url4-{uuid.uuid4().hex[:8]}@t.co",
        role_id,
    )

    async def project(key: str, name: str, slug: str | None) -> uuid.UUID:
        pid = uuid.uuid4()
        await conn.execute(
            "INSERT INTO projects (id, code, name, status, budget, progress_pct, slug) "
            "VALUES ($1, $2, $3, 'active', 0, 0, $4)",
            pid,
            f"PRJ-{uuid.uuid4().hex[:8]}",
            name,
            slug,
        )
        ids[key] = pid
        await conn.execute(
            "INSERT INTO project_contracts (project_id, contract_no, amount, advance_pct, "
            "retainage_pct, vat_pct, has_price_escalation, status) "
            "VALUES ($1, $2, 1000, 20, 5, 20, false, 'active')",
            pid,
            f"SZL-{uuid.uuid4().hex[:6]}",
        )
        return pid

    p_slugla = await project("p_slugla", "Köprü Güçlendirme", "kopru-guclendirme")
    p_slugsuz = await project("p_slugsuz", "Slugsuz Proje", None)

    # --- equipment: normal · ÇAKIŞAN · slug'lanamayan ---
    for key, name in (
        ("eq_normal", "Beko Loder"),
        ("eq_cakisan", "BEKO LODER"),
        ("eq_bos", "???"),
    ):
        eid = uuid.uuid4()
        await conn.execute(
            "INSERT INTO equipment (id, name, category, ownership, status) "
            "VALUES ($1, $2, 'machinery', 'owned', 'working')",
            eid,
            name,
        )
        ids[key] = eid

    # --- personnel: normal · ÇAKIŞAN (aynı ad) ---
    for key, ad in (("pers_normal", "Ahmet Yılmaz"), ("pers_cakisan", "Ahmet Yilmaz")):
        pid = uuid.uuid4()
        await conn.execute(
            "INSERT INTO personnel (id, full_name, source, is_active, is_draft) "
            "VALUES ($1, $2, 'company', true, false)",
            pid,
            ad,
        )
        ids[key] = pid

    # --- subcontractor_contracts: no VAR · no YOK (ad+kategori) · İKİSİ DE YOK ---
    async def subcontract(key: str, ad: str | None, kat: str | None, no: str | None) -> uuid.UUID:
        cid = uuid.uuid4()
        await conn.execute(
            "INSERT INTO subcontractor_contracts (id, project_id, subcontractor_name, "
            "work_category, contract_no, advance_pct, retainage_pct, vat_pct, "
            "payment_term_days, status, is_draft, created_by) "
            "VALUES ($1, $2, $3, $4, $5, 10, 5, 20, 30, 'active', false, $6)",
            cid,
            p_slugla,
            ad,
            kat,
            no,
            user_id,
        )
        ids[key] = cid
        return cid

    sc_nolu = await subcontract("sc_nolu", "Akın İnşaat", "Betonarme", "TSZ-2026-004")
    await subcontract("sc_adli", "Yıldız İnşaat", "Kalıp", None)
    sc_bos = await subcontract("sc_bos", None, None, None)

    # --- progress_payments: slug'lı proje · SLUG'SIZ proje (zincir kesilir) ---
    for key, proje in (("pp_slugla", p_slugla), ("pp_slugsuz", p_slugsuz)):
        ppid = uuid.uuid4()
        await conn.execute(
            "INSERT INTO progress_payments (id, project_id, sequence_no, status, vat_pct, "
            "advance_pct, retainage_pct, default_coefficient, created_by) "
            "VALUES ($1, $2, 1, 'draft', 20, 20, 5, 1, $3)",
            ppid,
            proje,
            user_id,
        )
        ids[key] = ppid

    # --- spp: slug ALACAK sözleşme · slug ALAMAYACAK sözleşme ---
    for key, sozlesme, sira in (("spp_slugla", sc_nolu, 48), ("spp_slugsuz", sc_bos, 1)):
        sid = uuid.uuid4()
        await conn.execute(
            "INSERT INTO subcontractor_progress_payments (id, contract_id, project_id, "
            "sequence_no, status, vat_pct, advance_pct, retainage_pct, default_coefficient, "
            "created_by) VALUES ($1, $2, $3, $4, 'draft', 20, 10, 5, 1, $5)",
            sid,
            sozlesme,
            p_slugla,
            sira,
            user_id,
        )
        ids[key] = sid

    # --- equipment_rental_invoices: İKİ TEDARİKÇİ AYNI NUMARA · numarasız taslak ---
    tedarikciler = []
    for ad in ("Alfa Kiralama", "Beta Kiralama"):
        tid = uuid.uuid4()
        await conn.execute(
            "INSERT INTO suppliers (id, name, payment_terms, is_active) "
            "VALUES ($1, $2, 'cash', true)",
            tid,
            ad,
        )
        tedarikciler.append(tid)
    for key, tedarikci, no in (
        ("kira_ilk", tedarikciler[0], "ORTAK2026001"),
        ("kira_cakisan", tedarikciler[1], "ORTAK2026001"),
        ("kira_nosuz", tedarikciler[0], None),
    ):
        kid = uuid.uuid4()
        await conn.execute(
            "INSERT INTO equipment_rental_invoices (id, supplier_id, invoice_no, period_year, "
            "period_month, rate_period, vat_rate, status) "
            "VALUES ($1, $2, $3, 2026, 8, 'hourly', 20, 'draft')",
            kid,
            tedarikci,
            no,
        )
        ids[key] = kid

    return ids


@pytest.mark.asyncio
async def test_geri_doldurma_cakismali_veriyle_de_TAMAMLANIR():
    """🔴 ÇEKİRDEK İDDİA: çakışmalı + slug'lanamayan veri üzerinde migration PATLAMAZ."""
    database = await _scratch()
    try:
        _alembic("upgrade", BEFORE_REVISION, database=database)
        conn = await asyncpg.connect(_dsn(database))
        try:
            ids = await _seed(conn)
        finally:
            await conn.close()

        _alembic("upgrade", URL4_REVISION, database=database)

        conn = await asyncpg.connect(_dsn(database))
        try:
            assert await conn.fetchval("SELECT version_num FROM alembic_version") == URL4_REVISION

            async def slug_of(table: str, key: str) -> str | None:
                return await conn.fetchval(f"SELECT slug FROM {table} WHERE id = $1", ids[key])

            # 1. Türkçe dönüşüm migration'ın KENDİ kopyasında da doğru.
            assert await slug_of("equipment", "eq_normal") == "beko-loder"
            # 2. Çakışma sayı ekiyle ÇÖZÜLDÜ, sessizce çakışmadı.
            assert await slug_of("equipment", "eq_cakisan") == "beko-loder-2"
            # 3. Slug'lanamayan kayıt ATLANDI (NULL) — migration DURMADI.
            assert await slug_of("equipment", "eq_bos") is None
            # 4. KVKK: personel slug'ı yalnız addan; çakışan ek alır.
            assert await slug_of("personnel", "pers_normal") == "ahmet-yilmaz"
            assert await slug_of("personnel", "pers_cakisan") == "ahmet-yilmaz-2"
            # 5. Sözleşme tabanı: `contract_no` -> ad+kategori -> NULL.
            assert await slug_of("subcontractor_contracts", "sc_nolu") == "tsz-2026-004"
            assert await slug_of("subcontractor_contracts", "sc_adli") == "yildiz-insaat-kalip"
            assert await slug_of("subcontractor_contracts", "sc_bos") is None
            # 6. Bileşik: proje slug'ı + sıra; slug'sız projede NULL.
            assert await slug_of("progress_payments", "pp_slugla") == "kopru-guclendirme-1"
            assert await slug_of("progress_payments", "pp_slugsuz") is None
            # 7. Kira: numara slug'ı, çakışma eki, numarasız taslak NULL.
            assert await slug_of("equipment_rental_invoices", "kira_ilk") == "ortak2026001"
            assert await slug_of("equipment_rental_invoices", "kira_cakisan") == "ortak2026001-2"
            assert await slug_of("equipment_rental_invoices", "kira_nosuz") is None

            for index in INDEXES:
                assert await conn.fetchval(
                    "SELECT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = $1)", index
                ), index

            # Kısmi indeks GERÇEKTEN kısmi: NULL slug ÇOKLANABİLİR olmalı.
            await conn.execute(
                "INSERT INTO equipment (id, name, category, ownership, status) "
                "VALUES ($1, '???', 'machinery', 'owned', 'working')",
                uuid.uuid4(),
            )
            # …ama DOLU slug çoklanamaz.
            with pytest.raises(asyncpg.UniqueViolationError):
                await conn.execute(
                    "INSERT INTO equipment (id, name, slug, category, ownership, status) "
                    "VALUES ($1, 'Kopya', 'beko-loder', 'machinery', 'owned', 'working')",
                    uuid.uuid4(),
                )
        finally:
            await conn.close()
    finally:
        await _drop(database)


@pytest.mark.asyncio
async def test_ZINCIR_SIRASI_sozlesmeleri_hakedislerden_ONCE_doldurur():
    """🔴 `spp.slug`, `subcontractor_contracts.slug`ten TÜRER — sıra BAĞLAYICI.

    Sıra bozulsaydı taşeron hakedişlerinin HEPSİ NULL kalırdı ve **hiçbir şey
    hata vermezdi**: sessiz, yarım bir göç. Bu test onu iki yönden bağlar —
    (a) SONUÇ: slug'lı sözleşmenin hakedişi `<sözleşme-slug>-<sıra>` almış,
    (b) KAYNAK: `_TABLES` dizisinde sözleşmeler hakedişlerden önce.
    """
    database = await _scratch()
    try:
        _alembic("upgrade", BEFORE_REVISION, database=database)
        conn = await asyncpg.connect(_dsn(database))
        try:
            ids = await _seed(conn)
        finally:
            await conn.close()

        _alembic("upgrade", URL4_REVISION, database=database)

        conn = await asyncpg.connect(_dsn(database))
        try:
            # (a) SONUÇ — zincir gerçekten kurulmuş.
            assert (
                await conn.fetchval(
                    "SELECT slug FROM subcontractor_progress_payments WHERE id = $1",
                    ids["spp_slugla"],
                )
                == "tsz-2026-004-48"
            )
            # Üst kaydın slug'ı yoksa çocuğununki de YOK (uydurma taban yazılmaz).
            assert (
                await conn.fetchval(
                    "SELECT slug FROM subcontractor_progress_payments WHERE id = $1",
                    ids["spp_slugsuz"],
                )
                is None
            )
        finally:
            await conn.close()
    finally:
        await _drop(database)

    # (b) KAYNAK — sıra migration'ın KENDİSİNDE iddia edilir. Sonuç iddiası tek
    # başına yeterli DEĞİLDİR: bir gün `_TABLES` alfabetik sıralansa sonuç yine
    # tesadüfen doğru çıkabilirdi (`subcontractor_contracts` <
    # `subcontractor_progress_payments`). Bu iddia niyeti sabitler.
    modul = _migration_modulu()
    sira = list(modul._TABLES)
    assert sira.index("subcontractor_contracts") < sira.index("subcontractor_progress_payments")
    # Aynı zincir `progress_payments` için de var ama üstü URL-2'de zaten dolu
    # olduğundan (`projects.slug`) bu migration içinde sıra kısıtı doğurmaz.
    assert set(sira) == set(TABLES)


def _migration_modulu():
    """Migration dosyasını modül olarak yükler (revizyon adı dosya adında değil)."""
    import importlib.util

    yol = BACKEND_DIR / "alembic" / "versions" / f"{URL4_REVISION}_url4_kalan_rotalar_slug.py"
    spec = importlib.util.spec_from_file_location("url4_migration", yol)
    assert spec is not None and spec.loader is not None
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


@pytest.mark.asyncio
async def test_downgrade_ve_yeniden_upgrade_TEMIZ():
    """Tur dönüşü: indeksler düşmezse ikinci `upgrade` "already exists" ile patlar."""
    database = await _scratch()
    try:
        _alembic("upgrade", URL4_REVISION, database=database)
        _alembic("downgrade", BEFORE_REVISION, database=database)

        conn = await asyncpg.connect(_dsn(database))
        try:
            for index in INDEXES:
                assert not await conn.fetchval(
                    "SELECT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = $1)", index
                ), index
            for table in TABLES:
                assert not await conn.fetchval(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = $1 AND column_name = 'slug')",
                    table,
                ), table
        finally:
            await conn.close()

        _alembic("upgrade", URL4_REVISION, database=database)
    finally:
        await _drop(database)


def test_migration_govdesi_RAISE_ETMEZ():
    """`Dockerfile` `alembic upgrade head && uvicorn` — gövdede `raise` OLMAZ.

    Bir istisna `&&`yi kısa devre yapar ve uvicorn HİÇ başlamaz. Geri doldurma
    her hâli (çakışma · üretilememe) `logger.warning` ile bildirip DEVAM eder.
    """
    kaynak = (
        BACKEND_DIR / "alembic" / "versions" / f"{URL4_REVISION}_url4_kalan_rotalar_slug.py"
    ).read_text(encoding="utf-8")
    kod = [
        satir
        for satir in kaynak.splitlines()
        if satir.strip().startswith("raise ") or satir.strip() == "raise"
    ]
    assert not kod, "migration govdesinde raise VAR:\n" + "\n".join(kod)
