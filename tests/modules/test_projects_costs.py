"""P10 T1 — maliyet/kâr çekirdeği (`projects/costs.py`) testleri.

Senaryo sayıları MOCKUP'TAN gelir, uydurulmamıştır:

* **KY** = `projedesign/Proje - Kendi Yatırım.dc.html` — 119 arsa ₺8.400.000 ·
  182 toplam bütçe maliyeti ₺29.800.000 · 169 satış hedefi ₺48.200.000 ·
  187-188 tahmini net kâr ₺18.400.000 / %38,2 marj.
* **KK** = `projedesign/Proje - Kat Karşılığı.dc.html` — 105-106 arsa maliyeti ₺0
  "Kat karşılığı ✓" · 121 bizim pay ₺30,4M · 135 inşaat maliyeti ₺17,6M ·
  139-140 kâr ₺12,8M / %42,1 marj · 208 "taşeron çalışır, hakediş kesilir".
* **E4** = `projedesign/Ekran 4 - Projeler.dc.html` 180-181 — taahhüt kartı
  yalnız "Sözleşme Bedeli / Harcanan" basar.
* **DS** = `projedesign/Form - Daire Satisi.dc.html` — 86 satış bedeli 1.440.000 ·
  90-91 "Bu Satıştan Kâr ₺460.000 · %31,9 marj" (⇒ ünite maliyeti 980.000).

**Yuvarlama toleransı:** motor parayı ve marjı `quantize2` ile İKİ ondalığa
yuvarlar; mockup marjı BİR ondalıkla basar. Bu yüzden marj iddiaları
`quantize(Decimal("0.1"))` ile karşılaştırılır (38,17 → %38,2), tutar iddiaları
kuruş kuruşuna eşitlik arar.
"""

from collections.abc import Iterator
from decimal import Decimal

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.contracts.models import SubcontractorContract
from app.modules.projects import costs
from app.modules.projects.models import Project, ProjectInvestment, ProjectType
from app.modules.subcontractor_progress_payments.models import (
    SubcontractorPaymentStatus,
    SubcontractorProgressPayment,
    SubcontractorProgressPaymentLine,
)
from app.modules.units.models import Unit, UnitOwnerSide
from app.modules.users.models import User
from tests.conftest import test_engine

_TENTH = Decimal("0.1")


def _bir_ondalik(value: Decimal | None) -> Decimal | None:
    """Mockup marjı bir ondalıkla basar; motor iki ondalık tutar (bkz. modül notu)."""
    return None if value is None else value.quantize(_TENTH)


def _line(
    *, price: str, quantity: str, coefficient: str = "1.000"
) -> SubcontractorProgressPaymentLine:
    return SubcontractorProgressPaymentLine(
        code="A.001",
        description="Kalem",
        unit="m2",
        contract_unit_price=Decimal(price),
        coefficient=Decimal(coefficient),
        quantity=Decimal(quantity),
    )


def _payment(
    status: SubcontractorPaymentStatus,
    *,
    lines: list[SubcontractorProgressPaymentLine],
    rejected_at: object | None = None,
) -> SubcontractorProgressPayment:
    payment = SubcontractorProgressPayment(
        sequence_no=1,
        status=status,
        vat_pct=Decimal("20"),
        advance_pct=Decimal("10"),
        retainage_pct=Decimal("5"),
        lines=lines,
    )
    payment.rejected_at = rejected_at  # type: ignore[assignment]
    return payment


def _unit(
    *,
    list_price: str | None = None,
    appraisal_value: str | None = None,
    gross_area_m2: str | None = None,
    owner_side: UnitOwnerSide | None = None,
) -> Unit:
    return Unit(
        unit_no="1",
        list_price=None if list_price is None else Decimal(list_price),
        appraisal_value=None if appraisal_value is None else Decimal(appraisal_value),
        gross_area_m2=None if gross_area_m2 is None else Decimal(gross_area_m2),
        owner_side=owner_side,
    )


def _ky_project() -> Project:
    """KY 119 + 182: dört bütçe kalemi 21,4M + arsa 8,4M = 29,8M toplam bütçe maliyeti."""
    project = Project(
        code="KY-1",
        name="Kendi Yatırım",
        project_type=ProjectType.kendi_yatirim,
        budget_material=Decimal("8000000"),
        budget_labor=Decimal("5000000"),
        budget_subcontractor=Decimal("6400000"),
        budget_overhead=Decimal("2000000"),
    )
    project.investment = ProjectInvestment(
        sales_target=Decimal("50000000"), land_cost=Decimal("8400000")
    )
    return project


def _kk_project() -> Project:
    """KK 135: inşaat bütçesi 17,6M; arsa maliyeti tanım gereği 0 (KK 105-106)."""
    return Project(
        code="KK-1",
        name="Kat Karşılığı",
        project_type=ProjectType.kat_karsiligi,
        budget_material=Decimal("6000000"),
        budget_labor=Decimal("4600000"),
        budget_subcontractor=Decimal("5000000"),
        budget_overhead=Decimal("2000000"),
    )


# --- Arsa maliyeti kuralı (spec §2) ---


def test_arsa_maliyeti_kendi_yatirimda_yatirim_satirindan_okunur() -> None:
    assert costs.land_cost(_ky_project()) == Decimal("8400000")


def test_arsa_maliyeti_kat_karsiligida_tanim_geregi_sifirdir() -> None:
    """KK 105-106 "Arsa Maliyeti ₺0 — Kat karşılığı ✓" — `None` DEĞİL, sıfır."""
    assert costs.land_cost(_kk_project()) == Decimal("0")


def test_arsa_maliyeti_taahhutte_yoktur() -> None:
    """Taahhütte arsa KAVRAMI yok: 0 basmak "bedava arsa" yalanı olurdu."""
    project = Project(code="T-1", name="Taahhüt", project_type=ProjectType.taahhut)
    assert costs.land_cost(project) is None


def test_arsa_maliyeti_yatirim_satiri_yokken_none() -> None:
    project = Project(code="KY-2", name="Yatırım", project_type=ProjectType.kendi_yatirim)
    assert costs.land_cost(project) is None


# --- Toplam bütçe maliyeti ---


def test_toplam_butce_maliyeti_dort_kalem_arti_arsadir() -> None:
    assert costs.total_budget_cost(_ky_project()) == Decimal("29800000.00")


def test_toplam_butce_maliyeti_kat_karsiligida_insaat_butcesine_esittir() -> None:
    assert costs.total_budget_cost(_kk_project()) == Decimal("17600000.00")


def test_girilmemis_arsa_maliyeti_toplama_sifir_katkida_bulunur() -> None:
    """`units.summary._sum` kuralı: NULL para 0 sayılır — ama `land_cost` yine
    `None` döner ki ekran "—" basabilsin."""
    project = Project(
        code="KY-3",
        name="Yatırım",
        project_type=ProjectType.kendi_yatirim,
        budget_material=Decimal("1000000"),
    )
    assert costs.total_budget_cost(project) == Decimal("1000000.00")
    assert costs.land_cost(project) is None


# --- Ünite değer toplamları ---


def test_liste_fiyati_toplami_bos_fiyatlari_atlar() -> None:
    units = [_unit(list_price="1000000"), _unit(list_price=None), _unit(list_price="500000")]
    assert costs.unit_list_price_total(units) == Decimal("1500000.00")


def test_kendi_pay_degeri_yalniz_yuklenici_tarafini_toplar() -> None:
    """KK 121 — arsa sahibinin üniteleri BİZİM pay değerine girmez."""
    units = [
        _unit(appraisal_value="20000000", owner_side=UnitOwnerSide.contractor),
        _unit(appraisal_value="10400000", owner_side=UnitOwnerSide.contractor),
        _unit(appraisal_value="9000000", owner_side=UnitOwnerSide.landowner),
    ]
    assert costs.our_share_value(units, ProjectType.kat_karsiligi) == Decimal("30400000.00")


# --- Kâr/marj türevleri (spec §2 formülleri) ---


def test_kendi_yatirim_kar_projeksiyonu_ky_mockupini_birebir_verir() -> None:
    """KY 169/182/187-188: 48,2M − 29,8M = 18,4M · %38,2 marj."""
    units = [_unit(list_price="30000000"), _unit(list_price="18200000")]

    projection = costs.investment_projection(_ky_project(), units)

    assert projection.revenue == Decimal("48200000.00")
    assert projection.cost == Decimal("29800000.00")
    assert projection.profit == Decimal("18400000.00")
    assert _bir_ondalik(projection.margin_pct) == Decimal("38.2")


def test_kendi_yatirim_karinda_satis_hedefi_kolonu_kullanilmaz() -> None:
    """S4: `sales_target` hesaba GİRMEZ — gelir ünite liste fiyatlarından türer."""
    project = _ky_project()
    project.investment.sales_target = Decimal("999999999")

    projection = costs.investment_projection(project, [_unit(list_price="48200000")])

    assert projection.revenue == Decimal("48200000.00")


def test_kat_karsiligi_kar_projeksiyonu_kk_mockupini_birebir_verir() -> None:
    """KK 121/135/139-140: 30,4M − 17,6M = 12,8M · %42,1 marj."""
    units = [
        _unit(appraisal_value="20000000", owner_side=UnitOwnerSide.contractor),
        _unit(appraisal_value="10400000", owner_side=UnitOwnerSide.contractor),
        _unit(appraisal_value="9000000", owner_side=UnitOwnerSide.landowner),
    ]

    projection = costs.land_share_projection(_kk_project(), units)

    assert projection.revenue == Decimal("30400000.00")
    assert projection.cost == Decimal("17600000.00")
    assert projection.profit == Decimal("12800000.00")
    assert _bir_ondalik(projection.margin_pct) == Decimal("42.1")


def test_taahhut_kari_sozlesme_bedeli_eksi_harcanandir() -> None:
    """E4 180-181 kartta basılmaz; iç türev olarak döner."""
    project = Project(
        code="T-2",
        name="Taahhüt",
        project_type=ProjectType.taahhut,
        contract_amount=Decimal("11200000"),
    )

    projection = costs.contracting_projection(project, Decimal("8400000"))

    assert projection.revenue == Decimal("11200000")
    assert projection.cost == Decimal("8400000")
    assert projection.profit == Decimal("2800000.00")


def test_taahhut_kari_sozlesme_bedeli_yokken_nonedir() -> None:
    project = Project(code="T-3", name="Taahhüt", project_type=ProjectType.taahhut)

    projection = costs.contracting_projection(project, Decimal("100"))

    assert projection.profit is None
    assert projection.margin_pct is None


def test_marj_gelir_sifirken_none_doner() -> None:
    """`units.summary._average` korkuluğu: sıfıra bölme YOK, sahte %0 basılmaz."""
    projection = costs.investment_projection(_ky_project(), [])

    assert projection.revenue == Decimal("0.00")
    assert projection.profit == Decimal("-29800000.00")
    assert projection.margin_pct is None


def test_tip_bazli_dagitici_dogru_projeksiyonu_secer() -> None:
    units = [_unit(list_price="48200000")]

    assert costs.profit_projection(
        _ky_project(), units, Decimal("0")
    ).cost == costs.total_budget_cost(_ky_project())
    assert costs.profit_projection(_kk_project(), [], Decimal("0")).revenue == Decimal("0.00")
    taahhut = Project(
        code="T-4",
        name="Taahhüt",
        project_type=ProjectType.taahhut,
        contract_amount=Decimal("500"),
    )
    assert costs.profit_projection(taahhut, [], Decimal("200")).profit == Decimal("300.00")


# --- Ünite maliyeti dağıtımı (S3) ---


def test_unite_maliyeti_brut_m2_oraninda_dagitilir() -> None:
    """S3: toplam bütçe maliyeti × ünite brüt m² / proje toplam brüt m²."""
    cost = costs.unit_cost(Decimal("29800000.00"), Decimal("100"), Decimal("4000"))

    assert cost == Decimal("745000.00")


def test_unite_maliyeti_m2siz_unitede_nonedir() -> None:
    assert costs.unit_cost(Decimal("29800000.00"), None, Decimal("4000")) is None


def test_unite_maliyeti_proje_toplam_m2si_sifirken_nonedir() -> None:
    assert costs.unit_cost(Decimal("29800000.00"), Decimal("100"), Decimal("0")) is None


def test_proje_brut_alan_toplami_bos_alanlari_atlar() -> None:
    units = [_unit(gross_area_m2="120.50"), _unit(gross_area_m2=None), _unit(gross_area_m2="79.50")]
    assert costs.gross_area_total(units) == Decimal("200.00")


# --- Satıştan kâr (DS 90-91) ---


def test_satistan_kar_ds_mockupini_birebir_verir() -> None:
    """DS 86/90-91: 1.440.000 − 980.000 = 460.000 · %31,9 marj."""
    projection = costs.sale_profit(Decimal("1440000"), Decimal("980000"))

    assert projection.profit == Decimal("460000.00")
    assert _bir_ondalik(projection.margin_pct) == Decimal("31.9")


def test_satistan_kar_unite_maliyeti_bilinmiyorken_nonedir() -> None:
    projection = costs.sale_profit(Decimal("1440000"), None)

    assert projection.profit is None
    assert projection.margin_pct is None


# --- Taşeron hakediş toplamları (S1/S2) ---


def test_harcanan_onaylanan_ve_odenen_brutlerin_toplamidir() -> None:
    """S1: harcanan = approved+paid · ödenen = paid · bekleyen = approved."""
    payments = [
        _payment(SubcontractorPaymentStatus.paid, lines=[_line(price="1000", quantity="100")]),
        _payment(SubcontractorPaymentStatus.approved, lines=[_line(price="1000", quantity="50")]),
    ]

    totals = costs.subcontractor_totals(payments)

    assert totals.paid == Decimal("100000.00")
    assert totals.pending == Decimal("50000.00")
    assert totals.spent == Decimal("150000.00")


def test_taslak_ve_onay_bekleyen_hakedis_maliyete_girmez() -> None:
    """GERÇEK enum draft | pending_approval | approved | paid'dir; "rejected"
    ayrı durum DEĞİL, `draft AND rejected_at IS NOT NULL` türevidir — üçü de
    maliyet dışıdır."""
    payments = [
        _payment(SubcontractorPaymentStatus.draft, lines=[_line(price="1000", quantity="999")]),
        _payment(
            SubcontractorPaymentStatus.pending_approval,
            lines=[_line(price="1000", quantity="888")],
        ),
        _payment(
            SubcontractorPaymentStatus.draft,
            lines=[_line(price="1000", quantity="777")],
            rejected_at="2026-08-09T00:00:00+00:00",
        ),
        _payment(SubcontractorPaymentStatus.paid, lines=[_line(price="1000", quantity="10")]),
    ]

    totals = costs.subcontractor_totals(payments)

    assert totals.spent == Decimal("10000.00")
    assert totals.paid == Decimal("10000.00")
    assert totals.pending == Decimal("0.00")


def test_brut_satir_duzeyinde_yuvarlanir_sql_sum_ile_ayni_degildir() -> None:
    """`progress_payments/summary.py:98-114` gerekçesi: `line_total` kuruş
    yuvarlaması SATIR düzeyindedir. SQL'de `SUM(price*coef*qty)` alınsaydı
    100,49 çıkardı; doğru sonuç 100,50'dir."""
    payment = _payment(
        SubcontractorPaymentStatus.paid,
        lines=[_line(price="33.33", coefficient="1.005", quantity="3")],
    )

    assert costs.subcontractor_totals([payment]).spent == Decimal("100.50")


def test_hakedissiz_kume_sifir_doner() -> None:
    totals = costs.subcontractor_totals([])

    assert (totals.spent, totals.paid, totals.pending) == (
        Decimal("0.00"),
        Decimal("0.00"),
        Decimal("0.00"),
    )


# --- Toplu okuma (N+1 yasağı) ---


@pytest.fixture
def _sorgu_sayaci() -> Iterator[list[str]]:
    """Sürücüye giden HER ifadeyi toplar (`test_work_category.py` deseni) —
    N+1 iddiası tahmine değil ÖLÇÜME dayanır."""
    ifadeler: list[str] = []

    def kaydet(conn, cursor, statement, parameters, context, executemany) -> None:  # noqa: ANN001
        ifadeler.append(" ".join(statement.split()))

    event.listen(test_engine.sync_engine, "before_cursor_execute", kaydet)
    try:
        yield ifadeler
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", kaydet)


async def _hakedis_yaz(
    session: AsyncSession,
    project: Project,
    creator: User,
    status: SubcontractorPaymentStatus,
    *,
    quantity: str,
) -> None:
    contract = SubcontractorContract(
        project_id=project.id,
        subcontractor_name="Akın İnşaat",
        created_by=creator.id,
    )
    session.add(contract)
    await session.flush()
    payment = SubcontractorProgressPayment(
        contract_id=contract.id,
        project_id=project.id,
        sequence_no=1,
        status=status,
        vat_pct=Decimal("20"),
        advance_pct=Decimal("10"),
        retainage_pct=Decimal("5"),
        created_by=creator.id,
        lines=[_line(price="1000", quantity=quantity)],
    )
    session.add(payment)
    await session.flush()


async def test_toplu_toplamlar_proje_sayisindan_bagimsiz_sorgu_kosar(
    seeded_db: AsyncSession, user_factory, project_factory, _sorgu_sayaci: list[str]
) -> None:
    """T3 liste ucunun temeli: proje başına ayrı sorgu YOK (spec §4)."""
    kurucu = await user_factory(
        email="maliyet@thk-crud.co", password="parola1234", role_key="system_admin"
    )
    birinci = await project_factory(code="P10-1", project_type="kendi_yatirim")
    ikinci = await project_factory(code="P10-2", project_type="kat_karsiligi")
    bossuz = await project_factory(code="P10-3", project_type="taahhut")
    await _hakedis_yaz(seeded_db, birinci, kurucu, SubcontractorPaymentStatus.paid, quantity="100")
    await _hakedis_yaz(
        seeded_db, birinci, kurucu, SubcontractorPaymentStatus.approved, quantity="50"
    )
    await _hakedis_yaz(seeded_db, ikinci, kurucu, SubcontractorPaymentStatus.draft, quantity="900")

    _sorgu_sayaci.clear()
    totals = await costs.subcontractor_totals_by_projects(
        seeded_db, [birinci.id, ikinci.id, bossuz.id]
    )

    # Bir sorgu hakedişler, bir sorgu `lines` (selectin) — proje sayısıyla BÜYÜMEZ.
    hakedis_sorgulari = [
        ifade for ifade in _sorgu_sayaci if "from subcontractor_progress_payments" in ifade.lower()
    ]
    satir_sorgulari = [
        ifade
        for ifade in _sorgu_sayaci
        if "from subcontractor_progress_payment_lines" in ifade.lower()
    ]
    assert len(hakedis_sorgulari) == 1, hakedis_sorgulari
    assert len(satir_sorgulari) == 1, satir_sorgulari
    assert totals[birinci.id].spent == Decimal("150000.00")
    assert totals[birinci.id].paid == Decimal("100000.00")
    assert totals[birinci.id].pending == Decimal("50000.00")
    # Taslak hakediş maliyete girmez; hakedişi olmayan proje de sıfırla döner.
    assert totals[ikinci.id].spent == Decimal("0.00")
    assert totals[bossuz.id].spent == Decimal("0.00")


async def test_toplu_toplamlar_bos_liste_icin_sorgu_kosmaz(
    seeded_db: AsyncSession, _sorgu_sayaci: list[str]
) -> None:
    _sorgu_sayaci.clear()

    assert await costs.subcontractor_totals_by_projects(seeded_db, []) == {}
    assert [
        ifade for ifade in _sorgu_sayaci if "subcontractor_progress_payments" in ifade.lower()
    ] == []


async def test_toplu_toplamlar_kapsam_disindaki_projeyi_cekmez(
    seeded_db: AsyncSession, user_factory, project_factory
) -> None:
    """Kapsam süzgeci SQL'dedir: istenmeyen projenin satırı hiç ÇEKİLMEZ."""
    kurucu = await user_factory(
        email="kapsam@thk-crud.co", password="parola1234", role_key="system_admin"
    )
    istenen = await project_factory(code="P10-4")
    disarida = await project_factory(code="P10-5")
    await _hakedis_yaz(seeded_db, istenen, kurucu, SubcontractorPaymentStatus.paid, quantity="10")
    await _hakedis_yaz(seeded_db, disarida, kurucu, SubcontractorPaymentStatus.paid, quantity="99")

    totals = await costs.subcontractor_totals_by_projects(seeded_db, [istenen.id])

    assert set(totals) == {istenen.id}
    assert totals[istenen.id].spent == Decimal("10000.00")


def test_bos_toplam_sabiti_degistirilemez() -> None:
    """`EMPTY_TOTALS` paylaşılan bir SABİTTİR: mutasyon kapısı kapalı olmalı."""
    assert costs.EMPTY_TOTALS.spent == Decimal("0.00")
    with pytest.raises(AttributeError):
        costs.EMPTY_TOTALS.spent = Decimal("1")  # type: ignore[misc]
