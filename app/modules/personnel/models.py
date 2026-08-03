import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

# Enum PAYLASILIR: `worker_source` DB tipi santiye gunlugu diliminde (b5c6d7e8f9a0)
# yaratildi; personel kaydi AYNI tipi kullanir. Yeni tip acmak ayni anlam kumesinin
# (sirket / taseron / genel) iki farkli DB tipini dogururdu (puantaj spec §2).
from app.modules.site_diary.models import WorkerSource


class Personnel(Base):
    """Puantajin ihtiyac duydugu MINIMUM personel cekirdegi (puantaj spec §1, §7 S1).

    Isciler login kullanicisi DEGILDIR — bu yuzden puantaj `users` uzerinden
    yazilamaz. `user_id` yalniz OPSIYONEL bir kopru (ofis personeli); login SART
    DEGILDIR.

    IK'nin geri kalani ERTELENMISTIR: belge takibi / izin yonetimi / SGK / bordro /
    ucret kolonu BU TABLODA YOKTUR (spec §1 ve §5). Meslek (`trade`) SERBEST
    METINDIR — katalog tablosu acilmaz (spec §7 S5, diary `trade` deseni).

    Silme YOKTUR (puantaj kayitlari bagli): pasiflestirme `is_active=false` ile
    yapilir (spec §3).
    """

    __tablename__ = "personnel"
    __table_args__ = (
        # Tek yon zorlanir: kaynak taseron DEGILSE taseron bagi bos olmalidir.
        # TERS YON ZORLANMAZ (spec §2): kaynagi `subcontractor` olan bir kayit
        # taseron secilmeden de olusturulabilir — taslak esnekligi.
        CheckConstraint(
            "source = 'subcontractor' OR subcontractor_id IS NULL",
            name="ck_personnel_subcontractor_only_for_subcontractor_source",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    trade: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source: Mapped[WorkerSource] = mapped_column(
        Enum(WorkerSource, name="worker_source"), nullable=False
    )
    # SET NULL: taseron kaydi silinse de personel (ve puantaj gecmisi) ayakta kalir.
    subcontractor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("subcontractors.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # SET NULL: kullanici silinse de personel kaydi (ve puantaji) durur.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
