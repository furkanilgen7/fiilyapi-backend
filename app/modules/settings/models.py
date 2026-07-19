import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class UILocale(str, enum.Enum):
    tr = "tr"
    en = "en"


class UICurrency(str, enum.Enum):
    TRY = "TRY"
    USD = "USD"
    EUR = "EUR"


class UIDensity(str, enum.Enum):
    comfortable = "comfortable"
    normal = "normal"
    compact = "compact"


class UITheme(str, enum.Enum):
    light = "light"
    dark = "dark"
    system = "system"


class UserPreferences(Base):
    """Kullanici-basina gorunum tercihleri (spec §4.1). Self-service."""

    __tablename__ = "user_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    locale: Mapped[UILocale] = mapped_column(
        Enum(UILocale, name="ui_locale"), nullable=False, default=UILocale.tr, server_default="tr"
    )
    currency: Mapped[UICurrency] = mapped_column(
        Enum(UICurrency, name="ui_currency"),
        nullable=False,
        default=UICurrency.TRY,
        server_default="TRY",
    )
    date_format: Mapped[str] = mapped_column(
        String(20), nullable=False, default="DD.MM.YYYY", server_default="DD.MM.YYYY"
    )
    density: Mapped[UIDensity] = mapped_column(
        Enum(UIDensity, name="ui_density"),
        nullable=False,
        default=UIDensity.normal,
        server_default="normal",
    )
    theme: Mapped[UITheme] = mapped_column(
        Enum(UITheme, name="ui_theme"),
        nullable=False,
        default=UITheme.light,
        server_default="light",
    )
    accent_color: Mapped[str] = mapped_column(
        String(20), nullable=False, default="#2563eb", server_default="#2563eb"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class NotificationPref(Base):
    """Kullanici-basina olay kanal tercihi (spec §4.1). v1'de gonderim yok, yalnizca kayit."""

    __tablename__ = "notification_prefs"
    __table_args__ = (
        UniqueConstraint("user_id", "event_key", name="uq_notification_user_event"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_key: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    in_app: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sms: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
