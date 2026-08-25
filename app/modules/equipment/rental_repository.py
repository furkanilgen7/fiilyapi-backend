"""Kira hakedişi veri erişimi (MK-2 T3) — yalnız SQL, yetki/kapsam KARARI yok.

`repository.py`nin (MK-1) kardeşidir ve aynı iş bölümünü taşır: kapsam kararı
(`visible_projects`, K9) `rental_service.py`dedir, buraya yalnız çözülmüş proje
kimlikleri gelir. Liste ve sayım AYNI süzgeç yardımcısını paylaşır — kopya
açılsaydı `total` ile gösterilen tablo zamanla ayrışırdı (TB3 kanonu).

## 🔴 Kilit sırası

Yazma yollarının HEPSİ önce **fatura başlığını** (`lock_invoice`), sonra
**satırları** (`lock_invoice_lines`, kimliğe göre artan) kilitler. Sıra tüm
uçlarda SABİTTİR; satırdan başlayan ikinci bir yol açılsaydı iki eşzamanlı istek
karşılıklı kilitlenme (deadlock) üretirdi. `populate_existing` ZORUNLUDUR: kilit
altında okunan durum TAZE olmalıdır, yoksa SQLAlchemy kimlik haritasındaki ESKİ
kopyayı verir ve kilit doğru alınmış olsa bile karar eski durumdan verilir.
"""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Row, Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.equipment.models import (
    Equipment,
    EquipmentOwnership,
    EquipmentRatePeriod,
    EquipmentRentalInvoice,
    EquipmentRentalInvoiceLine,
    EquipmentWorkLog,
    RentalInvoiceStatus,
)
from app.modules.equipment.repository import scope as equipment_scope
from app.modules.equipment.repository import work_log_scope
from app.modules.sites.models import Site

# --- Görünürlük (K9) ---


def invoice_scope(stmt: Select, project_ids: list[uuid.UUID]) -> Select:
    """🔴 K9 — `equipment.scope()`un birebir kardeşi, İKİ dallı ve OR'lu:

    * `site_id IS NULL` ("Tüm Projeler", M5:73) → kapsam süzgecine TABİ DEĞİL;
    * şantiyeli fatura → şantiyesinin projesi görünen projeler içinde olmalı.

    Depo/"tüm projeler" dalı OR'dan çıkarılsaydı proje seçilmemiş bir faturayı
    HİÇ KİMSE göremezdi (hiçbir projeye bağlı değildir).
    """
    gorunen_santiyeler = select(Site.id).where(Site.project_id.in_(project_ids))
    return stmt.where(
        EquipmentRentalInvoice.site_id.is_(None)
        | EquipmentRentalInvoice.site_id.in_(gorunen_santiyeler)
    )


# --- Fatura başlığı ---


async def get_invoice(
    session: AsyncSession, invoice_id: uuid.UUID
) -> EquipmentRentalInvoice | None:
    """OKUMA yolu — kilitsiz. Yazma yolları `lock_invoice` kullanır."""
    return await session.scalar(
        select(EquipmentRentalInvoice).where(EquipmentRentalInvoice.id == invoice_id)
    )


async def lock_invoice(
    session: AsyncSession, invoice_id: uuid.UUID
) -> EquipmentRentalInvoice | None:
    """🔴 EŞİK = KİLİT: `SELECT … FOR UPDATE`, DURUM DENETİMİNDEN ÖNCE.

    MK-2'nin eşiği bir kota değil bir DURUM KAPISIDIR: her adım YALNIZ BİR KEZ
    atılabilir. Kilitsiz iki eşzamanlı `pay` aynı `approved` durumunu okur, ikisi
    de geçer ve fatura İKİ KEZ ödenir (İK-2/İK-3 dersi). Tek istekli bir test
    bunu ASLA görmez; regresyon `test_mk2_rental_invoice_concurrency.py`dedir.

    `populate_existing` ZORUNLUDUR (modül docstring'i).
    """
    return (
        await session.execute(
            select(EquipmentRentalInvoice)
            .where(EquipmentRentalInvoice.id == invoice_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


def _filtered(
    stmt: Select,
    project_ids: list[uuid.UUID],
    *,
    supplier_id: uuid.UUID | None,
    site_id: uuid.UUID | None,
    equipment_id: uuid.UUID | None,
    status: RentalInvoiceStatus | None,
    period_year: int | None,
    period_month: int | None,
) -> Select:
    """Süzgeçler AND'lidir ve kapsam (K9) HER ZAMAN üstte kalır: `site_id`
    süzgeci kapsamı GENİŞLETMEZ, daraltır."""
    stmt = invoice_scope(stmt, project_ids)
    if supplier_id is not None:
        stmt = stmt.where(EquipmentRentalInvoice.supplier_id == supplier_id)
    if equipment_id is not None:
        # 🔴 `equipment_id` BAŞLIKTA DEĞİL SATIRDADIR (MK-2 şeması): süzgeç bu
        # yüzden bir `EXISTS`tir, JOIN DEĞİL. JOIN yazılsaydı aynı ekipmanın iki
        # satırı bulunan bir fatura listede İKİ KEZ görünür ve `total` gerçek
        # fatura sayısından fazla çıkardı (sayfalama kanonunun sessiz kaçağı).
        stmt = stmt.where(
            select(EquipmentRentalInvoiceLine.id)
            .where(
                EquipmentRentalInvoiceLine.invoice_id == EquipmentRentalInvoice.id,
                EquipmentRentalInvoiceLine.equipment_id == equipment_id,
            )
            .exists()
        )
    if site_id is not None:
        stmt = stmt.where(EquipmentRentalInvoice.site_id == site_id)
    if status is not None:
        stmt = stmt.where(EquipmentRentalInvoice.status == status)
    if period_year is not None:
        stmt = stmt.where(EquipmentRentalInvoice.period_year == period_year)
    if period_month is not None:
        stmt = stmt.where(EquipmentRentalInvoice.period_month == period_month)
    return stmt


async def list_invoices(
    session: AsyncSession,
    project_ids: list[uuid.UUID],
    *,
    supplier_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    equipment_id: uuid.UUID | None = None,
    status: RentalInvoiceStatus | None = None,
    period_year: int | None = None,
    period_month: int | None = None,
    limit: int,
    offset: int,
) -> list[EquipmentRentalInvoice]:
    """EN YENİ dönem önce; ikinci ölçüt (`id`) sayfalamayı DETERMİNİSTİK yapar —
    olmasaydı aynı döneme düşen faturalar sayfalar arasında kaybolup
    tekrarlanabilirdi."""
    stmt = _filtered(
        select(EquipmentRentalInvoice),
        project_ids,
        supplier_id=supplier_id,
        site_id=site_id,
        equipment_id=equipment_id,
        status=status,
        period_year=period_year,
        period_month=period_month,
    )
    stmt = (
        stmt.order_by(
            EquipmentRentalInvoice.period_year.desc(),
            EquipmentRentalInvoice.period_month.desc(),
            EquipmentRentalInvoice.id,
        )
        .limit(limit)
        .offset(offset)
    )
    return list((await session.execute(stmt)).scalars().all())


async def count_invoices(
    session: AsyncSession,
    project_ids: list[uuid.UUID],
    *,
    supplier_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    equipment_id: uuid.UUID | None = None,
    status: RentalInvoiceStatus | None = None,
    period_year: int | None = None,
    period_month: int | None = None,
) -> int:
    """`total` GÖRÜNEN ve SÜZÜLMÜŞ kümeyi sayar, tablonun tamamını değil."""
    stmt = _filtered(
        select(func.count()).select_from(EquipmentRentalInvoice),
        project_ids,
        supplier_id=supplier_id,
        site_id=site_id,
        equipment_id=equipment_id,
        status=status,
        period_year=period_year,
        period_month=period_month,
    )
    return (await session.execute(stmt)).scalar_one()


async def invoice_no_exists(
    session: AsyncSession,
    *,
    supplier_id: uuid.UUID,
    invoice_no: str,
    exclude_id: uuid.UUID | None = None,
) -> bool:
    """UQ `(supplier_id, invoice_no)`nun ÖN denetimi.

    IntegrityError'a düşmeden önce açık bir SELECT koşar ki kullanıcı alanına
    özel Türkçe bir 409 alsın (`DuplicateError` gerekçesi); DB kısıtı yarış
    durumu emniyet ağı olarak KALIR.
    """
    stmt = (
        select(func.count())
        .select_from(EquipmentRentalInvoice)
        .where(
            EquipmentRentalInvoice.supplier_id == supplier_id,
            EquipmentRentalInvoice.invoice_no == invoice_no,
        )
    )
    if exclude_id is not None:
        stmt = stmt.where(EquipmentRentalInvoice.id != exclude_id)
    return (await session.execute(stmt)).scalar_one() > 0


# --- Satırlar ---


async def invoice_lines(
    session: AsyncSession, invoice_id: uuid.UUID
) -> list[Row[tuple[EquipmentRentalInvoiceLine, Equipment]]]:
    """M5 tablosunun satırları — ekipman künyesiyle BİRLİKTE (tek sorgu).

    Ad/marka/plaka satır başına ayrı ayrı çekilseydi tablo başına N+1 sorgu
    doğardı. Sıra `(ekipman adı, satır türü, id)`dir: M5 aynı makinenin arıza
    satırını kira satırının hemen ardında basar ve sıra deterministik olmalıdır.
    """
    stmt = (
        select(EquipmentRentalInvoiceLine, Equipment)
        .join(Equipment, Equipment.id == EquipmentRentalInvoiceLine.equipment_id)
        .where(EquipmentRentalInvoiceLine.invoice_id == invoice_id)
        .order_by(
            Equipment.name,
            EquipmentRentalInvoiceLine.line_kind,
            EquipmentRentalInvoiceLine.id,
        )
    )
    return list((await session.execute(stmt)).all())


async def lock_invoice_lines(
    session: AsyncSession, invoice_id: uuid.UUID
) -> list[EquipmentRentalInvoiceLine]:
    """Satırları KİMLİĞE GÖRE ARTAN kilitler — sıra SABİTTİR (deadlock kapısı).

    Fatura başlığı ÖNCE kilitlenmiş olmalıdır (modül docstring'i).
    """
    return list(
        (
            await session.execute(
                select(EquipmentRentalInvoiceLine)
                .where(EquipmentRentalInvoiceLine.invoice_id == invoice_id)
                .order_by(EquipmentRentalInvoiceLine.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )


async def get_line(session: AsyncSession, line_id: uuid.UUID) -> EquipmentRentalInvoiceLine | None:
    """Satırın KİLİTSİZ okunuşu: yalnız `invoice_id`yi öğrenmek için.

    Kilit her zaman BAŞLIKTAN başlar; burada kilit alınsaydı satır → başlık
    sırası doğar ve öteki yollarla karşılıklı kilitlenirdi.
    """
    return await session.scalar(
        select(EquipmentRentalInvoiceLine).where(EquipmentRentalInvoiceLine.id == line_id)
    )


# --- 🔴 K2 SNAPSHOT kaynağı: çalışma kaydı ---


async def period_hours(
    session: AsyncSession,
    project_ids: list[uuid.UUID],
    *,
    supplier_id: uuid.UUID,
    date_from: date,
    date_to: date,
    site_id: uuid.UUID | None,
) -> list[Row[tuple[uuid.UUID, uuid.UUID | None, str, Decimal]]]:
    """🔴 K2 — satır snapshot'ının TEK kaynağı: dönemin çalışma/arıza saatleri.

    `(ekipman, kaydın şantiyesi, kayıt tipi)` başına saat toplamı döner; hangi
    satırın kurulacağına ve şantiyenin nasıl seçileceğine SERVİS karar verir
    (`rental_service._build_lines`) — kural SQL'e gömülseydi ikinci bir yerde
    yaşardı.

    Ekipman kümesi K8'in ta kendisidir: YALNIZ (a) faturanın tedarikçisine ait
    KİRALIK makineler ve (b) KENDİ makinelerimiz (`owned`, tedarikçi aranmaz).
    Başka bir firmanın kiralık makinesi bu faturaya HİÇ girmez — girseydi
    Liebherr'e kesilen fatura CAT'in makinesini de ödetirdi.

    İki kapsam kapısı birden koşar (MK-1 K9 + K20): makinenin kendisi görünür
    olmalı VE kaydın KENDİ `site_id`si görünür (ya da NULL) olmalı.
    """
    stmt = (
        equipment_scope(
            work_log_scope(
                select(
                    EquipmentWorkLog.equipment_id,
                    EquipmentWorkLog.site_id,
                    EquipmentWorkLog.record_type,
                    func.sum(EquipmentWorkLog.hours),
                ).join(Equipment, Equipment.id == EquipmentWorkLog.equipment_id),
                project_ids,
            ),
            project_ids,
        )
        .where(
            EquipmentWorkLog.work_date >= date_from,
            EquipmentWorkLog.work_date <= date_to,
            (
                (Equipment.ownership == EquipmentOwnership.rented)
                & (Equipment.supplier_id == supplier_id)
            )
            | (Equipment.ownership == EquipmentOwnership.owned),
        )
        .group_by(
            EquipmentWorkLog.equipment_id,
            EquipmentWorkLog.site_id,
            EquipmentWorkLog.record_type,
        )
    )
    if site_id is not None:
        # M5:73 "Proje" seçili ise hakediş O ŞANTİYENİN kayıtlarına iner;
        # "Tüm Projeler" (NULL) iken süzgeç HİÇ uygulanmaz.
        stmt = stmt.where(EquipmentWorkLog.site_id == site_id)
    return list((await session.execute(stmt)).all())


async def equipment_by_ids(
    session: AsyncSession, equipment_ids: list[uuid.UUID]
) -> dict[uuid.UUID, Equipment]:
    """Satır kurulumunun ekipman künyesi — TEK sorgu (kayıt başına sorgu yok)."""
    if not equipment_ids:
        return {}
    rows = (
        (await session.execute(select(Equipment).where(Equipment.id.in_(equipment_ids))))
        .scalars()
        .all()
    )
    return {row.id: row for row in rows}


async def site_names(session: AsyncSession, site_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    """Şantiye adları — M5 tabloda ve dağılım kartında AD basar.

    Ad DB'den çözülür, satıra KOPYALANMAZ: şantiye adı değiştiğinde ekranın eski
    adı göstermesi için bir sebep yoktur (snapshot olan şey SAAT ve BAĞDIR, ad
    değil).
    """
    if not site_ids:
        return {}
    rows = (await session.execute(select(Site.id, Site.name).where(Site.id.in_(site_ids)))).all()
    return {row[0]: row[1] for row in rows}


async def paid_lines_for_equipment(
    session: AsyncSession,
    project_ids: list[uuid.UUID],
    *,
    equipment_id: uuid.UUID,
) -> list[Row[tuple[EquipmentRentalInvoiceLine, EquipmentRatePeriod]]]:
    """MK-4 `Kümülatif Ödenen` (MD:82) — ÖDENMİŞ hakedişlerin satırları.

    🔴 SQL'de `SUM(...)` YAZILMAZ: ödenecek tutarın formülü `rental.py`dedir
    (MK-2 K4 "tek formül") ve dönem dönüşümünü (`hourly`/`daily`/`monthly`) ile
    satırın `capacity_hours` snapshot'ını (MK-3 K1) birlikte okur. Toplamı SQL'e
    yazmak, aynı paranın İKİNCİ bir formülünü doğururdu.

    `rate_period` FATURANINDIR (M5:74), satırın değil — bu yüzden satırla
    birlikte döner; çağıran onu satırdan uyduramaz.

    Durum süzgeci **yalnız `paid`**tir: "ödenen" ile "onaylanan" aynı şey
    değildir ve `approved` de sayılsaydı ekran henüz çıkmamış bir parayı
    ödenmiş gösterirdi. Kapsam (K9) fatura başlığından okunur.
    """
    stmt = invoice_scope(
        select(EquipmentRentalInvoiceLine, EquipmentRentalInvoice.rate_period).join(
            EquipmentRentalInvoice,
            EquipmentRentalInvoice.id == EquipmentRentalInvoiceLine.invoice_id,
        ),
        project_ids,
    ).where(
        EquipmentRentalInvoiceLine.equipment_id == equipment_id,
        EquipmentRentalInvoice.status == RentalInvoiceStatus.paid,
    )
    return list((await session.execute(stmt)).all())
