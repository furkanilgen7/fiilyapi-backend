import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.company import repository
from app.modules.company.models import Company
from app.modules.company.schemas import CompanyUpdate

_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]")


def safe_logo_filename(filename: str | None) -> str:
    """Content-Disposition basligina guvenli sekilde konacak dosya adini uretir.

    Istemci-saglamali dosya adindaki tirnak/CRLF/kontrol karakterleri header enjeksiyonuna
    yol acabilir; guvenli karakter kumesi disindaki her sey alt-cizgiyle degistirilir.
    Bos/gecersiz ad 'logo' olur."""
    if not filename:
        return "logo"
    cleaned = _SAFE_FILENAME.sub("_", filename).strip("._") or "logo"
    return cleaned


async def get_company(session: AsyncSession) -> Company:
    return await repository.get_or_create_singleton(session)


async def update_company(session: AsyncSession, data: CompanyUpdate) -> Company:
    company = await repository.get_or_create_singleton(session)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(company, field, value)
    await session.flush()
    return company


def logo_signature_matches(content_type: str, data: bytes) -> bool:
    """Yuklenen ikili verinin, bildirilen MIME tipiyle gercekten eslesip eslesmedigini
    magic-byte imzasiyla dogrular. Istemcinin bildirdigi content_type'a korU korune guvenmez."""
    if content_type == "image/png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type == "image/jpeg":
        return data.startswith(b"\xff\xd8\xff")
    if content_type == "image/webp":
        return len(data) >= 12 and data[0:4] == b"RIFF" and data[8:12] == b"WEBP"
    if content_type == "image/svg+xml":
        head = data[:1024].lstrip().lower()
        return head.startswith(b"<?xml") or head.startswith(b"<svg")
    return False


async def set_logo(
    session: AsyncSession, content_type: str, filename: str | None, data: bytes
) -> Company:
    return await repository.set_logo(session, content_type, filename, data)


async def clear_logo(session: AsyncSession) -> Company:
    return await repository.clear_logo(session)
