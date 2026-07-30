from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.core.errors import (
    BoqGroupSiteMismatchError,
    DeleteNotAllowedError,
    DomainError,
    DuplicateError,
    NotFoundError,
    PermissionLockedError,
    ProjectTypeMismatchError,
    ProjectValidationError,
    RelatedRecordsExistError,
    UnitValidationError,
)


async def _permission_locked_handler(request: Request, exc: PermissionLockedError) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content={"detail": str(exc)})


async def _delete_not_allowed_handler(request: Request, exc: DeleteNotAllowedError) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content={"detail": str(exc)})


async def _not_found_handler(request: Request, exc: NotFoundError) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exc)})


async def _project_type_mismatch_handler(
    request: Request, exc: ProjectTypeMismatchError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content={"detail": str(exc)}
    )


async def _project_validation_handler(
    request: Request, exc: ProjectValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content={"detail": str(exc)}
    )


async def _duplicate_error_handler(request: Request, exc: DuplicateError) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": str(exc)})


async def _related_records_exist_handler(
    request: Request, exc: RelatedRecordsExistError
) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": str(exc)})


async def _boq_group_site_mismatch_handler(
    request: Request, exc: BoqGroupSiteMismatchError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content={"detail": str(exc)}
    )


async def _unit_validation_handler(request: Request, exc: UnitValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content={"detail": str(exc)}
    )


async def _domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"detail": str(exc)})


async def _integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT, content={"detail": "Veri bütünlüğü hatası"}
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Alan hatalarını uygun HTTP koduna çeviren handler'ları kaydeder.

    Daha spesifik alt sınıflar önce kaydedilir; FastAPI istisna tipini tam eşleşmeyle
    bulamazsa MRO üzerinden yukarı çıkar, bu yüzden `DomainError` en genel yedek olarak
    en sonda kalmalıdır.
    """
    app.add_exception_handler(PermissionLockedError, _permission_locked_handler)
    app.add_exception_handler(DeleteNotAllowedError, _delete_not_allowed_handler)
    app.add_exception_handler(NotFoundError, _not_found_handler)
    app.add_exception_handler(ProjectTypeMismatchError, _project_type_mismatch_handler)
    app.add_exception_handler(ProjectValidationError, _project_validation_handler)
    app.add_exception_handler(DuplicateError, _duplicate_error_handler)
    app.add_exception_handler(RelatedRecordsExistError, _related_records_exist_handler)
    app.add_exception_handler(BoqGroupSiteMismatchError, _boq_group_site_mismatch_handler)
    app.add_exception_handler(UnitValidationError, _unit_validation_handler)
    app.add_exception_handler(DomainError, _domain_error_handler)
    app.add_exception_handler(IntegrityError, _integrity_error_handler)
