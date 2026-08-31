"""İK-3 T3 — donem ucları: acma, odeme takvimi, BY detayi, BG listesi.

Toplamlar SQL'de degil `summary.py`de hesaplanir ve bu bilinclidir: BG'nin
"Toplam Maliyet" sutunu ile BY'nin 4. karti AYNI fonksiyondan gecmelidir
(spec §7'nin uc kalemli formulu TEK KAYNAKTIR).
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, DuplicateError
from app.modules.audit import messages
from app.modules.payroll import guards, schemas, summary
from app.modules.payroll.models import PayrollPeriod, PayrollPeriodStatus, PayrollRate
from app.modules.payroll.service.core import (
    _line_response,
    _lines_with_names,
    _lock_period,
    get_period,
    rates_by_source,
)
from app.modules.site_diary.models import WorkerSource

# --- T3: dönem + satır uçlarının servisi -----------------------------------
#
# ## Kilit SIRASI tüm uçlarda SABİT: dönem → satır
#
# `compute_period` serileştirmesini dönem satırında yapar (yukarıdaki modül
# notu); `update_line` de ÖNCE dönemi, SONRA satırı kilitler. Sıra ters olsaydı
# bir `compute` ile bir `PATCH` birbirini karşılıklı bekleyip deadlock'a düşerdi
# (WORKFLOW §4 EŞİK=KİLİT). Tam eşzamanlılık regresyonu (iki gerçek bağlantı)
# T4'ün işidir; buradaki kural o testin ön koşuludur.
#
# ## `visible_projects` süzgeci YOKTUR
#
# Bordro şirket geneli bir İK varlığıdır (`personnel`/`timesheet` deseni):
# kapsam denetimi `payroll` İZNİDİR, proje erişimi değil. Bir bordro dönemi tek
# bir projeye ait değildir — süzgeç konsaydı aynı ayın toplamı iki kullanıcıda
# iki farklı sayı gösterirdi.

#: BY bölümlerinin EKRAN SIRASI: 124 → 172 → 240 → 268. `general` bordro tipi
#: değildir (spec §4) ama satırı varsa GİZLENMEZ — sona düşer, çünkü görünmeyen
#: bir satır sessizce kaybolmuş demektir.
SECTION_ORDER = (
    WorkerSource.company,
    WorkerSource.subcontractor,
    WorkerSource.freelance,
    WorkerSource.intern,
    WorkerSource.general,
)


async def create_period(
    session: AsyncSession, data: schemas.PayrollPeriodCreate
) -> tuple[PayrollPeriod, str]:
    """Ay açar. Var olan ay → **409** (UQ `(year, month)`).

    Çakışma UQ'ya DÜŞMEDEN önce açık bir SELECT ile yakalanır (`DuplicateError`
    deseni): IntegrityError'ın "Veri bütünlüğü hatası" metni kullanıcıya hangi
    ayın zaten açık olduğunu söylemezdi. UQ ikinci katman olarak KALIR (yarış).
    """
    mevcut = (
        await session.execute(
            select(PayrollPeriod.id).where(
                PayrollPeriod.year == data.year, PayrollPeriod.month == data.month
            )
        )
    ).scalar_one_or_none()
    if mevcut is not None:
        raise DuplicateError(guards.PERIOD_DUPLICATE)

    period = PayrollPeriod(year=data.year, month=data.month, payment_due_date=data.payment_due_date)
    session.add(period)
    await session.flush()
    return period, messages.payroll_period_created(period.year, period.month)


#: Ödeme TAKVİMİNİ donduran dönem durumları (T4b). Bugün `LOCKED_PERIOD_STATUSES`
#: ile aynı ikiliyi taşır ama ona BAĞLANMAZ ve bu bilinçlidir: o küme "yeniden
#: HESAP" kapısıdır, bu küme "ödeme TARİHİ" kapısı. Takma ad verilseydi birinin
#: yarın gevşetilmesi ötekini sessizce sürükler ve ödenmiş bir bordronun tarihi
#: kimse istemeden yazılabilir hâle gelirdi.
SCHEDULE_LOCKED_PERIOD_STATUSES = frozenset(
    {PayrollPeriodStatus.approved, PayrollPeriodStatus.paid}
)


async def update_period(
    session: AsyncSession, period_id: uuid.UUID, data: schemas.PayrollPeriodUpdate
) -> tuple[PayrollPeriod, str]:
    """`PATCH /payroll/periods/{id}` — ödeme takvimi (BY 63) düzeltmesi.

    🔴 **EŞİK = KİLİT (WORKFLOW §4):** dönem satırı `FOR UPDATE` ile ve DURUM
    DENETİMİNDEN ÖNCE okunur, sıra tüm uçlardaki gibi dönem → satır (burada
    satır tarafı yoktur). Kilit denetimden sonra alınsaydı eşzamanlı bir
    `approve` ile bu PATCH aynı `draft` durumunu okur, dönem onaylanırken tarihi
    de kayardı.

    Yalnız `draft` ve `pending_approval` yazılabilir; `approved`/`paid` **409**
    (gerekçe `guards.PERIOD_LOCKED_FOR_SCHEDULE`).
    """
    period = await _lock_period(session, period_id)
    if period.status in SCHEDULE_LOCKED_PERIOD_STATUSES:
        raise ConflictError(guards.PERIOD_LOCKED_FOR_SCHEDULE)

    period.payment_due_date = data.payment_due_date
    await session.flush()
    return period, messages.payroll_period_updated(
        period.year, period.month, period.payment_due_date
    )


async def get_period_detail(
    session: AsyncSession, period_id: uuid.UUID
) -> schemas.PayrollPeriodDetailResponse:
    """BY ekranının tamamı: künye + dört kart + tip bazında gruplanmış satırlar."""
    period = await get_period(session, period_id)
    lines = await _lines_with_names(session, [period.id])
    ozet = summary.build_period_summary(
        [line for line, _ in lines], await rates_by_source(session, period.year)
    )

    sections = []
    for source in SECTION_ORDER:
        bolum = [_line_response(line, ad) for line, ad in lines if line.personnel_source is source]
        if bolum:
            sections.append(
                schemas.PayrollSectionResponse(
                    personnel_source=source, line_count=len(bolum), lines=bolum
                )
            )

    return schemas.PayrollPeriodDetailResponse(
        id=period.id,
        year=period.year,
        month=period.month,
        status=period.status,
        payment_due_date=period.payment_due_date,
        approved_at=period.approved_at,
        paid_at=period.paid_at,
        sgk_submitted_at=period.sgk_submitted_at,
        summary=schemas.PayrollSummaryResponse.model_validate(ozet),
        sections=sections,
    )


async def list_periods(
    session: AsyncSession, *, limit: int, offset: int
) -> schemas.PayrollPeriodListResponse:
    """BG listesinin ZARFI — satırları `period_rows` üretir.

    Zarf ile satır üretimi AYRILDI (EXPORT-XLSX): `export.xlsx` ucu sayfasız
    okur ama zarfın `limit`/`offset` alanları sayfalama kavramına aittir ve
    `int`tir. Bölünme olmasaydı ya export ikinci bir sorgu yolu açardı ya da
    zarfın sözleşmesi `int | None`a gevşetilirdi (istemci tarafında kırıcı).
    """
    items, total = await period_rows(session, limit=limit, offset=offset)
    return schemas.PayrollPeriodListResponse(items=items, total=total, limit=limit, offset=offset)


async def period_rows(
    session: AsyncSession, *, limit: int | None, offset: int = 0
) -> tuple[list[schemas.PayrollPeriodListRow], int]:
    """BG satırları + toplam sayı — en YENİ dönem başta (BG tbody: Temmuz · Haziran · Mayıs).

    🔴 **`limit=None` TÜM dönemleri döner** (`audit/repository.py` emsali):
    dışa aktarma ekranın 200'lük tavanıyla SESSİZCE kırpılmaz. Tavan LİSTE
    ucunun imzasındadır (`_LIMIT = Query(le=200)`) ve orada DEĞİŞMEZ.

    Toplamlar SQL'de değil `summary.py`de hesaplanır ve bu bilinçlidir: BG'nin
    "Toplam Maliyet" sütunu ile BY'nin 4. kartı AYNI fonksiyondan geçmelidir
    (spec §7'nin üç kalemli formülü TEK KAYNAKTIR). SQL'de ikinci bir toplam
    yazılsaydı formül iki yerde yaşar, biri güncellenip öteki unutulurdu.
    Sayfa başına en çok 200 dönem okunur (TB3 tavanı) ve satırları TEK sorgu
    getirir — N+1 yoktur.
    """
    total = (await session.execute(select(func.count()).select_from(PayrollPeriod))).scalar_one()
    stmt = (
        select(PayrollPeriod)
        .order_by(PayrollPeriod.year.desc(), PayrollPeriod.month.desc())
        .offset(offset)
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    periods = list((await session.execute(stmt)).scalars().all())

    lines = await _lines_with_names(session, [p.id for p in periods])
    rates_by_year: dict[int, dict[WorkerSource, PayrollRate]] = {}
    for period in periods:
        if period.year not in rates_by_year:
            rates_by_year[period.year] = await rates_by_source(session, period.year)

    items = []
    for period in periods:
        ozet = summary.build_period_summary(
            [line for line, _ in lines if line.payroll_period_id == period.id],
            rates_by_year[period.year],
        )
        items.append(
            schemas.PayrollPeriodListRow(
                id=period.id,
                year=period.year,
                month=period.month,
                status=period.status,
                payment_due_date=period.payment_due_date,
                paid_at=period.paid_at,
                personnel_count=ozet.line_count,
                gross_total=ozet.gross_total,
                sgk_employer_total=ozet.sgk_employer_total,
                net_total=ozet.net_total,
                total_cost=ozet.total_employer_cost,
            )
        )
    return items, total
