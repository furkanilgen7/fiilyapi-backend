import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class BoqGroup(Base):
    """Poz grubu — santiye altindaki BOQ ust basligi (spec §3.1).

    `site_id` KALICI baglantidir (spec §8 soru 1, kullanici karari 2026-07-30):
    sozlesme/bolum baglari bu dilimde ACILMAZ, proje sonunda tek seferde kurulur.
    Grup adindaki bastaki sira numarasi ("1. TOPRAK...") SAKLANMAZ; sira
    `sort_order`'dan turetilir, numarayi frontend basar.
    """

    __tablename__ = "boq_groups"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sites.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    items: Mapped[list["BoqItem"]] = relationship(
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="BoqItem.sort_order, BoqItem.code",
    )


class BoqItem(Base):
    """Poz kalemi — BOQ tablo satiri (spec §3.2).

    `site_id` grup uzerinden dolayli olarak da erisilebilir ama ayrica burada
    tutulur: (site_id, code) benzersizligi icin gereklidir ve DB'de bilesik
    FK ile grup->site tutarliligi ZORLANMAZ (spec §3.3 invariant 1) — yazma
    yolu tekil oldugu icin servis korkulugu yeterli kabul edilir.
    """

    __tablename__ = "boq_items"
    __table_args__ = (
        UniqueConstraint("site_id", "code", name="uq_boq_items_site_code"),
        CheckConstraint("quantity > 0", name="ck_boq_items_quantity_positive"),
        CheckConstraint("unit_price >= 0", name="ck_boq_items_unit_price_nonneg"),
        # Poz dagitiminda her santiye icin tek kota hucresi vardir (POZ 98-99/108-109,
        # spec §3.3). contract_item_id NULL olan satirlar (santiyenin kendi basina
        # girdigi pozlar) bu kisidin disindadir.
        Index(
            "uq_boq_items_contract_item_site",
            "contract_item_id",
            "site_id",
            unique=True,
            postgresql_where=text("contract_item_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sites.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("boq_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # Birim serbest metindir (spec §8 soru 4, oneri): enum dondurulamaz, mockup'ta
    # m³/Ton/m² gibi karisik birimler goruluyor.
    unit: Mapped[str] = mapped_column(String(50), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # Spec §3.3 ONAYLI SAPMA (kalici karar 1'den): sozlesme kalemine bag. SET NULL
    # cunku BOQ satiri sahadaki gerceklesen isin kaydidir; sozlesme kalemi silinince
    # satir yok olmaz, yalniz bag kopar.
    contract_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employer_contract_items.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
