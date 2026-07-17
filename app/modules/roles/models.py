import enum
import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.access import AccessLevel, Scope
from app.core.db import Base

SYSTEM_ADMIN_KEY = "system_admin"


class ModuleGroup(str, enum.Enum):
    GENEL = "GENEL"
    SAHA = "SAHA"
    STOK_SATINALMA = "STOK_SATINALMA"
    MALI = "MALI"
    SISTEM = "SISTEM"


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    emoji: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Module(Base):
    """İzin matrisinin satırları. Sabit referans verisi — migration ile seed edilir."""

    __tablename__ = "modules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    group: Mapped[ModuleGroup] = mapped_column(
        Enum(ModuleGroup, name="module_group"), nullable=False
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class RolePermission(Base):
    """Matrisin bir hücresi: (rol, modül) -> seviye + kapsam."""

    __tablename__ = "role_permissions"
    __table_args__ = (UniqueConstraint("role_id", "module_id", name="uq_role_module"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    module_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("modules.id", ondelete="CASCADE"), nullable=False
    )
    access_level: Mapped[AccessLevel] = mapped_column(
        Enum(AccessLevel, name="access_level"), nullable=False, default=AccessLevel.none
    )
    scope: Mapped[Scope] = mapped_column(
        Enum(Scope, name="scope"), nullable=False, default=Scope.all
    )
