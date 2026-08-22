import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    LargeBinary,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import settings
from app.core.db import Base
from app.modules.approvals.definitions import DEFAULT_APPROVAL_THRESHOLD_TRY


class Company(Base):
    """Tek satirlik sirket bilgisi (spec §4.1). Cok-sirketlilik yok.

    Tekillik `only_row` uzerindeki UNIQUE + `only_row IS TRUE` CHECK ile zorlanir:
    ikinci satir eklenirse UNIQUE ihlali olur.
    """

    __tablename__ = "company"
    __table_args__ = (CheckConstraint("only_row IS TRUE", name="company_single_row"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    only_row: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true", unique=True
    )
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    tax_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    tax_office: Mapped[str | None] = mapped_column(String(100), nullable=True)
    trade_registry_no: Mapped[str | None] = mapped_column(String(100), nullable=True)
    kep_address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    website: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    logo_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    logo_content_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    logo_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    brand_color: Mapped[str] = mapped_column(
        String(20), nullable=False, default=settings.default_brand_color, server_default="#2563eb"
    )
    gib_integration_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    earsiv_portal: Mapped[str | None] = mapped_column(String(255), nullable=True)
    default_vat_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=settings.default_vat_rate, server_default="20.00"
    )
    auto_einvoice: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # OK-1A K3 — cok adimli onayin ₺ esigi. Kolon BASINA AYAR deseni
    # (`default_vat_rate` emsali): ayri bir "ayarlar" tablosu ACILMADI, cunku
    # tek satirlik sirket kaydi zaten sirket geneli ayarlarin yeridir.
    #
    # 🔴 `CompanyUpdate` semasina EKLENMEZ ve `PUT /company` bu kolona
    # DOKUNMAZ (R7): sirket formu `settings: full` seviyesindedir, esik ise
    # `approvals: admin` ister. Tek govdede birlesselerdi dusuk kapidan gecen
    # istek yuksek kapinin ardindaki degeri yazardi. Tek yazma yolu
    # `PUT /approvals/settings`tir.
    #
    # 🔴 Bu deger ZINCIR KURULURKEN DONAR: acik zincirler sonradan degisen
    # esikten ETKILENMEZ (`approval_chains.threshold_snapshot`).
    approval_threshold_try: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=DEFAULT_APPROVAL_THRESHOLD_TRY,
        server_default="500000.00",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
