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
    AccountingPeriodListItem,
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
    "previous_period",
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


def previous_period(year: int, month: int) -> Period:
    """🔴 K1 — TAKVİM olarak bir önceki ay; Ocak'ın öncesi ÖNCEKİ YILIN ARALIĞI.

    `(year, month - 1)` diye yazılsaydı Ocak için `(year, 0)` üretirdi; öyle bir
    dönem hiçbir zaman kaydedilmediği için sıra denetimi her 1 Ocak'ta SESSİZCE
    geçer ve Aralık sonsuza dek açık kalabilirdi. Kural yıl sınırında kopmaz.
    """
    return (year - 1, 12) if month == 1 else (year, month - 1)


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
    """K7 zarfı. `total` liste ile AYNI süzgeçten geçer (`_period_filtered`).

    🔴 DKAP-B / K1: sayfa BAŞINA tam olarak İKİ ek sorgu koşar —
    `repository.list_periods` (dönem + `closed_by_name`, outerjoin ile TEK
    sorgu) ve `repository.count_entries_by_period` (sayfadaki dönemlerin
    toplam + `draft` fiş sayısı, TEK `GROUP BY` sorgusunda `FILTER` ile
    birlikte gelir — K8, ikinci bir sorgu AÇILMAZ). İkisi de sayfa
    büyüklüğünden BAĞIMSIZ çalışır; döngü içinde `await` YOKTUR — yapısal
    N+1 garantisi budur.
    """
    satirlar = await repository.list_periods(session, year=year, limit=limit, offset=offset)
    sayilar = await repository.count_entries_by_period(
        session, ((donem.year, donem.month) for donem, _ in satirlar)
    )
    return AccountingPeriodListResponse(
        items=[
            AccountingPeriodListItem(
                **AccountingPeriodResponse.model_validate(donem).model_dump(),
                entry_count=sayilar.get((donem.year, donem.month), (0, 0))[0],
                draft_count=sayilar.get((donem.year, donem.month), (0, 0))[1],
                closed_by_name=ad,
            )
            for donem, ad in satirlar
        ],
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
        4. SIRA    — 🔴 SIRA-B: önceki dönem KAYITLI ve `open` ise **409**
        5. DAMGA   — `status` + `closed_at` + `closed_by_id` BİRLİKTE
        6. REFRESH — `updated_at` sunucu damgasıdır

    ## 🔴 4. adım — KRONOLOJİK SIRA (SIRA-B, kullanıcı kararı)

    Kapanış defterin bir noktasına "buraya kadar kesin" der. Temmuz açıkken
    Ağustos kapatılabilseydi bu cümle YALAN olurdu: Ağustos donmuşken Temmuz'a
    fiş girilmeye devam eder ve mizan/bilanço hangi aya kadar kesin olduğunu
    söyleyemezdi. Bu yüzden kapanış eskiden yeniye YÜRÜR.

    **Önceki dönem TAKVİM ayıdır** (`previous_period`, K1) — yıl sınırında
    kopmaz.

    **Kaydı olmayan önceki ay ENGEL DEĞİLDİR** (K2). `accounting_periods`
    satırının doğduğu TEK yer `lock_period`tir; o da yalnız bir yazma ya da
    kapatma isteğiyle koşar. Yani "satır yok" = *o ayda hiç iş olmamış*, "açık"
    DEĞİL. Engel sayılsaydı sistemin İLK kapanışı hiçbir zaman yapılamazdı:
    her ayın öncesinde sonsuza kadar kayıtsız aylar vardır. Doğal sonucu K3'tür
    — sistemdeki EN ESKİ dönem her zaman kapatılabilir.

    Denetim önceki dönemi **KİLİTLEMEZ** (`repository.get_period`, `FOR UPDATE`
    yok): burada bir eşik/sayaç yarışı yoktur — okunan şey komşu satırın
    DURUMUDUR ve o durumu yazan iki yol (`close`/`reopen`) kendi satırını zaten
    kilitler.

    🔴 **İki eşzamanlı kapatma ÖLÇÜLDÜ** (`test_mu2_periods_lock.py`, test 4):
    Temmuz + Ağustos aynı anda kapatılmak istendiğinde sonuç deterministik
    olarak *"Temmuz kapandı, Ağustos 409"*tur — Ağustos'u kapatan işlem,
    Temmuz'un henüz commit edilmemiş damgasını READ COMMITTED altında GÖREMEZ
    ve Temmuz'u `open` okur. Yani kilitsiz okuma MUHAFAZAKÂR yönde yanılır.
    Temmuz KAYITSIZ olsaydı ikisi de geçerdi, ki o da kronolojik olarak
    GEÇERLİ bir son durumdur ("ikisi de kapalı").

    Korunan şey bir eşik değil bir SON DURUM invaryantıdır: *"kapalı bir
    dönemin takvim öncesi, KAYITLI ve `open` olamaz"*. İki `close` bunu
    bozamaz. Bozan tek desen eşzamanlı `reopen(AY-1)` + `close(AY)`tir
    (test 5) — ve o, K5'in KENDİSİDİR: aynı son duruma sırayla da ulaşılır ve
    bu MEŞRUDUR. Kilidi genişletmek (önceki dönemi de kilitlemek) SABİT kilit
    sırasına yeni bir kenar ekler ve hiçbir invaryant KAZANDIRMAZ.

    🔴 Sıra denetimi taslak denetiminden SONRA koşar: iki engel birden varken
    kullanıcı ÖNCE kendi dönemindeki eksiği duyar (daha yakın iş), sonra
    komşusunun durumunu.

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
    onceki_yil, onceki_ay = previous_period(year, month)
    onceki = await repository.get_period(session, onceki_yil, onceki_ay)
    if onceki is not None and onceki.status is AccountingPeriodStatus.open:
        raise ConflictError(guards.period_previous_open(onceki_yil, onceki_ay))

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

    🔴 **SIRA-B: kronolojik sıra kuralı BURAYA GİRMEZ** (K5). `close` eskiden
    yeniye yürür; geri açma bunun simetriği DEĞİLDİR. "Ağustos kapalıyken
    Temmuz'u geri aç" tam olarak meşru düzeltme yoludur: Temmuz'da yanlış bir
    fiş bulunduğunda düzeltilecek yer Temmuz'dur. Buraya "önce sonrakini aç"
    kuralı konsaydı yönetici, tek bir ayı düzeltmek için kapanmış TÜM sonraki
    ayları geri açmak zorunda kalır — mali izi düzeltme adına daha da çok geri
    sarardı. Uç zaten `admin`dedir; kapı YETKİDEDİR, sırada değil.

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
