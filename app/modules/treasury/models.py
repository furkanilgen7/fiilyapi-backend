"""Hazine cekirdegi — banka/kasa hesabi + tahsilat/odeme kaydi (HZ-1 spec §2).

IKI TABLO:
  * `bank_accounts` — banka veya kasa hesabi (E9:70-84 kartlari)
  * `payments`      — bir faturaya kaydedilen tahsilat/odeme (FGI:220-247 formu)

Modul adi `treasury`dir cunku IZIN anahtari da odur: seed'de "Hazine"
(ModuleGroup.MALI) ZATEN VARDIR (`roles/seed_data.py:103`) — yeni izin modulu
ACILMAZ, izin migration'i YOKTUR (spec §4).

🔴 K2 — BAKIYE SAKLANMAZ, TURETILIR. Saklanan tek para alani
`opening_balance`tir; guncel bakiye `balance.py`nin (T2) TEK KAYNAGINDAN
hesaplanir:

    bakiye = opening_balance
           + Σ payments.amount  (bagli fatura direction = outgoing → tahsilat)
           − Σ payments.amount  (bagli fatura direction = incoming  → odeme)

Saklanan bir bakiye KACINILMAZ OLARAK KAYAR (iki eszamanli yazma, yarim
rollback, elle duzeltme) ve kaydigini kimse fark etmez. Hareket tablosu (HZ-3)
geldiginde ayni formule bir TERIM eklenir, kolon gocu gerekmez.
`inventory/balance.py` bu deseni zaten tasir — emsal odur.

🔴 K3 — HESAP SIRKET GENELIDIR: proje/santiye FK'si YOKTUR. E9'da hicbir alan
santiye gostermez, cek tablosunda proje sutunu yoktur. `suppliers` /
`stock_items` / `customers` emsali; erisim `treasury` izin moduluyle
denetlenir, IDOR unutulmus DEGILDIR.

🔴 K4 — TAHSILAT VE ODEME TEK TABLODUR. FGI'daki form gelen faturanin odemesi
icin de aynidir; YON bagli faturanin `direction`'indan gelir ve ayri bir kolon
ACILMAZ — iki gercek kaynak olsaydi biri digerinden sapabilirdi.

🔴 K5 — KISMI TAHSILAT SATIRDIR: `invoices` uzerinde `paid_amount` kolonu
ACILMAZ. Odenen = Σ payments, kalan = `invoice.total − Σ payments`; faturanin
durumu bundan TURETILEREK damgalanir. Politika degisirse cozum bir yeniden
hesaptir, veri gocu degil.

ACILMAYANLAR (spec §1, kasitli — "eksik" diye geri acilmaz): nakit
hareket/islem tablosu (HZ-3) · planlanan odeme · bakiye bilesenleri
(kullanilabilir/bloke) · para birimi/kur (`₺` metne gomulu sabit) · sube /
hesap no / SWIFT / kart rengi.

🔴 **FIN-1 (2026-08-18) BU LISTEYI KISALTTI:** cek/senet VARLIGI artik ACIK —
`financial_instruments` tablosu (E10'un tamami) bu dosyanin altinda tanimlidir.
HZ-1 spec'i onu "HZ-2" adiyla ertelemisti; is FIN-1 adiyla yapildi ve iki ad
AYNI isi gosterir. Bu dosyadaki her "HZ-2" atfi FIN-1 olarak okunur.

Serbest metin tavani: `note` kolonu `Text`tir (DB'de sinirsiz); 2000 karakter
tavani TB4/B4 standardi geregi SEMA katmanindadir
(`app.core.text.FREE_TEXT_MAX_LENGTH`).

Bu modul BASKA BIR MODULU IMPORT ETMEZ: FK hedefleri string tablo adiyla
verilir (P10'un `cost_cards` import cemberi tekrarlanmaz).
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
    Index,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class BankAccountType(str, enum.Enum):
    """Hesap tipi — E9:71,81 `Vadesiz` ve `Kasa`.

    🔴 K1: mockup YALNIZ bu ikisini ciziyor. `Vadeli` / `Kredi` / `POS` /
    `Doviz` ICAT EDILMEZ — acilsaydi hicbir ekranda karsiligi olmayan bir kume
    kalici olarak DB'ye yazilir, sonra da enum TAKASIYLA geri alinirdi.
    """

    checking = "checking"  # Vadesiz
    cash = "cash"  # Kasa


class PaymentMethodKind(str, enum.Enum):
    """Odeme sekli — FGI:225-228 KAPALI kumesi BIREBIR.

    ⚠️ `cheque` / `promissory_note` yalnizca ODEME SEKLININ ETIKETIDIR ve
    OYLE KALIR: bu alan tek basina bir cek KAYDI ACMAZ.

    🔴 **FIN-1 (2026-08-18) ILE DEGISEN KISIM:** artik cek/senet VARLIGI vardir
    (`FinancialInstrument`) ve `payments.financial_instrument_id` ile bu tabloya
    ISTEGE BAGLI bir bag kurulabilir. HZ-1'in "`cheque_id` kolonu bu yuzden
    yoktur" cumlesi ARTIK GECERSIZDIR — ama bagin **ZORUNLU OLMAMASI** bilincli
    bir karardir (FIN-1 K4): bugunku `method='cheque'` kayitlarinin hepsi bossa
    ve migration onlari dolduramiyorsa, zorunluluk MEVCUT VERIYI gecersiz
    kilardi. Yani etiket ile varlik AYRI iki olgudur ve biri otekini ima ETMEZ.

    `invoicing.InvoicePaymentMethod` ile AYRI bir tiptir ve oyle kalir: fatura
    tarafi `credit_card` tasir ama `promissory_note` tasimaz — kumeler
    birebir ayni degildir ve tek tipte birlestirmek ikisinden birine olmayan
    bir deger vaat ederdi.
    """

    transfer = "transfer"  # Banka Havalesi / EFT
    cheque = "cheque"  # Cek
    promissory_note = "promissory_note"  # Senet
    cash = "cash"  # Nakit


class BankAccount(Base):
    """Banka veya kasa hesabi (E9:70-84 kart verisi).

    `iban` NULLABLE'dir cunku Kasa satirinda IBAN YOKTUR (E9:83); tekillik bu
    yuzden KISMI indeksle kurulur — NULL'lar coklanabilir, dolu IBAN'lar
    tekildir (`customers.national_id` emsali). Kismi olmasaydi IKINCI kasa
    hesabi hic acilamazdi.

    `display_name` Kasa'da IBAN'in yerine basilan addir (E9:83 `Merkez Kasa`) ve
    `ck_bank_accounts_cash_has_name` onu Kasa tipinde ZORUNLU kilar: bos
    kalsaydi kart tamamen isimsiz gorunurdu. Vadesiz hesapta opsiyoneldir,
    orada banka adi zaten basilir.

    `opening_balance` SAKLANAN TEK para alanidir (K2) ve elle duzeltilebilir
    (uc 4): degisince bakiye kendiliginden yeniden turetilir.

    DELETE ucu vardir ama yalniz `admin` icindir ve odemesi olan hesap 409
    doner (FK RESTRICT'in servis karsiligi); normal kullanimdan kaldirma
    `is_active=false`tir (repo kanonu).
    """

    __tablename__ = "bank_accounts"
    __table_args__ = (
        Index(
            "uq_bank_accounts_iban",
            "iban",
            unique=True,
            postgresql_where=text("iban IS NOT NULL"),
        ),
        # DB SON SAVUNMADIR: servis 422 vermeyi unutsa bile isimsiz bir kasa
        # kaydi giremez.
        CheckConstraint(
            "account_type <> 'cash' OR display_name IS NOT NULL",
            name="ck_bank_accounts_cash_has_name",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # E9:71,76,81 `Ziraat Bank` · `Is Bank` · `Yapi Kredi`.
    bank_name: Mapped[str] = mapped_column(String(100), nullable=False)
    account_type: Mapped[BankAccountType] = mapped_column(
        Enum(BankAccountType, name="bank_account_type"), nullable=False
    )
    # IBAN azami 34 karakterdir (ISO 13616); TR'de 26.
    iban: Mapped[str | None] = mapped_column(String(34), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    opening_balance: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=0, server_default=text("0")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Payment(Base):
    """Bir faturaya kaydedilen tahsilat/odeme satiri (FGI:220-247).

    UC FK'nin UCU DE RESTRICT'tir: odemesi olan fatura, hesap ya da onu giren
    kullanici SILINEMEZ. CASCADE olsaydi bir kaydin silinmesi tahsilat
    gecmisini sessizce yok eder ve turetilmis bakiye (K2) kendiliginden
    kayardi — kaydigini da kimse fark etmezdi.

    `amount` icin `> 0` CHECK'i: sifir hicbir sey ifade etmez, negatif ise
    gizli bir IADE olurdu (iade/avans kavrami hicbir mockup'ta MODELLENMEMIS).
    Asiri tahsilat denetimi (K6, `Σ + yeni > total` → 422) DB'de degil
    servistedir ve KILITLIDIR (K7) — bir CHECK baska satirlarin toplamini
    goremez.

    `paid_on` INDEKSLIDIR: nakit akisi ucu (10) ay penceresini buradan suzer.
    FK'ler otomatik indeks URETMEZ, bu yuzden `invoice_id` (uc 6 + K5 toplami)
    ve `bank_account_id` (K2 bakiye turetimi) de acikca indekslenir.

    ZAMAN DAMGASI ILE `paid_on` AYRI SEYLERDIR: ilki kaydin girildigi an,
    ikincisi paranin gectigi gun — kullanici geriye donuk tarih girebilir.
    """

    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_payments_amount_positive"),
        Index("ix_payments_invoice_id", "invoice_id"),
        Index("ix_payments_bank_account_id", "bank_account_id"),
        Index("ix_payments_paid_on", "paid_on"),
        # FIN-1 K4 — FK'ler otomatik indeks URETMEZ ve `payments` buyur.
        Index("ix_payments_financial_instrument_id", "financial_instrument_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoices.id", ondelete="RESTRICT"), nullable=False
    )
    bank_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bank_accounts.id", ondelete="RESTRICT"), nullable=False
    )
    method: Mapped[PaymentMethodKind] = mapped_column(
        Enum(PaymentMethodKind, name="payment_method_kind"), nullable=False
    )
    # 🔴 FIN-1 K4 — ISTEGE BAGLI cek/senet bagi. UC KARAR birlikte alindi:
    #
    # (a) **nullable**: `method='cheque'` iken doluluk ZORUNLU KILINMAZ. Bugunku
    #     kayitlarin hepsi bostur ve migration onlari dolduramaz; zorunluluk
    #     MEVCUT VERIYI gecersizlestirirdi. Yani etiket (`method`) ile varlik
    #     (`financial_instrument_id`) ayri iki olgudur, biri otekini IMA ETMEZ.
    # (b) **SET NULL**: odeme kaydi cekten BAGIMSIZ bir olgudur — cek silinse de
    #     odeme ayakta kalir. RESTRICT olsaydi bir cekin silinmesi odeme gecmisine
    #     takilir, CASCADE olsaydi cekin silinmesi PARA KAYDINI yok ederdi
    #     (bu tablonun oteki uc FK'si RESTRICT'tir cunku ONLAR kaydin sahibidir).
    # (c) **indeksli** (yukarida): bir cekin odemelerini bulmak tam tarama olmaz.
    financial_instrument_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("financial_instruments.id", ondelete="SET NULL"),
        nullable=True,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    paid_on: Mapped[date] = mapped_column(Date, nullable=False)
    # Tavan SEMA katmanindadir (bkz. modul docstring'i).
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# --------------------------------------------------------------------------- #
# FIN-1 — cek & senet portfoyu (E10 "Cek & Odeme" ekraninin tamami)
# --------------------------------------------------------------------------- #


class FinancialInstrumentKind(str, enum.Enum):
    """Kiymetli evrak turu — E10:94-96 sekmeleri.

    🔴 **K1: CEK VE SENET AYRI TABLO ACMAZ.** Alan kumesi %95 ortaktir; ayirmak
    iki kopya dogrulayici, iki kopya KPI ve iki kopya durum makinesi demektir —
    ve biri otekinden sessizce sapardi. Tur bu yuzden bir KOLONDUR.

    Kume `PaymentMethodKind`in ODEME SEKLI kumesiyle etiket duzeyinde kesisir
    ama AYRI BIR TIPTIR: odeme sekli ayrica `transfer`/`cash` tasir ve tek tipte
    birlestirilseydi portfoye "Nakit cek" gibi anlamsiz bir uye vaat edilirdi.
    """

    cheque = "cheque"  # Cek
    promissory_note = "promissory_note"  # Senet (E10:96 "Senetler" sekmesi)


class FinancialInstrumentDirection(str, enum.Enum):
    """Yon — E10:94-95 `Alinan Cekler` / `Verilen Cekler` sekmeleri.

    Yon KOLONDUR ve turetilmez: `payments`ta yon bagli faturanin
    `direction`'indan gelir (K4) cunku odemenin bir sahibi vardir; cek ise
    KENDI BASINA durur — hicbir faturaya bagli olmayan bir cek de portfoydedir.
    """

    received = "received"  # Alinan (elimizde)
    issued = "issued"  # Verilen (karsiligini biz odeyecegiz)


class FinancialInstrumentStatus(str, enum.Enum):
    """Durum — gorev emri K2 birebir.

    🔴 **"VADEDE" BURADA YOKTUR VE OLMAYACAK.** E10:121,148'in turuncu rozeti bir
    enum uyesi DEGIL TUREVDIR (`status = portfolio` **ve** vade penceresi icinde).
    Enum'a konsaydi her gun bir cron'un satirlari guncellemesi gerekirdi ve
    **zamanla degisen bir olguyu kalici kolona yazmak BAYATLAR** — ertesi gun
    yanlis rozet basar, kimse fark etmez. Turev `instruments/derive.py`dedir ve
    yanitta `is_due` olarak AYRI bir alandir.

    Gecis kurallari `instruments/transitions.py`de TEK TABLODADIR; burada
    `if status == ...` YAZILMAZ.
    """

    portfolio = "portfolio"  # Portfoyde (E10:130,139)
    collected = "collected"  # Tahsil Edildi (E10:157)
    paid = "paid"  # Odendi — verilen cekin karsiligi cikti
    returned = "returned"  # Iade / karsiliksiz (E10:86 karti)
    cancelled = "cancelled"  # Iptal (E10:86 karti)


class FinancialInstrument(Base):
    """Cek ya da senet — TEK tablo (K1), E10 tablosunun satiri.

    ## Neden bu tablo acildi

    HZ-1'de `payments.method` "cekle odedim" diyebiliyordu ama **hangi cek**
    oldugu kayit altinda degildi: portfoy, vade takibi, tahsilat durumu yoktu.
    Bu tablo o varligi acar; `payments.financial_instrument_id` ise ISTEGE BAGLI
    bir bagdir (K4).

    ## Neyin BURADA OLMADIGI da bir karardir

    * **`serial_no` TEKIL DEGILDIR (K3).** Farkli bankalarin cek numaralari
      cakisir; ayni numara alinan ve verilen tarafta ayri ayri bulunabilir.
      UNIQUE konsaydi mesru bir kayit hic girilemezdi. Mukerrer UYARISI bir
      urun karari olabilir, veri kisiti DEGILDIR.
    * **Muhasebe fisi YOKTUR (K5).** Cek tahsil edilince yevmiye fisi atmak
      ayri bir dilimin isidir; portfoy bir ENVANTERDIR ve deftere baglanmasi
      ayri bir karar zinciri gerektirir.
    * **Turev kolon YOKTUR:** `is_due`, KPI toplamlari, kalan gun — hepsi
      sorgudan turer (`bank_accounts.balance` kanonunun aynisi).

    ## FK'ler NEDEN `SET NULL`

    Proje ve banka hesabi birer **BILGI BAGIDIR**, varligin parcasi degil:
    projesi silinen bir cek hala elimizdedir ve tahsil edilebilir. CASCADE
    olsaydi bir projenin silinmesi PORTFOYDEN para eksiltirdi. (BOQ-SEC-B'nin
    varlik-parcasi → CASCADE ayriminin obur tarafi.)

    Bu modul BASKA BIR MODULU IMPORT ETMEZ: FK hedefleri string tablo adiyla
    verilir.
    """

    __tablename__ = "financial_instruments"
    __table_args__ = (
        # DB SON SAVUNMADIR: servis 422 vermeyi unutsa bile sifir/negatif tutarli
        # bir kiymetli evrak giremez.
        CheckConstraint("amount > 0", name="ck_financial_instruments_amount_positive"),
        # 🔴 Vade kesideden ONCE olamaz. Sessizce kabul edilseydi vade raporu ve
        # "Bu Ay Vadeli" karti bozulurdu. Ayni gun MESRUDUR (goruldugunde odenen).
        CheckConstraint("due_date >= issue_date", name="ck_financial_instruments_due_after_issue"),
        # E10:94-95 sekmeleri + durum suzgeci ayni sorgudan gecer.
        Index("ix_financial_instruments_direction_status", "direction", "status"),
        # Vade penceresi (`is_due`, `due_this_month`) ve `due_before/after`.
        Index("ix_financial_instruments_due_date", "due_date"),
        # E10:96 "Senetler" sekmesi.
        Index("ix_financial_instruments_instrument_kind", "instrument_kind"),
        # 🔴 Emrin listesinde YOKTU, EKLENDI: kapsam suzgeci
        # (`project_id IS NULL OR project_id IN (...)`, `invoicing.scope_clause`
        # emsali) HER liste ve HER sayim sorgusunda kosar; FK otomatik indeks
        # uretmez.
        Index("ix_financial_instruments_project_id", "project_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    instrument_kind: Mapped[FinancialInstrumentKind] = mapped_column(
        Enum(FinancialInstrumentKind, name="financial_instrument_kind"), nullable=False
    )
    direction: Mapped[FinancialInstrumentDirection] = mapped_column(
        Enum(FinancialInstrumentDirection, name="financial_instrument_direction"), nullable=False
    )
    # E10:104 "Cek No" — E10:115 `0123456789`. TEKIL DEGIL (K3).
    serial_no: Mapped[str] = mapped_column(String(50), nullable=False)
    # E10:105 "Kesideci" — E10:116 `Guneskent A.S.`. Satirin kimligidir.
    drawer_name: Mapped[str] = mapped_column(String(200), nullable=False)
    # E10:116 kesidecinin ALTINDAKI gri satir (`Proje is avansi`).
    description: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # E10:106 "Banka" — senette banka OLMAYABILIR, bu yuzden nullable.
    bank_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # E10:107 "Keside Tarihi" · E10:108 "Vade".
    issue_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    # E10:109 "Tutar" — para `Numeric`, asla `float`.
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    status: Mapped[FinancialInstrumentStatus] = mapped_column(
        Enum(FinancialInstrumentStatus, name="financial_instrument_status"),
        nullable=False,
        default=FinancialInstrumentStatus.portfolio,
        server_default=text("'portfolio'"),
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    bank_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bank_accounts.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
