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
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    DuplicateError,
    NotFoundError,
    ProjectTypeMismatchError,
    UnitValidationError,
)
from app.modules.audit import messages
from app.modules.projects.models import Project, ProjectType
from app.modules.units import bulk, codes, guards, repository, service
from app.modules.units.importer import (
    ImportFileError,
    ImportRow,
    ParsedRow,
    normalize_header,
    parse_units_file,
)
from app.modules.units.models import Block, Unit, UnitOwnerSide
from app.modules.units.schemas import (
    UnitAllocationRequest,
    UnitBulkCreate,
    UnitBulkPreview,
    UnitBulkPreviewRow,
    UnitImportResult,
    UnitImportRowReport,
    UnitImportRowStatus,
    UnitImportSummary,
    UnitImportValidation,
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

    T10: satirlar `preview` ile AYNI saf fonksiyondan (`bulk.generate_units`)
    gelir — yalniz numaralar degil, slot alanlari ve kat artisi uygulanmis
    fiyatlar da. Burada ikinci bir uretim dali acilsaydi kullanici onizlemede
    gordugunden BASKA bir sey kaydeder ve bunu fark edemezdi (spec §12.4/34).
    """
    project = await guards.visible_project(session, actor, project_id)
    block = await guards.block_in_project(session, project, data.block_id)
    guards.ensure_net_le_gross(data.gross_area_m2, data.net_area_m2)

    # `{Blok}` jetonu blok KODUDUR (karar 4). Kodu NULL olan canli blokta
    # `effective_block_code` ile ANLIK turetilir ve SAKLANMAZ (karar 8, §0.B):
    # ikinci bir otorite dogmaz, cunku cagrilan fonksiyon kod uretiminin ta
    # kendisidir. Blok bir kez duzenlenip kodu kalicilastiginda cikti aynidir.
    generated = bulk.generate_units(data, codes.effective_block_code(block.code, block.name))
    numbers = [unit.unit_no for unit in generated]
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
                unit_no=unit.unit_no,
                unit_kind=data.unit_kind,
                layout=unit.layout,
                gross_area_m2=unit.gross_area_m2,
                net_area_m2=unit.net_area_m2,
                list_price=unit.list_price,
                # `appraisal_value` SLOTTA YOKTUR (TU tablosunda bu sutun hic
                # gecmiyor, spec §5.5) — ortak varsayilandan gelir.
                appraisal_value=data.appraisal_value,
                # Sutuna kat ETIKETI yazilir (METIN, karar 4); onizlemedeki
                # sayisal `floor` yalniz numaralandirmanin girdisidir ve
                # HICBIR sutuna yazilmaz.
                floor=unit.floor_label,
                facing=unit.facing,
                sort_order=next_sort_order + offset,
            )
            for offset, unit in enumerate(generated)
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


# --- Excel ice aktarma (spec §6.1-§6.5) — KISMI AKTARIM ---
#
# P3'un HEP-YA-HIC karari BILEREK TERSINE CEVRILDI (kullanici karari, spec §6.1):
# EI 38/202 "22 Gecerli Satiri Aktar" ve EI 101 "veya sadece gecerli satirlari
# aktarin" hep-ya-hicle uzlasmiyordu.
#
# ISLEM SINIRI — bu dosyanin en pahali hata sinifi:
#   * Gecerli satirlar KALICI yazilir; hatali satirlar HIC `session`'a girmez
#     (`ParsedRow.data is None` ⇔ satir hatali, tip duzeyinde imkânsizlik).
#   * HIC gecerli satir yoksa `_IMPORT_NOTHING_TO_WRITE` 422'si ILK `session.add`
#     ONCESINDE atilir; ustelik istisna istek transaction'ini geri alir, yani
#     "hicbir sey yazilmadi" garantisi IKI KATLIDIR.
#   * `created + skipped == summary.total_rows` her zaman saglanir — bu esitlik
#     "sessizce kaybolan satir" sinifinin tek gozlemlenebilir korkulugudur.


@dataclass(frozen=True)
class _RowPlan:
    """Bir Excel satirinin RAPORU + yazilacak verisi.

    Rapor ile veri AYNI nesnede durur: iki ayri listede tasinsalardi "raporda
    hatali gorunen satir yazilmis" durumu iki listenin sirasi kaydiginda sessizce
    dogardi.
    """

    report: UnitImportRowReport
    data: ImportRow | None  # yalniz YAZILACAK satirlarda dolu


def _domain_messages(project: Project, row: ImportRow, taken: dict[str, set[str]]) -> list[str]:
    """Tekil `POST` ile AYNI alan kurallari, satir satir uygulanir.

    Bu kurallar bilerek `importer.py`'de DEGIL: `net > brut` ve `owner_side`
    korkulugu tek yazma yolunun kurallaridir (`guards.ensure_net_le_gross`,
    `guards.ensure_owner_side_allowed`) ve ice aktarma onlari KOPYALAMAZ, CAGIRIR.

    Blokta zaten var olan `unit_no` artik dosyayi REDDETMEZ (spec §6.1/2):
    satir atlanir ve raporlanir — "duzelt ve yeniden yukle" dongusu boylece tek
    adimda tekrarlanabilir kalir.
    """
    messages: list[str] = []
    try:
        guards.ensure_net_le_gross(row.gross_area_m2, row.net_area_m2)
    except UnitValidationError as exc:
        messages.append(str(exc))
    try:
        guards.ensure_owner_side_allowed(project, row.owner_side)
    except ProjectTypeMismatchError as exc:
        messages.append(str(exc))
    if row.unit_no in taken.get(normalize_header(row.block_name), set()):
        messages.append(guards.DUPLICATE_UNIT)
    return messages


def _row_plan(
    parsed: ParsedRow, messages: list[str], *, importable: bool, imported: bool
) -> _RowPlan:
    if messages:
        status = UnitImportRowStatus.error
    elif parsed.warnings:
        status = UnitImportRowStatus.warning
        messages = [warning.message for warning in parsed.warnings]
    else:
        status = UnitImportRowStatus.ok
    return _RowPlan(
        report=UnitImportRowReport(
            row=parsed.row,
            status=status,
            unit_no=parsed.echo.unit_no,
            block_name=parsed.echo.block_name,
            floor=parsed.echo.floor,
            layout=parsed.echo.layout,
            gross_area_m2=parsed.echo.gross_area_m2,
            list_price=parsed.echo.list_price,
            messages=messages,
            imported=imported,
        ),
        data=parsed.data if importable else None,
    )


def _summary(plans: list[_RowPlan]) -> UnitImportSummary:
    """EI 94-99. `valid + warning + error == total_rows` YAPISAL olarak saglanir:
    her satirin durumu TEKTIR ve sayaclar tek gecisten uretilir."""
    statuses = [plan.report.status for plan in plans]
    return UnitImportSummary(
        total_rows=len(statuses),
        valid=statuses.count(UnitImportRowStatus.ok),
        warning=statuses.count(UnitImportRowStatus.warning),
        error=statuses.count(UnitImportRowStatus.error),
    )


async def _plan_rows(
    session: AsyncSession,
    actor: User,
    project_id: uuid.UUID,
    content: bytes,
    *,
    include_warnings: bool,
    dry_run: bool,
) -> tuple[Project, dict[str, Block], list[Unit], list[_RowPlan]]:
    """`import` ve `import/validate` ucunun ORTAK cekirdegi (spec §6.2).

    Iki uc de BU fonksiyondan beslenir; kural KOPYALANMAZ. Ayrisan iki kopya,
    "dogrulamada gecerli gorunup aktarimda atlanan satir" sinifini dogururdu ve
    kullanici bunu ancak eksik unitelerden fark ederdi.

    `dry_run` yalniz `imported` bayragini belirler — dogrulama ucu hicbir sey
    yazmadigi icin o bayrak DAIMA `False` olmalidir (spec §6.3).
    """
    project = await guards.visible_project(session, actor, project_id)
    try:
        parsed_rows = parse_units_file(content)
    except ImportFileError as exc:
        # Dosyanin TAMAMINI reddeden hata: satir listesi yok, tek Turkce mesaj.
        raise UnitValidationError(str(exc)) from exc

    blocks = {
        normalize_header(block.name): block
        for block, _ in await repository.list_blocks_for_project(session, project.id)
    }
    units = await repository.list_units_for_project(session, project.id)
    by_block_id = {block.id: key for key, block in blocks.items()}
    taken: dict[str, set[str]] = {key: set() for key in blocks}
    for unit in units:
        taken[by_block_id[unit.block_id]].add(unit.unit_no)

    plans: list[_RowPlan] = []
    for parsed in parsed_rows:
        messages = [error.message for error in parsed.errors]
        if parsed.data is not None:
            messages += _domain_messages(project, parsed.data, taken)
        # Uyarili satir kullanici isterse yazilir (EI 192); hatali satir ASLA.
        importable = not messages and (include_warnings or not parsed.warnings)
        plans.append(
            _row_plan(parsed, messages, importable=importable, imported=importable and not dry_run)
        )
    return project, blocks, units, plans


def _blocks_to_create(blocks: dict[str, Block], plans: list[_RowPlan]) -> list[str]:
    """Blok olusturma YALNIZ yazilacak satirlara baglidir (spec §12.5/47).

    Hatali satirin blogu acilsaydi kullanici hicbir unitesi olmayan hayalet bir
    blokla kalir ve bunu ancak blok listesinde fark ederdi.
    """
    names: list[str] = []
    seen = set(blocks)
    for plan in plans:
        if plan.data is None:
            continue
        key = normalize_header(plan.data.block_name)
        if key not in seen:
            seen.add(key)
            names.append(plan.data.block_name)
    return names


async def validate_import(
    session: AsyncSession,
    actor: User,
    project_id: uuid.UUID,
    content: bytes,
    *,
    site_id: uuid.UUID | None = None,
    include_warnings: bool = True,
) -> UnitImportValidation:
    """Spec §6.2 (EI 92-197). **HICBIR SEY YAZMAZ** — tek sozlesmesi budur.

    `bulk/preview` ile AYNI gerekcelerle ayri uctur (spec §5.4): yanit sekli
    farklidir (`UnitImportValidation` != `UnitImportResult`), denetim gunlugune
    YAZMAZ ve iki uc de ayni saf cekirdekten (`_plan_rows`) beslenir.

    `site_id` burada da dogrulanir: kullanici aktarimdan ONCE, dogrulama
    adiminda ogrenmelidir ki hedef santiyesi gecersiz.
    """
    _, blocks, _, plans = await _plan_rows(
        session, actor, project_id, content, include_warnings=include_warnings, dry_run=True
    )
    names = _blocks_to_create(blocks, plans)
    if names or site_id is not None:
        await guards.resolve_site(session, project_id, site_id)
    return UnitImportValidation(
        summary=_summary(plans),
        rows=[plan.report for plan in plans],
        blocks_to_create=names,
    )


async def import_units(
    session: AsyncSession,
    actor: User,
    project_id: uuid.UUID,
    content: bytes,
    *,
    site_id: uuid.UUID | None = None,
    include_warnings: bool = True,
) -> tuple[UnitImportResult, str]:
    """Spec §6.1-§6.5. Dosya BELLEKTE islenir ve ATILIR — diske/S3'e/DB'ye yazilmaz.

    Sira KATIDIR ve degistirilemez; her karar ilk `session.add`'DEN ONCE biter:

    1. proje gorunurlugu (404)
    2. dosya duzeyi kontroller (tip/boyut/satir sayisi/eksik baslik) → 422
    3. satir raporu: cozumleme hatalari + alan kurallari + blokta mevcut `unit_no`
    4. YAZILACAK satir yoksa 422 — buraya kadar hicbir sey yazilmadi
    5. yeni blok adlari icin §4.5 santiye kurali (`site_id`, karar 3)
    6. bloklar ve uniteler tek `add_all` + tek `flush`

    `site_id` YALNIZ yeni blok acarken kullanilir: dosyadaki blok projede zaten
    varsa o blok aynen kullanilir ve santiyesi DEGISTIRILMEZ — blok tasimak bu
    ucun isi degildir ve kullanici uniteye ekleme yaparken bloğunu tasidigini
    fark edemezdi (SESSIZ VERI TASIMA riski, spec §6.2).

    Blok adi NORMALLESTIRILEREK eslesir (`normalize_header`): dosyada "a blok"
    yazan kullanici mevcut "A Blok"a yazar. Aksi hâlde `uq_blocks_project_name`
    ihlaline dusup anlamsiz bir 409 alirdi.
    """
    project, blocks, units, plans = await _plan_rows(
        session, actor, project_id, content, include_warnings=include_warnings, dry_run=False
    )
    writable = [plan.data for plan in plans if plan.data is not None]
    if not writable:
        # `created=0` ile 200 donmek kullanicinin "aktarildi" sanmasina yol acardi.
        raise UnitValidationError(guards.IMPORT_NOTHING_TO_WRITE)

    created_blocks: list[Block] = []
    new_names = _blocks_to_create(blocks, plans)
    if new_names or site_id is not None:
        # Santiye TEK KEZ cozulur: dosyada santiye sutunu yoktur, dolayisiyla tum
        # yeni bloklar ayni §4.5 kuralina tabidir. `site_id` verilmisse yeni blok
        # gerekmese bile DOGRULANIR — gecersiz kimlik sessizce yutulmaz.
        site = await guards.resolve_site(session, project.id, site_id)
        for name in new_names:
            block = Block(project_id=project.id, site_id=site.id, name=name)
            session.add(block)
            blocks[normalize_header(name)] = block
            created_blocks.append(block)
        await session.flush()

    # Yeni satirlar blok icinde MEVCUTLARIN ARDINA eklenir (bulk ile ayni gerekce):
    # sifirdan baslasaydi yari dolu bir blokta eski ve yeni uniteler ic ice
    # gecerdi — `unit_no` metin oldugu icin ikincil sira "10 < 2" verir.
    next_sort: dict[str, int] = {}
    by_block_id = {block.id: key for key, block in blocks.items()}
    for unit in units:
        key = by_block_id[unit.block_id]
        next_sort[key] = max(next_sort.get(key, 0), int(unit.sort_order) + 1)

    new_units: list[Unit] = []
    for row in writable:
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
                # P3.1 T11: `Kat` METIN olarak AYNEN yazilir (karar 4), `Cephe`
                # bes degerli sozlukten gelir. `Maliyet` YAZILMAZ (karar 10).
                floor=row.floor,
                facing=row.facing,
                sort_order=offset,
            )
        )
    session.add_all(new_units)
    await session.flush()
    summary = _summary(plans)
    result = UnitImportResult(
        summary=summary,
        created=len(new_units),
        skipped=summary.total_rows - len(new_units),
        blocks_created=len(created_blocks),
        rows=[plan.report for plan in plans],
    )
    # Spec §9: dosyada kac satir olursa olsun TEK denetim satiri; mesaj ATLANAN
    # satir sayisini da tasir, yoksa gunluk "kac unite geldi" sorusuna yaniltici
    # cevap verirdi (spec §6.1).
    detail = messages.units_imported(project.name, result.created, result.skipped)
    return result, detail


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

    P9 spec §4.2 — HISSEDAR (`shareholder_id`), iki ek dogrulama olarak ayni
    siraya girer ve ikisi de YAZMADAN ONCE biter:

    5. `owner_side` `contractor`/`None` iken hissedar gonderilmisse 422
       (PG 221: select yalniz ARSA satirinda; PG 190: BIZ satiri "Yuklenici
       payi" basar). `landowner + shareholder_id=None` GECERLIDIR — atama
       zorunlu degildir (KKP 119 "—").
    6. Hissedar bu projeye ait degilse (veya hic yoksa) 404, unitedekiyle AYNI
       gorunmezlik gerekcesiyle; hicbir satir yazilmaz.

    TARAF DEGISINCE HISSEDAR BIRLIKTE GIDER: `owner_side` `landowner`dan
    cikinca (`contractor` ya da `None`) o unitenin `shareholder_id`si AYNI
    istekte temizlenir. Ayri bir istek beklenmez — uc atomiktir ve "yuklenici
    payinda hissedar" gibi yarim bir durum birakamaz. Ayni gerekceyle
    `shareholder_id` alani GONDERILMEZSE `None` sayilir (sema varsayilani):
    uc DEGISTIRME sozlesmesini korur, kismi guncellemeye yumusamaz.
    """
    project = await guards.visible_project(session, actor, project_id)
    if project.project_type is not ProjectType.kat_karsiligi:
        raise ProjectTypeMismatchError(guards.ALLOCATION_WRONG_TYPE)

    wanted = {item.unit_id: item for item in data.items}
    if len(wanted) != len(data.items):
        raise UnitValidationError(guards.DUPLICATE_IN_PAYLOAD)

    if any(
        item.shareholder_id is not None and item.owner_side is not UnitOwnerSide.landowner
        for item in data.items
    ):
        raise UnitValidationError(guards.SHAREHOLDER_WRONG_SIDE)

    requested_shareholders = {
        item.shareholder_id for item in data.items if item.shareholder_id is not None
    }
    # Projenin hissedarlari gorunurluk sorgusuyla ZATEN yuklendi
    # (`Project.shareholders`, `lazy="selectin"`) — hissedar basina "var mi"
    # sorgusu ACILMAZ ve okuma yuzeyiyle AYNI kaynak kullanilir. Kume
    # karsilastirmasi TEK adimda hem "baska projenin" hem "hic yok" durumunu
    # kapatir; ikisi de AYNI 404'u alir (IDOR-8).
    if not requested_shareholders <= {row.id for row in project.shareholders}:
        raise NotFoundError(guards.SHAREHOLDER_MISSING)

    units = await repository.get_units_by_ids(session, list(wanted))
    if len(units) != len(wanted) or any(unit.project_id != project.id for unit in units):
        raise NotFoundError(guards.UNIT_MISSING)

    for unit in units:
        item = wanted[unit.id]
        unit.owner_side = item.owner_side
        unit.shareholder_id = (
            item.shareholder_id if item.owner_side is UnitOwnerSide.landowner else None
        )
    await session.flush()
    # Spec §9: 42 unitelik bir kayit 42 satir yazsaydi gunlugu bogardi — TEK
    # satir. P9: hissedar atamasi sayisi AYNI ozete girer, yeni `AuditAction`
    # ACILMAZ (TB3 T3 emsali).
    assigned = sum(1 for unit in units if unit.shareholder_id is not None)
    detail = messages.unit_allocation_updated(project.name, len(units), assigned)
    return await service.list_units(session, actor, project_id), detail
