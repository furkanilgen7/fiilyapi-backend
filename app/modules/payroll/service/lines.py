"""İK-3 T3 — satir ucu: K3 brut override'i + S3 odeme bolusumu.

Sira ANLAMLIDIR ve `update_line`da korunur: once brut (neti degistirir), sonra
bolusum — bolusum YENI nete gore dogrulanir. Ters sirada eski nete gore dogru
olan bir bolusum kabul edilir, ardindan brut onu sessizce ezerdi.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, PayrollValidationError
from app.modules.audit import messages
from app.modules.payroll import compute, guards, schemas, transitions
from app.modules.payroll.models import PayrollLine, PayrollLineStatus, PayrollPeriod
from app.modules.payroll.service.core import (
    LOCKED_LINE_STATUSES,
    LOCKED_PERIOD_STATUSES,
    _full_name,
    _line_response,
    _locked_line,
    rates_by_source,
)
from app.modules.payroll.service.tax_context import _tax_context_for_line
from app.modules.personnel.models import Personnel


def _assert_line_editable(period: PayrollPeriod, line: PayrollLine) -> None:
    """Üç kapı, bu SIRAYLA — hepsi 409 (durum engeli, yetki değil).

    1. **Dönem** `approved`/`paid` (S5'in dönem tarafı): onaylanmış dönemin
       toplamları raporlanmıştır, içine sonradan satır büyütmek o raporu
       sessizce yalanlardı. Dönem kapısı ÖNCE gelir çünkü daha genel olandır.
    2. **K2 — `excluded` satır:** banka/elden ÖDEMEYE dair alanlardır; taşeron
       bordrodan ödenmez (ödemesi hakediş üzerinden yapılır) ve bölüşümünün
       doldurulabilmesi ödenmeyecek bir satır için ödeme talimatı hazırlanmasını,
       yani ÇİFT ÖDEMEYİ mümkün kılardı. Brüt override'ı da aynı kapıdan döner:
       `transitions.py` `excluded`ı terminal sayar, satır hiçbir hedefe geçemez.
       K2 kapısı S5'ten ÖNCEDİR ki taşeron satırı için AÇIKLAYICI mesaj dönsün —
       taşeron satırı zaten hiçbir zaman `approved` olamaz.
    3. **S5 — `approved`/`paid` satır:** ödeme izi.
    """
    if period.status in LOCKED_PERIOD_STATUSES:
        raise ConflictError(guards.PERIOD_LOCKED_FOR_EDIT)
    if line.status is PayrollLineStatus.excluded:
        raise ConflictError(guards.LINE_EXCLUDED)
    if line.status in LOCKED_LINE_STATUSES:
        raise ConflictError(guards.LINE_LOCKED)


async def _apply_gross_override(
    session: AsyncSession,
    period: PayrollPeriod,
    line: PayrollLine,
    actor_id: uuid.UUID,
    gross_amount: Decimal,
) -> None:
    """K3 — brüt elle değişir, İZ BIRAKIR, kesinti/net/bölüşüm YENİDEN TÜRER.

    Kesinti gövdeden alınmaz ve eski kesinti KORUNMAZ: korunsaydı brütü
    büyütmek neti orantısız şişirirdi. Hesap `compute.deduction_and_net`tir —
    otomatik satırlarla AYNI kural (kopyalanmaz, ÇAĞRILIR).

    Bölüşüm de netten yeniden türer (`compute.split_payment`): eski banka tutarı
    bırakılsaydı satır S3'ü İHLAL EDER durumda DB'ye yazılmış olurdu. Aynı
    gövdede açık bir bölüşüm geldiyse çağıran onu bunun ÜZERİNE yazar ve YENİ
    nete göre doğrular.

    Oran seti yoksa **422** (ŞEF KARARI 2, T2): kesintisi bilinmeyen bir brütten
    net türetmek, kesintiyi 0 saymak demektir.

    🔴 **IK3-GV — `deduction_and_net`in İKİNCİ ÇAĞIRANI BURASIDIR.** Vergi
    bağlamı (`TaxContext`) otomatik yolla AYNI yardımcıdan kurulur
    (`_tax_context_for_line`): kümülatif taban aynı snapshot zincirinden, tarife
    ve asgari ücret aynı yıldan gelir. İkinci bir bağlam kurulsaydı elle
    düzeltilen satır ile otomatik satır aynı girdide FARKLI vergi üretirdi.

    Dilimli rejimde tarife/asgari ücret satırı yoksa yine **422**dir (K3
    fail-closed): 0 vergiyle "düzeltilmiş" bir satır yazmak, kullanıcının elle
    girdiği brütü vergisiz ödemek olurdu.
    """
    rate = (await rates_by_source(session, period.year)).get(line.personnel_source)
    if rate is None:
        raise PayrollValidationError(guards.RATE_MISSING)

    person = (
        await session.execute(select(Personnel).where(Personnel.id == line.personnel_id))
    ).scalar_one()

    tax = await _tax_context_for_line(session, period, person)
    sonuc = compute.deduction_and_net(gross_amount, rate, tax)
    if sonuc is None:
        raise PayrollValidationError(guards.TAX_BRACKETS_MISSING)

    line.previous_gross_amount = line.gross_amount
    line.is_overridden = True
    line.overridden_by_id = actor_id
    line.overridden_at = datetime.now(UTC)

    kesintiler, net = sonuc
    line.gross_amount = gross_amount
    line.deduction_amount = kesintiler.total
    line.net_amount = net
    line.tax_base_amount = kesintiler.tax_base
    line.cumulative_tax_base = kesintiler.cumulative_tax_base
    line.income_tax_amount = kesintiler.income_tax
    line.bank_amount, line.cash_amount = compute.split_payment(net, person.payment_method)

    if line.status is PayrollLineStatus.uncomputed:
        # S4'ün çıkış kapısı: elle girilen brüt satırı ödenebilir kılar.
        transitions.assert_line_transition(line.status, PayrollLineStatus.pending)
        line.status = PayrollLineStatus.pending


def _apply_split(line: PayrollLine, bank_amount: Decimal, cash_amount: Decimal) -> None:
    """🔴 S3 — `banka + elden = net`, KURUŞ hassasiyetinde (`Decimal`, asla `float`).

    Doğrulama SUNUCUDADIR ve istemci hesabına GÜVENİLMEZ (spec §6/1): BY
    142-147'de iki ayrı `input` vardır, kullanıcı ikisini bağımsız yazabilir.
    Neti `null` olan satırda bölüşüm TANIMSIZDIR → 422 (S4).
    """
    if line.net_amount is None:
        raise PayrollValidationError(guards.SPLIT_WITHOUT_NET)
    if bank_amount + cash_amount != line.net_amount:
        raise PayrollValidationError(
            guards.split_mismatch(bank_amount, cash_amount, line.net_amount)
        )
    line.bank_amount = bank_amount
    line.cash_amount = cash_amount


async def update_line(
    session: AsyncSession,
    actor_id: uuid.UUID,
    line_id: uuid.UUID,
    data: schemas.PayrollLineUpdate,
) -> tuple[schemas.PayrollLineResponse, str]:
    """`PATCH /payroll/lines/{id}` — K3 override + S3 bölüşümü, TEK atomik işlem.

    Sıra ANLAMLIDIR: önce brüt (neti değiştirir), sonra bölüşüm — bölüşüm YENİ
    nete göre doğrulanır. Ters sırada eski nete göre doğru olan bir bölüşüm
    kabul edilir, ardından brüt onu sessizce ezerdi.

    Aynı brüt yeniden gönderilirse override İZİ YAZILMAZ: değişmeyen bir değer
    için "elle düzeltildi" damgası basmak, S6'nın koruma listesini gerçek
    düzeltmeler dışındaki satırlarla kirletirdi.
    """
    period, line = await _locked_line(session, line_id)
    _assert_line_editable(period, line)

    if data.gross_amount is not None and data.gross_amount != line.gross_amount:
        await _apply_gross_override(session, period, line, actor_id, data.gross_amount)
    if data.bank_amount is not None and data.cash_amount is not None:
        _apply_split(line, data.bank_amount, data.cash_amount)

    await session.flush()
    full_name = await _full_name(session, line.personnel_id)
    return _line_response(line, full_name), messages.payroll_line_updated(
        full_name, period.year, period.month
    )
