"""Satinalma cekirdegi — tedarikci + talep + teklif + siparis (SA spec §2).

BES TABLO:
  * `suppliers`              — tedarikci katalogu (TED karti)
  * `purchase_requests`      — satin alma talebi basligi (FST + SAT tablosu)
  * `purchase_request_lines` — talebin kalemleri (katalog kartli VEYA serbest metin)
  * `purchase_quotes`        — teklifler (TEK karsilastirma kartlari)
  * `purchase_orders`        — siparisler (SIP)

Modul adi `procurement`dir cunku IZIN anahtari da odur: seed'de "Satinalma &
Teklif" (ModuleGroup.STOK_SATINALMA) ZATEN VARDIR — yeni izin modulu ACILMAZ,
izin migration'i YOKTUR (spec §2).

TUREV OLAN HER SEY KOLON DEGILDIR (spec §2, kalici karar):
  * talebin/kalemin tutari      = SUM(quantity * estimated_unit_price)
  * "Mevcut Stok" (FST 75)      = ST bakiyesi (`stock_entry_lines` toplami)
  * "EN IYI FIYAT"/"EN HIZLI"   = tekliflerin karsilastirmasi
  * "Bu Yil Toplam Siparis"     = tedarikcinin siparislerinin toplami
  * `pending_orders` sayaci     = approved + in_transit siparis sayisi
Kolon acilsaydi iki kaynak olurdu ve biri otekinden kacinilmaz sekilde sapardi.

ACILMAYANLAR (spec §5, kasitli): cok adimli onay MOTORU/tablosu (§7 S2 — tek
onay adimi + ₺500K esigi) · tedarikci PUANI (degerlendirme girisi yok) ·
tedarikci adres/e-posta/IBAN (mockup'ta yok) · mal kabul tablosu ve kismi
teslim alanlari (§7 S4 — stok girisi siparisi otomatik `delivered` yapar) ·
e-posta/bildirim alanlari (altyapi yok).

ST bagi: `stock_entries.purchase_order_id` ADDITIVE kolonu ST modulunde
tanimlanir (`app/modules/inventory/models.py`) — bu modulu import ETMEDEN,
string tablo adiyla. Ters yonde iliski de KURULMAZ: iki modul birbirini import
ederse P10'un `cost_cards` import cemberi tekrarlanir.

Serbest metin tavani: `justification` / `note` kolonlari `Text`tir (DB'de
sinirsiz); 2000 karakter tavani TB4 standardi geregi SEMA katmanindadir
(`app.core.text.FREE_TEXT_MAX_LENGTH`) — uclari yazan T2/T3 bu sabiti
kullanmak ZORUNDADIR, migration gerekmez.
"""

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


class PaymentTerms(str, enum.Enum):
    """Odeme vadesi — TED 50/71/91/112 + FST 134'un KAPALI kumesi.

    Hem tedarikcinin varsayilan vadesi hem de teklifin vadesi bu tiptir; teklif
    tedarikcinin varsayilanindan SAPABILIR (pazarlik), bu yuzden iki ayri kolon.
    """

    cash = "cash"
    days_15 = "days_15"
    days_30 = "days_30"
    days_60 = "days_60"


class PurchasePriority(str, enum.Enum):
    """Talep onceligi (FST 55)."""

    normal = "normal"
    urgent = "urgent"
    critical = "critical"


class PurchaseRequestStatus(str, enum.Enum):
    """Talep durumu — §7 S1 ALTILI kume (SAT rozetleri + FST "Taslak") BIREBIR.

    `draft → pending_approval → quote_wait → ordered → delivered` + `rejected`.
    "Revize" gibi bir ara durum UYDURULMAZ — mockup'ta yoktur. Gecis matrisi
    T3'un isidir; DB burada yalniz kumeyi sabitler.
    """

    draft = "draft"
    pending_approval = "pending_approval"
    quote_wait = "quote_wait"
    ordered = "ordered"
    delivered = "delivered"
    rejected = "rejected"


class PurchaseOrderStatus(str, enum.Enum):
    """Siparis durumu — SIP 34 filtresi birebir.

    `delivered` damgasini stok girisi ATAR (§7 S4): `purchase_order_id` tasiyan
    bir giris kaydedilince siparis (ve varsa talebi) otomatik teslim sayilir.
    Kismi teslim ayrimi YOKTUR — bilinen sinir.
    """

    approved = "approved"
    in_transit = "in_transit"
    delivered = "delivered"


# `payment_terms` IKI tabloda kullanilir (tedarikcinin varsayilani + teklifin
# vadesi). Tip nesnesi TEK YERDE kurulur ve `metadata`ya baglanir: her kolonda
# ayri bir `Enum(...)` yazilsaydi `create_all` ayni tipi IKI KEZ yaratmayi
# denerdi ("type already exists"). Ayni sebeple `create_type` kararini da tek
# nesne tasir.
payment_terms_enum = Enum(PaymentTerms, name="payment_terms", metadata=Base.metadata)


class Supplier(Base):
    """Tedarikci karti (TED).

    SILINMEZ (spec §4): DELETE ucu yoktur, kullanimdan kaldirma `is_active=false`
    iledir; zaten teklifi/siparisi olan tedarikci FK RESTRICT'i yuzunden
    dusurulemez de.

    `category` SERBEST METINDIR: TED alt-etiketi ("Hazir Beton", "Nakliye", …)
    acik uclu bir kumedir — enum ICAT EDILSEYDI her yeni tedarikci turu
    migration gerektirirdi.

    `tax_no` String(10): TR vergi kimlik numarasi 10 hanedir. UNIQUE DEGILDIR —
    mockup'ta zorunlu bir alan degildir ve bosluk birakan kayitlarin cakismasi
    kullaniciyi kilitlerdi; tekillik gerekirse T2'nin isidir.

    PUAN/PERFORMANS KOLONU YOKTUR (spec §5): degerlendirme girisi hicbir ekranda
    yoktur, uydurma bir puan gostermektense hic gostermemek dogrudur.
    """

    __tablename__ = "suppliers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tax_no: Mapped[str | None] = mapped_column(String(10), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    payment_terms: Mapped[PaymentTerms] = mapped_column(payment_terms_enum, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class PurchaseRequest(Base):
    """Satin alma talebi basligi (FST formu + SAT tablosu satiri).

    `request_no` SUNUCU URETIR (§7 S6, `numbering.generate_request_number`) ve
    GLOBAL TEKILDIR — istemciden gelen bir numara kabul edilmez.

    Kapsam: talebin sahibi PROJEDIR (`project_id` zorunlu, CASCADE — repo
    deseni). `site_id`/`section_id` yalnizca DARALTMADIR (FST 57, istege bagli):
    santiye silinirse talep KALIR ve bagi kopar (SET NULL); CASCADE olsaydi
    santiye kapaninca satinalma tarihi de silinirdi.

    Onay meta'si UC alandan ibarettir (`approved_by_user_id`/`approved_at` +
    `rejected_at`/`rejection_reason`): §7 S2 geregi TEK onay adimi vardir. ₺500K
    esigi bir KURALDIR, kolon degildir; FST 159-165'teki zincir gorseli
    frontend turevidir ve burada bir "adim" tablosu ACILMAZ.

    TOPLAM TUTAR KOLONU YOKTUR: kalemlerin `quantity * estimated_unit_price`
    toplamidir. Esik denetimi de bu turevden yapilir — kolon olsaydi kalem
    degisiminde bayatlar ve esik SESSIZCE atlatilabilirdi.
    """

    __tablename__ = "purchase_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # 20 hane: `SAT-2026-0001` 13 karakter; dolgu asilirsa (10000+) yine sigar.
    request_no: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    request_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    priority: Mapped[PurchasePriority] = mapped_column(
        Enum(PurchasePriority, name="purchase_priority"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sites.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    section_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sections.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    needed_by: Mapped[date | None] = mapped_column(Date, nullable=True)
    # FST gerekce alani. Tavan SEMA katmanindadir (bkz. modul docstring'i).
    justification: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[PurchaseRequestStatus] = mapped_column(
        Enum(PurchaseRequestStatus, name="purchase_request_status"),
        nullable=False,
        default=PurchaseRequestStatus.draft,
        server_default="draft",
        index=True,
    )
    quote_deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # RESTRICT (repo deseni: hakedis/gunluk "olusturan" alanlari): talebi acan
    # kullanici, kaydi sahipsiz birakacak sekilde silinemez.
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class PurchaseRequestLine(Base):
    """Talebin kalem satiri (FST kalem tablosu).

    IKI KAPILI: kalem ya bir stok KARTINA baglanir (`stock_item_id`, FST 104
    "stok kartindan sec") ya da KATALOGSUZDUR (`free_text_name`/`free_text_unit`,
    FST "yeni malzeme tanimla"). Ikisinin ayni anda dolmasi/bosalmasi DB'de
    kisitlanmaz: taslak talep GEVSEKTIR (P6 deseni — draft yarim kaydedilebilir,
    `submit` sikidir) ve XOR CHECK'i taslagi kilitlerdi. Kural T2'nin isidir.

    `quantity > 0` ise DB'de CHECK'lidir: ST'nin negatif duzeltme istisnasi
    burada YOKTUR — sifir/negatif miktarli bir TALEP kalemi hicbir durumda
    anlamli degildir ve esik hesabini da bozardi.

    SATIR TUTARI KOLONU YOKTUR: `quantity * estimated_unit_price` TUREVDIR.
    "Mevcut Stok" (FST 75) de TUREVDIR — ST bakiyesinden okunur.

    `sort_order` (T3): FST kalem tablosu SIRALIDIR. Deger govdedeki kalem
    dizisinin INDEKSIDIR — istemci ayri bir alan GONDERMEZ, cunku gonderseydi
    cakisan/bosluklu siralar dogar ve sunucunun onlari yeniden duzenlemesi
    gerekirdi. Sunucu varsayilani da YOKTUR (NOT NULL, `server_default` yok):
    her yazma yolu degeri acikca doldurmak zorundadir.

    Zaman damgasi TASIMAZ: satirin omru basliga baglidir (CASCADE) ve mockup
    satir bazinda tarih GOSTERMEZ.
    """

    __tablename__ = "purchase_request_lines"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_purchase_request_lines_quantity_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("purchase_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stock_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("stock_items.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    free_text_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # ST'nin `unit` kolonuyla ayni olcek: birim SERBEST metindir, enum degildir.
    free_text_unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Miktar olcegi repo standardi Numeric(14, 3) — boq/sozlesme/hakedis/ST ile ayni.
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    estimated_unit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)


class PurchaseQuote(Base):
    """Bir talebe verilen teklif (TEK karsilastirma kartlari).

    `delivery_time` SERBEST METINDIR (TEK 67: "3 is gunu" / "Yarin sabah"):
    gun SAYISINA zorlanmaz. "EN HIZLI" rozeti bu yuzden istemci/servis
    turevidir; siralanabilir bir `delivery_days` kolonu ACILSAYDI mockup'un
    yazdigi ifadeler kaybolurdu.

    `shipping_included=false` iken `shipping_cost` doldurulur (TEK 90 "Hariç
    (+₺8.000)"); dahilse tutar YOKTUR — bu yuzden nullable.

    `is_selected` yalnizca bir DAMGADIR; "tek secili teklif" kurali `select-and-
    order` ucunun (T3) sorumlulugudur — kismi UNIQUE indeks, teklif duzenleme
    sirasinda gecici iki-secili durumu imkansiz kilarak ucu kilitlerdi.

    Tedarikci basina teklif TEKILLIGI de DB'de zorlanmaz: revize teklif akisi
    (ayni tedarikcinin ikinci fiyati) mockup'ta yasaklanmamistir.
    """

    __tablename__ = "purchase_quotes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("purchase_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("suppliers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    delivery_time: Mapped[str] = mapped_column(String(100), nullable=False)
    warranty_note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    payment_terms: Mapped[PaymentTerms] = mapped_column(payment_terms_enum, nullable=False)
    shipping_included: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    shipping_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    is_selected: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class PurchaseOrder(Base):
    """Siparis (SIP).

    `order_no` SUNUCU URETIR (§7 S6, `numbering.generate_order_number`).

    `request_id` NULLABLE'dir (§7 S3): SIP 35 "+ Siparis Olustur" dogrudan
    siparis acar ve mockup'taki SP-035'in talep karsiligi yoktur — talepsiz
    siparis MESRUDUR. Talebi olan siparis ise talebi KILITLER (RESTRICT):
    siparise donusmus bir talep silinirse siparisin gerekcesi kaybolurdu.

    `quote_id` SET NULL: secilen teklif bir gun dusurulse bile siparis kaydi
    ayakta kalir (tutar zaten `total_amount`ta donmustur).

    `total_amount` KOLONDUR, turev DEGILDIR — bilincli: siparis, teklifin o
    andaki fiyatinin DONMUS halidir; teklif sonradan duzeltilse bile verilen
    siparisin tutari degismemelidir.

    ## 🔴 SA-KILIT — `request_id` TEKILDIR (`uq_purchase_orders_request_id`)

    Bir talep EN COK BIR siparise donusur ve bu artik DB'de zorlanir. Kural
    uydurulmadi, urunden OLCULDU:

    * `request_id`i NULL-DISI yazan TEK yer `service.orders.select_and_order`;
      dogrudan siparis (`create_order`) her zaman `None` yazar,
    * `PurchaseOrderCreate` semasinda `request_id` YOKTUR (govdede gonderilse
      yok sayilir — `test_govdedeki_request_id_YOK_SAYILIR`),
    * `PurchaseOrderUpdate`te de YOKTUR: bag sonradan KURULAMAZ/DEGISTIRILEMEZ,
    * `REQUEST_TRANSITIONS`ta `ordered` hicbir ciftte KAYNAK degildir -> ayni
      talep ikinci kez `select-and-order` edilemez,
    * siparis durumlari `approved/in_transit/delivered`tir; **IPTAL durumu
      YOKTUR** ve `DELETE /purchase-orders/{id}` de yoktur (405, bekci testli)
      -> "iptal edip yeniden siparis" akisi da YOKTUR.

    Yani bugun bir talebin BOLUNEREK birden cok siparise donmesinin MESRU bir
    yolu yoktur; kisit hicbir akisi kirmaz. Kirilirsa (kismi/bolunmus siparis
    urune eklenirse) dogru hamle kisiti kismilastirmak ya da dusurmektir —
    sessizce cift kayda donmek DEGIL.

    🔴 **NULL'lar kisittan ETKILENMEZ:** Postgres UNIQUE coklu NULL'a izin
    verir, dolayisiyla TALEPSIZ (SIP 35) siparisler sinirsizdir. Bu davranis
    varsayilmadi, olculdu ve `test_DB_katmani_da_cift_siparisi_reddeder`de
    ACIKCA bekcilenir.

    Kisit UYGULAMA kilidinin YEDEGIDIR, yerine gecmez: asil savunma ucun
    `service.visible_request_locked` kapisidir (`router.select_and_order_
    endpoint`). Iki katman bilinclidir — `select_and_order`i cagirmayan yeni
    bir yazma yolu yarin acilirsa kusur DB'de durur.
    """

    __tablename__ = "purchase_orders"
    __table_args__ = (UniqueConstraint("request_id", name="uq_purchase_orders_request_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_no: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("purchase_requests.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    quote_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("purchase_quotes.id", ondelete="SET NULL"),
        nullable=True,
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("suppliers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    expected_delivery: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[PurchaseOrderStatus] = mapped_column(
        Enum(PurchaseOrderStatus, name="purchase_order_status"),
        nullable=False,
        default=PurchaseOrderStatus.approved,
        server_default="approved",
        index=True,
    )
    # SIP serbest notu. Tavan SEMA katmanindadir (bkz. modul docstring'i).
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
