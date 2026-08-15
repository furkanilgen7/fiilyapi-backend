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
from app.modules.accounting.accounts_router import router as accounting_accounts_router
from app.modules.accounting.periods_router import router as accounting_periods_router
from app.modules.accounting.router import router as accounting_journal_router
from app.modules.audit.router import router as audit_router
from app.modules.auth.router import router as auth_router
from app.modules.boq.router import router as boq_router
from app.modules.company.router import router as company_router
from app.modules.contracts.router import router as contracts_router
from app.modules.customers.router import router as customers_router
from app.modules.dashboard.router import router as dashboard_router
from app.modules.documents.router import router as documents_router
from app.modules.equipment.document_router import router as equipment_document_router
from app.modules.equipment.rental_router import router as equipment_rental_router
from app.modules.equipment.router import router as equipment_router
from app.modules.inventory.router import router as inventory_router
from app.modules.invoicing.router import router as invoicing_router
from app.modules.payroll.router import router as payroll_router
from app.modules.personnel.router import router as personnel_router
from app.modules.procurement.router import router as procurement_router
from app.modules.progress_payments.router import router as progress_payments_router
from app.modules.projects.router import employers_router
from app.modules.projects.router import router as projects_router
from app.modules.roles.router import router as roles_router
from app.modules.sales.router import router as sales_router
from app.modules.settings.router import router as settings_router
from app.modules.site_diary.router import router as site_diary_router
from app.modules.site_planning.router import router as site_planning_router
from app.modules.sites.router import router as sites_router
from app.modules.subcontractor_progress_payments.router import (
    router as subcontractor_progress_payments_router,
)
from app.modules.timesheet.router import router as timesheet_router
from app.modules.treasury.router import router as treasury_router
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
# `accounting_accounts_router` yalnız `/chart-of-accounts` kökünü taşır ve başka
# hiçbir router'ın yoluyla çakışmaz; kendi içindeki UUID/literal sırası router
# modül docstring'inde açıklanmıştır (bugün literal yol YOKTUR). Yevmiye uçları
# (T3b) AYRI bir router'dadır ve `/journal-entries` + `/journal` köklerini taşır.
app.include_router(accounting_accounts_router)
# `accounting_journal_router` `/journal-entries` ve `/journal` köklerini taşır;
# ikisi de başka hiçbir router'ın yoluyla çakışmaz (FastAPI SEGMENT bazında
# eşler — `/journal` ile `/journal-entries` ayrı köklerdir, önek benzerliği
# eşleşme üretmez). 🔴 Rota sırası tuzağı router'ın KENDİ İÇİNDE çözülür:
# `/journal-entries/summary` iki segmentlidir ve `/journal-entries/{entry_id}`
# ile aynı şekli taşır — ayrılmış yer orada işaretlidir, bekçi testi
# `test_rota_sirasi_summary_UUID_SANILMAZ` (MK-2 dersi).
app.include_router(accounting_journal_router)
# `accounting_periods_router` (MU-2 T3) `/accounting-periods` kökünü taşır.
# 🔴 ROTA SIRASI TUZAĞI DEĞERLENDİRİLDİ ve BU KÖKTE YOKTUR — gerekçe grep'le
# doğrulandı: repoda `/accounting-periods` ile başlayan BAŞKA hiçbir yol yoktur
# ve tek `prefix=` kullanan öteki router `/equipment`tir. Router'ın KENDİ içinde
# de çakışma yoktur: liste ucu TEK segmentlidir, ötekiler ÜÇ segmentlidir ve son
# segmentleri LİTERALDİR (`close`/`reopen`) — `/{year}/{month}` int'tir, UUID
# sanılabilecek bir yol açılmamıştır (MK-2 dersinin uygulanamadığı hâl).
# Sıra bu yüzden serbesttir; alfabetik yerine muhasebe router'larının yanında
# durur, çünkü üçü de aynı izin modülünü (`accounting`) paylaşır.
app.include_router(accounting_periods_router)
app.include_router(audit_router)
app.include_router(auth_router)
app.include_router(boq_router)
app.include_router(company_router)
app.include_router(contracts_router)
app.include_router(customers_router)
app.include_router(dashboard_router)
app.include_router(documents_router)
app.include_router(employers_router)
# 🔴 SIRA ZORUNLU: kira hakedişi router'ı `equipment_router`dan ÖNCE kaydedilir.
# `equipment_router` `/equipment/{equipment_id}` (UUID) yolunu taşır ve FastAPI
# yolları KAYIT SIRASINA göre eşler; sonra kaydedilseydi `/equipment/rental-invoices`
# bir UUID sanılıp 422'ye düşerdi. Kural bir bekçi testiyle kilitlidir
# (`test_rota_sirasi_rental_invoices_UUID_SANILMAZ`).
app.include_router(equipment_rental_router)
# 🔴 SIRA ZORUNLU: belge router'ı da `equipment_router`dan ÖNCE — `/equipment/
# document-types` iki segmentlidir ve `equipment_router`ın `/equipment/{equipment_id}`
# yoluyla AYNI şekli taşır (bekçi testi: `test_rota_sirasi_document_types_UUID_SANILMAZ`).
app.include_router(equipment_document_router)
app.include_router(equipment_router)
app.include_router(inventory_router)
# Rota sırası tuzağı `invoicing_router`ın KENDİ İÇİNDE çözülür (router modül
# docstring'i): `/invoices/summary` (T4) iki segmentlidir ve
# `/invoices/{invoice_id}` ile çakışır — ayrılmış yer orada işaretlidir.
app.include_router(invoicing_router)
app.include_router(payroll_router)
app.include_router(personnel_router)
app.include_router(procurement_router)
app.include_router(progress_payments_router)
app.include_router(projects_router)
app.include_router(roles_router)
app.include_router(sales_router)
app.include_router(settings_router)
app.include_router(site_diary_router)
app.include_router(site_planning_router)
app.include_router(sites_router)
app.include_router(subcontractor_progress_payments_router)
app.include_router(timesheet_router)
# `treasury_router` yalnız `/bank-accounts` kökünü taşır ve başka hiçbir
# router'ın yoluyla çakışmaz; kendi içindeki UUID/literal sırası da router modül
# docstring'inde açıklanmıştır (bugün literal yol YOKTUR). Ödeme uçları (T4)
# `/invoices/{id}/payments` altında ve `invoicing_router`ın İÇİNDE tanımlanır —
# ayrı bir router olarak buraya eklenmezler (spec §5, MK-2 dersi).
app.include_router(treasury_router)
app.include_router(units_router)
app.include_router(users_router)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
