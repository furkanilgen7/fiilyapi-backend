"""Fatura cekirdegi — gelen/giden fatura basligi + kalemleri (FAT-1 spec §2).

IKI TABLO:
  * `invoices`      — fatura basligi (FY listesi + FGE/FGI detay + FK formu)
  * `invoice_lines` — faturanin kalemleri (FGI:116-130 / FGE:150-160 / FK:168-183)

Modul adi `invoicing`dir cunku IZIN anahtari da odur: seed'de "Fatura Yonetimi"
(ModuleGroup.MALI) ZATEN VARDIR (`roles/seed_data.py:102`) — yeni izin modulu
ACILMAZ, izin migration'i YOKTUR (spec §6).

🔴 K7 — N-CARPANLI SNAPSHOT KANONU (MK-2→MK-3 dersi). Faturanin `total`ini
ureten carpanlarin TAMAMI burada DONMUSTUR ve hicbiri kaynaktan (hakedis /
sozlesme / ekipman karti / cari karti) CANLI OKUNMAZ:

  * miktar · birim fiyat · KDV orani        → `invoice_lines` (satir basina)
  * avans · teminat · tevkifat oranlari     → `invoices` baslik kolonlari
  * taraf unvani · VKN · vergi dairesi · adres → `invoices.party_*`
  * hesaplanan her ara toplam               → `invoices` para kolonlari

Para kolonlari TUREV OLDUKLARI HALDE SAKLANIR — bu bilincli bir istisnadir:
onaylanmis bir faturanin tutari, kaleminin/oranin sonradan duzeltilmesinden
etkilenmemelidir. Hesabin TEK KAYNAGI yine de `amounts.py`dir (T2); hicbir
uc/servis kendi toplamini hesaplamaz.

TUREV OLAN HER SEY KOLON DEGILDIR (spec §2/§3):
  * "Vade: 18.08.2026 (24 gun)" kalan gun sayisi → `due_date`ten turer (K1)
  * "Vadeli" rozeti                              → `sent` + dolu `due_date` (K1)
  * KDV farki / tahsil edilecek toplam           → ozet ucunun isi (§7 md.2)
  * satir KDV tutari                             → K3 dagitimi baslikta yapilir

ACILMAYANLAR (spec §1, kasitli — "eksik" diye geri acilmaz): GIB/e-Fatura
alanlari (UUID/ETTN/zarf/GIB durumu — hicbir YAZMA YOLU yok, hep NULL dururdu,
FAT-3'un isi) · muhasebe/yevmiye kaydi (hesap plani tablosu YOK) · tahsilat
kaydi ve banka hesabi (Hazine dilimi; burada yalniz DURUM damgasi var) ·
eslestirme motoru (FAT-2) · para birimi/kur (TRY sabit, madde 6) · iskonto
sutunu (uc kalem tablosunun hicbirinde cizili degil).

Serbest metin tavani: `note` / `description` kolonlari `Text`tir (DB'de
sinirsiz); 2000 karakter tavani TB4/B4 standardi geregi SEMA katmanindadir
(`app.core.text.FREE_TEXT_MAX_LENGTH`) — uclari yazan T3 bu sabiti kullanmak
ZORUNDADIR, migration gerekmez.

Bu modul BASKA BIR MODULU IMPORT ETMEZ: FK hedefleri string tablo adiyla
verilir (P10'un `cost_cards` import cemberi tekrarlanmaz).
"""

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


class InvoiceDirection(str, enum.Enum):
    """Fatura yonu — FGI:58 `GIDEN FATURA` · FGE:68 `GELEN FATURA`.

    Yon yalnizca bir etiket DEGILDIR: numarayi kimin urettigini (§4), hangi
    durum matrisinin gecerli oldugunu (§3) ve numara tekilliginin kapsamini
    (`uq_invoices_no_direction`) belirler.
    """

    outgoing = "outgoing"
    incoming = "incoming"


class InvoiceDocumentType(str, enum.Enum):
    """Belge tipi — FK:136-139 KAPALI kumesi birebir."""

    einvoice = "einvoice"  # e-Fatura (Satis)
    earchive = "earchive"  # e-Arsiv Fatura
    refund = "refund"  # Iade Faturasi
    withholding = "withholding"  # Tevkifatli Fatura


class InvoiceStatus(str, enum.Enum):
    """Durum — IKI YONUN kumesi TEK enum tipinde (spec §3).

    Giden:  `draft → sent → collected`
    Gelen:  `pending → approved` | `pending → disputed`

    Tek tip olmasinin sebebi `status` kolonunun tek olmasidir; YON DISI gecisi
    (giden faturaya `approve`) DB degil `transitions.py` (T2) reddeder — matris
    disi her gecis 409'dur.

    🔴 K1: "Vadeli" AYRI BIR DURUM DEGILDIR. FY:91 filtresi onu `Gonderildi`nin
    yaninda sunar ama FY'de `Gonderildi` rozetli TEK SATIR YOKTUR; ekran etiketi
    `due_date` doluysa "Vadeli", bossa "Gonderildi"dir. Turetilebilen SAKLANMAZ.

    🔴 K2: `draft` yalniz GIDEN tarafta anlamlidir — gelen fatura sisteme zaten
    kesilmis olarak girer (FGE:69 `GIB'den Geldi ✓`).

    Iptal/iade gecisi ve `approved` sonrasi ODEME durumu YOKTUR: ilki hicbir
    mockup'ta cizilmemistir, ikincisi Hazine diliminindir.
    """

    draft = "draft"
    sent = "sent"
    collected = "collected"
    pending = "pending"
    approved = "approved"
    disputed = "disputed"


class InvoicePaymentMethod(str, enum.Enum):
    """Odeme sekli — FK:145-148 KAPALI kumesi birebir."""

    transfer = "transfer"  # Havale / EFT
    cheque = "cheque"  # Cek
    cash = "cash"  # Nakit
    credit_card = "credit_card"  # Kredi Karti


#: 🔴 MU-3D — KAYNAK TEKİLLİĞİNİN KAPSAMI.
#:
#: ## "İPTAL EDİLMİŞ FATURA" BU ÜRÜNDE BİR DURUM DEĞİLDİR (ÖLÇÜLDÜ)
#:
#: `InvoiceStatus`ın ALTI üyesinin (`draft`/`sent`/`collected`/`pending`/
#: `approved`/`disputed`) HİÇBİRİ iptal anlamına gelmez ve sınıfın kendi
#: docstring'i bunu açıkça yazar: *"İptal/iade geçişi ve `approved` sonrası
#: ÖDEME durumu YOKTUR"*. `transitions.py` de aynı şeyi söyler: `collected`/
#: `approved`/`disputed` TERMİNALDİR, hiçbir çiftte KAYNAK değillerdir. Yani
#: kesilmiş bir fatura ne geri alınabilir ne silinebilir (silme YALNIZ `draft`
#: içindir, `DELETABLE_STATUS`).
#:
#: `disputed` de bir iptal DEĞİLDİR: gelen faturaya İTİRAZDIR, satır ayakta
#: kalır ve karşı tarafın belgesi geçerliliğini sürdürür.
#:
#: ## Geri almanın TEK modeli: `document_type='refund'`
#:
#: Bu üründe bir faturayı geri alan tek belge AYRI bir faturadır — İade
#: Faturası (`InvoiceDocumentType.refund`, FK:136-139 kapalı kümesi). Bu yüzden
#: kaynak tekilliğinin süzgeci DURUMA değil **BELGE TİPİNE** bakar: bir
#: hakedişe kesilmiş faturanın iadesi MEŞRUDUR ve aynı kaynağa bağlanabilmelidir,
#: ama İKİNCİ BİR ASIL FATURA bağlanamaz.
#:
#: 🔴 Metin ELLE YAZILMAZ, enum üyesinden TÜRETİLİR (`LIVE_SOURCE_WHERE`
#: kanonu): elle yazılsaydı üye yeniden adlandırıldığında süzgeç sessizce
#: HİÇBİR SATIRI süzmez ve tekillik iadeleri de kapsayarak FAZLA daralırdı —
#: yani meşru bir iade faturası kesilemez hâle gelirdi ve kusur ancak ilk
#: iadede, canlıda görünürdü.
BINDING_SOURCE_WHERE = f"document_type <> '{InvoiceDocumentType.refund.value}'"


def is_refund(invoice: "Invoice") -> bool:
    """🔴 KRIT-IADE — *"bu belge bir İADE mi"* sorusunun **TEK** kaynağı.

    Model dosyasında durur ve durmak ZORUNDADIR: bu soruyu bugün ÜÇ ayrı katman
    soruyor (fatura fişi · ödeme fişi · KDV beyannamesi) ve üçü de aynı cevabı
    vermek zorundadır. Üç yerde `invoice.document_type is
    InvoiceDocumentType.refund` yazılsaydı, dördüncü bir yüzey eklendiğinde
    (mizan · KPI şeridi) onu SORMAYAN bir kopya doğar ve kusur yine YALNIZ O
    YÜZEYDE açılırdı — KRIT-IADE'nin kusuru tam olarak buydu.

    🔴 Enum üyesiyle kıyaslanır, metinle DEĞİL (`BINDING_SOURCE_WHERE`in aynı
    kanonu): üye yeniden adlandırıldığında metin karşılaştırması sessizce
    `False` döner ve her iade normal fatura gibi fişlenirdi.
    """
    return invoice.document_type is InvoiceDocumentType.refund


#: 🔴 MU-3D — kaynak FK'si başına TEKİLLİK indeksleri: `(kolon adı, indeks adı)`.
#:
#: ## Neden GEREKLİ (ölçülmüş açık)
#:
#: MU-3D öncesi `ck_invoices_single_source` YALNIZCA *"bir faturada en fazla BİR
#: kaynak kolonu dolu olsun"* diyordu — *"bir kaynağa en fazla BİR fatura
#: bağlansın"* DEMİYORDU. Aynı `progress_payment_id` sınırsız sayıda faturaya
#: yazılabiliyordu ve bunu engelleyen HİÇBİR ŞEY yoktu: servis katmanında da
#: (`_assert_references` yalnız VARLIK ve KAPSAM bakar) bir sayım yoktu.
#:
#: Bedeli bir çift sayımdır ve İKİ yüzeyde birden görünür:
#:   · `vat_return` aynı hakedişin KDV'sini İKİ KEZ beyan eder (beyanname
#:     yalnız `invoices`tan türer ve kaynak FK'sini HİÇ görmez);
#:   · MU-3D'nin storno kuralı ikinci faturada çalışacak bir fiş BULAMAZ —
#:     hakediş fişi zaten ilk faturada stornolanmıştır — ve ikinci fatura
#:     gideri/hasılatı İKİNCİ KEZ deftere yazar.
#:
#: ## 🔴 `UniqueConstraint` DEĞİL `Index(unique=True)`
#:
#: PG'de bir UNIQUE KISITI kısmi olamaz (`WHERE` kabul etmez); `WHERE`li
#: tekillik YALNIZ `CREATE UNIQUE INDEX` ile kurulur. `NOT VALID` de bir seçenek
#: değildir: o kip YALNIZCA `CHECK` ve `FOREIGN KEY` içindir.
#:
#: 🔴 NULL'lar PG'de ayrıktır (`NULLS DISTINCT` varsayılanı) → kaynağa
#: BAĞLANMAMIŞ faturalar (çoğunluk) bu indekslerden HİÇ ETKİLENMEZ.
SOURCE_UNIQUE_INDEXES: tuple[tuple[str, str], ...] = (
    ("progress_payment_id", "uq_invoices_progress_payment"),
    ("subcontractor_progress_payment_id", "uq_invoices_subcontractor_progress_payment"),
    ("equipment_rental_invoice_id", "uq_invoices_equipment_rental_invoice"),
    ("purchase_order_id", "uq_invoices_purchase_order"),
)


def _dolu_sayisi(*kolonlar: str) -> str:
    """`en fazla biri dolu` CHECK'inin SQL metnini uretir.

    `a IS NOT NULL AND b IS NOT NULL` bicimi IKI kolon icin yeterdi ama dortte
    alti ayri ciftin yazilmasini gerektirirdi; sayim bicimi kolon eklendikce
    tek satirda buyur ve gozden kacan bir cift birakmaz.
    """
    return (
        "("
        + " + ".join(f"CASE WHEN {kolon} IS NULL THEN 0 ELSE 1 END" for kolon in kolonlar)
        + ") <= 1"
    )


# Oranlar NULLABLE'dir: NULL karsilastirmasi NULL uretir ve CHECK'i GECER —
# "kesinti isaretlenmemis" (NULL) ile "oran %0" (0) farkli seylerdir ve ekran
# ikisini ayri basar (FK:223/229/235 checkbox'lari).
_ORAN_CHECK = (
    "(advance_rate IS NULL OR advance_rate BETWEEN 0 AND 100) AND "
    "(retention_rate IS NULL OR retention_rate BETWEEN 0 AND 100) AND "
    "(withholding_rate IS NULL OR withholding_rate BETWEEN 0 AND 100)"
)


class Invoice(Base):
    """Fatura basligi (FY satiri + FGE/FGI detayi + FK formu).

    `invoice_no` NOT NULL'dir ama kaynagi YONE gore degisir (§4/S5): giden'de
    sunucu uretir (`FIL` + yil + 6 hane, ayracsiz), gelen'de ISTEMCI gonderir ve
    zorunludur (saticinin kendi serisi — FY:165/174/183 uc ayri seri koku).
    Tekillik bu yuzden GLOBAL DEGIL, YON ICINDEDIR: global olsaydi bir saticinin
    `FIL…` serisi bizim numaramizi bloklardi.

    TARAF (S4): unvan/VKN/vergi dairesi/adres SNAPSHOT'tir ve ZORUNLUDUR
    (`party_name` NOT NULL); dort opsiyonel FK yalnizca IZDIR ve en fazla BIRI
    dolar. Cari karti silinse/duzeltilse bile faturanin uzerindeki unvan
    DEGISMEZ — K7'nin taraf ayagi budur.

    KAYNAK: dort opsiyonel FK (hakedis · taseron hakedisi · makine kira
    hakedisi · siparis) ve yine en fazla BIRI dolar. Hepsi RESTRICT'tir:
    faturasi kesilmis bir kaynak kaydi silinemez, yoksa faturanin dayanagi
    kaybolurdu.

    GORUNURLUK: `project_id` (CASCADE) IDOR suzgecinin kolonudur
    (`purchase_requests` emsali). NULLABLE'dir: sirket geneli faturanin projesi
    yoktur ve yalniz modul izniyle gorunur (§6). `site_id` yalnizca BILGI
    alanidir (FGI:106) → SET NULL: santiye kapansa bile fatura ayakta kalir.

    PARA kolonlarinin hepsi NOT NULL'dir: sunucu her yazmada hesaplar. NULL bir
    toplam "bilinmiyor" ile "sifir"i ayni yere dusururdu (NULL-ESIK kanonu) ve
    SUM onlari sessizce yutardi.
    """

    __tablename__ = "invoices"
    __table_args__ = (
        # Yon ICINDE tekil (bkz. sinif docstring'i).
        UniqueConstraint("direction", "invoice_no", name="uq_invoices_no_direction"),
        CheckConstraint(
            _dolu_sayisi("employer_id", "customer_id", "supplier_id", "subcontractor_id"),
            name="ck_invoices_single_party",
        ),
        CheckConstraint(
            _dolu_sayisi(
                "progress_payment_id",
                "subcontractor_progress_payment_id",
                "equipment_rental_invoice_id",
                "purchase_order_id",
            ),
            name="ck_invoices_single_source",
        ),
        # DB SON SAVUNMADIR: servis 422 vermeyi unutsa bile negatif bir tutar
        # mali tabloya giremez.
        CheckConstraint(
            "subtotal >= 0 AND advance_amount >= 0 AND retention_amount >= 0 AND "
            "vat_amount >= 0 AND withholding_amount >= 0 AND total >= 0",
            name="ck_invoices_amounts_non_negative",
        ),
        CheckConstraint(_ORAN_CHECK, name="ck_invoices_rates_percentage"),
        # 🔴 MU-3D — KAYNAK BAŞINA TEK ASIL FATURA. Gerekçe ve neden
        # `UniqueConstraint` DEĞİL: `SOURCE_UNIQUE_INDEXES` sabitinin yanında.
        # Demetten ÜRETİLİR: elle dört kez yazılsaydı beşinci bir kaynak kolonu
        # eklendiğinde biri unutulur ve açık YALNIZ o kolonda kalırdı.
        *(
            Index(_ad, _kolon, unique=True, postgresql_where=text(BINDING_SOURCE_WHERE))
            for _kolon, _ad in SOURCE_UNIQUE_INDEXES
        ),
        # FK'ler otomatik indeks URETMEZ; liste suzgecleri bu sutunlardan gecer.
        Index("ix_invoices_issue_date", "issue_date"),
        Index("ix_invoices_project_id", "project_id"),
        Index("ix_invoices_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    direction: Mapped[InvoiceDirection] = mapped_column(
        Enum(InvoiceDirection, name="invoice_direction"), nullable=False
    )
    # 30 hane: `FIL2026000184` 13 karakter; saticinin serisi daha uzun olabilir
    # ve dolgu asilsa (1.000.000+) yine sigar.
    invoice_no: Mapped[str] = mapped_column(String(30), nullable=False)
    document_type: Mapped[InvoiceDocumentType] = mapped_column(
        Enum(InvoiceDocumentType, name="invoice_document_type"), nullable=False
    )
    status: Mapped[InvoiceStatus] = mapped_column(
        Enum(InvoiceStatus, name="invoice_status"), nullable=False
    )
    issue_date: Mapped[date] = mapped_column(Date, nullable=False)
    # FGI:68 — "kalan gun" TURETILIR, saklanmaz.
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    payment_method: Mapped[InvoicePaymentMethod | None] = mapped_column(
        Enum(InvoicePaymentMethod, name="invoice_payment_method"), nullable=True
    )
    # FK:153. Tavan SEMA katmanindadir (bkz. modul docstring'i).
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Taraf snapshot'i (K7) ---
    party_name: Mapped[str] = mapped_column(String(200), nullable=False)
    # TCKN 11 / VKN 10 — `customers.national_id`/`tax_number` emsali.
    party_tax_number: Mapped[str | None] = mapped_column(String(11), nullable=True)
    party_tax_office: Mapped[str | None] = mapped_column(String(100), nullable=True)
    party_address: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Taraf izi: en fazla BIRI dolu (ck_invoices_single_party) ---
    employer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employers.id", ondelete="RESTRICT"), nullable=True
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="RESTRICT"), nullable=True
    )
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=True
    )
    subcontractor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subcontractors.id", ondelete="RESTRICT"), nullable=True
    )

    # --- Kaynak izi: en fazla BIRI dolu (ck_invoices_single_source) ---
    progress_payment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("progress_payments.id", ondelete="RESTRICT"), nullable=True
    )
    subcontractor_progress_payment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("subcontractor_progress_payments.id", ondelete="RESTRICT"),
        nullable=True,
    )
    equipment_rental_invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("equipment_rental_invoices.id", ondelete="RESTRICT"),
        nullable=True,
    )
    purchase_order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_orders.id", ondelete="RESTRICT"), nullable=True
    )

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sites.id", ondelete="SET NULL"), nullable=True
    )

    # --- Para (§5 sirasiyla; TEK KAYNAK `amounts.py`) ---
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    advance_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    advance_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=0, server_default=text("0")
    )
    retention_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    retention_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=0, server_default=text("0")
    )
    tax_base: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    vat_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    withholding_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    withholding_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=0, server_default=text("0")
    )
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)

    # RESTRICT (repo deseni): faturayi kesen kullanici, kaydi sahipsiz
    # birakacak sekilde silinemez (FGI:198 "Olusturan").
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class InvoiceLine(Base):
    """Faturanin kalem satiri (FGI:116-130 · FGE:150-160 · FK:168-183).

    🔴 `vat_rate` SATIR BAZINDADIR (FGI:121). Mockup tfoot'u tek `%20` cizse de
    tablo oranı satirda tasir; baslikta tek oran varsayilsaydi karma oranli
    fatura sessizce yanlis KDV uretirdi. Kesintiler baslik duzeyinde kaldigi
    icin K3 dagitimi (`amounts.py`) burayi girdi olarak okur.

    `line_total` TUREV OLDUGU HALDE SAKLANIR (K7): `quantity × unit_price`
    satir bazinda yuvarlanir ve donar. FK:183 zaten "salt okunur hesaplanan"
    cizer — istemci GONDEREMEZ (T3'te 422).

    `sort_order` (FGI:116 `Sira`): degeri govdedeki kalem dizisinin INDEKSIDIR.
    Sunucu varsayilani YOKTUR (NOT NULL, `server_default` yok): her yazma yolu
    degeri acikca doldurmak zorundadir — varsayilan 0 olsaydi eksik doldurulan
    bir yol tum satirlari ayni sirada birakip keyfi dizerdi (SA/T3 dersi).

    POZ AYRI ALAN DEGILDIR (S2): FK:178 poz numarasini aciklamaya gomuyor
    (`… (Poz 03.001)`). Ayri bir `boq_item_id` acilsaydi mockup'in yazdigi
    serbest ifadeler kaybolur ve olmayan bir katalog bagi vaat edilirdi.

    `unit` SERBEST METINDIR (S3): FK:169 bir input'tur; FGI `m³`/`Ton`/`m²`,
    FGE `Saat` gosterir — kapali kume ICAT EDILMEZ.

    `detail_note` kaynaktan kopyalanan serbest metin SNAPSHOT'idir (FGI:127
    "Poz 03.001 · Fiyat farki katsayisi: 1,142" · FGE:159 "Temmuz 2026 ·
    Guneskent A-Blok") — canli hakedis/kira kaydindan OKUNMAZ.

    Zaman damgasi TASIMAZ: satirin omru basliga baglidir (CASCADE) ve uc kalem
    tablosunun hicbiri satir bazinda tarih GOSTERMEZ.
    """

    __tablename__ = "invoice_lines"
    __table_args__ = (
        # Sifir/negatif miktarli bir fatura kalemi hicbir durumda anlamli
        # degildir ve toplami sessizce bozardi.
        CheckConstraint("quantity > 0", name="ck_invoice_lines_quantity_positive"),
        # Fiyat 0 olabilir (bedelsiz kalem), negatif olamaz — iskonto sutunu
        # YOKTUR ve negatif fiyat onun yerine gecirilemez.
        CheckConstraint("unit_price >= 0", name="ck_invoice_lines_unit_price_non_negative"),
        CheckConstraint("vat_rate BETWEEN 0 AND 100", name="ck_invoice_lines_vat_rate_percentage"),
        Index("ix_invoice_lines_invoice_id", "invoice_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    # Tavan SEMA katmanindadir (bkz. modul docstring'i).
    description: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Miktar olcegi repo standardi Numeric(14, 3) — boq/sozlesme/hakedis/ST/SA
    # ile ayni.
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    detail_note: Mapped[str | None] = mapped_column(String(200), nullable=True)
