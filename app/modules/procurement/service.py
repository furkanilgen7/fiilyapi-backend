"""Satinalma is kurallari (T2) — tedarikci katalogu + satin alma talebi.

Spec: `docs/superpowers/specs/2026-08-12-sa-satinalma-design.md` §2, §3, §4.

IKI KATMANLI koruma (`inventory/service.py` deseninin birebiri): `procurement`
izni router'da YETKIYI verir, bu modul `projects.service.visible_projects` ile
KAPSAMI belirler.

## Kapsam iki varlikta FARKLIDIR — ve bu bilincli

* **`suppliers` (katalog): kapsam suzgeci YOKTUR.** Tabloda `project_id` kolonu
  bile yoktur (spec §2): ayni "Demirsan A.S." her projede kullanilir. IDOR
  unutulmus DEGILDIR — sonraki okuyucu buraya proje suzgeci EKLEMESIN
  (`stock_items`/`personnel` deseninin aynisi). **Ama kartin PARA turevi
  ("Bu Yil Toplam Siparis") KAPSAMLIDIR:** gorunmeyen projenin siparisi tutara
  girmez.
* **`purchase_requests`: kapsam suzgeci VARDIR.** Talep bir PROJEYE aittir;
  gorunmeyen projenin talebi listede yoktur ve tekil erisimde **404** doner —
  var olmayanla ayirt edilemez.

## Taslak-farkindalikli zorunluluk (P6 emsali)

Tutarlilik kurallari (XOR, `quantity > 0`, uzunluk tavanlari) HER yazmada
kosar ve SEMA katmanindadir. Zorunluluk kurallari (ihtiyac tarihi, en az bir
kalem) yalnizca taslak DISINDA kosar; TEK kaynaklari `validation.py`dir ve
onlari cagiran `submit` ucu **T3'undur** — bu dosyada onay/teklif/siparis
mantigi YOKTUR.
"""

import uuid
from decimal import Decimal

from sqlalchemy import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import can_delete
from app.core.errors import (
    ConflictError,
    DeleteNotAllowedError,
    NotFoundError,
    ProcurementValidationError,
)
from app.core.timezone import today
from app.modules.approvals import service as approvals_service
from app.modules.audit import messages
from app.modules.inventory.models import StockItem
from app.modules.procurement import guards, numbering, repository, transitions
from app.modules.procurement.models import (
    PurchaseOrder,
    PurchaseOrderStatus,
    PurchasePriority,
    PurchaseQuote,
    PurchaseRequest,
    PurchaseRequestLine,
    PurchaseRequestStatus,
    Supplier,
)
from app.modules.procurement.schemas import (
    PurchaseOrderCreate,
    PurchaseOrderListResponse,
    PurchaseOrderResponse,
    PurchaseOrderUpdate,
    PurchaseQuoteCard,
    PurchaseQuoteCreate,
    PurchaseQuoteListResponse,
    PurchaseQuoteResponse,
    PurchaseQuoteUpdate,
    PurchaseRequestCreate,
    PurchaseRequestLineCreate,
    PurchaseRequestLineResponse,
    PurchaseRequestListResponse,
    PurchaseRequestListRow,
    PurchaseRequestResponse,
    PurchaseRequestUpdate,
    SupplierCard,
    SupplierCreate,
    SupplierResponse,
    SupplierUpdate,
)
from app.modules.projects.service import visible_projects
from app.modules.sites import repository as sites_repository
from app.modules.users.models import User

PERMISSION_MODULE = guards.PERMISSION_MODULE
"""Izin anahtari — TEK KOPYA `guards.PERMISSION_MODULE`dedir (T3'te oraya
tasindi: `repository.actor_level` de ona ihtiyac duyar ve `repository → service`
ithalati donguye girerdi). Bu ad geriye donuk takma addir; router ve testler
`service.PERMISSION_MODULE` yazmaya devam eder."""


async def _visible_project_ids(session: AsyncSession, actor: User) -> list[uuid.UUID]:
    return [p.id for p in await visible_projects(session, actor)]


# --- Tedarikci (TED) ---


async def list_suppliers(
    session: AsyncSession,
    actor: User,
    *,
    q: str | None,
    category: str | None,
    is_active: bool | None,
    limit: int,
    offset: int,
) -> tuple[list[SupplierCard], int]:
    """TED kart izgarasinin veri kaynagi. **Katalogda kapsam suzgeci YOK**
    (modul docstring'i); kapsam yalniz PARA turevine uygulanir."""
    totals = repository.supplier_order_totals(
        await _visible_project_ids(session, actor), today().year
    )
    rows = await repository.list_suppliers(
        session, totals, q=q, category=category, is_active=is_active, limit=limit, offset=offset
    )
    total = await repository.count_suppliers(session, q=q, category=category, is_active=is_active)
    return [_to_supplier_card(row) for row in rows], total


def _to_supplier_card(row: Row) -> SupplierCard:
    """`(Supplier, orders_total, orders_count)` uclusunu TED kartina cevirir.

    Turev alanlar kart nesnesinden DEGIL satirdan gelir — modelde karsiliklari
    yoktur ve olmamalidir (spec §2).
    """
    supplier: Supplier = row[0]
    return SupplierCard(
        **SupplierResponse.model_validate(supplier).model_dump(),
        orders_total_this_year=row.orders_total,
        orders_count_this_year=row.orders_count,
    )


async def get_supplier_card(
    session: AsyncSession, actor: User, supplier_id: uuid.UUID
) -> SupplierCard:
    """Detay ucu liste ile AYNI turetmeyi kullanir (`repository` gerekcesi)."""
    totals = repository.supplier_order_totals(
        await _visible_project_ids(session, actor), today().year
    )
    row = await repository.get_supplier_with_totals(session, totals, supplier_id)
    if row is None:
        raise NotFoundError(guards.SUPPLIER_MISSING)
    return _to_supplier_card(row)


async def get_supplier(session: AsyncSession, supplier_id: uuid.UUID) -> Supplier:
    supplier = await repository.get_supplier(session, supplier_id)
    if supplier is None:
        raise NotFoundError(guards.SUPPLIER_MISSING)
    return supplier


def _strip(deger: str | None) -> str | None:
    return None if deger is None else (deger.strip() or None)


async def create_supplier(session: AsyncSession, data: SupplierCreate) -> tuple[Supplier, str]:
    """Yeni tedarikci karti.

    **AD TEKILLIGI ZORLANMAZ** ve bu bilinclidir: "Demirsan A.S." ile "Demirsan
    Ltd." mesru sekilde iki ayri firmadir, ayni grubun iki sirketi de olabilir.
    `tax_no` da UNIQUE degildir (T1 karari: alan zorunlu bile degil, bosluk
    birakan kayitlarin cakismasi kullaniciyi kilitlerdi).
    """
    supplier = Supplier(
        name=data.name.strip(),
        category=_strip(data.category),
        tax_no=_strip(data.tax_no),
        phone=_strip(data.phone),
        payment_terms=data.payment_terms,
        is_active=data.is_active,
    )
    session.add(supplier)
    await session.flush()
    return supplier, messages.supplier_created(supplier.name)


async def update_supplier(
    session: AsyncSession, supplier_id: uuid.UUID, data: SupplierUpdate
) -> tuple[Supplier, str]:
    """Kismi guncelleme. Gonderilmeyen alan ile `null` gonderilen alan
    `exclude_unset` ile ayrilir: `category: null` etiketi SILER, hic
    gondermemek ona DOKUNMAZ (`StockItemUpdate` dersi).

    **KULLANIMDAN KALDIRMA DA BURADAN GECER** (`is_active: false`) — DELETE ucu
    yoktur (spec §4).
    """
    supplier = await get_supplier(session, supplier_id)
    verilen = data.model_dump(exclude_unset=True)
    for alan in ("name", "category", "tax_no", "phone"):
        if alan in verilen:
            verilen[alan] = _strip(verilen[alan])
    # `name` bosaltilamaz: sema `min_length=1` uygular, `_strip` ise sadece
    # bosluklu bir degeri `None`a cevirebilirdi — o durumda alan atlanir.
    if verilen.get("name") is None:
        verilen.pop("name", None)

    for alan, deger in verilen.items():
        setattr(supplier, alan, deger)
    await session.flush()
    return supplier, messages.supplier_updated(supplier.name)


# --- Talep: kapsam ve govde referanslarinin dogrulanmasi ---


async def visible_request(
    session: AsyncSession, actor: User, request_id: uuid.UUID
) -> PurchaseRequest:
    """Tekil erisimin TEK kapisi — okuma da yazma da buradan gecer.

    Projesi gorunur kumede degilse **404** doner ve govde var OLMAYAN
    kimliginkiyle BIREBIR AYNIDIR — 403 verilseydi elinde kimlik olan kullanici
    kaydin var oldugunu ogrenirdi.
    """
    request = await repository.get_request(session, request_id)
    if request is None or request.project_id not in await _visible_project_ids(session, actor):
        raise NotFoundError(guards.REQUEST_MISSING)
    return request


async def visible_request_locked(
    session: AsyncSession, actor: User, request_id: uuid.UUID
) -> PurchaseRequest:
    """Kapsam suzgeci + `SELECT … FOR UPDATE` — DURUM GECISLERININ giris kapisi.

    🔴 OK-1A T3: onay zinciri talebin satirini kilitli gormek zorundadir ve
    KILIT SIRASI sabittir (**evrak -> zincir**). Okuma uclari kilit ALMAZ —
    `visible_request` orada kalir; gereksiz satir kilidi listeleri ve detay
    okumalarini yazma islemlerinin arkasinda bekletirdi.

    Kapsam karari (404) kilitten ONCE verilir: gorunmeyen bir kaydin satiri
    bosuna kilitlenmez ve govde var OLMAYAN kimliginkiyle BIREBIR AYNIDIR.
    """
    request = await visible_request(session, actor, request_id)
    locked = await repository.get_request_locked(session, request.id)
    if locked is None:
        # Yarista silinmis olabilir — var olmayan kayitla AYNI 404.
        raise NotFoundError(guards.REQUEST_MISSING)
    return locked


async def _assert_scope(
    session: AsyncSession,
    actor: User,
    project_id: uuid.UUID,
    site_id: uuid.UUID | None,
    section_id: uuid.UUID | None,
) -> None:
    """Govdedeki UC varlik referansi: proje · santiye · bolum. Hepsi **404**.

    ST §4b kanonu: *gorunmez/yok VARLIK referansi = 404 · bicim/kural ihlali =
    422.* Var OLMAYAN kimlik ile GORUNMEYEN kimlik AYNI cumleyi alir.

    Zincir SIKIDIR: santiye talebin PROJESINE, bolum de secilen SANTIYEYE ait
    olmalidir. Santiyesiz bolum secimi de 404'tur — bolum santiyenin ic
    kirilimidir (P2 karari) ve tek basina anlamli degildir. Gevsek birakilsaydi
    talep, projesiyle ilgisi olmayan bir bolume baglanabilir ve raporlar
    sessizce yanlis kirilirdi.
    """
    if project_id not in await _visible_project_ids(session, actor):
        raise NotFoundError(guards.REQUEST_PROJECT_INVALID)

    if site_id is not None:
        site = await sites_repository.get_site(session, site_id)
        if site is None or site.project_id != project_id:
            raise NotFoundError(guards.REQUEST_SITE_INVALID)

    if section_id is not None:
        if site_id is None:
            raise NotFoundError(guards.REQUEST_SECTION_INVALID)
        if await sites_repository.get_section_in_site(session, site_id, section_id) is None:
            raise NotFoundError(guards.REQUEST_SECTION_INVALID)


async def _assert_stock_items_exist(
    session: AsyncSession, lines: list[PurchaseRequestLineCreate]
) -> None:
    """Satirlarin TAMAMI TEK sorguda ve YAZIMDAN ONCE dogrulanir (ST deseni).

    Atomikligin tasiyicisi budur: bozuk bir satir yuzunden ne baslik ne satir
    yazilir. Kod **404**tur — satir ICINDE durmasi bunu degistirmez, referans
    yine bir VARLIGADIR (ST T4-artcisi).
    """
    item_ids = [line.stock_item_id for line in lines if line.stock_item_id is not None]
    if not item_ids:
        return
    eksik = set(item_ids) - await repository.existing_stock_item_ids(session, item_ids)
    if eksik:
        raise NotFoundError(guards.REQUEST_STOCK_ITEM_INVALID)


def _assert_draft(request: PurchaseRequest) -> None:
    """Taslak DISINDA duzenleme/silme **409**dur (spec §4).

    404 (yok) ya da 403 (yetki) DEGIL: kullanicinin yetkisi VARDIR, engelleyen
    sey kaydin DURUMUDUR. Kural ayni zamanda ₺500K esiginin en kisa atlatma
    yolunu da kapatir: dusuk tutarla onaylatip sonra kalem sismek IMKANSIZDIR.
    """
    if request.status is not PurchaseRequestStatus.draft:
        raise ConflictError(guards.REQUEST_NOT_DRAFT)


# --- Talep: yazma ---


def _new_lines(
    request_id: uuid.UUID, lines: list[PurchaseRequestLineCreate]
) -> list[PurchaseRequestLine]:
    """Kalemleri govdedeki SIRAYLA kurar.

    `sort_order` DIZININ KENDISIDIR — istemci ayri bir alan gondermez (sema
    gerekcesi): gonderseydi cakisan ya da bosluklu siralar dogar ve sunucunun
    onlari yeniden numaralandirmasi gerekirdi. REPLACE yolu da bu fonksiyondan
    gectigi icin siralama iki yazma yolunda TEK kopyadir.
    """
    return [
        PurchaseRequestLine(
            request_id=request_id,
            stock_item_id=data.stock_item_id,
            free_text_name=_strip(data.free_text_name),
            free_text_unit=_strip(data.free_text_unit),
            quantity=data.quantity,
            estimated_unit_price=data.estimated_unit_price,
            sort_order=sira,
        )
        for sira, data in enumerate(lines)
    ]


async def create_request(
    session: AsyncSession, actor: User, data: PurchaseRequestCreate
) -> tuple[PurchaseRequest, str]:
    """Baslik + kalemler ATOMIK yazilir: dogrulamalarin HEPSI yazimdan ONCEDIR.

    Sira bilinclidir:
      1. XOR / miktar / uzunluk — semada cozulur, DB'ye hic dokunulmaz (**422**);
      2. kapsam: proje · santiye · bolum (**404**, `_assert_scope`);
      3. kalemlerin stok kartlari (**404**, tek toplu sorgu);
      4. ancak bundan sonra numara uretimi ve `session.add`.

    Numara EN SONDA uretilir: `pg_advisory_xact_lock` islem boyu tutulur ve
    dogrulama basarisiz olacaksa kilidi bosuna almamak gerekir.

    **DURUM HER ZAMAN `draft`tir** — gecisler T3'undur.
    """
    await _assert_scope(session, actor, data.project_id, data.site_id, data.section_id)
    await _assert_stock_items_exist(session, data.lines)

    request_no = await numbering.generate_request_number(session)
    request = PurchaseRequest(
        request_no=request_no,
        request_date=data.request_date or today(),
        priority=data.priority,
        project_id=data.project_id,
        site_id=data.site_id,
        section_id=data.section_id,
        needed_by=data.needed_by,
        justification=data.justification,
        status=PurchaseRequestStatus.draft,
        quote_deadline=data.quote_deadline,
        created_by_user_id=actor.id,
    )
    session.add(request)
    await session.flush()

    if data.lines:
        session.add_all(_new_lines(request.id, data.lines))
        await session.flush()

    return request, messages.purchase_request_created(request.request_no)


async def update_request(
    session: AsyncSession, actor: User, request: PurchaseRequest, data: PurchaseRequestUpdate
) -> tuple[PurchaseRequest, str]:
    """YALNIZ taslakta (409 aksi halde). Kalemler gonderilirse REPLACE edilir.

    Kapsam UCLUSU (proje · santiye · bolum) BIRLIKTE dogrulanir: kullanici
    yalniz projeyi degistirse bile eski `site_id` yeni projeye ait olmayabilir
    ve talep sessizce tutarsiz kalirdi. Bu yuzden dogrulama, gonderilen ve
    mevcut degerlerin BIRLESIMI uzerinde kosar.
    """
    _assert_draft(request)
    verilen = data.model_dump(exclude_unset=True)

    project_id = verilen.get("project_id", request.project_id)
    site_id = verilen.get("site_id", request.site_id)
    section_id = verilen.get("section_id", request.section_id)
    await _assert_scope(session, actor, project_id, site_id, section_id)

    if data.lines is not None:
        await _assert_stock_items_exist(session, data.lines)

    # `project_id`/`priority`/`request_date` NOT NULL kolonlardir: `null`
    # gonderilirse mevcut deger KORUNUR (sema hepsini `| None` yazar cunku PATCH
    # govdesi kismidir). Geri kalan alanlar nullable'dir ve `null` onlari SILER.
    for alan in ("project_id", "priority", "request_date"):
        if verilen.get(alan) is not None:
            setattr(request, alan, verilen[alan])
    for alan in ("site_id", "section_id", "needed_by", "justification", "quote_deadline"):
        if alan in verilen:
            setattr(request, alan, verilen[alan])

    if data.lines is not None:
        for eski in await repository.load_request_lines(session, request.id):
            await session.delete(eski)
        await session.flush()
        if data.lines:
            session.add_all(_new_lines(request.id, data.lines))
        await session.flush()

    await session.flush()
    return request, messages.purchase_request_updated(request.request_no)


class _DeletableRequest:
    """`app.core.access.Deletable` protokolune KOPRU.

    Kural KOPYALANMAZ: silme kosulu repoda tek yerdedir (`can_delete`), ama o
    fonksiyon `created_by`/`is_draft` adlarini bekler; talebin karsiliklari
    `created_by_user_id` ve `status is draft`tir. Kopru olmasaydi ayni kural
    burada ikinci kez yazilir ve zamanla sapardi.
    """

    __slots__ = ("created_by", "is_draft")

    def __init__(self, request: PurchaseRequest) -> None:
        self.created_by = request.created_by_user_id
        self.is_draft = request.status is PurchaseRequestStatus.draft


async def can_delete_request(session: AsyncSession, actor: User, request: PurchaseRequest) -> bool:
    """Yanittaki `can_delete` bayragi ile SILME UCU AYNI fonksiyondan beslenir —
    ekran dugmeyi gosterip sonra 403 yemesin."""
    return can_delete(
        actor.id, await repository.actor_level(session, actor), _DeletableRequest(request)
    )


async def delete_request(session: AsyncSession, actor: User, request: PurchaseRequest) -> str:
    """Sira sabittir: durum (409) → yetki (403).

    Once yetkiye bakilsaydi, taslak OLMAYAN bir talebi silmeye calisan sahibi
    "yetkiniz yok" mesaji alir ve asil sebebi (kayit artik taslak degil)
    ogrenemezdi.

    Kalemler `ON DELETE CASCADE` ile gider (T1 semasi). Denetim metni satir YOK
    OLMADAN once kurulur (`warehouse_deleted` dersi).
    """
    _assert_draft(request)
    if not await can_delete_request(session, actor, request):
        raise DeleteNotAllowedError(guards.DELETE_NOT_ALLOWED)
    detail = messages.purchase_request_deleted(request.request_no)
    await session.delete(request)
    await session.flush()
    return detail


# --- Talep: okuma ve turevler ---


def _line_total(line: PurchaseRequestLine) -> Decimal | None:
    if line.estimated_unit_price is None:
        return None
    return line.quantity * line.estimated_unit_price


def _to_line_response(
    line: PurchaseRequestLine, item: StockItem | None, balances: dict[uuid.UUID, Decimal]
) -> PurchaseRequestLineResponse:
    """`name`/`unit` iki kapinin ORTAK yuzeyidir: stok kartli kalemde kartin,
    katalogsuz kalemde girilen degerler. Ekran iki dal icin ayri sutun okumak
    zorunda kalmasin."""
    return PurchaseRequestLineResponse(
        id=line.id,
        sort_order=line.sort_order,
        stock_item_id=line.stock_item_id,
        stock_item_code=None if item is None else item.code,
        free_text_name=line.free_text_name,
        free_text_unit=line.free_text_unit,
        name=item.name if item is not None else (line.free_text_name or ""),
        unit=item.unit if item is not None else line.free_text_unit,
        quantity=line.quantity,
        estimated_unit_price=line.estimated_unit_price,
        line_total=_line_total(line),
        # Katalogsuz kalemde bakiye YOKTUR (`null`); kartli kalemde hic hareket
        # gormemis kart 0 doner — "hic alinmadi" ile "stok karti yok" farkli.
        current_stock=None
        if line.stock_item_id is None
        else balances.get(line.stock_item_id, Decimal("0")),
    )


async def build_request_detail(
    session: AsyncSession, actor: User, request: PurchaseRequest
) -> PurchaseRequestResponse:
    """FST detay govdesi. UC sorgu kosar ve sayisi KALEM SAYISINDAN BAGIMSIZDIR
    (N+1 yok): kalemler+kartlar · bakiyeler · silme yetkisi."""
    lines = await repository.list_request_lines(session, request.id)
    item_ids = [line.stock_item_id for line, _ in lines if line.stock_item_id is not None]
    balances = await repository.current_stock_by_item(
        session, await _visible_project_ids(session, actor), item_ids
    )
    satirlar = [_to_line_response(line, item, balances) for line, item in lines]
    toplam = sum((s.line_total for s in satirlar if s.line_total is not None), Decimal("0"))

    return PurchaseRequestResponse(
        **_base_fields(request),
        estimated_total=toplam,
        can_delete=await can_delete_request(session, actor, request),
        lines=satirlar,
    )


def _base_fields(request: PurchaseRequest) -> dict:
    return {
        alan: getattr(request, alan)
        for alan in (
            "id",
            "request_no",
            "request_date",
            "priority",
            "project_id",
            "site_id",
            "section_id",
            "needed_by",
            "justification",
            "status",
            "quote_deadline",
            "approved_by_user_id",
            "approved_at",
            "rejected_at",
            "rejection_reason",
            "created_by_user_id",
            "created_at",
        )
    }


async def list_requests(
    session: AsyncSession,
    actor: User,
    *,
    status: PurchaseRequestStatus | None,
    project_id: uuid.UUID | None,
    priority: PurchasePriority | None,
    q: str | None,
    limit: int,
    offset: int,
) -> PurchaseRequestListResponse:
    """SAT tablosunun veri kaynagi.

    Dort sorgu kosar ve sayisi SATIR SAYISINDAN BAGIMSIZDIR: sayfa (tahmini
    toplam ve kalem sayisi JOIN'li alt sorgudan) · sayim · aktorun izin
    seviyesi (`can_delete` icin TEK kez) · gorunur projeler.
    """
    project_ids = await _visible_project_ids(session, actor)
    totals = repository.request_totals()
    suzgec = {"status": status, "project_id": project_id, "priority": priority, "q": q}

    rows = await repository.list_requests(
        session, project_ids, totals, limit=limit, offset=offset, **suzgec
    )
    total = await repository.count_requests(session, project_ids, **suzgec)
    level = await repository.actor_level(session, actor)

    return PurchaseRequestListResponse(
        items=[
            PurchaseRequestListRow(
                **_base_fields(row[0]),
                estimated_total=row.estimated_total,
                line_count=row.line_count,
                can_delete=can_delete(actor.id, level, _DeletableRequest(row[0])),
            )
            for row in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


# --- T3: onay akisi (submit / approve / reject) ---


async def perform_request_action(
    session: AsyncSession,
    actor: User,
    request: PurchaseRequest,
    action: transitions.RequestAction,
    *,
    reason: str | None = None,
) -> tuple[PurchaseRequest, str]:
    """Uc gecisin TEK yolu — matris `transitions.py`dedir, burada `if status` YOK.

    Denetim metni gecisten SONRA kurulur cunku metin YENI durumu adlandirir;
    kayit yok olmadigi icin `purchase_request_deleted` dersi (once kur) burada
    GECERLI DEGILDIR.

    🔴 OK-1A T3: metin zincirin kararyla BIRLESTIRILIR ve birlestirme kurali
    `approvals.service`te TEK kopyadir (uc evrak ailesi ayni sozlukten okur):
    ARA adimda YALNIZ adim metni yazilir (talebin durumu DEGISMEDI, "onaylandi"
    demek gunluge OLMAMIS bir olguyu yazmak olurdu), SON adimda ve rette IKISI
    DE yazilir.
    """
    decision = await transitions.apply_request_transition(
        session, actor, request, action, reason=reason
    )
    detail = _TRANSITION_MESSAGES[action](request.request_no)
    if action is transitions.RequestAction.reject:
        return request, approvals_service.rejection_audit_detail(detail, decision)
    return request, approvals_service.audit_detail(detail, decision)


_TRANSITION_MESSAGES = {
    transitions.RequestAction.submit: messages.purchase_request_submitted,
    transitions.RequestAction.approve: messages.purchase_request_approved,
    transitions.RequestAction.reject: messages.purchase_request_rejected,
}


# --- T3: teklif alt-kaynagi (TEK) ---


async def _assert_quote_wait(request: PurchaseRequest) -> None:
    """Teklif YAZIMI yalniz `quote_wait`te acik — aksi **409**.

    OKUMA kisitlanmaz: siparise donmus bir talebin karsilastirma gecmisi
    silinmez, yalnizca degistirilemez.
    """
    if request.status is not PurchaseRequestStatus.quote_wait:
        raise ConflictError(guards.REQUEST_NOT_QUOTE_WAIT)


async def _visible_quote(
    session: AsyncSession, request: PurchaseRequest, quote_id: uuid.UUID
) -> PurchaseQuote:
    """Yol CAPRAZININ tek kapisi: teklif BU talebin altinda degilse **404**.

    Var olmayan teklif ile baska talebin teklifi AYNI govdeyi alir — ayri
    mesajlar teklifin nerede oldugunu ele verirdi (ST §4b kanonu).
    """
    quote = await repository.get_quote_in_request(session, request.id, quote_id)
    if quote is None:
        raise NotFoundError(guards.QUOTE_MISSING)
    return quote


def _assert_shipping_rule(shipping_included: bool, shipping_cost: Decimal | None) -> None:
    """TEK 90'in iki hali. **BIRLESIK degerler uzerinde kosar** (PATCH tuzagi):
    govde yalniz `shipping_cost` tasiyip `shipping_included` DB'de `true`
    kalabilir — yalniz govdeye bakan bir kural ihlali sessizce gecirirdi."""
    if shipping_included and shipping_cost is not None:
        raise ProcurementValidationError(guards.QUOTE_SHIPPING_CONFLICT)


async def _quote_response(session: AsyncSession, quote: PurchaseQuote) -> PurchaseQuoteResponse:
    supplier = await get_supplier(session, quote.supplier_id)
    return PurchaseQuoteResponse(
        **{
            alan: getattr(quote, alan)
            for alan in (
                "id",
                "request_id",
                "supplier_id",
                "unit_price",
                "delivery_time",
                "warranty_note",
                "payment_terms",
                "shipping_included",
                "shipping_cost",
                "is_selected",
                "created_at",
            )
        },
        supplier_name=supplier.name,
    )


async def list_quotes(session: AsyncSession, request: PurchaseRequest) -> PurchaseQuoteListResponse:
    """TEK karsilastirma yaniti: kartlar + TOPLAM MALIYET + "EN IYI FIYAT".

    Iki sorgu kosar ve sayisi TEKLIF SAYISINDAN BAGIMSIZDIR: teklifler+
    tedarikciler (JOIN) ve talebin toplam miktari.

    Rozet TOPLAM maliyetten hesaplanir (`transitions.order_total_from_quote` —
    siparis tutariyla AYNI formul): birim fiyata bakilsaydi nakliyesi haric
    ucuz gorunen teklif yanlislikla one cikardi.
    """
    quantity_total = await repository.request_quantity_total(session, request.id)
    rows = await repository.list_quotes(session, request.id)

    kartlar = [
        PurchaseQuoteCard(
            **_quote_fields(row[0]),
            supplier_name=row.supplier_name,
            total_cost=transitions.order_total_from_quote(
                row[0].unit_price, quantity_total, row[0].shipping_included, row[0].shipping_cost
            ),
            # Gecici deger: en dusuk toplam bilinmeden karar verilemez.
            is_best_price=False,
        )
        for row in rows
    ]
    if kartlar:
        en_dusuk = min(kart.total_cost for kart in kartlar)
        # Beraberlikte HEPSI rozetlenir — birini keyfi secmek yaniltici olurdu.
        kartlar = [
            kart.model_copy(update={"is_best_price": kart.total_cost == en_dusuk})
            for kart in kartlar
        ]

    return PurchaseQuoteListResponse(
        items=kartlar, total=len(kartlar), request_quantity_total=quantity_total
    )


def _quote_fields(quote: PurchaseQuote) -> dict:
    return {
        alan: getattr(quote, alan)
        for alan in (
            "id",
            "request_id",
            "supplier_id",
            "unit_price",
            "delivery_time",
            "warranty_note",
            "payment_terms",
            "shipping_included",
            "shipping_cost",
            "is_selected",
            "created_at",
        )
    }


async def create_quote(
    session: AsyncSession, request: PurchaseRequest, data: PurchaseQuoteCreate
) -> tuple[PurchaseQuoteResponse, str]:
    """Sira: durum (409) → tedarikci referansi (404) → yazma.

    Tedarikci `get_supplier` ile cozulur (**404**, govde ici varlik referansi
    kanonu). Once yazilip FK'ye birakilsaydi kullanici "Veri butunlugu hatasi"
    (409) gorur ve hangi alani duzeltecegini bilemezdi.
    """
    await _assert_quote_wait(request)
    supplier = await get_supplier(session, data.supplier_id)

    quote = PurchaseQuote(
        request_id=request.id,
        supplier_id=supplier.id,
        unit_price=data.unit_price,
        delivery_time=data.delivery_time.strip(),
        warranty_note=_strip(data.warranty_note),
        payment_terms=data.payment_terms,
        shipping_included=data.shipping_included,
        shipping_cost=data.shipping_cost,
    )
    session.add(quote)
    await session.flush()
    return await _quote_response(session, quote), messages.purchase_quote_created(
        request.request_no, supplier.name
    )


async def update_quote(
    session: AsyncSession,
    request: PurchaseRequest,
    quote_id: uuid.UUID,
    data: PurchaseQuoteUpdate,
) -> tuple[PurchaseQuoteResponse, str]:
    """Kismi guncelleme; yalniz `quote_wait`te (409).

    Nakliye kurali BIRLESIK degerlerde kosar (`_assert_shipping_rule`) ve
    YAZIMDAN ONCEDIR: ihlal hicbir alani degistirmeden reddedilir.
    """
    await _assert_quote_wait(request)
    quote = await _visible_quote(session, request, quote_id)
    verilen = data.model_dump(exclude_unset=True)

    shipping_included = verilen.get("shipping_included", quote.shipping_included)
    shipping_cost = verilen.get("shipping_cost", quote.shipping_cost)
    if shipping_included is None:
        # `null` gonderilen bool alan mevcut degeri KORUR (NOT NULL kolon).
        shipping_included = quote.shipping_included
    _assert_shipping_rule(shipping_included, shipping_cost)

    for alan in ("unit_price", "delivery_time", "payment_terms", "shipping_included"):
        if verilen.get(alan) is not None:
            setattr(quote, alan, verilen[alan])
    for alan in ("warranty_note", "shipping_cost"):
        if alan in verilen:
            setattr(quote, alan, verilen[alan])
    if isinstance(quote.delivery_time, str):
        quote.delivery_time = quote.delivery_time.strip()

    await session.flush()
    yanit = await _quote_response(session, quote)
    return yanit, messages.purchase_quote_updated(request.request_no, yanit.supplier_name)


async def delete_quote(session: AsyncSession, request: PurchaseRequest, quote_id: uuid.UUID) -> str:
    """Yalniz `quote_wait`te (409). Denetim metni satir YOK OLMADAN ONCE kurulur."""
    await _assert_quote_wait(request)
    quote = await _visible_quote(session, request, quote_id)
    supplier = await get_supplier(session, quote.supplier_id)
    detail = messages.purchase_quote_deleted(request.request_no, supplier.name)
    await session.delete(quote)
    await session.flush()
    return detail


# --- T3: select-and-order (ATOMIK) ---


async def select_and_order(
    session: AsyncSession, actor: User, request: PurchaseRequest, quote_id: uuid.UUID
) -> tuple[PurchaseOrderResponse, str]:
    """ "Siparis Ver": teklifi sec + siparisi uret + talebi `ordered` yap.

    ## Neden acik SAVEPOINT

    Uc yazma TEK ISLEMDIR ve arada bir hata cikarsa HICBIRI kalmamalidir:
    yarim kalmis bir "secili teklif" ekranda siparissiz gorunur ve o talep bir
    daha duzeltilemezdi (teklif yazimi artik `ordered`da kapali olurdu). Istek
    yasam dongusune GUVENILMEZ — `get_db` yalnizca uc bir ISTISNA hattina
    dusunce geri alir; servis ic bir hatayi yakalayip yanit uretmeye kalksa ya
    da cagiran baska bir baglamda (T4'un ST zinciri, toplu is) kossa atomiklik
    kaybolurdu. `begin_nested` bunu KODUN ozelligi yapar, hattin degil.

    ## Sira

    1. durum (409) ve teklif (404) — yazimdan ONCE,
    2. talebin toplam miktari (tutarin carpani),
    3. savepoint: rakip teklifleri sifirla → teklifi isaretle → talebi gecir,
    4. numara uretimi EN SONDA (`pg_advisory_xact_lock` bosuna tutulmasin) ve
       siparisin yazimi.
    """
    quote = await _visible_quote(session, request, quote_id)
    # Durum kontrolu MATRISTEDIR: `quote_wait` disi her durum 409 verir ve
    # ikinci bir `if` yazilmaz.
    quantity_total = await repository.request_quantity_total(session, request.id)
    total_amount = transitions.order_total_from_quote(
        quote.unit_price, quantity_total, quote.shipping_included, quote.shipping_cost
    )

    async with session.begin_nested():
        await transitions.apply_request_transition(
            session, actor, request, transitions.RequestAction.select_and_order
        )
        await repository.clear_selected_quotes(session, request.id, quote.id)
        quote.is_selected = True
        await session.flush()

        order = PurchaseOrder(
            order_no=await numbering.generate_order_number(session),
            request_id=request.id,
            quote_id=quote.id,
            supplier_id=quote.supplier_id,
            project_id=request.project_id,
            total_amount=total_amount,
            status=PurchaseOrderStatus.approved,
            created_by_user_id=actor.id,
        )
        session.add(order)
        await session.flush()

    return await _order_response(session, order.id), messages.purchase_order_created_from_quote(
        order.order_no, request.request_no
    )


# --- T3: siparis (SIP) ---


async def _order_response(session: AsyncSession, order_id: uuid.UUID) -> PurchaseOrderResponse:
    row = await repository.get_order_row(session, order_id)
    if row is None:  # pragma: no cover - cagiranlar kaydi zaten cozmustur
        raise NotFoundError(guards.ORDER_MISSING)
    return _to_order_response(row)


def _to_order_response(row: Row) -> PurchaseOrderResponse:
    order: PurchaseOrder = row[0]
    return PurchaseOrderResponse(
        **{
            alan: getattr(order, alan)
            for alan in (
                "id",
                "order_no",
                "request_id",
                "quote_id",
                "supplier_id",
                "project_id",
                "total_amount",
                "expected_delivery",
                "status",
                "note",
                "created_by_user_id",
                "created_at",
            )
        },
        supplier_name=row.supplier_name,
        request_no=row.request_no,
    )


async def visible_order(session: AsyncSession, actor: User, order_id: uuid.UUID) -> PurchaseOrder:
    """Siparise tekil erisimin TEK kapisi. Gorunmeyen proje → **404**."""
    order = await repository.get_order(session, order_id)
    if order is None or order.project_id not in await _visible_project_ids(session, actor):
        raise NotFoundError(guards.ORDER_MISSING)
    return order


async def get_order_detail(
    session: AsyncSession, actor: User, order_id: uuid.UUID
) -> PurchaseOrderResponse:
    order = await visible_order(session, actor, order_id)
    return await _order_response(session, order.id)


async def list_orders(
    session: AsyncSession,
    actor: User,
    *,
    status: PurchaseOrderStatus | None,
    project_id: uuid.UUID | None,
    supplier_id: uuid.UUID | None,
    q: str | None,
    limit: int,
    offset: int,
) -> PurchaseOrderListResponse:
    """SIP tablosunun veri kaynagi — suzgecler AND'lidir.

    Uc sorgu kosar ve sayisi SATIR SAYISINDAN BAGIMSIZDIR (N+1 yok): gorunur
    projeler · sayfa (tedarikci adi ve talep numarasi JOIN'li) · sayim.
    """
    project_ids = await _visible_project_ids(session, actor)
    suzgec = {"status": status, "project_id": project_id, "supplier_id": supplier_id, "q": q}
    rows = await repository.list_orders(session, project_ids, limit=limit, offset=offset, **suzgec)
    total = await repository.count_orders(session, project_ids, **suzgec)
    return PurchaseOrderListResponse(
        items=[_to_order_response(row) for row in rows], total=total, limit=limit, offset=offset
    )


async def create_order(
    session: AsyncSession, actor: User, data: PurchaseOrderCreate
) -> tuple[PurchaseOrderResponse, str]:
    """DOGRUDAN (talepsiz) siparis — §7 S3, SIP 35.

    `request_id` semada YOKTUR (govdede gonderilse Pydantic yok sayar): talebe
    bagli siparisin tek yolu `select-and-order`dir, aksi halde talebin durum
    makinesi atlanirdi.

    Sira: proje kapsami (404) → tedarikci (404) → numara → yazma. Numara EN
    SONDA uretilir (T2 kurali: danisma kilidi bosuna tutulmasin).
    """
    if data.project_id not in await _visible_project_ids(session, actor):
        raise NotFoundError(guards.REQUEST_PROJECT_INVALID)
    supplier = await get_supplier(session, data.supplier_id)

    order = PurchaseOrder(
        order_no=await numbering.generate_order_number(session),
        request_id=None,
        quote_id=None,
        supplier_id=supplier.id,
        project_id=data.project_id,
        total_amount=data.total_amount,
        expected_delivery=data.expected_delivery,
        status=PurchaseOrderStatus.approved,
        note=data.note,
        created_by_user_id=actor.id,
    )
    session.add(order)
    await session.flush()
    return await _order_response(session, order.id), messages.purchase_order_created(
        order.order_no, supplier.name
    )


async def update_order(
    session: AsyncSession, order: PurchaseOrder, data: PurchaseOrderUpdate
) -> tuple[PurchaseOrderResponse, str]:
    """Durum gecisi + duzeltilebilir alanlar.

    `status` GONDERILMEZSE gecis denetimi hic kosmaz: not/tarih duzeltmesi bir
    gecis DEGILDIR. Gonderildiyse matris karar verir (`transitions.
    assert_order_transition`) — `delivered` DAHIL her matris disi hedef 409'dur
    (teslim damgasini stok girisi atar, §7 S4).
    """
    verilen = data.model_dump(exclude_unset=True)
    hedef = verilen.get("status")
    if hedef is not None:
        transitions.assert_order_transition(order, hedef)
        order.status = hedef

    for alan in ("expected_delivery", "note"):
        if alan in verilen:
            setattr(order, alan, verilen[alan])

    await session.flush()
    return await _order_response(session, order.id), messages.purchase_order_updated(order.order_no)
