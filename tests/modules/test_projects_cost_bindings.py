"""P10 T3 — proje kartlarının maliyet/kâr yer tutucuları ZARFIN İÇİNDE gerçeğe bağlanır.

Bu dilimin ana kuralı: yer tutucuları TÜKETEN UI **CANLIDA** (E4 proje kartları),
bu yüzden **alan tipi DEĞİŞMEZ** — `MetricPlaceholder` kalır, yalnız içi dolar
(`available=True` + `value`, `pending_module=None`). PT `CountPlaceholder`
emsalinin farkı burada bilinçlidir: dolu `MetricPlaceholder` artık
`pending_module` TAŞIMAZ (ROADMAP §3 "çelişkili sözleşme" borcu kapanır).

Senaryo sayıları MOCKUP'TAN gelir:

* **KY** = `projedesign/Proje - Kendi Yatırım.dc.html` 168-194 — 48,2M − 29,8M =
  18,4M / %38,2 (182 "Toplam Maliyet ₺29.800.000" = E4 kendi yatırım kartının
  `total_cost` alanı).
* **KK** = `projedesign/Proje - Kat Karşılığı.dc.html` 121-141 — bizim pay
  30,4M · inşaat 17,6M → 12,8M / %42,1.
* **E4** = `projedesign/Ekran 4 - Projeler.dc.html` 75/82/89 (tip bazlı alan
  setleri) · 181/206/231/256 (DÖRT taahhüt kartının HEPSİ "Harcanan" basar;
  tahmini kâr/marj alanı taahhütte YOKTUR).
"""

from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.contracts.models import SubcontractorContract, SubcontractorContractItem
from app.modules.projects.models import Project, ProjectInvestment, ProjectLandShare
from app.modules.projects.schemas import CountPlaceholder, MetricPlaceholder, metric
from app.modules.sites.models import Site
from app.modules.subcontractor_progress_payments.models import (
    SubcontractorPaymentStatus,
    SubcontractorProgressPayment,
    SubcontractorProgressPaymentLine,
)
from app.modules.units.models import Block, Unit, UnitKind, UnitOwnerSide
from app.modules.users.models import User
from tests.conftest import test_engine

_TENTH = Decimal("0.1")


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _login(client, user_factory, role_key: str = "system_admin") -> str:
    address = f"{role_key}@p10t3.co"
    await user_factory(email=address, password="parola1234", role_key=role_key)
    resp = await client.post("/auth/login", json={"email": address, "password": "parola1234"})
    return resp.json()["access_token"]


def _set_budget_lines(project: Project, *, material="0", labor="0", sub="0", overhead="0") -> None:
    project.budget_material = Decimal(material)
    project.budget_labor = Decimal(labor)
    project.budget_subcontractor = Decimal(sub)
    project.budget_overhead = Decimal(overhead)


async def _units(session: AsyncSession, project: Project, specs: list[dict]) -> list[Unit]:
    site = Site(project_id=project.id, code=f"SNT-{project.code}", name="Şantiye")
    session.add(site)
    await session.flush()
    block = Block(project_id=project.id, site_id=site.id, name="A Blok")
    session.add(block)
    await session.flush()
    created: list[Unit] = []
    for index, spec in enumerate(specs, start=1):
        unit = Unit(
            project_id=project.id,
            block_id=block.id,
            unit_no=str(index),
            unit_kind=UnitKind.apartment,
            list_price=spec.get("list_price"),
            appraisal_value=spec.get("appraisal_value"),
            gross_area_m2=spec.get("gross_area_m2"),
            owner_side=spec.get("owner_side"),
        )
        session.add(unit)
        created.append(unit)
    await session.flush()
    return created


async def _contract(
    session: AsyncSession, project: Project, creator: User, *, name: str
) -> SubcontractorContract:
    """Taşeron sözleşmesi + tek kalem (bedel türevdir, `amount` kolonu YOK)."""
    contract = SubcontractorContract(
        project_id=project.id, subcontractor_name=name, created_by=creator.id
    )
    session.add(contract)
    await session.flush()
    session.add(
        SubcontractorContractItem(
            contract_id=contract.id,
            code="A.001",
            description="Kalem",
            unit="m2",
            quantity=Decimal("1"),
            unit_price=Decimal("0"),
        )
    )
    await session.flush()
    return contract


async def _payment(
    session: AsyncSession,
    contract: SubcontractorContract,
    creator: User,
    status: SubcontractorPaymentStatus,
    *,
    quantity: str,
    sequence_no: int = 1,
) -> None:
    """Brüt = miktar × 1000 (kesintiler S2 gereği harcanana DOKUNMAZ)."""
    session.add(
        SubcontractorProgressPayment(
            contract_id=contract.id,
            project_id=contract.project_id,
            sequence_no=sequence_no,
            status=status,
            vat_pct=Decimal("20"),
            advance_pct=Decimal("10"),
            retainage_pct=Decimal("5"),
            created_by=creator.id,
            lines=[
                SubcontractorProgressPaymentLine(
                    code="A.001",
                    description="Kalem",
                    unit="m2",
                    contract_unit_price=Decimal("1000"),
                    coefficient=Decimal("1.000"),
                    quantity=Decimal(quantity),
                )
            ],
        )
    )
    await session.flush()


def _card(body: dict, project_id, key: str) -> dict:
    item = next(row for row in body["items"] if row["id"] == str(project_id))
    return item[key]


def _envelopes(node: Any, path: str = "") -> Iterator[tuple[str, dict]]:
    """Yanıt gövdesindeki TÜM zarfları (available/value|count taşıyan sözlük) gezer."""
    if isinstance(node, dict):
        if "available" in node and ("value" in node or "count" in node):
            yield path, node
        for key, value in node.items():
            yield from _envelopes(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _envelopes(value, f"{path}[{index}]")


# --- Zarf sözleşmesi (şema düzeyi) ---


def test_dolu_metric_zarfi_pending_module_tasiyamaz() -> None:
    """`available=True` ⇒ `pending_module is None` (ROADMAP §3 borcu)."""
    with pytest.raises(ValidationError):
        MetricPlaceholder(available=True, value=Decimal("1.00"), pending_module="project_costs")


def test_bos_metric_zarfi_pending_module_vermeden_kurulamaz() -> None:
    """Boş zarf HÂLÂ kaynağını bildirmek zorundadır: ekran "hangi modül gelince
    dolacak" bilgisini oradan basar."""
    with pytest.raises(ValidationError):
        MetricPlaceholder()


def test_count_zarfinin_dolu_iken_pending_module_tasimasi_KIRILMAZ() -> None:
    """PT emsali (puantaj sayaçları) BİLİNÇLİDİR — `CountPlaceholder`a dokunulmaz."""
    counter = CountPlaceholder(available=True, count=2, pending_module="timesheet")

    assert counter.count == 2
    assert counter.pending_module == "timesheet"


def test_metric_fabrikasi_degeri_olani_doldurur_olmayani_bos_birakir() -> None:
    dolu = metric(Decimal("18400000.00"), "project_costs")
    bos = metric(None, "project_costs")

    assert (dolu.available, dolu.value, dolu.pending_module) == (
        True,
        Decimal("18400000.00"),
        None,
    )
    assert (bos.available, bos.value, bos.pending_module) == (False, None, "project_costs")


# --- Tip bazlı alan setleri (E4 75/82/89) ---


async def test_kendi_yatirim_karti_maliyet_kar_marj_gercek_doner(
    client, db_session, user_factory, project_factory
):
    """KY 182/187-188: toplam maliyet 29,8M · kâr 18,4M · marj %38,2."""
    project = await project_factory(code="T3-KY", project_type="kendi_yatirim")
    _set_budget_lines(
        project, material="8000000", labor="5000000", sub="7000000", overhead="1400000"
    )
    db_session.add(ProjectInvestment(project_id=project.id, land_cost=Decimal("8400000.00")))
    await db_session.flush()
    await _units(
        db_session,
        project,
        [
            {"list_price": Decimal("24100000.00")},
            {"list_price": Decimal("24100000.00")},
        ],
    )
    token = await _login(client, user_factory)

    body = (await client.get("/projects", headers=_auth(token))).json()

    card = _card(body, project.id, "investment")
    assert card["total_cost"]["available"] is True
    assert Decimal(card["total_cost"]["value"]) == Decimal("29800000.00")
    assert card["total_cost"]["pending_module"] is None
    assert Decimal(card["estimated_profit"]["value"]) == Decimal("18400000.00")
    assert Decimal(card["margin"]["value"]).quantize(_TENTH) == Decimal("38.2")
    # P10 KAPSAMI DIŞI alanlar yer tutucu KALIR (satış/ünite dilimlerinin işi).
    assert card["sold_amount"]["available"] is False
    assert card["sales_ratio"]["available"] is False


async def test_kat_karsiligi_karti_pay_degeri_insaat_maliyeti_ve_marj_verir(
    client, db_session, user_factory, project_factory
):
    """KK 121/135/139-140: 30,4M − 17,6M = 12,8M / %42,1 · arsa 0 kuralı gömülü."""
    project = await project_factory(code="T3-KK", project_type="kat_karsiligi")
    _set_budget_lines(project, material="17600000")
    db_session.add(
        ProjectLandShare(
            project_id=project.id,
            landowner_name="Yılmaz Ailesi",
            our_share_pct=Decimal("55.00"),
            owner_share_pct=Decimal("45.00"),
        )
    )
    await db_session.flush()
    await _units(
        db_session,
        project,
        [
            {
                "appraisal_value": Decimal("30400000.00"),
                "owner_side": UnitOwnerSide.contractor,
            },
            {
                "appraisal_value": Decimal("25000000.00"),
                "owner_side": UnitOwnerSide.landowner,
            },
        ],
    )
    token = await _login(client, user_factory)

    body = (await client.get("/projects", headers=_auth(token))).json()

    card = _card(body, project.id, "land_share")
    assert Decimal(card["our_share_value"]["value"]) == Decimal("30400000.00")
    assert Decimal(card["construction_cost"]["value"]) == Decimal("17600000.00")
    assert Decimal(card["estimated_profit"]["value"]) == Decimal("12800000.00")
    assert Decimal(card["margin"]["value"]).quantize(_TENTH) == Decimal("42.1")
    assert card["construction_progress"]["available"] is False


async def test_taahhut_kartinin_harcanani_taseron_hakedislerinden_doner(
    client, db_session, user_factory, project_factory
):
    """E4 181/206/231/256 "Harcanan": spec §2 → taşeron hakedişleri approved+paid BRÜT.

    İşveren hakedişi (`progress_payments`) taahhütte GELİRDİR, harcama değil —
    alanın eski `pending_module`ı bu yüzden yanlış etiketti.
    """
    kurucu = await user_factory(email="harcanan@p10t3.co", password="parola1234", role_key="patron")
    project = await project_factory(
        code="T3-HR", project_type="taahhut", contract_amount="11200000.00"
    )
    contract = await _contract(db_session, project, kurucu, name="Akın İnşaat")
    await _payment(db_session, contract, kurucu, SubcontractorPaymentStatus.paid, quantity="5700")
    await _payment(
        db_session,
        contract,
        kurucu,
        SubcontractorPaymentStatus.approved,
        quantity="840",
        sequence_no=2,
    )
    # Maliyete GİRMEYEN durum (S1): harcananı büyütmemeli.
    await _payment(
        db_session,
        contract,
        kurucu,
        SubcontractorPaymentStatus.pending_approval,
        quantity="9000",
        sequence_no=3,
    )
    token = await _login(client, user_factory)

    body = (await client.get("/projects", headers=_auth(token))).json()

    spent = _card(body, project.id, "contracting")["spent"]
    assert spent["available"] is True
    assert Decimal(spent["value"]) == Decimal("6540000.00")
    assert spent["pending_module"] is None


async def test_hakedissiz_taahhut_projesinde_harcanan_SIFIR_gercek_cevaptir(
    client, db_session, user_factory, project_factory
):
    """Kaynak modül CANLI: hakedişi olmayan taahhütte `0.00` "bilinmiyor" değil
    "henüz harcanmadı"dır (`our_share_value`daki gerekçenin aynısı)."""
    project = await project_factory(
        code="T3-H0", project_type="taahhut", contract_amount="5100000.00"
    )
    await db_session.flush()
    token = await _login(client, user_factory)

    body = (await client.get("/projects", headers=_auth(token))).json()

    spent = _card(body, project.id, "contracting")["spent"]
    assert spent["available"] is True
    assert Decimal(spent["value"]) == Decimal("0.00")
    assert spent["pending_module"] is None


async def test_taahhut_kartinda_kar_marj_alani_YOKTUR(
    client, db_session, user_factory, project_factory
):
    """E4 180-181: taahhüt kartı yalnız bedel/harcanan basar — kâr alanı İCAT EDİLMEZ."""
    project = await project_factory(
        code="T3-TA", project_type="taahhut", contract_amount="11200000.00"
    )
    _set_budget_lines(project, material="1000000")
    await db_session.flush()
    token = await _login(client, user_factory)

    body = (await client.get("/projects", headers=_auth(token))).json()

    card = _card(body, project.id, "contracting")
    assert set(card) == {
        "spent",
        "physical_progress",
        "final_progress_payment",
        "worker_count",
        "subcontractor_count",
    }


async def test_butcesiz_projede_maliyet_zarfi_BOS_KALIR(
    client, db_session, user_factory, project_factory
):
    """Bütçe girilmemiş projede toplam 0 çıkar; bu "maliyet ₺0" DEĞİL "bilinmiyor"dur."""
    project = await project_factory(code="T3-B0", project_type="kendi_yatirim")
    await _units(db_session, project, [{"list_price": Decimal("1000000.00")}])
    token = await _login(client, user_factory)

    body = (await client.get("/projects", headers=_auth(token))).json()

    card = _card(body, project.id, "investment")
    for key in ("total_cost", "estimated_profit", "margin"):
        assert card[key]["available"] is False, key
        assert card[key]["value"] is None, key
        assert card[key]["pending_module"] == "project_costs", key


async def test_liste_yanitindaki_HER_dolu_zarf_pending_module_tasimaz(
    client, db_session, user_factory, project_factory
):
    """Zarf sözleşmesi UÇ düzeyinde: gövdedeki tüm zarflar taranır (yalnız kart değil)."""
    project = await project_factory(code="T3-ZR", project_type="kendi_yatirim")
    _set_budget_lines(project, material="10000000")
    await db_session.flush()
    await _units(db_session, project, [{"list_price": Decimal("20000000.00")}])
    token = await _login(client, user_factory)

    body = (await client.get("/projects", headers=_auth(token))).json()

    zarflar = list(_envelopes(body))
    assert any(zarf["available"] for _, zarf in zarflar)
    for yol, zarf in zarflar:
        if "count" in zarf:
            continue  # CountPlaceholder emsali bilinçli olarak KIRILMAZ
        assert (zarf["pending_module"] is None) == zarf["available"], (yol, zarf)


async def test_detay_ucu_ile_liste_ucu_ayni_maliyet_degerini_verir(
    client, db_session, user_factory, project_factory
):
    """Ekran karttan detaya geçince rakam DEĞİŞMEZ (tek hesap kaynağı)."""
    project = await project_factory(code="T3-DT", project_type="kendi_yatirim")
    _set_budget_lines(project, material="12000000")
    await db_session.flush()
    await _units(db_session, project, [{"list_price": Decimal("20000000.00")}])
    token = await _login(client, user_factory)

    liste = (await client.get("/projects", headers=_auth(token))).json()
    detay = (await client.get(f"/projects/{project.id}", headers=_auth(token))).json()

    assert detay["investment"]["total_cost"] == _card(liste, project.id, "investment")["total_cost"]
    assert Decimal(detay["investment"]["estimated_profit"]["value"]) == Decimal("8000000.00")


# --- N+1 ölçümü (spec §4) ---


@pytest.fixture
def _sorgu_sayaci() -> Iterator[list[str]]:
    """T1/T2 deseninin aynısı: N+1 iddiası tahmine değil ÖLÇÜME dayanır."""
    ifadeler: list[str] = []

    def kaydet(conn, cursor, statement, parameters, context, executemany) -> None:  # noqa: ANN001
        ifadeler.append(" ".join(statement.split()))

    event.listen(test_engine.sync_engine, "before_cursor_execute", kaydet)
    try:
        yield ifadeler
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", kaydet)


def _tablo_sayimi(ifadeler: list[str], tablo: str) -> int:
    return sum(1 for ifade in ifadeler if f"from {tablo}" in ifade.lower())


async def test_proje_listesinde_sorgu_sayisi_proje_sayisindan_bagimsizdir(
    db_session, user_factory, project_factory, _sorgu_sayaci: list[str]
):
    """Spec §4: kart türevleri proje başına sorgu AÇMAZ."""
    from app.modules.projects.service import list_projects_overview
    from app.modules.users.models import UserProjectAccess

    user = await user_factory(email="olcum@p10t3.co", password="parola1234", role_key="patron")
    db_session.add(UserProjectAccess(user_id=user.id, project_id=None, all_projects=True))
    tek = await project_factory(code="T3-N1", project_type="kendi_yatirim")
    _set_budget_lines(tek, material="1000000")
    await _units(db_session, tek, [{"list_price": Decimal("100.00")}])
    await db_session.flush()

    _sorgu_sayaci.clear()
    await list_projects_overview(db_session, user, None, None)
    tek_sayim = _tablo_sayimi(_sorgu_sayaci, "units")

    for sira in range(3):
        proje = await project_factory(code=f"T3-N{sira + 2}", project_type="kendi_yatirim")
        _set_budget_lines(proje, material="1000000")
        await _units(db_session, proje, [{"list_price": Decimal("100.00")} for _ in range(4)])
    await db_session.flush()

    _sorgu_sayaci.clear()
    yanit = await list_projects_overview(db_session, user, None, None)
    cok_sayim = _tablo_sayimi(_sorgu_sayaci, "units")

    assert len(yanit.items) == 4
    assert tek_sayim == cok_sayim, (tek_sayim, cok_sayim)
    assert cok_sayim <= 1, cok_sayim


_TAAHHUT_TABLOLARI = (
    "subcontractor_progress_payments",
    "subcontractor_progress_payment_lines",
)


async def test_taahhut_kartlarinda_sorgu_sayisi_proje_ve_hakedis_sayisindan_bagimsizdir(
    db_session, user_factory, project_factory, _sorgu_sayaci: list[str]
):
    """Spec §4: "Harcanan" bağı proje başına sorgu AÇMAZ (1 proje vs 4 çok hakedişli)."""
    from app.modules.projects.service import list_projects_overview
    from app.modules.users.models import UserProjectAccess

    user = await user_factory(email="taolcum@p10t3.co", password="parola1234", role_key="patron")
    db_session.add(UserProjectAccess(user_id=user.id, project_id=None, all_projects=True))
    tek = await project_factory(code="T3-TN1", project_type="taahhut")
    sozlesme = await _contract(db_session, tek, user, name="Tek Taşeron")
    await _payment(db_session, sozlesme, user, SubcontractorPaymentStatus.paid, quantity="10")
    await db_session.flush()

    _sorgu_sayaci.clear()
    await list_projects_overview(db_session, user, None, None)
    tek_sayim = {tablo: _tablo_sayimi(_sorgu_sayaci, tablo) for tablo in _TAAHHUT_TABLOLARI}

    for sira in range(3):
        proje = await project_factory(code=f"T3-TN{sira + 2}", project_type="taahhut")
        for index in range(2):
            ek = await _contract(db_session, proje, user, name=f"Taşeron {index}")
            for no in (1, 2):
                await _payment(
                    db_session,
                    ek,
                    user,
                    SubcontractorPaymentStatus.paid,
                    quantity="10",
                    sequence_no=no,
                )
    await db_session.flush()

    _sorgu_sayaci.clear()
    yanit = await list_projects_overview(db_session, user, None, None)
    cok_sayim = {tablo: _tablo_sayimi(_sorgu_sayaci, tablo) for tablo in _TAAHHUT_TABLOLARI}

    assert len(yanit.items) == 4
    assert tek_sayim == cok_sayim, (tek_sayim, cok_sayim)
    assert all(sayi == 1 for sayi in cok_sayim.values()), cok_sayim


async def test_taahhut_projesi_yoksa_taseron_okumasi_HIC_kosmaz(
    db_session, user_factory, project_factory, _sorgu_sayaci: list[str]
):
    """Ünite okumasının tip süzgecinin aynısı: taahhüt projesi yoksa hakediş
    tablosuna hiç DOKUNULMAZ."""
    from app.modules.projects.service import list_projects_overview
    from app.modules.users.models import UserProjectAccess

    user = await user_factory(email="tipsuzgec@p10t3.co", password="parola1234", role_key="patron")
    db_session.add(UserProjectAccess(user_id=user.id, project_id=None, all_projects=True))
    proje = await project_factory(code="T3-TS0", project_type="kendi_yatirim")
    _set_budget_lines(proje, material="1000")
    await db_session.flush()

    _sorgu_sayaci.clear()
    await list_projects_overview(db_session, user, None, None)

    assert _tablo_sayimi(_sorgu_sayaci, "subcontractor_progress_payments") == 0


# --- Mutasyon denetimi ---


async def test_kart_hesabi_orm_nesnesini_DEGISTIRMEZ(
    db_session, user_factory, project_factory, seeded_db
):
    from app.modules.projects.service import list_projects_overview
    from app.modules.users.models import UserProjectAccess

    user = await user_factory(email="mutasyon@p10t3.co", password="parola1234", role_key="patron")
    db_session.add(UserProjectAccess(user_id=user.id, project_id=None, all_projects=True))
    project = await project_factory(code="T3-MU", project_type="kendi_yatirim")
    _set_budget_lines(project, material="5000000")
    await db_session.flush()
    uniteler = await _units(db_session, project, [{"list_price": Decimal("9000000.00")}])
    once = (project.budget_material, project.budget, uniteler[0].list_price)

    await list_projects_overview(db_session, user, None, None)

    assert (project.budget_material, project.budget, uniteler[0].list_price) == once
