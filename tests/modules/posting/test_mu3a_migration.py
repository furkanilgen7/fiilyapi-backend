"""MU-3A T4 — migration TUR DÖNÜŞÜ + DB SEMANTİĞİ.

`tests/modules/accounting/test_mu1_migration_db.py`nin kardeşidir ve
yardımcıları ondan alır (KOPYALANMAZ — iki kopya bir gün AYRIŞIR).

## Neden ayrı bir tur dönüşü testi

Bu migration **YENİ BİR POSTGRES ENUM TİPİ** getiriyor (`journal_source_type`)
ve tipi İKİ TABLO birden kullanıyor (`journal_entries` + `posting_rules`).
Downgrade'de tipi düşürmeyi unutmak ikinci `upgrade`i
`type "journal_source_type" already exists` ile patlatır (`d4e5f6a7b8c9` dersi)
ve bu YALNIZ CANLIDA görülürdü. `test_tur_donusu_IKINCI_upgrade_de_gecer` tam
olarak bunu ölçer — "downgrade koştu" demek yetmez, İKİNCİ UPGRADE koşmalıdır.

## DB SEMANTİĞİ bu dilimde İDEMPOTANLIĞIN SON SAVUNMASIDIR

`test_mu3a_source_stamp.py` aynı kuralları ORM üzerinden ölçer;
burada ölçülen şey MIGRATION'IN ÜRETTİĞİ ŞEMAdır. İkisi ayrışabilir: model
katmanına bir kısıt eklenip migration'a yazılmayı unutulsaydı test kümesi
(`Base.metadata.create_all`) yeşil kalır ve CANLI kısıtsız kalırdı.

Test kendi TEK KULLANIMLIK veritabanını açar ve sonunda düşürür; `.env` ve
`TEST_DATABASE_URL` veritabanı ELLENMEZ.

⚠️ PG SÜRÜM TUZAĞI: yerel 18, CI 16 — RESTRICT ihlali sürüme göre 23001 veya
23503 bildirir; iddia bu yüzden DAR bir tuple ile iki sınıfı da kabul eder.
"""

import subprocess
import uuid
from datetime import date

import asyncpg
import pytest

from app.modules.accounting.models import JournalSourceType
from tests.modules.accounting._mu1_migration import (
    ALEMBIC_CMD,
    BACKEND_DIR,
    RESTRICT_ERRORS,
    _asyncpg_dsn,
    _constraint_exists,
    _current_revision,
    _drop_scratch_database,
    _enum_exists,
    _enum_labels,
    _run_alembic,
    _seed_user,
    _table_exists,
)

#: Revizyonlara AÇIKÇA çıkılır; `head`/`-1` KULLANILMAZ — sonraki dilimler
#: revizyon ekledikçe bu test sessizce başka bir şeyi ölçerdi.
PARENT_REVISION = "b6c7d8e9f0a1"
MU3A_REVISION = "a2d6b11efdcf"

SOURCE_ENUM = "journal_source_type"
RULE_TABLE = "posting_rules"

#: 🔴 Üye SIRASI kilitlidir (`ALTER TYPE … ADD VALUE` SONA ekler).
#:
#: 🔴 Bu liste **MU-3A REVİZYONUNDAKİ DB hâlini** tarif eder, modelin BUGÜNKÜ
#: hâlini DEĞİL (`_mu1_migration.EXPECTED_ENUM_LABELS` deseni). `a2d6b11efdcf`a
#: çıkan bir veritabanında tip BEŞ üyelidir; altıncı üye
#: (`equipment_rental_invoice`) MU-3D'nin `b7c8d9e0f1a2` migration'ıyla gelir.
#: İkisi karıştırılırsa bu test, ölçtüğünü sandığı şeyi değil sonraki
#: dilimlerin şemasını ölçmeye başlar.
EXPECTED_LABELS = [
    "invoice",
    "payment",
    "payroll_period",
    "progress_payment",
    "subcontractor_progress_payment",
]

CONSTRAINTS = (
    "uq_journal_entries_source",
    "ck_journal_entries_source_pair",
    "uq_posting_rules_source_role",
    "ck_posting_rules_role_key_format",
)


async def _create_scratch() -> str:
    database = f"mu3a_mig_{uuid.uuid4().hex[:8]}"
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
    source_type: str | None = None,
    source_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Kısıtın ölçüldüğü en küçük geçerli başlık — satırsız, toplamlar 0/0."""
    entry_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO journal_entries "
        "(id, entry_no, entry_date, period_year, period_month, description, status, "
        " total_debit, total_credit, source_type, source_id, created_by_id) "
        "VALUES ($1, $2, $3, 2026, 7, 'Migration probu', 'posted', 0, 0, "
        f"$4::{SOURCE_ENUM}, $5, $6)",
        entry_id,
        entry_no,
        date(2026, 7, 17),
        source_type,
        source_id,
        user_id,
    )
    return entry_id


# --------------------------------------------------------------------------- #
# Zincir
# --------------------------------------------------------------------------- #


def test_alembic_has_single_head():
    """İki head = canlıda deploy kilitlenmesi (`alembic upgrade head` patlar).

    Head'in KİMLİĞİ iddia EDİLMEZ (repo kanonu): sonraki dilim head'i ileri
    taşıdığında bu test ilgisiz yere kırılırdı.
    """
    result = subprocess.run(
        [*ALEMBIC_CMD, "heads"], cwd=BACKEND_DIR, capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stderr
    heads = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(heads) == 1, f"tek head bekleniyordu, çıktı:\n{result.stdout}"


def test_migration_parent_is_the_expected_revision():
    """🔴 Ebeveyn `b6c7d8e9f0a1` (MK-4). Arada başka bir dilim merge edilirse
    re-parent ŞART — bu sabit ve migration BİRLİKTE güncellenir (P8/TH dersi)."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(str(BACKEND_DIR / "alembic.ini")))
    assert script.get_revision(MU3A_REVISION).down_revision == PARENT_REVISION


def test_revizyon_kimligi_TEKILDIR():
    """🔴 Migration id'leri bu depoda ELLE yazılır ve ÇAKIŞIR.

    Çift head'den FARKLI bir arızadır ve re-parent düzeltmez: iki dosya aynı
    `revision` değerini taşırsa alembic zinciri sessizce kısaltır. Ölçüm
    KİMLİĞE değil TEKİLLİĞE bakar — sonraki dilimler dosya ekledikçe geçerli
    kalsın.
    """
    versions = sorted((BACKEND_DIR / "alembic" / "versions").glob("*.py"))
    kimlikler = [
        satir.split("=", 1)[1].strip().strip('"')
        for dosya in versions
        for satir in dosya.read_text().splitlines()
        if satir.startswith("revision: str =")
    ]
    assert len(kimlikler) == len(set(kimlikler)), (
        "aynı `revision` kimliği iki dosyada: "
        f"{sorted({k for k in kimlikler if kimlikler.count(k) > 1})}"
    )
    assert MU3A_REVISION in kimlikler


# --------------------------------------------------------------------------- #
# Tur dönüşü
# --------------------------------------------------------------------------- #


async def test_tur_donusu_IKINCI_upgrade_de_gecer():
    """🔴 `downgrade` ENUM TİPİNİ DÜŞÜRMEZSE bu test kırmızı olur.

    "downgrade koştu" demek YETMEZ: unutulan `DROP TYPE` yalnızca İKİNCİ
    `upgrade`de görünür ve canlıda deploy'u kilitler.
    """
    database = await _create_scratch()
    try:
        _run_alembic("upgrade", MU3A_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _current_revision(conn) == MU3A_REVISION
            assert await _table_exists(conn, RULE_TABLE)
            assert await _enum_exists(conn, SOURCE_ENUM)
            assert await _enum_labels(conn, SOURCE_ENUM) == EXPECTED_LABELS
            for kisit in CONSTRAINTS:
                assert await _constraint_exists(conn, kisit), kisit
        finally:
            await conn.close()

        _run_alembic("downgrade", PARENT_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _current_revision(conn) == PARENT_REVISION
            assert not await _table_exists(conn, RULE_TABLE)
            assert not await _enum_exists(conn, SOURCE_ENUM), (
                "`journal_source_type` downgrade'de DÜŞMEDİ — ikinci upgrade "
                '"type already exists" ile YALNIZ CANLIDA patlardı'
            )
            for kisit in CONSTRAINTS:
                assert not await _constraint_exists(conn, kisit), kisit
        finally:
            await conn.close()

        _run_alembic("upgrade", MU3A_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _current_revision(conn) == MU3A_REVISION
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


#: MU-3A'dan SONRA eklenen üyeler — eklendikleri revizyon SIRASIYLA.
#: Yeni bir aile fişlendiğinde buraya EKLENİR; eklenmezse aşağıdaki iddia
#: kırılır ve üyenin bir migration'ı olduğu SORULUR.
LATER_LABELS = [
    "equipment_rental_invoice",  # MU-3D · b7c8d9e0f1a2
]


def test_MODEL_enum_uyeleri_MIGRATION_ZINCIRIYLE_AYNIDIR():
    """🔴 Model = MU-3A tabanı + sonradan `ADD VALUE` ile eklenenler, SIRASIYLA.

    Model doğrudan `EXPECTED_LABELS` ile karşılaştırılamaz: o liste MU-3A
    revizyonundaki DB hâlidir ve MU-3D altıncı üyeyi eklemiştir. Ama
    karşılaştırma BÜTÜNÜYLE de kaldırılamazdı — kaldırılsaydı modele eklenip
    hiçbir migration'a yazılmayan bir üye canlıda `invalid input value for
    enum` ile YALNIZ ÜRETİMDE patlardı.

    🔴 SIRA da iddianın parçasıdır: `ALTER TYPE … ADD VALUE` üyeyi DAİMA SONA
    ekler ve `enum_range` o sırayı döner. Model sınıfında üye araya sokulsaydı
    iki katman AYRIŞIR ve `enum_range`e güvenen her ölçüm yanılırdı.
    """
    assert [uye.value for uye in JournalSourceType] == EXPECTED_LABELS + LATER_LABELS


# --------------------------------------------------------------------------- #
# Migration'ın ÜRETTİĞİ şemanın semantiği
# --------------------------------------------------------------------------- #


async def test_migrate_edilmis_semada_kisitlar_ISIRIR():
    """🔴 Dört kural, MIGRATION'IN ürettiği şema üzerinde ölçülür.

    `Base.metadata.create_all` ile kurulan test şeması BURADA KULLANILMAZ:
    modele eklenip migration'a yazılmayı unutulan bir kısıt orada yeşil kalır,
    canlıda ise HİÇ OLMAZDI.
    """
    database = await _create_scratch()
    try:
        _run_alembic("upgrade", MU3A_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            user_id = await _seed_user(conn)
            belge_id = uuid.uuid4()

            # 1. Elle fişler (kaynak NULL) BİRBİRİNİ ENGELLEMEZ.
            await _insert_entry(conn, user_id, entry_no="YEV-2026-0001")
            await _insert_entry(conn, user_id, entry_no="YEV-2026-0002")

            # 2. Aynı belgeye İKİNCİ fiş → UNIQUE.
            await _insert_entry(
                conn,
                user_id,
                entry_no="YEV-2026-0003",
                source_type=JournalSourceType.invoice.value,
                source_id=belge_id,
            )
            with pytest.raises(asyncpg.UniqueViolationError):
                await _insert_entry(
                    conn,
                    user_id,
                    entry_no="YEV-2026-0004",
                    source_type=JournalSourceType.invoice.value,
                    source_id=belge_id,
                )

            # 3. FARKLI aile, AYNI kimlik → serbest.
            await _insert_entry(
                conn,
                user_id,
                entry_no="YEV-2026-0005",
                source_type=JournalSourceType.payment.value,
                source_id=belge_id,
            )

            # 4. YARIM çift → CHECK.
            with pytest.raises(asyncpg.CheckViolationError):
                await _insert_entry(
                    conn,
                    user_id,
                    entry_no="YEV-2026-0006",
                    source_type=JournalSourceType.invoice.value,
                    source_id=None,
                )
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


async def test_posting_rules_kisitlari_ISIRIR():
    """Rol biçimi · `(tür, rol)` tekilliği · hesabın RESTRICT ile korunması."""
    database = await _create_scratch()
    try:
        _run_alembic("upgrade", MU3A_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            # 🔴 `320` TDHP seed migration'ıyla ZATEN VARDIR (elle eklemek
            # `uq_chart_of_accounts_code`e çarpar) — ve KARAR-2'nin cari ana
            # hesabı tam olarak odur, uydurma bir kod ölçümü zayıflatırdı.
            account_id = await conn.fetchval("SELECT id FROM chart_of_accounts WHERE code = '320'")
            assert account_id is not None, "TDHP seed'inde `320 Satıcılar` yok"

            async def _kural(role_key: str, *, source: str = "invoice") -> None:
                await conn.execute(
                    "INSERT INTO posting_rules (id, source_type, role_key, account_id) "
                    f"VALUES ($1, $2::{SOURCE_ENUM}, $3, $4)",
                    uuid.uuid4(),
                    source,
                    role_key,
                    account_id,
                )

            await _kural("payable")

            # Biçim: büyük harf REDDEDİLİR — `Payable` ile `payable` iki AYRI
            # satır olabilseydi hangisinin çözüleceği yazım tercihi olurdu.
            with pytest.raises(asyncpg.CheckViolationError):
                await _kural("Payable")

            # Bir rolün TEK hesabı olur.
            with pytest.raises(asyncpg.UniqueViolationError):
                await _kural("payable")

            # Aynı rol BAŞKA ailede serbesttir (anahtar ÇİFTTİR).
            await _kural("payable", source="payment")

            # 🔴 RESTRICT: eşlemesi olan hesap SİLİNEMEZ.
            with pytest.raises(RESTRICT_ERRORS):
                await conn.execute("DELETE FROM chart_of_accounts WHERE id = $1", account_id)
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)
