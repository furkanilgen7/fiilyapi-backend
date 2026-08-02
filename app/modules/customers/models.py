import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class CustomerType(str, enum.Enum):
    """Form - Daire Satisi 70 "Alici Tipi": Gercek Kisi · Tuzel Kisi (Firma)."""

    person = "person"
    company = "company"


class Customer(Base):
    """Alici — satis kaydinin karsi tarafi (P8 spec §2).

    `employers` tablosundan AYRIDIR: isveren kat karsiligi sozlesmesinin
    tarafidir (arsa sahibi), alici ise uniteyi satin alan kisidir. Ikisini tek
    tabloda toplamak, "isveren listesi" ekranini yuzlerce daire alicisiyla
    doldurmak demek olurdu.

    Proje-BAGIMSIZDIR (spec §6): ayni alici birden cok projede unite alabilir,
    bu yuzden `project_id` sutunu YOKTUR. Erisim izin modulu (`sales`)
    seviyesinde denetlenir.

    TCKN/VKN: tip basina biri dolu olur (dogrulama Pydantic'te, T2). DB yalniz
    BENZERSIZLIGI zorlar ve bunu KISMI indeksle yapar — NULL'lar coklanabilir,
    dolu degerler benzersizdir (`uq_sections_site_code` ile ayni teknik).
    Kolon boyu ikisi de String(11): TCKN 11, VKN 10 hane.
    """

    __tablename__ = "customers"
    __table_args__ = (
        Index(
            "uq_customers_national_id",
            "national_id",
            unique=True,
            postgresql_where=text("national_id IS NOT NULL"),
        ),
        Index(
            "uq_customers_tax_number",
            "tax_number",
            unique=True,
            postgresql_where=text("tax_number IS NOT NULL"),
        ),
        # Liste ekraninin arama kolonu (T2: ad/TCKN/VKN).
        Index("ix_customers_name", "name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_type: Mapped[CustomerType] = mapped_column(
        Enum(CustomerType, name="customer_type"), nullable=False
    )  # F70
    name: Mapped[str] = mapped_column(String(200), nullable=False)  # F71
    national_id: Mapped[str | None] = mapped_column(String(11), nullable=True)  # F72 (TCKN)
    tax_number: Mapped[str | None] = mapped_column(String(11), nullable=True)  # F72 (VKN)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)  # F73
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)  # F74
    address: Mapped[str | None] = mapped_column(Text, nullable=True)  # F76
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
