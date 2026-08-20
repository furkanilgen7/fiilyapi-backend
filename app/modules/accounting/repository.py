"""Muhasebe veri erişimi (MU-1 T3a) — yalnız SQL, karar yok.

`treasury/repository.py` deseninin kardeşi. İki farkı vardır ve ikisi de
bilinçlidir:

🔴 **KAPSAM SÜZGECİ YOKTUR (spec §3).** Hesap planı ŞİRKET GENELİ bir katalogtur:
`chart_of_accounts` tablosunda `project_id`/`site_id` kolonu yoktur ve HP'nin
beş sütununda hiçbir proje/şantiye alanı çizilmemiştir. `suppliers`/`stock_items`
emsali; erişim `accounting` izin modülüyle denetlenir, **IDOR unutulmuş
DEĞİLDİR, yapısal olarak yoktur**. Buraya `project_ids` parametresi eklemek
olmayan bir süzgeci varmış gibi gösterirdi.

🔴 **BAKİYE BURADA HESAPLANMAZ.** Liste `balance.select_accounts_with_balance()`
üzerine yalnız SÜZGEÇ/SIRA/SAYFA ekler; ikinci bir formül yazılsaydı liste ile
detay aynı hesap için farklı sayı basar ve bakiye saklanmadığı için hiçbir kolon
farkı ele vermezdi.

## Hiyerarşi sorgusu

`parent_id` FK YOKTUR (K4): alt hesaplar KODUN ÖNEKİYLE bulunur
(`codes.child_prefix`). Önek torunları da kapsar — çocuğu silinmiş ama torunu
duran bir grup "yaprak" sanılmamalıdır.

## N+1

Liste ucu hesap sayısından BAĞIMSIZ olarak iki sorgu koşar (satırlar + sayım).
`test_liste_N_ARTI_1_YAPMAZ` bunu `before_cursor_execute` sayacıyla ÖLÇER.
"""

import uuid
from collections.abc import Iterable, Sequence
from decimal import Decimal

from sqlalchemy import Select, delete, func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounting import codes
from app.modules.accounting.balance import select_accounts_with_balance
from app.modules.accounting.models import (
    AccountingPeriod,
    ChartAccount,
    ChartAccountType,
    JournalEntry,
    JournalEntryStatus,
    JournalLine,
)
from app.modules.users.models import User

__all__ = [
    "accounts_by_ids",
    "code_exists",
    "count_accounts",
    "count_entries",
    "count_entries_by_period",
    "count_journal_lines_for_account",
    "count_periods",
    "delete_lines",
    "get_account",
    "get_account_by_code",
    "get_entry",
    "has_child_accounts",
    "has_draft_entries",
    "list_accounts_with_balance",
    "list_entries",
    "list_periods",
    "load_lines",
    "load_lines_with_accounts",
    "reversal_exists",
]

_LIKE_ESCAPE = "\\"


def _like_escape(deger: str) -> str:
    """LIKE joker karakterlerini KAÇIRIR (`invoicing.repository` deseni).

    🔴 R15: kaçırılmazsa arama kutusuna `%` yazan kullanıcı TÜM hesapları, `_`
    yazan ise beklemediği satırları görür. **Kaçış karakterinin kendisi ÖNCE
    kaçırılır** — sonra kaçırılsaydı sonradan eklenen ters bölüler de ikinci
    turda çiftlenirdi.
    """
    return deger.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _filtered(
    stmt: Select,
    *,
    q: str | None,
    account_type: ChartAccountType | None,
    is_active: bool | None,
) -> Select:
    """HP filtre çubuğu (spec §7). Süzgeçler AND'lidir.

    `q` KOD ve AD üzerinde kısmi arar (HP:47 tek kutudur): yalnız adda arasaydı
    kod yazan kullanıcı "hesap yok" sanısına düşerdi.

    🔴 `account_type` (HP:60 `Tür`) ile `is_active` (HP:62 `Durum`) AYRI
    süzgeçlerdir ve birbirinin yerine GEÇMEZ (R3) — ikisi de Türkçe'de "aktif"
    okunur ama biri dört üyeli enum, öteki boolean bir kaldırma bayrağıdır.

    Liste ve sayım AYNI yardımcıdan geçer: kopya açılsaydı `total` ile gösterilen
    tablo zamanla ayrışır ve hesaplar "sayfa dışında kalmış" gibi görünürdü.
    """
    if account_type is not None:
        stmt = stmt.where(ChartAccount.account_type == account_type)
    if is_active is not None:
        stmt = stmt.where(ChartAccount.is_active == is_active)
    if q:
        desen = f"%{_like_escape(q)}%"
        stmt = stmt.where(
            ChartAccount.code.ilike(desen, escape=_LIKE_ESCAPE)
            | ChartAccount.name.ilike(desen, escape=_LIKE_ESCAPE)
        )
    return stmt


async def list_accounts_with_balance(
    session: AsyncSession,
    *,
    q: str | None,
    account_type: ChartAccountType | None,
    is_active: bool | None,
    limit: int,
    offset: int,
) -> list[tuple[ChartAccount, Decimal]]:
    """Satır + TÜRETİLMİŞ bakiye, hesap sayısından bağımsız TEK sorguda.

    Sıralama `code ASC`tir (spec §7) ve hiyerarşiyi KENDİLİĞİNDEN üretir: metin
    sırası `10` · `100` · `12` · `120` · `120.01` verir, yani HP'nin grup-altı
    yerleşimi ikinci bir "ağaç kurma" adımı olmadan çıkar. Kod TEKİL olduğu için
    ikinci bir sıralama ölçütü GEREKMEZ — sayfalar arasında satır kaybolup
    tekrarlayamaz.
    """
    stmt = _filtered(
        select_accounts_with_balance(), q=q, account_type=account_type, is_active=is_active
    )
    stmt = stmt.order_by(ChartAccount.code).limit(limit).offset(offset)
    return [(account, bakiye) for account, bakiye in (await session.execute(stmt)).all()]


async def count_accounts(
    session: AsyncSession,
    *,
    q: str | None,
    account_type: ChartAccountType | None,
    is_active: bool | None,
) -> int:
    """Sayım liste ile AYNI süzgeçten geçer — `total` tabloyla ayrışmasın."""
    stmt = _filtered(
        select(func.count()).select_from(ChartAccount),
        q=q,
        account_type=account_type,
        is_active=is_active,
    )
    return (await session.execute(stmt)).scalar_one()


async def get_account(
    session: AsyncSession, account_id: uuid.UUID, *, for_update: bool = False
) -> ChartAccount | None:
    """Tekil okuma; `for_update` satırı KİLİTLER.

    `populate_existing` ŞARTTIR: kimlik haritası bayat bir nesne taşıyorsa
    `session.get` onu SORGUSUZ döndürür ve kilit HİÇ ALINMAZ — TOCTOU penceresi
    sessizce açık kalırdı (`invoicing.get_invoice` dersi).
    """
    if not for_update:
        return await session.get(ChartAccount, account_id)
    return await session.get(ChartAccount, account_id, with_for_update=True, populate_existing=True)


async def get_account_by_code(session: AsyncSession, code: str) -> ChartAccount | None:
    """Koddan hesap — K-Ş3 kapısının (ebeveyn arama) tek yolu.

    Ebeveynin KAYDI olmayabilir (`NNN.NN` alt hesap `e5f6a7b8c9d0` tohumunda
    hiç yazılmaz, K2; ya da kullanıcı ana hesabı silmiş/hiç migrate etmemiş
    olabilir, R14): `None` bir hata değildir, "kapı ısırmaz" demektir.
    """
    stmt = select(ChartAccount).where(ChartAccount.code == code)
    return (await session.execute(stmt)).scalar_one_or_none()


async def code_exists(
    session: AsyncSession, code: str, *, exclude_id: uuid.UUID | None = None
) -> bool:
    """`uq_chart_of_accounts_code` ön denetimi (R16).

    `exclude_id` PATCH içindir: kaydın kendisi dışlanmasaydı kullanıcı yalnızca
    adı düzeltirken formun geri gönderdiği kendi kodu yüzünden 409 alırdı.
    """
    stmt = select(func.count()).select_from(ChartAccount).where(ChartAccount.code == code)
    if exclude_id is not None:
        stmt = stmt.where(ChartAccount.id != exclude_id)
    return bool((await session.execute(stmt)).scalar_one())


async def has_child_accounts(session: AsyncSession, code: str) -> bool:
    """Hesabın ALTINDA (çocuk ya da TORUN) kayıt var mı? — K4 hiyerarşisi.

    `parent_id` FK olmadığı için sorgu ÖNEK üzerindedir (`codes.child_prefix`).
    En alt düzeyde önek `None`dır ve hiç sorgu koşulmaz: `NNN.NN` altına bir şey
    açılamaz (üçüncü kırılım yoktur).

    Kendisi DIŞLANIR — dışlanmasaydı her hesap kendi çocuğu sayılır ve hiçbir
    hesap ne silinebilir ne de yaprak olabilirdi.
    """
    onek = codes.child_prefix(code)
    if onek is None:
        return False
    desen = f"{_like_escape(onek)}%"
    stmt = (
        select(func.count())
        .select_from(ChartAccount)
        .where(
            ChartAccount.code.like(desen, escape=_LIKE_ESCAPE),
            ChartAccount.code != code,
        )
    )
    return bool((await session.execute(stmt)).scalar_one())


async def count_journal_lines_for_account(session: AsyncSession, account_id: uuid.UUID) -> int:
    """Hesaba kesilmiş fiş satırı sayısı — ÜÇ kapının ortak ölçütü.

    Kullanıcıları: DELETE'in 409'u (FK RESTRICT'in servis karşılığı) · `code`
    değişiminin 409'u · K-Ş3'ün ebeveyn denetimi.

    🔴 DURUM SÜZGECİ YOKTUR ve olmamalıdır: `draft` bir fiş bakiyeye girmese de
    (K3) o hesaba BAĞLIDIR. Süzgeç konsaydı taslak satırı olan bir hesap
    silinebilir, FK RESTRICT ham bir 500 üretir ve kullanıcı ayrımsız bir hata
    alırdı.
    """
    stmt = select(func.count()).select_from(JournalLine).where(JournalLine.account_id == account_id)
    return (await session.execute(stmt)).scalar_one()


# --------------------------------------------------------------------------- #
# T3b — YEVMİYE (spec §7 yolları 6-14)
#
# 🔴 Burada da KAPSAM SÜZGECİ YOKTUR ve aynı sebeple (spec §3): `journal_entries`
# tablosunda `project_id`/`site_id` kolonu yoktur, E8'in altı sütununda hiçbir
# proje/şantiye alanı çizilmemiştir. Erişimi `accounting` izni denetler.
#
# 🔴 KİLİT SIRASI uçtan uca SABİTTİR: **fiş → satırlar → hesap**. Bu dosyadaki
# sorgular o sırayı bozacak bir kilit almaz; ters sırada kilitleyen bir yol
# eklenirse karşılıklı kilitlenme (deadlock) doğar.
# --------------------------------------------------------------------------- #


async def get_entry(
    session: AsyncSession, entry_id: uuid.UUID, *, for_update: bool = False
) -> JournalEntry | None:
    """Tekil okuma; `for_update` satırı KİLİTLER (EŞİK = KİLİT'in 1. adımı).

    🔴 `populate_existing` ŞARTTIR: kimlik haritası bayat bir nesne taşıyorsa
    `session.get` onu SORGUSUZ döndürür ve **kilit HİÇ ALINMAZ** — TOCTOU
    penceresi sessizce açık kalırdı (`invoicing.get_invoice` dersi). Kilidin
    kendisi de OKUMADA alınır: `UPDATE`in örtük satır kilidi yazma ANINDA, yani
    kararın çok geç bir noktasında alınır ve iki eşzamanlı `post` da aynı
    `draft`ı okurdu.
    """
    if not for_update:
        return await session.get(JournalEntry, entry_id)
    return await session.get(JournalEntry, entry_id, with_for_update=True, populate_existing=True)


def _entry_filtered(
    stmt: Select,
    *,
    status: JournalEntryStatus | None,
    year: int | None,
    month: int | None,
) -> Select:
    """Fiş listesinin süzgeçleri — liste ve sayım AYNI yardımcıdan geçer.

    Kopya açılsaydı `total` ile gösterilen tablo zamanla ayrışır ve fişler
    "sayfa dışında kalmış" gibi görünürdü.
    """
    if status is not None:
        stmt = stmt.where(JournalEntry.status == status)
    if year is not None:
        stmt = stmt.where(JournalEntry.period_year == year)
    if month is not None:
        stmt = stmt.where(JournalEntry.period_month == month)
    return stmt


async def list_entries(
    session: AsyncSession,
    *,
    status: JournalEntryStatus | None,
    year: int | None,
    month: int | None,
    limit: int,
    offset: int,
) -> list[JournalEntry]:
    """Fiş başlıkları — 🔴 sıralamanın son parçası `id`dir.

    `entry_date DESC` tek başına belirleyici DEĞİLDİR: aynı gün girilen iki fiş
    keyfî sırada dönerdi ve sayfalama satır tekrarlar/atlardı (R8'in liste
    ucundaki izdüşümü). `created_at` de tek başına yetmez — `func.now()` işlem
    başına SABİTTİR, aynı işlemde yazılan fişlerin damgası EŞİTTİR.
    """
    stmt = _entry_filtered(select(JournalEntry), status=status, year=year, month=month)
    stmt = (
        stmt.order_by(
            JournalEntry.entry_date.desc(),
            JournalEntry.created_at.desc(),
            JournalEntry.id.desc(),
        )
        .limit(limit)
        .offset(offset)
    )
    return list((await session.execute(stmt)).scalars().all())


async def count_entries(
    session: AsyncSession,
    *,
    status: JournalEntryStatus | None,
    year: int | None,
    month: int | None,
) -> int:
    stmt = _entry_filtered(
        select(func.count()).select_from(JournalEntry), status=status, year=year, month=month
    )
    return (await session.execute(stmt)).scalar_one()


async def load_lines(session: AsyncSession, entry_id: uuid.UUID) -> list[JournalLine]:
    """Fişin bacakları, `sort_order` ASC — gövdedeki dizinin AYNISI.

    Son ölçüt `id`dir: `sort_order` NOT NULL ve sunucu tarafından yazılıyor olsa
    da, iki satırın aynı sırayı taşıdığı bir gün gelirse sıra keyfî olmamalıdır.
    """
    stmt = (
        select(JournalLine)
        .where(JournalLine.entry_id == entry_id)
        .order_by(JournalLine.sort_order, JournalLine.id)
    )
    return list((await session.execute(stmt)).scalars().all())


async def load_lines_with_accounts(
    session: AsyncSession, entry_id: uuid.UUID
) -> list[tuple[JournalLine, ChartAccount]]:
    """Bacak + hesabı **TEK** sorguda (N+1 yasağı).

    Satır başına hesap çekilseydi iki bacaklı bir fişte fark edilmez, elli
    bacaklı bir bordro fişinde patlardı. `join` INNER'dır ve öyle kalır:
    `account_id` NOT NULL + RESTRICT FK olduğu için hesapsız satır YAPISAL
    OLARAK imkânsızdır.
    """
    stmt = (
        select(JournalLine, ChartAccount)
        .join(ChartAccount, ChartAccount.id == JournalLine.account_id)
        .where(JournalLine.entry_id == entry_id)
        .order_by(JournalLine.sort_order, JournalLine.id)
    )
    return [(satir, hesap) for satir, hesap in (await session.execute(stmt)).all()]


async def delete_lines(session: AsyncSession, entry_id: uuid.UUID) -> None:
    """Bacakları toptan siler (`PUT lines` ve DELETE'in ilk adımı).

    DB'de CASCADE de vardır; açık silme KİLİT SIRASINI (fiş → satırlar) uçtan
    uca sabit tutmak içindir.
    """
    await session.execute(delete(JournalLine).where(JournalLine.entry_id == entry_id))


async def accounts_by_ids(
    session: AsyncSession, account_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, ChartAccount]:
    """Gövdedeki hesap referanslarını **TEK** sorguda çözer.

    Bulunamayan kimlik sözlükte YER ALMAZ; çağıran 404'ü kendi verir (🔴 ST
    kanonu: gövde içi varlık referansı 404'tür). Boş listede hiç sorgu koşmaz.
    """
    if not account_ids:
        return {}
    stmt = select(ChartAccount).where(ChartAccount.id.in_(set(account_ids)))
    return {hesap.id: hesap for hesap in (await session.execute(stmt)).scalars().all()}


async def reversal_exists(session: AsyncSession, entry_id: uuid.UUID) -> bool:
    """Fişin stornosu VAR MI — `uq_journal_entries_reversal_of`un ön denetimi.

    Sorgu UNIQUE'e DÜŞMEDEN önce koşar ki kullanıcı ayrımsız bir "Veri bütünlüğü
    hatası" yerine Türkçe bir sebep alsın (R16 deseninin storno karşılığı). UQ
    yarış durumu emniyet ağı olarak KALIR; kilit (`get_entry(for_update=True)`)
    zaten aynı fiş üzerinde iki eşzamanlı stornoyu sıraya sokar.
    """
    stmt = (
        select(func.count())
        .select_from(JournalEntry)
        .where(JournalEntry.reversal_of_id == entry_id)
    )
    return bool((await session.execute(stmt)).scalar_one())


# --------------------------------------------------------------------------- #
# MU-2 T3 — `accounting_periods`
# --------------------------------------------------------------------------- #


async def has_draft_entries(session: AsyncSession, year: int, month: int) -> bool:
    """Dönemde `draft` fiş VAR MI — kapanışın 3. adımı.

    Süzgeç `(period_year, period_month)`tir, `entry_date` DEĞİL: ikisi
    `ck_journal_entries_period_matches_date` ile kilitlidir ama dönem kolonları
    `ix_journal_entries_period` indeksini kullanır ve mizanın (T4) okuyacağı
    kolonların AYNISIDIR — iki farklı yerden iki farklı dönem tanımı okumak
    kapanışı ile mizanı ayrıştırırdı.

    🔴 Yalnız `draft` sayılır. `posted`/`reversed` fiş kapanışı ENGELLEMEZ:
    kapanışın amacı tam olarak onları DONDURMAKTIR (gerekçe `guards.py`).
    """
    stmt = (
        select(func.count())
        .select_from(JournalEntry)
        .where(
            JournalEntry.period_year == year,
            JournalEntry.period_month == month,
            JournalEntry.status == JournalEntryStatus.draft,
        )
    )
    return bool((await session.execute(stmt)).scalar_one())


def _period_filtered(stmt: Select, *, year: int | None) -> Select:
    """Dönem listesinin TEK süzgeci — liste ve sayım aynı yardımcıdan geçer
    (`_entry_filtered` deseni). Kopya açılsaydı `total` ile tablo ayrışırdı."""
    if year is not None:
        stmt = stmt.where(AccountingPeriod.year == year)
    return stmt


async def list_periods(
    session: AsyncSession, *, year: int | None, limit: int, offset: int
) -> list[tuple[AccountingPeriod, str | None]]:
    """Dönemler + kapatan adı — 🔴 `year DESC, month DESC` (en yeni başta).

    Yön fiş listesinin `entry_date DESC` kanonuyla AYNIDIR: kullanıcının ilgisi
    daima en son döneme yakındır ve artan sıra, on yıl sonra ekranın ilk
    sayfasını 2026'da bırakırdı.

    Sıralama BELİRLEYİCİDİR ve son ölçüte ihtiyaç DUYMAZ: `(year, month)`
    `uq_accounting_periods_year_month` ile TEKİLDİR, dolayısıyla iki satır aynı
    anahtarı taşıyamaz ve sayfalama satır tekrarlayamaz/atlayamaz.

    🔴 **DKAP-B / K1 + K5:** `closed_by_name` `outerjoin(User, ...)` ile AYNI
    sorguda gelir — `audit/repository.py`nin "aktör outerjoin ile aynı sorguda
    gelir, N+1 YOK" deseninin birebir kopyasıdır. `AccountingPeriod` modelinde
    `closed_by_id` için bir `relationship()` TANIMLI DEĞİLDİR (`models.py`),
    yani burada `lazy="selectin"` gibi bir ön-yükleme kanonu YAPISAL OLARAK
    MÜMKÜN DEĞİLDİR — sayaç bu ekranda kör kalamaz.
    """
    stmt = _period_filtered(
        select(AccountingPeriod, User.full_name).outerjoin(
            User, AccountingPeriod.closed_by_id == User.id
        ),
        year=year,
    )
    stmt = (
        stmt.order_by(AccountingPeriod.year.desc(), AccountingPeriod.month.desc())
        .limit(limit)
        .offset(offset)
    )
    return [(row[0], row[1]) for row in (await session.execute(stmt)).all()]


async def count_periods(session: AsyncSession, *, year: int | None) -> int:
    stmt = _period_filtered(select(func.count()).select_from(AccountingPeriod), year=year)
    return (await session.execute(stmt)).scalar_one()


async def count_entries_by_period(
    session: AsyncSession, periods: Iterable[tuple[int, int]]
) -> dict[tuple[int, int], tuple[int, int]]:
    """🔴 DKAP-B / K1 — sayfadaki dönemlerin fiş sayılarını TEK sorguda toplu
    döner (`GROUP BY`); dönem başına ayrı sorgu YOKTUR. Değer `(toplam,
    draft_sayisi)` çiftidir — `draft_sayisi` `count(*) FILTER (WHERE
    status = 'draft')` ile AYNI sorguda gelir, İKİNCİ bir sorgu AÇILMAZ.

    🔴 DKAP-B / K9 — bu ekranda İKİ AYRI kapı vardır, KARIŞTIRILMAMALIDIR:

    1. **Kapalı döneme YAZMA yasağı** (`periods_service.assert_periods_open`,
       `status is closed` kontrolü) — STATÜ AYRIMI YAPMAZ, kapalı dönem
       `draft`/`posted`/`reversed` fark etmeksizin HER yazmayı reddeder.
    2. **Kapanışın ÖN KOŞULU** (`has_draft_entries`, bu dosyada yukarıda) —
       STATÜ AYRIMI YAPAR: yalnız `draft` fiş kapanışı ENGELLER, `posted`/
       `reversed` engellemez.

    Toplam (`entry_count`) 1. kapının kümesine bakar — kapalı dönemde zaten
    `draft` KALMAZ, dolayısıyla toplamda statü ayrımına gerek YOKTUR ve
    mockup'ın "Fiş" sütunu (defter hacmi) budur. Ama toplam TEK BAŞINA 2.
    kapıyı yansıtmaz: 10 `posted` + 1 `draft` fişli bir dönem "11 fiş" basar
    ama `has_draft_entries` yüzünden KAPATILAMAZ — kullanıcı bu ikisini
    bağdaştıramaz. `draft_sayisi` tam olarak bu ayrımı taşır: ekran
    `draft_sayisi > 0` ile "kapatılamaz" durumunu OLGUDAN türetebilir
    (kapanabilirlik KARARININ kendisi burada TAŞINMAZ — o karar
    `periods_service`in kapısıdır, bkz. `AccountingPeriodListItem` docstring'i).

    Boş küme (sayfa boşsa) sorgusuz `{}` döner — `tuple_(...).in_(())` boş
    IN'de PG'de sözdizimi hatası fırlatır, bu yüzden erken çıkış ŞARTTIR.
    """
    pairs = list(dict.fromkeys(periods))
    if not pairs:
        return {}
    stmt = (
        select(
            JournalEntry.period_year,
            JournalEntry.period_month,
            func.count(),
            func.count().filter(JournalEntry.status == JournalEntryStatus.draft),
        )
        .where(tuple_(JournalEntry.period_year, JournalEntry.period_month).in_(pairs))
        .group_by(JournalEntry.period_year, JournalEntry.period_month)
    )
    rows = (await session.execute(stmt)).all()
    return {(yil, ay): (toplam, taslak) for yil, ay, toplam, taslak in rows}
