import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import AccessLevel
from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.errors import UnitValidationError
from app.core.openapi import COMMON_ERROR_RESPONSES
from app.core.permissions import require_permission
from app.core.ratelimit import client_ip
from app.modules.audit.models import AuditAction
from app.modules.audit.service import record_audit
from app.modules.units import batch, importer, service
from app.modules.units.models import UnitKind, UnitSalesStatus
from app.modules.units.schemas import (
    BlockCreate,
    BlockListResponse,
    BlockResponse,
    BlockUpdate,
    UnitAllocationRequest,
    UnitBulkCreate,
    UnitBulkPreview,
    UnitCreate,
    UnitImportResult,
    UnitImportValidation,
    UnitListResponse,
    UnitOwnerSideFilter,
    UnitResponse,
    UnitUpdate,
)
from app.modules.users.models import User

# Uclar iki ayri kok altina dagilir (P4 deseni): proje baglamli uclar
# `/projects/...`, kimligi yukari cozumleyen tekil uclar `/blocks/...` ve
# `/units/...` altindadir — bu yuzden router prefix TASIMAZ.
#
# BFF TUZAGI (frontend dilimi icin): IKI kok var, `units` VE `blocks`. Ikisi de
# `src/app/api/backend/[...path]/route.ts` ALLOWED_ROOTS listesine eklenmezse
# ilgili modul YALNIZ CANLIDA 404 verir.
router = APIRouter(tags=["units"], responses=COMMON_ERROR_RESPONSES)

# Spec §8: YENI IZIN MODULU ACILMAZ — blok ve unite projenin alt kayitlaridir,
# `projects` modulunun seviyeleri kullanilir. Modul sayisi 17'de kalir.
_VIEW = require_permission("projects", AccessLevel.view)
# Yazma uclari `full` ister (spec §8): `view` yetmez (IDOR-13).
_FULL = require_permission("projects", AccessLevel.full)
# KULLANICI KARARI 2026-07-30: SILME uclari bir seviye yukaridadir. `full`
# yazmayi kapsar, SILMEYI KAPSAMAZ (`app/core/access.py` §5.0).
_ADMIN = require_permission("projects", AccessLevel.admin)


async def _audit(
    request: Request,
    session: AsyncSession,
    user: User,
    action: AuditAction,
    detail: str,
) -> None:
    """Denetim satiri (spec §9, B5 deseni).

    Metin servis katmanindan HAZIR gelir: silme uclarinda adlar kayit yok
    olmadan once okunmak zorundadir ve router onlari sonradan hicbir sorguyla
    geri getiremez (bkz. `service.py` §9 notu). Yalniz YAZMA uclari cagirir —
    okuma uclari denetim satiri URETMEZ (P4 T7 kurali).

    `record_audit` commit etmez: satir asil islemle AYNI transaction'a girer,
    dolayisiyla reddedilen (409/422) bir istek denetim satiri da birakmaz.
    """
    await record_audit(
        session,
        action=action,
        detail=detail,
        actor_user_id=user.id,
        ip_address=client_ip(request),
    )


@router.get("/projects/{project_id}/blocks", response_model=BlockListResponse, dependencies=[_VIEW])
async def list_blocks_endpoint(
    project_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> BlockListResponse:
    """Spec §7.1. Blok seciciler (unite formu, toplu uretim formu) bu ucu kullanir."""
    return await service.list_blocks(session, user, project_id)


@router.get("/projects/{project_id}/units", response_model=UnitListResponse, dependencies=[_VIEW])
async def list_units_endpoint(
    project_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    block_id: Annotated[uuid.UUID | None, Query()] = None,
    site_id: Annotated[uuid.UUID | None, Query()] = None,
    kind: Annotated[UnitKind | None, Query()] = None,
    owner_side: Annotated[UnitOwnerSideFilter | None, Query()] = None,
    floor: Annotated[str | None, Query(max_length=20)] = None,
    sales_status: Annotated[UnitSalesStatus | None, Query()] = None,
) -> UnitListResponse:
    """Spec §7.4. Suzgecler YALNIZ listeyi daraltir; `totals` daima projenin
    tamamini sayar. `site_id` blok uzerinden cozulur (`units`'te `site_id` yok)."""
    return await service.list_units(
        session,
        user,
        project_id,
        block_id=block_id,
        site_id=site_id,
        kind=kind,
        owner_side=owner_side,
        floor=floor,
        sales_status=sales_status,
    )


@router.post(
    "/projects/{project_id}/blocks",
    response_model=BlockResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_FULL],
)
async def create_block_endpoint(
    request: Request,
    project_id: uuid.UUID,
    data: BlockCreate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> BlockResponse:
    """Spec §7.2. Tek santiyeli projede `site_id` gonderilmezse otomatik atanir
    (§4.5) — mockup'ta santiye secici yoktur (KY 38 / KK 39)."""
    block, detail = await service.create_block(session, user, project_id, data)
    await _audit(request, session, user, AuditAction.create, detail)
    return await service.block_response(session, block)


@router.patch("/blocks/{block_id}", response_model=BlockResponse, dependencies=[_FULL])
async def update_block_endpoint(
    request: Request,
    block_id: uuid.UUID,
    data: BlockUpdate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> BlockResponse:
    """Spec §7.3. Kimlik YUKARI cozumlenir (blok → proje → gorunurluk);
    gorunmeyen projenin blogu 404 doner, 403 DEGIL."""
    block, detail = await service.update_block(session, user, block_id, data)
    await _audit(request, session, user, AuditAction.update, detail)
    return await service.block_response(session, block)


@router.post(
    "/projects/{project_id}/units",
    response_model=UnitResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_FULL],
)
async def create_unit_endpoint(
    request: Request,
    project_id: uuid.UUID,
    data: UnitCreate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> UnitResponse:
    """Spec §7.5. Govdedeki `block_id` bu projeye ait olmali (IDOR-9), aksi hâlde 404."""
    unit, detail = await service.create_unit(session, user, project_id, data)
    await _audit(request, session, user, AuditAction.create, detail)
    return await service.unit_response(session, unit)


@router.patch("/units/{unit_id}", response_model=UnitResponse, dependencies=[_FULL])
async def update_unit_endpoint(
    request: Request,
    unit_id: uuid.UUID,
    data: UnitUpdate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> UnitResponse:
    """Spec §7.6. Kimlik YUKARI cozumlenir (unite → proje → gorunurluk);
    `block_id` ile ayni proje icinde tasima serbesttir."""
    unit, detail = await service.update_unit(session, user, unit_id, data)
    await _audit(request, session, user, AuditAction.update, detail)
    return await service.unit_response(session, unit)


@router.delete("/units/{unit_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[_ADMIN])
async def delete_unit_endpoint(
    request: Request,
    unit_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Spec §7.9. Unite silme kosulsuzdur (P3'te uniteye bagli tablo yok, §1.3).

    KULLANICI KARARI 2026-07-30: kapi `_ADMIN`'dir, PATCH'ten (`_FULL`) BIR
    SEVIYE YUKARI — `app/core/access.py`: "full silmeyi KAPSAMAZ — silme
    yalnizca admin seviyesindedir". `users`/`roles`/sirket logosu DELETE
    uclariyla tutarlilik saglanir.

    BILINEN SONUC (kabul edildi): seed matrisinde `projects:admin` yalniz
    `system_admin`'dedir; proje muduru dahil kimse silemez.

    Gorunurluk kurali DEGISMEDI (gorunmeyen projenin unitesi 404, 403 degil)
    fakat `projects:admin` gorunurluk suzgecini zaten atladigindan (spec §5.2)
    bu dalin HTTP uzerinden ULASILABILIR bir senaryosu kalmamistir; kural
    `guards.visible_unit`'te ve PATCH ucunda (hâlâ `full`) yerinde durur."""
    detail = await service.delete_unit(session, user, unit_id)
    await _audit(request, session, user, AuditAction.delete, detail)


@router.delete("/blocks/{block_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[_ADMIN])
async def delete_block_endpoint(
    request: Request,
    block_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Spec §7.9. CASCADE YOK: unitesi olan blok 409 ile reddedilir — 24 daireyi
    tek istekte silmek geri alinamaz veri kaybidir.

    KULLANICI KARARI 2026-07-30: kapi `_ADMIN`'dir (bkz. `delete_unit_endpoint`
    gerekcesi) — `app/core/access.py`: "full silmeyi KAPSAMAZ". Yetki kapisi
    409 korkulugundan ONCE calisir: yetkisiz aktor 403 alir, blogun unite
    tasiyip tasimadigini OGRENEMEZ."""
    detail = await service.delete_block(session, user, block_id)
    await _audit(request, session, user, AuditAction.delete, detail)


@router.post(
    "/projects/{project_id}/units/bulk",
    response_model=UnitListResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_FULL],
)
async def bulk_create_units_endpoint(
    request: Request,
    project_id: uuid.UUID,
    data: UnitBulkCreate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> UnitListResponse:
    """Spec §7.7. HEP-YA-HIC: uretilen numaralardan biri bile blokta varsa
    HICBIRI yazilmaz (409). Yanit guncel tam listedir — ekran tabloyu yeniden
    cizer, ikinci bir GET'e gerek kalmaz.

    Denetim: 24 unite uretilse de ISTEK BASINA TEK satir yazilir (spec §9)."""
    result, detail = await batch.bulk_create_units(session, user, project_id, data)
    await _audit(request, session, user, AuditAction.create, detail)
    return result


@router.post(
    "/projects/{project_id}/units/bulk/preview",
    response_model=UnitBulkPreview,
    dependencies=[_FULL],
)
async def preview_bulk_units_endpoint(
    project_id: uuid.UUID,
    data: UnitBulkCreate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> UnitBulkPreview:
    """Spec §5.4 (TU 159-182). **HICBIR SEY YAZMAZ** ve **DENETIM URETMEZ**.

    `dry_run` bayragi yerine AYRI UC olmasinin uc gerekcesi (spec §5.4):
    1. Yanit sekilleri farklidir — gercek uretim `201 UnitListResponse` doner;
       onizlemede `id`'si olan unite yoktur. Tek uc `response_model`'i bir
       `Union`'a zorlar ve `gen:api` ciktisinda sessiz `undefined` sinifi dogar.
    2. Denetim ayrimi temiz kalir: "yazan uc denetim yazar" kurali bir bayraga
       BAGLI HALE GELMEZ. Bu yuzden bu fonksiyon `_audit` CAGIRMAZ ve `Request`
       parametresi bile ALMAZ — denetim yazmak icin gereken IP bu ucta yoktur.
    3. Uretim mantigi tek kopyadir: iki uc da `bulk.generate_units`'i cagirir.

    Izin `full` KALIR: onizleme yazma akisinin parcasidir ve `view` kullanicisina
    fiyat uretim kurallarini acmaz. Cakisma HATA DEGILDIR (TU 177) — satirlar
    `conflict=true` ile 200 doner; blokaj yalniz `POST …/units/bulk`'tadir (409).
    """
    return await batch.preview_bulk_units(session, user, project_id, data)


@router.patch(
    "/projects/{project_id}/units/allocation",
    response_model=UnitListResponse,
    dependencies=[_FULL],
)
async def update_allocation_endpoint(
    request: Request,
    project_id: uuid.UUID,
    data: UnitAllocationRequest,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> UnitListResponse:
    """Spec §7.10 (KKP 25). Paylar TOPLU URETIMDE atanmaz, SONRADAN bu ucla
    girilir: paylasim noterden sonra belli olur (KKP 78).

    ATOMIK: tek satir bile reddedilirse hicbiri yazilmaz. Listedeki bir unite
    BASKA projeye aitse 404 doner (IDOR-8) ve bu projenin hicbir satiri
    degismez. Yanit guncel tam listedir — ekran tabloyu yeniden cizer.

    Denetim: 42 unitelik bir kayit TEK satir yazar (spec §9) — satir basina
    gunluk, denetim gunlugunu okunamaz hâle getirirdi.
    """
    result, detail = await batch.update_allocation(session, user, project_id, data)
    await _audit(request, session, user, AuditAction.update, detail)
    return result


@router.post(
    "/projects/{project_id}/units/import/validate",
    response_model=UnitImportValidation,
    dependencies=[_FULL],
)
async def validate_import_endpoint(
    project_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    file: Annotated[UploadFile, File()],
    site_id: Annotated[uuid.UUID | None, Form()] = None,
    include_warnings: Annotated[bool, Form()] = True,
) -> UnitImportValidation:
    """Spec §6.2 (EI 92-197, "Yeniden Doğrula"). **HICBIR SEY YAZMAZ.**

    `bulk/preview` ile AYNI uc gerekceyle ayri uctur (`dry_run` bayragi DEGIL):
    1. Yanit sekli farklidir (`UnitImportValidation` != `UnitImportResult`); tek
       uc `response_model`'i bir `Union`'a zorlar ve `gen:api` ciktisinda sessiz
       `undefined` sinifi dogar.
    2. Denetim ayrimi temiz kalir: bu fonksiyon `_audit` CAGIRMAZ ve `Request`
       parametresi bile ALMAZ — denetim yazmak icin gereken IP burada YOKTUR.
    3. Kural TEK KOPYADIR: iki uc de `batch._plan_rows`'tan beslenir.

    DOSYA SAKLANMADIGI ICIN (P3 §7.8'in degismeyen siniri) "Yeniden Doğrula →
    Aktar" akisinda dosya IKI KEZ yuklenir. Tarayicida bu bedavadir: `File`
    nesnesi zaten istemcinin bellegindedir. Frontend dilimi bunu bilerek yazar.
    """
    try:
        importer.ensure_xlsx(file.filename)
        importer.ensure_size(file.size)
    except importer.ImportFileError as exc:
        raise UnitValidationError(str(exc)) from exc
    return await batch.validate_import(
        session,
        user,
        project_id,
        await file.read(),
        site_id=site_id,
        include_warnings=include_warnings,
    )


@router.post(
    "/projects/{project_id}/units/import",
    response_model=UnitImportResult,
    dependencies=[_FULL],
)
async def import_units_endpoint(
    request: Request,
    project_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    file: Annotated[UploadFile, File()],
    site_id: Annotated[uuid.UUID | None, Form()] = None,
    include_warnings: Annotated[bool, Form()] = True,
) -> UnitImportResult:
    """Spec §6.1-§6.5. BELGE SAKLAMA ALTYAPISI GEREKMEZ ve kurulmayacaktir: dosya
    bellekte okunur, uniteler yaratilir, dosya ATILIR. Diske, S3'e, veritabanina
    hicbir sey yazilmaz — P3'e sigmasinin tek sebebi budur.

    KISMI AKTARIM (P3'un hep-ya-hic karari BILEREK tersine cevrildi, spec §6.1):
    gecerli satirlar yazilir, hatalilar raporlanir. Hic gecerli satir yoksa 422 —
    `created=0` ile 200 donmek kullanicinin "aktarildi" sanmasina yol acardi.

    `site_id` (EI 61 "Hedef Şantiye", karar 3) YALNIZ yeni blok acarken kullanilir.
    `include_warnings` EI 192 kutucugudur; varsayilani mockup'taki gibi ISARETLIDIR.

    Boyut IKI KEZ olculur: once istemcinin bildirdigi `size` ile (henuz govde
    bellege alinmadan), sonra GERCEKTEN okunan `bytes` uzunluguyla
    (`parse_units_file`) — istemci basligina guvenilmez.
    """
    try:
        importer.ensure_xlsx(file.filename)
        importer.ensure_size(file.size)
    except importer.ImportFileError as exc:
        raise UnitValidationError(str(exc)) from exc
    result, detail = await batch.import_units(
        session,
        user,
        project_id,
        await file.read(),
        site_id=site_id,
        include_warnings=include_warnings,
    )
    await _audit(request, session, user, AuditAction.create, detail)
    return result
