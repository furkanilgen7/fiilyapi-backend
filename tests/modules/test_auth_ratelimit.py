from collections.abc import Iterator

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded

from app.core.config import settings
from app.core.ratelimit import client_ip, limiter, rate_limit_exceeded_handler


def test_client_ip_prefers_forwarded_for() -> None:
    scope = {"type": "http", "headers": [(b"x-forwarded-for", b"203.0.113.7, 10.0.0.1")]}
    assert client_ip(Request(scope)) == "203.0.113.7"


async def test_rate_limit_returns_429_over_threshold() -> None:
    limiter = Limiter(key_func=client_ip)
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


# ---------------------------------------------------------------------------
# 🔴 GERÇEK UYGULAMANIN BEKÇİSİ (auth kayıt 103)
#
# Yukarıdaki `test_rate_limit_returns_429_over_threshold` KENDİ `Limiter`ını, KENDİ
# `FastAPI()`sini ve KENDİ `/probe` ucunu kuruyor: slowapi kütüphanesinin çalıştığını
# kanıtlıyor, FİİL uygulamasının onu kullandığını DEĞİL. `tests/conftest.py:60` ise
# gerçek limiter'ı TÜM küme boyunca kapatıyor. Sonuç: `app/modules/auth/router.py:23`
# ve `:53`teki iki dekoratör silinse, yanlış sıraya konsa ya da `settings` yerine sabit
# bir dizeye bağlansa beş kapının hiçbiri kırmızı vermiyordu — dekoratör OpenAPI
# şemasında görünmez, tipte iz bırakmaz. Aşağıdaki iki test GERÇEK `app`i, GERÇEK
# `/auth/login` ve `/auth/refresh` uçlarını kullanır ve eşiği `settings`ten TÜRETİR:
# router sabit bir eşiğe bağlanırsa "erken frenlendi" iddiası düşer.
# ---------------------------------------------------------------------------


def _esik(limit_dizesi: str) -> int:
    """`"10/minute"` -> `10`."""
    return int(limit_dizesi.split("/")[0])


@pytest.fixture
def gercek_limiter() -> Iterator[None]:
    """`tests/conftest.py:60` limiter'ı modül düzeyinde kapatır; bu fikstür YALNIZ bu
    testler boyunca açar ve iddia düşse de `finally` ile geri kapatır — küme geri
    kalanının login-yoğun testleri paylaşılan sayaçta birbirini boğmaz."""
    limiter.reset()
    limiter.enabled = True
    try:
        yield
    finally:
        limiter.enabled = False
        limiter.reset()


async def test_gercek_login_ucu_settings_esiginin_ustunde_429_doner(
    client: AsyncClient, gercek_limiter: None
) -> None:
    esik = _esik(settings.login_rate_limit)
    basliklar = {"x-forwarded-for": "198.51.100.11"}
    govde = {"email": "bilinmeyen@example.com", "password": "yanlis-parola"}

    for sira in range(esik):
        yanit = await client.post("/auth/login", json=govde, headers=basliklar)
        assert yanit.status_code == 401, (
            f"{sira + 1}. istek eşik ({esik}) altındayken {yanit.status_code} döndü — "
            "hız sınırı settings.login_rate_limit dışında bir eşiğe bağlı."
        )

    tasan = await client.post("/auth/login", json=govde, headers=basliklar)
    assert tasan.status_code == 429, (
        f"{esik + 1}. giriş denemesi {tasan.status_code} döndü; /auth/login hız sınırı "
        "dekoratörü GERÇEK uygulamada bağlı değil (kaba kuvvet freni yok)."
    )
    assert tasan.json()["detail"] == "Çok fazla deneme, lütfen daha sonra tekrar deneyin"


async def test_gercek_refresh_ucu_settings_esiginin_ustunde_429_doner(
    client: AsyncClient, gercek_limiter: None
) -> None:
    esik = _esik(settings.refresh_rate_limit)
    basliklar = {"x-forwarded-for": "198.51.100.22"}
    govde = {"refresh_token": "gecersiz-token"}

    for sira in range(esik):
        yanit = await client.post("/auth/refresh", json=govde, headers=basliklar)
        assert yanit.status_code == 401, (
            f"{sira + 1}. istek eşik ({esik}) altındayken {yanit.status_code} döndü — "
            "hız sınırı settings.refresh_rate_limit dışında bir eşiğe bağlı."
        )

    tasan = await client.post("/auth/refresh", json=govde, headers=basliklar)
    assert tasan.status_code == 429, (
        f"{esik + 1}. yenileme denemesi {tasan.status_code} döndü; /auth/refresh hız "
        "sınırı dekoratörü GERÇEK uygulamada bağlı değil."
    )
    assert tasan.json()["detail"] == "Çok fazla deneme, lütfen daha sonra tekrar deneyin"
