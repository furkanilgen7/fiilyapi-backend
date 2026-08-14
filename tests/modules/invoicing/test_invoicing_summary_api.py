"""FAT-1 T4 — `GET /invoices/summary` (spec §7 md.2, FY:69-75).

## Bu dosyanın kilitlediği kararlar

1. **BEŞ KPI birebir mockup'tan:** `Kesilen (Bu Ay)` · `Gelen (Bu Ay)` ·
   `Tahsil Edilecek` · `KDV Farkı` · `Onay Bekleyen`.
2. 🔴 **`pending_approval` ADETTİR, tutar DEĞİL** (FY:75 kartı tek bir sayı
   basar: `3` · "Gelen fatura"). İlk üç kart HEM tutar HEM adet taşır
   (FY:71/72/73 alt satırı: "18 fatura", "34 fatura", "4 fatura vadeli").
3. 🔴 **Görünürlük (IDOR) süzgeci özet uçta da geçerlidir:** listede görünmeyen
   fatura toplama GİRMEZ. Aksi hâlde özet, liste ucunun sakladığı tutarı sızdıran
   bir yan kapı olurdu.
4. **Ay penceresi `DISPLAY_TIMEZONE`dedir** (`app/core/timezone.today`): geçen
   ayın faturası "Bu Ay" kartlarına girmez ama `receivable`/`vat_difference`
   kartlarına — adları ay taşımaz — girer.
5. **Rota sırası:** `/invoices/summary` bir UUID sanılıp 422'ye DÜŞMEZ.
"""

from datetime import date, timedelta
from decimal import Decimal

from app.core.timezone import today
from app.modules.invoicing.models import InvoiceDirection, InvoiceStatus

_YOL = "/invoices/summary"


def _bu_ay() -> date:
    """Bu ayın 15'i — ayın ilk/son gününe denk gelip sınır belirsizliği
    yaratmayan güvenli bir gün."""
    return today().replace(day=15)


def _gecen_ay() -> date:
    """Bu ayın 1'inden bir gün öncesi = geçen ayın son günü (yıl dönümünde de
    doğrudur; `month - 1` aritmetiği Ocak'ta çökerdi)."""
    return today().replace(day=1) - timedelta(days=1)


async def _kurulum(fabrika, gorunen_proje, gorunmeyen_proje) -> None:
    """Dört görünür + bir GÖRÜNMEYEN fatura.

    Tutarlar birbirinden ayırt edilebilir seçildi: bir kart yanlış kümeden
    beslenirse toplam başka bir kartın değerine eşit çıkmaz, tanınabilir bir
    sayı üretir.
    """
    # A — giden, BU AY, `sent`: 1000 matrah · 200 KDV · 1200 toplam
    await fabrika(
        project=gorunen_proje,
        status=InvoiceStatus.sent,
        issue_date=_bu_ay(),
        lines=[("A kalemi", "1.000", "1000.00")],
    )
    # B — giden, GEÇEN AY, `draft`: 500 · 100 · 600
    await fabrika(
        project=gorunen_proje,
        issue_date=_gecen_ay(),
        lines=[("B kalemi", "1.000", "500.00")],
    )
    # C — gelen, BU AY, `pending`: 800 · 160 · 960
    await fabrika(
        project=gorunen_proje,
        direction=InvoiceDirection.incoming,
        status=InvoiceStatus.pending,
        invoice_no="LT-SUM-0001",
        issue_date=_bu_ay(),
        lines=[("C kalemi", "1.000", "800.00")],
    )
    # D — gelen, BU AY, `approved`: 200 · 40 · 240
    await fabrika(
        project=gorunen_proje,
        direction=InvoiceDirection.incoming,
        status=InvoiceStatus.approved,
        invoice_no="LT-SUM-0002",
        issue_date=_bu_ay(),
        lines=[("D kalemi", "1.000", "200.00")],
    )
    # E — GÖRÜNMEYEN projenin giden `sent` faturası: hiçbir toplama girmemeli.
    await fabrika(
        project=gorunmeyen_proje,
        status=InvoiceStatus.sent,
        issue_date=_bu_ay(),
        lines=[("E kalemi", "1.000", "999000.00")],
    )


async def test_ozet_bes_KPI_yi_doner(
    client, muhasebe_headers, fatura_fabrikasi, gorunen_proje, gorunmeyen_proje
) -> None:
    await _kurulum(fatura_fabrikasi, gorunen_proje, gorunmeyen_proje)
    resp = await client.get(_YOL, headers=muhasebe_headers)
    assert resp.status_code == 200, resp.text
    govde = resp.json()

    assert Decimal(govde["issued_this_month"]["amount"]) == Decimal("1200.00")
    assert govde["issued_this_month"]["count"] == 1
    assert Decimal(govde["received_this_month"]["amount"]) == Decimal("1200.00")
    assert govde["received_this_month"]["count"] == 2
    assert Decimal(govde["receivable"]["amount"]) == Decimal("1200.00")
    assert govde["receivable"]["count"] == 1
    # Giden KDV (200 + 100) − gelen KDV (160 + 40) = 100
    assert Decimal(govde["vat_difference"]) == Decimal("100.00")
    assert govde["pending_approval"] == 1


async def test_ozet_pending_approval_ADETTIR_tutar_degil(
    client, muhasebe_headers, fatura_fabrikasi, gorunen_proje, gorunmeyen_proje
) -> None:
    """🔴 FY:75 kartı TEK bir sayı basar. Tutar dönseydi ekran ₺960,00'ı "3"
    yerine gösterir ve kart mockup'la tutmazdı."""
    await _kurulum(fatura_fabrikasi, gorunen_proje, gorunmeyen_proje)
    govde = (await client.get(_YOL, headers=muhasebe_headers)).json()
    assert isinstance(govde["pending_approval"], int)
    assert govde["pending_approval"] == 1


async def test_ozet_gorunmeyen_projenin_faturasini_TOPLAMA_KATMAZ(
    client, muhasebe_headers, admin_headers, fatura_fabrikasi, gorunen_proje, gorunmeyen_proje
) -> None:
    """🔴 IDOR — aynı veri kümesi iki farklı kapsamdan OKUNUR.

    `admin` (`projects=_A`) görünmeyen projeyi de görür; muhasebe görmez. İki
    yanıt AYRIŞMAK ZORUNDADIR: aynıysalar süzgeç hiç uygulanmıyordur.
    """
    await _kurulum(fatura_fabrikasi, gorunen_proje, gorunmeyen_proje)

    kisitli = (await client.get(_YOL, headers=muhasebe_headers)).json()
    tam = (await client.get(_YOL, headers=admin_headers)).json()

    assert Decimal(kisitli["issued_this_month"]["amount"]) == Decimal("1200.00")
    assert kisitli["receivable"]["count"] == 1
    # E faturası: 999000 matrah · 199800 KDV · 1198800 toplam
    assert Decimal(tam["issued_this_month"]["amount"]) == Decimal("1200000.00")
    assert tam["receivable"]["count"] == 2


async def test_ozet_gecen_ayin_faturasi_BU_AY_kartlarina_girmez(
    client, muhasebe_headers, fatura_fabrikasi, gorunen_proje
) -> None:
    """Ay penceresi `DISPLAY_TIMEZONE`dedir. B faturası (geçen ay) `issued_this_
    month`a girmez ama `vat_difference` — adı ay taşımaz — onu da kapsar."""
    await fatura_fabrikasi(
        project=gorunen_proje,
        issue_date=_gecen_ay(),
        lines=[("B kalemi", "1.000", "500.00")],
    )
    govde = (await client.get(_YOL, headers=muhasebe_headers)).json()
    assert Decimal(govde["issued_this_month"]["amount"]) == Decimal("0.00")
    assert govde["issued_this_month"]["count"] == 0
    assert Decimal(govde["vat_difference"]) == Decimal("100.00")


async def test_ozet_bos_kurulumda_sifir_doner(client, muhasebe_headers) -> None:
    """Para her zaman İKİ HANELİDİR: kart "₺0" değil "₺0,00" tabanından
    biçimlenir (`procurement/summary.py` kuralı)."""
    resp = await client.get(_YOL, headers=muhasebe_headers)
    assert resp.status_code == 200, resp.text
    govde = resp.json()
    assert govde["issued_this_month"] == {"amount": "0.00", "count": 0}
    assert govde["received_this_month"] == {"amount": "0.00", "count": 0}
    assert govde["receivable"] == {"amount": "0.00", "count": 0}
    assert govde["vat_difference"] == "0.00"
    assert govde["pending_approval"] == 0


async def test_ozet_view_yeter_pm_okur(client, pm_headers, fatura_fabrikasi, gorunen_proje) -> None:
    await fatura_fabrikasi(project=gorunen_proje, issue_date=_bu_ay())
    resp = await client.get(_YOL, headers=pm_headers)
    assert resp.status_code == 200, resp.text


async def test_ozet_yetkisiz_403(client, yetkisiz_headers) -> None:
    resp = await client.get(_YOL, headers=yetkisiz_headers)
    assert resp.status_code == 403, resp.text


async def test_ozet_rotasi_UUID_SANILMAZ(client, muhasebe_headers) -> None:
    """🔴 ROTA SIRASI (MK-2 dersi): `summary` `{invoice_id}`den SONRA
    kaydedilseydi bir UUID sanılır ve 422 dönerdi — 200 bunu kanıtlar."""
    resp = await client.get(_YOL, headers=muhasebe_headers)
    assert resp.status_code == 200, resp.text
