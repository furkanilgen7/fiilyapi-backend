"""Stok cekirdegi — katalog + depo + giris hareketleri (ST spec §2).

DORT TABLO, BILINCLI AYRIM:
  * `stock_items`      — malzeme KARTI (katalog); hareketten bagimsiz yasar
  * `warehouses`       — depo; `site_id IS NULL` = merkez depo (SG 84)
  * `stock_entries`    — hareket BASLIGI (SG formunun ust yarisi)
  * `stock_entry_lines`— hareketin satirlari (SG formunun kalem tablosu)

**BAKIYE KOLONU YOKTUR** (spec §3): depo/kart bakiyesi
`SUM(stock_entry_lines.quantity)` TUREVIDIR. Kolon acilsaydi iki kaynak olurdu
ve biri digerinden kacinilmaz sekilde sapardi; transferin cift bacagi (§7 S4)
zaten toplam korunumunu saglar.

Modul adi `inventory`dir cunku IZIN anahtari da odur: seed'de "Stok & Depo"
(ModuleGroup.STOK_SATINALMA) ZATEN vardir — spec §7 S5 geregi yeni izin modulu
ACILMAZ, izin migration'i YOKTUR.

Kapsam disi (spec §5, kasitli): tedarikci KATALOGU (yalniz
`supplier_name` serbest metin) · sarf/cikis tablosu (tek kapi `adjustment`
satirinin negatif miktaridir) · belge alani (BC form-slot) · bolum-ihtiyac
kolonu (ŞS "Aylik Ihtiyac"/"Bolum" PENDING). Bunlar SA ve BC dilimlerinin isidir.
ST'nin siparis FK'si SA T1'de (`f3a4b5c6d7e8`) ADDITIVE olarak acildi:
`stock_entries.purchase_order_id` — tedarikci ise HALA serbest metindir.

Serbest metin tavani: `note` kolonu `Text`tir (DB'de sinirsiz); 2000 karakter
tavani TB4 standardi geregi SEMA katmanindadir (`app.core.text.FREE_TEXT_MAX_LENGTH`)
— hareket ucunu yazan T3 bu sabiti kullanmak ZORUNDADIR, migration gerekmez.
"""

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
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


class StockCategory(str, enum.Enum):
    """Malzeme kartinin kategorisi (E3 99 select + tablo rozetleri).

    Yapi Malzemesi · Demir-Celik · Elektrik · Mekanik · Ic Yapi — mockup'un
    KAPALI kumesidir, bu yuzden enum'dur. Birim (`unit`) ise aksine ACIK
    ucludur ve SERBEST METIN kalir.
    """

    structural = "structural"
    steel = "steel"
    electrical = "electrical"
    mechanical = "mechanical"
    interior = "interior"


class StockEntryType(str, enum.Enum):
    """Hareket tipi (SG 53-76).

    `purchase`   — satin alma girisi (miktar > 0)
    `transfer`   — depolar arasi tasima; `source_warehouse_id` ZORUNLU ve kaynak
                   depodan ayni miktarda otomatik dusus yapilir (CIFT BACAK,
                   §7 S4). Tek bacak olsaydi transfer stok YARATIRDI.
    `adjustment` — sayim farki / iade / sarf; satirlari NEGATIF olabilir.

    Kurallar tipe BAGLI oldugu icin DB'de degil, hareket ucunda (T3) uygulanir.
    """

    purchase = "purchase"
    transfer = "transfer"
    adjustment = "adjustment"


class StockQuality(str, enum.Enum):
    """Teslim alinan kalemin kalite damgasi (SG 117 ✓/⚠/✗)."""

    ok = "ok"
    defective = "defective"
    rejected = "rejected"


class StockItem(Base):
    """Malzeme KARTI — katalog (SG 134 "stok karti").

    `code` SERBEST bicimlidir (SNK-0421 yalnizca bir ornektir; onek ZORLANMAZ)
    ama GLOBAL tekildir: ayni kod iki kart olamaz.

    `min_stock` NULL olabilir — o zaman kartin durumu (Kritik/Dusuk/Normal/Fazla)
    `None`dur; esik yokken durum UYDURULMAZ (spec §3).

    SILINMEZ: hareketi olan kart `stock_entry_lines` RESTRICT'i yuzunden zaten
    dusurulemez; kullanimdan kaldirma `is_active=false` iledir (spec §4).
    """

    __tablename__ = "stock_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[StockCategory] = mapped_column(
        Enum(StockCategory, name="stock_category"), nullable=False
    )
    # SERBEST METIN (spec §2): Ton/Torba/Metre/Adet/m³ — mockup kumesi acik uclu,
    # enum ICAT EDILMEZ; yeni bir birim migration gerektirmemelidir.
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    # Miktar olcegi repo standardi Numeric(14, 3) — boq/sozlesme/hakedis ile ayni.
    min_stock: Mapped[Decimal | None] = mapped_column(Numeric(14, 3), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Warehouse(Base):
    """Depo (spec §7 S2). Ornek veri SEED EDILMEZ (D-1/D-2/D-3 mockup verisidir).

    `site_id IS NULL` = MERKEZ DEPO ("Merkez Depo (Sincan)", SG 84): hicbir
    santiyeye bagli degildir ve gorunurlugu proje kapsamina DEGIL, yalniz stok
    iznine baglidir (§7 S2b). Zorunlu bir `site_id` merkez depoyu modellenemez
    kilardi.

    `SET NULL`: santiye silinirse deposu ve dolayisiyla hareket gecmisi
    KAYBOLMAZ, yalnizca santiye bagi kopar (fiilen merkez depoya doner).
    CASCADE burada bakiye tarihini silerdi.

    UQ (site_id, name): ayni santiyede ayni adli iki depo acilamaz. BILINEN SINIR
    — Postgres'in varsayilan `NULLS DISTINCT` semantigi yuzunden merkez depo
    dalinda (`site_id IS NULL`) kisit fiilen ISLEMEZ; oradaki tekillik yazma
    ucunun (T2: mevcut-ad kontrolu → 409) sorumlulugundadir (belge arsivi
    `document_folders` ile ayni durum).
    """

    __tablename__ = "warehouses"
    __table_args__ = (UniqueConstraint("site_id", "name", name="uq_warehouses_site_name"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sites.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class StockEntry(Base):
    """Hareket BASLIGI — SG formunun ust yarisi.

    `warehouse_id` HEDEF depodur ve ZORUNLUDUR; `RESTRICT` cunku hareketi olan
    bir depo silinirse bakiye sessizce degisirdi.

    `source_warehouse_id` yalniz `transfer` tipinde dolar (kaynak depo). Tip
    kurali DB'de DEGIL uygulama katmanindadir (T3) — Postgres'te tipe bagli
    kosullu zorunluluk ancak CHECK ile ifade edilirdi ve ileride yeni bir tip
    eklendiginde migration gerektirirdi.

    `supplier_name` SERBEST METINDIR (§7 S3): tedarikci KATALOGU SA diliminin
    isidir; simdiden FK acilsaydi SA geldiginde geriye donuk eslestirme borcu
    dogardi.

    `received_by_user_id` `SET NULL`: kullanici silinse de irsaliye kaydi durur.
    """

    __tablename__ = "stock_entries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entry_type: Mapped[StockEntryType] = mapped_column(
        Enum(StockEntryType, name="stock_entry_type"), nullable=False
    )
    entry_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("warehouses.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    source_warehouse_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("warehouses.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    supplier_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # SA dilimi (T1) ile ACILDI: SG 85 "Ilgili Siparis" gercege doner.
    #
    # IMPORT CEMBERI KURULMAZ (P10 `cost_cards` tuzagi): hedef tablo STRING adla
    # yazilir, `app.modules.procurement` BURADA import EDILMEZ ve karsi tarafta
    # cift yonlu bir `relationship` de KURULMAZ. Bagi okuyan uc (T4) siparisi
    # kendi sorgusuyla getirir.
    #
    # SET NULL: siparis kaydi bir gun dusurulse bile stok hareketi KALIR —
    # bakiye bir satinalma kaydina bagli olarak yok olamaz.
    purchase_order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("purchase_orders.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    delivery_note_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    received_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # SG 169 serbest notu. Tavan SEMA katmanindadir (bkz. modul docstring'i).
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # T3: hareket LISTESI satirlariyla birlikte doner ve `selectinload` ile TEK
    # ek sorguda gelir (N+1 yok). `lazy="raise"` BILINCLIDIR: async oturumda
    # tembel yukleme `MissingGreenlet` ile 500 uretir (P11'in devrettigi tuzak),
    # bu yuzden yukleme UNUTULURSA sessiz bir yavaslama degil GURULTULU bir
    # hata olsun istenir. Yazma yolu (`POST /stock/entries`) bu koleksiyona hic
    # DOKUNMAZ: yanit, olusturulan satir nesnelerinden dogrudan kurulur.
    lines: Mapped[list["StockEntryLine"]] = relationship(
        "StockEntryLine",
        cascade="all, delete-orphan",
        order_by="StockEntryLine.id",
        lazy="raise",
    )


class StockEntryLine(Base):
    """Hareketin kalem satiri — SG formunun kalem tablosu.

    `quantity` ISARET KISITI TASIMAZ: `adjustment` satirlari NEGATIF olabilir
    (sayim farki/iade/sarf tek kapisi, §7 S4). "purchase > 0" kurali TIPE
    baglidir ve baslikta durur — DB'de ifade edilseydi cok tablolu bir CHECK
    gerekirdi. Eksi bakiye de ENGELLENMEZ, yalnizca raporlanir.

    SATIR TUTARI KOLONU YOKTUR: `quantity * unit_price` TUREVDIR (spec §2).
    `unit_price` nullable — transfer/duzeltme satirlarinda fiyat yoktur ve
    fiyatsiz kalem toplam stok degerine GIRMEZ (§7 S6).
    """

    __tablename__ = "stock_entry_lines"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("stock_entries.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("stock_items.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # --- BOLUM / POZ ATFI (STOK-BOLUM T1, kullanici karari 2026-08-29) ---
    #
    # 🔴 ETIKET SATIR BAZINDADIR, baslikta DEGIL: tek bir sarf fisi ayni gun
    # farkli malzemeleri farkli pozlara cikarabilir.
    #
    # 🔴 BUNLAR BAKIYENIN BOYUTU DEGILDIR. "STOK DEPODA DURUR, BOLUM TUKETIR":
    # bolume ayri depo acilmaz, `balance.legs()` bir satir bile degismez ve
    # bakiye DEPO duzeyinde kalir. Buraya bakan bir sonraki okuyucu bakiyeyi
    # `section_id`ye gore gruplamaya KALKMASIN — o sayi bir bakiye degil, bir
    # ATIF toplamidir ve ayri bir uctan (`GET /sections/{id}/stock`) doner.
    #
    # ⚠️ `purchase_requests.section_id` ILE KARISTIRILMAZ. O bag *"bu malzemeyi
    # HANGI BOLUM TALEP ETTI"*dir (satinalma niyeti); bu kolon ise *"bu satirin
    # malzemesi HANGI BOLUM icin depoya girdi / hangi bolumden cikti"*dir
    # (stok gercegi). Ikisi ayri zamanlarda ve ayri kisilerce dolar, birbirinden
    # turetilemez — bkz. `schemas.SiteStockRow` docstring'i.
    #
    # SET NULL (desen `site_diary_lines.boq_item_id`ten olculdu): poz ya da
    # bolum dusurulse de stok hareketi KALIR. CASCADE secilseydi bir bolumun
    # silinmesi hareket satirini ve dolayisiyla BAKIYEYI degistirirdi.
    #
    # IMPORT CEMBERI KURULMAZ (`purchase_order_id` deseni): hedef tablolar
    # STRING adla yazilir, `app.modules.sites` / `app.modules.boq` BURADA
    # import EDILMEZ ve karsi tarafta `relationship` de kurulmaz.
    section_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sections.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    boq_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("boq_items.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    quality: Mapped[StockQuality] = mapped_column(
        Enum(StockQuality, name="stock_quality"),
        nullable=False,
        default=StockQuality.ok,
        server_default="ok",
    )
