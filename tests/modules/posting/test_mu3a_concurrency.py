"""MU-3A T3 — 🔴 **İKİ EŞZAMANLI ONAY, TEK FİŞ.**

`tests/modules/accounting/test_fisno_concurrency.py`nin kardeşidir ve aynı
deseni izler: tek kullanımlık bir veritabanı, İKİ BAĞIMSIZ oturum, birincinin
commit'i BEKLETİLİRKEN ikincisinin BLOKE olduğunun `not done` ile DOĞRUDAN
ölçülmesi.

## Neden paylaşılan `db_session` YETMEZ

Kök `tests/conftest.py`nin `db_session`ı her testi TEK bağlantı üzerinde bir
SAVEPOINT'e sarar. O oturum üzerinde iki `asyncio` görevi AYNI bağlantıyı
paylaşır: gerçek bir danışma kilidi hiç yarışmaz (aynı oturum kendi kilidini
yeniden alır) ve KİLİTSİZ bir `post_document` de yeşil kalırdı.

## 🔴 SABİT SÜRELİ BARİYER YETMEZ — KİLİDİN TÜRÜ DOĞRULANIR

`asyncio.sleep` + `not done` tek başına FLAKY'dir. Bu dosya beklemeyi
`pg_stat_activity`den okur ve `wait_event_type = 'Lock'` **ve**
`wait_event = 'advisory'` olduğunu ayrıca çakar. Doğrulanmasaydı görev
bambaşka bir sebeple (bağlantı kurulumu, dönem satırı kilidi) yavaşlamış
olabilir ve bekçi hiçbir şey ölçmezdi.

## İki test, İKİ AYRI katman

* `test_eszamanli_iki_onay_TEK_fis_uretir` — SERVİS katmanı: kaybeden bekler,
  sonra kazananın fişini `created=False` ile döndürür. İstisna ATILMAZ.
* `test_KILIT_OLMASA_DA_DB_ikinci_fisi_REDDEDER` — DB katmanı: `post_document`
  ATLANIR ve iki oturum DOĞRUDAN satır yazar. Servis kapısı bir gün atlanırsa
  tekilliği ayakta tutan tek şeyin `uq_journal_entries_source` olduğunu ölçer.

⚠️ FAT-1 dersi: eşzamanlılık bekçisi İZOLE koşuda (soğuk bağlantı havuzu) kör
kalabilir. Bu dosya HEM TEK BAŞINA HEM DOSYA BÜTÜN koşturulup raporlanır.
"""

import asyncio
import uuid
from contextlib import asynccontextmanager, suppress
from datetime import date
from decimal import Decimal

import asyncpg
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.db import Base
from app.modules.accounting.models import (
    ChartAccount,
    ChartAccountType,
    JournalEntry,
    JournalEntryStatus,
    JournalSourceType,
)
from app.modules.posting import service as posting_service
from app.modules.posting.models import PostingRule
from app.modules.posting.service import PostingLine
from app.modules.roles.models import Role
from app.modules.users.models import User

KAYNAK = JournalSourceType.invoice
TARIH = date(2026, 7, 17)
TUTAR = Decimal("1000.00")
GIDER_ROL = "expense"
CARI_ROL = "payable"

#: Bariyer yoklama bütçesi. SABİT BİR `sleep` DEĞİL: kilit görünene kadar
#: yoklanır ve görünmezse test AÇIKÇA düşer.
BARIYER_TIMEOUT_SN = 20.0
"""🔴 CI'da 5.0 sn YETMİYORDU (EXPORT-XLSX turunda yerelde de üretildi).

Bu tavanı yükseltmek bekçiyi ZAYIFLATMAZ: kilit hiç alınmazsa bariyer yine
düşer, yalnız daha geç düşer. Dar tutmanın bedeli ise SAHTE KIRMIZIYDI —
yavaş bir makinede ikinci görev kilide varmadan süre doluyordu."""
BARIYER_ARALIK_SN = 0.05


def _asyncpg_dsn(database: str) -> str:
    base = settings.test_database_url.replace("postgresql+asyncpg://", "postgresql://")
    return base.rsplit("/", 1)[0] + f"/{database}"


def _sqlalchemy_dsn(database: str) -> str:
    return settings.test_database_url.rsplit("/", 1)[0] + f"/{database}"


async def _create_scratch_database() -> str:
    database = f"mu3a_yaris_{uuid.uuid4().hex[:8]}"
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


class _Ortam:
    def __init__(self, session_factory, actor_id: uuid.UUID) -> None:  # noqa: ANN001
        self.Session = session_factory
        self.actor_id = actor_id


@asynccontextmanager
async def _yaris_ortami():  # noqa: ANN201
    """Tek kullanımlık veritabanı + eşleme zemini; sonunda GERÇEKTEN düşer.

    Kurulum COMMIT EDİLİR: iki bağımsız bağlantının AYNI eşlemeyi görmesi
    şarttır, aksi hâlde yarış değil iki ayrı boş dünya kurulurdu.
    """
    database = await _create_scratch_database()
    engine = create_async_engine(_sqlalchemy_dsn(database))
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as kurulum:
            role = Role(key="mu3a_yaris", name="MU-3A Eşzamanlılık Rolü")
            kurulum.add(role)
            await kurulum.flush()
            user = User(
                email="mu3a-yaris@muhasebe.co",
                password_hash="x",
                full_name="MU-3A Yarış",
                role_id=role.id,
            )
            kurulum.add(user)

            gider = ChartAccount(
                code="740", name="Yarış Gider", account_type=ChartAccountType.expense
            )
            cari = ChartAccount(
                code="320", name="Yarış Satıcı", account_type=ChartAccountType.liability
            )
            kurulum.add_all([gider, cari])
            await kurulum.flush()
            kurulum.add_all(
                [
                    PostingRule(source_type=KAYNAK, role_key=GIDER_ROL, account_id=gider.id),
                    PostingRule(source_type=KAYNAK, role_key=CARI_ROL, account_id=cari.id),
                ]
            )
            await kurulum.commit()
            ortam = _Ortam(session_factory, user.id)

        yield ortam
    finally:
        await engine.dispose()
        await _drop_scratch_database(database)


async def _fisle(ortam: _Ortam, session: AsyncSession, belge_id: uuid.UUID):  # noqa: ANN202
    actor = await session.get(User, ortam.actor_id)
    assert actor is not None
    return await posting_service.post_document(
        session,
        actor,
        source_type=KAYNAK,
        source_id=belge_id,
        entry_date=TARIH,
        description="Yarış faturası",
        lines=[
            PostingLine(role_key=GIDER_ROL, debit=TUTAR),
            PostingLine(role_key=CARI_ROL, credit=TUTAR),
        ],
    )


async def _fisle_ve_commit(ortam: _Ortam, session: AsyncSession, belge_id: uuid.UUID):  # noqa: ANN202
    sonuc = await _fisle(ortam, session, belge_id)
    await session.commit()
    return sonuc


async def _danisma_kilidinde_bekleyen_var_mi(gozlemci: AsyncSession) -> bool:
    """🔴 Kilidin TÜRÜ doğrulanır — yalnız "bekliyor" YETMEZ.

    `wait_event_type='Lock'` + `wait_event='advisory'` çifti, beklemenin
    `pg_advisory_xact_lock`tan geldiğini söyler. Yalnız `Lock` bakılsaydı dönem
    satırının `FOR UPDATE` kilidi (`transactionid`/`tuple`) de sayılır ve
    danışma kilidi hiç alınmasa bile bariyer yeşil geçerdi.

    🔴 `datname = current_database()` ŞARTTIR (EXPORT-XLSX turunda ölçüldü).
    `pg_stat_activity` SUNUCU GENELİDİR: bu dosya kendi tek kullanımlık
    veritabanını kurar, ama depoda danışma kilidi kullanan İKİ dosya daha
    vardır (`procurement/test_select_and_order_yarisi.py`,
    `invoicing/test_validation.py`) ve `-n 4` altında AYNI ANDA koşabilirler.
    Süzgeç olmadan BAŞKA bir veritabanındaki bekleyen bu bariyeri tatmin eder;
    bariyer, bu testin kilidi HİÇ alınmasa bile yeşil geçerdi — yani bekçi
    doğru sonucu YANLIŞ SEBEPLE verirdi. `pid <> pg_backend_pid()` ise
    gözlemcinin kendisini saymamak içindir.
    """
    sayi = await gozlemci.scalar(
        text(
            "SELECT count(*) FROM pg_stat_activity "
            "WHERE wait_event_type = 'Lock' AND wait_event = 'advisory' "
            "AND datname = current_database() AND pid <> pg_backend_pid()"
        )
    )
    return bool(sayi)


async def _bariyer(gozlemci: AsyncSession, gorev: asyncio.Task) -> None:
    """Kilit GÖRÜNENE KADAR yoklar; görünmezse AÇIKÇA düşer."""
    gecen = 0.0
    while gecen < BARIYER_TIMEOUT_SN:
        if await _danisma_kilidinde_bekleyen_var_mi(gozlemci):
            return
        if gorev.done():
            break
        await asyncio.sleep(BARIYER_ARALIK_SN)
        gecen += BARIYER_ARALIK_SN
    raise AssertionError(
        "ikinci onay danışma kilidinde BEKLEMEDİ — `post_document` KİLİTSİZ: iki "
        "eşzamanlı onay aynı belgeye iki fiş yazmayı deneyebilir"
    )


async def _gorevi_sonlandir(gorev: asyncio.Task) -> None:
    """Arka plan görevini HER YOLDA kapat — oturum ve engine kapanmadan ÖNCE.

    🔴 EXPORT-XLSX turunda CI'da ölçülen KUSUR buydu. Görev `ikinci` oturumunu
    kullanır ama o oturumun SAHİBİ `async with` bloğudur. Blok bir istisnayla
    çıkarsa (bariyer düşerse) oturum, ardından `engine.dispose()` bağlantıyı
    görev HÂLÂ ÜZERİNDEYKEN kapatır. asyncpg bunu
    `ConnectionDoesNotExistError` ya da "another operation is in progress"
    diye bildirir ve bu gürültü ASIL hatayı — "ikinci onay danışma kilidinde
    BEKLEMEDİ" — EZER. Yani bekçi düştüğünde NEDEN düştüğü okunamaz hâle
    gelirdi; testin kendisi kendi teşhisini yok ediyordu.

    Yerelde görünmezdi çünkü bariyer hiç zaman aşımına uğramıyordu; CI'da
    makine yavaşladıkça uğradı. Sıralamayı DEĞİŞTİRMEZ: yarış aynen kurulur,
    yalnız görev başıboş bırakılmaz.
    """
    if not gorev.done():
        gorev.cancel()
    # İstisnayı TÜKET: alınmayan görev istisnası asyncio tarafından ayrıca
    # loglanır ve gerçek hatanın üstünü örter.
    with suppress(BaseException):
        await gorev


async def test_eszamanli_iki_onay_TEK_fis_uretir():
    """tx1 fişi yazar ama COMMIT ETMEZ; tx2'nin BEKLEDİĞİ ölçülür, sonra sonuç."""
    async with _yaris_ortami() as ortam:
        belge_id = uuid.uuid4()
        async with (
            ortam.Session() as birinci,
            ortam.Session() as ikinci,
            ortam.Session() as gozlemci,
        ):
            ilk = await _fisle(ortam, birinci, belge_id)
            assert ilk.created is True

            gorev = asyncio.create_task(_fisle_ve_commit(ortam, ikinci, belge_id))
            try:
                await _bariyer(gozlemci, gorev)
                assert not gorev.done()

                await birinci.commit()
                sonuc = await gorev

                # 🔴 Kaybeden İSTİSNA ALMAZ: kilidi devraldıktan sonra TAZE bir
                # okuma yapar (READ COMMITTED) ve kazananın fişini döndürür.
                assert sonuc.created is False
                assert sonuc.entry.id == ilk.entry.id

                toplam = await gozlemci.scalar(select(func.count()).select_from(JournalEntry))
                assert toplam == 1
            finally:
                # Bariyer düşerse görev BAŞIBOŞ kalırdı; aşağıdaki `async with`
                # çıkışı onun bağlantısını altından çeker ve asyncpg gürültüsü
                # asıl hatayı ezer. Sıra ŞART: görev önce, oturumlar sonra.
                await _gorevi_sonlandir(gorev)


async def test_KILIT_OLMASA_DA_DB_ikinci_fisi_REDDEDER():
    """🔴 SERVİS KAPISI ATLANDI — tekilliği ayakta tutan TEK şey DB kısıtıdır.

    `post_document` HİÇ ÇAĞRILMAZ; iki oturum doğrudan satır yazar. Bu, yarın
    yazılacak (ve giriş noktasını atlayacak) bir yazma yolunun temsilcisidir.
    """
    async with _yaris_ortami() as ortam:
        belge_id = uuid.uuid4()

        def _fis(entry_no: str) -> JournalEntry:
            return JournalEntry(
                entry_no=entry_no,
                entry_date=TARIH,
                period_year=TARIH.year,
                period_month=TARIH.month,
                description="Kapıyı atlayan yol",
                status=JournalEntryStatus.posted,
                total_debit=Decimal("0"),
                total_credit=Decimal("0"),
                source_type=KAYNAK,
                source_id=belge_id,
                created_by_id=ortam.actor_id,
            )

        async with ortam.Session() as birinci, ortam.Session() as ikinci:
            birinci.add(_fis("YEV-2026-9001"))
            await birinci.flush()

            gorev = asyncio.create_task(_yaz_ve_commit(ikinci, _fis("YEV-2026-9002")))
            await asyncio.sleep(0.3)
            assert not gorev.done(), (
                "ikinci satır BEKLEMEDİ — `uq_journal_entries_source` yok: aynı "
                "belgeye iki fiş yazılabiliyor"
            )

            await birinci.commit()
            with pytest.raises(IntegrityError) as hata:
                await gorev
            assert "uq_journal_entries_source" in str(hata.value.orig)

        async with ortam.Session() as denetci:
            toplam = await denetci.scalar(select(func.count()).select_from(JournalEntry))
            assert toplam == 1


async def _yaz_ve_commit(session: AsyncSession, entry: JournalEntry) -> None:
    session.add(entry)
    await session.flush()
    await session.commit()
