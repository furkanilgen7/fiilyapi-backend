"""Tedarikçi + satın alma talebi uçları (SA T2) — spec §4'ün ilk iki satırı.

Kapı `procurement` iznidir (spec §2, seed'de HAZIR — matris DEĞİŞMEDİ). Seviye
sırası `none < view < draft < request < approve < full < admin`
(`app/core/access.py`) ve üç kapı buradan çıkar:

| Uç | Yetki |
|---|---|
| `GET /suppliers` | `view` |
| `POST /suppliers` | `full` |
| `GET /suppliers/{id}` | `view` |
| `PATCH /suppliers/{id}` | `full` |
| `GET /purchase-requests` | `view` |
| `POST /purchase-requests` | `request` |
| `GET /purchase-requests/{id}` | `view` |
| `PATCH /purchase-requests/{id}` | `request` |
| `DELETE /purchase-requests/{id}` | `request` + `can_delete` |

**Neden tedarikçi `full`, talep `request`:** matriste şantiye şefi ve saha
mühendisi `request` seviyesindedir (`roles/seed_data.py`). Talebi sahadan açan
onlardır; tedarikçi KATALOĞU ise satınalmanın işidir — şef katalog kaydı
açamamalıdır. Tek bir kapı seçilseydi ya şef talep açamaz ya da herkes
tedarikçi ekleyebilirdi.

**DELETE kapısı `_ADMIN` DEĞİLDİR** ve bu bilinçli bir istisnadır
(`contracts/router.py.delete_subcontractor_contract_endpoint` emsali): saf
`_ADMIN` kapısı şefin KENDİ taslağını silmesini de engellerdi ve spec §5.0'ın
taslak istisnasını uçta anlamsız bırakırdı. Kesin kararı servisteki
`can_delete` verir.

`GET` uçları `record_audit` ÇAĞIRMAZ (WORKFLOW kuralı — okumalar denetlenmez);
yazma uçlarının hepsi tek denetim satırı yazar ve metin servis katmanında,
kayıt değişmeden/yok olmadan ÖNCE kurulur.

Router prefix TAŞIMAZ: uçlar iki ayrı kök altına dağılır (`/suppliers` ve
`/purchase-requests`) — `inventory`/`documents` deseninin birebiri.

## AÇILMAYAN uçlar (spec §4, §5 — icat yasağı)

* **`DELETE /suppliers/{id}` YOKTUR** (spec §4): kullanımdan kaldırma
  `PATCH {"is_active": false}` iledir; teklifi/siparişi olan tedarikçi FK
  RESTRICT'i yüzünden zaten düşürülemez. Yol tanımlı olmadığı için FastAPI
  **405** döner ve bu bir BEKÇİ TESTİYLE kilitlidir (`test_silme_ucu_yoktur_405`).
* **`submit`/`approve`/`reject` · teklif alt-kaynağı · `select-and-order` ·
  sipariş uçları · `purchasing/summary` · karşılaştırma Excel'i T3/T4'ündür**
  ve bu dosyada HİÇBİRİ açılmaz. Onay zinciri MOTORU, tedarikçi puanı,
  e-posta/bildirim, mal kabul ucu ve kısmi teslim alanı ise HİÇBİR dilimde
  açılmaz (spec §5, kalıcı karar).
"""

import uuid
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
from app.modules.procurement import service
from app.modules.procurement.models import PurchasePriority, PurchaseRequestStatus
from app.modules.procurement.schemas import (
    PurchaseRequestCreate,
    PurchaseRequestListResponse,
    PurchaseRequestResponse,
    PurchaseRequestUpdate,
    SupplierCard,
    SupplierCreate,
    SupplierListResponse,
    SupplierResponse,
    SupplierUpdate,
)
from app.modules.users.models import User

router = APIRouter(tags=["procurement"], responses=COMMON_ERROR_RESPONSES)

_VIEW = require_permission(service.PERMISSION_MODULE, AccessLevel.view)
_REQUEST = require_permission(service.PERMISSION_MODULE, AccessLevel.request)
_FULL = require_permission(service.PERMISSION_MODULE, AccessLevel.full)

# TB3 sayfalama standardı: varsayılan 50, tavan 200 — tavan aşımı sessizce
# KIRPILMAZ, 422 döner (ST T2 ile birebir).
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


# --- Tedarikçi kataloğu (TED) ---


@router.get("/suppliers", response_model=SupplierListResponse, dependencies=[_VIEW])
async def list_suppliers_endpoint(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    q: str | None = None,
    category: str | None = None,
    is_active: bool | None = None,
    limit: _LIMIT = 50,
    offset: _OFFSET = 0,
) -> SupplierListResponse:
    """TED kart ızgarasının veri kaynağı — süzgeçler AND'lidir.

    `q` AD ve KATEGORİ üzerinde kısmi arar (kart ikisini üst üste basar).
    `is_active` gönderilmezse PASİF tedarikçiler de listelenir: sessiz gizleme
    yok, ekran hangi kümeyi istediğini açıkça söyler.

    "Bu Yıl Toplam Sipariş" (TED 52) TÜREVDİR ve yalnız GÖRÜNEN projelerin
    siparişlerini kapsar (`service` gerekçesi).
    """
    items, total = await service.list_suppliers(
        session, user, q=q, category=category, is_active=is_active, limit=limit, offset=offset
    )
    return SupplierListResponse(items=items, total=total, limit=limit, offset=offset)


@router.post(
    "/suppliers",
    response_model=SupplierResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_FULL],
)
async def create_supplier_endpoint(
    request: Request,
    data: SupplierCreate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> SupplierResponse:
    """Yeni tedarikçi kartı. Ad ve VKN tekilliği ZORLANMAZ (`service` gerekçesi).

    Yanıt "Bu Yıl Toplam Sipariş" TAŞIMAZ: yeni kartta değer zorunlu olarak
    sıfırdır ve onun için ayrıca bir toplama sorgusu koşturmak gereksizdir.
    """
    supplier, detail = await service.create_supplier(session, data)
    await _audit(request, session, user, AuditAction.create, detail)
    return SupplierResponse.model_validate(supplier)


@router.get("/suppliers/{supplier_id}", response_model=SupplierCard, dependencies=[_VIEW])
async def get_supplier_endpoint(
    supplier_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> SupplierCard:
    """Tekil kart — liste ile AYNI türetmeyi kullanır (iki ekran aynı tutarı
    göstersin diye ikinci bir formül yazılmaz)."""
    return await service.get_supplier_card(session, user, supplier_id)


@router.patch("/suppliers/{supplier_id}", response_model=SupplierResponse, dependencies=[_FULL])
async def update_supplier_endpoint(
    request: Request,
    supplier_id: uuid.UUID,
    data: SupplierUpdate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> SupplierResponse:
    """Kısmi güncelleme. **Kullanımdan kaldırma da buradan geçer**
    (`{"is_active": false}`) — DELETE ucu yoktur (modül docstring'i)."""
    supplier, detail = await service.update_supplier(session, supplier_id, data)
    await _audit(request, session, user, AuditAction.update, detail)
    return SupplierResponse.model_validate(supplier)


# --- Satın alma talebi (FST + SAT) ---


@router.get("/purchase-requests", response_model=PurchaseRequestListResponse, dependencies=[_VIEW])
async def list_purchase_requests_endpoint(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    status_filter: Annotated[PurchaseRequestStatus | None, Query(alias="status")] = None,
    project_id: uuid.UUID | None = None,
    priority: PurchasePriority | None = None,
    q: str | None = None,
    limit: _LIMIT = 50,
    offset: _OFFSET = 0,
) -> PurchaseRequestListResponse:
    """SAT tablosunun veri kaynağı — süzgeçler AND'lidir.

    Kapsam süzgeci HER ZAMAN uygulanır: görünmeyen projenin talebi listede
    YOKTUR ve `total`a da girmez.

    Tahmini toplam ve kalem sayısı TÜREVDİR; satır KALEMLERİ TAŞIMAZ (şema
    gerekçesi). `limit` varsayılan 50, tavan 200 — aşım 422.
    """
    return await service.list_requests(
        session,
        user,
        status=status_filter,
        project_id=project_id,
        priority=priority,
        q=q,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/purchase-requests",
    response_model=PurchaseRequestResponse,
    status_code=status.HTTP_201_CREATED,
    responses={404: {"description": "Seçilen proje/şantiye/bölüm/malzeme bulunamadı"}},
    dependencies=[_REQUEST],
)
async def create_purchase_request_endpoint(
    request: Request,
    data: PurchaseRequestCreate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> PurchaseRequestResponse:
    """FST formunun kaydı: başlık + kalemler TEK gövde, ATOMİK.

    **TASLAK-FARKINDALIKLI (P6 emsali):** zorunlu tek alan `project_id`dir;
    "Taslak Kaydet" yarım formu saklar. Sıkı doğrulama (`validation.
    submit_blockers`) `submit` ucundadır ve **T3'ündür**.

    * kalem XOR ihlali / miktar ≤ 0 / uzunluk tavanı → **422**
    * görünmeyen ya da olmayan proje/şantiye/bölüm/malzeme kartı → **404**

    Bozuk bir kalem varsa HİÇBİR ŞEY yazılmaz — ne başlık ne satır. Denetime
    TALEP BAŞINA TEK satır düşer. `request_no` sunucu üretir; gövdedeki numara
    ve durum YOK SAYILIR.
    """
    purchase_request, detail = await service.create_request(session, user, data)
    await _audit(request, session, user, AuditAction.create, detail)
    return await service.build_request_detail(session, user, purchase_request)


@router.get(
    "/purchase-requests/{request_id}",
    response_model=PurchaseRequestResponse,
    dependencies=[_VIEW],
)
async def get_purchase_request_endpoint(
    request_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> PurchaseRequestResponse:
    """FST detayı: başlık + kalemler + TÜREVLER (satır tutarı · tahmini toplam ·
    "Mevcut Stok"). Görünmeyen talep var olmayanla AYNI 404'ü alır."""
    purchase_request = await service.visible_request(session, user, request_id)
    return await service.build_request_detail(session, user, purchase_request)


@router.patch(
    "/purchase-requests/{request_id}",
    response_model=PurchaseRequestResponse,
    responses={
        404: {"description": "Talep ya da seçilen proje/şantiye/bölüm/malzeme bulunamadı"},
        409: {"description": "Yalnızca taslak talep düzenlenebilir"},
    },
    dependencies=[_REQUEST],
)
async def update_purchase_request_endpoint(
    request: Request,
    request_id: uuid.UUID,
    data: PurchaseRequestUpdate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> PurchaseRequestResponse:
    """**YALNIZ taslakta** (spec §4); değilse **409** — yetki değil DURUM engeli.

    `lines` gönderilirse kalemler REPLACE edilir (tek atomik işlem); hiç
    göndermemek onlara DOKUNMAZ, boş liste hepsini SİLER.
    """
    purchase_request = await service.visible_request(session, user, request_id)
    purchase_request, detail = await service.update_request(session, user, purchase_request, data)
    await _audit(request, session, user, AuditAction.update, detail)
    return await service.build_request_detail(session, user, purchase_request)


@router.delete(
    "/purchase-requests/{request_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        403: {"description": "Yalnızca talebi açan kendi taslağını silebilir"},
        409: {"description": "Yalnızca taslak talep silinebilir"},
    },
    dependencies=[_REQUEST],
)
async def delete_purchase_request_endpoint(
    request: Request,
    request_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """**YALNIZ taslak** silinir (409 aksi hâlde) ve kararı `can_delete` verir
    (403 aksi hâlde) — kapı gerekçesi modül docstring'indedir.

    Yanıtın `can_delete` bayrağı ile bu uç AYNI fonksiyondan beslenir: ekran
    düğmeyi gösterip sonra 403 yemez. Kalemler CASCADE ile gider.

    Yanıt `204 No Content`, gövdesizdir.
    """
    purchase_request = await service.visible_request(session, user, request_id)
    detail = await service.delete_request(session, user, purchase_request)
    await _audit(request, session, user, AuditAction.delete, detail)
