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


class DiarySubmitBlockedError(DomainError):
    """EV on-kosulu saglanmadi — 422. `reasons` kullaniciya gosterilir (Turkce)."""

    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = reasons


#: Kilitli gun icin kullaniciya gosterilecek metni (kilitliyse) ya da None doner.
DayLockCheck = Callable[[AsyncSession, uuid.UUID, date], Awaitable[str | None]]


@dataclass(frozen=True, slots=True)
class SubmitContext:
    entry_id: uuid.UUID
    site_id: uuid.UUID
    entry_date: date
    actor_id: uuid.UUID


#: Gonder'i engelleyen nedenlerin listesini doner; bos liste = engel yok.
SubmitGuard = Callable[[AsyncSession, SubmitContext], Awaitable[list[str]]]

_day_locks: list[DayLockCheck] = []
_submit_guards: list[SubmitGuard] = []


def register_day_lock(check: DayLockCheck) -> None:
    if check not in _day_locks:
        _day_locks.append(check)


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
    session: AsyncSession, site_id: uuid.UUID, days: Iterable[date]
) -> None:
    """Gunlerden biri kilitliyse 409 (`ConflictError`, durum engeli). Kayit yoksa no-op."""
    if not _day_locks:
        return
    for day in sorted(set(days)):
        for check in _day_locks:
            message = await check(session, site_id, day)
            if message:
                raise ConflictError(message)


async def assert_submit_allowed(session: AsyncSession, ctx: SubmitContext) -> None:
    """Gonder on-kosullari; engel varsa 422 `DiarySubmitBlockedError`. Kayit yoksa no-op."""
    reasons: list[str] = []
    for guard in _submit_guards:
        reasons.extend(await guard(session, ctx))
    if reasons:
        raise DiarySubmitBlockedError(reasons)
