"""Toplu yollar: toplu uretim, uretim ONIZLEMESI, Excel ice aktarma, paylasim
(spec §5.4, §7.7, §7.8, §7.10).

Tekil CRUD'dan (`service.py`) AYRI dosyada tutulur: yazan ucunun ortak sinifi
ATOMIKLIK'tir ("hep-ya-hic, kismi yazma OLMAZ") ve hepsi tek istekte yuzlerce
satira dokunur. Kurallar `guards.py`'den CAGRILIR, kopyalanmaz.

`preview_bulk_units` bu dosyadaki TEK OKUMA yoludur ve bilerek buradadir:
onizleme ile gercek uretimin AYNI saf fonksiyondan (`bulk.generate_units`)
beslendigi ancak yan yana dururken gorunur kalir.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    DuplicateError,
    NotFoundError,
    ProjectTypeMismatchError,
    UnitImportError,
    UnitValidationError,
)
from app.modules.audit import messages
from app.modules.projects.models import Project, ProjectType
from app.modules.units import bulk, codes, guards, repository, service
from app.modules.units.bulk import generate_unit_numbers
from app.modules.units.importer import (
    IMPORT_ROW_ERRORS,
    MAX_REPORTED_ERRORS,
    ImportFileError,
    ImportRow,
    RowError,
    normalize_header,
    parse_units_file,
)
from app.modules.units.models import Block, Unit
from app.modules.units.schemas import (
    UnitAllocationRequest,
    UnitBulkCreate,
    UnitBulkPreview,
    UnitBulkPreviewRow,
    UnitImportResult,
    UnitImportRowError,
    UnitListResponse,
)
from app.modules.users.models import User

# Toplu uretim cakismasinda hata mesajinda listelenecek numara adedi (spec §7.7).
# 500 numarayi tek satira dizmek mesaji okunamaz kilar; ilk 20 kullaniciya
# hangi araligi duzeltecegini gostermeye yeter.
_MAX_CONFLICT_NUMBERS = 20


# --- Toplu uretim (spec §6.3, §7.7) — ATOMIKLIK SINIFI ---


async def bulk_create_units(
    session: AsyncSession, actor: User, project_id: uuid.UUID, data: UnitBulkCreate
) -> tuple[UnitListResponse, str]:
    """Spec §7.7. HEP-YA-HIC: kismi yazma OLMAZ.

    Sira KATIDIR ve degistirilemez — her dogrulama ilk `session.add`'DEN ONCE
    biter, boylece reddedilen istek tek satir bile yazmaz:

    1. proje gorunurlugu (404) ve blogun bu projeye ait olmasi (404, IDOR-9)
    2. ortak varsayilanlarin alan kurallari (`net > brut` → 422); tekil POST ile
       AYNI kural, cunku ayni sutunlara yaziyoruz
    3. uretilecek numaralarin tamami (saf fonksiyon, DB'ye dokunmaz)
    4. blokta mevcut numaralarla kesisim — TEK `SELECT` (`existing_unit_nos`);
       kesisim bossa DEGILSE hicbir `INSERT` yapilmadan 409

    Ardindan tum satirlar tek `add_all` + tek `flush` ile yazilir. `get_db`
    istek basina tek transaction acar; bir istisna cikarsa rollback eder —
    dolayisiyla 4. adimdan sonra olusabilecek bir yaris durumu (ayni anda ayni
    numarayi yazan ikinci istek) `uq_units_block_no` ihlaline duser ve
    `IntegrityError → 409` handler'i TUM parti geri alinmis hâlde yanit verir.

    `owner_side` UYGULANMAZ: `UnitBulkCreate` semasinda boyle bir alan YOKTUR
    (spec §6.3) — uretilen tum uniteler pay atanmamis baslar (§5.3), bu da §3.3
    korkulugunu her proje tipinde yapisal olarak saglar.
    """
    project = await guards.visible_project(session, actor, project_id)
    block = await guards.block_in_project(session, project, data.block_id)
    guards.ensure_net_le_gross(data.gross_area_m2, data.net_area_m2)

    # `{Blok}` jetonu blok KODUDUR (karar 4). Kodu NULL olan canli blokta
    # `effective_block_code` ile ANLIK turetilir ve SAKLANMAZ (karar 8, §0.B):
    # ikinci bir otorite dogmaz, cunku cagrilan fonksiyon kod uretiminin ta
    # kendisidir. Blok bir kez duzenlenip kodu kalicilastiginda cikti aynidir.
    numbers = generate_unit_numbers(data, codes.effective_block_code(block.code, block.name))
    taken = await repository.existing_unit_nos(session, block.id, numbers)
    if taken:
        # Uretim sirasi KORUNUR (kume sirasi degil): kullanici hangi araligin
        # cakistigini ancak sirali listede gorebilir.
        conflicting = [number for number in numbers if number in taken]
        listed = ", ".join(conflicting[:_MAX_CONFLICT_NUMBERS])
        raise DuplicateError(f"{guards.BULK_NUMBERS_TAKEN}: {listed}")

    next_sort_order = await repository.max_sort_order(session, block.id) + 1
    session.add_all(
        [
            Unit(
                project_id=project.id,
                block_id=block.id,
                unit_no=number,
                unit_kind=data.unit_kind,
                layout=data.layout,
                gross_area_m2=data.gross_area_m2,
                net_area_m2=data.net_area_m2,
                list_price=data.list_price,
                appraisal_value=data.appraisal_value,
                sort_order=next_sort_order + offset,
            )
            for offset, number in enumerate(numbers)
        ]
    )
    await session.flush()
    # Spec §9: ISTEK BASINA TEK denetim satiri — 24 unite icin 24 satir degil.
    detail = messages.units_bulk_created(project.name, block.name, len(numbers))
    return await service.list_units(session, actor, project_id), detail


async def preview_bulk_units(
    session: AsyncSession, actor: User, project_id: uuid.UUID, data: UnitBulkCreate
) -> UnitBulkPreview:
    """Spec §5.4. **HICBIR SEY YAZMAZ** — bu fonksiyonun tek sozlesmesi budur.

    Burada `session.add`, `flush`, `commit` ya da herhangi bir `UPDATE` YOKTUR
    ve olmamalidir; tek DB erisimi cakisma sorgusudur (`existing_unit_nos`, saf
    `SELECT`). Denetim satiri da yazilmaz: onizleme bir OKUMA ucudur (spec §9,
    P4 T7 kurali) ve router bu fonksiyondan denetim METNI almaz — imzasinin
    `bulk_create_units`'ten farkli olmasi (tek deger, `tuple` degil) bu ayrimi
    YAPISAL kilar, unutulabilir bir konvansiyona birakmaz.

    Uretim mantigi TEK KOPYADIR: `bulk.generate_units` saf fonksiyonu hem burada
    hem `bulk_create_units`'te cagrilir. `POST …/units/bulk` onizlemeden gelen
    satirlari KABUL ETMEZ, ayni girdiden yeniden uretir — aksi hâlde istemci
    govdesi fiyat uydurabilirdi (TU 182 "Onizlemeyi Yenile").

    Cakisma HATA DEGILDIR (spec §5.6, TU 177): satirlar `conflict=True` ile
    doner ve kullanici `start_number`'i degistirip yeniden onizler. Blokaj
    yalniz kaydetmededir (409).
    """
    project = await guards.visible_project(session, actor, project_id)
    block = await guards.block_in_project(session, project, data.block_id)
    guards.ensure_net_le_gross(data.gross_area_m2, data.net_area_m2)

    generated = bulk.generate_units(data, codes.effective_block_code(block.code, block.name))
    numbers = [unit.unit_no for unit in generated]
    taken = await repository.existing_unit_nos(session, block.id, numbers)
    return UnitBulkPreview(
        total_units=len(generated),
        total_list_value=bulk.total_list_value(generated),
        # Uretim sirasi KORUNUR (kume sirasi degil): kullanici hangi araligin
        # cakistigini ancak sirali listede gorebilir (409 mesajiyla ayni gerekce).
        conflicting_unit_nos=[number for number in numbers if number in taken],
        rows=[
            UnitBulkPreviewRow(
                unit_no=unit.unit_no,
                floor=unit.floor,
                floor_label=unit.floor_label,
                layout=unit.layout,
                gross_area_m2=unit.gross_area_m2,
                net_area_m2=unit.net_area_m2,
                facing=unit.facing,
                list_price=unit.list_price,
                conflict=unit.unit_no in taken,
            )
            for unit in generated
        ],
    )


# --- Excel ice aktarma (spec §6.4, §7.8) — HEP-YA-HIC + SATIR BAZLI RAPOR ---


def _row_error(error: RowError) -> UnitImportRowError:
    return UnitImportRowError(row=error.row, column=error.column, message=error.message)


def _raise_row_errors(errors: list[RowError]) -> None:
    """Spec §7.8: HICBIR satir yazilmaz, ama kullanici tum hatalari TEK seferde gorur.

    "Ilk hatada dur" 48 satirlik bir dosyayi 48 kez yuklemeye zorlardi; yarim
    yazma ise dosyayi duzeltip yeniden yuklemeyi imkânsiz kilardi (basarili
    satirlar artik cakisir). Ikisi birlikte uygulanir.
    """
    if not errors:
        return
    ordered = sorted(errors, key=lambda error: error.row)
    remaining = len(ordered) - MAX_REPORTED_ERRORS
    raise UnitImportError(
        IMPORT_ROW_ERRORS.format(count=len({error.row for error in ordered})),
        [_row_error(error).model_dump() for error in ordered[:MAX_REPORTED_ERRORS]],
        f"Ve {remaining} hata daha" if remaining > 0 else None,
    )


def _domain_row_errors(
    project: Project, rows: list[ImportRow], taken: dict[str, set[str]]
) -> list[RowError]:
    """Tekil `POST` ile AYNI alan kurallari, satir satir uygulanir.

    Bu kurallar bilerek `importer.py`'de DEGIL: `net > brut` ve `owner_side`
    korkulugu tek yazma yolunun kurallaridir (`guards.ensure_net_le_gross`,
    `guards.ensure_owner_side_allowed`) ve ice aktarma onlari KOPYALAMAZ, CAGIRIR.
    """
    errors: list[RowError] = []
    for row in rows:
        try:
            guards.ensure_net_le_gross(row.gross_area_m2, row.net_area_m2)
        except UnitValidationError as exc:
            errors.append(RowError(row.row, "Net m²", str(exc)))
        try:
            guards.ensure_owner_side_allowed(project, row.owner_side)
        except ProjectTypeMismatchError as exc:
            errors.append(RowError(row.row, "Pay", str(exc)))
        if row.unit_no in taken.get(normalize_header(row.block_name), set()):
            errors.append(RowError(row.row, "Ünite No", guards.DUPLICATE_UNIT))
    return errors


async def import_units(
    session: AsyncSession, actor: User, project_id: uuid.UUID, content: bytes
) -> tuple[UnitImportResult, str]:
    """Spec §7.8. Dosya BELLEKTE islenir ve ATILIR — diske/S3'e/DB'ye yazilmaz.

    Sira KATIDIR (bulk ile ayni gerekce): her dogrulama ilk `session.add`'DEN
    ONCE biter, boylece reddedilen bir dosya tek satir bile — tek BLOK bile —
    yazmaz:

    1. proje gorunurlugu (404)
    2. dosya duzeyi kontroller (tip/boyut/satir sayisi/eksik baslik) → 422
    3. satir cozumleme hatalari (saf, DB'siz)
    4. alan kurallari + blokta mevcut `unit_no` (tek `SELECT`'ten gelen kume)
    5. yeni blok adlari icin §4.5 santiye kurali
    6. bloklar ve uniteler tek `add_all` + tek `flush`

    Blok adi NORMALLESTIRILEREK eslesir (`normalize_header`): dosyada "a blok"
    yazan kullanici mevcut "A Blok"a yazar. Aksi hâlde `uq_blocks_project_name`
    ihlaline dusup anlamsiz bir 409 alirdi.
    """
    project = await guards.visible_project(session, actor, project_id)
    try:
        rows, parse_errors = parse_units_file(content)
    except ImportFileError as exc:
        # Dosyanin TAMAMINI reddeden hata: satir listesi yok, tek Turkce mesaj.
        raise UnitValidationError(str(exc)) from exc
    _raise_row_errors(parse_errors)

    blocks = {
        normalize_header(block.name): block
        for block, _ in await repository.list_blocks_for_project(session, project.id)
    }
    units = await repository.list_units_for_project(session, project.id)
    by_block_id = {block.id: key for key, block in blocks.items()}
    taken: dict[str, set[str]] = {key: set() for key in blocks}
    for unit in units:
        taken[by_block_id[unit.block_id]].add(unit.unit_no)

    _raise_row_errors(_domain_row_errors(project, rows, taken))

    new_names = [row.block_name for row in rows if normalize_header(row.block_name) not in blocks]
    created_blocks: list[Block] = []
    if new_names:
        # Santiye TEK KEZ cozulur: dosyada santiye sutunu yoktur, dolayisiyla tum
        # yeni bloklar ayni §4.5 kuralina tabidir (cok santiyeli projede 422).
        site = await guards.resolve_site(session, project.id, None)
        for name in new_names:
            key = normalize_header(name)
            if key in blocks:
                continue
            block = Block(project_id=project.id, site_id=site.id, name=name)
            session.add(block)
            blocks[key] = block
            created_blocks.append(block)
        await session.flush()

    # Yeni satirlar blok icinde MEVCUTLARIN ARDINA eklenir (bulk ile ayni gerekce):
    # sifirdan baslasaydi yari dolu bir blokta eski ve yeni uniteler ic ice
    # gecerdi — `unit_no` metin oldugu icin ikincil sira "10 < 2" verir.
    next_sort: dict[str, int] = {}
    for unit in units:
        key = by_block_id[unit.block_id]
        next_sort[key] = max(next_sort.get(key, 0), int(unit.sort_order) + 1)

    new_units: list[Unit] = []
    for row in rows:
        key = normalize_header(row.block_name)
        offset = next_sort.get(key, 0)
        next_sort[key] = offset + 1
        new_units.append(
            Unit(
                project_id=project.id,
                block_id=blocks[key].id,
                unit_no=row.unit_no,
                unit_kind=row.unit_kind,
                layout=row.layout,
                gross_area_m2=row.gross_area_m2,
                net_area_m2=row.net_area_m2,
                list_price=row.list_price,
                appraisal_value=row.appraisal_value,
                owner_side=row.owner_side,
                sort_order=offset,
            )
        )
    session.add_all(new_units)
    await session.flush()
    result = UnitImportResult(created=len(rows), blocks_created=len(created_blocks), errors=[])
    # Spec §9: dosyada kac satir olursa olsun TEK denetim satiri.
    return result, messages.units_imported(project.name, result.created)


# --- Paylasim (spec §7.10, §5.3) — ATOMIKLIK + IDOR SINIFI ---


async def update_allocation(
    session: AsyncSession, actor: User, project_id: uuid.UUID, data: UnitAllocationRequest
) -> tuple[UnitListResponse, str]:
    """Spec §7.10 (KKP 25 "Paylasimi Kaydet"). HEP-YA-HIC, tek transaction.

    Paylar TOPLU URETIMDE ATANMAZ (§6.3'te `owner_side` alani yoktur): paylasim
    noterden SONRA belli olur (KKP 78), bu yuzden ayri bir uc olarak girilir.

    Sira KATIDIR ve degistirilemez — her dogrulama ilk yazmadan ONCE biter:

    1. proje gorunurlugu (404, IDOR-1); gorunmeyen proje var olmayanla AYNI mesaj
    2. proje tipi `kat_karsiligi` degilse hic islem yapilmadan 422 (§3.3)
    3. listede tekrarlanan `unit_id` → 422; "son kazanir" SESSIZ kabul EDILMEZ,
       ekranda iki satira dokunan kullanici hangisinin gecerli oldugunu goremezdi
    4. tum uniteler TEK `SELECT` ile cekilir; eksik VEYA baska projeye ait tek
       satir bile varsa 404 (IDOR-8) ve HICBIRI yazilmaz

    4. adimda "bulunamadi" ile "baska projenin" AYNI mesaji doner: aksi hâlde
    elinde UUID olan kullanici kaydin var oldugunu ve baskasina ait oldugunu
    ayirt edebilirdi (`guards.visible_unit` ile ayni gerekce).
    """
    project = await guards.visible_project(session, actor, project_id)
    if project.project_type is not ProjectType.kat_karsiligi:
        raise ProjectTypeMismatchError(guards.ALLOCATION_WRONG_TYPE)

    wanted = {item.unit_id: item.owner_side for item in data.items}
    if len(wanted) != len(data.items):
        raise UnitValidationError(guards.DUPLICATE_IN_PAYLOAD)

    units = await repository.get_units_by_ids(session, list(wanted))
    if len(units) != len(wanted) or any(unit.project_id != project.id for unit in units):
        raise NotFoundError(guards.UNIT_MISSING)

    for unit in units:
        unit.owner_side = wanted[unit.id]
    await session.flush()
    # Spec §9: 42 unitelik bir kayit 42 satir yazsaydi gunlugu bogardi — TEK satir.
    detail = messages.unit_allocation_updated(project.name, len(units))
    return await service.list_units(session, actor, project_id), detail
