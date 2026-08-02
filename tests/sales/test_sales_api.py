"""P8 T3 — `unit_sales` çekirdeği: POST/GET/PATCH/DELETE (spec §2, §4, §5).

Mockup `Form - Daire Satisi.dc.html` (F) satır numaraları:
- 54-56 proje / blok-ünite / satış tipi · 60 "Liste Fiyatı" (F84 readonly ikizi)
- 62 "Maliyet" ve 90 "Bu Satıştan Kâr" → `pending_module: "project_costs"` (karar 3)
- 70-76 alıcı (T2'de kapandı) · 75 "Satış Danışmanı"
- 84-87 liste fiyatı / indirim / satış bedeli / KDV
- 99-106 ödeme planı tipi / peşinat / taksit sayısı / ilk taksit / vade farkı
- 156-158 tapu devir koşulu / planlanan tapu / teslim · 161-163 kat irtifakı /
  ipotek / gecikme faizi
- 169-202 satış belgeleri → `pending_module: "documents"` · 207 peşinat faturası
  → `pending_module: "invoicing"`

Mockup `Satış Yönetimi.dc.html` (S) liste kolonları 150-212:
- 150 "Ünite" · 151 "Alıcı" · 152 "Satış Bedeli" · 153 "Tahsil Edilen" ·
  154 "Kalan" · 155 "Ödeme Planı" · 156 "Durum" · 205-215 TOPLAM satırı
- 166 "Tapu Devredildi" · 180 "⚠ 2 taksit gecikmiş" · 188 "Kapora alındı · 15 gün"
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.modules.audit.models import AuditLog
from app.modules.sales.guards import (
    LANDOWNER_UNIT_NOT_SELLABLE,
    SALE_MISSING,
    SALE_NOT_DELETABLE,
    UNIT_ALREADY_SOLD,
    UNIT_MISSING,
)
from app.modules.sales.models import SaleInstallment, UnitSale, UnitSaleStatus
from app.modules.units.models import Unit, UnitSalesStatus

TAM_GOVDE = {
    "sale_type": "sale",  # F56
    "discount_amount": "40000.00",  # F85
    "sale_price": "1440000.00",  # F86
    "vat_pct": "1.00",  # F87
    "deed_condition": "full_payment",  # F156
    "planned_deed_date": "2027-09-01",  # F157
    "delivery_date": "2026-12-31",  # F158
    "has_condominium_easement": True,  # F161
    "has_mortgage": False,  # F162
    "late_fee_monthly_pct": "2.50",  # F163
    "payment_plan_type": "down_payment_installments",  # F99
    "down_payment": "440000.00",  # F103
    "installment_count": 12,  # F104
    "first_installment_date": "2026-09-01",  # F105
    "term_interest_pct": "0.00",  # F106
}


def _govde(unite, musteri, **degisiklikler) -> dict:
    return TAM_GOVDE | {
        "unit_id": str(unite.id),
        "customer_id": str(musteri.id),
        **degisiklikler,
    }


async def _olustur(client, headers, proje, unite, musteri, **degisiklikler) -> dict:
    resp = await client.post(
        f"/projects/{proje.id}/sales",
        json=_govde(unite, musteri, **degisiklikler),
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _unite_durumu(session, unite_id) -> UnitSalesStatus | None:
    unit = (await session.execute(select(Unit).where(Unit.id == unite_id))).scalar_one()
    await session.refresh(unit)
    return unit.sales_status


# --- POST mutlu yol ---


@pytest.mark.asyncio
async def test_satis_olusturma_tum_alanlar(client, admin_headers, proje, unite, musteri):
    govde = await _olustur(client, admin_headers, proje, unite, musteri)

    assert govde["sale_type"] == "sale"
    assert govde["status"] == "active"
    assert govde["sale_price"] == "1440000.00"
    assert govde["discount_amount"] == "40000.00"
    assert govde["vat_pct"] == "1.00"
    assert govde["deed_condition"] == "full_payment"
    assert govde["planned_deed_date"] == "2027-09-01"
    assert govde["delivery_date"] == "2026-12-31"
    assert govde["has_condominium_easement"] is True
    assert govde["has_mortgage"] is False
    assert govde["late_fee_monthly_pct"] == "2.50"
    assert govde["payment_plan_type"] == "down_payment_installments"
    assert govde["down_payment"] == "440000.00"
    assert govde["installment_count"] == 12
    assert govde["first_installment_date"] == "2026-09-01"
    assert govde["term_interest_pct"] == "0.00"


@pytest.mark.asyncio
async def test_liste_fiyati_uniteden_anlik_goruntuye_alinir(
    client, admin_headers, proje, unite, musteri, db_session
):
    """F84 mockup'ta `readonly` — istemci göndermez, sunucu üniteden yazar.

    Ünite fiyatı sonradan değişse bile satış belgesindeki değer DEĞİŞMEMELİ.
    """
    govde = await _olustur(client, admin_headers, proje, unite, musteri)
    assert govde["list_price_snapshot"] == "1480000.00"

    unite.list_price = Decimal("1600000.00")
    await db_session.flush()

    detay = await client.get(f"/sales/{govde['id']}", headers=admin_headers)
    assert detay.json()["list_price_snapshot"] == "1480000.00"


@pytest.mark.asyncio
async def test_unite_ve_alici_etiketleri_doner(client, admin_headers, proje, unite, musteri):
    """S150-151: liste "A · Daire 12" ve alıcı adı + TCKN gösterir."""
    govde = await _olustur(client, admin_headers, proje, unite, musteri)

    assert govde["block_name"] == "A Blok"
    assert govde["unit_no"] == "12"
    assert govde["unit_label"] == "A Blok · 12"
    assert govde["customer_name"] == "Mehmet Aydın"
    assert govde["customer_national_id"] == "12345678901"
    assert govde["customer_tax_number"] is None


@pytest.mark.asyncio
async def test_maliyet_ve_kar_yer_tutucudur(client, admin_headers, proje, unite, musteri):
    """KALICI KARAR 3: F62 "Maliyet" ve F90 "Bu Satıştan Kâr" SÜTUNU YOKTUR.

    Sahte rakam yerine dürüst boş durum döner; F168-202 belgeler ve F206-207
    peşinat faturası da `pending_modules` listesinde bildirilir.
    """
    govde = await _olustur(client, admin_headers, proje, unite, musteri)

    assert govde["unit_cost"] == {
        "available": False,
        "value": None,
        "pending_module": "project_costs",
    }
    assert govde["sale_profit"] == {
        "available": False,
        "value": None,
        "pending_module": "project_costs",
    }
    assert govde["pending_modules"] == ["project_costs", "documents", "invoicing"]


@pytest.mark.asyncio
async def test_min_sale_price_altinda_satis_serbest(
    client, admin_headers, proje, unite, musteri, db_session
):
    """KALICI KARAR 2: `min_sale_price` zorlanmaz — uyarı bile üretilmez."""
    unite.min_sale_price = Decimal("1400000.00")
    await db_session.flush()

    govde = await _olustur(client, admin_headers, proje, unite, musteri, sale_price="900000.00")
    assert govde["sale_price"] == "900000.00"


# --- `units.sales_status` senkronu (spec §3) ---


@pytest.mark.asyncio
async def test_rezervasyon_uniteyi_reserved_yapar(
    client, admin_headers, proje, unite, musteri, db_session
):
    govde = await _olustur(client, admin_headers, proje, unite, musteri, sale_type="reservation")

    assert govde["status"] == "reservation"
    assert await _unite_durumu(db_session, unite.id) is UnitSalesStatus.reserved


@pytest.mark.asyncio
async def test_kesin_satis_uniteyi_sold_yapar(
    client, admin_headers, proje, unite, musteri, db_session
):
    await _olustur(client, admin_headers, proje, unite, musteri, sale_type="sale")
    assert await _unite_durumu(db_session, unite.id) is UnitSalesStatus.sold


@pytest.mark.asyncio
async def test_on_sozlesme_de_aktif_satistir(
    client, admin_headers, proje, unite, musteri, db_session
):
    """F56 üçüncü seçenek "Ön Sözleşme": kapora değildir → `active` + `sold`."""
    govde = await _olustur(client, admin_headers, proje, unite, musteri, sale_type="pre_contract")

    assert govde["status"] == "active"
    assert await _unite_durumu(db_session, unite.id) is UnitSalesStatus.sold


# --- Kapılar ---


@pytest.mark.asyncio
async def test_arsa_sahibi_unitesi_satilamaz(
    client, admin_headers, proje, arsa_sahibi_unitesi, musteri
):
    """Spec §8 S3 (kullanıcı kararı): `owner_side='landowner'` → 422."""
    resp = await client.post(
        f"/projects/{proje.id}/sales",
        json=_govde(arsa_sahibi_unitesi, musteri),
        headers=admin_headers,
    )

    assert resp.status_code == 422
    assert resp.json()["detail"] == LANDOWNER_UNIT_NOT_SELLABLE


@pytest.mark.asyncio
async def test_ikinci_acik_kayit_409(client, admin_headers, proje, unite, musteri):
    await _olustur(client, admin_headers, proje, unite, musteri)

    resp = await client.post(
        f"/projects/{proje.id}/sales", json=_govde(unite, musteri), headers=admin_headers
    )

    assert resp.status_code == 409
    assert resp.json()["detail"] == UNIT_ALREADY_SOLD


@pytest.mark.asyncio
async def test_iptal_edilen_kayittan_sonra_yeni_satis_acilabilir(
    client, admin_headers, proje, unite, musteri, db_session
):
    """`uq_unit_sales_open_unit` kısmi indeksi `cancelled`ı KAPSAMAZ."""
    ilk = await _olustur(client, admin_headers, proje, unite, musteri)
    kayit = (
        await db_session.execute(select(UnitSale).where(UnitSale.id == uuid.UUID(ilk["id"])))
    ).scalar_one()
    kayit.status = UnitSaleStatus.cancelled
    await db_session.flush()

    resp = await client.post(
        f"/projects/{proje.id}/sales", json=_govde(unite, musteri), headers=admin_headers
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["id"] != ilk["id"]


@pytest.mark.asyncio
async def test_baska_projenin_unitesi_404(client, admin_headers, proje, yabanci_unite, musteri):
    """Ünite proje sınırını aşamaz; varlığı da sızdırılmaz (units IDOR-9 deseni)."""
    resp = await client.post(
        f"/projects/{proje.id}/sales", json=_govde(yabanci_unite, musteri), headers=admin_headers
    )

    assert resp.status_code == 404
    assert resp.json()["detail"] == UNIT_MISSING


@pytest.mark.asyncio
async def test_olmayan_unite_404(client, admin_headers, proje, unite, musteri):
    resp = await client.post(
        f"/projects/{proje.id}/sales",
        json=_govde(unite, musteri) | {"unit_id": str(uuid.uuid4())},
        headers=admin_headers,
    )

    assert resp.status_code == 404
    assert resp.json()["detail"] == UNIT_MISSING


@pytest.mark.asyncio
async def test_olmayan_musteri_404(client, admin_headers, proje, unite, musteri):
    resp = await client.post(
        f"/projects/{proje.id}/sales",
        json=_govde(unite, musteri) | {"customer_id": str(uuid.uuid4())},
        headers=admin_headers,
    )

    assert resp.status_code == 404


# --- Danışman anlık görüntüsü (F75) ---


@pytest.mark.asyncio
async def test_danisman_adi_anlik_goruntuye_alinir(
    client, admin_headers, proje, unite, musteri, user_factory
):
    """`sites.manager_name` deseni: FK verilir, ad kullanıcıdan doldurulur."""
    danisman = await user_factory(
        email="danisman@sales.co",
        password="parola1234",
        role_key="patron",
        full_name="Elif Yıldırım",
    )

    govde = await _olustur(
        client, admin_headers, proje, unite, musteri, advisor_user_id=str(danisman.id)
    )

    assert govde["advisor_user_id"] == str(danisman.id)
    assert govde["advisor_name"] == "Elif Yıldırım"


@pytest.mark.asyncio
async def test_danisman_verilmezse_ad_bos(client, admin_headers, proje, unite, musteri):
    govde = await _olustur(client, admin_headers, proje, unite, musteri)
    assert govde["advisor_user_id"] is None
    assert govde["advisor_name"] is None


@pytest.mark.asyncio
async def test_olmayan_danisman_422(client, admin_headers, proje, unite, musteri):
    """`sites._resolve_user_name` gerekçesi: istenen kaynak SATIŞTIR, kullanıcı

    burada bir ALAN DEĞERİDİR — 404 dönmek "bu UUID'li kullanıcı yok" bilgisini
    satış ucundan sızdırmak olurdu.
    """
    resp = await client.post(
        f"/projects/{proje.id}/sales",
        json=_govde(unite, musteri) | {"advisor_user_id": str(uuid.uuid4())},
        headers=admin_headers,
    )

    assert resp.status_code == 422


# --- Liste (S150-212) ---


@pytest.mark.asyncio
async def test_liste_turevleri_taksitlerden_hesaplanir(
    client, admin_headers, proje, unite, musteri, db_session
):
    """S153-155: "Tahsil Edilen" / "Kalan" TÜREVDİR — kolon açılmaz.

    S155 "12 taksit · 8/12" ve S180 "⚠ 2 taksit gecikmiş" de aynı satırlardan.
    """
    satis = await _olustur(client, admin_headers, proje, unite, musteri)
    sale_id = uuid.UUID(satis["id"])
    dun = date.today() - timedelta(days=1)
    yarin = date.today() + timedelta(days=1)
    db_session.add_all(
        [
            SaleInstallment(
                sale_id=sale_id,
                sequence_no=0,
                label="Peşinat",
                due_date=dun,
                amount=Decimal("440000.00"),
                paid_amount=Decimal("440000.00"),
            ),
            SaleInstallment(
                sale_id=sale_id,
                sequence_no=1,
                label="1 / 2",
                due_date=dun,
                amount=Decimal("500000.00"),
                paid_amount=Decimal("100000.00"),
            ),
            SaleInstallment(
                sale_id=sale_id,
                sequence_no=2,
                label="2 / 2",
                due_date=yarin,
                amount=Decimal("500000.00"),
                paid_amount=Decimal("0.00"),
            ),
        ]
    )
    await db_session.flush()

    resp = await client.get(f"/projects/{proje.id}/sales", headers=admin_headers)

    assert resp.status_code == 200, resp.text
    satir = resp.json()["items"][0]
    assert satir["paid_amount"] == "540000.00"
    assert satir["remaining_amount"] == "900000.00"
    assert satir["installment_total"] == 2
    assert satir["installment_paid_count"] == 0
    assert satir["overdue_installment_count"] == 1


@pytest.mark.asyncio
async def test_plansiz_satista_turevler_sifir(client, admin_headers, proje, unite, musteri):
    """S190 "Belirlenmedi": plan henüz üretilmemişse tahsilat 0, kalan = bedel."""
    await _olustur(client, admin_headers, proje, unite, musteri)

    resp = await client.get(f"/projects/{proje.id}/sales", headers=admin_headers)

    satir = resp.json()["items"][0]
    assert satir["paid_amount"] == "0.00"
    assert satir["remaining_amount"] == "1440000.00"
    assert satir["installment_total"] == 0
    assert satir["overdue_installment_count"] == 0


@pytest.mark.asyncio
async def test_liste_toplamlari(client, admin_headers, proje, unite, ikinci_unite, musteri):
    """S205-215 TOPLAM satırı — satır türevlerinin aynı kaynaktan toplamı."""
    await _olustur(client, admin_headers, proje, unite, musteri, sale_price="1000000.00")
    await _olustur(client, admin_headers, proje, ikinci_unite, musteri, sale_price="500000.00")

    resp = await client.get(f"/projects/{proje.id}/sales", headers=admin_headers)

    toplam = resp.json()["totals"]
    assert toplam["count"] == 2
    assert toplam["sale_price_total"] == "1500000.00"
    assert toplam["paid_total"] == "0.00"
    assert toplam["remaining_total"] == "1500000.00"


@pytest.mark.asyncio
async def test_liste_yalniz_o_projenin_satislarini_doner(
    client, admin_headers, proje, baska_proje, unite, yabanci_unite, musteri
):
    await _olustur(client, admin_headers, proje, unite, musteri)
    await _olustur(client, admin_headers, baska_proje, yabanci_unite, musteri)

    resp = await client.get(f"/projects/{proje.id}/sales", headers=admin_headers)

    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["unit_id"] == str(unite.id)


# --- Detay / güncelleme ---


@pytest.mark.asyncio
async def test_detay_200(client, admin_headers, proje, unite, musteri):
    satis = await _olustur(client, admin_headers, proje, unite, musteri)

    resp = await client.get(f"/sales/{satis['id']}", headers=admin_headers)

    assert resp.status_code == 200
    assert resp.json()["id"] == satis["id"]


@pytest.mark.asyncio
async def test_olmayan_satis_404(client, admin_headers):
    resp = await client.get(f"/sales/{uuid.uuid4()}", headers=admin_headers)

    assert resp.status_code == 404
    assert resp.json()["detail"] == SALE_MISSING


@pytest.mark.asyncio
async def test_patch_kismi_gunceller(client, admin_headers, proje, unite, musteri):
    satis = await _olustur(client, admin_headers, proje, unite, musteri)

    resp = await client.patch(
        f"/sales/{satis['id']}",
        json={"sale_price": "1400000.00", "has_mortgage": True},
        headers=admin_headers,
    )

    assert resp.status_code == 200, resp.text
    govde = resp.json()
    assert govde["sale_price"] == "1400000.00"
    assert govde["has_mortgage"] is True
    # Gönderilmeyen alan DEĞİŞMEZ.
    assert govde["discount_amount"] == "40000.00"


@pytest.mark.asyncio
async def test_patch_govdesinde_status_ve_unit_id_yoktur(
    client, admin_headers, proje, unite, musteri, db_session
):
    """Durum geçişleri T5'in (`activate`/`transfer-deed`/`cancel`) işidir; ünite

    değişimi ise iki ünitenin senkronunu ve tek-açık-kayıt tekliğini birlikte
    ilgilendirir. İkisi de `UnitSaleUpdate` şemasında YOKTUR → sessizce yok sayılır.
    """
    satis = await _olustur(client, admin_headers, proje, unite, musteri, sale_type="reservation")

    resp = await client.patch(
        f"/sales/{satis['id']}",
        json={"status": "deed_transferred", "unit_id": str(uuid.uuid4())},
        headers=admin_headers,
    )

    assert resp.status_code == 200
    assert resp.json()["status"] == "reservation"
    assert resp.json()["unit_id"] == str(unite.id)
    assert await _unite_durumu(db_session, unite.id) is UnitSalesStatus.reserved


@pytest.mark.asyncio
async def test_patch_danisman_adini_tazeler(
    client, admin_headers, proje, unite, musteri, user_factory
):
    satis = await _olustur(client, admin_headers, proje, unite, musteri)
    danisman = await user_factory(
        email="burak@sales.co", password="parola1234", role_key="patron", full_name="Burak Aksoy"
    )

    resp = await client.patch(
        f"/sales/{satis['id']}",
        json={"advisor_user_id": str(danisman.id)},
        headers=admin_headers,
    )

    assert resp.json()["advisor_name"] == "Burak Aksoy"


@pytest.mark.asyncio
async def test_patch_danisman_temizlenince_ad_da_temizlenir(
    client, admin_headers, proje, unite, musteri, user_factory
):
    danisman = await user_factory(
        email="elif@sales.co", password="parola1234", role_key="patron", full_name="Elif Yıldırım"
    )
    satis = await _olustur(
        client, admin_headers, proje, unite, musteri, advisor_user_id=str(danisman.id)
    )

    resp = await client.patch(
        f"/sales/{satis['id']}", json={"advisor_user_id": None}, headers=admin_headers
    )

    assert resp.json()["advisor_user_id"] is None
    assert resp.json()["advisor_name"] is None


# --- Silme (spec §4: yalnız `reservation`) ---


@pytest.mark.asyncio
async def test_rezervasyon_silinir_ve_unite_listede_doner(
    client, admin_headers, proje, unite, musteri, db_session
):
    satis = await _olustur(client, admin_headers, proje, unite, musteri, sale_type="reservation")

    resp = await client.delete(f"/sales/{satis['id']}", headers=admin_headers)

    assert resp.status_code == 204
    assert await _unite_durumu(db_session, unite.id) is UnitSalesStatus.listed


@pytest.mark.asyncio
async def test_aktif_satis_silinemez(client, admin_headers, proje, unite, musteri):
    """`active`/`deed_transferred` SİLİNMEZ — iptal edilir (T5 `cancel`)."""
    satis = await _olustur(client, admin_headers, proje, unite, musteri, sale_type="sale")

    resp = await client.delete(f"/sales/{satis['id']}", headers=admin_headers)

    assert resp.status_code == 409
    assert resp.json()["detail"] == SALE_NOT_DELETABLE


@pytest.mark.asyncio
async def test_tapu_devredilmis_satis_silinemez(
    client, admin_headers, proje, unite, musteri, db_session
):
    satis = await _olustur(client, admin_headers, proje, unite, musteri)
    kayit = (
        await db_session.execute(select(UnitSale).where(UnitSale.id == uuid.UUID(satis["id"])))
    ).scalar_one()
    kayit.status = UnitSaleStatus.deed_transferred
    await db_session.flush()

    resp = await client.delete(f"/sales/{satis['id']}", headers=admin_headers)

    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_silinen_rezervasyondan_sonra_yeni_satis_acilabilir(
    client, admin_headers, proje, unite, musteri
):
    satis = await _olustur(client, admin_headers, proje, unite, musteri, sale_type="reservation")
    await client.delete(f"/sales/{satis['id']}", headers=admin_headers)

    resp = await client.post(
        f"/projects/{proje.id}/sales", json=_govde(unite, musteri), headers=admin_headers
    )

    assert resp.status_code == 201, resp.text


# --- Denetim günlüğü ---


@pytest.mark.asyncio
async def test_yazma_uclari_denetim_satiri_yazar(
    client, admin_headers, proje, unite, musteri, db_session
):
    satis = await _olustur(client, admin_headers, proje, unite, musteri, sale_type="reservation")
    await client.patch(f"/sales/{satis['id']}", json={"sale_price": "1.00"}, headers=admin_headers)
    await client.delete(f"/sales/{satis['id']}", headers=admin_headers)

    detaylar = [
        row.detail
        for row in (await db_session.execute(select(AuditLog))).scalars().all()
        if "satış" in row.detail.lower()
    ]

    assert any(d.startswith("Ünite satışı oluşturuldu") for d in detaylar)
    assert any(d.startswith("Ünite satışı güncellendi") for d in detaylar)
    assert any(d.startswith("Ünite satışı silindi") for d in detaylar)
    assert all("A Blok · 12" in d for d in detaylar)


@pytest.mark.asyncio
async def test_okuma_uclari_denetim_yazmaz(
    client, admin_headers, proje, unite, musteri, db_session
):
    await _olustur(client, admin_headers, proje, unite, musteri)
    onceki = len((await db_session.execute(select(AuditLog))).scalars().all())

    await client.get(f"/projects/{proje.id}/sales", headers=admin_headers)

    assert len((await db_session.execute(select(AuditLog))).scalars().all()) == onceki
