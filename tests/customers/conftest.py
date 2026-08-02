"""P8 T2 — `customers` uçlarının login/yetki fixture'ları.

`tests/contracts/conftest.py` deseninin birebiri: kök `tests/conftest.py`de hazır
başlık fixture'ı YOKTUR, her modül kendi `_login`/`_auth` yardımcısını kurar.

`customers` PROJE-BAĞIMSIZDIR (spec §6) — bu yüzden burada `kisitli_headers`
benzeri bir `user_project_access` fixture'ı YOKTUR ve olmamalıdır: erişim yalnız
`sales` izin seviyesiyle denetlenir.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


async def _login(client: AsyncClient, user_factory, role_key: str, email: str) -> str:
    await user_factory(email=email, password="parola1234", role_key=role_key)
    resp = await client.post("/auth/login", json={"email": email, "password": "parola1234"})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def admin_headers(
    client: AsyncClient, seeded_db: AsyncSession, user_factory
) -> dict[str, str]:
    """`system_admin` — `sales=_A` (yazma dahil her şey)."""
    token = await _login(client, user_factory, "system_admin", "admin@customers.co")
    return _auth(token)


@pytest.fixture
async def view_headers(
    client: AsyncClient, seeded_db: AsyncSession, user_factory
) -> dict[str, str]:
    """`accounting` — `sales=(view, finance)`: okur ama YAZAMAZ (403)."""
    token = await _login(client, user_factory, "accounting", "muhasebe@customers.co")
    return _auth(token)


@pytest.fixture
async def yetkisiz_headers(
    client: AsyncClient, seeded_db: AsyncSession, user_factory
) -> dict[str, str]:
    """`site_chief` — `sales=_N`: her uçta 403."""
    token = await _login(client, user_factory, "site_chief", "sefi@customers.co")
    return _auth(token)
