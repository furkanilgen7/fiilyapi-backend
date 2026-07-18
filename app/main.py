import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.bootstrap import ensure_first_admin
from app.core.exception_handlers import register_exception_handlers
from app.modules.auth.router import router as auth_router
from app.modules.projects.router import router as projects_router
from app.modules.roles.router import router as roles_router
from app.modules.users.router import router as users_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Bootstrap başarısız olursa API yine de ayağa kalksın (örn. /docs erişilebilir kalsın);
    # hatayı sessizce yutmuyoruz — logluyoruz.
    try:
        await ensure_first_admin()
    except Exception:
        logger.exception("İlk admin bootstrap'ı başarısız oldu")
    yield


app = FastAPI(title="FİİL Yapı ERP API", version="0.1.0", lifespan=lifespan)
register_exception_handlers(app)
app.include_router(auth_router)
app.include_router(projects_router)
app.include_router(roles_router)
app.include_router(users_router)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
