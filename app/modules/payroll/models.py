"""İK-3 bordro çekirdeği — veri modeli (spec §4).

Üç tablo: dönem (ay) · dönem satırı (personel başına) · yapılandırılabilir oran
tablosu. Router/servis BU DOSYADA YOKTUR (T2+).

Bu modülün taşıdığı kalıcı kararlar:

* **K1 — oranlar VERİDİR.** Yedi oran `payroll_rates`ta durur, koda gömülmez;
  mevzuat değişince kod değişmez. 🔴 **IK3-GV (2026-08-17) ile aynı kural
  TARİFEYE de uygulandı:** dilimli/kümülatif gelir vergisi motoru artık VARDIR
  ve dilimler `payroll_tax_brackets` tablosunda, asgari ücret
  `payroll_minimum_wages` tablosunda durur — koda gömülü sabit YOKTUR
  (JSON kolon da YASAKTIR: CHECK yazılamaz, bozuk/eksik dilim seti DB'de yasal
  olur, `Numeric` kuruş disiplini kaybolur).
* **S1 — açık oran kazanır.** BY tablosundaki tutarlar temsilîdir; SGK 70-81'de
  AÇIKÇA yazılı yüzdeler SEED değeridir (migration `c5d6e7f8a9b0`).
* **S2 — oran seti `(yıl, personel tipi)` anahtarlıdır**, tek global oran değil:
  BY 127 / 175 / 243 / 271 dört ayrı rejim çiziyor.
* **S3 — `banka + elden = net` invariantı.** Kuruş hassasiyeti `Numeric(12,2)`.
  Doğrulama SERVİStedir (`bank`/`cash`/`net` üçü de NULL olabildiği için DB
  CHECK'i S4 ile çelişirdi).
* **S4 — fail-closed:** ücreti olmayan personelde brüt/net **`null`** durur,
  UYDURMA 0 BASILMAZ; bu yüzden beş para kolonu da nullable ve SUNUCU
  VARSAYILANI YOKTUR.
* **K3/S6 — düzeltme iz bırakır** (`is_overridden` + kim/ne zaman/önceki değer)
  ve yeniden hesap bu satırları EZMEZ.
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
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

# Paylaşılan tip: `worker_source` DB tipi şantiye günlüğü diliminde
# (b5c6d7e8f9a0) yaratıldı, İK-3 ona `freelance`/`intern` değerlerini TAKAS ile
# ekledi. Yeni bir `personnel_source` tipi AÇILMAZ (puantaj spec §2).
from app.modules.site_diary.models import WorkerSource

# Oran sütunlarının ölçeği. ÜÇ ondalık ZORUNLUDUR: damga vergisi %0,759'dur
# (SGK 73) ve iki ondalık onu 0,76'ya yuvarlayıp kesintiyi sessizce şişirirdi.
RATE_PRECISION = 6
RATE_SCALE = 3

# S3: para kolonlarının kuruş hassasiyeti.
MONEY_PRECISION = 12
MONEY_SCALE = 2


class IncomeKind(str, enum.Enum):
    """Gelir türü — GVK m.103 tarifesinin HANGİ tablosu (K5).

    Ücret ve ücret dışı tarifeler 3. dilimden itibaren AYRIŞIR (2026'da ücret
    1.500.000/%27 iken ücret dışı 1.000.000'dur). Bordro HER ZAMAN `wage`
    kullanır ve tohumda yalnız `wage` BASILIR — ücret dışı satırlar
    kullanılmadığı için uydurulmaz (WORKFLOW §3).

    🔴 Kolon YİNE DE ŞİMDİ açılır: sonradan eklenseydi geçmiş tohumun hangi
    tabloya ait olduğu belirsiz kalır ve varsayılan bir değer atamak, ücret dışı
    bir tarifeyi ücret tarifesi gibi göstermeyi mümkün kılardı.
    """

    wage = "wage"
    non_wage = "non_wage"


class PayrollPeriodStatus(str, enum.Enum):
    """Dönem durumu (spec §4, S8: BY 56/303 + BG durum sütunu).

    Zincir `draft → pending_approval → approved → paid`; ATLAMA YOKTUR ve geri
    geçiş yalnız `paid` DEĞİLKEN mümkündür — geçiş kapısı T3'te servistedir.
    """

    draft = "draft"
    pending_approval = "pending_approval"
    approved = "approved"
    paid = "paid"


class PayrollLineStatus(str, enum.Enum):
    """Satır durumu (spec §4).

    `uncomputed` S4'ün taşıyıcısıdır: ücreti olmayan personelin satırı AÇILIR
    ama brüt/net `null` durur ve ödeme onayına GİRMEZ. `excluded` K2'nin
    taşıyıcısıdır: taşeron satırı görünür ve maliyete girer, ÖDENMEZ (ödemesi
    hakediş üzerinden taşerona yapılır) — çift ödeme yapısal olarak imkânsızdır.
    """

    uncomputed = "uncomputed"
    pending = "pending"
    approved = "approved"
    paid = "paid"
    excluded = "excluded"


class PayrollPeriod(Base):
    """Bordro dönemi = bir AY (spec §4).

    UQ (year, month): bir ay için TEK bordro — ikinci `POST` 409'dur.

    BG kartlarındaki toplamlar (çalışan sayısı · brüt · SGK işveren · net ·
    toplam maliyet) KOLON DEĞİLDİR: satırlardan TÜREVDİR. Kolon açılsaydı iki
    gerçek kaynak doğar ve `compute` sonrası sessizce çelişirdi.

    `sgk_submitted_at` yalnız bir DAMGADIR (SGK 44): dış sistem entegrasyonu
    YOKTUR, alan elle işaretlenir (spec §1).
    """

    __tablename__ = "payroll_periods"
    __table_args__ = (
        CheckConstraint("month >= 1 AND month <= 12", name="ck_payroll_periods_month_range"),
        UniqueConstraint("year", "month", name="uq_payroll_periods_year_month"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[PayrollPeriodStatus] = mapped_column(
        Enum(PayrollPeriodStatus, name="payroll_period_status"),
        nullable=False,
        default=PayrollPeriodStatus.draft,
        server_default=text("'draft'::payroll_period_status"),
        index=True,
    )
    # BY 63 "Son ödeme" — bilgi alanıdır, geçiş kapısı DEĞİLDİR.
    payment_due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # SET NULL: onaylayan kullanıcı silinse de dönem ve onay ZAMANI ayakta kalır
    # (İK-2 `decided_by` emsali).
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sgk_submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class PayrollLine(Base):
    """Dönem satırı — personel başına brüt/kesinti/net (spec §4, BY tablosu birebir).

    `personnel_id` **RESTRICT**'tir (CASCADE DEĞİL, İK-1/İK-2 deseninin bilinçli
    istisnası): bordro satırı bir PARA izidir, personel kaydı silinerek yok
    edilemez. Personel zaten silinmez, `is_active=false` ile pasifleşir.

    `personnel_source` satır anındaki tipin SNAPSHOT'ıdır: personel taşerondan
    şirket kadrosuna geçse GEÇMİŞ bordro değişmez. `personnel`e JOIN atıp tipi
    canlı okumak, ödenmiş bir dönemi geriye dönük başka bir rejime taşırdı.

    Kesinti oranları satıra KOPYALANMAZ (K1): tek gerçek kaynak `payroll_rates`.

    Beş para kolonu da nullable ve sunucu varsayılansızdır (S4): `uncomputed`
    satırda hepsi `null` durur — "0 ödenecek" ile "hesaplanamadı" birbirinden
    ayırt edilebilir olmalıdır.

    `bank + cash = net` invariantı (S3) DB CHECK'i DEĞİLDİR: üç kolonun da NULL
    olabildiği `uncomputed` durumda CHECK ya S4'ü kırar ya da anlamsız biçimde
    NULL'a izin verip hiçbir şey zorlamaz. Doğrulama T3'te servistedir (ihlal 422).
    """

    __tablename__ = "payroll_lines"
    __table_args__ = (
        CheckConstraint("days IS NULL OR days >= 0", name="ck_payroll_lines_days_positive"),
        CheckConstraint(
            "gross_amount IS NULL OR gross_amount >= 0",
            name="ck_payroll_lines_gross_positive",
        ),
        CheckConstraint(
            "deduction_amount IS NULL OR deduction_amount >= 0",
            name="ck_payroll_lines_deduction_positive",
        ),
        CheckConstraint(
            "net_amount IS NULL OR net_amount >= 0", name="ck_payroll_lines_net_positive"
        ),
        CheckConstraint(
            "bank_amount IS NULL OR bank_amount >= 0", name="ck_payroll_lines_bank_positive"
        ),
        CheckConstraint(
            "cash_amount IS NULL OR cash_amount >= 0", name="ck_payroll_lines_cash_positive"
        ),
        # IK3-GV K1 — vergi SNAPSHOT'ı: üçü de negatif olamaz.
        CheckConstraint(
            "tax_base_amount IS NULL OR tax_base_amount >= 0",
            name="ck_payroll_lines_tax_base_positive",
        ),
        CheckConstraint(
            "cumulative_tax_base IS NULL OR cumulative_tax_base >= 0",
            name="ck_payroll_lines_cumulative_tax_base_positive",
        ),
        CheckConstraint(
            "income_tax_amount IS NULL OR income_tax_amount >= 0",
            name="ck_payroll_lines_income_tax_positive",
        ),
        UniqueConstraint(
            "payroll_period_id", "personnel_id", name="uq_payroll_lines_period_personnel"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # CASCADE: dönem silinince satırları düşer — yetim satır bırakılmaz.
    payroll_period_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("payroll_periods.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    personnel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("personnel.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    personnel_source: Mapped[WorkerSource] = mapped_column(
        Enum(WorkerSource, name="worker_source"), nullable=False
    )
    # S7: gün PUANTAJDAN okunur; serbest mesleklide gün YOKTUR (BY 254 "—").
    days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gross_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(MONEY_PRECISION, MONEY_SCALE), nullable=True
    )
    deduction_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(MONEY_PRECISION, MONEY_SCALE), nullable=True
    )
    net_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(MONEY_PRECISION, MONEY_SCALE), nullable=True
    )
    bank_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(MONEY_PRECISION, MONEY_SCALE), nullable=True
    )
    cash_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(MONEY_PRECISION, MONEY_SCALE), nullable=True
    )
    # --- IK3-GV K1: KÜMÜLATİF MATRAH SNAPSHOT'TIR, `SUM` DEĞİLDİR ------------
    #
    # 🔴 Gerekçe ÖLÇÜLDÜ: `service.create_period` yalnız UQ `(year, month)`
    # kontrol eder — **ay sırası hiçbir yerde zorlanmaz.** Temmuz açılıp
    # hesaplanabilir (kümülatif 0 → ilk dilim), `approve`+`pay` ile DONAR, sonra
    # Mart açılır. `SUM` yolu seçilseydi aynı sorgu Temmuz için artık başka bir
    # sayı üretirdi ama Temmuz'un `deduction_amount`ı eski değeri taşırdı ve
    # ASLA düzeltilemezdi (`transitions.py` tek yönlüdür, DELETE ucu yoktur) →
    # ödenmiş bir dönemin vergisi kalıcı olarak, SESSİZCE yanlış.
    #
    # 🔑 MK-2 kanonu: türev para N çarpandan oluşuyorsa snapshot N'in HEPSİNİ
    # kapsar. Burada üç çarpan var ve üçü de saklanır: o ayın matrahı
    # (`tax_base_amount`), o ana kadarki kümülatif (`cumulative_tax_base`) ve
    # sonuç (`income_tax_amount`). Tarife + istisna dördüncü çarpandır ve
    # `payroll_tax_brackets`/`payroll_minimum_wages`ın YILLIK satırlarında,
    # `upsert_rate`in kilitli-yıl korkuluğuyla korunarak durur.
    #
    # Üçü de nullable ve SUNUCU VARSAYILANSIZDIR (S4): `uncomputed` satırda
    # `null` durur — "vergi yok" ile "hesaplanamadı" ayırt edilebilir olmalıdır.
    #: Gelir vergisi matrahı = `brüt − SGK işçi − işsizlik işçi` (KK-7 adım 1).
    #: 🔴 Asgari ücret istisnası bu matrahta KALIR (indirim değil KREDİdir).
    tax_base_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(MONEY_PRECISION, MONEY_SCALE), nullable=True
    )
    #: Yıl başından bu ay DAHİL biriken matrah — tarifenin girdisi.
    cumulative_tax_base: Mapped[Decimal | None] = mapped_column(
        Numeric(MONEY_PRECISION, MONEY_SCALE), nullable=True
    )
    #: 🔴 O ayın gelir vergisi — istisna DÜŞÜLMÜŞ, taban 0. IK3-GV öncesinde bu
    #: sayı hesabın HİÇBİR YERİNDE ayrı bir `Decimal` olarak var olmuyordu.
    income_tax_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(MONEY_PRECISION, MONEY_SCALE), nullable=True
    )
    # K3 izi: kim/ne zaman/önceki değer. `compute` bu satırı EZMEZ (S6).
    is_overridden: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    overridden_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    overridden_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    previous_gross_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(MONEY_PRECISION, MONEY_SCALE), nullable=True
    )
    status: Mapped[PayrollLineStatus] = mapped_column(
        Enum(PayrollLineStatus, name="payroll_line_status"),
        nullable=False,
        default=PayrollLineStatus.uncomputed,
        server_default=text("'uncomputed'::payroll_line_status"),
        index=True,
    )
    # K2: taşeron satırının niçin ödemeye girmediği KAYITLIDIR — sessiz atlama yok.
    excluded_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class PayrollRate(Base):
    """Yapılandırılabilir kesinti/prim oranları (K1, spec §4).

    Anahtar `(yıl, personel tipi)`dir (S2). SEED'i migration'dadır: 2026 için
    dört tip (`company` · `subcontractor` · `freelance` · `intern`). `general`
    ("genel işçi") bordro tipi DEĞİLDİR — BY dört bölüm çiziyor.

    Yedi oran ve mockup kaynakları: SGK işçi %14 (SGK 70) · işsizlik işçi %1
    (SGK 71) · gelir vergisi %10 (SGK 72) · damga %0,759 (SGK 73) · SGK işveren
    %20,5 (SGK 79) · işsizlik işveren %2 (SGK 80) · kısa çalışma %1 (SGK 81).

    `is_active`: eski yılın seti SİLİNMEZ (geçmiş bordronun hesabı okunabilir
    kalmalı), pasifleştirilir. Oran GÜNCELLEME ucu T5'tedir; geçmiş dönemin
    hesabını geriye dönük değiştirmemesi servisin işidir.
    """

    __tablename__ = "payroll_rates"
    __table_args__ = (
        CheckConstraint(
            "sgk_employee_pct >= 0 AND unemployment_employee_pct >= 0 "
            "AND income_tax_pct >= 0 AND stamp_tax_pct >= 0 "
            "AND sgk_employer_pct >= 0 AND unemployment_employer_pct >= 0 "
            "AND short_work_pct >= 0",
            name="ck_payroll_rates_non_negative",
        ),
        UniqueConstraint("year", "personnel_source", name="uq_payroll_rates_year_source"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    personnel_source: Mapped[WorkerSource] = mapped_column(
        Enum(WorkerSource, name="worker_source"), nullable=False
    )
    sgk_employee_pct: Mapped[Decimal] = mapped_column(
        Numeric(RATE_PRECISION, RATE_SCALE), nullable=False
    )
    unemployment_employee_pct: Mapped[Decimal] = mapped_column(
        Numeric(RATE_PRECISION, RATE_SCALE), nullable=False
    )
    #: 🔴 **IK3-GV K3 — `NULL` = DİLİMLİ MOTOR, dolu = DÜZ ORAN.**
    #:
    #: Rejim seçimi de VERİDİR: koda gömülü bir `if source in (...)` olsaydı
    #: mevzuat değişince kod değişirdi (K1 ile doğrudan çelişki). 2026 tohumu:
    #: `company`/`subcontractor` → `NULL` (GVK m.103 artan oranlı tarife) ·
    #: `freelance` → 20 (GVK m.94 serbest meslek stopajı) · `intern` → 0.
    #:
    #: 🔴 **KARŞI-RİSK ve ZORUNLU BEKÇİSİ:** `NULL` sessizce "vergi yok" diye
    #: OKUNAMAZ (NULL-EŞİK kanonu, SA dilimi). `NULL` iken o yıl için dilim seti
    #: ya da asgari ücret satırı bulunamazsa satır `uncomputed`a DÜŞER
    #: (ŞEF KARARI 2 deseni, fail-closed) — **0 vergi ASLA yazılmaz.**
    #: `intern`in 0'ı ise VERİDİR ve korunur: 0 ile `NULL` aynı şey değildir.
    income_tax_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(RATE_PRECISION, RATE_SCALE), nullable=True
    )
    stamp_tax_pct: Mapped[Decimal] = mapped_column(
        Numeric(RATE_PRECISION, RATE_SCALE), nullable=False
    )
    sgk_employer_pct: Mapped[Decimal] = mapped_column(
        Numeric(RATE_PRECISION, RATE_SCALE), nullable=False
    )
    unemployment_employer_pct: Mapped[Decimal] = mapped_column(
        Numeric(RATE_PRECISION, RATE_SCALE), nullable=False
    )
    short_work_pct: Mapped[Decimal] = mapped_column(
        Numeric(RATE_PRECISION, RATE_SCALE), nullable=False
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


# --------------------------------------------------------------------------- #
# IK3-GV — dilimli gelir vergisi tarifesi (K2) + asgari ücret (KK-7)
# --------------------------------------------------------------------------- #


class PayrollTaxBracket(Base):
    """GVK m.103 artan oranlı tarifesinin BİR DİLİMİ — K2, `payroll_rates` emsali.

    Anahtar `(year, income_kind, ordinal)`dir. `payroll_rates`in `(yıl, tip)`
    anahtarıyla aynı aile: tarife de YILLIKTIR ve mevzuat değişince KOD
    DEĞİŞMEZ.

    🔴 **JSON kolon YASAK.** Beş dilimi tek bir `jsonb`a koymak üç şeyi birden
    kaybettirirdi: (a) DB CHECK yazılamaz — bozuk/eksik bir dilim seti veritabanı
    düzeyinde YASAL olurdu; (b) `Numeric` kuruş disiplini gider, `float`
    yuvarlaması para zincirine sızardı; (c) tek satırın kısmi güncellenmesi
    imkânsızlaşırdı.

    🔴 **Kod içi sabit de YASAK** — bu modülün K1'i ("oranlar VERİDİR, koda
    gömülmez") ile doğrudan çelişirdi.

    `upper_bound IS NULL` **son dilim** demektir ("üstü"). Setin bütünlüğü
    (1..N aralıksız · sınırlar kesin artan · NULL yalnız sonda) DB'de tek satır
    üzerinden ZORLANAMAZ — o doğrulama `income_tax.normalize_brackets`tadır ve
    ihlali fail-closed'dur (satır `uncomputed`, 0 vergi YAZILMAZ). DB CHECK'i
    yalnız satır-içi olguları taşır.

    `is_active`: `payroll_rates` ile aynı kural — eski yılın tarifesi SİLİNMEZ
    (geçmiş bordronun hesabı okunabilir kalmalıdır), pasifleştirilir.

    🔴 **OKUMA/YAZMA UCU YOKTUR (K8).** Tarife migration'da tohumlanır; openapi
    215 yolda KALIR. `payroll_rates`in bile ekranı yokken dilimin ucu gerekmez;
    `GET/PUT /payroll/tax-brackets` ayrı ve ERTELENMİŞ bir dilimdir.
    """

    __tablename__ = "payroll_tax_brackets"
    __table_args__ = (
        CheckConstraint("ordinal >= 1", name="ck_payroll_tax_brackets_ordinal_positive"),
        CheckConstraint(
            "rate_pct >= 0 AND rate_pct <= 100",
            name="ck_payroll_tax_brackets_rate_range",
        ),
        # Sıfır ya da eksi bir üst sınır hiçbir matrahı kapsamaz: dilim ÖLÜ olurdu.
        CheckConstraint(
            "upper_bound IS NULL OR upper_bound > 0",
            name="ck_payroll_tax_brackets_upper_bound_positive",
        ),
        UniqueConstraint(
            "year", "income_kind", "ordinal", name="uq_payroll_tax_brackets_year_kind_ordinal"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    income_kind: Mapped[IncomeKind] = mapped_column(
        Enum(IncomeKind, name="payroll_income_kind"),
        nullable=False,
        default=IncomeKind.wage,
        server_default=text("'wage'::payroll_income_kind"),
    )
    #: 1'den başlar ve ARALIKSIZ artar; sıra ANLAMLIDIR (tarife birikimlidir).
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Dilimin üst eşiği; **`NULL` = son dilim** ("üstü").
    #: `Numeric(14,2)`: matrah 12 hanelik para kolonundan BÜYÜK olabilir
    #: (5.300.000 eşiği kuruşuyla sığar ama tarife yıllar içinde büyür).
    upper_bound: Mapped[Decimal | None] = mapped_column(Numeric(14, MONEY_SCALE), nullable=True)
    #: Oran YÜZDEDİR (`15.000` = %15) — `payroll_rates` ile AYNI ölçek.
    rate_pct: Mapped[Decimal] = mapped_column(Numeric(RATE_PRECISION, RATE_SCALE), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class PayrollMinimumWage(Base):
    """Yıllık BRÜT asgari ücret — KK-7 istisnasının TEK girdisi.

    🔴 Niçin AYRI TABLO, niçin kod sabiti DEĞİL: asgari ücret her yıl değişir ve
    K1 ("oranlar VERİDİR") bu kalem için de geçerlidir. `payroll_rates`e
    konsaydı `(yıl, tip)` anahtarı yüzünden DÖRT KOPYA doğar ve dördü birbiriyle
    çelişebilirdi; asgari ücret personel tipine göre değişmez.

    🔴 Yalnız BRÜT saklanır. Net (2026'da 28.075,50) TÜRETİLİR
    (`brüt − SGK işçi − işsizlik işçi`, `income_tax.minimum_wage_tax_base`) —
    ikinci bir gerçek kaynak açılsaydı oran değişince sessizce çelişirdi.
    İstisnanın aylık tutarları (Oca-Haz 4.211,33 · Tem 4.537,75 ·
    Ağu-Ara 5.615,10) da SAKLANMAZ: türev paradır, hesaplanır (MK-2 kanonu).

    Satırı olmayan yıl **fail-closed**tur: dilimli rejimdeki satır `uncomputed`
    kalır, istisnasız tam vergi KESİLMEZ. İstisnayı 0 saymak, asgari ücretliden
    ayda ~4.500 TL fazla kesmek olurdu.
    """

    __tablename__ = "payroll_minimum_wages"
    __table_args__ = (
        CheckConstraint("gross_amount > 0", name="ck_payroll_minimum_wages_gross_positive"),
        UniqueConstraint("year", name="uq_payroll_minimum_wages_year"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    gross_amount: Mapped[Decimal] = mapped_column(
        Numeric(MONEY_PRECISION, MONEY_SCALE), nullable=False
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
