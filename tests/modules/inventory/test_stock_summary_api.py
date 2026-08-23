"""ST T3 — `GET /stock/summary` (E3) ve `GET /sites/{id}/stock` (ŞS).

Spec §3 (türevler) · §7 **S1** (durum formülü) · §7 **S6** (toplam değer).
Mockup: `Ekran 3 - Stok & Depo.dc.html` (**E3**, KPI 72-89) ·
`Şantiye - Stok.dc.html` (**ŞS**, KPI 86-91).

## Durum formülü — kullanıcı ONAYLI, E3'ün verisinden TÜRETİLMİŞ

E3'ün YEDİ örnek satırı formülün kendisidir ve `test_e3_yedi_ornek_satiri`
onları BİREBİR tekrarlar. Sabitler TEK KAYNAKTADIR
(`app/modules/inventory/balance.py`: `CRITICAL_RATIO` / `EXCESS_RATIO`);
sihirli sayı serpilmez ve `min_stock` yoksa durum `None`dur (uydurma yok).

## PENDING (icat yasağı)

E3'ün "Bekleyen Sipariş" KPI'ı ile ŞS'nin "Aylık İhtiyaç"/"Bölüm" sütunlarının
GERÇEK DEĞERİ ÜRETİLMEZ: hiçbir giriş yüzeyi yoktur (sipariş SA diliminin,
bölüm ihtiyacı planlama/BOQ türevinin işidir). Repodaki mevcut yer tutucu
zarfları (`MetricPlaceholder` / `ListPlaceholder`) taşınır.
"""

import re
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal

import pytest
from sqlalchemy import event

from app.modules.inventory.models import StockCategory
from tests.conftest import test_engine

_GUN = "2026-07-27"

# E3 tablosunun yedi satırı: (kod, ad, kategori, birim, bakiye, min, beklenen durum)
E3_SATIRLARI = [
    ("SNK-0421", "Nervürlü Demir Ø12", "steel", "Ton", "2.400", "10.000", "critical"),
    ("SNK-0108", "CTP32,5 Çimento", "structural", "Torba", "840.000", "200.000", "normal"),
    ("ELK-0334", "NYY 4x16 Kablo", "electrical", "Metre", "120.000", "150.000", "low"),
    ("SNK-0055", "Tuğla 19x9x13", "structural", "Adet", "12400.000", "5000.000", "normal"),
    ("SNK-0201", "C25/30 Hazır Beton", "structural", "m³", "85.000", "20.000", "normal"),
    ("MKN-0192", "Su Borusu PP-R 32mm", "mechanical", "Metre", "30.000", "80.000", "critical"),
    ("SNK-0447", "Alçı Levha 12.5mm", "interior", "Adet", "2800.000", "500.000", "excess"),
]


async def _giris(client, headers, depo, kart, miktar, *, fiyat=None, gun=_GUN, tip="purchase"):
    satir = {"item_id": str(kart.id), "quantity": miktar}
    if fiyat is not None:
        satir["unit_price"] = fiyat
    yanit = await client.post(
        "/stock/entries",
        json={
            "entry_type": tip,
            "entry_date": gun,
            "warehouse_id": str(depo.id),
            "lines": [satir],
        },
        headers=headers,
    )
    assert yanit.status_code == 201, yanit.text


async def _ozet(client, headers, sorgu: str = "") -> dict:
    yanit = await client.get(f"/stock/summary{sorgu}", headers=headers)
    assert yanit.status_code == 200, yanit.text
    return yanit.json()


# --- §7 S1: durum formülü ---


@pytest.mark.asyncio
async def test_e3_yedi_ornek_satiri(client, admin_headers, depo_fabrikasi, kart_fabrikasi):
    """E3'ün yedi satırı BİREBİR: oranlar 0,24 · 4,2 · 0,8 · 2,48 · 4,25 ·
    0,375 · 5,6 — formülün kendisi bu veriden türetilmiştir (§7 S1)."""
    depo = await depo_fabrikasi("D-1 Ambar")
    beklenen = {}
    for kod, ad, kategori, birim, bakiye, esik, durum in E3_SATIRLARI:
        kart = await kart_fabrikasi(
            kod, name=ad, category=StockCategory(kategori), unit=birim, min_stock=esik
        )
        await _giris(client, admin_headers, depo, kart, bakiye)
        beklenen[kod] = (bakiye, durum)

    govde = await _ozet(client, admin_headers)
    assert govde["total"] == 7
    for satir in govde["items"]:
        bakiye, durum = beklenen[satir["code"]]
        assert Decimal(satir["balance"]) == Decimal(bakiye), satir["code"]
        assert satir["status"] == durum, f"{satir['code']}: {satir['status']} != {durum}"


@pytest.mark.asyncio
async def test_durum_sinir_degerleri(client, admin_headers, depo_fabrikasi, kart_fabrikasi):
    """Sınırlar KAPALI/AÇIK ayrımıyla: `< %50×min` · `< min` · `> 5×min`.

    Tam eşitlikler bir üst kademededir; `<=` yazılsaydı eşiği TAM tutturan bir
    kalem "kritik" görünür ve satınalma boşuna tetiklenirdi.
    """
    depo = await depo_fabrikasi("Merkez Depo (Sincan)")
    senaryolar = [
        ("SNR-01", "49.999", "critical"),  # %50 eşiğinin hemen ALTI
        ("SNR-02", "50.000", "low"),  # TAM %50×min → kritik DEĞİL
        ("SNR-03", "99.999", "low"),
        ("SNR-04", "100.000", "normal"),  # TAM min → düşük DEĞİL
        ("SNR-05", "500.000", "normal"),  # TAM 5×min → fazla DEĞİL
        ("SNR-06", "500.001", "excess"),
    ]
    for kod, bakiye, _ in senaryolar:
        kart = await kart_fabrikasi(kod, min_stock="100.000")
        await _giris(client, admin_headers, depo, kart, bakiye)

    govde = await _ozet(client, admin_headers, "?limit=200")
    durumlar = {s["code"]: s["status"] for s in govde["items"]}
    for kod, _, beklenen in senaryolar:
        assert durumlar[kod] == beklenen, f"{kod}: {durumlar[kod]} != {beklenen}"


@pytest.mark.asyncio
async def test_esiksiz_kartin_durumu_none(client, admin_headers, depo_fabrikasi, kart_fabrikasi):
    """`min_stock` yoksa durum UYDURULMAZ (spec §3)."""
    depo = await depo_fabrikasi("Merkez Depo (Sincan)")
    kart = await kart_fabrikasi("SNK-9999", min_stock=None)
    await _giris(client, admin_headers, depo, kart, "5.000")

    satir = (await _ozet(client, admin_headers))["items"][0]
    assert satir["min_stock"] is None
    assert satir["status"] is None


@pytest.mark.asyncio
async def test_hareketsiz_kart_sifir_bakiye_ile_listelenir(client, admin_headers, kart_fabrikasi):
    """Katalogda olup hiç hareket görmemiş kart 0 bakiye ile görünür — listeden
    DÜŞMEZ, yoksa "min 10 olan kalem hiç alınmamış" uyarısı hiç doğmazdı."""
    await kart_fabrikasi("SNK-0421", min_stock="10.000")
    satir = (await _ozet(client, admin_headers))["items"][0]
    assert Decimal(satir["balance"]) == Decimal("0")
    assert satir["status"] == "critical"


# --- Pasif kalem görünürlüğü (F-ST canlı smoke bulgusu, yönetim kararı 2026-08-12) ---
#
# pasif + bakiye 0  → SÜZÜLÜR (pasifleştirilen, elde kalmayan kart katalogda yer kaplamaz)
# pasif + bakiye ≠ 0 → LİSTELENİR (envanter gerçeği gizlenmez)
# aktif             → HER ZAMAN listelenir (bakiye 0 olsa da)
# KPI sayaçları AYNI kurala uyar: liste ile sayaç ayrışırsa ekranda "3 kalem"
# yazıp 2 satır görünürdü.


@pytest.mark.asyncio
async def test_ozet_pasif_bakiyesiz_kart_listelenmez(client, admin_headers, kart_fabrikasi):
    """Pasif + bakiye 0 → ne listede ne KPI'da (canlıda `SMOKE-FST-01` kaldı)."""
    await kart_fabrikasi("SNK-0421", min_stock="10.000")
    await kart_fabrikasi("PSF-0001", name="Pasif Bakiyesiz", is_active=False)

    govde = await _ozet(client, admin_headers, "?limit=200")
    assert {s["code"] for s in govde["items"]} == {"SNK-0421"}
    assert govde["total"] == 1
    assert govde["kpis"]["total_items"] == 1


@pytest.mark.asyncio
async def test_ozet_pasif_bakiyeli_kart_listelenir(
    client, admin_headers, depo_fabrikasi, kart_fabrikasi
):
    """Pasif + bakiye ≠ 0 → LİSTELENİR: elde stoğu olan kartı saklamak yanıltıcı."""
    depo = await depo_fabrikasi("Merkez Depo (Sincan)")
    kart = await kart_fabrikasi("PSF-0002", name="Pasif Bakiyeli", is_active=False)
    await _giris(client, admin_headers, depo, kart, "7.000", fiyat="10.00")

    govde = await _ozet(client, admin_headers, "?limit=200")
    assert {s["code"] for s in govde["items"]} == {"PSF-0002"}
    assert govde["total"] == 1
    assert govde["kpis"]["total_items"] == 1
    assert Decimal(govde["kpis"]["total_value"]) == Decimal("70.00")


@pytest.mark.asyncio
async def test_ozet_aktif_bakiyesiz_kart_listelenir(client, admin_headers, kart_fabrikasi):
    """Aktif + bakiye 0 → listede VE KPI'da: "min 10 olan kalem hiç alınmamış"
    uyarısı ancak böyle doğar."""
    await kart_fabrikasi("SNK-0421", min_stock="10.000")

    govde = await _ozet(client, admin_headers, "?limit=200")
    assert {s["code"] for s in govde["items"]} == {"SNK-0421"}
    assert govde["kpis"]["total_items"] == 1
    assert govde["kpis"]["critical_count"] == 1


# --- Süzgeçler (E3 filtre çubuğu) ---


@pytest.mark.asyncio
async def test_ozet_suzgecleri(client, admin_headers, depo_fabrikasi, kart_fabrikasi):
    depo = await depo_fabrikasi("D-1 Ambar")
    for kod, ad, kategori, birim, bakiye, esik, _ in E3_SATIRLARI:
        kart = await kart_fabrikasi(
            kod, name=ad, category=StockCategory(kategori), unit=birim, min_stock=esik
        )
        await _giris(client, admin_headers, depo, kart, bakiye)

    kritik = await _ozet(client, admin_headers, "?status=critical")
    assert {s["code"] for s in kritik["items"]} == {"SNK-0421", "MKN-0192"}
    assert kritik["total"] == 2

    kategori = await _ozet(client, admin_headers, "?category=structural")
    assert kategori["total"] == 3

    arama = await _ozet(client, admin_headers, "?q=SNK-04")
    assert {s["code"] for s in arama["items"]} == {"SNK-0421", "SNK-0447"}


@pytest.mark.asyncio
async def test_ozet_sayfalama_tavani(client, admin_headers):
    assert (await client.get("/stock/summary?limit=201", headers=admin_headers)).status_code == 422
    govde = await _ozet(client, admin_headers)
    assert govde["limit"] == 50
    assert govde["offset"] == 0


# --- §7 S6: toplam değer + fiyatsız kalem ---


@pytest.mark.asyncio
async def test_toplam_deger_son_giris_fiyatiyla(
    client, admin_headers, depo_fabrikasi, kart_fabrikasi
):
    """SON giriş fiyatı × bakiye. Ağırlıklı ortalama İCAT EDİLMEZ (§7 S6):
    10×100 + 10×200 alımı 3000 değil **4000** eder (son fiyat 200, bakiye 20)."""
    depo = await depo_fabrikasi("Merkez Depo (Sincan)")
    kart = await kart_fabrikasi("SNK-0421")
    await _giris(client, admin_headers, depo, kart, "10.000", fiyat="100.00", gun="2026-07-01")
    await _giris(client, admin_headers, depo, kart, "10.000", fiyat="200.00", gun="2026-07-10")

    govde = await _ozet(client, admin_headers)
    assert Decimal(govde["items"][0]["last_unit_price"]) == Decimal("200.00")
    assert Decimal(govde["kpis"]["total_value"]) == Decimal("4000.00")


@pytest.mark.asyncio
async def test_fiyatsiz_hareket_son_fiyati_silmez(
    client, admin_headers, depo_fabrikasi, kart_fabrikasi
):
    """Transfer/düzeltme satırlarında fiyat YOKTUR; sonradan gelen fiyatsız bir
    hareket kalemi değerden DÜŞÜRMEZ — yalnız FİYATLI girişler sayılır."""
    depo = await depo_fabrikasi("Merkez Depo (Sincan)")
    kart = await kart_fabrikasi("SNK-0421")
    await _giris(client, admin_headers, depo, kart, "10.000", fiyat="100.00", gun="2026-07-01")
    await _giris(client, admin_headers, depo, kart, "5.000", gun="2026-07-20", tip="adjustment")

    govde = await _ozet(client, admin_headers)
    assert Decimal(govde["items"][0]["last_unit_price"]) == Decimal("100.00")
    assert Decimal(govde["kpis"]["total_value"]) == Decimal("1500.00")


@pytest.mark.asyncio
async def test_fiyatsiz_kalem_degere_girmez_ve_ayrica_raporlanir(
    client, admin_headers, depo_fabrikasi, kart_fabrikasi
):
    """Fiyatsız kalem SESSİZCE 0 SAYILMAZ: değere girmez ve `items_without_price`
    sayacında ayrıca raporlanır (§7 S6) — yoksa "değer neden düşük" sorusu
    cevapsız kalırdı."""
    depo = await depo_fabrikasi("Merkez Depo (Sincan)")
    fiyatli = await kart_fabrikasi("SNK-0421")
    fiyatsiz = await kart_fabrikasi("SNK-0108", name="CTP32,5 Çimento")
    bos = await kart_fabrikasi("SNK-0055", name="Tuğla 19x9x13")
    await _giris(client, admin_headers, depo, fiyatli, "10.000", fiyat="100.00")
    await _giris(client, admin_headers, depo, fiyatsiz, "40.000")

    kpi = (await _ozet(client, admin_headers))["kpis"]
    assert Decimal(kpi["total_value"]) == Decimal("1000.00")
    # Bakiyesi olup fiyatı olmayan TEK kalem: hiç hareket görmemiş kart (bos)
    # değeri zaten etkilemez, sayaca da girmez.
    assert kpi["items_without_price"] == 1
    assert bos.code == "SNK-0055"


# --- E3 KPI'ları (72-89) ---


@pytest.mark.asyncio
async def test_e3_kpi_seridi(client, admin_headers, depo_fabrikasi, kart_fabrikasi):
    depo = await depo_fabrikasi("D-1 Ambar")
    for kod, ad, kategori, birim, bakiye, esik, _ in E3_SATIRLARI:
        kart = await kart_fabrikasi(
            kod, name=ad, category=StockCategory(kategori), unit=birim, min_stock=esik
        )
        await _giris(client, admin_headers, depo, kart, bakiye, fiyat="10.00")

    kpi = (await _ozet(client, admin_headers))["kpis"]
    assert kpi["critical_count"] == 2  # demir + PP-R
    assert kpi["low_count"] == 1  # NYY
    assert kpi["total_items"] == 7
    toplam_bakiye = sum(Decimal(s[4]) for s in E3_SATIRLARI)
    assert Decimal(kpi["total_value"]) == toplam_bakiye * Decimal("10.00")


@pytest.mark.asyncio
async def test_kpi_sayfalanan_degil_tum_kumeyi_kapsar(
    client, admin_headers, depo_fabrikasi, kart_fabrikasi
):
    """KPI şeridi SAYFAYI değil SÜZÜLEN KÜMEYİ özetler: sayfa başına
    hesaplansaydı ikinci sayfada "toplam stok değeri" değişirdi."""
    depo = await depo_fabrikasi("D-1 Ambar")
    for kod, ad, kategori, birim, bakiye, esik, _ in E3_SATIRLARI:
        kart = await kart_fabrikasi(
            kod, name=ad, category=StockCategory(kategori), unit=birim, min_stock=esik
        )
        await _giris(client, admin_headers, depo, kart, bakiye, fiyat="10.00")

    ilk_sayfa = await _ozet(client, admin_headers, "?limit=2")
    assert len(ilk_sayfa["items"]) == 2
    assert ilk_sayfa["total"] == 7
    assert ilk_sayfa["kpis"]["total_items"] == 7
    assert ilk_sayfa["kpis"]["critical_count"] == 2


@pytest.mark.asyncio
async def test_bekleyen_siparis_zarfi_gercektir(client, admin_headers):
    """E3 "Bekleyen Sipariş": SA T4'te GERÇEĞE döndü.

    Sipariş tablosu artık VARDIR; zarf DOLUDUR (`available=true`) ve bu yüzden
    `pending_module` **null**dur — dolu bir zarf "hangi modül gelince dolacak"
    bilgisi taşımaz (`MetricPlaceholder` sözleşmesi, P10 T3).

    Sipariş verisiyle kurulmuş uçtan uca hâli `tests/modules/procurement/
    test_purchasing_summary_api.py`dedir (bu paketin fixture'ları satınalma
    kayıtları üretmez).
    """
    zarf = (await _ozet(client, admin_headers))["kpis"]["pending_orders"]
    assert zarf["available"] is True
    assert zarf["value"] == "0"
    assert zarf["pending_module"] is None


# --- Depo kırılımı ---


@pytest.mark.asyncio
async def test_depo_kirilimi(
    client, admin_headers, gorunen_santiye, depo_fabrikasi, kart_fabrikasi
):
    """E3 "Depo" sütunu: kalem birden çok depoda durabilir."""
    d1 = await depo_fabrikasi("D-1 Ambar", site=gorunen_santiye)
    d2 = await depo_fabrikasi("Merkez Depo (Sincan)")
    kart = await kart_fabrikasi("SNK-0421")
    await _giris(client, admin_headers, d1, kart, "6.000")
    await _giris(client, admin_headers, d2, kart, "4.000")

    satir = (await _ozet(client, admin_headers))["items"][0]
    kirilim = {k["warehouse_name"]: k for k in satir["warehouses"]}
    assert Decimal(kirilim["D-1 Ambar"]["balance"]) == Decimal("6.000")
    assert kirilim["D-1 Ambar"]["site_id"] == str(gorunen_santiye.id)
    assert Decimal(kirilim["Merkez Depo (Sincan)"]["balance"]) == Decimal("4.000")
    assert kirilim["Merkez Depo (Sincan)"]["site_id"] is None


@pytest.mark.asyncio
async def test_ozet_gorunmeyen_depoyu_bakiyeye_katmaz(
    client, admin_headers, satinalma_headers, gorunmeyen_santiye, depo_fabrikasi, kart_fabrikasi
):
    """IDOR: başka projenin deposundaki stok bakiyeye de kırılıma da GİRMEZ."""
    gizli = await depo_fabrikasi("D-9 Ambar", site=gorunmeyen_santiye)
    acik = await depo_fabrikasi("Merkez Depo (Sincan)")
    kart = await kart_fabrikasi("SNK-0421")
    await _giris(client, admin_headers, gizli, kart, "70.000")
    await _giris(client, admin_headers, acik, kart, "30.000")

    kisitli = (await _ozet(client, satinalma_headers))["items"][0]
    assert Decimal(kisitli["balance"]) == Decimal("30.000")
    assert [k["warehouse_name"] for k in kisitli["warehouses"]] == ["Merkez Depo (Sincan)"]

    tam = (await _ozet(client, admin_headers))["items"][0]
    assert Decimal(tam["balance"]) == Decimal("100.000")


# --- ŞS: GET /sites/{id}/stock ---


@pytest.mark.asyncio
async def test_santiye_stogu_merkez_depoyu_saymaz(
    client, admin_headers, gorunen_santiye, depo_fabrikasi, kart_fabrikasi
):
    """Spec §3 kararı: "şantiye bakiyesi = o şantiyenin depoları". Merkez depo
    (`site_id IS NULL`) HİÇBİR şantiyenin bakiyesine girmez."""
    santiye_deposu = await depo_fabrikasi("D-1 Ambar", site=gorunen_santiye)
    merkez = await depo_fabrikasi("Merkez Depo (Sincan)")
    kart = await kart_fabrikasi("SNK-0421", min_stock="10.000")
    await _giris(client, admin_headers, santiye_deposu, kart, "2.400")
    await _giris(client, admin_headers, merkez, kart, "500.000")

    yanit = await client.get(f"/sites/{gorunen_santiye.id}/stock", headers=admin_headers)
    assert yanit.status_code == 200, yanit.text
    satir = yanit.json()["items"][0]
    assert Decimal(satir["balance"]) == Decimal("2.400")
    assert satir["status"] == "critical"


@pytest.mark.asyncio
async def test_santiye_stogu_hareketsiz_karti_listelemez(
    client, admin_headers, gorunen_santiye, depo_fabrikasi, kart_fabrikasi
):
    """ŞS "o şantiyenin malzemeleri" ekranıdır: şantiyeye hiç girmemiş katalog
    kartı listeyi doldurmaz (genel özetin aksine)."""
    depo = await depo_fabrikasi("D-1 Ambar", site=gorunen_santiye)
    giren = await kart_fabrikasi("SNK-0421")
    await kart_fabrikasi("SNK-9999", name="Hiç Girmeyen")
    await _giris(client, admin_headers, depo, giren, "5.000")

    govde = (await client.get(f"/sites/{gorunen_santiye.id}/stock", headers=admin_headers)).json()
    assert govde["total"] == 1
    assert govde["items"][0]["code"] == "SNK-0421"


@pytest.mark.asyncio
async def test_santiye_stogu_pasif_bakiyesiz_karti_listelemez(
    client, admin_headers, gorunen_santiye, depo_fabrikasi, kart_fabrikasi
):
    """Pasif + bakiye 0 → ŞS'de de düşer; hareketi OLSA bile (giriş + düzeltme
    ile sıfırlanmış). Sayaç da düşer, yoksa liste ile KPI ayrışırdı."""
    depo = await depo_fabrikasi("D-1 Ambar", site=gorunen_santiye)
    kalan = await kart_fabrikasi("SNK-0421", min_stock="10.000")
    biten = await kart_fabrikasi("PSF-0001", name="Pasif Bakiyesiz", is_active=False)
    await _giris(client, admin_headers, depo, kalan, "5.000")
    await _giris(client, admin_headers, depo, biten, "5.000")
    await _giris(client, admin_headers, depo, biten, "-5.000", tip="adjustment")

    govde = (
        await client.get(f"/sites/{gorunen_santiye.id}/stock?limit=200", headers=admin_headers)
    ).json()
    assert {s["code"] for s in govde["items"]} == {"SNK-0421"}
    assert govde["total"] == 1
    assert govde["kpis"]["total_items"] == 1


@pytest.mark.asyncio
async def test_santiye_stogu_pasif_bakiyeli_karti_listeler(
    client, admin_headers, gorunen_santiye, depo_fabrikasi, kart_fabrikasi
):
    """Pasif + bakiye ≠ 0 → ŞS'de KALIR: şantiyede fiilen duran malzeme gizlenmez."""
    depo = await depo_fabrikasi("D-1 Ambar", site=gorunen_santiye)
    kart = await kart_fabrikasi("PSF-0002", name="Pasif Bakiyeli", is_active=False)
    await _giris(client, admin_headers, depo, kart, "7.000", fiyat="10.00")

    govde = (
        await client.get(f"/sites/{gorunen_santiye.id}/stock?limit=200", headers=admin_headers)
    ).json()
    assert {s["code"] for s in govde["items"]} == {"PSF-0002"}
    assert govde["kpis"]["total_items"] == 1
    assert Decimal(govde["kpis"]["total_value"]) == Decimal("70.00")


@pytest.mark.asyncio
async def test_santiye_stogu_aktif_bakiyesiz_karti_listeler(
    client, admin_headers, gorunen_santiye, depo_fabrikasi, kart_fabrikasi
):
    """Aktif + bakiye 0 → ŞS'de KALIR: "bu şantiyede tükendi" bilgisi "hiç
    olmadı"dan farklıdır (hareketi olduğu için ŞS'nin INNER JOIN'ine girer)."""
    depo = await depo_fabrikasi("D-1 Ambar", site=gorunen_santiye)
    kart = await kart_fabrikasi("SNK-0421", min_stock="10.000")
    await _giris(client, admin_headers, depo, kart, "5.000")
    await _giris(client, admin_headers, depo, kart, "-5.000", tip="adjustment")

    govde = (
        await client.get(f"/sites/{gorunen_santiye.id}/stock?limit=200", headers=admin_headers)
    ).json()
    assert {s["code"] for s in govde["items"]} == {"SNK-0421"}
    assert Decimal(govde["items"][0]["balance"]) == Decimal("0")
    assert govde["kpis"]["total_items"] == 1


@pytest.mark.asyncio
async def test_santiye_stogu_kpi_seridi(
    client, admin_headers, gorunen_santiye, depo_fabrikasi, kart_fabrikasi
):
    """ŞS 86-91: Toplam Malzeme · Kritik · Düşük · Stok Değeri.
    E3'ün aksine "Bekleyen Sipariş" YOKTUR (mockup'ta o kart çizilmemiş)."""
    depo = await depo_fabrikasi("D-1 Ambar", site=gorunen_santiye)
    kritik = await kart_fabrikasi("SNK-0421", min_stock="10.000")
    dusuk = await kart_fabrikasi("ELK-0334", name="NYY 4x16 Kablo", min_stock="150.000")
    await _giris(client, admin_headers, depo, kritik, "2.400", fiyat="10.00")
    await _giris(client, admin_headers, depo, dusuk, "120.000", fiyat="5.00")

    kpi = (await client.get(f"/sites/{gorunen_santiye.id}/stock", headers=admin_headers)).json()[
        "kpis"
    ]
    assert kpi["total_items"] == 2
    assert kpi["critical_count"] == 1
    assert kpi["low_count"] == 1
    assert Decimal(kpi["total_value"]) == Decimal("624.00")  # 2,4×10 + 120×5
    assert "pending_orders" not in kpi


@pytest.mark.asyncio
async def test_santiye_stogu_pending_sutunlari(
    client, admin_headers, gorunen_santiye, depo_fabrikasi, kart_fabrikasi
):
    """ŞS "Aylık İhtiyaç" ve "Bölüm" sütunlarının GİRİŞ YÜZEYİ YOKTUR: değer
    uydurulmaz, yer tutucu zarf kaynağı bildirir (spec §3, §5)."""
    depo = await depo_fabrikasi("D-1 Ambar", site=gorunen_santiye)
    kart = await kart_fabrikasi("SNK-0421")
    await _giris(client, admin_headers, depo, kart, "5.000")

    satir = (await client.get(f"/sites/{gorunen_santiye.id}/stock", headers=admin_headers)).json()[
        "items"
    ][0]
    assert satir["monthly_need"] == {
        "available": False,
        "value": None,
        "pending_module": "site_planning",
    }
    assert satir["section"]["available"] is False
    assert satir["section"]["items"] == []
    assert satir["section"]["pending_module"] == "site_planning"


@pytest.mark.asyncio
async def test_santiye_stogu_gorunmeyen_santiye_404(client, satinalma_headers, gorunmeyen_santiye):
    import uuid as _uuid

    gizli = await client.get(f"/sites/{gorunmeyen_santiye.id}/stock", headers=satinalma_headers)
    olmayan = await client.get(f"/sites/{_uuid.uuid4()}/stock", headers=satinalma_headers)
    assert gizli.status_code == olmayan.status_code == 404
    assert gizli.json()["detail"] == olmayan.json()["detail"]


@pytest.mark.asyncio
async def test_santiye_stogu_yetkisiz_403(client, yetkisiz_headers, gorunen_santiye):
    yanit = await client.get(f"/sites/{gorunen_santiye.id}/stock", headers=yetkisiz_headers)
    assert yanit.status_code == 403, yanit.text


# --- N+1 ÖLÇÜMÜ ---


@contextmanager
def _sorgu_sayaci() -> Iterator[list[str]]:
    """Sürücüye giden HER ifadeyi toplar (`test_projects_timeline` emsali):
    sorgu sayısı iddiaları tahmine değil ÖLÇÜME dayanır."""
    ifadeler: list[str] = []

    def kaydet(conn, cursor, statement, parameters, context, executemany) -> None:  # noqa: ANN001
        ifadeler.append(" ".join(statement.split()))

    event.listen(test_engine.sync_engine, "before_cursor_execute", kaydet)
    try:
        yield ifadeler
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", kaydet)


_STOK_TABLOLARI = re.compile(r"\b(stock_items|stock_entries|stock_entry_lines|warehouses)\b")


def _stok_sorgulari(ifadeler: list[str]) -> list[str]:
    """Yalnız stok tablolarına giden ifadeler; kimlik doğrulama (users/roles)
    sorguları veri hacminden bağımsızdır ve sayıma girmez."""
    return [i for i in ifadeler if _STOK_TABLOLARI.search(i)]


async def _hacim_kur(
    client, headers, depo_fabrikasi, kart_fabrikasi, kart_sayisi, depo_sayisi, onek
):
    depolar = [await depo_fabrikasi(f"{onek}-D{i}") for i in range(depo_sayisi)]
    for k in range(kart_sayisi):
        kart = await kart_fabrikasi(f"{onek}-{k:04d}", min_stock="10.000")
        for depo in depolar:
            await _giris(client, headers, depo, kart, "3.000", fiyat="7.00")


@pytest.mark.asyncio
async def test_ozet_ucunda_n_plus_1_yok(client, admin_headers, depo_fabrikasi, kart_fabrikasi):
    """Kalem/depo sayısı artınca sorgu sayısı SABİT kalmalı."""
    await _hacim_kur(client, admin_headers, depo_fabrikasi, kart_fabrikasi, 2, 2, "AZ")
    with _sorgu_sayaci() as ifadeler:
        await _ozet(client, admin_headers, "?limit=200")
    kucuk = len(_stok_sorgulari(ifadeler))

    await _hacim_kur(client, admin_headers, depo_fabrikasi, kart_fabrikasi, 6, 4, "COK")
    with _sorgu_sayaci() as ifadeler:
        await _ozet(client, admin_headers, "?limit=200")
    buyuk = len(_stok_sorgulari(ifadeler))

    assert kucuk == buyuk, f"N+1: küçük hacimde {kucuk}, büyük hacimde {buyuk} sorgu"

    # 🔴 MUTLAK TAVAN (P-YT3 T3, 2026-08-23). Yukaridaki esitlik iddiasi
    # "N+1 yok" der ama "maliyet artmadi" DEMEZ: hacimden BAGIMSIZ sabit bir
    # ek sorgu iki olcumu de ayni miktarda kaydirir ve iddia YESIL kalir
    # (P-YT2 dashboard'da olctu, P-YT3 satis listesinde tekrar uretti).
    # Tavan o sinifi gorur. SINIRI: sayac yalniz STOK tablolarini sayar
    # (`_stok_sorgulari`), baska bir tabloya acilan sabit sorgu buraya da
    # gorunmez. Sayiyi DUSURMEK serbest, YUKSELTMEK gerekcelidir.
    #
    # Tavan BOSLUKSUZ (olculen sayinin kendisi): sayac zaten kimlik/rol
    # sorgularini disarida birakiyor, yani altyapi calkantisi bu sayiyi
    # oynatmaz — bir bosluk birakmak yalnizca o kadarlik bir mutasyonu
    # gorunmez kilardi (fiilen olculdu: tavan 4 iken +1 mutasyon YESIL kaldi).
    assert buyuk <= 4, f"/stock/summary sicak yolu {buyuk} stok sorgusuna cikti (tavan 4)"


@pytest.mark.asyncio
async def test_santiye_stok_ucunda_n_plus_1_yok(
    client, admin_headers, gorunen_santiye, depo_fabrikasi, kart_fabrikasi
):
    async def _kur(kart_sayisi: int, onek: str) -> None:
        depo = await depo_fabrikasi(f"{onek}-Depo", site=gorunen_santiye)
        for k in range(kart_sayisi):
            kart = await kart_fabrikasi(f"{onek}-{k:04d}", min_stock="10.000")
            await _giris(client, admin_headers, depo, kart, "3.000", fiyat="7.00")

    async def _olc() -> int:
        with _sorgu_sayaci() as ifadeler:
            yanit = await client.get(
                f"/sites/{gorunen_santiye.id}/stock?limit=200", headers=admin_headers
            )
            assert yanit.status_code == 200, yanit.text
        return len(_stok_sorgulari(ifadeler))

    await _kur(2, "AZ")
    kucuk = await _olc()
    await _kur(8, "COK")
    buyuk = await _olc()

    assert kucuk == buyuk, f"N+1: küçük hacimde {kucuk}, büyük hacimde {buyuk} sorgu"

    # 🔴 MUTLAK TAVAN (P-YT3 T3, 2026-08-23). Yukaridaki esitlik iddiasi
    # "N+1 yok" der ama "maliyet artmadi" DEMEZ: hacimden BAGIMSIZ sabit bir
    # ek sorgu iki olcumu de ayni miktarda kaydirir ve iddia YESIL kalir
    # (P-YT2 dashboard'da olctu, P-YT3 satis listesinde tekrar uretti).
    # Tavan o sinifi gorur. SINIRI: sayac yalniz STOK tablolarini sayar
    # (`_stok_sorgulari`), baska bir tabloya acilan sabit sorgu buraya da
    # gorunmez. Sayiyi DUSURMEK serbest, YUKSELTMEK gerekcelidir.
    #
    # Tavan BOSLUKSUZ (olculen sayinin kendisi): sayac zaten kimlik/rol
    # sorgularini disarida birakiyor, yani altyapi calkantisi bu sayiyi
    # oynatmaz — bir bosluk birakmak yalnizca o kadarlik bir mutasyonu
    # gorunmez kilardi (fiilen olculdu: tavan 4 iken +1 mutasyon YESIL kaldi).
    assert buyuk <= 3, f"ŞS sicak yolu {buyuk} stok sorgusuna cikti (tavan 3)"
