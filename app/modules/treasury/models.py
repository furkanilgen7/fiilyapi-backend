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

ACILMAYANLAR (spec §1, kasitli — "eksik" diye geri acilmaz): cek/senet VARLIGI
(E10'un tamami; durum gecisleri ve `Karsiliksiz` hic cizilmemis → HZ-2) · nakit
hareket/islem tablosu (HZ-3) · planlanan odeme · bakiye bilesenleri
(kullanilabilir/bloke) · para birimi/kur (`₺` metne gomulu sabit) · sube /
hesap no / SWIFT / kart rengi.

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

    ⚠️ `cheque` / `promissory_note` yalnizca ODEME SEKLININ ETIKETIDIR: cek ya
    da senet KAYDI ACMAZ (cek varligi HZ-2'nin isi, `cheque_id` kolonu bu
    yuzden yoktur).

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
