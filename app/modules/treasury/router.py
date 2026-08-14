"""Banka hesabı uçları (HZ-1 T3) — spec §4'ün 1-5 numaralı yolları.

Kapı `treasury` iznidir (spec §4, seed'de HAZIR — 🔴 **matris DEĞİŞMEDİ, yeni
izin modülü AÇILMADI, izin migration'ı YOKTUR**). Seviye sırası
`none < view < draft < request < approve < full < admin` (`app/core/access.py`)
ve üç kapı buradan çıkar:

| Uç | Yetki |
|---|---|
| `GET /bank-accounts` | `view` |
| `POST /bank-accounts` | `full` |
| `GET /bank-accounts/{id}` | `view` |
| `PATCH /bank-accounts/{id}` | `full` |
| `DELETE /bank-accounts/{id}` | **`admin`** |

**Neden `DELETE` düz `admin`:** `full` silmeyi KAPSAMAZ (repo kanonu). Banka
hesabı mali bir kayıttır ve ödeme geçmişinin taşıyıcısıdır; muhasebeci onu tek
başına düşürememelidir (`invoicing`/`documents` deseni). Normal kullanımdan
kaldırma yolu `PATCH {"is_active": false}`tur.

`GET` uçları `record_audit` ÇAĞIRMAZ (WORKFLOW kuralı — okumalar denetlenmez);
üç yazma ucunun her biri TEK denetim satırı yazar ve metin servis katmanında,
kayıt değişmeden/yok olmadan ÖNCE kurulur.

## AÇILMAYAN uçlar (spec §1/§4, icat yasağı)

Ödeme uçları (`GET`/`POST /invoices/{id}/payments`, `DELETE /payments/{id}`)
**T4'ündür** ve ikisi de `invoicing` iznine bağlıdır; türev uçlar
(`/treasury/upcoming-payments`, `/treasury/cash-flow`) **T5'indir**. Çek/senet
(E10) ve nakit hareket tablosu KAPSAM DIŞIDIR (HZ-2/HZ-3).

## Rota sırası

`/bank-accounts/{account_id}` (UUID) ile çakışan iki-segmentli LİTERAL yol
BU DİLİMDE YOKTUR. T5'in `/treasury/…` yolları farklı bir kök taşır, yani
çakışmaz; buna karşılık bu router'a ileride `/bank-accounts/<literal>` biçiminde
bir yol eklenirse UUID rotasının ÜSTÜNE konmalıdır — FastAPI yolları KAYIT
SIRASINA göre eşler ve sonra kaydedilen literal bir UUID sanılıp 422'ye düşer
(MK-2 dersi, `main.py:94-104`). Ayrılmış yer aşağıda işaretlidir.
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
from app.modules.treasury import service
from app.modules.treasury.schemas import (
    BankAccountCreate,
    BankAccountListResponse,
    BankAccountResponse,
    BankAccountUpdate,
)
from app.modules.users.models import User

router = APIRouter(tags=["treasury"], responses=COMMON_ERROR_RESPONSES)

_VIEW = require_permission(service.PERMISSION_MODULE, AccessLevel.view)
_FULL = require_permission(service.PERMISSION_MODULE, AccessLevel.full)
_ADMIN = require_permission(service.PERMISSION_MODULE, AccessLevel.admin)

# TB3 sayfalama standardı: varsayılan 50, tavan 200 — tavan aşımı sessizce
# KIRPILMAZ, 422 döner (ST/SA/`invoicing` ile birebir).
_LIMIT = Annotated[int, Query(ge=1, le=200)]
_OFFSET = Annotated[int, Query(ge=0)]

_YAZMA_YANITLARI = {
    409: {"description": "Bu IBAN başka bir hesapta kayıtlı"},
    422: {"description": "Gövde kuralı ihlali (Kasa hesabında görünen ad zorunludur)"},
}


async def _audit(
    request: Request,
    session: AsyncSession,
    user: User,
    action: AuditAction,
    detail: str,
) -> None:
    """Denetim satırı (B5 deseni). Metin PARAMETREDİR, burada kurulmaz.

    🔴 Yeni `AuditAction` üyesi AÇILMADI (TB3/T3 kanonu): `action` gerçek bir
    Postgres enum tipidir ve yeni üye migration ister. Ayrım METİNDEDİR.
    """
    await record_audit(
        session,
        action=action,
        detail=detail,
        actor_user_id=user.id,
        ip_address=client_ip(request),
    )


# --- Uç 1: liste ---


@router.get("/bank-accounts", response_model=BankAccountListResponse, dependencies=[_VIEW])
async def list_bank_accounts_endpoint(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    is_active: bool | None = None,
    limit: _LIMIT = 50,
    offset: _OFFSET = 0,
) -> BankAccountListResponse:
    """E9:70-84 kart şeridi — her satır **TÜRETİLMİŞ `balance`** taşır (K2).

    Süzgeç `is_active`tir ve `total`a da uygulanır. `limit` varsayılan 50, tavan
    200 — aşım **422** (kırpma DEĞİL).

    🔴 **Proje/şantiye kapsam süzgeci YOKTUR (K3):** hesap şirket genelidir
    (`suppliers`/`customers` emsali), erişimi `treasury` izni denetler.
    """
    return await service.list_accounts(session, is_active=is_active, limit=limit, offset=offset)


# --- Uç 2: oluştur ---


@router.post(
    "/bank-accounts",
    response_model=BankAccountResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_YAZMA_YANITLARI,
    dependencies=[_FULL],
)
async def create_bank_account_endpoint(
    request: Request,
    data: BankAccountCreate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> BankAccountResponse:
    """Yeni banka ya da kasa hesabı.

    * `account_type` KAPALI kümedir: `checking` | `cash` (K1)
    * Kasa'da `display_name` ZORUNLUDUR → aksi **422** (DB CHECK'i son savunma)
    * IBAN normalize edilir; aynı IBAN **409**, NULL IBAN'lar çoklanabilir
    * `balance` gövdeden GELEMEZ (**422**): türevdir, `opening_balance`tan doğar
    """
    account, detail = await service.create_account(session, data)
    await _audit(request, session, user, AuditAction.create, detail)
    return await service.get_account_response(session, account.id)


# --------------------------------------------------------------------------- #
# 🔴 AYRILMIŞ YER — iki segmentli LİTERAL `/bank-accounts/<literal>` yolları.
#
# Aşağıdaki `/bank-accounts/{account_id}` (UUID) rotasıyla ÇAKIŞIRLAR: FastAPI
# yolları KAYIT SIRASINA göre eşler, sonra kaydedilen literal bir UUID sanılıp
# 422'ye düşer (MK-2 dersi). Bugün böyle bir yol YOKTUR; eklenecek olan HER biri
# bu satırın ÜSTÜNE gelir.
# --------------------------------------------------------------------------- #


# --- Uç 3: detay ---


@router.get(
    "/bank-accounts/{account_id}",
    response_model=BankAccountResponse,
    responses={404: {"description": "Banka hesabı bulunamadı"}},
    dependencies=[_VIEW],
)
async def get_bank_account_endpoint(
    account_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> BankAccountResponse:
    """Tek hesap + türetilmiş bakiye. Bakiye liste ucuyla AYNI kaynaktan gelir."""
    return await service.get_account_response(session, account_id)


# --- Uç 4: PATCH ---


@router.patch(
    "/bank-accounts/{account_id}",
    response_model=BankAccountResponse,
    responses={404: {"description": "Banka hesabı bulunamadı"}, **_YAZMA_YANITLARI},
    dependencies=[_FULL],
)
async def update_bank_account_endpoint(
    request: Request,
    account_id: uuid.UUID,
    data: BankAccountUpdate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> BankAccountResponse:
    """Kısmi güncelleme; kayıt DENETİMLERDEN ÖNCE kilitlenir (TOCTOU).

    `opening_balance` DEĞİŞEBİLİR (elle düzeltme meşrudur) ve bakiye
    kendiliğinden yeniden türetilir. Tipi `cash`e çevirip adı boş bırakmak da
    **422**dir: kural DB'deki kayıtla BİRLEŞTİRİLMİŞ değerler üzerinde koşar.
    """
    account, detail = await service.update_account(session, account_id, data)
    await _audit(request, session, user, AuditAction.update, detail)
    return await service.get_account_response(session, account.id)


# --- Uç 5: DELETE ---


@router.delete(
    "/bank-accounts/{account_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        404: {"description": "Banka hesabı bulunamadı"},
        409: {"description": "Bu hesaba bağlı ödeme kayıtları var"},
    },
    dependencies=[_ADMIN],
)
async def delete_bank_account_endpoint(
    request: Request,
    account_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """**YALNIZ `admin`** → 204; ödemesi olan hesap **409**.

    `full` seviyesi (muhasebe) 403 alır — gerekçe modül docstring'indedir.
    409 SERVİSTEN gelir: ham FK ihlalinin 500'ü ya da ayrımsız "Veri bütünlüğü
    hatası" kullanıcıya SIZMAZ. Yanıt gövdesizdir.
    """
    detail = await service.delete_account(session, account_id)
    await _audit(request, session, user, AuditAction.delete, detail)
