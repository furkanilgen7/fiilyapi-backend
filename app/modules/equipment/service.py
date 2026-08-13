"""Ekipman çekirdeği iş kuralları (T1 iskeleti) — MK-1 spec §2, §4, §6.

İKİ KATMANLI koruma (`inventory`/`documents` servis deseninin birebiri):
`equipment` izni router'da YETKİYİ verir, bu modül `visible_projects` ile
KAPSAMI belirler.

## Kapsam kuralı (K20) — `personnel`/`payroll` İSTİSNASI BURADA GEÇERSİZ

Ekipman bir şantiyeye atanır ve maliyeti bir projeye yansır, dolayısıyla
`visible_projects` süzgeci UYGULANIR. **Tek istisna:** `site_id IS NULL` olan
(depodaki) ekipman hiçbir projeye ait değildir ve `equipment` izni olan HERKESE
görünür — ST'nin merkez depo (`warehouses.site_id IS NULL`) kuralının kardeşi.
Çalışma ve yakıt kayıtları KENDİ `site_id`leriyle süzülür (K9), ekipmanın
bugünkü atamasıyla değil.

## Bu dosyada NE YOK

Yazma uçlarının kuralları (K2 koşullu zorunluluk · K11 `hours` sunucu hesabı ·
K12 kilitli 24 saat tavanı) ve türev hesaplar (K15 satırlardan toplam · K16
fail-closed `null` · K17 sapma rozeti · K18 maliyet formülü) T3-T5'indir.
K17/K18 kendi TEK dosyalarında (`consumption.py` / `cost.py`) duracaktır —
eşikler ve `DAILY_HOURS` sabiti iki yere kopyalanmaz.
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import EquipmentValidationError, NotFoundError
from app.modules.equipment import cost, repository
from app.modules.equipment.models import (
    Equipment,
    EquipmentCategory,
    EquipmentOwnership,
    EquipmentStatus,
)
from app.modules.equipment.schemas import EquipmentCreate, EquipmentUpdate
from app.modules.personnel.models import Personnel
from app.modules.procurement.models import Supplier
from app.modules.projects.service import visible_projects
from app.modules.sites import repository as sites_repository
from app.modules.users.models import User

PERMISSION_MODULE = "equipment"

EQUIPMENT_MISSING = "Ekipman bulunamadı."
"""Görünmeyen VE var olmayan kaydın TEK cümlesi — ikisi ayırt EDİLEMEZ."""

SITE_MISSING = "Seçilen şantiye bulunamadı."
OPERATOR_MISSING = "Seçilen operatör bulunamadı."
SUPPLIER_MISSING = "Seçilen tedarikçi bulunamadı."

PURCHASE_AMOUNT_REQUIRED = (
    "Şirkete ait (sahip olunan) ekipmanda alış bedeli zorunludur. "
    "Kiralık ekipmanda bu alan boş bırakılabilir."
)
"""🔴 K2. Kural SERVİStedir, DB `CHECK`i DEĞİL: kiralık makinenin alış bedeli
yoktur ve şemaya konsaydı hiç kaydedilemezdi; CHECK'e konsaydı kullanıcı Türkçe
bir mesaj yerine anlaşılmaz bir bütünlük hatası alırdı (İK-3 S3 emsali)."""


async def get_equipment_or_404(session: AsyncSession, equipment_id: uuid.UUID) -> Equipment:
    """Kapsam dışı ya da olmayan kayıt AYNI cevabı verir: 404 (spec §4).

    Kapsam denetimi (K20) çağıran uçtadır ve 403 DEĞİL 404 üretir — "görmediğin
    kaydın varlığını da öğrenme" kuralı (IDOR deseni, P2).
    """
    equipment = await repository.get_equipment(session, equipment_id)
    if equipment is None:
        raise NotFoundError(EQUIPMENT_MISSING)
    return equipment


async def _visible_project_ids(session: AsyncSession, actor: User) -> list[uuid.UUID]:
    return [p.id for p in await visible_projects(session, actor)]


async def _is_visible_site(session: AsyncSession, actor: User, site_id: uuid.UUID | None) -> bool:
    """K20'nin TEKİL kayıt için okunuşu. `None` (depodaki makine) HER ZAMAN
    görünür — kapsamı boş küme olan kullanıcı da onu görür."""
    if site_id is None:
        return True
    site = await sites_repository.get_site(session, site_id)
    return site is not None and site.project_id in await _visible_project_ids(session, actor)


async def visible_equipment(
    session: AsyncSession, actor: User, equipment_id: uuid.UUID
) -> Equipment:
    """🔴 Görünürlüğün TEK kapısı — liste dışındaki HER uç (detay, PATCH ve
    ileride çalışma/yakıt kayıtları) buradan geçer.

    Yetki seviyesi bu kararın ÖNÜNE GEÇMEZ: `equipment:admin` taşıyan ama
    projeyi görmeyen kullanıcı da 404 alır, yoksa yetkili hesap bir keşif
    aracına dönerdi (ST IDOR dersi).
    """
    equipment = await get_equipment_or_404(session, equipment_id)
    if not await _is_visible_site(session, actor, equipment.site_id):
        raise NotFoundError(EQUIPMENT_MISSING)
    return equipment


async def _assert_references(
    session: AsyncSession,
    actor: User,
    *,
    site_id: uuid.UUID | None,
    operator_id: uuid.UUID | None,
    supplier_id: uuid.UUID | None,
) -> None:
    """Gövdedeki varlık referansları — **var olmayan referans 404** (ST kanonu).

    `site_id` görünmeyen bir şantiyeyi gösterdiğinde de AYNI 404 döner: aksi
    hâlde kullanıcı makinesini görmediği bir projeye taşıyıp kaydı kendinden
    gizleyebilir, üstelik o projenin varlığını da öğrenirdi.

    **Operatör için "aktif personel olmalı" kuralı YOKTUR** (spec sessiz, icat
    edilmez) — yalnız VARLIĞI aranır.
    """
    if not await _is_visible_site(session, actor, site_id):
        raise NotFoundError(SITE_MISSING)
    if operator_id is not None and await session.get(Personnel, operator_id) is None:
        raise NotFoundError(OPERATOR_MISSING)
    if supplier_id is not None and await session.get(Supplier, supplier_id) is None:
        raise NotFoundError(SUPPLIER_MISSING)


def _assert_purchase_amount(ownership: EquipmentOwnership, purchase_amount: Decimal | None) -> None:
    """🔴 K2 — TEK denetim noktası. POST ile PATCH aynı fonksiyonu çağırır;
    ikinci bir kopya yazılsaydı `rented` kaydedip sonra `owned`a çekmek kuralı
    atlardı (kuralın yalnız POST'ta yaşadığı klasik kaçak)."""
    if ownership is EquipmentOwnership.owned and purchase_amount is None:
        raise EquipmentValidationError(PURCHASE_AMOUNT_REQUIRED)


async def list_equipment(
    session: AsyncSession,
    actor: User,
    *,
    status: EquipmentStatus | None,
    category: EquipmentCategory | None,
    site_id: uuid.UUID | None,
    ownership: EquipmentOwnership | None,
    q: str | None,
    is_active: bool | None,
    limit: int,
    offset: int,
) -> tuple[list[Equipment], int]:
    """Liste + `total` TEK kapsam kararını paylaşır (TB3 kanonu)."""
    project_ids = await _visible_project_ids(session, actor)
    suzgecler = {
        "status": status,
        "category": category,
        "site_id": site_id,
        "ownership": ownership,
        "q": q,
        "is_active": is_active,
    }
    items = await repository.list_equipment(
        session, project_ids, limit=limit, offset=offset, **suzgecler
    )
    total = await repository.count_equipment(session, project_ids, **suzgecler)
    return items, total


async def create_equipment(
    session: AsyncSession, actor: User, data: EquipmentCreate
) -> tuple[Equipment, str]:
    """Yeni ekipman kartı (M2 formu).

    Sıra ÖNEMLİ: önce referans/kapsam (404), sonra K2 (422). Tersi olsaydı
    kapsam dışı bir şantiyeye eksik gövdeyle POST atan kullanıcı 422 alır ve
    şantiyenin GÖRÜNMEDİĞİNİ değil gövdesinin eksik olduğunu öğrenirdi.
    """
    await _assert_references(
        session,
        actor,
        site_id=data.site_id,
        operator_id=data.operator_id,
        supplier_id=data.supplier_id,
    )
    _assert_purchase_amount(data.ownership, data.purchase_amount)
    equipment = Equipment(**data.model_dump())
    session.add(equipment)
    await session.flush()
    return equipment, f"Ekipman eklendi: {equipment.name}"


async def update_equipment(
    session: AsyncSession, equipment: Equipment, actor: User, data: EquipmentUpdate
) -> tuple[Equipment, str]:
    """Kısmi güncelleme — kullanımdan kaldırma da buradan geçer (`is_active`).

    `exclude_unset` ŞART (F-İK dersi): gönderilmemiş alan ile `null` gönderilmiş
    alan farklıdır ve dokunulmamış bir alan sunucudaki değeri EZMEMELİDİR.

    🔴 K2 denetimi MEVCUT SATIR + GÖVDE birleşimi üzerinden koşar; yalnız gövdeye
    bakılsaydı `{"ownership": "owned"}` tek başına kuralı atlardı.

    Denetim yalnız İKİ ALANDAN BİRİNE DOKUNULDUĞUNDA koşar (F-İK "touched"
    deseni): her PATCH'te koşsaydı, kuralın öncesinden kalmış (ya da doğrudan
    DB'den açılmış) bedelsiz bir `owned` satır BİR DAHA HİÇ güncellenemez —
    hurdaya bile ayrılamaz — hâle gelirdi. Kuralın hedefi kaydı KİLİTLEMEK
    değil, bu iki alanın birlikte tutarlı kalmasıdır.
    """
    degisiklikler = data.model_dump(exclude_unset=True)
    if {"site_id", "operator_id", "supplier_id"} & degisiklikler.keys():
        await _assert_references(
            session,
            actor,
            site_id=degisiklikler.get("site_id", equipment.site_id),
            operator_id=degisiklikler.get("operator_id"),
            supplier_id=degisiklikler.get("supplier_id"),
        )
    if {"ownership", "purchase_amount"} & degisiklikler.keys():
        _assert_purchase_amount(
            degisiklikler.get("ownership", equipment.ownership),
            degisiklikler.get("purchase_amount", equipment.purchase_amount),
        )
    for alan, deger in degisiklikler.items():
        setattr(equipment, alan, deger)
    await session.flush()
    return equipment, f"Ekipman güncellendi: {equipment.name}"


class EquipmentSummary(NamedTuple):
    """M1'in dört KPI kartı — K21: mockup ÜÇ durum çiziyor, sunucu DÖRDÜNÜ verir."""

    working: int
    broken: int
    maintenance: int
    idle: int
    monthly_cost: Decimal


def _month_bounds(bugun: date) -> tuple[date, date]:
    """Cari ayın ilk ve son günü. "Aylık maliyet" cari aydır: geçmiş aylar
    eklenseydi KPI her ay birikerek büyür, hiçbir zaman düşmezdi."""
    ilk = bugun.replace(day=1)
    sonraki_ay = (
        ilk.replace(year=ilk.year + 1, month=1)
        if ilk.month == 12
        else ilk.replace(month=ilk.month + 1)
    )
    return ilk, sonraki_ay - timedelta(days=1)


async def summarize(session: AsyncSession, actor: User) -> EquipmentSummary:
    """`GET /equipment/summary` — M1 KPI'ları.

    🔴 **K15: toplam SATIRLARDAN türer.** Mockup'ın ₺124K'sı (M3 tfoot'u) KENDİ
    satırlarıyla tutarsızdır ve KOPYALANMAZ.
    🔴 **K18: formül `cost.py`dedir**, burada ikinci kez YAZILMAZ.
    🔴 **K16:** bedeli/dönemi bilinmeyen makine (maliyeti `None`) toplama
    UYDURMA bir `0` ile GİRMEZ — atlanır; bilinen makinelerin parası bundan
    etkilenmez. Sonucun kendisi `null` yapılmadı çünkü KPI bir toplamdır ve
    tek bilinmeyen makine yüzünden bütün filonun maliyetini gizlemek
    kullanıcıyı ekranın tamamından ederdi.
    """
    project_ids = await _visible_project_ids(session, actor)
    sayaclar = await repository.status_counts(session, project_ids)
    ilk, son = _month_bounds(date.today())
    satirlar = await repository.worked_hours_by_equipment(
        session, project_ids, date_from=ilk, date_to=son
    )
    toplam = Decimal("0")
    for hours, rate_amount, rate_period, capacity in satirlar:
        satir_maliyeti = cost.compute_cost(
            hours=hours,
            rate_amount=rate_amount,
            rate_period=rate_period,
            monthly_capacity_hours=capacity,
        )
        if satir_maliyeti is not None:
            toplam += satir_maliyeti
    return EquipmentSummary(
        working=sayaclar.get(EquipmentStatus.working, 0),
        broken=sayaclar.get(EquipmentStatus.broken, 0),
        maintenance=sayaclar.get(EquipmentStatus.maintenance, 0),
        idle=sayaclar.get(EquipmentStatus.idle, 0),
        monthly_cost=toplam,
    )
