import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class UnitKind(str, enum.Enum):
    """KY 71 "48 Daire + 4 Dukkan", KY 308 "Dukkan 2", SY 104/132-135.

    P3.1 §4.3: UE 74 bes secenek gosterir (Daire · Dukkan/Ticari · Ofis · Depo ·
    Otopark), bu yuzden `office` / `warehouse` / `parking` eklendi. Enum genislemesi
    `ALTER TYPE ... ADD VALUE` ile DEGIL, tip TAKASIYLA yapilir (izole revizyon
    `c1d2e3f4a5b6`) — `ADD VALUE` ayni islem icinde kullanilamaz ve GERI ALINAMAZ.

    Karar 13: ekran etiketleri DEGISMEZ (KY 71 / KK 72 / SY 74 hala "Daire +
    Dukkan" der); uc yeni deger yalniz sayaclara eklenir ve sifirsa gorunmez.
    """

    apartment = "apartment"
    shop = "shop"
    office = "office"
    warehouse = "warehouse"
    parking = "parking"


class UnitOwnerSide(str, enum.Enum):
    """KKP 90 "Sahip" sutunu: 100 `BIZ` (contractor), 109 `ARSA` (landowner)."""

    contractor = "contractor"
    landowner = "landowner"


class Block(Base):
    """Blok — proje altindaki unite grubu (spec §4.1).

    Tablonun kendisi ve `site_id` bagi MOCKUP'TA YOKTUR; ikisi de kullanici
    karari 2026-07-30 ile onayli sapmadir (spec §2.5/§13). Ekranda blok yine
    yalnizca grup basligidir.

    Blok adi PROJE icinde benzersizdir, santiye icinde degil: KY 271 ve KKP 86
    blok adini santiye baglami olmadan gosterir ("A Blok · Daire 12"), ayni
    projede iki "A Blok" olsaydi etiket ayirt edilemezdi.

    Kat sayisi / teslim tarihi / blok kodu gibi alanlar BILINCLI OLARAK YOKTUR
    (spec §4.1 notu): mockup'ta karsiliklari yok, ihtiyac dogunca additive eklenir.
    """

    __tablename__ = "blocks"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_blocks_project_name"),
        # Yapay gorunur ama islevseldir: `units`'in bilesik FK'sinin hedefidir
        # (spec §4.1), boylece unit.project_id != block.project_id DB duzeyinde
        # imkansiz olur — servis korkuluguna guvenilmez.
        UniqueConstraint("project_id", "id", name="uq_blocks_project_id_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sites.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    # SY 74/104 blok sirasi alfabetik olmayabilir ("Zemin" en sonda: KY 308).
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Unit(Base):
    """Unite — blok altindaki daire/dukkan (spec §4.2).

    `site_id` YOKTUR: santiye blok uzerinden turetilir (spec §4.0). Iki farkli
    yoldan ayni gercege ulasmak senkron kaymasi demektir; tek otorite `blocks`.

    Ileri bag ACILMAZ (spec §1.3): `sale_id`, `shareholder_id`, `contract_id`,
    `sales_status` gibi sutunlar yoktur — satis durumu P8'in tablosunun turevidir.

    Iki ayri fiyat sutunu (spec §4.4, kullanici karari): `list_price` satisa
    cikarilan fiyattir (KY 274 "Liste Fiyati"), `appraisal_value` paylasimin
    tabani olan noter/ekspertiz degeridir (KKP 89 "Rayic Deger"). Tek sutuna
    sikistirmak, kendi payimizi satisa cikardigimizda rayic degerin uzerine
    yazilmasi ve paylasim tablosunun geriye donuk bozulmasi demek olurdu.

    TUZAK — ileride proje/santiye DELETE ucu acilirsa: `blocks` DB'de projeye ve
    santiyeye CASCADE ile baglidir, ama `units.block_id` RESTRICT'tir. Ham SQL ile
    `DELETE FROM projects` sorunsuz calisir (Postgres unite cascade'ini once
    isletir), buna karsin ORM uzerinden `session.delete(project)` once
    `DELETE FROM sites` yayinlar — ORM uniteleri bilmedigi icin bloklar
    dusurulmeye calisilir ve RESTRICT'e carpar. Boyle bir uc yazilirsa uniteler
    ONCE elle silinmelidir. Bugun projede de santiyede de DELETE ucu YOKTUR.
    """

    __tablename__ = "units"
    __table_args__ = (
        # Bilesik FK: blok–proje tutarliligini DB zorlar (spec §4.3).
        ForeignKeyConstraint(
            ["project_id", "block_id"],
            ["blocks.project_id", "blocks.id"],
            name="fk_units_block_project",
            ondelete="RESTRICT",
        ),
        # Benzersizlik blokla birlikte tanimlidir: A Blok "1" ile B Blok "1"
        # ayni anda vardir (SY 76 ve 106).
        UniqueConstraint("block_id", "unit_no", name="uq_units_block_no"),
        CheckConstraint("gross_area_m2 IS NULL OR gross_area_m2 >= 0", name="ck_units_gross_area"),
        CheckConstraint("net_area_m2 IS NULL OR net_area_m2 >= 0", name="ck_units_net_area"),
        CheckConstraint("list_price IS NULL OR list_price >= 0", name="ck_units_list_price"),
        CheckConstraint(
            "appraisal_value IS NULL OR appraisal_value >= 0", name="ck_units_appraisal_value"
        ),
        CheckConstraint(
            "gross_area_m2 IS NULL OR net_area_m2 IS NULL OR net_area_m2 <= gross_area_m2",
            name="ck_units_net_le_gross",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # ON DELETE RESTRICT: unitesi olan blok silinemez (spec §7.9). Servis
    # korkulugu VE DB kisiti iki katmanli guvence olusturur — 24 daireyi tek
    # istekte sessizce silmek geri alinamaz veri kaybidir.
    block_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("blocks.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    unit_no: Mapped[str] = mapped_column(String(30), nullable=False)
    unit_kind: Mapped[UnitKind] = mapped_column(Enum(UnitKind, name="unit_kind"), nullable=False)
    layout: Mapped[str | None] = mapped_column(String(20), nullable=True)
    gross_area_m2: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    net_area_m2: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    list_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    appraisal_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    # Nullable kalir: paylasim noterden sonra girilir (KKP 78, spec §5.3).
    owner_side: Mapped[UnitOwnerSide | None] = mapped_column(
        Enum(UnitOwnerSide, name="unit_owner_side"), nullable=True
    )
    # `unit_no` metin oldugu icin alfabetik sira "10 < 2" verir (SY 76-99).
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
