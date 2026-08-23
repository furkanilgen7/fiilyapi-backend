"""Ekipman modülünün ON BİR enum'u + paylaşılan `Enum` TİPİ.

`equipment_rate_period_enum` bilinçli olarak TEK NESNEdir: hem `equipment`
hem `equipment_rental_invoices` tablosu onu kullanır. İki ayrı `Enum(...)`
kurulsaydı SQLAlchemy aynı PostgreSQL tipini İKİ KEZ yaratmaya çalışırdı.

Bu dosya tablo TANIMLAMAZ; `cost.py` / `consumption.py` / şemalar ondan
yalnız OKUR.
"""

import enum

from sqlalchemy import (
    Enum,
)

from app.core.db import Base


class EquipmentCategory(str, enum.Enum):
    """M2:85 — altı kategori.

    Kategori İKONU (M1 emojileri) DB'de tutulmaz: kategoriden türer, frontend
    haritasıdır (spec §5).
    """

    crane = "crane"
    machinery = "machinery"
    truck = "truck"
    concrete = "concrete"
    compressor = "compressor"
    hand_tool = "hand_tool"


class EquipmentStatus(str, enum.Enum):
    """M2:120 — dört durum.

    `idle` (boşta) M1 kartlarında sayaç olarak basılmıyor ama K21 gereği açılır:
    sunucu mockup'tan FAZLA veri verebilir, EKSİK veremez.
    """

    working = "working"
    maintenance = "maintenance"
    broken = "broken"
    idle = "idle"


class EquipmentOwnership(str, enum.Enum):
    """M2:54-66 — mülkiyet. K2 koşullu zorunluluğunun anahtarı."""

    owned = "owned"
    rented = "rented"


class EquipmentFinancing(str, enum.Enum):
    """M2:102 — finansman biçimi."""

    cash = "cash"
    bank_loan = "bank_loan"
    leasing = "leasing"


class EquipmentRatePeriod(str, enum.Enum):
    """M2:109 — birim bedelin dönemi. K18 maliyet formülünün girdisi."""

    hourly = "hourly"
    daily = "daily"
    monthly = "monthly"


class EquipmentFuelType(str, enum.Enum):
    """M2:121 — yakıt tipi. `none` = yakıt tüketmeyen ekipman (el aleti)."""

    diesel = "diesel"
    gasoline = "gasoline"
    electric = "electric"
    none = "none"


class EquipmentNormUnit(str, enum.Enum):
    """K5 — norm tüketimin birimi. M4:62 `Lt/km` örneğini basıyor.

    `lt_km` bir FAIL-CLOSED kapısıdır (K16): kilometre verisi hiçbir ekranda
    girilmediği için bu birimdeki ekipmanda sapma HESAPLANMAZ, `null` durur.
    """

    lt_hour = "lt_hour"
    lt_km = "lt_km"


class EquipmentMaintenancePeriod(str, enum.Enum):
    """K6 — M2:123'ün DÖRT seçeneği olduğu gibi.

    "Aylık"ı saat kolonuna sıkıştırmak (NULL + ayrı bayrak) aynı bilgiyi iki
    kolona bölerdi.
    """

    hours_250 = "hours_250"
    hours_500 = "hours_500"
    hours_1000 = "hours_1000"
    monthly = "monthly"


class WorkLogType(str, enum.Enum):
    """K10 — çalışma mı arıza mı. İki kolonlu tek kayıt M3+M5'in iki sunumunu
    da üretemezdi."""

    worked = "worked"
    breakdown = "breakdown"


# 🔴 MK-2 spec §5: `equipment_rate_period` DB tipi TEKTİR ve MK-1'in malıdır.
# Hem `equipment.rate_period` hem `equipment_rental_invoices.rate_period` BU
# NESNEYİ paylaşır; her kolonda ayrı bir `Enum(...)` yazılsaydı `create_all` aynı
# tipi İKİ KEZ yaratmayı denerdi (`payment_terms` emsali) ve `worker_source`
# dersinde olduğu gibi iki farklı değer listesi iddia edilebilirdi.
equipment_rate_period_enum = Enum(
    EquipmentRatePeriod, name="equipment_rate_period", metadata=Base.metadata
)


class RentalInvoiceStatus(str, enum.Enum):
    """MK-2 K5 — kira hakedişi durum makinesi (M5:65).

    Zincir: `draft → pending_verification → approved → paid`.
    Ayrı bir `rejected` durumu YOKTUR: reddetme `approved → pending_verification`
    geri geçişidir (İK-3'ün red deseni). Ayrı durum açılsaydı reddedilmiş bir
    fatura "onaya bekleyen" listesinden düşer ve sessizce kaybolurdu.
    """

    draft = "draft"
    pending_verification = "pending_verification"
    approved = "approved"
    paid = "paid"


class RentalLineKind(str, enum.Enum):
    """MK-2 K3 — satırın ÖDENECEĞE KATILIMI buradan okunur.

    * `rented` → ödenecek toplama **GİRER**
    * `owned` → görünür, maliyeti raporlanır, toplama **GİRMEZ** (M5:140-151)
    * `breakdown` → tutarı "hariç tutulan" olarak raporlanır, toplama **GİRMEZ**
      (M5:128-139 üstü çizili)

    🔴 Çift ödeme YAPISAL olarak imkânsızdır: `owned`/`breakdown` hiçbir toplamın
    kaynağı değildir (İK-3 K2'nin `excluded` deseni birebir). Tek bir "hariç"
    bayrağına indirgenseydi `owned` ile `breakdown` ayrımı kaybolur, M5'in iki
    ayrı sunumu (kendi malı vs. arıza indirimi) üretilemezdi.
    """

    rented = "rented"
    owned = "owned"
    breakdown = "breakdown"
