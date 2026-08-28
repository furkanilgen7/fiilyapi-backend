"""Bordro servisi — İK-3 T2 (`compute` akışı) + T3 (dönem/satır uçları).

Hesabın kendisi `compute.py`dedir (saf, DB'siz), toplama `summary.py`de, geçiş
tablosu `transitions.py`de. Bu dosya AKIŞTIR: kimin satırı açılır, gün nereden
okunur, hangi satır KORUNUR, kapı ne zaman kapalıdır. `DomainError` türevleri
`app/core/exception_handlers.py`te HTTP'ye çevrilir — router `try/except`
YAZMAZ.

## Neden gün sayısını burada saymıyoruz da `worked_day_clause`i import ediyoruz?

Adam-güne hangi hücrenin sayıldığı PUANTAJIN kanonudur (`timesheet/matrix.py`) ve
mockup'tan gelir (E5 236: çalışılan gün SAATLİDİR · E5 262/283: izin ve geçici
görev rozetleri saat taşımaz, sayılmaz). Burada yeniden tanımlansaydı bordronun günü ile puantaj
ekranının adam-günü zamanla ayrışır ve kullanıcı iki ekranda iki sayı görürdü.

## EŞİK = KİLİT (WORKFLOW §4, İK-2 dersi)

Serileştirme **dönem satırındadır** ve kilit DURUM DENETİMİNDEN ÖNCE alınır:
iki eşzamanlı `compute` (ya da `compute` + dönem onayı) sırayla koşar. Kilit
denetimden sonra alınsaydı iki istek de "dönem taslak" görüp aynı satırları
iki kez yazmaya çalışır, UQ ihlaliyle biri 500'e düşerdi.

## Bilinçli sınır

Personel bordro kapsamından çıkarsa (pasifleşme/taslağa dönme) MEVCUT satırı
SİLİNMEZ: silinmiş bir satır, o ay gerçekten hesaplanmış bir tutarın izini yok
ederdi. Satır olduğu gibi durur; kapsam dışına çıkan kişiye YENİ satır açılmaz.

## 🔴 Paket yapisi (TB-PAYROLL) — davranis DEGISMEDI

Dosya 1349 satirdaydi (tavan 800) ve bolumun EN KOTU ihlaliydi. Dosyanin KENDI
bolum isaretlerine (T2 / IK3-GV / T3 / T4 / T5) gore sekize bolundu; hicbir uc,
SQL, yanit govdesi, hata metni ya da kilit sirasi degismedi. Dis imza KORUNDU:
eski `service.py`nin TUM modul duzeyi adlari (ozel `_` adlar ve ITHAL EDILMIS
adlar DAHIL) buradan aynen okunabilir.

Katmanlar (ok yonu = bagimlilik, cember YOK):

    core  <-  tax_context  <-  compute_flow
      ^            ^
      +-- periods  +-- lines
      +-- approvals
      +-- sgk_notification
      +-- rates

* `core.py`             — kilit noktalari (EŞİK = KİLİT), oran okuma, satir yaniti
* `tax_context.py`      — IK3-GV: tarife / asgari ucret / kumulatif matrah okumasi
* `compute_flow.py`     — T2 `compute` akisi (kimin satiri acilir, ne KORUNUR)
* `periods.py`          — T3 donem ucları (acma, takvim, BY detayi, BG listesi)
* `lines.py`            — T3 satir ucu (K3 brut override + S3 bolusum)
* `approvals.py`        — T4 onay + odeme (🔴 para cikisinin kapisi)
* `sgk_notification.py` — T5 SGK ozeti + damgasi
* `rates.py`            — T5 oran seti ucları + yil korkulugu

### Neden ITHAL EDILMIS adlar da yeniden ihrac ediliyor

Eski `service.py`nin ad uzayinda `uuid`, `Decimal`, `messages`, `compute` gibi
adlar da GORUNURDU (`service.compute` yazan bir cagiran calisirdi). Bugun
hicbir cagirani yok — ama "bugun yok" ile "sozlesme degil" ayni sey degildir ve
bolme dilimi davranis DEGISTIRMEMELIDIR. Kume
`tests/modules/payroll/tbpayroll_servis_yuzeyi.txt` anlik goruntusunde
DONDURULMUSTUR; bu adlari dusurmek isteyen sonraki okuyucu once o dosyayi
bilincli olarak guncellemek zorundadir — kaza ile dusuremez.

`X as X` bicimi bilinclidir: acik yeniden-ihrac, `noqa` olmadan F401'i
susturur ve `__all__`e girmeyen ozel adlari da kapsar (`personnel/service`
emsali).
"""

import calendar as calendar
import uuid as uuid
from datetime import UTC as UTC
from datetime import date as date
from datetime import datetime as datetime
from decimal import Decimal as Decimal

from sqlalchemy import func as func
from sqlalchemy import select as select
from sqlalchemy.ext.asyncio import AsyncSession as AsyncSession

from app.core.errors import ConflictError as ConflictError
from app.core.errors import DuplicateError as DuplicateError
from app.core.errors import NotFoundError as NotFoundError
from app.core.errors import PayrollValidationError as PayrollValidationError
from app.modules.audit import messages as messages
from app.modules.payroll import compute as compute
from app.modules.payroll import guards as guards
from app.modules.payroll import income_tax as income_tax
from app.modules.payroll import schemas as schemas
from app.modules.payroll import sgk as sgk
from app.modules.payroll import summary as summary
from app.modules.payroll import transitions as transitions
from app.modules.payroll.models import IncomeKind as IncomeKind
from app.modules.payroll.models import PayrollLine as PayrollLine
from app.modules.payroll.models import PayrollLineStatus as PayrollLineStatus
from app.modules.payroll.models import PayrollMinimumWage as PayrollMinimumWage
from app.modules.payroll.models import PayrollPeriod as PayrollPeriod
from app.modules.payroll.models import PayrollPeriodStatus as PayrollPeriodStatus
from app.modules.payroll.models import PayrollRate as PayrollRate
from app.modules.payroll.models import PayrollTaxBracket as PayrollTaxBracket
from app.modules.payroll.schemas import PayrollComputeResult as PayrollComputeResult
from app.modules.payroll.service.approvals import (
    _assert_line_decidable as _assert_line_decidable,
)
from app.modules.payroll.service.approvals import (
    approve_line as approve_line,
)
from app.modules.payroll.service.approvals import (
    approve_period as approve_period,
)
from app.modules.payroll.service.approvals import (
    pay_period as pay_period,
)
from app.modules.payroll.service.approvals import (
    reject_line as reject_line,
)
from app.modules.payroll.service.compute_flow import (
    _apply as _apply,
)
from app.modules.payroll.service.compute_flow import (
    _existing_lines as _existing_lines,
)
from app.modules.payroll.service.compute_flow import (
    _man_day_counts as _man_day_counts,
)
from app.modules.payroll.service.compute_flow import (
    _payroll_personnel as _payroll_personnel,
)
from app.modules.payroll.service.compute_flow import (
    _personnel_with_timesheet_records as _personnel_with_timesheet_records,
)
from app.modules.payroll.service.compute_flow import (
    _promote_period_after_compute as _promote_period_after_compute,
)
from app.modules.payroll.service.compute_flow import (
    compute_period as compute_period,
)
from app.modules.payroll.service.core import (
    LOCKED_LINE_STATUSES as LOCKED_LINE_STATUSES,
)
from app.modules.payroll.service.core import (
    LOCKED_PERIOD_STATUSES as LOCKED_PERIOD_STATUSES,
)
from app.modules.payroll.service.core import (
    PERMISSION_MODULE as PERMISSION_MODULE,
)
from app.modules.payroll.service.core import (
    _full_name as _full_name,
)
from app.modules.payroll.service.core import (
    _line_response as _line_response,
)
from app.modules.payroll.service.core import (
    _lines_with_names as _lines_with_names,
)
from app.modules.payroll.service.core import (
    _lock_period as _lock_period,
)
from app.modules.payroll.service.core import (
    _locked_line as _locked_line,
)
from app.modules.payroll.service.core import (
    _locked_period_lines as _locked_period_lines,
)
from app.modules.payroll.service.core import (
    get_period as get_period,
)
from app.modules.payroll.service.core import (
    month_bounds as month_bounds,
)
from app.modules.payroll.service.core import (
    rates_by_source as rates_by_source,
)
from app.modules.payroll.service.lines import (
    _apply_gross_override as _apply_gross_override,
)
from app.modules.payroll.service.lines import (
    _apply_split as _apply_split,
)
from app.modules.payroll.service.lines import (
    _assert_line_editable as _assert_line_editable,
)
from app.modules.payroll.service.lines import (
    update_line as update_line,
)
from app.modules.payroll.service.periods import (
    SCHEDULE_LOCKED_PERIOD_STATUSES as SCHEDULE_LOCKED_PERIOD_STATUSES,
)
from app.modules.payroll.service.periods import (
    SECTION_ORDER as SECTION_ORDER,
)
from app.modules.payroll.service.periods import (
    create_period as create_period,
)
from app.modules.payroll.service.periods import (
    get_period_detail as get_period_detail,
)
from app.modules.payroll.service.periods import (
    list_periods as list_periods,
)
from app.modules.payroll.service.periods import (
    update_period as update_period,
)
from app.modules.payroll.service.rates import (
    list_rates as list_rates,
)
from app.modules.payroll.service.rates import (
    upsert_rate as upsert_rate,
)
from app.modules.payroll.service.rates import (
    year_has_locked_period as year_has_locked_period,
)
from app.modules.payroll.service.sgk_notification import (
    sgk_summary as sgk_summary,
)
from app.modules.payroll.service.sgk_notification import (
    submit_sgk as submit_sgk,
)
from app.modules.payroll.service.tax_context import (
    _minimum_wage_gross as _minimum_wage_gross,
)
from app.modules.payroll.service.tax_context import (
    _missing_prior_period_count as _missing_prior_period_count,
)
from app.modules.payroll.service.tax_context import (
    _opening_tax_base as _opening_tax_base,
)
from app.modules.payroll.service.tax_context import (
    _prior_cumulative_bases as _prior_cumulative_bases,
)
from app.modules.payroll.service.tax_context import (
    _tax_brackets as _tax_brackets,
)
from app.modules.payroll.service.tax_context import (
    _tax_context_for_line as _tax_context_for_line,
)
from app.modules.personnel.models import Personnel as Personnel
from app.modules.site_diary.models import WorkerSource as WorkerSource
from app.modules.timesheet.matrix import worked_day_clause as worked_day_clause
from app.modules.timesheet.models import TimesheetEntry as TimesheetEntry
