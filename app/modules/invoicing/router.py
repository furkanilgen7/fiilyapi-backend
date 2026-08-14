"""Fatura uçları (FAT-1 T3) — spec §7'nin 1, 3, 4, 5, 6, 7 numaralı yolları.

Kapı `invoicing` iznidir (spec §6, seed'de HAZIR — matris DEĞİŞMEDİ). Seviye
sırası `none < view < draft < request < approve < full < admin`
(`app/core/access.py`) ve üç kapı buradan çıkar:

| Uç | Yetki |
|---|---|
| `GET /invoices` | `view` |
| `POST /invoices` | `full` |
| `GET /invoices/{id}` | `view` |
| `PATCH /invoices/{id}` | `full` |
| `PUT /invoices/{id}/lines` | `full` |
| `DELETE /invoices/{id}` | **`admin`** |

**Neden `DELETE` düz `admin`:** `full` silmeyi KAPSAMAZ (repo kanonu) ve
`procurement`in `can_delete` istisnası burada GEÇERSİZDİR — faturanın "sahibi"
onu kesen kullanıcı değil ŞİRKETTİR; muhasebeci kendi kestiği taslağı bile
tek başına düşürememelidir (mali belge, `documents`/`inventory` deseni).

`GET` uçları `record_audit` ÇAĞIRMAZ (WORKFLOW kuralı — okumalar denetlenmez);
yazma uçlarının hepsi TEK denetim satırı yazar ve metin servis katmanında,
kayıt değişmeden/yok olmadan ÖNCE kurulur.

## AÇILMAYAN uçlar (spec §1/§7, icat yasağı)

`GİB'den Çek` (FY:23) · muhasebe fişi (FGE:197-241) · tahsilat KAYDI
(FGI:220-247; burada yalnız DURUM damgası olacaktır, T4) · `Kısmi Onayla`
(FGE:140) · toplu seçim/onay · `e-Arşiv` ve `İtiraz/İade` sekmeleri. Durum
uçları (`send`/`mark-collected`/`approve`/`dispute`) ve `GET /invoices/summary`
**T4'ündür**.

## 🔴 ROTA SIRASI (spec §9, MK-2 dersi — `main.py:94-104`)

`/invoices/summary` İKİ SEGMENTLİDİR ve `/invoices/{invoice_id}` (UUID) ile
AYNI şekli taşır; FastAPI yolları KAYIT SIRASINA göre eşler. Sonra
kaydedilseydi `summary` bir UUID sanılıp 422'ye düşerdi. Yeri aşağıda
AYRILMIŞTIR ve kural bir bekçi testiyle kilitlidir
(`test_rota_sirasi_iki_segmentli_literal_yollar_UUID_rotasindan_ONCE`).
"""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import AccessLevel
from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.openapi import COMMON_ERROR_RESPONSES
from app.core.permissions import require_permission
from app.core.ratelimit import client_ip
from app.modules.audit.models import AuditAction
from app.modules.audit.service import record_audit
from app.modules.invoicing import service
from app.modules.invoicing.models import InvoiceDirection, InvoiceStatus
from app.modules.invoicing.schemas import (
    InvoiceCreate,
    InvoiceDetailResponse,
    InvoiceLinesReplace,
    InvoiceListResponse,
    InvoiceUpdate,
)
from app.modules.users.models import User

router = APIRouter(tags=["invoicing"], responses=COMMON_ERROR_RESPONSES)

_VIEW = require_permission(service.PERMISSION_MODULE, AccessLevel.view)
_FULL = require_permission(service.PERMISSION_MODULE, AccessLevel.full)
_ADMIN = require_permission(service.PERMISSION_MODULE, AccessLevel.admin)

# TB3 sayfalama standardı: varsayılan 50, tavan 200 — tavan aşımı sessizce
# KIRPILMAZ, 422 döner (ST/SA ile birebir).
_LIMIT = Annotated[int, Query(ge=1, le=200)]
_OFFSET = Annotated[int, Query(ge=0)]


async def _audit(
    request: Request,
    session: AsyncSession,
    user: User,
    action: AuditAction,
    detail: str,
) -> None:
    """Denetim satırı (B5 deseni). Metin PARAMETREDİR, burada kurulmaz."""
    await record_audit(
        session,
        action=action,
        detail=detail,
        actor_user_id=user.id,
        ip_address=client_ip(request),
    )


# --- Uç 1: liste ---


@router.get("/invoices", response_model=InvoiceListResponse, dependencies=[_VIEW])
async def list_invoices_endpoint(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    direction: InvoiceDirection | None = None,
    status_filter: Annotated[InvoiceStatus | None, Query(alias="status")] = None,
    project_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    q: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: _LIMIT = 50,
    offset: _OFFSET = 0,
) -> InvoiceListResponse:
    """FY tablosunun veri kaynağı — süzgeçler AND'lidir.

    Kapsam süzgeci HER ZAMAN uygulanır: görünmeyen projenin faturası listede
    YOKTUR ve `total`a da girmez. `project_id` NULL fatura (şirket geneli)
    modül izniyle görünür (§6).

    `q` FATURA NUMARASI ve TARAF ADI üzerinde kısmi arar (FY:94). `status`
    süzgeci ÜÇ giden değerini de alır; ekranın "Vadeli" seçeneği `sent`e eşlenir
    (K1 — "Vadeli" ayrı bir durum DEĞİLDİR).

    `limit` varsayılan 50, tavan 200 — aşım **422**.
    """
    return await service.list_invoices(
        session,
        user,
        direction=direction,
        status=status_filter,
        project_id=project_id,
        site_id=site_id,
        q=q,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )


# --- Uç 3: oluştur ---


@router.post(
    "/invoices",
    response_model=InvoiceDetailResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        404: {"description": "Seçilen proje/şantiye/cari/kaynak kayıt bulunamadı"},
        409: {"description": "Bu fatura numarası bu yönde zaten kayıtlı"},
        422: {"description": "Gövde kuralı ihlali (numara sahibi · tek taraf · oran toplamı)"},
    },
    dependencies=[_FULL],
)
async def create_invoice_endpoint(
    request: Request,
    data: InvoiceCreate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> InvoiceDetailResponse:
    """FK formunun kaydı: başlık + kalemler TEK gövde, ATOMİK.

    * giden → `draft`, gelen → `pending` (K2); gövde `status` GÖNDEREMEZ
    * giden numarayı SUNUCU üretir (`FIL…`), gelen numarayı İSTEMCİ verir (S5)
    * `line_total`/`sort_order` ve hesaplanmış para alanları gövdeden GELEMEZ
      (**422**) — oranlar (`*_rate`) GELİR
    * görünmeyen ya da olmayan proje/şantiye/cari/kaynak → **404**

    Bozuk bir kalem varsa HİÇBİR ŞEY yazılmaz — ne başlık ne satır. Denetime
    FATURA BAŞINA TEK satır düşer.
    """
    invoice, detail = await service.create_invoice(session, user, data)
    await _audit(request, session, user, AuditAction.create, detail)
    return await service.build_detail(session, invoice)


# --------------------------------------------------------------------------- #
# 🔴 AYRILMIŞ YER — `GET /invoices/summary` (spec §7 md.2, **T4**) BURAYA GELİR.
#
# İki segmentlidir ve aşağıdaki `/invoices/{invoice_id}` (UUID) rotasıyla
# ÇAKIŞIR: FastAPI yolları KAYIT SIRASINA göre eşler, sonra kaydedilirse
# `summary` bir UUID sanılıp 422'ye düşer (MK-2 dersi, `main.py:94-104`).
# Yeni iki segmentli LİTERAL yolların hepsi bu satırın ÜSTÜNE eklenir.
# --------------------------------------------------------------------------- #


# --- Uç 4: detay ---


@router.get(
    "/invoices/{invoice_id}",
    response_model=InvoiceDetailResponse,
    responses={404: {"description": "Fatura bulunamadı"}},
    dependencies=[_VIEW],
)
async def get_invoice_endpoint(
    invoice_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> InvoiceDetailResponse:
    """FGI/FGE detayı: başlık + kalemler + SAKLANAN toplamlar.

    Görünmeyen fatura var olmayanla AYNI 404'ü alır. Toplamlar okuma anında
    yeniden HESAPLANMAZ (K7): fatura donmuş bir belgedir.
    """
    invoice = await service.visible_invoice(session, user, invoice_id)
    return await service.build_detail(session, invoice)


# --- Uç 5: PATCH ---


@router.patch(
    "/invoices/{invoice_id}",
    response_model=InvoiceDetailResponse,
    responses={
        404: {"description": "Fatura ya da seçilen proje/şantiye/cari/kaynak bulunamadı"},
        409: {"description": "Fatura bu durumda düzenlenemez"},
        422: {"description": "Gövde kuralı ihlali ya da gelen faturada kapsam dışı alan"},
    },
    dependencies=[_FULL],
)
async def update_invoice_endpoint(
    request: Request,
    invoice_id: uuid.UUID,
    data: InvoiceUpdate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> InvoiceDetailResponse:
    """**Giden faturada yalnız `draft`, gelen faturada yalnız `pending`** —
    aksi **409** (yetki değil DURUM engeli).

    Gelen faturada yalnız `note`/`due_date`/`payment_method` düzeltilebilir
    (**422** aksi hâlde): gelen fatura SATICININ belgesidir.

    Kayıt kilitlenerek okunur ve durum kapısı KİLİTLİ satır üzerinde koşar
    (spec §8, TOCTOU). Oran değişirse başlık toplamları `amounts`tan YENİDEN
    hesaplanır; kalemler değişmez (onların yolu `PUT lines`).
    """
    invoice = await service.visible_invoice(session, user, invoice_id, for_update=True)
    invoice, detail = await service.update_invoice(session, user, invoice, data)
    await _audit(request, session, user, AuditAction.update, detail)
    return await service.build_detail(session, invoice)


# --- Uç 6: DELETE ---


@router.delete(
    "/invoices/{invoice_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        404: {"description": "Fatura bulunamadı"},
        409: {"description": "Yalnızca taslak fatura silinebilir"},
    },
    dependencies=[_ADMIN],
)
async def delete_invoice_endpoint(
    request: Request,
    invoice_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """**YALNIZ `admin` + yalnız `draft`** → 204; başka durum **409**.

    `full` seviyesi (muhasebe) 403 alır — gerekçe modül docstring'indedir.
    Kalemler birlikte gider. Yanıt gövdesizdir.
    """
    invoice = await service.visible_invoice(session, user, invoice_id, for_update=True)
    detail = await service.delete_invoice(session, invoice)
    await _audit(request, session, user, AuditAction.delete, detail)


# --- Uç 7: PUT lines ---


@router.put(
    "/invoices/{invoice_id}/lines",
    response_model=InvoiceDetailResponse,
    responses={
        404: {"description": "Fatura bulunamadı"},
        409: {"description": "Kalemler yalnızca taslak faturada değiştirilebilir"},
    },
    dependencies=[_FULL],
)
async def replace_invoice_lines_endpoint(
    request: Request,
    invoice_id: uuid.UUID,
    data: InvoiceLinesReplace,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> InvoiceDetailResponse:
    """Kalem kümesini TOPTAN yazar (hakediş/puantaj emsali) — yalnız `draft`.

    `sort_order` gövdedeki dizinin İNDEKSİDİR, `line_total` sunucunun hesabıdır;
    ikisi de gövdeden GELEMEZ (**422**). Başlık toplamları aynı hesapla
    güncellenir. Boş liste hepsini SİLER (kalemsiz taslak meşrudur; K6 kapısı
    `send`/`approve` anındadır, T4).

    Kilit sırası SABİT: fatura → kalemler.
    """
    invoice = await service.visible_invoice(session, user, invoice_id, for_update=True)
    invoice, detail = await service.replace_lines(session, invoice, data)
    await _audit(request, session, user, AuditAction.update, detail)
    return await service.build_detail(session, invoice)
