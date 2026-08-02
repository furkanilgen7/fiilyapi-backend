import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded

from app.core.bootstrap import ensure_company, ensure_first_admin
from app.core.config import Settings, settings
from app.core.exception_handlers import register_exception_handlers
from app.core.ratelimit import limiter, rate_limit_exceeded_handler
from app.modules.audit.router import router as audit_router
from app.modules.auth.router import router as auth_router
from app.modules.boq.router import router as boq_router
from app.modules.company.router import router as company_router
from app.modules.contracts.router import router as contracts_router
from app.modules.customers.router import router as customers_router
from app.modules.dashboard.router import router as dashboard_router
from app.modules.progress_payments.router import router as progress_payments_router
from app.modules.projects.router import employers_router
from app.modules.projects.router import router as projects_router
from app.modules.roles.router import router as roles_router
from app.modules.sales.router import router as sales_router
from app.modules.settings.router import router as settings_router
from app.modules.sites.router import router as sites_router
from app.modules.units.router import router as units_router
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
    try:
        await ensure_company()
    except Exception:
        logger.exception("Sirket bootstrap'i basarisiz oldu")
    yield


def _configure_cors(app: FastAPI, cfg: Settings) -> None:
    """Env'de origin verilmişse sıkı CORS middleware'i ekler.

    Wildcard `*` + credentials birlikte KULLANILMAZ — origin'ler açık liste olmalı.
    Liste boşsa (dev varsayılanı) middleware hiç eklenmez.
    """
    origins = cfg.cors_origin_list
    if not origins:
        return
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


app = FastAPI(title="FİİL Yapı ERP API", version="0.1.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
register_exception_handlers(app)
_configure_cors(app, settings)
app.include_router(audit_router)
app.include_router(auth_router)
app.include_router(boq_router)
app.include_router(company_router)
app.include_router(contracts_router)
app.include_router(customers_router)
app.include_router(dashboard_router)
app.include_router(employers_router)
app.include_router(progress_payments_router)
app.include_router(projects_router)
app.include_router(roles_router)
app.include_router(sales_router)
app.include_router(settings_router)
app.include_router(sites_router)
app.include_router(units_router)
app.include_router(users_router)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
