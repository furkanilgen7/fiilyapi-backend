"""T1 — boq_groups/boq_items modelleri, kisitlar ve cascade davranisi (spec §3.1-3.3)."""

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.modules.boq.models import BoqGroup, BoqItem
from app.modules.sites.models import Site


async def _site(session, project, code: str = "A-BLOK", **kwargs) -> Site:
    site = Site(project_id=project.id, code=code, name=kwargs.pop("name", "A-Blok Şantiyesi"))
    for field, value in kwargs.items():
        setattr(site, field, value)
    session.add(site)
    await session.flush()
    return site


def _group(site: Site, name: str = "TOPRAK VE TEMEL İŞLERİ", **kwargs) -> BoqGroup:
    return BoqGroup(site_id=site.id, name=name, **kwargs)


def _item(site: Site, group: BoqGroup, code: str = "01.001", **kwargs) -> BoqItem:
    defaults = {
        "description": "Kazı (Makine ile)",
        "unit": "m³",
        "quantity": Decimal("1240.000"),
        "unit_price": Decimal("280.00"),
    }
    defaults.update(kwargs)
    return BoqItem(site_id=site.id, group_id=group.id, code=code, **defaults)


async def test_group_defaults(db_session, project_factory):
    project = await project_factory("P-BOQ-1")
    site = await _site(db_session, project)
    group = _group(site)
    db_session.add(group)
    await db_session.flush()

    loaded = (
        await db_session.execute(select(BoqGroup).where(BoqGroup.id == group.id))
    ).scalar_one()
    assert loaded.sort_order == 0
    assert loaded.name == "TOPRAK VE TEMEL İŞLERİ"


async def test_item_defaults(db_session, project_factory):
    project = await project_factory("P-BOQ-2")
    site = await _site(db_session, project)
    group = _group(site)
    db_session.add(group)
    await db_session.flush()
    item = _item(site, group)
    db_session.add(item)
    await db_session.flush()

    loaded = (await db_session.execute(select(BoqItem).where(BoqItem.id == item.id))).scalar_one()
    assert loaded.sort_order == 0
    assert loaded.code == "01.001"
    assert loaded.quantity == Decimal("1240.000")
    assert loaded.unit_price == Decimal("280.00")


async def test_duplicate_code_same_site_raises_integrity_error(db_session, project_factory):
    project = await project_factory("P-BOQ-3")
    site = await _site(db_session, project)
    group = _group(site)
    db_session.add(group)
    await db_session.flush()
    db_session.add(_item(site, group, code="01.001"))
    await db_session.flush()

    db_session.add(_item(site, group, code="01.001", description="Baska kalem"))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_same_code_in_different_sites_is_allowed(db_session, project_factory):
    project = await project_factory("P-BOQ-4")
    site_a = await _site(db_session, project, code="A-BLOK")
    site_b = await _site(db_session, project, code="B-BLOK")
    group_a = _group(site_a)
    group_b = _group(site_b)
    db_session.add_all([group_a, group_b])
    await db_session.flush()

    db_session.add(_item(site_a, group_a, code="01.001"))
    db_session.add(_item(site_b, group_b, code="01.001"))
    await db_session.flush()  # dogurgan olmadan gecmeli


async def test_quantity_must_be_positive(db_session, project_factory):
    project = await project_factory("P-BOQ-5")
    site = await _site(db_session, project)
    group = _group(site)
    db_session.add(group)
    await db_session.flush()

    db_session.add(_item(site, group, quantity=Decimal("0.000")))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_unit_price_cannot_be_negative(db_session, project_factory):
    project = await project_factory("P-BOQ-6")
    site = await _site(db_session, project)
    group = _group(site)
    db_session.add(group)
    await db_session.flush()

    db_session.add(_item(site, group, unit_price=Decimal("-1.00")))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_site_delete_cascades_to_groups_and_items(db_session, project_factory):
    project = await project_factory("P-BOQ-7")
    site = await _site(db_session, project)
    group = _group(site)
    db_session.add(group)
    await db_session.flush()
    item = _item(site, group)
    db_session.add(item)
    await db_session.flush()
    group_id, item_id = group.id, item.id

    await db_session.delete(site)
    await db_session.flush()

    assert (
        await db_session.execute(select(BoqGroup).where(BoqGroup.id == group_id))
    ).first() is None
    assert (await db_session.execute(select(BoqItem).where(BoqItem.id == item_id))).first() is None


async def test_group_delete_cascades_to_items(db_session, project_factory):
    project = await project_factory("P-BOQ-8")
    site = await _site(db_session, project)
    group = _group(site)
    db_session.add(group)
    await db_session.flush()
    item = _item(site, group)
    db_session.add(item)
    await db_session.flush()
    item_id = item.id

    await db_session.delete(group)
    await db_session.flush()

    assert (await db_session.execute(select(BoqItem).where(BoqItem.id == item_id))).first() is None


# --- BOQ-SEC T1: tahsis tablosu kısıtları DB DÜZEYİNDE kanıtlanır ----------
#
# 🔴 Servis korkuluğunun varlığı, kısıtın DB'de OLDUĞUNU kanıtlamaz: korkuluk
# yarın bir yerde atlanabilir. Aşağıdaki iddialar ihlali gerçekten DENER ve
# veritabanının reddettiğini görür.


async def _section(session, site, name: str = "Kat 6-10"):
    from app.modules.sites.models import Section

    section = Section(site_id=site.id, name=name)
    session.add(section)
    await session.flush()
    return section


async def test_allocation_ayni_poz_ayni_bolum_IKI_SATIR_yazamaz(db_session, project_factory):
    """UQ (boq_item_id, section_id) — DEFERRABLE olduğu için ihlal COMMIT/flush
    sonunda değil, `SET CONSTRAINTS IMMEDIATE` ile ZORLANARAK ölçülür.

    Ertelenmiş kısıtın var olduğunu görmenin tek dürüst yolu budur: `flush`
    tek başına ertelenmiş kısıtı tetiklemez ve test SESSİZCE yeşil kalırdı.
    """
    from sqlalchemy import text

    from app.modules.boq.models import BoqItemSectionAllocation

    project = await project_factory("P-BOQSEC-1")
    site = await _site(db_session, project)
    group = _group(site)
    db_session.add(group)
    await db_session.flush()
    item = _item(site, group)
    db_session.add(item)
    await db_session.flush()
    section = await _section(db_session, site)

    db_session.add_all(
        [
            BoqItemSectionAllocation(
                boq_item_id=item.id, section_id=section.id, quantity=Decimal("100.000")
            ),
            BoqItemSectionAllocation(
                boq_item_id=item.id, section_id=section.id, quantity=Decimal("200.000")
            ),
        ]
    )
    await db_session.flush()

    with pytest.raises(IntegrityError) as hata:
        await db_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    assert "uq_boq_item_section_allocations_item_section" in str(hata.value), str(hata.value)


async def test_allocation_sifir_ve_negatif_miktar_DB_tarafindan_reddedilir(
    db_session, project_factory
):
    """CHECK (quantity > 0) — sıfır tahsis bir SATIR olarak tutulmaz."""
    from app.modules.boq.models import BoqItemSectionAllocation

    project = await project_factory("P-BOQSEC-2")
    site = await _site(db_session, project)
    group = _group(site)
    db_session.add(group)
    await db_session.flush()
    item = _item(site, group)
    db_session.add(item)
    await db_session.flush()
    section = await _section(db_session, site)

    item_id, section_id = item.id, section.id

    for miktar in (Decimal("0.000"), Decimal("-1.000")):
        db_session.add(
            BoqItemSectionAllocation(boq_item_id=item_id, section_id=section_id, quantity=miktar)
        )
        with pytest.raises(IntegrityError) as hata:
            await db_session.flush()
        # 🔴 "IntegrityError atıldı" YETMEZ: rollback sonrası kurulum satırları da
        # düşmüş olabilir ve ikinci tur FK ihlaliyle SAHTE YEŞİL verirdi. İhlal
        # eden kısıtın ADI iddia edilir.
        assert "ck_boq_item_section_allocations_qty_positive" in str(hata.value), str(hata.value)
        await db_session.rollback()
