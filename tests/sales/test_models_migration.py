"""P8 T1 — customers / unit_sales / sale_installments modelleri ve kisitlari (spec §2).

Router/servis YOKTUR (T2-T5'in isi); burada yalniz SEMA dogrulanir: enum kumeleri,
kismi benzersiz indeksler, FK silme davranislari ve CHECK'ler.
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError

from app.modules.customers.models import Customer, CustomerType
from app.modules.projects.models import Project
from app.modules.sales.models import (
    DeedCondition,
    InstallmentPaymentMethod,
    PaymentPlanType,
    SaleInstallment,
    SaleType,
    UnitSale,
    UnitSaleStatus,
)
from app.modules.sites.models import Site
from app.modules.units.models import Block, Unit, UnitKind
from app.modules.users.models import User


async def _unit(session, project: Project, unit_no: str = "1") -> Unit:
    site = Site(project_id=project.id, code=f"SNT-{unit_no}-{uuid.uuid4().hex[:6]}", name="Merkez")
    session.add(site)
    await session.flush()
    block = Block(project_id=project.id, site_id=site.id, name=f"Blok {unit_no}")
    session.add(block)
    await session.flush()
    unit = Unit(
        project_id=project.id, block_id=block.id, unit_no=unit_no, unit_kind=UnitKind.apartment
    )
    session.add(unit)
    await session.flush()
    return unit


async def _customer(session, **kwargs) -> Customer:
    defaults: dict = {"customer_type": CustomerType.person, "name": "Ahmet Yilmaz"}
    defaults.update(kwargs)
    customer = Customer(**defaults)
    session.add(customer)
    await session.flush()
    return customer


def _sale(unit: Unit, customer: Customer, user: User, **kwargs) -> UnitSale:
    defaults: dict = {
        "sale_type": SaleType.sale,
        "status": UnitSaleStatus.active,
        "sale_price": Decimal("1440000.00"),
    }
    defaults.update(kwargs)
    return UnitSale(
        unit_id=unit.id,
        project_id=unit.project_id,
        customer_id=customer.id,
        created_by=user.id,
        **defaults,
    )


# --- enum kumeleri (spec §2) ---


def test_customer_type_uyeleri():
    assert [c.value for c in CustomerType] == ["person", "company"]


def test_sale_type_uyeleri():
    assert [s.value for s in SaleType] == ["sale", "reservation", "pre_contract"]


def test_unit_sale_status_uyeleri():
    assert [s.value for s in UnitSaleStatus] == [
        "reservation",
        "active",
        "deed_transferred",
        "cancelled",
    ]


def test_deed_condition_uyeleri():
    assert [d.value for d in DeedCondition] == [
        "full_payment",
        "after_down_payment",
        "at_contract",
    ]


def test_payment_plan_type_uyeleri():
    assert [p.value for p in PaymentPlanType] == [
        "cash",
        "down_payment_installments",
        "bank_loan",
        "barter",
    ]


def test_installment_payment_method_uyeleri():
    assert [m.value for m in InstallmentPaymentMethod] == [
        "transfer",
        "cash",
        "cheque",
        "auto_payment",
    ]


async def test_yeni_tablolar_olusur(db_session):
    tablolar = await db_session.run_sync(lambda s: inspect(s.bind).get_table_names())
    for ad in ("customers", "unit_sales", "sale_installments"):
        assert ad in tablolar


async def test_units_tablosuna_sale_id_sutunu_ACILMADI(db_session):
    """Ileri bag kurali (units spec §1.3): iliski `unit_sales.unit_id` yonundendir."""
    sonuc = await db_session.execute(
        text(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name='units' AND column_name='sale_id'"
        )
    )
    assert sonuc.scalar_one() == 0


async def test_unit_sales_maliyet_kar_sutunu_ACMAZ(db_session):
    """Kalici karar 3: maliyet/kar P10'un isi (`pending_module: project_costs`)."""
    sonuc = await db_session.execute(
        text("SELECT column_name FROM information_schema.columns WHERE table_name='unit_sales'")
    )
    sutunlar = {satir[0] for satir in sonuc.all()}
    assert not sutunlar & {"unit_cost", "cost", "profit", "expected_profit", "margin_pct"}


# --- customers ---


async def test_customer_tckn_benzersiz(db_session):
    await _customer(db_session, national_id="12345678901")
    await _customer(db_session, national_id="12345678902")

    db_session.add(
        Customer(customer_type=CustomerType.person, name="Kopya", national_id="12345678901")
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_customer_vkn_benzersiz(db_session):
    await _customer(
        db_session, customer_type=CustomerType.company, name="A AS", tax_number="1234567890"
    )

    db_session.add(
        Customer(customer_type=CustomerType.company, name="B AS", tax_number="1234567890")
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_customer_bos_kimlik_alanlari_coklanabilir(db_session):
    """Kismi indeks: NULL TCKN/VKN tasiyan alicilar serbestce coklanir."""
    await _customer(db_session, name="Kimliksiz 1")
    await _customer(db_session, name="Kimliksiz 2")

    sayi = await db_session.scalar(
        select(text("count(*)")).select_from(Customer).where(Customer.national_id.is_(None))
    )
    assert sayi >= 2


async def test_customer_projeye_bagli_degil(db_session):
    """Spec §6: alici sirket genelidir, `project_id` sutunu YOKTUR."""
    sonuc = await db_session.execute(
        text(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name='customers' AND column_name='project_id'"
        )
    )
    assert sonuc.scalar_one() == 0


# --- unit_sales ---


async def test_unite_basina_tek_acik_satis(db_session, project_factory, user_factory):
    project = await project_factory("P-SALE-1")
    unit = await _unit(db_session, project)
    musteri = await _customer(db_session)
    kullanici = await user_factory("sales1@fiil.test", "Parola123!", "patron")

    db_session.add(_sale(unit, musteri, kullanici))
    await db_session.flush()

    db_session.add(_sale(unit, musteri, kullanici, status=UnitSaleStatus.reservation))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_iptal_edilen_satis_uniteyi_serbest_birakir(
    db_session, project_factory, user_factory
):
    project = await project_factory("P-SALE-2")
    unit = await _unit(db_session, project)
    musteri = await _customer(db_session)
    kullanici = await user_factory("sales2@fiil.test", "Parola123!", "patron")

    db_session.add(_sale(unit, musteri, kullanici, status=UnitSaleStatus.cancelled))
    db_session.add(_sale(unit, musteri, kullanici, status=UnitSaleStatus.cancelled))
    await db_session.flush()

    # Iptaller kisiti kapsamaz, bu yuzden yeni bir ACIK satis acilabilir.
    db_session.add(_sale(unit, musteri, kullanici))
    await db_session.flush()


async def test_negatif_satis_bedeli_reddedilir(db_session, project_factory, user_factory):
    project = await project_factory("P-SALE-3")
    unit = await _unit(db_session, project)
    musteri = await _customer(db_session)
    kullanici = await user_factory("sales3@fiil.test", "Parola123!", "patron")

    db_session.add(_sale(unit, musteri, kullanici, sale_price=Decimal("-1.00")))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_satisi_olan_unite_silinemez(db_session, project_factory, user_factory):
    """`unit_id` FK RESTRICT: satis kaydi duran unite dusurulemez."""
    project = await project_factory("P-SALE-4")
    unit = await _unit(db_session, project)
    musteri = await _customer(db_session)
    kullanici = await user_factory("sales4@fiil.test", "Parola123!", "patron")
    db_session.add(_sale(unit, musteri, kullanici))
    await db_session.flush()

    with pytest.raises(IntegrityError):
        await db_session.execute(text("DELETE FROM units WHERE id = :id"), {"id": str(unit.id)})


async def test_satisi_olan_alici_silinemez(db_session, project_factory, user_factory):
    """`customer_id` FK RESTRICT (spec §4: alici silme ucu de YOKTUR)."""
    project = await project_factory("P-SALE-5")
    unit = await _unit(db_session, project)
    musteri = await _customer(db_session)
    kullanici = await user_factory("sales5@fiil.test", "Parola123!", "patron")
    db_session.add(_sale(unit, musteri, kullanici))
    await db_session.flush()

    with pytest.raises(IntegrityError):
        await db_session.execute(
            text("DELETE FROM customers WHERE id = :id"), {"id": str(musteri.id)}
        )


async def test_proje_silinince_satis_cascade(db_session, project_factory, user_factory):
    sonuc = await db_session.execute(
        text(
            "SELECT rc.delete_rule FROM information_schema.referential_constraints rc "
            "JOIN information_schema.key_column_usage k "
            "ON k.constraint_name = rc.constraint_name "
            "WHERE k.table_name='unit_sales' AND k.column_name='project_id'"
        )
    )
    assert sonuc.scalar_one() == "CASCADE"


async def test_danisman_fk_set_null(db_session):
    sonuc = await db_session.execute(
        text(
            "SELECT rc.delete_rule FROM information_schema.referential_constraints rc "
            "JOIN information_schema.key_column_usage k "
            "ON k.constraint_name = rc.constraint_name "
            "WHERE k.table_name='unit_sales' AND k.column_name='advisor_user_id'"
        )
    )
    assert sonuc.scalar_one() == "SET NULL"


async def test_olusturan_kullanici_fk_restrict(db_session):
    sonuc = await db_session.execute(
        text(
            "SELECT rc.delete_rule FROM information_schema.referential_constraints rc "
            "JOIN information_schema.key_column_usage k "
            "ON k.constraint_name = rc.constraint_name "
            "WHERE k.table_name='unit_sales' AND k.column_name='created_by'"
        )
    )
    assert sonuc.scalar_one() == "RESTRICT"


async def test_tapu_teslim_alanlari_varsayilanlari(db_session, project_factory, user_factory):
    project = await project_factory("P-SALE-6")
    unit = await _unit(db_session, project)
    musteri = await _customer(db_session)
    kullanici = await user_factory("sales6@fiil.test", "Parola123!", "patron")
    satis = _sale(
        unit,
        musteri,
        kullanici,
        deed_condition=DeedCondition.full_payment,
        planned_deed_date=date(2027, 6, 1),
        payment_plan_type=PaymentPlanType.down_payment_installments,
    )
    db_session.add(satis)
    await db_session.flush()
    await db_session.refresh(satis)

    assert satis.has_condominium_easement is False
    assert satis.has_mortgage is False
    assert satis.late_fee_monthly_pct is None


# --- sale_installments ---


async def test_taksit_sira_numarasi_satis_icinde_benzersiz(
    db_session, project_factory, user_factory
):
    project = await project_factory("P-SALE-7")
    unit = await _unit(db_session, project)
    musteri = await _customer(db_session)
    kullanici = await user_factory("sales7@fiil.test", "Parola123!", "patron")
    satis = _sale(unit, musteri, kullanici)
    db_session.add(satis)
    await db_session.flush()

    db_session.add(
        SaleInstallment(
            sale_id=satis.id,
            sequence_no=0,
            label="Peşinat",
            due_date=date(2026, 7, 27),
            amount=Decimal("440000.00"),
            payment_method=InstallmentPaymentMethod.transfer,
        )
    )
    await db_session.flush()

    db_session.add(
        SaleInstallment(
            sale_id=satis.id,
            sequence_no=0,
            label="Kopya",
            due_date=date(2026, 8, 27),
            amount=Decimal("1.00"),
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_taksit_paid_amount_varsayilani_sifir(db_session, project_factory, user_factory):
    project = await project_factory("P-SALE-8")
    unit = await _unit(db_session, project)
    musteri = await _customer(db_session)
    kullanici = await user_factory("sales8@fiil.test", "Parola123!", "patron")
    satis = _sale(unit, musteri, kullanici)
    db_session.add(satis)
    await db_session.flush()

    taksit = SaleInstallment(
        sale_id=satis.id,
        sequence_no=1,
        label="1 / 12",
        due_date=date(2026, 9, 1),
        amount=Decimal("83333.00"),
    )
    db_session.add(taksit)
    await db_session.flush()
    await db_session.refresh(taksit)

    assert taksit.paid_amount == Decimal("0.00")
    assert taksit.paid_at is None


async def test_satis_silinince_taksitler_cascade(db_session, project_factory, user_factory):
    project = await project_factory("P-SALE-9")
    unit = await _unit(db_session, project)
    musteri = await _customer(db_session)
    kullanici = await user_factory("sales9@fiil.test", "Parola123!", "patron")
    satis = _sale(unit, musteri, kullanici)
    db_session.add(satis)
    await db_session.flush()
    db_session.add(
        SaleInstallment(
            sale_id=satis.id,
            sequence_no=0,
            label="Peşinat",
            due_date=date(2026, 7, 27),
            amount=Decimal("440000.00"),
        )
    )
    await db_session.flush()

    await db_session.execute(text("DELETE FROM unit_sales WHERE id = :id"), {"id": str(satis.id)})

    kalan = await db_session.execute(
        text("SELECT count(*) FROM sale_installments WHERE sale_id = :id"), {"id": str(satis.id)}
    )
    assert kalan.scalar_one() == 0


async def test_negatif_tahsilat_reddedilir(db_session, project_factory, user_factory):
    project = await project_factory("P-SALE-10")
    unit = await _unit(db_session, project)
    musteri = await _customer(db_session)
    kullanici = await user_factory("sales10@fiil.test", "Parola123!", "patron")
    satis = _sale(unit, musteri, kullanici)
    db_session.add(satis)
    await db_session.flush()

    db_session.add(
        SaleInstallment(
            sale_id=satis.id,
            sequence_no=1,
            label="1 / 12",
            due_date=date(2026, 9, 1),
            amount=Decimal("100.00"),
            paid_amount=Decimal("-1.00"),
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
