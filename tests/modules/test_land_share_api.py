"""P-KK T6 — `GET /projects/{id}/land-share/summary` ve `.../units`.

Testler durum koduyla YETİNMEZ: gövdeyi de doğrular (FastAPI'nin "rota yok"
404'ü ile alan katmanının "proje yok" 404'ü aynı koddur) ve denge iddiaları
sabit beklenen sayı yazmak yerine KÜMEYİ KURUP sonucu türetir (MT-2 kanonu).

Çakılan ayrışma noktaları:

1. **Üç kümenin toplamı** — atanmamış (`owner_side IS NULL`) üniteler ne bizim
   paya ne arsa payına sayılır; üçünün toplamı toplam üniteye EŞİT.
2. **Kat karşılığı OLMAYAN proje** → 404, boş özet değil.
3. **Sıfıra bölme** — rayiç değeri hiç girilmemiş proje → sapma `None`.
4. **Hissedar oranları toplamı ≠ 100** — bozuk veri OLDUĞU GİBİ basılır.
5. **Çelişkili satır** (`owner_side=contractor` + `shareholder_id` dolu) —
   `owner_side` otoritedir, hissedar dağılımına sızmaz.
6. **N+1** — ünite sayısı sorgu sayısını BÜYÜTMEZ.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from decimal import Decimal

from sqlalchemy import event

from app.modules.projects.land_share import LAND_SHARE_MISSING
from app.modules.projects.models import LandShareShareholder, ProjectLandShare
from app.modules.units.models import UnitKind, UnitOwnerSide, UnitSalesStatus
from tests.conftest import test_engine
from tests.modules.units.test_units_api import _auth, _block, _login, _site, _unit


def _summary_url(project_id: uuid.UUID) -> str:
    return f"/projects/{project_id}/land-share/summary"


def _units_url(project_id: uuid.UUID) -> str:
    return f"/projects/{project_id}/land-share/units"


async def _land_share(session, project, our_pct: str = "55.00", **kwargs) -> ProjectLandShare:
    defaults: dict = {
        "landowner_name": "Yılmaz Ailesi",
        "our_share_pct": Decimal(our_pct),
        "owner_share_pct": Decimal("100.00") - Decimal(our_pct),
    }
    defaults.update(kwargs)
    row = ProjectLandShare(project_id=project.id, **defaults)
    session.add(row)
    await session.flush()
    return row


async def _shareholder(session, project, name: str, share_pct: str) -> LandShareShareholder:
    row = LandShareShareholder(project_id=project.id, name=name, share_pct=Decimal(share_pct))
    session.add(row)
    await session.flush()
    return row


@contextmanager
def _sorgu_sayaci() -> Iterator[list[str]]:
    """Sürücüye giden HER ifadeyi toplar — N+1 iddiası tahmine değil ÖLÇÜME
    dayanır (`test_units_shareholder.py` deseninin aynısı)."""
    ifadeler: list[str] = []

    def kaydet(conn, cursor, statement, parameters, context, executemany) -> None:  # noqa: ANN001
        ifadeler.append(" ".join(statement.split()))

    event.listen(test_engine.sync_engine, "before_cursor_execute", kaydet)
    try:
        yield ifadeler
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", kaydet)


async def _kk_project(session, project_factory, code: str = "KK-1", **kwargs):
    project = await project_factory(code=code, project_type="kat_karsiligi")
    await _land_share(session, project, **kwargs)
    return project


# --- Mutlu yol: mockup aritmetiği ---


async def test_summary_returns_contract_card_fields(
    client, db_session, user_factory, project_factory
):
    """K5: mockup'ın çizdiği YEDİ sözleşme alanı da modelde vardır ve döner."""
    project = await _kk_project(
        db_session,
        project_factory,
        contract_no="KKS-2026-001",
        notary_date=date(2026, 1, 8),
        land_area_m2=Decimal("2840.00"),
        construction_area_m2=Decimal("6420.00"),
        delivery_date=date(2027, 6, 30),
        daily_penalty=Decimal("15000.00"),
        guarantee_amount=Decimal("2500000.00"),
    )
    token = await _login(client, user_factory, "system_admin")

    resp = await client.get(_summary_url(project.id), headers=_auth(token))

    assert resp.status_code == 200
    contract = resp.json()["contract"]
    assert contract["contract_no"] == "KKS-2026-001"
    assert contract["notary_date"] == "2026-01-08"
    assert contract["land_area_m2"] == "2840.00"
    assert contract["construction_area_m2"] == "6420.00"
    assert contract["delivery_date"] == "2027-06-30"
    assert contract["daily_penalty"] == "15000.00"
    assert contract["guarantee_amount"] == "2500000.00"
    assert contract["landowner_name"] == "Yılmaz Ailesi"
    assert contract["our_share_pct"] == "55.00"
    assert contract["owner_share_pct"] == "45.00"


async def test_summary_partitions_sum_to_total(client, db_session, user_factory, project_factory):
    """🔴 Üç kümenin toplamı toplam üniteye EŞİT — atanmamışlar hiçbir tarafa sayılmaz.

    İddia sabit sayı yazmaz: küme kurulur, beklenen sonuç KURULAN kümeden türer.
    """
    project = await _kk_project(db_session, project_factory)
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    plan = (
        [(UnitOwnerSide.contractor, "1000.00")] * 4
        + [(UnitOwnerSide.landowner, "2000.00")] * 3
        + [(None, "500.00")] * 2
    )
    for index, (side, value) in enumerate(plan):
        await _unit(
            db_session,
            project,
            block,
            unit_no=str(index + 1),
            owner_side=side,
            appraisal_value=Decimal(value),
        )
    token = await _login(client, user_factory, "system_admin")

    body = (await client.get(_summary_url(project.id), headers=_auth(token))).json()

    beklenen_biz = sum(1 for side, _ in plan if side is UnitOwnerSide.contractor)
    beklenen_arsa = sum(1 for side, _ in plan if side is UnitOwnerSide.landowner)
    beklenen_bos = sum(1 for side, _ in plan if side is None)
    assert body["our_side"]["unit_count"] == beklenen_biz
    assert body["owner_side"]["unit_count"] == beklenen_arsa
    assert body["unassigned"]["unit_count"] == beklenen_bos
    assert body["totals"]["unit_count"] == len(plan)
    assert (
        body["our_side"]["unit_count"]
        + body["owner_side"]["unit_count"]
        + body["unassigned"]["unit_count"]
        == body["totals"]["unit_count"]
    )
    # Değer tarafında da aynı bekçi: üç kümenin değeri toplam değeri verir.
    assert Decimal(body["our_side"]["value_total"]) + Decimal(
        body["owner_side"]["value_total"]
    ) + Decimal(body["unassigned"]["value_total"]) == Decimal(body["totals"]["value_total"])


async def test_summary_value_balance_excludes_unassigned(
    client, db_session, user_factory, project_factory
):
    """Atanmamış ünitenin rayici gerçekleşen ORANI seyreltmez — payda atanmıştır."""
    project = await _kk_project(db_session, project_factory)
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    await _unit(
        db_session,
        project,
        block,
        "1",
        owner_side=UnitOwnerSide.contractor,
        appraisal_value=Decimal("55.00"),
    )
    await _unit(
        db_session,
        project,
        block,
        "2",
        owner_side=UnitOwnerSide.landowner,
        appraisal_value=Decimal("45.00"),
    )
    await _unit(db_session, project, block, "3", appraisal_value=Decimal("900.00"))
    token = await _login(client, user_factory, "system_admin")

    value = (await client.get(_summary_url(project.id), headers=_auth(token))).json()["balance"][
        "value_balance"
    ]

    assert value["assigned_value_total"] == "100.00"
    assert value["our_actual_pct"] == "55.00"
    assert value["deviation_pct"] == "0.00"
    assert value["is_within_tolerance"] is True
    assert value["tolerance_pct"] == "1.0"


async def test_summary_our_side_sales_breakdown(client, db_session, user_factory, project_factory):
    """Satış kırılımı YALNIZ bizim tarafta; `remaining_value` rezerveyi de kapsar."""
    project = await _kk_project(db_session, project_factory)
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    for index, status in enumerate(
        (UnitSalesStatus.sold, UnitSalesStatus.reserved, UnitSalesStatus.listed)
    ):
        await _unit(
            db_session,
            project,
            block,
            str(index + 1),
            owner_side=UnitOwnerSide.contractor,
            sales_status=status,
            appraisal_value=Decimal("100.00"),
        )
    token = await _login(client, user_factory, "system_admin")

    our = (await client.get(_summary_url(project.id), headers=_auth(token))).json()["our_side"]

    assert (our["sold_count"], our["reserved_count"], our["available_count"]) == (1, 1, 1)
    assert our["sold_value"] == "100.00"
    # 300 − 100: rezerve ünite hâlâ KALAN STOKTUR (mockup "Kalan Stok 15 ünite").
    assert our["remaining_value"] == "200.00"


# --- Ayrışma: 404, sıfıra bölme, bozuk veri, çelişki ---


async def test_summary_without_land_share_record_is_404(
    client, db_session, user_factory, project_factory
):
    """🔴 Kat karşılığı OLMAYAN proje 404 alır, BOŞ ÖZET DEĞİL.

    Boş özet ekrana "%0/%0 paylaşım" bastırır ve kullanıcı veriyi kaybettiğini
    sanardı. Gövde de doğrulanır: rota 404'ü ile alan 404'ü aynı kod.
    """
    project = await project_factory(code="TAAHHUT-1")
    token = await _login(client, user_factory, "system_admin")

    resp = await client.get(_summary_url(project.id), headers=_auth(token))

    assert resp.status_code == 404
    assert resp.json()["detail"] == LAND_SHARE_MISSING


async def test_units_without_land_share_record_is_404(
    client, db_session, user_factory, project_factory
):
    """İki uç AYNI kapıdan geçer — biri açık kalırsa ekran yarım veri basardı."""
    project = await project_factory(code="TAAHHUT-2")
    token = await _login(client, user_factory, "system_admin")

    resp = await client.get(_units_url(project.id), headers=_auth(token))

    assert resp.status_code == 404
    assert resp.json()["detail"] == LAND_SHARE_MISSING


async def test_unknown_project_is_404_without_leaking_existence(client, user_factory):
    token = await _login(client, user_factory, "system_admin")

    resp = await client.get(_summary_url(uuid.uuid4()), headers=_auth(token))

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Proje bulunamadı"


async def test_summary_without_any_unit_does_not_divide_by_zero(
    client, db_session, user_factory, project_factory
):
    """🔴 Hiç ünitesi olmayan proje: sapma `None`, `0` DEĞİL."""
    project = await _kk_project(db_session, project_factory)
    token = await _login(client, user_factory, "system_admin")

    body = (await client.get(_summary_url(project.id), headers=_auth(token))).json()

    value = body["balance"]["value_balance"]
    assert value["our_actual_pct"] is None
    assert value["deviation_pct"] is None
    assert value["is_within_tolerance"] is None
    # Eşik payda yokken BİLE döner — frontend kopyalamak zorunda kalmasın.
    assert value["tolerance_pct"] == "1.0"
    counts = body["balance"]["count_balance"]
    assert counts["total_unit_count"] == 0
    assert counts["our_expected_count"] == 0
    assert counts["owner_expected_count"] == 0


async def test_summary_with_zero_appraisal_values_does_not_divide_by_zero(
    client, db_session, user_factory, project_factory
):
    """Ünite VAR ama rayiç girilmemiş: adet dengesi çalışır, değer dengesi `None`.

    Bir projenin adet olarak dengede olup değer olarak HESAPLANAMAZ olması
    tam olarak iki dengenin neden ayrı olduğudur (K2).
    """
    project = await _kk_project(db_session, project_factory)
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    await _unit(db_session, project, block, "1", owner_side=UnitOwnerSide.contractor)
    await _unit(db_session, project, block, "2", owner_side=UnitOwnerSide.landowner)
    token = await _login(client, user_factory, "system_admin")

    body = (await client.get(_summary_url(project.id), headers=_auth(token))).json()

    assert body["balance"]["count_balance"]["our_assigned_count"] == 1
    assert body["balance"]["value_balance"]["deviation_pct"] is None
    assert body["balance"]["value_balance"]["is_within_tolerance"] is None


async def test_summary_prints_broken_shareholder_percentages_as_is(
    client, db_session, user_factory, project_factory
):
    """🔴 Hissedar oranları toplamı ≠ 100 → uç PATLAMAZ, OLDUĞU GİBİ basar.

    Ekranın görevi toplamı olduğu gibi göstermektir, düzeltmek değil: sessizce
    normalize etmek kullanıcının bozuk veriyi görmesini engellerdi.
    """
    project = await _kk_project(db_session, project_factory)
    await _shareholder(db_session, project, "Ahmet Yılmaz", "50.00")
    await _shareholder(db_session, project, "Fatma Yılmaz", "40.00")
    token = await _login(client, user_factory, "system_admin")

    rows = (await client.get(_summary_url(project.id), headers=_auth(token))).json()["shareholders"]

    assert [row["share_pct"] for row in rows] == ["50.00", "40.00"]
    # Ünitesi olmayan hissedar da LİSTEDE KALIR (mockup üçünü de basar).
    assert [row["unit_count"] for row in rows] == [0, 0]


async def test_shareholder_distribution_ignores_contradictory_contractor_unit(
    client, db_session, user_factory, project_factory
):
    """🔴 `owner_side=contractor` + `shareholder_id` dolu = ÇELİŞKİ.

    KARAR: `owner_side` otoritedir. Ünite bizim paya sayılır ve hissedar
    dağılımına GİRMEZ; aksi hâlde aynı ünite hem `our_side.unit_count`ta hem
    hissedar toplamında sayılırdı. (Yazma yolu bu bileşimi zaten 422 ile
    reddediyor — çelişki ancak eski/elle veriden gelir.)

    Ünite LİSTESİ ise `shareholder_name`i olduğu gibi basar: çelişki ancak
    görünürse düzeltilebilir.
    """
    project = await _kk_project(db_session, project_factory)
    holder = await _shareholder(db_session, project, "Ahmet Yılmaz", "100.00")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    await _unit(
        db_session,
        project,
        block,
        "1",
        owner_side=UnitOwnerSide.contractor,
        shareholder_id=holder.id,
        appraisal_value=Decimal("100.00"),
    )
    token = await _login(client, user_factory, "system_admin")

    body = (await client.get(_summary_url(project.id), headers=_auth(token))).json()

    assert body["our_side"]["unit_count"] == 1
    assert body["owner_side"]["unit_count"] == 0
    assert body["shareholders"][0]["unit_count"] == 0
    assert body["shareholders"][0]["value_total"] == "0.00"

    rows = (await client.get(_units_url(project.id), headers=_auth(token))).json()["items"]
    assert rows[0]["shareholder_name"] == "Ahmet Yılmaz"
    assert rows[0]["owner_side"] == "contractor"


async def test_shareholder_distribution_counts_only_landowner_units(
    client, db_session, user_factory, project_factory
):
    project = await _kk_project(db_session, project_factory)
    ahmet = await _shareholder(db_session, project, "Ahmet Yılmaz", "50.00")
    await _shareholder(db_session, project, "Fatma Yılmaz", "50.00")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    for index in range(3):
        await _unit(
            db_session,
            project,
            block,
            str(index + 1),
            owner_side=UnitOwnerSide.landowner,
            shareholder_id=ahmet.id,
            appraisal_value=Decimal("100.00"),
        )
    # Hissedarı ATANMAMIŞ arsa ünitesi (KKP 119 "—") hiçbir satıra girmez.
    await _unit(
        db_session,
        project,
        block,
        "4",
        owner_side=UnitOwnerSide.landowner,
        appraisal_value=Decimal("100.00"),
    )
    token = await _login(client, user_factory, "system_admin")

    body = (await client.get(_summary_url(project.id), headers=_auth(token))).json()

    rows = {row["name"]: row for row in body["shareholders"]}
    assert rows["Ahmet Yılmaz"]["unit_count"] == 3
    assert rows["Ahmet Yılmaz"]["value_total"] == "300.00"
    assert rows["Fatma Yılmaz"]["unit_count"] == 0
    # Hissedar toplamı arsa payını AŞMAZ (atanmamış hissedar dağılımda yok).
    assert (
        sum(row["unit_count"] for row in body["shareholders"]) <= body["owner_side"]["unit_count"]
    )


# --- Ünite listesi: süzgeç + sayfalama + N+1 ---


async def test_units_filter_unassigned_selects_null_owner_side(
    client, db_session, user_factory, project_factory
):
    """`unassigned` sütunda saklanan bir durum DEĞİL, yalnızca sorgu dilidir."""
    project = await _kk_project(db_session, project_factory)
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    await _unit(db_session, project, block, "1", owner_side=UnitOwnerSide.contractor)
    await _unit(db_session, project, block, "2", owner_side=UnitOwnerSide.landowner)
    await _unit(db_session, project, block, "3")
    token = await _login(client, user_factory, "system_admin")

    for side, beklenen in (("contractor", ["1"]), ("landowner", ["2"]), ("unassigned", ["3"])):
        body = (
            await client.get(
                _units_url(project.id), params={"owner_side": side}, headers=_auth(token)
            )
        ).json()
        assert [row["unit_no"] for row in body["items"]] == beklenen
        assert body["total"] == 1


async def test_units_pagination_total_is_filtered_set_size(
    client, db_session, user_factory, project_factory
):
    """`total` SÜZGEÇLENMİŞ kümenin boyutudur (sayfalamadan ÖNCE) — sayfa
    çubuğu buradan çıkar. Sayfalar birleştiğinde küme AYNEN geri gelir."""
    project = await _kk_project(db_session, project_factory)
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    for index in range(7):
        await _unit(
            db_session,
            project,
            block,
            str(index + 1),
            owner_side=UnitOwnerSide.contractor,
            sort_order=index,
        )
    await _unit(db_session, project, block, "99", owner_side=UnitOwnerSide.landowner, sort_order=99)
    token = await _login(client, user_factory, "system_admin")

    params = {"owner_side": "contractor", "limit": 3}
    first = (await client.get(_units_url(project.id), params=params, headers=_auth(token))).json()
    second = (
        await client.get(
            _units_url(project.id), params={**params, "offset": 3}, headers=_auth(token)
        )
    ).json()
    third = (
        await client.get(
            _units_url(project.id), params={**params, "offset": 6}, headers=_auth(token)
        )
    ).json()

    assert first["total"] == second["total"] == third["total"] == 7
    assert (len(first["items"]), len(second["items"]), len(third["items"])) == (3, 3, 1)
    birlesik = [row["unit_no"] for page in (first, second, third) for row in page["items"]]
    assert birlesik == [str(index + 1) for index in range(7)]


async def test_units_row_carries_shareholder_and_buyer_names(
    client, db_session, user_factory, project_factory
):
    """Mockup "Hissedar / Alıcı" sütunu: iki ad da YANITTA gelir (N+1 yok)."""
    project = await _kk_project(db_session, project_factory)
    holder = await _shareholder(db_session, project, "Ahmet Yılmaz", "100.00")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site, name="A Blok")
    await _unit(
        db_session,
        project,
        block,
        "2",
        owner_side=UnitOwnerSide.landowner,
        shareholder_id=holder.id,
        unit_kind=UnitKind.apartment,
        layout="3+1",
        gross_area_m2=Decimal("148.00"),
        appraisal_value=Decimal("1380000.00"),
    )
    token = await _login(client, user_factory, "system_admin")

    row = (await client.get(_units_url(project.id), headers=_auth(token))).json()["items"][0]

    assert row["block_name"] == "A Blok"
    assert row["layout"] == "3+1"
    assert row["gross_area_m2"] == "148.00"
    assert row["appraisal_value"] == "1380000.00"
    assert row["shareholder_name"] == "Ahmet Yılmaz"
    assert row["buyer_name"] is None


async def test_units_query_count_is_constant_in_unit_count(
    client, db_session, user_factory, project_factory
):
    """🔴 N+1 bekçisi: ünite sayısı 2'den 12'ye çıkarken sorgu sayısı DEĞİŞMEZ.

    Ölçüm tahmine değil sürücü olayına dayanır; hissedar/blok/satış adları
    ünite başına sorgu açsaydı 400 ünitelik projede uç çökerdi.
    """
    token = await _login(client, user_factory, "system_admin")

    async def _olc(code: str, unite_sayisi: int) -> int:
        project = await _kk_project(db_session, project_factory, code=code)
        holder = await _shareholder(db_session, project, "Ahmet Yılmaz", "100.00")
        site = await _site(db_session, project)
        block = await _block(db_session, project, site)
        for index in range(unite_sayisi):
            await _unit(
                db_session,
                project,
                block,
                str(index + 1),
                owner_side=UnitOwnerSide.landowner,
                shareholder_id=holder.id,
                appraisal_value=Decimal("100.00"),
            )
        with _sorgu_sayaci() as ifadeler:
            resp = await client.get(
                _units_url(project.id), params={"limit": 200}, headers=_auth(token)
            )
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == unite_sayisi
        return len(ifadeler)

    assert await _olc("KK-N1", 2) == await _olc("KK-N2", 12)


async def test_units_search_matches_unit_no_and_block_name(
    client, db_session, user_factory, project_factory
):
    project = await _kk_project(db_session, project_factory)
    site = await _site(db_session, project)
    a_blok = await _block(db_session, project, site, name="A Blok")
    b_blok = await _block(db_session, project, site, name="B Blok")
    await _unit(db_session, project, a_blok, "12")
    await _unit(db_session, project, b_blok, "7")
    token = await _login(client, user_factory, "system_admin")

    by_unit = (
        await client.get(_units_url(project.id), params={"q": "12"}, headers=_auth(token))
    ).json()
    by_block = (
        await client.get(_units_url(project.id), params={"q": "b blok"}, headers=_auth(token))
    ).json()

    assert [row["unit_no"] for row in by_unit["items"]] == ["12"]
    assert [row["unit_no"] for row in by_block["items"]] == ["7"]


async def test_units_block_filter_narrows_list(client, db_session, user_factory, project_factory):
    project = await _kk_project(db_session, project_factory)
    site = await _site(db_session, project)
    a_blok = await _block(db_session, project, site, name="A Blok")
    b_blok = await _block(db_session, project, site, name="B Blok")
    await _unit(db_session, project, a_blok, "1")
    await _unit(db_session, project, b_blok, "1")
    token = await _login(client, user_factory, "system_admin")

    body = (
        await client.get(
            _units_url(project.id), params={"block_id": str(b_blok.id)}, headers=_auth(token)
        )
    ).json()

    assert body["total"] == 1
    assert body["items"][0]["block_name"] == "B Blok"


async def test_units_limit_above_cap_is_422(client, db_session, user_factory, project_factory):
    """Tavan aşımı SESSİZCE KIRPILMAZ (K7 sayfalama standardı)."""
    project = await _kk_project(db_session, project_factory)
    token = await _login(client, user_factory, "system_admin")

    resp = await client.get(_units_url(project.id), params={"limit": 500}, headers=_auth(token))

    assert resp.status_code == 422


async def test_summary_requires_authentication(client, db_session, project_factory):
    project = await _kk_project(db_session, project_factory)

    resp = await client.get(_summary_url(project.id))

    assert resp.status_code == 401
