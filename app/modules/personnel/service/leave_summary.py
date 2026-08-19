"""IK-2 T4 — izin OZETI (spec §3, §4 — IZ mockup birebir)."""

import calendar
from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timezone
from app.modules.personnel import leave, repository
from app.modules.personnel.schemas import (
    HrLeavesSummaryResponse,
    LeaveBalanceResponse,
)
from app.modules.personnel.service.core import SUMMARY_LIST_LIMIT
from app.modules.personnel.service.leave_decisions import _balance_response


def _month_window(today: date) -> tuple[date, date]:
    """İZ 48'in "bu ay" penceresi: `today`nin ayının ilk ve son günü.

    Ay sonu `calendar.monthrange` ile bulunur — `+30 gün` yaklaşık bir pencere
    açar ve Şubat'ta bir sonraki ayın günlerini KPI'ya sokardı.
    """
    son_gun = calendar.monthrange(today.year, today.month)[1]
    return date(today.year, today.month, 1), date(today.year, today.month, son_gun)


def _balance_sort_key(row: LeaveBalanceResponse) -> tuple[int, Decimal, str]:
    """İZ 133-168 sırası: **kalan AZALAN**, hakkı bilinmeyenler EN SONDA.

    Mockup satırları 11 · 9 · 8 · "Hak yok" sırasındadır — ekranın önce en çok
    izni biriken kişiyi göstermesi izin planlamasının işidir. `None` kalanı
    sıfırmış gibi sıralamak, hakkı olmayan personeli kullanmayanların ARASINA
    serpiştirirdi; ayrı bir bayrakla sona alınır. Eşitlik ada göre çözülür ki
    sıra istekten isteğe OYNAMASIN.
    """
    if row.remaining is None:
        return (1, Decimal("0"), row.personnel_name)
    return (0, -row.remaining, row.personnel_name)


async def build_hr_leaves_summary(
    session: AsyncSession, *, year: int | None = None, today: date | None = None
) -> HrLeavesSummaryResponse:
    """İZ özeti: 5 KPI + bakiye tablosu — SABİT sorgu sayısı (N+1 yok).

    BEŞ aggrega sorgu çekilir (bekleyen sayısı · bugün izinli · bu ay kullanılan ·
    personel+devreden satırları · personel bazlı yıllık kullanım group-by'ı);
    hak/kalan/kıdem/yüzde türevleri Python'da `leave.py` TEK KAYNAĞINDAN hesaplanır
    ve satır kurulumu bakiye ucuyla AYNI `_balance_response`tan geçer — ekranda iki
    farklı "kalan" doğamaz. Sorgu sayısı VERİ BÜYÜKLÜĞÜNDEN BAĞIMSIZDIR
    (`test_n_plus_1_sabit_sorgu`).

    `year` verilmezse İÇİNDE BULUNULAN yıl (İZ 120 seçicisinin varsayılanı);
    `today` enjekte edilir (servis sınırı `timezone.today()` verir, test sabit tarih).

    KPI'lar TÜM personeli sayar, tablo `SUMMARY_LIST_LIMIT` satırda kırpılır
    (İK-1 emsali): kırpma bir GÖRÜNTÜ sınırıdır, sayaçları eksiltmez.
    """
    today = today or timezone.today()
    year = year or today.year
    ay_baslangic, ay_bitis = _month_window(today)

    pending_requests = await repository.count_pending_leave_requests(session)
    on_leave_today = await repository.count_personnel_on_leave(session, today)
    days_used_this_month = await repository.sum_deductible_approved_days_between(
        session, ay_baslangic, ay_bitis
    )
    rows = await repository.list_active_published_personnel_with_balance(session, year)
    used_by_personnel = await repository.sum_deductible_approved_days_by_personnel(session, year)

    reference = leave.balance_reference_date(year, today)
    balances: list[LeaveBalanceResponse] = []
    total_debt = Decimal("0")
    carryover_risk = 0
    unknown = 0

    for personnel, carried_over_raw in rows:
        # Bakiye satırı YOKSA devreden sıfırdır (satır yalnız MANUEL devreden içindir).
        carried_over = carried_over_raw if carried_over_raw is not None else Decimal("0")
        used = used_by_personnel.get(personnel.id, 0)
        entitlement = leave.annual_entitlement(personnel.hire_date, reference)
        satir = _balance_response(personnel, year, today, entitlement, carried_over, used)
        balances.append(satir)

        if satir.remaining is None:
            # 🔴 fail-closed: hesaplanamayan hak toplama 0 olarak KARIŞMAZ, sayılır.
            unknown += 1
            continue
        # Borç = personele HÂLÂ borçlu olunan gün. Negatif kalan (fazla kullanılmış
        # izin) ters yönlü bir alacaktır; netleştirilseydi ekrandaki toplam bir
        # başkasının borcunu sessizce yutardı.
        if satir.remaining > 0:
            total_debt += satir.remaining
        # İZ 50 "Devreden Risk · Yıl sonu yanacak": devredeni VAR ve kalanı DURUYOR.
        # Kalanı tükenmiş kişide yanacak gün kalmamıştır; devredeni olmayan zaten
        # riskte değildir.
        if carried_over > 0 and satir.remaining > 0:
            carryover_risk += 1

    balances.sort(key=_balance_sort_key)

    return HrLeavesSummaryResponse(
        year=year,
        pending_requests=pending_requests,
        on_leave_today=on_leave_today,
        days_used_this_month=days_used_this_month,
        total_leave_debt=total_debt,
        carryover_risk_personnel=carryover_risk,
        unknown_entitlement_personnel=unknown,
        balances=balances[:SUMMARY_LIST_LIMIT],
    )
