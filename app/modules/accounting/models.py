"""Muhasebe cekirdegi — hesap plani + yevmiye fisi/satiri (MU-1 spec §3).

UC TABLO:
  * `chart_of_accounts` — tekduzen hesap plani katalogu (HP:58-62 tablosu)
  * `journal_entries`   — yevmiye fisi BASLIGI (E8 defterinin arkasindaki kayit)
  * `journal_lines`     — fisin bacaklari (E8:101-106 tablosu SATIR bazlidir)

Modul adi `accounting`tir cunku IZIN anahtari da odur: seed'de "Muhasebe"
ZATEN VARDIR (`roles/seed_data.py:99`) — yeni izin modulu ACILMAZ, izin
migration'i YOKTUR (spec §2/K8).

🔴 K1 — DENGE KORUNUR: IKI KATMAN, hicbiri tek basina yetmez
--------------------------------------------------------------------------
Katman 1 (servis, `validation.py`, yazimdan ONCE, 422): `Σ debit = Σ credit`,
en az iki satir, yalnizca yaprak hesap.
Katman 2 (BURASI, DB = SON savunma): servis 422 vermeyi unutsa bile bozuk bir
mali kayit tabloya GIREMEZ.

  * `journal_lines.debit`/`credit` **NOT NULL** — NULL tutar satira hic giremez.
  * `ck_journal_lines_amounts_non_negative` — negatif tutar `Σ`yi sessizce
    dengeleyemez (bir borc satirina `-100` yazip sahte denge kurmak imkansiz).
  * `ck_journal_lines_single_side` — `(0,0)` ve cift-dolu satir reddedilir;
    E8'in her satiri TEK TARAFLIDIR (bos taraf hep `—`, E8:114 vd.).
  * `ck_journal_entries_posted_balanced` — DENGESIZ fis `posted` OLAMAZ; taslak
    dengesiz BIRAKILABILIR (kayitlastirma aninda kapi yeniden kosar).
  * `journal_entries.total_debit`/`total_credit` **NOT NULL** — nullable
    olsalardi `NULL = NULL` **NULL** uretir ve CHECK'i **GECERDI**; denge kisiti
    sessizce devre disi kalirdi.

NULL fail-closed'un tam senaryosu: `debit=NULL, credit=NULL` olan bir satir
`SUM` tarafindan YUTULUR, iki toplam da degismez ve **dengesiz fis dengede
sayilir**. Uc mekanizmanin ucu birden bu deligi kapatir.

Toplamlar TUREV OLDUKLARI HALDE BASLIKTA SAKLANIR (FAT-1 `invoices` para
kolonlarinin bilincli istisnasinin ayni gerekcesi): bir CHECK **baska
satirlarin toplamini GOREMEZ** (`treasury/models.py` asiri-tahsilat notu). K1
"DB duzeyinde korunur" diyorsa toplam bir KOLON olmak zorundadir. Sapma
penceresi kapalidir: satirlar YALNIZ `draft`ta ve YALNIZ tek yoldan
(`_apply_totals`) yazilir, CHECK de zaten yalniz `posted`ta isirir.
TRIGGER YOKTUR (repo hicbir yerde kullanmiyor) — "posted fisin satiri UPDATE
edilemez" iddiasi SERVIS katmanindadir.

🔴 K3 — BAKIYE SAKLANMAZ, TURETILIR (`accounting/balance.py` TEK KAYNAK,
`treasury/balance.py` deseni). HP:61 `Bakiye (₺)` bir kolon DEGILDIR:

    net(hesap) = COALESCE(Σ journal_lines.debit − Σ journal_lines.credit, 0)
                 WHERE journal_entries.status IN ('posted', 'reversed')
    bakiye     = SIGN[account_type] * net    # aktif/gider +1, pasif/gelir −1

`reversed` fisler de sayilir: kayitlastirilmis fis defterden CIKMAZ, yalniz
ters kaydiyla notrlenir. Saklanan bir bakiye kacinilmaz olarak KAYAR ve
kaydigini hicbir kolon farki ele vermezdi.

🔴 K4 — HIYERARSI `parent_id` FK'SIYLE DEGIL, KODUN ICINDE tasinir. `120.01`in
ebeveyni `120`, `120`inki `12`dir; `12`ninki YOKTUR (sinif bir KAYIT DEGILDIR —
HP:69/135/161/187 bantlarinda kod sutunu yoktur). `parent_id` acilsaydi
turetilebilir bir sey saklanir ve kod duzeltildiginde FK bayatlardi.

🔴 R3 — `account_type` ILE `is_active` KARISTIRILMAZ. Ikisi de Turkce'de
"aktif" der ama AYRI SEYLERDIR:
  * `account_type` = HP:60 **Tur** sutunu (Aktif/Pasif/Gelir/Gider rozeti),
  * `is_active`    = HP:62 **Durum** sutunu (satir basina tek yesil nokta,
    METIN YOKTUR).

🔴 KAPSAM (IDOR) — UC TABLODA DA `project_id`/`site_id` YOKTUR. HP'nin bes,
E8'in alti sutununda hicbir proje/santiye alani yoktur; E8:113'teki
`– Guneskent` SERBEST METNIN icindedir. Hesap plani sirket geneli bir
katalogtur (`suppliers`/`stock_items`/`bank_accounts` sinifi) ve erisim
tamamen `accounting` izniyle denetlenir. IDOR unutulmus DEGIL, YAPISAL OLARAK
YOKTUR; maliyet merkezi/proje kirilimi MU-3'un isidir.

ACILMAYANLAR (spec §9, kasitli — "eksik" diye geri acilmaz): mizan · KDV
beyani · banka mutabakati · e-Fatura · mali tablolar (hepsi MU-2+) · donem
kapanisi / `accounting_periods` (yapi hazir: `period_year/month` + indeks) ·
fatura/hazine/bordro → otomatik fis (MU-3) · `entry_no` + `numbering.py`
(hicbir mockup sutununda fis numarasi yok; kimlik `id`dir) · `parent_id` FK ·
sinif KAYDI · `is_contra` kolonu (`257`in parantezi bir SUNUM kuralidir,
adin `(-)` son ekinden gelir; hicbir form onay kutusu cizmemis) · Excel/disa
aktarim · para birimi/kur (`₺` metne gomulu sabit) · fise belge eki · toplu
ice aktarim / tekduzen hesap plani seed'i · `draft` icin onay akisi.

Serbest metin tavani: `description` kolonu `Text`tir (DB'de sinirsiz); 2000
karakter tavani TB4/B4 standardi geregi SEMA katmanindadir
(`app.core.text.FREE_TEXT_MAX_LENGTH`) — migration gerektirmez.

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

#: K4 kod dilbilgisi — HP'den CIKARILAN, icat edilmeyen kume:
#: grup `NN` (HP:72,97,115) · ana hesap `NNN` (HP:76-204) · alt hesap `NNN.NN`
#: (E8:112,120,128,136,144,152). Ilk hane `0` OLAMAZ (sinifsiz hesap yoktur).
#: 🔴 `NNN.NN.NNN` (ucuncu kirilim) hicbir mockup'ta YOKTUR → yapisal olarak
#: REDDEDILIR; acilsaydi mizanin (MU-2) hic gormedigi bir duzey dogardi.
ACCOUNT_CODE_CHECK = r"code ~ '^[1-9][0-9]$' OR code ~ '^[1-9][0-9]{2}(\.[0-9]{2})?$'"

#: K9'un drift-proof hali: donem kolonlari VARDIR (MU-2 EŞİK=KİLİT'i
#: `(period_year, period_month)` uzerinden kilitleyecek) ama KAYAMAZ.
#: `EXTRACT` bir `date` kolonu uzerinde IMMUTABLE'dir, CHECK'te yasaldir.
#: 🔴 K6 acisindan temiz: `entry_date` bir `date`tir, `timestamptz` DEGIL —
#: AST bekcisinin 3. kalibi tetiklenmez.
PERIOD_MATCHES_DATE_CHECK = (
    "period_year = EXTRACT(YEAR FROM entry_date)::int AND "
    "period_month = EXTRACT(MONTH FROM entry_date)::int"
)


class ChartAccountType(str, enum.Enum):
    """Hesap turu — HP:60 `Tur` sutununun KAPALI kumesi birebir.

    Dort rozet cizilidir: `Aktif` (HP:78) · `Pasif` (HP:154) · `Gelir` (HP:192)
    · `Gider` (HP:199). **Besinci uye ICAT EDILMEZ** — ozkaynak/nazim gibi bir
    tur eklenseydi hicbir ekranda karsiligi olmayan bir kumeyi kalici olarak
    DB'ye yazardik.

    🔴 Bu enum HP:62 `Durum` sutunu DEGILDIR (bkz. modul docstring'i R3):
    Durum `is_active` boolean'idir, Tur budur.

    K3 isaret kurali bu turden okunur: `asset`/`expense` → `+1`,
    `liability`/`revenue` → `−1` (`balance.py` TEK KAYNAK).
    """

    asset = "asset"  # Aktif
    liability = "liability"  # Pasif
    revenue = "revenue"  # Gelir
    expense = "expense"  # Gider


class JournalEntryStatus(str, enum.Enum):
    """Fis durumu — K2 durum makinesi (`transitions.py` matris TEK kopya).

        draft ──post──▶ posted ──reverse──▶ reversed

    Ters kayit YENI BIR FIS uretir (alan ya da bayrak degil): orijinal
    `reversed` damgalanir, storno dogrudan `posted` dogar ve
    `reversal_of_id` ile orijinali gosterir. `reversed` TERMINALDIR —
    stornonun stornosu sonsuz zincir acardi, mali anlami yoktur.

    🔴 `reversed` fis BAKIYEDEN DUSMEZ (`POSTING_STATUSES` = posted + reversed):
    yalniz `posted` sayilsaydi orijinal defterden duser, storno ters bacaklariyla
    eklenir ve net **−orijinal** cikardi (cift ters kayit). Ikisi de sayilinca
    net TAM SIFIR olur.
    """

    draft = "draft"
    posted = "posted"
    reversed = "reversed"


class ChartAccount(Base):
    """Hesap plani kaydi (HP:58-62 satiri).

    `code` KIMLIKTIR ve hiyerarsiyi TASIR (K4). Tekildir; ayni kod iki kez
    acilsaydi yevmiye satirlari iki karta bolunur ve bakiye (K3) ikiye ayrilirdi.

    GRUP BIR KAYITTIR (HP:72,97,115 `10 Hazir Degerler` gibi) — kodu doludur,
    yalnizca Tur/Bakiye/Durum sutunlari RENDER EDILMEZ. SINIF ise KAYIT DEGILDIR
    (HP:69,135,161,187 bantlarinda kod sutunu yoktur); kodun ilk hanesinden
    turetilir. HP:187 `SINIF 5` yazip altina `600`/`730`/`760` diziyor —
    **K15: satirlar kazanir**, bant etiketi bir sunucu alani DEGILDIR.

    `is_active` (HP:62 `Durum`) bir KALDIRMA bayragidir: fis satiri ya da alt
    hesabi olan bir hesap SILINEMEZ (servis 409), kaldirma yolu bu bayraktir.
    Indekslenmez — iki degerli, secicilik yok.
    """

    __tablename__ = "chart_of_accounts"
    __table_args__ = (
        UniqueConstraint("code", name="uq_chart_of_accounts_code"),
        # Bicim DB'de zorlanir: servis regex'i atlansa bile `1200` ya da
        # `120.01.001` gibi bir kod plani sessizce bozamaz.
        CheckConstraint(ACCOUNT_CODE_CHECK, name="ck_chart_of_accounts_code_format"),
        # HP:60 suzgeci bu sutundan gecer.
        Index("ix_chart_of_accounts_account_type", "account_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # 20 hane: en uzun yasal bicim `NNN.NN` = 6 karakter; pay birakilir.
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    # HP:153 `Birikmis Amortismanlar (-)` — `(-)` ADIN parcasidir (§1c).
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    account_type: Mapped[ChartAccountType] = mapped_column(
        Enum(ChartAccountType, name="chart_account_type"), nullable=False
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


class JournalEntry(Base):
    """Yevmiye fisi basligi.

    🔴 `entry_no` (fis numarasi) YOKTUR: ne HP'de ne E8'de fis numarasi sutunu
    cizilmistir. FAT-1'de vardi cunku FY tablosunda cizilliydi. Kimlik `id`dir,
    `numbering.py` ACILMAZ.

    `description` E8:113'un UST satiridir (islemin ADI, bir NOT degil);
    `detail_note` ALT satiridir ve bir FK DEGILDIR: alti ornekten biri
    (`48 personel · SGK dahil`) hicbir varliga cozulmez — heterojen kume =
    SERBEST METIN (`invoice_lines.detail_note` ile ayni ad/rol/olcu). FK
    acilsaydi MU-3'un (entegrasyon) isi buraya sizardi.

    `period_year`/`period_month` TURETILEBILIR oldugu halde KOLONDUR (K9): MU-2
    donem kilidini bu ciftin uzerinden alacak. `ck_journal_entries_period_
    matches_date` ikisini uzlastirir — kolon vardir ve KAYAMAZ.

    `reversal_of_id` UNIQUE'tir: bir fisin en fazla BIR stornosu olur. PG'de
    cok sayida NULL serbesttir, yani stornosu OLMAYAN fis sayisi sinirsizdir —
    kisit tam olarak istenen seyi soyler.

    `created_by_id` RESTRICT: fisi giren kullanici, mali izi sahipsiz birakacak
    sekilde silinemez (repo deseni).
    """

    __tablename__ = "journal_entries"
    __table_args__ = (
        # Bir fisin en fazla BIR stornosu olur (K2).
        UniqueConstraint("reversal_of_id", name="uq_journal_entries_reversal_of"),
        CheckConstraint(PERIOD_MATCHES_DATE_CHECK, name="ck_journal_entries_period_matches_date"),
        # 🔴 K1'in baslik ayagi: DENGESIZ FIS `posted` OLAMAZ. `draft` dengesiz
        # BIRAKILABILIR — kapi kayitlastirma aninda yeniden kosar.
        CheckConstraint(
            "status <> 'posted' OR total_debit = total_credit",
            name="ck_journal_entries_posted_balanced",
        ),
        CheckConstraint(
            "total_debit >= 0 AND total_credit >= 0",
            name="ck_journal_entries_totals_non_negative",
        ),
        Index("ix_journal_entries_entry_date", "entry_date"),
        # E8:75 ay penceresi ve MU-2 donem kilidi bu ciftten gecer.
        Index("ix_journal_entries_period", "period_year", "period_month"),
        Index("ix_journal_entries_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # E8:101 `Tarih`. `Mapped[date]`tir — `timestamptz` DEGIL (K6).
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    period_year: Mapped[int] = mapped_column(Integer, nullable=False)
    period_month: Mapped[int] = mapped_column(Integer, nullable=False)
    # Tavan SEMA katmanindadir (bkz. modul docstring'i).
    description: Mapped[str] = mapped_column(Text, nullable=False)
    detail_note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[JournalEntryStatus] = mapped_column(
        Enum(JournalEntryStatus, name="journal_entry_status"), nullable=False
    )
    # 🔴 NOT NULL SART: nullable olsalardi `NULL = NULL` NULL uretir ve
    # `ck_journal_entries_posted_balanced` sessizce GECERDI.
    total_debit: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=0, server_default=text("0")
    )
    total_credit: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=0, server_default=text("0")
    )
    # RESTRICT: stornosu olan fis silinemez, yoksa storno dayanaksiz kalirdi.
    reversal_of_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journal_entries.id", ondelete="RESTRICT"), nullable=True
    )
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class JournalLine(Base):
    """Fisin bacagi (E8:101-106 tablosu SATIR bazlidir, fis bazli degil).

    🔴 HER SATIR TEK TARAFLIDIR (`ck_journal_lines_single_side`): E8'in alti
    satirinin bos tarafi HEP `—`dir. Tek bir `amount` + `side` kolonu secilseydi
    `SUM(borc)` bir `CASE` icine gizlenir ve K1'in DB kisiti YAZILAMAZDI.

    `account_id` RESTRICT: fis satiri olan hesap SILINEMEZ. CASCADE olsaydi
    hesabin silinmesi yevmiye satirlarini sessizce yok eder ve turetilmis bakiye
    (K3) **kaydigi fark edilmeden** kayardi.

    `entry_id` CASCADE: satirin omru basliga baglidir.

    `sort_order` govdedeki satir dizisinin INDEKSIDIR; sunucu varsayilani
    YOKTUR (NOT NULL, `server_default` yok) — varsayilan 0 olsaydi eksik
    doldurulan bir yol tum satirlari ayni sirada birakirdi (FAT-1/SA dersi).
    Kosan bakiyenin (E8:106) kanonik siralamasinin ucuncu parcasidir.

    SATIRDA `description` VE ZAMAN DAMGASI ACILMAZ: bir fisin iki bacagi ayni
    islemi anlatir; satira tasinsaydi ayni metin tekrarlanir ve AYRISABILIRDI.
    """

    __tablename__ = "journal_lines"
    __table_args__ = (
        # DB SON SAVUNMADIR: negatif tutar `Σ`yi sessizce dengeleyemez.
        CheckConstraint("debit >= 0 AND credit >= 0", name="ck_journal_lines_amounts_non_negative"),
        # `(0,0)` ve cift-dolu satir REDDEDILIR (bkz. sinif docstring'i).
        CheckConstraint(
            "(debit > 0 AND credit = 0) OR (credit > 0 AND debit = 0)",
            name="ck_journal_lines_single_side",
        ),
        # FK'ler otomatik indeks URETMEZ: defter (`/journal`) ve bakiye
        # turetimi (K3) bu iki sutundan gecer.
        Index("ix_journal_lines_entry_id", "entry_id"),
        Index("ix_journal_lines_account_id", "account_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journal_entries.id", ondelete="CASCADE"), nullable=False
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chart_of_accounts.id", ondelete="RESTRICT"), nullable=False
    )
    # 🔴 NOT NULL: NULL tutar `SUM` tarafindan YUTULUR ve dengesiz fis dengede
    # sayilirdi (modul docstring'i, NULL fail-closed).
    debit: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=0, server_default=text("0")
    )
    credit: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=0, server_default=text("0")
    )
