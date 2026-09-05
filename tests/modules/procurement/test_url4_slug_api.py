"""URL-4 — `GET /purchase-requests/{request_id}` talep numarasıyla açılır.

## Anahtar `request_no`dur — MIGRATION YOK

Ölçüldü (`procurement/models.py:201`): `request_no` `String(20)`, **`unique=True`
ve NOT NULL**. Yani tablo ZATEN şirket geneli tekil, boş olamayan bir anahtar
taşıyor; ikinci bir `slug` kolonu aynı bilgiyi iki yerde tutar ve bu dilime
gereksiz bir migration eklerdi.

Anahtar GLOBAL tekil olduğu için görünürlük süzgeci çözümden SONRA uygulanabilir
(hakediş/kira faturası gibi kapsam-içi anahtarlarda tersi gerekirdi) — süzgeç
yine de ATLANAMAZ: tekil erişimin TEK kapısı `visible_request`tir.
"""

import uuid

from app.modules.procurement.guards import REQUEST_MISSING

_YOL = "/purchase-requests"


async def test_uuid_ve_numara_AYNI_govdeyi_doner(
    client, satinalma_headers, talep_fabrikasi, gorunen_proje
) -> None:
    talep = await talep_fabrikasi(gorunen_proje)

    by_uuid = await client.get(f"{_YOL}/{talep.id}", headers=satinalma_headers)
    by_no = await client.get(f"{_YOL}/{talep.request_no}", headers=satinalma_headers)

    assert by_uuid.status_code == by_no.status_code == 200, by_no.text
    assert by_uuid.json() == by_no.json()
    assert by_no.json()["id"] == str(talep.id)


async def test_slug_alani_NUMARANIN_KENDISIDIR_ve_LISTEDE_de_bulunur(
    client, satinalma_headers, talep_fabrikasi, gorunen_proje
) -> None:
    """🔴 Liste ucu `satinalma/talepler/[id]` bağlantısını üretir — slug ORADA da olmalı.

    `_base_fields` hem listeyi hem detayı beslediği için tek yerde eklendi;
    test ikisini de OKUR çünkü şemalar bir gün ayrılabilir.
    """
    talep = await talep_fabrikasi(gorunen_proje)

    detay = await client.get(f"{_YOL}/{talep.id}", headers=satinalma_headers)
    assert detay.json()["slug"] == talep.request_no

    liste = await client.get(_YOL, headers=satinalma_headers)
    assert liste.status_code == 200, liste.text
    satir = next(k for k in liste.json()["items"] if k["id"] == str(talep.id))
    assert satir["slug"] == talep.request_no

    # Yayınlanan anahtar GERÇEKTEN o kaydı açar (karşıt kanıt).
    assert (await client.get(f"{_YOL}/{satir['slug']}", headers=satinalma_headers)).json()[
        "id"
    ] == str(talep.id)


async def test_gorunmeyen_projenin_talebi_NUMARAYLA_da_404(
    client, sef_headers, admin_headers, talep_fabrikasi, gorunmeyen_proje
) -> None:
    """🔴 Numara TAHMİN EDİLEBİLİR (`SAT-2026-0001` sunucu üretir), UUID değil."""
    talep = await talep_fabrikasi(gorunmeyen_proje)

    numarayla = await client.get(f"{_YOL}/{talep.request_no}", headers=sef_headers)
    uuid_ile = await client.get(f"{_YOL}/{talep.id}", headers=sef_headers)
    olmayan = await client.get(f"{_YOL}/SAT-YOK-9999", headers=sef_headers)

    assert numarayla.status_code == uuid_ile.status_code == olmayan.status_code == 404
    assert numarayla.json() == uuid_ile.json() == olmayan.json() == {"detail": REQUEST_MISSING}

    # 🔴 POZİTİF KONTROL (K-IKIZ1): GÖREN aktör AYNI numarayla 200 alır —
    # 404'ler numaranın çözülmemesinden DEĞİL, görünürlükten geliyor.
    goren = await client.get(f"{_YOL}/{talep.request_no}", headers=admin_headers)
    assert goren.status_code == 200, goren.text
    assert goren.json()["id"] == str(talep.id)


async def test_PATCH_numara_kabul_ETMEZ_422(
    client, satinalma_headers, talep_fabrikasi, gorunen_proje
) -> None:
    """Yazma yüzeyi tahmin edilebilir bir anahtara AÇILMAZ (URL-2 kararı 3)."""
    talep = await talep_fabrikasi(gorunen_proje)

    resp = await client.patch(
        f"{_YOL}/{talep.request_no}", json={"justification": "x"}, headers=satinalma_headers
    )
    assert resp.status_code == 422, resp.text

    # POZİTİF KONTROL: UUID ile AYNI uç çalışır.
    assert (
        await client.patch(
            f"{_YOL}/{talep.id}", json={"justification": "x"}, headers=satinalma_headers
        )
    ).status_code == 200


async def test_bozuk_deger_artik_422_DEGIL_404(client, satinalma_headers) -> None:
    """URL-2 kararı 6'nın kabul edilmiş YAN ETKİSİ."""
    assert (
        await client.get(f"{_YOL}/kesinlikle-uuid-degil", headers=satinalma_headers)
    ).status_code == 404
    assert (
        await client.get(f"{_YOL}/{uuid.uuid4()}", headers=satinalma_headers)
    ).status_code == 404
