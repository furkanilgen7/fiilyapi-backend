"""ST T3 — ÇİFT BACAK ve türev bakiye. Bu dilimin BİR NUMARALI TUZAĞI.

Spec §3 (bakiye = SUM türevi, kolon YOK) · §7 S4 (transfer çift bacak).

`transfer` tipinde miktar hedef depoya **artı**, kaynak depodan **eksi** yansır.
Tek bacaklı bir transfer YOKTAN STOK YARATIR ve şirket toplamını şişirir; bu
dosyanın taşıyıcı testi `test_transfer_sirket_toplamini_degistirmez`dir.

Türetme AYNA SATIR YAZMAZ: kaynak bacağı bakiye sorgusunun kendisinde
(`app/modules/inventory/balance.py`) `source_warehouse_id` üzerinden NEGATİF
işaretle üretilir — böylece hareket başlığı TEK kalır (audit tek olay), ayna
satırlar hareket listesini ikiye katlamaz ve "iki kayıt birbirinden sapar"
riski hiç doğmaz.
"""

from decimal import Decimal

import pytest

_GUN = "2026-07-27"


async def _hareket(client, headers, tip, hedef, kart, miktar, *, kaynak=None, fiyat=None):
    satir = {"item_id": str(kart.id), "quantity": miktar}
    if fiyat is not None:
        satir["unit_price"] = fiyat
    govde = {
        "entry_type": tip,
        "entry_date": _GUN,
        "warehouse_id": str(hedef.id),
        "lines": [satir],
    }
    if kaynak is not None:
        govde["source_warehouse_id"] = str(kaynak.id)
    yanit = await client.post("/stock/entries", json=govde, headers=headers)
    assert yanit.status_code == 201, yanit.text
    return yanit.json()


async def _ozet_satiri(client, headers, kod: str) -> dict:
    yanit = await client.get("/stock/summary", headers=headers)
    assert yanit.status_code == 200, yanit.text
    return next(s for s in yanit.json()["items"] if s["code"] == kod)


def _depo_bakiyesi(satir: dict, depo_id) -> Decimal:
    kirilim = next((k for k in satir["warehouses"] if k["warehouse_id"] == str(depo_id)), None)
    return Decimal("0") if kirilim is None else Decimal(kirilim["balance"])


@pytest.mark.asyncio
async def test_transfer_sirket_toplamini_degistirmez(
    client, admin_headers, gorunen_santiye, depo_fabrikasi, kart_fabrikasi
):
    """TOPLAM KORUNUMU — T4 review'ünün bizzat deneyeceği test.

    A'da 100 varken A→B 40 transferinden sonra: A 60'a DÜŞER, B 40'a ÇIKAR,
    şirket geneli toplam 100'de KALIR. Tek bacaklı bir uygulamada toplam 140
    olurdu (yoktan 40 stok).
    """
    a = await depo_fabrikasi("D-1 Ambar", site=gorunen_santiye)
    b = await depo_fabrikasi("Merkez Depo (Sincan)")
    kart = await kart_fabrikasi("SNK-0421", min_stock=None)

    await _hareket(client, admin_headers, "purchase", a, kart, "100.000")
    once = await _ozet_satiri(client, admin_headers, "SNK-0421")
    assert Decimal(once["balance"]) == Decimal("100.000")

    await _hareket(client, admin_headers, "transfer", b, kart, "40.000", kaynak=a)
    sonra = await _ozet_satiri(client, admin_headers, "SNK-0421")

    assert _depo_bakiyesi(sonra, a.id) == Decimal("60.000"), "kaynak bacak DÜŞMEDİ"
    assert _depo_bakiyesi(sonra, b.id) == Decimal("40.000"), "hedef bacak ARTMADI"
    assert Decimal(sonra["balance"]) == Decimal("100.000"), (
        "TOPLAM KORUNUMU KIRILDI: transfer yoktan stok yarattı"
    )


@pytest.mark.asyncio
async def test_zincirli_senaryo_transfer_duzeltme_transfer(
    client, admin_headers, gorunen_santiye, depo_fabrikasi, kart_fabrikasi
):
    """Transfer → negatif düzeltme → tekrar transfer.

    Düzeltme TOPLAMI DEĞİŞTİRİR (gerçek sarf/iade), transfer DEĞİŞTİRMEZ.
    İkisinin farkı bakiye türevinin doğruluk ölçüsüdür.
    """
    a = await depo_fabrikasi("D-1 Ambar", site=gorunen_santiye)
    b = await depo_fabrikasi("D-2 Açık Alan", site=gorunen_santiye)
    c = await depo_fabrikasi("Merkez Depo (Sincan)")
    kart = await kart_fabrikasi("SNK-0108", name="CTP32,5 Çimento")

    await _hareket(client, admin_headers, "purchase", a, kart, "1000.000")
    await _hareket(client, admin_headers, "transfer", b, kart, "300.000", kaynak=a)
    # Sarf: B deposundan 120 harcandı (tek çıkış kapısı `adjustment`, §7 S4).
    await _hareket(client, admin_headers, "adjustment", b, kart, "-120.000")
    await _hareket(client, admin_headers, "transfer", c, kart, "80.000", kaynak=b)

    satir = await _ozet_satiri(client, admin_headers, "SNK-0108")
    assert _depo_bakiyesi(satir, a.id) == Decimal("700.000")
    assert _depo_bakiyesi(satir, b.id) == Decimal("100.000")
    assert _depo_bakiyesi(satir, c.id) == Decimal("80.000")
    # 1000 alındı, 120 harcandı → 880. Üç transfer toplamı DEĞİŞTİRMEDİ.
    assert Decimal(satir["balance"]) == Decimal("880.000")
    assert sum(Decimal(k["balance"]) for k in satir["warehouses"]) == Decimal("880.000")


@pytest.mark.asyncio
async def test_ileri_geri_transfer_bakiyeyi_baslangica_dondurur(
    client, admin_headers, gorunen_santiye, depo_fabrikasi, kart_fabrikasi
):
    """A→B→A: iki bacak simetrik olmasaydı stok yolda kaybolur ya da çoğalırdı."""
    a = await depo_fabrikasi("D-1 Ambar", site=gorunen_santiye)
    b = await depo_fabrikasi("Merkez Depo (Sincan)")
    kart = await kart_fabrikasi("SNK-0055", name="Tuğla 19x9x13")

    await _hareket(client, admin_headers, "purchase", a, kart, "50.000")
    await _hareket(client, admin_headers, "transfer", b, kart, "50.000", kaynak=a)
    await _hareket(client, admin_headers, "transfer", a, kart, "50.000", kaynak=b)

    satir = await _ozet_satiri(client, admin_headers, "SNK-0055")
    assert _depo_bakiyesi(satir, a.id) == Decimal("50.000")
    assert _depo_bakiyesi(satir, b.id) == Decimal("0.000")
    assert Decimal(satir["balance"]) == Decimal("50.000")


@pytest.mark.asyncio
async def test_transfer_kaynak_depoyu_eksiye_dusurebilir(
    client, admin_headers, depo_fabrikasi, kart_fabrikasi
):
    """§7 S4: eksi bakiye ENGELLENMEZ, yalnız türevde görünür."""
    a = await depo_fabrikasi("Merkez Depo (Sincan)")
    b = await depo_fabrikasi("D-3 Kapalı")
    kart = await kart_fabrikasi("MKN-0192", name="Su Borusu PP-R 32mm")

    await _hareket(client, admin_headers, "transfer", b, kart, "25.000", kaynak=a)

    satir = await _ozet_satiri(client, admin_headers, "MKN-0192")
    assert _depo_bakiyesi(satir, a.id) == Decimal("-25.000")
    assert _depo_bakiyesi(satir, b.id) == Decimal("25.000")
    assert Decimal(satir["balance"]) == Decimal("0.000")


@pytest.mark.asyncio
async def test_santiye_bakiyesi_ile_genel_ozet_ayni_turetmeyi_kullanir(
    client, admin_headers, gorunen_santiye, depo_fabrikasi, kart_fabrikasi
):
    """TEK KANONİK TÜRETME: `/stock/summary` depo kırılımı ile
    `/sites/{id}/stock` bakiyesi AYNI sayıyı vermek zorundadır.

    **Merkez depo hiçbir şantiyenin bakiyesine GİRMEZ** (spec §3): şantiye
    bakiyesi "o şantiyenin depoları"dır. Genel özet ise merkez dahil hepsini
    kapsar — bu testin iki tarafı bu ayrımı da kilitler.
    """
    santiye_deposu = await depo_fabrikasi("D-1 Ambar", site=gorunen_santiye)
    merkez = await depo_fabrikasi("Merkez Depo (Sincan)")
    kart = await kart_fabrikasi("SNK-0201", name="C25/30 Hazır Beton")

    await _hareket(client, admin_headers, "purchase", santiye_deposu, kart, "85.000")
    await _hareket(client, admin_headers, "purchase", merkez, kart, "15.000")

    genel = await _ozet_satiri(client, admin_headers, "SNK-0201")
    assert Decimal(genel["balance"]) == Decimal("100.000")

    santiye = await client.get(f"/sites/{gorunen_santiye.id}/stock", headers=admin_headers)
    assert santiye.status_code == 200, santiye.text
    satir = next(s for s in santiye.json()["items"] if s["code"] == "SNK-0201")
    assert Decimal(satir["balance"]) == Decimal("85.000")
    assert Decimal(satir["balance"]) == _depo_bakiyesi(genel, santiye_deposu.id)


@pytest.mark.asyncio
async def test_bakiye_kolonu_acilmadi(client, admin_headers, depo_fabrikasi, kart_fabrikasi):
    """BEKÇİ: bakiye TÜREVDİR (spec §3). Kart ve depo künyeleri bakiye alanı
    TAŞIMAZ — taşısaydı iki kaynak olur ve biri diğerinden saparadı."""
    depo = await depo_fabrikasi("Merkez Depo (Sincan)")
    kart = await kart_fabrikasi("SNK-0421")
    await _hareket(client, admin_headers, "purchase", depo, kart, "10.000")

    kartlar = await client.get("/stock/items", headers=admin_headers)
    assert "balance" not in kartlar.json()["items"][0]
    depolar = await client.get("/warehouses", headers=admin_headers)
    assert "balance" not in depolar.json()["items"][0]
