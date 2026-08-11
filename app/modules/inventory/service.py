"""Stok çekirdeği iş kuralları (T2) — katalog + depo. Spec §2, §4, §7 S2.

İKİ KATMANLI koruma (`documents/service.py` deseninin birebiri): `inventory`
izni router'da YETKİYİ verir, bu modül `projects.service.visible_projects` ile
KAPSAMI belirler.

## Kapsam iki varlıkta FARKLIDIR — ve bu bilinçlidir

* **`stock_items` (katalog): kapsam süzgeci YOKTUR.** Tabloda `project_id`
  kolonu bile yoktur (spec §2): aynı "Nervürlü Demir Ø12" kartı her projede
  kullanılır. IDOR unutulmuş DEĞİLDİR — sonraki okuyucu buraya proje süzgeci
  EKLEMESİN (`personnel` deseninin aynısı).
* **`warehouses` (depo): kapsam süzgeci VARDIR** ama yalnız ŞANTİYELİ depolara
  uygulanır. Merkez depo (`site_id IS NULL`) `inventory` izni olan HERKESE
  görünür — spec §7 **S2b**, kullanıcı onaylı.

## Hareket / türev uçları BU DOSYADA YOKTUR

Bakiye, durum formülü, KPI ve `stock_entries` yazımı T3'ün işidir. Bakiye
KOLONU açılmaz (spec §3): `SUM(stock_entry_lines.quantity)` türevdir.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    DuplicateError,
    NotFoundError,
    RelatedRecordsExistError,
    SiteValidationError,
)
from app.modules.audit import messages
from app.modules.inventory import guards, repository
from app.modules.inventory.models import StockCategory, StockItem, Warehouse
from app.modules.inventory.schemas import (
    StockItemCreate,
    StockItemUpdate,
    WarehouseCreate,
)
from app.modules.projects.service import visible_projects
from app.modules.sites import repository as sites_repository
from app.modules.sites.models import Site
from app.modules.users.models import User

PERMISSION_MODULE = "inventory"
"""Spec §7 S5: izin anahtarı seed'de ZATEN vardı ("Stok & Depo", 9. modül, grup
STOK_SATINALMA) — yeni izin modülü AÇILMAZ, izin migration'ı YOKTUR.

Kapılar: okuma `view`, yazma `full`, silme `admin` (`full` silmeyi KAPSAMAZ,
`app/core/access.py`). Sonucu (kabul edildi): seed matrisinde `inventory:admin`
yalnız `system_admin`dedir — patron da satınalma da depo SİLEMEZ.
"""


# --- Malzeme kartı (katalog) ---


async def get_stock_item(session: AsyncSession, item_id: uuid.UUID) -> StockItem:
    item = await repository.get_stock_item(session, item_id)
    if item is None:
        raise NotFoundError(guards.STOCK_ITEM_MISSING)
    return item


async def _assert_code_free(
    session: AsyncSession, code: str, *, exclude_id: uuid.UUID | None = None
) -> None:
    """`code` GLOBAL tekilliği — UYGULAMA katmanında.

    DB `UNIQUE`ına düşülseydi kullanıcı "Veri bütünlüğü hatası" görürdü; burada
    alanına özel Türkçe 409 verilir. DB kısıtı İKİNCİ katman olarak KALIR:
    kontrol ile INSERT arasında başka bir istek aynı kodu yazarsa
    `IntegrityError` → 409 eşlemesi devreye girer.
    """
    if await repository.find_stock_item_by_code(session, code, exclude_id=exclude_id) is not None:
        raise DuplicateError(guards.DUPLICATE_STOCK_ITEM_CODE)


async def list_stock_items(
    session: AsyncSession,
    *,
    category: StockCategory | None,
    q: str | None,
    is_active: bool | None,
    limit: int,
    offset: int,
) -> tuple[list[StockItem], int]:
    """Katalog listesi + toplam. **Kapsam süzgeci YOK** (modül docstring'i).

    `is_active` GÖNDERİLMEZSE süzgeç uygulanmaz — pasif kart sessizce gizlenmez;
    ekran hangi kümeyi istediğini açıkça söyler (`personnel` kararı).
    """
    items = await repository.list_stock_items(
        session, category=category, q=q, is_active=is_active, limit=limit, offset=offset
    )
    total = await repository.count_stock_items(session, category=category, q=q, is_active=is_active)
    return items, total


async def create_stock_item(session: AsyncSession, data: StockItemCreate) -> tuple[StockItem, str]:
    code = data.code.strip()
    await _assert_code_free(session, code)
    item = StockItem(
        code=code,
        name=data.name.strip(),
        category=data.category,
        unit=data.unit.strip(),
        min_stock=data.min_stock,
        is_active=data.is_active,
    )
    session.add(item)
    await session.flush()
    return item, messages.stock_item_created(item.code, item.name)


async def update_stock_item(
    session: AsyncSession, item_id: uuid.UUID, data: StockItemUpdate
) -> tuple[StockItem, str]:
    """Kısmi güncelleme. Gönderilmeyen alan ile `null` gönderilen alan
    `exclude_unset` ile ayrılır: `min_stock: null` eşiği SİLER, hiç göndermemek
    ona DOKUNMAZ. `exclude_unset` olmadan bir ad değişikliği eşiği sessizce
    silerdi (`DocumentUpdate` dersi).

    **Kullanımdan kaldırma da BURADAN geçer** (`is_active: false`) — DELETE ucu
    yoktur (spec §4).
    """
    item = await get_stock_item(session, item_id)
    verilen = data.model_dump(exclude_unset=True)

    if "code" in verilen:
        verilen["code"] = verilen["code"].strip()
        await _assert_code_free(session, verilen["code"], exclude_id=item.id)
    for alan in ("name", "unit"):
        if alan in verilen:
            verilen[alan] = verilen[alan].strip()

    for alan, deger in verilen.items():
        setattr(item, alan, deger)
    await session.flush()
    return item, messages.stock_item_updated(item.code, item.name)


# --- Depo kapsamı (IDOR) ---


async def _visible_project_ids(session: AsyncSession, actor: User) -> list[uuid.UUID]:
    return [p.id for p in await visible_projects(session, actor)]


async def visible_warehouse(
    session: AsyncSession, actor: User, warehouse_id: uuid.UUID
) -> tuple[Warehouse, Site | None]:
    """Tekil erişimin TEK kapısı — okuma da yazma da buradan geçer.

    Merkez depo (`site_id IS NULL`) kapsam süzgecine TABİ DEĞİLDİR (spec §7 S2b):
    izni olan herkes erişir. Şantiyeli depoda şantiyenin projesi görünür kümede
    değilse **404** döner ve gövde var OLMAYAN kimliğinkiyle BİREBİR AYNIDIR —
    403 verilseydi elinde kimlik olan kullanıcı kaydın var olduğunu öğrenirdi.
    """
    warehouse = await repository.get_warehouse(session, warehouse_id)
    if warehouse is None:
        raise NotFoundError(guards.WAREHOUSE_MISSING)
    if warehouse.site_id is None:
        return warehouse, None
    site = await sites_repository.get_site(session, warehouse.site_id)
    if site is None or site.project_id not in await _visible_project_ids(session, actor):
        raise NotFoundError(guards.WAREHOUSE_MISSING)
    return warehouse, site


async def _assert_site_visible(
    session: AsyncSession, actor: User, site_id: uuid.UUID | None
) -> Site | None:
    """Gövdedeki `site_id` görünür bir şantiye mi? Değilse **422** (404 DEĞİL).

    Var OLMAYAN kimlik ile GÖRÜNMEYEN kimlik AYNI cümleyi alır (`guards`
    gerekçesi). `None` meşrudur ve MERKEZ depo demektir.
    """
    if site_id is None:
        return None
    site = await sites_repository.get_site(session, site_id)
    if site is None or site.project_id not in await _visible_project_ids(session, actor):
        raise SiteValidationError(guards.WAREHOUSE_SITE_INVALID)
    return site


async def _assert_warehouse_name_free(
    session: AsyncSession,
    site_id: uuid.UUID | None,
    name: str,
    *,
    exclude_id: uuid.UUID | None = None,
) -> None:
    """Kapsam içinde ad tekilliği — UYGULAMA KATMANINDA.

    ⚠️ Bu kontrol "ihtiyaten" değil ZORUNLUDUR: `uq_warehouses_site_name`
    Postgres'in `NULLS DISTINCT` semantiği yüzünden `site_id IS NULL` olduğu
    ANDA (MERKEZ depo) fiilen çalışmaz (T1 notu). Yani DB yalnız şantiyeli
    depoları korur; merkez dalında tek savunma BU FONKSİYONDUR.
    """
    mevcut = await repository.find_warehouse_by_name(session, site_id, name, exclude_id=exclude_id)
    if mevcut is not None:
        raise DuplicateError(guards.DUPLICATE_WAREHOUSE_NAME)


# --- Depo okuma / yazma ---


async def list_warehouses(
    session: AsyncSession, actor: User, *, limit: int, offset: int
) -> tuple[list[Warehouse], int]:
    project_ids = await _visible_project_ids(session, actor)
    items = await repository.list_warehouses(session, project_ids, limit=limit, offset=offset)
    total = await repository.count_warehouses(session, project_ids)
    return items, total


async def create_warehouse(
    session: AsyncSession, actor: User, data: WarehouseCreate
) -> tuple[Warehouse, str]:
    """Sıra sabittir: kapsam doğrulaması (422) → ad tekilliği (409).

    Önce 409 bakılsaydı, yabancı bir `site_id` gönderen kullanıcı o şantiyede
    hangi depo adlarının KULLANILDIĞINI öğrenebilirdi (`documents.create_folder`
    dersi).
    """
    site = await _assert_site_visible(session, actor, data.site_id)
    name = data.name.strip()
    await _assert_warehouse_name_free(session, data.site_id, name)

    warehouse = Warehouse(name=name, site_id=data.site_id)
    session.add(warehouse)
    await session.flush()
    return warehouse, messages.warehouse_created(
        None if site is None else site.name, warehouse.name
    )


async def rename_warehouse(
    session: AsyncSession, warehouse: Warehouse, site: Site | None, name: str
) -> tuple[Warehouse, str]:
    """YALNIZ ad değişir — kapsam (`site_id`) DEĞİŞMEZ (`schemas` gerekçesi).

    Eski ad denetim metni için değişiklikten ÖNCE okunur (`role_renamed` dersi):
    sonra okunsaydı günlükte yeni ad iki kez çıkar ve neyin değiştiği kaybolurdu.
    """
    yeni = name.strip()
    await _assert_warehouse_name_free(session, warehouse.site_id, yeni, exclude_id=warehouse.id)
    eski = warehouse.name
    warehouse.name = yeni
    await session.flush()
    return warehouse, messages.warehouse_renamed(None if site is None else site.name, eski, yeni)


async def delete_warehouse(session: AsyncSession, warehouse: Warehouse, site: Site | None) -> str:
    """YALNIZ HAREKETSİZ depo silinir; hareketi varsa 409 (`guards`).

    Korkuluk olmadan da DB engellerdi (`stock_entries.warehouse_id` RESTRICT'tir)
    ama kullanıcı anlaşılmaz bir "Veri bütünlüğü hatası" görürdü; burada
    eyleme dönük Türkçe bir mesaj alır. DB kısıtı İKİNCİ katman olarak KALIR.

    YARIŞ: satır önce DIŞLAYICI kilitlenir; kontrol ile `DELETE` arasına yeni
    bir hareket giremez. ⚠️ T3 NOTU: hareket yazan uç depoyu `FOR SHARE` ile
    kilitlemelidir, yoksa yarış o ayakta açık kalır.

    Denetim metni satır YOK OLMADAN ÖNCE kurulur. Engellenen silme (409) istisna
    attığı için denetime HİÇBİR ŞEY yazmaz — günlük gerçekleşen olayı kaydeder,
    denemeyi değil.
    """
    await repository.lock_warehouse_for_update(session, warehouse.id)
    if await repository.warehouse_has_entries(session, warehouse.id):
        raise RelatedRecordsExistError(guards.WAREHOUSE_HAS_ENTRIES)
    detail = messages.warehouse_deleted(None if site is None else site.name, warehouse.name)
    await session.delete(warehouse)
    await session.flush()
    return detail
