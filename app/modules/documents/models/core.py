"""Belge arşivi çekirdeği — klasör + künye + ikili içerik (spec §2).

ÜÇ TABLO, BİLİNÇLİ AYRIM:
  * `document_folders` — serbest klasör ağacı (otomatik kategori seed'i YOK, §7 S3)
  * `documents` — KÜNYE; liste/arama sorguları YALNIZ buna dokunur
  * `document_blobs` — baytlar; künyeden ayrı tutulur ki 48 MB'lık sütun liste
    sorgularına girmesin ve TOAST şişmesi izole kalsın (§7 S1)

Kapsam dışı (spec §1/§5, kasıtlı): versiyon tablosu YOK (mockup versiyonu yalnız
dosya ADINDA taşır — "Rev3"/"v4") · onay akışı YOK · etiket YOK ·
thumbnail/önizleme YOK · form belge-slot tablosu YOK.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class DocumentFolder(Base):
    """Klasör — proje ya da şantiye düzeyinde, serbest adlandırmalı (spec §2).

    `site_id IS NULL` = PROJE DÜZEYİ klasör (E12'nin kökü proje/şantiye ikilisidir).
    `parent_id` self-FK'dır: UI iki seviye gösterir, model N-seviyeyi YASAKLAMAZ.
    Üst klasör silinirse alt klasör SET NULL ile köke düşer — ağaç silme, veri
    kaybına dönüşmez.

    UQ (project_id, site_id, parent_id, name): aynı kapsamda aynı adlı iki klasör
    açılamaz. BİLİNEN SINIR — Postgres'in varsayılan `NULLS DISTINCT` semantiği
    yüzünden `site_id`/`parent_id` NULL olan dalda (proje düzeyi kök klasörler)
    kısıt fiilen İŞLEMEZ; `SitePlanRow.section_id` NULL dalıyla aynı durum.
    Tekillik o dalda yazma ucunun (T2: mevcut-ad kontrolü → 409) sorumluluğundadır.
    """

    __tablename__ = "document_folders"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "site_id",
            "parent_id",
            "name",
            name="uq_document_folder_scope_name",
        ),
        Index("ix_document_folders_project_site", "project_id", "site_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sites.id", ondelete="CASCADE"),
        nullable=True,
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("document_folders.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    # Kullanıcı silinse de klasör ayakta kalır (arşiv kaydı kişiye bağlı değildir).
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Document(Base):
    """Belge KÜNYESİ — baytlar burada DEĞİL, `document_blobs`ta (spec §2).

    `project_id`/`site_id` görünürlük süzgecinin (`visible_projects`) kapsamıdır;
    klasörden türetilebilirdi ama her liste sorgusunda JOIN gerektirirdi —
    site_diary/puantaj deseniyle aynı şekilde KOPYALANIR. `folder_id` SET NULL:
    klasör silinince belge kaybolmaz, kapsamın köküne düşer.

    `uploaded_by_name` bir SNAPSHOT'tır (SB144 "Şantiye Şefi: S. Öztürk"):
    kullanıcı silinse ya da adı değişse bile arşiv kaydı ne yazıyorsa odur.

    **`DocumentBlob` ile ilişki TANIMLANMAZ** — kasıtlı. Bir `relationship`,
    ileride biri `lazy` değerini değiştirdiğinde tüm liste sorgularına 48 MB'lık
    bayt sütununu sokabilir. Baytlara erişim T2'deki `StorageBackend`in açık
    sorgusuyla olur; kanıt: `tests/documents/test_blob_isolation.py`.
    """

    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_project_site", "project_id", "site_id"),
        Index("ix_documents_folder_id", "folder_id"),
        # "Son Eklenenler" sıralaması (spec §3) — tarama yerine indeks.
        Index("ix_documents_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    folder_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("document_folders.id", ondelete="SET NULL"),
        nullable=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sites.id", ondelete="CASCADE"),
        nullable=True,
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    # BigInteger: 50 MB int32'ye sığar ama sınır config'ten gelir ve büyüyebilir.
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # SB alt-satırının serbest metni ("48 fotoğraf", "Aylık denetim").
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploaded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    uploaded_by_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class DocumentBlob(Base):
    """Belgenin baytları — künyeden AYRI tablo (spec §2 / §7 S1).

    `document_id` hem PK hem FK'dır: belge başına en fazla bir içerik, künye
    silinince CASCADE ile birlikte gider (yetim bayt kalmaz).

    v1 depolama DB'dir; T2'de gelecek `StorageBackend` soyutlaması sayesinde
    R2/S3'e geçiş TEK sınıf değişimidir — künye şeması değişmez.
    """

    __tablename__ = "document_blobs"

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        primary_key=True,
    )
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
