"""Muhasebe DÖNEM KİLİDİ (MU-2 T3) — kapat · aç · kapalı-döneme-yazma yasağı.

`service.py`/`state_service.py`den AYRI bir dosyadır: o ikisi fişin içeriğini ve
durumunu yazar, bu dosya DÖNEMİN kendisini yönetir ve yasağın TEK kapısını
tutar. İçeri alınsalardı 800 satır tavanına doğru itilirdi (MU-1 kanonu).

## 🔴 UPSERT-SONRA-KİLİTLE — bu dosyanın ASIL deseni

Dönem kaydı PROAKTİF açılmaz: 12 ay satırı önden yazmak YAGNI'dir ve "hangi
yıllar açılmıştı" diye ikinci bir soru doğururdu. **Kayıt YOKSA dönem AÇIKTIR.**

Ama o zaman kilitlenecek satır da yoktur ve iki eşzamanlı `close` isteği ikisi
de "satır yok" görüp INSERT ederdi → `uq_accounting_periods_year_month` ihlali →
biri **500**. Bu KABUL EDİLEMEZ. Bu yüzden `lock_period` her denetimden ÖNCE:

    1. INSERT … VALUES (…, 'open') ON CONFLICT (year, month) DO NOTHING
    2. SELECT … WHERE year=? AND month=? FOR UPDATE   (+ populate_existing)

İki adım aynı transaction'da çakışmayı SERİLEŞTİRİR: ikinci istek ya UNIQUE
indeks kilidinde (adım 1) ya satır kilidinde (adım 2) bekler ve uyandığında
kararı TAZE satır üzerinde YENİDEN verir. `populate_existing` ayrılmaz
parçasıdır — kimlik haritasındaki bayat nesne kilidi HİÇ ALDIRMAZDI
(`invoicing.get_invoice` dersi).

Yan fayda: yazma akışları da dönemi kilitlediği için dönem listesi kendiliğinden
dolar; kullanıcı hiçbir dönemi elle "açmak" zorunda kalmaz.

## 🔴 KİLİT SIRASI — SABİT ve GLOBAL

    accounting_periods  →  journal_entries  →  journal_lines  →  chart_of_accounts

Dönem satırı **EN ÖNCE** kilitlenir. Fişe bağlı uçlarda (`PATCH`/`DELETE`/
`PUT lines`/`post`/`reverse`) dönemi öğrenmek için fişe KİLİTSİZ bir bakış atmak
gerekir; bakış yalnızca HANGİ dönemin kilitleneceğini söyler, hiçbir karar ona
dayanmaz — karar her zaman KİLİTLİ satırlar üzerinde verilir
(`service.entry_for_write`, sondaki `PERIOD_MOVED` emniyet ağı dahil).

**Birden çok dönem** kilitlenecekse (yalnız iki yol: `PATCH entry_date` eski+yeni
dönemi, `reverse` orijinal+bugün dönemini) sıra **artan `(year, month)`**dır.
Sabit bir sıra olmasaydı iki istek dönemleri ters sırada kilitler ve karşılıklı
kilitlenme (deadlock) doğardı.

`close`/`reopen` YALNIZCA dönem satırını kilitler, hiçbir fiş satırına
dokunmaz — bu yüzden kapanış ile yazma arasında ters yönlü bir kilit çifti
yapısal olarak oluşamaz.

## 🔴 Yasak TEK BİR YERDE yaşar

Altı giriş noktası (`create`/`update`/`delete`/`replace_lines`/`post`/`reverse`)
`assert_periods_open`ı çağırır; denetim onlara KOPYALANMAZ. Kopyalansaydı biri
bir gün güncellenmez ve o yol kapıyı sessizce atlardı (BC dersi: *"alanın TÜM
giriş noktaları aynı sabitten okur"*).

## Yeni `AuditAction` üyesi AÇILMADI

`action` gerçek bir Postgres enum tipidir. Kapatma `approve`a (bir ONAYDIR),
açma `update`e oturur; ayrım `messages.accounting_period_*` METNİNDEDİR.
"""

import uuid
from collections.abc import Iterable
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError
from app.modules.accounting import guards, repository
from app.modules.accounting.models import AccountingPeriod, AccountingPeriodStatus
from app.modules.accounting.periods_schemas import (
    AccountingPeriodListResponse,
    AccountingPeriodResponse,
)
from app.modules.audit import messages
from app.modules.users.models import User

__all__ = [
    "assert_periods_open",
    "close_period",
    "list_periods",
    "lock_period",
    "period_of",
    "reopen_period",
]

#: `(yıl, ay)` çifti. Dönem her yerde BU ŞEKİLDE dolaşır; ayrı iki parametre
#: olarak taşınsaydı sıralama (deadlock önlemi) bir yerde ters kurulabilirdi.
Period = tuple[int, int]


def period_of(gun: date) -> Period:
    """Takvim gününün dönemi. 🔴 `journal_entries.period_*` ile AYNI türetme.

    `ck_journal_entries_period_matches_date` fişin kolonlarını `entry_date`e
    kilitler; buradaki türetme onunla BİREBİR olmalıdır, yoksa yasak fişin
    gerçekte durduğu dönemden BAŞKA bir dönemi denetlerdi.
    """
    return (gun.year, gun.month)


async def lock_period(session: AsyncSession, year: int, month: int) -> AccountingPeriod:
    """🔴 UPSERT-SONRA-KİLİTLE — modül docstring'indeki iki adım.

    Dönüş DAİMA bir satırdır: yoksa `open` olarak doğar. Çağıranın "None geldi,
    demek ki açık" diye ikinci bir dal yazması GEREKMEZ ve o dal olmadığı için
    kilitsiz bir karar yolu da yoktur.

    `session.get(..., with_for_update=True)` KULLANILMAZ: kilitlenecek satır
    birincil anahtarla değil `(year, month)` ile bulunur.
    """
    await session.execute(
        pg_insert(AccountingPeriod)
        .values(
            id=uuid.uuid4(),
            year=year,
            month=month,
            status=AccountingPeriodStatus.open,
        )
        .on_conflict_do_nothing(index_elements=["year", "month"])
    )
    stmt = (
        select(AccountingPeriod)
        .where(AccountingPeriod.year == year, AccountingPeriod.month == month)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return (await session.execute(stmt)).scalar_one()


async def assert_periods_open(session: AsyncSession, periods: Iterable[Period]) -> None:
    """🔴 KAPALI DÖNEME YAZMA YASAĞININ TEK KAPISI — altı uç buraya bakar.

    Her dönem KİLİTLENEREK okunur (emir: denetim kilitli okumayla yapılır); bu
    sayede `close` ile `post`/`create` yarışı serileşir ve "kapanıştan hemen
    sonra kapalı döneme düşen fiş" penceresi kapanır.

    Sıra **artan `(year, month)`**dır (deadlock önlemi, modül docstring'i) ve
    küme TEKİLLEŞTİRİLİR: aynı dönemi iki kez kilitlemek zararsızdır ama
    `PATCH`in eski=yeni dönem hâlinde gereksiz ikinci bir turdur.
    """
    for year, month in sorted(set(periods)):
        period = await lock_period(session, year, month)
        if period.status is AccountingPeriodStatus.closed:
            raise ConflictError(guards.PERIOD_CLOSED)


# --------------------------------------------------------------------------- #
# Uçlar
# --------------------------------------------------------------------------- #


async def list_periods(
    session: AsyncSession, *, year: int | None, limit: int, offset: int
) -> AccountingPeriodListResponse:
    """K7 zarfı. `total` liste ile AYNI süzgeçten geçer (`_period_filtered`)."""
    satirlar = await repository.list_periods(session, year=year, limit=limit, offset=offset)
    return AccountingPeriodListResponse(
        items=[AccountingPeriodResponse.model_validate(donem) for donem in satirlar],
        total=await repository.count_periods(session, year=year),
        limit=limit,
        offset=offset,
    )


async def close_period(
    session: AsyncSession, actor: User, year: int, month: int
) -> tuple[AccountingPeriod, str]:
    """🔴 EŞİK = KİLİT — SIRA DEĞİŞMEZ:

        1. KİLİT   — `lock_period` (UPSERT + `FOR UPDATE`), TÜM denetimlerden ÖNCE
        2. DURUM   — zaten `closed` ise **409**
        3. TASLAK  — dönemde `draft` fiş varsa **409**
        4. DAMGA   — `status` + `closed_at` + `closed_by_id` BİRLİKTE
        5. REFRESH — `updated_at` sunucu damgasıdır

    **Kilit 2. adımdan SONRA alınsaydı** iki eşzamanlı `close` da `open` okur,
    ikisi de damgayı yazar ve ikincisi birincinin `closed_at`ini EZERDİ; kayıt
    yokken ise ikisi de INSERT edip UNIQUE ihlaliyle 500 üretirdi.

    Adım 3 kilitten SONRA koştuğu için taslak sayımı ile damga arasına başka bir
    işlem giremez: eşzamanlı bir `create_entry` de aynı dönem satırını kilitler
    ve ya kapanıştan önce ya sonra sıraya girer.

    🔴 Damga ÜÇ PARÇADIR ve `ck_accounting_periods_closed_stamp` üçünü birlikte
    zorlar (MK-2 N-ÇARPANLI SNAPSHOT kanonunun kardeşi): biri unutulsaydı DB'nin
    KENDİSİ kısıtı ihlal eder ve kullanıcı ayrımsız bir 409 alırdı.
    """
    period = await lock_period(session, year, month)

    if period.status is AccountingPeriodStatus.closed:
        raise ConflictError(guards.PERIOD_ALREADY_CLOSED)
    if await repository.has_draft_entries(session, year, month):
        raise ConflictError(guards.PERIOD_HAS_DRAFT_ENTRIES)

    period.status = AccountingPeriodStatus.closed
    period.closed_at = datetime.now(UTC)
    period.closed_by_id = actor.id
    await session.flush()
    await session.refresh(period)
    return period, messages.accounting_period_closed(year, month)


async def reopen_period(
    session: AsyncSession, actor: User, year: int, month: int
) -> tuple[AccountingPeriod, str]:
    """`closed → open` — kilit sırası `close` ile BİREBİR AYNIDIR.

        1. KİLİT   — `lock_period`
        2. DURUM   — zaten `open` ise **409** (kaydı hiç olmayan dönem de AÇIKTIR)
        3. DAMGA   — `closed_at`/`closed_by_id` SÖKÜLÜR
        4. REFRESH

    🔴 Damga SÖKÜLMEK ZORUNDADIR: `ck_accounting_periods_closed_stamp`in ters
    yönü `open` bir dönemde damganın NULL olmasını şart koşar. Bırakılsaydı
    yeniden açılmış dönem eski kapatma damgasını taşır ve mali iz YALAN SÖYLERDİ.

    `actor` YAZILMAZ ama parametredir: "kim açtı" sorusunun yeri denetim
    günlüğüdür (B5) — tabloda `reopened_by_id` kolonu AÇILMADI, çünkü üçüncü bir
    durum yoktur ve iki damga taşımak `CLOSED_STAMP_CHECK`in ikili mantığını
    tanımsız kılardı.
    """
    period = await lock_period(session, year, month)

    if period.status is AccountingPeriodStatus.open:
        raise ConflictError(guards.PERIOD_ALREADY_OPEN)

    period.status = AccountingPeriodStatus.open
    period.closed_at = None
    period.closed_by_id = None
    await session.flush()
    await session.refresh(period)
    return period, messages.accounting_period_reopened(year, month)
