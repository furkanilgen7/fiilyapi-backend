"""PLN-B2.1 — gün kancası (PORT) test ikizi: sahte kilit + sahte Gönder koruyucusu.

🔴 Port süreç-genelidir ve EV modülü router importuyla GERÇEK kaydını yapar
(`earned_value/diary_adapter.py`). Bu fikstür portu BİLİNÇLİ boşaltır, sahte
kaydı kurar ve sonda ESKİ fotoğrafı GERİ YÜKLER (`day_hooks.restore`) — geri
yüklenmeseydi aynı işçide sonra koşan testler EV kaydını kaybeder, sahte-yeşil
doğardı. Kayıt yapılmazsa fikstür "modülsüz kurulum"dur (port boş).

`tests/site_diary/conftest.py` ve `tests/timesheet/conftest.py` bunu yeniden
dışa verir; iki paket AYNI ikizi kullanır.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import day_hooks

KILIT_METNI = "Bu gün rapor onayıyla kilitli (test)"


@dataclass
class SahtePort:
    """Kilitli (şantiye, gün) kümesi + sorulan günlerin kaydı + Gönder engelleri."""

    kilitli: set[tuple[uuid.UUID, date]] = field(default_factory=set)
    sorulan: list[tuple[uuid.UUID, date]] = field(default_factory=list)
    engeller: list[str] = field(default_factory=list)
    gonder_baglamlari: list[day_hooks.SubmitContext] = field(default_factory=list)

    async def _kilit(self, session: AsyncSession, site_id: uuid.UUID, day: date) -> str | None:
        self.sorulan.append((site_id, day))
        return KILIT_METNI if (site_id, day) in self.kilitli else None

    async def _koruyucu(self, session: AsyncSession, ctx: day_hooks.SubmitContext) -> list[str]:
        self.gonder_baglamlari.append(ctx)
        return list(self.engeller)

    def kilitle(self, site_id: uuid.UUID, day: date) -> None:
        self.kilitli.add((site_id, day))
        day_hooks.register_day_lock(self._kilit)

    def engelle(self, *reasons: str) -> None:
        self.engeller.extend(reasons)
        day_hooks.register_submit_guard(self._koruyucu)

    def dinle(self) -> None:
        """Kilit/engel YOK ama port kayıtlı: sorulan günleri ve bağlamı kaydeder."""
        day_hooks.register_day_lock(self._kilit)
        day_hooks.register_submit_guard(self._koruyucu)

    def sorulan_gunler(self) -> set[date]:
        return {day for _, day in self.sorulan}


@pytest.fixture
def port() -> Iterator[SahtePort]:
    onceki = day_hooks.registered()
    day_hooks.unregister_all()
    try:
        yield SahtePort()
    finally:
        day_hooks.restore(onceki)
