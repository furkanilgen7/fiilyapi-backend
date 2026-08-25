"""MU-2 T3 — dönem kilidi eşzamanlılık testlerinin PAYLAŞILAN kurulum/temizlik
yardımcıları.

Gövdeler `test_mu2_periods_lock.py`den TAŞINDI (kopyalanmadı); 800 satır tavanı
için dosya sınırı değişti, DAVRANIŞ değişmedi.

🔴 **TESTLERİN HEPSİ ve `_temizle` AYNI DOSYADA KALDI.** Bu dosya `db_session`
yalıtımını KULLANMAZ — gerçekten commit eder, bıraktığı her satır paylaşılan
test veritabanında KALICIDIR. `_temizle`yi çağıran testler ile onu bekçileyen
`test_6_TEMIZLIK_HICBIR_SATIR_BIRAKMAZ_sayac_DAHIL` birbirinden AYRILSAYDI
bekçi başka bir işçinin (xdist `--dist loadfile`) veritabanına bakar ve
KENDİLİĞİNDEN yeşil kalırdı — yani hiçbir şey bekçilemezdi.
Bölünen tek şey yardımcı GÖVDELERİDİR; çağrı sırası ve dosya BÜTÜNLÜĞÜ aynı.
"""

import asyncio
import contextlib
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import delete, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import ConflictError
from app.core.security import hash_password
from app.modules.accounting import numbering, periods_service, service, state_service
from app.modules.accounting.models import (
    AccountingPeriod,
    AccountingPeriodStatus,
    ChartAccount,
    ChartAccountType,
    JournalEntry,
    JournalEntryCounter,
    JournalEntryStatus,
    JournalLine,
)
from app.modules.accounting.schemas import JournalEntryCreate, JournalLineInput
from app.modules.accounting.transitions import JournalAction
from app.modules.roles.models import Role
from app.modules.users.models import User
from tests.conftest import test_engine

_SessionFactory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

#: Rol anahtarı ve e-postalar TESTE ÖZELDİR: bu dosya GERÇEKTEN commit ettiği
#: için sızıntı ancak yaratılan satırların tam bilinmesiyle kapanır.
_ROL_ANAHTARI = "mu2_donem_admin"
_EPOSTALAR = ("mu2-kilit1@donem.co", "mu2-kilit2@donem.co")
_KODLAR = ("199", "399")

#: Testin dönemi — canlı takvimden UZAK, sabit. Değişken bir dönem (bugün)
#: seçilseydi başka bir testin kurduğu satırla çakışabilirdi.
YIL, AY = 2031, 5
TARIH = date(YIL, AY, 12)

#: SIRA-B — kronolojik sıra denetiminin baktığı KOMŞU dönemler. `ONCEKI` (2031/4)
#: `(YIL, AY)`nin takvim öncesidir; `ONCEKININ_ONCESI` (2031/3) yalnızca
#: `ONCEKI`nin kendisinin de kapatılabilmesi için KAPALI kurulur — aksi hâlde
#: eşzamanlılık testinde iki görevden biri sıra kuralına takılır ve yarış hiç
#: kurulamazdı.
ONCEKI = (YIL, AY - 1)
ONCEKININ_ONCESI = (YIL, AY - 2)
_DONEMLER = ((YIL, AY), ONCEKI, ONCEKININ_ONCESI)

#: Baraj/görev bekleyişlerinin TAVANI. Kilit DOĞRUYKEN görevler saniyenin
#: altında biter; tavan yalnızca bozuk bir kurulumun testi asmasını engeller.
_TAVAN_SANIYE = 15


class _Kurulum:
    def __init__(
        self,
        actor_ids: list[uuid.UUID],
        role_id: uuid.UUID,
        account_ids: list[uuid.UUID],
        entry_id: uuid.UUID | None = None,
    ) -> None:
        self.actor_ids = actor_ids
        self.role_id = role_id
        self.account_ids = account_ids
        self.entry_id = entry_id


async def _kur(
    *, taslak_fis: bool = False, donem_var: bool = False, sira_zinciri: bool = False
) -> _Kurulum:
    """İki aktör + iki YAPRAK hesap; istenirse dönemde bir `draft` fiş.

    🔴 `donem_var=True` dönem satırını **AÇIK** olarak ÖNCEDEN yazar. Bu dal
    `FOR UPDATE`in tek başına taşıdığı yükü açığa çıkarır: satır varken
    `ON CONFLICT DO NOTHING` hiç beklemez ve serileştirmeyi YALNIZCA satır
    kilidi yapar (modül docstring'i).

    🔴 İZİN SATIRI GEREKMEZ: yetki kapısı ROUTER'dadır (`require_permission`),
    bu dosya SERVİSİ doğrudan çağırır. Muhasebe kapsam süzgeci taşımaz (spec §3),
    dolayısıyla proje/şantiye kurulumu da yoktur.
    """
    async with _SessionFactory() as session:
        role = Role(key=_ROL_ANAHTARI, name="Dönem Eşzamanlılık Rolü")
        session.add(role)
        await session.flush()
        aktorler = [
            User(
                email=eposta,
                password_hash=hash_password("parola1234"),
                full_name=f"Dönem Aktörü {sira}",
                role_id=role.id,
            )
            for sira, eposta in enumerate(_EPOSTALAR, start=1)
        ]
        session.add_all(aktorler)
        hesaplar = [
            ChartAccount(code=_KODLAR[0], name="Kasa (kilit)", account_type=ChartAccountType.asset),
            ChartAccount(
                code=_KODLAR[1], name="Satıcılar (kilit)", account_type=ChartAccountType.liability
            ),
        ]
        session.add_all(hesaplar)
        if donem_var:
            session.add(AccountingPeriod(year=YIL, month=AY, status=AccountingPeriodStatus.open))
        if sira_zinciri:
            # 🔴 Aktörler ÖNCE flush edilir: `closed_by_id` Python tarafında
            # doğan bir UUID'dir ve flush olmadan `None`dır — damga eksik kalır
            # ve `ck_accounting_periods_closed_stamp` INSERT'ü reddederdi.
            await session.flush()
            # SIRA-B: (AY-1) AÇIK — yarışın konusu; (AY-2) KAPALI — (AY-1)'in
            # kendisi de kapatılabilsin diye. `closed` damgası BÜTÜNDÜR
            # (`ck_accounting_periods_closed_stamp`), bu yüzden üç parça birlikte.
            session.add(
                AccountingPeriod(
                    year=ONCEKI[0], month=ONCEKI[1], status=AccountingPeriodStatus.open
                )
            )
            session.add(
                AccountingPeriod(
                    year=ONCEKININ_ONCESI[0],
                    month=ONCEKININ_ONCESI[1],
                    status=AccountingPeriodStatus.closed,
                    closed_at=datetime(2031, 4, 1, tzinfo=UTC),
                    closed_by_id=aktorler[0].id,
                )
            )
        await session.flush()

        entry_id: uuid.UUID | None = None
        if taslak_fis:
            entry = JournalEntry(
                # 🔑 FIS-NO — `entry_no` NOT NULL (bkz. `conftest.fis_fabrikasi`).
                entry_no=await numbering.generate_entry_no(session, year=YIL),
                entry_date=TARIH,
                period_year=YIL,
                period_month=AY,
                description="Kilit taslağı",
                status=JournalEntryStatus.draft,
                total_debit=Decimal("1000.00"),
                total_credit=Decimal("1000.00"),
                created_by_id=aktorler[0].id,
            )
            session.add(entry)
            await session.flush()
            session.add_all(
                [
                    JournalLine(
                        entry_id=entry.id,
                        sort_order=0,
                        account_id=hesaplar[0].id,
                        debit=Decimal("1000.00"),
                        credit=Decimal("0.00"),
                    ),
                    JournalLine(
                        entry_id=entry.id,
                        sort_order=1,
                        account_id=hesaplar[1].id,
                        debit=Decimal("0.00"),
                        credit=Decimal("1000.00"),
                    ),
                ]
            )
            await session.flush()
            entry_id = entry.id

        await session.commit()
        return _Kurulum(
            [a.id for a in aktorler], role.id, [h.id for h in hesaplar], entry_id=entry_id
        )


async def _gorevleri_bosalt(*gorevler: asyncio.Task | None) -> None:
    """Temizlikten ÖNCE görevleri sonlandırır — MUTASYON DENETİMİ İÇİN ŞART.

    Kilit kaldırıldığında iddia kırmızıya döner ve gövde ORTADA terk edilir; bir
    görev hâlâ commit etmemiş bir transaction içinde kilit tutuyor olabilir. Bu
    boşaltma olmadan `_temizle`nin DELETE'i o kilidi sonsuza dek bekler ve
    kırmızı test SONSUZ ASKIYA dönüşürdü (İK-2 dersi).
    """
    for gorev in gorevler:
        if gorev is None:
            continue
        gorev.cancel()
        with contextlib.suppress(BaseException):
            await gorev


async def _temizle(kurulum: _Kurulum) -> None:
    async with _SessionFactory() as session:
        fis_ids = (
            (
                await session.execute(
                    select(JournalEntry.id).where(
                        JournalEntry.period_year == YIL, JournalEntry.period_month == AY
                    )
                )
            )
            .scalars()
            .all()
        )
        if fis_ids:
            await session.execute(delete(JournalLine).where(JournalLine.entry_id.in_(fis_ids)))
            # Storno önce silinir: `reversal_of_id` FK'si orijinali tutar.
            await session.execute(
                delete(JournalEntry).where(JournalEntry.reversal_of_id.in_(fis_ids))
            )
            await session.execute(delete(JournalEntry).where(JournalEntry.id.in_(fis_ids)))
        await session.execute(
            delete(AccountingPeriod).where(
                tuple_(AccountingPeriod.year, AccountingPeriod.month).in_(_DONEMLER)
            )
        )
        # 🔴 SAYAC SATIRI DA SILINIR (TB-XDIST, 2026-08-25). Bu dosya GERCEKTEN
        # commit eder; `generate_entry_no(..., year=YIL)` cagrisi
        # `journal_entry_counters`e KALICI bir satir yaziyordu ve temizlik onu
        # ATLIYORDU. Sonuc: paylasilan test veritabaninda `{2031: N}` satiri
        # kaliyor ve `test_fisno_numbering.py::test_YIL_sayaclari_BIRBIRINI_sifirlamaz`
        # (tabloyu GLOBAL okuyan bir iddia) kirmiziya donuyordu. Seri kosuda
        # gorunmuyordu cunku alfabetik sirada `test_fisno_*` bu dosyadan ONCE
        # kosuyor; sira degisince (xdist `--dist loadfile`) hemen patliyor.
        # KANIT: iki dosya bu sirayla SERI kosuldugunda da kirmizi (olculdu).
        await session.execute(delete(JournalEntryCounter).where(JournalEntryCounter.year == YIL))
        await session.execute(delete(ChartAccount).where(ChartAccount.id.in_(kurulum.account_ids)))
        await session.execute(delete(User).where(User.id.in_(kurulum.actor_ids)))
        await session.execute(delete(Role).where(Role.id == kurulum.role_id))
        await session.commit()


async def _guvenli_temizlik(kurulum: _Kurulum, *gorevler: asyncio.Task | None) -> None:
    """Görevleri boşalt, sonra TAVANLI temizle. Temizliğin kendi hatası ASIL
    iddianın hata metnini EZMEMELİDİR."""
    await _gorevleri_bosalt(*gorevler)
    with contextlib.suppress(Exception):
        await asyncio.wait_for(_temizle(kurulum), timeout=_TAVAN_SANIYE)


async def _kapat(
    kurulum: _Kurulum,
    aktor_sirasi: int,
    baraj: asyncio.Barrier,
    yil: int = YIL,
    ay: int = AY,
) -> str:
    """Bağımsız bir bağlantıda TAM `close` yolu: UPSERT → KİLİT → denetim → damga.

    🔴 ISINMA + BARAJ — determinizmin tamamı buradadır (modül docstring'i).
    """
    async with _SessionFactory() as session:
        actor = await session.get(User, kurulum.actor_ids[aktor_sirasi])
        await asyncio.wait_for(baraj.wait(), timeout=_TAVAN_SANIYE)
        try:
            await periods_service.close_period(session, actor, yil, ay)
        except ConflictError:
            await session.rollback()
            return "conflict"
        except Exception as hata:  # noqa: BLE001
            await session.rollback()
            # 🔴 UNIQUE ihlali (500) burada AYRI bir sonuç olarak geri döner:
            # yutulsaydı `count("closed") == 1` iddiası doğru çıkar ve kusur
            # GÖRÜNMEZ kalırdı.
            return f"error:{type(hata).__name__}"
        await session.commit()
        return "closed"


async def _ac_donem(
    kurulum: _Kurulum,
    aktor_sirasi: int,
    baraj: asyncio.Barrier,
    yil: int = YIL,
    ay: int = AY,
) -> str:
    async with _SessionFactory() as session:
        actor = await session.get(User, kurulum.actor_ids[aktor_sirasi])
        await asyncio.wait_for(baraj.wait(), timeout=_TAVAN_SANIYE)
        try:
            await periods_service.reopen_period(session, actor, yil, ay)
        except ConflictError:
            await session.rollback()
            return "conflict"
        except Exception as hata:  # noqa: BLE001
            await session.rollback()
            return f"error:{type(hata).__name__}"
        await session.commit()
        return "opened"


async def _fis_olustur(kurulum: _Kurulum, aktor_sirasi: int, baraj: asyncio.Barrier) -> str:
    """Kapalı-döneme-yazma yasağının eşzamanlı hâli: dönemde YENİ taslak fiş."""
    async with _SessionFactory() as session:
        actor = await session.get(User, kurulum.actor_ids[aktor_sirasi])
        await asyncio.wait_for(baraj.wait(), timeout=_TAVAN_SANIYE)
        try:
            await service.create_entry(
                session,
                actor,
                JournalEntryCreate(
                    entry_date=TARIH,
                    description="Eşzamanlı fiş",
                    lines=[
                        JournalLineInput(
                            account_id=kurulum.account_ids[0],
                            debit=Decimal("50.00"),
                            credit=Decimal("0.00"),
                        ),
                        JournalLineInput(
                            account_id=kurulum.account_ids[1],
                            debit=Decimal("0.00"),
                            credit=Decimal("50.00"),
                        ),
                    ],
                ),
            )
        except ConflictError:
            await session.rollback()
            return "conflict"
        except Exception as hata:  # noqa: BLE001
            await session.rollback()
            return f"error:{type(hata).__name__}"
        await session.commit()
        return "ok"


async def _kayitlastir(kurulum: _Kurulum, aktor_sirasi: int, baraj: asyncio.Barrier) -> str:
    async with _SessionFactory() as session:
        actor = await session.get(User, kurulum.actor_ids[aktor_sirasi])
        await asyncio.wait_for(baraj.wait(), timeout=_TAVAN_SANIYE)
        try:
            await state_service.perform_transition(
                session, actor, kurulum.entry_id, JournalAction.post
            )
        except ConflictError:
            await session.rollback()
            return "conflict"
        except Exception as hata:  # noqa: BLE001
            await session.rollback()
            return f"error:{type(hata).__name__}"
        await session.commit()
        return "posted"
