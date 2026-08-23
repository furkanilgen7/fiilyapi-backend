"""MK-2/FRM-1 belge tabloları: belge TÜRÜ + belgenin kendisi.

`documents` modülünün kardeşi ama AYRI tablolardır (ekipmana bağlı arşiv).
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class EquipmentDocumentType(Base):
    """Ekipman belge tipi katalogu — M2:134-159'un altı sabit slotu (MK-2 spec §2.3).

    `personnel_document_types`in KARDEŞİDİR ama kolon adları BİREBİR DEĞİLDİR:
    spec §2.3 açıkça `code` · `name` · `is_required` · `sort_order` sayar.
    `code` personel tarafında YOKTUR — burada eklenir çünkü altı slot SABİT ve
    frontend'in ikon/renk haritası (M2:134-159 emoji + arka plan rengi) bir
    isim değil bir KODA bağlanmalıdır; ad değişse (yeniden adlandırma) bile
    haritalama KIRILMAMALIDIR.

    CRUD ucu AÇILMAZ (İK-1 emsali): yönetimi ayarlar dilimine ertelenmiştir,
    seed 6 sabit tiptir.
    """

    __tablename__ = "equipment_document_types"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    is_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class EquipmentDocument(Base):
    """Ekipman belgesi — M2:134-159 slotlarının yüklenmiş hâli (MK-2 spec §2.3).

    Dosya alanları (`filename`/`mime_type`/`size_bytes`/`content`) BC/İK-1'in
    saklama TEKNİĞİNİ birebir izler: uzantı beyaz listesi + boyut tavanı
    `app.modules.documents.files`/`settings.document_max_bytes`ten AYNEN
    okunur, indirmede `nosniff` + `attachment` başlığı BASILIR (T3 emsali) —
    yeni bir doğrulama/saklama kuralı İCAT EDİLMEZ.

    🔴 **Bilinçli sapma (İK-1'den farklı nokta):** `personnel_documents`
    baytları KENDİ TAŞIMAZ, genel `documents` arşivine `document_id` ile
    bağlanır — o arşiv `project_id` ZORUNLU tutar (proje/şantiye klasör
    hiyerarşisi için). Ekipmanın `site_id`si NULL olabilir (K4: "Depoda"),
    yani her ekipman belgesinin bir projeye bağlanabileceği garanti DEĞİLDİR;
    genel arşive zorlamak ya uydurma bir proje ataması ya da imkânsız bir
    NOT NULL ihlali doğururdu. Bu yüzden `content` BURADA (bytea, `equipment`
    modülünün kendi tablosunda) tutulur — döküm teknikleri ORTAK, tablo AYRI.

    `content` liste/özet sorgularına GİRMEZ (repository katmanı yalnız
    gereken kolonları seçer) — `documents`/`document_blobs` ayrımının
    TAŞIDIĞI aynı gerekçe (TOAST şişmesini liste sorgusundan izole tutmak).

    `type_id` **RESTRICT**'tir: kullanımda olan katalog tipi silinemez (CRUD
    ucu zaten yok ama DB seviyesinde de korunur). `equipment_id` **CASCADE**:
    ekipman silinemez zaten (RESTRICT'li çalışma/yakıt/kira kayıtları varsa),
    ama silinebildiği teorik durumda belgesi yetim kalmaz.

    `valid_until` **K7, onaylı sapma**: mockup'ın belge slotlarında tarih alanı
    çizilmez ama "Periyodik Muayene · Yıllık zorunlu" (M2:139) ve "Sigorta
    Poliçesi" (M2:154) süreli belgelerdir — tarihsiz saklanan bir muayene
    süresi dolduğunda da "var" görünürdü (güvenlik yüzeyi). Nullable'dır,
    zorunlu KILINMAZ.
    """

    __tablename__ = "equipment_documents"
    __table_args__ = (
        CheckConstraint("size_bytes >= 0", name="ck_equipment_documents_size_non_negative"),
        Index("ix_equipment_documents_equipment_type", "equipment_id", "type_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    equipment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("equipment.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("equipment_document_types.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    # FRM-1 — belge künyesi (mockup biçimi `TC-48-MUA-2026`). K1: uzunluk
    # EMSALLE bağlıdır (`contracts.contract_no` · `equipment.serial_no` ·
    # `equipment_rental_invoices.invoice_no` hepsi String(100)) — yeni bir
    # uzunluk İCAT EDİLMEZ. Nullable: eski satırlar ve numarasız belgeler meşru.
    document_no: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # FRM-1/K6 — adlar personel tarafıyla BİREBİR (`personnel_documents.
    # issued_at` / `.note`); eşanlamlı yeni ad uydurulmaz.
    issued_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # K7 — onaylı sapma (yukarı bakınız).
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
