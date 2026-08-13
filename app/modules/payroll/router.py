"""Bordro dönem + satır uçları — İK-3 T3 (spec §5'in ilk beş satırı).

Mockup otoritesi: `projedesign/Bordro Yönetimi.dc.html` (BY) ·
`Bordro Geçmişi.dc.html` (BG).

| Uç | Yetki | Mockup |
|---|---|---|
| `GET /payroll/periods` | `view` | BG 44-47 + tbody |
| `POST /payroll/periods` | `full` | BY 52 ay seçici |
| `GET /payroll/periods/{id}` | `view` | BY 69-93 + 124/172/240/268 |
| `POST /payroll/periods/{id}/compute` | `full` | BY tablosunun doldurulması |
| `PATCH /payroll/lines/{id}` | `full` | BY 142-147 iki `input` |

Kapı `payroll` iznidir (spec S9): okuma `view`, yazma `full`. **Seed'de ZATEN
VARDIR** (`roles/seed_data.py:182`) — yeni izin modülü AÇILMADI, matris
DEĞİŞMEDİ. Ayrı bir `payroll:admin` de açılmaz: silme ucu yoktur.

**`visible_projects` süzgeci YOKTUR** ve bu BİLİNÇLİDİR (`personnel`/
`timesheet` deseni): bordro şirket geneli bir İK varlığıdır, bir dönem tek bir
projeye ait değildir. Süzgeç konsaydı aynı ayın toplamı iki kullanıcıda iki
farklı sayı gösterirdi. Karar `service.py`de gerekçeli ve testle kilitlidir.

`GET` uçları `record_audit` ÇAĞIRMAZ (WORKFLOW kuralı — okumalar denetlenmez);
üç yazma ucunun her biri TEK denetim satırı yazar ve metin servis katmanında
kurulur.

## Bu dilimde AÇILMAYAN uçlar (icat yasağı)

Satır/dönem onayı · ödeme damgası · SGK özeti ve damgası · oran yönetimi ·
Excel export **T4-T5'in işidir** (spec §5). EFT talimatı (BY 319), makbuz
(BY 328) ve SGK'ya gerçek gönderim (SGK 44) HİÇBİR dilimde açılmaz (spec §1).
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
from app.modules.audit import messages
from app.modules.audit.models import AuditAction
from app.modules.audit.service import record_audit
from app.modules.payroll import service
from app.modules.payroll.schemas import (
    PayrollComputeResult,
    PayrollLineResponse,
    PayrollLineUpdate,
    PayrollPeriodApproveResult,
    PayrollPeriodCreate,
    PayrollPeriodDetailResponse,
    PayrollPeriodListResponse,
    PayrollPeriodPayResult,
)
from app.modules.users.models import User

router = APIRouter(tags=["payroll"], responses=COMMON_ERROR_RESPONSES)

_VIEW = require_permission(service.PERMISSION_MODULE, AccessLevel.view)
_FULL = require_permission(service.PERMISSION_MODULE, AccessLevel.full)

# TB3 sayfalama standardı: varsayılan 50, tavan 200 — aşım sessizce KIRPILMAZ,
# 422 döner (SA/ST ile birebir).
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


@router.get("/payroll/periods", response_model=PayrollPeriodListResponse, dependencies=[_VIEW])
async def list_payroll_periods_endpoint(
    session: Annotated[AsyncSession, Depends(get_db)],
    limit: _LIMIT = 50,
    offset: _OFFSET = 0,
) -> PayrollPeriodListResponse:
    """BG tablosu: dönem · çalışan · brüt · SGK işveren · net · toplam maliyet.

    En YENİ dönem başta (BG tbody: Temmuz · Haziran · Mayıs). Toplamlar
    TÜREVDİR — dönem tablosunda toplam kolonu yoktur (models.py: iki gerçek
    kaynak doğar ve `compute` sonrası sessizce çelişirdi).

    "Çalışan" sütunu dönemin TÜM satırlarını sayar (taşeron dahil, BY tfoot
    48 = 12+29+5+2); BY 71'in kart sayısı ise yalnız ÖDENEBİLİR satırlardır.
    """
    return await service.list_periods(session, limit=limit, offset=offset)


@router.post(
    "/payroll/periods",
    response_model=PayrollPeriodDetailResponse,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"description": "Bu ay için bordro dönemi zaten açılmış"}},
    dependencies=[_FULL],
)
async def create_payroll_period_endpoint(
    request: Request,
    data: PayrollPeriodCreate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> PayrollPeriodDetailResponse:
    """Ay AÇAR, doldurmaz — satırlar `compute` ucundan gelir.

    Var olan ay **409**dur (UQ `(year, month)`, spec §4). Yeni dönem HER ZAMAN
    `draft`tır; gövdeden durum alınmaz (`extra="forbid"`).
    """
    period, detail = await service.create_period(session, data)
    await _audit(request, session, user, AuditAction.create, detail)
    return await service.get_period_detail(session, period.id)


@router.get(
    "/payroll/periods/{period_id}",
    response_model=PayrollPeriodDetailResponse,
    dependencies=[_VIEW],
)
async def get_payroll_period_endpoint(
    period_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> PayrollPeriodDetailResponse:
    """BY ekranı: dört özet kartı (69-93) + tip bazında gruplanmış satırlar.

    🔴 İlk üç kart ÖDEME tabanını gösterir (`excluded` taşeron ve `uncomputed`
    satırlar HARİÇ, K2/S4); dördüncü kart MALİYET tabanını (`excluded` DAHİL) ve
    hesabı **`brüt + SGK işveren + işsizlik işveren + kısa çalışma`**dır
    (spec §7) — BY 92'nin "SGK işveren payı dahil" ETİKETİ mockup'tan, HESAP
    spec'ten gelir.

    Görünmeyen dönem var olmayanla AYNI 404'ü alır.
    """
    return await service.get_period_detail(session, period_id)


@router.post(
    "/payroll/periods/{period_id}/compute",
    response_model=PayrollComputeResult,
    responses={409: {"description": "Onaylanmış veya ödenmiş dönem yeniden hesaplanamaz"}},
    dependencies=[_FULL],
)
async def compute_payroll_period_endpoint(
    request: Request,
    period_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> PayrollComputeResult:
    """Puantaj + ücret + oranlardan satırları üretir/günceller (T2 akışı).

    Elle düzeltilmiş (`is_overridden`, S6) ve onaylı/ödenmiş (S5) satırlar
    KORUNUR ve **sayıyla raporlanır** — sessiz atlama yoktur (WORKFLOW §3).
    Dönem `approved`/`paid` ise **409**.
    """
    sonuc = await service.compute_period(session, period_id)
    period = await service.get_period(session, period_id)
    await _audit(
        request,
        session,
        user,
        AuditAction.update,
        messages.payroll_period_computed(period.year, period.month),
    )
    return sonuc


@router.patch(
    "/payroll/lines/{line_id}",
    response_model=PayrollLineResponse,
    responses={
        409: {"description": "Onaylanmış/ödenmiş satır ya da taşeron satırı değiştirilemez"},
        422: {"description": "Banka + elden toplamı nete eşit değil ya da oran seti yok"},
    },
    dependencies=[_FULL],
)
async def update_payroll_line_endpoint(
    request: Request,
    line_id: uuid.UUID,
    data: PayrollLineUpdate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> PayrollLineResponse:
    """Brüt override (K3) + banka/elden bölüşümü (S3) — BY 142-147.

    * **S3 (spec §6/1):** `banka + elden ≠ net` → **422**, KURUŞ kaymasında da
      (`Decimal`; `float` karşılaştırması yapılmaz). İki alan BİRLİKTE gönderilir.
    * **S5 (spec §6/4):** `approved`/`paid` satır — ve onaylanmış DÖNEMİN her
      satırı — **409**. Ödeme izi geriye dönük düzeltilmez.
    * **K2 (spec §2):** taşeron (`excluded`) satırı **409** — bordrodan ödenmez,
      bölüşümü de düzenlenmez; çift ödeme yapısal olarak imkânsız kalmalıdır.
    * **K3:** brüt elle değişince iz yazılır (kim/ne zaman/önceki değer) ve
      kesinti/net/bölüşüm `compute.py`nin oran mantığıyla YENİDEN TÜRETİLİR —
      kesinti gövdeden alınmaz.
    """
    satir, detail = await service.update_line(session, user.id, line_id, data)
    await _audit(request, session, user, AuditAction.update, detail)
    return satir


# --- T4: onay + ödeme yolu (spec §5'in 6.-8. satırları) --------------------
#
# | Uç | Yetki | Mockup |
# |---|---|---|
# | `POST /payroll/lines/{id}/approve` · `/reject` | `full` | BY satır durumu |
# | `POST /payroll/periods/{id}/approve` | `full` | BY 303 "Tümünü Onayla" |
# | `POST /payroll/periods/{id}/pay` | `full` | BY 56 "Ödemeyi Onayla" sonrası |
#
# Dördü de `payroll:full`dur: onay ve ödeme İZİN gerektiren PARA olaylarıdır,
# `view` seviyesi yalnız görmeye yeter. Dördü de TEK denetim satırı yazar ve
# `AuditAction.approve` kullanır (`audit/models.py` docstring'i: onay uçları) —
# yalnız RED bir onay değil bir geri alma olduğu için `update`tir.
#
# 🔴 EFT talimatı (BY 319) ve makbuz (BY 328) BU DİLİMDE DE AÇILMAZ (spec §1):
# `/pay` bir DAMGADIR, banka entegrasyonu yoktur.


@router.post(
    "/payroll/lines/{line_id}/approve",
    response_model=PayrollLineResponse,
    responses={
        409: {
            "description": (
                "Taşeron satırı, hesaplanamamış satır, zaten onaylı/ödenmiş satır "
                "ya da onaylanmış/ödenmiş dönem"
            )
        }
    },
    dependencies=[_FULL],
)
async def approve_payroll_line_endpoint(
    request: Request,
    line_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> PayrollLineResponse:
    """Satır onayı — `pending → approved`.

    * **🔴 K2 (spec §2, §6/2):** taşeron (`excluded`) satırı **409**. Taşeronun
      ödemesi hakediş (TH) üzerinden yapılır; buradan da onaylanabilseydi aynı
      emek İKİ KEZ ödenirdi. Çift ödeme yapısal olarak imkânsız kalmalıdır.
    * **S4 (spec §6/3):** brütü `null` olan (`uncomputed`) satır **409** —
      "ödenecek bir şey yok" yalanı damgalanmaz; önce brüt girilir.
    * **S8:** `approved`/`paid` satır **409** (atlama ve tekrar yok).
    """
    satir, detail = await service.approve_line(session, line_id)
    await _audit(request, session, user, AuditAction.approve, detail)
    return satir


@router.post(
    "/payroll/lines/{line_id}/reject",
    response_model=PayrollLineResponse,
    responses={409: {"description": "Yalnız onaylanmış satırın onayı geri alınabilir"}},
    dependencies=[_FULL],
)
async def reject_payroll_line_endpoint(
    request: Request,
    line_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> PayrollLineResponse:
    """Satır reddi = ONAYIN GERİ ALINMASI — `approved → pending` (S5 düzeltme yolu).

    Ayrı bir `rejected` durumu YOKTUR: satır durumu kümesi T1'de kapanmıştır.
    Geri alınan satır yeniden düzenlenebilir olur. `pending`/`uncomputed`/
    `paid`/`excluded` satırda **409**.
    """
    satir, detail = await service.reject_line(session, line_id)
    await _audit(request, session, user, AuditAction.update, detail)
    return satir


@router.post(
    "/payroll/periods/{period_id}/approve",
    response_model=PayrollPeriodApproveResult,
    responses={409: {"description": "Dönem onay adımına geçirilemez"}},
    dependencies=[_FULL],
)
async def approve_payroll_period_endpoint(
    request: Request,
    period_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> PayrollPeriodApproveResult:
    """BY 303 "Tümünü Onayla" — dönemi TEK ADIM ilerletir, `pending` satırları onaylar.

    `draft → pending_approval → approved`; **atlama YOKTUR** (S8), üçüncü çağrı
    **409**. Ödeme damgası bu uçtan basılmaz (`/pay` ayrıdır).

    🔴 "Tümünü" onaylamaz: `uncomputed` (S4) ve taşeron (K2) satırlar ATLANIR ve
    yanıtta **sebebe göre ayrı sayılarla** raporlanır — sessiz atlama yoktur
    (WORKFLOW §3).
    """
    sonuc, detail = await service.approve_period(session, user.id, period_id)
    await _audit(request, session, user, AuditAction.approve, detail)
    return sonuc


@router.post(
    "/payroll/periods/{period_id}/pay",
    response_model=PayrollPeriodPayResult,
    responses={409: {"description": "Yalnız onaylanmış dönem ödenebilir"}},
    dependencies=[_FULL],
)
async def pay_payroll_period_endpoint(
    request: Request,
    period_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> PayrollPeriodPayResult:
    """Ödendi damgası (`paid_at`) — dönem ve ONAYLI satırlar `paid`.

    * **S8:** dönem `approved` değilse **409** — `draft → paid` para çıkışının
      onay zincirini atlardı. İkinci `pay` de **409**: ikinci ödeme demektir.
    * **🔴 K2:** taşeron satırı `paid` OLMAZ ve `paid_net_total`a GİRMEZ.
    * Onaylanmamış ve hesaplanamamış satırlar ödenmez, sayıyla raporlanır.

    Dış entegrasyon YOKTUR (spec §1): EFT talimatı gönderilmez.
    """
    sonuc, detail = await service.pay_period(session, period_id)
    await _audit(request, session, user, AuditAction.approve, detail)
    return sonuc
