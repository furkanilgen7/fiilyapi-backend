"""Malzeme kartı + depo şemaları (ST spec §2, §4) — T2.

`personnel/schemas.py` üçlüsünün (Create/Update/Response) kardeşi.

## Uzunluk tavanları kolon sınırlarıyla BİREBİRDİR

`app.core.text.FREE_TEXT_MAX_LENGTH` BURADA KULLANILMAZ ve bu bir eksiklik
değildir: o sabit yalnız kolonu `Text` (DB'de sınırsız) olan alanlar içindir
(`tests/test_serbest_metin_tavani.py` "mevcut dar sınırlar gevşetilmedi"). T2'nin
alanlarının hepsi `String(N)`dir, dolayısıyla tavanları N'dir — 2000'e çekilseydi
kullanıcı 422 yerine anlaşılmaz bir DB hatası alırdı. Tek `Text` alan
(`stock_entries.note`) T3'ündür ve O SABİTİ kullanmak ZORUNDADIR.

## Kapsam dışı alanlar (spec §5, icat yasağı)

Sipariş bağı · tedarikçi kataloğu · bakiye/durum alanı · "Aylık İhtiyaç" ·
belge slotu bu şemalarda YOKTUR. Bakiye ve durum TÜREVDİR (spec §3) ve T3'ün
özet uçlarından gelir; kart gövdesine kolon olarak sızmaz.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.inventory.models import StockCategory

# Model `String(30)`/`String(200)`/`String(20)` — şema ile DB sınırı AYNI olmalı.
_CODE = Field(min_length=1, max_length=30)
_NAME = Field(min_length=1, max_length=200)
_UNIT = Field(min_length=1, max_length=20)

# Eşik NEGATİF OLAMAZ: durum formülü (spec §3, `%50×min` / `min` / `5×min`)
# negatif bir eşikte anlamını yitirir ve her kalem "fazla" görünürdü. Ölçek
# kolonla aynıdır (`Numeric(14, 3)`).
_MIN_STOCK = Field(default=None, ge=0, max_digits=14, decimal_places=3)

# Depo adı `String(100)`.
_WAREHOUSE_NAME = Field(min_length=1, max_length=100)


class StockItemCreate(BaseModel):
    """`POST /stock/items` gövdesi.

    `unit` SERBEST METİNDİR (spec §2): Ton/Torba/Metre/Adet/m³ kümesi açık
    uçludur ve yeni bir birim migration gerektirmemelidir. `category` ise
    KAPALI kümedir (E3 99 select'i), bu yüzden enum'dur.
    """

    code: str = _CODE
    name: str = _NAME
    category: StockCategory
    unit: str = _UNIT
    min_stock: Decimal | None = _MIN_STOCK
    is_active: bool = True


class StockItemUpdate(BaseModel):
    """`PATCH /stock/items/{id}` — TÜM alanlar isteğe bağlı.

    Alanın GÖNDERİLMEMESİ ile `null` GÖNDERİLMESİ farklıdır ve fark
    `model_fields_set` ile korunur: `min_stock: null` eşiği SİLER (durum
    `None` olur, spec §3), hiç göndermemek ona DOKUNMAZ.

    Kullanımdan kaldırma YOLU budur (`is_active: false`) — DELETE ucu yoktur.
    """

    code: str | None = Field(default=None, min_length=1, max_length=30)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    category: StockCategory | None = None
    unit: str | None = Field(default=None, min_length=1, max_length=20)
    min_stock: Decimal | None = _MIN_STOCK
    is_active: bool | None = None


class StockItemResponse(BaseModel):
    """Kart künyesi. **Bakiye / durum ALANI YOKTUR** (spec §3): ikisi de
    hareketlerden TÜREVDİR ve T3'ün özet uçlarından gelir. Buraya konsaydı
    katalog listesi her çizilişte hareket tablosunu tarardı."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    category: StockCategory
    unit: str
    min_stock: Decimal | None
    is_active: bool
    created_at: datetime


class StockItemListResponse(BaseModel):
    """`personnel`/`audit`/`users` liste deseni: `total` + `limit`/`offset`."""

    items: list[StockItemResponse]
    total: int
    limit: int
    offset: int


class WarehouseCreate(BaseModel):
    """`POST /warehouses` gövdesi.

    `site_id` NULL = **MERKEZ DEPO** (SG 84 "Merkez Depo (Sincan)"): hiçbir
    şantiyeye bağlı değildir ve görünürlüğü proje kapsamına DEĞİL yalnız stok
    iznine bağlıdır (spec §7 S2b).
    """

    name: str = _WAREHOUSE_NAME
    site_id: uuid.UUID | None = None


class WarehouseUpdate(BaseModel):
    """`PATCH /warehouses/{id}` — YALNIZ ad.

    `site_id` BİLİNÇLİ olarak YOKTUR (`DocumentFolderUpdate` deseni): kapsam
    değiştirmek bir IDOR yüzeyidir — merkez depo şantiyeye çekilerek gizlenebilir
    ya da tersi yapılabilirdi — ve hiçbir mockup depo taşımayı istemez. Alan
    gövdede gönderilse bile Pydantic onu yok sayar, kapsam DEĞİŞMEZ.
    """

    name: str = _WAREHOUSE_NAME


class WarehouseResponse(BaseModel):
    """Depo künyesi. **Bakiye alanı YOKTUR** — kart gövdesiyle aynı gerekçe."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    site_id: uuid.UUID | None
    created_at: datetime


class WarehouseListResponse(BaseModel):
    items: list[WarehouseResponse]
    total: int
    limit: int
    offset: int
