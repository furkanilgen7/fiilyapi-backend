import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, Enum, ForeignKey, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class ProjectStatus(str, enum.Enum):
    active = "active"
    on_hold = "on_hold"
    completed = "completed"


class ProjectType(str, enum.Enum):
    """Üç iş modeli — kart düzenini ve gelir mantığını belirler (spec §3.1)."""

    taahhut = "taahhut"
    kendi_yatirim = "kendi_yatirim"
    kat_karsiligi = "kat_karsiligi"


class Project(Base):
    """Proje çekirdeği (Alt-Proje 2 · P1). budget/progress_pct F6 mirasıdır, kalır."""

    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    status: Mapped[ProjectStatus] = mapped_column(
        Enum(ProjectStatus, name="project_status"), nullable=False, default=ProjectStatus.active
    )
    project_type: Mapped[ProjectType] = mapped_column(
        Enum(ProjectType, name="project_type"),
        nullable=False,
        default=ProjectType.taahhut,
        server_default="taahhut",
    )
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    contract_no: Mapped[str | None] = mapped_column(String(100), nullable=True)
    contract_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    employer_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    budget: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    progress_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    investment: Mapped["ProjectInvestment | None"] = relationship(
        lazy="selectin", cascade="all, delete-orphan", uselist=False
    )
    land_share: Mapped["ProjectLandShare | None"] = relationship(
        lazy="selectin", cascade="all, delete-orphan", uselist=False
    )
    shareholders: Mapped[list["LandShareShareholder"]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", order_by="LandShareShareholder.name"
    )


class ProjectInvestment(Base):
    """Kendi yatırım uzantısı (1-1). Türev alanlar (satılan, kâr…) P10'un işi."""

    __tablename__ = "project_investment"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    sales_target: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    land_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)


class ProjectLandShare(Base):
    """Kat karşılığı uzantısı (1-1). Arsa maliyeti sütunu YOK — tanım gereği 0 (spec §3.3)."""

    __tablename__ = "project_land_share"
    __table_args__ = (
        CheckConstraint("our_share_pct + owner_share_pct = 100", name="ck_land_share_pct_total"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    landowner_name: Mapped[str] = mapped_column(String(200), nullable=False)
    our_share_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    owner_share_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    contract_no: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notary_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    land_area_m2: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    construction_area_m2: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    daily_penalty: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    guarantee_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)


class LandShareShareholder(Base):
    """Kat karşılığı hissedarı (1-N). Hissedar başına ünite dağılımı P9'un işi."""

    __tablename__ = "land_share_shareholder"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    share_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
