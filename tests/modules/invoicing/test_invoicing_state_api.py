"""🔴 MU-3B NOTU: `send`/`approve` artık FİŞ KESER (`invoicing/posting.py`), yani
`posting_rules` eşlemesi olmadan **422** verirler. Bu uçları ölçen testler
`fatura_eslemesi` fixture'ını ister — canlıda o satırları `c0d1e2f3a4b5`
migration'ı tohumlar, test kümesi migration koşmaz.

FAT-1 T4 — durum geçiş uçları (spec §7 md. 8, 9, 10, 11).

## Bu dosyanın kilitlediği kararlar

1. **Geçiş kararı TEK kaynaktan (`transitions.py`) okunur.** Uçlar kendi
   `if status == …` denetimini YAZMAZ; matris dışı çift de yön dışı çağrı da
   **409**'dur.
2. **YÖN DIŞI çağrı 409'dur, 404 değil:** giden faturaya `approve`, gelen
   faturaya `send` atılamaz. Kayıt GÖRÜNÜR ve yetki VARDIR — engelleyen şey
   işlemin bu yöne ait OLMAMASIDIR.
3. 🔴 **K6 kapısı:** kalemsiz faturada `send`/`approve` **422**. "Kalem yok" ile
   "tutar sıfır" aynı 0'ı üretmemelidir (NULL-EŞİK kanonunun kardeşi).
   `mark-collected` ve `dispute` bu kapıyı UYGULAMAZ.
4. 🔴 **K7:** geçiş yalnız `status` damgalar. Para alanları YENİDEN HESAPLANMAZ
   ve kaynaktan hiçbir şey CANLI OKUNMAZ — `sent`/`approved` fatura donmuştur.
5. Yetki `full`dür (PM `view` ile 403 alır), kapsam süzgeci geçerlidir
   (görünmeyen projenin faturası **404**).
"""

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.modules.audit.models import AuditAction, AuditLog
from app.modules.invoicing.guards import INVOICE_MISSING
from app.modules.invoicing.models import Invoice, InvoiceDirection, InvoiceStatus
from app.modules.invoicing.validation import LINES_REQUIRED

_YOL = "/invoices"

#: Para kolonlarının TAMAMI — K7 bekçisi hepsini karşılaştırır.
_PARA_ALANLARI = (
    "subtotal",
    "advance_amount",
    "retention_amount",
    "tax_base",
    "vat_amount",
    "withholding_amount",
    "total",
)


# --- Uç 8: send (draft → sent) ---


async def test_send_taslak_giden_faturayi_gonderir(
    client, muhasebe_headers, fatura_fabrikasi, gorunen_proje, seeded_db, fatura_eslemesi
) -> None:
    fatura = await fatura_fabrikasi(project=gorunen_proje)
    resp = await client.post(f"{_YOL}/{fatura.id}/send", headers=muhasebe_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == InvoiceStatus.sent.value
    await seeded_db.refresh(fatura)
    assert fatura.status is InvoiceStatus.sent


async def test_send_denetim_satiri_yazar(
    client, muhasebe_headers, fatura_fabrikasi, gorunen_proje, seeded_db, fatura_eslemesi
) -> None:
    """Yeni `AuditAction` üyesi AÇILMADI (TB3/T3 kanonu) — ayrım METİNDEDİR."""
    fatura = await fatura_fabrikasi(project=gorunen_proje, invoice_no="FILSEND00001")
    resp = await client.post(f"{_YOL}/{fatura.id}/send", headers=muhasebe_headers)
    assert resp.status_code == 200, resp.text
    kayitlar = (
        (await seeded_db.execute(select(AuditLog).where(AuditLog.action == AuditAction.update)))
        .scalars()
        .all()
    )
    assert any("FILSEND00001" in k.detail and "gönder" in k.detail.lower() for k in kayitlar), [
        k.detail for k in kayitlar
    ]


async def test_send_kalemsiz_fatura_422(
    client, muhasebe_headers, fatura_fabrikasi, gorunen_proje
) -> None:
    """🔴 K6 — kalemsiz fatura kusursuz biçimde 0,00₺ hesaplanır; HESAP DOĞRU,
    FATURA YANLIŞTIR."""
    fatura = await fatura_fabrikasi(project=gorunen_proje, lines=[])
    resp = await client.post(f"{_YOL}/{fatura.id}/send", headers=muhasebe_headers)
    assert resp.status_code == 422, resp.text
    assert LINES_REQUIRED in resp.json()["detail"]


async def test_send_zaten_gonderilmis_fatura_409(
    client, muhasebe_headers, fatura_fabrikasi, gorunen_proje
) -> None:
    """MATRİS DIŞI: `(sent, send)` çifti tabloda yoktur."""
    fatura = await fatura_fabrikasi(project=gorunen_proje, status=InvoiceStatus.sent)
    resp = await client.post(f"{_YOL}/{fatura.id}/send", headers=muhasebe_headers)
    assert resp.status_code == 409, resp.text


async def test_send_gelen_faturaya_409_YON_DISI(
    client, muhasebe_headers, fatura_fabrikasi, gorunen_proje
) -> None:
    fatura = await fatura_fabrikasi(
        project=gorunen_proje,
        direction=InvoiceDirection.incoming,
        status=InvoiceStatus.pending,
        invoice_no="LT2026070184",
    )
    resp = await client.post(f"{_YOL}/{fatura.id}/send", headers=muhasebe_headers)
    assert resp.status_code == 409, resp.text


async def test_send_gorunmeyen_proje_faturasi_404(
    client, muhasebe_headers, fatura_fabrikasi, gorunmeyen_proje
) -> None:
    fatura = await fatura_fabrikasi(project=gorunmeyen_proje)
    resp = await client.post(f"{_YOL}/{fatura.id}/send", headers=muhasebe_headers)
    assert resp.status_code == 404, resp.text
    # Gövde VAR OLMAYAN faturanınkiyle BİREBİR aynıdır — FastAPI'nin genel
    # "Not Found"u değil, kapsam süzgecinin kendi cümlesi. (Bu iddia olmadan
    # test, rota henüz açılmamışken de yeşil geçerdi.)
    assert resp.json()["detail"] == INVOICE_MISSING


async def test_send_yalniz_full_pm_403(client, pm_headers, fatura_fabrikasi, gorunen_proje) -> None:
    fatura = await fatura_fabrikasi(project=gorunen_proje)
    resp = await client.post(f"{_YOL}/{fatura.id}/send", headers=pm_headers)
    assert resp.status_code == 403, resp.text


# --- Uç 9: mark-collected (sent → collected) ---


async def test_mark_collected_gonderilmis_faturayi_tahsil_eder(
    client, muhasebe_headers, fatura_fabrikasi, gorunen_proje
) -> None:
    fatura = await fatura_fabrikasi(project=gorunen_proje, status=InvoiceStatus.sent)
    resp = await client.post(f"{_YOL}/{fatura.id}/mark-collected", headers=muhasebe_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == InvoiceStatus.collected.value


async def test_mark_collected_taslak_fatura_409(
    client, muhasebe_headers, fatura_fabrikasi, gorunen_proje
) -> None:
    fatura = await fatura_fabrikasi(project=gorunen_proje)
    resp = await client.post(f"{_YOL}/{fatura.id}/mark-collected", headers=muhasebe_headers)
    assert resp.status_code == 409, resp.text


async def test_mark_collected_gelen_faturaya_409_YON_DISI(
    client, muhasebe_headers, fatura_fabrikasi, gorunen_proje
) -> None:
    fatura = await fatura_fabrikasi(
        project=gorunen_proje,
        direction=InvoiceDirection.incoming,
        status=InvoiceStatus.pending,
        invoice_no="LT2026070185",
    )
    resp = await client.post(f"{_YOL}/{fatura.id}/mark-collected", headers=muhasebe_headers)
    assert resp.status_code == 409, resp.text


async def test_mark_collected_kalemsiz_faturada_K6_UYGULANMAZ(
    client, muhasebe_headers, fatura_fabrikasi, gorunen_proje
) -> None:
    """Kalem kapısı YALNIZ `send`/`approve` içindir (`validation.GATE_ACTIONS`).

    `mark-collected` zaten kalemli bir `sent` faturadan gelir; kapıyı buraya da
    koymak, veri kaybı yaşamış eski bir kaydı sonsuza dek `sent`te kilitlerdi.
    """
    fatura = await fatura_fabrikasi(project=gorunen_proje, status=InvoiceStatus.sent, lines=[])
    resp = await client.post(f"{_YOL}/{fatura.id}/mark-collected", headers=muhasebe_headers)
    assert resp.status_code == 200, resp.text


# --- Uç 10: approve (pending → approved) ---


async def test_approve_bekleyen_gelen_faturayi_onaylar(
    client, muhasebe_headers, fatura_fabrikasi, gorunen_proje, seeded_db, fatura_eslemesi
) -> None:
    fatura = await fatura_fabrikasi(
        project=gorunen_proje,
        direction=InvoiceDirection.incoming,
        status=InvoiceStatus.pending,
        invoice_no="LT2026070186",
    )
    resp = await client.post(f"{_YOL}/{fatura.id}/approve", headers=muhasebe_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == InvoiceStatus.approved.value
    kayitlar = (
        (await seeded_db.execute(select(AuditLog).where(AuditLog.action == AuditAction.approve)))
        .scalars()
        .all()
    )
    assert any("LT2026070186" in k.detail for k in kayitlar), [k.detail for k in kayitlar]


async def test_approve_kalemsiz_fatura_422(
    client, muhasebe_headers, fatura_fabrikasi, gorunen_proje
) -> None:
    fatura = await fatura_fabrikasi(
        project=gorunen_proje,
        direction=InvoiceDirection.incoming,
        status=InvoiceStatus.pending,
        invoice_no="LT2026070187",
        lines=[],
    )
    resp = await client.post(f"{_YOL}/{fatura.id}/approve", headers=muhasebe_headers)
    assert resp.status_code == 422, resp.text
    assert LINES_REQUIRED in resp.json()["detail"]


async def test_approve_giden_faturaya_409_YON_DISI(
    client, muhasebe_headers, fatura_fabrikasi, gorunen_proje
) -> None:
    fatura = await fatura_fabrikasi(project=gorunen_proje)
    resp = await client.post(f"{_YOL}/{fatura.id}/approve", headers=muhasebe_headers)
    assert resp.status_code == 409, resp.text


async def test_approve_zaten_onayli_fatura_409(
    client, muhasebe_headers, fatura_fabrikasi, gorunen_proje
) -> None:
    """`approved` TERMİNALDİR — hiçbir çiftte kaynak değildir."""
    fatura = await fatura_fabrikasi(
        project=gorunen_proje,
        direction=InvoiceDirection.incoming,
        status=InvoiceStatus.approved,
        invoice_no="LT2026070188",
    )
    resp = await client.post(f"{_YOL}/{fatura.id}/approve", headers=muhasebe_headers)
    assert resp.status_code == 409, resp.text


# --- Uç 11: dispute (pending → disputed) ---


async def test_dispute_bekleyen_faturaya_itiraz_eder(
    client, muhasebe_headers, fatura_fabrikasi, gorunen_proje
) -> None:
    fatura = await fatura_fabrikasi(
        project=gorunen_proje,
        direction=InvoiceDirection.incoming,
        status=InvoiceStatus.pending,
        invoice_no="LT2026070189",
    )
    resp = await client.post(f"{_YOL}/{fatura.id}/dispute", headers=muhasebe_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == InvoiceStatus.disputed.value


async def test_dispute_kalemsiz_faturada_K6_UYGULANMAZ(
    client, muhasebe_headers, fatura_fabrikasi, gorunen_proje
) -> None:
    """İtiraz bir REDDETMEDİR: eksik kalem, itirazı engellemek için sebep
    değildir (`validation` modül docstring'i)."""
    fatura = await fatura_fabrikasi(
        project=gorunen_proje,
        direction=InvoiceDirection.incoming,
        status=InvoiceStatus.pending,
        invoice_no="LT2026070190",
        lines=[],
    )
    resp = await client.post(f"{_YOL}/{fatura.id}/dispute", headers=muhasebe_headers)
    assert resp.status_code == 200, resp.text


async def test_dispute_giden_faturaya_409_YON_DISI(
    client, muhasebe_headers, fatura_fabrikasi, gorunen_proje
) -> None:
    fatura = await fatura_fabrikasi(project=gorunen_proje)
    resp = await client.post(f"{_YOL}/{fatura.id}/dispute", headers=muhasebe_headers)
    assert resp.status_code == 409, resp.text


async def test_dispute_itiraz_edilmis_fatura_409(
    client, muhasebe_headers, fatura_fabrikasi, gorunen_proje
) -> None:
    fatura = await fatura_fabrikasi(
        project=gorunen_proje,
        direction=InvoiceDirection.incoming,
        status=InvoiceStatus.disputed,
        invoice_no="LT2026070191",
    )
    resp = await client.post(f"{_YOL}/{fatura.id}/dispute", headers=muhasebe_headers)
    assert resp.status_code == 409, resp.text


# --- 🔴 K7: geçiş para ALANLARINA DOKUNMAZ ---


@pytest.mark.parametrize(
    ("islem", "durum", "yon", "numara"),
    [
        ("send", InvoiceStatus.draft, InvoiceDirection.outgoing, None),
        ("mark-collected", InvoiceStatus.sent, InvoiceDirection.outgoing, None),
        ("approve", InvoiceStatus.pending, InvoiceDirection.incoming, "LT2026070192"),
        ("dispute", InvoiceStatus.pending, InvoiceDirection.incoming, "LT2026070193"),
    ],
)
async def test_gecis_para_alanlarini_YENIDEN_HESAPLAMAZ(
    client,
    muhasebe_headers,
    fatura_fabrikasi,
    gorunen_proje,
    seeded_db,
    fatura_eslemesi,
    islem: str,
    durum: InvoiceStatus,
    yon: InvoiceDirection,
    numara: str | None,
) -> None:
    """🔴 K7 — geçiş yalnız `status` damgalar.

    Fabrika faturayı BİLEREK `amounts.compute`un üretmeyeceği tutarlarla kurar
    (oran dolu ama kesinti tutarı 0). Geçiş uçları yeniden hesaplasaydı bu
    değerler DEĞİŞİRDİ ve donmuş bir belge canlıya dönerdi. Kolonların TAMAMI
    karşılaştırılır: N çarpanlı snapshot iddiası N'in hepsini kapsamalıdır.
    """
    fatura = await fatura_fabrikasi(
        project=gorunen_proje,
        direction=yon,
        status=durum,
        invoice_no=numara,
        advance_rate="20.00",
        retention_rate="5.00",
        withholding_rate="20.00",
    )
    once = {alan: getattr(fatura, alan) for alan in _PARA_ALANLARI}
    assert any(deger != Decimal("0.00") for deger in once.values())

    resp = await client.post(f"{_YOL}/{fatura.id}/{islem}", headers=muhasebe_headers)
    assert resp.status_code == 200, resp.text

    yenilenen = (
        await seeded_db.execute(select(Invoice).where(Invoice.id == fatura.id))
    ).scalar_one()
    sonra = {alan: getattr(yenilenen, alan) for alan in _PARA_ALANLARI}
    assert sonra == once, f"{islem} para alanlarını değiştirdi: {once} → {sonra}"
    # Oranlar da donmuştur.
    assert yenilenen.advance_rate == Decimal("20.00")
    assert yenilenen.retention_rate == Decimal("5.00")
    assert yenilenen.withholding_rate == Decimal("20.00")
