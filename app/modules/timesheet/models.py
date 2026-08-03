import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class TimesheetCode(str, enum.Enum):
    """Gun hucresinin kodu (puantaj spec §2).

    E5'in dortlusu (calisti / izinli / tatil / fazla mesai) + SP'nin `G`'si
    (gecici gorev) TEK sette birlestirildi — iki ekran ayni enum'u kullanir.

    Yarim gun / rapor kodu YOKTUR (mockup'ta yok, spec §5) — ileride enum
    genisletmesiyle eklenir.
    """

    worked = "worked"
    leave = "leave"
    holiday = "holiday"
    overtime = "overtime"
    temporary_duty = "temporary_duty"


class TimesheetEntry(Base):
    """Gun x kisi puantaj hucresi (puantaj spec §2).

    UQ (personnel_id, work_date): bir kisi bir gunde TEK yerdedir — iki santiyenin
    ayni gun ayni isciyi yazmasi bu kisitla engellenir (santiye cakismasi).

    `project_id` santiyeden turetilebilir ama her matris sorgusunda JOIN
    gerektirirdi — `visible_projects` suzgeci icin santiyeden KOPYALANIR
    (site_diary / taseron hakedisi deseni).

    Kisi/gun toplamlari (adam-gun, gunluk sayi, FM saat toplami) TUREVDIR —
    toplam kolonu ACILMAZ (diary deseni).

    Onay/durum kolonu YOKTUR (spec §7 S3): duz kaydet + audit izi.
    """

    __tablename__ = "timesheet_entries"
    __table_args__ = (
        UniqueConstraint("personnel_id", "work_date", name="uq_timesheet_entries_personnel_date"),
        # FM saati OPSIYONELDIR (spec §7 S2). Girildiyse anlamli olmalidir: sifir ya
        # da negatif "fazla mesai" yoktur ve bir gun 24 saatten uzun degildir.
        CheckConstraint(
            "overtime_hours IS NULL OR (overtime_hours > 0 AND overtime_hours <= 24)",
            name="ck_timesheet_entries_overtime_hours_range",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # RESTRICT: puantaji olan personel silinemez (spec §3 — silme yok, pasiflestirme var).
    personnel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("personnel.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
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
    # SET NULL: bolum silinse de puantaj hucresi ayakta kalir (bilgi/suzgec alani).
    section_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sections.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    work_date: Mapped[date] = mapped_column(Date, nullable=False)
    code: Mapped[TimesheetCode] = mapped_column(
        Enum(TimesheetCode, name="timesheet_code"), nullable=False
    )
    overtime_hours: Mapped[Decimal | None] = mapped_column(Numeric(4, 1), nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
