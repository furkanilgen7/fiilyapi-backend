import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, backref, mapped_column, relationship

from app.core.db import Base
from app.modules.projects.models import Project


class SiteStatus(str, enum.Enum):
    """project_status ile ayni ucludur ama AYRI enum'dur (spec §2.3): sirf bugun
    ayni olduklari icin paylasilan bir enum'a baglamak, santiyeye ileride
    `suspended` gibi bir durum eklemeyi imkansiz kilar."""

    active = "active"
    on_hold = "on_hold"
    completed = "completed"


class SectionStatus(str, enum.Enum):
    planned = "planned"
    active = "active"
    completed = "completed"


class Site(Base):
    """Santiye — proje altindaki ikinci katman (Alt-Proje 2 · P2, spec §2.1).

    `contract_amount` sutunu YOK: isveren sozlesmesi proje duzeyindedir, santiye
    payi BOQ dagitiminin turevidir (spec §2.1). `site_manager_name` FK degil
    serbest metindir — santiye sefi her zaman sistem kullanicisi olmayabilir.
    """

    __tablename__ = "sites"
    __table_args__ = (UniqueConstraint("project_id", "code", name="uq_sites_project_code"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # spec §8 acik soru 2 — oneri uygulandi: kod ZORUNLU, verilmezse ad'dan
    # turetilir (service._derive_code) ve kullanici duzeltebilir.
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    status: Mapped[SiteStatus] = mapped_column(
        Enum(SiteStatus, name="site_status"),
        nullable=False,
        default=SiteStatus.active,
        server_default="active",
    )
    address: Mapped[str | None] = mapped_column(String(300), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    site_manager_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    sections: Mapped[list["Section"]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", order_by="Section.sort_order"
    )
    # backref, Project'e `sites` koleksiyonunu ekler: bagimlilik tek yonlu kalir
    # (projects modulu sites'i import etmez, sites projects'i import eder).
    # lazy="selectin" zorunlu — async oturumda tembel yukleme MissingGreenlet atar.
    project: Mapped[Project] = relationship(
        Project,
        lazy="selectin",
        backref=backref(
            "sites", lazy="selectin", cascade="all, delete-orphan", order_by="Site.code"
        ),
    )


class Section(Base):
    """Bolum — santiyenin ic kirilimi (spec §2.2). ISTEGE BAGLI katmandir:
    santiye sifir bolumle gecerlidir, otomatik "Genel" bolumu ACILMAZ (spec §2.4).

    `budget` sutunu YOK — bolum bedeli BOQ kalemlerinin toplamidir, turevdir.
    """

    __tablename__ = "sections"
    __table_args__ = (
        # Kismi benzersiz indeks: kodsuz bolumler serbestce coklanabilir, kod
        # verilmisse santiye icinde benzersizdir.
        Index(
            "uq_sections_site_code",
            "site_id",
            "code",
            unique=True,
            postgresql_where=text("code IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sites.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    status: Mapped[SectionStatus] = mapped_column(
        Enum(SectionStatus, name="section_status"),
        nullable=False,
        default=SectionStatus.planned,
        server_default="planned",
    )
    manager_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
