"""STOK-BOLUM — satir bazinda bolum/poz atfi ve bolum malzeme kirilimi.

Bu dosyanin bekcileri UC AYRI iddiayi tasir ve karistirilmamalidir:

1. **ATIF YAZILIYOR VE GERI OKUNUYOR** (pozitif kontrol) — kapi her govdeye
   422 vermiyor. Bu olmadan asagidaki reddetme testleri BOSA koser (K-IKIZ1).
2. **TUTARLILIK KAPISI** — baska santiyenin bolumune/pozuna sarf YAZILAMAZ.
3. **KIRILIM UCU** — sarf toplami dogru turetiliyor ve BAKIYE DONMUYOR.
"""

import uuid
from decimal import Decimal

# --------------------------------------------------------------------------- #
# 1. POZITIF KONTROL — gecerli atif GECER ve GERI OKUNUR
# --------------------------------------------------------------------------- #


async def test_gecerli_atif_yazilir_ve_kunyede_geri_okunur(
    client,
    admin_headers,
    gorunen_santiye,
    depo_fabrikasi,
    kart_fabrikasi,
    bolum_fabrikasi,
    poz_fabrikasi,
):
    """🔴 POZITIF KONTROL. Bu gecmezse asagidaki 422 bekcilerinin HICBIRI
    bir sey kanitlamaz: her govdeye 422 veren bozuk bir uc de onlari yesil
    gecerdi (K-IKIZ1)."""
    depo = await depo_fabrikasi("D-1 Ambar", site=gorunen_santiye)
    kart = await kart_fabrikasi("SNK-0421")
    bolum = await bolum_fabrikasi(gorunen_santiye, "A1", "A1 Kenar Ayak")
    poz = await poz_fabrikasi(gorunen_santiye, "C-01")

    resp = await client.post(
        "/stock/entries",
        json={
            "entry_type": "adjustment",
            "entry_date": "2026-08-29",
            "warehouse_id": str(depo.id),
            "lines": [
                {
                    "item_id": str(kart.id),
                    "quantity": "-4.900",
                    "unit_price": "100.00",
                    "section_id": str(bolum.id),
                    "boq_item_id": str(poz.id),
                }
            ],
        },
        headers=admin_headers,
    )

    assert resp.status_code == 201, resp.text
    satir = resp.json()["lines"][0]
    assert (satir["section_id"], satir["boq_item_id"]) == (str(bolum.id), str(poz.id))


async def test_atif_OPSIYONELDIR_mevcut_akislar_422ye_DUSMEZ(
    client, admin_headers, gorunen_santiye, depo_fabrikasi, kart_fabrikasi
):
    """Regresyon: iki kolon nullable acildi — atifsiz hareket AYNEN calisir."""
    depo = await depo_fabrikasi("D-1 Ambar", site=gorunen_santiye)
    kart = await kart_fabrikasi("SNK-0421")

    resp = await client.post(
        "/stock/entries",
        json={
            "entry_type": "purchase",
            "entry_date": "2026-08-29",
            "warehouse_id": str(depo.id),
            "lines": [{"item_id": str(kart.id), "quantity": "10.000"}],
        },
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["lines"][0] == {
        **resp.json()["lines"][0],
        "section_id": None,
        "boq_item_id": None,
    }


async def test_ETIKET_SATIR_BAZINDADIR_ayni_fis_iki_farkli_poza_cikar(
    client,
    admin_headers,
    gorunen_santiye,
    depo_fabrikasi,
    kart_fabrikasi,
    bolum_fabrikasi,
    poz_fabrikasi,
):
    """🔑 Kullanici kararinin (2026-08-29) TASIYICI bekcisi.

    Etiket BASLIKTA olsaydi bu govde yazilamazdi ve kullanici fisi BOLMEK
    zorunda kalirdi. Iki satir, iki AYRI poz, TEK fis.
    """
    depo = await depo_fabrikasi("D-1 Ambar", site=gorunen_santiye)
    demir = await kart_fabrikasi("SNK-0421", "Nervürlü Demir")
    kalip = await kart_fabrikasi("SNK-0999", "Kalıp Kontrplak")
    bolum = await bolum_fabrikasi(gorunen_santiye, "A1", "A1 Kenar Ayak")
    poz_demir = await poz_fabrikasi(gorunen_santiye, "C-01")
    poz_kalip = await poz_fabrikasi(gorunen_santiye, "B-01", "Kalıp işleri")

    resp = await client.post(
        "/stock/entries",
        json={
            "entry_type": "adjustment",
            "entry_date": "2026-08-29",
            "warehouse_id": str(depo.id),
            "lines": [
                {
                    "item_id": str(demir.id),
                    "quantity": "-4.900",
                    "section_id": str(bolum.id),
                    "boq_item_id": str(poz_demir.id),
                },
                {
                    "item_id": str(kalip.id),
                    "quantity": "-2.000",
                    "section_id": str(bolum.id),
                    "boq_item_id": str(poz_kalip.id),
                },
            ],
        },
        headers=admin_headers,
    )

    assert resp.status_code == 201, resp.text
    assert {s["boq_item_id"] for s in resp.json()["lines"]} == {
        str(poz_demir.id),
        str(poz_kalip.id),
    }


# --------------------------------------------------------------------------- #
# 2. TUTARLILIK KAPISI — fail-closed
# --------------------------------------------------------------------------- #


async def test_BASKA_SANTIYENIN_bolumune_sarf_YAZILAMAZ(
    client,
    admin_headers,
    gorunen_santiye,
    gorunmeyen_santiye,
    depo_fabrikasi,
    kart_fabrikasi,
    bolum_fabrikasi,
):
    """🔴 Dilimin bir numarali veri bozuklugu kapisi (5. tuzak).

    `admin_headers` KASITLIDIR: `projects=_A` oldugu icin ikinci santiye ona
    GORUNUR. Yani 404'e dusmez — kapinin gercekten SANTIYE ESLESMESINI
    olctugu, gorunurlugu degil, boylece kanitlanir.
    """
    depo = await depo_fabrikasi("D-1 Ambar", site=gorunen_santiye)
    kart = await kart_fabrikasi("SNK-0421")
    yabanci = await bolum_fabrikasi(gorunmeyen_santiye, "X1", "Marina Bodrum")

    resp = await client.post(
        "/stock/entries",
        json={
            "entry_type": "adjustment",
            "entry_date": "2026-08-29",
            "warehouse_id": str(depo.id),
            "lines": [
                {"item_id": str(kart.id), "quantity": "-1.000", "section_id": str(yabanci.id)}
            ],
        },
        headers=admin_headers,
    )

    assert resp.status_code == 422, resp.text
    assert "şantiyesine ait değil" in resp.json()["detail"]


async def test_BASKA_SANTIYENIN_pozuna_sarf_YAZILAMAZ(
    client,
    admin_headers,
    gorunen_santiye,
    gorunmeyen_santiye,
    depo_fabrikasi,
    kart_fabrikasi,
    poz_fabrikasi,
):
    depo = await depo_fabrikasi("D-1 Ambar", site=gorunen_santiye)
    kart = await kart_fabrikasi("SNK-0421")
    yabanci = await poz_fabrikasi(gorunmeyen_santiye, "Z-99")

    resp = await client.post(
        "/stock/entries",
        json={
            "entry_type": "adjustment",
            "entry_date": "2026-08-29",
            "warehouse_id": str(depo.id),
            "lines": [
                {"item_id": str(kart.id), "quantity": "-1.000", "boq_item_id": str(yabanci.id)}
            ],
        },
        headers=admin_headers,
    )

    assert resp.status_code == 422, resp.text
    assert "iş kalemi" in resp.json()["detail"]


async def test_MERKEZ_DEPODA_santiye_kapisi_UYGULANMAZ_ama_BOLUM_POZ_capasi_TUTAR(
    client,
    admin_headers,
    gorunen_santiye,
    gorunmeyen_santiye,
    depo_fabrikasi,
    kart_fabrikasi,
    bolum_fabrikasi,
    poz_fabrikasi,
):
    """🔴 Merkez depo karari — FAIL-OPEN (santiye capasi) + FAIL-CLOSED (bolum↔poz).

    TEK testte IKI iddia var ve bilincli: ayri testler olsaydi biri "merkez
    depodan hicbir sey yazilamiyor" hâline gerileyip digerini yesil birakabilirdi.
    """
    merkez = await depo_fabrikasi("Merkez Depo (Sincan)")
    kart = await kart_fabrikasi("SNK-0421")
    bolum = await bolum_fabrikasi(gorunen_santiye, "A1", "A1 Kenar Ayak")
    kendi_pozu = await poz_fabrikasi(gorunen_santiye, "C-01")
    yabanci_poz = await poz_fabrikasi(gorunmeyen_santiye, "Z-99")

    def govde(poz):
        return {
            "entry_type": "adjustment",
            "entry_date": "2026-08-29",
            "warehouse_id": str(merkez.id),
            "lines": [
                {
                    "item_id": str(kart.id),
                    "quantity": "-1.000",
                    "section_id": str(bolum.id),
                    "boq_item_id": str(poz.id),
                }
            ],
        }

    # FAIL-OPEN: merkez deponun santiyesi YOKTUR, capa yoktur → gecer.
    gecerli = await client.post("/stock/entries", json=govde(kendi_pozu), headers=admin_headers)
    assert gecerli.status_code == 201, gecerli.text

    # FAIL-CLOSED: merkez depoda TEK capa bolum↔poz iliskisidir → tutar.
    bozuk = await client.post("/stock/entries", json=govde(yabanci_poz), headers=admin_headers)
    assert bozuk.status_code == 422, bozuk.text
    assert "aynı şantiyeye ait değil" in bozuk.json()["detail"]


async def test_GORUNMEYEN_bolum_404_ve_kimlik_SIZMAZ(
    client,
    satinalma_headers,
    gorunen_santiye,
    gorunmeyen_santiye,
    depo_fabrikasi,
    kart_fabrikasi,
    bolum_fabrikasi,
):
    """IDOR: `satinalma_headers` yalniz `gorunen_proje`yi gorur.

    Var OLMAYAN kimlik ile GORUNMEYEN kimlik AYNI govdeyi alir — kimlik
    varligi sizdirilmaz. Iki cagri TEK `assert`te karsilastirilir.
    """
    depo = await depo_fabrikasi("D-1 Ambar", site=gorunen_santiye)
    kart = await kart_fabrikasi("SNK-0421")
    gizli = await bolum_fabrikasi(gorunmeyen_santiye, "X1", "Marina Bodrum")

    async def dene(bolum_id):
        return await client.post(
            "/stock/entries",
            json={
                "entry_type": "adjustment",
                "entry_date": "2026-08-29",
                "warehouse_id": str(depo.id),
                "lines": [
                    {"item_id": str(kart.id), "quantity": "-1.000", "section_id": str(bolum_id)}
                ],
            },
            headers=satinalma_headers,
        )

    gorunmeyen = await dene(gizli.id)
    yok = await dene(uuid.uuid4())

    assert (gorunmeyen.status_code, gorunmeyen.json()) == (404, yok.json()), (
        "gorunmeyen bolum ile var olmayan bolum AYRISTI — kimlik sizdiriliyor"
    )
    assert yok.status_code == 404


async def test_BOZUK_ATIFTA_HICBIR_SEY_YAZILMAZ(
    client,
    admin_headers,
    seeded_db,
    gorunen_santiye,
    gorunmeyen_santiye,
    depo_fabrikasi,
    kart_fabrikasi,
    bolum_fabrikasi,
):
    """Atomiklik: kapi YAZIMDAN ONCE kosar — ne baslik ne satir kalir."""
    from sqlalchemy import func, select

    from app.modules.inventory.models import StockEntry

    depo = await depo_fabrikasi("D-1 Ambar", site=gorunen_santiye)
    kart = await kart_fabrikasi("SNK-0421")
    yabanci = await bolum_fabrikasi(gorunmeyen_santiye, "X1", "Marina Bodrum")

    resp = await client.post(
        "/stock/entries",
        json={
            "entry_type": "adjustment",
            "entry_date": "2026-08-29",
            "warehouse_id": str(depo.id),
            "lines": [
                {"item_id": str(kart.id), "quantity": "-1.000"},
                {"item_id": str(kart.id), "quantity": "-2.000", "section_id": str(yabanci.id)},
            ],
        },
        headers=admin_headers,
    )

    assert resp.status_code == 422, resp.text
    assert await seeded_db.scalar(select(func.count()).select_from(StockEntry)) == 0


async def test_TRANSFERDE_atif_YASAKTIR(
    client, admin_headers, gorunen_santiye, depo_fabrikasi, kart_fabrikasi, bolum_fabrikasi
):
    """🔴 CIFT BACAK karari.

    `transfer` tek satir yazar ama bakiyeye IKI bacak olarak yansir
    (`balance.legs()`); satirin TEK `section_id`si iki bacaga birden ait
    olamaz. Ustelik transfer TUKETIM DEGILDIR — malzeme hâlâ bir depodadir.
    Bu yuzden atif transferde REDDEDILIR ve belirsizlik CEVAPLANMAZ, ORTADAN
    KALDIRILIR. Kural govdenin kendi icinde cozulur → SEMA katmani, 422.
    """
    kaynak = await depo_fabrikasi("D-1 Ambar", site=gorunen_santiye)
    hedef = await depo_fabrikasi("D-2 Saha", site=gorunen_santiye)
    kart = await kart_fabrikasi("SNK-0421")
    bolum = await bolum_fabrikasi(gorunen_santiye, "A1", "A1 Kenar Ayak")

    resp = await client.post(
        "/stock/entries",
        json={
            "entry_type": "transfer",
            "entry_date": "2026-08-29",
            "warehouse_id": str(hedef.id),
            "source_warehouse_id": str(kaynak.id),
            "lines": [{"item_id": str(kart.id), "quantity": "5.000", "section_id": str(bolum.id)}],
        },
        headers=admin_headers,
    )

    assert resp.status_code == 422, resp.text


async def test_TAHSIS_ARANMAZ_fail_open(
    client,
    admin_headers,
    seeded_db,
    gorunen_santiye,
    depo_fabrikasi,
    kart_fabrikasi,
    bolum_fabrikasi,
    poz_fabrikasi,
):
    """🔴 6. tuzagin karari: poz bolume TAHSIS EDILMEMIS olsa da sarf yazilir.

    Tahsis PLANLAMA bilgisidir; bu uc GERCEKLESENI kaydeder. Sart konsaydi
    planlama yapilmamis santiye hic malzeme cikisi yazamazdi. Bekci once
    tahsisin GERCEKTEN YOK oldugunu olcer (pozitif kontrolun aynasi).
    """
    from sqlalchemy import func, select

    from app.modules.boq.models import BoqItemSectionAllocation

    depo = await depo_fabrikasi("D-1 Ambar", site=gorunen_santiye)
    kart = await kart_fabrikasi("SNK-0421")
    bolum = await bolum_fabrikasi(gorunen_santiye, "A1", "A1 Kenar Ayak")
    poz = await poz_fabrikasi(gorunen_santiye, "C-01")

    assert (
        await seeded_db.scalar(
            select(func.count())
            .select_from(BoqItemSectionAllocation)
            .where(BoqItemSectionAllocation.section_id == bolum.id)
        )
        == 0
    ), "tahsis VAR — bu bekcinin iddiasi bosa koser"

    resp = await client.post(
        "/stock/entries",
        json={
            "entry_type": "adjustment",
            "entry_date": "2026-08-29",
            "warehouse_id": str(depo.id),
            "lines": [
                {
                    "item_id": str(kart.id),
                    "quantity": "-1.000",
                    "section_id": str(bolum.id),
                    "boq_item_id": str(poz.id),
                }
            ],
        },
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text


# --------------------------------------------------------------------------- #
# 3. KIRILIM UCU — GET /sections/{id}/stock
# --------------------------------------------------------------------------- #


async def test_bolum_kirilimi_SARFI_ve_ATFI_AYIRIR(
    client,
    admin_headers,
    gorunen_santiye,
    depo_fabrikasi,
    kart_fabrikasi,
    bolum_fabrikasi,
    poz_fabrikasi,
):
    """🔑 Ucun tasiyici iddiasi: `+10 alim` ile `-4 sarf` BIRBIRINI GOTURMEZ.

    Tek bir "toplam" basilsaydi net 6 gorunur ve ekran 4 birimin harcandigini
    HIC soyleyemezdi.
    """
    depo = await depo_fabrikasi("D-1 Ambar", site=gorunen_santiye)
    kart = await kart_fabrikasi("SNK-0421")
    bolum = await bolum_fabrikasi(gorunen_santiye, "A1", "A1 Kenar Ayak")
    poz = await poz_fabrikasi(gorunen_santiye, "C-01")
    atif = {"section_id": str(bolum.id), "boq_item_id": str(poz.id)}

    for tip, miktar in (("purchase", "10.000"), ("adjustment", "-4.000")):
        resp = await client.post(
            "/stock/entries",
            json={
                "entry_type": tip,
                "entry_date": "2026-08-29",
                "warehouse_id": str(depo.id),
                "lines": [
                    {"item_id": str(kart.id), "quantity": miktar, "unit_price": "100.00"} | atif
                ],
            },
            headers=admin_headers,
        )
        assert resp.status_code == 201, resp.text

    govde = (await client.get(f"/sections/{bolum.id}/stock", headers=admin_headers)).json()

    assert govde["total"] == 1
    satir = govde["items"][0]
    assert {
        "assigned": satir["assigned_quantity"],
        "issued": satir["issued_quantity"],
        "net": satir["net_quantity"],
        "boq_code": satir["boq_code"],
    } == {"assigned": "10.000", "issued": "4.000", "net": "6.000", "boq_code": "C-01"}
    assert govde["kpis"]["issued_value"] == "400.00"
    # 🔴 BAKIYE DONMEZ — urun karari ("STOK DEPODA DURUR, BOLUM TUKETIR").
    assert "balance" not in satir


async def test_bolum_kirilimi_POZ_BAZINDA_ayrisir_ve_pozsuz_satir_KALIR(
    client,
    admin_headers,
    gorunen_santiye,
    depo_fabrikasi,
    kart_fabrikasi,
    bolum_fabrikasi,
    poz_fabrikasi,
):
    """Satirlar (malzeme, poz) cifti basinadir; poz NULL olan satir SILINMEZ."""
    depo = await depo_fabrikasi("D-1 Ambar", site=gorunen_santiye)
    kart = await kart_fabrikasi("SNK-0421")
    bolum = await bolum_fabrikasi(gorunen_santiye, "A1", "A1 Kenar Ayak")
    poz = await poz_fabrikasi(gorunen_santiye, "C-01")

    resp = await client.post(
        "/stock/entries",
        json={
            "entry_type": "adjustment",
            "entry_date": "2026-08-29",
            "warehouse_id": str(depo.id),
            "lines": [
                {
                    "item_id": str(kart.id),
                    "quantity": "-3.000",
                    "section_id": str(bolum.id),
                    "boq_item_id": str(poz.id),
                },
                {"item_id": str(kart.id), "quantity": "-2.000", "section_id": str(bolum.id)},
            ],
        },
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text

    govde = (await client.get(f"/sections/{bolum.id}/stock", headers=admin_headers)).json()

    assert [(s["boq_code"], s["issued_quantity"]) for s in govde["items"]] == [
        ("C-01", "3.000"),
        (None, "2.000"),
    ], "poz kirilimi ya da NULLS LAST siralamasi bozuldu"
    # `item_count` DISTINCT KART sayisidir, satir sayisi DEGIL.
    assert govde["kpis"]["item_count"] == 1


async def test_bolum_kirilimi_BASKA_bolumun_hareketini_SAYMAZ(
    client, admin_headers, gorunen_santiye, depo_fabrikasi, kart_fabrikasi, bolum_fabrikasi
):
    """Kirilimin izolasyonu — atifsiz ve baska-bolumlu satirlar sizmaz."""
    depo = await depo_fabrikasi("D-1 Ambar", site=gorunen_santiye)
    kart = await kart_fabrikasi("SNK-0421")
    a1 = await bolum_fabrikasi(gorunen_santiye, "A1", "A1 Kenar Ayak")
    a2 = await bolum_fabrikasi(gorunen_santiye, "A2", "A2 Orta Ayak")

    resp = await client.post(
        "/stock/entries",
        json={
            "entry_type": "adjustment",
            "entry_date": "2026-08-29",
            "warehouse_id": str(depo.id),
            "lines": [
                {"item_id": str(kart.id), "quantity": "-1.000", "section_id": str(a1.id)},
                {"item_id": str(kart.id), "quantity": "-7.000", "section_id": str(a2.id)},
                {"item_id": str(kart.id), "quantity": "-9.000"},
            ],
        },
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text

    govde = (await client.get(f"/sections/{a1.id}/stock", headers=admin_headers)).json()
    assert [s["issued_quantity"] for s in govde["items"]] == ["1.000"]


async def test_kirilim_ucu_GORUNMEYEN_bolumde_404(
    client, satinalma_headers, gorunmeyen_santiye, bolum_fabrikasi
):
    gizli = await bolum_fabrikasi(gorunmeyen_santiye, "X1", "Marina Bodrum")
    gorunmeyen = await client.get(f"/sections/{gizli.id}/stock", headers=satinalma_headers)
    yok = await client.get(f"/sections/{uuid.uuid4()}/stock", headers=satinalma_headers)
    assert (gorunmeyen.status_code, gorunmeyen.json()) == (404, yok.json())


async def test_kirilim_ucu_YETKISIZ_role_KAPALI(
    client, yetkisiz_headers, gorunen_santiye, bolum_fabrikasi
):
    """Kapi `inventory:view` — `accounting` (`_N`) okumada bile 403."""
    bolum = await bolum_fabrikasi(gorunen_santiye, "A1", "A1 Kenar Ayak")
    resp = await client.get(f"/sections/{bolum.id}/stock", headers=yetkisiz_headers)
    assert resp.status_code == 403, resp.text


async def test_fiyatsiz_satir_DEGERE_GIRMEZ_ama_RAPORLANIR(
    client, admin_headers, gorunen_santiye, depo_fabrikasi, kart_fabrikasi, bolum_fabrikasi
):
    """§7 S6 kuralinin bolum seridindeki karsiligi: sessiz 0 YOK."""
    depo = await depo_fabrikasi("D-1 Ambar", site=gorunen_santiye)
    kart = await kart_fabrikasi("SNK-0421")
    bolum = await bolum_fabrikasi(gorunen_santiye, "A1", "A1 Kenar Ayak")

    resp = await client.post(
        "/stock/entries",
        json={
            "entry_type": "adjustment",
            "entry_date": "2026-08-29",
            "warehouse_id": str(depo.id),
            "lines": [
                {"item_id": str(kart.id), "quantity": "-5.000"} | {"section_id": str(bolum.id)}
            ],
        },
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text

    kpi = (await client.get(f"/sections/{bolum.id}/stock", headers=admin_headers)).json()["kpis"]
    assert (kpi["total_value"], kpi["lines_without_price"]) == ("0.00", 1)


# --------------------------------------------------------------------------- #
# 4. ŞS "Bolum" sutunu + section_id suzgeci
# --------------------------------------------------------------------------- #


async def test_SS_bolum_sutunu_GERCEGE_dondu(
    client, admin_headers, gorunen_santiye, depo_fabrikasi, kart_fabrikasi, bolum_fabrikasi
):
    """`SiteStockRow.section` artik DOLU zarf doner (STOK-BOLUM)."""
    depo = await depo_fabrikasi("D-1 Ambar", site=gorunen_santiye)
    kart = await kart_fabrikasi("SNK-0421")
    bolum = await bolum_fabrikasi(gorunen_santiye, "A1", "A1 Kenar Ayak")

    resp = await client.post(
        "/stock/entries",
        json={
            "entry_type": "purchase",
            "entry_date": "2026-08-29",
            "warehouse_id": str(depo.id),
            "lines": [{"item_id": str(kart.id), "quantity": "5.000", "section_id": str(bolum.id)}],
        },
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text

    satir = (await client.get(f"/sites/{gorunen_santiye.id}/stock", headers=admin_headers)).json()[
        "items"
    ][0]
    assert satir["section"] == {
        "available": True,
        "items": ["A1 Kenar Ayak"],
        "pending_module": "site_planning",
    }
    # "Aylik Ihtiyac" YER TUTUCU KALIR — plan izgarasi malzeme satiri tasimaz.
    assert satir["monthly_need"]["available"] is False


async def test_SS_section_id_suzgeci_BAKIYEYI_DEGISTIRMEZ_satir_kumesini_daraltir(
    client, admin_headers, gorunen_santiye, depo_fabrikasi, kart_fabrikasi, bolum_fabrikasi
):
    """🔴 Suzgecin ANLAMI: bakiye DEPO duzeyinde kalir.

    Iki kart girer, biri bolume atfedilir. Suzgec ACIKKEN yalniz o kart
    listelenir ama BAKIYESI TAM (10) doner — bolume atfedilen 4 degil. Bakiye
    suzulseydi ekran "depoda 4 var" derdi ve bu YALAN olurdu.
    """
    depo = await depo_fabrikasi("D-1 Ambar", site=gorunen_santiye)
    demir = await kart_fabrikasi("SNK-0421", "Nervürlü Demir")
    civi = await kart_fabrikasi("SNK-0777", "Çivi")
    bolum = await bolum_fabrikasi(gorunen_santiye, "A1", "A1 Kenar Ayak")

    resp = await client.post(
        "/stock/entries",
        json={
            "entry_type": "purchase",
            "entry_date": "2026-08-29",
            "warehouse_id": str(depo.id),
            "lines": [
                {"item_id": str(demir.id), "quantity": "4.000", "section_id": str(bolum.id)},
                {"item_id": str(demir.id), "quantity": "6.000"},
                {"item_id": str(civi.id), "quantity": "3.000"},
            ],
        },
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text

    suzgecsiz = (
        await client.get(f"/sites/{gorunen_santiye.id}/stock", headers=admin_headers)
    ).json()
    suzgecli = (
        await client.get(
            f"/sites/{gorunen_santiye.id}/stock?section_id={bolum.id}", headers=admin_headers
        )
    ).json()

    assert suzgecsiz["total"] == 2, "POZITIF KONTROL: suzgecsiz iki kart gorunmeliydi"
    assert suzgecli["total"] == 1
    assert suzgecli["items"][0]["code"] == "SNK-0421"
    assert Decimal(suzgecli["items"][0]["balance"]) == Decimal("10.000"), (
        "BAKIYE SUZULMUS — bakiye depo duzeyinde kalmali (STOK DEPODA DURUR)"
    )
    # Serit de ayni kumeyi ozetler: liste/total/KPI ayrissaydi ekran celiskili olurdu.
    assert suzgecli["kpis"]["total_items"] == 1


async def test_SS_suzgecinde_BASKA_SANTIYENIN_bolumu_404(
    client, admin_headers, gorunen_santiye, gorunmeyen_santiye, bolum_fabrikasi
):
    """Aksi hâlde `?section_id=` baska santiyenin kirilimini sizdirirdi."""
    yabanci = await bolum_fabrikasi(gorunmeyen_santiye, "X1", "Marina Bodrum")
    resp = await client.get(
        f"/sites/{gorunen_santiye.id}/stock?section_id={yabanci.id}", headers=admin_headers
    )
    assert resp.status_code == 404, resp.text


# --------------------------------------------------------------------------- #
# 5. ON DELETE semantigi — `SET NULL` karari
# --------------------------------------------------------------------------- #


async def test_BOLUM_SILININCE_stok_satiri_KALIR_bag_kopar(
    client,
    admin_headers,
    seeded_db,
    gorunen_santiye,
    depo_fabrikasi,
    kart_fabrikasi,
    bolum_fabrikasi,
):
    """🔴 `SET NULL` kararının bekçisi (desen `site_diary_lines.boq_item_id`).

    CASCADE seçilseydi bir bölümün silinmesi stok hareketi SATIRINI silerdi —
    yani BAKİYEYİ değiştirirdi. Bakiye, bir bölüm kaydına bağlı olarak yok
    olamaz. Bekçi önce satırın gerçekten yazıldığını ölçer (pozitif kontrol).
    """
    from sqlalchemy import select

    from app.modules.inventory.models import StockEntryLine

    depo = await depo_fabrikasi("D-1 Ambar", site=gorunen_santiye)
    kart = await kart_fabrikasi("SNK-0421")
    bolum = await bolum_fabrikasi(gorunen_santiye, "A1", "A1 Kenar Ayak")

    resp = await client.post(
        "/stock/entries",
        json={
            "entry_type": "adjustment",
            "entry_date": "2026-08-29",
            "warehouse_id": str(depo.id),
            "lines": [{"item_id": str(kart.id), "quantity": "-5.000", "section_id": str(bolum.id)}],
        },
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text

    satir = (await seeded_db.execute(select(StockEntryLine))).scalars().one()
    assert satir.section_id == bolum.id, "POZITIF KONTROL: atif yazilmamis"

    await seeded_db.delete(bolum)
    await seeded_db.flush()
    await seeded_db.refresh(satir)

    assert satir.section_id is None, "bag kopmadi"
    assert satir.quantity == Decimal("-5.000"), "🔴 SATIR SILINMIS — bakiye degisti (CASCADE?)"
