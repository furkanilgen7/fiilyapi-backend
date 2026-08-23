"""MK-1 çekirdek tabloları: ekipman kartı · çalışma kaydı · yakıt kaydı.

Modülün K1-K10 kararları (kartın kolonları, `site_id` atama hedefi, arızanın
AYRI kayıt tipi olması, `amount`ın KOLON OLMAMASI) burada yaşar; kararların
tam listesi paket cephesinin (`__init__.py`) docstring'indedir.
"""

import uuid
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.modules.equipment.models.constants import (
    DEFAULT_MONTHLY_CAPACITY_HOURS,
    HOURS_PRECISION,
    HOURS_SCALE,
    MONEY_PRECISION,
    MONEY_SCALE,
    QUANTITY_PRECISION,
    QUANTITY_SCALE,
    UNIT_PRICE_PRECISION,
    UNIT_PRICE_SCALE,
)
from app.modules.equipment.models.enums import (
    EquipmentCategory,
    EquipmentFinancing,
    EquipmentFuelType,
    EquipmentMaintenancePeriod,
    EquipmentNormUnit,
    EquipmentOwnership,
    EquipmentRatePeriod,
    EquipmentStatus,
    WorkLogType,
    equipment_rate_period_enum,
)


class Equipment(Base):
    """Ekipman kartı — M1 listesi + M2 formu (spec §2.1).

    Silme UCU YOKTUR: kullanımdan kaldırma `is_active=false` iledir. Çalışma ve
    yakıt kayıtları zaten RESTRICT'lidir (maliyet izi), yani kaydı olan ekipman
    DB seviyesinde de silinemez.

    `site_id`/`operator_id`/`supplier_id` üçü de **SET NULL**'dır: şantiye,
    personel ya da tedarikçi kaydı kalksa ekipmanın kendisi ve maliyet geçmişi
    AYAKTA kalır — bağ kopar, veri kaybolmaz.
    """

    __tablename__ = "equipment"
    __table_args__ = (
        CheckConstraint(
            "purchase_amount IS NULL OR purchase_amount >= 0",
            name="ck_equipment_purchase_amount_non_negative",
        ),
        CheckConstraint(
            "market_value IS NULL OR market_value >= 0",
            name="ck_equipment_market_value_non_negative",
        ),
        CheckConstraint(
            "rate_amount IS NULL OR rate_amount >= 0",
            name="ck_equipment_rate_amount_non_negative",
        ),
        CheckConstraint(
            "norm_consumption IS NULL OR norm_consumption > 0",
            name="ck_equipment_norm_consumption_positive",
        ),
        # K16: kapasite 0 ise kullanım % `null` döner (sıfıra bölme yok); NEGATİF
        # kapasite ise hiçbir okumada anlamlı değildir.
        CheckConstraint(
            "monthly_capacity_hours >= 0", name="ck_equipment_monthly_capacity_non_negative"
        ),
        CheckConstraint(
            "depreciation_years IS NULL OR depreciation_years > 0",
            name="ck_equipment_depreciation_years_positive",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[EquipmentCategory] = mapped_column(
        Enum(EquipmentCategory, name="equipment_category"), nullable=False, index=True
    )
    # K1: M1:94 kart yalnız markayı basar → ayrı kolonlar.
    brand: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    serial_no: Mapped[str | None] = mapped_column(String(100), nullable=True)
    plate_no: Mapped[str | None] = mapped_column(String(30), nullable=True)
    model_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ownership: Mapped[EquipmentOwnership] = mapped_column(
        Enum(EquipmentOwnership, name="equipment_ownership"),
        nullable=False,
        default=EquipmentOwnership.owned,
        server_default=text("'owned'::equipment_ownership"),
    )
    # K2: nullable — kiralık makinenin alış bedeli yoktur; zorunluluk serviste.
    purchase_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(MONEY_PRECISION, MONEY_SCALE), nullable=True
    )
    purchase_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # M2:100 üç seçenek basıyor (5/10/15) ama SERBEST TAMSAYIDIR: enum açmak
    # dördüncü bir amortisman süresini imkânsız kılardı.
    depreciation_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # K3: satıcı ve kiralama firması AYNI kolondur.
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("suppliers.id", ondelete="SET NULL"),
        nullable=True,
    )
    financing: Mapped[EquipmentFinancing | None] = mapped_column(
        Enum(EquipmentFinancing, name="equipment_financing"), nullable=True
    )
    market_value: Mapped[Decimal | None] = mapped_column(
        Numeric(MONEY_PRECISION, MONEY_SCALE), nullable=True
    )
    # K18: maliyet formülünün tabanı. Yoksa maliyet `null`dır, 0 DEĞİL (K16).
    rate_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(MONEY_PRECISION, MONEY_SCALE), nullable=True
    )
    rate_period: Mapped[EquipmentRatePeriod | None] = mapped_column(
        equipment_rate_period_enum, nullable=True
    )
    # K4: NULL = "Depoda (Atanmadı)". K20: NULL olan ekipman HERKESE görünür.
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sites.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    operator_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("personnel.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[EquipmentStatus] = mapped_column(
        Enum(EquipmentStatus, name="equipment_status"),
        nullable=False,
        default=EquipmentStatus.working,
        server_default=text("'working'::equipment_status"),
        index=True,
    )
    # M1:122/148 — "Fren balatası değişimi" gibi serbest açıklama.
    status_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # M1:123/149 — "Tahmini dönüş" tarihi.
    status_expected_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    fuel_type: Mapped[EquipmentFuelType | None] = mapped_column(
        Enum(EquipmentFuelType, name="equipment_fuel_type"), nullable=True
    )
    # K5: SAYI (metin değil) + ayrı birim enum'u.
    norm_consumption: Mapped[Decimal | None] = mapped_column(
        Numeric(QUANTITY_PRECISION, QUANTITY_SCALE), nullable=True
    )
    norm_unit: Mapped[EquipmentNormUnit | None] = mapped_column(
        Enum(EquipmentNormUnit, name="equipment_norm_unit"), nullable=True
    )
    maintenance_period: Mapped[EquipmentMaintenancePeriod | None] = mapped_column(
        Enum(EquipmentMaintenancePeriod, name="equipment_maintenance_period"), nullable=True
    )
    # K7: VERİ, koda gömülü sabit DEĞİL.
    monthly_capacity_hours: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=DEFAULT_MONTHLY_CAPACITY_HOURS,
        server_default=text(str(DEFAULT_MONTHLY_CAPACITY_HOURS)),
    )
    # K8: YALNIZ bir işaret — hiçbir yan etki tetiklemez.
    is_company_asset: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
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


class EquipmentWorkLog(Base):
    """Çalışma / arıza kaydı — M3 (spec §2.2).

    `equipment_id` **RESTRICT**'tir (`payroll_lines`→`personnel` emsali): kaydı
    olan ekipman silinemez, yoksa maliyet geçmişi sessizce delinirdi.

    **UQ YOKTUR:** bir ekipman aynı gün birden çok vardiya ya da arıza kaydı
    taşıyabilir. Günlük tavan (K12: saat toplamı ≤ 24) bir EŞİK denetimidir ve
    servistedir — eşik = kilit kanonu gereği `equipment` satırı denetimden ÖNCE
    `with_for_update` ile kilitlenir.

    `hours` **SUNUCU HESABIDIR** (K11): aralık verilmişse `end − start`, arıza
    kaydında (aralıksız) doğrudan alınır. İstemcinin gönderdiği `hours` 422'dir.
    Gece yarısını geçen vardiya bu dilimde DESTEKLENMEZ (422) — sessiz negatif
    saatten iyidir.
    """

    __tablename__ = "equipment_work_logs"
    __table_args__ = (
        # K12 tavanı GÜNLÜK TOPLAM üzerindedir ve serviste kilitle denetlenir;
        # burada yalnız tek kaydın kendi içinde anlamlı olduğu aralık zorlanır.
        CheckConstraint("hours >= 0 AND hours <= 24", name="ck_equipment_work_logs_hours_range"),
        # K11: iki zaman alanı BİRLİKTE ya hiç verilmez ya ikisi de verilir.
        CheckConstraint(
            "(start_time IS NULL) = (end_time IS NULL)",
            name="ck_equipment_work_logs_time_pair",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    equipment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("equipment.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    work_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    # K9: kaydın KENDİ şantiyesi — `equipment.site_id`nin snapshot'ı DEĞİL,
    # tarihsel gerçeği. Makine taşınınca geçmiş aylar başka projeye yazılmaz.
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sites.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Arıza kaydında operatör YOKTUR (M3:280) → nullable.
    operator_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("personnel.id", ondelete="SET NULL"),
        nullable=True,
    )
    record_type: Mapped[WorkLogType] = mapped_column(
        Enum(WorkLogType, name="work_log_type"),
        nullable=False,
        default=WorkLogType.worked,
        server_default=text("'worked'::work_log_type"),
        index=True,
    )
    start_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    end_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    hours: Mapped[Decimal] = mapped_column(Numeric(HOURS_PRECISION, HOURS_SCALE), nullable=False)
    # M3:283 arıza sebebi.
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class EquipmentFuelLog(Base):
    """Yakıt kaydı — M4 (spec §2.3).

    `amount` KOLON DEĞİLDİR: `liters × unit_price` her okumada türetilir. Kolon
    açılsaydı iki gerçek kaynak doğar ve biri güncellenmediğinde para sessizce
    ayrışırdı (P10 "tek formül" kanonu).

    `unit_price` SATIR BAZLIDIR (K13): dönem sabiti olsaydı geçmiş kayıtların
    tutarı bugünkü fiyatla değişirdi.
    """

    __tablename__ = "equipment_fuel_logs"
    __table_args__ = (
        # Sıfır litrelik ya da bedelsiz bir yakıt kaydı hiçbir şey anlatmaz ve
        # sapma hesabını sessizce sulandırırdı.
        CheckConstraint("liters > 0", name="ck_equipment_fuel_logs_liters_positive"),
        CheckConstraint("unit_price > 0", name="ck_equipment_fuel_logs_unit_price_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    equipment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("equipment.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    fuel_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sites.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    liters: Mapped[Decimal] = mapped_column(
        Numeric(QUANTITY_PRECISION, QUANTITY_SCALE), nullable=False
    )
    unit_price: Mapped[Decimal] = mapped_column(
        Numeric(UNIT_PRICE_PRECISION, UNIT_PRICE_SCALE), nullable=False
    )
    # K14: M4:114 "Giren" ROL basıyor ama rol kullanıcıdan türer; rol
    # saklansaydı kimin girdiği kaybolurdu.
    entered_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    @property
    def amount(self) -> Decimal:
        """🔴 T5 — `liters × unit_price`, TÜRETİLİR (bu KOLON DEĞİLDİR, sınıf
        docstring'i). Formül `cost.fuel_amount`ten TEK YERDEN gelir; deferred
        import ile, çünkü `cost.py` bu modülden (`EquipmentRatePeriod`) okur —
        modül düzeyinde import edilseydi çember (P10 `cost_cards` dersi) açardı.
        """
        from app.modules.equipment.cost import fuel_amount

        return fuel_amount(liters=self.liters, unit_price=self.unit_price)
