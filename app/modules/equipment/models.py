"""MK-1 makine & ekipman çekirdeği — veri modeli (spec §2, §5).

Üç tablo: ekipman kartı (M1+M2) · çalışma kaydı (M3) · yakıt kaydı (M4).
Router/servis mantığı BU DOSYADA YOKTUR (T3+).

Bu modülün taşıdığı kalıcı kararlar:

* **K1 — `brand` ve `model` AYRI kolondur.** M2:86 tek alan çiziyor ama M1:94
  kart yalnız markayı basıyor; tek alanda saklansaydı liste ekranı markayı
  ayıklamak için metin parçalardı. Onaylı sapma.
* **K2 — `purchase_amount` DB'de nullable'dır.** Koşullu zorunluluk
  (`ownership == owned` iken 422) SERVİStedir, DB CHECK'i DEĞİL — kiralık
  makinenin alış bedeli yoktur (İK-3 S3 emsali: kural nerede yaşadığı bilinsin).
* **K3 — Satıcı ve kiralama firması TEK `supplier_id`'dir.** SA'nın `suppliers`
  tablosu yeniden kullanılır; iki alan tutulsaydı aynı firma iki kez yazılır ve
  tedarikçi bakiyesi ikiye bölünürdü.
* **K4 — Atama hedefi `site_id`'dir, `warehouse_id` AÇILMAZ.** "Depoda
  (Atanmadı)" = `site_id IS NULL`. İkinci bir atama hedefi "makine nerede"
  sorusuna iki cevap üretirdi. Onaylı sapma.
* **K5 — `norm_consumption` SAYI + `norm_unit` ENUM'a ayrılır.** M4 bunun
  üzerinden yüzde sapma hesaplıyor; metin saklansaydı hesap her okumada metin
  ayrıştırmaya bağlı olurdu.
* **K7 — `monthly_capacity_hours` VERİDİR, koda gömülmez** (İK-3 K1 emsali);
  vinç ile el aleti aynı kapasitede değildir.
* **K8 — `is_company_asset` YALNIZ BİR İŞARETTİR.** Sabit kıymet modülü YOK;
  hiçbir yan etki tetiklemez.
* **K9 — Tarihsel atama izi `equipment_work_logs.site_id`de yaşar**;
  `equipment.site_id` BUGÜNKÜ atamadır. Makine şantiye değiştirince geçmiş
  maliyet dağılımı geriye dönük başka projeye yazılmaz.
* **K10 — Arıza AYRI KAYIT TİPİDİR** (`record_type`), aynı kayıtta ikinci saat
  kolonu değil: M3:282 arızayı kendi satırı (operatörsüz, sebep metniyle),
  M5:128-139 ayrı satır olarak basıyor.
* **`amount` KOLON DEĞİLDİR** (yakıt): `liters × unit_price` her okumada
  türetilir — P10 "tek formül" kanonu; iki yerde yaşayan para zamanla ayrışır.
* **`is_draft` AÇILMAZ:** M2'de taslak butonu YOKTUR (personel formunun aksine).
"""

import enum
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

# Para kolonlarının kuruş hassasiyeti (alış bedeli / rayiç / birim bedel).
MONEY_PRECISION = 18
MONEY_SCALE = 2

# Yakıt birim fiyatı DÖRT ondalıklıdır: litre fiyatı kuruşun altında kotalanır
# (M4:111) ve iki ondalık, litre × fiyat çarpımını sistematik olarak kaydırırdı.
UNIT_PRICE_PRECISION = 10
UNIT_PRICE_SCALE = 4

# Litre ve norm tüketim ölçeği.
QUANTITY_PRECISION = 10
QUANTITY_SCALE = 2

# Saat: 24 saatlik tavan (K12) iki ondalıkla rahat sığar.
HOURS_PRECISION = 6
HOURS_SCALE = 2

# K7: kullanım yüzdesinin PAYDASI. Mockup'tan tersine mühendislikle doğrulandı
# (186/200 = %93 · 152/200 = %76 · 42/200 = %21 · 168/200 = %84 · 144/200 = %72
# — beşi de M3 rozetleriyle birebir). Ekipman başına DEĞİŞTİRİLEBİLİR.
DEFAULT_MONTHLY_CAPACITY_HOURS = 200


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
        Enum(EquipmentRatePeriod, name="equipment_rate_period"), nullable=True
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
