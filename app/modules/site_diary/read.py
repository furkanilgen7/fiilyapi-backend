"""Şantiye günlüğü OKUMA yolu (T2) — detay ve liste yanıtlarının kurulumu.

`service.py`den ayrı durur (taşeron hakedişi modülünün aynı gerekçesi): yazma
yolu (kapsam + kilit + kurallar) ile okuma yolu (yanıt inşası) farklı hızda
değişir; T3 satır türevlerini, T4 durum alanlarını BURAYA ekleyecektir.

Yön TEK taraflıdır: bu modül `service`in kapsam yardımcılarını çağırır, `service`
buradan hiçbir şey İMPORT ETMEZ — döngüsel import doğmaz.
"""

import uuid
from decimal import Decimal

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


def _line_read(line: SiteDiaryLine) -> SiteDiaryLineRead:
    return SiteDiaryLineRead(
        id=line.id,
        boq_item_id=line.boq_item_id,
        code=line.code,
        description=line.description,
        unit=line.unit,
        unit_price=line.unit_price,
        quantity=line.quantity,
        line_amount=line_amount(line),
    )


def build_detail(context: EntryContext) -> SiteDiaryEntryDetail:
    """GÖRÜNÜRLÜK KONTROLÜ YAPMAZ — çağıranın kapsam kararını çoktan vermiş
    olması ŞARTTIR. `POST`/`PATCH` uçları bu yüzden `get_detail` değil bunu
    çağırır: aksi hâlde `visible_projects` sorgusu istek başına İKİ KEZ koşardı.
    """
    entry = context.entry
    return SiteDiaryEntryDetail(
        id=entry.id,
        site_id=entry.site_id,
        project_id=entry.project_id,
        entry_date=entry.entry_date,
        section_id=entry.section_id,
        weather=entry.weather,
        temperature_c=entry.temperature_c,
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
        lines=[_line_read(line) for line in entry.lines],
        worker_counts=[
            SiteDiaryWorkerCountRead(id=row.id, trade=row.trade, source=row.source, count=row.count)
            for row in entry.worker_counts
        ],
        lines_total=lines_total(entry),
        worker_total=worker_total(entry),
    )


async def get_detail(
    session: AsyncSession, actor: User, entry_id: uuid.UUID
) -> SiteDiaryEntryDetail:
    return build_detail(await visible_entry(session, actor, entry_id))


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
