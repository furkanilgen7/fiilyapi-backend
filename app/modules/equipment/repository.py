"""Ekipman çekirdeği veri erişimi (T1 iskeleti) — yalnız SQL, yetki/kapsam KARARI yok.

Kapsam kararı (`visible_projects`, K20) bu katmanda DEĞİL `service.py`dedir
(`inventory`/`documents` repository deseninin kardeşi); buraya yalnız çözülmüş
proje/şantiye kimlikleri gelir.

Liste ve sayım AYNI süzgeç yardımcısını paylaşır (`inventory` deseni): kopya
açılsaydı `total` ile gösterilen tablo zamanla ayrışırdı.
"""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Row, Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.equipment.models import (
    Equipment,
    EquipmentCategory,
    EquipmentOwnership,
    EquipmentRatePeriod,
    EquipmentStatus,
    EquipmentWorkLog,
    WorkLogType,
)
from app.modules.sites.models import Site


def _like_escape(deger: str) -> str:
    """LIKE joker karakterlerini KAÇIRIR (`inventory.repository` deseni).

    Kaçırılmazsa arama kutusuna `%` yazan kullanıcı TÜM filoyu, `_` yazan ise
    beklemediği satırları görür. Kaçış karakterinin kendisi ÖNCE kaçırılır.
    """
    return deger.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def get_equipment(session: AsyncSession, equipment_id: uuid.UUID) -> Equipment | None:
    """Tekil ekipman — pasifleri DE getirir.

    `is_active=false` süzgeci BURADA UYGULANMAZ: pasif bir ekipmanın kartı
    okunabilmelidir (geçmiş maliyeti hâlâ ona bağlıdır), aksi halde kayıtları
    olan pasif bir makine sistemde erişilemez hale gelirdi. Listenin varsayılan
    süzgeci uç katmanının kararıdır.
    """
    return await session.scalar(select(Equipment).where(Equipment.id == equipment_id))


async def get_equipment_for_update(
    session: AsyncSession, equipment_id: uuid.UUID
) -> Equipment | None:
    """K12 EŞİK = KİLİT kanonu: günlük 24 saat tavanı denetlenmeden ÖNCE
    `equipment` satırı kilitlenir.

    Kilitsiz bir eşik denetimi iki eşzamanlı çalışma kaydında HER İKİSİNİ de
    geçirir (İK-2 K2 / İK-3 dersi) ve tek istekli test bunu GÖRMEZ. Kilit sırası
    tüm uçlarda SABİTTİR: önce `equipment`, sonra kayıt satırları.
    """
    return await session.scalar(
        select(Equipment).where(Equipment.id == equipment_id).with_for_update()
    )


# --- Görünürlük süzgeci (K20) ---


def scope(stmt: Select, project_ids: list[uuid.UUID]) -> Select:
    """🔴 K20 — ekipman görünürlüğü. İKİ dallıdır ve dallar OR'ludur:

    * `site_id IS NULL` (DEPODAKİ makine) → kapsam süzgecine TABİ DEĞİL;
    * şantiyeli makine → şantiyesinin projesi görünen projeler içinde olmalı.

    Depo dalı OR'dan çıkarılsaydı henüz atanmamış makineyi HİÇ KİMSE göremezdi
    (hiçbir projeye bağlı değildir); şantiye dalı çıkarılsaydı başka projenin
    makinesi sızardı. `inventory._warehouse_scope`un birebir kardeşidir —
    alt sorgu tek seferliktir, kayıt başına sorgu (N+1) AÇILMAZ.
    """
    gorunen_santiyeler = select(Site.id).where(Site.project_id.in_(project_ids))
    return stmt.where(Equipment.site_id.is_(None) | Equipment.site_id.in_(gorunen_santiyeler))


def _filtered(
    stmt: Select,
    project_ids: list[uuid.UUID],
    *,
    status: EquipmentStatus | None,
    category: EquipmentCategory | None,
    site_id: uuid.UUID | None,
    ownership: EquipmentOwnership | None,
    q: str | None,
    is_active: bool | None,
) -> Select:
    """Spec §4'ün beş süzgeci + aktiflik. Hepsi AND'lidir ve kapsam (K20)
    HER ZAMAN üstte kalır: `site_id` süzgeci kapsamı GENİŞLETMEZ, daraltır."""
    stmt = scope(stmt, project_ids)
    if status is not None:
        stmt = stmt.where(Equipment.status == status)
    if category is not None:
        stmt = stmt.where(Equipment.category == category)
    if site_id is not None:
        stmt = stmt.where(Equipment.site_id == site_id)
    if ownership is not None:
        stmt = stmt.where(Equipment.ownership == ownership)
    if q:
        desen = f"%{_like_escape(q)}%"
        stmt = stmt.where(
            Equipment.name.ilike(desen, escape="\\")
            | Equipment.brand.ilike(desen, escape="\\")
            | Equipment.model.ilike(desen, escape="\\")
            | Equipment.plate_no.ilike(desen, escape="\\")
            | Equipment.serial_no.ilike(desen, escape="\\")
        )
    if is_active is not None:
        stmt = stmt.where(Equipment.is_active.is_(is_active))
    return stmt


async def list_equipment(
    session: AsyncSession,
    project_ids: list[uuid.UUID],
    *,
    status: EquipmentStatus | None = None,
    category: EquipmentCategory | None = None,
    site_id: uuid.UUID | None = None,
    ownership: EquipmentOwnership | None = None,
    q: str | None = None,
    is_active: bool | None = None,
    limit: int,
    offset: int,
) -> list[Equipment]:
    """Sıralama DB'de (`ORDER BY name, id`) — sayfalama deterministik olsun.

    İkinci ölçüt olmasaydı aynı adlı iki makine her istekte farklı sırada gelir
    ve sayfalar arasında satır kaybolup tekrarlanabilirdi.
    """
    stmt = _filtered(
        select(Equipment),
        project_ids,
        status=status,
        category=category,
        site_id=site_id,
        ownership=ownership,
        q=q,
        is_active=is_active,
    )
    stmt = stmt.order_by(Equipment.name, Equipment.id).limit(limit).offset(offset)
    return list((await session.execute(stmt)).scalars().all())


async def count_equipment(
    session: AsyncSession,
    project_ids: list[uuid.UUID],
    *,
    status: EquipmentStatus | None = None,
    category: EquipmentCategory | None = None,
    site_id: uuid.UUID | None = None,
    ownership: EquipmentOwnership | None = None,
    q: str | None = None,
    is_active: bool | None = None,
) -> int:
    """Sayım liste ile AYNI süzgeçten geçer: `total` GÖRÜNEN ve SÜZÜLMÜŞ kümeyi
    sayar, tablonun tamamını değil."""
    stmt = _filtered(
        select(func.count()).select_from(Equipment),
        project_ids,
        status=status,
        category=category,
        site_id=site_id,
        ownership=ownership,
        q=q,
        is_active=is_active,
    )
    return (await session.execute(stmt)).scalar_one()


# --- Özet (M1 KPI'ları) ---


async def status_counts(
    session: AsyncSession, project_ids: list[uuid.UUID]
) -> dict[EquipmentStatus, int]:
    """DÖRT durumun sayısı TEK sorguda (K21) — durum başına sorgu AÇILMAZ.

    Yalnız `is_active` makineler sayılır: pasifleştirme silmenin yerine geçer
    (spec §2.1) ve kullanımdan kaldırılmış bir makineyi "Aktif Çalışıyor"
    saymak KPI'ı yalan söyletirdi. Sıfır olan durum sorgudan HİÇ dönmez;
    eksik anahtarı servis 0'a tamamlar.
    """
    stmt = scope(
        select(Equipment.status, func.count()).where(Equipment.is_active.is_(True)), project_ids
    ).group_by(Equipment.status)
    return {satir[0]: satir[1] for satir in (await session.execute(stmt)).all()}


async def worked_hours_by_equipment(
    session: AsyncSession,
    project_ids: list[uuid.UUID],
    *,
    date_from: date,
    date_to: date,
) -> list[Row[tuple[Decimal, Decimal | None, EquipmentRatePeriod | None, int]]]:
    """Dönemin ekipman başına ÇALIŞMA saati + o makinenin bedel künyesi.

    Maliyet BURADA hesaplanmaz — formül `cost.py`dedir (K18) ve SQL'e ikinci kez
    yazılsaydı `DAILY_HOURS` ile fail-closed `null` kuralı iki yerde yaşardı.
    Dönüş satırı hesabın girdilerini taşır, sonucunu değil.

    İki süzgeç birden koşar (K9 + K20): makinenin kendisi görünür olmalı VE
    kaydın KENDİ `site_id`si görünür (ya da NULL) olmalı — makine şantiye
    değiştirdiğinde geçmiş kayıt taşındığı yere değil YAPILDIĞI yere aittir.

    `breakdown` kayıtları DIŞARIDADIR (K10): M3 arızayı ayrı sütunda sayar ve
    para sütununa katmaz.
    """
    gorunen_santiyeler = select(Site.id).where(Site.project_id.in_(project_ids))
    stmt = (
        scope(
            select(
                func.sum(EquipmentWorkLog.hours),
                Equipment.rate_amount,
                Equipment.rate_period,
                Equipment.monthly_capacity_hours,
            ).join(Equipment, Equipment.id == EquipmentWorkLog.equipment_id),
            project_ids,
        )
        .where(
            EquipmentWorkLog.record_type == WorkLogType.worked,
            EquipmentWorkLog.work_date >= date_from,
            EquipmentWorkLog.work_date <= date_to,
            EquipmentWorkLog.site_id.is_(None) | EquipmentWorkLog.site_id.in_(gorunen_santiyeler),
        )
        .group_by(
            Equipment.id,
            Equipment.rate_amount,
            Equipment.rate_period,
            Equipment.monthly_capacity_hours,
        )
    )
    return list((await session.execute(stmt)).all())
