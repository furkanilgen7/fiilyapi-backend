"""Bordro özetleri — BY 69-93'ün dört kartı ve BG 44-49'un sütunları (İK-3 T3).

Saf ve yan etkisizdir (`compute.py`nin kardeşi): DB'ye dokunmaz, satır listesi
ve oran sözlüğü alır, sayı üretir. Aritmetiğin kendisi yine `compute.py`dedir —
burada olan yalnız TOPLAMADIR ve hangi satırın hangi toplama gireceği kararıdır.

## 🔴 İKİ AYRI TABAN

Bu modülün var oluş sebebi budur ve tek bir küme sanılırsa para yanlış çıkar:

| Taban | Kimler | Nerede |
|---|---|---|
| **ÖDEME** | yalnız `pending`/`approved`/`paid` satırlar | BY 69-87, ilk üç kart |
| **MALİYET** | brütü hesaplanmış TÜM satırlar (`excluded` DAHİL) | BY 90-92 · BG 46-49 |

* **K2 (spec §2, §6/2):** taşeron satırı `excluded`tır — `net`i ödeme
  kartlarına **girmez** (ödemesi hakediş üzerinden taşerona yapılır, çift ödeme
  yapısal olarak imkânsızdır) ama işverenin **maliyetine girer** (BY 186-189
  satırı tabloda görünür ve tutarları basılıdır).
* **S4 (spec §6/3):** `uncomputed` satırın brütü `null`dur; hiçbir toplama
  girmez ve **AYRI SAYILIR** (`uncomputed_count`). İK-2'nin
  `unknown_entitlement_personnel` emsali: sessiz atlama YOKTUR (WORKFLOW §3).
* Oran seti sonradan pasifleşirse hesaplanmış bir brütün işveren yükü
  **BİLİNMEZ** olur: satır maliyet toplamından düşer ve `unknown_cost_count`ta
  görünür. 0 saymak maliyeti sistematik olarak küçük gösterirdi (fail-closed,
  SA dilimindeki NULL-EŞİK kanonu).

## Sayaçlar neden ayrı ayrı duruyor

`net_personnel_count` (BY 71 "48 çalışan") ÖDENEBİLİR satırları sayar;
BG 45'in "Çalışan" sütunu ise dönemin TÜM satırlarını (`line_count`) sayar —
BY tfoot'taki 48 = 12 + 29 + 5 + 2, yani taşeron da dahildir. İkisi aynı sayı
DEĞİLDİR ve tek alana indirgenirse ya kart ya liste yalan söyler.
"""

from dataclasses import dataclass
from decimal import Decimal

from app.modules.payroll import compute
from app.modules.payroll.models import PayrollLine, PayrollLineStatus, PayrollRate
from app.modules.site_diary.models import WorkerSource

#: Ödeme tabanına giren satır durumları. `uncomputed` (S4) ve `excluded` (K2)
#: KASTEN dışarıdadır — ikisi de "ödenecek bir tutar" ifade etmez.
PAYABLE_LINE_STATUSES = frozenset(
    {PayrollLineStatus.pending, PayrollLineStatus.approved, PayrollLineStatus.paid}
)

ZERO_MONEY = Decimal("0.00")

#: Yüzdelerin ölçeği — BY 79/87 tek ondalık basıyor ("%71,5").
PCT_QUANTUM = Decimal("0.1")


@dataclass(frozen=True)
class PeriodSummary:
    """BY dört kartı + BG sütunlarının TEK kaynağı. DONMUŞTUR."""

    line_count: int
    #: --- ödeme tabanı (BY 69-87) ---
    net_total: Decimal
    net_personnel_count: int
    bank_total: Decimal
    bank_personnel_count: int
    bank_pct: Decimal | None
    cash_total: Decimal
    cash_personnel_count: int
    cash_pct: Decimal | None
    #: --- maliyet tabanı (BY 90-92 · BG 46-49) ---
    gross_total: Decimal
    sgk_employer_total: Decimal
    total_employer_cost: Decimal
    #: --- görünür sayaçlar: sessiz atlama yok (WORKFLOW §3) ---
    uncomputed_count: int
    excluded_count: int
    unknown_cost_count: int


def _pct(part: Decimal, whole: Decimal) -> Decimal | None:
    """Payın bütündeki oranı — bütün sıfırsa **`None`**.

    0 dönmek "hiç banka ödemesi yok" derdi; oysa ödenecek hiçbir şey yoktur ve
    yüzde TANIMSIZDIR. Ekran "—" basar.
    """
    if whole == 0:
        return None
    return (part / whole * Decimal("100")).quantize(PCT_QUANTUM)


def build_period_summary(
    lines: list[PayrollLine], rates: dict[WorkerSource, PayrollRate]
) -> PeriodSummary:
    """Dönemin satırlarından dört kartı ve BG sütunlarını üretir.

    `rates` DÖNEMİN YILINA ait aktif oran setidir (`service.rates_by_source`);
    bugünün yılı DEĞİLDİR (S2) — geçmiş bir dönemin maliyeti bu yılın oranıyla
    yeniden yazılamaz.
    """
    net_total = bank_total = cash_total = ZERO_MONEY
    gross_total = sgk_employer_total = employer_cost_total = ZERO_MONEY
    net_count = bank_count = cash_count = 0
    uncomputed_count = excluded_count = unknown_cost_count = 0

    for line in lines:
        if line.status is PayrollLineStatus.uncomputed:
            uncomputed_count += 1
        elif line.status is PayrollLineStatus.excluded:
            excluded_count += 1

        # --- ödeme tabanı ---
        if line.status in PAYABLE_LINE_STATUSES and line.net_amount is not None:
            net_total += line.net_amount
            net_count += 1
            if line.bank_amount is not None and line.bank_amount > 0:
                bank_total += line.bank_amount
                bank_count += 1
            if line.cash_amount is not None and line.cash_amount > 0:
                cash_total += line.cash_amount
                cash_count += 1

        # --- maliyet tabanı: `excluded` DAHİL, `uncomputed` hariç (brütü yok) ---
        if line.gross_amount is None:
            continue
        # Brüt oran setinden BAĞIMSIZ bir olgudur: oran kaybolsa da bilinir ve
        # BG 46 sütununda basılır. Yalnız İŞVEREN yükü bilinmez hâle gelir.
        gross_total += line.gross_amount
        rate = rates.get(line.personnel_source)
        maliyet = compute.total_employer_cost(line.gross_amount, rate)
        if maliyet is None:
            unknown_cost_count += 1
            continue
        employer_cost_total += maliyet
        sgk_employer_total += compute.rate_share(line.gross_amount, rate.sgk_employer_pct)

    return PeriodSummary(
        line_count=len(lines),
        net_total=net_total,
        net_personnel_count=net_count,
        bank_total=bank_total,
        bank_personnel_count=bank_count,
        bank_pct=_pct(bank_total, net_total),
        cash_total=cash_total,
        cash_personnel_count=cash_count,
        cash_pct=_pct(cash_total, net_total),
        gross_total=gross_total,
        sgk_employer_total=sgk_employer_total,
        total_employer_cost=employer_cost_total,
        uncomputed_count=uncomputed_count,
        excluded_count=excluded_count,
        unknown_cost_count=unknown_cost_count,
    )
