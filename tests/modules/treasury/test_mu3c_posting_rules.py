"""MU-3C + ODM-1 — `posting_rules` TOHUMU: iki katman eşitliği + migration davranışı.

## Neden İKİ KATMAN

Tohum migration'ları `app.modules.treasury.posting`i BİLEREK IMPORT ETMEZ (K1
kanonu: uygulanmış bir migration DONMUŞ olmalıdır, uygulama kodu zamanla
değişir) ve eşlemeyi DONMUŞ BİR KOPYA olarak taşır. Bedeli, iki metnin sessizce
ayrışabilmesidir: ürün demeti `102`yi `101`e çevirse bile migration eski kodu
tohumlar ve CANLI, kodun anlattığından BAŞKA bir hesaba fiş atardı. Bu dosya o
bedeli ödettirir (MU-3B deseni).

## 🔴 ODM-1 — `payment` ailesi ARTIK İKİ MIGRATION'DAN TOHUMLANIR

`d1e2f3a4b5c6` dört satırı (`102`/`100`/`320`/`120`), `a6b7c8d9e0f1` iki satırı
(`101`/`103`) tohumlar. Eşitlik testi tek bir migration'a bakamaz: BİRLEŞİMİ
ürün demetiyle karşılaştırır. Yalnız yeni migration'a bakılsaydı, biri eski
migration'ın satırlarını ürün demetinden düşürdüğünde test YEŞİL kalırdı.

🔴 Bu dosya migration'ı kendi TEK KULLANIMLIK veritabanında koşar; `.env` ve
`TEST_DATABASE_URL` veritabanı ELLENMEZ.
"""

import ast
import uuid
from pathlib import Path

import asyncpg

from app.modules.accounting.models import JournalSourceType
from app.modules.invoicing.posting import INVOICE_POSTING_RULES
from app.modules.treasury.instruments.posting import INSTRUMENT_POSTING_RULES
from app.modules.treasury.posting import PAYMENT_POSTING_RULES
from tests.modules.accounting._mu1_migration import (
    BACKEND_DIR,
    _asyncpg_dsn,
    _drop_scratch_database,
    _run_alembic,
)

MU3B_SEED_REVISION = "c0d1e2f3a4b5"
MU3C_SEED_REVISION = "d1e2f3a4b5c6"
ODM1_ENUM_REVISION = "f5a6b7c8d9e0"
ODM1_SEED_REVISION = "a6b7c8d9e0f1"

VERSIONS = Path("alembic") / "versions"
MU3C_MIGRATION_PATH = VERSIONS / "d1e2f3a4b5c6_mu3c_odeme_posting_rules_tohumu.py"
ODM1_MIGRATION_PATH = VERSIONS / "a6b7c8d9e0f1_odm1_cek_posting_rules_tohumu.py"

SOURCE_ENUM = "journal_source_type"
PAYMENT_SOURCE = JournalSourceType.payment.value
INSTRUMENT_SOURCE = JournalSourceType.financial_instrument.value


def _seed_rules(migration_path: Path):
    """`SEED_RULES` demetini AST'den okur — migration IMPORT EDİLMEZ.

    Import edilseydi `alembic.op` bağlamı olmadan modül yan etkileri koşar ve
    test, ölçtüğü şeyin dışında bir sebeple kırılabilirdi.
    """
    agac = ast.parse((BACKEND_DIR / migration_path).read_text())
    for dugum in agac.body:
        hedef = getattr(dugum, "target", None) or getattr(dugum, "targets", [None])[0]
        if isinstance(hedef, ast.Name) and hedef.id == "SEED_RULES":
            return ast.literal_eval(dugum.value)
    raise AssertionError(f"{migration_path}: `SEED_RULES` bulunamadı")


def _odm1_aile(source_type: str) -> tuple[tuple[str, str], ...]:
    for aile, kurallar in _seed_rules(ODM1_MIGRATION_PATH):
        if aile == source_type:
            return tuple(tuple(satir) for satir in kurallar)
    raise AssertionError(f"ODM-1 tohumunda `{source_type}` ailesi YOK")


def test_ODEME_ailesi_IKI_MIGRATION_BIRLESIMI_urun_demetiyle_BIREBIR_ayni():
    """🔴 İKİ KATMAN EŞİTLİĞİ — ODM-1'den sonra üç parçalı.

    Birleşim küme olarak karşılaştırılır (satırlar iki AYRI migration'dan
    gelir, aralarında bir sıra yoktur) ama ürün demetinin KENDİ sırası ayrıca
    kilitlenir: alfabetiktir ve ODM-1 satırları demetin ORTASINA girer.
    """
    mu3c = tuple(tuple(satir) for satir in _seed_rules(MU3C_MIGRATION_PATH))
    odm1 = _odm1_aile(PAYMENT_SOURCE)
    birlesim = mu3c + odm1

    assert len(birlesim) == len(set(birlesim)), "iki migration AYNI satırı tohumluyor"
    assert sorted(birlesim) == sorted(PAYMENT_POSTING_RULES), (
        "migration tohumu ürün demetiyle AYRIŞTI — canlı, kodun anlattığından "
        f"BAŞKA bir hesaba fiş atar: {sorted(birlesim)}"
    )
    assert PAYMENT_POSTING_RULES == tuple(sorted(PAYMENT_POSTING_RULES)), (
        "ürün demeti rol adına göre ALFABETİK değil — iki katman eşitliği sıraya dayanır"
    )


def test_CEK_ailesi_tohumu_URUN_demetiyle_BIREBIR_ayni():
    """🔴 `financial_instrument` ailesi TEK migration'dan gelir → sıra DAHİL."""
    assert _odm1_aile(INSTRUMENT_SOURCE) == INSTRUMENT_POSTING_RULES


def test_CEK_ARA_HESAPLARI_101_ve_103_TOHUMLANIR():
    """🔴 ODM-1 — MU-3C'nin `101/103 TOHUMLANMAZ` bekçisi TERSİNE ÇEVRİLDİ.

    Eski bekçi *"çek/senet geçişleri fiş ATMAZ, ara hesap AÇILMAZ"* diyordu ve
    gerekçesi ölçülmüştü: o gün nakdin tek tanımı `Σ payments`tı, portföy o
    formüle terim katmıyordu, dolayısıyla bir çek fişi yevmiyeden türeyen nakdi
    Hazine'nin kendi bakiyesinden AYIRIRDI. MU-3C aynı yerde doğrusunun
    `101`/`103` olduğunu ve bunun **bir ÜRÜN KARARI** olduğunu da yazıyordu.

    ODM-1 o karardır: nakit tanımı `treasury/balance.py`de süzgeç kazanır
    (bağlı ödeme yalnız `collected`/`paid` iken nakit sayılır), ayrışma
    YAPISAL olarak kapanır ve ara hesaplar AÇILIR.

    Bu test kararın kendisini kilitler: `101`/`103` **İKİ ailede de** bir role
    bağlıdır. Yalnız birinde olsaydı çekin bir bacağı ara hesabı açar, öteki
    onu KAPATAMAZ ve `101` sonsuza dek dolu kalırdı.
    """
    for demet in (PAYMENT_POSTING_RULES, INSTRUMENT_POSTING_RULES):
        esleme = dict(demet)
        assert esleme["instrument_receivable"] == "101", "alınan çek `101`e bağlanmadı"
        assert esleme["instrument_payable"] == "103", "verilen çek `103`e bağlanmadı"


def test_CIFT_SAYIM_YOK_gider_ve_hasilat_rolleri_ODEME_ailesinde_TANIMSIZ():
    """🔴 BU DİLİMİN EN AĞIR VERİ İDDİASI.

    Ödeme fişi cariyi kapatır; gider/hasılat MU-3B'de ZATEN yazılmıştır.
    `740`/`600` (ve öteki sonuç hesapları) bu ailede TANIMLI OLSAYDI bir bacak
    onlara düşebilir, fiş yine dengeli kalır ve mizan DOĞRU görünürdü — kusuru
    hiçbir kolon farkı ele vermezdi. Fail-closed olan taraf tanımsızlıktır:
    `post_document` çözemediği rolde **422** verir.
    """
    kodlar = {kod for _rol, kod in PAYMENT_POSTING_RULES}

    assert "740" not in kodlar, "ÇİFT SAYIM: ödeme fişi gidere dokunuyor"
    assert "600" not in kodlar, "ÇİFT SAYIM: ödeme fişi hasılata dokunuyor"
    # Kalan bacaklar YALNIZ nakit + çek ara hesabı + cari.
    assert kodlar == {"100", "101", "102", "103", "120", "320"}


def test_CIFT_SAYIM_YOK_gider_hasilat_ve_CARI_rolleri_CEK_ailesinde_TANIMSIZ():
    """🔴 `payment` ailesindeki emsalin KARDEŞİ — ve bir madde DAHA sert.

    Çek tahsili yalnızca paranın YERİNİ değiştirir:

        B 102 Bankalar  ·  A 101 Alınan Çekler

    * `740`/`600` tanımlı olsaydı aynı gider/hasılat ÜÇÜNCÜ kez yazılabilirdi
      (fatura + ödeme + çek) ve fiş yine dengeli görünürdü.
    * 🔴 `120`/`320` de TANIMSIZDIR ve bu ailede olması `740`dan DAHA
      tehlikelidir: cari ZATEN ödeme fişinde kapanmıştır, burada bir kez daha
      kapansaydı müşterinin borcu tahsilat başına İKİ KAT düşer ve bakiye
      NEGATİFE geçerdi.

    Fail-closed olan taraf tanımsızlıktır: `post_document` çözemediği rolde
    **422** verir ve fişi YARIM YAZMAZ.
    """
    kodlar = {kod for _rol, kod in INSTRUMENT_POSTING_RULES}

    assert "740" not in kodlar, "ÇİFT SAYIM: çek fişi gidere dokunuyor"
    assert "600" not in kodlar, "ÇİFT SAYIM: çek fişi hasılata dokunuyor"
    assert "120" not in kodlar, "ÇİFT KAPANIŞ: çek fişi alıcı carisine dokunuyor"
    assert "320" not in kodlar, "ÇİFT KAPANIŞ: çek fişi satıcı carisine dokunuyor"
    assert kodlar == {"100", "101", "102", "103"}


def test_KARAR_1_ve_2_demette_CAKILI():
    """KARAR-1: `170`/`350` ÖLÜ hesaptır. KARAR-2: alt hesap AÇILMAZ."""
    esleme = dict(PAYMENT_POSTING_RULES)

    assert esleme["receivable"] == "120"
    assert esleme["payable"] == "320"
    assert esleme["bank"] == "102"
    assert esleme["cash"] == "100"

    for demet in (PAYMENT_POSTING_RULES, INSTRUMENT_POSTING_RULES):
        kodlar = [kod for _rol, kod in demet]
        assert "170" not in kodlar, "KARAR-1 ihlali: yıllara yaygın rejim ölü hesaptır"
        assert "350" not in kodlar, "KARAR-1 ihlali: yıllara yaygın rejim ölü hesaptır"
        assert not any("." in kod for kod in kodlar), (
            "KARAR-2 ihlali: alt hesap AÇILMAZ (MU-4); `320.04` açıldığı an "
            "`320`e bakan kural 422 verir"
        )


async def _scratch() -> str:
    database = f"mu3c_seed_{uuid.uuid4().hex[:8]}"
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
    satirlar = await conn.fetch(
        "SELECT r.role_key, h.code FROM posting_rules r "
        "JOIN chart_of_accounts h ON h.id = r.account_id "
        "WHERE r.source_type::text = $1 ORDER BY r.role_key",
        source_type,
    )
    return sorted((s["role_key"], s["code"]) for s in satirlar)


async def test_migration_TOHUMLAR_ve_IKINCI_upgrade_PATLAMAZ():
    """🔴 K6 — IDEMPOTENS. `Dockerfile` her açılışta `alembic upgrade head` koşar.

    Yarım kalmış bir deploy'dan sonraki ikinci `upgrade` patlasaydı `&&` kısa
    devre yapar ve uvicorn HİÇ BAŞLAMAZDI (tam kesinti).

    🔴 Ayrıca ölçülen şey: `ADD VALUE` ile TOHUM AYRI migration'lardır ve olmak
    ZORUNDADIR (`ADD VALUE` + değeri KULLANMA aynı işlemde HATA). İkisi
    birleştirilseydi bu test `unsafe use of new value` ile kırmızıya dönerdi ve
    kusur bugün YALNIZ CANLIDA görülürdü.
    """
    database = await _scratch()
    try:
        _run_alembic("upgrade", MU3C_SEED_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            # 🔴 POZİTİF KONTROL: üye ODM-1'den ÖNCE YOK. Olsaydı aşağıdaki
            # sıra iddiası hiçbir şey ölçmezdi.
            assert INSTRUMENT_SOURCE not in await _enum_labels(conn), (
                "üye ODM-1'den ÖNCE de vardı — test bir şey ölçmüyor"
            )
            assert not await _kural_kodlari(conn, INSTRUMENT_SOURCE)
        finally:
            await conn.close()

        _run_alembic("upgrade", ODM1_SEED_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            etiketler = await _enum_labels(conn)
            assert etiketler == [uye.value for uye in JournalSourceType], (
                f"enum SIRASI modelden ayrıştı: {etiketler}"
            )
            assert etiketler[-1] == INSTRUMENT_SOURCE, (
                "yeni üye SONA eklenmedi — `enum_range`e güvenen her ölçüm yanılır"
            )
            assert await _kural_kodlari(conn, PAYMENT_SOURCE) == sorted(PAYMENT_POSTING_RULES), (
                "ödeme tohumu eksik ya da BAŞKA hesaba bağlandı"
            )
            assert await _kural_kodlari(conn, INSTRUMENT_SOURCE) == sorted(
                INSTRUMENT_POSTING_RULES
            ), "çek tohumu eksik ya da BAŞKA hesaba bağlandı"
        finally:
            await conn.close()

        # İkinci ve üçüncü tur — `ON CONFLICT DO NOTHING` yoksa BURADA patlar.
        _run_alembic("downgrade", ODM1_ENUM_REVISION, database=database)
        _run_alembic("upgrade", ODM1_SEED_REVISION, database=database)
        _run_alembic("upgrade", ODM1_SEED_REVISION, database=database)

        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            for source_type, demet in (
                (PAYMENT_SOURCE, PAYMENT_POSTING_RULES),
                (INSTRUMENT_SOURCE, INSTRUMENT_POSTING_RULES),
            ):
                adet = await conn.fetchval(
                    "SELECT count(*) FROM posting_rules WHERE source_type::text = $1",
                    source_type,
                )
                assert adet == len(demet), f"{source_type}: tekrar koşan tohum satır ÇOĞALTTI"
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


async def test_ODM1_downgrade_MU3C_ve_FATURA_satirlarina_DOKUNMAZ():
    """🔴 Downgrade YALNIZ KENDİ EKLEDİĞİNİ geri alır.

    `payment` ailesinde MU-3C'nin DÖRT satırı (`102`/`100`/`320`/`120`) YERİNDE
    KALMALIDIR. Kapısız bir `DELETE FROM posting_rules WHERE source_type =
    'payment'` yazılsaydı canlıda bir geri alma, çeke hiç dokunmayan sıradan
    ödeme fişlemesini de SESSİZCE 422 vermeye başlatırdı — ve bunu hiçbir
    şema farkı ele vermezdi.
    """
    database = await _scratch()
    try:
        _run_alembic("upgrade", ODM1_SEED_REVISION, database=database)
        _run_alembic("downgrade", ODM1_ENUM_REVISION, database=database)

        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            mu3c = sorted(tuple(satir) for satir in _seed_rules(MU3C_MIGRATION_PATH))
            assert await _kural_kodlari(conn, PAYMENT_SOURCE) == mu3c, (
                "downgrade MU-3C'nin ödeme eşlemesini de süpürdü"
            )
            assert not await _kural_kodlari(conn, INSTRUMENT_SOURCE), (
                "çek kuralları downgrade'de DÜŞMEDİ"
            )
            assert await _kural_kodlari(conn, JournalSourceType.invoice.value) == sorted(
                INVOICE_POSTING_RULES
            ), "downgrade FATURA eşlemesini de sildi"
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


async def test_downgrade_FATURA_ailesine_DOKUNMAZ():
    """MU-3C downgrade'i YALNIZ kendi tohumunu siler.

    Kapısız bir `DELETE FROM posting_rules` MU-3B'nin fatura eşlemesini de
    süpürür ve canlıda fatura fişlemesi SESSİZCE 422 vermeye başlardı.
    """
    database = await _scratch()
    try:
        _run_alembic("upgrade", MU3C_SEED_REVISION, database=database)
        _run_alembic("downgrade", MU3B_SEED_REVISION, database=database)

        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert not await _kural_kodlari(conn, PAYMENT_SOURCE)
            assert await _kural_kodlari(conn, JournalSourceType.invoice.value) == sorted(
                INVOICE_POSTING_RULES
            ), "downgrade FATURA eşlemesini de sildi"
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)
