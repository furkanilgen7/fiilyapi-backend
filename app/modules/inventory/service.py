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
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    DuplicateError,
    NotFoundError,
    RelatedRecordsExistError,
)
from app.modules.audit import messages
from app.modules.dashboard.schemas import ListPlaceholder
from app.modules.inventory import guards, repository
from app.modules.inventory.balance import StockStatus
from app.modules.inventory.models import (
    StockCategory,
    StockEntry,
    StockEntryLine,
    StockEntryType,
    StockItem,
    Warehouse,
)
from app.modules.inventory.schemas import (
    SiteStockKpis,
    SiteStockResponse,
    SiteStockRow,
    StockEntryCreate,
    StockEntryLineResponse,
    StockEntryResponse,
    StockItemCreate,
    StockItemUpdate,
    StockSummaryKpis,
    StockSummaryResponse,
    StockSummaryRow,
    StockWarehouseBalance,
    WarehouseCreate,
)
from app.modules.projects.schemas import MetricPlaceholder, metric
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

    `is_active` GÖNDERİLMEZSE suzgec uygulanmaz — pasif kart sessizce gizlenmez;
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
    """Gövdedeki `site_id` görünür bir şantiye mi? Değilse **404**.

    ⚠️ **T4-artçı kararı (2026-08-11, kullanıcı — spec'e EK KARAR):** burası
    önce 422 veriyordu. Kural TEK cümleye bağlandı: **görünmez/yok VARLIK
    referansı = 404 · biçim/kural ihlali = 422.** `site_id` bir VARLIK
    referansıdır, dolayısıyla `POST /stock/entries`in `warehouse_id`i ile AYNI
    kodu döndürür — iki uç arasında emsal ayrışması bırakılmadı.

    Var OLMAYAN kimlik ile GÖRÜNMEYEN kimlik AYNI cümleyi alır (`guards`
    gerekçesi). `None` meşrudur ve MERKEZ depo demektir.
    """
    if site_id is None:
        return None
    site = await sites_repository.get_site(session, site_id)
    if site is None or site.project_id not in await _visible_project_ids(session, actor):
        raise NotFoundError(guards.WAREHOUSE_SITE_INVALID)
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
    """Sıra sabittir: kapsam doğrulaması (**404**, T4-artçı) → ad tekilliği (409).

    Önce 409 bakılsaydı, yabancı bir `site_id` gönderen kullanıcı o şantiyede
    hangi depo adlarının KULLANILDIĞINI öğrenebilirdi (`documents.create_folder`
    dersi). Sıra kod DEĞİŞSE DE korunur: 404'ün 409'dan önce gelmesi şarttır.
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


# --- Hareket yazımı (T3) ---

PENDING_PURCHASING = "purchasing"
"""E3 "Bekleyen Sipariş" KPI'ının bağlı olduğu modül anahtarı (SA dilimi).
Kullanıcıya gösterilecek metin DEĞİL, B6 zarf sözleşmesindeki anahtardır."""

PENDING_SITE_PLANNING = "site_planning"
"""ŞS "Aylık İhtiyaç" / "Bölüm" sütunlarının bağlı olduğu modül anahtarı."""

_MONEY = Decimal("0.01")


async def _assert_items_exist(session: AsyncSession, item_ids: list[uuid.UUID]) -> None:
    """Satırların TAMAMI TEK sorguda doğrulanır — ve YAZIMDAN ÖNCE.

    Atomikliğin taşıyıcısı budur: kart başına `session.get` ile ilerlenseydi
    hem N sorgu açılır hem de ilk satırlar yazıldıktan sonra hata çıkardı.
    """
    eksik = set(item_ids) - await repository.existing_item_ids(session, item_ids)
    if eksik:
        raise NotFoundError(guards.ENTRY_ITEM_INVALID)


async def _assert_receiver_exists(session: AsyncSession, user_id: uuid.UUID | None) -> None:
    """SG 88 "Teslim Alan". FK `SET NULL`dur ve var olmayan kimlik zaten
    `IntegrityError`a düşerdi; oradaki gövde "Veri bütünlüğü hatası"dır ve
    kullanıcı hangi alanı düzelteceğini öğrenemezdi."""
    if user_id is not None and await session.get(User, user_id) is None:
        raise NotFoundError(guards.ENTRY_RECEIVER_INVALID)


async def create_stock_entry(
    session: AsyncSession, actor: User, data: StockEntryCreate
) -> tuple[StockEntry, list[StockEntryLine], str]:
    """Başlık + satırlar ATOMİK yazılır: doğrulamaların HEPSİ yazımdan ÖNCEDİR.

    Sıra bilinçlidir:
      1. tipe bağlı gövde kuralları — şemada çözülür, DB'ye hiç dokunulmaz (**422**);
      2. IDOR: hedef VE kaynak depo görünür mü (**404**, `visible_warehouse`);
      3. `FOR SHARE` kilidi (aşağıdaki not);
      4. kart ve teslim-alan doğrulaması (**404** — T4-artçı kuralı: gövde içi
         VARLIK referansı 404'tür, biçim/kural ihlali 422);
      5. ancak bundan sonra `session.add`.

    Böylece geçersiz bir satır yüzünden ne başlık ne satır yazılır — testte
    DB sayımı SIFIR kalır.

    ⚠️ **KİLİT (T2'nin devir notu):** hedef ve kaynak depo `FOR SHARE` ile
    kilitlenmezse eşzamanlı `DELETE /warehouses/{id}` penceresinde INSERT
    DB'nin `RESTRICT` kısıtına düşer ve kullanıcıya **500** döner. Silme yolu
    aynı satırı `FOR UPDATE` ile kilitler; ikisi birbirini dışlar.

    ÇİFT BACAK için AYNA SATIR YAZILMAZ: kaynak bacağı bakiye sorgusunda
    (`balance.legs`) üretilir. Gerekçesi o modülün docstring'indedir.

    ⚠️ **SİPARİŞ BAĞI (SA T4, §7 S4):** `purchase_order_id` gövdede varsa
    sipariş YAZIMDAN ÖNCE çözülür (görünmeyen/olmayan → **404**, hiçbir şey
    yazılmaz) ve yazımdan SONRA `delivered` damgalanır. İki adım, `stock_link`
    modülünün gerekçesindeki sebeple ayrıdır.

    ⚠️ **İMPORT GECİKMELİDİR ve bu bilinçlidir:** `procurement` bu dosyanın
    başında import EDİLMEZ, çünkü `procurement.repository` zaten `inventory`yi
    okur ve modül düzeyinde çember kurulurdu (P10 `cost_cards` dersi). Yön iki
    bekçi testiyle kilitli (`test_stock_entry_delivery_chain`).
    """
    from app.modules.procurement import stock_link

    # Şantiye künyesi hareket denetiminde KULLANILMAZ (depo adı kapsamı zaten
    # taşır); `visible_warehouse` yine de tek görünürlük kapısı olduğu için çağrılır.
    hedef, _ = await visible_warehouse(session, actor, data.warehouse_id)
    kaynak: Warehouse | None = None
    if data.source_warehouse_id is not None:
        kaynak, _ = await visible_warehouse(session, actor, data.source_warehouse_id)

    kilitlenecek = sorted({hedef.id} | ({kaynak.id} if kaynak is not None else set()))
    await repository.lock_warehouses_for_share(session, kilitlenecek)

    await _assert_items_exist(session, [satir.item_id for satir in data.lines])
    await _assert_receiver_exists(session, data.received_by_user_id)
    order = (
        None
        if data.purchase_order_id is None
        else await stock_link.resolve_order(session, actor, data.purchase_order_id)
    )

    entry = StockEntry(
        entry_type=data.entry_type,
        entry_date=data.entry_date,
        warehouse_id=hedef.id,
        source_warehouse_id=None if kaynak is None else kaynak.id,
        supplier_name=None if data.supplier_name is None else data.supplier_name.strip(),
        purchase_order_id=None if order is None else order.id,
        delivery_note_no=(None if data.delivery_note_no is None else data.delivery_note_no.strip()),
        received_by_user_id=data.received_by_user_id,
        note=data.note,
    )
    session.add(entry)
    await session.flush()

    lines = [
        StockEntryLine(
            entry_id=entry.id,
            item_id=satir.item_id,
            quantity=satir.quantity,
            unit_price=satir.unit_price,
            quality=satir.quality,
        )
        for satir in data.lines
    ]
    session.add_all(lines)
    await session.flush()

    if order is not None:
        # Damga YAZIMDAN SONRA: hareket yazılamasaydı sipariş teslim
        # görünmemeliydi. Zaten `delivered` siparişte sessizce hiçbir şey
        # olmaz (idempotent — `stock_link` gerekçesi).
        await stock_link.stamp_delivery(session, order)

    detail = messages.stock_entry_created(
        entry.entry_type.value,
        hedef.name,
        None if kaynak is None else kaynak.name,
        entry.delivery_note_no,
    )
    return entry, lines, detail


def to_entry_response(entry: StockEntry, lines: list[StockEntryLine]) -> StockEntryResponse:
    """Satırlar PARAMETREDİR, `entry.lines`tan OKUNMAZ.

    `StockEntry.lines` ilişkisi `lazy="raise"`dır: yazma yolunda ona dokunmak
    async oturumda `MissingGreenlet` (500) üretirdi. Liste ucu satırları
    `selectinload` ile önceden yükler ve aynı fonksiyona geçirir.
    """
    return StockEntryResponse(
        id=entry.id,
        entry_type=entry.entry_type,
        entry_date=entry.entry_date,
        warehouse_id=entry.warehouse_id,
        source_warehouse_id=entry.source_warehouse_id,
        supplier_name=entry.supplier_name,
        purchase_order_id=entry.purchase_order_id,
        delivery_note_no=entry.delivery_note_no,
        received_by_user_id=entry.received_by_user_id,
        note=entry.note,
        created_at=entry.created_at,
        lines=[StockEntryLineResponse.model_validate(satir) for satir in lines],
    )


async def list_stock_entries(
    session: AsyncSession,
    actor: User,
    *,
    entry_type: StockEntryType | None,
    warehouse_id: uuid.UUID | None,
    date_from: date | None,
    date_to: date | None,
    limit: int,
    offset: int,
) -> tuple[list[StockEntryResponse], int]:
    project_ids = await _visible_project_ids(session, actor)
    suzgec = {
        "entry_type": entry_type,
        "warehouse_id": warehouse_id,
        "date_from": date_from,
        "date_to": date_to,
    }
    entries = await repository.list_entries(
        session, project_ids, limit=limit, offset=offset, **suzgec
    )
    total = await repository.count_entries(session, project_ids, **suzgec)
    return [to_entry_response(e, list(e.lines)) for e in entries], total


# --- Türev okuma: E3 genel özeti + ŞS şantiye özeti ---


def _quantize_money(value: Decimal | None) -> Decimal:
    return (Decimal("0") if value is None else value).quantize(_MONEY, rounding=ROUND_HALF_UP)


def _breakdown_by_item(rows: list) -> dict[uuid.UUID, list[StockWarehouseBalance]]:
    """Depo kırılımı satırlarını kaleme göre gruplar — kalem başına sorgu YOK."""
    gruplar: dict[uuid.UUID, list[StockWarehouseBalance]] = {}
    for row in rows:
        gruplar.setdefault(row.item_id, []).append(
            StockWarehouseBalance(
                warehouse_id=row.warehouse_id,
                warehouse_name=row.warehouse_name,
                site_id=row.site_id,
                balance=row.balance,
            )
        )
    return gruplar


async def build_stock_summary(
    session: AsyncSession,
    actor: User,
    *,
    status: StockStatus | None,
    category: StockCategory | None,
    q: str | None,
    limit: int,
    offset: int,
) -> StockSummaryResponse:
    """E3'ün veri kaynağı. Kapsam: GÖRÜNEN tüm depolar — merkez DAHİL (spec §3).

    Dört sorgu koşar ve sayısı veri hacminden BAĞIMSIZDIR (N+1 yok): sayfa ·
    sayım · KPI · depo kırılımı. KPI sayfayı değil SÜZÜLEN KÜMEYİ özetler.
    """
    project_ids = await _visible_project_ids(session, actor)
    warehouse_ids = repository.visible_warehouse_ids(project_ids)
    ctx = repository.summary_context(warehouse_ids)
    suzgec = {
        "status": None if status is None else status.value,
        "category": category,
        "q": q,
    }

    rows = await repository.list_summary_rows(
        session, ctx, only_moved=False, limit=limit, offset=offset, **suzgec
    )
    total = await repository.count_summary_rows(session, ctx, only_moved=False, **suzgec)
    kpi = await repository.summary_kpis(session, ctx, only_moved=False, **suzgec)
    kirilim = _breakdown_by_item(
        await repository.warehouse_breakdown(session, warehouse_ids, [row[0].id for row in rows])
    )

    return StockSummaryResponse(
        items=[
            StockSummaryRow(
                id=row[0].id,
                code=row[0].code,
                name=row[0].name,
                category=row[0].category,
                unit=row[0].unit,
                min_stock=row[0].min_stock,
                balance=row.balance,
                status=row.status,
                last_unit_price=row.last_price,
                warehouses=kirilim.get(row[0].id, []),
            )
            for row in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
        kpis=StockSummaryKpis(
            total_value=_quantize_money(kpi.total_value),
            critical_count=kpi.critical_count,
            low_count=kpi.low_count,
            total_items=kpi.total_items,
            items_without_price=kpi.items_without_price,
            # E3 81 "Bekleyen Sipariş": SA T4'te GERÇEĞE döndü (aşağıdaki
            # yardımcının gerekçesi).
            pending_orders=await _pending_orders_metric(session, actor),
        ),
    )


async def _pending_orders_metric(session: AsyncSession, actor: User) -> MetricPlaceholder:
    """E3 81 "Bekleyen Sipariş" = `approved` + `in_transit` sipariş sayısı.

    ⚠️ **İKİ ANAHTAR KARIŞTIRILMAZ:** `PENDING_PURCHASING` (`"purchasing"`) bu
    zarfın ETİKETİ, `procurement` ise izin matrisinin modül anahtarıdır. Etiket
    yalnızca zarf BOŞ kaldığında görünür ve artık o dal koşmaz — sabit yine de
    silinmez, ŞS'nin kardeş zarfı ile aynı sözleşmeyi belgeler.

    Zarf ELLE KURULMAZ: `metric` tek kapıdır (P10 dersi — tutarsız üçlü
    pydantic doğrulayıcısında 500 üretir). Sayı her zaman vardır, dolayısıyla
    zarf her zaman DOLUDUR: sıfır bekleyen sipariş "veri yok" değil gerçek bir
    cevaptır.

    ⚠️ İmport GECİKMELİDİR (`create_stock_entry` gerekçesi: çember yasağı).
    """
    from app.modules.procurement import stock_link

    sayi = await stock_link.pending_order_count(session, await _visible_project_ids(session, actor))
    return metric(Decimal(sayi), PENDING_PURCHASING)


async def _visible_site(session: AsyncSession, actor: User, site_id: uuid.UUID) -> Site:
    """Şantiye → proje, ardından PAYLAŞILAN görünürlük süzgeci.

    Kapsam mantığı KOPYALANMAZ: `visible_projects` bu repoda tek kaynaktır
    (`_visible_project_ids` üzerinden). Görünmeyen şantiye ile var olmayan
    şantiye AYNI 404 gövdesini alır.
    """
    site = await sites_repository.get_site(session, site_id)
    if site is None or site.project_id not in await _visible_project_ids(session, actor):
        raise NotFoundError(guards.SITE_MISSING)
    return site


async def build_site_stock(
    session: AsyncSession, actor: User, site_id: uuid.UUID, *, limit: int, offset: int
) -> SiteStockResponse:
    """ŞS'nin veri kaynağı. Kapsam: YALNIZ o şantiyenin depoları.

    **Merkez depo (`site_id IS NULL`) BURAYA GİRMEZ** (spec §3 kararı, tartışma
    yok): girseydi aynı merkez stok her şantiyede tekrar sayılır ve şantiye
    toplamları şirket toplamını aşardı. Genel özet (`/stock/summary`) ise merkez
    dahil hepsini kapsar — iki uç AYNI türetmeyi farklı kapsamla çağırır.

    `only_moved=True`: şantiyeye hiç girmemiş katalog kartı listelenmez.
    """
    site = await _visible_site(session, actor, site_id)
    warehouse_ids = repository.site_warehouse_ids(site.id)
    ctx = repository.summary_context(warehouse_ids)
    suzgec = {"status": None, "category": None, "q": None}

    rows = await repository.list_summary_rows(
        session, ctx, only_moved=True, limit=limit, offset=offset, **suzgec
    )
    total = await repository.count_summary_rows(session, ctx, only_moved=True, **suzgec)
    kpi = await repository.summary_kpis(session, ctx, only_moved=True, **suzgec)

    return SiteStockResponse(
        items=[
            SiteStockRow(
                id=row[0].id,
                code=row[0].code,
                name=row[0].name,
                category=row[0].category,
                unit=row[0].unit,
                min_stock=row[0].min_stock,
                balance=row.balance,
                status=row.status,
                # ŞS "Aylık İhtiyaç" / "Bölüm" — P-YT3 (2026-08-23) denetlendi ve
                # KALDI. `site_planning` CANLI; engel (a) plan izgarasının malzeme
                # satırı taşımaması, (b) `section` için talep-bölüm bağının YANLIŞ
                # ANLAM taşıması. Tam gerekçe: `schemas.SiteStockRow` docstring'i.
                monthly_need=MetricPlaceholder(pending_module=PENDING_SITE_PLANNING),
                section=ListPlaceholder(pending_module=PENDING_SITE_PLANNING),
            )
            for row in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
        kpis=SiteStockKpis(
            total_value=_quantize_money(kpi.total_value),
            critical_count=kpi.critical_count,
            low_count=kpi.low_count,
            total_items=kpi.total_items,
            items_without_price=kpi.items_without_price,
        ),
    )
