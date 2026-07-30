"""T9 — santiye silme korkuluk sorgulari (`site_has_sections` / `_boq` / `_blocks`).

Spec: §7.1 (silme uclari + bagli kayit korkulugu), §12.3.

## Bu dosya neden bu dilimin en kritik test seti

`sites.id`'yi hedefleyen **dort FK'nin da `ON DELETE CASCADE`** oldugu koddan
dogrulandi:

| Bagli tablo | Kolon | Davranis |
|---|---|---|
| `sections` | `site_id` | CASCADE |
| `boq_groups` | `site_id` | CASCADE |
| `boq_items` | `site_id` | CASCADE |
| `blocks` | `site_id` | CASCADE |

Yani **DB kendiliginden KORUMAZ**. Korkuluksuz tek bir `DELETE /sites/{id}`
cagrisi bolumleri, poz gruplarini, poz kalemlerini ve bloklari SESSIZCE yok
eder — geri alinamaz bir veri kaybi. Koruma tamamen UYGULAMA katmanindadir ve
bu uc sorgudur. Burada bir dal delinirse (ornegin `boq_groups` unutulursa)
T10'un `DELETE` ucu o dalda cascade'i tetikler.

`units.block_id`'nin `RESTRICT` olmasi tek kismi dogal agdir — ama o bir KAZA
sonucu korumadir, tasarim degildir ve poz/bolum tarafini hic korumaz.

Bu task'ta **hicbir uc acilmaz**: yalniz sorgular ve testleri (T9 -> T10 sirasi
pazarlik disidir).
"""

import uuid
from decimal import Decimal

from app.modules.boq.models import BoqGroup, BoqItem
from app.modules.sites import repository
from app.modules.sites.models import Section, Site
from app.modules.units.models import Block


async def _site(session, project, code: str = "A-BLOK") -> Site:
    site = Site(project_id=project.id, code=code, name=f"{code} Şantiyesi")
    session.add(site)
    await session.flush()
    return site


async def _section(session, site, name: str = "Kaba İnşaat") -> Section:
    section = Section(site_id=site.id, name=name)
    session.add(section)
    await session.flush()
    return section


async def _group(session, site, name: str = "TOPRAK VE TEMEL İŞLERİ") -> BoqGroup:
    group = BoqGroup(site_id=site.id, name=name)
    session.add(group)
    await session.flush()
    return group


async def _item(session, site, group, code: str = "01.001") -> BoqItem:
    item = BoqItem(
        site_id=site.id,
        group_id=group.id,
        code=code,
        description="Kazı (Makine ile)",
        unit="m³",
        quantity=Decimal("1240.000"),
        unit_price=Decimal("280.00"),
    )
    session.add(item)
    await session.flush()
    return item


async def _block(session, project, site, name: str = "A Blok") -> Block:
    block = Block(project_id=project.id, site_id=site.id, name=name)
    session.add(block)
    await session.flush()
    return block


# --- Bolum ---


async def test_site_has_sections_true_when_section_exists(db_session, project_factory):
    project = await project_factory("G-1")
    site = await _site(db_session, project)
    await _section(db_session, site)

    assert await repository.site_has_sections(db_session, site.id) is True


async def test_site_has_sections_false_when_empty(db_session, project_factory):
    project = await project_factory("G-2")
    site = await _site(db_session, project)

    assert await repository.site_has_sections(db_session, site.id) is False


# --- Poz (BOQ) ---


async def test_site_has_boq_true_for_boq_item(db_session, project_factory):
    project = await project_factory("G-3")
    site = await _site(db_session, project)
    group = await _group(db_session, site)
    await _item(db_session, site, group)

    assert await repository.site_has_boq(db_session, site.id) is True


async def test_site_has_boq_true_for_boq_group_without_items(db_session, project_factory):
    """GRUP TEK BASINA da engeldir (spec §7.1: "`boq_items` **veya** `boq_groups`").

    Yalniz kalemlere bakmak, kalemsiz gruplari olan bir santiyenin silinmesinde
    o gruplari SESSIZCE cascade'e gonderirdi.
    """
    project = await project_factory("G-4")
    site = await _site(db_session, project)
    await _group(db_session, site)

    assert await repository.site_has_boq(db_session, site.id) is True


async def test_site_has_boq_false_when_empty(db_session, project_factory):
    project = await project_factory("G-5")
    site = await _site(db_session, project)

    assert await repository.site_has_boq(db_session, site.id) is False


# --- Blok ---


async def test_site_has_blocks_true_when_block_exists(db_session, project_factory):
    project = await project_factory("G-6")
    site = await _site(db_session, project)
    await _block(db_session, project, site)

    assert await repository.site_has_blocks(db_session, site.id) is True


async def test_site_has_blocks_false_when_empty(db_session, project_factory):
    project = await project_factory("G-7")
    site = await _site(db_session, project)

    assert await repository.site_has_blocks(db_session, site.id) is False


# --- Kapsam sizintisi agi ---


async def test_guards_scoped_to_the_given_site(db_session, project_factory):
    """BASKA santiyenin bolumu/pozu/blogu `True` DONDURMEZ.

    Kapsam suzgeci dusen bir korkuluk daha da tehlikelidir: bos bir santiye
    silinemez hâle gelir, kullanici korkulugu "hatali" sanip GEVSETIR ve gercek
    koruma da kalkar.
    """
    project = await project_factory("G-8")
    target = await _site(db_session, project, "BOS")
    other = await _site(db_session, project, "DOLU")
    await _section(db_session, other)
    group = await _group(db_session, other)
    await _item(db_session, other, group)
    await _block(db_session, project, other)

    assert await repository.site_has_sections(db_session, target.id) is False
    assert await repository.site_has_boq(db_session, target.id) is False
    assert await repository.site_has_blocks(db_session, target.id) is False


async def test_guards_use_exists_and_fetch_no_rows(db_session, project_factory):
    """`block_has_units` deseni: `EXISTS` sorgusu, SATIR CEKMEZ.

    Kanit iki katmanlidir: (1) uretilen SQL `EXISTS` icerir, (2) donen deger
    `bool`dur — ORM nesnesi ya da sayim DEGIL. Kac bolum/poz/blok oldugu
    KULLANILMAZ (hata mesajinda adet verilmez, §7.1) ve 500 kalemi saymanin
    anlami yoktur.
    """
    project = await project_factory("G-9")
    site = await _site(db_session, project)
    await _section(db_session, site)
    group = await _group(db_session, site)
    await _item(db_session, site, group)
    await _block(db_session, project, site)

    statements: list[str] = []
    original_execute = db_session.execute

    async def _recording_execute(statement, *args, **kwargs):
        statements.append(str(statement))
        return await original_execute(statement, *args, **kwargs)

    db_session.execute = _recording_execute
    try:
        results = [
            await repository.site_has_sections(db_session, site.id),
            await repository.site_has_boq(db_session, site.id),
            await repository.site_has_blocks(db_session, site.id),
        ]
    finally:
        db_session.execute = original_execute

    assert results == [True, True, True]
    assert all(isinstance(value, bool) for value in results)
    assert len(statements) == 3
    assert all("EXISTS" in sql.upper() for sql in statements)


async def test_guards_false_for_unknown_site(db_session, seeded_db):
    """Var olmayan santiye: korkuluk patlamaz, `False` doner.

    Gorunurluk/varlik denetimi ONCE kosar (§7.1 ortak kurallari); repository
    yalniz veri okur, ikinci bir 404 mantigi ICAT ETMEZ.
    """
    missing = uuid.uuid4()

    assert await repository.site_has_sections(db_session, missing) is False
    assert await repository.site_has_boq(db_session, missing) is False
    assert await repository.site_has_blocks(db_session, missing) is False
