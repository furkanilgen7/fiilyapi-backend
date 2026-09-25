"""Gun kancalari (PORT) — cekirdek gunluk/puantaj yazma yollarinin istege bagli modullere sorulari.

PLANLAMA-SPEC §2.7: cekirdek moduller planlamayi IMPORT ETMEZ; ama iki temas kacinilmazdir
(§2, §3.12): rapor onayi o tarihe kadar gunlugu VE puantaji KILITLER (B2-6) ve EV'li
santiyede gunluk "Gonder"i on-kosula baglanir (B2-3, B2-4, B2-8). Bu dosya o iki temasin
SOZLESMESIDIR: cekirdek yalniz buradaki fonksiyonlari cagirir; bir modul (bugun
`earned_value/diary_adapter.py`) uygulamasini `register_*` ile KAYDEDER.

* Kayit YOKSA port bostur → cekirdek bugunku gibi calisir (modulsuz kurulum, §2.7).
* Bagimlilik yonu tek: modul → `app.core.day_hooks`. Bu dosya hicbir urun modulunu
  import etmez.
* Birden cok kayit desteklenir (liste); sira kayit sirasidir.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, DomainError


@dataclass(frozen=True, slots=True)
class SubmitReason:
    """Gonder engeli: YAPISAL `code` (istemci metne bakmaz — EV-BORC-2) + Turkce metin."""

    code: str
    message: str


#: Duz metin donduren (eski) koruyucunun maddesi bu kodla sarilir.
UNSPECIFIED_REASON = "unspecified"


def as_reason(item: str | SubmitReason) -> SubmitReason:
    return item if isinstance(item, SubmitReason) else SubmitReason(UNSPECIFIED_REASON, item)


class DiarySubmitBlockedError(DomainError):
    """EV on-kosulu saglanmadi — 422. `reasons` metinleri (geri uyum) + `items` kodlu."""

    def __init__(self, reasons: list[str | SubmitReason]) -> None:
        self.items = [as_reason(r) for r in reasons]
        self.reasons = [r.message for r in self.items]
        super().__init__("; ".join(self.reasons))


class DaysLockedError(ConflictError):
    """409 + `locked_days` (PLN-B2.x-B, spec §3.14): istemci kilitli gunleri salt okunur
    basabilsin diye yanit KILITLI GUN LISTESINI tasir (`exception_handlers`)."""

    def __init__(self, message: str, locks: list[DayLock]) -> None:
        super().__init__(message)
        self.day_locks = locks
        self.locked_days = [lock.day for lock in locks]


#: Kilitli gun icin kullaniciya gosterilecek metni (kilitliyse) ya da None doner.
DayLockCheck = Callable[[AsyncSession, uuid.UUID, date], Awaitable[str | None]]
#: EV-BORC-4: kilitli gunu KOYAN raporun tarihi (kilitli degilse None) — ekranda
#: "25.09.2026 raporuyla kilitli". Istege bagli; `register_day_lock(check, report_date=…)`.
DayLockReport = Callable[[AsyncSession, uuid.UUID, date], Awaitable[date | None]]


@dataclass(frozen=True, slots=True)
class DayLock:
    """Kilitli gun + onu koyan rapor tarihi (gunler ardisik olmayabilir, farkli raporlara
    bagli olabilir: kilit gun bazinda acilabilir)."""

    day: date
    report_date: date | None


@dataclass(frozen=True, slots=True)
class SubmitContext:
    entry_id: uuid.UUID
    site_id: uuid.UUID
    entry_date: date
    actor_id: uuid.UUID


#: Gonder'i engelleyen nedenlerin listesini doner; bos liste = engel yok. Madde `SubmitReason`
#: (kodlu) ya da duz metin (eski imza; `UNSPECIFIED_REASON` koduyla sarilir).
SubmitGuard = Callable[[AsyncSession, SubmitContext], Awaitable[list[str | SubmitReason]]]

_day_locks: list[DayLockCheck] = []
_submit_guards: list[SubmitGuard] = []
#: kilit kontrolu → rapor tarihi saglayicisi. `registered()`/`restore()` demetine GIRMEZ
#: (2'li demet sozlesmesi korunur); kontrol kaydi geri yuklenince eslesmesi de gecerli olur.
_lock_reports: dict[DayLockCheck, DayLockReport] = {}


def register_day_lock(check: DayLockCheck, *, report_date: DayLockReport | None = None) -> None:
    if check not in _day_locks:
        _day_locks.append(check)
    if report_date is not None:
        _lock_reports[check] = report_date


def register_submit_guard(guard: SubmitGuard) -> None:
    if guard not in _submit_guards:
        _submit_guards.append(guard)


def unregister_all() -> None:
    """Yalniz testler icin: portu bosalt (modulsuz kurulumu taklit)."""
    _day_locks.clear()
    _submit_guards.clear()


def registered() -> tuple[tuple[DayLockCheck, ...], tuple[SubmitGuard, ...]]:
    return tuple(_day_locks), tuple(_submit_guards)


def restore(snapshot: tuple[tuple[DayLockCheck, ...], tuple[SubmitGuard, ...]]) -> None:
    """Yalniz testler icin: `registered()` fotografini GERI yukle. 🔴 `unregister_all()`
    kullanan her fikstur sonunda bunu cagirmali — yoksa ayni isci surecinde sonra kosan
    testler modul kaydini (ör. EV kilidi) kaybeder ve SAHTE-YESIL gecer."""
    _day_locks[:] = list(snapshot[0])
    _submit_guards[:] = list(snapshot[1])


async def assert_days_unlocked(
    session: AsyncSession,
    site_id: uuid.UUID,
    days: Iterable[date],
    *,
    report_days: Iterable[date] | None = None,
) -> None:
    """Gunlerden biri kilitliyse 409 (`DaysLockedError`, durum engeli). Kayit yoksa no-op.

    Yanitin `locked_days`i `report_days` (verilmisse; orn. puantaj haftasinin 7 gunu)
    icindeki, yoksa `days` icindeki kilitli gunlerdir."""
    if not _day_locks:
        return
    for day in sorted(set(days)):
        for check in _day_locks:
            message = await check(session, site_id, day)
            if message:
                scope = days if report_days is None else report_days
                raise DaysLockedError(message, await day_locks(session, site_id, scope))


async def day_locks(
    session: AsyncSession, site_id: uuid.UUID, days: Iterable[date]
) -> list[DayLock]:
    """Kilitli gunler + onlari koyan rapor tarihi (sirali). Ayni `DayLockCheck` kayitlarini
    sorar; kilidi bulan kontrolun rapor saglayicisi yoksa `report_date` None. Kayit YOKSA bos
    liste (modulsuz kurulum)."""
    if not _day_locks:
        return []
    out: list[DayLock] = []
    for day in sorted(set(days)):
        for check in _day_locks:
            if await check(session, site_id, day):
                reporter = _lock_reports.get(check)
                report = await reporter(session, site_id, day) if reporter else None
                out.append(DayLock(day, report))
                break
    return out


async def locked_days(
    session: AsyncSession, site_id: uuid.UUID, days: Iterable[date]
) -> list[date]:
    """Kilitli gunlerin listesi (sirali) — `day_locks`in gun kolonu (PLN-B2.x-B)."""
    return [lock.day for lock in await day_locks(session, site_id, days)]


async def assert_submit_allowed(session: AsyncSession, ctx: SubmitContext) -> None:
    """Gonder on-kosullari; engel varsa 422 `DiarySubmitBlockedError`. Kayit yoksa no-op."""
    reasons: list[str | SubmitReason] = []
    for guard in _submit_guards:
        reasons.extend(await guard(session, ctx))
    if reasons:
        raise DiarySubmitBlockedError(reasons)
