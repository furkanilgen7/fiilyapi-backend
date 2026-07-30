"""T10 — `DELETE /sites/{site_id}` (spec §7.1, §12.3).

## Bu dosya neden VERI KAYBI SINIFI bir test setidir

`sites.id`'yi hedefleyen **dort FK'nin de `ON DELETE CASCADE`** oldugu koddan
dogrulandi (`sections`, `boq_groups`, `boq_items`, `blocks`). Yani DB
KENDILIGINDEN KORUMAZ: korkuluksuz tek bir `DELETE /sites/{id}` cagrisi
bolumleri, poz gruplarini, poz kalemlerini ve bloklari SESSIZCE yok eder ve bu
GERI ALINAMAZ.

Bu yuzden **409 donmesi tek basina kanit DEGILDIR**: 409 doner ama silme yine de
gerceklesirse (ornegin korkuluk `session.delete`ten SONRA kosarsa) hata gorunur,
veri gitmistir. Kanit, engellenen denemeden SONRA **dort tablonun da sayiminin
degismemis olmasidir** — asagida `_counts` yardimcisi tam olarak bunu olcer ve
engelleme testlerinin hepsi oncesi/sonrasi esitligini dogrular.
"""

import uuid
from decimal import Decimal

from sqlalchemy import func, select

from app.core.access import AccessLevel
from app.modules.boq.models import BoqGroup, BoqItem
from app.modules.roles.models import Module, Role, RolePermission
from app.modules.sites.models import Section, Site
from app.modules.units.models import Block, Unit, UnitKind

# Spec §7.2 — silme korkuluklarinin Turkce metinleri (testte BIREBIR beklenir).
SECTION_BLOCKER = "Bu şantiyede bölüm var, önce bölümleri silin"
BOQ_BLOCKER = "Bu şantiyede iş kalemi var, önce iş kalemlerini silin"
BLOCK_BLOCKER = "Bu şantiyede blok var, önce blokları silin"
SITE_MISSING = "Şantiye bulunamadı"
SECTION_MISSING = "Bölüm bulunamadı"


async def _login(client, user_factory, role_key: str = "system_admin") -> str:
    """Silme kapisi `sites:admin` — seed matrisinde YALNIZ `system_admin`'de var."""
    address = f"{role_key}-del@t.co"
    await user_factory(email=address, password="parola1234", role_key=role_key)
    resp = await client.post("/auth/login", json={"email": address, "password": "parola1234"})
    return resp.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _site(session, project, code: str = "A-BLOK", **kwargs) -> Site:
    site = Site(project_id=project.id, code=code, name=kwargs.pop("name", "A-Blok Şantiyesi"))
    for field, value in kwargs.items():
        setattr(site, field, value)
    session.add(site)
    await session.flush()
    return site


async def _section(session, site, name: str = "Kaba İnşaat", **kwargs) -> Section:
    section = Section(site_id=site.id, name=name, **kwargs)
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


async def _unit(session, project, block, unit_no: str = "1") -> Unit:
    unit = Unit(
        project_id=project.id,
        block_id=block.id,
        unit_no=unit_no,
        unit_kind=UnitKind.apartment,
    )
    session.add(unit)
    await session.flush()
    return unit


async def _counts(session, site_id: uuid.UUID) -> dict[str, int]:
    """CASCADE'in tetiklenmedigini kanitlayan olcum (§0.1).

    Dort bagli tablonun da SANTIYE KAPSAMINDA sayimi + santiyenin kendisi.
    `units` ayrica sayilir: `units.block_id` RESTRICT oldugu icin blok
    cascade'i patlar, ama bu KAZA sonucu bir korumadir — olculmeden guvenilmez.
    """

    async def _count(model, column, value) -> int:
        stmt = select(func.count()).select_from(model).where(column == value)
        return int((await session.execute(stmt)).scalar_one())

    block_ids = (
        (await session.execute(select(Block.id).where(Block.site_id == site_id))).scalars().all()
    )
    unit_count = 0
    if block_ids:
        stmt = select(func.count()).select_from(Unit).where(Unit.block_id.in_(block_ids))
        unit_count = int((await session.execute(stmt)).scalar_one())
    return {
        "sites": await _count(Site, Site.id, site_id),
        "sections": await _count(Section, Section.site_id, site_id),
        "boq_groups": await _count(BoqGroup, BoqGroup.site_id, site_id),
        "boq_items": await _count(BoqItem, BoqItem.site_id, site_id),
        "blocks": await _count(Block, Block.site_id, site_id),
        "units": unit_count,
    }


# --- S1: bos santiye silinir ---


async def test_delete_empty_site_returns_204(client, db_session, user_factory, project_factory):
    project = await project_factory("D-1")
    site = await _site(db_session, project)
    token = await _login(client, user_factory)

    resp = await client.delete(f"/sites/{site.id}", headers=_auth(token))

    assert resp.status_code == 204
    follow_up = await client.get(f"/sites/{site.id}", headers=_auth(token))
    assert follow_up.status_code == 404
    assert follow_up.json()["detail"] == SITE_MISSING


async def test_delete_returns_204_with_empty_body(
    client, db_session, user_factory, project_factory
):
    project = await project_factory("D-2")
    site = await _site(db_session, project)
    token = await _login(client, user_factory)

    resp = await client.delete(f"/sites/{site.id}", headers=_auth(token))

    assert resp.status_code == 204
    assert resp.content == b""


# --- S2: bolum engeli ---


async def test_delete_site_with_section_returns_409(
    client, db_session, user_factory, project_factory
):
    project = await project_factory("D-3")
    site = await _site(db_session, project)
    await _section(db_session, site)
    token = await _login(client, user_factory)

    resp = await client.delete(f"/sites/{site.id}", headers=_auth(token))

    assert resp.status_code == 409
    assert resp.json()["detail"] == SECTION_BLOCKER


async def test_delete_site_with_section_leaves_site_and_sections_intact(
    client, db_session, user_factory, project_factory
):
    """S2'nin ASIL amaci: 409 gordukten sonra HICBIR SEY silinmemis olmali.

    Durum kodu tek basina kanit degildir; sayim esitligi cascade'in
    tetiklenmediginin tek gercek kanitidir.
    """
    project = await project_factory("D-4")
    site = await _site(db_session, project)
    await _section(db_session, site, "Kaba İnşaat")
    await _section(db_session, site, "İnce İşler")
    token = await _login(client, user_factory)
    before = await _counts(db_session, site.id)

    resp = await client.delete(f"/sites/{site.id}", headers=_auth(token))

    assert resp.status_code == 409
    assert await _counts(db_session, site.id) == before
    assert before["sites"] == 1
    assert before["sections"] == 2


# --- S3: poz engeli ---


async def test_delete_site_with_boq_item_returns_409(
    client, db_session, user_factory, project_factory
):
    project = await project_factory("D-5")
    site = await _site(db_session, project)
    group = await _group(db_session, site)
    await _item(db_session, site, group)
    token = await _login(client, user_factory)
    before = await _counts(db_session, site.id)

    resp = await client.delete(f"/sites/{site.id}", headers=_auth(token))

    assert resp.status_code == 409
    assert resp.json()["detail"] == BOQ_BLOCKER
    assert await _counts(db_session, site.id) == before
    assert before["boq_items"] == 1
    assert before["boq_groups"] == 1


async def test_delete_site_with_boq_group_only_returns_409(
    client, db_session, user_factory, project_factory
):
    """Kalemsiz GRUP da tek basina engeldir (spec §7.1: `boq_items` VEYA `boq_groups`)."""
    project = await project_factory("D-6")
    site = await _site(db_session, project)
    await _group(db_session, site)
    token = await _login(client, user_factory)
    before = await _counts(db_session, site.id)

    resp = await client.delete(f"/sites/{site.id}", headers=_auth(token))

    assert resp.status_code == 409
    assert resp.json()["detail"] == BOQ_BLOCKER
    assert await _counts(db_session, site.id) == before
    assert before["boq_items"] == 0
    assert before["boq_groups"] == 1


# --- S4: blok engeli ---


async def test_delete_site_with_block_returns_409(
    client, db_session, user_factory, project_factory
):
    project = await project_factory("D-7")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    await _unit(db_session, project, block, "1")
    await _unit(db_session, project, block, "2")
    token = await _login(client, user_factory)
    before = await _counts(db_session, site.id)

    resp = await client.delete(f"/sites/{site.id}", headers=_auth(token))

    assert resp.status_code == 409
    assert resp.json()["detail"] == BLOCK_BLOCKER
    assert await _counts(db_session, site.id) == before
    assert before["blocks"] == 1
    assert before["units"] == 2


# --- S5: taslaga AYRICALIK YOK ---


async def test_delete_draft_site_with_section_returns_409(
    client, db_session, user_factory, project_factory
):
    """ "Taslak zaten yarim, gitsin" kisayolu YAZILMAZ (spec §7.1)."""
    project = await project_factory("D-8")
    site = await _site(db_session, project, is_draft=True)
    await _section(db_session, site)
    token = await _login(client, user_factory)
    before = await _counts(db_session, site.id)

    resp = await client.delete(f"/sites/{site.id}", headers=_auth(token))

    assert resp.status_code == 409
    assert resp.json()["detail"] == SECTION_BLOCKER
    assert await _counts(db_session, site.id) == before


# --- Sira ve mesaj disiplini ---


async def test_delete_stops_at_first_blocker(client, db_session, user_factory, project_factory):
    """Bolum + poz + blok birlikteyken kullaniciya TEK, eyleme donuk mesaj doner."""
    project = await project_factory("D-9")
    site = await _site(db_session, project)
    await _section(db_session, site)
    group = await _group(db_session, site)
    await _item(db_session, site, group)
    await _block(db_session, project, site)
    token = await _login(client, user_factory)
    before = await _counts(db_session, site.id)

    resp = await client.delete(f"/sites/{site.id}", headers=_auth(token))

    assert resp.status_code == 409
    assert resp.json()["detail"] == SECTION_BLOCKER
    assert BOQ_BLOCKER not in resp.text
    assert BLOCK_BLOCKER not in resp.text
    assert await _counts(db_session, site.id) == before


async def test_delete_error_message_omits_counts(client, db_session, user_factory, project_factory):
    """`BLOCK_HAS_UNITS` dersi: hata govdesi gorunurluk disi bilgi (adet) TASIMAZ."""
    project = await project_factory("D-10")
    site = await _site(db_session, project)
    for index in range(3):
        await _section(db_session, site, f"Faz {index}")
    token = await _login(client, user_factory)

    resp = await client.delete(f"/sites/{site.id}", headers=_auth(token))

    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail == SECTION_BLOCKER
    assert not any(character.isdigit() for character in detail)


# --- S9: korkuluk KALICI KILIT uretmiyor ---


async def test_delete_after_removing_sections_returns_204(
    client, db_session, user_factory, project_factory
):
    project = await project_factory("D-11")
    site = await _site(db_session, project)
    section = await _section(db_session, site)
    token = await _login(client, user_factory)

    blocked = await client.delete(f"/sites/{site.id}", headers=_auth(token))
    assert blocked.status_code == 409

    await db_session.delete(section)
    await db_session.flush()
    # ORM kimlik haritasi tazelensin: aksi hâlde santiyenin `sections`
    # koleksiyonu bayat kalir ve silinmis satiri ikinci kez silmeye calisir.
    await db_session.refresh(site, attribute_names=["sections"])

    resp = await client.delete(f"/sites/{site.id}", headers=_auth(token))

    assert resp.status_code == 204
    assert (await _counts(db_session, site.id))["sites"] == 0


# --- 404 / 409 ayrimi ---


async def test_delete_missing_site_returns_404(client, user_factory):
    token = await _login(client, user_factory)

    resp = await client.delete(f"/sites/{uuid.uuid4()}", headers=_auth(token))

    assert resp.status_code == 404
    assert resp.json()["detail"] == SITE_MISSING


async def test_delete_invisible_site_returns_same_404_body(
    client, db_session, user_factory, project_factory
):
    """Gorunmeyen GERCEK santiye ile var olmayan UUID AYIRT EDILEMEZ (§7.1 ortak kural).

    Aksi hâlde elinde UUID olan kullanici kaydin hâlâ var oldugunu ve baska bir
    projeye ait oldugunu ogrenirdi.
    """
    project = await project_factory("D-12")
    site = await _site(db_session, project)
    # `patron` sites=full tasir; silme kapisi icin admin'e cekilir ama proje
    # erisimi VERILMEZ — boylece gorunurluk suzgeci tek basina sinanir.
    role_id = (await db_session.execute(select(Role.id).where(Role.key == "patron"))).scalar_one()
    module_id = (
        await db_session.execute(select(Module.id).where(Module.key == "sites"))
    ).scalar_one()
    permission = (
        await db_session.execute(
            select(RolePermission).where(
                RolePermission.role_id == role_id, RolePermission.module_id == module_id
            )
        )
    ).scalar_one()
    permission.access_level = AccessLevel.admin
    await db_session.flush()
    await user_factory(email="patron-del@t.co", password="parola1234", role_key="patron")
    login = await client.post(
        "/auth/login", json={"email": "patron-del@t.co", "password": "parola1234"}
    )
    token = login.json()["access_token"]

    invisible = await client.delete(f"/sites/{site.id}", headers=_auth(token))
    unknown = await client.delete(f"/sites/{uuid.uuid4()}", headers=_auth(token))

    assert invisible.status_code == unknown.status_code == 404
    assert invisible.json() == unknown.json() == {"detail": SITE_MISSING}
