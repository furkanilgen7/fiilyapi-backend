import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class PlanResourceKind(str, enum.Enum):
    """Izgara satirinin kaynak turu (planlama spec §2).

    `crew` = ekip satiri (P126 "Kalipci" — bolum grubu altinda) ·
    `equipment` = P158 "Makine & Ekipman" grubu (P162 "Tower Crane").

    Makine modulu yokken ekipman satiri SERBEST METINDIR (spec §6 S3 onayi):
    ekipman FK'si BU dilimde ACILMAZ, modul gelince kopru ayri istir.
    """

    crew = "crew"
    equipment = "equipment"


class PlanCellTag(str, enum.Enum):
    """Hucrenin renk kodu (planlama spec §2, P127-179).

    Mockup'un rengi YORUMLANMADAN tasinir: kategori/durum ayrimi mockup'ta
    karisik, anlam frontend'de renkle birebir eslesir. `NULL` = renksiz hucre.
    """

    blue = "blue"
    green = "green"
    yellow = "yellow"
    purple = "purple"
    gray = "gray"
    red = "red"


class PlanGoalStatus(str, enum.Enum):
    """Haftalik hedefin rozeti (planlama spec §2, P209-224).

    `is_done` checkbox'i (P207) ile bu rozet mockup'ta AYRI gorunur — ikisi de
    saklanir, birbirine BAGLANMAZ (biri digerini turetmez).
    """

    completed = "completed"
    in_progress = "in_progress"
    waiting = "waiting"
    service_pending = "service_pending"


class SitePlanRow(Base):
    """Haftalik plan izgarasinin satiri — kaynak (spec §2).

    UQ (site_id, kind, section_id, label): ayni bolumun ayni etiketli satiri
    iki kez acilmaz. NOT: Postgres'te NULL'lar catismaz, yani `section_id`
    NULL olan ekipman satirlarinda kisit fiilen ISLEMEZ — tekillik o dalda
    yazma ucunun (PUT rows, DEGISTIRME semantigi) sorumlulugundadir.

    `project_id` santiyeden turetilebilir ama her izgara sorgusunda JOIN
    gerektirirdi — `visible_projects` suzgeci icin santiyeden KOPYALANIR
    (site_diary / puantaj deseni).

    Plan-gerceklesen kiyas kolonu YOKTUR (spec §5 — turev rapor katmani isi).
    """

    __tablename__ = "site_plan_rows"
    __table_args__ = (
        UniqueConstraint(
            "site_id",
            "kind",
            "section_id",
            "label",
            name="uq_site_plan_rows_site_kind_section_label",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sites.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[PlanResourceKind] = mapped_column(
        Enum(PlanResourceKind, name="plan_resource_kind"), nullable=False
    )
    # SET NULL: bolum silinse de plan satiri ayakta kalir (gruplama alani);
    # ekipman satirlarinda ZATEN NULL'dur.
    section_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sections.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    # P126 "(14)" — satir duzeyi planlanan isci sayisi; opsiyonel (ekipmanda yok).
    planned_worker_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SitePlanCell(Base):
    """Izgara hucresi — (satir, gun) ikilisi (spec §2).

    UQ (row_id, plan_date): bir satirin bir gununde TEK hucre. Hucre YOKLUGU =
    o gun icin plan yok — bos metinli hucre yazilmaz.

    `text` metin ne diyorsa odur (P127 "Kat 9 Kalip", P163 "✓ Calisiyor");
    ayristirilmaz. `tag` mockup renginin ham tasiyicisidir.
    """

    __tablename__ = "site_plan_cells"
    __table_args__ = (UniqueConstraint("row_id", "plan_date", name="uq_site_plan_cells_row_date"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    row_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("site_plan_rows.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    plan_date: Mapped[date] = mapped_column(Date, nullable=False)
    text: Mapped[str] = mapped_column(String(200), nullable=False)
    tag: Mapped[PlanCellTag | None] = mapped_column(
        Enum(PlanCellTag, name="plan_cell_tag"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SitePlanGoal(Base):
    """Haftalik hedef (spec §2, P203-227).

    `note` TEK serbest alandir: mockup'un alt satirlari (sorumlu / tarih /
    miktar / bagimlilik) UC FARKLI bicimde gorundugu icin ayri kolonlara
    AYRISTIRILMAZ.

    `week_start` haftanin Pazartesi'sidir; normalizasyon uc katmaninin isidir.
    """

    __tablename__ = "site_plan_goals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sites.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    week_start: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_done: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    status: Mapped[PlanGoalStatus] = mapped_column(
        Enum(PlanGoalStatus, name="plan_goal_status"), nullable=False
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SitePlanSprint(Base):
    """Santiyenin sprint etiketi (spec §2 / §6 S4 onayi; P107 "Kat 8-9 Tamamlama").

    Yalniz AD + AKTIFLIK saklanir. TARIH ALANI YOKTUR (mockup gostermiyor) ve
    "Hafta / Ay / Sprint" GORUNUM KIPI backend'e period-tipi kolonu ACMAZ —
    kip UI isidir.

    Kismi UQ (site_id) WHERE is_active: bir santiyede AYNI ANDA tek aktif
    sprint; gecmis sprintler `is_active = false` olarak yan yana durabilir.
    """

    __tablename__ = "site_plan_sprints"
    __table_args__ = (
        Index(
            "uq_site_plan_sprints_active_site",
            "site_id",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sites.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
