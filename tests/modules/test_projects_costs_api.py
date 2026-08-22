"""P10 T2 — `GET /projects/{id}/costs` uç testleri.

Senaryo sayıları MOCKUP'TAN gelir (T1 test dosyasının aynı kaynakları):

* **KY** = `projedesign/Proje - Kendi Yatırım.dc.html` — 113-161 "Maliyet
  Kırılımı" kartı (119 arsa ₺8.400.000 · 127-132 inşaat harcanan/bütçe ·
  134-154 Ruhsat & Harçlar / Finansman / Pazarlama · 156-159 Toplam Harcanan) ·
  168-194 kâr projeksiyonu (169 ₺48.200.000 · 182 ₺29.800.000 · 187-188
  ₺18.400.000 / %38,2) · 212-249 taşeron maliyet tablosu (Taşeron/Sözleşme/
  Ödenen/Bekleyen + 244-248 tfoot toplamı).
* **KK** = `projedesign/Proje - Kat Karşılığı.dc.html` 104-141 — arsa ₺0
  "Kat karşılığı ✓" · 121 bizim pay ₺30,4M · 135 inşaat maliyeti ₺17,6M ·
  139-140 kâr ₺12,8M / %42,1 marj.
* **E4** = `projedesign/Ekran 4 - Projeler.dc.html` 180-181 — taahhütte
  "Sözleşme Bedeli / Harcanan".

Marj toleransı T1'deki gerekçenin aynısı: motor iki ondalık tutar, mockup bir
ondalık basar (38,17 → %38,2).
"""

import uuid
from collections.abc import Iterator
from decimal import Decimal

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import AccessLevel
from app.modules.contracts.models import SubcontractorContract, SubcontractorContractItem
from app.modules.customers.models import Customer, CustomerType
from app.modules.projects.models import Project, ProjectInvestment
from app.modules.projects.schemas import SubcontractorCostRow, SubcontractorCostSummary
from app.modules.roles.models import Module, Role, RolePermission
from app.modules.sales.models import SaleType, UnitSale, UnitSaleStatus
from app.modules.sites.models import Site
from app.modules.subcontractor_progress_payments.models import (
    SubcontractorPaymentStatus,
    SubcontractorProgressPayment,
    SubcontractorProgressPaymentLine,
)
from app.modules.units.models import Block, Unit, UnitKind, UnitOwnerSide, UnitSalesStatus
from app.modules.users.models import User, UserProjectAccess
from tests.conftest import test_engine

_TENTH = Decimal("0.1")


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _login(client, user_factory, role_key: str, *, email: str | None = None) -> str:
    address = email or f"{role_key}@p10.co"
    await user_factory(email=address, password="parola1234", role_key=role_key)
    resp = await client.post("/auth/login", json={"email": address, "password": "parola1234"})
    return resp.json()["access_token"]


async def _scoped_login(client, db_session, user_factory, project: Project | None) -> str:
    """Kapsamlı kullanıcı: yalnız verilen projeye erişir (IDOR kapısı testi)."""
    user = await user_factory(email="kapsamli@p10.co", password="parola1234", role_key="patron")
    db_session.add(
        UserProjectAccess(
            user_id=user.id,
            project_id=None if project is None else project.id,
            all_projects=False,
        )
    )
    await db_session.flush()
    resp = await client.post(
        "/auth/login", json={"email": "kapsamli@p10.co", "password": "parola1234"}
    )
    return resp.json()["access_token"]


async def _set_permission(session: AsyncSession, role_key: str, level: AccessLevel) -> None:
    role_id = (await session.execute(select(Role.id).where(Role.key == role_key))).scalar_one()
    module_id = (
        await session.execute(select(Module.id).where(Module.key == "projects"))
    ).scalar_one()
    permission = (
        await session.execute(
            select(RolePermission).where(
                RolePermission.role_id == role_id, RolePermission.module_id == module_id
            )
        )
    ).scalar_one()
    permission.access_level = level
    await session.flush()


def _set_budget_lines(project: Project, *, material="0", labor="0", sub="0", overhead="0") -> None:
    project.budget_material = Decimal(material)
    project.budget_labor = Decimal(labor)
    project.budget_subcontractor = Decimal(sub)
    project.budget_overhead = Decimal(overhead)


async def _units(session: AsyncSession, project: Project, specs: list[dict]) -> list[Unit]:
    """Blok + üniteler. Ünite `block_id` ZORUNLUDUR, blok da şantiyeye bağlıdır."""
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


async def _customer(session: AsyncSession, name: str = "Mehmet Aydın") -> Customer:
    customer = Customer(customer_type=CustomerType.person, name=name)
    session.add(customer)
    await session.flush()
    return customer


async def _sale(
    session: AsyncSession,
    unit: Unit,
    customer: Customer,
    creator: User,
    status: UnitSaleStatus,
    *,
    price: str,
) -> UnitSale:
    """Satış kaydı + ünitenin satış durumu.

    `sales_status` gerçek yolda servis senkronize eder (P8 T3); burada ORM ile
    yazıldığı için elle kurulur — "kalan stok" ölçütü bu kolondan okur.
    """
    sale = UnitSale(
        unit_id=unit.id,
        project_id=unit.project_id,
        customer_id=customer.id,
        sale_type=SaleType.sale,
        status=status,
        sale_price=Decimal(price),
        created_by=creator.id,
    )
    session.add(sale)
    if status in (UnitSaleStatus.active, UnitSaleStatus.deed_transferred):
        unit.sales_status = UnitSalesStatus.sold
    elif status is UnitSaleStatus.reservation:
        unit.sales_status = UnitSalesStatus.reserved
    await session.flush()
    return sale


async def _contract(
    session: AsyncSession,
    project: Project,
    creator: User,
    *,
    name: str,
    work_category: str | None = None,
    item_quantity: str = "1",
    item_price: str | None = "0",
    contract_no: str | None = None,
    with_item: bool = True,
) -> SubcontractorContract:
    """`with_item=False`: KALEMSİZ sözleşme — üretimde ERİŞİLEBİLİR bir durumdur
    (`SubcontractorContractCreate.items` `default_factory=list`, yani her sözleşme
    kalemleri girilmeden ÖNCE bu hâlden geçer) ve bedeli `0.00` olur."""
    contract = SubcontractorContract(
        project_id=project.id,
        subcontractor_name=name,
        work_category=work_category,
        contract_no=contract_no,
        created_by=creator.id,
    )
    session.add(contract)
    await session.flush()
    if not with_item:
        return contract
    session.add(
        SubcontractorContractItem(
            contract_id=contract.id,
            code="A.001",
            description="Kalem",
            unit="m2",
            quantity=Decimal(item_quantity),
            unit_price=None if item_price is None else Decimal(item_price),
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
    rejected: bool = False,
) -> SubcontractorProgressPayment:
    payment = SubcontractorProgressPayment(
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
    if rejected:
        # "Revize Gerekli" BEŞİNCİ bir durum değildir: `draft` + `rejected_at`.
        payment.rejected_at = payment.created_at
    session.add(payment)
    await session.flush()
    return payment


# --- KY senaryosu (kendi yatırım) ---


async def test_ky_maliyet_kirilimi_ve_kar_projeksiyonu_mockupi_birebir_verir(
    client, db_session, user_factory, project_factory
):
    """KY 113-194: arsa 8,4M · inşaat bütçesi 21,4M · 48,2M − 29,8M = 18,4M · %38,2."""
    kurucu = await user_factory(email="kurucu@p10.co", password="parola1234", role_key="patron")
    project = await project_factory(code="KY-1", project_type="kendi_yatirim")
    _set_budget_lines(
        project, material="8000000", labor="5000000", sub="7000000", overhead="1400000"
    )
    db_session.add(
        ProjectInvestment(
            project_id=project.id,
            land_cost=Decimal("8400000.00"),
            # S4: satış hedefi kolonu hesapta KULLANILMAZ — çeliştirilmediği burada kanıtlanır.
            sales_target=Decimal("1.00"),
        )
    )
    await db_session.flush()
    await _units(
        db_session,
        project,
        [
            {"list_price": Decimal("24100000.00"), "gross_area_m2": Decimal("100.00")},
            {"list_price": Decimal("24100000.00"), "gross_area_m2": Decimal("100.00")},
        ],
    )
    contract = await _contract(
        db_session, project, kurucu, name="Akın İnşaat", work_category="Betonarme"
    )
    await _payment(db_session, contract, kurucu, SubcontractorPaymentStatus.paid, quantity="5700")
    await _payment(
        db_session,
        contract,
        kurucu,
        SubcontractorPaymentStatus.approved,
        quantity="840",
        sequence_no=2,
    )
    token = await _login(client, user_factory, "system_admin")

    resp = await client.get(f"/projects/{project.id}/costs", headers=_auth(token))

    assert resp.status_code == 200
    body = resp.json()
    breakdown = body["breakdown"]
    assert Decimal(breakdown["land_cost"]) == Decimal("8400000.00")
    assert Decimal(breakdown["construction_budget"]) == Decimal("21400000.00")
    assert Decimal(breakdown["construction_spent"]) == Decimal("6540000.00")
    # KY 156-159 "Toplam Harcanan" = BİLİNEN kalemler (arsa + inşaat).
    assert Decimal(breakdown["total_spent"]) == Decimal("14940000.00")
    profit = body["profit"]
    assert Decimal(profit["revenue"]) == Decimal("48200000.00")
    assert Decimal(profit["cost"]) == Decimal("29800000.00")
    assert Decimal(profit["profit"]) == Decimal("18400000.00")
    assert Decimal(profit["margin_pct"]).quantize(_TENTH) == Decimal("38.2")


async def test_gerceklesen_satis_ve_kalan_stok_KY_iki_satirini_verir(
    client, db_session, user_factory, project_factory
):
    """KY 173-180 (kullanıcı kararı 2026-08-09): "Gerçekleşen Satış" satış
    BEDELLERİNİN, "Kalan Stok Değeri" satılmamış ünitelerin LİSTE fiyatlarının
    toplamıdır."""
    kurucu = await user_factory(email="stok@p10.co", password="parola1234", role_key="patron")
    project = await project_factory(code="ST-1", project_type="kendi_yatirim")
    uniteler = await _units(
        db_session,
        project,
        [
            {"list_price": Decimal("20000000.00")},
            {"list_price": Decimal("11420000.00")},
            {"list_price": Decimal("9000000.00")},
            {"list_price": Decimal("7780000.00")},
        ],
    )
    musteri = await _customer(db_session)
    await _sale(
        db_session, uniteler[0], musteri, kurucu, UnitSaleStatus.active, price="20000000.00"
    )
    await _sale(
        db_session,
        uniteler[1],
        musteri,
        kurucu,
        UnitSaleStatus.deed_transferred,
        price="11420000.00",
    )
    token = await _login(client, user_factory, "system_admin")

    body = (await client.get(f"/projects/{project.id}/costs", headers=_auth(token))).json()

    profit = body["profit"]
    assert Decimal(profit["realized_sales"]) == Decimal("31420000.00")
    assert Decimal(profit["remaining_stock_value"]) == Decimal("16780000.00")
    # Gelir (KY 169) LİSTE fiyatları toplamıdır ve iki yeni satırdan BAĞIMSIZDIR.
    assert Decimal(profit["revenue"]) == Decimal("48200000.00")


async def test_iptal_ve_rezerve_satis_gerceklesen_satisa_girmez(
    client, db_session, user_factory, project_factory
):
    """Ölçüt `sales.summary._SOLD_STATUSES`: rezervasyon ciro DEĞİLDİR, iptal
    edilmiş satış ise hiç sayılmaz."""
    kurucu = await user_factory(email="iptal@p10.co", password="parola1234", role_key="patron")
    project = await project_factory(code="ST-2", project_type="kendi_yatirim")
    uniteler = await _units(
        db_session,
        project,
        [
            {"list_price": Decimal("5000000.00")},
            {"list_price": Decimal("4000000.00")},
            {"list_price": Decimal("3000000.00")},
        ],
    )
    musteri = await _customer(db_session)
    await _sale(db_session, uniteler[0], musteri, kurucu, UnitSaleStatus.active, price="5000000.00")
    await _sale(
        db_session, uniteler[1], musteri, kurucu, UnitSaleStatus.reservation, price="4000000.00"
    )
    await _sale(
        db_session, uniteler[2], musteri, kurucu, UnitSaleStatus.cancelled, price="3000000.00"
    )
    token = await _login(client, user_factory, "system_admin")

    profit = (await client.get(f"/projects/{project.id}/costs", headers=_auth(token))).json()[
        "profit"
    ]

    assert Decimal(profit["realized_sales"]) == Decimal("5000000.00")
    # Rezerve ünite "boş" DEĞİLDİR; iptal edilen satışın ünitesi stokta KALIR.
    assert Decimal(profit["remaining_stock_value"]) == Decimal("3000000.00")


async def test_taahhutte_gerceklesen_satis_ve_kalan_stok_YOKTUR(
    client, db_session, user_factory, project_factory
):
    """Taahhütte ünite/satış KAVRAMI yok (`_UNIT_REVENUE_TYPES` süzgeci) — iki
    alan `None` döner, 0 basmak "hiç satılmadı" yalanı olurdu."""
    project = await project_factory(
        code="ST-3", project_type="taahhut", contract_amount="10000000.00"
    )
    token = await _login(client, user_factory, "system_admin")

    profit = (await client.get(f"/projects/{project.id}/costs", headers=_auth(token))).json()[
        "profit"
    ]

    assert profit["realized_sales"] is None
    assert profit["remaining_stock_value"] is None


async def test_bekleyen_uc_kalem_zarf_icinde_doner_uydurma_sifir_basmaz(
    client, db_session, user_factory, project_factory
):
    """KY 134-154: Ruhsat & Harçlar · Finansman · Pazarlama kaynağı YOK → pending."""
    project = await project_factory(code="KY-2", project_type="kendi_yatirim")
    token = await _login(client, user_factory, "system_admin")

    body = (await client.get(f"/projects/{project.id}/costs", headers=_auth(token))).json()

    for key in ("permits", "financing", "marketing"):
        kalem = body["breakdown"][key]
        assert kalem["available"] is False, key
        assert kalem["value"] is None, key
        assert kalem["pending_module"], key


# --- KK senaryosu (kat karşılığı) ---


async def test_kk_kar_projeksiyonu_mockupi_birebir_verir(
    client, db_session, user_factory, project_factory
):
    """KK 104-141: arsa ₺0 · inşaat 17,6M · bizim pay 30,4M → 12,8M / %42,1."""
    project = await project_factory(code="KK-1", project_type="kat_karsiligi")
    _set_budget_lines(project, material="17600000")
    await db_session.flush()
    await _units(
        db_session,
        project,
        [
            {
                "appraisal_value": Decimal("30400000.00"),
                "owner_side": UnitOwnerSide.contractor,
            },
            # Arsa sahibinin ünitesi BİZİM PAY değerine girmez.
            {
                "appraisal_value": Decimal("25000000.00"),
                "owner_side": UnitOwnerSide.landowner,
            },
        ],
    )
    token = await _login(client, user_factory, "system_admin")

    body = (await client.get(f"/projects/{project.id}/costs", headers=_auth(token))).json()

    assert Decimal(body["breakdown"]["land_cost"]) == Decimal("0")
    assert Decimal(body["breakdown"]["construction_budget"]) == Decimal("17600000.00")
    profit = body["profit"]
    assert Decimal(profit["revenue"]) == Decimal("30400000.00")
    assert Decimal(profit["cost"]) == Decimal("17600000.00")
    assert Decimal(profit["profit"]) == Decimal("12800000.00")
    assert Decimal(profit["margin_pct"]).quantize(_TENTH) == Decimal("42.1")


async def test_taahhutte_arsa_maliyeti_none_ve_kar_sozlesme_eksi_harcanandir(
    client, db_session, user_factory, project_factory
):
    """E4 180-181: taahhütte arsa KAVRAMI yok (0 basmak "bedava arsa" yalanı olurdu)."""
    kurucu = await user_factory(email="taahhut@p10.co", password="parola1234", role_key="patron")
    project = await project_factory(
        code="TA-1", project_type="taahhut", contract_amount="10000000.00"
    )
    contract = await _contract(db_session, project, kurucu, name="Akın İnşaat")
    await _payment(db_session, contract, kurucu, SubcontractorPaymentStatus.paid, quantity="4000")
    token = await _login(client, user_factory, "system_admin")

    body = (await client.get(f"/projects/{project.id}/costs", headers=_auth(token))).json()

    assert body["breakdown"]["land_cost"] is None
    assert Decimal(body["breakdown"]["construction_spent"]) == Decimal("4000000.00")
    assert Decimal(body["profit"]["revenue"]) == Decimal("10000000.00")
    assert Decimal(body["profit"]["profit"]) == Decimal("6000000.00")


# --- Durum süzgeci ---


async def test_taslak_onay_bekleyen_ve_reddedilmis_hakedis_maliyete_girmez(
    client, db_session, user_factory, project_factory
):
    """S1 süzgeci: yalnız `approved`+`paid`. Reddedilmiş taslak da SIZMAZ."""
    kurucu = await user_factory(email="suzgec@p10.co", password="parola1234", role_key="patron")
    project = await project_factory(code="SZ-1", project_type="taahhut")
    contract = await _contract(db_session, project, kurucu, name="Akın İnşaat")
    await _payment(db_session, contract, kurucu, SubcontractorPaymentStatus.paid, quantity="100")
    await _payment(
        db_session,
        contract,
        kurucu,
        SubcontractorPaymentStatus.draft,
        quantity="9000",
        sequence_no=2,
    )
    await _payment(
        db_session,
        contract,
        kurucu,
        SubcontractorPaymentStatus.pending_approval,
        quantity="8000",
        sequence_no=3,
    )
    await _payment(
        db_session,
        contract,
        kurucu,
        SubcontractorPaymentStatus.draft,
        quantity="7000",
        sequence_no=4,
        rejected=True,
    )
    token = await _login(client, user_factory, "system_admin")

    body = (await client.get(f"/projects/{project.id}/costs", headers=_auth(token))).json()

    assert Decimal(body["breakdown"]["construction_spent"]) == Decimal("100000.00")
    assert Decimal(body["subcontractor_total"]["paid"]) == Decimal("100000.00")
    assert Decimal(body["subcontractor_total"]["pending"]) == Decimal("0.00")


# --- Taşeron maliyet tablosu (KY 212-249) ---


async def test_taseron_tablosu_toplami_satirlarin_toplamina_esittir(
    client, db_session, user_factory, project_factory
):
    """KY 244-248 tfoot: toplam satırı satırların toplamıdır — iki farklı kaynak YOK.

    Hakedişsiz sözleşme de satır açar (KY 236-243 "Demirci Alüminyum ₺0/₺0").
    """
    kurucu = await user_factory(email="tablo@p10.co", password="parola1234", role_key="patron")
    project = await project_factory(code="TS-1", project_type="taahhut")
    akin = await _contract(
        db_session,
        project,
        kurucu,
        name="Akın İnşaat",
        work_category="Betonarme",
        item_quantity="8400",
        item_price="1000",
    )
    yilmaz = await _contract(
        db_session,
        project,
        kurucu,
        name="Yılmaz Elektrik",
        work_category="Elektrik",
        item_quantity="2400",
        item_price="1000",
    )
    await _contract(
        db_session,
        project,
        kurucu,
        name="Demirci Alüminyum",
        work_category="Doğrama",
        item_quantity="1800",
        item_price="1000",
    )
    await _payment(db_session, akin, kurucu, SubcontractorPaymentStatus.paid, quantity="5700")
    await _payment(
        db_session, akin, kurucu, SubcontractorPaymentStatus.approved, quantity="840", sequence_no=2
    )
    await _payment(db_session, yilmaz, kurucu, SubcontractorPaymentStatus.paid, quantity="1200")
    token = await _login(client, user_factory, "system_admin")

    body = (await client.get(f"/projects/{project.id}/costs", headers=_auth(token))).json()

    rows = body["subcontractors"]
    assert [row["subcontractor_name"] for row in rows] == [
        "Akın İnşaat",
        "Demirci Alüminyum",
        "Yılmaz Elektrik",
    ]
    by_name = {row["subcontractor_name"]: row for row in rows}
    assert Decimal(by_name["Akın İnşaat"]["contract_amount"]) == Decimal("8400000.00")
    assert Decimal(by_name["Akın İnşaat"]["paid"]) == Decimal("5700000.00")
    assert Decimal(by_name["Akın İnşaat"]["pending"]) == Decimal("840000.00")
    assert by_name["Akın İnşaat"]["work_category"] == "Betonarme"
    # Satır kimliği geri getirilebilir olmalı (mockup "İş Kalemi" sütunu sözleşme düzeyi).
    assert by_name["Akın İnşaat"]["contract_id"] == str(akin.id)
    assert Decimal(by_name["Demirci Alüminyum"]["paid"]) == Decimal("0.00")
    total = body["subcontractor_total"]
    for alan in ("contract_amount", "paid", "pending"):
        assert Decimal(total[alan]) == sum(Decimal(row[alan]) for row in rows), alan
    # İnşaat harcanan tablonun ödenen+bekleyeni ile AYNI kaynaktan gelir.
    assert Decimal(body["breakdown"]["construction_spent"]) == Decimal(total["paid"]) + Decimal(
        total["pending"]
    )


async def test_ayni_taseronun_iki_sozlesmesi_AYRI_satir_acar(
    client, db_session, user_factory, project_factory
):
    """Satır birimi SÖZLEŞMEDİR (KY 205-249): satırdaki "İş Kalemi" metni sözleşme
    düzeyi bir kavramdır, iki iş kapsamı tek satıra EZİLEMEZ.

    Toplam yine satırların toplamıdır — satır birimi değişti, tfoot DEĞİŞMEDİ.
    """
    kurucu = await user_factory(email="ikili@p10.co", password="parola1234", role_key="patron")
    project = await project_factory(code="TS-2", project_type="taahhut")
    birinci = await _contract(
        db_session,
        project,
        kurucu,
        name="Akın İnşaat",
        work_category="Betonarme",
        item_quantity="1000",
        item_price="1000",
        contract_no="TS-2-01",
    )
    ikinci = await _contract(
        db_session,
        project,
        kurucu,
        name="Akın İnşaat",
        work_category="Doğrama",
        item_quantity="500",
        item_price="1000",
        contract_no="TS-2-02",
    )
    await _payment(db_session, birinci, kurucu, SubcontractorPaymentStatus.paid, quantity="300")
    token = await _login(client, user_factory, "system_admin")

    body = (await client.get(f"/projects/{project.id}/costs", headers=_auth(token))).json()

    rows = body["subcontractors"]
    assert [row["contract_id"] for row in rows] == [str(birinci.id), str(ikinci.id)]
    assert [row["contract_no"] for row in rows] == ["TS-2-01", "TS-2-02"]
    # Kategori artık SÖZLEŞMEDEN gelir: "ayrışırsa None" kuralı KALDIRILDI.
    assert [row["work_category"] for row in rows] == ["Betonarme", "Doğrama"]
    assert [Decimal(row["contract_amount"]) for row in rows] == [
        Decimal("1000000.00"),
        Decimal("500000.00"),
    ]
    assert [Decimal(row["paid"]) for row in rows] == [Decimal("300000.00"), Decimal("0.00")]
    total = body["subcontractor_total"]
    for alan in ("contract_amount", "paid", "pending"):
        assert Decimal(total[alan]) == sum(Decimal(row[alan]) for row in rows), alan
    assert Decimal(body["breakdown"]["construction_spent"]) == Decimal("300000.00")


async def test_kategorisiz_sozlesmenin_is_kalemi_sutunu_BOS_doner(
    client, db_session, user_factory, project_factory
):
    """Kullanıcı kararı 2026-08-09: mockup'ın "İş Kalemi" sütunu `work_category`
    ile beslenir; YENİ KOLON AÇILMAZ. Taslak sözleşmede kategori NULL olabilir ve
    bu MEŞRUDUR — satır yine açılır, sütun boş basılır (uydurma metin YOK).
    """
    kurucu = await user_factory(
        email="kategorisiz@p10.co", password="parola1234", role_key="patron"
    )
    project = await project_factory(code="TS-4", project_type="taahhut")
    taslak = await _contract(
        db_session, project, kurucu, name="Akın İnşaat", item_quantity="100", item_price="1000"
    )
    await _contract(
        db_session,
        project,
        kurucu,
        name="Yılmaz Elektrik",
        work_category="Elektrik",
        item_quantity="50",
        item_price="1000",
    )
    token = await _login(client, user_factory, "system_admin")

    body = (await client.get(f"/projects/{project.id}/costs", headers=_auth(token))).json()

    rows = {row["subcontractor_name"]: row for row in body["subcontractors"]}
    assert rows["Akın İnşaat"]["work_category"] is None
    assert rows["Akın İnşaat"]["contract_id"] == str(taslak.id)
    assert Decimal(rows["Akın İnşaat"]["contract_amount"]) == Decimal("100000.00")
    assert rows["Yılmaz Elektrik"]["work_category"] == "Elektrik"


async def test_sozlesme_nosuz_satirlar_da_deterministik_siralanir(
    client, db_session, user_factory, project_factory
):
    """Taslak sözleşmenin `contract_no`su NULL'dur; sıralama yine kararlı olmalı
    (ad → `contract_no` → `contract_id`), aksi hâlde tablo her istekte oynar."""
    kurucu = await user_factory(email="sirali@p10.co", password="parola1234", role_key="patron")
    project = await project_factory(code="TS-3", project_type="taahhut")
    for _ in range(3):
        await _contract(
            db_session, project, kurucu, name="Akın İnşaat", item_quantity="1", item_price="1000"
        )
    token = await _login(client, user_factory, "system_admin")

    birinci = (await client.get(f"/projects/{project.id}/costs", headers=_auth(token))).json()
    ikinci = (await client.get(f"/projects/{project.id}/costs", headers=_auth(token))).json()

    kimlikler = [row["contract_id"] for row in birinci["subcontractors"]]
    assert len(kimlikler) == 3
    assert kimlikler == sorted(kimlikler)
    assert kimlikler == [row["contract_id"] for row in ikinci["subcontractors"]]


# --- İlerleme sütunu (KY 214/222/230 · KK 217/223/229) ---


async def test_ilerleme_ODENEN_bolu_SOZLESME_yuzdesidir(
    client, db_session, user_factory, project_factory
):
    """ "İlerleme" sütunu = `Ödenen / Sözleşme × 100`, iki ondalık.

    Beklenen değerler ELDE hesaplandı; üretim ifadesi testte YENİDEN
    KOŞTURULMADI (aksi hâlde test formülü değil kendini doğrulardı):

    * 5.700.000 / 8.400.000 × 100 = 67,857142… → **67.86** (KY 214'ün `%68`
      bar genişliğinin iki haneli hâli; yuvarlama ISIRIR).
    * 1.200.000 / 2.400.000 × 100 = 50 TAM → **50.00** (KY 222 `%50`).
    * 24.690 / 200.000 × 100 = 12,345 → TAM YARIM, yuvarlama MODUNU ayırt eder:
      `quantize2` ROUND_HALF_UP'tır ve **12.35** verir; ROUND_HALF_EVEN olsaydı
      12.34 gelirdi (4 çift olduğu için aşağı yuvarlardı).
    """
    kurucu = await user_factory(email="ilerleme@p10.co", password="parola1234", role_key="patron")
    project = await project_factory(code="IL-1", project_type="taahhut")
    akin = await _contract(
        db_session,
        project,
        kurucu,
        name="Akın İnşaat",
        work_category="Betonarme",
        item_quantity="8400",
        item_price="1000",
    )
    yilmaz = await _contract(
        db_session,
        project,
        kurucu,
        name="Yılmaz Elektrik",
        work_category="Elektrik",
        item_quantity="2400",
        item_price="1000",
    )
    yarim = await _contract(
        db_session,
        project,
        kurucu,
        name="Zeta Yuvarlama",
        work_category="Mekanik",
        item_quantity="200",
        item_price="1000",
    )
    await _payment(db_session, akin, kurucu, SubcontractorPaymentStatus.paid, quantity="5700")
    await _payment(db_session, yilmaz, kurucu, SubcontractorPaymentStatus.paid, quantity="1200")
    await _payment(db_session, yarim, kurucu, SubcontractorPaymentStatus.paid, quantity="24.69")
    token = await _login(client, user_factory, "system_admin")

    body = (await client.get(f"/projects/{project.id}/costs", headers=_auth(token))).json()

    rows = {row["subcontractor_name"]: row for row in body["subcontractors"]}
    # Payda/pay gerçekten kurulmuş mu — oran doğru çıksın diye önce girdiler ölçülür.
    assert Decimal(rows["Akın İnşaat"]["contract_amount"]) == Decimal("8400000.00")
    assert Decimal(rows["Akın İnşaat"]["paid"]) == Decimal("5700000.00")
    assert Decimal(rows["Akın İnşaat"]["progress_pct"]) == Decimal("67.86")
    assert Decimal(rows["Yılmaz Elektrik"]["progress_pct"]) == Decimal("50.00")
    assert Decimal(rows["Zeta Yuvarlama"]["contract_amount"]) == Decimal("200000.00")
    assert Decimal(rows["Zeta Yuvarlama"]["paid"]) == Decimal("24690.00")
    assert Decimal(rows["Zeta Yuvarlama"]["progress_pct"]) == Decimal("12.35")


async def test_ilerleme_GERCEK_SIFIRI_TANIMSIZDAN_ayirir(
    client, db_session, user_factory, project_factory
):
    """İki "sıfır görünümlü" durum AYNI DEĞERE ÇÖKMEZ (NULL-EŞİK kanonu):

    * bedeli olan ama hiç ödeme görmemiş sözleşme → `0.00` = GERÇEK %0. Mockup
      bunu harfiyen basar (KY 236-243 "Demirci Alüminyum ₺1,8M / ₺0" → `%0`).
    * bedeli `0.00` olan sözleşme → payda TANIMSIZ → `None`. Uydurma bir %0
      basmak "veri yok"u "ilerleme yok" gibi gösterirdi; kullanıcı ekranda
      taşeronun hiç çalışmadığını sanardı. Bu hâl üretimde ERİŞİLEBİLİRDİR ve
      MEŞRUDUR: kalemsiz sözleşme (`items` `default_factory=list`) ile bütün
      kalemlerinin `unit_price`ı NULL olan sözleşme aynı `0.00` bedeli üretir.
    """
    kurucu = await user_factory(email="sifir@p10.co", password="parola1234", role_key="patron")
    project = await project_factory(code="IL-2", project_type="taahhut")
    await _contract(
        db_session,
        project,
        kurucu,
        name="Demirci Alüminyum",
        work_category="Doğrama",
        item_quantity="1800",
        item_price="1000",
    )
    await _contract(db_session, project, kurucu, name="Kalemsiz Ltd", with_item=False)
    await _contract(db_session, project, kurucu, name="Fiyatsiz Ltd", item_price=None)
    token = await _login(client, user_factory, "system_admin")

    body = (await client.get(f"/projects/{project.id}/costs", headers=_auth(token))).json()

    rows = {row["subcontractor_name"]: row for row in body["subcontractors"]}
    gercek_sifir = rows["Demirci Alüminyum"]
    assert Decimal(gercek_sifir["contract_amount"]) == Decimal("1800000.00")
    assert Decimal(gercek_sifir["paid"]) == Decimal("0.00")
    assert Decimal(gercek_sifir["progress_pct"]) == Decimal("0.00")
    for tanimsiz_ad in ("Kalemsiz Ltd", "Fiyatsiz Ltd"):
        tanimsiz = rows[tanimsiz_ad]
        assert Decimal(tanimsiz["contract_amount"]) == Decimal("0.00"), tanimsiz_ad
        assert tanimsiz["progress_pct"] is None, tanimsiz_ad
    # AYRIŞMA: ikisi tek değere çökerse test anlamsızlaşır.
    assert gercek_sifir["progress_pct"] != rows["Kalemsiz Ltd"]["progress_pct"]


async def test_ilerleme_payi_ODENENDIR_BEKLEYEN_paya_GIRMEZ(
    client, db_session, user_factory, project_factory
):
    """AYRIŞMA NOKTASI: `Ödenen / Sözleşme` ile `(Ödenen + Bekleyen) / Sözleşme`
    burada FARKLI cevap verir; bekleyeni 0 olan bir kurulumda test hiçbir şey
    kanıtlamazdı.

    Ölçüm (KY tablosu, iki bağımsız mockup 6/6 satırda aynı formülde buluşuyor):
    5,7/8,4 = %68 basılır, (5,7+0,84)/8,4 = %77,9 basılmaz. Burada da
    5.000.000 / 10.000.000 = **%50.00** beklenir, 8.000.000 / 10.000.000 = %80.00
    DEĞİL.
    """
    kurucu = await user_factory(email="ayrisma@p10.co", password="parola1234", role_key="patron")
    project = await project_factory(code="IL-3", project_type="taahhut")
    akin = await _contract(
        db_session,
        project,
        kurucu,
        name="Akın İnşaat",
        work_category="Betonarme",
        item_quantity="10000",
        item_price="1000",
    )
    await _payment(db_session, akin, kurucu, SubcontractorPaymentStatus.paid, quantity="5000")
    await _payment(
        db_session,
        akin,
        kurucu,
        SubcontractorPaymentStatus.approved,
        quantity="3000",
        sequence_no=2,
    )
    token = await _login(client, user_factory, "system_admin")

    body = (await client.get(f"/projects/{project.id}/costs", headers=_auth(token))).json()

    (row,) = body["subcontractors"]
    assert Decimal(row["contract_amount"]) == Decimal("10000000.00")
    assert Decimal(row["paid"]) == Decimal("5000000.00")
    # Bekleyen GERÇEKTEN doludur: iki formülü ayıran şey budur.
    assert Decimal(row["pending"]) == Decimal("3000000.00")
    assert Decimal(row["progress_pct"]) == Decimal("50.00")
    assert Decimal(row["progress_pct"]) != Decimal("80.00")


def test_tfoot_ILERLEME_TASIMAZ_satir_TASIR():
    """KY 244-248 tfoot'unun "İlerleme" hücresi HARFİYEN BOŞTUR (`<td></td>`),
    KK tablosunun ise tfoot'u hiç yoktur.

    Toplam bir ilerleme yüzdesi eklemek mockup'ın İSTEMEDİĞİ bir sayıyı icat
    etmek olurdu (üstelik "hangi ortalama" sorusunun cevabı da yoktur: satır
    ortalaması ile Σödenen/Σbedel farklı sayılardır). Sütun SATIR düzeyinde
    yaşar, tfoot'ta yaşamaz.
    """
    assert "progress_pct" in SubcontractorCostRow.model_fields
    assert "progress_pct" not in SubcontractorCostSummary.model_fields
    assert set(SubcontractorCostSummary.model_fields) == {"contract_amount", "paid", "pending"}


# --- Yetki ve IDOR ---


async def test_costs_izinsiz_role_403_doner(client, user_factory, project_factory):
    """seed: `procurement` satırında projects = none."""
    project = await project_factory(code="YT-1")
    token = await _login(client, user_factory, "procurement")

    resp = await client.get(f"/projects/{project.id}/costs", headers=_auth(token))

    assert resp.status_code == 403


async def test_costs_kimliksiz_401_doner(client, project_factory):
    project = await project_factory(code="YT-2")
    assert (await client.get(f"/projects/{project.id}/costs")).status_code == 401


async def test_costs_gorunmeyen_proje_var_olmayandan_ayirt_edilemez(
    client, db_session, user_factory, project_factory
):
    """IDOR: kapsam dışı proje ile hiç var olmayan proje AYNI 404 gövdesini verir."""
    izinli = await project_factory(code="ID-1")
    gizli = await project_factory(code="ID-2")
    token = await _scoped_login(client, db_session, user_factory, izinli)

    gizli_resp = await client.get(f"/projects/{gizli.id}/costs", headers=_auth(token))
    yok_resp = await client.get(f"/projects/{uuid.uuid4()}/costs", headers=_auth(token))

    assert gizli_resp.status_code == 404
    assert yok_resp.status_code == 404
    assert gizli_resp.json() == yok_resp.json()
    assert (
        await client.get(f"/projects/{izinli.id}/costs", headers=_auth(token))
    ).status_code == 200


async def test_costs_view_seviyesi_yeterlidir(client, db_session, user_factory, project_factory):
    """Uç OKUMADIR: `projects:view` yeter, `full` şart değildir."""
    project = await project_factory(code="VW-1")
    await _set_permission(db_session, "site_chief", AccessLevel.view)
    user = await user_factory(email="sef@p10.co", password="parola1234", role_key="site_chief")
    db_session.add(UserProjectAccess(user_id=user.id, project_id=project.id, all_projects=False))
    await db_session.flush()
    login = await client.post("/auth/login", json={"email": "sef@p10.co", "password": "parola1234"})
    token = login.json()["access_token"]

    resp = await client.get(f"/projects/{project.id}/costs", headers=_auth(token))

    assert resp.status_code == 200


# --- N+1 ölçümü ---


@pytest.fixture
def _sorgu_sayaci() -> Iterator[list[str]]:
    """T1 desenin aynısı: N+1 iddiası tahmine değil ÖLÇÜME dayanır."""
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


_OLCULEN_TABLOLAR = (
    "subcontractor_contracts",
    "subcontractor_contract_items",
    "subcontractor_progress_payments",
    "subcontractor_progress_payment_lines",
    "units",
    # Kullanıcı kararı 2026-08-09: "Gerçekleşen Satış" satış kayıtlarından gelir —
    # satış SAYISI sorgu sayısını BÜYÜTMEMELİDİR.
    "unit_sales",
)


async def test_sorgu_sayisi_taseron_ve_hakedis_sayisindan_bagimsizdir(
    db_session, user_factory, project_factory, _sorgu_sayaci: list[str]
):
    """Spec §4: tek gidiş-dönüş hedefi — satır sayısı sorgu sayısını BÜYÜTMEZ."""
    from app.modules.projects import cost_summary

    kurucu = await user_factory(email="olcum@p10.co", password="parola1234", role_key="patron")
    kucuk = await project_factory(code="NP-1", project_type="kendi_yatirim")
    buyuk = await project_factory(code="NP-2", project_type="kendi_yatirim")
    musteri = await _customer(db_session, name="Ölçüm Müşterisi")
    tek = await _contract(
        db_session, kucuk, kurucu, name="Tek Taşeron", item_quantity="10", item_price="1000"
    )
    await _payment(db_session, tek, kurucu, SubcontractorPaymentStatus.paid, quantity="5")
    kucuk_uniteler = await _units(db_session, kucuk, [{"list_price": Decimal("1000.00")}])
    await _sale(
        db_session, kucuk_uniteler[0], musteri, kurucu, UnitSaleStatus.active, price="1000.00"
    )
    for index in range(4):
        contract = await _contract(
            db_session,
            buyuk,
            kurucu,
            name=f"Taşeron {index}",
            item_quantity="10",
            item_price="1000",
        )
        for sira in (1, 2):
            await _payment(
                db_session,
                contract,
                kurucu,
                SubcontractorPaymentStatus.paid,
                quantity="5",
                sequence_no=sira,
            )
    buyuk_uniteler = await _units(
        db_session, buyuk, [{"list_price": Decimal("1000.00")} for _ in range(6)]
    )
    # Küçük projede 1, büyükte 5 satış: satış sayısı sorgu sayısını BÜYÜTMEMELİ.
    for unite in buyuk_uniteler[:5]:
        await _sale(db_session, unite, musteri, kurucu, UnitSaleStatus.active, price="1000.00")
    # `investment` `lazy="selectin"`tir: gerçek yolda sorgu ile YÜKLENMİŞ gelir
    # (uç `visible_projects`ten okur). Testte elle açılan nesnede yükleme
    # tetiklenmediği için tazelenir — ölçüm öncesi, sayaç dışında.
    for proje in (kucuk, buyuk):
        await db_session.refresh(proje, attribute_names=["investment"])

    _sorgu_sayaci.clear()
    await cost_summary.build_project_costs(db_session, kucuk)
    kucuk_sayim = {tablo: _tablo_sayimi(_sorgu_sayaci, tablo) for tablo in _OLCULEN_TABLOLAR}

    _sorgu_sayaci.clear()
    buyuk_yanit = await cost_summary.build_project_costs(db_session, buyuk)
    buyuk_sayim = {tablo: _tablo_sayimi(_sorgu_sayaci, tablo) for tablo in _OLCULEN_TABLOLAR}

    assert len(buyuk_yanit.subcontractors) == 4
    assert kucuk_sayim == buyuk_sayim, (kucuk_sayim, buyuk_sayim)
    assert all(sayi == 1 for sayi in buyuk_sayim.values()), buyuk_sayim


async def test_taahhutte_unite_ve_satis_tablolarina_HIC_dokunulmaz(
    db_session, user_factory, project_factory, _sorgu_sayaci: list[str]
):
    """Tip süzgeci (`_UNIT_REVENUE_TYPES`): taahhütte gelir sözleşme bedelidir —
    ne ünite ne satış tablosu OKUNUR."""
    from app.modules.projects import cost_summary

    project = await project_factory(
        code="NP-3", project_type="taahhut", contract_amount="1000000.00"
    )
    await db_session.flush()

    _sorgu_sayaci.clear()
    await cost_summary.build_project_costs(db_session, project)

    assert _tablo_sayimi(_sorgu_sayaci, "units") == 0
    assert _tablo_sayimi(_sorgu_sayaci, "unit_sales") == 0


# --- Mutasyon denetimi ---


async def test_yanit_uretimi_projeyi_ve_uniteleri_degistirmez(
    db_session, user_factory, project_factory
):
    """Okuma ucu MUTASYON YAPMAZ: iki çağrı aynı sonucu verir, ORM alanları sabit kalır."""
    from app.modules.projects import cost_summary

    kurucu = await user_factory(email="mutasyon@p10.co", password="parola1234", role_key="patron")
    project = await project_factory(code="MT-1", project_type="kendi_yatirim")
    _set_budget_lines(project, material="1000000")
    await db_session.flush()
    uniteler = await _units(
        db_session, project, [{"list_price": Decimal("2000000.00"), "gross_area_m2": Decimal("50")}]
    )
    contract = await _contract(db_session, project, kurucu, name="Akın İnşaat")
    await _payment(db_session, contract, kurucu, SubcontractorPaymentStatus.paid, quantity="10")
    await db_session.refresh(project, attribute_names=["investment"])

    birinci = await cost_summary.build_project_costs(db_session, project)
    ikinci = await cost_summary.build_project_costs(db_session, project)

    assert birinci == ikinci
    assert project.budget_material == Decimal("1000000")
    assert uniteler[0].list_price == Decimal("2000000.00")
    # Yanıt şeması dondurulmuş değil ama ÜRETİM saf olmalı: aynı girdi aynı çıktı.
    assert birinci.breakdown.construction_spent == Decimal("10000.00")
