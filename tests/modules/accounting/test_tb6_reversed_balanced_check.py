"""TB6 T2 — dengesiz `reversed` fiş CHECK borcu (MU-2'den kalan açık borç).

## Kapatılan delik

`ck_journal_entries_posted_balanced` yalnız `status <> 'posted'` diyordu; ama
`balance.POSTING_STATUSES` = `posted` **+ `reversed`**tir ve deftere ikisi de
GİRER. Yani **dengesiz bir `reversed` fiş DB'ye yasal olarak girebiliyordu** ve
girdiğinde mizan/bilanço/gelir tablosu kalıcı olarak kayıyordu.

## 🔴 Bu dosyanın iddiaları DB DÜZEYİNDEDİR

Servis katmanı zaten koruyordu (matris `draft → reversed`i tanımaz, toplamlar
yalnız `draft`ta yazılır) — **kanıtlanacak olan KISITIN KENDİSİDİR.** Bu yüzden
testler `session.add()` ile DOĞRUDAN ORM'den yazar ve `IntegrityError` bekler:
uçtan ölçen bir test bu sınıfı GÖREMEZ ("iki katman birbirini maskeler" kanonu,
alt katmanın kendi bekçisi olur).

## 🔴 Kümenin İKİ kopyası vardır ve bu bilinçlidir

`models.BALANCE_ENFORCED_STATUSES` (SQL yansıması) ile
`balance.POSTING_STATUSES` (defterin süzgeci) AYNI kümedir ama iki AYRI
katmandadır (ters import bağımlılığı yüzünden birleştirilemezler). Ayrışmaları
sessiz bir delik açardı — `test_kisit_kumesi_POSTING_STATUSES_ile_AYNI` onu
bağlar.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounting import balance
from app.modules.accounting.models import (
    BALANCE_ENFORCED_STATUSES,
    JournalEntry,
    JournalEntryStatus,
)

pytestmark = pytest.mark.asyncio

#: PG'nin CHECK ihlali sınıfı. Tek elemanlı ama TUPLE'dır (PG 18/16 farkı
#: kanonu): sınıf kodu sürüme göre genişlerse burası ölçülerek büyütülür,
#: ata sınıfa GEVŞETİLMEZ.
CHECK_VIOLATION = ("23514",)


def test_kisit_kumesi_POSTING_STATUSES_ile_AYNI() -> None:
    """🔴 İKİ KATMAN AYRIŞAMAZ: deftere giren her durumun dengesi zorlanır.

    `balance.POSTING_STATUSES`e yeni bir üye eklenip `BALANCE_ENFORCED_STATUSES`
    unutulsaydı, o durumdaki dengesiz fişler yine deftere girer ve borç AYNEN
    geri gelirdi — bu kez fark edilmeden.
    """
    assert set(BALANCE_ENFORCED_STATUSES) == {durum.value for durum in balance.POSTING_STATUSES}


async def _yaz(
    session: AsyncSession,
    kullanici_id,  # noqa: ANN001
    *,
    status: JournalEntryStatus,
    debit: str,
    credit: str,
) -> None:
    """Fişi DOĞRUDAN yazar — servis katmanı HİÇ devrede değildir."""
    session.add(
        JournalEntry(
            entry_date=date(2026, 7, 17),
            period_year=2026,
            period_month=7,
            description="TB6 denge probu",
            status=status,
            total_debit=Decimal(debit),
            total_credit=Decimal(credit),
            created_by_id=kullanici_id,
        )
    )
    await session.flush()


async def test_DENGESIZ_reversed_fis_DB_DUZEYINDE_REDDEDILIR(
    seeded_db: AsyncSession, kullanici_id
) -> None:
    """🔴 TB6 T2'nin ta kendisi: bu satır ESKİ kısıtla DB'ye GİRİYORDU."""
    with pytest.raises(IntegrityError) as hata:
        await _yaz(
            seeded_db,
            kullanici_id,
            status=JournalEntryStatus.reversed,
            debit="500.00",
            credit="0.00",
        )
    assert hata.value.orig.sqlstate in CHECK_VIOLATION
    assert "ck_journal_entries_posting_balanced" in str(hata.value.orig)


async def test_DENGESIZ_posted_fis_REDDEDILIR(seeded_db: AsyncSession, kullanici_id) -> None:
    """Eski kısıtın kapsadığı hâl — regresyon: yeni kısıt onu KAYBETMEDİ."""
    with pytest.raises(IntegrityError) as hata:
        await _yaz(
            seeded_db,
            kullanici_id,
            status=JournalEntryStatus.posted,
            debit="500.00",
            credit="0.00",
        )
    assert hata.value.orig.sqlstate in CHECK_VIOLATION


async def test_DENGESIZ_draft_fis_KABUL_EDILIR(seeded_db: AsyncSession, kullanici_id) -> None:
    """🔴 SINIR: `draft` dengesiz BIRAKILABİLİR ve bu KASITLIDIR.

    Kısıt `draft`a da kapatılsaydı yarım bırakılmış bir fiş kaydedilemez, tek
    satırını girip ertesi gün devam etmek imkânsız olurdu. Kapı
    kayıtlaştırma anında (`post`) zaten yeniden koşar.
    """
    await _yaz(
        seeded_db, kullanici_id, status=JournalEntryStatus.draft, debit="500.00", credit="0.00"
    )


async def test_DENGELI_reversed_fis_KABUL_EDILIR(seeded_db: AsyncSession, kullanici_id) -> None:
    """Kısıt storno akışını TIKAMAZ: gerçek bir `reversed` fiş zaten dengelidir."""
    await _yaz(
        seeded_db,
        kullanici_id,
        status=JournalEntryStatus.reversed,
        debit="500.00",
        credit="500.00",
    )
