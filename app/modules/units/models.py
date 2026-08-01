import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
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


class BlockRoofType(str, enum.Enum):
    """BE 80 "Cati Tipi": Yok · Dubleks · Teras."""

    none = "none"
    duplex = "duplex"
    terrace = "terrace"


class BlockGroundUsage(str, enum.Enum):
    """BE 82 "Zemin Kat Kullanimi": Ticari · Konut · Ortak Alan."""

    commercial = "commercial"
    apartment = "apartment"
    common = "common"


class BlockParkingType(str, enum.Enum):
    """BE 86 "Otopark": Kapali · Acik · Yok."""

    closed = "closed"
    open = "open"
    none = "none"


class BlockStatus(str, enum.Enum):
    """BE 101 "Durum": Planlama · Insaat Halinde · Tamamlandi.

    Sunucu varsayilani `construction` (mockup 101 `selected`), fakat sutun
    NULLABLE kalir: mevcut canli bloklara "Insaat Halinde" varsaymak yanlis
    olabilirdi ve karar 8 canli satirlara dokunan veri migration'ini yasaklar.
    """

    planning = "planning"
    construction = "construction"
    completed = "completed"


class UnitFacing(str, enum.Enum):
    """UE 78 / TU 112 "Cephe" — karar 7: mockup'ta gecen TAM OLARAK bes deger.

    Pusulanin kalan uc yonu (`northeast`, `northwest`, `southeast`) ICAT EDILMEZ;
    ihtiyac dogarsa additive olarak enum takasiyla eklenir (spec §4.2).
    """

    south = "south"
    southwest = "southwest"
    east = "east"
    north = "north"
    west = "west"


class UnitParkingRight(str, enum.Enum):
    """UE 81 "Otopark Hakki": Yok · 1 Kapali · 2."""

    none = "none"
    one_closed = "one_closed"
    two = "two"


class UnitSalesStatus(str, enum.Enum):
    """UE 94 "Satis Durumu": Satista (Bos) · Rezerve · Satildi · Satisa Kapali.

    "Arsa Sahibinde" (KKP 92) bu kumeye GIRMEZ: o `owner_side='landowner'`
    turevidir ve zaten `is_landowner_share` olarak doner. KY 276'nin "Tapulu"
    degeri de girmez — tapu devri P8'in kaydidir ve `sold` ile eslenir.
    """

    listed = "listed"
    reserved = "reserved"
    sold = "sold"
    closed = "closed"


class Block(Base):
    """Blok — proje altindaki unite grubu (spec §4.1).

    Tablonun kendisi ve `site_id` bagi MOCKUP'TA YOKTUR; ikisi de kullanici
    karari 2026-07-30 ile onayli sapmadir (spec §2.5/§13). Ekranda blok yine
    yalnizca grup basligidir.

    Blok adi PROJE icinde benzersizdir, santiye icinde degil: KY 271 ve KKP 86
    blok adini santiye baglami olmadan gosterir ("A Blok · Daire 12"), ayni
    projede iki "A Blok" olsaydi etiket ayirt edilemezdi.

    P3.1 (`Form - Blok Ekle`): kat sayisi, teslim tarihi ve blok kodu dahil 13
    alan EKLENDI — P3'te "mockup'ta karsiligi yok" gerekcesiyle atlanmislardi,
    blok formu mockup'i bunlari acikca istiyor. Hicbiri NOT NULL DEGILDIR
    (taslak destegi); `status` yalniz YENI satirlar icin `construction`
    varsayilani alir. "Tahmini Toplam Ünite" SAKLANMAZ — turevdir (spec §3.3).
    """

    __tablename__ = "blocks"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_blocks_project_name"),
        # Nullable sutun uzerinde: Postgres'te birden cok NULL serbesttir, bu
        # yuzden kodu olmayan eski bloklar kisiti ihlal etmez (spec §3.2).
        UniqueConstraint("project_id", "code", name="uq_blocks_project_code"),
        CheckConstraint(
            "basement_floor_count IS NULL OR basement_floor_count >= 0",
            name="ck_blocks_basement_floor_count",
        ),
        CheckConstraint("floor_count IS NULL OR floor_count >= 0", name="ck_blocks_floor_count"),
        CheckConstraint(
            "units_per_floor IS NULL OR units_per_floor >= 0", name="ck_blocks_units_per_floor"
        ),
        CheckConstraint("shop_count IS NULL OR shop_count >= 0", name="ck_blocks_shop_count"),
        CheckConstraint(
            "construction_area_m2 IS NULL OR construction_area_m2 >= 0",
            name="ck_blocks_construction_area",
        ),
        CheckConstraint(
            "elevator_count IS NULL OR elevator_count >= 0", name="ck_blocks_elevator_count"
        ),
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
    # BE 71: kod ADDAN kisaltilir ("A Blok" → "A"); PRJ-/SNT- deseni KULLANILMAZ
    # cunku unite numarasi koda baglidir (TU 159-165: `C-1`). Canli bloklarda
    # NULL dogar ve NULL kalir — backfill migration'i YOKTUR (karar 8).
    code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    basement_floor_count: Mapped[int | None] = mapped_column(Integer, nullable=True)  # BE 78
    floor_count: Mapped[int | None] = mapped_column(Integer, nullable=True)  # BE 79
    roof_type: Mapped[BlockRoofType | None] = mapped_column(
        Enum(BlockRoofType, name="block_roof_type"), nullable=True
    )  # BE 80
    units_per_floor: Mapped[int | None] = mapped_column(Integer, nullable=True)  # BE 81
    ground_floor_usage: Mapped[BlockGroundUsage | None] = mapped_column(
        Enum(BlockGroundUsage, name="block_ground_usage"), nullable=True
    )  # BE 82
    shop_count: Mapped[int | None] = mapped_column(Integer, nullable=True)  # BE 83
    # `sites.construction_area_m2` ile AYNI ad ve boy (spec §3.1).
    construction_area_m2: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    elevator_count: Mapped[int | None] = mapped_column(Integer, nullable=True)  # BE 85
    parking_type: Mapped[BlockParkingType | None] = mapped_column(
        Enum(BlockParkingType, name="block_parking_type"), nullable=True
    )  # BE 86
    estimated_delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)  # BE 100
    # NOT NULL DEGIL: varsayilan yalniz YENI satirlara uygulanir; mevcut canli
    # bloklar NULL kalir (spec §3.1, karar 8).
    status: Mapped[BlockStatus | None] = mapped_column(
        Enum(BlockStatus, name="block_status"), nullable=True, server_default="construction"
    )  # BE 101
    # `Text` degil `String(500)`: sinirsiz metin frontend'de `maxLength`
    # konamamasina ve sessiz 422 sinifina yol acar (spec §3.1).
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)  # BE 102
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

    Ileri bag ACILMAZ (spec §1.3): `sale_id`, `shareholder_id`, `contract_id`
    sutunlari yoktur.

    GELECEK IS — P8 (unite satisi) geldiginde:
    `sales_status` OTOMATIK yonetilmeye baslayacak (satis kaydi acildiginda
    `reserved`, tapu devrinde `sold` vb.) ve ELLE giris kilitlenecektir:
    `UnitCreate`/`UnitUpdate` semalarindan alan cikarilacak ya da salt-okunur
    hale gelecek. Bugun elle girilmesi gecici bir cozumdur, kalici tasarim
    degildir. P8 spec'i bu paragrafi kaynak alarak gecisi (mevcut elle girilmis
    degerlerin ne olacagini) tanimlamak zorundadir. Sutun P3.1'de kullanici
    karari 2 ile ACILDI (P3 §4.6'dan bilincli DONUS, spec §4.4) — bir sonraki
    ajan bunu "P3 ihlali" sanip SILMEMELIDIR.

    Maliyet sutunu ACILMAZ (karar 3, spec §4.5): maliyet ileride Is
    Kalemleri/satinalmadan otomatik hesaplanacaktir; `unit_cost` ve
    `expected_profit` yer tutucu olarak doner.

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
        # `ck_units_floor` YOKTUR — kat METINDIR (karar 4, spec §4.2).
        CheckConstraint(
            "balcony_area_m2 IS NULL OR balcony_area_m2 >= 0", name="ck_units_balcony_area"
        ),
        CheckConstraint(
            "bathroom_count IS NULL OR bathroom_count >= 0", name="ck_units_bathroom_count"
        ),
        CheckConstraint(
            "min_sale_price IS NULL OR min_sale_price >= 0", name="ck_units_min_sale_price"
        ),
        # Kume ({1, 10, 20}) DB'de DEGIL, Pydantic'te zorlanir (karar 9): KDV
        # listesi yasayla degisir, %8 eklenirse migration degil tek satir kod.
        CheckConstraint(
            "vat_rate IS NULL OR (vat_rate >= 0 AND vat_rate <= 100)", name="ck_units_vat_rate"
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
    # KARAR 4: kat METINDIR, sayi degil. "Zemin" / "3. Kat" / "Cati Kati"
    # etiketlerini bir tam sayiya cevirmek KONVANSIYON ICAT ETMEK olurdu
    # (cati kati = floor_count + 1?). Siralama ihtiyacini `sort_order` karsilar.
    floor: Mapped[str | None] = mapped_column(String(20), nullable=True)  # UE 66
    facing: Mapped[UnitFacing | None] = mapped_column(
        Enum(UnitFacing, name="unit_facing"), nullable=True
    )  # UE 78
    balcony_area_m2: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)  # UE 79
    bathroom_count: Mapped[int | None] = mapped_column(Integer, nullable=True)  # UE 80
    parking_right: Mapped[UnitParkingRight | None] = mapped_column(
        Enum(UnitParkingRight, name="unit_parking_right"), nullable=True
    )  # UE 81
    # `min_sale_price <= list_price` HICBIR katmanda zorlanmaz (karar 2).
    min_sale_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)  # UE 92
    vat_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)  # UE 93
    # Bkz. sinif docstring'indeki P8 gecis notu — bu sutun silinmemelidir.
    sales_status: Mapped[UnitSalesStatus | None] = mapped_column(
        Enum(UnitSalesStatus, name="unit_sales_status"), nullable=True, server_default="listed"
    )  # UE 94
    # `unit_no` metin oldugu icin alfabetik sira "10 < 2" verir (SY 76-99).
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
