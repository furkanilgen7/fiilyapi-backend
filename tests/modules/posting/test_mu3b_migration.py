"""MU-3B T-MIG — kısmi tekilliğin MIGRATION'IN ÜRETTİĞİ ŞEMADA ölçülmesi.

`test_mu3b_repost.py` aynı kuralı `Base.metadata.create_all` ile kurulmuş bir
şemada ölçer. İkisi AYRIŞABİLİR ve bu deponun tekrar tekrar ölçtüğü kusurdur:
model katmanına bir indeks eklenip migration'a yazılmayı unutulsaydı test kümesi
YEŞİL kalır ve **CANLI tam tekillikte donardı** — stornolanan hiçbir belge
yeniden fişlenemezdi ve bunu hiçbir test göstermezdi.

## Neden TUR DÖNÜŞÜ de ölçülür

`downgrade` TAM tekilliği geri kurar; bu bir DARALTMADIR ve kısmi tekillik
altında yazılmış (ölü + canlı) çiftler varsa `ADD CONSTRAINT` ham bir hatayla
patlar. Migration bu yüzden ÖNCE SAYAR ve `RuntimeError` ile DURUR. Test iki
dalı da koşar: temiz veride tur dönüşü GEÇER, çakışan veride DURUR.

Test kendi TEK KULLANIMLIK veritabanını açar ve sonunda düşürür; `.env` ve
`TEST_DATABASE_URL` veritabanı ELLENMEZ.
"""

import uuid
from datetime import date

import asyncpg

from app.modules.accounting.models import LIVE_SOURCE_WHERE
from tests.modules.accounting._mu1_migration import (
    _asyncpg_dsn,
    _constraint_exists,
    _current_revision,
    _drop_scratch_database,
    _index_exists,
    _run_alembic,
    _seed_user,
)

#: Revizyonlara AÇIKÇA çıkılır; `head`/`-1` KULLANILMAZ — sonraki dilimler
#: revizyon ekledikçe bu test sessizce başka bir şeyi ölçerdi.
PARENT_REVISION = "a2d6b11efdcf"
MU3B_REVISION = "b9c0d1e2f3a4"

INDEX_NAME = "uq_journal_entries_source"
SOURCE_ENUM = "journal_source_type"


async def _create_scratch() -> str:
    database = f"mu3b_mig_{uuid.uuid4().hex[:8]}"
    admin = await asyncpg.connect(_asyncpg_dsn("postgres"))
    try:
        await admin.execute(f'CREATE DATABASE "{database}"')
    finally:
        await admin.close()
    return database


async def _insert_entry(
    conn: asyncpg.Connection,
    user_id: uuid.UUID,
    *,
    entry_no: str,
    source_id: uuid.UUID,
    status: str,
) -> None:
    """Kısıtın ölçüldüğü en küçük geçerli başlık — satırsız, toplamlar 0/0."""
    await conn.execute(
        "INSERT INTO journal_entries "
        "(id, entry_no, entry_date, period_year, period_month, description, status, "
        " total_debit, total_credit, source_type, source_id, created_by_id) "
        "VALUES ($1, $2, $3, 2026, 7, 'Migration probu', $4::journal_entry_status, 0, 0, "
        f"'invoice'::{SOURCE_ENUM}, $5, $6)",
        uuid.uuid4(),
        entry_no,
        date(2026, 7, 17),
        status,
        source_id,
        user_id,
    )


def test_migration_parent_is_the_expected_revision():
    """🔴 Ebeveyn `a2d6b11efdcf` (MU-3A). Arada başka bir dilim merge edilirse
    re-parent ŞART — bu sabit ve migration BİRLİKTE güncellenir (P8/TH dersi)."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from tests.modules.accounting._mu1_migration import BACKEND_DIR

    script = ScriptDirectory.from_config(Config(str(BACKEND_DIR / "alembic.ini")))
    assert script.get_revision(MU3B_REVISION).down_revision == PARENT_REVISION


def test_migration_metni_MODEL_sabitiyle_AYNI_kosulu_tasir():
    """🔴 İKİ KATMAN EŞİTLİĞİ — donmuş kopya ile `models.LIVE_SOURCE_WHERE`.

    Migration uygulama kodunu bilinçli olarak IMPORT ETMEZ (K1: uygulanmış bir
    migration DONMUŞ olmalıdır). Bedeli, iki metnin sessizce ayrışabilmesidir:
    biri `reversed`i süzer, öteki başka bir durumu — ve `entry_for_source` ile
    indeks farklı kümeleri tarif ederdi. Bu test o bedeli ödettirir.

    `models.LIVE_SOURCE_WHERE`ın KENDİSİ enum üyesinden TÜRETİLİR, yani üye
    yeniden adlandırılırsa bu iddia da kırılır (`MU-SEED` T5 deseni).
    """
    from tests.modules.accounting._mu1_migration import BACKEND_DIR

    kaynak = (
        BACKEND_DIR / "alembic" / "versions" / "b9c0d1e2f3a4_mu3b_canli_fis_kismi_tekilligi.py"
    ).read_text()

    assert f'LIVE_WHERE = "{LIVE_SOURCE_WHERE}"' in kaynak, (
        f"migration donmuş kopyası model sabitinden ayrıştı: {LIVE_SOURCE_WHERE!r}"
    )


async def test_upgrade_KISITI_INDEKSE_donusturur_ve_KISMI_yapar():
    """🔴 Ölçülen şey MIGRATION'IN ÜRETTİĞİ ŞEMADIR, modelin değil."""
    database = await _create_scratch()
    try:
        _run_alembic("upgrade", PARENT_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            # MU-3A'da bir KISITTIR (kısmi olamaz).
            assert await _constraint_exists(conn, INDEX_NAME) is True
        finally:
            await conn.close()

        _run_alembic("upgrade", MU3B_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _current_revision(conn) == MU3B_REVISION
            # 🔴 Artık bir KISIT DEĞİL, kısmi bir unique İNDEKSTİR.
            assert await _constraint_exists(conn, INDEX_NAME) is False
            assert await _index_exists(conn, INDEX_NAME) is True
            tanim = await conn.fetchval(
                "SELECT indexdef FROM pg_indexes WHERE indexname = $1", INDEX_NAME
            )
            assert "UNIQUE" in tanim, tanim
            # Süzgeç ŞART: olmadan indeks TAM tekilliğe eşdeğerdir.
            assert "WHERE" in tanim and "reversed" in tanim, tanim
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


async def test_upgrade_sonrasi_OLU_fis_yeni_fisi_ENGELLEMEZ_canli_ciftler_REDDEDILIR():
    """Şemanın DAVRANIŞI — `indexdef` metni tek başına yetmez.

    İki iddia BİRLİKTE tutulur: gevşeme uygulandı VE idempotanlık ayakta.
    Yalnız birincisi ölçülseydi süzgeci `WHERE true` yazan bir migration da
    yeşil geçerdi.
    """
    database = await _create_scratch()
    try:
        _run_alembic("upgrade", MU3B_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            user_id = await _seed_user(conn)
            belge_id = uuid.uuid4()

            await _insert_entry(
                conn, user_id, entry_no="YEV-2026-0001", source_id=belge_id, status="reversed"
            )
            # GEVŞEME: ölü fişin yanına CANLI fiş yazılabilir.
            await _insert_entry(
                conn, user_id, entry_no="YEV-2026-0002", source_id=belge_id, status="posted"
            )

            # İDEMPOTANLIK: ikinci CANLI fiş REDDEDİLİR.
            try:
                await _insert_entry(
                    conn, user_id, entry_no="YEV-2026-0003", source_id=belge_id, status="posted"
                )
            except asyncpg.UniqueViolationError as hata:
                assert INDEX_NAME in str(hata)
            else:
                raise AssertionError("aynı belgeye İKİNCİ CANLI fiş yazıldı — kısmi tekillik yok")
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


async def test_tur_donusu_TEMIZ_veride_gecer_ve_IKINCI_upgrade_de_gecer():
    """`downgrade` → `upgrade` — indeks/kısıt dönüşümü iki yönde de tutar.

    "downgrade koştu" demek YETMEZ: ikinci `upgrade` de koşmalıdır, yoksa yarım
    bir deploy'dan sonraki açılış YALNIZ CANLIDA patlardı (`Dockerfile`ın
    `alembic upgrade head && uvicorn` zinciri kısa devre yapar).
    """
    database = await _create_scratch()
    try:
        _run_alembic("upgrade", MU3B_REVISION, database=database)
        _run_alembic("downgrade", PARENT_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _constraint_exists(conn, INDEX_NAME) is True
        finally:
            await conn.close()

        _run_alembic("upgrade", MU3B_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _current_revision(conn) == MU3B_REVISION
            assert await _index_exists(conn, INDEX_NAME) is True
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


async def test_downgrade_CAKISAN_veride_DURUR_ve_semayi_BOZMAZ():
    """🔴 VERİ KAPISI: yarım downgrade, durmuş bir downgrade'den KÖTÜDÜR.

    Kısmi tekillik altında yazılmış (ölü + canlı) çift, TAM tekilliğe dönüşü
    imkânsız kılar. `op.create_unique_constraint` ham bir hata verir ve indeks
    ZATEN DÜŞMÜŞ olurdu — şema kısıtsız kalırdı. Kapı SAYIMI önce yapar.
    """
    import os
    import subprocess

    from tests.modules.accounting._mu1_migration import ALEMBIC_CMD, BACKEND_DIR

    database = await _create_scratch()
    try:
        _run_alembic("upgrade", MU3B_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            user_id = await _seed_user(conn)
            belge_id = uuid.uuid4()
            await _insert_entry(
                conn, user_id, entry_no="YEV-2026-0001", source_id=belge_id, status="reversed"
            )
            await _insert_entry(
                conn, user_id, entry_no="YEV-2026-0002", source_id=belge_id, status="posted"
            )
        finally:
            await conn.close()

        # `_run_alembic` başarısızlıkta `pytest.fail` eder; BURADA başarısızlık
        # BEKLENEN sonuçtur, bu yüzden alt süreç DOĞRUDAN koşulur.
        sonuc = subprocess.run(
            [*ALEMBIC_CMD, "downgrade", PARENT_REVISION],
            cwd=BACKEND_DIR,
            env={**os.environ, "DATABASE_URL": _asyncpg_dsn(database)},
            capture_output=True,
            text=True,
            timeout=300,
        )
        assert sonuc.returncode != 0, sonuc.stdout
        assert "downgrade DURDURULDU" in sonuc.stderr + sonuc.stdout

        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            # ŞEMA BOZULMADI: indeks yerinde, revizyon ilerlememiş.
            assert await _index_exists(conn, INDEX_NAME) is True
            assert await _current_revision(conn) == MU3B_REVISION
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)
