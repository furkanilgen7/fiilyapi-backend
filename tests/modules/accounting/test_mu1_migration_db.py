"""MU-1 T2 — muhasebe şeması: MİGRATION TUR DÖNÜŞÜ + DB SEMANTİĞİ.

`test_mu1_migration.py`nin ikinci parçası (800 satır tavanı bölmesi); paylaşılan
yardımcılar `_mu1_migration.py`dedir.

NEDEN AYRI BİR TUR DÖNÜŞÜ TESTİ: bu migration **İKİ** yeni Postgres enum tipi
getiriyor (`chart_account_type` / `journal_entry_status`). Birini bile
downgrade'de düşürmeyi unutmak ikinci `upgrade`i "type already exists" ile
patlatır (`d4e5f6a7b8c9` dersi) ve bu **yalnız canlıda** görülürdü.

DB SEMANTİĞİ bu dilimde **K1'in son savunmasıdır**: tek taraflılık, negatif tutar
yasağı, `debit`/`credit` NOT NULL, dengesiz fişin `posted` olamaması, dönem–tarih
kilidi, kod dilbilgisi, iki UNIQUE ve üç FK davranışı.

Test kendi TEK KULLANIMLIK veritabanını açar ve sonunda düşürür; `.env` ve
`TEST_DATABASE_URL` veritabanı ELLENMEZ.

⚠️ PG SÜRÜM TUZAĞI: yerel 18, CI 16 — RESTRICT ihlali sürüme göre 23001 veya
23503 bildirir; iddialar bu yüzden DAR bir tuple ile iki sınıfı da kabul eder.
"""

import subprocess

import asyncpg
import pytest

from ._mu1_migration import (
    ALEMBIC_CMD,
    BACKEND_DIR,
    CONSTRAINTS,
    EXPECTED_ENUM_LABELS,
    HZ1_REVISION,
    INDEXES,
    MU1_REVISION,
    NEW_ENUMS,
    RESTRICT_ERRORS,
    TABLES,
    _asyncpg_dsn,
    _constraint_exists,
    _create_scratch_database,
    _current_revision,
    _drop_scratch_database,
    _enum_exists,
    _enum_labels,
    _index_exists,
    _insert_account,
    _insert_entry,
    _insert_line,
    _run_alembic,
    _seed_user,
    _table_exists,
)


def test_alembic_has_single_head():
    """İki head = canlıda deploy kilitlenmesi (`alembic upgrade head` patlar)."""
    result = subprocess.run(
        [*ALEMBIC_CMD, "heads"],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    heads = [line for line in result.stdout.splitlines() if line.strip()]
    # Head'in KİMLİĞİ iddia EDİLMEZ (repo kanonu): sonraki dilim head'i ileri
    # taşıdığında bu test ilgisiz yere kırılırdı.
    assert len(heads) == 1, f"tek head bekleniyordu, çıktı:\n{result.stdout}"


def test_migration_parent_is_the_expected_revision():
    """🔴 Ebeveyn `c4d5e6f7a8b9` (HZ-1). Arada başka bir dilim merge edilirse
    re-parent ŞART — bu sabit ve migration BİRLİKTE güncellenir (P8/TH dersi)."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(str(BACKEND_DIR / "alembic.ini")))
    revision = script.get_revision(MU1_REVISION)
    assert revision.down_revision == HZ1_REVISION


async def test_upgrade_downgrade_upgrade_round_trip():
    """🔴 İKİ yeni enum downgrade'de DÜŞER; düşmezse ikinci upgrade patlar."""
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", MU1_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            for table in TABLES:
                assert await _table_exists(conn, table), table
            for enum_name in NEW_ENUMS:
                assert await _enum_exists(conn, enum_name), enum_name
                assert await _enum_labels(conn, enum_name) == EXPECTED_ENUM_LABELS[enum_name]
            for index in INDEXES:
                assert await _index_exists(conn, index), index
            for constraint in CONSTRAINTS:
                assert await _constraint_exists(conn, constraint), constraint
            assert await _current_revision(conn) == MU1_REVISION
        finally:
            await conn.close()

        _run_alembic("downgrade", HZ1_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            for table in TABLES:
                # Kalan bir tablo İKİNCİ upgrade'i "already exists" ile patlatırdı.
                assert not await _table_exists(conn, table), table
            for enum_name in NEW_ENUMS:
                assert not await _enum_exists(conn, enum_name), (
                    f"{enum_name} tipi downgrade'de kalmış — ikinci upgrade patlar"
                )
            # Komşu modüller AYAKTA: MU-1 hiçbir tabloya ADDITIVE kolon eklemez
            # (fatura/hazine → otomatik fiş MU-3'ün işidir).
            for komsu in ("invoices", "payments", "bank_accounts", "users"):
                assert await _table_exists(conn, komsu), komsu
            assert await _current_revision(conn) == HZ1_REVISION
        finally:
            await conn.close()

        _run_alembic("upgrade", MU1_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            for table in TABLES:
                assert await _table_exists(conn, table), table
            for enum_name in NEW_ENUMS:
                assert await _enum_exists(conn, enum_name), enum_name
            assert await _current_revision(conn) == MU1_REVISION
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


# --------------------------------------------------------------------------- #
# DB semantigi — K1'in SON savunmasi
# --------------------------------------------------------------------------- #


async def test_db_level_line_semantics():
    """🔴 K1 KATMAN 2 — satır ayağı. Servis 422 vermeyi unutsa bile:
    çift-dolu satır, `(0,0)` satırı, negatif tutar ve NULL tutar DB'ye GİREMEZ.

    NULL'ın ayrı iddia edilmesinin sebebi: `debit=NULL, credit=NULL` olan satır
    `SUM` tarafından YUTULUR, iki toplam da değişmez ve **dengesiz fiş dengede
    sayılır**. `single_side` CHECK'i bunu YAKALAMAZ (NULL karşılaştırması NULL
    üretir ve CHECK'i geçer) — kapatan şey `nullable=False`tır."""
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", MU1_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            user_id = await _seed_user(conn)
            account_id = await _insert_account(conn, "100")
            entry_id = await _insert_entry(conn, user_id)

            # Tek taraflı satırlar KABUL: borç bacağı ve alacak bacağı.
            await _insert_line(conn, entry_id, account_id, debit="100.00", credit="0")
            await _insert_line(conn, entry_id, account_id, debit="0", credit="100.00", sort_order=1)

            # Sunucu varsayılanları: iki taraf da 0 (satır tek taraflı CHECK'e
            # takılır, yani varsayılan tek başına bir satır AÇAMAZ).
            row = await conn.fetchrow(
                "SELECT debit, credit FROM journal_lines WHERE entry_id = $1 AND sort_order = 0",
                entry_id,
            )
            assert row["debit"] == 100
            assert row["credit"] == 0

            # 🔴 ÇİFT DOLU satır: E8'in her satırının boş tarafı `—`dir.
            with pytest.raises(asyncpg.CheckViolationError):
                await _insert_line(conn, entry_id, account_id, debit="50.00", credit="50.00")

            # 🔴 `(0,0)`: toplama katkısı olmayan satır fişi şişiremez.
            with pytest.raises(asyncpg.CheckViolationError):
                await _insert_line(conn, entry_id, account_id, debit="0", credit="0")

            # 🔴 NEGATİF tutar: bir borç satırına `-100` yazıp sahte denge
            # kurmak yapısal olarak imkânsızdır.
            with pytest.raises(asyncpg.CheckViolationError):
                await _insert_line(conn, entry_id, account_id, debit="-100.00", credit="0")
            with pytest.raises(asyncpg.CheckViolationError):
                await _insert_line(conn, entry_id, account_id, debit="0", credit="-100.00")

            # 🔴 NULL tutar (fail-closed'un YAPISAL garantisi).
            for debit, credit in ((None, "100.00"), ("100.00", None), (None, None)):
                with pytest.raises(asyncpg.NotNullViolationError):
                    await _insert_line(conn, entry_id, account_id, debit=debit, credit=credit)

            # `account_id` RESTRICT: fiş satırı olan hesap SİLİNEMEZ.
            with pytest.raises(RESTRICT_ERRORS):
                await conn.execute("DELETE FROM chart_of_accounts WHERE id = $1", account_id)

            # `entry_id` CASCADE: başlık silinince satırlar gider.
            await conn.execute("DELETE FROM journal_entries WHERE id = $1", entry_id)
            kalan = await conn.fetchval(
                "SELECT count(*) FROM journal_lines WHERE entry_id = $1", entry_id
            )
            assert kalan == 0
            # Satırı kalmayan hesap artık silinebilir.
            await conn.execute("DELETE FROM chart_of_accounts WHERE id = $1", account_id)
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


async def test_db_level_entry_semantics():
    """🔴 K1 KATMAN 2 — başlık ayağı + K9 dönem kilidi + K2 storno tekilliği.

    `total_*` NOT NULL'ın AYRI iddiası: nullable olsalardı `NULL = NULL` **NULL**
    üretir, `ck_journal_entries_posted_balanced` NULL sonucu REDDETMEZ ve
    dengesiz bir fiş `posted` damgalanabilirdi."""
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", MU1_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            user_id = await _seed_user(conn)

            # 🔴 Taslak DENGESİZ bırakılabilir: K1 kapısı kayıtlaştırma anında
            # yeniden koşar, taslak hâlâ yazılırken dengesiz olabilir.
            draft_id = await _insert_entry(
                conn, user_id, status="draft", total_debit="100.00", total_credit="0"
            )
            assert draft_id is not None

            # 🔴 DENGESİZ fiş `posted` OLAMAZ.
            with pytest.raises(asyncpg.CheckViolationError):
                await _insert_entry(
                    conn, user_id, status="posted", total_debit="100.00", total_credit="90.00"
                )

            # Dengeli fiş `posted` olur.
            posted_id = await _insert_entry(
                conn, user_id, status="posted", total_debit="100.00", total_credit="100.00"
            )

            # 🔴 `total_*` NOT NULL — nullable olsalardı denge CHECK'i sessizce
            # devre dışı kalırdı.
            with pytest.raises(asyncpg.NotNullViolationError):
                await conn.execute(
                    "UPDATE journal_entries SET total_credit = NULL WHERE id = $1", posted_id
                )

            # Negatif toplam REDDEDİLİR.
            with pytest.raises(asyncpg.CheckViolationError):
                await _insert_entry(
                    conn, user_id, total_debit="-1.00", total_credit="-1.00", status="draft"
                )

            # 🔴 K9: `entry_date` 2026-07-17 iken `period_month = 8` KAYAMAZ.
            with pytest.raises(asyncpg.CheckViolationError):
                await _insert_entry(conn, user_id, entry_date="2026-07-17", period_month=8)
            with pytest.raises(asyncpg.CheckViolationError):
                await _insert_entry(conn, user_id, entry_date="2026-07-17", period_year=2025)
            # Doğru dönem KABUL (yıl sınırı dahil).
            await _insert_entry(
                conn, user_id, entry_date="2026-12-31", period_year=2026, period_month=12
            )

            # 🔴 Bir fişin en fazla BİR stornosu olur.
            await _insert_entry(
                conn,
                user_id,
                status="posted",
                total_debit="100.00",
                total_credit="100.00",
                reversal_of_id=posted_id,
            )
            with pytest.raises(asyncpg.UniqueViolationError):
                await _insert_entry(
                    conn,
                    user_id,
                    status="posted",
                    total_debit="100.00",
                    total_credit="100.00",
                    reversal_of_id=posted_id,
                )

            # 🔴 …ama stornosu OLMAYAN fiş sayısı SINIRSIZDIR: PG çok sayıda
            # NULL'a izin verir. Bu ayrıca iddia edilir, yoksa kısıt "her fişin
            # bir stornosu olmalı" diye yanlış anlaşılırdı.
            for _ in range(3):
                await _insert_entry(conn, user_id, reversal_of_id=None)
            null_sayisi = await conn.fetchval(
                "SELECT count(*) FROM journal_entries WHERE reversal_of_id IS NULL"
            )
            assert null_sayisi >= 4

            # RESTRICT: stornosu olan fiş ve fişi giren kullanıcı silinemez.
            with pytest.raises(RESTRICT_ERRORS):
                await conn.execute("DELETE FROM journal_entries WHERE id = $1", posted_id)
            with pytest.raises(RESTRICT_ERRORS):
                await conn.execute("DELETE FROM users WHERE id = $1", user_id)
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


async def test_db_level_account_code_semantics():
    """🔴 K4 kod dilbilgisi DB'de zorlanır. `NNN.NN.NNN` (üçüncü kırılım)
    hiçbir mockup'ta YOKTUR ve YAPISAL olarak reddedilir — açılsaydı mizanın
    (MU-2) hiç görmediği bir düzey doğardı. İlk hane `0` olamaz: sınıfsız hesap
    yoktur."""
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", MU1_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            # KABUL: grup `NN` · ana hesap `NNN` · alt hesap `NNN.NN`.
            for kod in ("10", "100", "120.01", "19", "191", "257", "600", "730", "999.99"):
                await _insert_account(conn, kod)

            # RET: tek hane (sınıf KAYIT DEĞİLDİR) · sıfırla başlayan · dört
            # hane · tek haneli kırılım · üçüncü kırılım · harf.
            for kod in (
                "0",
                "1",
                "01",
                "0.01",
                "1200",
                "120.1",
                "120.011",
                "120.01.001",
                "abc",
                "12a",
                "120,01",
                "",
                " 120",
            ):
                with pytest.raises(asyncpg.CheckViolationError):
                    await _insert_account(conn, kod)

            # 🔴 Aynı kod iki kez giremez: yevmiye satırları iki karta bölünür
            # ve bakiye (K3) ikiye ayrılırdı.
            with pytest.raises(asyncpg.UniqueViolationError):
                await _insert_account(conn, "100", name="Kasa 2")

            # `is_active` sunucu varsayılanı AÇIK (HP:62 yeşil nokta).
            aktif = await conn.fetchval(
                "SELECT is_active FROM chart_of_accounts WHERE code = '100'"
            )
            assert aktif is True

            # Dört tür de yazılabilir (HP:78/154/192/199).
            for i, tur in enumerate(("asset", "liability", "revenue", "expense")):
                await _insert_account(conn, f"{i + 2}00.01", account_type=tur)
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)
