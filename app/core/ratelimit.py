from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded


def _client_ip(request: Request) -> str:
    """Hız sınırı anahtarı: gerçek istemci IP'si.

    Railway/prod proxy arkasında `request.client.host` proxy'nin IP'sidir; gerçek istemci
    `X-Forwarded-For`'un ilk girdisindedir. Onu tercih eder, yoksa doğrudan bağlantıya düşer.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "anonymous"


# In-memory limiter — Railway tek instance olduğundan Redis gerekmez.
limiter = Limiter(key_func=_client_ip)


async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": "Çok fazla deneme, lütfen daha sonra tekrar deneyin"},
    )
