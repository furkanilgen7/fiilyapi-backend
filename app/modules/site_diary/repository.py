"""Şantiye günlüğü okuma/yazma sorguları (T2).

`subcontractor_progress_payments/repository.py` deseninin aynısı: filtreler SQL
düzeyinde uygulanır, kapsam kararı HER ZAMAN çağıran servisten gelir — bu modül
KENDİSİ görünürlük kararı VERMEZ (iki katman kuralı).
"""

import calendar
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.models import BoqItem
from app.modules.site_diary.models import DiaryStatus, SiteDiaryEntry, SiteDiaryLine
from app.modules.sites.models import Section, Site


async def get_entry(session: AsyncSession, entry_id: uuid.UUID) -> SiteDiaryEntry | None:
    """`session.get` DEĞİL açık `select` + `populate_existing`.

    `session.get` kimlik haritasındaki nesneyi SORGU KOŞMADAN döndürür; o nesne
    aynı oturumda `SiteDiaryEntry(...)` ile kurulmuşsa `worker_counts` ilişkisi
    HİÇ yüklenmemiş olur ve `lazy="selectin"` devreye girmez — okuma yolu senkron
    olduğu için erişim anında `MissingGreenlet` ile patlar (ampirik olarak
    doğrulandı: T2 detay testi bu yüzden kırmızıydı).

    Açık `select` her çağrıda sorguyu koşar, `populate_existing` kimlik
    haritasındaki nesneyi TAZELER ve iki `selectin` ilişkisi de yüklenir
    (toplam 3 sorgu, N+1 yok).
    """
    stmt = (
        select(SiteDiaryEntry)
        .where(SiteDiaryEntry.id == entry_id)
        .execution_options(populate_existing=True)
    )
    return (await session.execute(stmt)).scalars().first()


async def get_entry_locked(session: AsyncSession, entry_id: uuid.UUID) -> SiteDiaryEntry | None:
    """`SELECT … FOR UPDATE`. `populate_existing=True` ZORUNLUDUR: kimlik
    haritasındaki ESKİ nesne dönerse kilit alınmış ama DURUM eski değerinden
    okunmuş olur — var gibi görünen, aslında olmayan bir koruma
    (`subcontractor_progress_payments.repository.get_payment_locked` dersi).
    """
    return await session.get(SiteDiaryEntry, entry_id, with_for_update=True, populate_existing=True)


async def get_entry_by_date(
    session: AsyncSession,
    site_id: uuid.UUID,
    entry_date: date,
    *,
    exclude_entry_id: uuid.UUID | None = None,
) -> SiteDiaryEntry | None:
    """UQ (site_id, entry_date) ÖN KONTROLÜ — `IntegrityError`a düşmeden 409.

    `exclude_entry_id` PATCH yolu içindir: kaydın kendi tarihini kendisiyle
    çakıştırması (aynı tarihi yeniden göndermek) bir çakışma DEĞİLDİR.
    """
    stmt = select(SiteDiaryEntry).where(
        SiteDiaryEntry.site_id == site_id,
        SiteDiaryEntry.entry_date == entry_date,
    )
    if exclude_entry_id is not None:
        stmt = stmt.where(SiteDiaryEntry.id != exclude_entry_id)
    return (await session.execute(stmt)).scalars().first()


async def get_section_with_site(
    session: AsyncSession, section_id: uuid.UUID
) -> tuple[Section, Site] | None:
    """Bölüm + şantiyesi TEK sorguda — `section_id` sahiplik kontrolü."""
    stmt = (
        select(Section, Site).join(Site, Site.id == Section.site_id).where(Section.id == section_id)
    )
    row = (await session.execute(stmt)).first()
    return (row[0], row[1]) if row is not None else None


async def list_boq_items(session: AsyncSession, site_id: uuid.UUID) -> list[BoqItem]:
    """Satır iskeletinin KAYNAĞI (spec §2): şantiyenin TÜM BOQ pozları.

    Poz kaynağı BOQ'dur; grup kırılımı satıra TAŞINMAZ (GK'de satır listesi
    düzdür), bu yüzden gruplar üzerinden değil doğrudan kalemler okunur.
    Sıralama `code`tur: satır ilişkisi de (`SiteDiaryLine.code`) böyle sıralanır,
    iki farklı sıra iki farklı ekran görüntüsü demek olurdu.
    """
    stmt = select(BoqItem).where(BoqItem.site_id == site_id).order_by(BoqItem.code)
    return list((await session.execute(stmt)).scalars().all())


async def get_boq_items_by_ids(
    session: AsyncSession, item_ids: list[uuid.UUID]
) -> dict[uuid.UUID, BoqItem]:
    """`PUT …/lines` gövdesindeki TÜM pozlar TEK sorguda (satır başına sorgu YOK).

    Şantiye süzgeci BURADA uygulanmaz: sahiplik kararı çağıran katmanın işidir
    (`lines._resolve`), çünkü "poz yok" ile "poz başka şantiyenin" AYNI cevabı
    almalıdır ve bu karar bir SORGU değil bir KURALDIR.
    """
    if not item_ids:
        return {}
    stmt = select(BoqItem).where(BoqItem.id.in_(item_ids))
    return {item.id: item for item in (await session.execute(stmt)).scalars().all()}


async def cumulative_quantities_before(
    session: AsyncSession, site_id: uuid.UUID, entry_date: date
) -> dict[uuid.UUID, Decimal]:
    """GK229 kümülatifinin ÖN-TOPLAMI: aynı ayda, aynı şantiyede, bu günden ÖNCE
    **gönderilmiş** kayıtların poz bazlı miktar toplamı.

    `submitted` süzgeci T4 `summary` ucuyla (spec §3) BİLEREK aynıdır: iki ekran
    aynı sayıyı söylemek zorundadır. Kaydın KENDİ miktarı buraya girmez —
    okuma katmanı onu üstüne ekler (`read._line_read`), böylece taslak da
    "gönderirsem ne olacak" değerini gösterir.

    Bağı kopmuş satır (`boq_item_id IS NULL`) hangi poza yazılacağını KAYBETMİŞTİR;
    toplamdan düşer (taşeron `completed_quantities` deseninin aynısı).
    """
    start, _ = _month_bounds(entry_date.year, entry_date.month)
    stmt = (
        select(SiteDiaryLine.boq_item_id, func.sum(SiteDiaryLine.quantity))
        .join(SiteDiaryEntry, SiteDiaryEntry.id == SiteDiaryLine.entry_id)
        .where(
            SiteDiaryEntry.site_id == site_id,
            SiteDiaryEntry.status == DiaryStatus.submitted,
            SiteDiaryEntry.entry_date >= start,
            SiteDiaryEntry.entry_date < entry_date,
            SiteDiaryLine.boq_item_id.is_not(None),
        )
        .group_by(SiteDiaryLine.boq_item_id)
    )
    return {item_id: total for item_id, total in (await session.execute(stmt)).all()}


def _month_bounds(year: int, month: int | None) -> tuple[date, date]:
    """Yarı-açık aralık yerine KAPALI aralık: `entry_date` bir `Date`tir, saat
    bileşeni yoktur, bu yüzden `BETWEEN` gün sınırlarını kaçırmaz."""
    if month is None:
        return date(year, 1, 1), date(year, 12, 31)
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def _list_stmt(site_id: uuid.UUID, *, year: int | None, month: int | None):
    """Liste ve sayaç sorgusunun PAYLAŞTIĞI `WHERE` gövdesi.

    İki sorgu ayrı süzgeç kopyası taşısaydı `total` ile `items` zamanla farklı
    kümeleri sayardı — sayfalamanın en sinsi hatası.
    """
    stmt = select(SiteDiaryEntry).where(SiteDiaryEntry.site_id == site_id)
    if year is not None:
        start, end = _month_bounds(year, month)
        stmt = stmt.where(SiteDiaryEntry.entry_date.between(start, end))
    return stmt


async def list_entries(
    session: AsyncSession,
    site_id: uuid.UUID,
    *,
    year: int | None,
    month: int | None,
    limit: int,
    offset: int,
) -> list[SiteDiaryEntry]:
    """ "Son Kayıtlar": en YENİ gün önce. Eşitlik durumu UQ nedeniyle imkânsızdır
    ama `id` ikincil sıra olarak durur — sayfalamanın deterministik olması için."""
    stmt = (
        _list_stmt(site_id, year=year, month=month)
        .order_by(SiteDiaryEntry.entry_date.desc(), SiteDiaryEntry.id)
        .limit(limit)
        .offset(offset)
    )
    return list((await session.execute(stmt)).scalars().all())


async def count_entries(
    session: AsyncSession, site_id: uuid.UUID, *, year: int | None, month: int | None
) -> int:
    inner = _list_stmt(site_id, year=year, month=month).with_only_columns(SiteDiaryEntry.id)
    stmt = select(func.count()).select_from(inner.subquery())
    return int((await session.execute(stmt)).scalar_one())
