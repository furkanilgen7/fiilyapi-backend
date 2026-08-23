"""İK-3 T5 — kesinti oran seti ucları (K1) + T5 para korkulugu.

🔴 `year_has_locked_period` bir OKUMA gibi gorunur ama DEGILDIR: yilin TUM
donemlerini `FOR UPDATE` ile ve DURUM SUZGECI OLMADAN kilitler (TOCTOU).
Gerekcesi kendi docstring'indedir ve `tax_brackets_service.py` de onu cagirir.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError
from app.modules.audit import messages
from app.modules.payroll import guards, schemas
from app.modules.payroll.models import PayrollPeriod, PayrollRate
from app.modules.payroll.service.core import LOCKED_PERIOD_STATUSES
from app.modules.site_diary.models import WorkerSource


async def list_rates(
    session: AsyncSession, year: int | None = None
) -> schemas.PayrollRateListResponse:
    """`GET /payroll/rates` — oran setleri (K1).

    Pasif setler de DÖNER (`is_active` alanıyla birlikte): geçmiş bir bordronun
    hangi oranla hesaplandığı okunabilir kalmalıdır (models.py). Sıra
    `(yıl azalan, tip)`tir — en yeni yıl başta.
    """
    sorgu = select(PayrollRate)
    if year is not None:
        sorgu = sorgu.where(PayrollRate.year == year)
    rows = list(
        (
            await session.execute(
                sorgu.order_by(PayrollRate.year.desc(), PayrollRate.personnel_source)
            )
        )
        .scalars()
        .all()
    )
    return schemas.PayrollRateListResponse(
        items=[schemas.PayrollRateResponse.model_validate(row) for row in rows], total=len(rows)
    )


async def year_has_locked_period(session: AsyncSession, year: int) -> bool:
    """O yılda `approved`/`paid` bir dönem var mı? (T5 oran korkuluğu)

    `LOCKED_PERIOD_STATUSES` YENİDEN KULLANILIR ve bu bilinçlidir: "hesabı
    donmuş dönem" tanımı tek yerde durmalıdır — `compute` kapısıyla oran kapısı
    aynı olguyu ölçer.

    🔴 **EŞİK = KİLİT (WORKFLOW §4).** Yılın TÜM dönemleri `FOR UPDATE` ile ve
    DURUM SÜZGECİ OLMADAN okunur. İki ayrıntı da zorunludur:

    * **Süzgeçsiz:** `WHERE status IN (...)` ile kilitlenseydi "hiç onaylı dönem
      yok" hâlinde HİÇBİR satır kilitlenmez, koruma da olmazdı. Eşzamanlı bir
      `approve_period` tam bu anda dönemi onaylayıp commit edebilir ve oran
      yazısı onaylanmış bir dönemin hesabını yine değiştirirdi (TOCTOU).
    * **Sıra:** `approve_period` de aynı dönem satırlarını kilitler ve zincir
      her yerde dönem → satırdır; ters sıra olmadığı için deadlock doğmaz.

    Kilitlenen satır sayısı bir yılda en çok 12'dir (UQ `(year, month)`).
    """
    periods = (
        (
            await session.execute(
                select(PayrollPeriod)
                .where(PayrollPeriod.year == year)
                .order_by(PayrollPeriod.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )
    return any(period.status in LOCKED_PERIOD_STATUSES for period in periods)


async def upsert_rate(
    session: AsyncSession,
    year: int,
    source: WorkerSource,
    data: schemas.PayrollRateUpdate,
) -> tuple[PayrollRate, str]:
    """`PUT /payroll/rates/{year}/{source}` — set açar ya da DEĞİŞTİRİR (K1).

    🔴 **GEÇMİŞ DÖNEM DEĞİŞMEZ (para korkuluğu).** O yılda `approved`/`paid` bir
    dönem varsa yazma **409**dur. Gerekçe: K1 gereği oran satıra KOPYALANMAZ
    (tek gerçek kaynak `payroll_rates`) ve `summary.py`/`sgk.py` işveren tarafını
    dönemin yılına ait CANLI setten türetir; oran değişince onaylanmış dönemin
    raporlanmış toplamları ve SGK bildiriminin TAMAMI geriye dönük değişirdi.

    Kapı GÜNCELLEMEYE değil YILA kapanır: oran satırı olmayan bir tip için YENİ
    set açmak da o tipin satırlarını `unknown_cost_count`tan çıkarıp maliyete
    eklerdi — sonuç aynı şekilde değişirdi.

    Kural bordroyu TIKAMAZ: başka yıl serbesttir (mevzuat değişimi engellenmez)
    ve `draft`/`pending_approval` dönemli yıl da serbesttir.

    PUT TAM SETTİR (`PayrollRateUpdate`): kısmi gönderim yoktur, eksik alan
    sessizce 0 olamaz.
    """
    if await year_has_locked_period(session, year):
        raise ConflictError(guards.RATES_LOCKED_BY_PERIOD)

    rate = (
        await session.execute(
            select(PayrollRate).where(
                PayrollRate.year == year, PayrollRate.personnel_source == source
            )
        )
    ).scalar_one_or_none()
    if rate is None:
        rate = PayrollRate(year=year, personnel_source=source)
        session.add(rate)

    degerler = data.model_dump()
    for alan, deger in degerler.items():
        setattr(rate, alan, deger)

    await session.flush()
    return rate, messages.payroll_rate_updated(year, source.value, degerler)
