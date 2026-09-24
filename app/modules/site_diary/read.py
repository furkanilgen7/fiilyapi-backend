"""Şantiye günlüğü OKUMA yolu (T2) — detay ve liste yanıtlarının kurulumu.

`service.py`den ayrı durur (taşeron hakedişi modülünün aynı gerekçesi): yazma
yolu (kapsam + kilit + kurallar) ile okuma yolu (yanıt inşası) farklı hızda
değişir; T3 satır türevlerini, T4 durum alanlarını BURAYA ekleyecektir.

Yön TEK taraflıdır: bu modül `service`in kapsam yardımcılarını çağırır, `service`
buradan hiçbir şey İMPORT ETMEZ — döngüsel import doğmaz.
"""

import uuid
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.progress_payments.calculations import quantize2
from app.modules.site_diary import repository
from app.modules.site_diary.models import SiteDiaryEntry, SiteDiaryLine
from app.modules.site_diary.schemas import (
    SiteDiaryEntryDetail,
    SiteDiaryEntryListItem,
    SiteDiaryEntryListResponse,
    SiteDiaryLineRead,
    SiteDiaryWorkerCountRead,
)
from app.modules.site_diary.service import EntryContext, visible_entry, visible_site
from app.modules.users.models import User

_ZERO_MONEY = Decimal("0.00")
_ZERO_QUANTITY = Decimal("0.000")


def line_amount(line: SiteDiaryLine) -> Decimal:
    """GK230 ₺ katkısı — KATSAYISIZ `quantity × unit_price` (spec §2).

    Yuvarlama `progress_payments.calculations.quantize2`den gelir (`Numeric(18,2)`,
    `ROUND_HALF_UP`): projede TEK para yuvarlama kuralı vardır, ikinci bir kopya
    zamanla kuruş farkı üretirdi.
    """
    return quantize2(line.unit_price * line.quantity)


def lines_total(entry: SiteDiaryEntry) -> Decimal:
    """Satır ₺ toplamı — TÜREV (kolon yok). Toplama SATIR BAZINDA yuvarlanmış
    değerler girer: ekranda gösterilen satırların toplamı ile alttaki toplam
    tutmak zorundadır."""
    return sum((line_amount(line) for line in entry.lines), _ZERO_MONEY)


def worker_total(entry: SiteDiaryEntry) -> int:
    """İşçi toplamı — TÜREV (kolon yok, spec §2)."""
    return sum(row.count for row in entry.worker_counts)


def cumulative_quantity(
    line: SiteDiaryLine, prior: dict[uuid.UUID, Decimal], own: dict[uuid.UUID, Decimal]
) -> Decimal:
    """GK229 kümülatifi — TÜREV (kolon yok, spec §2). **KALEM düzeyinde, AY içinde.**

    `prior` = ay başından bu güne kadarki **gönderilmiş** kayıtların poz bazlı
    toplamı (`repository.cumulative_quantities_before`); üstüne BU kaydın o
    kaleme ait BÜTÜN satırlarının (PLN-B2.1: bölümler dahil) miktarı eklenir
    (`own`). Böylece ayın son gönderilmiş kaydında değer `summary`nin kalem
    miktarına BİREBİR eşit kalır (summary docstring'indeki değişmez). Bölüm
    kırılımsız (eski) veride satır başına bir kalem olduğundan değer AYNIDIR.
    Yaprak (kalem × bölüm) kümülatifi ayrı alandır: `leaf_cumulative`.

    Bağı kopmuş satırın (`boq_item_id IS NULL`) geçmişi ADRESLENEMEZ: yalnız
    kendi miktarını gösterir, sessizce başka bir pozun toplamına yazılmaz.
    """
    if line.boq_item_id is None:
        return line.quantity
    return prior.get(line.boq_item_id, _ZERO_QUANTITY) + own[line.boq_item_id]


class _LeafContext(NamedTuple):
    """Yaprak türevlerinin girdileri — kayıt başına SABİT sayıda toplu sorgu."""

    prior: dict[tuple[uuid.UUID, uuid.UUID | None], Decimal]
    allocations: dict[tuple[uuid.UUID, uuid.UUID], Decimal]
    item_quantities: dict[uuid.UUID, Decimal]


async def _leaf_context(session: AsyncSession, entry: SiteDiaryEntry) -> _LeafContext:
    """Üç toplu sorgu (yaprak ön-toplamı · tahsisler · kalem miktarları); satırsız
    ya da yalnız bağı kopmuş satırlı kayıtta HİÇ sorgu açılmaz (N+1 yok)."""
    item_ids = {line.boq_item_id for line in entry.lines if line.boq_item_id is not None}
    if not item_ids:
        return _LeafContext(prior={}, allocations={}, item_quantities={})
    prior = await repository.leaf_cumulative_before(
        session, entry.site_id, entry.entry_date, item_ids
    )
    allocations = await repository.allocations_for_items(session, item_ids)
    items = await repository.get_boq_items_by_ids(session, list(item_ids))
    return _LeafContext(
        prior=prior,
        allocations=allocations,
        item_quantities={item_id: item.quantity for item_id, item in items.items()},
    )


def planned_quantity(line: SiteDiaryLine, leaf: _LeafContext) -> Decimal | None:
    """Yaprağın planlı miktarı (spec §3.9 B1-3).

    Bölümlü: kalemin o bölüme tahsisi (tahsisi sonradan kalkmışsa 0). Bölümsüz:
    kalem miktarı − Σ tahsis, 0'ın altına inmez (K3 invariantı Σ tahsis ≤ miktar;
    korkuluk yine de burada durur). Bağı kopmuş satırda `None`.
    """
    if line.boq_item_id is None or line.boq_item_id not in leaf.item_quantities:
        return None
    if line.section_id is not None:
        return leaf.allocations.get((line.boq_item_id, line.section_id), _ZERO_QUANTITY)
    allocated = sum(
        (qty for (item_id, _), qty in leaf.allocations.items() if item_id == line.boq_item_id),
        _ZERO_QUANTITY,
    )
    return max(leaf.item_quantities[line.boq_item_id] - allocated, _ZERO_QUANTITY)


def leaf_cumulative(line: SiteDiaryLine, leaf: _LeafContext) -> Decimal | None:
    """Yaprak kümülatifi: bu günden ÖNCEKİ gönderilmişler (tüm zamanlar) + bu satır."""
    if line.boq_item_id is None:
        return None
    return leaf.prior.get((line.boq_item_id, line.section_id), _ZERO_QUANTITY) + line.quantity


def _line_read(
    line: SiteDiaryLine,
    prior: dict[uuid.UUID, Decimal],
    own: dict[uuid.UUID, Decimal],
    leaf: _LeafContext,
) -> SiteDiaryLineRead:
    planned = planned_quantity(line, leaf)
    cumulative = leaf_cumulative(line, leaf)
    return SiteDiaryLineRead(
        id=line.id,
        boq_item_id=line.boq_item_id,
        code=line.code,
        description=line.description,
        unit=line.unit,
        unit_price=line.unit_price,
        quantity=line.quantity,
        cumulative_quantity=cumulative_quantity(line, prior, own),
        line_amount=line_amount(line),
        section_id=line.section_id,
        overrun_reason=line.overrun_reason,
        leaf_cumulative_quantity=cumulative,
        planned_quantity=planned,
        remaining_quantity=(
            None if planned is None or cumulative is None else planned - cumulative
        ),
    )


def _own_item_totals(entry: SiteDiaryEntry) -> dict[uuid.UUID, Decimal]:
    totals: dict[uuid.UUID, Decimal] = {}
    for line in entry.lines:
        if line.boq_item_id is not None:
            totals[line.boq_item_id] = totals.get(line.boq_item_id, _ZERO_QUANTITY) + line.quantity
    return totals


async def build_detail(session: AsyncSession, context: EntryContext) -> SiteDiaryEntryDetail:
    """GÖRÜNÜRLÜK KONTROLÜ YAPMAZ — çağıranın kapsam kararını çoktan vermiş
    olması ŞARTTIR. `POST`/`PATCH`/`PUT …/lines` uçları bu yüzden `get_detail`
    değil bunu çağırır: aksi hâlde `visible_projects` sorgusu istek başına İKİ
    KEZ koşardı.

    T3'te `async` oldu: kümülatif türevi (GK229) TEK toplu sorgu ister
    (`prior`, satır başına sorgu YOK). PLN-B2.1 yaprak türevleri üç toplu sorgu
    daha ekler (`_leaf_context`) — kayıt başına SABİT. Sorgular ilişkilere
    DOKUNMAZ, bu yüzden `worker_counts`/`lines` `selectin` yüklemesi bozulmaz.

    `temperature_c` (kullanımdan kalkıyor, B2-2) `temp_max_c`den TÜRETİLİR.
    """
    entry = context.entry
    prior = await repository.cumulative_quantities_before(session, entry.site_id, entry.entry_date)
    own = _own_item_totals(entry)
    leaf = await _leaf_context(session, entry)
    return SiteDiaryEntryDetail(
        id=entry.id,
        site_id=entry.site_id,
        project_id=entry.project_id,
        entry_date=entry.entry_date,
        section_id=entry.section_id,
        weather=entry.weather,
        temperature_c=entry.temp_max_c,
        temp_min_c=entry.temp_min_c,
        temp_max_c=entry.temp_max_c,
        wind_ms=entry.wind_ms,
        work_done=entry.work_done,
        chief_note=entry.chief_note,
        safety_meeting_held=entry.safety_meeting_held,
        ppe_checked=entry.ppe_checked,
        has_incident=entry.has_incident,
        incident_note=entry.incident_note,
        status=entry.status,
        submitted_at=entry.submitted_at,
        created_by=entry.created_by,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
        lines=[_line_read(line, prior, own, leaf) for line in entry.lines],
        worker_counts=[
            SiteDiaryWorkerCountRead(
                id=row.id,
                trade=row.trade,
                source=row.source,
                count=row.count,
                subcontractor_id=row.subcontractor_id,
                hours=row.hours,
            )
            for row in entry.worker_counts
        ],
        lines_total=lines_total(entry),
        worker_total=worker_total(entry),
    )


async def get_detail(
    session: AsyncSession, actor: User, entry_id: uuid.UUID
) -> SiteDiaryEntryDetail:
    return await build_detail(session, await visible_entry(session, actor, entry_id))


async def list_entries(
    session: AsyncSession,
    actor: User,
    site_id: uuid.UUID,
    *,
    year: int | None,
    month: int | None,
    limit: int,
    offset: int,
) -> SiteDiaryEntryListResponse:
    """Kapsam kararı ŞANTİYE üzerinden verilir (`visible_site`): görünmeyen
    şantiyenin listesi boş liste DEĞİL 404'tür — boş liste, "şantiye var ama
    kaydı yok" ile "şantiyeyi göremiyorsun"u aynı cevaba düşürürdü.

    Satır/işçi toplamları `lazy="selectin"` sayesinde ek sorgu ÜRETMEZ: iki
    ilişki de sayfa başına TEK ek sorguda toplu yüklenir (N+1 yok).
    """
    site, _ = await visible_site(session, actor, site_id)
    entries = await repository.list_entries(
        session, site.id, year=year, month=month, limit=limit, offset=offset
    )
    total = await repository.count_entries(session, site.id, year=year, month=month)
    return SiteDiaryEntryListResponse(
        items=[
            SiteDiaryEntryListItem(
                id=entry.id,
                site_id=entry.site_id,
                project_id=entry.project_id,
                entry_date=entry.entry_date,
                section_id=entry.section_id,
                weather=entry.weather,
                has_incident=entry.has_incident,
                status=entry.status,
                worker_total=worker_total(entry),
                lines_total=lines_total(entry),
                created_by=entry.created_by,
                created_at=entry.created_at,
            )
            for entry in entries
        ],
        total=total,
        limit=limit,
        offset=offset,
    )
