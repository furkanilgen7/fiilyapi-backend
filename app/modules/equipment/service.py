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

## İş kurallarının HARİTASI

* **K2** koşullu zorunluluk → `_assert_purchase_amount` (TEK denetim noktası);
* **K11** `hours` sunucu hesabı → `_resolve_hours` (POST ve PATCH aynı fonksiyon);
* **🔴 K12** günlük 24 saat tavanı → `_lock_equipment` + `_assert_daily_cap`
  (EŞİK = KİLİT: kilit DENETİMDEN ÖNCE, sıra tüm uçlarda SABİT);
* **K15** toplamlar satırlardan → `work_summary`;
* **K9** kaydın kendi şantiyesi → `create_work_log` damgası + `work_log_scope`.

**K16/K17/K18 BURADA DEĞİLDİR:** fail-closed `null`, sapma rozeti ve maliyet
formülü kendi TEK dosyalarındadır (`consumption.py` / `cost.py`) ve bu modül
onlardan yalnız OKUR — eşikler ile `DAILY_HOURS` sabiti iki yere kopyalanmaz.

Yakıt kaydı kuralları T5'indir.
"""

import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import EquipmentValidationError, NotFoundError
from app.modules.equipment import consumption, cost, repository
from app.modules.equipment.models import (
    Equipment,
    EquipmentCategory,
    EquipmentOwnership,
    EquipmentStatus,
    EquipmentWorkLog,
    WorkLogType,
)
from app.modules.equipment.schemas import (
    EquipmentCreate,
    EquipmentUpdate,
    WorkLogCreate,
    WorkLogUpdate,
    WorkSummaryResponse,
    WorkSummaryRow,
    WorkSummaryTotals,
    WorkSummaryWeek,
)
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


# --- Çalışma kaydı (M3 · spec §4 · K9 · K10 · K11 · K12) ---

WORK_LOG_MISSING = "Çalışma kaydı bulunamadı."
"""Görünmeyen VE var olmayan kaydın TEK cümlesi — ikisi ayırt EDİLEMEZ."""

HOURS_IS_SERVER_COMPUTED = (
    "Başlangıç ve bitiş saati verildiğinde çalışma süresi sunucu tarafından hesaplanır; "
    "'hours' alanı gönderilemez. Süreyi doğrudan yazmak için saat aralığını boşaltın."
)
TIME_PAIR_REQUIRED = (
    "Başlangıç ve bitiş saati birlikte verilmelidir: ikisini de girin ya da ikisini de boş bırakın."
)
OVERNIGHT_NOT_SUPPORTED = (
    "Bitiş saati başlangıç saatinden önce olamaz. Gece yarısını geçen vardiya bu sürümde "
    "desteklenmiyor; vardiyayı iki güne iki ayrı kayıt olarak girin."
)
HOURS_REQUIRED = (
    "Saat aralığı verilmediğinde çalışma süresi ('hours') zorunludur (arıza kaydı gibi)."
)

#: 🔴 K12 — bir günün saat TAVANI. Fizik kuralıdır, ekipmana göre değişmez;
#: `monthly_capacity_hours`un (K7, VERİ) aksine koda gömülüdür.
MAX_DAILY_HOURS = Decimal("24")

DAILY_HOURS_EXCEEDED = (
    "Aynı ekipmanın aynı gündeki kayıtları toplamı 24 saati aşamaz "
    "(mevcut {mevcut} saat + girilen {girilen} saat)."
)

#: Saat çözümlemesinin ölçeği — kolon `Numeric(6, 2)`.
_HOURS_QUANTUM = Decimal("0.01")
_SECONDS_PER_HOUR = Decimal("3600")


def _resolve_hours(
    *, start_time: time | None, end_time: time | None, hours: Decimal | None
) -> Decimal:
    """🔴 K11 — `hours` SUNUCU HESABIDIR. Kuralın TEK yaşadığı yer.

    POST ve PATCH aynı fonksiyonu çağırır; PATCH'e ikinci bir kopya yazılsaydı
    POST'ta 422 olan gövde PATCH'ten sızardı (kuralın yalnız POST'ta yaşadığı
    klasik kaçak — K2'nin aynı emsali).

    Dört kapı, hepsi 422:

    1. aralık YARIM verilmiş (yalnız biri) → anlamsız bir kayıt;
    2. aralık TAM verilmişken `hours` da gönderilmiş → sunucu hesabının üzerine
       yazma girişimi; SESSİZCE YOKSAYILSAYDI istemci kendi hesabının tutulduğunu
       sanır, ekranda başka bir sayı görürdü;
    3. `end < start` → gece vardiyası bu dilimde DESTEKLENMEZ (spec K11); sessiz
       bir negatif saatten iyidir;
    4. ne aralık ne saat → kaydın hiçbir süresi yok.

    `end == start` REDDEDİLMEZ: spec yalnız `end < start`ı yasaklar ve sıfır
    saatlik bir kayıt (yanlışlıkla açılıp düzeltilecek satır) yasak değildir.
    """
    if (start_time is None) != (end_time is None):
        raise EquipmentValidationError(TIME_PAIR_REQUIRED)
    if start_time is None or end_time is None:
        if hours is None:
            raise EquipmentValidationError(HOURS_REQUIRED)
        # Doğrudan alınan saat de KOLONUN ölçeğine çekilir: aksi halde aynı
        # kayıt yazıldığı istekte `8`, yeniden okunduğunda `8.00` dönerdi ve
        # istemci iki farklı dizge görürdü.
        return hours.quantize(_HOURS_QUANTUM)
    if hours is not None:
        raise EquipmentValidationError(HOURS_IS_SERVER_COMPUTED)
    if end_time < start_time:
        raise EquipmentValidationError(OVERNIGHT_NOT_SUPPORTED)
    fark = datetime.combine(date.min, end_time) - datetime.combine(date.min, start_time)
    return (Decimal(fark.total_seconds()) / _SECONDS_PER_HOUR).quantize(_HOURS_QUANTUM)


async def _lock_equipment(session: AsyncSession, *equipment_ids: uuid.UUID) -> None:
    """🔴 K12 EŞİK = KİLİT: tavan denetiminden ÖNCE `equipment` satır(lar)ı kilitlenir.

    Kilitsiz bir eşik denetimi iki eşzamanlı kayıtta HER İKİSİNİ de geçirir
    (İK-2 K5 / İK-3 çift ödeme dersi) ve TEK istekli bir test bunu ASLA görmez —
    regresyonu `tests/modules/equipment/test_mk1_work_log_concurrency.py`
    iki gerçek bağlantıyla tutar.

    **Kilit sırası SABİTTİR: kimliğe göre artan.** PATCH bir kaydı başka makineye
    taşırken İKİ ekipmanı birden kilitler; sıra sabitlenmeseydi iki eşzamanlı
    ters yönlü taşıma karşılıklı kilitlenme (deadlock) üretirdi. DELETE'te tavan
    yalnız AZALIR ama kilit yine de alınır ve sıra korunur: aynı satırlara iki
    farklı sırayla giren ikinci bir yol, kilit düzeninin tamamını bozardı.
    """
    for equipment_id in sorted(set(equipment_ids)):
        await repository.get_equipment_for_update(session, equipment_id)


async def _assert_daily_cap(
    session: AsyncSession,
    *,
    equipment_id: uuid.UUID,
    work_date: date,
    hours: Decimal,
    exclude_log_id: uuid.UUID | None = None,
) -> None:
    """🔴 K12 — günlük 24 saat tavanı. `_lock_equipment`ten SONRA çağrılır.

    Çakışma/vardiya örtüşmesi DENETLENMEZ (spec K12: mockup vardiya modeli
    çizmiyor) — yalnız günlük toplam.
    """
    mevcut = await repository.day_hours_total(
        session, equipment_id, work_date, exclude_log_id=exclude_log_id
    )
    if mevcut + hours > MAX_DAILY_HOURS:
        raise EquipmentValidationError(DAILY_HOURS_EXCEEDED.format(mevcut=mevcut, girilen=hours))


async def visible_work_log(
    session: AsyncSession, actor: User, log_id: uuid.UUID
) -> EquipmentWorkLog:
    """Çalışma kaydı görünürlüğünün TEK kapısı — detay, PATCH ve DELETE buradan geçer.

    İKİ kapı birden: kaydın KENDİ şantiyesi (K9) görünür olmalı VE makinesi
    görünür olmalı. İkincisi olmasaydı `site_id IS NULL` bir kayıt, görünmeyen
    bir projeye atanmış makinenin varlığını ele verirdi.
    """
    log = await repository.get_work_log(session, log_id)
    if log is None:
        raise NotFoundError(WORK_LOG_MISSING)
    if not await _is_visible_site(session, actor, log.site_id):
        raise NotFoundError(WORK_LOG_MISSING)
    if not await _is_visible_site(
        session, actor, (await get_equipment_or_404(session, log.equipment_id)).site_id
    ):
        raise NotFoundError(WORK_LOG_MISSING)
    return log


async def list_work_logs(
    session: AsyncSession,
    actor: User,
    *,
    equipment_id: uuid.UUID | None,
    site_id: uuid.UUID | None,
    date_from: date | None,
    date_to: date | None,
    record_type: WorkLogType | None,
    limit: int,
    offset: int,
) -> tuple[list[EquipmentWorkLog], int]:
    """Liste + `total` TEK kapsam kararını paylaşır (TB3 kanonu)."""
    project_ids = await _visible_project_ids(session, actor)
    suzgecler = {
        "equipment_id": equipment_id,
        "site_id": site_id,
        "date_from": date_from,
        "date_to": date_to,
        "record_type": record_type,
    }
    items = await repository.list_work_logs(
        session, project_ids, limit=limit, offset=offset, **suzgecler
    )
    total = await repository.count_work_logs(session, project_ids, **suzgecler)
    return items, total


async def create_work_log(
    session: AsyncSession, actor: User, data: WorkLogCreate
) -> tuple[EquipmentWorkLog, str]:
    """`POST /equipment/work-logs`.

    Sıra ÖNEMLİ ve tüm yazma uçlarında AYNI:

    1. görünürlük/referans (404) — gövdesi eksik bir istek, görmediği makinenin
       varlığını 422 üzerinden öğrenmemelidir;
    2. 🔴 **KİLİT** (`equipment` satırı) — denetimlerden ÖNCE, TOCTOU penceresi
       açılmasın;
    3. K11 saat çözümlemesi (saf, DB'ye dokunmaz);
    4. K12 günlük tavan (kilit ALTINDA okunur).

    Operatör YALNIZ varlığı için aranır; "arıza kaydında operatör olamaz" gibi
    bir kural spec'te YOKTUR ve icat edilmez (K10 yalnız zorunlu olmadığını
    söyler).
    """
    equipment = await visible_equipment(session, actor, data.equipment_id)
    if not await _is_visible_site(session, actor, data.site_id):
        raise NotFoundError(SITE_MISSING)
    if data.operator_id is not None and await session.get(Personnel, data.operator_id) is None:
        raise NotFoundError(OPERATOR_MISSING)

    await _lock_equipment(session, equipment.id)
    hours = _resolve_hours(start_time=data.start_time, end_time=data.end_time, hours=data.hours)
    await _assert_daily_cap(
        session, equipment_id=equipment.id, work_date=data.work_date, hours=hours
    )

    alanlar = data.model_dump(exclude={"hours"})
    if "site_id" not in data.model_fields_set:
        # 🔴 K9 SNAPSHOT: şantiye verilmemişse kaydın şantiyesi, makinenin O ANKİ
        # ataması olarak DAMGALANIR. `NULL` bırakılsaydı K9 kâğıt üzerinde kalır
        # ve maliyet dağılımı ("hangi şantiye ne kadar makine yaktı") hiçbir
        # zaman üretilemezdi. Açıkça `null` GÖNDEREN istek (depoda yapılan iş)
        # damgalanmaz — `model_fields_set` bu ikisini ayırır.
        alanlar["site_id"] = equipment.site_id
    log = EquipmentWorkLog(**alanlar, hours=hours, created_by_id=actor.id)
    session.add(log)
    await session.flush()
    return log, f"Çalışma kaydı eklendi: {equipment.name} · {data.work_date} · {hours} saat"


async def update_work_log(
    session: AsyncSession, actor: User, log: EquipmentWorkLog, data: WorkLogUpdate
) -> tuple[EquipmentWorkLog, str]:
    """`PATCH /equipment/work-logs/{id}` — kayıt hatası düzeltilebilir.

    🔴 K11 ve K12 burada **BİRLEŞİK değerler** üzerinde koşar: yalnız gövdeye
    bakılsaydı `{"hours": 12}` tek başına aralığı duran bir kaydın sunucu
    hesabını ezerdi ve `{"work_date": …}` tek başına hedef günün tavanını hiç
    ölçmezdi.

    Kilit HER İKİ ekipmanı da kapsar (kayıt başka makineye taşınabilir) ve
    `_lock_equipment` sırayı sabitler.
    """
    degisiklikler = data.model_dump(exclude_unset=True)
    hedef_equipment_id = degisiklikler.get("equipment_id", log.equipment_id)
    hedef_gun = degisiklikler.get("work_date", log.work_date)
    hedef_site_id = degisiklikler.get("site_id", log.site_id)

    if hedef_equipment_id != log.equipment_id:
        await visible_equipment(session, actor, hedef_equipment_id)
    if "site_id" in degisiklikler and not await _is_visible_site(session, actor, hedef_site_id):
        raise NotFoundError(SITE_MISSING)
    operator_id = degisiklikler.get("operator_id")
    if operator_id is not None and await session.get(Personnel, operator_id) is None:
        raise NotFoundError(OPERATOR_MISSING)

    await _lock_equipment(session, log.equipment_id, hedef_equipment_id)
    hours = _resolve_hours(
        start_time=degisiklikler.get("start_time", log.start_time),
        end_time=degisiklikler.get("end_time", log.end_time),
        # 🔴 `hours` YALNIZ gövdede varsa "verilmiş" sayılır: satırdaki mevcut
        # saat taşınsaydı, aralığı duran HER kayıt kendi eski saati yüzünden
        # 2. kapıya takılır ve bir daha hiç düzeltilemezdi.
        hours=degisiklikler.get("hours"),
    )
    await _assert_daily_cap(
        session,
        equipment_id=hedef_equipment_id,
        work_date=hedef_gun,
        hours=hours,
        exclude_log_id=log.id,
    )

    for alan, deger in degisiklikler.items():
        setattr(log, alan, deger)
    log.hours = hours
    await session.flush()
    return log, f"Çalışma kaydı güncellendi: {hedef_gun} · {hours} saat"


async def delete_work_log(session: AsyncSession, actor: User, log_id: uuid.UUID) -> str:
    """`DELETE /equipment/work-logs/{id}` — çalışma kaydı MALİ İZ DEĞİLDİR.

    Maliyet ondan TÜREVDİR (K18: her okumada yeniden hesaplanır), dolayısıyla
    hakediş satırının aksine yanlış girilen kayıt silinebilir; ekipmanın kendisi
    (kartı) silinemez — orada iz `RESTRICT`lidir.

    Tavan yalnız AZALIR ama kilit yine de alınır: kilit sırası TÜM uçlarda
    sabittir (`_lock_equipment` gerekçesi).
    """
    log = await visible_work_log(session, actor, log_id)
    await _lock_equipment(session, log.equipment_id)
    kunye = f"{log.work_date} · {log.hours} saat"
    await session.delete(log)
    await session.flush()
    return f"Çalışma kaydı silindi: {kunye}"


# --- Çalışma özeti (M3 ana tablosu · K15) ---


def month_bounds(year: int, month: int) -> tuple[date, date]:
    """Verilen ayın ilk ve son günü. `_month_bounds` (cari ay) ile aynı
    aritmetiği paylaşır ama dönemi PARAMETREDİR."""
    ilk = date(year, month, 1)
    sonraki = ilk.replace(year=year + 1, month=1) if month == 12 else ilk.replace(month=month + 1)
    return ilk, sonraki - timedelta(days=1)


def _monday(gun: date) -> date:
    """Haftanın PAZARTESİSİ. Hafta sınırının TEK tanımı."""
    return gun - timedelta(days=gun.weekday())


def _week_buckets(ilk: date, son: date, gunluk: list[Row]) -> list[WorkSummaryWeek]:
    """🔴 M3:219-243 haftalık kovaları.

    **Hafta sınırı = PAZARTESİ başlangıçlı ISO haftası**, ayın 1'ini içeren
    haftadan sayılır (`index` 1'den başlar). Takvim haftası seçildi çünkü
    kullanıcı "bu hafta" derken takvim haftasını kastediyor; "ayın 1'inden
    itibaren 7'şer gün" seçilseydi aynı pazartesi ayın başında H1, sonunda H5
    olur ve ardışık iki ayın grafikleri karşılaştırılamazdı.

    Sınırlar AYA KIRPILIR: kova "1–5 Temmuz" der, haziranın son günlerini
    saymaz — grafiğin altındaki toplam, tablonun toplamıyla tutmalıdır (K15).

    İzoleli yıl sonu sorunu YOKTUR: hafta indeksi ISO hafta NUMARASINDAN değil
    pazartesiler arasındaki GÜN FARKINDAN türer.
    """
    ilk_pazartesi = _monday(ilk)
    kova_sayisi = ((_monday(son) - ilk_pazartesi).days // 7) + 1

    saatler: list[dict[WorkLogType, Decimal]] = [
        dict.fromkeys(WorkLogType, Decimal("0")) for _ in range(kova_sayisi)
    ]
    for gun, tip, saat in gunluk:
        saatler[(_monday(gun) - ilk_pazartesi).days // 7][tip] += saat

    kovalar: list[WorkSummaryWeek] = []
    for sira in range(kova_sayisi):
        pazartesi = ilk_pazartesi + timedelta(weeks=sira)
        kova = saatler[sira]
        toplam = sum(kova.values(), Decimal("0"))
        kovalar.append(
            WorkSummaryWeek(
                index=sira + 1,
                start_date=max(pazartesi, ilk),
                end_date=min(pazartesi + timedelta(days=6), son),
                hours=toplam,
                # Beraberlikte `worked` kazanır: bir haftayı arıza rengine
                # boyamak, o hafta en az onun kadar çalışılmışken yanıltıcıdır.
                dominant_record_type=(
                    None
                    if not toplam
                    else (
                        WorkLogType.breakdown
                        if kova[WorkLogType.breakdown] > kova[WorkLogType.worked]
                        else WorkLogType.worked
                    )
                ),
            )
        )
    return kovalar


async def work_summary(
    session: AsyncSession, actor: User, *, year: int, month: int, site_id: uuid.UUID | None
) -> WorkSummaryResponse:
    """`GET /equipment/work-summary` — M3'ün TAMAMI.

    🔴 **K15: tfoot SATIRLARDAN türer.** Mockup'ın 428 saat / ₺124.800 / %69'u
    kendi satırlarıyla tutarsızdır (692 / ₺144.200 / %57,7) ve KOPYALANMAZ.
    🔴 **K18: maliyet `cost.py`den**, 🔴 **K7: kullanım % `consumption.py`den**
    gelir — ikisi de burada YENİDEN yazılmaz.
    🔴 **K16:** maliyeti bilinmeyen satır `null` durur ve toplama UYDURMA bir 0
    ile GİRMEZ; toplamın kendisi `null` yapılmaz (tek bilinmeyen makine yüzünden
    bütün tabloyu gizlemek kullanıcıyı ekranın tamamından ederdi).
    """
    project_ids = await _visible_project_ids(session, actor)
    ilk, son = month_bounds(year, month)
    ham = await repository.work_summary_rows(
        session, project_ids, date_from=ilk, date_to=son, site_id=site_id
    )

    satirlar: list[WorkSummaryRow] = []
    for (
        equipment_id,
        name,
        equipment_site_id,
        hours,
        breakdown_hours,
        rate_amount,
        rate_period,
        capacity,
    ) in ham:
        kullanim = consumption.compute_usage(hours=hours, monthly_capacity_hours=capacity)
        satirlar.append(
            WorkSummaryRow(
                equipment_id=equipment_id,
                equipment_name=name,
                site_id=equipment_site_id,
                hours=hours,
                usage_pct=kullanim.usage_pct,
                usage_reason=kullanim.usage_reason,
                breakdown_hours=breakdown_hours,
                cost=cost.compute_cost(
                    hours=hours,
                    rate_amount=rate_amount,
                    rate_period=rate_period,
                    monthly_capacity_hours=capacity,
                ),
            )
        )

    bilinen_kullanimlar = [s.usage_pct for s in satirlar if s.usage_pct is not None]
    toplamlar = WorkSummaryTotals(
        hours=sum((s.hours for s in satirlar), Decimal("0")),
        breakdown_hours=sum((s.breakdown_hours for s in satirlar), Decimal("0")),
        cost=sum((s.cost for s in satirlar if s.cost is not None), Decimal("0")),
        usage_pct_avg=(
            consumption.quantize_ratio(sum(bilinen_kullanimlar) / len(bilinen_kullanimlar))
            if bilinen_kullanimlar
            else None
        ),
    )
    gunluk = await repository.daily_hours_by_type(
        session, project_ids, date_from=ilk, date_to=son, site_id=site_id
    )
    return WorkSummaryResponse(
        year=year,
        month=month,
        rows=satirlar,
        totals=toplamlar,
        weeks=_week_buckets(ilk, son, gunluk),
    )
