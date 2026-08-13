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

from sqlalchemy import Row, Select, and_, case, func, select
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


# --- Çalışma kaydı (M3 · T4) ---


def work_log_scope(stmt: Select, project_ids: list[uuid.UUID]) -> Select:
    """🔴 K9 + K20 — çalışma kaydının görünürlüğü KENDİ `site_id`sindedir.

    `scope()`un (ekipman) kardeşidir ve aynı iki dallı OR'u taşır: `site_id IS
    NULL` kayıt (depodaki makinenin işi) herkese görünür, şantiyeli kayıt
    şantiyesinin projesi görünüyorsa görünür.

    Ekipmanın BUGÜNKÜ ataması burada KULLANILMAZ: makine şantiye değiştirdiğinde
    geçmiş kayıtların görünürlüğü de geriye dönük değişseydi, dünkü maliyet
    bugün başka bir projeye ait olurdu (K9'un ta kendisi).
    """
    gorunen_santiyeler = select(Site.id).where(Site.project_id.in_(project_ids))
    return stmt.where(
        EquipmentWorkLog.site_id.is_(None) | EquipmentWorkLog.site_id.in_(gorunen_santiyeler)
    )


async def get_work_log(session: AsyncSession, log_id: uuid.UUID) -> EquipmentWorkLog | None:
    return await session.scalar(select(EquipmentWorkLog).where(EquipmentWorkLog.id == log_id))


def _work_log_filtered(
    stmt: Select,
    project_ids: list[uuid.UUID],
    *,
    equipment_id: uuid.UUID | None,
    site_id: uuid.UUID | None,
    date_from: date | None,
    date_to: date | None,
    record_type: WorkLogType | None,
) -> Select:
    """Spec §4'ün beş süzgeci. İKİ kapsam kararı birden koşar (`worked_hours_by_equipment`
    deseni): kaydın kendi şantiyesi VE makinenin kendisi görünür olmalı.

    İkincisi olmasaydı `site_id IS NULL` bir kayıt, görünmeyen bir projeye
    atanmış makinenin varlığını (ve saatini) ele verirdi.
    """
    stmt = scope(
        work_log_scope(stmt, project_ids).join(
            Equipment, Equipment.id == EquipmentWorkLog.equipment_id
        ),
        project_ids,
    )
    if equipment_id is not None:
        stmt = stmt.where(EquipmentWorkLog.equipment_id == equipment_id)
    if site_id is not None:
        stmt = stmt.where(EquipmentWorkLog.site_id == site_id)
    if date_from is not None:
        stmt = stmt.where(EquipmentWorkLog.work_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(EquipmentWorkLog.work_date <= date_to)
    if record_type is not None:
        stmt = stmt.where(EquipmentWorkLog.record_type == record_type)
    return stmt


async def list_work_logs(
    session: AsyncSession,
    project_ids: list[uuid.UUID],
    *,
    equipment_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    record_type: WorkLogType | None = None,
    limit: int,
    offset: int,
) -> list[EquipmentWorkLog]:
    """M3'ün "Son Kayıtlar" paneli: EN YENİ önce.

    İkinci ölçüt (`id`) olmasaydı aynı güne düşen kayıtlar her istekte farklı
    sırada gelir, sayfalar arasında satır kaybolup tekrarlanabilirdi.
    """
    stmt = _work_log_filtered(
        select(EquipmentWorkLog),
        project_ids,
        equipment_id=equipment_id,
        site_id=site_id,
        date_from=date_from,
        date_to=date_to,
        record_type=record_type,
    )
    stmt = (
        stmt.order_by(EquipmentWorkLog.work_date.desc(), EquipmentWorkLog.id)
        .limit(limit)
        .offset(offset)
    )
    return list((await session.execute(stmt)).scalars().all())


async def count_work_logs(
    session: AsyncSession,
    project_ids: list[uuid.UUID],
    *,
    equipment_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    record_type: WorkLogType | None = None,
) -> int:
    stmt = _work_log_filtered(
        select(func.count()).select_from(EquipmentWorkLog),
        project_ids,
        equipment_id=equipment_id,
        site_id=site_id,
        date_from=date_from,
        date_to=date_to,
        record_type=record_type,
    )
    return (await session.execute(stmt)).scalar_one()


async def day_hours_total(
    session: AsyncSession,
    equipment_id: uuid.UUID,
    work_date: date,
    *,
    exclude_log_id: uuid.UUID | None = None,
) -> Decimal:
    """🔴 K12'nin EŞİK OKUMASI: bir ekipmanın bir günündeki saat toplamı.

    KAPSAM SÜZGECİ YOKTUR ve bu bilinçlidir: tavan bir FİZİK kuralıdır (gün 24
    saattir), görünürlük kuralı değil. Süzülseydi kullanıcının göremediği bir
    kayıt tavandan düşer ve makine kâğıt üzerinde 24 saatten fazla çalışırdı.

    `exclude_log_id` PATCH içindir: düzeltilen kayıt KENDİ eski saatiyle
    çakışmamalıdır, yoksa 20 saatlik bir kaydı 22'ye çekmek (20 + 22 = 42)
    imkânsız olurdu.

    Arıza kayıtları DA sayılır (K10 tipi ayırır ama günü uzatmaz).
    """
    stmt = select(func.coalesce(func.sum(EquipmentWorkLog.hours), 0)).where(
        EquipmentWorkLog.equipment_id == equipment_id,
        EquipmentWorkLog.work_date == work_date,
    )
    if exclude_log_id is not None:
        stmt = stmt.where(EquipmentWorkLog.id != exclude_log_id)
    return (await session.execute(stmt)).scalar_one()


# --- Çalışma özeti (M3 ana tablosu · K15) ---


def _log_join_conditions(
    project_ids: list[uuid.UUID],
    *,
    date_from: date,
    date_to: date,
    site_id: uuid.UUID | None,
):
    """Dönem + kapsam koşulları JOIN'in ON'unda durur, WHERE'de DEĞİL.

    WHERE'e konsaydı LEFT JOIN iç birleşime dönüşür ve o ay hiç çalışmamış
    makine (M3'ün Forklift satırı) tablodan tamamen DÜŞERDİ.
    """
    gorunen_santiyeler = select(Site.id).where(Site.project_id.in_(project_ids))
    kosullar = [
        EquipmentWorkLog.equipment_id == Equipment.id,
        EquipmentWorkLog.work_date >= date_from,
        EquipmentWorkLog.work_date <= date_to,
        EquipmentWorkLog.site_id.is_(None) | EquipmentWorkLog.site_id.in_(gorunen_santiyeler),
    ]
    if site_id is not None:
        kosullar.append(EquipmentWorkLog.site_id == site_id)
    return kosullar


def _hours_of(tip: WorkLogType):
    """Tipe göre koşullu toplam — İKİ sütun TEK taramada üretilir (K10).

    İki ayrı sorgu koşulsaydı çalışma ve arıza saatleri farklı anların
    fotoğrafından gelebilirdi.
    """
    return func.coalesce(
        func.sum(case((EquipmentWorkLog.record_type == tip, EquipmentWorkLog.hours), else_=0)),
        0,
    )


async def work_summary_rows(
    session: AsyncSession,
    project_ids: list[uuid.UUID],
    *,
    date_from: date,
    date_to: date,
    site_id: uuid.UUID | None = None,
) -> list[Row]:
    """M3 tablosunun satırları — maliyet BURADA hesaplanmaz.

    Dönüş satırı hesabın GİRDİLERİNİ taşır (bedel + dönem + kapasite), sonucunu
    değil: formül `cost.py`dedir (K18) ve SQL'e ikinci kez yazılsaydı
    `DAILY_HOURS` ile fail-closed `null` kuralı iki yerde yaşardı.

    Kaynak tablo `equipment`tir (kayıt tablosu değil): o ay hiç çalışmamış makine
    de 0 saatle listelenmelidir (M3'ün Forklift satırı), yoksa "bu ay hangi
    makine boş durdu?" sorusu ekranda cevapsız kalırdı.

    İki eleme kuralı `HAVING`dedir:

    * pasif makine yalnız o dönemde KAYDI VARSA listelenir — geçmiş maliyeti
      kaybolmaz ama hurdalık tabloyu şişirmez;
    * `site_id` süzgeci verildiğinde tablo O ŞANTİYEDE iş görmüş makinelere
      iner; inmeseydi şantiye süzgeci filonun tamamını 0 saatle basardı.
    """
    kayit_sayisi = func.count(EquipmentWorkLog.id)
    eleme = (
        (kayit_sayisi > 0)
        if site_id is not None
        else (Equipment.is_active.is_(True) | (kayit_sayisi > 0))
    )
    stmt = (
        scope(
            select(
                Equipment.id,
                Equipment.name,
                Equipment.site_id,
                _hours_of(WorkLogType.worked),
                _hours_of(WorkLogType.breakdown),
                Equipment.rate_amount,
                Equipment.rate_period,
                Equipment.monthly_capacity_hours,
            )
            .select_from(Equipment)
            .outerjoin(
                EquipmentWorkLog,
                and_(
                    *_log_join_conditions(
                        project_ids, date_from=date_from, date_to=date_to, site_id=site_id
                    )
                ),
            ),
            project_ids,
        )
        .group_by(
            Equipment.id,
            Equipment.name,
            Equipment.site_id,
            Equipment.rate_amount,
            Equipment.rate_period,
            Equipment.monthly_capacity_hours,
            Equipment.is_active,
        )
        .having(eleme)
        .order_by(Equipment.name, Equipment.id)
    )
    return list((await session.execute(stmt)).all())


async def daily_hours_by_type(
    session: AsyncSession,
    project_ids: list[uuid.UUID],
    *,
    date_from: date,
    date_to: date,
    site_id: uuid.UUID | None = None,
) -> list[Row[tuple[date, WorkLogType, Decimal]]]:
    """Haftalık kovaların HAM verisi: gün + tip başına saat toplamı.

    Kovalama SQL'de DEĞİL serviste yapılır (`_week_buckets`): hafta sınırının
    tanımı bir İŞ KURALIDIR ve SQL lehçesine (`date_trunc`) gömülseydi tanım iki
    yerde — kova sınırı ile etiketi arasında — ayrışabilirdi.
    """
    stmt = (
        scope(
            select(
                EquipmentWorkLog.work_date,
                EquipmentWorkLog.record_type,
                func.sum(EquipmentWorkLog.hours),
            ).join(Equipment, Equipment.id == EquipmentWorkLog.equipment_id),
            project_ids,
        )
        .where(
            and_(
                *_log_join_conditions(
                    project_ids, date_from=date_from, date_to=date_to, site_id=site_id
                )
            )
        )
        .group_by(EquipmentWorkLog.work_date, EquipmentWorkLog.record_type)
    )
    return list((await session.execute(stmt)).all())
