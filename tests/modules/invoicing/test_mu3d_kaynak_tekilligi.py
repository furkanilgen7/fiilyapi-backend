"""🔴 MU-3D İŞ 3 — KAYNAK BAŞINA TEK ASIL FATURA (`d2e3f4a5b6c7`).

## Ölçülen açık

MU-3D öncesi aynı `progress_payment_id` sınırsız sayıda faturaya yazılabiliyordu:
`ck_invoices_single_source` yalnız *"bir faturada en fazla BİR kaynak kolonu
dolu"* der, servis katmanı (`_assert_references`) yalnız VARLIK ve PROJE
KAPSAMI bakar, ve kaynak FK'leri PATCH ile de yazılabilir. Yani tek gerçek
bekçi DB'dir.

## Neden MIGRATION'IN ÜRETTİĞİ ŞEMADA ölçülür

`Base.metadata.create_all` ile kurulan test şeması modelden doğar. Modele
eklenip migration'a yazılmayı unutulan bir indeks orada YEŞİL kalır, canlıda
ise HİÇ OLMAZDI — ve çift sayım açığı yalnız üretimde açık kalırdı. Bu dosya
bu yüzden kendi TEK KULLANIMLIK veritabanını açar ve `alembic upgrade` koşar;
`.env` ve `TEST_DATABASE_URL` veritabanı ELLENMEZ.

## 🔴 DÖRT KOLON AYRI AYRI ÖLÇÜLÜR

Tek bir kolonda ölçülseydi, demetten üretilen indeks döngüsü bozulup yalnız
ilk kolonu kursa bile test yeşil kalırdı — ve öteki üç kaynağın açığı hiç
görünmezdi.
"""

import uuid
from datetime import date

import asyncpg
import pytest

from app.modules.invoicing.models import BINDING_SOURCE_WHERE, SOURCE_UNIQUE_INDEXES
from tests.modules.accounting._mu1_migration import (
    BACKEND_DIR,
    _asyncpg_dsn,
    _current_revision,
    _drop_scratch_database,
    _index_exists,
    _run_alembic,
    _seed_user,
)

#: Revizyonlara AÇIKÇA çıkılır; `head`/`-1` KULLANILMAZ — sonraki dilimler
#: revizyon ekledikçe bu test sessizce başka bir şeyi ölçerdi.
PARENT_REVISION = "d1e2f3a4b5c6"
MU3D_REVISION = "d2e3f4a5b6c7"

MIGRATION_PATH = (
    BACKEND_DIR / "alembic" / "versions" / "d2e3f4a5b6c7_mu3d_kaynak_fatura_tekilligi.py"
)

#: `(kolon, indeks, kaynak tablosu)` — kaynak satırını kurmak için tablo adı da
#: gerekir; FK `RESTRICT`tir ve var olmayan bir kimlik yazılamaz.
KAYNAKLAR: tuple[tuple[str, str, str], ...] = (
    ("progress_payment_id", "uq_invoices_progress_payment", "progress_payments"),
    (
        "subcontractor_progress_payment_id",
        "uq_invoices_subcontractor_progress_payment",
        "subcontractor_progress_payments",
    ),
    (
        "equipment_rental_invoice_id",
        "uq_invoices_equipment_rental_invoice",
        "equipment_rental_invoices",
    ),
    ("purchase_order_id", "uq_invoices_purchase_order", "purchase_orders"),
)


# --------------------------------------------------------------------------- #
# İKİ KATMAN EŞİTLİĞİ — migration uygulama kodunu IMPORT ETMEZ (K1)
# --------------------------------------------------------------------------- #


def test_migration_ebeveyni_BEKLENEN_revizyondur():
    """Araya başka bir dilim merge edilirse re-parent ŞART (P8/TH dersi)."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(str(BACKEND_DIR / "alembic.ini")))
    assert script.get_revision(MU3D_REVISION).down_revision == PARENT_REVISION


def test_migration_SUZGEC_metni_MODEL_sabitiyle_AYNIDIR():
    """🔴 Donmuş kopya ↔ `models.BINDING_SOURCE_WHERE`.

    Migration uygulama kodunu bilinçli olarak IMPORT ETMEZ (uygulanmış bir
    migration DONMUŞ olmalıdır). Bedeli iki metnin sessizce ayrışabilmesidir:
    biri iadeleri süzer, öteki süzmez — ve indeks ile modelin tarif ettiği
    küme AYRIŞIRDI. Model sabitinin KENDİSİ `InvoiceDocumentType.refund`tan
    TÜRETİLİR, yani üye yeniden adlandırılırsa bu iddia da kırılır.
    """
    kaynak = MIGRATION_PATH.read_text()
    assert f'WHERE_SQL = "{BINDING_SOURCE_WHERE}"' in kaynak, (
        f"migration donmuş kopyası model sabitinden ayrıştı: {BINDING_SOURCE_WHERE!r}"
    )


def test_migration_INDEKS_demeti_MODEL_demetiyle_AYNIDIR():
    """🔴 Sıra ve içerik birebir — bir kolon migration'da unutulsaydı o kaynağın
    açığı YALNIZ CANLIDA açık kalır, test şeması onu yine kapatırdı."""
    kaynak = MIGRATION_PATH.read_text()
    for kolon, indeks in SOURCE_UNIQUE_INDEXES:
        assert f'("{kolon}", "{indeks}")' in kaynak, f"migration demetinde eksik: {kolon}"
    assert tuple(kolon for kolon, _ in SOURCE_UNIQUE_INDEXES) == tuple(
        kolon for kolon, _, _ in KAYNAKLAR
    ), "test evreni model demetinden AYRIŞTI"


# --------------------------------------------------------------------------- #
# MIGRATION'IN ÜRETTİĞİ ŞEMANIN SEMANTİĞİ
# --------------------------------------------------------------------------- #


async def _scratch() -> str:
    database = f"mu3d_mig_{uuid.uuid4().hex[:8]}"
    admin = await asyncpg.connect(_asyncpg_dsn("postgres"))
    try:
        await admin.execute(f'CREATE DATABASE "{database}"')
    finally:
        await admin.close()
    return database


async def _fatura(
    conn: asyncpg.Connection,
    user_id: uuid.UUID,
    *,
    kolon: str,
    kaynak_id: uuid.UUID | None,
    document_type: str = "einvoice",
) -> None:
    """Kısıtın ölçüldüğü en küçük geçerli fatura başlığı — kalemsiz."""
    await conn.execute(
        "INSERT INTO invoices "
        "(id, direction, invoice_no, document_type, status, issue_date, party_name, "
        f" subtotal, advance_amount, retention_amount, tax_base, vat_amount, "
        f" withholding_amount, total, created_by_id, {kolon}) "
        "VALUES ($1, 'outgoing'::invoice_direction, $2, "
        "$3::invoice_document_type, 'draft'::invoice_status, $4, 'Prob A.S.', "
        "0, 0, 0, 0, 0, 0, 0, $5, $6)",
        uuid.uuid4(),
        f"MU3D{uuid.uuid4().hex[:10].upper()}",
        document_type,
        date(2026, 7, 17),
        user_id,
        kaynak_id,
    )


async def _fk_ertele(conn: asyncpg.Connection) -> None:
    """Kaynak FK'lerini bu OTURUM için düşürür.

    🔴 Ölçülen kural TEKİLLİKTİR, FK bütünlüğü DEĞİL (o zaten `ck_`/FK
    testlerinde ölçülü). Dört kaynak tablosunun tamamına geçerli satır kurmak
    (proje → sözleşme → hakediş → …) bu testi ölçtüğü kuralın onlarca katı
    büyüklükte bir kuruluma bağlar ve kırmızı, tekilliği değil kurulumu
    gösterirdi. Veritabanı TEK KULLANIMLIKTIR ve sonunda düşürülür.
    """
    for kolon, _indeks, _tablo in KAYNAKLAR:
        kisit = await conn.fetchval(
            "SELECT con.conname FROM pg_constraint con "
            "JOIN pg_class rel ON rel.oid = con.conrelid "
            "JOIN pg_attribute att ON att.attrelid = rel.oid AND att.attnum = con.conkey[1] "
            "WHERE rel.relname = 'invoices' AND con.contype = 'f' AND att.attname = $1",
            kolon,
        )
        assert kisit is not None, f"`invoices.{kolon}` FK'si BULUNAMADI — şema değişmiş"
        await conn.execute(f"ALTER TABLE invoices DROP CONSTRAINT {kisit}")


async def test_upgrade_DORT_kaynak_indeksini_de_KURAR():
    """🔴 Dördü de ayrı ayrı — biri eksik kalsaydı o kaynağın açığı sürerdi."""
    database = await _scratch()
    try:
        _run_alembic("upgrade", PARENT_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            for _kolon, indeks, _tablo in KAYNAKLAR:
                assert not await _index_exists(conn, indeks), (
                    f"`{indeks}` MU-3D'den ÖNCE de vardı — test bir şey ölçmüyor"
                )
        finally:
            await conn.close()

        _run_alembic("upgrade", MU3D_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _current_revision(conn) == MU3D_REVISION
            for _kolon, indeks, _tablo in KAYNAKLAR:
                assert await _index_exists(conn, indeks), indeks
                # 🔴 KISMİ olduğu ayrıca ölçülür: `WHERE`siz kurulmuş bir indeks
                #    de `_index_exists`ten GEÇERDİ ve meşru iade faturasını
                #    engellerdi.
                tanim = await conn.fetchval(
                    "SELECT indexdef FROM pg_indexes WHERE indexname = $1", indeks
                )
                assert "WHERE" in tanim.upper(), f"`{indeks}` KISMİ DEĞİL: {tanim}"
                assert "refund" in tanim, f"`{indeks}` iade süzgecini taşımıyor: {tanim}"
        finally:
            await conn.close()

        _run_alembic("downgrade", PARENT_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _current_revision(conn) == PARENT_REVISION
            for _kolon, indeks, _tablo in KAYNAKLAR:
                assert not await _index_exists(conn, indeks), (
                    f"`{indeks}` downgrade'de DÜŞMEDİ — ikinci upgrade "
                    '"already exists" ile YALNIZ CANLIDA patlardı'
                )
        finally:
            await conn.close()

        # İkinci tur: `IF EXISTS`li downgrade'den sonra upgrade YİNE geçmeli.
        _run_alembic("upgrade", MU3D_REVISION, database=database)
    finally:
        await _drop_scratch_database(database)


async def test_AYNI_kaynaga_IKINCI_asil_fatura_REDDEDILIR_dort_kolonda_da():
    """🔴 BU DİLİMİN ÇİFT SAYIM KAPISI — dört kolon AYRI AYRI ısırır."""
    database = await _scratch()
    try:
        _run_alembic("upgrade", MU3D_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            await _fk_ertele(conn)
            user_id = await _seed_user(conn)

            for kolon, indeks, _tablo in KAYNAKLAR:
                kaynak_id = uuid.uuid4()
                await _fatura(conn, user_id, kolon=kolon, kaynak_id=kaynak_id)

                with pytest.raises(asyncpg.UniqueViolationError) as hata:
                    await _fatura(conn, user_id, kolon=kolon, kaynak_id=kaynak_id)
                assert indeks in str(hata.value), f"reddeden kısıt `{indeks}` DEĞİL: {hata.value}"

                # 🔴 BAŞKA bir kaynak SERBEST — indeks kolonun TAMAMINI değil
                #    tekrar eden DEĞERİ engellemeli.
                await _fatura(conn, user_id, kolon=kolon, kaynak_id=uuid.uuid4())
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


async def test_IADE_faturasi_AYNI_kaynaga_baglanabilir_ve_KAYNAKSIZ_fatura_SERBESTTIR():
    """🔴 İndeksin İKİ kaçış deliği — ikisi de BİLEREK açıktır.

    * **İade faturası** (`document_type='refund'`) bu üründe bir faturayı geri
      alan TEK belgedir (iptal DURUMU yoktur, ölçüldü). Kapsam dışında
      bırakılmasaydı kesilmiş bir hakediş faturası HİÇ düzeltilemezdi.
    * **Kaynağa bağlanmamış fatura** (`NULL`) çoğunluktur; PG'de NULL'lar
      ayrıktır ve indeks onları HİÇ görmez. Bu ayrıca ölçülür çünkü
      `NULLS NOT DISTINCT` ile kurulmuş bir indeks TÜM kaynaksız faturaları
      tek bir satıra indirir ve fatura kesmeyi tamamen kilitlerdi.
    """
    database = await _scratch()
    try:
        _run_alembic("upgrade", MU3D_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            await _fk_ertele(conn)
            user_id = await _seed_user(conn)
            kolon = "progress_payment_id"
            kaynak_id = uuid.uuid4()

            await _fatura(conn, user_id, kolon=kolon, kaynak_id=kaynak_id)
            # İADE: aynı kaynağa BAĞLANABİLİR.
            await _fatura(conn, user_id, kolon=kolon, kaynak_id=kaynak_id, document_type="refund")
            # İKİNCİ bir iade de serbesttir (kısmi indeks iadeleri hiç görmez).
            await _fatura(conn, user_id, kolon=kolon, kaynak_id=kaynak_id, document_type="refund")
            # Asıl fatura hâlâ REDDEDİLİR — iadeler kapıyı AÇMADI.
            with pytest.raises(asyncpg.UniqueViolationError):
                await _fatura(conn, user_id, kolon=kolon, kaynak_id=kaynak_id)

            # KAYNAKSIZ: üç fatura yan yana durabilir.
            for _ in range(3):
                await _fatura(conn, user_id, kolon=kolon, kaynak_id=None)
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


async def test_KIRLI_veride_indeks_ATLANIR_ve_migration_BASARIYLA_biter():
    """🔴 `raise` YOKTUR — `Dockerfile`daki `&&` uvicorn'u HİÇ BAŞLATMAZDI.

    🔴 Ayrıca ölçülen ikinci şey: KİRLİ olan kolon atlanırken TEMİZ olanların
    indeksi YİNE KURULUR. Tek bir `return` yazılsaydı bir kolonun geçmiş verisi
    öteki üçünü de bekçisiz bırakırdı ve bunu hiçbir sayı ele vermezdi.
    """
    database = await _scratch()
    try:
        _run_alembic("upgrade", PARENT_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            await _fk_ertele(conn)
            user_id = await _seed_user(conn)
            kirli_id = uuid.uuid4()
            # TEK kolon kirletilir: `progress_payment_id`.
            await _fatura(conn, user_id, kolon="progress_payment_id", kaynak_id=kirli_id)
            await _fatura(conn, user_id, kolon="progress_payment_id", kaynak_id=kirli_id)
        finally:
            await conn.close()

        # 🔴 PATLAMAZ.
        _run_alembic("upgrade", MU3D_REVISION, database=database)

        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _current_revision(conn) == MU3D_REVISION, (
                "migration kirli veride BAŞARIYLA bitmedi"
            )
            assert not await _index_exists(conn, "uq_invoices_progress_payment"), (
                "kirli kolonda indeks KURULDU — `CREATE UNIQUE INDEX` patlamalıydı"
            )
            for _kolon, indeks, _tablo in KAYNAKLAR[1:]:
                assert await _index_exists(conn, indeks), (
                    f"TEMİZ kolon `{indeks}` kirli komşusu yüzünden BEKÇİSİZ kaldı"
                )
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)
