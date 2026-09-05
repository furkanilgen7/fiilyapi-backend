"""Silme uclari (spec §7.1) — CASCADE'i ENGELLEMEK tek istir."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import RelatedRecordsExistError

# Denetim METINLERI merkezidir (`audit/messages.py`): f-string ne servise ne
# router'a gomulur. Silme ve yayin metinleri BURADA kurulur, cunku gereken
# baglam (silinmeden onceki ad, `is_draft`in ONCEKI degeri) yalniz servis
# katmaninda vardir.
from app.modules.audit import messages
from app.modules.sites import guards, repository
from app.modules.sites.service.visibility import _visible_section, _visible_site
from app.modules.users.models import User


async def delete_site(session: AsyncSession, actor: User, site_id: uuid.UUID) -> str:
    """Spec §7.1. **CASCADE'i ENGELLEMEK bu fonksiyonun TEK isidir.**

    `sites.id`'yi hedefleyen DORT FK'nin da `ON DELETE CASCADE` oldugu koddan
    dogrulandi (`sections`, `boq_groups`, `boq_items`, `blocks`). Yani DB
    KENDILIGINDEN KORUMAZ: asagidaki uc kontrol kaldirilirsa tek bir istek
    bolumleri, poz gruplarini, poz kalemlerini ve bloklari SESSIZCE yok eder ve
    bu GERI ALINAMAZ. `delete_block` (`units/service.py:307`) deseninin
    birebiridir, tek farkla: orada DB'de `RESTRICT` ikinci katman olarak vardi,
    BURADA YOKTUR — servis korkulugu TEK savunmadir.

    Sira sabittir ve ILK ENGELDE DURUR: bolum -> poz -> blok. Kullaniciya tek,
    eyleme donuk mesaj verilir; uc engeli birden listelemek onu ayni formda uc
    kez geri gonderirdi.

    Taslak santiye icin AYRICALIK YOKTUR: bolumlu bir taslak da 409 doner.
    "Taslak zaten yarim, gitsin" kisayolu taslak/yayin ayrimini silme
    guvenliginin onune gecirirdi.

    Donen deger: DENETIM METNI. Metin `session.delete`ten ONCE kurulur
    (`units/service.py:327` dersi) — satir gittikten sonra `project.name` ve
    `site.name` guvenilir okunamaz ve denetim satiri bos adla yazilirdi, yani
    silinen kaydin NE OLDUGU tamamen kaybolurdu.

    Engellenen silme (409) denetime HICBIR SEY yazmaz: bu fonksiyon istisna
    atarak doner, metin hic kurulmaz. Denetim gerceklesen olayi kaydeder,
    denemeyi degil.
    """
    site, project = await _visible_site(session, actor, site_id)
    if await repository.site_has_sections(session, site.id):
        raise RelatedRecordsExistError(guards.SITE_HAS_SECTIONS)
    if await repository.site_has_boq(session, site.id):
        raise RelatedRecordsExistError(guards.SITE_HAS_BOQ)
    if await repository.site_has_blocks(session, site.id):
        raise RelatedRecordsExistError(guards.SITE_HAS_BLOCKS)
    if await repository.site_has_contracts(session, site.id):
        raise RelatedRecordsExistError(guards.SITE_HAS_CONTRACTS)
    if await repository.site_has_progress_payment_lines(session, site.id):
        raise RelatedRecordsExistError(guards.SITE_HAS_PROGRESS_PAYMENTS)
    detail = messages.site_deleted(project.name, site.name)
    await session.delete(site)
    await session.flush()
    return detail


async def delete_section(session: AsyncSession, actor: User, section_id: uuid.UUID) -> str:
    """Spec §7.1. Bolum silme KOSULSUZDUR — uydurma bir engel yazilmaz.

    🔴 ESKI METIN YANLISTI (BOQ-SEC'te olculdu): "sections.id'yi hedefleyen
    HICBIR FK yoktur" cumlesi yazildigi gunden beri bayattir — BUGUN ON BIR FK
    vardir (`personnel`, `timesheet`, `site_diary`, `site_planning`,
    `procurement`, `subcontractor_progress_payments`, `sections.depends_on_
    section_id` = SET NULL; `section_milestones` ve `boq_item_section_
    allocations` = CASCADE). DAVRANIS DEGISMEDI, yalniz gerekce duzeltildi.

    Silme HALA kosulsuzdur ve bu BILINCLIDIR:
    - `SET NULL` bacaklarinda kayit ayakta kalir, yalniz bilgi bagi kopar;
    - `CASCADE` bacaklarinda giden satirin BAGIMSIZ VARLIGI YOKTUR
      (kilometre tasi bolumun bir parcasidir; tahsis satiri ise "su poz, su
      bolume, su kadar" demekten ibarettir).

    # P5 notunun cevabi (BOQ-SEC K2): bag `boq_groups.section_id` olarak DEGIL
    # `boq_item_section_allocations` olarak acildi ve `section_has_boq`
    # korkulugu EKLENMEDI. O korkulugun gerekcesi "bolum silmek poz gruplarini
    # sessizce goturur"du; burada giden sey POZ DEGIL yalnizca TAHSISTIR —
    # pozun kendisi ve `quantity`si aynen durur, miktar "atanmamis" havuzuna
    # geri doner. Korkuluk eklenseydi kullanici, silmek istedigi bolumu
    # kurtarmak icin once her pozun tahsisini elle bosaltmak zorunda kalirdi.

    Gorunurluk suzgeci ONCE kosar (`_visible_section`: bolum -> santiye ->
    proje): gorunmeyen bolum 404 `Bölüm bulunamadı` doner ve govdesi var
    olmayan UUID'ninkiyle BIREBIR AYNIDIR.

    Kalan bolumlerin `sort_order` degerleri YENIDEN NUMARALANMAZ (davranis
    kilidi): silme, dokunulmayan satirlarin sirasini degistirmez.

    Donen deger: DENETIM METNI — `delete_site` ile ayni gerekce, metin satir yok
    olmadan ONCE kurulur.
    """
    section, site = await _visible_section(session, actor, section_id)
    detail = messages.section_deleted(site.name, section.name)
    await session.delete(section)
    await session.flush()
    return detail
