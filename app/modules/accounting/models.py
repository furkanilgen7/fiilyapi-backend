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
  * `ck_journal_entries_posting_balanced` — DENGESIZ fis DEFTERE GIREMEZ
    (`posted` + `reversed`, TB6 T2); taslak dengesiz BIRAKILABILIR
    (kayitlastirma aninda kapi yeniden kosar).
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
(`_apply_totals`) yazilir, CHECK de `draft` DISINDAKI her durumda isirir
(TB6 T2: eskiden yalniz `posted`ti — asagidaki `BALANCE_ENFORCED_STATUSES`).
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

ACILMAYANLAR (spec §9, kasitli — "eksik" diye geri acilmaz): banka
mutabakati · e-Fatura · fatura/hazine/bordro → otomatik fis (MU-3) ·
`parent_id` FK · sinif KAYDI · Excel/disa aktarim · para birimi/kur
(`₺` metne gomulu sabit) · fise belge eki · toplu ice aktarim / tekduzen hesap
plani seed'i · `draft` icin onay akisi.

SONRADAN ACILANLAR (tarih sirasiyla — bu liste bilerek TUTULUR ki bir kararin
geri alindigi gorunur olsun): mizan + KDV beyani + donem kapanisi /
`accounting_periods` (MU-2) · mali tablolar: Bilanco + Nakit Akis Tablosu
(MT-1) · 🔑 **`is_contra` kolonu (MT-1/KK-1, kullanici karari 2026-08-16)** —
MU-1 `257`in parantezini bir SUNUM kurali sayip kolonu acmamisti; MT-1'de
sunucunun `Maddi Duran Varliklar (net)` kalemini FIILEN netlemesi gerektigi
icin karar geri alindi · 🔑 **`ChartAccountType.equity` (ayni karar)** —
Bilanco `III. OZKAYNAKLAR` bolumu dort uyeli kumeyle ifade edilemiyordu ·
🔑 **`entry_no` + `numbering.py` (FIS-NO, kullanici karari 2026-08-21)** —
MU-1 "hicbir mockup sutununda fis numarasi yok, kimlik `id`dir" gerekcesiyle
acmamisti; dayanak iki mockup'ta FIILEN cizili oldugu icin karar geri alindi
(bkz. `JournalEntry` sinif docstring'i).

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

#: MU-2 — kapanis damgasinin BUTUNLUGU. Bir durum damgasi N parcadan
#: olusuyorsa N'in HEPSI birlikte yazilir (MK-2 N-CARPANLI SNAPSHOT kanonunun
#: kardesi). Iki yon de kilitlidir:
#:   * `closed` + eksik damga → "kapali ama kim/ne zaman kapatti belli degil";
#:     denetim gunlugu (B5) o donemi kimin kilitledigini SORAMAZ hale gelir.
#:   * `open` + artik damga → yeniden acilmis donem hala eski kapatma damgasini
#:     tasir ve mali iz YALAN SOYLER.
#: 🔴 Enum iki degerlidir; ucuncu bir uye acilsaydi bu CHECK'in ikili mantigi
#: TANIMSIZ kalirdi (bkz. `AccountingPeriodStatus`).
CLOSED_STAMP_CHECK = (
    "(status = 'closed' AND closed_at IS NOT NULL AND closed_by_id IS NOT NULL) OR "
    "(status = 'open' AND closed_at IS NULL AND closed_by_id IS NULL)"
)


class ChartAccountType(str, enum.Enum):
    """Hesap turu — HP:60 `Tur` sutunu + MT-1'in `equity` uyesi.

    HP dort rozet cizer: `Aktif` (HP:78) · `Pasif` (HP:154) · `Gelir` (HP:192)
    · `Gider` (HP:199).

    🔑 **KULLANICI KARARI (2026-08-16, MT-1/KK-1 — TAM TDHP UYUMU): `equity`
    BESINCI UYE OLARAK ACILDI.** Bu, MU-1'in *"Besinci uye ICAT EDILMEZ"*
    kanonunun **bilincli iptalidir** ve gerekcesi olculmustur: Bilanco'nun
    `III. OZKAYNAKLAR` bolumu (BL:80-84 — `Sermaye` · `Gecmis Yillar Karlari` ·
    `Donem Net Kari`) dort uyeli kumeyle ifade edilemiyor. `500 Sermaye`
    `liability` sayilsaydi hesap plani ekraninda `Pasif` rozeti basar ve
    bilanco bu satirlari `I. KISA VADELI YUKUMLULUKLER` bolumunden ayiramazdi.
    Iptal `equity` ILE SINIRLIDIR: `memorandum`/`cost`/`contra` gibi bir ALTINCI
    uye hala acilmaz (kontra bir TUR degil, `is_contra` bayragidir).

    🔴 Bu enum HP:62 `Durum` sutunu DEGILDIR (bkz. modul docstring'i R3):
    Durum `is_active` boolean'idir, Tur budur.

    K3 isaret kurali bu turden okunur: `asset`/`expense` → `+1`,
    `liability`/`revenue`/**`equity`** → `−1` (`balance.py` TEK KAYNAK).
    🔴 `balance.SIGN` sozlugune `equity` girisi ZORUNLUDUR: `sign_case()`in
    `else_` dali BILEREK yoktur ve eksik uye **NULL** uretir.

    Uye SIRASI kilitlidir: Postgres'te `ALTER TYPE … ADD VALUE` uyeyi SONA
    ekler, `enum_range` da o sirayi doner (migration testi bunu olcer).
    """

    asset = "asset"  # Aktif
    liability = "liability"  # Pasif
    revenue = "revenue"  # Gelir
    expense = "expense"  # Gider
    equity = "equity"  # Ozkaynak (MT-1/KK-1)


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


#: 🔴 TB6 T2 — dengesi **DB duzeyinde** zorlanan durumlar. `balance`in
#: `POSTING_STATUSES` demetiyle AYNI kume olmak ZORUNDADIR ve bu bir yorum
#: degil, TESTLE baglidir (`test_tb6_reversed_balanced_check`): iki liste
#: ayrisirsa deftere giren ama dengesi denetlenmeyen bir durum dogar.
#:
#: 🔴 Burada durur, `balance.py`de DEGIL: `balance` bu modulu import eder, ters
#: yon dongu olurdu. `balance.POSTING_STATUSES` anlamli olani (defterin
#: suzgeci), bu sabit ise onun SQL yansimasidir.
BALANCE_ENFORCED_STATUSES: tuple[str, ...] = ("posted", "reversed")

#: CHECK'in SQL'i ELLE yazilmaz, kumeden URETILIR: elle yazilsaydi yeni bir
#: durum eklendiginde biri guncellenir, oteki kalirdi.
POSTING_BALANCED_CHECK = (
    "status NOT IN ("
    + ", ".join(f"'{durum}'" for durum in BALANCE_ENFORCED_STATUSES)
    + ") OR total_debit = total_credit"
)


class AccountingPeriodStatus(str, enum.Enum):
    """Donem durumu — IKI degerli, ucuncu uye ICAT EDILMEZ.

        open ──kapat──▶ closed ──(ac)──▶ open

    `locked`/`archived`/`reopened` gibi bir ucuncu uye ACILMAZ. Iki gerekcesi
    var: (1) hicbir ekran ucuncu bir rozet cizmiyor, (2) `CLOSED_STAMP_CHECK`
    IKILI bir mantiktir — ucuncu bir degerde damganin ne olmasi gerektigi
    TANIMSIZ kalir ve kisit sessizce her seyi kabul eden bir sey haline gelirdi.

    "Yeniden acildi" AYRI BIR DURUM DEGILDIR: donem `open`a doner ve damga
    SOKULUR (CHECK bunu zorlar). `reopened_at` kolonu da yoktur — kim ne zaman
    acti sorusunun yeri denetim gunlugudur (B5), bu tablo DEGIL.
    """

    open = "open"
    closed = "closed"


class AccountingPeriod(Base):
    """Muhasebe donemi (yil/ay) ve kapanis damgasi.

    MU-1 bu tabloyu BILEREK acmamisti (modul docstring'i "ACILMAYANLAR"):
    `journal_entries.period_year`/`period_month` cifti ve `ix_journal_entries_
    period` indeksi tam olarak BU tablo icin hazirlanmisti. Donem kaydi burada
    dogar; kapali doneme yazma YASAGI ve kilit mantigi SERVIS katmanindadir
    (T3) — bu sinif yalniz KAYDIN kendisini ve tutarliligini garanti eder.

    🔴 `(year, month)` TEKILDIR. Ayni ay iki kez acilabilseydi biri `open` biri
    `closed` iki satir dogar ve "2026/07 kapali mi?" sorusunun IKI cevabi
    olurdu; donem kilidi hangi satira bakacagini bilemezdi.

    🔴 UNIQUE ZATEN bir B-tree indeks URETIR — ayrica bir
    `ix_accounting_periods_year_month` ACILMAZ. Acilsaydi AYNI iki sutun
    uzerinde IKINCI bir indeks tasinir, her yazma iki kez maliyetlenir ve
    hicbir okuma hizlanmazdi. Sorgu yolu (`WHERE year = ? AND month = ?`)
    zaten UNIQUE indeksin ta kendisini kullanir.

    🔴 `ck_accounting_periods_closed_stamp` bu tablonun ASIL bekcisidir; gerekce
    `CLOSED_STAMP_CHECK` sabitinin yanindadir. Kaldirilirsa "kapali ama damgasiz"
    donem yazilabilir hale gelir ve mali iz sessizce bosalir.

    Ay ve yil bantlari (`ck_..._month_range` / `ck_..._year_range`) yazim
    hatasina karsi son savunmadir: `month = 0`/`13` var olmayan bir donem
    uretir, mizan hicbir takvimde bulamaz; `year = 26`/`20026` ise sessizce
    kalici olurdu. Bant `journal_entries`te YOKTU (orada donem `entry_date`ten
    TURETILIR ve `ck_journal_entries_period_matches_date` ile kilitlidir) —
    burada tarih dayanagi olmadigi icin bant ACIKCA yazilir.

    KAPSAM (IDOR) — `project_id`/`site_id` YOKTUR, MU-1'in uc tablosuyla AYNI
    gerekce: hesap plani ve yevmiye sirket geneliyse donem de oyledir. Proje
    bazli donem acilsaydi ayni ay bir projede kapali bir projede acik olur ve
    "donem kapali" ifadesi ANLAMINI KAYBEDERDI.

    TUREV ALAN YOKTUR: donemin toplamlari/mizani SAKLANMAZ, yevmiyeden
    TURETILIR (K3'un kardesi). Saklansaydi kaydigini hicbir kolon farki ele
    vermezdi.

    `closed_by_id` RESTRICT: donemi kapatan kullanici, mali izi sahipsiz
    birakacak sekilde silinemez (`journal_entries.created_by_id` deseni). SET
    NULL olsaydi kapali donem damgasiz kalir ve `ck_accounting_periods_closed_
    stamp` DB'nin KENDISI tarafindan ihlal edilirdi.
    """

    __tablename__ = "accounting_periods"
    __table_args__ = (
        # Bir (yil, ay) icin TEK kayit — bkz. sinif docstring'i.
        UniqueConstraint("year", "month", name="uq_accounting_periods_year_month"),
        CheckConstraint("month BETWEEN 1 AND 12", name="ck_accounting_periods_month_range"),
        CheckConstraint("year BETWEEN 2000 AND 2100", name="ck_accounting_periods_year_range"),
        # 🔴 Damga BUTUNDUR: `closed` ise ikisi de DOLU, `open` ise ikisi de NULL.
        CheckConstraint(CLOSED_STAMP_CHECK, name="ck_accounting_periods_closed_stamp"),
        # AYRICA `Index(...)` YOK: UNIQUE zaten indekstir (docstring gerekcesi).
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[AccountingPeriodStatus] = mapped_column(
        Enum(AccountingPeriodStatus, name="accounting_period_status"),
        nullable=False,
        default=AccountingPeriodStatus.open,
        server_default=text("'open'"),
    )
    # 🔴 IKISI DE nullable OLMAK ZORUNDA: `open` donemde ikisi de NULL'dir
    # (CHECK bunu zorlar). NOT NULL olsalardi acik donem HIC yazilamazdi.
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


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
    # 🔑 MT-1/KK-1 — KONTRA BAYRAGI. `257 Birikmis Amortismanlar (-)` kendi mali
    # tablo kaleminden CIKARILIR: BL:57 `Maddi Duran Varliklar (net)` =
    # 2.400.000 + 1.840.000 − 620.000 = 3.620.000. MU-1 bunu bir SUNUM kurali
    # sayip kolonu acmamisti (adin `(-)` son eki); MT-1'de sunucu netlemeyi
    # YAPMAK ZORUNDA oldugu icin karar geri alindi.
    #
    # 🔴 KURAL TEK CUMLEDIR: `is_contra = True` <=> hesabin DOGAL BAKIYE YONU
    # (`SIGN[account_type]`), dustugu KALEMIN TARAFININ TERSIDIR. Bakiyesi o
    # kalemden DUSULUR.
    #   * `257 Birikmis Amortismanlar (-)` -> `liability` (alacak) ama AKTIF
    #     tarafta `Maddi Duran Varliklar (net)` kalemine duser -> **True**
    #   * `501 Odenmemis Sermaye (-)` -> `equity` (alacak), PASIF tarafta kalir
    #     -> **False** (borc bakiyesi `SIGN[equity] = -1` ile zaten duser)
    # 🔴 `(-)` SON EKINE bakan bir kural YANLISTIR ve `257` disindaki her kontra
    # hesapta isareti TERS cevirir (T7 final review'de olculdu: `501` kontra
    # isaretlenince `Sermaye` 6.000 yerine 14.000 basiyor).
    #
    # 🔴 NOT NULL + `server_default`: nullable olsaydi `NULL` bir ucuncu hal
    # uretir, Python'da "yanlis" sayilirken SQL ifadelerinde NULL yayardi.
    # Sunucu varsayilani ORM disi her yazma yolu (migration data-fix, elle SQL)
    # icin sarttir.
    is_contra: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class JournalEntry(Base):
    """Yevmiye fisi basligi.

    🔑 **`entry_no` VARDIR** (FIS-NO, kullanici karari 2026-08-21). MU-1 bu
    kolonu "hicbir mockup sutununda fis numarasi yok" gerekcesiyle ACMAMISTI;
    karar GERI ALINDI cunku dayanak iki mockup'ta FIILEN cizilidir:
      * `projedesign/Form - Yevmiye Kaydi.dc.html` — **Fis No** alani `disabled`
        ve "Otomatik" / "Kayitta uretilir" der: numarayi SUNUCU verir, istemci
        GONDEREMEZ (sema `extra="forbid"` ile bunu 422'ye cevirir).
      * `projedesign/Muhasebe - Donem Kapanisi.dc.html` — TASLAK fisler
        `YEV-2026-0214` / `0216` / `0218` ile listelenir. Tek basina UC seyi
        birden kanitlar: bicim `YEV-{yil}-{sira}`dir, numara `draft`ta ZATEN
        vardir ve sira BOSLUKLU ilerler (214 -> 216 -> 218).

    Uretim `accounting/numbering.py`dedir (bu dilimde ACILDI). Kullanicinin
    bagladigi uc karar kolona gomuludur:
      1. Sira YIL bazlidir — yil `period_year` KOLONUNDAN okunur (tek kaynak;
         `ck_journal_entries_period_matches_date` onu `entry_date`in yiliyla
         zaten esitler) — ve her 1 Ocak'ta 1'e doner. Sayac SIRKET GENELINDE
         tektir: santiye/proje kirilimi YOKTUR (bu tabloda `project_id` de
         yoktur). Dort hane bir TAVAN degil EN AZ genisliktir; 9999'dan sonra
         numara BUDANMAZ, bes haneye UZAR.
      2. BOSLUK OLABILIR: fis silinince numarasi bosta kalir, sayac GERI
         ALINMAZ ve numaralar YENIDEN DIZILMEZ.
      3. Numara `draft` ACILIRKEN verilir ve `posted` olurken DEGISMEZ. `PATCH`
         `entry_date`i sonraki YILA tasisa bile numara KAYMAZ: bir kez verilir
         ve fisin kimligidir — kaydigi anda kullanicinin elindeki kagit yanlis
         fisi gosterirdi.

    🔴 UNIQUE **kolonun genelindedir**, `(period_year, entry_no)` ciftinde
    DEGIL: yil ZATEN numaranin icindedir, yani kolon geneli tekillik dogru
    olcudur. Cift kisit hem ayni seyi iki kez soyler hem de YANLIS olurdu —
    `period_year` bir `PATCH` ile degisir ama numara degismez, dolayisiyla cift
    kisit fisin kimligini KAYAN bir alana baglardi.

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
        # 🔑 FIS-NO — numara SIRKET GENELINDE tekildir (yil numaranin icinde).
        UniqueConstraint("entry_no", name="uq_journal_entries_entry_no"),
        CheckConstraint(PERIOD_MATCHES_DATE_CHECK, name="ck_journal_entries_period_matches_date"),
        # 🔴 K1'in baslik ayagi: DENGESIZ FIS DEFTERE GIREMEZ. `draft` dengesiz
        # BIRAKILABILIR — kapi kayitlastirma aninda yeniden kosar.
        CheckConstraint(POSTING_BALANCED_CHECK, name="ck_journal_entries_posting_balanced"),
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
    # 🔑 FIS-NO — `YEV-2026-0214`. SUNUCU URETIR (`numbering.generate_entry_no`).
    #
    # 🔴 NOT NULL: numarasiz fis diye bir sey YOKTUR. Nullable olsaydi numara
    # uretmeyi UNUTAN bir yazma yolu satiri sessizce NULL birakir ve kusur ancak
    # kullanici fisi telefonda soylemeye calistiginda gorunurdu; UNIQUE de
    # PG'de coklu NULL'a izin verdigi icin kisit onu HIC yakalamazdi.
    #
    # `String(20)`: `request_no`/`order_no` deseni. `YEV-2026-0001` 13
    # karakterdir; bant, sirasi ALTI haneye uzamis bir yila kadar yeter.
    # `server_default` YOKTUR ve olmamalidir: uydurulmus bir varsayilan
    # (`''` gibi) UNIQUE'e carpardi — numara TEK yoldan, ureticiden gelir.
    entry_no: Mapped[str] = mapped_column(String(20), nullable=False)
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
    # `ck_journal_entries_posting_balanced` sessizce GECERDI.
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


class JournalEntryCounter(Base):
    """FIS-NO — yil bazli yevmiye fis numarasi sayaci (`YEV-{yil}-{sira}`).

    🔴 **NEDEN UCUNCU BIR MEKANIZMA — `procurement`/`invoicing` deseni BURADA
    YANLIS OLURDU.** Depoda zaten iki numara ureticisi var ve ikisi de
    `pg_advisory_xact_lock(anahtar, yil)` + `max(cast(sonek AS int)) + 1`
    kullanir; ikisinin de docstring'i `SELECT … FOR UPDATE`yi ACIKCA REDDEDER
    ("kilitlenecek SATIR henuz yoktur"). Bu tablo o kanondan BILEREK ayrilir ve
    bu bir DRIFT DEGILDIR:

    `max + 1` numarayi HAYATTA KALAN SATIRLARDAN yeniden HESAPLAR. En buyuk
    numarali fis silinince numarasi YENIDEN KULLANILIR — bu, kullanicinin
    2. kararini ("sayac GERI ALINMAZ") dogrudan cigner ve mali izi bozar:
    silinen fisi kagida basmis bir kullanici, ayni numarayi tasiyan BASKA bir
    fisle karsilasirdi. Yevmiye fisinde bu bir KENAR DURUM DEGILDIR: `draft`
    SILINEBILIR ve numara `draft` ACILIRKEN verilir, yani "kullanici taslak
    acti, sonra vazgecti" OLAGAN yoldur. `procurement`/`invoicing`de ayni fark
    ISIRMAZ cunku oradaki numaralar ayni bicimde silinmez.

    Sayac tablosu MONOTONDUR ve bunu yapisal olarak atlatir: fislerden BAGIMSIZ
    yasar, silmeden hic etkilenmez ve yalnizca ileri gider. Bosluk bir kusur
    degil, kararin ta kendisidir. Satir VAR OLDUGU icin `SELECT … FOR UPDATE`
    de burada ise YARAR — reddedilme gerekcesi (satirin yoklugu) UPSERT-SONRA-
    KILITLE ile ortadan kalkar (MU-2 kanonu, `numbering.py`de uygulanir).

    Ayri bir Postgres `SEQUENCE` de secilmedi: yil basinda sifirlanmasi ELLE
    mudahale ister ve `nextval` transaction disidir — rollback'te bosluk birakir
    ama daha onemlisi kilit davranisi test edilebilir DEGILDIR.

    `year` BIRINCIL ANAHTARDIR: yil basina TEK satir. Ayri bir `id` + UNIQUE
    acilsaydi "2026'nin sayaci kac?" sorusunun IKI cevabi olabilirdi.

    `next_no` = BIR SONRAKI dagitilacak siradir, kullanilan SON numara DEGIL.
    "Son kullanilan" saklansaydi yilin ilk fisi 0 ile ifade edilirdi ve 0 hem
    "hic dagitilmadi" hem de gecerli bir sira gibi okunabilirdi; "sonraki" her
    zaman DOGRUDAN kullanilabilir bir degerdir ve ureticide `+1` dali kalmaz.

    KAPSAM: santiye/proje kirilimi YOKTUR — sayac SIRKET GENELINDE tektir
    (kullanici karari) ve `journal_entries`te zaten `project_id` de yoktur.
    Zaman damgasi kolonu da ACILMAZ: bu bir MALI KAYIT degil bir sayactir,
    "kim ne zaman numara aldi" sorusunun yaniti fisin kendisidir.
    """

    __tablename__ = "journal_entry_counters"
    __table_args__ = (
        # Elle bir `UPDATE … SET next_no = 0` sayaci GERI SARARDI; 1'in altina
        # inmek "sayac geri alinmaz" kararinin tek fiili ihlal yoludur.
        CheckConstraint("next_no >= 1", name="ck_journal_entry_counters_next_no_positive"),
    )

    # `autoincrement=False`: `Integer` + `primary_key` ikilisi SQLAlchemy'de
    # varsayilan olarak SERIAL'e ayartir; yil bir dizi degeri DEGIL, veridir.
    year: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    next_no: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
