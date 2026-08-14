"""🔴 K7 — N-ÇARPANLI SNAPSHOT KANONU, KAYNAK MUTASYONU KANITI (spec §5, T5/1).

> *Bir türev para değeri N çarpandan oluşuyorsa, snapshot iddiası N'in
> **HEPSİNİ** kapsamalıdır.*

MK-2 dersinin TAM ŞEKLİ budur: orada saat DONDURULMUŞ ama BEDEL canlı
okunuyordu; snapshot "kapatılmış gibi" görünüyordu çünkü kimse çarpanları TEK
TEK sayıp her birini ayrı ayrı KIRMAYA çalışmamıştı.

Bu dosya, dilimin geri kalanının kanıtlamadığı şeyi kanıtlar. `test_invoicing_
state_api.py`deki K7 bekçisi yalnız **geçişin** yeniden hesaplamadığını gösterir
(fatura hiç değişmeden `status` damgalanır). Buradaki iddia daha güçlüdür:

    KAYNAK KAYIT DEĞİŞİR → DONMUŞ FATURANIN HİÇBİR ALANI DEĞİŞMEZ.

Faturanın `total`ını üreten çarpanların TAMAMI ve donma yerleri:

| # | Çarpan | Nerede donuyor | Bu dosyada kırılan kaynak |
|---|---|---|---|
| 1 | miktar | `invoice_lines.quantity` | sipariş kalemi/tutarı |
| 2 | birim fiyat | `invoice_lines.unit_price` | sipariş tutarı · tedarikçi kartı |
| 3 | KDV oranı | `invoice_lines.vat_rate` | — (satırda, kaynağı yok) |
| 4 | avans oranı | `invoices.advance_rate` | — (başlıkta, kaynağı yok) |
| 5 | teminat oranı | `invoices.retention_rate` | — (başlıkta) |
| 6 | tevkifat oranı | `invoices.withholding_rate` | — (başlıkta) |
| 7 | taraf ünvanı | `invoices.party_name` | **işveren/tedarikçi kartı adı** |
| 8 | taraf VKN | `invoices.party_tax_number` | **kartın vergi numarası** |
| 9 | vergi dairesi / adres | `invoices.party_*` | kart alanları |
| 10 | her ara toplam | `invoices` para kolonları | sipariş `total_amount`ı |

3-6 için "kaynak" YOKTUR: oranlar faturaya elle girilir, hiçbir kayıttan
türemezler — kırılacak bir bağ da yoktur. 1-2 ve 7-10'un kaynağı vardır ve
aşağıda BİZZAT DEĞİŞTİRİLİR.

🔴 YAPISAL KANIT (testin tamamlayıcısı, YERİNE GEÇMEZ — MK-2'nin dersi tam da
"yapısal olarak kapalı görünmek yetmez"dir):

`invoicing/models.py`de hiçbir `relationship()` YOKTUR → tembel yükleme ile
okuma anında kaynak kayda uzanacak bir kapı açılmamıştır; FK'lar yalnızca
İZDİR. `test_kalem_ve_baslikta_relationship_ACILMAZ` bunu kilitler.

⚠️ DİKKAT — yanıltıcı bir "kanıt" burada ÇÜRÜTÜLDÜ: modül BAŞKA modüllerin
modellerini GERÇEKTEN import eder (`service.py`: `Employer`, `Customer`,
`Supplier`, `Subcontractor`, `ProgressPayment`, `SubcontractorProgressPayment`,
`EquipmentRentalInvoice`, `PurchaseOrder`). Bu importlar **YAZMA anındaki**
referans doğrulaması içindir (gövdedeki varlık var mı, görünüyor mu → 404) ve
K7'yi İHLAL ETMEZ. "Import yok, o hâlde canlı okuma yok" çıkarımı YANLIŞ olurdu;
tek geçerli kanıt aşağıdaki DAVRANIŞ testidir.
"""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.invoicing.models import (
    Invoice,
    InvoiceDirection,
    InvoiceDocumentType,
    InvoiceLine,
    InvoiceStatus,
)
from app.modules.procurement.models import PurchaseOrder, Supplier
from app.modules.projects.models import Employer, Project

pytestmark = pytest.mark.asyncio


async def _kur_donmus_fatura(
    seeded_db: AsyncSession,
    *,
    proje: Project,
    isveren: Employer,
    siparis: PurchaseOrder,
    kullanici_kimligi,
) -> Invoice:
    """Taraf FK'sı VE kaynak FK'sı DOLU, `sent` (donmuş) bir giden fatura.

    İki FK'nın da dolu olması şart: K7 hem TARAF ayağından hem KAYNAK ayağından
    kırılmaya çalışılacak. (`ck_invoices_single_party` / `_single_source` en
    fazla BİRER tane ister — birer tane veriyoruz.)
    """
    invoice = Invoice(
        direction=InvoiceDirection.outgoing,
        invoice_no="FIL2026000777",
        document_type=InvoiceDocumentType.einvoice,
        status=InvoiceStatus.sent,
        issue_date=date(2026, 7, 18),
        # Taraf SNAPSHOT'ı — işveren kartından KOPYALANMIŞTIR, ona bağlı değil.
        party_name="Güneşkent Gayrimenkul A.Ş.",
        party_tax_number="1234567890",
        party_tax_office="Çankaya V.D.",
        party_address="Çankaya / Ankara",
        employer_id=isveren.id,
        purchase_order_id=siparis.id,
        project_id=proje.id,
        subtotal=Decimal("10000.00"),
        advance_rate=Decimal("20.00"),
        advance_amount=Decimal("2000.00"),
        retention_rate=Decimal("5.00"),
        retention_amount=Decimal("500.00"),
        tax_base=Decimal("7500.00"),
        vat_amount=Decimal("1500.00"),
        withholding_rate=Decimal("20.00"),
        withholding_amount=Decimal("300.00"),
        total=Decimal("8700.00"),
        created_by_id=await kullanici_kimligi("admin@fatura.co"),
    )
    seeded_db.add(invoice)
    await seeded_db.flush()
    seeded_db.add(
        InvoiceLine(
            invoice_id=invoice.id,
            sort_order=0,
            description="Kaba İnşaat (Poz 03.001)",
            unit="m³",
            quantity=Decimal("100.000"),
            unit_price=Decimal("100.00"),
            vat_rate=Decimal("20.00"),
            line_total=Decimal("10000.00"),
            detail_note="Temmuz 2026 · Güneşkent A-Blok",
        )
    )
    await seeded_db.flush()
    return invoice


async def test_K7_kaynak_kayitlar_DEGISSE_BILE_donmus_faturanin_HICBIR_alani_degismez(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    gorunen_proje: Project,
    isveren: Employer,
    tedarikci: Supplier,
    gorunmeyen_siparis: PurchaseOrder,
    kullanici_kimligi,
) -> None:
    """🔴 K7'nin ASIL kanıtı: kaynak kırılır, fatura kımıldamaz.

    Kaçan TEK bir çarpan olsaydı (ör. `party_name` yanıtta işveren kartından
    okunsaydı) bu test o alanda KIRMIZI olurdu — MK-2'deki kusurun aynısı.
    """
    fatura = await _kur_donmus_fatura(
        seeded_db,
        proje=gorunen_proje,
        isveren=isveren,
        siparis=gorunmeyen_siparis,
        kullanici_kimligi=kullanici_kimligi,
    )

    once = await client.get(f"/invoices/{fatura.id}", headers=admin_headers)
    assert once.status_code == 200, once.text
    onceki = once.json()

    # --- KAYNAKLARI KIR (hepsi faturanın "çarpan" kaynakları) ---
    isveren.name = "DEĞİŞTİRİLMİŞ Ünvan A.Ş."
    isveren.tax_number = "9999999999"
    tedarikci.name = "DEĞİŞTİRİLMİŞ Tedarikçi"
    gorunmeyen_siparis.total_amount = Decimal("999999.99")
    await seeded_db.flush()

    sonra = await client.get(f"/invoices/{fatura.id}", headers=admin_headers)
    assert sonra.status_code == 200, sonra.text

    # 🔴 Alan alan DEĞİL, yanıtın TAMAMI karşılaştırılır: kısmi bir iddia
    # gelecekte eklenecek bir alanın canlı okunmasını GÖRMEZDİ.
    assert sonra.json() == onceki, (
        "Kaynak kayıt değişti ve DONMUŞ faturanın bir alanı OYNADI — K7 ihlali "
        "(MK-2'nin 'saat donduruldu ama bedel canlı okunuyordu' kusurunun aynısı)"
    )

    # Kaynağın gerçekten değiştiğini de kanıtla: yukarıdaki eşitlik, mutasyon
    # hiç uygulanmadıysa da geçerdi (testin kendi yalancı yeşili).
    await seeded_db.refresh(isveren)
    assert isveren.name == "DEĞİŞTİRİLMİŞ Ünvan A.Ş."
    assert onceki["party_name"] == "Güneşkent Gayrimenkul A.Ş."
    assert onceki["party_tax_number"] == "1234567890"


async def test_kalem_ve_baslikta_relationship_ACILMAZ() -> None:
    """Modelde `relationship()` YOKTUR — tembel yükleme kapısı KAPALI kalır.

    Bir gün `Invoice.employer = relationship(...)` eklenirse, bir yanıt şeması
    o ilişkiden ünvan okumaya BAŞLAYABİLİR ve K7 sessizce delinir. Bu bekçi
    kapıyı kaynak düzeyinde kapalı tutar; davranış testi de ayrıca koşar.
    """
    kaynak = (Path(__file__).parents[3] / "app/modules/invoicing/models.py").read_text()
    assert "relationship(" not in kaynak, (
        "`invoicing/models.py`ye bir `relationship()` eklenmiş — canlı okuma kapısı "
        "açıldı, K7 snapshot kanonu tehlikede (spec §5)"
    )


async def test_K7_taraf_snapshotu_faturaya_YAZILIR_karttan_OKUNMAZ(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    gorunen_proje: Project,
    isveren: Employer,
) -> None:
    """Yazma anında kopyalanır: gövdedeki `party_name` kartınkinden FARKLI
    olabilir ve fatura GÖVDEDEKİNİ saklar.

    Sunucu `employer_id`den ünvanı kendi doldursaydı, kullanıcının fatura
    üzerinde yazdığı ünvan sessizce EZİLİRDİ (ve kart değişince fatura oynardı).
    """
    resp = await client.post(
        "/invoices",
        headers=admin_headers,
        json={
            "direction": "outgoing",
            "document_type": "einvoice",
            "issue_date": "2026-07-18",
            # Kartta "Güneşkent Gayrimenkul A.Ş." yazıyor; fatura BAŞKA bir
            # ünvanla kesiliyor (ticaret ünvanı değişikliği, şube, vb.).
            "party_name": "Güneşkent Gayrimenkul A.Ş. (Ankara Şubesi)",
            "party_tax_number": "1234567890",
            "employer_id": str(isveren.id),
            "project_id": str(gorunen_proje.id),
            "lines": [
                {
                    "description": "Kaba İnşaat",
                    "unit": "m³",
                    "quantity": "100.000",
                    "unit_price": "100.00",
                    "vat_rate": "20.00",
                }
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["party_name"] == "Güneşkent Gayrimenkul A.Ş. (Ankara Şubesi)"
    assert isveren.name == "Güneşkent Gayrimenkul A.Ş."
