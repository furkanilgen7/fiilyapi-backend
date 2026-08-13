"""MK-1 T4 — 🔴 K12 EŞİK = KİLİT KANONU: günlük 24 saat tavanı eşzamanlılık altında.

Spec §3 K12: "bu bir eşik denetimidir → `equipment` satırı `with_for_update` ile
denetimden ÖNCE kilitlenir; kilit sırası tüm uçlarda SABİT; regresyon **iki gerçek
bağlantıyla** yazılır ve kilit kaldırılınca KIRMIZI olduğu kanıtlanır."

## Niçin `client`/`seeded_db` KULLANILMAZ

`tests/conftest.py`'deki `db_session` her testi TEK bağlantı üzerinde SAVEPOINT'e
sarar ve dış transaction'ı asla gerçekten COMMIT ETMEZ — o session üzerinde iki
`asyncio.gather` görevi AYNI bağlantıyı paylaşır ve gerçek satır kilidi test
EDİLEMEZ. Bu dosya `tests/personnel/test_ik2_leave_concurrency.py` (İK-2) ve
`tests/progress_payments/test_concurrency.py` desenini birebir izler: `test_engine`
üzerinden İKİ BAĞIMSIZ bağlantı, gerçek commit, sonunda gerçek temizlik.

Bariyer (`asyncio.Event`) BİLİNÇLİDİR: çıplak `asyncio.gather` iki görevi kritik
anda KESİŞTİRMEZ, yarış penceresi hiç açılmayabilir. Burada tx1 kilidi ALIP
TUTARKEN tx2'nin bloke olduğu DOĞRUDAN kanıtlanır.

## Kurulumun DEPO makinesi kullanması bilinçlidir

Ekipman `site_id IS NULL` açılır (K4/K20 depo istisnası): böylece kurulum proje,
şantiye ve `user_project_access` satırı YARATMAK ZORUNDA KALMAZ — gerçekten
commit eden bir testte yaratılan her satır bir sızıntı riskidir.
"""

import asyncio
import contextlib
import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import delete, event, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import EquipmentValidationError
from app.core.security import hash_password
from app.modules.equipment import service
from app.modules.equipment.models import Equipment, EquipmentCategory, EquipmentWorkLog
from app.modules.equipment.schemas import WorkLogCreate
from app.modules.roles.models import Role
from app.modules.users.models import User
from tests.conftest import test_engine

pytestmark = pytest.mark.asyncio

_SessionFactory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

_GUN = date(2026, 7, 17)

#: Rol anahtarı TESTE ÖZELDİR: `seed_reference_data`'nın ürettiği üretim
#: anahtarlarıyla çakışmaz — bu dosya GERÇEKTEN commit ettiği için sızıntı
#: ancak yaratılan satırların tam bilinmesiyle kapanır.
_ROL_ANAHTARI = "mk1_conc_admin"
_EPOSTALAR = ("mk1-kayit1@conc.co", "mk1-kayit2@conc.co")


class _Kurulum:
    def __init__(
        self, equipment_id: uuid.UUID, actor_ids: list[uuid.UUID], role_id: uuid.UUID
    ) -> None:
        self.equipment_id = equipment_id
        self.actor_ids = actor_ids
        self.role_id = role_id


async def _kur() -> _Kurulum:
    async with _SessionFactory() as session:
        role = Role(key=_ROL_ANAHTARI, name="Makine Eşzamanlılık Rolü")
        session.add(role)
        await session.flush()

        equipment = Equipment(name="Eşzamanlılık Vinci", category=EquipmentCategory.crane)
        session.add(equipment)
        aktorler = [
            User(
                email=eposta,
                password_hash=hash_password("parola1234"),
                full_name=f"Kayıt Aktörü {sira}",
                role_id=role.id,
            )
            for sira, eposta in enumerate(_EPOSTALAR, start=1)
        ]
        session.add_all(aktorler)
        await session.flush()
        await session.commit()
        return _Kurulum(
            equipment_id=equipment.id,
            actor_ids=[a.id for a in aktorler],
            role_id=role.id,
        )


async def _gorevleri_bosalt(*gorevler: asyncio.Task | None) -> None:
    """Temizlikten ÖNCE tüm görevleri sonlandırır — MUTASYON DENETİMİ İÇİN ŞART.

    Kilit kaldırıldığında `not task2.done()` iddiası kırmızıya döner ve test
    gövdesi ORTADA terk edilir; `task1` hâlâ commit etmemiş bir transaction
    içinde satır kilidi TUTUYOR olur. Bu boşaltma olmadan `_temizle`nin DELETE'i
    o kilidi SONSUZA DEK bekler ve kırmızı bir test SONSUZ ASKIYA dönüşürdü —
    mutasyon kanıtı okunamaz hâle gelirdi (İK-2 dersi).
    """
    for gorev in gorevler:
        if gorev is None:
            continue
        gorev.cancel()
        with contextlib.suppress(BaseException):
            await gorev


async def _temizle(kurulum: _Kurulum) -> None:
    async with _SessionFactory() as session:
        await session.execute(
            delete(EquipmentWorkLog).where(EquipmentWorkLog.equipment_id == kurulum.equipment_id)
        )
        await session.execute(delete(Equipment).where(Equipment.id == kurulum.equipment_id))
        await session.execute(delete(User).where(User.id.in_(kurulum.actor_ids)))
        await session.execute(delete(Role).where(Role.id == kurulum.role_id))
        await session.commit()


def _govde(equipment_id: uuid.UUID, saat: str) -> WorkLogCreate:
    return WorkLogCreate(equipment_id=equipment_id, work_date=_GUN, hours=Decimal(saat))


async def _kaydet_ve_tut(
    equipment_id: uuid.UUID,
    actor_id: uuid.UUID,
    saat: str,
    kilit_alindi: asyncio.Event,
    kilidi_birak: asyncio.Event,
) -> str:
    """tx1: kaydı yazar (kilit + tavan denetimi + flush) ama sinyal gelene kadar
    COMMIT ETMEZ — `SELECT … FOR UPDATE` kilidi bu süre boyunca AÇIK kalır
    (`flush` kilidi BIRAKMAZ, yalnız commit/rollback bırakır)."""
    async with _SessionFactory() as session:
        actor = await session.get(User, actor_id)
        await service.create_work_log(session, actor, _govde(equipment_id, saat))
        kilit_alindi.set()
        await kilidi_birak.wait()
        await session.commit()
        return "created"


async def _kaydet(equipment_id: uuid.UUID, actor_id: uuid.UUID, saat: str) -> str:
    async with _SessionFactory() as session:
        actor = await session.get(User, actor_id)
        try:
            await service.create_work_log(session, actor, _govde(equipment_id, saat))
            await session.commit()
            return "created"
        except EquipmentValidationError:
            await session.rollback()
            return "rejected"


async def _gun_toplami(equipment_id: uuid.UUID) -> Decimal:
    async with _SessionFactory() as session:
        return (
            await session.execute(
                select(func.coalesce(func.sum(EquipmentWorkLog.hours), 0)).where(
                    EquipmentWorkLog.equipment_id == equipment_id,
                    EquipmentWorkLog.work_date == _GUN,
                )
            )
        ).scalar_one()


async def test_iki_esZamanli_kayit_gunluk_tavani_atlatamaz() -> None:
    """🔴 K12 ASIL REGRESYON: aynı ekipman + aynı güne İKİ eşzamanlı 20 saat.

    Kilit YOKKEN ikisi de `toplam = 0` okur, ikisi de `0 + 20 <= 24` görüp geçer
    ve makine bir günde **40 saat** çalışmış olur. Kilit VARKEN tx2 sıraya girer,
    tx1'in commit'ini görür (`toplam = 20`) ve `20 + 20 > 24` diyerek 422 alır.

    Tek istekli bir test bunu ASLA göremez (İK-2 K2 dersi): tek istek yarışı
    hiç açmaz.
    """
    kurulum = await _kur()
    kilit_alindi = asyncio.Event()
    kilidi_birak = asyncio.Event()
    task1: asyncio.Task | None = None
    task2: asyncio.Task | None = None
    try:
        task1 = asyncio.create_task(
            _kaydet_ve_tut(
                kurulum.equipment_id, kurulum.actor_ids[0], "20", kilit_alindi, kilidi_birak
            )
        )
        await asyncio.wait_for(kilit_alindi.wait(), timeout=5)

        task2 = asyncio.create_task(_kaydet(kurulum.equipment_id, kurulum.actor_ids[1], "20"))
        await asyncio.sleep(0.3)
        assert not task2.done(), (
            "tx2, tx1 kilidi serbest bırakmadan ilerleyebildi — `create_work_log` "
            "artık `equipment` satırını KİLİTLEMİYOR olabilir (K12 yarışı yeniden açık)"
        )

        kilidi_birak.set()
        sonuc1 = await asyncio.wait_for(task1, timeout=5)
        sonuc2 = await asyncio.wait_for(task2, timeout=5)
        assert sorted([sonuc1, sonuc2]) == ["created", "rejected"]

        toplam = await _gun_toplami(kurulum.equipment_id)
        assert toplam == Decimal("20.00"), f"günlük 24 saat tavanı atlatıldı: {toplam}"
    finally:
        await _gorevleri_bosalt(task1, task2)
        await _temizle(kurulum)


async def test_esZamanli_silme_ve_kayit_ayni_kilit_sirasini_paylasir() -> None:
    """DELETE'te tavan AZALIR ama kilit yine de ALINIR (kilit sırası SABİT).

    Sıra uçtan uca aynı olmasaydı, DELETE'i `work_log` satırından başlatan bir
    yol ile POST'u `equipment`ten başlatan yol karşılıklı kilitlenme (deadlock)
    üretirdi. Burada silme, açık tutulan POST kilidinin ARKASINDA bekler.
    """
    kurulum = await _kur()
    async with _SessionFactory() as session:
        actor = await session.get(User, kurulum.actor_ids[0])
        log, _ = await service.create_work_log(session, actor, _govde(kurulum.equipment_id, "10"))
        log_id = log.id
        await session.commit()

    kilit_alindi = asyncio.Event()
    kilidi_birak = asyncio.Event()
    task1: asyncio.Task | None = None
    task2: asyncio.Task | None = None
    try:
        task1 = asyncio.create_task(
            _kaydet_ve_tut(
                kurulum.equipment_id, kurulum.actor_ids[0], "10", kilit_alindi, kilidi_birak
            )
        )
        await asyncio.wait_for(kilit_alindi.wait(), timeout=5)

        async def sil() -> str:
            async with _SessionFactory() as session:
                actor = await session.get(User, kurulum.actor_ids[1])
                await service.delete_work_log(session, actor, log_id)
                await session.commit()
                return "deleted"

        task2 = asyncio.create_task(sil())
        await asyncio.sleep(0.3)
        assert not task2.done(), (
            "silme, POST'un `equipment` kilidini beklemedi — `delete_work_log` "
            "kilit sırasını PAYLAŞMIYOR (karşılıklı kilitlenme penceresi)"
        )

        kilidi_birak.set()
        assert await asyncio.wait_for(task1, timeout=5) == "created"
        assert await asyncio.wait_for(task2, timeout=5) == "deleted"
        assert await _gun_toplami(kurulum.equipment_id) == Decimal("10.00")
    finally:
        await _gorevleri_bosalt(task1, task2)
        await _temizle(kurulum)


async def test_kilit_tavan_okumasindan_ONCE_alinir() -> None:
    """Kilidin VARLIĞI, YERİ ve SIRASI — SQL düzeyinde (TOCTOU).

    Davranış testi kilidin ALINDIĞINI ölçer ama NEREDE alındığını tam ayırt
    edemez: kilit eşiği besleyen `sum(hours)` okumasından SONRA alınırsa yarış
    penceresi AÇIK kalır ve iki istek de eski toplamı okumuş olur.
    """
    kurulum = await _kur()
    ifadeler: list[str] = []

    def kaydet(conn, cursor, statement, parameters, context, executemany) -> None:  # noqa: ANN001
        ifadeler.append(" ".join(statement.split()))

    event.listen(test_engine.sync_engine, "before_cursor_execute", kaydet)
    try:
        async with _SessionFactory() as session:
            actor = await session.get(User, kurulum.actor_ids[0])
            await service.create_work_log(session, actor, _govde(kurulum.equipment_id, "8"))
            await session.commit()
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", kaydet)
        await _temizle(kurulum)

    ekipman_kilidi = [
        i for i, ifade in enumerate(ifadeler) if "FOR UPDATE" in ifade and "FROM equipment" in ifade
    ]
    esik_okumasi = [
        i for i, ifade in enumerate(ifadeler) if "sum(equipment_work_logs.hours)" in ifade
    ]

    assert ekipman_kilidi, f"`equipment` satırı FOR UPDATE ile okunmadı: {ifadeler}"
    assert esik_okumasi, f"günlük tavanı besleyen sum() okuması hiç koşmadı: {ifadeler}"
    assert ekipman_kilidi[0] < esik_okumasi[0], (
        "kilit, eşiği besleyen okumadan SONRA alınmış — TOCTOU penceresi açık"
    )
