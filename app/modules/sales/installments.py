"""Ödeme planının TEK yazma yolu — P8 T4 (spec §4, §8 S2; mockup F99-F147).

## Üç uç, tek kural kümesi

* `generate_plan` — F100 "Plan Oluştur": sunucu otoritesi. Satırlar
  `unit_sales`in dört plan sütunundan (F103 peşinat · F104 taksit sayısı ·
  F105 ilk taksit · F106 vade farkı) ÜRETİLİR, istemciden alınmaz.
* `save_installments` — `PUT …/installments`, **DEĞİŞTİRME semantiği**
  (`progress_payments/lines.py` deseni): gövde planın TAMAMIDIR, gövdede
  geçmeyen satır SİLİNİR. `contracts` dağıtımının BİRLEŞTİRME semantiğinin
  TERSİDİR — ikisi frontend'de yan yana kullanılır, karıştırılmamalıdır.
* `pay_installment` — §8 S2 tahsilatı; kısmi ödeme destekli.

## Sıra — ÖNCE KİLİT, sonra TÜM doğrulamalar, sonra TEK yazma

Kilit (`repository.lock_installments` / `get_installment_locked`) doğrulamayı
besleyen okumalardan ÖNCE alınır (TB1 dersi): sonra alınsaydı iki eşzamanlı
istek aynı "tahsil edilen"i okur, ikisi de geçerli sanılır ve satır aşırı
ödenirdi. Doğrulamalar yazmanın arasına serpiştirilmez (`lines.py` §"Sıra"):
ikinci satırda patlayan bir istek birincisini çoktan session'a eklemiş olurdu.

## Tahsilat KORUNUR — sessiz kayıp yok

`paid_amount > 0` olan satır ne yeniden üretimle (409 `PLAN_HAS_PAYMENTS`) ne
de gövdeden düşürülerek (409 `PAID_INSTALLMENT_REMOVED`) yok edilebilir; tutarı
da tahsilatın altına indirilemez (422 `PAID_INSTALLMENT_BELOW_PAID`). Gerekçe:
tahsilat bir MUHASEBE OLAYIDIR, plan satırı ise bir taahhüttür — taahhüdü
düzenlemek olayı silmemelidir.

## Gecikme faizi (§8 S5) ve vade farkı (F106)

İkisi de yalnız GÖSTERİM türevidir: bu dosya ne tahakkuk satırı yazar ne de
plan tutarlarını şişirir (bkz. `plan.py` kararı).
"""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timezone
from app.core.errors import ConflictError, DuplicateError, SiteValidationError
from app.modules.audit import messages
from app.modules.sales import guards, plan, repository
from app.modules.sales.models import SaleInstallment, UnitSale
from app.modules.sales.schemas import (
    InstallmentPayInput,
    SaleInstallmentInput,
    SaleInstallmentResponse,
    SaleInstallmentsSave,
    SalePlanResponse,
    unit_label,
)
from app.modules.users.models import User

__all__ = ["generate_plan", "get_plan", "pay_installment", "save_installments"]

_ZERO = Decimal("0.00")


# --- Yanıt zarfı ---


def _installment_response(row: SaleInstallment, today: date) -> SaleInstallmentResponse:
    """`today` DIŞARIDAN gelir (`repository.installment_stats` ile aynı kural):

    "gecikmiş" bir TARİH KARŞILAŞTIRMASIDIR ve burada `date.today()` çağırmak
    yanıtı çalıştığı güne bağımlı, dolayısıyla test edilemez kılardı.
    """
    return SaleInstallmentResponse(
        id=row.id,
        sale_id=row.sale_id,
        sequence_no=row.sequence_no,
        label=row.label,
        due_date=row.due_date,
        amount=row.amount,
        payment_method=row.payment_method,
        paid_amount=row.paid_amount,
        paid_at=row.paid_at,
        remaining_amount=row.amount - row.paid_amount,
        # S180 "⚠ 2 taksit gecikmiş" satır düzeyi türevi: vadesi geçmiş VE
        # tamamı tahsil edilmemiş. `repository.installment_stats.overdue_count`
        # ile AYNI tanım — iki farklı "gecikmiş" tanımı olmaz.
        is_overdue=row.due_date < today and row.paid_amount < row.amount,
    )


async def _plan_response(session: AsyncSession, sale: UnitSale, today: date) -> SalePlanResponse:
    rows = await repository.list_installments(session, sale.id)
    return SalePlanResponse(
        sale_id=sale.id,
        sale_price=sale.sale_price,
        total_amount=sum((row.amount for row in rows), start=_ZERO),
        paid_amount=sum((row.paid_amount for row in rows), start=_ZERO),
        term_interest_amount=plan.term_interest_amount(
            sale.sale_price, sale.down_payment or _ZERO, sale.term_interest_pct
        ),
        items=[_installment_response(row, today) for row in rows],
    )


async def get_plan(session: AsyncSession, actor: User, sale_id: uuid.UUID) -> SalePlanResponse:
    """`GET /sales/{id}/installments` — planı OKUYAN tek uç (T5).

    T4 planı yazan üç ucu kapattı ama okuyan bir uç bırakmadı: plan yalnız yazma
    yanıtlarında görülebiliyordu, `GET /sales/{id}` ise satırları taşımıyor.
    Yanıt zarfı T4'ün `SalePlanResponse`udur — ikinci bir plan şeması AÇILMAZ.

    Planı olmayan satış **404 DEĞİL** boş plan döner: satış vardır, planı yoktur
    ve "kayıt yok" ile "plan yok" farklı şeylerdir.

    Kilit YOK: okuma ucu hiçbir şey yazmaz ve `FOR UPDATE` almak eşzamanlı
    tahsilatları gereksiz yere serileştirirdi.
    """
    sale, _ = await guards.visible_sale(session, actor, sale_id)
    return await _plan_response(session, sale, timezone.today())


async def _unit_label(session: AsyncSession, sale: UnitSale) -> str:
    """Denetim metninin "A Blok · 12" parçası (`service._to_response` ile aynı kaynak).

    `service.py`nin yazma fonksiyonlarıyla aynı sözleşme: metin SERVİSTE kurulur,
    satırı yazan ROUTER'dır — böylece reddedilen (409/422) bir istek denetim
    satırı bırakmaz.
    """
    row = await repository.get_sale_row(session, sale.id)
    if row is None:  # pragma: no cover - FK + aynı transaction garantisi
        raise guards.NotFoundError(guards.SALE_MISSING)
    _, unit, block, _ = row
    return unit_label(block.name, unit.unit_no)


def _sync_paid_at(row: SaleInstallment, now: datetime | None = None) -> None:
    """`paid_at` = "satır TAM ödendi" anıdır, kısmi ödemede boş KALIR.

    Tutar sonradan yükseltilirse (plan düzenlemesi) damga TEMİZLENİR: aksi hâlde
    satır hem "ödenmiş" damgası taşır hem de bakiyesi olurdu.
    """
    if row.paid_amount >= row.amount:
        row.paid_at = row.paid_at or (now or datetime.now(UTC))
    else:
        row.paid_at = None


# --- 1) generate-plan (F100) ---


async def generate_plan(
    session: AsyncSession, actor: User, sale_id: uuid.UUID
) -> tuple[SalePlanResponse, str]:
    """Satışın plan sütunlarından satırları ÜRETİR (sunucu otoritesi).

    Mevcut plan ÜZERİNE YAZILIR (F100 düğmesi bir "tazele" eylemidir) ama YALNIZ
    hiç tahsilat yoksa; bir kuruş bile tahsil edilmişse 409 döner ve plan
    DOKUNULMADAN kalır.
    """
    sale, project = await guards.visible_sale(session, actor, sale_id)

    # Kilit ÖNCE: eşzamanlı bir `pay` isteği, "tahsilat var mı" kontrolü ile
    # satırların silinmesi arasına giremesin.
    await repository.lock_installments(session, sale.id)
    mevcut = await repository.list_installments(session, sale.id)
    guards.ensure_plan_replaceable(mevcut)

    down_payment = sale.down_payment or _ZERO
    installment_count = sale.installment_count or 0
    if down_payment <= _ZERO and installment_count <= 0:
        raise SiteValidationError(guards.PLAN_INPUT_MISSING)
    if down_payment > sale.sale_price:
        raise SiteValidationError(guards.PLAN_DOWN_PAYMENT_EXCEEDS)
    if installment_count > 0 and sale.first_installment_date is None:
        raise SiteValidationError(guards.PLAN_INPUT_MISSING)

    rows = plan.build_plan(
        sale_price=sale.sale_price,
        down_payment=down_payment,
        installment_count=installment_count,
        first_installment_date=sale.first_installment_date,
        # F119 "Sözleşme imzasında": ayrı bir sözleşme tarihi kolonu YOKTUR
        # (spec §2), kaydın açılış tarihi bu anlamın en yakın karşılığıdır.
        #
        # `created_at` bir `timestamptz`tir ve UTC olarak okunur; ham `.date()`
        # UTC GÜNÜNÜ verirdi. TR gecesi 00:00-03:00 arasında açılan bir satışın
        # peşinatı böylece "dün"e vadelenir ve kayıt DOĞDUĞU ANDA gecikmiş
        # görünürdü (TB5 §1'de kanıtlanan kusur). Gün sınırı görüntüleme saat
        # diliminde okunur.
        down_payment_due_date=timezone.to_display(sale.created_at).date(),
    )

    # --- Buradan itibaren yazma; doğrulama YOK. ---
    for row in mevcut:
        await session.delete(row)
    await session.flush()
    session.add_all(
        [
            SaleInstallment(
                sale_id=sale.id,
                sequence_no=planned.sequence_no,
                label=planned.label,
                due_date=planned.due_date,
                amount=planned.amount,
            )
            for planned in rows
        ]
    )
    await session.flush()
    response = await _plan_response(session, sale, timezone.today())
    detail = messages.sale_plan_generated(
        project.name, await _unit_label(session, sale), len(response.items)
    )
    return response, detail


# --- 2) PUT installments (DEĞİŞTİRME semantiği) ---


def _resolve_inputs(
    items: list[SaleInstallmentInput],
    sale: UnitSale,
    existing: dict[int, SaleInstallment],
) -> None:
    """Gövdenin TÜM kurallarını yazmadan ÖNCE koşturur (`lines._resolve` deseni).

    Sıra: gövde-içi çift → toplam eşitliği → tahsilatlı satır korumaları.
    """
    seen: set[int] = set()
    total = _ZERO
    for entry in items:
        if entry.sequence_no in seen:
            raise DuplicateError(guards.DUPLICATE_SEQUENCE_NO)
        seen.add(entry.sequence_no)
        total += entry.amount

        current = existing.get(entry.sequence_no)
        if current is not None and entry.amount < current.paid_amount:
            raise SiteValidationError(guards.PAID_INSTALLMENT_BELOW_PAID)

    if total != sale.sale_price:
        raise SiteValidationError(guards.INSTALLMENT_TOTAL_MISMATCH)

    # Gövdeden DÜŞEN tahsilatlı satır: 409. Sessizce silinseydi işlenmiş tahsilat
    # kaybolur, satışın "Tahsil Edilen" türevi (S153) kendiliğinden geri düşerdi.
    if any(row.paid_amount > 0 for seq, row in existing.items() if seq not in seen):
        raise ConflictError(guards.PAID_INSTALLMENT_REMOVED)


async def save_installments(
    session: AsyncSession, actor: User, sale_id: uuid.UUID, data: SaleInstallmentsSave
) -> tuple[SalePlanResponse, str]:
    """Gövde planın YENİ HÂLİDİR; geçmeyen satır SİLİNİR (⚠️ DEĞİŞTİRME).

    Var olan satır KORUNUR (kimliği, `paid_amount`ı ve `paid_at`i ile) —
    eşleştirme `sequence_no` üzerindendir, çünkü satırın doğal anahtarı odur
    (UQ `uq_sale_installments_sale_sequence`). Silip yeniden eklemek tahsilat
    geçmişini kimliksizleştirirdi.
    """
    sale, project = await guards.visible_sale(session, actor, sale_id)

    # Kilit ÖNCE (TB1 deseni): doğrulamayı besleyen `list_installments`
    # okumasından da önce — aksi hâlde eşzamanlı `pay` araya girer ve tutarı
    # düşürülen satır aşırı ödenmiş kalırdı.
    await repository.lock_installments(session, sale.id)
    rows = await repository.list_installments(session, sale.id)
    existing = {row.sequence_no: row for row in rows}

    _resolve_inputs(data.items, sale, existing)

    # --- Buradan itibaren yazma; doğrulama YOK. ---
    gonderilen = {entry.sequence_no for entry in data.items}
    for sequence_no, row in existing.items():
        if sequence_no not in gonderilen:
            await session.delete(row)

    for entry in data.items:
        row = existing.get(entry.sequence_no)
        if row is None:
            # `paid_amount` AÇIKÇA 0 verilir: sütun varsayılanı (`default=0`)
            # ancak flush anında uygulanır, oysa `_sync_paid_at` daha ÖNCE okur.
            row = SaleInstallment(sale_id=sale.id, sequence_no=entry.sequence_no, paid_amount=_ZERO)
            session.add(row)
        row.label = entry.label
        row.due_date = entry.due_date
        row.amount = entry.amount
        row.payment_method = entry.payment_method
        _sync_paid_at(row)
    await session.flush()
    response = await _plan_response(session, sale, timezone.today())
    detail = messages.sale_plan_saved(
        project.name, await _unit_label(session, sale), len(response.items)
    )
    return response, detail


# --- 3) pay (§8 S2) ---


async def pay_installment(
    session: AsyncSession, actor: User, installment_id: uuid.UUID, data: InstallmentPayInput
) -> tuple[SaleInstallmentResponse, str]:
    """Taksit üzerine ELLE tahsilat işler (hazine entegrasyonu YOK, spec §5).

    Satır `visible_installment` içinde `FOR UPDATE` ile kilitli okunur; aşağıdaki
    "bakiye" hesabı o kilitli okumadan beslenir, dolayısıyla iki eşzamanlı
    tahsilat SERİLEŞTİRİLİR (bkz. `tests/sales/test_installment_concurrency.py`).
    """
    installment, sale, project = await guards.visible_installment(session, actor, installment_id)

    if installment.paid_amount + data.amount > installment.amount:
        raise SiteValidationError(guards.PAYMENT_EXCEEDS_INSTALLMENT)

    installment.paid_amount = installment.paid_amount + data.amount
    _sync_paid_at(installment)
    await session.flush()
    detail = messages.sale_installment_paid(
        project.name, await _unit_label(session, sale), installment.label, data.amount
    )
    return _installment_response(installment, timezone.today()), detail
