"""P8 T4 — ödeme planı: `generate-plan` + `PUT installments` + `pay` (spec §4, §8 S2).

Mockup `Form - Daire Satisi.dc.html` (F) satır numaraları:
- 99-100 "💳 Ödeme Planı" kartı + "Plan Oluştur" düğmesi (= `generate-plan` ucu)
- 103-106 peşinat (440.000) / taksit sayısı (12) / ilk taksit (2026-09-01) /
  vade farkı (0) — planın DÖRT girdisi, hepsi `unit_sales` sütunu
- 117-121 peşinat satırı: "Peşinat" · "Sözleşme imzasında" · 440.000
- 124-127 ve 132-135 taksit satırları: "1 / 12" / "2 / 12" · "Aylık taksit" ·
  01.09.2026 / 01.10.2026 · 83.333
- 139 "… 10 taksit daha · Toplam 12 taksit"
- 143 TOPLAM ₺1.440.000 = F86 satış bedeli → **Σ amount == sale_price**
- 122/129 ödeme şekli (Havale/EFT · Nakit · Çek · Otomatik Ödeme)

Mockup'ta vade farkı 0'dır (satır 106) ve TOPLAM tam olarak satış bedeline
eşittir (satır 143); bu yüzden vade farkı plan TUTARLARINI ŞİŞİRMEZ — bkz.
`app/modules/sales/plan.py` gerekçesi.
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.modules.audit.models import AuditLog
from app.modules.sales.guards import (
    INSTALLMENT_MISSING,
    INSTALLMENT_TOTAL_MISMATCH,
    PAID_INSTALLMENT_BELOW_PAID,
    PAID_INSTALLMENT_REMOVED,
    PAYMENT_EXCEEDS_INSTALLMENT,
    PLAN_HAS_PAYMENTS,
    PLAN_INPUT_MISSING,
    SALE_MISSING,
)
from app.modules.sales.models import SaleInstallment

pytestmark = pytest.mark.asyncio

# F86 satış bedeli + F103/F104/F105/F106 plan girdileri (mockup 84-106).
TAM_GOVDE = {
    "sale_type": "sale",
    "sale_price": "1440000.00",
    "payment_plan_type": "down_payment_installments",
    "down_payment": "440000.00",
    "installment_count": 12,
    "first_installment_date": "2026-09-01",
    "term_interest_pct": "0.00",
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


async def _plan_uret(client, headers, sale_id) -> dict:
    resp = await client.post(f"/sales/{sale_id}/generate-plan", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _satir(sequence_no: int, amount: str, due_date: str = "2026-09-01", **ek) -> dict:
    return {
        "sequence_no": sequence_no,
        "label": f"{sequence_no} / 1" if sequence_no else "Peşinat",
        "due_date": due_date,
        "amount": amount,
        **ek,
    }


# --- 1) generate-plan ---


async def test_plan_uretimi_mockup_ornegini_birebir_uretir(
    client, admin_headers, proje, unite, musteri
):
    """F103-106 girdileri → F117-139 tablosu: peşinat + 12 taksit, TOPLAM 1.440.000."""
    satis = await _satis(client, admin_headers, proje, unite, musteri)
    plan = await _plan_uret(client, admin_headers, satis["id"])

    satirlar = plan["items"]
    assert len(satirlar) == 13  # peşinat + 12 taksit (mockup 139)
    assert satirlar[0]["sequence_no"] == 0
    assert satirlar[0]["label"] == "Peşinat"  # F118
    assert satirlar[0]["amount"] == "440000.00"  # F121
    assert satirlar[0]["due_date"] == date.today().isoformat()  # F120 "Sözleşme imzasında"
    assert satirlar[1]["label"] == "1 / 12"  # F124
    assert satirlar[1]["due_date"] == "2026-09-01"  # F105/F126
    assert satirlar[1]["amount"] == "83333.33"  # F127 (83.333 gösterimi)
    assert satirlar[2]["due_date"] == "2026-10-01"  # F135 — aylık ilerler
    assert satirlar[12]["label"] == "12 / 12"
    assert satirlar[12]["due_date"] == "2027-08-01"
    # Kuruş dengeleme SON taksitte: 1.000.000 − 11 × 83.333,33 = 83.333,37
    assert satirlar[12]["amount"] == "83333.37"
    assert plan["total_amount"] == "1440000.00"  # F143 TOPLAM
    assert sum(Decimal(s["amount"]) for s in satirlar) == Decimal("1440000.00")


async def test_kurus_dengelemesi_bolunmeyen_tutarda_son_taksitte_toplanir(
    client, admin_headers, proje, unite, musteri
):
    """100.000 / 3 tam bölünmez — fark SON satıra biner, Σ TAM eşit kalır."""
    satis = await _satis(
        client,
        admin_headers,
        proje,
        unite,
        musteri,
        sale_price="100000.00",
        down_payment="0.00",
        installment_count=3,
    )
    plan = await _plan_uret(client, admin_headers, satis["id"])

    assert [s["amount"] for s in plan["items"]] == ["33333.33", "33333.33", "33333.34"]
    assert sum(Decimal(s["amount"]) for s in plan["items"]) == Decimal("100000.00")


async def test_pesinatsiz_plan_sifirinci_satiri_uretmez(
    client, admin_headers, proje, unite, musteri
):
    """`down_payment` yok/0 → `sequence_no=0` satırı AÇILMAZ (0 TL'lik peşinat satırı sahtedir)."""
    satis = await _satis(
        client, admin_headers, proje, unite, musteri, down_payment=None, installment_count=2
    )
    plan = await _plan_uret(client, admin_headers, satis["id"])

    assert [s["sequence_no"] for s in plan["items"]] == [1, 2]
    assert [s["label"] for s in plan["items"]] == ["1 / 2", "2 / 2"]
    assert sum(Decimal(s["amount"]) for s in plan["items"]) == Decimal("1440000.00")


async def test_taksitsiz_pesin_plan_tek_satir_uretir(client, admin_headers, proje, unite, musteri):
    """ "Peşin" (F99 `cash`): peşinat = satış bedeli, taksit yok → tek satır."""
    satis = await _satis(
        client,
        admin_headers,
        proje,
        unite,
        musteri,
        payment_plan_type="cash",
        down_payment="1440000.00",
        installment_count=0,
        first_installment_date=None,
    )
    plan = await _plan_uret(client, admin_headers, satis["id"])

    assert [(s["sequence_no"], s["amount"]) for s in plan["items"]] == [(0, "1440000.00")]


async def test_plan_girdisi_eksikse_422(client, admin_headers, proje, unite, musteri):
    """Peşinat da taksit de yoksa üretilecek plan YOKTUR — sessiz boş plan değil, 422."""
    satis = await _satis(
        client,
        admin_headers,
        proje,
        unite,
        musteri,
        down_payment=None,
        installment_count=None,
        first_installment_date=None,
    )
    resp = await client.post(f"/sales/{satis['id']}/generate-plan", headers=admin_headers)

    assert resp.status_code == 422
    assert resp.json()["detail"] == PLAN_INPUT_MISSING


async def test_pesinat_satis_bedelini_asamaz_422(client, admin_headers, proje, unite, musteri):
    satis = await _satis(client, admin_headers, proje, unite, musteri, down_payment="1500000.00")
    resp = await client.post(f"/sales/{satis['id']}/generate-plan", headers=admin_headers)

    assert resp.status_code == 422


async def test_odenmemis_plan_uzerine_yeniden_uretilir(
    client, admin_headers, proje, unite, musteri, db_session
):
    """Hiç tahsilat yoksa "Plan Oluştur" (F100) planı TAZELER — eski satırlar silinir."""
    satis = await _satis(client, admin_headers, proje, unite, musteri)
    await _plan_uret(client, admin_headers, satis["id"])

    guncel = await client.patch(
        f"/sales/{satis['id']}", json={"installment_count": 2}, headers=admin_headers
    )
    assert guncel.status_code == 200, guncel.text
    plan = await _plan_uret(client, admin_headers, satis["id"])

    assert [s["sequence_no"] for s in plan["items"]] == [0, 1, 2]
    kalan = (
        (
            await db_session.execute(
                select(SaleInstallment).where(SaleInstallment.sale_id == uuid.UUID(satis["id"]))
            )
        )
        .scalars()
        .all()
    )
    assert len(kalan) == 3


async def test_tahsilatli_planin_uzerine_yazilamaz_409(
    client, admin_headers, proje, unite, musteri, db_session
):
    """Tahsilat KAYBOLAMAZ: bir satırda bile `paid_amount > 0` varsa yeniden üretim 409."""
    satis = await _satis(client, admin_headers, proje, unite, musteri)
    plan = await _plan_uret(client, admin_headers, satis["id"])
    odeme = await client.post(
        f"/sales/installments/{plan['items'][0]['id']}/pay",
        json={"amount": "1000.00"},
        headers=admin_headers,
    )
    assert odeme.status_code == 200, odeme.text

    resp = await client.post(f"/sales/{satis['id']}/generate-plan", headers=admin_headers)

    assert resp.status_code == 409
    assert resp.json()["detail"] == PLAN_HAS_PAYMENTS
    kalan = (
        (
            await db_session.execute(
                select(SaleInstallment).where(SaleInstallment.sale_id == uuid.UUID(satis["id"]))
            )
        )
        .scalars()
        .all()
    )
    assert len(kalan) == 13  # plan DOKUNULMADAN durur


async def test_plan_uretimi_denetim_satiri_yazar(
    client, admin_headers, proje, unite, musteri, db_session
):
    satis = await _satis(client, admin_headers, proje, unite, musteri)
    await _plan_uret(client, admin_headers, satis["id"])

    kayitlar = (await db_session.execute(select(AuditLog))).scalars().all()
    assert any(
        "Ödeme planı oluşturuldu" in k.detail and "A Blok · 12" in k.detail for k in kayitlar
    )


# --- 2) PUT installments (DEĞİŞTİRME semantiği) ---


async def test_degistirme_semantigi_govdede_olmayan_satir_silinir(
    client, admin_headers, proje, unite, musteri
):
    """`progress_payments` `PUT …/lines` semantiğinin aynısı: gövde planın TAMAMIDIR."""
    satis = await _satis(client, admin_headers, proje, unite, musteri)
    await _plan_uret(client, admin_headers, satis["id"])

    resp = await client.put(
        f"/sales/{satis['id']}/installments",
        json={
            "items": [
                _satir(0, "440000.00", "2026-08-01"),
                _satir(1, "1000000.00", "2026-09-01"),
            ]
        },
        headers=admin_headers,
    )

    assert resp.status_code == 200, resp.text
    assert [s["sequence_no"] for s in resp.json()["items"]] == [0, 1]


async def test_degistirme_semantigi_satir_eklenebilir(client, admin_headers, proje, unite, musteri):
    satis = await _satis(
        client, admin_headers, proje, unite, musteri, down_payment="0.00", installment_count=1
    )
    await _plan_uret(client, admin_headers, satis["id"])

    resp = await client.put(
        f"/sales/{satis['id']}/installments",
        json={
            "items": [
                _satir(1, "440000.00", "2026-09-01", payment_method="transfer"),
                _satir(2, "500000.00", "2026-10-01", payment_method="cash"),
                _satir(3, "500000.00", "2026-11-01", payment_method="cheque"),
            ]
        },
        headers=admin_headers,
    )

    assert resp.status_code == 200, resp.text
    govde = resp.json()
    assert [s["sequence_no"] for s in govde["items"]] == [1, 2, 3]
    # F122/129 ödeme şekli gövdeden gelir (Havale/EFT · Nakit · Çek).
    assert [s["payment_method"] for s in govde["items"]] == ["transfer", "cash", "cheque"]


async def test_toplam_satis_bedelinden_sapamaz_422(client, admin_headers, proje, unite, musteri):
    """F143 TOPLAM = F86; sunucu doğrular (spec §2), istemciye güvenilmez."""
    satis = await _satis(client, admin_headers, proje, unite, musteri)

    resp = await client.put(
        f"/sales/{satis['id']}/installments",
        json={"items": [_satir(1, "1439999.99", "2026-09-01")]},
        headers=admin_headers,
    )

    assert resp.status_code == 422
    assert resp.json()["detail"] == INSTALLMENT_TOTAL_MISMATCH


async def test_tahsilatli_satir_govdeden_dusurulemez_409(
    client, admin_headers, proje, unite, musteri
):
    """DEĞİŞTİRME semantiği tahsilatı SESSİZCE YUTAMAZ — tahsilatlı satır korunur."""
    satis = await _satis(client, admin_headers, proje, unite, musteri)
    plan = await _plan_uret(client, admin_headers, satis["id"])
    await client.post(
        f"/sales/installments/{plan['items'][0]['id']}/pay",
        json={"amount": "440000.00"},
        headers=admin_headers,
    )

    resp = await client.put(
        f"/sales/{satis['id']}/installments",
        json={"items": [_satir(1, "1440000.00", "2026-09-01")]},
        headers=admin_headers,
    )

    assert resp.status_code == 409
    assert resp.json()["detail"] == PAID_INSTALLMENT_REMOVED


async def test_tahsilatli_satirin_tutari_tahsilatin_altina_inemez_422(
    client, admin_headers, proje, unite, musteri
):
    satis = await _satis(client, admin_headers, proje, unite, musteri)
    plan = await _plan_uret(client, admin_headers, satis["id"])
    await client.post(
        f"/sales/installments/{plan['items'][0]['id']}/pay",
        json={"amount": "440000.00"},
        headers=admin_headers,
    )

    resp = await client.put(
        f"/sales/{satis['id']}/installments",
        json={
            "items": [
                _satir(0, "400000.00", "2026-08-01"),
                _satir(1, "1040000.00", "2026-09-01"),
            ]
        },
        headers=admin_headers,
    )

    assert resp.status_code == 422
    assert resp.json()["detail"] == PAID_INSTALLMENT_BELOW_PAID


async def test_korunan_satirin_tahsilati_ve_kimligi_degismez(
    client, admin_headers, proje, unite, musteri
):
    """Satır SİLİNİP yeniden eklenmez (hakediş `lines` deseni): kimlik + tahsilat durur."""
    satis = await _satis(client, admin_headers, proje, unite, musteri)
    plan = await _plan_uret(client, admin_headers, satis["id"])
    pesinat_id = plan["items"][0]["id"]
    await client.post(
        f"/sales/installments/{pesinat_id}/pay",
        json={"amount": "100000.00"},
        headers=admin_headers,
    )

    resp = await client.put(
        f"/sales/{satis['id']}/installments",
        json={
            "items": [
                _satir(0, "440000.00", "2026-08-15"),
                _satir(1, "1000000.00", "2026-09-01"),
            ]
        },
        headers=admin_headers,
    )

    pesinat = resp.json()["items"][0]
    assert pesinat["id"] == pesinat_id
    assert pesinat["paid_amount"] == "100000.00"
    assert pesinat["due_date"] == "2026-08-15"


async def test_ayni_sira_numarasi_iki_kez_gonderilemez_409(
    client, admin_headers, proje, unite, musteri
):
    satis = await _satis(client, admin_headers, proje, unite, musteri)

    resp = await client.put(
        f"/sales/{satis['id']}/installments",
        json={
            "items": [
                _satir(1, "720000.00", "2026-09-01"),
                _satir(1, "720000.00", "2026-10-01"),
            ]
        },
        headers=admin_headers,
    )

    assert resp.status_code == 409


async def test_put_denetim_satiri_yazar(client, admin_headers, proje, unite, musteri, db_session):
    satis = await _satis(client, admin_headers, proje, unite, musteri)
    await client.put(
        f"/sales/{satis['id']}/installments",
        json={"items": [_satir(1, "1440000.00", "2026-09-01")]},
        headers=admin_headers,
    )

    kayitlar = (await db_session.execute(select(AuditLog))).scalars().all()
    assert any("Ödeme planı güncellendi" in k.detail for k in kayitlar)


# --- 3) pay (§8 S2) ---


async def test_kismi_odeme_paid_at_yazmaz(client, admin_headers, proje, unite, musteri):
    """Kısmi ödeme desteklidir: `paid_amount` artar, `paid_at` HÂLÂ boştur."""
    satis = await _satis(client, admin_headers, proje, unite, musteri)
    plan = await _plan_uret(client, admin_headers, satis["id"])

    resp = await client.post(
        f"/sales/installments/{plan['items'][0]['id']}/pay",
        json={"amount": "40000.00"},
        headers=admin_headers,
    )

    assert resp.status_code == 200, resp.text
    govde = resp.json()
    assert govde["paid_amount"] == "40000.00"
    assert govde["remaining_amount"] == "400000.00"
    assert govde["paid_at"] is None


async def test_tam_odeme_paid_at_yazar(client, admin_headers, proje, unite, musteri):
    satis = await _satis(client, admin_headers, proje, unite, musteri)
    plan = await _plan_uret(client, admin_headers, satis["id"])
    taksit_id = plan["items"][0]["id"]

    await client.post(
        f"/sales/installments/{taksit_id}/pay",
        json={"amount": "40000.00"},
        headers=admin_headers,
    )
    resp = await client.post(
        f"/sales/installments/{taksit_id}/pay",
        json={"amount": "400000.00"},
        headers=admin_headers,
    )

    govde = resp.json()
    assert govde["paid_amount"] == "440000.00"
    assert govde["remaining_amount"] == "0.00"
    assert govde["paid_at"] is not None


async def test_asiri_odeme_422(client, admin_headers, proje, unite, musteri):
    satis = await _satis(client, admin_headers, proje, unite, musteri)
    plan = await _plan_uret(client, admin_headers, satis["id"])

    resp = await client.post(
        f"/sales/installments/{plan['items'][0]['id']}/pay",
        json={"amount": "440000.01"},
        headers=admin_headers,
    )

    assert resp.status_code == 422
    assert resp.json()["detail"] == PAYMENT_EXCEEDS_INSTALLMENT


async def test_tahsilat_satis_turevlerine_yansir(client, admin_headers, proje, unite, musteri):
    """S153-154 "Tahsil Edilen"/"Kalan" kolonları — T3 türevleri tahsilatı görür."""
    satis = await _satis(client, admin_headers, proje, unite, musteri)
    plan = await _plan_uret(client, admin_headers, satis["id"])
    await client.post(
        f"/sales/installments/{plan['items'][0]['id']}/pay",
        json={"amount": "440000.00"},
        headers=admin_headers,
    )

    detay = (await client.get(f"/sales/{satis['id']}", headers=admin_headers)).json()
    assert detay["paid_amount"] == "440000.00"
    assert detay["remaining_amount"] == "1000000.00"
    assert detay["installment_paid_count"] == 0  # peşinat taksit SAYILMAZ (T3 kuralı)


async def test_odeme_denetim_satiri_yazar(client, admin_headers, proje, unite, musteri, db_session):
    satis = await _satis(client, admin_headers, proje, unite, musteri)
    plan = await _plan_uret(client, admin_headers, satis["id"])
    await client.post(
        f"/sales/installments/{plan['items'][0]['id']}/pay",
        json={"amount": "40000.00"},
        headers=admin_headers,
    )

    kayitlar = (await db_session.execute(select(AuditLog))).scalars().all()
    assert any("Taksit tahsilatı" in k.detail for k in kayitlar)


# --- 4) IDOR (spec §6) ---


async def test_kapsam_disi_kullanici_plan_ucundan_404_alir(
    client, admin_headers, kapsam_disi_headers, proje, unite, musteri
):
    satis = await _satis(client, admin_headers, proje, unite, musteri)

    uretim = await client.post(f"/sales/{satis['id']}/generate-plan", headers=kapsam_disi_headers)
    kaydet = await client.put(
        f"/sales/{satis['id']}/installments",
        json={"items": [_satir(1, "1440000.00", "2026-09-01")]},
        headers=kapsam_disi_headers,
    )

    assert uretim.status_code == 404
    assert uretim.json()["detail"] == SALE_MISSING
    assert kaydet.status_code == 404


async def test_kapsam_disi_kullanici_taksit_odeyemez_404(
    client, admin_headers, kapsam_disi_headers, proje, unite, musteri
):
    """Taksit → satış → proje zinciri: görünmeyen taksit VAR OLMAYANLA aynı yanıtı verir."""
    satis = await _satis(client, admin_headers, proje, unite, musteri)
    plan = await _plan_uret(client, admin_headers, satis["id"])

    gorunmeyen = await client.post(
        f"/sales/installments/{plan['items'][0]['id']}/pay",
        json={"amount": "1.00"},
        headers=kapsam_disi_headers,
    )
    yok = await client.post(
        f"/sales/installments/{uuid.uuid4()}/pay",
        json={"amount": "1.00"},
        headers=kapsam_disi_headers,
    )

    assert gorunmeyen.status_code == 404
    assert yok.status_code == 404
    assert gorunmeyen.json() == yok.json() == {"detail": INSTALLMENT_MISSING}


# --- 5) İzin (spec §8 S1) ---


async def test_view_seviyesi_plan_yazamaz_403(
    client, admin_headers, view_headers, proje, unite, musteri
):
    """`sales=view` okur, YAZAMAZ; üç uç da `sales:full` ister."""
    satis = await _satis(client, admin_headers, proje, unite, musteri)
    plan = await _plan_uret(client, admin_headers, satis["id"])

    uretim = await client.post(f"/sales/{satis['id']}/generate-plan", headers=view_headers)
    kaydet = await client.put(
        f"/sales/{satis['id']}/installments",
        json={"items": [_satir(1, "1440000.00", "2026-09-01")]},
        headers=view_headers,
    )
    odeme = await client.post(
        f"/sales/installments/{plan['items'][0]['id']}/pay",
        json={"amount": "1.00"},
        headers=view_headers,
    )

    assert uretim.status_code == 403
    assert kaydet.status_code == 403
    assert odeme.status_code == 403


async def test_gecikme_faizi_tahakkuk_kaydi_uretmez(
    client, admin_headers, proje, unite, musteri, db_session
):
    """§8 S5: gecikme faizi YALNIZ gösterim türevidir — vadesi geçmiş taksit için
    ek satır/borç kaydı YAZILMAZ (F163 `late_fee_monthly_pct` yalnız saklanır)."""
    dun = (date.today() - timedelta(days=40)).isoformat()
    satis = await _satis(
        client,
        admin_headers,
        proje,
        unite,
        musteri,
        down_payment="0.00",
        installment_count=1,
        first_installment_date=dun,
        late_fee_monthly_pct="2.50",
    )
    plan = await _plan_uret(client, admin_headers, satis["id"])

    assert len(plan["items"]) == 1
    assert plan["items"][0]["amount"] == "1440000.00"
    satirlar = (
        (
            await db_session.execute(
                select(SaleInstallment).where(SaleInstallment.sale_id == uuid.UUID(satis["id"]))
            )
        )
        .scalars()
        .all()
    )
    assert len(satirlar) == 1
