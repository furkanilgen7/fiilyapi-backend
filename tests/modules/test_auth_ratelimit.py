from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded

from app.core.ratelimit import _client_ip, rate_limit_exceeded_handler


def test_client_ip_prefers_forwarded_for() -> None:
    scope = {"type": "http", "headers": [(b"x-forwarded-for", b"203.0.113.7, 10.0.0.1")]}
    assert _client_ip(Request(scope)) == "203.0.113.7"


async def test_rate_limit_returns_429_over_threshold() -> None:
    limiter = Limiter(key_func=_client_ip)
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

    @app.get("/probe")
    @limiter.limit("2/minute")
    async def probe(request: Request) -> dict[str, bool]:
        return {"ok": True}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.get("/probe")
        second = await client.get("/probe")
        third = await client.get("/probe")

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429
    assert third.json()["detail"] == "Çok fazla deneme, lütfen daha sonra tekrar deneyin"
