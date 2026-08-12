"""ST T3 — `POST /stock/entries` + `GET /stock/entries`.

Spec: `docs/superpowers/specs/2026-08-11-st-stok-cekirdegi-design.md` §4, §7 S4.
Mockup: `Form - Stok Girisi.dc.html` (**SG**).

Bu dosyanın DONDURDUĞU kararlar:

1. **Gövde SG'nin birebiri — SİPARİŞ ALANLARI HARİÇ.** SG 85 "İlgili Sipariş"
   select'i, SG 95/113 "Sipariş" sütunu ve SG 176 "otomatik bildirim" onayı
   **SA dilimine** aittir; şemada YOKTUR ve bir bekçi testiyle kilitlidir.
2. **Tip kuralları gövde düzeyindedir (422).** `purchase`/`transfer` miktarı
   pozitif; `transfer` `source_warehouse_id` ZORUNLU, kendine transfer yasak;
   `adjustment` NEGATİF olabilir ama SIFIR olamaz ve kaynak depo TAŞIMAZ.
2b. **DURUM KODU KURALI (T4-artçı, 2026-08-11 kullanıcı kararı — spec'e EK):**
   **gövde içi VARLIK referansı = 404 · biçim/kural ihlali = 422.** Yani
   `warehouse_id`/`source_warehouse_id`/`item_id`/`received_by_user_id` (ve
   `POST /warehouses`ta `site_id`) görünmez ya da yoksa **404**; miktar/tip
   kuralları ihlal edilirse **422**. Kuralın kendisi
   `test_durum_kodu_kurali_govde_ici_varlik_referansi_404` ile kilitlidir.
3. **Eksi bakiye ENGELLENMEZ** (§7 S4): boş depodan çıkış 201 döner. Katı engel
   sayım düzeltmesini kilitlerdi; eksi bakiye yalnız RAPORLANIR.
4. **ATOMİKLİK:** satırlardan biri geçersizse başlık da satır da yazılmaz.
5. **Audit giriş başına TEK olay** — satır başına değil (spec §4).
"""

import uuid
from datetime import date

import pytest
from sqlalchemy import func, select

from app.modules.audit.models import AuditLog
from app.modules.inventory.models import StockEntry, StockEntryLine

_GUN = "2026-07-27"


def _govde(warehouse_id, item_id, **alanlar) -> dict:
    govde = {
        "entry_type": "purchase",
        "entry_date": _GUN,
        "warehouse_id": str(warehouse_id),
        "lines": [{"item_id": str(item_id), "quantity": "15.000", "unit_price": "21500.00"}],
    }
    govde.update(alanlar)
    return govde


async def _sayimlar(session) -> tuple[int, int]:
    baslik = (await session.execute(select(func.count()).select_from(StockEntry))).scalar_one()
    satir = (await session.execute(select(func.count()).select_from(StockEntryLine))).scalar_one()
    return baslik, satir


# --- Mutlu yol: SG'nin başlık alanları birebir ---


@pytest.mark.asyncio
async def test_satinalma_girisi_sg_alanlariyla_kaydedilir(
    client, satinalma_headers, gorunen_santiye, depo_fabrikasi, kart_fabrikasi, kullanici_kimligi
):
    """SG 84-88: tarih · depo · tedarikçi · irsaliye no · teslim alan · not."""
    depo = await depo_fabrikasi("D-1 Ambar", site=gorunen_santiye)
    kart = await kart_fabrikasi("SNK-0421")
    teslim_alan = await kullanici_kimligi("satinalma@stok.co")

    yanit = await client.post(
        "/stock/entries",
        json=_govde(
            depo.id,
            kart.id,
            supplier_name="Demirsan A.Ş.",
            delivery_note_no="IRS-2026-8842",
            received_by_user_id=str(teslim_alan),
            note="NYY kablo 50 m eksik geldi.",
        ),
        headers=satinalma_headers,
    )

    assert yanit.status_code == 201, yanit.text
    govde = yanit.json()
    assert govde["entry_type"] == "purchase"
    assert govde["entry_date"] == _GUN
    assert govde["warehouse_id"] == str(depo.id)
    assert govde["source_warehouse_id"] is None
    assert govde["supplier_name"] == "Demirsan A.Ş."
    assert govde["delivery_note_no"] == "IRS-2026-8842"
    assert govde["received_by_user_id"] == str(teslim_alan)
    assert govde["note"] == "NYY kablo 50 m eksik geldi."
    assert len(govde["lines"]) == 1
    satir = govde["lines"][0]
    assert satir["item_id"] == str(kart.id)
    assert satir["quantity"] == "15.000"
    assert satir["unit_price"] == "21500.00"
    # SG 117 ✓/⚠/✗ — gönderilmezse "uygun".
    assert satir["quality"] == "ok"


@pytest.mark.asyncio
async def test_yalnizca_BASLIK_siparis_bagi_vardir(
    client, satinalma_headers, depo_fabrikasi, kart_fabrikasi
):
    """SA BEKÇİSİ (T4'te güncellendi): SG 85 "İlgili Sipariş" AÇILDI, gerisi HAYIR.

    T3'te bu test "hiçbir sipariş alanı yok" diyordu; SA T4 başlıktaki
    `purchase_order_id`yi gerçeğe döndürdü (§7 S4). Bekçinin geri kalanı AYNEN
    durur ve hâlâ kalıcı kararları korur:

    * `notify_supplier` (SG 176 otomatik bildirim) → bildirim altyapısı yok;
    * SATIR düzeyi sipariş alanı (SG 95/113) → kısmi teslim ayrımı YOKTUR.

    Var olmayan bir sipariş kimliği artık sessizce yutulmaz, **404**tür — o
    kanonun testleri `tests/modules/procurement/test_stock_entry_delivery_chain`
    paketindedir.
    """
    depo = await depo_fabrikasi("Merkez Depo (Sincan)")
    kart = await kart_fabrikasi("SNK-0421")

    yanit = await client.post(
        "/stock/entries",
        json=_govde(depo.id, kart.id, notify_supplier=True),
        headers=satinalma_headers,
    )

    assert yanit.status_code == 201, yanit.text
    govde = yanit.json()
    assert govde["purchase_order_id"] is None
    assert "notify_supplier" not in govde
    assert [a for a in govde if "order" in a] == ["purchase_order_id"]
    assert not [a for a in govde["lines"][0] if "order" in a]


# --- Tip kuralları (422) ---


@pytest.mark.asyncio
async def test_satinalmada_negatif_miktar_422(
    client, satinalma_headers, depo_fabrikasi, kart_fabrikasi
):
    depo = await depo_fabrikasi("Merkez Depo (Sincan)")
    kart = await kart_fabrikasi("SNK-0421")
    yanit = await client.post(
        "/stock/entries",
        json=_govde(depo.id, kart.id, lines=[{"item_id": str(kart.id), "quantity": "-1.000"}]),
        headers=satinalma_headers,
    )
    assert yanit.status_code == 422, yanit.text


@pytest.mark.asyncio
async def test_satinalmada_kaynak_depo_verilirse_422(
    client, satinalma_headers, depo_fabrikasi, kart_fabrikasi
):
    """`source_warehouse_id` YALNIZ transferindir; satınalmada verilmesi
    "nereden geldi" sorusunu cevapsız bırakıp çift bacak yaratırdı."""
    hedef = await depo_fabrikasi("Merkez Depo (Sincan)")
    kaynak = await depo_fabrikasi("D-3 Kapalı")
    kart = await kart_fabrikasi("SNK-0421")
    yanit = await client.post(
        "/stock/entries",
        json=_govde(hedef.id, kart.id, source_warehouse_id=str(kaynak.id)),
        headers=satinalma_headers,
    )
    assert yanit.status_code == 422, yanit.text


@pytest.mark.asyncio
async def test_duzeltmede_kaynak_depo_verilirse_422(
    client, satinalma_headers, depo_fabrikasi, kart_fabrikasi
):
    hedef = await depo_fabrikasi("Merkez Depo (Sincan)")
    kaynak = await depo_fabrikasi("D-3 Kapalı")
    kart = await kart_fabrikasi("SNK-0421")
    yanit = await client.post(
        "/stock/entries",
        json=_govde(hedef.id, kart.id, entry_type="adjustment", source_warehouse_id=str(kaynak.id)),
        headers=satinalma_headers,
    )
    assert yanit.status_code == 422, yanit.text


@pytest.mark.asyncio
async def test_transferde_kaynak_depo_zorunlu_422(
    client, satinalma_headers, depo_fabrikasi, kart_fabrikasi
):
    """ÇİFT BACAĞIN ÖN KOŞULU: kaynağı olmayan transfer yoktan stok yaratırdı."""
    depo = await depo_fabrikasi("Merkez Depo (Sincan)")
    kart = await kart_fabrikasi("SNK-0421")
    yanit = await client.post(
        "/stock/entries",
        json=_govde(depo.id, kart.id, entry_type="transfer"),
        headers=satinalma_headers,
    )
    assert yanit.status_code == 422, yanit.text


@pytest.mark.asyncio
async def test_kendine_transfer_422(client, satinalma_headers, depo_fabrikasi, kart_fabrikasi):
    """Aynı depo hem kaynak hem hedefse iki bacak birbirini götürür: kayıt
    anlamsızdır ve hareket geçmişini gürültüye boğar."""
    depo = await depo_fabrikasi("Merkez Depo (Sincan)")
    kart = await kart_fabrikasi("SNK-0421")
    yanit = await client.post(
        "/stock/entries",
        json=_govde(depo.id, kart.id, entry_type="transfer", source_warehouse_id=str(depo.id)),
        headers=satinalma_headers,
    )
    assert yanit.status_code == 422, yanit.text


@pytest.mark.asyncio
async def test_duzeltmede_negatif_miktar_serbest(
    client, satinalma_headers, depo_fabrikasi, kart_fabrikasi
):
    """§7 S4: sayım farkı / iade / SARF tek kapısı budur. Ayrı bir çıkış ucu
    AÇILMAZ — bu test o kararın taşıyıcısıdır."""
    depo = await depo_fabrikasi("Merkez Depo (Sincan)")
    kart = await kart_fabrikasi("SNK-0421")
    yanit = await client.post(
        "/stock/entries",
        json=_govde(
            depo.id,
            kart.id,
            entry_type="adjustment",
            lines=[{"item_id": str(kart.id), "quantity": "-3.500"}],
        ),
        headers=satinalma_headers,
    )
    assert yanit.status_code == 201, yanit.text
    assert yanit.json()["lines"][0]["quantity"] == "-3.500"


@pytest.mark.asyncio
async def test_sifir_miktar_her_tipte_422(
    client, satinalma_headers, depo_fabrikasi, kart_fabrikasi
):
    depo = await depo_fabrikasi("Merkez Depo (Sincan)")
    kart = await kart_fabrikasi("SNK-0421")
    for tip in ("purchase", "adjustment"):
        yanit = await client.post(
            "/stock/entries",
            json=_govde(
                depo.id,
                kart.id,
                entry_type=tip,
                lines=[{"item_id": str(kart.id), "quantity": "0.000"}],
            ),
            headers=satinalma_headers,
        )
        assert yanit.status_code == 422, f"{tip}: {yanit.text}"


@pytest.mark.asyncio
async def test_satirsiz_giris_422(client, satinalma_headers, depo_fabrikasi):
    depo = await depo_fabrikasi("Merkez Depo (Sincan)")
    yanit = await client.post(
        "/stock/entries",
        json={
            "entry_type": "purchase",
            "entry_date": _GUN,
            "warehouse_id": str(depo.id),
            "lines": [],
        },
        headers=satinalma_headers,
    )
    assert yanit.status_code == 422, yanit.text


@pytest.mark.asyncio
async def test_not_serbest_metin_tavani_2000(
    client, satinalma_headers, depo_fabrikasi, kart_fabrikasi
):
    """`note` kolonu `Text`tir; tavan ŞEMADADIR
    (`app.core.text.FREE_TEXT_MAX_LENGTH`, TB4 standardı)."""
    depo = await depo_fabrikasi("Merkez Depo (Sincan)")
    kart = await kart_fabrikasi("SNK-0421")
    yanit = await client.post(
        "/stock/entries",
        json=_govde(depo.id, kart.id, note="x" * 2001),
        headers=satinalma_headers,
    )
    assert yanit.status_code == 422, yanit.text


# --- Eksi bakiye ENGELLENMEZ (§7 S4) ---


@pytest.mark.asyncio
async def test_bos_depodan_cikis_eksi_bakiyeye_izin_verir(
    client, satinalma_headers, depo_fabrikasi, kart_fabrikasi
):
    """Katı engel sayım düzeltmesini KİLİTLERDİ; eksi bakiye yalnız raporlanır."""
    depo = await depo_fabrikasi("Merkez Depo (Sincan)")
    kart = await kart_fabrikasi("SNK-0421", min_stock="10.000")
    yanit = await client.post(
        "/stock/entries",
        json=_govde(
            depo.id,
            kart.id,
            entry_type="adjustment",
            lines=[{"item_id": str(kart.id), "quantity": "-5.000"}],
        ),
        headers=satinalma_headers,
    )
    assert yanit.status_code == 201, yanit.text

    ozet = await client.get("/stock/summary", headers=satinalma_headers)
    satir = next(s for s in ozet.json()["items"] if s["code"] == "SNK-0421")
    assert satir["balance"] == "-5.000"
    assert satir["status"] == "critical"


@pytest.mark.asyncio
async def test_bos_depodan_transfer_eksi_bakiyeye_izin_verir(
    client, satinalma_headers, depo_fabrikasi, kart_fabrikasi
):
    kaynak = await depo_fabrikasi("Merkez Depo (Sincan)")
    hedef = await depo_fabrikasi("D-3 Kapalı")
    kart = await kart_fabrikasi("SNK-0421")
    yanit = await client.post(
        "/stock/entries",
        json=_govde(
            hedef.id,
            kart.id,
            entry_type="transfer",
            source_warehouse_id=str(kaynak.id),
            lines=[{"item_id": str(kart.id), "quantity": "4.000"}],
        ),
        headers=satinalma_headers,
    )
    assert yanit.status_code == 201, yanit.text


# --- DURUM KODU KURALI (T4-artçı) ---


@pytest.mark.asyncio
async def test_durum_kodu_kurali_govde_ici_varlik_referansi_404(
    client, satinalma_headers, gorunmeyen_santiye, depo_fabrikasi, kart_fabrikasi
):
    """Kuralın TEK bekçisi: **gövde içi VARLIK referansı = 404 · biçim/kural
    ihlali = 422** (2026-08-11 kullanıcı kararı, spec'e EK karar).

    Üç varlık referansı da AYNI kodu döndürür — biri 422'ye kayarsa bu test
    kırılır. Dördüncü referans (`site_id`) `test_warehouses_api.py`dedir; onun
    ucu farklı olduğu için oradan kilitlenir.

    Son iddia KARŞI ÖRNEKTİR: biçim ihlali 422 olarak KALIR, yoksa kural
    "her şey 404" diye yozlaşırdı.
    """
    depo = await depo_fabrikasi("Merkez Depo (Sincan)")
    kaynak_gorunmez = await depo_fabrikasi("D-9 Ambar", site=gorunmeyen_santiye)
    kart = await kart_fabrikasi("SNK-0421")

    async def _kod(govde: dict) -> int:
        return (
            await client.post("/stock/entries", json=govde, headers=satinalma_headers)
        ).status_code

    # 1) hedef depo yok · 2) kaynak depo GÖRÜNMÜYOR · 3) kart yok · 4) teslim alan yok
    assert await _kod(_govde(uuid.uuid4(), kart.id)) == 404
    assert (
        await _kod(
            _govde(
                depo.id,
                kart.id,
                entry_type="transfer",
                source_warehouse_id=str(kaynak_gorunmez.id),
            )
        )
        == 404
    )
    assert await _kod(_govde(depo.id, uuid.uuid4())) == 404
    assert await _kod(_govde(depo.id, kart.id, received_by_user_id=str(uuid.uuid4()))) == 404

    # KARŞI ÖRNEK: biçim/kural ihlali 422 KALIR (kendine transfer)
    assert (
        await _kod(
            _govde(depo.id, kart.id, entry_type="transfer", source_warehouse_id=str(depo.id))
        )
        == 422
    )


# --- ATOMİKLİK ---


@pytest.mark.asyncio
async def test_bozuk_satir_hicbir_sey_yazmaz(
    client, satinalma_headers, seeded_db, depo_fabrikasi, kart_fabrikasi
):
    """İkinci satırın kartı YOK: başlık da ilk satır da YAZILMAZ.

    Kod **404**'tür (T4-artçı kuralı, 2026-08-11: gövde içi VARLIK referansı =
    404; önce 422'ydi). Satır İÇİNDE durması bunu değiştirmez — referans yine
    bir varlığadır.
    """
    depo = await depo_fabrikasi("Merkez Depo (Sincan)")
    kart = await kart_fabrikasi("SNK-0421")
    once = await _sayimlar(seeded_db)

    yanit = await client.post(
        "/stock/entries",
        json=_govde(
            depo.id,
            kart.id,
            lines=[
                {"item_id": str(kart.id), "quantity": "15.000"},
                {"item_id": str(uuid.uuid4()), "quantity": "3.000"},
            ],
        ),
        headers=satinalma_headers,
    )

    assert yanit.status_code == 404, yanit.text
    assert await _sayimlar(seeded_db) == once == (0, 0)
    liste = await client.get("/stock/entries", headers=satinalma_headers)
    assert liste.json()["total"] == 0


@pytest.mark.asyncio
async def test_gorunmeyen_kaynak_depo_hicbir_sey_yazmaz(
    client, satinalma_headers, seeded_db, gorunmeyen_santiye, depo_fabrikasi, kart_fabrikasi
):
    """Kaynak bacağın IDOR'u da yazımdan ÖNCE denetlenir."""
    hedef = await depo_fabrikasi("Merkez Depo (Sincan)")
    kaynak = await depo_fabrikasi("D-9 Ambar", site=gorunmeyen_santiye)
    kart = await kart_fabrikasi("SNK-0421")

    yanit = await client.post(
        "/stock/entries",
        json=_govde(hedef.id, kart.id, entry_type="transfer", source_warehouse_id=str(kaynak.id)),
        headers=satinalma_headers,
    )

    assert yanit.status_code == 404, yanit.text
    assert await _sayimlar(seeded_db) == (0, 0)


@pytest.mark.asyncio
async def test_bilinmeyen_teslim_alan_hicbir_sey_yazmaz(
    client, satinalma_headers, seeded_db, depo_fabrikasi, kart_fabrikasi
):
    """SG 88 "Teslim Alan" kullanıcısı YOK → **404** (T4-artçı kuralı: gövde
    içi VARLIK referansı; önce 422'ydi)."""
    depo = await depo_fabrikasi("Merkez Depo (Sincan)")
    kart = await kart_fabrikasi("SNK-0421")
    yanit = await client.post(
        "/stock/entries",
        json=_govde(depo.id, kart.id, received_by_user_id=str(uuid.uuid4())),
        headers=satinalma_headers,
    )
    assert yanit.status_code == 404, yanit.text
    assert await _sayimlar(seeded_db) == (0, 0)


# --- IDOR ---


@pytest.mark.asyncio
async def test_gorunmeyen_hedef_depoya_giris_404(
    client, satinalma_headers, gorunmeyen_santiye, depo_fabrikasi, kart_fabrikasi
):
    """Görünmeyen depo ile VAR OLMAYAN depo AYNI gövdeyi alır."""
    depo = await depo_fabrikasi("D-9 Ambar", site=gorunmeyen_santiye)
    kart = await kart_fabrikasi("SNK-0421")

    gizli = await client.post(
        "/stock/entries", json=_govde(depo.id, kart.id), headers=satinalma_headers
    )
    olmayan = await client.post(
        "/stock/entries", json=_govde(uuid.uuid4(), kart.id), headers=satinalma_headers
    )
    assert gizli.status_code == olmayan.status_code == 404
    assert gizli.json()["detail"] == olmayan.json()["detail"]


@pytest.mark.asyncio
async def test_merkez_depoya_izinli_herkes_giris_yapar(
    client, satinalma_headers, depo_fabrikasi, kart_fabrikasi
):
    """§7 S2b: merkez depo proje kapsamına TABİ DEĞİLDİR."""
    depo = await depo_fabrikasi("Merkez Depo (Sincan)")
    kart = await kart_fabrikasi("SNK-0421")
    yanit = await client.post(
        "/stock/entries", json=_govde(depo.id, kart.id), headers=satinalma_headers
    )
    assert yanit.status_code == 201, yanit.text


# --- Yetki ---


@pytest.mark.asyncio
async def test_okuma_yetkisi_yazamaz_403(client, sef_headers, depo_fabrikasi, kart_fabrikasi):
    depo = await depo_fabrikasi("Merkez Depo (Sincan)")
    kart = await kart_fabrikasi("SNK-0421")
    yanit = await client.post("/stock/entries", json=_govde(depo.id, kart.id), headers=sef_headers)
    assert yanit.status_code == 403, yanit.text


@pytest.mark.asyncio
async def test_yetkisiz_okumada_bile_403(client, yetkisiz_headers):
    for yol in ("/stock/entries", "/stock/summary"):
        yanit = await client.get(yol, headers=yetkisiz_headers)
        assert yanit.status_code == 403, f"{yol}: {yanit.text}"


# --- Audit: giriş başına TEK olay ---


@pytest.mark.asyncio
async def test_audit_giris_basina_tek_olay(
    client, satinalma_headers, seeded_db, depo_fabrikasi, kart_fabrikasi
):
    """İKİ satırlı bir giriş TEK denetim satırı yazar (spec §4). Satır başına
    yazılsaydı 40 kalemlik bir irsaliye günlüğü boğardı."""
    depo = await depo_fabrikasi("Merkez Depo (Sincan)")
    a = await kart_fabrikasi("SNK-0421")
    b = await kart_fabrikasi("SNK-0108", name="CTP32,5 Çimento")
    once = (await seeded_db.execute(select(func.count()).select_from(AuditLog))).scalar_one()

    yanit = await client.post(
        "/stock/entries",
        json=_govde(
            depo.id,
            a.id,
            lines=[
                {"item_id": str(a.id), "quantity": "15.000"},
                {"item_id": str(b.id), "quantity": "840.000"},
            ],
        ),
        headers=satinalma_headers,
    )
    assert yanit.status_code == 201, yanit.text

    sonra = (await seeded_db.execute(select(func.count()).select_from(AuditLog))).scalar_one()
    assert sonra - once == 1


# --- GET /stock/entries ---


@pytest.mark.asyncio
async def test_hareket_listesi_suzgecleri(
    client, satinalma_headers, gorunen_santiye, depo_fabrikasi, kart_fabrikasi
):
    d1 = await depo_fabrikasi("D-1 Ambar", site=gorunen_santiye)
    d2 = await depo_fabrikasi("Merkez Depo (Sincan)")
    kart = await kart_fabrikasi("SNK-0421")

    async def _yaz(depo, tip, gun, **ek):
        yanit = await client.post(
            "/stock/entries",
            json=_govde(depo.id, kart.id, entry_type=tip, entry_date=gun, **ek),
            headers=satinalma_headers,
        )
        assert yanit.status_code == 201, yanit.text

    await _yaz(d1, "purchase", "2026-07-01")
    await _yaz(d2, "purchase", "2026-07-15")
    await _yaz(d1, "transfer", "2026-07-20", source_warehouse_id=str(d2.id))

    hepsi = await client.get("/stock/entries", headers=satinalma_headers)
    assert hepsi.json()["total"] == 3

    tip = await client.get("/stock/entries?entry_type=transfer", headers=satinalma_headers)
    assert tip.json()["total"] == 1

    # Depo süzgeci İKİ BACAĞI da kapsar: d2 bir kez hedef, bir kez KAYNAKTIR.
    depo = await client.get(f"/stock/entries?warehouse_id={d2.id}", headers=satinalma_headers)
    assert depo.json()["total"] == 2

    aralik = await client.get(
        "/stock/entries?date_from=2026-07-10&date_to=2026-07-16", headers=satinalma_headers
    )
    assert aralik.json()["total"] == 1
    assert aralik.json()["items"][0]["entry_date"] == "2026-07-15"


@pytest.mark.asyncio
async def test_hareket_listesi_sayfalama_tavani(client, satinalma_headers):
    """TB3 standardı: tavan aşımı sessizce kırpılmaz, 422 döner."""
    assert (
        await client.get("/stock/entries?limit=201", headers=satinalma_headers)
    ).status_code == 422
    yanit = await client.get("/stock/entries", headers=satinalma_headers)
    assert yanit.json()["limit"] == 50
    assert yanit.json()["offset"] == 0


@pytest.mark.asyncio
async def test_hareket_listesi_gorunmeyen_depoyu_gizler(
    client, satinalma_headers, admin_headers, gorunmeyen_santiye, depo_fabrikasi, kart_fabrikasi
):
    gizli = await depo_fabrikasi("D-9 Ambar", site=gorunmeyen_santiye)
    kart = await kart_fabrikasi("SNK-0421")
    yazildi = await client.post(
        "/stock/entries", json=_govde(gizli.id, kart.id), headers=admin_headers
    )
    assert yazildi.status_code == 201, yazildi.text

    assert (await client.get("/stock/entries", headers=satinalma_headers)).json()["total"] == 0
    assert (await client.get("/stock/entries", headers=admin_headers)).json()["total"] == 1


@pytest.mark.asyncio
async def test_hareket_duzeltme_ve_silme_uclari_yoktur(
    client, satinalma_headers, depo_fabrikasi, kart_fabrikasi
):
    """Hareket DÜZELTİLMEZ, ters işaretli bir `adjustment` ile düzeltilir:
    geçmişi yeniden yazmak bakiye tarihini de yeniden yazardı.

    `/stock/entries/{id}` altında HİÇBİR yöntem tanımlı olmadığı için FastAPI
    yolu hiç eşleştiremez ve 404 döner (kart ucundaki 405'ten farkı budur:
    orada `PATCH` VARDIR, yalnız `DELETE` yoktur). İleride biri tekil bir yol
    açarsa bu bekçi kırılır.
    """
    depo = await depo_fabrikasi("Merkez Depo (Sincan)")
    kart = await kart_fabrikasi("SNK-0421")
    yanit = await client.post(
        "/stock/entries", json=_govde(depo.id, kart.id), headers=satinalma_headers
    )
    kimlik = yanit.json()["id"]
    silme = await client.delete(f"/stock/entries/{kimlik}", headers=satinalma_headers)
    guncelleme = await client.patch(f"/stock/entries/{kimlik}", json={}, headers=satinalma_headers)
    assert silme.status_code == 404
    assert guncelleme.status_code == 404


@pytest.mark.asyncio
async def test_hareketi_olan_depo_silinemez_409(
    client, admin_headers, depo_fabrikasi, kart_fabrikasi
):
    """T2'nin korkuluğu T3'ün yazdığı gerçek hareketle DE doğrulanır."""
    kaynak = await depo_fabrikasi("Merkez Depo (Sincan)")
    hedef = await depo_fabrikasi("D-3 Kapalı")
    kart = await kart_fabrikasi("SNK-0421")
    yazildi = await client.post(
        "/stock/entries",
        json=_govde(hedef.id, kart.id, entry_type="transfer", source_warehouse_id=str(kaynak.id)),
        headers=admin_headers,
    )
    assert yazildi.status_code == 201, yazildi.text

    # HEDEF bacak da KAYNAK bacak da aynı korumadadır.
    assert (
        await client.delete(f"/warehouses/{hedef.id}", headers=admin_headers)
    ).status_code == 409
    assert (
        await client.delete(f"/warehouses/{kaynak.id}", headers=admin_headers)
    ).status_code == 409


@pytest.mark.asyncio
async def test_gecmis_tarihli_giris_kabul_edilir(
    client, satinalma_headers, depo_fabrikasi, kart_fabrikasi
):
    """İrsaliye günler sonra girilebilir; tarih kısıtı UYDURULMAZ."""
    depo = await depo_fabrikasi("Merkez Depo (Sincan)")
    kart = await kart_fabrikasi("SNK-0421")
    yanit = await client.post(
        "/stock/entries",
        json=_govde(depo.id, kart.id, entry_date=str(date(2020, 1, 1))),
        headers=satinalma_headers,
    )
    assert yanit.status_code == 201, yanit.text
