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
from app.modules.units.models import (
    Block,
    BlockGroundUsage,
    BlockParkingType,
    BlockRoofType,
    BlockStatus,
    Unit,
    UnitFacing,
    UnitKind,
    UnitOwnerSide,
    UnitParkingRight,
    UnitSalesStatus,
)


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


def test_unit_kind_bes_deger_icerir():
    """P3.1 spec §4.3: UE 74 Daire · Dukkan · Ofis · Depo · Otopark."""
    assert [member.value for member in UnitKind] == [
        "apartment",
        "shop",
        "office",
        "warehouse",
        "parking",
    ]


async def test_unit_kind_db_enum_degerleri(db_session):
    """pg_enum'da bes etiket, spec §4.3'teki sirayla."""
    labels = (
        (
            await db_session.execute(
                text(
                    "SELECT e.enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
                    "WHERE t.typname = 'unit_kind' ORDER BY e.enumsortorder"
                )
            )
        )
        .scalars()
        .all()
    )
    assert list(labels) == ["apartment", "shop", "office", "warehouse", "parking"]


async def test_unit_kind_office_warehouse_parking_yazilabilir(db_session, project_factory):
    project = await project_factory("P-UNIT-18")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)

    for index, kind in enumerate((UnitKind.office, UnitKind.warehouse, UnitKind.parking)):
        db_session.add(_unit(project, block, unit_no=f"K{index}", unit_kind=kind))
    await db_session.flush()  # dogurgan olmadan gecmeli


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


# --- P3.1 / R2: yedi yeni enum tipi ---


def test_yedi_yeni_enum_uyeleri():
    """Spec §3.1 ve §4.1/4.2 tablolarindaki deger kumeleri BIREBIR."""
    assert [m.value for m in BlockRoofType] == ["none", "duplex", "terrace"]
    assert [m.value for m in BlockGroundUsage] == ["commercial", "apartment", "common"]
    assert [m.value for m in BlockParkingType] == ["closed", "open", "none"]
    assert [m.value for m in BlockStatus] == ["planning", "construction", "completed"]
    assert [m.value for m in UnitFacing] == ["south", "southwest", "east", "north", "west"]
    assert [m.value for m in UnitParkingRight] == ["none", "one_closed", "two"]
    assert [m.value for m in UnitSalesStatus] == ["listed", "reserved", "sold", "closed"]


def test_unit_facing_bes_deger():
    """Karar 7: mockup'ta gecen TAM OLARAK bes yon; `northeast` / `northwest` /
    `southeast` ICAT EDILMEZ."""
    assert len(UnitFacing) == 5
    for absent in ("northeast", "northwest", "southeast"):
        assert absent not in {m.value for m in UnitFacing}


# --- P3.1 / R3: 21 yeni kolon ---

BLOCK_NEW_COLUMNS = (
    "code",
    "basement_floor_count",
    "floor_count",
    "roof_type",
    "units_per_floor",
    "ground_floor_usage",
    "shop_count",
    "construction_area_m2",
    "elevator_count",
    "parking_type",
    "estimated_delivery_date",
    "status",
    "notes",
)
UNIT_NEW_COLUMNS = (
    "floor",
    "facing",
    "balcony_area_m2",
    "bathroom_count",
    "parking_right",
    "min_sale_price",
    "vat_rate",
    "sales_status",
)


async def _nullability(session, table: str) -> dict[str, str]:
    rows = (
        await session.execute(
            text(
                "SELECT column_name, is_nullable FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = :table"
            ),
            {"table": table},
        )
    ).all()
    return {name: nullable for name, nullable in rows}


async def test_blocks_13_yeni_kolon_hepsi_nullable(db_session):
    """Plan §0.A.5: bu dilimde HICBIR kolon NOT NULL yapilmaz (taslak destegi)."""
    nullability = await _nullability(db_session, "blocks")
    assert {column: nullability.get(column) for column in BLOCK_NEW_COLUMNS} == {
        column: "YES" for column in BLOCK_NEW_COLUMNS
    }


async def test_units_8_yeni_kolon_hepsi_nullable(db_session):
    nullability = await _nullability(db_session, "units")
    assert {column: nullability.get(column) for column in UNIT_NEW_COLUMNS} == {
        column: "YES" for column in UNIT_NEW_COLUMNS
    }


async def test_units_floor_string20_ve_check_yok(db_session):
    """Karar 4: kat METINDIR; `ck_units_floor` YOKTUR."""
    row = (
        await db_session.execute(
            text(
                "SELECT data_type, character_maximum_length FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'units' AND column_name = 'floor'"
            )
        )
    ).one()
    assert row.data_type == "character varying"
    assert row.character_maximum_length == 20

    constraints = (
        (
            await db_session.execute(
                text(
                    "SELECT conname FROM pg_constraint WHERE conrelid = 'units'::regclass "
                    "AND contype = 'c'"
                )
            )
        )
        .scalars()
        .all()
    )
    assert "ck_units_floor" not in set(constraints)


async def test_yeni_check_kisitlari_isimleriyle_var(db_session):
    """Spec §3.1 / §4.1 tablolarindaki CHECK adlari BIREBIR."""
    for table, expected in (
        (
            "blocks",
            {
                "ck_blocks_basement_floor_count",
                "ck_blocks_floor_count",
                "ck_blocks_units_per_floor",
                "ck_blocks_shop_count",
                "ck_blocks_construction_area",
                "ck_blocks_elevator_count",
            },
        ),
        (
            "units",
            {
                "ck_units_balcony_area",
                "ck_units_bathroom_count",
                "ck_units_min_sale_price",
                "ck_units_vat_rate",
            },
        ),
    ):
        names = set(
            (
                await db_session.execute(
                    text(
                        "SELECT conname FROM pg_constraint "
                        f"WHERE conrelid = '{table}'::regclass AND contype = 'c'"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert expected <= names, f"{table}: eksik CHECK {expected - names}"


async def test_status_server_default_construction(db_session, project_factory):
    project = await project_factory("P-UNIT-19")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site, name="Varsayilan Blok")
    await db_session.refresh(block)
    assert block.status is BlockStatus.construction


async def test_sales_status_server_default_listed(db_session, project_factory):
    project = await project_factory("P-UNIT-20")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    unit = _unit(project, block)
    db_session.add(unit)
    await db_session.flush()
    await db_session.refresh(unit)
    assert unit.sales_status is UnitSalesStatus.listed


async def test_uq_blocks_project_code_null_serbest(db_session, project_factory):
    """Postgres'te birden cok NULL serbesttir: kodu olmayan eski bloklar kisiti ihlal etmez."""
    project = await project_factory("P-UNIT-21")
    site = await _site(db_session, project)
    await _block(db_session, project, site, name="A Blok", code=None)
    await _block(db_session, project, site, name="B Blok", code=None)  # dogurgan olmadan gecmeli


async def test_uq_blocks_project_code_ayni_kod_reddedilir(db_session, project_factory):
    project = await project_factory("P-UNIT-22")
    site = await _site(db_session, project)
    await _block(db_session, project, site, name="A Blok", code="A")

    db_session.add(Block(project_id=project.id, site_id=site.id, name="B Blok", code="A"))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_negatif_sayac_check_ihlali(db_session, project_factory):
    project = await project_factory("P-UNIT-23")
    site = await _site(db_session, project)

    db_session.add(Block(project_id=project.id, site_id=site.id, name="Eksi Blok", floor_count=-1))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_units_vat_rate_check_0_100(db_session, project_factory):
    project = await project_factory("P-UNIT-24")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)

    db_session.add(_unit(project, block, vat_rate=Decimal("101.00")))
    with pytest.raises(IntegrityError):
        await db_session.flush()


def test_sales_status_docstring_p8_notu_icerir():
    """Bir sonraki ajan sutunu "P3 ihlali" sanip SILMEMELIDIR (spec §4.4).

    Docstring hem YENI gecis notunu tasimali hem de P3'un artik gecersiz olan
    "sales_status sutunu YOKTUR" iddiasini TASIMAMALIDIR.
    """
    doc = Unit.__doc__
    assert doc is not None
    assert "GELECEK IS — P8" in doc
    assert "sales_status" in doc
    assert "gecici bir cozumdur" in doc
    assert "`sales_status` gibi sutunlar yoktur" not in doc
