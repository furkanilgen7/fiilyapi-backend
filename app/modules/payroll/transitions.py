"""Bordronun İKİ durum makinesi (spec §6/7, S8) — TEK tablo, tek kapı.

Geçerli geçişler aşağıdaki iki veri yapısındadır; uçlar ve servis kendi
`if status == …` kontrollerini YAZMAZ. Tabloda olmayan her çift **409**'dur —
"tanımlı olanı say, gerisini reddet" yaklaşımıyla yeni bir durum eklendiğinde
varsayılan davranış REDDETMEKTİR. Desen `progress_payments/transitions.py` ve
`procurement/transitions.py`ten gelir; `build_transition_table` İTHAL EDİLMEDİ
çünkü o fonksiyon hakedişin `PaymentAction` dörtlüsüne bağlıdır — bordronun
eylem kümesi (hesapla/düzelt/onayla/öde) farklıdır ve ortaklaştırılsaydı iki iş
akışının şekli tek sabitte düğümlenirdi.

## Neyin tabloda OLMADIĞI da bir karardır

* **`excluded` hiçbir çiftte KAYNAK değildir** (K2): taşeron satırı yapısal bir
  terminaldir. Ödemesi hakediş üzerinden taşerona yapılır ve bordrodan da
  ödenebilseydi çift ödeme mümkün olurdu. "Hesaplanabilir hâle gelince
  `pending` yapalım" yolu bu yüzden tabloda YOKTUR.
* **`paid` de hiçbir çiftte kaynak değildir** (dönemde de satırda da): banka
  çıkışı olmuş bir kaydı geri sarmak, kayıt ile para hareketi arasındaki bağı
  koparırdı.
* Satırda tek GERİ geçiş `approved → pending`tir (spec S5'in düzeltme yolu).
  Dönem `paid` iken onun da kapalı olması SERVİSİN işidir: tablo çiftin
  ŞEKLİNİ bilir, kaydın bağlamını değil.

## T3 kapsamı

T3 yalnız satır tablosunu TÜKETİR (`uncomputed → pending`, K3 override'ı bir
`uncomputed` satırı ödenebilir kıldığında). Dönem tablosu burada durur çünkü
"atlama yok" invariantının TEK bir evi olmalıdır ve dönem uçlarını (onay/ödeme)
açan T4 onu kendi `if`iyle yeniden icat etmemelidir.
"""

from app.core.errors import ConflictError
from app.modules.payroll.models import PayrollLineStatus, PayrollPeriodStatus

#: Dönem zinciri (BY 56/303 + BG durum sütunu): ileri, KOMŞU adımlar.
PERIOD_TRANSITIONS: frozenset[tuple[PayrollPeriodStatus, PayrollPeriodStatus]] = frozenset(
    {
        (PayrollPeriodStatus.draft, PayrollPeriodStatus.pending_approval),
        (PayrollPeriodStatus.pending_approval, PayrollPeriodStatus.approved),
        (PayrollPeriodStatus.approved, PayrollPeriodStatus.paid),
    }
)

#: Satır zinciri. `uncomputed → pending` K3 override'ının çıkışıdır (S4).
LINE_TRANSITIONS: frozenset[tuple[PayrollLineStatus, PayrollLineStatus]] = frozenset(
    {
        (PayrollLineStatus.uncomputed, PayrollLineStatus.pending),
        (PayrollLineStatus.pending, PayrollLineStatus.approved),
        (PayrollLineStatus.approved, PayrollLineStatus.paid),
        (PayrollLineStatus.approved, PayrollLineStatus.pending),
    }
)

PERIOD_TRANSITION_DENIED = "Bordro dönemi bu duruma geçirilemez"
LINE_TRANSITION_DENIED = "Bordro satırı bu duruma geçirilemez"


def assert_period_transition(current: PayrollPeriodStatus, target: PayrollPeriodStatus) -> None:
    """Tabloda olmayan her çift 409 — ADIM ATLAMA dahil (`draft → approved`)."""
    if (current, target) not in PERIOD_TRANSITIONS:
        raise ConflictError(PERIOD_TRANSITION_DENIED)


def assert_line_transition(current: PayrollLineStatus, target: PayrollLineStatus) -> None:
    if (current, target) not in LINE_TRANSITIONS:
        raise ConflictError(LINE_TRANSITION_DENIED)
