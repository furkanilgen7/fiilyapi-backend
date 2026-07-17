from fastapi import FastAPI

from app.core.exception_handlers import register_exception_handlers
from app.modules.auth.router import router as auth_router
from app.modules.projects.router import router as projects_router

app = FastAPI(title="FİİL Yapı ERP API", version="0.1.0")
register_exception_handlers(app)
app.include_router(auth_router)
app.include_router(projects_router)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
