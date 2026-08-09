"""Taşeron hakediş satırlarının TEK yazma yolu (T3; spec §2 guard'ı, §4 kota).

## ⚠️ Semantik: DEĞİŞTİRME (replace)

`PUT /subcontractor-progress-payments/{id}/lines` gövdesi ekranın TAMAMIDIR:
gövdede geçmeyen satır **SİLİNİR**. İşveren `progress_payments/lines.py` ile
AYNI semantik, `PUT …/contract/distribution` BİRLEŞTİRMESİNİN tersidir.

## İşveren modülünden İKİ FARK (bilinçli, şef kararı 2026-08-02)

1. **Şantiye kırılımı YOK.** Hücre kimliği tek başına `contract_item_id`'dir —
   taşeron sözleşmesi zaten tek şantiyeye (ya da proje geneline) bağlıdır.
2. **Fiyat farkı katsayısı KİLİTSİZ.** `subcontractor_contracts`ta
   `has_price_escalation` kolonu YOKTUR ve bu dilimde açılmaz; işverendeki
   `guards.validate_coefficient` kilidi taşerona UYGULANMAZ. Tek doğrulama
   `coefficient > 0`'dır ve Pydantic'te durur (`schemas.py`).

## Sıra — ÖNCE TÜM DOĞRULAMALAR, SONRA TEK YAZMA

`_resolve` hiçbir şey YAZMAZ, `_apply` hiçbir şey DOĞRULAMAZ (işveren H5'in
"kısmi yazma bırakma" dersi): ikinci satırda patlayan istek birincisini
session'a eklemiş olmamalıdır.
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DuplicateError, SiteValidationError
from app.modules.contracts import repository as contracts_repository
from app.modules.contracts.models import SubcontractorContract, SubcontractorContractItem
from app.modules.site_diary import bridge
from app.modules.subcontractor_progress_payments import guards, repository
from app.modules.subcontractor_progress_payments.models import (
    QuantitySource,
    SubcontractorProgressPayment,
    SubcontractorProgressPaymentLine,
)
from app.modules.subcontractor_progress_payments.schemas import (
    SubcontractorProgressPaymentLineInput,
)

_ZERO = Decimal("0")


@dataclass(frozen=True)
class _ResolvedLine:
    """Doğrulaması BİTMİŞ satır planı — henüz hiçbir şey yazılmadı."""

    item: SubcontractorContractItem
    group_name: str | None
    quantity: Decimal
    coefficient: Decimal
    sort_order: int
    # SD-2 damgası (TB4 B1): SUNUCUDA türetilir, gövdeden ALINMAZ.
    quantity_source: QuantitySource


def completed_quantities(
    payments: list[SubcontractorProgressPayment],
) -> dict[uuid.UUID, Decimal]:
    """Kalem → kümülatif miktar; SORGUSUZ gövde (toplama kuralının TEK kopyası).

    Bağı kopmuş satır (`contract_item_id IS NULL`, FK `SET NULL`) hangi kaleme
    yazılacağını KAYBETMİŞTİR; kümülatiften kalıcı olarak DÜŞER — ONAYLI SAPMA,
    işveren §6.5 notunun (H6 denetimi D3) taşeron karşılığı. T4'ün onay anındaki
    yeniden doğrulaması da AYNI gövdeden okur, ikinci bir toplama açılmaz.
    """
    totals: dict[uuid.UUID, Decimal] = {}
    for prior in payments:
        for line in prior.lines:
            if line.contract_item_id is None:
                continue
            totals[line.contract_item_id] = totals.get(line.contract_item_id, _ZERO) + line.quantity
    return totals


async def completed_quantities_for(
    session: AsyncSession,
    contract_id: uuid.UUID,
    *,
    exclude_payment_id: uuid.UUID | None = None,
) -> dict[uuid.UUID, Decimal]:
    """`completed_quantities`in sorgulu hâli — kota TAM kümeden (sırasız) okunur.

    Kota bir TOPLAM kısıtıdır: sıra tabanlı okunsaydı büyük sıra numaralı bir
    hakediş önce onaylandığında küçük numaralı onu "önceki" saymaz ve onay
    sırasını değiştirmek tavanı aşmanın meşru bir yolu olurdu.
    """
    payments = await repository.list_completed_payments(
        session, contract_id, exclude_payment_id=exclude_payment_id
    )
    return completed_quantities(payments)


def check_quota(
    item: SubcontractorContractItem, completed_quantity: Decimal, quantity: Decimal
) -> None:
    """Spec §4 tavanı: `kümülatif + bu satır ≤ subcontractor_contract_items.quantity`.

    T4 (onay anındaki sırasız TAM küme yeniden doğrulaması) BU fonksiyonu
    yeniden çağırır — kural iki kopya OLMAZ. Buradaki imza bilinçli olarak
    "artış" bilgisi TAŞIMAZ: artış inceltmesi yalnız satır YAZMA yolunun
    kuralıdır (aşağıdaki `_resolve` gerekçesi), onayda GEÇERSİZDİR.
    """
    if completed_quantity + quantity > item.quantity:
        raise SiteValidationError(
            guards.quantity_exceeds_quota(item.code, item.quantity - completed_quantity, item.unit)
        )


def _stamp(
    diary_totals: dict[uuid.UUID, Decimal], item_id: uuid.UUID, quantity: Decimal
) -> QuantitySource:
    """Damgaya ÇEVİRME kuralının TEK kopyası (işveren `lines._stamp` ikizi).

    İki çağıranı vardır — satır yazma yolu (`_resolve`) ve dönem değişince
    yeniden damgalama (`restamp_for_period`); ikinci bir kopya, bir yolda
    `diary`, diğerinde `manual` üreten sessiz bir ayrışma demek olurdu.
    """
    return (
        QuantitySource.diary
        if bridge.is_diary_quantity(diary_totals.get(item_id), quantity)
        else QuantitySource.manual
    )


async def restamp_for_period(
    session: AsyncSession,
    contract: SubcontractorContract,
    payment: SubcontractorProgressPayment,
) -> None:
    """Hakedişin DÖNEMİ değiştiğinde (`PATCH …/{id}`) MEVCUT satırların damgasını
    yeniden türetir — T5 bulgusu; işveren `lines.restamp_for_period` ikizi.

    Satırlara hiç dokunmayan bir `PATCH` dönemi taşıdığında eski dönemin
    günlüğüyle eşleştiği için `diary` damgalanmış satır, yeni dönemle hiç
    ilgisi olmadan rozetli kalırdı. Miktarlar DEĞİŞMEZ; yalnız iddia yeniden
    sınanır ve kural `_resolve` ile aynı tek kaynaktan (`site_diary.bridge` +
    `_stamp`) okunur.
    """
    diary_totals = await bridge.subcontractor_period_totals(
        session,
        contract.id,
        contract.site_id,
        year=payment.period_year,
        month=payment.period_month,
    )
    for line in payment.lines:
        if line.contract_item_id is None:
            # Bağı kopmuş satır hangi kaleme ait olduğunu KAYBETMİŞTİR: günlük
            # toplamıyla kıyaslanamaz → iddia düşer.
            line.quantity_source = QuantitySource.manual
            continue
        line.quantity_source = _stamp(diary_totals, line.contract_item_id, line.quantity)


async def _resolve(
    session: AsyncSession,
    contract: SubcontractorContract,
    inputs: list[SubcontractorProgressPaymentLineInput],
    *,
    default_coefficient: Decimal,
    exclude_payment_id: uuid.UUID | None,
    existing: dict[uuid.UUID, SubcontractorProgressPaymentLine],
    period: tuple[int | None, int | None],
) -> list[_ResolvedLine]:
    """Gövde-içi çift → kalem-sözleşme sahipliği → fiyat guard'ı → kota tavanı.

    **Hiçbir yazma YAPMAZ.** Sorgular satır başına DEĞİL, gövdenin tamamı için
    toplu koşar (N+1 yok).

    `existing` = bu hakedişte HÂLİHAZIRDA duran satırlar. İki kural buradan
    okur: katsayı öntanımı (yalnız YENİ satıra iner) ve kotanın ARTIŞ koşulu.

    `period` = hakedişin KENDİ dönemi — SD-2 damgasının (TB4 B1) süzgeci. Günlük
    toplamı gövdenin tamamı için TEK kez okunur; köprü işveren ailesiyle AYNI
    kaynaktan (`site_diary.bridge`) gelir.
    """
    item_ids = [entry.contract_item_id for entry in inputs]
    items = await repository.get_contract_items_by_ids(session, item_ids)
    completed = await completed_quantities_for(
        session, contract.id, exclude_payment_id=exclude_payment_id
    )
    item_groups = await group_names(session, list(items.values()))
    period_year, period_month = period
    diary_totals = await bridge.subcontractor_period_totals(
        session, contract.id, contract.site_id, year=period_year, month=period_month
    )

    seen: set[uuid.UUID] = set()
    resolved: list[_ResolvedLine] = []
    for index, entry in enumerate(inputs):
        if entry.contract_item_id in seen:
            raise DuplicateError(guards.DUPLICATE_LINE)
        seen.add(entry.contract_item_id)

        item = items.get(entry.contract_item_id)
        if item is None or item.contract_id != contract.id:
            # Var olmayan kalem ile BAŞKA sözleşmenin kalemi AYNI 422'yi alır
            # (IDOR yüzeyi: kimlik varlığı sızdırılmaz).
            raise SiteValidationError(guards.ITEM_CONTRACT_MISMATCH)
        if item.unit_price is None:
            # "Girilmedi ≠ 0 TL" (spec §2): satır `contract_unit_price` NOT NULL'dur.
            raise SiteValidationError(guards.ITEM_PRICE_REQUIRED)

        existing_line = existing.get(entry.contract_item_id)
        current_quantity = _ZERO if existing_line is None else existing_line.quantity

        # Kontrol YALNIZ ARTIŞTA koşar (işveren H5 denetimi O1 dersi): sözleşme
        # miktarı SONRADAN düşürülürse taslakta duran satır zaten aşmış olur —
        # kural azaltmaya da uygulansaydı kullanıcı `quantity: 0` göndererek bile
        # taslağı kurtaramaz, hakediş kilitlenirdi. Yeni satırda "mevcut miktar"
        # 0'dır, yani kotayı aşan YENİ satır bu inceltmeden faydalanmaz.
        if entry.quantity > current_quantity:
            check_quota(item, completed.get(item.id, _ZERO), entry.quantity)

        coefficient = entry.coefficient
        if coefficient is None:
            coefficient = (
                default_coefficient if existing_line is None else existing_line.coefficient
            )

        # SD-2 (kullanıcı kararı S1): damga HER PUT'ta yeniden türetilir —
        # miktar günlük toplamından ayrıldığı anda kaynak iddiası düşer.
        quantity_source = _stamp(diary_totals, item.id, entry.quantity)

        resolved.append(
            _ResolvedLine(
                item=item,
                group_name=item_groups.get(item.source_contract_item_id),
                quantity=entry.quantity,
                coefficient=coefficient,
                quantity_source=quantity_source,
                # `sort_order` gönderilmezse GÖVDE SIRASI otoritedir (işveren
                # deseni): ekran satırları zaten görünen sırada gönderir.
                sort_order=index if entry.sort_order is None else entry.sort_order,
            )
        )
    return resolved


async def group_names(
    session: AsyncSession, items: list[SubcontractorContractItem]
) -> dict[uuid.UUID, str | None]:
    """`source_contract_item_id → employer_contract_groups.name` zinciri, TEK sorguda.

    `service._build_lines` ile AYNI kaynaktan (`contracts.repository.
    get_employer_item_groups`) okur — grup adı snapshot'ının ikinci bir çözüm
    yolu AÇILMAZ.
    """
    source_ids = [item.source_contract_item_id for item in items if item.source_contract_item_id]
    rows = await contracts_repository.get_employer_item_groups(session, source_ids)
    return {item_id: group_name for item_id, _, group_name in rows}


def _new_line(plan: _ResolvedLine) -> SubcontractorProgressPaymentLine:
    """Snapshot beşlisi YALNIZ yeni satırda kalemden kopyalanır; mevcut satırın
    snapshot'ı DONMUŞTUR (tazeleme yalnız `refresh-prices` ucundadır).

    `quantity_source` istekten ALINMAZ (bilinçli kural SÜRER: istekten alınması
    `diary` rozetini sahte doldurmanın yolu olurdu) — değeri TB4 B1 ile
    SUNUCUDA türetilir (`_resolve` → `site_diary.bridge`).
    """
    return SubcontractorProgressPaymentLine(
        contract_item_id=plan.item.id,
        code=plan.item.code,
        description=plan.item.description,
        unit=plan.item.unit,
        contract_unit_price=plan.item.unit_price,
        coefficient=plan.coefficient,
        quantity=plan.quantity,
        group_name=plan.group_name,
        quantity_source=plan.quantity_source,
    )


async def apply_lines(
    session: AsyncSession,
    contract: SubcontractorContract,
    payment: SubcontractorProgressPayment,
    inputs: list[SubcontractorProgressPaymentLineInput],
) -> int:
    """Gövdeyi hakedişe uygular (DEĞİŞTİRME semantiği); düşen bağı-kopmuş satır
    sayısını döner.

    Var olan satır KORUNUR (kimliği ve snapshot'ı ile), yalnız miktar/katsayı/
    sıra güncellenir. Kalemi silinmiş satır gövdeden ADRESLENEMEZ, bu yüzden ilk
    kaydetmede düşer — kaçınılmaz ama SESSİZ değil: sayısı döndürülür ve yanıtın
    `dropped_orphan_count` alanıyla kullanıcıya bildirilir.
    """
    existing = {
        line.contract_item_id: line for line in payment.lines if line.contract_item_id is not None
    }
    dropped_orphan_count = sum(1 for line in payment.lines if line.contract_item_id is None)
    resolved = await _resolve(
        session,
        contract,
        inputs,
        default_coefficient=payment.default_coefficient,
        exclude_payment_id=payment.id,
        existing=existing,
        period=(payment.period_year, payment.period_month),
    )

    # --- Buradan itibaren yazma; doğrulama YOK (yukarıdaki sıra kısıtı). ---
    new_lines: list[SubcontractorProgressPaymentLine] = []
    for plan in resolved:
        line = existing.get(plan.item.id)
        if line is None:
            line = _new_line(plan)
        else:
            line.quantity = plan.quantity
            line.coefficient = plan.coefficient
            # Damga TAZELENİR (SD-2): eski `diary` iddiası miktarla birlikte düşer.
            line.quantity_source = plan.quantity_source
        line.sort_order = plan.sort_order
        new_lines.append(line)
    payment.lines = new_lines
    await session.flush()
    return dropped_orphan_count


async def refresh_snapshots(session: AsyncSession, payment: SubcontractorProgressPayment) -> int:
    """`POST …/refresh-prices`in satır tarafı: snapshot BEŞLİSİNİ kalemden
    yeniden kopyalar, tazelenen satır sayısını döner.

    Snapshot kuralı (hangi beş alan, hangi kaynaktan) bu modülde TEK kopyadır —
    `_new_line` ile aynı beşliyi yazar, `service.py` kuralı TEKRARLAMAZ.

    * `coefficient`/`quantity` KULLANICI verisidir, DOKUNULMAZ.
    * Bağı kopmuş (`contract_item_id IS NULL`) ya da fiyatı geri çekilmiş kalem
      atlanır: satır SİLİNMEZ, yalnız sayaca girmez (`contract_unit_price` NOT
      NULL'dur, NULL yazılamaz — eski snapshot korunur).
    * Beş alanın TAMAMI aynıysa satır yazılmaz (gereksiz `UPDATE` yok; no-op
      tazeleme 0 döner).
    """
    item_ids = [line.contract_item_id for line in payment.lines if line.contract_item_id]
    items = await repository.get_contract_items_by_ids(session, item_ids)
    item_groups = await group_names(session, list(items.values()))

    refreshed_count = 0
    for line in payment.lines:
        item = items.get(line.contract_item_id) if line.contract_item_id else None
        if item is None or item.unit_price is None:
            continue
        group_name = item_groups.get(item.source_contract_item_id)
        if (
            line.code == item.code
            and line.description == item.description
            and line.unit == item.unit
            and line.contract_unit_price == item.unit_price
            and line.group_name == group_name
        ):
            continue
        line.code = item.code
        line.description = item.description
        line.unit = item.unit
        line.contract_unit_price = item.unit_price
        line.group_name = group_name
        refreshed_count += 1
    return refreshed_count
