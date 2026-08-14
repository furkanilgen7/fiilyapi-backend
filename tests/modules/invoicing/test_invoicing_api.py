"""FAT-1 T3 — liste · oluştur · detay uçları (spec §7 md. 1, 3, 4).

## Bu dosyanın kilitlediği kararlar

1. **Sayfalama tavanı KIRPMAZ, 422 verir** (TB3/T2 kanonu): `limit=201` sessizce
   200'e çekilseydi ekran "hepsi bu kadar" sanır, eksik veri gösterirdi.
2. **İstemcinin GÖNDEREMEYECEĞİ alanlar 422'dir, sessizce yok sayılmaz**
   (`site_planning` `extra="forbid"` emsali): giden `invoice_no` · `line_total` ·
   `sort_order` ve hesaplanmış para alanlarının HEPSİ. Yok sayılsalardı kullanıcı
   gönderdiği tutarın yazıldığını sanırdı.
3. **Gelen faturada `invoice_no` İSTEMCİDENDİR ve ZORUNLUDUR** (S5) — satıcının
   kendi serisidir, sunucu üretemez.
4. **IDOR:** görünmeyen projenin faturası listede YOKTUR, `total`a da girmez ve
   tekil erişimde 404'tür. `project_id` NULL fatura (şirket geneli) modül izniyle
   GÖRÜNÜR.
5. **Gövde içi varlık referansı görünmüyorsa 404** (ST kanonu), 403 değil.
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.modules.audit.models import AuditAction, AuditLog
from app.modules.invoicing.models import InvoiceDirection, InvoiceStatus

_YOL = "/invoices"

_KALEM = {
    "description": "Kaba İnşaat İmalatı (Poz 03.001)",
    "unit": "m³",
    "quantity": "100.000",
    "unit_price": "1000.00",
    "vat_rate": "20.00",
}


def _giden(**alanlar) -> dict:
    govde = {
        "direction": "outgoing",
        "document_type": "einvoice",
        "issue_date": "2026-07-18",
        "party_name": "Güneşkent Gayrimenkul A.Ş.",
        "party_tax_number": "1234567890",
        "lines": [dict(_KALEM)],
    }
    govde.update(alanlar)
    return govde


def _gelen(**alanlar) -> dict:
    govde = _giden(direction="incoming", invoice_no="LT2026070184", party_name="Liebherr Kiralama")
    govde.update(alanlar)
    return govde


# --- Uç 1: liste ---


async def test_liste_zarfi_ve_varsayilan_limit(client, muhasebe_headers) -> None:
    resp = await client.get(_YOL, headers=muhasebe_headers)
    assert resp.status_code == 200, resp.text
    govde = resp.json()
    assert set(govde) == {"items", "total", "limit", "offset"}
    assert govde["limit"] == 50
    assert govde["offset"] == 0


async def test_limit_tavani_KIRPILMAZ_422(client, muhasebe_headers) -> None:
    """TB3/T2 kanonu — tavan aşımı sessizce 200'e çekilmez."""
    resp = await client.get(_YOL, headers=muhasebe_headers, params={"limit": 201})
    assert resp.status_code == 422, resp.text


async def test_limit_sifir_422(client, muhasebe_headers) -> None:
    resp = await client.get(_YOL, headers=muhasebe_headers, params={"limit": 0})
    assert resp.status_code == 422, resp.text


async def test_liste_yon_suzgeci(client, muhasebe_headers, fatura_fabrikasi, gorunen_proje) -> None:
    await fatura_fabrikasi(project=gorunen_proje, direction=InvoiceDirection.outgoing)
    await fatura_fabrikasi(
        project=gorunen_proje, direction=InvoiceDirection.incoming, status=InvoiceStatus.pending
    )
    resp = await client.get(_YOL, headers=muhasebe_headers, params={"direction": "incoming"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] == 1
    assert resp.json()["items"][0]["direction"] == "incoming"


async def test_liste_durum_suzgeci(
    client, muhasebe_headers, fatura_fabrikasi, gorunen_proje
) -> None:
    await fatura_fabrikasi(project=gorunen_proje, status=InvoiceStatus.draft)
    await fatura_fabrikasi(project=gorunen_proje, status=InvoiceStatus.sent)
    resp = await client.get(_YOL, headers=muhasebe_headers, params={"status": "sent"})
    assert resp.json()["total"] == 1


async def test_liste_proje_ve_santiye_suzgeci(
    client, muhasebe_headers, fatura_fabrikasi, gorunen_proje, gorunen_santiye
) -> None:
    await fatura_fabrikasi(project=gorunen_proje, site=gorunen_santiye)
    await fatura_fabrikasi(project=gorunen_proje)
    proje = await client.get(
        _YOL, headers=muhasebe_headers, params={"project_id": str(gorunen_proje.id)}
    )
    assert proje.json()["total"] == 2
    santiye = await client.get(
        _YOL, headers=muhasebe_headers, params={"site_id": str(gorunen_santiye.id)}
    )
    assert santiye.json()["total"] == 1


async def test_liste_q_fatura_no_ve_taraf_adinda_arar(
    client, muhasebe_headers, fatura_fabrikasi, gorunen_proje
) -> None:
    """FY:94 `Fatura ara...` — kutu İKİ sütunu birden arar."""
    await fatura_fabrikasi(
        project=gorunen_proje, invoice_no="FIL2026000184", party_name="Güneşkent Gayrimenkul A.Ş."
    )
    await fatura_fabrikasi(
        project=gorunen_proje, invoice_no="FIL2026000183", party_name="Çelik Holding A.Ş."
    )
    numara = await client.get(_YOL, headers=muhasebe_headers, params={"q": "000184"})
    assert numara.json()["total"] == 1
    taraf = await client.get(_YOL, headers=muhasebe_headers, params={"q": "çelik"})
    assert taraf.json()["total"] == 1


async def test_liste_tarih_araligi_suzgeci(
    client, muhasebe_headers, fatura_fabrikasi, gorunen_proje
) -> None:
    from datetime import date

    await fatura_fabrikasi(project=gorunen_proje, issue_date=date(2026, 7, 1))
    await fatura_fabrikasi(project=gorunen_proje, issue_date=date(2026, 7, 20))
    resp = await client.get(
        _YOL,
        headers=muhasebe_headers,
        params={"date_from": "2026-07-10", "date_to": "2026-07-31"},
    )
    assert resp.json()["total"] == 1


async def test_IDOR_gorunmeyen_projenin_faturasi_listede_YOK(
    client, muhasebe_headers, fatura_fabrikasi, gorunen_proje, gorunmeyen_proje
) -> None:
    """Kapsam süzgeci `total`a da uygulanır — sayfa dışı kalmış gibi görünmez."""
    await fatura_fabrikasi(project=gorunen_proje)
    await fatura_fabrikasi(project=gorunmeyen_proje)
    resp = await client.get(_YOL, headers=muhasebe_headers)
    assert resp.json()["total"] == 1
    assert all(s["project_id"] == str(gorunen_proje.id) for s in resp.json()["items"])


async def test_IDOR_kullanicinin_verdigi_gorunmeyen_proje_bos_doner(
    client, muhasebe_headers, fatura_fabrikasi, gorunmeyen_proje
) -> None:
    await fatura_fabrikasi(project=gorunmeyen_proje)
    resp = await client.get(
        _YOL, headers=muhasebe_headers, params={"project_id": str(gorunmeyen_proje.id)}
    )
    assert resp.json()["total"] == 0


async def test_projesiz_fatura_modul_izniyle_GORUNUR(
    client, muhasebe_headers, fatura_fabrikasi
) -> None:
    """§6 — şirket geneli fatura (`project_id` NULL) kapsam süzgecine takılmaz."""
    await fatura_fabrikasi(project=None)
    resp = await client.get(_YOL, headers=muhasebe_headers)
    assert resp.json()["total"] == 1
    assert resp.json()["items"][0]["project_id"] is None


async def test_liste_yetkisiz_403(client, yetkisiz_headers) -> None:
    resp = await client.get(_YOL, headers=yetkisiz_headers)
    assert resp.status_code == 403, resp.text


# --- Uç 3: oluştur ---


async def test_giden_fatura_olusur_numara_SUNUCUDAN_durum_draft(
    client, muhasebe_headers, gorunen_proje
) -> None:
    resp = await client.post(
        _YOL, headers=muhasebe_headers, json=_giden(project_id=str(gorunen_proje.id))
    )
    assert resp.status_code == 201, resp.text
    govde = resp.json()
    assert govde["invoice_no"].startswith("FIL")
    assert govde["status"] == "draft"
    assert govde["direction"] == "outgoing"


async def test_giden_faturada_para_amounts_modulunden_hesaplanir(
    client, muhasebe_headers, gorunen_proje
) -> None:
    """Sunucu kendi toplamını yazmaz: 100 × 1000 = 100.000 matrah, %20 KDV."""
    resp = await client.post(
        _YOL, headers=muhasebe_headers, json=_giden(project_id=str(gorunen_proje.id))
    )
    govde = resp.json()
    assert Decimal(govde["subtotal"]) == Decimal("100000.00")
    assert Decimal(govde["tax_base"]) == Decimal("100000.00")
    assert Decimal(govde["vat_amount"]) == Decimal("20000.00")
    assert Decimal(govde["total"]) == Decimal("120000.00")
    assert Decimal(govde["lines"][0]["line_total"]) == Decimal("100000.00")
    assert govde["lines"][0]["sort_order"] == 0


async def test_oranlar_ISTEMCIDEN_gelir_ve_kesinti_hesaplanir(
    client, muhasebe_headers, gorunen_proje
) -> None:
    """FK:223/229/235 — oranlar formdan girilir, TUTARLARI sunucu hesaplar."""
    resp = await client.post(
        _YOL,
        headers=muhasebe_headers,
        json=_giden(project_id=str(gorunen_proje.id), advance_rate="20.00", retention_rate="5.00"),
    )
    assert resp.status_code == 201, resp.text
    govde = resp.json()
    assert Decimal(govde["advance_amount"]) == Decimal("20000.00")
    assert Decimal(govde["retention_amount"]) == Decimal("5000.00")
    assert Decimal(govde["tax_base"]) == Decimal("75000.00")
    assert Decimal(govde["vat_amount"]) == Decimal("15000.00")
    assert Decimal(govde["total"]) == Decimal("90000.00")


async def test_tevkifat_KDVden_dusulur(client, muhasebe_headers, gorunen_proje) -> None:
    """K4 — tevkifatın matrahı KDV'dir ve `total`dan DÜŞÜLÜR."""
    resp = await client.post(
        _YOL,
        headers=muhasebe_headers,
        json=_giden(project_id=str(gorunen_proje.id), withholding_rate="20.00"),
    )
    govde = resp.json()
    assert Decimal(govde["withholding_amount"]) == Decimal("4000.00")
    assert Decimal(govde["total"]) == Decimal("116000.00")


async def test_giden_faturada_istemci_invoice_no_GONDEREMEZ_422(
    client, muhasebe_headers, gorunen_proje
) -> None:
    resp = await client.post(
        _YOL,
        headers=muhasebe_headers,
        json=_giden(project_id=str(gorunen_proje.id), invoice_no="FIL2026000001"),
    )
    assert resp.status_code == 422, resp.text


async def test_gelen_faturada_invoice_no_ZORUNLU_422(
    client, muhasebe_headers, gorunen_proje
) -> None:
    """S5 — satıcının serisi sunucu tarafından üretilemez."""
    govde = _gelen(project_id=str(gorunen_proje.id))
    govde.pop("invoice_no")
    resp = await client.post(_YOL, headers=muhasebe_headers, json=govde)
    assert resp.status_code == 422, resp.text


async def test_gelen_fatura_pending_baslar_ve_numarasi_KORUNUR(
    client, muhasebe_headers, gorunen_proje
) -> None:
    """K2 — `draft` yalnız giden taraftadır."""
    resp = await client.post(
        _YOL, headers=muhasebe_headers, json=_gelen(project_id=str(gorunen_proje.id))
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["status"] == "pending"
    assert resp.json()["invoice_no"] == "LT2026070184"


@pytest.mark.parametrize(
    "alan",
    [
        "subtotal",
        "advance_amount",
        "retention_amount",
        "tax_base",
        "vat_amount",
        "withholding_amount",
        "total",
    ],
)
async def test_hesaplanan_para_alanlari_GONDERILEMEZ_422(
    client, muhasebe_headers, gorunen_proje, alan: str
) -> None:
    resp = await client.post(
        _YOL, headers=muhasebe_headers, json=_giden(project_id=str(gorunen_proje.id), **{alan: "1"})
    )
    assert resp.status_code == 422, f"{alan} sessizce yok sayıldı: {resp.text}"


@pytest.mark.parametrize("alan,deger", [("line_total", "1.00"), ("sort_order", 3)])
async def test_kalemde_line_total_ve_sort_order_GONDERILEMEZ_422(
    client, muhasebe_headers, gorunen_proje, alan: str, deger
) -> None:
    kalem = dict(_KALEM) | {alan: deger}
    resp = await client.post(
        _YOL, headers=muhasebe_headers, json=_giden(project_id=str(gorunen_proje.id), lines=[kalem])
    )
    assert resp.status_code == 422, f"{alan} sessizce yok sayıldı: {resp.text}"


async def test_status_GONDERILEMEZ_422(client, muhasebe_headers, gorunen_proje) -> None:
    """Durum sunucunundur (K2/INITIAL_STATUS) — gövdeden gelemez."""
    resp = await client.post(
        _YOL, headers=muhasebe_headers, json=_giden(project_id=str(gorunen_proje.id), status="sent")
    )
    assert resp.status_code == 422, resp.text


async def test_iki_taraf_karti_birlikte_422(
    client, muhasebe_headers, gorunen_proje, isveren, alici
) -> None:
    """`ck_invoices_single_party` SERVİSTE yakalanır — kullanıcıya 500 gitmez."""
    resp = await client.post(
        _YOL,
        headers=muhasebe_headers,
        json=_giden(
            project_id=str(gorunen_proje.id),
            employer_id=str(isveren.id),
            customer_id=str(alici.id),
        ),
    )
    assert resp.status_code == 422, resp.text


async def test_iki_kaynak_referansi_birlikte_422(
    client, muhasebe_headers, gorunen_proje, gorunmeyen_siparis
) -> None:
    """`ck_invoices_single_source` SERVİSTE yakalanır."""
    resp = await client.post(
        _YOL,
        headers=muhasebe_headers,
        json=_giden(
            project_id=str(gorunen_proje.id),
            purchase_order_id=str(gorunmeyen_siparis.id),
            progress_payment_id=str(uuid.uuid4()),
        ),
    )
    assert resp.status_code == 422, resp.text


async def test_gorunmeyen_proje_referansi_404(client, muhasebe_headers, gorunmeyen_proje) -> None:
    resp = await client.post(
        _YOL, headers=muhasebe_headers, json=_giden(project_id=str(gorunmeyen_proje.id))
    )
    assert resp.status_code == 404, resp.text


async def test_olmayan_taraf_karti_404(client, muhasebe_headers, gorunen_proje) -> None:
    resp = await client.post(
        _YOL,
        headers=muhasebe_headers,
        json=_giden(project_id=str(gorunen_proje.id), employer_id=str(uuid.uuid4())),
    )
    assert resp.status_code == 404, resp.text


async def test_gorunmeyen_kaynak_referansi_404_403_DEGIL(
    client, muhasebe_headers, gorunen_proje, gorunmeyen_siparis
) -> None:
    """ST kanonu: görünmez/yok VARLIK referansı = 404."""
    resp = await client.post(
        _YOL,
        headers=muhasebe_headers,
        json=_giden(project_id=str(gorunen_proje.id), purchase_order_id=str(gorunmeyen_siparis.id)),
    )
    assert resp.status_code == 404, resp.text


async def test_baska_projenin_santiyesi_404(
    client, muhasebe_headers, gorunen_proje, gorunmeyen_santiye
) -> None:
    resp = await client.post(
        _YOL,
        headers=muhasebe_headers,
        json=_giden(project_id=str(gorunen_proje.id), site_id=str(gorunmeyen_santiye.id)),
    )
    assert resp.status_code == 404, resp.text


async def test_kesinti_oranlari_toplami_yuzden_buyuk_422(
    client, muhasebe_headers, gorunen_proje
) -> None:
    resp = await client.post(
        _YOL,
        headers=muhasebe_headers,
        json=_giden(project_id=str(gorunen_proje.id), advance_rate="70.00", retention_rate="40.00"),
    )
    assert resp.status_code == 422, resp.text


async def test_serbest_metin_tavani_TEK_SABITTEN_not(
    client, muhasebe_headers, gorunen_proje
) -> None:
    """TB4/B4 dersi — tavan `app.core.text.FREE_TEXT_MAX_LENGTH`tir."""
    from app.core.text import FREE_TEXT_MAX_LENGTH

    resp = await client.post(
        _YOL,
        headers=muhasebe_headers,
        json=_giden(project_id=str(gorunen_proje.id), note="x" * (FREE_TEXT_MAX_LENGTH + 1)),
    )
    assert resp.status_code == 422, resp.text


async def test_serbest_metin_tavani_TEK_SABITTEN_kalem_aciklamasi(
    client, muhasebe_headers, gorunen_proje
) -> None:
    from app.core.text import FREE_TEXT_MAX_LENGTH

    kalem = dict(_KALEM) | {"description": "y" * (FREE_TEXT_MAX_LENGTH + 1)}
    resp = await client.post(
        _YOL, headers=muhasebe_headers, json=_giden(project_id=str(gorunen_proje.id), lines=[kalem])
    )
    assert resp.status_code == 422, resp.text


async def test_sifir_miktarli_kalem_422(client, muhasebe_headers, gorunen_proje) -> None:
    kalem = dict(_KALEM) | {"quantity": "0.000"}
    resp = await client.post(
        _YOL, headers=muhasebe_headers, json=_giden(project_id=str(gorunen_proje.id), lines=[kalem])
    )
    assert resp.status_code == 422, resp.text


async def test_kalemsiz_taslak_SERBESTTIR(client, muhasebe_headers, gorunen_proje) -> None:
    """K6 kapısı `send`/`approve` anındadır (T4) — taslak kaydetmek serbesttir."""
    resp = await client.post(
        _YOL, headers=muhasebe_headers, json=_giden(project_id=str(gorunen_proje.id), lines=[])
    )
    assert resp.status_code == 201, resp.text
    assert Decimal(resp.json()["total"]) == Decimal("0.00")


async def test_projesiz_fatura_olusturulabilir(client, muhasebe_headers) -> None:
    resp = await client.post(_YOL, headers=muhasebe_headers, json=_giden())
    assert resp.status_code == 201, resp.text
    assert resp.json()["project_id"] is None


async def test_olusturma_denetim_satiri_yazar(
    client, muhasebe_headers, gorunen_proje, seeded_db
) -> None:
    resp = await client.post(
        _YOL, headers=muhasebe_headers, json=_giden(project_id=str(gorunen_proje.id))
    )
    assert resp.status_code == 201, resp.text
    kayitlar = (
        (await seeded_db.execute(select(AuditLog).where(AuditLog.action == AuditAction.create)))
        .scalars()
        .all()
    )
    assert any(resp.json()["invoice_no"] in k.detail for k in kayitlar)


async def test_olusturma_yalniz_full_pm_403(client, pm_headers, gorunen_proje) -> None:
    resp = await client.post(
        _YOL, headers=pm_headers, json=_giden(project_id=str(gorunen_proje.id))
    )
    assert resp.status_code == 403, resp.text


# --- Uç 4: detay ---


async def test_detay_kalemleri_sirasiyla_doner(
    client, muhasebe_headers, fatura_fabrikasi, gorunen_proje
) -> None:
    fatura = await fatura_fabrikasi(
        project=gorunen_proje,
        lines=[("Birinci", "1.000", "100.00"), ("İkinci", "2.000", "200.00")],
    )
    resp = await client.get(f"{_YOL}/{fatura.id}", headers=muhasebe_headers)
    assert resp.status_code == 200, resp.text
    kalemler = resp.json()["lines"]
    assert [k["sort_order"] for k in kalemler] == [0, 1]
    assert [k["description"] for k in kalemler] == ["Birinci", "İkinci"]


async def test_detay_gorunmeyen_fatura_404(
    client, muhasebe_headers, fatura_fabrikasi, gorunmeyen_proje
) -> None:
    fatura = await fatura_fabrikasi(project=gorunmeyen_proje)
    resp = await client.get(f"{_YOL}/{fatura.id}", headers=muhasebe_headers)
    assert resp.status_code == 404, resp.text


async def test_detay_olmayan_fatura_ayni_404(client, muhasebe_headers) -> None:
    resp = await client.get(f"{_YOL}/{uuid.uuid4()}", headers=muhasebe_headers)
    assert resp.status_code == 404, resp.text


async def test_detay_projesiz_fatura_gorunur(client, muhasebe_headers, fatura_fabrikasi) -> None:
    fatura = await fatura_fabrikasi(project=None)
    resp = await client.get(f"{_YOL}/{fatura.id}", headers=muhasebe_headers)
    assert resp.status_code == 200, resp.text


# --- Rota sırası bekçisi (spec §9, MK-2 dersi) ---


def test_rota_sirasi_iki_segmentli_literal_yollar_UUID_rotasindan_ONCE() -> None:
    """🔴 `/invoices/summary` (T4) `/invoices/{invoice_id}` ile ÇAKIŞIR.

    FastAPI yolları KAYIT SIRASINA göre eşler; `summary` sonra kaydedilseydi bir
    UUID sanılıp 422'ye düşerdi (MK-2 `main.py:94-104` dersi). Bu bekçi bugün
    boş kümede geçer ama kuralı KİLİTLER: T4 `summary`yi ayrılmış yere koymak
    zorundadır.
    """
    from app.modules.invoicing.router import router

    yollar = [rota.path for rota in router.routes]
    uuid_yollari = [i for i, yol in enumerate(yollar) if yol.startswith("/invoices/{invoice_id}")]
    assert uuid_yollari, "detay rotası kaydedilmemiş"
    ilk_uuid = min(uuid_yollari)
    for sira, yol in enumerate(yollar):
        if yol.startswith("/invoices/") and "{invoice_id}" not in yol:
            assert sira < ilk_uuid, f"{yol} rotası UUID rotasından SONRA kaydedilmiş"
