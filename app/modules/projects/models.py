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
    Numeric,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.modules.contracts.models import ContractStatus


class ProjectStatus(str, enum.Enum):
    # Sira mockup Durum acilirini yansitir (spec §2.1): Planlama · Aktif · Beklemede.
    # `completed` UI'da gorunmez ama enum'da KALIR (spec §7.2): ProjectCounts.completed
    # ve dashboard sayaci ona baglidir; kaldirmak canli veriyi ve iki ekrani kirar.
    planning = "planning"
    active = "active"
    on_hold = "on_hold"
    completed = "completed"


class ProjectType(str, enum.Enum):
    """Üç iş modeli — kart düzenini ve gelir mantığını belirler (spec §3.1)."""

    taahhut = "taahhut"
    kendi_yatirim = "kendi_yatirim"
    kat_karsiligi = "kat_karsiligi"


class PriceIndexType(str, enum.Enum):
    """Fiyat farki endeks tipi (spec §2.4). Mockup satir 128 sirasi."""

    ufe = "ufe"  # ÜFE
    tufe = "tufe"  # TÜFE
    construction_cost = "construction_cost"  # İnşaat Maliyet Endeksi
    fixed_coefficient = "fixed_coefficient"  # Sabit Katsayı


class Employer(Base):
    """İşveren kartoteksi asgari çekirdeği (spec §2.2). Alt-Proje 3'ten öne çekildi;
    tam firma/cari hesap alanları (kısa ad, cari kod, IBAN, adres...) orada gelecek.

    Yeni izin modülü AÇILMAZ (spec §2.5/§7.6): `projects` view/admin ile korunur.
    """

    __tablename__ = "employers"
    __table_args__ = (
        # Kismi benzersiz indeks: VKN opsiyoneldir, coklu NULL serbest olmali.
        # sites.uq_sections_site_code ile ayni desen (spec §2.2).
        Index(
            "uq_employers_tax_number",
            "tax_number",
            unique=True,
            postgresql_where=text("tax_number IS NOT NULL"),
        ),
        Index("ix_employers_name", "name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    tax_number: Mapped[str | None] = mapped_column(String(11), nullable=True)
    contact_person: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Project(Base):
    """Proje çekirdeği (Alt-Proje 2 · P1). budget/progress_pct F6 mirasıdır, kalır."""

    __tablename__ = "projects"
    __table_args__ = (
        # URL-2: slug ŞİRKET GENELİ tekildir — proje URL'inin (`/projeler/<slug>`)
        # üstünde bir kapsam yoktur, kapsam SORULACAK bir yer de yoktur.
        #
        # Kısmi indeks (`uq_employers_tax_number` deseni): slug NULLABLE'dır ve
        # çoklu NULL serbest kalmalıdır. Nullable olmasının gerekçesi
        # `Project.slug` alan yorumundadır.
        Index(
            "uq_projects_slug",
            "slug",
            unique=True,
            postgresql_where=text("slug IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    # URL-2 — okunabilir URL kimliği. OLUŞTURULURKEN üretilir, AD DEĞİŞİNCE
    # DEĞİŞMEZ (kullanıcı kararı 2026-08-29): paylaşılmış bir bağlantı proje
    # yeniden adlandırıldı diye ÖLMEZ, bu yüzden v1'de yönlendirme/geçmiş
    # tablosuna gerek YOKTUR.
    #
    # 🔴 NULLABLE, ve bu bilinçlidir (emirdeki "olmayacaksa gerekçelendir"):
    #   1. Adı tamamen noktalama/ASCII-dışı olan bir kayıt slug ÜRETEMEZ
    #      (`slugify` -> None). NOT NULL olsaydı böyle bir ad ya 422 ile
    #      REDDEDİLİRDİ (bugün geçerli olan bir adı kırmak) ya da uydurma bir
    #      taban yazılırdı — ikisi de kullanıcıya zarar.
    #   2. Slug'ın TEK meşru üreticisi servis katmanıdır. NOT NULL, ORM
    #      nesnesini doğrudan kuran her yolu (iç yazma yolları + 86 test dosyası)
    #      slug vermeye zorlardı; `sections.code` emsali aynı sebeple nullable.
    # NULL slug ZARARSIZDIR: o kaydın URL'i UUID olarak yaşar (karar 2).
    slug: Mapped[str | None] = mapped_column(String(160), nullable=True)
    status: Mapped[ProjectStatus] = mapped_column(
        Enum(ProjectStatus, name="project_status"), nullable=False, default=ProjectStatus.active
    )
    project_type: Mapped[ProjectType] = mapped_column(
        Enum(ProjectType, name="project_type"),
        nullable=False,
        default=ProjectType.taahhut,
        server_default="taahhut",
    )
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    contract_no: Mapped[str | None] = mapped_column(String(100), nullable=True)
    contract_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    # employer_name KALIR ama artik TUREV/anlik goruntudur (spec §2.3): employer_id
    # doluysa servis her yazmada employer.name'i buraya kopyalar. P1 liste ekrani,
    # dashboard ve sites.schemas bu alani join'siz okuyor — kirilmasin diye durur.
    employer_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    employer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        # RESTRICT: projesi olan isveren silinemez (ileri donuk korkuluk).
        ForeignKey("employers.id", ondelete="RESTRICT"),
        nullable=True,
    )
    parcel: Mapped[str | None] = mapped_column(String(50), nullable=True)
    address: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Toplam butce. Bu dilimden SONRA yazilan satirlarda degismez:
    # budget = budget_material + budget_labor + budget_subcontractor + budget_overhead
    # (servis hesaplar, istemci `budget` yok sayilir — spec §2.3, §7.5). Goc eski
    # satirlara DOKUNMAZ: dort kalem 0 kalir, budget eski degerini korur.
    budget: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    budget_material: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=0, server_default=text("0")
    )
    budget_labor: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=0, server_default=text("0")
    )
    budget_subcontractor: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=0, server_default=text("0")
    )
    budget_overhead: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=0, server_default=text("0")
    )
    is_draft: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    progress_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    employer: Mapped["Employer | None"] = relationship(lazy="selectin")
    contract: Mapped["ProjectContract | None"] = relationship(
        lazy="selectin", cascade="all, delete-orphan", uselist=False
    )
    investment: Mapped["ProjectInvestment | None"] = relationship(
        lazy="selectin", cascade="all, delete-orphan", uselist=False
    )
    land_share: Mapped["ProjectLandShare | None"] = relationship(
        lazy="selectin", cascade="all, delete-orphan", uselist=False
    )
    shareholders: Mapped[list["LandShareShareholder"]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", order_by="LandShareShareholder.name"
    )


class ProjectContract(Base):
    """İşveren sözleşmesi (1-1, spec §2.4). Proje düzeyinde tekildir; şantiye payı
    BOQ dağıtımının türevidir, bu yüzden alanlar `sites`'a değil buraya yazılır.

    `contract_no` ve `amount` burada otoritedir; servis her yazmada bunları
    `projects.contract_no` / `projects.contract_amount` anlık görüntüsüne kopyalar.
    Başlangıç/bitiş tarihi ve `Süre (Gün)` BURAYA açılmaz: tarihler
    `projects.start_date`/`end_date`'te durur, süre türevdir (spec §2.4).
    """

    __tablename__ = "project_contracts"
    __table_args__ = (
        CheckConstraint(
            "advance_pct BETWEEN 0 AND 100 "
            "AND retainage_pct BETWEEN 0 AND 100 "
            "AND vat_pct BETWEEN 0 AND 100",
            name="ck_contract_pct_range",
        ),
        # Kutucuk kapaliyken (has_price_escalation=false) dolu endeks saklanmaz.
        CheckConstraint(
            "has_price_escalation = true OR (index_type IS NULL AND base_index_value IS NULL)",
            name="ck_contract_escalation",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        primary_key=True,
    )
    contract_no: Mapped[str | None] = mapped_column(String(100), nullable=True)
    signature_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    advance_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=20, server_default=text("20")
    )
    retainage_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=5, server_default=text("5")
    )
    vat_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=20, server_default=text("20")
    )
    late_penalty_daily: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    has_price_escalation: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    index_type: Mapped[PriceIndexType | None] = mapped_column(
        Enum(PriceIndexType, name="price_index_type"), nullable=True
    )
    base_index_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    # Sunucu varsayilani anlamli (active) oldugu icin NOT NULL (spec §3.1) — "yeni
    # kolonlar NOT NULL yapilmaz" kurali *kullanicinin doldurmasi gereken* alanlar
    # icindir, bu onlardan biri degildir (sites'taki Boolean'larla ayni desen).
    status: Mapped[ContractStatus] = mapped_column(
        Enum(ContractStatus, name="contract_status"),
        nullable=False,
        default=ContractStatus.active,
        server_default="active",
    )


class ProjectInvestment(Base):
    """Kendi yatırım uzantısı (1-1). Türev alanlar (satılan, kâr…) P10'un işi."""

    __tablename__ = "project_investment"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    sales_target: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    land_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)


class ProjectLandShare(Base):
    """Kat karşılığı uzantısı (1-1). Arsa maliyeti sütunu YOK — tanım gereği 0 (spec §3.3)."""

    __tablename__ = "project_land_share"
    __table_args__ = (
        CheckConstraint("our_share_pct + owner_share_pct = 100", name="ck_land_share_pct_total"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    landowner_name: Mapped[str] = mapped_column(String(200), nullable=False)
    our_share_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    owner_share_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    contract_no: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notary_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    land_area_m2: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    construction_area_m2: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    daily_penalty: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    guarantee_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)


class LandShareShareholder(Base):
    """Kat karşılığı hissedarı (1-N). Hissedar başına ünite dağılımı P9'un işi."""

    __tablename__ = "land_share_shareholder"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    share_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
