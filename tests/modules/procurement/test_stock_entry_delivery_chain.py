"""SA T4 — ST bağı: stok girişi sipariş+talebi `delivered` yapar (§7 S4).

Kullanıcı kararı S4: ayrı bir "mal kabul" ucu AÇILMAZ; teslim damgasını
`purchase_order_id` taşıyan bir STOK GİRİŞİ atar. Kısmi teslim ayrımı YOKTUR
(bilinen sınır).

## Bu paketin taşıdığı üç kanon

1. **Gövde içi varlık referansı = 404** (ST §4b): görünmeyen ya da olmayan
   sipariş kimliği AYNI gövdeyi alır ve o istekte HİÇBİR ŞEY yazılmaz.
2. **İMPORT YÖNÜ**: `inventory` modül düzeyinde `procurement`i import ETMEZ;
   tek temas noktası `procurement.stock_link`tir ve o da FONKSİYON İÇİNDEN
   çağrılır. Kural bir AST bekçisiyle kilitlidir (P10 `cost_cards` çemberi).
3. **Teslim matrisleri LİTERAL kilitlidir** (T3'ün M7 dersi): tabloyu kendi
   kendinden üreten bir test mutasyonu yutar.
"""

import ast
import pathlib
import uuid

import pytest
from sqlalchemy import func, select

from app.modules.inventory.models import StockEntry
from app.modules.procurement import transitions
from app.modules.procurement.models import (
    PurchaseOrderStatus,
    PurchaseRequestStatus,
)

_ENTRIES = "/stock/entries"


async def _giris(client, headers, depo, kart, *, order_id=None, entry_type="purchase", **ek):
    govde = {
        "entry_type": entry_type,
        "entry_date": "2026-08-12",
        "warehouse_id": str(depo.id),
        "lines": [{"item_id": str(kart.id), "quantity": "5.000", "unit_price": "100.00"}],
        **ek,
    }
    if order_id is not None:
        govde["purchase_order_id"] = str(order_id)
    return await client.post(_ENTRIES, json=govde, headers=headers)


# --- Zincir ---


async def test_stok_girisi_siparisi_teslim_eder(
    client,
    satinalma_headers,
    seeded_db,
    gorunen_proje,
    tedarikci_fabrikasi,
    siparis_fabrikasi,
    depo_fabrikasi,
    kart_fabrikasi,
):
    """`approved` sipariş, `purchase_order_id` taşıyan bir girişte `delivered` olur."""
    siparis = await siparis_fabrikasi(gorunen_proje, await tedarikci_fabrikasi("Demirsan A.Ş."))
    depo = await depo_fabrikasi("Merkez Depo")
    kart = await kart_fabrikasi("DMR-0012")

    yanit = await _giris(client, satinalma_headers, depo, kart, order_id=siparis.id)

    assert yanit.status_code == 201, yanit.text
    assert yanit.json()["purchase_order_id"] == str(siparis.id)
    await seeded_db.refresh(siparis)
    assert siparis.status is PurchaseOrderStatus.delivered


async def test_yolda_siparis_de_teslim_olur(
    client,
    satinalma_headers,
    seeded_db,
    gorunen_proje,
    tedarikci_fabrikasi,
    siparis_fabrikasi,
    depo_fabrikasi,
    kart_fabrikasi,
):
    """`in_transit → delivered` yalnız BU yoldan geçer (PATCH'te hâlâ 409)."""
    siparis = await siparis_fabrikasi(
        gorunen_proje,
        await tedarikci_fabrikasi("Demirsan A.Ş."),
        status=PurchaseOrderStatus.in_transit,
    )
    depo = await depo_fabrikasi("Merkez Depo")
    kart = await kart_fabrikasi("DMR-0012")

    assert (
        await _giris(client, satinalma_headers, depo, kart, order_id=siparis.id)
    ).status_code == 201
    await seeded_db.refresh(siparis)
    assert siparis.status is PurchaseOrderStatus.delivered


async def test_zincir_bagli_talebi_de_teslim_eder(
    client,
    satinalma_headers,
    seeded_db,
    gorunen_proje,
    tedarikci_fabrikasi,
    talep_fabrikasi,
    siparis_fabrikasi,
    depo_fabrikasi,
    kart_fabrikasi,
):
    """Siparişin talebi varsa O DA `delivered` olur — tek atomik işlemde."""
    talep = await talep_fabrikasi(
        gorunen_proje, status=PurchaseRequestStatus.ordered, lines=[("3.000", "100.00")]
    )
    siparis = await siparis_fabrikasi(gorunen_proje, await tedarikci_fabrikasi("Demirsan A.Ş."))
    siparis.request_id = talep.id
    await seeded_db.flush()
    depo = await depo_fabrikasi("Merkez Depo")
    kart = await kart_fabrikasi("DMR-0012")

    assert (
        await _giris(client, satinalma_headers, depo, kart, order_id=siparis.id)
    ).status_code == 201

    await seeded_db.refresh(siparis)
    await seeded_db.refresh(talep)
    assert siparis.status is PurchaseOrderStatus.delivered
    assert talep.status is PurchaseRequestStatus.delivered


async def test_talepsiz_siparis_zinciri_bozmaz(
    client,
    satinalma_headers,
    seeded_db,
    gorunen_proje,
    tedarikci_fabrikasi,
    siparis_fabrikasi,
    depo_fabrikasi,
    kart_fabrikasi,
):
    """`request_id` NULL (SIP 35 doğrudan siparişi) — zincir yalnız siparişi damgalar."""
    siparis = await siparis_fabrikasi(gorunen_proje, await tedarikci_fabrikasi("Demirsan A.Ş."))
    assert siparis.request_id is None
    depo = await depo_fabrikasi("Merkez Depo")
    kart = await kart_fabrikasi("DMR-0012")

    assert (
        await _giris(client, satinalma_headers, depo, kart, order_id=siparis.id)
    ).status_code == 201
    await seeded_db.refresh(siparis)
    assert siparis.status is PurchaseOrderStatus.delivered


async def test_ikinci_giris_idempotenttir(
    client,
    satinalma_headers,
    seeded_db,
    gorunen_proje,
    tedarikci_fabrikasi,
    siparis_fabrikasi,
    depo_fabrikasi,
    kart_fabrikasi,
):
    """Zaten `delivered` siparişe İKİNCİ giriş **409 DEĞİL**, sessiz geçiştir.

    Karar (T4): stok hareketi bir OLGUDUR — sipariş damgası yüzünden
    reddedilseydi gerçekten gelen mal kayda giremez ve bakiye eksik kalırdı.
    Kısmi teslim ayrımı olmadığı için ikinci parti tam olarak bu yoldan gelir.
    """
    siparis = await siparis_fabrikasi(gorunen_proje, await tedarikci_fabrikasi("Demirsan A.Ş."))
    depo = await depo_fabrikasi("Merkez Depo")
    kart = await kart_fabrikasi("DMR-0012")

    assert (
        await _giris(client, satinalma_headers, depo, kart, order_id=siparis.id)
    ).status_code == 201
    ikinci = await _giris(client, satinalma_headers, depo, kart, order_id=siparis.id)

    assert ikinci.status_code == 201, ikinci.text
    await seeded_db.refresh(siparis)
    assert siparis.status is PurchaseOrderStatus.delivered
    assert (await seeded_db.execute(select(func.count()).select_from(StockEntry))).scalar_one() == 2


# --- Gövde içi varlık referansı = 404 (ST §4b) ---


async def test_gorunmeyen_siparis_referansi_404_ve_hicbir_sey_yazilmaz(
    client,
    satinalma_headers,
    seeded_db,
    gorunmeyen_proje,
    tedarikci_fabrikasi,
    siparis_fabrikasi,
    depo_fabrikasi,
    kart_fabrikasi,
):
    """IDOR: başka projenin siparişi bu kullanıcı için YOKTUR.

    Doğrulama YAZIMDAN ÖNCEDİR: reddedilen istekten geriye hareket KALMAZ.
    """
    siparis = await siparis_fabrikasi(gorunmeyen_proje, await tedarikci_fabrikasi("Demirsan A.Ş."))
    depo = await depo_fabrikasi("Merkez Depo")
    kart = await kart_fabrikasi("DMR-0012")

    yanit = await _giris(client, satinalma_headers, depo, kart, order_id=siparis.id)

    assert yanit.status_code == 404, yanit.text
    assert yanit.json()["detail"] == "Sipariş bulunamadı"
    await seeded_db.refresh(siparis)
    assert siparis.status is PurchaseOrderStatus.approved
    assert (await seeded_db.execute(select(func.count()).select_from(StockEntry))).scalar_one() == 0


async def test_olmayan_siparis_referansi_AYNI_govdeyi_alir(
    client, satinalma_headers, depo_fabrikasi, kart_fabrikasi
):
    depo = await depo_fabrikasi("Merkez Depo")
    kart = await kart_fabrikasi("DMR-0012")

    yanit = await _giris(client, satinalma_headers, depo, kart, order_id=uuid.uuid4())

    assert yanit.status_code == 404, yanit.text
    assert yanit.json()["detail"] == "Sipariş bulunamadı"


@pytest.mark.parametrize("tip", ["transfer", "adjustment"])
async def test_siparis_referansi_yalniz_alim_hareketinde_422(
    client,
    satinalma_headers,
    gorunen_proje,
    tedarikci_fabrikasi,
    siparis_fabrikasi,
    depo_fabrikasi,
    kart_fabrikasi,
    tip,
):
    """SG 85 "İlgili Sipariş" ALIM formunun alanıdır.

    Transferde/düzeltmede sipariş bağı anlamsızdır ve serbest bırakılsaydı bir
    depo transferi siparişi sessizce "teslim edildi" yapardı.
    """
    siparis = await siparis_fabrikasi(gorunen_proje, await tedarikci_fabrikasi("Demirsan A.Ş."))
    depo = await depo_fabrikasi("Merkez Depo")
    kaynak = await depo_fabrikasi("Şantiye Deposu")
    kart = await kart_fabrikasi("DMR-0012")
    ek = {"source_warehouse_id": str(kaynak.id)} if tip == "transfer" else {}

    yanit = await _giris(
        client, satinalma_headers, depo, kart, order_id=siparis.id, entry_type=tip, **ek
    )

    assert yanit.status_code == 422, yanit.text


async def test_siparissiz_giris_hala_calisir(
    client, satinalma_headers, depo_fabrikasi, kart_fabrikasi
):
    """Alan İSTEĞE BAĞLIDIR: sipariş bağı olmayan giriş (SG'nin çoğu) bozulmaz."""
    depo = await depo_fabrikasi("Merkez Depo")
    kart = await kart_fabrikasi("DMR-0012")

    yanit = await _giris(client, satinalma_headers, depo, kart)

    assert yanit.status_code == 201, yanit.text
    assert yanit.json()["purchase_order_id"] is None


# --- Matris (LİTERAL — mutasyon denetimi) ---


def test_teslim_matrisleri_TAM_OLARAK_uc_cifti_tanimlar():
    """🛑 Teslim tabloları MANUEL tablolardan AYRIDIR ve bu bilinçlidir.

    `ORDER_TRANSITIONS` PATCH ucunun tablosudur; oraya `delivered` eklenseydi
    kullanıcı hiç mal girmemiş bir siparişi elle teslim edilmiş yapabilirdi
    (§7 S4'ün tam olarak yasakladığı şey). Teslim damgası AYRI bir tablodan
    geçer ve o tabloyu YALNIZCA `stock_link` kullanır.

    İddia LİTERALDİR: tablodan üretilen bir test, tabloya eklenen beşinci bir
    çifti sessizce yutardı (T3'ün M7 dersi).
    """
    assert transitions.ORDER_DELIVERY_TRANSITIONS == frozenset(
        {
            (PurchaseOrderStatus.approved, PurchaseOrderStatus.delivered),
            (PurchaseOrderStatus.in_transit, PurchaseOrderStatus.delivered),
        }
    )
    assert transitions.REQUEST_DELIVERY_TRANSITIONS == frozenset(
        {(PurchaseRequestStatus.ordered, PurchaseRequestStatus.delivered)}
    )


async def test_elle_delivered_hala_409(
    client, satinalma_headers, gorunen_proje, tedarikci_fabrikasi, siparis_fabrikasi
):
    """Teslim tablosunun açılması PATCH kapısını AÇMAZ (davranış kilidi)."""
    siparis = await siparis_fabrikasi(gorunen_proje, await tedarikci_fabrikasi("Demirsan A.Ş."))

    yanit = await client.patch(
        f"/purchase-orders/{siparis.id}", json={"status": "delivered"}, headers=satinalma_headers
    )

    assert yanit.status_code == 409, yanit.text


# --- İmport yönü bekçisi ---


def _modul_duzeyi_importlar(yol: pathlib.Path) -> list[str]:
    """Dosyanın YALNIZCA modül düzeyindeki (top-level) import adları."""
    agac = ast.parse(yol.read_text(encoding="utf-8"))
    adlar: list[str] = []
    for dugum in agac.body:
        if isinstance(dugum, ast.Import):
            adlar += [ad.name for ad in dugum.names]
        elif isinstance(dugum, ast.ImportFrom) and dugum.module is not None:
            adlar.append(dugum.module)
    return adlar


def test_inventory_modul_duzeyinde_procurement_IMPORT_ETMEZ():
    """P10 `cost_cards` çemberinin tekrarını engelleyen bekçi.

    `procurement → inventory` yönü AÇIKTIR (T2: bakiye ve kart okunur). Ters
    yön modül düzeyinde açılsaydı iki paket birbirini import eder ve içe
    aktarma sırası bir gün 500 üretirdi. ST bağı bu yüzden `stock_link`
    modülüne FONKSİYON İÇİNDEN (gecikmeli) girer.

    🔴 TB7 T4 (kanon 6): `glob("*.py")` yalnız üst düzeyi tarar; `inventory`
    ileride pakete bölünürse (`statement_map` emsali) alt dosyalar denetim
    dışında kalırdı. `rglob` alt dizinleri de kapsar.
    """
    kok = pathlib.Path(__file__).resolve().parents[3] / "app" / "modules" / "inventory"
    for dosya in sorted(kok.rglob("*.py")):
        kirli = [ad for ad in _modul_duzeyi_importlar(dosya) if "procurement" in ad]
        assert kirli == [], (dosya.name, kirli)


def test_procurement_inventory_SERVISINI_import_etmez():
    """Ters yönün kilidi: `procurement` yalnız ST'nin VERİ katmanını okur.

    `inventory.service` import edilseydi, `stock_link` üzerinden geri çağrı
    yapan yol gerçek bir çember kurardı.
    """
    kok = pathlib.Path(__file__).resolve().parents[3] / "app" / "modules" / "procurement"
    for dosya in sorted(kok.rglob("*.py")):
        kirli = [
            ad for ad in _modul_duzeyi_importlar(dosya) if ad == "app.modules.inventory.service"
        ]
        assert kirli == [], (dosya.name, kirli)
