"""Bordro şemaları — `compute` özeti (T2) + dönem/satır sözleşmeleri (T3).

## `extra="forbid"` bu modülde ÇEKİRDEK KURALDIR

İK-2'nin `days` emsali: istemci SUNUCU HESABINI gönderemez. Bordroda bu kural
para sınıfıdır — `net_amount`, `deduction_amount`, `status` ya da
`is_overridden` gövdeden kabul edilseydi bir istemci kendi hesabını yazdırabilir
ve S3/S5 kapıları anlamsızlaşırdı. Yazma şemaları **yalnız** kullanıcının
gerçekten girdiği üç alanı taşır: brüt (K3 override) + banka/elden bölüşümü.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.payroll.models import (
    MONEY_PRECISION,
    MONEY_SCALE,
    RATE_PRECISION,
    RATE_SCALE,
    PayrollLineStatus,
    PayrollPeriodStatus,
)
from app.modules.site_diary.models import WorkerSource

#: Dönem yılı için akla yatkın sınırlar. Serbest bırakılsaydı bir yazım hatası
#: (20226) UQ'yu kirletir ve geri alınamayan bir dönem satırı yaratırdı.
MIN_PAYROLL_YEAR = 2000
MAX_PAYROLL_YEAR = 2100

#: Para alanlarının şema karşılığı — `Numeric(12,2)` ile AYNI ölçek (models.py).
#: `Annotated` tipidir, paylaşılan bir `Field` NESNESİ değil: tek bir `FieldInfo`
#: üç alana birden verilseydi Pydantic onu paylaşılan durum olarak taşırdı.
Money = Annotated[Decimal, Field(ge=0, max_digits=MONEY_PRECISION, decimal_places=MONEY_SCALE)]


class PayrollComputeResult(BaseModel):
    """`POST /payroll/periods/{id}/compute` özeti — **sessiz atlama YOKTUR**.

    Atlanan satırlar sayıyla raporlanır (WORKFLOW §3): kullanıcı "hesapladım"
    yanıtını alıp elle düzelttiği satırın niçin değişmediğini merak etmemelidir.
    İki atlama sebebi AYRI sayılır çünkü anlamları farklıdır — biri kullanıcının
    kendi düzeltmesidir (K3/S6), diğeri ödeme izidir (S5).
    """

    created: int = Field(description="Yeni açılan satır sayısı")
    updated: int = Field(description="Yeniden hesaplanıp güncellenen satır sayısı")
    skipped_overridden: int = Field(
        description="Elle düzeltildiği için KORUNAN satır sayısı (S6)",
    )
    skipped_approved: int = Field(
        description="Onaylı/ödenmiş olduğu için KORUNAN satır sayısı (S5)",
    )


class PayrollPeriodApproveResult(BaseModel):
    """`POST /payroll/periods/{id}/approve` — BY 303 "Tümünü Onayla".

    🔴 **Atlananlar SEBEBE GÖRE ayrı sayılır** (WORKFLOW §3): "3 satır onaylandı"
    tek başına, iki satırın niçin dışarıda kaldığını gizlerdi ve kullanıcı eksik
    ödemeyi banka ekstresinden öğrenirdi. Sebepler farklı İŞ gerektirir:

    * `skipped_excluded` → **K2**: taşeron satırı; ödemesi hakediş modülünün
      (TH) işidir, burada yapılacak bir şey YOKTUR;
    * `skipped_uncomputed` → **S4**: ücret verisi eksik; kullanıcı ya personelin
      ücretini tanımlar ya da brütü elle girer;
    * `skipped_already_approved` → satır zaten onaylı/ödenmiş; bilgi amaçlıdır.

    `period_status` DÖNÜŞTE VERİLİR çünkü uç dönemi TEK ADIM ilerletir
    (`draft → pending_approval → approved`) ve ekran hangi adımda olduğunu
    yanıttan öğrenmelidir — ikinci bir `GET` ile tahmin etmemelidir.
    """

    period_status: PayrollPeriodStatus
    approved: int = Field(description="Onaylanan satır sayısı")
    skipped_uncomputed: int = Field(description="Brütü hesaplanamadığı için atlanan satır (S4)")
    skipped_excluded: int = Field(description="Taşeron olduğu için atlanan satır (K2)")
    skipped_already_approved: int = Field(description="Zaten onaylı/ödenmiş satır")


class PayrollPeriodPayResult(BaseModel):
    """`POST /payroll/periods/{id}/pay` — ödendi damgası (spec §5).

    🔴 `paid_net_total` ÖDENEN satırların netidir; **taşeron satırı bu toplama
    GİRMEZ** (K2). Girseydi banka talimatı taşeron işçisinin netini de taşır ve
    aynı emek hem hakedişten hem bordrodan ödenirdi.

    `skipped_unapproved` sessiz atlamayı kapatır: onayı geri alınmış bir satır
    ödenmez ve bu ekranda GÖRÜNÜR.
    """

    period_status: PayrollPeriodStatus
    paid_at: datetime
    paid: int = Field(description="Ödendi damgası basılan satır sayısı")
    paid_net_total: Decimal = Field(description="Ödenen satırların net toplamı")
    skipped_unapproved: int = Field(description="Onaylanmadığı için ödenmeyen satır")
    skipped_uncomputed: int = Field(description="Brütü hesaplanamadığı için ödenmeyen satır (S4)")
    skipped_excluded: int = Field(description="Taşeron olduğu için ödenmeyen satır (K2)")


# --- Dönem yazma -----------------------------------------------------------


class PayrollPeriodCreate(BaseModel):
    """`POST /payroll/periods` gövdesi — ay AÇAR, doldurmaz.

    `status` gövdeden ALINMAZ: yeni dönem HER ZAMAN `draft`tır ve ileri
    durumlara yalnız geçiş tablosundan (`transitions.py`, S8) gidilir. Alan
    açılsaydı istemci bir ayı doğrudan `paid` açıp onay zincirini atlardı.
    """

    model_config = ConfigDict(extra="forbid")

    year: int = Field(ge=MIN_PAYROLL_YEAR, le=MAX_PAYROLL_YEAR)
    month: int = Field(ge=1, le=12)
    #: BY 63 "Son ödeme" — bilgi alanıdır, geçiş kapısı DEĞİLDİR (models.py).
    payment_due_date: date | None = None


class PayrollPeriodUpdate(BaseModel):
    """`PATCH /payroll/periods/{id}` gövdesi — YALNIZ ödeme tarihi (T4b).

    Dönemin başka hiçbir alanı buradan değişmez: `year`/`month` kimliktir (UQ),
    `status` geçiş tablosunun (S8) işidir, damgalar (`approved_at`/`paid_at`/
    `sgk_submitted_at`) kendi uçlarında basılır. Alan eklemek bu uçtan onay
    zincirini atlamayı mümkün kılardı.

    🔴 **Boş gövde 422'dir ve bu `null` göndermekten AYRIDIR.** Tek alanlı ve
    nullable bir şemada `{}` ile `{"payment_due_date": null}` varsayılan
    değerle ayırt edilemez; ayrım `model_fields_set` ile korunur. İkisi tek
    davranışa indirgenseydi ya boş bir istek tarihi sessizce SİLERDİ ya da
    yanlış girilmiş bir tarihi temizlemek imkânsız olurdu.
    """

    model_config = ConfigDict(extra="forbid")

    #: BY 63 "Son ödeme". **Sunucu tarih ÜRETMEZ, varsayılan KOYMAZ ve dönemin
    #: yıl/ayıyla tutarlılığını DENETLEMEZ:** mockup bu alanın formunu çizmez,
    #: BG'nin üç dönemde de ayın 20'sini göstermesi bir iş kuralı DEĞİLDİR
    #: (WORKFLOW §3, uydurma yasağı) ve ödeme gerçek hayatta sonraki aya sarkar.
    payment_due_date: date | None = None

    @model_validator(mode="after")
    def _en_az_bir_alan(self) -> "PayrollPeriodUpdate":
        if "payment_due_date" not in self.model_fields_set:
            raise ValueError("Güncellenecek en az bir alan gönderilmelidir")
        return self


# --- Satır yazma -----------------------------------------------------------


class PayrollLineUpdate(BaseModel):
    """`PATCH /payroll/lines/{id}` gövdesi — kullanıcının GİRDİĞİ üç alan.

    * `gross_amount` → K3 brüt override'ı; kesinti ve net bundan YENİDEN türer
      (`compute.deduction_and_net`), gövdeden alınmaz.
    * `bank_amount` + `cash_amount` → BY 142-147'deki iki ayrı `input`.
      **İkisi birlikte gönderilir**: yalnız biri gönderilip öteki sunucuya
      tamamlatılsaydı S3 bir DOĞRULAMA değil bir HESAP olurdu ve "gerisi elden
      mi, yoksa yanlış mı yazdım?" ayrımı kaybolurdu.

    Boş gövde reddedilir: hiçbir alan göndermemek bir işlem değildir ve 200
    dönmek kullanıcıya "kaydettim" demek olurdu.
    """

    model_config = ConfigDict(extra="forbid")

    gross_amount: Money | None = None
    bank_amount: Money | None = None
    cash_amount: Money | None = None

    @model_validator(mode="after")
    def _en_az_bir_alan_ve_bolusum_butun(self) -> "PayrollLineUpdate":
        if self.gross_amount is None and self.bank_amount is None and self.cash_amount is None:
            raise ValueError("Güncellenecek en az bir alan gönderilmelidir")
        if (self.bank_amount is None) != (self.cash_amount is None):
            raise ValueError("Banka ve elden tutarları BİRLİKTE gönderilmelidir")
        return self


# --- Okuma -----------------------------------------------------------------


class PayrollLineResponse(BaseModel):
    """BY tablosunun bir satırı (110-118 başlıkları + 133-148 gövdesi).

    `personnel_name` satıra GÖMÜLÜR (BY 137): ekran her satır için ikinci bir
    personel isteği atmak zorunda kalmamalıdır. `personnel_source` satırın
    SNAPSHOT'ıdır (models.py) — canlı personel tipi değil.

    Beş para alanı da `null` OLABİLİR (S4): "0 ödenecek" ile "hesaplanamadı"
    ayırt edilebilir kalmalıdır.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    personnel_id: uuid.UUID
    personnel_name: str
    personnel_source: WorkerSource
    days: int | None
    gross_amount: Decimal | None
    deduction_amount: Decimal | None
    net_amount: Decimal | None
    bank_amount: Decimal | None
    cash_amount: Decimal | None
    status: PayrollLineStatus
    #: K2 — satırın niçin ödemeye girmediği YAZILI (sessiz atlama yok).
    excluded_reason: str | None
    #: K3 izi — ekran "elle düzeltildi" rozetini bundan basar.
    is_overridden: bool
    overridden_at: datetime | None
    previous_gross_amount: Decimal | None


class PayrollSectionResponse(BaseModel):
    """BY 124/172/240/268 bölüm başlıkları — tip bazında gruplama.

    Bölüm ETİKETİ ("ŞİRKET KADROSU — SGK 4a") sunucudan DÖNMEZ: o bir ekran
    metnidir ve mockup'ta rejim adıyla birlikte yazılır. Sunucu tipi ve sayıyı
    verir; sayı BURADAN gelir çünkü başlık "· 12 çalışan" basar ve ekranın
    kendi `lines.length`ini sayması sayfalanmış bir listede yanlış olurdu.
    """

    personnel_source: WorkerSource
    line_count: int
    lines: list[PayrollLineResponse]


class PayrollSummaryResponse(BaseModel):
    """BY 69-93'ün dört kartı + görünür sayaçlar (`summary.PeriodSummary` aynası).

    🔴 İki taban ayrıdır: ilk üç kart ÖDEME tabanını (`excluded`/`uncomputed`
    hariç), dördüncü kart MALİYET tabanını (`excluded` DAHİL) gösterir.
    Ayrıntı `summary.py` docstring'inde.
    """

    model_config = ConfigDict(from_attributes=True)

    line_count: int
    net_total: Decimal
    net_personnel_count: int
    bank_total: Decimal
    bank_personnel_count: int
    #: Ödeme tabanı boşken **`null`** — 0 basmak "hepsi banka" yalanı olurdu.
    bank_pct: Decimal | None
    cash_total: Decimal
    cash_personnel_count: int
    cash_pct: Decimal | None
    gross_total: Decimal
    sgk_employer_total: Decimal
    #: brüt + (SGK işveren + işsizlik işveren + kısa çalışma) — spec §7.
    total_employer_cost: Decimal
    uncomputed_count: int
    excluded_count: int
    unknown_cost_count: int


class PayrollPeriodDetailResponse(BaseModel):
    """BY ekranının tamamı: dönem künyesi + dört kart + tip bazında satırlar."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    year: int
    month: int
    status: PayrollPeriodStatus
    payment_due_date: date | None
    approved_at: datetime | None
    paid_at: datetime | None
    sgk_submitted_at: datetime | None
    summary: PayrollSummaryResponse
    sections: list[PayrollSectionResponse]


class PayrollPeriodListRow(BaseModel):
    """BG tablosunun bir satırı (44-47 başlıkları).

    `personnel_count` dönemin TÜM satırlarını sayar (BY tfoot 48 = 12+29+5+2);
    BY 71'in kart sayısı ise ÖDENEBİLİR satırlardır. İkisi aynı değildir
    (`summary.py` gerekçesi) ve tek alana indirgenirse biri yalan söyler.
    """

    id: uuid.UUID
    year: int
    month: int
    status: PayrollPeriodStatus
    payment_due_date: date | None
    paid_at: datetime | None
    personnel_count: int
    gross_total: Decimal
    #: BG 47 — YALNIZ SGK işveren payı; toplam maliyetin üç kaleminden biri.
    sgk_employer_total: Decimal
    net_total: Decimal
    #: BG 49 — `total_employer_cost` ile AYNI kaynaktan (`compute`), kopya değil.
    total_cost: Decimal


class PayrollPeriodListResponse(BaseModel):
    items: list[PayrollPeriodListRow]
    total: int
    limit: int
    offset: int


# --- T5: SGK bildirimi (SGK 55-95) -----------------------------------------


class PayrollSgkSummaryResponse(BaseModel):
    """SGK 55-95 — KPI dörtlüsü + işçi payları + işveren payları + ödenecek prim.

    🔴 **Mockup TUTARLARI beklenti değildir** (spec S1): SGK mockup'ı kendi
    aritmetiğine uymuyor (SGK 82 işveren toplamını 148.800 yazar, kendi
    oranlarından 174.652 çıkar). Açık ORAN kazanır ve buradaki sayılar
    mockup'takinden BÜYÜKTÜR — gerekçe `sgk.py` docstring'inde.

    🔴 **SGK 96-118 (çalışan listesi + "SGK No") YOKTUR:** spec §5 bu ucu 55-95
    ile sınırlar ve `sgk_no` diye bir kolon İK-1'de yoktur (uydurulmaz).

    İki sayaç `null` sayı ÜRETMEDEN eksiği görünür kılar (WORKFLOW §3):
    `uncomputed_count` ücreti tanımsız satırları, `unknown_rate_count` oran seti
    olmayan tipleri sayar; ikisi de matraha GİRMEZ (fail-closed).
    """

    model_config = ConfigDict(from_attributes=True)

    period_id: uuid.UUID
    year: int
    month: int
    #: SGK 44-47 banner'ı: damga basılmışsa bildirim "gönderildi" sayılır.
    sgk_submitted_at: datetime | None
    #: --- KPI dörtlüsü (SGK 55-58) ---
    declared_personnel_count: int = Field(description="SGK 55 — bildirilen çalışan (4a + 4b)")
    sgk_base_total: Decimal = Field(description="SGK 56 — SGK matrahı")
    sgk_premium_total: Decimal = Field(description="SGK 57 — SGK primi (işçi + işveren)")
    unemployment_total: Decimal = Field(description="SGK 58 — işsizlik sigortası (işçi + işveren)")
    #: --- işçi payları (SGK 69-73) ---
    sgk_employee_total: Decimal
    unemployment_employee_total: Decimal
    income_tax_total: Decimal
    stamp_tax_total: Decimal
    employee_deduction_total: Decimal = Field(description="SGK 73 — toplam işçi kesintisi")
    #: --- işveren payları (SGK 79-82) ---
    sgk_employer_total: Decimal
    unemployment_employer_total: Decimal
    short_work_total: Decimal
    #: SGK 82 — **ÜÇ kalemin tamamı** (spec §7); brüt DAHİL DEĞİLDİR (o BY 90'ın
    #: `total_employer_cost`udur, ayrı bir kavramdır).
    employer_burden_total: Decimal
    #: SGK 86-91 — etiket AÇIKÇA "İşçi + İşveren SGK + İşsizlik" (SGK 89): gelir
    #: vergisi/damga (vergi dairesine gider) ve kısa çalışma bu toplamda YOKTUR.
    sgk_payable_total: Decimal
    uncomputed_count: int
    unknown_rate_count: int


class PayrollSgkSubmitResult(BaseModel):
    """`POST /payroll/periods/{id}/sgk-submit` — YALNIZ damga (spec §1).

    Dış sistem entegrasyonu YOKTUR: ne HTTP isteği, ne kuyruk, ne dosya
    gönderimi. Yanıt bu yüzden bir "gönderim sonucu" değil, damganın ZAMANIDIR.
    """

    period_id: uuid.UUID
    sgk_submitted_at: datetime


# --- T5: oran tablosu (K1) -------------------------------------------------

#: Oran alanlarının şema karşılığı — `Numeric(6,3)` ile AYNI ölçek (models.py).
#: **Üst sınır %100:** bir kalem brütün tamamından fazlasını kesemez. Sınırsız
#: bırakılsaydı bir yazım hatası (%2000) neti eksiye düşürür ve
#: `ck_payroll_lines_net_positive` ihlaliyle `compute` 500'e patlardı —
#: kullanıcı hatası sunucu hatası gibi görünürdü.
Rate = Annotated[Decimal, Field(ge=0, le=100, max_digits=RATE_PRECISION, decimal_places=RATE_SCALE)]

#: `compute.EMPLOYEE_RATE_FIELDS`in şema tarafındaki aynası: neti belirleyen
#: kalemler. İşveren kalemleri KASTEN dışarıdadır — onlar maliyettir, kesinti
#: değil (spec §7) ve toplamları %100'ü aşsa bile net eksiye düşmez.
_EMPLOYEE_RATE_FIELDS = (
    "sgk_employee_pct",
    "unemployment_employee_pct",
    "income_tax_pct",
    "stamp_tax_pct",
)

MAX_TOTAL_PCT = Decimal("100")


class PayrollRateUpdate(BaseModel):
    """`PUT /payroll/rates/{year}/{source}` gövdesi — **TAM SET** (K1).

    Yedi oranın hepsi ZORUNLUDUR: kısmi gönderim kabul edilseydi eksik alan
    sessizce 0 olur ve "kesinti yok" yalanı üretilirdi. PUT bir DEĞİŞTİRMEDİR,
    yama değildir; anahtar (`year`, `source`) yoldadır, gövdede TEKRARLANMAZ —
    ikisi çelişirse hangisinin kazandığı sorusu doğardı.
    """

    model_config = ConfigDict(extra="forbid")

    sgk_employee_pct: Rate
    unemployment_employee_pct: Rate
    income_tax_pct: Rate
    stamp_tax_pct: Rate
    sgk_employer_pct: Rate
    unemployment_employer_pct: Rate
    short_work_pct: Rate
    #: Eski yılın seti SİLİNMEZ, pasifleştirilir (models.py): geçmiş bordronun
    #: hesabı okunabilir kalmalıdır.
    is_active: bool = True

    @model_validator(mode="after")
    def _isci_paylari_yuzu_asamaz(self) -> "PayrollRateUpdate":
        """🔴 Dört İŞÇİ kaleminin TOPLAMI da %100'ü aşamaz.

        Tek tek geçerli (her biri ≤ %100) ama toplamı %101 olan bir set, brütü
        tanımlı HER personelin netini negatife çevirir ve DB CHECK'ine çarpardı.
        Sınır kalem başına değil TOPLAM üzerinde de durmalıdır.
        """
        toplam = sum(getattr(self, alan) for alan in _EMPLOYEE_RATE_FIELDS)
        if toplam > MAX_TOTAL_PCT:
            raise ValueError(
                f"İşçi kesinti oranlarının toplamı %100'ü aşamaz (gönderilen: %{toplam})"
            )
        return self


class PayrollRateResponse(BaseModel):
    """Bir oran seti — `(yıl, personel tipi)` anahtarlı (S2)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    year: int
    personnel_source: WorkerSource
    sgk_employee_pct: Decimal
    unemployment_employee_pct: Decimal
    income_tax_pct: Decimal
    stamp_tax_pct: Decimal
    sgk_employer_pct: Decimal
    unemployment_employer_pct: Decimal
    short_work_pct: Decimal
    is_active: bool


class PayrollRateListResponse(BaseModel):
    """Oran setleri — **sayfalama YOKTUR ve bu bilinçlidir.**

    Tablo yılda en çok DÖRT satır büyür (spec §4'ün dört bordro tipi); TB3
    sayfalama korkuluğu sınırsız büyüyen listeler içindir. `limit` eklenseydi
    ekran oran matrisini sayfalamak zorunda kalır ve kullanıcı bir yılın
    setini parça parça görürdü.
    """

    items: list[PayrollRateResponse]
    total: int
