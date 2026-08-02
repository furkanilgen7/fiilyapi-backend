"""Ünite satışı şemaları — P8 spec §2/§4, mockup `Form - Daire Satisi` (F) ve
`Satış Yönetimi` (S).

## Gövdede BİLİNÇLİ OLARAK olmayan alanlar

| alan | neden yok |
|---|---|
| `list_price_snapshot` | F84 mockup'ta `readonly` — sunucu ÜNİTEDEN yazar (anlık görüntü) |
| `status` | başlangıç değeri `sale_type`tan türer; geçişler T5'in uçlarıdır |
| `unit_id` (PATCH'te) | ünite değişimi İKİ ünitenin senkronunu ve tekliği birlikte ilgilendirir |
| `sale_type` (PATCH'te) | `status` ile eşleşiktir; rezervasyon→satış geçişi T5 `activate` ucudur |
| maliyet / kâr | KALICI KARAR 3 — `pending_module: "project_costs"` (aşağıda) |
| belgeler / peşinat faturası | F168-207 → `pending_modules` (belge çekirdeği + `invoicing`) |

`min_sale_price` KONTROLÜ HİÇBİR KATMANDA YOKTUR (kalıcı karar 2): ne şemada,
ne serviste, ne DB'de — uyarı bile üretilmez.
"""

import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.customers.models import CustomerType
from app.modules.projects.schemas import MetricPlaceholder
from app.modules.sales.models import (
    DeedCondition,
    PaymentPlanType,
    SaleType,
    UnitSaleStatus,
)

# KDV kümesi ({1, 10, 20}) `units.schemas.VatRate`ten GELİR — F87 ile UE 93 AYNI
# kuraldır (karar 9) ve iki kopya validator zamanla ayrışır.
from app.modules.units.schemas import VatRate

# KALICI KARAR 3 / karar 8 / `invoicing` boşluğu — yer tutucu anahtarları tek yerde.
COST_MODULE = "project_costs"
DOCUMENTS_MODULE = "documents"
INVOICING_MODULE = "invoicing"
PENDING_MODULES = [COST_MODULE, DOCUMENTS_MODULE, INVOICING_MODULE]

_LABEL_SEPARATOR = " · "


def unit_label(block_name: str, unit_no: str) -> str:
    """S159 "A · Daire 12" etiketinin sunucu tarafı: blok adı + ünite numarası.

    Ekran "Daire" sözcüğünü ünite tipinden kendisi ekler; sunucu Türkçe ETİKET
    ÜRETMEZ, yalnız iki veri parçasını birleştirir.
    """
    return f"{block_name}{_LABEL_SEPARATOR}{unit_no}"


class _SaleFormFields(BaseModel):
    """F56-F163'ün ortak gövdesi — `Create` ve `Update` için TEK kopya."""

    discount_amount: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    vat_pct: VatRate = None  # F87 — küme {1, 10, 20} (karar 9)
    advisor_user_id: uuid.UUID | None = None  # F75
    reservation_deposit: Decimal | None = Field(
        default=None, ge=0, max_digits=18, decimal_places=2
    )  # S188
    reservation_due_date: date | None = None  # S188 "15 gün süre"
    deed_condition: DeedCondition | None = None  # F156
    planned_deed_date: date | None = None  # F157
    delivery_date: date | None = None  # F158
    has_condominium_easement: bool = False  # F161
    has_mortgage: bool = False  # F162
    # DOLU = gecikme faizi uygulanır, NULL = uygulanmaz (F163). Ayrı bir
    # `has_late_fee` bayrağı AÇILMAZ — iki alan birbiriyle çelişebilirdi.
    late_fee_monthly_pct: Decimal | None = Field(default=None, ge=0, max_digits=5, decimal_places=2)
    payment_plan_type: PaymentPlanType | None = None  # F99
    down_payment: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    installment_count: int | None = Field(default=None, ge=0)  # F104
    first_installment_date: date | None = None  # F105
    term_interest_pct: Decimal | None = Field(default=None, ge=0, max_digits=5, decimal_places=2)


# Servis, form alanlarını TEK TEK yazmak yerine bu kümeyi kullanır.
SALE_FORM_FIELDS = frozenset(_SaleFormFields.model_fields)


class UnitSaleCreate(_SaleFormFields):
    unit_id: uuid.UUID  # F55
    customer_id: uuid.UUID  # F70-76 (T2 kartoteksinden seçilir)
    sale_type: SaleType  # F56
    sale_price: Decimal = Field(ge=0, max_digits=18, decimal_places=2)  # F86


class UnitSaleUpdate(_SaleFormFields):
    """TÜM alanlar opsiyoneldir; "gönderilmedi" ile "null yapıldı" ayrımı serviste

    `model_dump(exclude_unset=True)` ile çözülür (P1/P2/P4 deseni).

    `has_condominium_easement`/`has_mortgage` burada `None` varsayılanı alır:
    `False` varsayılanı, gönderilmeyen kutucuğu her PATCH'te SESSİZCE temizlerdi.
    """

    sale_price: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    has_condominium_easement: bool | None = None
    has_mortgage: bool | None = None


class UnitSaleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    unit_id: uuid.UUID
    customer_id: uuid.UUID
    sale_type: SaleType
    status: UnitSaleStatus
    # S150-151 kolonlarının kaynağı (ünite ve alıcı ayrı çağrı gerektirmesin).
    block_name: str
    unit_no: str
    unit_label: str
    customer_name: str
    customer_type: CustomerType
    customer_national_id: str | None
    customer_tax_number: str | None
    list_price_snapshot: Decimal | None
    discount_amount: Decimal | None
    sale_price: Decimal
    vat_pct: Decimal | None
    advisor_user_id: uuid.UUID | None
    advisor_name: str | None
    reservation_deposit: Decimal | None
    reservation_due_date: date | None
    deed_condition: DeedCondition | None
    planned_deed_date: date | None
    delivery_date: date | None
    has_condominium_easement: bool
    has_mortgage: bool
    late_fee_monthly_pct: Decimal | None
    payment_plan_type: PaymentPlanType | None
    down_payment: Decimal | None
    installment_count: int | None
    first_installment_date: date | None
    term_interest_pct: Decimal | None
    # --- Tahsilat türevleri (S153-155, S180) — KOLON DEĞİL ---
    paid_amount: Decimal
    remaining_amount: Decimal
    installment_total: int
    installment_paid_count: int
    overdue_installment_count: int
    # --- Yer tutucular (spec §5) ---
    # KALICI KARAR 3: F62 "Maliyet" ve F90 "Bu Satıştan Kâr" sütunu YOKTUR;
    # sahte rakam yerine dürüst boş durum döner. Bir sonraki ajan bunları
    # "eksik alan" sanıp DOLDURMAMALIDIR — kaynak P10 `project_costs`tur.
    unit_cost: MetricPlaceholder = Field(
        default_factory=lambda: MetricPlaceholder(pending_module=COST_MODULE)
    )
    sale_profit: MetricPlaceholder = Field(
        default_factory=lambda: MetricPlaceholder(pending_module=COST_MODULE)
    )
    # F168-202 satış belgeleri (belge çekirdeği, karar 8) + F206-207 peşinat
    # faturası (`invoicing` modülünün kodu henüz yazılmadı) — `contracts`
    # şemalarındaki `pending_modules` deseninin aynısı.
    pending_modules: list[str] = Field(default_factory=lambda: list(PENDING_MODULES))


class UnitSaleTotals(BaseModel):
    """S205-215 TOPLAM satırı — satır türevleriyle AYNI kaynaktan toplanır."""

    count: int
    sale_price_total: Decimal
    paid_total: Decimal
    remaining_total: Decimal


class UnitSaleListResponse(BaseModel):
    totals: UnitSaleTotals
    items: list[UnitSaleResponse]
