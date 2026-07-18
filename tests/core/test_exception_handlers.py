import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.errors import DomainError, PermissionLockedError
from app.core.exception_handlers import register_exception_handlers


@pytest.fixture
def handler_app():
    """DomainError alt sınıflarını fırlatan iki uçlu, korkuluklu bir test uygulaması."""
    test_app = FastAPI()
    register_exception_handlers(test_app)

    @test_app.get("/kilitli")
    async def kilitli() -> None:
        raise PermissionLockedError("Sistem Yöneticisi rolünün izinleri değiştirilemez")

    @test_app.get("/alan-hatasi")
    async def alan_hatasi() -> None:
        raise DomainError("Alan kuralı ihlal edildi")

    return test_app


@pytest.fixture
async def handler_client(handler_app):
    transport = ASGITransport(app=handler_app)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client


async def test_permission_locked_error_returns_403_with_message(handler_client):
    response = await handler_client.get("/kilitli")

    assert response.status_code == 403
    assert response.json() == {"detail": "Sistem Yöneticisi rolünün izinleri değiştirilemez"}


async def test_domain_error_returns_400_with_message(handler_client):
    response = await handler_client.get("/alan-hatasi")

    assert response.status_code == 400
    assert response.json() == {"detail": "Alan kuralı ihlal edildi"}


async def test_integrity_error_maps_to_409():
    from sqlalchemy.exc import IntegrityError

    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    async def boom():
        raise IntegrityError("stmt", {}, Exception("fk"))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get("/boom")
    assert resp.status_code == 409
