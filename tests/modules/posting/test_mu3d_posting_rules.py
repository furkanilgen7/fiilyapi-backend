"""🔴 MU-3D — ÜÇ HAKEDİŞ AİLESİNİN `posting_rules` TOHUMU + enum üyesi.

## Neden İKİ KATMAN

`a4b5c6d7e8f9` migration'ı üç ürün demetini de BİLEREK IMPORT ETMEZ (K1
kanonu: uygulanmış bir migration DONMUŞ olmalıdır) ve eşlemeyi DONMUŞ BİR
KOPYA olarak taşır. Bedeli, iki katmanın sessizce ayrışabilmesidir: ürün demeti
`740`ı `170`e çevirse bile migration eski kodu tohumlar ve CANLI, kodun
anlattığından BAŞKA bir hesaba fiş atardı. Bu dosya o bedeli ödettirir
(MU-3B/MU-3C deseni).

🔴 Bu dosya migration'ı kendi TEK KULLANIMLIK veritabanında koşar; `.env` ve
`TEST_DATABASE_URL` veritabanı ELLENMEZ.
"""

import ast
import uuid
from pathlib import Path

import asyncpg

from app.modules.accounting.models import JournalSourceType
from app.modules.equipment.rental_posting import RENTAL_POSTING_RULES
from app.modules.progress_payments.posting import PROGRESS_PAYMENT_POSTING_RULES
from app.modules.subcontractor_progress_payments.posting import SUBCONTRACTOR_POSTING_RULES
from tests.modules.accounting._mu1_migration import (
    BACKEND_DIR,
    _asyncpg_dsn,
    _drop_scratch_database,
    _run_alembic,
)

ENUM_REVISION = "b7c8d9e0f1a2"
SEED_REVISION = "a4b5c6d7e8f9"
PARENT_REVISION = "d2e3f4a5b6c7"
MIGRATION_PATH = Path("alembic") / "versions" / "a4b5c6d7e8f9_mu3d_hakedis_posting_rules_tohumu.py"
SOURCE_ENUM = "journal_source_type"

#: 🔴 ÜRÜN demetleri, `source_type` ile eşlenmiş — migration'ın SEED_RULES'ü ile
#: BİREBİR (sıra dahil) aynı olmalıdır.
URUN_DEMETLERI: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    (JournalSourceType.progress_payment.value, PROGRESS_PAYMENT_POSTING_RULES),
    (JournalSourceType.subcontractor_progress_payment.value, SUBCONTRACTOR_POSTING_RULES),
    (JournalSourceType.equipment_rental_invoice.value, RENTAL_POSTING_RULES),
)


def _migration_seed_rules():
    """`SEED_RULES` demetini AST'den okur — migration IMPORT EDİLMEZ.

    Import edilseydi `alembic.op` bağlamı olmadan modül yan etkileri koşar ve
    test, ölçtüğü şeyin dışında bir sebeple kırılabilirdi.
    """
    agac = ast.parse((BACKEND_DIR / MIGRATION_PATH).read_text())
    for dugum in agac.body:
        hedef = getattr(dugum, "target", None) or getattr(dugum, "targets", [None])[0]
        if isinstance(hedef, ast.Name) and hedef.id == "SEED_RULES":
            return ast.literal_eval(dugum.value)
    raise AssertionError("migration'da `SEED_RULES` bulunamadı")


def test_migration_tohumu_UC_URUN_demetiyle_BIREBIR_ayni():
    """🔴 İKİ KATMAN EŞİTLİĞİ — aile sırası ve rol sırası DAHİL."""
    assert _migration_seed_rules() == URUN_DEMETLERI


def test_ISVEREN_ailesi_OTEKI_IKISININ_AYNASIDIR():
    """🔴 Kullanıcı kararının metni *"gider + cari borç"* der; bu işveren
    hakedişi için TERSTİR ve kod ÖLÇÜLEREK yazılmıştır.

    `progress_payments` bizim işverene KESTİĞİMİZ hakediştir → ALACAK + HASILAT.
    Roller ters tohumlansaydı mizan her işveren hakedişinde iki KAT tutar kadar
    oynar, faturanın stornosu hiçbir şeyi netlemezdi ve fiş yine DENGELİ
    göründüğü için hiçbir toplam bunu ele vermezdi.
    """
    assert PROGRESS_PAYMENT_POSTING_RULES == (("receivable", "120"), ("revenue", "600"))
    assert SUBCONTRACTOR_POSTING_RULES == (("expense", "740"), ("payable", "320"))
    assert RENTAL_POSTING_RULES == (("expense", "740"), ("payable", "320"))


def test_KDV_ROLU_UC_AILEDE_de_TANIMSIZDIR():
    """🔴 BU DİLİMİN EN AĞIR VERİ İDDİASI.

    Hakediş fişi KDV'SİZDİR. `vat_input`/`vat_output` rolleri bu üç ailede
    TANIMLI OLSAYDI bir bacak onlara düşebilir, fiş yine dengeli kalır ve mizan
    DOĞRU görünürdü — kusuru yalnızca beyanname ile yevmiyenin karşılaştırılması
    ele verirdi ve o karşılaştırma yılda bir yapılır.

    `accounting.vat_return` beyannameyi YALNIZ `invoices`tan türetir ve kaynak
    süzgeci YOKTUR; hakedişe KDV yazılsaydı MU-3B'nin *"beyanname == yevmiye"*
    kimliği kuruş toleransı olmadan ve SESSİZCE bozulurdu.
    """
    yasak = {"vat_input", "vat_output", "vat"}
    for _source_type, kurallar in URUN_DEMETLERI:
        roller = {rol for rol, _kod in kurallar}
        assert not (roller & yasak), f"{_source_type} ailesinde KDV rolü TANIMLI: {roller & yasak}"


def test_KARAR_1_yillara_yaygin_rejim_HICBIR_ailede_YOK():
    """🔴 KARAR-1 · NORMAL TİCARİ REJİM. `170`/`350` seed'de VARDIR ama ÖLÜDÜR."""
    for _source_type, kurallar in URUN_DEMETLERI:
        kodlar = {kod for _rol, kod in kurallar}
        assert not (kodlar & {"170", "350"}), f"{_source_type}: yıllara yaygın hesap SEÇİLMİŞ"


def test_KARAR_2_alt_hesap_ACILMAZ():
    """Cari ANA hesap (`320`/`120`); `320.04` MU-4'e kaldı."""
    for _source_type, kurallar in URUN_DEMETLERI:
        for _rol, kod in kurallar:
            assert "." not in kod, f"{_source_type}: alt hesap kodu tohumlanmış ({kod})"


async def _scratch() -> str:
    database = f"mu3d_seed_{uuid.uuid4().hex[:8]}"
    admin = await asyncpg.connect(_asyncpg_dsn("postgres"))
    try:
        await admin.execute(f'CREATE DATABASE "{database}"')
    finally:
        await admin.close()
    return database


async def _enum_labels(conn: asyncpg.Connection) -> list[str]:
    return await conn.fetchval(
        "SELECT array_agg(enumlabel::text ORDER BY enumsortorder) "
        "FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid WHERE t.typname = $1",
        SOURCE_ENUM,
    )


async def _kural_kodlari(conn: asyncpg.Connection, source_type: str):
    return await conn.fetch(
        "SELECT r.role_key, h.code FROM posting_rules r "
        "JOIN chart_of_accounts h ON h.id = r.account_id "
        "WHERE r.source_type::text = $1 ORDER BY r.role_key",
        source_type,
    )


async def test_ENUM_uyesi_SONA_eklenir_ve_tohum_UC_AILEYI_de_kurar():
    """🔴 Üye SIRASI kilitlidir + tohum migration'ın ÜRETTİĞİ şemada ölçülür.

    🔴 Ayrıca ölçülen şey: `ADD VALUE` ile TOHUM AYRI migration'lardır ve
    olmak ZORUNDADIR (`ADD VALUE` + değeri KULLANMA aynı işlemde HATA). İkisi
    birleştirilseydi bu test `unsafe use of new value` ile kırmızıya dönerdi.
    """
    database = await _scratch()
    try:
        _run_alembic("upgrade", PARENT_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            oncesi = await _enum_labels(conn)
            assert JournalSourceType.equipment_rental_invoice.value not in oncesi, (
                "üye MU-3D'den ÖNCE de vardı — test bir şey ölçmüyor"
            )
        finally:
            await conn.close()

        _run_alembic("upgrade", SEED_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            etiketler = await _enum_labels(conn)
            assert etiketler == [uye.value for uye in JournalSourceType], (
                f"enum SIRASI modelden ayrıştı: {etiketler}"
            )
            assert etiketler[-1] == JournalSourceType.equipment_rental_invoice.value, (
                "yeni üye SONA eklenmedi — `enum_range`e güvenen her ölçüm yanılır"
            )

            for source_type, kurallar in URUN_DEMETLERI:
                satirlar = await _kural_kodlari(conn, source_type)
                assert sorted((r["role_key"], r["code"]) for r in satirlar) == sorted(kurallar), (
                    f"{source_type} tohumu ÜRÜN demetiyle ayrıştı: {satirlar}"
                )
        finally:
            await conn.close()

        _run_alembic("downgrade", ENUM_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            for source_type, _kurallar in URUN_DEMETLERI:
                assert not await _kural_kodlari(conn, source_type), (
                    f"{source_type} kuralları downgrade'de DÜŞMEDİ"
                )
        finally:
            await conn.close()

        # 🔴 Tur dönüşü: ikinci upgrade `ON CONFLICT DO NOTHING` sayesinde GEÇER.
        _run_alembic("upgrade", SEED_REVISION, database=database)
    finally:
        await _drop_scratch_database(database)


async def test_HESAP_PLANI_BOSKEN_migration_PATLAMAZ_ve_kural_URETMEZ():
    """🔴 `raise` YOKTUR — `Dockerfile`daki `&&` uvicorn'u HİÇ BAŞLATMAZDI.

    `chart_of_accounts` boş bir veritabanında `INSERT … SELECT`in JOIN'i hiçbir
    satır üretmez ve migration WARNING düşüp BAŞARIYLA biter. Fail-closed olan
    taraf çalışma zamanıdır: `post_document` çözemediği rolde **422** verir.

    🔴 Bu dal ölçülmeseydi, eksik hesap yüzünden patlayan bir migration canlı
    açılışı KİLİTLERDİ ve bunu hiçbir yeşil test göstermezdi.
    """
    database = await _scratch()
    try:
        # Tohum migration'ları hesap planını doldurmaz; hesaplar MU-SEED'dedir.
        _run_alembic("upgrade", SEED_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            hesap_sayisi = await conn.fetchval("SELECT count(*) FROM chart_of_accounts")
            if hesap_sayisi:
                # Hesap planı tohumluysa kurallar da kurulmuş olmalıdır.
                for source_type, kurallar in URUN_DEMETLERI:
                    assert len(await _kural_kodlari(conn, source_type)) == len(kurallar)
            else:
                for source_type, _kurallar in URUN_DEMETLERI:
                    assert not await _kural_kodlari(conn, source_type), (
                        "hesapsız veritabanında kural ÜRETİLDİ"
                    )
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)
