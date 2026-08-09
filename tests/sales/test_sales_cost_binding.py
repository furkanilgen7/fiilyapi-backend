"""P10 T3 — satış yanıtının `unit_cost` / `sale_profit` zarfları doldu.

Sayılar **DS** = `projedesign/Form - Daire Satisi.dc.html` 62 ("Maliyet
₺980.000") ve 90-91 ("Bu Satıştan Kâr ₺460.000 · Satış bedeli − ünite
maliyeti · %31,9 marj")dan gelir.

Marj için AYRI bir alan AÇILMAZ: `UnitSaleResponse`ta marj kolonu yoktur ve
mockup'ta olmayan alan icat edilmez — ekran %31,9'u kâr/bedelden türetir
(spec §5 "başabaş noktası türev metin, backend alan açmaz" kuralının aynısı).

Senaryo: bütçe 9,8M · proje brüt m² 1.780 · ünite 178 m² → maliyet 980.000;
satış bedeli 1.440.000 → kâr 460.000 (DS birebir).
"""

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.models import Project
from app.modules.units.models import Block, Unit, UnitKind

pytestmark = pytest.mark.asyncio


async def _ds_senaryosu(session: AsyncSession, proje: Project, blok: Block, unite: Unit) -> None:
    """DS 58-62 girdileri: ünite 178 m², projenin toplamı 1.780 m², bütçe 9,8M."""
    proje.budget_material = Decimal("9800000.00")
    unite.gross_area_m2 = Decimal("178.00")
    session.add(
        Unit(
            project_id=proje.id,
            block_id=blok.id,
            unit_no="99",
            unit_kind=UnitKind.apartment,
            gross_area_m2=Decimal("1602.00"),
        )
    )
    await session.flush()


async def _satis(client, headers, proje, unite, musteri, *, sale_price="1440000.00") -> dict:
    resp = await client.post(
        f"/projects/{proje.id}/sales",
        json={
            "unit_id": str(unite.id),
            "customer_id": str(musteri.id),
            "sale_type": "sale",
            "sale_price": sale_price,
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_satis_kaydinda_unite_maliyeti_ve_kar_gercek_doner(
    client, admin_headers, seeded_db, proje, blok, unite, musteri
):
    """DS 62/90: maliyet 980.000 · kâr 1.440.000 − 980.000 = 460.000."""
    await _ds_senaryosu(seeded_db, proje, blok, unite)

    govde = await _satis(client, admin_headers, proje, unite, musteri)

    assert govde["unit_cost"]["available"] is True
    assert govde["unit_cost"]["pending_module"] is None
    assert Decimal(govde["unit_cost"]["value"]) == Decimal("980000.00")
    assert Decimal(govde["sale_profit"]["value"]) == Decimal("460000.00")
    # DS 91 marjı ekran türetir: 460.000 / 1.440.000 = %31,9.
    oran = Decimal(govde["sale_profit"]["value"]) / Decimal(govde["sale_price"]) * 100
    assert oran.quantize(Decimal("0.1")) == Decimal("31.9")


async def test_satis_listesi_ve_detayi_ayni_maliyeti_verir(
    client, admin_headers, seeded_db, proje, blok, unite, musteri
):
    """Liste/detay/geçiş yanıtları TEK kaynaktan gelir — ayrışamaz."""
    await _ds_senaryosu(seeded_db, proje, blok, unite)
    olusan = await _satis(client, admin_headers, proje, unite, musteri)

    liste = (await client.get(f"/projects/{proje.id}/sales", headers=admin_headers)).json()
    detay = (await client.get(f"/sales/{olusan['id']}", headers=admin_headers)).json()

    assert liste["items"][0]["unit_cost"] == olusan["unit_cost"]
    assert detay["sale_profit"] == olusan["sale_profit"]


async def test_m2si_olmayan_unitenin_satisinda_zarf_BOS_KALIR(
    client, admin_headers, seeded_db, proje, blok, unite, musteri
):
    """Maliyet bilinmiyorsa kâr da bilinmez (uydurma rakam basılmaz)."""
    proje.budget_material = Decimal("9800000.00")
    unite.gross_area_m2 = None
    await seeded_db.flush()

    govde = await _satis(client, admin_headers, proje, unite, musteri)

    for alan in ("unit_cost", "sale_profit"):
        assert govde[alan]["available"] is False, alan
        assert govde[alan]["value"] is None, alan
        assert govde[alan]["pending_module"] == "project_costs", alan


async def test_satis_listesinde_sorgu_sayisi_satis_sayisindan_bagimsizdir(
    client, admin_headers, seeded_db, proje, blok, unite, ikinci_unite, musteri
):
    """Spec §4: satış başına maliyet sorgusu AÇILMAZ."""
    from collections.abc import Iterator
    from contextlib import contextmanager

    from sqlalchemy import event

    from tests.conftest import test_engine

    @contextmanager
    def sayac() -> Iterator[list[str]]:
        ifadeler: list[str] = []

        def kaydet(conn, cursor, statement, parameters, context, executemany) -> None:  # noqa: ANN001
            ifadeler.append(" ".join(statement.split()))

        event.listen(test_engine.sync_engine, "before_cursor_execute", kaydet)
        try:
            yield ifadeler
        finally:
            event.remove(test_engine.sync_engine, "before_cursor_execute", kaydet)

    await _ds_senaryosu(seeded_db, proje, blok, unite)
    ikinci_unite.gross_area_m2 = Decimal("100.00")
    await seeded_db.flush()
    await _satis(client, admin_headers, proje, unite, musteri)

    with sayac() as ifadeler:
        await client.get(f"/projects/{proje.id}/sales", headers=admin_headers)
        tek_sayim = len(ifadeler)

    await _satis(client, admin_headers, proje, ikinci_unite, musteri, sale_price="500000.00")

    with sayac() as ifadeler:
        liste = await client.get(f"/projects/{proje.id}/sales", headers=admin_headers)
        cift_sayim = len(ifadeler)

    assert len(liste.json()["items"]) == 2
    assert tek_sayim == cift_sayim, (tek_sayim, cift_sayim)
