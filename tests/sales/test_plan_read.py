"""P8 T5 — `GET /sales/{id}/installments` (planı OKUYAN uç).

T4 planı yazan üç ucu (`generate-plan` / `PUT installments` / `pay`) kapattı ama
planı OKUYAN bir uç bırakmadı: plan yalnız yazma yanıtlarında görülebiliyordu ve
`GET /sales/{id}` satırları taşımıyor. Bu uç o boşluğu kapatır ve T4'ün
`SalePlanResponse` şemasını AYNEN kullanır (ikinci bir plan zarfı YOK).

Mockup `Form - Daire Satisi.dc.html`: 110-147 plan tablosu · 143 TOPLAM.
Mockup `Satış Yönetimi.dc.html`: 180 "⚠ 2 taksit gecikmiş" — satır düzeyi
"gecikmiş" TÜREVDİR (`due_date` geçmiş + `paid_amount < amount`), kolon değil.
"""

import uuid
from datetime import date, timedelta

import pytest

from app.modules.sales.guards import SALE_MISSING
from app.modules.sales.router import get_sale_plan_endpoint, save_sale_installments_endpoint

pytestmark = pytest.mark.asyncio

TAM_GOVDE = {
    "sale_type": "sale",
    "sale_price": "1440000.00",
    "payment_plan_type": "down_payment_installments",
    "down_payment": "440000.00",
    "installment_count": 12,
    "first_installment_date": "2026-09-01",
}


async def _satis(client, headers, proje, unite, musteri, **degisiklikler) -> dict:
    govde = TAM_GOVDE | {
        "unit_id": str(unite.id),
        "customer_id": str(musteri.id),
        **degisiklikler,
    }
    resp = await client.post(f"/projects/{proje.id}/sales", json=govde, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _satir(sequence_no: int, amount: str, due_date: str) -> dict:
    return {
        "sequence_no": sequence_no,
        "label": "Peşinat" if sequence_no == 0 else f"{sequence_no} / 2",
        "due_date": due_date,
        "amount": amount,
    }


def test_ucun_yaniti_t4_semasiyla_AYNIDIR():
    """`SalePlanResponse` PAYLAŞILIR — ikinci bir plan zarfı kurulmaz."""
    assert (
        get_sale_plan_endpoint.__annotations__["return"]
        is save_sale_installments_endpoint.__annotations__["return"]
    )


async def test_plan_okunur_ve_toplamlari_doner(client, admin_headers, proje, unite, musteri):
    satis = await _satis(client, admin_headers, proje, unite, musteri)
    uretim = await client.post(f"/sales/{satis['id']}/generate-plan", headers=admin_headers)
    assert uretim.status_code == 200, uretim.text

    resp = await client.get(f"/sales/{satis['id']}/installments", headers=admin_headers)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["sale_id"] == satis["id"]
    assert body["sale_price"] == "1440000.00"
    assert body["total_amount"] == "1440000.00"  # F143 TOPLAM
    assert body["paid_amount"] == "0.00"
    assert len(body["items"]) == 13  # peşinat + 12 taksit
    assert body["items"][0]["label"] == "Peşinat"


async def test_plansiz_satis_bos_liste_doner(client, admin_headers, proje, unite, musteri):
    """Plan üretilmemişse uç 404 DEĞİL boş plan döner: satış vardır, planı yoktur."""
    satis = await _satis(client, admin_headers, proje, unite, musteri)

    resp = await client.get(f"/sales/{satis['id']}/installments", headers=admin_headers)

    assert resp.status_code == 200, resp.text
    assert resp.json()["items"] == []
    assert resp.json()["total_amount"] == "0.00"


async def test_gecikmis_turevi_vadesi_gecen_odenmemis_satirda_true(
    client, admin_headers, proje, unite, musteri
):
    """S180: `due_date` geçmiş VE `paid_amount < amount` → `is_overdue` true."""
    satis = await _satis(client, admin_headers, proje, unite, musteri)
    dun = str(date.today() - timedelta(days=1))
    yarin = str(date.today() + timedelta(days=1))
    kayit = await client.put(
        f"/sales/{satis['id']}/installments",
        json={
            "items": [
                _satir(0, "440000.00", dun),
                _satir(1, "500000.00", dun),
                _satir(2, "500000.00", yarin),
            ]
        },
        headers=admin_headers,
    )
    assert kayit.status_code == 200, kayit.text
    # Peşinat TAM tahsil edilir → vadesi geçse bile gecikmiş SAYILMAZ.
    pesinat_id = kayit.json()["items"][0]["id"]
    odeme = await client.post(
        f"/sales/installments/{pesinat_id}/pay",
        json={"amount": "440000.00"},
        headers=admin_headers,
    )
    assert odeme.status_code == 200, odeme.text

    body = (await client.get(f"/sales/{satis['id']}/installments", headers=admin_headers)).json()

    gecikme = {row["sequence_no"]: row["is_overdue"] for row in body["items"]}
    assert gecikme == {0: False, 1: True, 2: False}
    kalanlar = {row["sequence_no"]: row["remaining_amount"] for row in body["items"]}
    assert kalanlar == {0: "0.00", 1: "500000.00", 2: "500000.00"}
    assert body["paid_amount"] == "440000.00"


async def test_kismi_tahsilatli_vadesi_gecmis_satir_gecikmistir(
    client, admin_headers, proje, unite, musteri
):
    satis = await _satis(client, admin_headers, proje, unite, musteri)
    dun = str(date.today() - timedelta(days=1))
    kayit = await client.put(
        f"/sales/{satis['id']}/installments",
        json={"items": [_satir(0, "1440000.00", dun)]},
        headers=admin_headers,
    )
    assert kayit.status_code == 200, kayit.text
    satir_id = kayit.json()["items"][0]["id"]
    assert (
        await client.post(
            f"/sales/installments/{satir_id}/pay",
            json={"amount": "1.00"},
            headers=admin_headers,
        )
    ).status_code == 200

    body = (await client.get(f"/sales/{satis['id']}/installments", headers=admin_headers)).json()

    assert body["items"][0]["is_overdue"] is True
    assert body["items"][0]["remaining_amount"] == "1439999.00"


# --- Görünürlük ve yetki ---


async def test_kapsam_disi_plan_okumasi_404(
    client, admin_headers, kapsam_disi_headers, proje, unite, musteri
):
    satis = await _satis(client, admin_headers, proje, unite, musteri)

    resp = await client.get(f"/sales/{satis['id']}/installments", headers=kapsam_disi_headers)

    assert resp.status_code == 404
    assert resp.json()["detail"] == SALE_MISSING


async def test_olmayan_satisin_plani_404(client, admin_headers):
    resp = await client.get(f"/sales/{uuid.uuid4()}/installments", headers=admin_headers)
    assert resp.status_code == 404
    assert resp.json()["detail"] == SALE_MISSING


async def test_view_yetkisi_plani_OKUYABILIR(
    client, admin_headers, view_headers, proje, unite, musteri
):
    """Okuma ucu `sales:view` ister — muhasebe planı görebilmelidir."""
    satis = await _satis(client, admin_headers, proje, unite, musteri)

    resp = await client.get(f"/sales/{satis['id']}/installments", headers=view_headers)

    assert resp.status_code == 200, resp.text


async def test_yetkisiz_plan_okumasi_403(
    client, admin_headers, yetkisiz_headers, proje, unite, musteri
):
    satis = await _satis(client, admin_headers, proje, unite, musteri)

    resp = await client.get(f"/sales/{satis['id']}/installments", headers=yetkisiz_headers)

    assert resp.status_code == 403, resp.text
