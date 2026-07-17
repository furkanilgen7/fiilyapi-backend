from fastapi import FastAPI

from app.modules.auth.router import router as auth_router

app = FastAPI(title="FİİL Yapı ERP API", version="0.1.0")
app.include_router(auth_router)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
