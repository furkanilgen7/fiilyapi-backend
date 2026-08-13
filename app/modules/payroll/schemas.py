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
