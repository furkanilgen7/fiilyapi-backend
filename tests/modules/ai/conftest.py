"""AI-0b bekçilerinin ortak koşum takımı.

🔴 **Bekçi, ölçtüğü yolu KENDİSİ KURMAZ** (AI-0a'nın en pahalı dersi). Burada
kurulan tek şey `get_db` override'ıdır — o da testin *veritabanı* bağlantısını
işçi oturumuna yöneltmek için, rotaları değil. Rotalar `build_read_plane`in
kendi kurduğu rotalardır; bir mutant `include_router` yerine düz `append`
yaparsa bu takım onu **görür**.

⚠️ `build_read_plane` üretimde `dependency_overrides == {get_db:
get_ai_readonly_db}` bırakır ve `test_ai0a_read_plane.py::test_B5_...` bunu
**dict eşitliğiyle** kilitler. Burada override edilen sözlük, `build_read_plane`
çağrısının DÖNDÜRDÜĞÜ örneğe aittir; üretim davranışı değişmez ve B5 yeşil kalır.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import AccessLevel
from app.core.db import get_db
from app.core.security import create_access_token
from app.main import app as ana_app
from app.modules.ai.actor import aktor_baglami
from app.modules.ai.readplane import build_read_plane
from app.modules.ai.registry import ActorContext
from app.modules.ai.transport import ReadOnlyTransport
from app.modules.users.models import User


@pytest.fixture
def okuma_duzlemi(db_session: AsyncSession):
    """Test oturumuna bağlı okuma düzlemi."""

    async def _get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    duzlem = build_read_plane(ana_app)
    duzlem.dependency_overrides[get_db] = _get_db
    return duzlem


@pytest.fixture
def transport_factory(okuma_duzlemi):
    """Bir kullanıcı için `ReadOnlyTransport` üretir (kendi bearer'ıyla, T1)."""
    kapatilacaklar: list[httpx.AsyncClient] = []

    def _yap(user: User | None = None, *, bearer: str | None = None) -> ReadOnlyTransport:
        if bearer is None:
            assert user is not None
            bearer = create_access_token(user.id, user.token_version)
        istemci = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=okuma_duzlemi, raise_app_exceptions=True),
            base_url="http://okuma",
        )
        kapatilacaklar.append(istemci)
        return ReadOnlyTransport(istemci, bearer=bearer)

    yield _yap
    for istemci in kapatilacaklar:
        # `aclose` beklenmez: ASGI taşıyıcısının kapatacak soketi yoktur.
        istemci.is_closed  # noqa: B018


@pytest.fixture
def actor_factory(seeded_db: AsyncSession):
    async def _yap(user: User) -> ActorContext:
        return await aktor_baglami(seeded_db, user)

    return _yap


def sahte_aktor(
    permissions: dict[str, AccessLevel],
    *,
    role_key: str = "site_chief",
    role_is_system: bool = False,
) -> ActorContext:
    """DB'ye dokunmayan aktör — katalog/prompt iddiaları için."""
    return ActorContext(
        user_id=uuid.uuid4(),
        role_key=role_key,
        role_is_system=role_is_system,
        permissions=permissions,
    )


#: Her modülde `view` — "hiçbir kapı kapalı değil" tabanı.
def tam_izin(seviye: AccessLevel = AccessLevel.view) -> dict[str, AccessLevel]:
    from app.modules.roles.seed_data import MATRIX

    return {modul: seviye for modul in MATRIX}
