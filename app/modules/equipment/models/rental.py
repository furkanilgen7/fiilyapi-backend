"""MK-2 kira hakedişi tabloları: başlık + satır.

`core`daki `equipment` tablosuna `ForeignKey` ile bağlıdır; kolon ölçekleri
`constants`tan, durum/tür enum'ları `enums`tan gelir.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
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
from app.modules.equipment.models.constants import (
    DEFAULT_VAT_RATE,
    MONEY_PRECISION,
    MONEY_SCALE,
    RENTAL_HOURS_PRECISION,
    RENTAL_HOURS_SCALE,
    VAT_RATE_PRECISION,
    VAT_RATE_SCALE,
)
from app.modules.equipment.models.enums import (
    EquipmentRatePeriod,
    RentalInvoiceStatus,
    RentalLineKind,
    equipment_rate_period_enum,
)


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
        # 🔴 MK-2 migration'ı (`e8f9a0b1c2d3`) bu bileşik indeksi YARATIYOR ama
        # model onu BEYAN ETMİYORDU → `alembic check` her koşuda sahte bir
        # `remove_index` diff'i üretiyordu (TB1 sınıfı sessiz borç: bir gün
        # birisi autogenerate çıktısına güvenip dönem indeksini düşürürdü).
        # ŞEMA DEĞİŞMEZ, migration GEREKMEZ — yalnız beyan hizalanır.
        Index("ix_equipment_rental_invoices_period", "period_year", "period_month"),
        # URL-4: slug GLOBAL tekildir ve indeks KISMIDIR (`WHERE slug IS NOT NULL`)
        # — kolon nullable oldugu icin coklu NULL serbest kalmak ZORUNDA.
        Index(
            "uq_equipment_rental_invoices_slug",
            "slug",
            unique=True,
            postgresql_where=text("slug IS NOT NULL"),
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
    # URL-4: kaynak `invoice_no`dur. Mockup ÖLÇÜLDÜ (`Makine - Kira Hakedişi
    # Liste`): listede tanımlayıcı olarak YALNIZ `Fatura No` sütunu vardır,
    # hakediş sıra numarası sütunu HİÇ YOKTUR; faturası girilmemiş taslak satır
    # ekranda birebir `— (kayıt no yok)` basar. Bu yüzden `invoice_no` NULL iken
    # slug de NULL'dır ve o kayıt UUID'siyle yaşar — ekranın söylediği şeyin
    # birebir karşılığı, uydurulmuş bir taban DEĞİL.
    # UQ `(supplier_id, invoice_no)` olduğu için `invoice_no` şirket geneli
    # tekil DEĞİLDİR; iki tedarikçinin aynı numarası `unique_slug` ile `-2` eki
    # alır (tedarikçi adı slug'a KATILMAZ: kullanıcı listede numarayı okur).
    slug: Mapped[str | None] = mapped_column(String(160), nullable=True)
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
        CheckConstraint(
            "capacity_hours IS NULL OR capacity_hours >= 0",
            name="ck_equipment_rental_invoice_lines_capacity_hours_non_negative",
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
    # 🔴 MK-3 K1 — aylık kira bedelini saate çeviren PAYDA da bir SNAPSHOT'tır.
    # Satır kurulurken `equipment.monthly_capacity_hours`tan KOPYALANIR. Canlı
    # okunsaydı, ekipman kartındaki kapasite düzeltildiğinde ONAYLANMIŞ (hatta
    # ödenmiş) bir aylık-sabit kira faturasının tutarı geriye dönük oynardı —
    # `worked_hours`/`rate_amount` ile TAM OLARAK aynı sınıf delik. (Kalıcı ders:
    # bir türev para değeri N çarpandan oluşuyorsa snapshot iddiası N'in HEPSİNİ
    # kapsamalıdır; MK-2'de saat donduruldu bedel unutuldu, bedel donduruldu
    # payda unutuldu.)
    #
    # NULLABLE'dır (K2, fail-closed): değer yoksa saatlik bedel HESAPLANAMAZ ve
    # `our_amount` `null` durur — uydurma 0 ya da enjekte edilmiş bir varsayılan
    # BASILMAZ (varsayılan ekipman tablosunun işidir, faturanın değil). Mevcut
    # satırlar migration'da (a0b1c2d3e4f5) ekipmandan DOLDURULUR (K4).
    #
    # 🔴 Çözülmüş saatlik bedel KOLONLAŞMAZ: para tek formülden türer (MK-2 K4);
    # burada donan şey GİRDİdir, TÜREV değil.
    capacity_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
