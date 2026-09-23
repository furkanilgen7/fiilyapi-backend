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
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core import timezone
from app.modules.audit.models import AuditLog
from app.modules.sales.guards import (
    INSTALLMENT_AMOUNT_NOT_POSITIVE,
    INSTALLMENT_MISSING,
    INSTALLMENT_TOTAL_MISMATCH,
    PAID_INSTALLMENT_BELOW_PAID,
    PAID_INSTALLMENT_REMOVED,
    PAYMENT_EXCEEDS_INSTALLMENT,
    PLAN_BALANCE_UNCOVERED,
    PLAN_HAS_PAYMENTS,
    PLAN_INPUT_MISSING,
    PLAN_INSTALLMENT_TOO_SMALL,
    SALE_CANCELLED_NOT_WRITABLE,
    SALE_MISSING,
    SALE_PRICE_BELOW_COLLECTED,
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
    assert satirlar[0]["due_date"] == timezone.today().isoformat()  # F120 "Sözleşme imzasında"
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
    dun = (timezone.today() - timedelta(days=40)).isoformat()
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


# --- 6) Sıfır tutarlı plan satırı DOĞMAZ (Σ == sale_price yapısal olarak) ---


async def test_sifir_tutarli_taksit_satiri_kabul_edilmez_422(
    client, admin_headers, proje, unite, musteri
):
    """0,00 tutarlı satır DOĞDUĞU ANDA "tam ödendi" sayılır — gövdeden reddedilir.

    `repository.installment_stats` "ödenmiş"i `paid_amount >= amount` ile ölçer;
    sıfır tutarlı satırda `0 >= 0` DOĞRUDUR, dolayısıyla satır hiç tahsilat
    yokken hem `installment_paid_count`a girer hem de `_sync_paid_at` ile
    `paid_at` damgası alır (toplam yine `sale_price`a eşit olduğu için
    `INSTALLMENT_TOTAL_MISMATCH` bu gövdeyi GEÇİRİR).
    """
    satis = await _satis(client, admin_headers, proje, unite, musteri)

    resp = await client.put(
        f"/sales/{satis['id']}/installments",
        json={
            "items": [
                _satir(0, "1440000.00", "2026-08-01"),
                _satir(1, "0.00", "2026-09-01"),
            ]
        },
        headers=admin_headers,
    )

    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == INSTALLMENT_AMOUNT_NOT_POSITIVE


async def test_pesinat_bedelin_tamamiysa_taksit_uretilmez_422(
    client, admin_headers, proje, unite, musteri
):
    """`down_payment == sale_price` + taksit sayısı > 0 → taksitlendirilecek bakiye 0.

    `build_plan` bu hâlde `installment_count` adet 0,00 tutarlı satır üretir;
    satış listesi "12/12 ödendi · 0 gecikmiş" derken kalan borç 1.440.000'dir.
    """
    satis = await _satis(client, admin_headers, proje, unite, musteri, down_payment="1440000.00")

    resp = await client.post(f"/sales/{satis['id']}/generate-plan", headers=admin_headers)

    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == PLAN_INSTALLMENT_TOO_SMALL


async def test_taksitsiz_planda_pesinat_bedelin_tamamini_karsilamalidir_422(
    client, admin_headers, proje, unite, musteri
):
    """Peşinat var, taksit YOK, peşinat bedelin ALTINDA → plan eksik kalırdı.

    `plan.build_plan` bu hâlde `financed` bakiyesini DAĞITMADAN döner ve
    `total_amount` `sale_price`ın altında çıkar; oysa `PUT installments` aynı
    gövdeyi `INSTALLMENT_TOTAL_MISMATCH` ile reddeder — iki yazma yolu AYRIŞIR.
    """
    satis = await _satis(
        client,
        admin_headers,
        proje,
        unite,
        musteri,
        down_payment="440000.00",
        installment_count=0,
        first_installment_date=None,
    )

    resp = await client.post(f"/sales/{satis['id']}/generate-plan", headers=admin_headers)

    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == PLAN_BALANCE_UNCOVERED


# --- 7) Satış durumu kapısı: iptal edilmiş satışa plan/tahsilat YAZILMAZ ---


async def _iptal_et(client, headers, sale_id) -> None:
    resp = await client.post(
        f"/sales/{sale_id}/cancel", json={"reason": "Alıcı vazgeçti"}, headers=headers
    )
    assert resp.status_code == 200, resp.text


async def test_iptal_edilmis_satista_plan_uretilemez_409(
    client, admin_headers, proje, unite, musteri
):
    """İptal ünitenin vitrinini serbest bırakır (`listed`) — kayıt artık yazılabilir değil."""
    satis = await _satis(client, admin_headers, proje, unite, musteri)
    await _iptal_et(client, admin_headers, satis["id"])

    resp = await client.post(f"/sales/{satis['id']}/generate-plan", headers=admin_headers)

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == SALE_CANCELLED_NOT_WRITABLE


async def test_iptal_edilmis_satisin_plani_degistirilemez_409(
    client, admin_headers, proje, unite, musteri
):
    satis = await _satis(client, admin_headers, proje, unite, musteri)
    await _plan_uret(client, admin_headers, satis["id"])
    await _iptal_et(client, admin_headers, satis["id"])

    resp = await client.put(
        f"/sales/{satis['id']}/installments",
        json={"items": [_satir(1, "1440000.00", "2026-09-01")]},
        headers=admin_headers,
    )

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == SALE_CANCELLED_NOT_WRITABLE


async def test_iptal_edilmis_satisa_tahsilat_islenemez_409(
    client, admin_headers, proje, unite, musteri
):
    """Özet KPI'sı iptalleri SAYMAZ (`list_sale_rows(exclude_cancelled=True)`),

    dolayısıyla iptal edilmiş kayda işlenen para `collection.collected_amount`a
    hiç girmez — tahsil edilmiş ama hiçbir özete girmeyen para doğar.
    """
    satis = await _satis(client, admin_headers, proje, unite, musteri)
    plan = await _plan_uret(client, admin_headers, satis["id"])
    await _iptal_et(client, admin_headers, satis["id"])

    resp = await client.post(
        f"/sales/installments/{plan['items'][0]['id']}/pay",
        json={"amount": "50000.00"},
        headers=admin_headers,
    )

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == SALE_CANCELLED_NOT_WRITABLE


async def test_tapusu_devredilmis_satista_tahsilat_islenmeye_DEVAM_eder(
    client, admin_headers, proje, unite, musteri
):
    """KASITLI İSTİSNA — kapı `deed_transferred`i KAPSAMAZ.

    F156 `at_contract`/`after_down_payment` tapu devir koşullarında tapu
    taksitler bitmeden devredilir; kalan taksitlerin tahsilatı MEŞRUDUR. Bu test
    durum kapısının fazla geniş kurulmadığını bekçiler.
    """
    satis = await _satis(client, admin_headers, proje, unite, musteri)
    plan = await _plan_uret(client, admin_headers, satis["id"])
    devir = await client.post(f"/sales/{satis['id']}/transfer-deed", headers=admin_headers)
    assert devir.status_code == 200, devir.text

    resp = await client.post(
        f"/sales/installments/{plan['items'][0]['id']}/pay",
        json={"amount": "50000.00"},
        headers=admin_headers,
    )

    assert resp.status_code == 200, resp.text


# --- 8) `PATCH /sales/{id}` bedeli tahsilatın altına indiremez ---


async def test_bedel_tahsil_edilenin_altina_indirilemez_422(
    client, admin_headers, proje, unite, musteri
):
    """440.000 tahsil edilmiş bir satışta bedel 1,00'e çekilemez (422).

    Kapı yoksa `remaining_amount` −439.999,00 döner ve kayıt ÇIKIŞSIZ kalır:
    `generate-plan` 409 `PLAN_HAS_PAYMENTS`, `PUT installments` ise toplamı
    1,00'e indirmek için tahsilatlı satırı düşürmek (409) ya da tahsilatın
    altına çekmek (422) zorunda kalır.
    """
    satis = await _satis(client, admin_headers, proje, unite, musteri)
    plan = await _plan_uret(client, admin_headers, satis["id"])
    odeme = await client.post(
        f"/sales/installments/{plan['items'][0]['id']}/pay",
        json={"amount": "440000.00"},
        headers=admin_headers,
    )
    assert odeme.status_code == 200, odeme.text

    resp = await client.patch(
        f"/sales/{satis['id']}", json={"sale_price": "1.00"}, headers=admin_headers
    )

    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == SALE_PRICE_BELOW_COLLECTED

    oku = await client.get(f"/sales/{satis['id']}", headers=admin_headers)
    assert oku.json()["sale_price"] == "1440000.00"
    assert Decimal(oku.json()["remaining_amount"]) >= Decimal("0.00")


async def test_tahsilatin_ustundeki_bedel_degisimi_gecer_ve_plan_onarilabilir(
    client, admin_headers, proje, unite, musteri
):
    """POZİTİF KONTROL — kapı BEDELİ tahsilata bağlar, plan TOPLAMINA değil.

    Tahsilatın (440.000) üstünde kalan her bedel PATCH'ten geçer ve plan
    ardından `PUT installments` ile yeni bedele hizalanabilir. Kapı plan
    toplamına bağlansaydı bu gövde 422 olurdu ve satışın bedeli bir daha
    değiştirilemezdi.
    """
    satis = await _satis(client, admin_headers, proje, unite, musteri)
    plan = await _plan_uret(client, admin_headers, satis["id"])
    await client.post(
        f"/sales/installments/{plan['items'][0]['id']}/pay",
        json={"amount": "440000.00"},
        headers=admin_headers,
    )

    resp = await client.patch(
        f"/sales/{satis['id']}", json={"sale_price": "1200000.00"}, headers=admin_headers
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["remaining_amount"] == "760000.00"

    onarim = await client.put(
        f"/sales/{satis['id']}/installments",
        json={
            "items": [
                _satir(0, "440000.00", timezone.today().isoformat()),
                _satir(1, "760000.00", "2026-09-01"),
            ]
        },
        headers=admin_headers,
    )

    assert onarim.status_code == 200, onarim.text
    assert onarim.json()["total_amount"] == "1200000.00"


async def test_patch_bedel_degisimi_plani_gecici_hizasiz_birakir(
    client, admin_headers, proje, unite, musteri
):
    """BEKÇİ — `total_amount != sale_price` PATCH sonrası ULAŞILABİLİR bir hâldir.

    `SalePlanResponse` docstring'i eşitliği "HER ZAMAN" diye tanımlarsa yalan
    söyler: kapı (`guards.SALE_PRICE_BELOW_COLLECTED`) bedeli yalnız TAHSİLATA
    bağlar, plan TOPLAMINA değil (bkz. `guards.py:173-178`). PATCH'ten sonra
    `GET /sales/{id}/installments` yeni bedeli, plan ise ESKİ toplamı taşır —
    kullanıcı `PUT installments`/`generate-plan` ile hizalayana kadar.
    """
    satis = await _satis(client, admin_headers, proje, unite, musteri)
    await _plan_uret(client, admin_headers, satis["id"])

    resp = await client.patch(
        f"/sales/{satis['id']}", json={"sale_price": "1300000.00"}, headers=admin_headers
    )
    assert resp.status_code == 200, resp.text

    plan = await client.get(f"/sales/{satis['id']}/installments", headers=admin_headers)
    assert plan.status_code == 200, plan.text
    body = plan.json()
    assert body["sale_price"] == "1300000.00"
    assert body["total_amount"] == "1440000.00"
    assert body["total_amount"] != body["sale_price"]
