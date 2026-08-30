import enum
import uuid
from datetime import datetime
from ipaddress import IPv4Address, IPv6Address

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Text, desc, func
from sqlalchemy.dialects.postgresql import INET, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AuditAction(str, enum.Enum):
    """Denetim gunlugunde kaydedilen islem turleri.

    `approve` ve `backup` degerleri simdiden tanimlidir; uretici uclari sonraki
    fazlarda (hakedis onayi, yedekleme) eklenecek.

    Proje geneli deseni (`str, enum.Enum`) korunur; StrEnum'a gecis `__str__`
    davranisini degistirir (bkz. pyproject.toml UP042 notu).
    """

    login = "login"
    create = "create"
    update = "update"
    delete = "delete"
    approve = "approve"
    backup = "backup"
    # AI-0b: FIIL AI'in bir TURUNUN ozet satiri (spec §2.2 KATMAN 6 / S8).
    # `approve`/`backup` gibi ureticisi SONRAKI fazda (AI-1 `POST /ai/chat`)
    # gelir; enumu simdi acmak ikinci bir enum takas migration'ini onler.
    # Araç-basina ayrintili iz AYRI tablodadir (`ai_tool_calls`) — bu uye
    # denetim gunlugune TUR BASINA TEK ozet satir dusurmek icindir.
    ai_turn = "ai_turn"


class AuditLog(Base):
    """Degistirilemez denetim kaydi (spec §3).

    Yalnizca INSERT ve SELECT yapilir: bu tablo icin UPDATE/DELETE ucu, servis
    fonksiyonu veya repository yardimcisi YOKTUR.
    """

    __tablename__ = "audit_log"
    __table_args__ = (
        # Varsayilan siralama `occurred_at DESC` oldugu icin indeks de DESC.
        Index("ix_audit_log_occurred_at", desc("occurred_at")),
        Index("ix_audit_log_actor_user_id", "actor_user_id"),
        Index("ix_audit_log_action", "action"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # ON DELETE SET NULL: kullanici silinince denetim izi silinmemeli, aktor "Sistem"e duser.
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[AuditAction] = mapped_column(
        Enum(AuditAction, name="audit_action"), nullable=False
    )
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    # Yazarken string kabul edilir; asyncpg okurken IPv4Address/IPv6Address dondurur,
    # bu yuzden sunum katmani (Task 4 semasi) degeri str() ile metne cevirir.
    ip_address: Mapped[IPv4Address | IPv6Address | None] = mapped_column(INET, nullable=True)
