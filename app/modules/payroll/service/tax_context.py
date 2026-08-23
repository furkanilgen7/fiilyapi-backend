"""IK3-GV — dilimli gelir vergisinin DB tarafi (tarife, asgari ucret, kumulatif).

`compute.py` saftir ve DB'ye dokunmaz; bu dosya onun `TaxContext` girdisini
veritabanindan OKUR. Ayri durmasinin sebebi olculmustur: hem toplu yol
(`compute_period`, `DISTINCT ON` ile N+1'siz) hem tek satir yolu
(`_apply_gross_override`) AYNI kaynaklardan beslenmek zorundadir — ikinci bir
baglam kurulsaydi elle duzeltilen satir ile otomatik satir ayni girdide FARKLI
vergi uretirdi.

Uc okuma da fail-closed'dir: tarife yoksa `None`, asgari ucret yoksa `None`,
eksik onceki ay SESSIZ gecilmez SAYILIR.
"""

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.payroll import compute, income_tax
from app.modules.payroll.models import (
    IncomeKind,
    PayrollLine,
    PayrollMinimumWage,
    PayrollPeriod,
    PayrollPeriodStatus,
    PayrollTaxBracket,
)
from app.modules.personnel.models import Personnel

# --- IK3-GV: dilimli vergi bağlamı ----------------------------------------
#
# 🔴 KÜMÜLATİF MATRAH SNAPSHOT'TIR, `SUM` DEĞİLDİR (K1). Gerekçe modelde
# (`models.py` `PayrollLine`) yazılıdır ve ÖLÇÜLMÜŞTÜR: `create_period` ay
# sırasını hiç zorlamaz, onaylanan dönem geri alınamaz (`transitions.py` tek
# yönlü, DELETE ucu yok) → `SUM` yolu ödenmiş bir dönemin vergisini kalıcı ve
# SESSİZ biçimde yanlış bırakırdı.
#
# Zincir şöyle kurulur: bir ayın tabanı, **daha erken bir ayın satırına
# YAZILMIŞ** `cumulative_tax_base`tir. Böylece Temmuz onaylandıktan sonra Mart
# açılıp hesaplansa bile Temmuz'un vergisi DEĞİŞMEZ (KK-8: geçmiş dönemler
# donmuş kalır) ve Mart kendi doğru tabanından hesaplanır.


async def _tax_brackets(
    session: AsyncSession, year: int
) -> tuple[income_tax.TaxBracket, ...] | None:
    """Yılın ÜCRET tarifesi — satırı yoksa **`None`** (fail-closed, K3).

    Yalnız `is_active` satırlar okunur (`payroll_rates` kuralıyla aynı: eski
    yılın tarifesi silinmez, pasifleştirilir).

    🔴 Set BURADA doğrulanmaz; doğrulama `income_tax.normalize_brackets`tadır ve
    `compute` onu bir istisnayla karşılayıp satırı `uncomputed`a düşürür. Burada
    doğrulansaydı bozuk bir set TÜM dönemi 500'e düşürür, tek bir tipin satırı
    yüzünden bordronun tamamı hesaplanamaz olurdu.
    """
    rows = (
        (
            await session.execute(
                select(PayrollTaxBracket).where(
                    PayrollTaxBracket.year == year,
                    PayrollTaxBracket.income_kind == IncomeKind.wage,
                    PayrollTaxBracket.is_active.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return None
    return tuple(
        income_tax.TaxBracket(
            ordinal=row.ordinal, upper_bound=row.upper_bound, rate_pct=row.rate_pct
        )
        for row in rows
    )


async def _minimum_wage_gross(session: AsyncSession, year: int) -> Decimal | None:
    """Yılın BRÜT asgari ücreti — satırı yoksa **`None`** (fail-closed, KK-7).

    İstisnayı 0 saymak asgari ücretliden ayda ~4.500 TL fazla kesmek olurdu.
    """
    return (
        await session.execute(
            select(PayrollMinimumWage.gross_amount).where(
                PayrollMinimumWage.year == year, PayrollMinimumWage.is_active.is_(True)
            )
        )
    ).scalar_one_or_none()


async def _prior_cumulative_bases(
    session: AsyncSession, year: int, month: int
) -> dict[uuid.UUID, Decimal]:
    """Personel başına, AYNI YILIN daha erken bir ayına YAZILMIŞ son kümülatif.

    🔴 `SUM(tax_base_amount)` DEĞİL: en yakın önceki ayın **snapshot**ı okunur
    (K1). Aradaki bir ay eksikse ya da hesaplanmamışsa taban o eksikliği
    sessizce yutmaz — eksik ay `missing_prior_period_count` sayacında GÖRÜNÜR
    (K4). Fark ölçüldü: `SUM` yolunda sonradan açılan bir ay, ÖNCEDEN ONAYLANMIŞ
    sonraki ayların tabanını geriye dönük değiştirirdi ve o aylar
    düzeltilemezdi.

    `DISTINCT ON (personnel_id) … ORDER BY personnel_id, month DESC` PostgreSQL
    özelliğidir ve N+1'i önler: 48 kişilik bir dönemde tek sorgu koşar.
    """
    rows = await session.execute(
        select(PayrollLine.personnel_id, PayrollLine.cumulative_tax_base)
        .join(PayrollPeriod, PayrollPeriod.id == PayrollLine.payroll_period_id)
        .where(
            PayrollPeriod.year == year,
            PayrollPeriod.month < month,
            PayrollLine.cumulative_tax_base.is_not(None),
        )
        .distinct(PayrollLine.personnel_id)
        .order_by(PayrollLine.personnel_id, PayrollPeriod.month.desc())
    )
    return {personnel_id: taban for personnel_id, taban in rows.all()}


def _opening_tax_base(person: Personnel, year: int) -> Decimal:
    """K7 devir matrahı — YALNIZ yılı tutuyorsa kullanılır (fail-closed).

    Kolon AÇIKTIR ama hiçbir uç onu DOLDURMAZ (GV GT 311 md.21/5: devir
    çalışanın talebine bağlıdır, otomatik değildir), varsayılan 0'dır ve
    bugünkü davranış değişmez. Yıl niteleyicisi `NULL` ya da farklıysa devir
    YOK sayılır: aksi hâlde 2026'da girilen bir devir 2027'de de uygulanır ve
    "31 Aralık → 1 Ocak sıfırlanır" kuralını sessizce bozardı.
    """
    if person.opening_tax_base_year != year:
        return Decimal("0.00")
    return person.opening_tax_base


async def _missing_prior_period_count(session: AsyncSession, year: int, month: int) -> int:
    """🔴 K4 — SIRASIZ DÖNEM: fail-closed SAYAÇ, sessiz geçiş YOK.

    Aynı yılın daha erken bir ayı `payroll_periods`ta YOKSA ya da hâlâ `draft`
    ise, o ayın matrahı kümülatife GİRMEMİŞTİR ve bu dönemin vergisi olması
    gerekenden DÜŞÜK çıkar. Sayaç bunu görünür kılar (İK-2'nin
    `unknown_entitlement_personnel` emsali).

    🔴 **409 ile REDDEDİLMEZ:** yıl ortasında sisteme geçişi imkânsız kılardı
    (Ağustos'ta başlayan bir şirket Ocak-Temmuz'u açmak zorunda kalırdı).
    🔴 **SESSİZ DE GEÇİLMEZ:** "aynı yeşil iki anlam taşır" — doğru sırayla
    hesaplanmış bir dönem ile sırasız hesaplanmış bir dönem AYIRT EDİLEBİLİR
    olmalıdır.
    """
    if month <= 1:
        return 0
    hazir = set(
        (
            await session.execute(
                select(PayrollPeriod.month).where(
                    PayrollPeriod.year == year,
                    PayrollPeriod.month < month,
                    PayrollPeriod.status != PayrollPeriodStatus.draft,
                )
            )
        )
        .scalars()
        .all()
    )
    return len([ay for ay in range(1, month) if ay not in hazir])


async def _tax_context_for_line(
    session: AsyncSession, period: PayrollPeriod, person: Personnel
) -> compute.TaxContext:
    """TEK bir satır için vergi bağlamı — override yolunun (K3) girdisi.

    `compute_period`in toplu okumalarının tek kişilik eşidir ve AYNI
    kaynaklardan besleneceği için iki yol aynı girdide aynı sayıyı üretir
    (T4 kabul şartı). Toplu yolla tek fonksiyonda birleştirilmedi çünkü toplu
    yol N+1'den kaçınmak için `DISTINCT ON` kullanır; burada tek kişi vardır ve
    aynı sorgunun sözlüğünden okunur.
    """
    prior = await _prior_cumulative_bases(session, period.year, period.month)
    return compute.TaxContext(
        month=period.month,
        prior_cumulative_base=prior.get(person.id, _opening_tax_base(person, period.year)),
        brackets=await _tax_brackets(session, period.year),
        minimum_wage_gross=await _minimum_wage_gross(session, period.year),
    )
