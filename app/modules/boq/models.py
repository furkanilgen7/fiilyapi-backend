import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class BoqGroup(Base):
    """Poz grubu — santiye altindaki BOQ ust basligi (spec §3.1).

    `site_id` KALICI baglantidir (spec §8 soru 1, kullanici karari 2026-07-30):
    sozlesme/bolum baglari bu dilimde ACILMAZ, proje sonunda tek seferde kurulur.
    Grup adindaki bastaki sira numarasi ("1. TOPRAK...") SAKLANMAZ; sira
    `sort_order`'dan turetilir, numarayi frontend basar.
    """

    __tablename__ = "boq_groups"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sites.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    items: Mapped[list["BoqItem"]] = relationship(
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="BoqItem.sort_order, BoqItem.code",
    )


class BoqItem(Base):
    """Poz kalemi — BOQ tablo satiri (spec §3.2).

    `site_id` grup uzerinden dolayli olarak da erisilebilir ama ayrica burada
    tutulur: (site_id, code) benzersizligi icin gereklidir ve DB'de bilesik
    FK ile grup->site tutarliligi ZORLANMAZ (spec §3.3 invariant 1) — yazma
    yolu tekil oldugu icin servis korkulugu yeterli kabul edilir.
    """

    __tablename__ = "boq_items"
    __table_args__ = (
        UniqueConstraint("site_id", "code", name="uq_boq_items_site_code"),
        CheckConstraint("quantity > 0", name="ck_boq_items_quantity_positive"),
        CheckConstraint("unit_price >= 0", name="ck_boq_items_unit_price_nonneg"),
        # Poz dagitiminda her santiye icin tek kota hucresi vardir (POZ 98-99/108-109,
        # spec §3.3). contract_item_id NULL olan satirlar (santiyenin kendi basina
        # girdigi pozlar) bu kisidin disindadir.
        Index(
            "uq_boq_items_contract_item_site",
            "contract_item_id",
            "site_id",
            unique=True,
            postgresql_where=text("contract_item_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sites.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("boq_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # Birim serbest metindir (spec §8 soru 4, oneri): enum dondurulamaz, mockup'ta
    # m³/Ton/m² gibi karisik birimler goruluyor.
    unit: Mapped[str] = mapped_column(String(50), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # Spec §3.3 ONAYLI SAPMA (kalici karar 1'den): sozlesme kalemine bag. SET NULL
    # cunku BOQ satiri sahadaki gerceklesen isin kaydidir; sozlesme kalemi silinince
    # satir yok olmaz, yalniz bag kopar.
    contract_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employer_contract_items.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class BoqItemSectionAllocation(Base):
    """Bir pozun BIR BOLUME tahsis edilen MIKTARI (BOQ-SEC, kullanici karari 2026-08-17).

    🔴 Bu bir `boq_items.section_id` FK'si DEGILDIR ve olamaz: bir poz BIRDEN COK
    boluma pay edilebilir (1.200 m³ betonun 400'u "Kat 6-10", 300'u "Kat 11-15",
    500'u atanmamis). Mockup'in `section-form/BoqAssignmentCard.tsx:13-21`de
    cizdigi "Santiye Kotasi / Bu Bolume" ikilisi tam olarak budur: kota
    `boq_items.quantity`, "bu bolume" ise BU tablodaki satirdir.

    INVARIANT (K3): `SUM(quantity) <= boq_items.quantity`. DB ile ZORLANAMAZ
    (satirlar arasi toplam kisidi bir CHECK'e sigmaz) — servis katmaninda ve
    🔴 POZ SATIRI `FOR UPDATE` ILE KILITLENEREK tutulur (EŞİK = KİLİT, İK-2
    dersi): kilitsiz bir esik kontrolu iki eszamanli tahsiste IKISINI DE gecirir.
    Invariantin IKI yazma kapisi vardir ve ikisi de AYNI kilidi alir:
    `service.replace_allocations` (tahsis toplami ARTAR) ve `service.update_item`
    (poz `quantity`si DUSER — kotayi tahsis toplaminin altina cekmek ayni
    invarianti ters yonden kirar).

    ON DELETE CASCADE — ve bu, repodaki YEDI `sections.id` FK'sinin (`SET NULL`)
    BILINCLI SAPMASIDIR (K2). Gerekce: tahsis satirinin BAGIMSIZ VARLIGI YOKTUR;
    o satir "su poz, su bolume, su kadar" demekten ibarettir, bolum gidince cumle
    anlamsizlasir. `SET NULL` secilseydi kolon nullable olmak ZORUNDA kalirdi
    (NOT NULL kolona SET NULL calisma aninda FK hatasi verir), sahipsiz satirlar
    birikir ve hicbir ekranda gorunmeden pozun kotasini BLOKE ederdi; UNIQUE de
    NULL dalinda islemedigi icin coklanabilirlerdi. CASCADE veri kaybi DEGILDIR:
    poz satiri ve `quantity`si AYNEN durur, yalniz tahsis cozulur ve miktar
    "atanmamis" havuzuna geri doner.

    UQ (boq_item_id, section_id) DEFERRABLE INITIALLY DEFERRED — `site_planning`
    deseni (`SitePlanRow`): DEGISTIRME (replace) ucu tek istekte bir satiri silip
    baskasini onun anahtarina tasiyabilir; anlik kontrolde INSERT DELETE'ten once
    flush edilirse istek HAKSIZ yere cakisma alirdi. Ertelenmis kontrol gercek
    cakismayi HALA yakalar; govde ici tekillik ayrica servis katmaninda 422 verir.
    """

    __tablename__ = "boq_item_section_allocations"
    __table_args__ = (
        UniqueConstraint(
            "boq_item_id",
            "section_id",
            name="uq_boq_item_section_allocations_item_section",
            deferrable=True,
            initially="DEFERRED",
        ),
        # Sifir tahsis bir SATIR olarak tutulmaz — silinir (K1).
        CheckConstraint("quantity > 0", name="ck_boq_item_section_allocations_qty_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    boq_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("boq_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    section_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # `boq_items.quantity` ile AYNI tip: olcek/hassasiyet farki bir invariant kacagidir.
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
