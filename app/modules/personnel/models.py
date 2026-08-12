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
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

# Enum PAYLASILIR: `worker_source` DB tipi santiye gunlugu diliminde (b5c6d7e8f9a0)
# yaratildi; personel kaydi AYNI tipi kullanir. Yeni tip acmak ayni anlam kumesinin
# (sirket / taseron / genel) iki farkli DB tipini dogururdu (puantaj spec §2).
# İK-1 spec §5 K2: `Serbest Meslek`/`Stajyer` PE 90 secenekleri bu enum'a
# EKLENMEZ — takas SGK 4a/4b ayrimi netlesince İK-3'te yapilir.
from app.modules.site_diary.models import WorkerSource


class Gender(str, enum.Enum):
    """PE 51-118 (İK-1 spec §1). İkili kume — mockup'ta ucuncu secenek yok."""

    male = "male"
    female = "female"


class MaritalStatus(str, enum.Enum):
    """PE 51-118 (İK-1 spec §1)."""

    single = "single"
    married = "married"


class WageType(str, enum.Enum):
    """PE 113 (İK-1 spec §1)."""

    daily = "daily"
    monthly = "monthly"
    hourly = "hourly"


class PaymentMethod(str, enum.Enum):
    """PE 115 (İK-1 spec §1)."""

    bank = "bank"
    cash = "cash"
    mixed = "mixed"


class Personnel(Base):
    """Puantajin ihtiyac duydugu MINIMUM personel cekirdegi (puantaj spec §1, §7 S1)
    + İK-1 kart genislemesi (spec §1, §5).

    Isciler login kullanicisi DEGILDIR — bu yuzden puantaj `users` uzerinden
    yazilamaz. `user_id` yalniz OPSIYONEL bir kopru (ofis personeli); login SART
    DEGILDIR.

    İK-1 ile eklenen TUM yeni kolonlar NULLABLE'dir (spec §5 K3) — taslak/yayin
    ayrimindaki zorunluluk SERVIS katmaninda uygulanir (bu dilimin T2'si), DB
    seviyesinde zorlanmaz.

    `tc_no` UNIQUE INDEKS tasir ama NULL DEGERLER SERBESTTIR: Postgres'in
    varsayilan `NULLS DISTINCT` semantigi altinda iki NULL `tc_no` birbirine
    esit SAYILMAZ, yani kisit yalniz DOLU (ve esit) iki TCKN'de tetiklenir —
    taslak asamasinda TCKN girilmemis coklu kayit engellenmez (spec §5 K1,
    checksum dogrulamasi SERVISTEDIR — bu tablo yalniz UQ zorlar).

    Foto kolonu AÇILMADI (spec §5 K6, BC form-slot pending). Vergi no formda
    YOK → AÇILMADI. `worker_source` enum'una yeni deger EKLENMEDI (spec §5 K2).

    Silme YOKTUR (puantaj kayitlari bagli): pasiflestirme `is_active=false` ile
    yapilir (spec §3).
    """

    __tablename__ = "personnel"
    __table_args__ = (
        # Tek yon zorlanir: kaynak taseron DEGILSE taseron bagi bos olmalidir.
        # TERS YON ZORLANMAZ (spec §2): kaynagi `subcontractor` olan bir kayit
        # taseron secilmeden de olusturulabilir — taslak esnekligi.
        CheckConstraint(
            "source = 'subcontractor' OR subcontractor_id IS NULL",
            name="ck_personnel_subcontractor_only_for_subcontractor_source",
        ),
        UniqueConstraint("tc_no", name="uq_personnel_tc_no"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    trade: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source: Mapped[WorkerSource] = mapped_column(
        Enum(WorkerSource, name="worker_source"), nullable=False
    )
    # SET NULL: taseron kaydi silinse de personel (ve puantaj gecmisi) ayakta kalir.
    subcontractor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("subcontractors.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # SET NULL: kullanici silinse de personel kaydi (ve puantaji) durur.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )

    # --- İK-1: personel karti genislemesi (spec §1, PE 51-118 birebir) --------
    tc_no: Mapped[str | None] = mapped_column(String(11), nullable=True)
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    gender: Mapped[Gender | None] = mapped_column(Enum(Gender, name="gender"), nullable=True)
    marital_status: Mapped[MaritalStatus | None] = mapped_column(
        Enum(MaritalStatus, name="marital_status"), nullable=True
    )
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    emergency_contact_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    emergency_contact_phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    hire_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    wage_type: Mapped[WageType | None] = mapped_column(
        Enum(WageType, name="wage_type"), nullable=True
    )
    wage_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    payment_method: Mapped[PaymentMethod | None] = mapped_column(
        Enum(PaymentMethod, name="payment_method"), nullable=True
    )
    iban: Mapped[str | None] = mapped_column(String(34), nullable=True)
    sgk_no: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # SET NULL: atanan proje/bolum silinse de personel kaydi ayakta kalir —
    # atama kolonlari birer DARALTMADIR, personelin sahibi degildir (spec §5 K4).
    assigned_project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    assigned_section_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sections.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    is_draft: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class PersonnelDocumentType(Base):
    """Belge tipi katalogu (İK-1 spec §2) — SEED'i 6 sabit tiptir, CRUD ucu

    ACILMAZ (bu dilimin de T2/T3/T4'un de isi degil; yonetimi ayarlar dilimine
    ertelenmistir). `validity_months` NULL = suresiz (PE 141/151 ornekleri "1
    yil"/"3 yil"; kimlik fotokopisi gibi suresiz tipler NULL kalir).
    """

    __tablename__ = "personnel_document_types"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(150), nullable=False, unique=True)
    is_mandatory: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    validity_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PersonnelDocument(Base):
    """Personel belgesi kaydi (İK-1 spec §2, BT birebir).

    Durum (valid/expiring/expired/missing) TUREVDIR — kolon YOKTUR, hesap T3/T4
    servis katmaninda yapilir (spec §2 son paragraf).

    `type_id` XOR `free_label`: katalogdan bir tip SECILIR YA DA serbest etiket
    girilir (PE 188-193 dropzone), ikisi birden ya da hicbiri OLAMAZ — CHECK
    `ck_personnel_document_type_xor_label`.

    `document_id` BC-2 PILOTUDUR: dosya baytlari `documents` arsivine yazilir,
    bu kayit yalniz KUNYEYE bagli tutar. SET NULL — arsiv kaydi silinse de
    takip kaydi KALIR (dosyasiz kayit da mesrudur, spec §2).
    """

    __tablename__ = "personnel_documents"
    __table_args__ = (
        CheckConstraint(
            "(type_id IS NOT NULL AND free_label IS NULL) OR "
            "(type_id IS NULL AND free_label IS NOT NULL)",
            name="ck_personnel_document_type_xor_label",
        ),
        Index("ix_personnel_documents_valid_until", "valid_until"),
        Index("ix_personnel_documents_personnel_type", "personnel_id", "type_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # CASCADE: personel silinemez (spec §3) ama tur donusu/testler icin belge de
    # personelle birlikte gitmelidir — yetim belge birakilmaz.
    personnel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("personnel.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # RESTRICT: katalog tipi kullanimda ise silinemez (CRUD ucu zaten YOK ama DB
    # seviyesinde de korunur).
    type_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("personnel_document_types.id", ondelete="RESTRICT"),
        nullable=True,
    )
    free_label: Mapped[str | None] = mapped_column(String(150), nullable=True)
    # SET NULL: BC arsiv kaydi silinse de takip kaydi kalir (dosyasiz da mesru).
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
    )
    issued_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
