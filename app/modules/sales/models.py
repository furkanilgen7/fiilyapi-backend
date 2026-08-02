import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class SaleType(str, enum.Enum):
    """F56 "Satis Tipi": Kesin Satis · Rezervasyon (Kapora) · On Sozlesme."""

    sale = "sale"
    reservation = "reservation"
    pre_contract = "pre_contract"


class UnitSaleStatus(str, enum.Enum):
    """Satis kaydinin yasam dongusu (spec §2/§3).

    `units.sales_status` (UnitSalesStatus) ile KARISTIRILMAMALI: o unitenin
    vitrin durumudur (`listed/reserved/sold/closed`), bu ise satis kaydinin
    durumudur. Enum tipi adlari da ayridir: `unit_sales_status` (unite) ve
    `unit_sale_status` (satis kaydi).

    `reservation` → `active` (sozlesmeli/taksitli) → `deed_transferred`
    (S166 "Tapu Devredildi"); `cancelled` her durumdan gelinebilen son duraktir.
    Gecis matrisinin KODU T5'in isidir; T1 yalniz kumeyi tanimlar.
    """

    reservation = "reservation"
    active = "active"
    deed_transferred = "deed_transferred"
    cancelled = "cancelled"


class DeedCondition(str, enum.Enum):
    """F156 "Tapu Devir Kosulu": Tum odeme tamamlaninca · Pesinat sonrasi · Sozlesme imzasinda."""

    full_payment = "full_payment"
    after_down_payment = "after_down_payment"
    at_contract = "at_contract"


class PaymentPlanType(str, enum.Enum):
    """F99 "Odeme Plani": Pesin · Pesinat + Taksit · Banka Kredisi · Takas/Trampa."""

    cash = "cash"
    down_payment_installments = "down_payment_installments"
    bank_loan = "bank_loan"
    barter = "barter"


class InstallmentPaymentMethod(str, enum.Enum):
    """F122/129 "Odeme Sekli": Havale/EFT · Nakit · Cek · Otomatik Odeme."""

    transfer = "transfer"
    cash = "cash"
    cheque = "cheque"
    auto_payment = "auto_payment"


class UnitSale(Base):
    """Unite satis kaydi (P8 spec §2).

    UNITE BASINA EN COK BIR ACIK KAYIT: `uq_unit_sales_open_unit` kismi
    benzersiz indeksi `cancelled` DISINDAKI tum durumlari kapsar. Servis
    korkuluguna guvenilmez — iki es zamanli istek ayni daireyi iki musteriye
    satabilirdi.

    ILERI BAG YOK (units spec §1.3 kurali korunur): `units` tablosuna `sale_id`
    sutunu ACILMAZ; iliski her zaman `unit_sales.unit_id` yonunden okunur.
    `units.sales_status` bu kaydin durumundan TURETILIR (spec §3) ve senkronun
    kodu T3'un isidir.

    MALIYET/KAR SUTUNU YOKTUR (kalici karar 3): mockup'taki F62 "Maliyet" ve
    F90 "Bu Satistan Kar" alanlari `pending_module: "project_costs"` (P10)
    olarak doner. Bir sonraki ajan bunlari "eksik alan" sanip EKLEMEMELIDIR.

    SATIS BELGELERI YOKTUR (F168-202): belge cekirdegi kendi diliminde acilir
    (kalici karar 8). "Pesinat icin otomatik fatura" (F206) da yok — `invoicing`
    modulunun kodu henuz yazilmadi.

    `min_sale_price` ALTINA satis ENGELLENMEZ (kalici karar 2) — DB'de de,
    serviste de kisit yoktur.

    Fiyat anlik goruntuleri (`list_price_snapshot`, `advisor_name`): unite
    fiyati ya da danisman kaydi sonradan degisse bile satis belgesi uzerindeki
    deger DEGISMEMELIDIR.
    """

    __tablename__ = "unit_sales"
    __table_args__ = (
        # Ayni unitede ikinci ACIK kayit imkansiz; iptal edilenler serbest.
        Index(
            "uq_unit_sales_open_unit",
            "unit_id",
            unique=True,
            postgresql_where=text("status <> 'cancelled'"),
        ),
        CheckConstraint("sale_price >= 0", name="ck_unit_sales_sale_price"),
        CheckConstraint(
            "list_price_snapshot IS NULL OR list_price_snapshot >= 0",
            name="ck_unit_sales_list_price_snapshot",
        ),
        CheckConstraint(
            "discount_amount IS NULL OR discount_amount >= 0",
            name="ck_unit_sales_discount_amount",
        ),
        # Kume ({1, 10, 20}) DB'de DEGIL Pydantic'te zorlanir (units.vat_rate ile
        # ayni gerekce, karar 9): KDV listesi yasayla degisir.
        CheckConstraint(
            "vat_pct IS NULL OR (vat_pct >= 0 AND vat_pct <= 100)", name="ck_unit_sales_vat_pct"
        ),
        CheckConstraint(
            "reservation_deposit IS NULL OR reservation_deposit >= 0",
            name="ck_unit_sales_reservation_deposit",
        ),
        CheckConstraint(
            "down_payment IS NULL OR down_payment >= 0", name="ck_unit_sales_down_payment"
        ),
        CheckConstraint(
            "installment_count IS NULL OR installment_count >= 0",
            name="ck_unit_sales_installment_count",
        ),
        CheckConstraint(
            "term_interest_pct IS NULL OR term_interest_pct >= 0",
            name="ck_unit_sales_term_interest_pct",
        ),
        CheckConstraint(
            "late_fee_monthly_pct IS NULL OR late_fee_monthly_pct >= 0",
            name="ck_unit_sales_late_fee_monthly_pct",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # RESTRICT: satisi olan unite silinemez (unite silme ucu bugun yoktur ama
    # DB kisiti gelecekteki bir ucun sessiz veri kaybini onler).
    unit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("units.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # Gorunurluk suzgeci (visible_projects, spec §6) bu sutundan calisir; unite
    # uzerinden JOIN etmek her sorguya bir adim eklerdi.
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    sale_type: Mapped[SaleType] = mapped_column(
        Enum(SaleType, name="sale_type"), nullable=False
    )  # F56
    # Sunucu varsayilani YOK: kayit ya rezervasyon ya satistir, dogru baslangic
    # degerini `sale_type`a bakarak servis secer (T3).
    status: Mapped[UnitSaleStatus] = mapped_column(
        Enum(UnitSaleStatus, name="unit_sale_status"), nullable=False, index=True
    )
    list_price_snapshot: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2), nullable=True
    )  # F84
    discount_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)  # F85
    sale_price: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)  # F86
    vat_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)  # F87
    # SET NULL: danismanin kullanici kaydi silinse de satis kaydi ayakta kalir;
    # ad zaten `advisor_name`de dondurulmustur.
    advisor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )  # F75
    advisor_name: Mapped[str | None] = mapped_column(String(200), nullable=True)  # F75
    reservation_deposit: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2), nullable=True
    )  # S188
    # S4 (onayli): suresi dolunca OTOMATIK iptal YOKTUR — zamanlanmis is
    # altyapisi yok; ekran "suresi doldu" turevini bu tarihten hesaplar.
    reservation_due_date: Mapped[date | None] = mapped_column(Date, nullable=True)  # S188
    deed_condition: Mapped[DeedCondition | None] = mapped_column(
        Enum(DeedCondition, name="deed_condition"), nullable=True
    )  # F156
    planned_deed_date: Mapped[date | None] = mapped_column(Date, nullable=True)  # F157
    delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)  # F158
    has_condominium_easement: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )  # F161
    has_mortgage: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )  # F162
    # DOLU = gecikme faizi uygulanir, NULL = uygulanmaz (F163). Ayri bir
    # `has_late_fee` bayragi ACILMAZ: iki sutun birbiriyle celisebilirdi.
    # S5 (onayli): faiz yalniz GOSTERIM turevidir, tahakkuk/borc kaydi yoktur.
    late_fee_monthly_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    payment_plan_type: Mapped[PaymentPlanType | None] = mapped_column(
        Enum(PaymentPlanType, name="payment_plan_type"), nullable=True
    )  # F99
    down_payment: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)  # F103
    installment_count: Mapped[int | None] = mapped_column(Integer, nullable=True)  # F104
    first_installment_date: Mapped[date | None] = mapped_column(Date, nullable=True)  # F105
    term_interest_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)  # F106
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SaleInstallment(Base):
    """Odeme plani satiri (F110-147).

    `sequence_no = 0` PESINAT satiridir (F117 "Pesinat"), 1..n aylik taksitler
    (F124 "1 / 12"). Ayri bir `is_down_payment` bayragi ACILMAZ: sira numarasi
    zaten tek otoritedir.

    Plan toplaminin `sale_price`a esitligi DB'de DEGIL serviste dogrulanir
    (T4): kisit satir-basina degil TABLO-BASINA bir toplamdir ve Postgres'te
    ancak trigger'la zorlanabilirdi.

    "Gecikmis" TUREVDIR (due_date gecmis + paid_amount < amount) — durum sutunu
    ACILMAZ, cunku her gun kendiliginden degisen bir degeri saklamak senkron
    kaymasi demektir.
    """

    __tablename__ = "sale_installments"
    __table_args__ = (
        UniqueConstraint("sale_id", "sequence_no", name="uq_sale_installments_sale_sequence"),
        CheckConstraint("sequence_no >= 0", name="ck_sale_installments_sequence_no"),
        CheckConstraint("amount >= 0", name="ck_sale_installments_amount"),
        CheckConstraint("paid_amount >= 0", name="ck_sale_installments_paid_amount"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # CASCADE: plan satis kaydinin parcasidir, bagimsiz omru yoktur.
    sale_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("unit_sales.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(50), nullable=False)  # F118
    due_date: Mapped[date] = mapped_column(Date, nullable=False)  # F120
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)  # F121
    payment_method: Mapped[InstallmentPaymentMethod | None] = mapped_column(
        Enum(InstallmentPaymentMethod, name="installment_payment_method"), nullable=True
    )  # F122/129
    # S2 (onayli): tahsilat taksit uzerine ELLE islenir; hazine entegrasyonu
    # kendi diliminde. Kismi odeme desteklenir, bu yuzden bayrak degil TUTARdir.
    paid_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal("0"), server_default=text("0")
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
