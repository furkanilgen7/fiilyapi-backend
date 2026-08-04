"""Belge modülünün FastAPI bağımlılıkları — depolama dikişi burada durur.

Uçlar ve servis katmanı somut `DbStorageBackend`i ASLA import etmez; ihtiyaç
duydukları tip `StorageBackend` arayüzüdür ve örneği buradan gelir. R2/S3'e
geçiş bu dosyadaki TEK satırın değişmesidir (spec §7 S1'in "tek sınıf" sözü).

Testler `app.dependency_overrides[get_storage_backend]` ile sahte bir backend
takar — kanıt `tests/documents/test_storage_backend.py`.
"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.modules.documents.storage import DbStorageBackend, StorageBackend


def get_storage_backend(session: Annotated[AsyncSession, Depends(get_db)]) -> StorageBackend:
    """İstek başına depolama backend'i.

    Dönüş tipi bilinçli olarak ARAYÜZDÜR: bağımlılığı kullanan kod somut tipi
    tip düzeyinde de görmez, dolayısıyla ona bağlanamaz.
    """
    return DbStorageBackend(session)
