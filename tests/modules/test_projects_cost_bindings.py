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

import inspect
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
    """E4 122 "Toplam Maliyet" = HARCANAN (kullanıcı kararı 2026-08-09): arsa 8,4M
    + inşaat harcanan 10,24M = 18,64M. KY hero ikilisi ("₺20,3M / ₺29,8M bütçe")
    iki sayının FARKLI şeyler olduğunun kanıtıdır.

    Kâr/marj DEĞİŞMEZ: 48,2M − 29,8M bütçe = 18,4M / %38,2 (KY 182/187-188).
    """
    kurucu = await user_factory(
        email="kyharcanan@p10t3.co", password="parola1234", role_key="patron"
    )
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
    contract = await _contract(db_session, project, kurucu, name="Akın İnşaat")
    await _payment(db_session, contract, kurucu, SubcontractorPaymentStatus.paid, quantity="10240")
    token = await _login(client, user_factory)

    body = (await client.get("/projects", headers=_auth(token))).json()

    card = _card(body, project.id, "investment")
    assert card["total_cost"]["available"] is True
    assert Decimal(card["total_cost"]["value"]) == Decimal("18640000.00")
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


async def test_kendi_yatirim_toplam_maliyeti_ile_kat_karsiligi_insaat_maliyeti_AYRISIR(
    client, db_session, user_factory, project_factory
):
    """Kullanıcı kararı 2026-08-09: iki alan artık BAŞKA şeyler ölçer ve bağları
    KOPARILDI — `total_cost` HARCANAN (E4 122), `construction_cost` BÜTÇE (KK 135).

    Aynı bütçe + aynı hakediş verisiyle iki tipin kartı FARKLI rakam basmalıdır;
    eskiden `construction_cost` bir property olarak `total_cost`u döndürüyordu.
    """
    kurucu = await user_factory(email="ayrisma@p10t3.co", password="parola1234", role_key="patron")
    yatirim = await project_factory(code="T3-AY1", project_type="kendi_yatirim")
    _set_budget_lines(yatirim, material="17600000")
    kat = await project_factory(code="T3-AY2", project_type="kat_karsiligi")
    _set_budget_lines(kat, material="17600000")
    db_session.add(
        ProjectLandShare(
            project_id=kat.id,
            landowner_name="Yılmaz Ailesi",
            our_share_pct=Decimal("55.00"),
            owner_share_pct=Decimal("45.00"),
        )
    )
    await db_session.flush()
    for proje in (yatirim, kat):
        sozlesme = await _contract(db_session, proje, kurucu, name="Akın İnşaat")
        await _payment(
            db_session, sozlesme, kurucu, SubcontractorPaymentStatus.paid, quantity="4000"
        )
    token = await _login(client, user_factory)

    body = (await client.get("/projects", headers=_auth(token))).json()

    # Kendi yatırım: arsa girilmemiş → yalnız inşaat HARCANANI.
    assert Decimal(_card(body, yatirim.id, "investment")["total_cost"]["value"]) == Decimal(
        "4000000.00"
    )
    # Kat karşılığı: KK 135 BÜTÇEDİR ve kâr projeksiyonunun tabanıdır — harcanana DÖNMEZ.
    assert Decimal(_card(body, kat.id, "land_share")["construction_cost"]["value"]) == Decimal(
        "17600000.00"
    )


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
    """Bütçe girilmemiş projede KÂR/MARJ bilinmez: toplam 0 çıkar ama bu "maliyet
    ₺0" DEĞİL "bilinmiyor"dur.

    `total_cost` bu kuralın DIŞINDADIR (kullanıcı kararı 2026-08-09): o artık
    HARCANANDIR ve kaynağı (arsa + taşeron hakedişi) canlı olduğu için değer
    daima bilinir — hakedişsiz projede `0.00` gerçek cevaptır.
    """
    project = await project_factory(code="T3-B0", project_type="kendi_yatirim")
    await _units(db_session, project, [{"list_price": Decimal("1000000.00")}])
    token = await _login(client, user_factory)

    body = (await client.get("/projects", headers=_auth(token))).json()

    card = _card(body, project.id, "investment")
    for key in ("estimated_profit", "margin"):
        assert card[key]["available"] is False, key
        assert card[key]["value"] is None, key
        assert card[key]["pending_module"] == "project_costs", key
    assert card["total_cost"]["available"] is True
    assert Decimal(card["total_cost"]["value"]) == Decimal("0.00")


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


async def test_kendi_yatirim_kartlarinda_harcanan_okumasi_da_TEK_sorgudur(
    db_session, user_factory, project_factory, _sorgu_sayaci: list[str]
):
    """Kullanıcı kararı 2026-08-09 harcanan okumasını kendi yatırım projelerine de
    açtı; süzgeç genişledi ama toplu okuma TEK sorgu KALDI (spec §4)."""
    from app.modules.projects.service import list_projects_overview
    from app.modules.users.models import UserProjectAccess

    user = await user_factory(email="kyolcum@p10t3.co", password="parola1234", role_key="patron")
    db_session.add(UserProjectAccess(user_id=user.id, project_id=None, all_projects=True))
    tek = await project_factory(code="T3-KN1", project_type="kendi_yatirim")
    sozlesme = await _contract(db_session, tek, user, name="Tek Taşeron")
    await _payment(db_session, sozlesme, user, SubcontractorPaymentStatus.paid, quantity="10")
    await db_session.flush()

    _sorgu_sayaci.clear()
    await list_projects_overview(db_session, user, None, None)
    tek_sayim = {tablo: _tablo_sayimi(_sorgu_sayaci, tablo) for tablo in _TAAHHUT_TABLOLARI}

    for sira in range(3):
        proje = await project_factory(code=f"T3-KN{sira + 2}", project_type="kendi_yatirim")
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


async def test_harcanan_alani_olmayan_tipte_taseron_okumasi_HIC_kosmaz(
    db_session, user_factory, project_factory, _sorgu_sayaci: list[str]
):
    """Ünite okumasının tip süzgecinin aynısı: harcanan alanı olmayan tip
    (kat karşılığı — KK kartı yalnız BÜTÇE basar) hakediş tablosuna DOKUNMAZ.

    Kendi yatırım artık bu süzgecin İÇİNDEDİR (kullanıcı kararı 2026-08-09:
    E4 122 "Toplam Maliyet" = harcanan), taahhütle birlikte okunur.
    """
    from app.modules.projects.service import list_projects_overview
    from app.modules.users.models import UserProjectAccess

    user = await user_factory(email="tipsuzgec@p10t3.co", password="parola1234", role_key="patron")
    db_session.add(UserProjectAccess(user_id=user.id, project_id=None, all_projects=True))
    proje = await project_factory(code="T3-TS0", project_type="kat_karsiligi")
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


# --- Kat karşılığı TARAF ünite sayaçları (E4 148-149) ---
#
# Mockup otoritesi: `projedesign/Ekran 4 - Projeler.dc.html` 148-149 — kartın
# paylaşım şeridi "Biz %55 · 23 ünite" / "Arsa %45 · 19" basar. İki sayı da düz
# `owner_side` sayımıdır ve `GET /projects/{id}/land-share/summary` ucunun
# `our_side.unit_count` / `owner_side.unit_count` alanlarıyla AYNI sayılardır.


async def _kk_projesi(db_session, project_factory, *, code: str) -> Project:
    """Kat karşılığı proje + `ProjectLandShare` kaydı.

    Kayıt ŞART: `_land_share_card` kaydı olmayan projede `None` döner ve kart
    hiç kurulmaz — sayaç testi o hâlde neyi ölçtüğünü bilemezdi.
    """
    project = await project_factory(code=code, project_type="kat_karsiligi")
    db_session.add(
        ProjectLandShare(
            project_id=project.id,
            landowner_name="Yılmaz Ailesi",
            our_share_pct=Decimal("55.00"),
            owner_share_pct=Decimal("45.00"),
        )
    )
    await db_session.flush()
    return project


async def test_kat_karsiligi_karti_taraf_unite_sayaclarini_GERCEK_doner(
    client, db_session, user_factory, project_factory
):
    """E4 148-149 şeridinin iki sayacı ZARFIN İÇİNDE gerçeğe bağlanır.

    🔴 SAHTE-YEŞİL YASAĞI: beklenen 3/2 sayıları AŞAĞIDAKİ kurulumdan ELDE
    sayılmıştır (üç `contractor`, iki `landowner`, bir de taraflandırılmamış).
    Beklentiyi `len([u for u in units if u.owner_side is ...])` ile üretmek
    uygulamanın aynasını uygulamaya karşı sınamak olurdu — o test yüklem
    kaymasını GÖREMEZ.

    Altıncı (atanmamış) ünite bilinçlidir: hiçbir tarafa sayılmadığı için
    3 + 2 ≠ 6 olur ve "toplam ünite sayısını basıyor" hatası yakalanır.
    """
    project = await _kk_projesi(db_session, project_factory, code="T3-TS1")
    await _units(
        db_session,
        project,
        [
            {"appraisal_value": Decimal("100.00"), "owner_side": UnitOwnerSide.contractor},
            {"appraisal_value": Decimal("100.00"), "owner_side": UnitOwnerSide.contractor},
            {"appraisal_value": Decimal("100.00"), "owner_side": UnitOwnerSide.contractor},
            {"appraisal_value": Decimal("100.00"), "owner_side": UnitOwnerSide.landowner},
            {"appraisal_value": Decimal("100.00"), "owner_side": UnitOwnerSide.landowner},
            {"appraisal_value": Decimal("100.00"), "owner_side": None},
        ],
    )
    token = await _login(client, user_factory)

    body = (await client.get("/projects", headers=_auth(token))).json()

    card = _card(body, project.id, "land_share")
    # Zarf ŞEKLİ `_worker_count` emsalinin AYNISIDIR: dolu `CountPlaceholder`
    # `pending_module` TAŞIMAYA DEVAM EDER (bkz. `CountPlaceholder` notu).
    assert card["our_unit_count"] == {"available": True, "count": 3, "pending_module": "units"}
    assert card["owner_unit_count"]["available"] is True
    assert card["owner_unit_count"]["count"] == 2

    # Kart ile özet ucu AYNI projede AYNI sayıyı söyler (yüklem tek kopyadır).
    ozet = (
        await client.get(f"/projects/{project.id}/land-share/summary", headers=_auth(token))
    ).json()
    assert ozet["our_side"]["unit_count"] == 3
    assert ozet["owner_side"]["unit_count"] == 2
    assert ozet["unassigned"]["unit_count"] == 1


async def test_taraf_sayacinda_SIFIR_gercek_cevaptir_bilinmeyenden_AYRIDIR(
    client, db_session, user_factory, project_factory
):
    """🔴 K2 — "0" ile "bilinmiyor" AYNI TESTTE ayrışır.

    Kaynak modül (`units`) CANLIDIR: bizim payımızda ünite olmaması bir CEVAPTIR,
    eksik veri değil. Üç hâl tek testte karşılaştırılır:

    1. hiç ünitesi olmayan kat karşılığı proje → DOLU zarf + `count == 0`,
    2. üniteleri olan ama HİÇBİRİ taraflandırılmamış proje (noter paylaşımı
       öncesi gerçek dünya hâli) → yine DOLU zarf + `count == 0`,
    3. kat karşılığı OLMAYAN proje → alan kartta HİÇ YOKTUR (0 da basmaz).

    (1) ile (2) bu kartta AYNI cevabı verir ve vermelidir: ikisinde de bizim
    payımızda sıfır ünite vardır. Aradaki farkı taşıyan yer bu kart DEĞİL,
    `land-share/summary` ucunun `unassigned` bölümüdür — orada (1) sıfır, (2)
    üç ünite gösterir. (3) ise "alan yok" hâlidir ve 0'dan yapısal olarak ayrıdır.
    """
    bos = await _kk_projesi(db_session, project_factory, code="T3-TS2")
    atanmamis = await _kk_projesi(db_session, project_factory, code="T3-TS3")
    await _units(
        db_session,
        atanmamis,
        [{"appraisal_value": Decimal("100.00"), "owner_side": None} for _ in range(3)],
    )
    yatirim = await project_factory(code="T3-TS4", project_type="kendi_yatirim")
    _set_budget_lines(yatirim, material="1000")
    await db_session.flush()
    token = await _login(client, user_factory)

    body = (await client.get("/projects", headers=_auth(token))).json()

    # (1) ünitesi HİÇ olmayan proje: boş yer tutucu DEĞİL, dolu zarf içinde 0.
    bos_card = _card(body, bos.id, "land_share")
    assert bos_card["our_unit_count"]["available"] is True
    assert bos_card["our_unit_count"]["count"] == 0
    assert bos_card["owner_unit_count"]["available"] is True
    assert bos_card["owner_unit_count"]["count"] == 0

    # (2) üniteleri var ama taraflandırılmamış: iki taraf da yine dolu 0.
    atanmamis_card = _card(body, atanmamis.id, "land_share")
    assert atanmamis_card["our_unit_count"]["available"] is True
    assert atanmamis_card["our_unit_count"]["count"] == 0
    assert atanmamis_card["owner_unit_count"]["available"] is True
    assert atanmamis_card["owner_unit_count"]["count"] == 0

    # (1) ile (2) arasındaki fark KAYBOLMAZ; başka uçta durur.
    def _ozet_url(project_id) -> str:
        return f"/projects/{project_id}/land-share/summary"

    bos_ozet = (await client.get(_ozet_url(bos.id), headers=_auth(token))).json()
    atanmamis_ozet = (await client.get(_ozet_url(atanmamis.id), headers=_auth(token))).json()
    assert bos_ozet["unassigned"]["unit_count"] == 0
    assert atanmamis_ozet["unassigned"]["unit_count"] == 3

    # (3) alan HİÇ YOK hâli: kendi yatırım kartında bu iki anahtar bulunmaz.
    yatirim_card = _card(body, yatirim.id, "investment")
    assert "our_unit_count" not in yatirim_card
    assert "owner_unit_count" not in yatirim_card


def test_taraf_yuklemi_TEK_dosyada_yasar_kopyalanmaz() -> None:
    """🔴 K3 — yapısal bekçi: "ünite hangi tarafta" yüklemi ÜÇ yerde kopyaydı.

    `land_share.get_summary` (özet ucu), `costs.our_share_value` (pay değeri) ve
    kart bağı aynı `owner_side` karşılaştırmasını ayrı ayrı yazsaydı, TEK
    kopyada yapılan bir kayma (ör. atanmamış üniteyi "bizim" saymak) kart ile
    özet ucunun AYNI proje hakkında farklı sayı söylemesi demek olurdu — ve
    hiçbir davranış testi bunu yakalamazdı, çünkü her uç kendi kopyasına göre
    doğru kalırdı. Yüklem bu yüzden `unit_sides.py`de TEK kopyadır.

    Bekçi `codes.py` emsalinin (`tests/modules/units/test_units_block_codes.py`)
    aynısıdır: kaynak metni okunur, dizge aranır.
    """
    from app.modules.projects import cost_cards, costs, land_share, unit_sides

    for modul in (land_share, costs, cost_cards):
        kaynak = inspect.getsource(modul)
        for yuklem in ("UnitOwnerSide.contractor", "UnitOwnerSide.landowner", "owner_side is None"):
            assert yuklem not in kaynak, (
                f"{modul.__name__} taraf yüklemini KENDİ yazıyor ({yuklem!r}); "
                "tek kopya app/modules/projects/unit_sides.py'dedir."
            )

    tek_kaynak = inspect.getsource(unit_sides)
    assert "UnitOwnerSide.contractor" in tek_kaynak
    assert "UnitOwnerSide.landowner" in tek_kaynak
    assert "owner_side is None" in tek_kaynak


async def test_taraf_sayaclari_unite_sayisi_arttikca_SORGU_ACMAZ(
    db_session, user_factory, project_factory, _sorgu_sayaci: list[str]
):
    """🔴 N+1 bekçisi: sayaçlar ZATEN yüklü listeden türer, yeni sorgu AÇMAZ.

    Ünite 2'den 12'ye çıkarken `units` tablosuna giden ifade sayısı DEĞİŞMEZ.
    Sayaçlar için ayrı bir `SELECT count(*)` yazılsaydı bu ölçüm büyürdü.
    """
    from app.modules.projects.service import list_projects_overview
    from app.modules.users.models import UserProjectAccess

    user = await user_factory(email="tarafn1@p10t3.co", password="parola1234", role_key="patron")
    db_session.add(UserProjectAccess(user_id=user.id, project_id=None, all_projects=True))
    proje = await _kk_projesi(db_session, project_factory, code="T3-TSN")
    site = Site(project_id=proje.id, code="SNT-TSN", name="Şantiye")
    db_session.add(site)
    await db_session.flush()
    blok = Block(project_id=proje.id, site_id=site.id, name="A Blok")
    db_session.add(blok)
    await db_session.flush()

    async def _unite_ekle(ilk: int, son: int) -> None:
        """Tek numaralar BİZ, çift numaralar ARSA."""
        for no in range(ilk, son + 1):
            db_session.add(
                Unit(
                    project_id=proje.id,
                    block_id=blok.id,
                    unit_no=str(no),
                    unit_kind=UnitKind.apartment,
                    appraisal_value=Decimal("100.00"),
                    owner_side=(
                        UnitOwnerSide.contractor if no % 2 == 1 else UnitOwnerSide.landowner
                    ),
                )
            )
        await db_session.flush()

    await _unite_ekle(1, 2)
    _sorgu_sayaci.clear()
    az = await list_projects_overview(db_session, user, None, None)
    az_sayim = _tablo_sayimi(_sorgu_sayaci, "units")

    await _unite_ekle(3, 12)
    _sorgu_sayaci.clear()
    cok = await list_projects_overview(db_session, user, None, None)
    cok_sayim = _tablo_sayimi(_sorgu_sayaci, "units")

    # Sayaçların GERÇEKTEN büyüdüğünü de doğrula: sabit 0 dönen bir uygulama
    # sorgu ölçümünü sahte-yeşil geçerdi (1/1 → 6/6, elde sayıldı).
    assert (az.items[0].land_share.our_unit_count.count) == 1
    assert (az.items[0].land_share.owner_unit_count.count) == 1
    assert (cok.items[0].land_share.our_unit_count.count) == 6
    assert (cok.items[0].land_share.owner_unit_count.count) == 6
    assert az_sayim == cok_sayim, (az_sayim, cok_sayim)
    assert cok_sayim <= 1, cok_sayim


def test_taraf_KUMESININ_KENDISI_bekcilidir_yeni_enum_uyesi_sessizce_gecmez() -> None:
    """🔴 Bir kümeyle çalışan bekçi, KÜMENİN KENDİSİNİ de sınamalıdır (MT-2 kanonu).

    `unit_sides.partition` üç kümeye ayırır ve üçüncüsü (`unassigned`) ekranda
    *"noter paylaşımı henüz yapılmadı"* diye okunur — yani bir OLGU iddiasıdır.
    Ayrım `else` ile yazılsaydı `UnitOwnerSide`a eklenecek DÖRDÜNCÜ bir hâl
    sessizce "atanmamış" sayılır ve ekran ATANMIŞ bir üniteyi atanmamış diye
    basardı; sayılar yine tutacağı için hiçbir davranış testi de görmezdi.

    Bu bekçi iki katmanlıdır:
    1. enum'un BUGÜNKÜ üye kümesi çakılır — üye eklenirse bu test kırmızı olur
       ve geliştirici `unit_sides`ı karara bağlamak zorunda kalır;
    2. bilinmeyen bir taraf değeri `ValueError` ile PATLAR (sessizce bir kümeye
       düşmez) — sahte bir `Unit` ile doğrudan sınanır.
    """
    from types import SimpleNamespace

    from app.modules.projects import unit_sides
    from app.modules.units.models import UnitOwnerSide

    assert {uye.value for uye in UnitOwnerSide} == {"contractor", "landowner"}, (
        "`UnitOwnerSide` genisledi: `unit_sides.partition` uc kumesi ve bu testin "
        "beklentisi birlikte karara baglanmalidir."
    )

    with pytest.raises(ValueError, match="Bilinmeyen taraf"):
        unit_sides.partition([SimpleNamespace(owner_side="ortak_alan")])


# --- YER TUTUCU DENETİMİ 2026-08-22: gerekçeler ÇÜRÜMESİN diye çakılır ---
#
# Denetimin bulgusu: `pending_module` artık "modül yok" DEMİYOR — sahaya çıkan
# 13 anahtarın hepsi CANLI bir kaynağı adlandırıyor (`service._metric`
# docstring'i). Kalan yer tutucuların GERÇEK engelleri çağrı yerlerine yazıldı;
# aşağıdaki iki bekçi o yazıların hâlâ doğru olduğunu ölçer.


def test_projects_progress_pct_sutununun_YAZMA_YOLU_YOKTUR() -> None:
    """🔴 Denetimin BAŞ BULGUSU: `projects.progress_pct` YAZIMI ÖLÜ bir fosildir.

    Bu bir DİLEK değil, ÖLÇÜLMÜŞ durumdur. `construction_progress` yer tutucusunun
    (`service._land_share_card`) en tehlikeli tuzağı, bu sütunun apaçık bir kaynak
    gibi görünmesidir: `Numeric(5,2), nullable=False, default=0` (models.py:143),
    zaten HAM servis ediliyor (`ProjectListItem.progress_pct` zarf DEĞİL düz
    `Decimal`) — ama hiçbir HTTP isteği onu SET EDEMEZ, çünkü ne `ProjectCreate`
    ne `ProjectUpdate` böyle bir alan taşır. Buna rağmen daima 0 da değildir:
    `alembic/versions/795d6498e4da_projects_seed.py` üç demo projeye 42.50/15.00/
    100.00 yazar ve o revizyon head'in atasıdır. Yani sütun, kullanıcının açtığı
    her projede kalıcı 0; üç tohum satırında ise hiçbir formdan düzeltilemeyen
    donmuş bir değer.

    ⚠️ BU TEST KIRMIZIYA DÖNERSE: biri yazma yolu açmış demektir ve
    `construction_progress` tuzak yorumu (service.py, `_land_share_card`)
    YENİDEN KARARA BAĞLANMALIDIR — fosil artık fosil değildir.
    """
    from app.modules.projects.schemas import ProjectCreate, ProjectUpdate

    assert "progress_pct" not in ProjectCreate.model_fields, (
        "`ProjectCreate`e `progress_pct` eklenmis: `construction_progress` fosil "
        "gerekcesi artik gecerli olmayabilir, yeniden karara baglayin."
    )
    assert "progress_pct" not in ProjectUpdate.model_fields, (
        "`ProjectUpdate`e `progress_pct` eklenmis: `construction_progress` fosil "
        "gerekcesi artik gecerli olmayabilir, yeniden karara baglayin."
    )


async def test_govdeye_konan_progress_pct_POST_ve_PATCH_te_YOK_SAYILIR(client, user_factory):
    """Yapısal iddianın DAVRANIŞ tarafı: gövdeye elle yazmak da işe yaramaz.

    Pydantic varsayılanı `extra="ignore"`tır (`ProjectCreate`te `extra=` ayarı
    YOKTUR), bu yüzden fazladan anahtar 422 vermez — SESSİZCE DÜŞER. Sessiz
    düşüş tam da tehlikeli olan hâldir: istemci "gönderdim" sanır, sütun 0 kalır.
    Bu yüzden hem yaratma hem güncelleme yolu ölçülür.
    """
    token = await _login(client, user_factory)

    created = await client.post(
        "/projects",
        json={
            "code": "T3-FOSIL",
            "name": "Fosil Sütun Testi",
            "project_type": "taahhut",
            "is_draft": True,
            "progress_pct": "42.50",
        },
        headers=_auth(token),
    )
    assert created.status_code == 201, created.text
    assert Decimal(created.json()["progress_pct"]) == Decimal("0")

    project_id = created.json()["id"]
    patched = await client.patch(
        f"/projects/{project_id}",
        json={"name": "Fosil Sütun Testi 2", "progress_pct": "99.00"},
        headers=_auth(token),
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["name"] == "Fosil Sütun Testi 2"  # PATCH GERÇEKTEN koştu
    assert Decimal(patched.json()["progress_pct"]) == Decimal("0")


# Denetimin SINIFLANDIRMASI (kart, alan, anahtar, sınıf) — gerekçelerin TAM
# metni `service.py`deki çağrı yerlerindedir, burada yalnız ÇAKILIR:
#
#   (A) BAYAT  — kaynak CANLI, alan yalnızca henüz bağlanmadı (toplu okuyucu
#                ve/veya süzgeç kararı eksik).
#   (C) TUZAK  — bağlamak AKTİF OLARAK YANLIŞ olurdu: ya mockup kendi etiketiyle
#                çelişiyor, ya zarfın ŞEKLİ alanı ifade edemiyor, ya da anahtar
#                yapısal olarak karşılanamaz.
_DENETIM_2026_08_22 = (
    ("contracting", "physical_progress", "progress_payments", "C"),
    ("contracting", "final_progress_payment", "progress_payments", "C"),
    ("contracting", "subcontractor_count", "subcontracts", "A"),
    ("investment", "sold_amount", "units", "A"),
    ("investment", "sales_ratio", "units", "C"),
    ("investment", "unit_summary", "units", "C"),
    ("land_share", "construction_progress", "progress_payments", "C"),
)

_KART_TIPI = {
    "contracting": "taahhut",
    "investment": "kendi_yatirim",
    "land_share": "kat_karsiligi",
}


async def test_denetimin_YEDI_yer_tutucusu_hala_BOS_ve_anahtarini_TASIYOR(
    client, db_session, user_factory, project_factory
):
    """🔴 Gerekçe ÇÜRÜME bekçisi — yedi alanın hepsi tek tabloda çakılı.

    Bu test alanların bağlanmasını YASAKLAMAZ; bağlayanı, kaydedilmiş gerekçeyi
    OKUMAYA ZORLAR. Biri `service.py`deki tuzak/bayat notunu okumadan bir alanı
    doldurursa burası kırmızıya döner ve o notu güncellemek zorunda kalır.

    Anahtarın kendisi de çakılıdır: `pending_module` artık "modül yok" demiyor,
    "veri hangi modülün mülkiyetinde" diyor — anahtarı sessizce değiştirmek,
    çağrı yerindeki gerekçeyi de geçersiz kılar.
    """
    await _kk_projesi(db_session, project_factory, code="T3-DEN-KK")
    await project_factory(code="T3-DEN-TA", project_type="taahhut")
    await project_factory(code="T3-DEN-KY", project_type="kendi_yatirim")
    token = await _login(client, user_factory)

    body = (await client.get("/projects", headers=_auth(token))).json()
    kartlar = {
        kart: next(
            row[kart]
            for row in body["items"]
            if row["project_type"] == tip and row["code"].startswith("T3-DEN-")
        )
        for kart, tip in _KART_TIPI.items()
    }

    for kart, alan, anahtar, sinif in _DENETIM_2026_08_22:
        zarf = kartlar[kart][alan]
        assert zarf["available"] is False, (
            f"{kart}.{alan} BAGLANMIS: `service.py`deki SINIF ({sinif}) gerekcesi "
            f"okunup guncellenmeli (bu testin satiri da silinmeli)."
        )
        assert zarf["pending_module"] == anahtar, (
            f"{kart}.{alan} anahtari degismis ({zarf['pending_module']!r} != "
            f"{anahtar!r}): cagri yerindeki gerekce de gozden gecirilmeli."
        )


# --- P-YT4 DENETİMİ (2026-08-23): `construction_progress` anahtarının AÇIK UCU ---


def test_taseron_tarafinda_FIZIKSEL_ILERLEME_HESABI_YOKTUR() -> None:
    """🔴 `construction_progress` anahtarının neden DEĞİŞMEDİĞİNİ çakar.

    P-YT1 ölçtü: `_land_share_card.construction_progress` yer tutucusunun
    `pending_module="progress_payments"` anahtarı YAPISAL OLARAK
    KARŞILANAMAZ — kat karşılığı projesinde İŞVEREN yoktur, o modül bu değeri
    asla veremez. P-YT1 kusuru yazdı ama düzeltmedi.

    P-YT4 doğru anahtarı ARADI ve **bugün doğru bir anahtar OLMADIĞINI** ölçtü:
    işveren tarafında fiziksel ilerleme `progress_payments/service.py`de
    (`physical_numerator` → `_progress_block.physical_pct`) hesaplanır; TAŞERON
    tarafında böyle bir hesap HİÇ YOKTUR. Anahtarı "olabilecek" bir modüle
    çevirmek ölçülmüş bir olguyu tahminle değiştirmek olurdu.

    ⚠️ BU TEST KIRMIZIYA DÖNERSE: taşeron tarafına fiziksel ilerleme yazılmış
    demektir ve `projects/cards.py::_land_share_card` içindeki TUZAK A notu
    YENİDEN KARARA BAĞLANMALIDIR — artık dürüst bir anahtar VARDIR.
    """
    import pathlib

    modul = (
        pathlib.Path(__file__).resolve().parents[2]
        / "app"
        / "modules"
        / "subcontractor_progress_payments"
    )
    assert modul.is_dir(), "TH modülü taşınmış: bu bekçinin yolu güncellenmeli."
    fiziksel = {
        dosya.name: [
            satir for satir in dosya.read_text(encoding="utf-8").splitlines() if "physical" in satir
        ]
        for dosya in sorted(modul.glob("*.py"))
    }
    bulunan = {ad: satirlar for ad, satirlar in fiziksel.items() if satirlar}
    assert bulunan == {}, (
        "Taşeron tarafında fiziksel ilerleme belirmiş "
        f"({bulunan}): `_land_share_card.construction_progress` anahtarı "
        "(`progress_payments`) yeniden karara bağlanmalı."
    )
    # Karşı kutup: işveren tarafında hesap GERÇEKTEN vardır — bekçi "hiçbir yerde
    # yok" diye boş bir iddia kurmuyor, ASİMETRİYİ ölçüyor.
    isveren = (
        pathlib.Path(__file__).resolve().parents[2]
        / "app"
        / "modules"
        / "progress_payments"
        / "service.py"
    ).read_text(encoding="utf-8")
    assert "physical_numerator" in isveren
