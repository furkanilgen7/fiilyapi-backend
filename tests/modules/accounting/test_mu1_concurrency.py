"""MU-1 T3b — 🔴 **EŞİK = KİLİT** (spec §5, WORKFLOW §4 kanonu · İK-2 dersi).

`state_service.perform_transition` sırası DEĞİŞMEZDİR ve kilit HER ŞEYDEN ÖNCE
gelir:

    1. kilit   — `get_entry(..., for_update=True)` (`with_for_update` +
                 `populate_existing`)
    2. matris  — `transitions.next_status` → **409**
    3. storno kapıları — zaten terslenmiş / stornonun stornosu → **409**
    4. K1      — `validation.balance_blockers` → **422**
    5. damga + storno yazımı
    6. `session.refresh(entry)` (yoksa async'te `MissingGreenlet` = **500**)

Kilit 2. adımdan SONRA alınsaydı iki eşzamanlı `post` da `draft` okur, ikisi de
matrisi geçer ve fiş **İKİ KEZ** kayıtlaştırılırdı; iki eşzamanlı `reverse` ise
**İKİ storno** üretirdi ve `uq_journal_entries_reversal_of` kullanıcıya ayrımsız
bir "Veri bütünlüğü hatası" olarak yansırdı.

## Neden `client`/`seeded_db` KULLANILMAZ

Kök `tests/conftest.py`nin `db_session`ı her testi TEK bağlantı üzerinde bir
SAVEPOINT'e sarar ve dış transaction'ı asla gerçekten COMMIT ETMEZ; o session
üzerinde iki `asyncio` görevi AYNI bağlantıyı paylaşır ve gerçek satır kilidi
test EDİLEMEZ. Bu dosya bilinçli olarak `test_engine`den İKİ BAĞIMSIZ bağlantı
açar, kurulumu GERÇEKTEN commit eder ve sonunda GERÇEKTEN temizler
(`tests/progress_payments/test_concurrency.py` deseni).

🔴 Bariyer deseni (`asyncio.Event`) ŞARTTIR: yalın `asyncio.gather` iki görevi
kritik anda KESİŞTİRMEZ, yarış penceresi hiç açılmaz ve kilitsiz kod da yeşil
kalabilir (FAT-1'in kalıcı dersi). Burada tx1 kilidi ALIP TUTARKEN tx2'nin
bloke olduğu DOĞRUDAN kanıtlanır.
"""

import asyncio
import uuid
from decimal import Decimal

from sqlalchemy import delete, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import ConflictError
from app.core.security import hash_password
from app.core.timezone import today
from app.modules.accounting import numbering, state_service
from app.modules.accounting.models import (
    AccountingPeriod,
    ChartAccount,
    ChartAccountType,
    JournalEntry,
    JournalEntryStatus,
    JournalLine,
)
from app.modules.accounting.transitions import JournalAction
from app.modules.roles.models import Role
from app.modules.users.models import User
from tests.conftest import test_engine

_SessionFactory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

#: Rol anahtarı bilinçli olarak TESTE ÖZELDİR: `seed_reference_data`'nın ürettiği
#: üretim anahtarlarıyla (`system_admin`, `patron`) çakışmaz ve sızarsa
#: `test_role_key_is_unique`i kırmaz.
_ROL_ANAHTARI = "mu1_conc_admin"
_KODLAR = ("910", "920")


class _Kurulum:
    def __init__(self, entry_id, actor_id, ikinci_actor_id, account_ids, role_id) -> None:
        self.entry_id = entry_id
        self.actor_id = actor_id
        self.ikinci_actor_id = ikinci_actor_id
        self.account_ids = account_ids
        self.role_id = role_id


async def _kur(status: JournalEntryStatus) -> _Kurulum:
    """Gerçek commit'li kurulum — iki bağımsız bağlantı aynı veriyi görmelidir.

    İzin/modül satırı KURULMAZ: bu dosya `state_service`i DOĞRUDAN çağırır,
    yetki kapısı (`require_permission`) router'dadır. Kullanıcı yalnızca
    `journal_entries.created_by_id` RESTRICT FK'sı için gereklidir.
    """
    async with _SessionFactory() as session:
        role = Role(key=_ROL_ANAHTARI, name="MU-1 Eşzamanlılık Rolü")
        session.add(role)
        await session.flush()

        kullanicilar = []
        for sira in (1, 2):
            user = User(
                email=f"mu1-conc-{sira}@muhasebe.co",
                password_hash=hash_password("parola1234"),
                full_name=f"Eşzamanlılık {sira}",
                role_id=role.id,
            )
            session.add(user)
            kullanicilar.append(user)
        await session.flush()

        kasa = ChartAccount(code=_KODLAR[0], name="Eş Kasa", account_type=ChartAccountType.asset)
        karsi = ChartAccount(
            code=_KODLAR[1], name="Eş Satıcı", account_type=ChartAccountType.liability
        )
        session.add_all([kasa, karsi])
        await session.flush()

        from datetime import date

        entry = JournalEntry(
            # 🔑 FIS-NO — `entry_no` NOT NULL (bkz. `conftest.fis_fabrikasi`).
            entry_no=await numbering.generate_entry_no(session, year=2026),
            entry_date=date(2026, 7, 17),
            period_year=2026,
            period_month=7,
            description="Eşzamanlılık fişi",
            status=status,
            total_debit=Decimal("100.00"),
            total_credit=Decimal("100.00"),
            created_by_id=kullanicilar[0].id,
        )
        session.add(entry)
        await session.flush()
        session.add_all(
            [
                JournalLine(
                    entry_id=entry.id,
                    sort_order=0,
                    account_id=kasa.id,
                    debit=Decimal("100.00"),
                    credit=Decimal("0"),
                ),
                JournalLine(
                    entry_id=entry.id,
                    sort_order=1,
                    account_id=karsi.id,
                    debit=Decimal("0"),
                    credit=Decimal("100.00"),
                ),
            ]
        )
        await session.commit()
        return _Kurulum(
            entry.id,
            kullanicilar[0].id,
            kullanicilar[1].id,
            [kasa.id, karsi.id],
            role.id,
        )


async def _temizle(kurulum: _Kurulum) -> None:
    """`_kur`un yarattığı HER satırı geri alır — sızıntı paylaşılan test
    veritabanına KALICI olurdu (TB1'de fiilen yaşandı).

    🔴 MU-2 T3'ten sonra `accounting_periods` DE silinir: yazma yolları dönem
    satırını UPSERT ile DOĞURUR (kilitlenecek satır olmadan eşzamanlılık
    serileşemezdi), yani bu dosya artık kendisinin yaratmadığı sanılan bir satır
    bırakır. Bırakıldığında `test_mu2_periods_api.py`nin fabrikası aynı `(yıl,
    ay)` için ikinci kez INSERT etmeye çalışır ve UNIQUE ihlaline düşer —
    kusur BU DOSYADA doğar, orada patlardı.

    İki dönem dokunulur: fişin dönemi (`2026/07`) ve stornonun düştüğü BUGÜNÜN
    dönemi (`_build_reversal` → `timezone.today()`).
    """
    async with _SessionFactory() as session:
        # Storno ÖNCE gider: `reversal_of_id` RESTRICT'tir.
        stornolar = (
            (
                await session.execute(
                    select(JournalEntry.id).where(JournalEntry.reversal_of_id.is_not(None))
                )
            )
            .scalars()
            .all()
        )
        hedefler = [*stornolar, kurulum.entry_id]
        await session.execute(delete(JournalLine).where(JournalLine.entry_id.in_(hedefler)))
        await session.execute(delete(JournalEntry).where(JournalEntry.id.in_(hedefler)))
        await session.execute(delete(ChartAccount).where(ChartAccount.code.in_(_KODLAR)))
        bugun = today()
        await session.execute(
            delete(AccountingPeriod).where(
                tuple_(AccountingPeriod.year, AccountingPeriod.month).in_(
                    [(2026, 7), (bugun.year, bugun.month)]
                )
            )
        )
        await session.execute(delete(User).where(User.role_id == kurulum.role_id))
        await session.execute(delete(Role).where(Role.id == kurulum.role_id))
        await session.commit()


async def _gecis_ve_tut(
    entry_id: uuid.UUID,
    actor_id: uuid.UUID,
    action: JournalAction,
    kilit_alindi: asyncio.Event,
    birak: asyncio.Event,
) -> str:
    """tx1: geçişi tamamlar ama `birak` sinyaline kadar COMMIT ETMEZ.

    `SELECT … FOR UPDATE` kilidi commit/rollback'e kadar sürer; `flush` onu
    BIRAKMAZ.
    """
    async with _SessionFactory() as session:
        actor = await session.get(User, actor_id)
        await state_service.perform_transition(session, actor, entry_id, action)
        kilit_alindi.set()
        await birak.wait()
        await session.commit()
        return "ok"


async def _gecis(entry_id: uuid.UUID, actor_id: uuid.UUID, action: JournalAction) -> str:
    async with _SessionFactory() as session:
        actor = await session.get(User, actor_id)
        try:
            await state_service.perform_transition(session, actor, entry_id, action)
            await session.commit()
            return "ok"
        except ConflictError:
            await session.rollback()
            return "conflict"


async def _yarisi_kos(kurulum: _Kurulum, action: JournalAction) -> list[str]:
    kilit_alindi = asyncio.Event()
    birak = asyncio.Event()

    task1 = asyncio.create_task(
        _gecis_ve_tut(kurulum.entry_id, kurulum.actor_id, action, kilit_alindi, birak)
    )
    await asyncio.wait_for(kilit_alindi.wait(), timeout=5)

    task2 = asyncio.create_task(_gecis(kurulum.entry_id, kurulum.ikinci_actor_id, action))
    await asyncio.sleep(0.3)
    assert not task2.done(), (
        "tx2, tx1 kilidi serbest bırakmadan ilerleyebildi — "
        "`perform_transition` artık fiş satırını KİLİTLEMİYOR olabilir "
        "(`for_update=True` ya da `populate_existing` düşmüş)"
    )

    birak.set()
    sonuclar = [
        await asyncio.wait_for(task1, timeout=5),
        await asyncio.wait_for(task2, timeout=5),
    ]
    return sorted(sonuclar)


async def test_iki_esZamanli_post_yalniz_biri_gecer() -> None:
    """🔴 Kilitsiz hâlde iki eşzamanlı `post` da `draft` okur, ikisi de matrisi
    geçer ve fiş İKİ KEZ kayıtlaştırılırdı.

    Bekleyen istek uyandığında kararı YENİDEN verir: taze satırda durum artık
    `posted` olduğu için matris `(posted, post)` çiftini tanımaz ve **409** döner.
    """
    kurulum = await _kur(JournalEntryStatus.draft)
    try:
        assert await _yarisi_kos(kurulum, JournalAction.post) == ["conflict", "ok"]

        async with _SessionFactory() as session:
            entry = await session.get(JournalEntry, kurulum.entry_id)
            assert entry.status is JournalEntryStatus.posted
    finally:
        await _temizle(kurulum)


async def test_iki_esZamanli_reverse_YALNIZ_BIR_storno_uretir() -> None:
    """🔴 İki storno doğsaydı hesabın bakiyesi (K3) `−orijinal` kadar kayardı ve
    kaydığını hiçbir kolon farkı ele vermezdi (bakiye SAKLANMAZ).

    Sayım doğrudan `reversal_of_id` üzerindedir: `uq_journal_entries_reversal_of`
    son savunma olarak KALIR, ama kullanıcıya Türkçe bir 409 gitmesi servis
    kapısına bağlıdır.
    """
    kurulum = await _kur(JournalEntryStatus.posted)
    try:
        assert await _yarisi_kos(kurulum, JournalAction.reverse) == ["conflict", "ok"]

        async with _SessionFactory() as session:
            stornolar = (
                (
                    await session.execute(
                        select(JournalEntry).where(JournalEntry.reversal_of_id == kurulum.entry_id)
                    )
                )
                .scalars()
                .all()
            )
            assert len(stornolar) == 1
            orijinal = await session.get(JournalEntry, kurulum.entry_id)
            assert orijinal.status is JournalEntryStatus.reversed
    finally:
        await _temizle(kurulum)
