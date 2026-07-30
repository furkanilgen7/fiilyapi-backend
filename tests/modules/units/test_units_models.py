"""B1 — blocks/units modelleri, kisitlar, cascade ve RESTRICT davranisi (spec §4.1-4.3).

Hiyerarsi: Proje › Santiye › Blok › Unite (spec §4.0). `units`'te `site_id` YOKTUR;
santiye blok uzerinden turetilir. Blok–proje tutarliligi bilesik FK ile DB duzeyinde
zorlanir — servis korkuluguna guvenilmez (spec §4.1).
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.modules.projects.models import Project
from app.modules.sites.models import Site
from app.modules.units.models import Block, Unit, UnitKind, UnitOwnerSide


async def _site(session, project: Project, code: str = "SANTIYE-1", name: str = "Merkez") -> Site:
    site = Site(project_id=project.id, code=code, name=name)
    session.add(site)
    await session.flush()
    return site


async def _block(session, project: Project, site: Site, name: str = "A Blok", **kwargs) -> Block:
    block = Block(project_id=project.id, site_id=site.id, name=name, **kwargs)
    session.add(block)
    await session.flush()
    return block


def _unit(project: Project, block: Block, unit_no: str = "1", **kwargs) -> Unit:
    defaults: dict = {"unit_kind": UnitKind.apartment}
    defaults.update(kwargs)
    return Unit(project_id=project.id, block_id=block.id, unit_no=unit_no, **defaults)


# --- blocks ---


async def test_block_requires_project_and_site(db_session, project_factory):
    project = await project_factory("P-UNIT-1")
    await _site(db_session, project)

    db_session.add(Block(project_id=project.id, site_id=None, name="A Blok"))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_block_name_unique_within_project(db_session, project_factory):
    project = await project_factory("P-UNIT-2")
    site = await _site(db_session, project)
    await _block(db_session, project, site, name="A Blok")

    db_session.add(Block(project_id=project.id, site_id=site.id, name="A Blok"))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_block_same_name_allowed_in_other_project(db_session, project_factory):
    project_a = await project_factory("P-UNIT-3A")
    project_b = await project_factory("P-UNIT-3B")
    site_a = await _site(db_session, project_a)
    site_b = await _site(db_session, project_b)

    await _block(db_session, project_a, site_a, name="A Blok")
    await _block(db_session, project_b, site_b, name="A Blok")  # dogurgan olmadan gecmeli


# --- units ---


async def test_unit_no_unique_within_block(db_session, project_factory):
    project = await project_factory("P-UNIT-4")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    db_session.add(_unit(project, block, unit_no="1"))
    await db_session.flush()

    db_session.add(_unit(project, block, unit_no="1"))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_unit_no_repeatable_across_blocks(db_session, project_factory):
    """SY 76 ve SY 106: A Blok "1" ile B Blok "1" ayni anda vardir."""
    project = await project_factory("P-UNIT-5")
    site = await _site(db_session, project)
    block_a = await _block(db_session, project, site, name="A Blok")
    block_b = await _block(db_session, project, site, name="B Blok")

    db_session.add(_unit(project, block_a, unit_no="1"))
    db_session.add(_unit(project, block_b, unit_no="1"))
    await db_session.flush()  # dogurgan olmadan gecmeli


async def test_unit_composite_fk_rejects_cross_project_block(db_session, project_factory):
    """Bilesik FK'nin kaniti: unit.project_id != block.project_id DB'de imkansizdir."""
    project_a = await project_factory("P-UNIT-6A")
    project_b = await project_factory("P-UNIT-6B")
    site_a = await _site(db_session, project_a)
    block_a = await _block(db_session, project_a, site_a)

    # Tekil FK'larin ikisi de saglanir (proje B var, blok A var); yalniz bilesik FK reddeder.
    db_session.add(_unit(project_b, block_a, unit_no="1"))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_unit_check_negative_areas(db_session, project_factory):
    project = await project_factory("P-UNIT-7")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)

    db_session.add(_unit(project, block, gross_area_m2=Decimal("-1.00")))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_unit_check_negative_net_area(db_session, project_factory):
    project = await project_factory("P-UNIT-8")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)

    db_session.add(_unit(project, block, net_area_m2=Decimal("-1.00")))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_unit_check_negative_list_price(db_session, project_factory):
    project = await project_factory("P-UNIT-9")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)

    db_session.add(_unit(project, block, list_price=Decimal("-1.00")))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_unit_check_negative_appraisal_value(db_session, project_factory):
    project = await project_factory("P-UNIT-10")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)

    db_session.add(_unit(project, block, appraisal_value=Decimal("-1.00")))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_unit_check_net_not_greater_than_gross(db_session, project_factory):
    """spec §4.3 / karar 5: net alan brutten buyuk olamaz (FDS 59 → 178/152)."""
    project = await project_factory("P-UNIT-11")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)

    db_session.add(
        _unit(project, block, gross_area_m2=Decimal("100.00"), net_area_m2=Decimal("120.00"))
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_unit_check_net_le_gross_allows_nulls(db_session, project_factory):
    """CHECK NULL'lari gecirir: brut bilinmiyorken net girilebilir."""
    project = await project_factory("P-UNIT-12")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)

    db_session.add(_unit(project, block, gross_area_m2=None, net_area_m2=Decimal("50.00")))
    await db_session.flush()  # dogurgan olmadan gecmeli


# --- cascade / restrict ---


async def test_project_delete_cascades_blocks_and_units(db_session, project_factory):
    """DB duzeyi kanit: `projects` satiri silinince blok VE unite birlikte gider.

    Silme kasitli olarak ham SQL ile yapilir. ORM uzerinden `session.delete(project)`
    cagirmak farkli bir yoldan gider: Project→Site iliskisi `cascade="all,
    delete-orphan"` oldugu icin ORM once `DELETE FROM sites` yayinlar, o da DB'de
    bloklari dusurmeye calisir ve uniteler hala dururken RESTRICT'e carpar. Bugun
    ne projede ne santiyede DELETE ucu vardir (ikisi de yalniz test yolu), ama boyle
    bir uc acilirsa ONCE unitelerin silinmesi gerekecek — bkz. `Unit` docstring'i.
    """
    project = await project_factory("P-UNIT-13")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    unit = _unit(project, block)
    db_session.add(unit)
    await db_session.flush()
    block_id, unit_id = block.id, unit.id

    db_session.expunge_all()
    await db_session.execute(text("DELETE FROM projects WHERE id = :id"), {"id": project.id})
    await db_session.flush()

    assert (await db_session.execute(select(Block).where(Block.id == block_id))).first() is None
    assert (await db_session.execute(select(Unit).where(Unit.id == unit_id))).first() is None


async def test_site_delete_cascades_blocks(db_session, project_factory):
    project = await project_factory("P-UNIT-14")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    block_id = block.id

    await db_session.delete(site)
    await db_session.flush()

    assert (await db_session.execute(select(Block).where(Block.id == block_id))).first() is None


async def test_block_delete_restricted_when_units_exist(db_session, project_factory):
    """spec §4.2: unitesi olan blok DB duzeyinde silinemez (ON DELETE RESTRICT)."""
    project = await project_factory("P-UNIT-15")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    db_session.add(_unit(project, block))
    await db_session.flush()

    with pytest.raises(IntegrityError):
        await db_session.execute(text("DELETE FROM blocks WHERE id = :id"), {"id": block.id})
        await db_session.flush()


# --- enum'lar ---


async def test_unit_kind_enum_rejects_unknown_value(db_session, project_factory):
    project = await project_factory("P-UNIT-16")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)

    with pytest.raises(DBAPIError):
        await db_session.execute(
            text(
                "INSERT INTO units (id, project_id, block_id, unit_no, unit_kind, sort_order) "
                "VALUES (:id, :project_id, :block_id, :unit_no, 'villa', 0)"
            ),
            {
                "id": uuid.uuid4(),
                "project_id": project.id,
                "block_id": block.id,
                "unit_no": "1",
            },
        )


async def test_unit_owner_side_nullable(db_session, project_factory):
    """spec §5.3: paylasim noterden sonra girilir, bos birakmak hata degildir."""
    project = await project_factory("P-UNIT-17")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)

    unit = _unit(project, block, owner_side=None)
    db_session.add(unit)
    await db_session.flush()
    assert unit.owner_side is None

    unit.owner_side = UnitOwnerSide.landowner
    await db_session.flush()
    loaded = (await db_session.execute(select(Unit).where(Unit.id == unit.id))).scalar_one()
    assert loaded.owner_side is UnitOwnerSide.landowner
