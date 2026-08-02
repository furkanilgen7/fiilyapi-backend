"""Alıcı (müşteri) şemaları — P8 spec §2, mockup `Form - Daire Satisi` 70-76.

`contracts/schemas.py.Subcontractor*` üçlüsünün (Create/Update/Response) birebir
kardeşi. Tip-kimlik uyuşması burada DEĞİL `guards.py`de doğrulanır: PATCH kısmi
gövde gönderir, kural ancak DB'deki kayıtla BİRLEŞTİRİLMİŞ değerler üzerinde
anlamlıdır (bkz. `guards.validate_customer_identity`).
"""

import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.modules.customers.models import CustomerType


class CustomerCreate(BaseModel):
    customer_type: CustomerType  # F70
    name: str = Field(min_length=1, max_length=200)  # F71
    # TCKN 11, VKN 10 hane — kolon ikisinde de String(11). Biçim/hane
    # doğrulaması BİLİNÇLİ OLARAK yok (guards.py "Biçim doğrulaması" notu).
    national_id: str | None = Field(default=None, max_length=11)  # F72 (TCKN)
    tax_number: str | None = Field(default=None, max_length=11)  # F72 (VKN)
    phone: str | None = Field(default=None, max_length=20)  # F73
    email: str | None = Field(default=None, max_length=254)  # F74
    address: str | None = None  # F76


class CustomerUpdate(BaseModel):
    customer_type: CustomerType | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)
    national_id: str | None = Field(default=None, max_length=11)
    tax_number: str | None = Field(default=None, max_length=11)
    phone: str | None = Field(default=None, max_length=20)
    email: str | None = Field(default=None, max_length=254)
    address: str | None = None


class CustomerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    customer_type: CustomerType
    name: str
    national_id: str | None
    tax_number: str | None
    phone: str | None
    email: str | None
    address: str | None


class CustomerListResponse(BaseModel):
    items: list[CustomerResponse]
