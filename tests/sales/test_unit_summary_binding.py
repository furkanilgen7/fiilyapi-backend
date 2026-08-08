"""P8 T5 — `units/summary.py`'daki `_UNIT_SALES` yer tutucularının GERÇEK veriye bağlanması.

P3'te dört alan "veri kaynağı henüz yazılmadı" yer tutucusuydu (`pending_module:
"unit_sales"`): `UnitResponse.sale_price` (KY 275) · `UnitResponse.buyer_name`
(KY 277) · `UnitTotals.sales_revenue` (KY 93) · `UnitTotals.average_sale_price`
(KY 267). P8 satış kaydını açtığı için dördü de artık gerçek değerdir —
`sales_status`ün P3.1'de yer tutucudan gerçek sütuna dönüşünün aynısı.

BAĞLANMAYANLAR yer tutucu KALIR: `unit_cost` ve `expected_profit` (kalıcı karar
3 → P10 `project_costs`). `shareholder` yer tutucusu P9 T3'te KALKTI ve yerini
gerçek `shareholder_id`/`shareholder_name` aldı.
"""

import pytest

pytestmark = pytest.mark.asyncio


async def _satis(client, headers, proje, unite, musteri, **degisiklikler) -> dict:
    govde = {
        "unit_id": str(unite.id),
        "customer_id": str(musteri.id),
        "sale_type": "sale",
        "sale_price": "1440000.00",
        **degisiklikler,
    }
    resp = await client.post(f"/projects/{proje.id}/sales", json=govde, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _uniteler(client, headers, proje) -> dict:
    resp = await client.get(f"/projects/{proje.id}/units", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _unite_satiri(body: dict, unit_id: str) -> dict:
    for group in body["blocks"]:
        for unit in group["units"]:
            if unit["id"] == unit_id:
                return unit
    raise AssertionError(f"ünite listede yok: {unit_id}")


async def test_satissiz_unitede_fiyat_ve_alici_bostur(client, admin_headers, proje, unite, musteri):
    """Yer tutucu SÖZLEŞMESİ kalkar ama uydurma değer de üretilmez: `None`."""
    body = await _uniteler(client, admin_headers, proje)

    satir = _unite_satiri(body, str(unite.id))
    assert satir["sale_price"] is None
    assert satir["buyer_name"] is None
    assert body["totals"]["sales_revenue"] == "0.00"
    assert body["totals"]["average_sale_price"] is None


async def test_satis_kaydi_unite_satirina_fiyat_ve_alici_yazar(
    client, admin_headers, proje, unite, ikinci_unite, musteri
):
    """KY 275/277: satış bedeli ve alıcı adı AÇIK satış kaydından okunur."""
    await _satis(client, admin_headers, proje, unite, musteri)

    body = await _uniteler(client, admin_headers, proje)

    satir = _unite_satiri(body, str(unite.id))
    assert satir["sale_price"] == "1440000.00"
    assert satir["buyer_name"] == musteri.name
    assert satir["sales_status"] == "sold"
    # Satışı olmayan ünite boş kalır — tek satış tüm listeyi boyamaz.
    assert _unite_satiri(body, str(ikinci_unite.id))["sale_price"] is None


async def test_ciro_yalniz_GERCEKLESEN_satislardan_toplanir(
    client, admin_headers, proje, unite, ikinci_unite, musteri
):
    """KY 93 "Satış Geliri" GERÇEKLEŞEN satıştır: rezervasyon ciro DEĞİLDİR.

    Ünite satırı yine de rezervasyonun bedelini gösterir (`sales_status`
    `reserved`tır ve ekran o daireye kimin kapora verdiğini görmelidir);
    toplam ciroya ise yalnız `active`/`deed_transferred` kayıtlar girer.
    """
    await _satis(client, admin_headers, proje, unite, musteri)
    await _satis(
        client,
        admin_headers,
        proje,
        ikinci_unite,
        musteri,
        sale_type="reservation",
        sale_price="800000.00",
    )

    body = await _uniteler(client, admin_headers, proje)

    assert _unite_satiri(body, str(ikinci_unite.id))["sale_price"] == "800000.00"
    assert body["totals"]["sales_revenue"] == "1440000.00"
    assert body["totals"]["average_sale_price"] == "1440000.00"


async def test_iptal_edilen_satis_unite_satirindan_dusulur(
    client, admin_headers, proje, unite, musteri
):
    satis = await _satis(client, admin_headers, proje, unite, musteri)
    iptal = await client.post(
        f"/sales/{satis['id']}/cancel", json={"reason": "Fesih"}, headers=admin_headers
    )
    assert iptal.status_code == 200, iptal.text

    body = await _uniteler(client, admin_headers, proje)

    satir = _unite_satiri(body, str(unite.id))
    assert satir["sale_price"] is None
    assert satir["buyer_name"] is None
    assert satir["sales_status"] == "listed"
    assert body["totals"]["sales_revenue"] == "0.00"


async def test_maliyet_kar_YER_TUTUCU_KALIR(client, admin_headers, proje, unite, musteri):
    """Kalıcı karar 3: maliyet/kâr AÇILMAZ — bunlar yer tutucu KALIR.

    Hissedar (KKP 91) artık burada DEĞİL: P9 T3'te yer tutucudan gerçek alana
    döndü ve `shareholder` anahtarı yanıttan tamamen çıktı (bir sonraki ajan
    bunu "eksik alan" sanıp geri koymamalıdır).
    """
    await _satis(client, admin_headers, proje, unite, musteri)

    satir = _unite_satiri(await _uniteler(client, admin_headers, proje), str(unite.id))

    assert satir["unit_cost"] == {
        "available": False,
        "value": None,
        "pending_module": "project_costs",
    }
    assert satir["expected_profit"]["pending_module"] == "project_costs"
    assert "shareholder" not in satir
    assert satir["shareholder_id"] is None
    assert satir["shareholder_name"] is None


async def test_tekil_unite_yaniti_da_satis_bilgisini_tasir(
    client, admin_headers, proje, unite, musteri
):
    """PATCH/GET tekil yanıtı listeyle AYNI kaynaktan beslenir — iki doğruluk tanımı olmaz."""
    await _satis(client, admin_headers, proje, unite, musteri)

    resp = await client.patch(f"/units/{unite.id}", json={"layout": "3+1"}, headers=admin_headers)

    assert resp.status_code == 200, resp.text
    assert resp.json()["sale_price"] == "1440000.00"
    assert resp.json()["buyer_name"] == musteri.name
