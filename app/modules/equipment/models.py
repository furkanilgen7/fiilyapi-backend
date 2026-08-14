"""Makine & ekipman — veri modeli (MK-1 spec §2/§5 + MK-2 spec §2.1/§2.2/§5).

Beş tablo: ekipman kartı (M1+M2) · çalışma kaydı (M3) · yakıt kaydı (M4) ·
kira hakedişi başlığı (M5) · kira hakedişi satırı (M5 tablosu).
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
    UniqueConstraint,
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

# MK-2 K1: KDV oranının VARSAYILANIDIR, SABİTİ DEĞİL. Oran `vat_rate`
# kolonunda satır satır yaşar; koda gömülseydi mevzuat değişiminde GEÇMİŞ
# faturaların tutarı geriye dönük oynardı (İK-3 `payroll_rates` dersi).
DEFAULT_VAT_RATE = Decimal("20.00")

# Oran ölçeği: yüzde iki ondalıkla ifade edilir (%20,00 · %8,00 · %1,00).
VAT_RATE_PRECISION = 5
VAT_RATE_SCALE = 2

# MK-2 saat ölçeği. MK-1'in `HOURS_PRECISION`ı (6) TEK GÜNÜN saatidir; kira
# hakedişi satırı bir AYIN toplamını taşır (M5: 186 saat) ve dönem birikimi
# altı hanenin altında sıkışmamalıdır.
RENTAL_HOURS_PRECISION = 8
RENTAL_HOURS_SCALE = 2


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


class EquipmentRentalInvoice(Base):
    """Kira hakedişi başlığı — M5 (MK-2 spec §2.1).

    Kiralama firmasından **GELEN** faturanın kaydıdır: çalışma kayıtlarından
    hesaplanan saatlerle doğrulanır ve ödenecek tutar buradan çıkar.

    Bu tablonun taşıdığı kalıcı kararlar:

    * **K1 — `invoice_amount` KDV HARİÇ matrahtır** ve `vat_rate` bir KOLONDUR,
      koda gömülü sabit DEĞİL. `vat_amount` ve `payable_total` KOLON DEĞİLDİR;
      `invoice_amount` + `vat_rate`ten türer (P10 "tek formül" kanonu). Oran
      koda gömülseydi mevzuat değişince GEÇMİŞ faturalar geriye dönük oynardı
      (İK-3 `payroll_rates` dersi).
    * **UQ `(supplier_id, invoice_no)`** — aynı faturayı iki kez ödemeyi
      YAPISAL olarak engeller. `invoice_no` NULL iken Postgres'in varsayılan
      `NULLS DISTINCT` semantiği altında taslaklar serbesttir
      (`personnel.tc_no` emsali): taslak açan kullanıcı fatura numarasını
      bilmeyebilir ve ikinci taslakta kilitlenmemelidir.
    * **`supplier_id` RESTRICT'tir** (`equipment.supplier_id`in SET NULL'ının
      bilinçli istisnası): fatura bir PARA izidir, tedarikçi kaydı silinerek
      ödemenin muhatabı yok edilemez.
    * **K5 — durum makinesi** `RentalInvoiceStatus`tadır; geçiş kapıları
      SERVİStedir (DB CHECK'i değil), `approved`/`paid` faturada düzenleme
      409'dur.
    * Toplamlar (`our_total` · `owned_total` · `excluded_breakdown_amount`)
      KOLON DEĞİLDİR: SATIRLARDAN türer (MK-1 K15).
    """

    __tablename__ = "equipment_rental_invoices"
    __table_args__ = (
        CheckConstraint(
            "period_month >= 1 AND period_month <= 12",
            name="ck_equipment_rental_invoices_month_range",
        ),
        CheckConstraint(
            "invoice_amount IS NULL OR invoice_amount >= 0",
            name="ck_equipment_rental_invoices_amount_non_negative",
        ),
        # Negatif ya da %100'ü aşan bir KDV oranı hiçbir okumada anlamlı değildir.
        CheckConstraint(
            "vat_rate >= 0 AND vat_rate <= 100",
            name="ck_equipment_rental_invoices_vat_rate_range",
        ),
        UniqueConstraint(
            "supplier_id",
            "invoice_no",
            name="uq_equipment_rental_invoices_supplier_invoice_no",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # K8: bir fatura TEK tedarikçiye aittir; `rented` satırların ekipmanı bu
    # tedarikçiyle eşleşmek zorundadır (ihlal 422, denetim SERVİStedir).
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("suppliers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # M5:59 — taslakta henüz bilinmeyebilir.
    invoice_no: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # M5:63 — firmanın kestiği tutar, KDV HARİÇ (K1).
    invoice_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(MONEY_PRECISION, MONEY_SCALE), nullable=True
    )
    # M5:72 — dönemsiz fatura hiçbir aya düşmezdi.
    period_year: Mapped[int] = mapped_column(Integer, nullable=False)
    period_month: Mapped[int] = mapped_column(Integer, nullable=False)
    # M5:73 "Tüm Projeler" = NULL. K9: NULL olan fatura HERKESE görünür.
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sites.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # M5:74 — MK-1'in tipi YENİDEN KULLANILIR (DB tipi TEK, spec §5).
    rate_period: Mapped[EquipmentRatePeriod] = mapped_column(
        equipment_rate_period_enum, nullable=False
    )
    # K1: oran VERİDİR — varsayılanı %20, ama satır kendi oranını taşır.
    vat_rate: Mapped[Decimal] = mapped_column(
        Numeric(VAT_RATE_PRECISION, VAT_RATE_SCALE),
        nullable=False,
        default=DEFAULT_VAT_RATE,
        server_default=text(str(DEFAULT_VAT_RATE)),
    )
    status: Mapped[RentalInvoiceStatus] = mapped_column(
        Enum(RentalInvoiceStatus, name="rental_invoice_status"),
        nullable=False,
        default=RentalInvoiceStatus.draft,
        server_default=text("'draft'::rental_invoice_status"),
        index=True,
    )
    # SET NULL: onaylayan kullanıcı silinse de fatura ve onay ZAMANI ayakta
    # kalır (İK-3 `payroll_periods` emsali).
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class EquipmentRentalInvoiceLine(Base):
    """Kira hakedişi satırı — M5 tablosu (MK-2 spec §2.2).

    * **K2 — `worked_hours` SNAPSHOT'tır, canlı sorgu DEĞİL.** Satır kurulurken
      çalışma kaydından okunur ve KOPYALANIR. Canlı JOIN olsaydı, fatura
      onaylandıktan sonra biri geçmiş bir çalışma kaydını düzelttiğinde
      ONAYLANMIŞ bir ödemenin dayanağı sessizce değişirdi (İK-3
      `personnel_source` snapshot'ı ile aynı ilke). Tazeleme AYRI ve AÇIK bir
      eylemdir (`POST …/reload`, yalnız `draft`ta).
    * **K4 — `our_amount` KOLON DEĞİLDİR:** `worked_hours × saatlik bedel` her
      okumada türetilir ve saatlik bedel MK-1'in `cost.py`sinden gelir. Satırın
      `rate_amount`ı doluysa o, boşsa ekipmanın kendi bedeli; ikisi de yoksa
      **`null`** (MK-1 K16 fail-closed), 0 DEĞİL.
    * **K6 — `hours_variance` da KOLON DEĞİLDİR:** `invoiced_hours − worked_hours`
      türevidir ve rozet (`variance_status`) sunucu damgasıdır (F-P10 kanonu).
    * **UQ `(invoice_id, equipment_id, line_kind)`** — aynı makine hem `rented`
      hem `breakdown` satırı taşıyabilir (M5 ikisini AYRI satır çiziyor), ama
      aynı türden iki satır taşıyamaz. UQ `line_kind`i içermeseydi arıza satırı
      sessizce reddedilirdi.
    * `equipment_id` **RESTRICT**'tir: satırı olan ekipman silinemez (para izi);
      `invoice_id` **CASCADE**'dir: fatura düşünce yetim satır bırakılmaz.
    """

    __tablename__ = "equipment_rental_invoice_lines"
    __table_args__ = (
        CheckConstraint(
            "worked_hours >= 0", name="ck_equipment_rental_invoice_lines_worked_hours_non_negative"
        ),
        CheckConstraint(
            "breakdown_hours >= 0",
            name="ck_equipment_rental_invoice_lines_breakdown_hours_non_negative",
        ),
        CheckConstraint(
            "rate_amount IS NULL OR rate_amount >= 0",
            name="ck_equipment_rental_invoice_lines_rate_amount_non_negative",
        ),
        CheckConstraint(
            "invoiced_hours IS NULL OR invoiced_hours >= 0",
            name="ck_equipment_rental_invoice_lines_invoiced_hours_non_negative",
        ),
        UniqueConstraint(
            "invoice_id",
            "equipment_id",
            "line_kind",
            name="uq_equipment_rental_invoice_lines_equipment_kind",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("equipment_rental_invoices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    equipment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("equipment.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # K3: ödenecek toplama katılım BURADAN okunur.
    line_kind: Mapped[RentalLineKind] = mapped_column(
        Enum(RentalLineKind, name="rental_line_kind"), nullable=False
    )
    # 🔴 Satırın ŞANTİYESİ — o da bir SNAPSHOT'tır (K2 ilkesi + MK-1 K9). M5:89
    # tabloda satır başına "Şantiye" sütunu vardır ve M5:177-193 proje dağılımı
    # tam olarak satırın şantiyesi + ekipmanı + saati + tutarıdır. Dağılım canlı
    # `equipment.site_id`den türetilseydi, makine bir sonraki ay taşındığında
    # ONAYLANMIŞ bir faturanın proje maliyeti geriye dönük başka projeye kayardı.
    # NULL = "Atanmamış" kovası; uydurma bir proje adı BASILMAZ.
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sites.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # K2: SNAPSHOT — çalışma kaydından kopyalanır, canlı okunmaz.
    worked_hours: Mapped[Decimal] = mapped_column(
        Numeric(RENTAL_HOURS_PRECISION, RENTAL_HOURS_SCALE), nullable=False
    )
    # M5:92 — arıza saati. Varsayılanı 0'dır: arızasız satırda "bilinmiyor" ile
    # "arıza yok" aynı şey değildir ve M5 her satırda bir sayı basar.
    breakdown_hours: Mapped[Decimal] = mapped_column(
        Numeric(RENTAL_HOURS_PRECISION, RENTAL_HOURS_SCALE),
        nullable=False,
        default=Decimal("0"),
        server_default=text("0"),
    )
    # M5:93 — DÜZENLENEBİLİR; boşsa ekipmanın kendi bedeline düşülür, o da
    # yoksa maliyet `null` durur (K4, fail-closed).
    rate_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(MONEY_PRECISION, MONEY_SCALE), nullable=True
    )
    # M5:95 — firmanın İDDİA ETTİĞİ saat. Bizim `worked_hours`umuzdan AYRI
    # kolondur: fark (K6) ancak iki bağımsız sayı varsa hesaplanabilir.
    invoiced_hours: Mapped[Decimal | None] = mapped_column(
        Numeric(RENTAL_HOURS_PRECISION, RENTAL_HOURS_SCALE), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
