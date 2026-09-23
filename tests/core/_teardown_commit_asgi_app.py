"""Yardımcı ASGI uygulaması — `test_teardown_commit_http_olcum.py` gerçek bir
uvicorn süreciyle bunu çalıştırıp GERÇEK bir soket üzerinden ölçer.

Ayrı dosyada tutulma sebebi: `uvicorn <modül>:app` alt süreç olarak
başlatılabilsin diye içe aktarılabilir bir modül gerekir.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, FastAPI

from app.core.exception_handlers import register_exception_handlers


class _PatlayanSession:
    async def commit(self) -> None:
        raise RuntimeError("teardown commit anında patladı")


async def _get_db_taklit() -> AsyncGenerator[_PatlayanSession, None]:
    """`app/core/db.py:get_db` ile AYNI şekil: `try` içinde `yield` + commit."""
    session = _PatlayanSession()
    try:
        yield session
        await session.commit()
    except Exception:
        raise


app = FastAPI()
register_exception_handlers(app)


@app.post("/kaydet")
async def kaydet(db: Annotated[_PatlayanSession, Depends(_get_db_taklit)]) -> dict[str, bool]:
    return {"ok": True}
