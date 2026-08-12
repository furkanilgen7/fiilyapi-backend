"""SA T4 — `GET /purchasing/summary` (SAT 69-86 + SIP 38-43 KPI'ları).

Mockup gerekçeleri (kart etiketleri BİREBİR):
* SAT 71-72 "Açık Talepler"      → `open_requests`
* SAT 75-76 "Teklif Bekleniyor"  → `quote_wait_requests`
* SAT 79-80 "Bu Ay Sipariş"      → `orders_this_month_total`
* SAT 83-84 "Onay Bekleyen"      → `pending_approval_requests`
* SIP 39 "Aktif Siparişler"      → `active_orders`
* SIP 40 "Bu Ay Toplam"          → `orders_this_month_total` (SAT ile TEK türetme)
* SIP 41 "Yolda"                 → `in_transit_orders`
* SIP 42 "Teslim Edildi"         → `delivered_orders`
"""

from datetime import UTC, datetime

from app.modules.procurement.models import PurchaseOrderStatus, PurchaseRequestStatus

_YOL = "/purchasing/summary"


async def _ozet(client, headers, **params):
    yanit = await client.get(_YOL, params=params, headers=headers)
    assert yanit.status_code == 200, yanit.text
    return yanit.json()


async def test_bos_kurulumda_tum_sayaclar_sifir(client, satinalma_headers):
    """Veri yokken KPI'lar 0'dır — alan hiç dönmemek ya da `null` olmak DEĞİL."""
    ozet = await _ozet(client, satinalma_headers)

    assert ozet == {
        "open_requests": 0,
        "quote_wait_requests": 0,
        "pending_approval_requests": 0,
        "orders_this_month_total": "0.00",
        "active_orders": 0,
        "in_transit_orders": 0,
        "delivered_orders": 0,
    }


async def test_talep_sayaclari_duruma_gore_ayrisir(
    client, satinalma_headers, gorunen_proje, talep_fabrikasi
):
    """ "Açık Talepler" = TASLAK OLMAYAN ve SONUÇLANMAMIŞ talepler.

    Taslak sayılmaz (kişisel yarım form), `delivered`/`rejected` de sayılmaz
    (kapanmış). Geriye `pending_approval + quote_wait + ordered` kalır — SAT'ın
    8 = 2 + 5 + 1 aritmetiği de bunu söyler.
    """
    for durum in (
        PurchaseRequestStatus.draft,
        PurchaseRequestStatus.pending_approval,
        PurchaseRequestStatus.pending_approval,
        PurchaseRequestStatus.quote_wait,
        PurchaseRequestStatus.ordered,
        PurchaseRequestStatus.delivered,
        PurchaseRequestStatus.rejected,
    ):
        await talep_fabrikasi(gorunen_proje, status=durum)

    ozet = await _ozet(client, satinalma_headers)

    assert ozet["pending_approval_requests"] == 2
    assert ozet["quote_wait_requests"] == 1
    assert ozet["open_requests"] == 4


async def test_siparis_sayaclari_ve_bu_ay_tutari(
    client, satinalma_headers, gorunen_proje, tedarikci_fabrikasi, siparis_fabrikasi
):
    """ "Aktif" = teslim EDİLMEMİŞ (approved + in_transit) — `pending_orders`
    zarfıyla TEK kaynak. Tutar YALNIZ para kartında ay süzgeçlidir."""
    tedarikci = await tedarikci_fabrikasi("Demirsan A.Ş.")
    await siparis_fabrikasi(gorunen_proje, tedarikci, total_amount="100000.00")
    await siparis_fabrikasi(
        gorunen_proje,
        tedarikci,
        total_amount="250000.50",
        status=PurchaseOrderStatus.in_transit,
    )
    await siparis_fabrikasi(
        gorunen_proje, tedarikci, total_amount="40000.00", status=PurchaseOrderStatus.delivered
    )

    ozet = await _ozet(client, satinalma_headers)

    assert ozet["active_orders"] == 2
    assert ozet["in_transit_orders"] == 1
    assert ozet["delivered_orders"] == 1
    # Üç sipariş de BU AY açıldı (fabrika `created_at`i sunucu saatidir).
    assert ozet["orders_this_month_total"] == "390000.50"


async def test_gorunmeyen_projenin_verisi_sizmaz(
    client,
    satinalma_headers,
    gorunmeyen_proje,
    tedarikci_fabrikasi,
    siparis_fabrikasi,
    talep_fabrikasi,
):
    """IDOR: kapsam süzgeci HER sayaçta koşar — para dahil."""
    await talep_fabrikasi(gorunmeyen_proje, status=PurchaseRequestStatus.pending_approval)
    await siparis_fabrikasi(
        gorunmeyen_proje, await tedarikci_fabrikasi("Demirsan A.Ş."), total_amount="999999.00"
    )

    ozet = await _ozet(client, satinalma_headers)

    assert ozet["pending_approval_requests"] == 0
    assert ozet["active_orders"] == 0
    assert ozet["orders_this_month_total"] == "0.00"


async def test_proje_suzgeci_kapsamin_USTUNE_gecer(
    client,
    admin_headers,
    gorunen_proje,
    gorunmeyen_proje,
    tedarikci_fabrikasi,
    siparis_fabrikasi,
):
    """`project_id` süzgeci kapsamı GENİŞLETMEZ, daraltır (`list_orders` deseni)."""
    tedarikci = await tedarikci_fabrikasi("Demirsan A.Ş.")
    await siparis_fabrikasi(gorunen_proje, tedarikci, total_amount="100000.00")
    await siparis_fabrikasi(gorunmeyen_proje, tedarikci, total_amount="200000.00")

    hepsi = await _ozet(client, admin_headers)
    tek = await _ozet(client, admin_headers, project_id=str(gorunen_proje.id))

    assert hepsi["active_orders"] == 2
    assert tek["active_orders"] == 1
    assert tek["orders_this_month_total"] == "100000.00"


async def test_gecen_ayin_siparisi_tutara_girmez(
    client, satinalma_headers, seeded_db, gorunen_proje, tedarikci_fabrikasi, siparis_fabrikasi
):
    """ "Bu Ay" gerçekten AY süzgecidir; sayaçlar ise süzgeçsizdir."""
    siparis = await siparis_fabrikasi(
        gorunen_proje, await tedarikci_fabrikasi("Demirsan A.Ş."), total_amount="70000.00"
    )
    siparis.created_at = datetime(2020, 3, 15, tzinfo=UTC)
    await seeded_db.flush()

    ozet = await _ozet(client, satinalma_headers)

    assert ozet["orders_this_month_total"] == "0.00"
    assert ozet["active_orders"] == 1


async def test_okuma_izni_sart(client, yetkisiz_headers):
    yanit = await client.get(_YOL, headers=yetkisiz_headers)
    assert yanit.status_code == 403, yanit.text


async def test_kimliksiz_401(client):
    assert (await client.get(_YOL)).status_code == 401


# --- ST'nin `pending_orders` zarfı GERÇEĞE döndü ---


async def _stok_ozeti_zarfi(client, headers) -> dict:
    yanit = await client.get("/stock/summary", headers=headers)
    assert yanit.status_code == 200, yanit.text
    return yanit.json()["kpis"]["pending_orders"]


async def test_bekleyen_siparis_zarfi_artik_DOLUDUR(
    client, satinalma_headers, gorunen_proje, tedarikci_fabrikasi, siparis_fabrikasi
):
    """E3 81 "Bekleyen Sipariş" = `approved` + `in_transit` sipariş SAYISI.

    ⚠️ İki anahtar KARIŞTIRILMAZ: `purchasing` ST zarfının etiketi,
    `procurement` izin matrisinin modül anahtarıdır. Zarf artık DOLU olduğu
    için `pending_module` **null**dur (aşağıdaki sözleşme testi).
    """
    tedarikci = await tedarikci_fabrikasi("Demirsan A.Ş.")
    await siparis_fabrikasi(gorunen_proje, tedarikci)
    await siparis_fabrikasi(gorunen_proje, tedarikci, status=PurchaseOrderStatus.in_transit)
    await siparis_fabrikasi(gorunen_proje, tedarikci, status=PurchaseOrderStatus.delivered)

    zarf = await _stok_ozeti_zarfi(client, satinalma_headers)

    assert zarf == {"available": True, "value": "2", "pending_module": None}


async def test_zarf_sozlesmesi_iki_yonlu(
    client, satinalma_headers, gorunen_proje, tedarikci_fabrikasi, siparis_fabrikasi
):
    """`available=true ⇒ pending_module is None` (ve tersi).

    P10 dersi: zarf ELLE kurulmaz (`available`/`value`/`pending_module` üçlüsü
    tutarsız kurulduğunda pydantic doğrulayıcısı 500 üretir); tek kapı
    `projects.schemas.metric`tir. Sıfır sipariş de DOLU bir zarftır — "hiç
    bekleyen sipariş yok" ile "veri kaynağı yok" AYNI ŞEY DEĞİLDİR.
    """
    bos = await _stok_ozeti_zarfi(client, satinalma_headers)
    assert bos["available"] is True
    assert bos["pending_module"] is None
    assert bos["value"] == "0"

    await siparis_fabrikasi(gorunen_proje, await tedarikci_fabrikasi("Demirsan A.Ş."))
    dolu = await _stok_ozeti_zarfi(client, satinalma_headers)
    assert (dolu["pending_module"] is None) is dolu["available"]


async def test_zarf_gorunmeyen_projeyi_saymaz(
    client, satinalma_headers, gorunmeyen_proje, tedarikci_fabrikasi, siparis_fabrikasi
):
    await siparis_fabrikasi(gorunmeyen_proje, await tedarikci_fabrikasi("Demirsan A.Ş."))

    assert (await _stok_ozeti_zarfi(client, satinalma_headers))["value"] == "0"


async def test_teslim_edilen_siparis_zarftan_duser(
    client,
    satinalma_headers,
    seeded_db,
    gorunen_proje,
    tedarikci_fabrikasi,
    siparis_fabrikasi,
    depo_fabrikasi,
    kart_fabrikasi,
):
    """Zincirin zarfa yansıması: stok girişi sayacı DÜŞÜRÜR (uçtan uca)."""
    siparis = await siparis_fabrikasi(gorunen_proje, await tedarikci_fabrikasi("Demirsan A.Ş."))
    depo = await depo_fabrikasi("Merkez Depo")
    kart = await kart_fabrikasi("DMR-0012")
    assert (await _stok_ozeti_zarfi(client, satinalma_headers))["value"] == "1"

    yanit = await client.post(
        "/stock/entries",
        json={
            "entry_type": "purchase",
            "entry_date": "2026-08-12",
            "warehouse_id": str(depo.id),
            "purchase_order_id": str(siparis.id),
            "lines": [{"item_id": str(kart.id), "quantity": "5.000", "unit_price": "100.00"}],
        },
        headers=satinalma_headers,
    )
    assert yanit.status_code == 201, yanit.text

    assert (await _stok_ozeti_zarfi(client, satinalma_headers))["value"] == "0"
