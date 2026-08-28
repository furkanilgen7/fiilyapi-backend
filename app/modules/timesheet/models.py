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
    """Gun hucresinin KOD hali — hucrenin "saat DEGIL" olan halleri (PUAN-SAAT).

    🔴 **Kod artik calisilan gunu ANLATMAZ.** Puantaj gun kodundan adam-saate
    gecti (mockup `Ekran 5 - Puantaj.dc.html`, `5f3a944`): calisilan gun artik
    `hours` kolonudur, kod yalnizca "o gun calisilmadi ama SEBEBI var" halini
    tasir. Mockup'ta `Izin` ve `Gorev` ROZET olarak durur (E5 262/283), calisma
    ise `<input type="number">`tir (E5 236).

    **`worked` ve `overtime` uyeleri KALKTI:**
    * `worked` = "9 saat calisti" → artik `hours = 9`;
    * `overtime` = "9 saat + FM" → artik `hours = 9 + FM`. **FM SAKLANMAZ,
      TUREVDIR** (`hours.week_totals`): haftalik 45 saat tavani ile gunluk 9
      saat tavaninin birlesiminden hesaplanir, bir kolonda duramaz.

    PG enum TIPI (`timesheet_code`) hala bes etiket tasir — PostgreSQL enum
    etiketi SILEMEZ. Olu etiketlerin geri sizmasini `ck_timesheet_entries_code_allowed`
    CHECK'i engeller (DB duzeyinde; uygulama katmani yetmez).

    `holiday` KORUNDU: yeni mockup'ta rozeti yok ama canlida kodu tasiyan satir
    olabilir ve enum uyesini dusurmek o satirlari OKUNAMAZ yapardi.
    """

    leave = "leave"
    holiday = "holiday"
    temporary_duty = "temporary_duty"


class TimesheetEntry(Base):
    """Gun x kisi puantaj hucresi — **saat VEYA kod** (PUAN-SAAT).

    UQ (personnel_id, work_date): bir kisi bir gunde TEK yerdedir — iki santiyenin
    ayni gun ayni isciyi yazmasi bu kisitla engellenir (santiye cakismasi).

    ## 🔴 Hucrenin sozlesmesi: `hours` ile `code`tan TAM BIRI dolu

    `ck_timesheet_entries_hours_xor_code` bunu **DB duzeyinde** zorlar. Uygulama
    korkulugu yetmez (kanon: *"sozlesme kisiti tipte yasamaz"*): iki alani da bos
    birakan bir hucre "gun girildi ama hicbir sey demiyor" olurdu ve haftalik
    toplamlara sessizce 0 katardi; ikisini de dolduran hucre ise ayni gunu hem
    calisilmis hem izinli sayardi.

    Hucre YOKSA o gun **girilmemistir** (mockup E5 242 `placeholder="—"`,
    "Calisilmadi"). Sifir saatli hucre ACILMAZ — `hours > 0` CHECK'i bunu kapatir.

    `project_id` santiyeden turetilebilir ama her matris sorgusunda JOIN
    gerektirirdi — `visible_projects` suzgeci icin santiyeden KOPYALANIR
    (site_diary / taseron hakedisi deseni).

    Kisi/gun toplamlari (normal saat, FM saat, adam-gun) TUREVDIR — toplam
    kolonu ACILMAZ (diary deseni). **FM ozellikle bir kolon DEGILDIR**: haftalik
    kapsamda hesaplanir, gun satirinda anlami yoktur.

    Onay/durum kolonu YOKTUR (spec §7 S3): duz kaydet + audit izi.
    """

    __tablename__ = "timesheet_entries"
    __table_args__ = (
        UniqueConstraint("personnel_id", "work_date", name="uq_timesheet_entries_personnel_date"),
        # Saat anlamli olmalidir: "0 saat calisti" bir hucre DEGIL, hucrenin
        # YOKLUGUDUR; bir gun de 24 saatten uzun degildir.
        CheckConstraint(
            "hours IS NULL OR (hours > 0 AND hours <= 24)",
            name="ck_timesheet_entries_hours_range",
        ),
        # 🔴 Hucrenin TEK sozlesmesi: saat XOR kod.
        CheckConstraint(
            "(hours IS NULL) <> (code IS NULL)",
            name="ck_timesheet_entries_hours_xor_code",
        ),
        # PG enum'dan silinemeyen olu etiketler (`worked`, `overtime`) geri
        # sizamasin: goc sonrasi hicbir satir onlari tasimaz ve tasiyamaz.
        CheckConstraint(
            "code IS NULL OR code IN ('leave', 'holiday', 'temporary_duty')",
            name="ck_timesheet_entries_code_allowed",
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
    #: Calisilan SAAT (mockup E5 236 `<input type="number">`). Kodlu hucrede NULL.
    hours: Mapped[Decimal | None] = mapped_column(Numeric(4, 1), nullable=True)
    #: Calisilmamis gunun SEBEBI (izin / tatil / gecici gorev). Saatli hucrede NULL.
    code: Mapped[TimesheetCode | None] = mapped_column(
        Enum(TimesheetCode, name="timesheet_code"), nullable=True
    )
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
