"""FIS-NO T1 — 🔴 **EŞİK = KİLİT**: iki eşzamanlı fiş AYNI numarayı ALAMAZ.

`SAT`/`SP` emsalinin (`tests/modules/procurement/test_procurement_numbering.py`)
kardeşidir ve aynı deseni izler: tek kullanımlık bir veritabanı, İKİ BAĞIMSIZ
oturum, birincinin commit'i BEKLETİLİRKEN ikincisinin BLOKE olduğunun `not
done` ile DOĞRUDAN ölçülmesi.

## Neden paylaşılan `db_session` YETMEZ

Kök `tests/conftest.py`nin `db_session`ı her testi TEK bağlantı üzerinde bir
SAVEPOINT'e sarar ve dış transaction'ı asla COMMIT ETMEZ. O oturum üzerinde iki
`asyncio` görevi AYNI bağlantıyı paylaşır: gerçek bir satır kilidi hiç yarışmaz
ve KİLİTSİZ bir üretici de yeşil kalırdı (MU-1 eşzamanlılık dosyasının kalıcı
dersi). Bu dosya `.env`/`TEST_DATABASE_URL` veritabanına DOKUNMAZ; kendi
veritabanını açar, kullanır ve düşürür.

## 🔴 ÖLÇÜLDÜ: fişler AYRI AYLARDA açılır — yoksa bekçi KÖRDÜR

`service.create_entry` en önde `periods_service.assert_periods_open` çağırır ve
o da UPSERT-SONRA-KİLİTLE ile **`accounting_periods` satırını `FOR UPDATE`**
kilitler. İki fiş AYNI aya kesilseydi dönem satırı ikisini kendiliğinden
SERİLEŞTİRİRDİ: `max(entry_no) + 1` gibi KİLİTSİZ bir üretici bile yeşil kalır
ve bekçi hiçbir şey ölçmezdi.

Sayaç ise AY değil **YIL** bazlıdır (kullanıcı kararı). Yarışın gerçek penceresi
tam olarak buradadır: **aynı yılın FARKLI ayları** ayrı dönem satırlarını
kilitler, dönem kilidi devreye girmez ve numara üretiminin KENDİ kilidi
sınanır. Bu yüzden aşağıdaki iki test 07/08/09 aylarını kullanır.

## İki test, İKİ AYRI hâl

* `test_eszamanli_iki_fis_AYNI_numarayi_alamaz` — sayaç zaten VARDIR (yılın ilk
  fişi commit edilmiştir): sınanan şey mevcut sayacın kilitlenmesidir.
* `test_YILIN_ILK_FISI_yarisinda_da_numara_TEKILDIR` — sayaç HENÜZ YOKTUR:
  sınanan şey MU-2'nin UPSERT-SONRA-KİLİTLE kanonunun burada da uygulanmasıdır.
  Kilitlenecek satırın VARLIĞI da kilidin parçasıdır; "önce SELECT, yoksa
  INSERT" yazan bir üretici iki eşzamanlı istekte ya iki kez `0001` verir ya da
  tekillik kısıtına düşüp kullanıcıya ayrımsız bir 500 gösterir.

⚠️ FAT-1 dersi: eşzamanlılık bekçisi İZOLE koşuda (soğuk bağlantı havuzu) kör
kalabilir. Bu dosya HEM TEK BAŞINA HEM DOSYA BÜTÜN koşturulup raporlanır.
"""

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal

import asyncpg
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.db import Base
from app.modules.accounting import service
from app.modules.accounting.models import ChartAccount, ChartAccountType, JournalEntry
from app.modules.accounting.schemas import JournalEntryCreate, JournalLineInput
from app.modules.roles.models import Role
from app.modules.users.models import User

#: Yarışan iki fişin ayları. 🔴 AYNI OLAMAZLAR (modül docstring'i): dönem satırı
#: kilidi bekçiyi kör ederdi. Yıl ORTAKTIR — sayaç yıl bazlıdır.
YIL = 2026
AYLAR = (7, 8, 9)


def _asyncpg_dsn(database: str) -> str:
    base = settings.test_database_url.replace("postgresql+asyncpg://", "postgresql://")
    return base.rsplit("/", 1)[0] + f"/{database}"


def _sqlalchemy_dsn(database: str) -> str:
    return settings.test_database_url.rsplit("/", 1)[0] + f"/{database}"


async def _create_scratch_database() -> str:
    database = f"fisno_yaris_{uuid.uuid4().hex[:8]}"
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
    """Yarışın FK zemini: oturum fabrikası + `create_entry`nin istediği kimlikler."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        actor_id: uuid.UUID,
        borc_hesap_id: uuid.UUID,
        alacak_hesap_id: uuid.UUID,
    ) -> None:
        self.Session = session_factory
        self.actor_id = actor_id
        self.borc_hesap_id = borc_hesap_id
        self.alacak_hesap_id = alacak_hesap_id


@asynccontextmanager
async def _yaris_ortami():  # noqa: ANN201
    """Tek kullanımlık veritabanı + en küçük FK zemini; sonunda GERÇEKTEN düşer.

    Kurulum COMMIT EDİLİR: iki bağımsız bağlantının AYNI veriyi görmesi şarttır,
    aksi hâlde yarış değil iki ayrı boş dünya kurulurdu.
    """
    database = await _create_scratch_database()
    engine = create_async_engine(_sqlalchemy_dsn(database))
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as kurulum:
            role = Role(key="fisno_yaris", name="FIS-NO Eşzamanlılık Rolü")
            kurulum.add(role)
            await kurulum.flush()

            user = User(
                email="fisno-yaris@muhasebe.co",
                password_hash="x",
                full_name="FIS-NO Yarış",
                role_id=role.id,
            )
            kurulum.add(user)

            kasa = ChartAccount(code="900", name="Yarış Kasa", account_type=ChartAccountType.asset)
            karsi = ChartAccount(
                code="901", name="Yarış Satıcı", account_type=ChartAccountType.liability
            )
            kurulum.add_all([kasa, karsi])
            await kurulum.flush()
            await kurulum.commit()
            ortam = _Ortam(session_factory, user.id, kasa.id, karsi.id)

        yield ortam
    finally:
        await engine.dispose()
        await _drop_scratch_database(database)


async def _yarat(ortam: _Ortam, session: AsyncSession, ay: int) -> JournalEntry:
    """`POST /journal-entries`in servis gövdesi — COMMIT ETMEZ.

    Uç yerine servis çağrılır: yarış, HTTP istemcisinin değil veritabanı
    kilidinin ölçüsüdür ve `client` fixture'ı zaten tek bağlantıya bağlıdır.
    """
    actor = await session.get(User, ortam.actor_id)
    assert actor is not None
    entry, _ = await service.create_entry(
        session,
        actor,
        JournalEntryCreate(
            entry_date=date(YIL, ay, 15),
            description=f"Yarış fişi {YIL}-{ay:02d}",
            lines=[
                JournalLineInput(
                    account_id=ortam.borc_hesap_id, debit=Decimal("100.00"), credit=Decimal("0")
                ),
                JournalLineInput(
                    account_id=ortam.alacak_hesap_id, debit=Decimal("0"), credit=Decimal("100.00")
                ),
            ],
        ),
    )
    return entry


async def _yarat_ve_commit(ortam: _Ortam, session: AsyncSession, ay: int) -> JournalEntry:
    entry = await _yarat(ortam, session, ay)
    await session.commit()
    return entry


async def _bekleyen_gorevi_olc(
    ortam: _Ortam, birinci: AsyncSession, ikinci: AsyncSession, aylar: tuple[int, int]
) -> tuple[JournalEntry, JournalEntry]:
    """tx1 numarayı ALIR ama COMMIT ETMEZ; tx2'nin BEKLEDİĞİ ölçülür.

    `asyncio.sleep(0.3)` + `not done` bariyeri ŞARTTIR: yalın bir
    `asyncio.gather` iki görevi kritik anda kesiştirmez, yarış penceresi hiç
    açılmaz ve kilitsiz kod da yeşil kalırdı (FAT-1'in kalıcı dersi).
    """
    ilk = await _yarat(ortam, birinci, aylar[0])

    gorev = asyncio.create_task(_yarat_ve_commit(ortam, ikinci, aylar[1]))
    await asyncio.sleep(0.3)
    assert not gorev.done(), (
        "ikinci fiş beklemedi — numara üretimi KİLİTSİZ: iki eşzamanlı istek "
        "aynı `entry_no`yu alır (ya da tekillik kısıtına düşüp 500 üretir)"
    )

    await birinci.commit()
    ikincisi = await asyncio.wait_for(gorev, timeout=10)
    return ilk, ikincisi


async def _tablodaki_numaralar(ortam: _Ortam) -> list[str]:
    """COMMIT SONRASI gerçekte yazılmış numaralar — sıralı ve TEKİL olmalıdır."""
    async with ortam.Session() as session:
        satirlar = (await session.execute(select(JournalEntry))).scalars()
        return sorted(entry.entry_no for entry in satirlar)


async def test_eszamanli_iki_fis_AYNI_numarayi_alamaz() -> None:
    """Sayaç ZATEN VAR: yılın ilk fişi commit edilmiştir, yarış `0002`/`0003` içindir.

    Kilit YOKSA iki oturum da commit edilmemiş durumu okur, ikisi de `0002`
    döner; tekillik kısıtı varsa biri 500'e düşer, yoksa iki fiş AYNI numarayla
    yaşar. Kilit VARSA ikinci üretim birincinin commit'ini BEKLER.
    """
    async with _yaris_ortami() as ortam:
        async with ortam.Session() as hazirlik:
            ilk = await _yarat_ve_commit(ortam, hazirlik, AYLAR[0])

        async with ortam.Session() as birinci, ortam.Session() as ikinci:
            ikincisi, ucuncusu = await _bekleyen_gorevi_olc(
                ortam, birinci, ikinci, (AYLAR[1], AYLAR[2])
            )

        numaralar = [ilk.entry_no, ikincisi.entry_no, ucuncusu.entry_no]
        assert numaralar == ["YEV-2026-0001", "YEV-2026-0002", "YEV-2026-0003"]
        assert len(set(await _tablodaki_numaralar(ortam))) == 3


async def test_YILIN_ILK_FISI_yarisinda_da_numara_TEKILDIR() -> None:
    """🔴 Sayaç satırı HENÜZ YOK — UPSERT-SONRA-KİLİTLE'nin bekçisi.

    "Önce SELECT, satır yoksa INSERT" yazan bir üretici burada kırılır: iki
    eşzamanlı istek de "sayaç yok" görür, ikisi de `0001` üretir ve ikisi de
    kendi sayaç satırını INSERT etmeye kalkar. Kilitlenecek satırın VARLIĞI da
    kilidin parçasıdır (MU-2 kanonu).
    """
    async with _yaris_ortami() as ortam:
        async with ortam.Session() as birinci, ortam.Session() as ikinci:
            ilk, ikincisi = await _bekleyen_gorevi_olc(ortam, birinci, ikinci, (AYLAR[0], AYLAR[1]))

        assert ilk.entry_no == "YEV-2026-0001"
        assert ikincisi.entry_no == "YEV-2026-0002"
        assert await _tablodaki_numaralar(ortam) == ["YEV-2026-0001", "YEV-2026-0002"]


async def test_KONTROL_ayni_AYDA_donem_kilidi_yarisi_zaten_MASKELER() -> None:
    """🔴 POZİTİF KONTROL — yukarıdaki iki bekçinin BOŞ olmadığının kanıtı.

    Aynı senaryo **aynı aya** kesilir. `assert_periods_open` iki isteği
    `accounting_periods` satırı üzerinden serileştirir, ikinci görev BLOKE olur
    ve bariyer bunu görür. İki şeyi birden kanıtlar:

    1. `not done` bariyeri ÇALIŞAN bir ölçüm aletidir — kilit VARSA görüyor.
       Görmeseydi kardeş testler "hep kırmızı" olur, hiçbir şeyi ölçmezdi.
    2. Sayaç kilidinin bekçisi bu yüzden AYRI AYLAR kullanmak ZORUNDADIR:
       aynı ayda dönem kilidi yarışı maskeler ve KİLİTSİZ bir üretici bile
       yeşil kalırdı.

    Numara İDDİA EDİLMEZ: bu test T1'de de T3'ten sonra da YEŞİLDİR, çünkü
    ölçtüğü şey `entry_no` değil ölçüm aletinin kendisidir.
    """
    async with _yaris_ortami() as ortam:
        async with ortam.Session() as birinci, ortam.Session() as ikinci:
            await _bekleyen_gorevi_olc(ortam, birinci, ikinci, (AYLAR[0], AYLAR[0]))
