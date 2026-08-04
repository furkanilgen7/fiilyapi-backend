"""Belge arşivi veri erişimi — yalnız SQL, yetki/kapsam kararı YOK.

Kapsam süzgeci (`visible_projects`) bu katmanda DEĞİL `service.py`dedir
(`site_planning/repository.py` deseninin kardeşi).

Bu dosyada `document_blobs` GEÇMEZ: baytlara erişim tek bir yerdedir
(`storage.py`). Künye ve klasör sorguları blob tablosuna asla dokunmaz —
`tests/documents/test_blob_isolation.py` bunu SQL düzeyinde dondurur.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.documents.models import Document, DocumentFolder


async def list_folders(
    session: AsyncSession, project_id: uuid.UUID, site_id: uuid.UUID | None
) -> list[DocumentFolder]:
    """Bir KAPSAMIN klasörleri — DÜZ liste, hiyerarşiyi `parent_id` taşır.

    `site_id is None` demek "proje düzeyi klasörler" demektir, "hepsi" DEĞİL
    (kararın gerekçesi `service.list_folders` docstring'indedir); bu yüzden
    koşul `IS NULL`dır, süzgecin atlanması değil.

    Sıralama DB'de yapılır — liste her yenilendiğinde aynı sırada gelmelidir.
    """
    stmt = (
        select(DocumentFolder)
        .where(
            DocumentFolder.project_id == project_id,
            DocumentFolder.site_id.is_(None)
            if site_id is None
            else DocumentFolder.site_id == site_id,
        )
        .order_by(DocumentFolder.name)
    )
    return list((await session.execute(stmt)).scalars().all())


async def get_folder(session: AsyncSession, folder_id: uuid.UUID) -> DocumentFolder | None:
    return await session.get(DocumentFolder, folder_id)


async def find_folder_by_name(
    session: AsyncSession,
    project_id: uuid.UUID,
    site_id: uuid.UUID | None,
    parent_id: uuid.UUID | None,
    name: str,
    *,
    exclude_id: uuid.UUID | None = None,
) -> DocumentFolder | None:
    """UQ ile BİREBİR aynı dörtlü üzerinden mevcut-ad kontrolü.

    NULL karşılaştırmaları `IS NULL` ile yazılır: `== None` SQL'de `= NULL`
    üretseydi proje düzeyi kök klasörlerde kontrol HİÇBİR ŞEY bulamaz ve DB
    kısıtının çalışmadığı tam o dalda tekillik tamamen kaybolurdu.

    `exclude_id` PATCH içindir: kaydın KENDİSİ çakışma sayılmaz, aksi hâlde aynı
    adla ikinci kez "Kaydet" basmak 409 verirdi.
    """
    stmt = select(DocumentFolder).where(
        DocumentFolder.project_id == project_id,
        DocumentFolder.site_id.is_(None) if site_id is None else DocumentFolder.site_id == site_id,
        DocumentFolder.parent_id.is_(None)
        if parent_id is None
        else DocumentFolder.parent_id == parent_id,
        DocumentFolder.name == name,
    )
    if exclude_id is not None:
        stmt = stmt.where(DocumentFolder.id != exclude_id)
    return (await session.execute(stmt.limit(1))).scalars().first()


async def lock_folder_for_update(session: AsyncSession, folder_id: uuid.UUID) -> None:
    """Silme yolunun DIŞLAYICI kilidi (`FOR UPDATE`).

    `lock_folder_shared` ile birlikte "boş mu?" kontrolü ile `DELETE` arasındaki
    yarışı kapatır: alt klasör açan istek aynı satırı PAYLAŞIMLI kilitler, iki
    kilit çakışır ve işlemler sıraya girer. Kilitsiz bırakılsaydı iki eşzamanlı
    istek klasörü hem "boş" görüp silebilir hem de içine kayıt yazabilirdi.
    """
    await session.execute(
        select(DocumentFolder.id).where(DocumentFolder.id == folder_id).with_for_update()
    )


async def lock_folder_shared(session: AsyncSession, folder_id: uuid.UUID) -> None:
    """Alt kayıt ekleyen yolun PAYLAŞIMLI kilidi (`FOR SHARE`).

    ⚠️ T3 NOTU: belge yükleme ucu bir klasöre künye yazarken AYNI çağrıyı
    yapmalıdır. Yapmazsa "boş klasör" kontrolü ile silme arasındaki pencerede
    yüklenen belge, klasörü silinmiş hâlde bulur (`folder_id` SET NULL ile
    kapsamın köküne düşer — sessiz veri kayması).
    """
    await session.execute(
        select(DocumentFolder.id).where(DocumentFolder.id == folder_id).with_for_update(read=True)
    )


async def folder_has_children(session: AsyncSession, folder_id: uuid.UUID) -> bool:
    stmt = (
        select(func.count())
        .select_from(DocumentFolder)
        .where(DocumentFolder.parent_id == folder_id)
    )
    return bool((await session.execute(stmt)).scalar_one())


async def folder_has_documents(session: AsyncSession, folder_id: uuid.UUID) -> bool:
    stmt = select(func.count()).select_from(Document).where(Document.folder_id == folder_id)
    return bool((await session.execute(stmt)).scalar_one())
