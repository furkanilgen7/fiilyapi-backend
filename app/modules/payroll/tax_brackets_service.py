"""TB6 T1 — gelir vergisi TARİFESİNİN yönetim uçlarının servisi.

`service.py`den AYRI bir dosyadır ve bu bilinçlidir (`accounting/state_service.py`
emsali): o dosya 1.349 satırla 800 tavanının ZATEN üstündedir (açık borç) ve
tarife yönetimi oraya eklenseydi borç büyütülmüş olurdu. Ayrım da doğaldır —
`service.py` bordroyu HESAPLAR, bu dosya hesabın GİRDİSİNİ yönetir.

`_year_has_locked_period` KOPYALANMAZ, `service`ten çağrılır: "hesabı donmuş
yıl" tanımı tek yerde durmalıdır (oran kapısıyla tarife kapısı AYNI olguyu
ölçer).
"""

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError
from app.modules.audit import messages
from app.modules.payroll import guards, schemas, service
from app.modules.payroll.models import IncomeKind, PayrollTaxBracket

__all__ = ["list_tax_brackets", "replace_tax_brackets"]


async def list_tax_brackets(
    session: AsyncSession,
    year: int | None = None,
    income_kind: IncomeKind | None = None,
) -> schemas.PayrollTaxBracketListResponse:
    """`GET /payroll/tax-brackets` — tarife dilimleri (IK3-GV K2).

    Pasif setler de DÖNER (`is_active` alanıyla birlikte): geçmiş bir bordronun
    hangi tarifeyle hesaplandığı okunabilir kalmalıdır (`list_rates` emsali).

    🔴 Sıra `(yıl azalan, gelir türü, ORDINAL artan)`dır. `ordinal` bir süs
    değil TARİFENİN KENDİSİDİR (birikimli okunur); sıralanmadan basılsaydı
    kullanıcı setin deliğini/örtüşmesini ekrandan hiç göremezdi.
    """
    sorgu = select(PayrollTaxBracket)
    if year is not None:
        sorgu = sorgu.where(PayrollTaxBracket.year == year)
    if income_kind is not None:
        sorgu = sorgu.where(PayrollTaxBracket.income_kind == income_kind)
    rows = list(
        (
            await session.execute(
                sorgu.order_by(
                    PayrollTaxBracket.year.desc(),
                    PayrollTaxBracket.income_kind,
                    PayrollTaxBracket.ordinal,
                )
            )
        )
        .scalars()
        .all()
    )
    return schemas.PayrollTaxBracketListResponse(
        items=[schemas.PayrollTaxBracketResponse.model_validate(row) for row in rows],
        total=len(rows),
    )


async def replace_tax_brackets(
    session: AsyncSession,
    year: int,
    income_kind: IncomeKind,
    data: schemas.PayrollTaxBracketSetUpdate,
) -> tuple[list[PayrollTaxBracket], str]:
    """`PUT /payroll/tax-brackets/{year}/{income_kind}` — TAM KÜME değiştirme.

    🔴 **GEÇMİŞ DÖNEM DEĞİŞMEZ (para korkuluğu).** O yılda `approved`/`paid` bir
    dönem varsa yazma **409**dur ve gerekçe `upsert_rate`inkiyle AYNI DEĞİLDİR:
    vergi satıra SNAPSHOT edilir (`_apply`), o hâlde onaylı dönemin raporlanmış
    sayısı bu yazıyla kendiliğinden değişmez. Kapı `income_tax.monthly_income_tax`
    yüzünden gereklidir — ayın vergisi `T(önceki + bu ay) − T(önceki)`dir ve İKİ
    çağrı da YÜRÜRLÜKTEKİ setle yapılır; yıl ortasında tarife değişirse ondan
    sonra hesaplanan ilk ay, ödenmiş ayların TÜM farkını tek başına yutar.

    🔴 **Eski satırlar SİLİNİR, pasifleştirilmez.** Seçenek yoktur:
    `uq_payroll_tax_brackets_year_kind_ordinal` yeni setin `ordinal`lerini
    eskilerin üstüne çarpar, iki set aynı `(yıl, tür)` altında YAN YANA DURAMAZ.
    "Eski tarife silinmez" kuralı YIL bazındadır ve bundan etkilenmez.

    Kilit `_year_has_locked_period`in `FOR UPDATE`idir (EŞİK = KİLİT) ve
    denetimden ÖNCE alınır: eşzamanlı bir `approve_period` aksi hâlde tam bu
    pencerede dönemi onaylayabilirdi (TOCTOU).
    """
    if await service._year_has_locked_period(session, year):
        raise ConflictError(guards.TAX_BRACKETS_LOCKED_BY_PERIOD)

    await session.execute(
        delete(PayrollTaxBracket).where(
            PayrollTaxBracket.year == year, PayrollTaxBracket.income_kind == income_kind
        )
    )
    # 🔴 `flush` ŞARTTIR: silme ile eklemenin AYNI flush'a düşmesi hâlinde
    # SQLAlchemy INSERT'leri DELETE'ten önce sıralayabilir ve UQ ihlali doğardı.
    await session.flush()

    rows = [
        PayrollTaxBracket(
            year=year,
            income_kind=income_kind,
            ordinal=dilim.ordinal,
            upper_bound=dilim.upper_bound,
            rate_pct=dilim.rate_pct,
            is_active=data.is_active,
        )
        for dilim in sorted(data.brackets, key=lambda d: d.ordinal)
    ]
    session.add_all(rows)
    await session.flush()

    return rows, messages.payroll_tax_brackets_updated(
        year,
        income_kind.value,
        [(row.ordinal, row.upper_bound, row.rate_pct) for row in rows],
        data.is_active,
    )
