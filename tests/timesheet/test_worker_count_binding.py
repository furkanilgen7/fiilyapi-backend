"""T4 — `sites`/`projects` servislerindeki `_TIMESHEET` yer tutucularının bağlanması.

P1/P2'de `worker_count` (şantiye kartı ŞP 118 "48 işçi" · bölüm satırı · taahhüt
kartı) ve `active_worker_count` (şantiye listesi alt KPI şeridi) "veri kaynağı
henüz yazılmadı" yer tutucusuydu (`available: false`, `count: null`). Puantaj
kaydı açıldığı için dördü de artık GERÇEK sayıdır.

## Dönem kararı — İÇİNDE BULUNULAN AY

Bu uçların hiçbirinde `year`/`month` sorgu parametresi YOKTUR (şantiye listesi,
şantiye detayı, bölüm detayı, proje listesi); dönem sunucuda seçilmek zorundadır.
Puantajın dönem birimi AYDIR (matris uçları `year`+`month` ister, spec §3) ve
mockup'taki sayaç anlık bir "şu an sahada kaç kişi var" rozetidir — bu yüzden
"aktif dönem" = görüntüleme saat dilimindeki (`core.timezone.today`) İÇİNDE
BULUNULAN AY'dır. Geçen ayın hücreleri sayıya GİRMEZ.

Sayılan şey **distinct personel**dir: aynı kişinin 20 günü 20 işçi DEĞİLDİR.
"""

from datetime import date, timedelta

import pytest
from httpx import AsyncClient

from app.core.timezone import today
from app.modules.timesheet.models import TimesheetCode

pytestmark = pytest.mark.asyncio

_C = TimesheetCode.worked


def bu_ay(day: int) -> date:
    """İçinde bulunulan ayın `day`. günü — sayacın dönemi buradan okunur."""
    return today().replace(day=day)


def gecen_ay() -> date:
    """Önceki ayın SON günü (ayın ilk gününden bir gün geri)."""
    return bu_ay(1) - timedelta(days=1)


async def _santiye_listesi(client: AsyncClient, headers, proje) -> dict:
    yanit = await client.get(f"/projects/{proje.id}/sites", headers=headers)
    assert yanit.status_code == 200, yanit.text
    return yanit.json()


async def _santiye_detay(client: AsyncClient, headers, santiye) -> dict:
    yanit = await client.get(f"/sites/{santiye.id}", headers=headers)
    assert yanit.status_code == 200, yanit.text
    return yanit.json()


async def _bolum_detay(client: AsyncClient, headers, bolum) -> dict:
    yanit = await client.get(f"/sections/{bolum.id}", headers=headers)
    assert yanit.status_code == 200, yanit.text
    return yanit.json()


async def _proje_listesi(client: AsyncClient, headers) -> dict:
    yanit = await client.get("/projects", headers=headers)
    assert yanit.status_code == 200, yanit.text
    return yanit.json()


def _proje_satiri(govde: dict, proje_id) -> dict:
    for item in govde["items"]:
        if item["id"] == str(proje_id):
            return item
    raise AssertionError(f"proje listede yok: {proje_id}")


# --- Bağlanmış sözleşme ---


async def test_kayitsiz_santiyede_sayac_sifirdir_ama_hazirdir(
    client, admin_headers, proje, santiye
):
    """Yer tutucu sözleşmesi KALKAR: `available` artık true, `count` uydurma değil 0."""
    liste = await _santiye_listesi(client, admin_headers, proje)

    assert liste["items"][0]["worker_count"] == {
        "available": True,
        "count": 0,
        "pending_module": "timesheet",
    }
    assert liste["totals"]["active_worker_count"] == {
        "available": True,
        "count": 0,
        "pending_module": "timesheet",
    }


async def test_santiye_karti_distinct_personeli_sayar(
    client, admin_headers, proje, santiye, mehmet, ali, admin_kullanicisi, hucre_fabrikasi
):
    """Mehmet'in İKİ günü tek işçidir; Ali ikinci işçidir → 2."""
    await hucre_fabrikasi(santiye, mehmet, bu_ay(1), _C, admin_kullanicisi)
    await hucre_fabrikasi(santiye, mehmet, bu_ay(2), _C, admin_kullanicisi)
    await hucre_fabrikasi(santiye, ali, bu_ay(1), _C, admin_kullanicisi)

    liste = await _santiye_listesi(client, admin_headers, proje)
    assert liste["items"][0]["worker_count"]["count"] == 2

    detay = await _santiye_detay(client, admin_headers, santiye)
    assert detay["worker_count"]["count"] == 2


async def test_gecen_ayin_kaydi_sayilmaz(
    client, admin_headers, proje, santiye, mehmet, ali, admin_kullanicisi, hucre_fabrikasi
):
    """Dönem İÇİNDE BULUNULAN AY'dır: önceki ayın hücresi rozeti şişirmez."""
    await hucre_fabrikasi(santiye, mehmet, bu_ay(1), _C, admin_kullanicisi)
    await hucre_fabrikasi(santiye, ali, gecen_ay(), _C, admin_kullanicisi)

    detay = await _santiye_detay(client, admin_headers, santiye)
    assert detay["worker_count"]["count"] == 1


async def test_baska_santiyenin_kaydi_karta_girmez_proje_toplamina_girer(
    client,
    admin_headers,
    proje,
    santiye,
    ikinci_santiye,
    mehmet,
    ali,
    admin_kullanicisi,
    hucre_fabrikasi,
):
    """Kart ŞANTİYE kapsamındadır; alt KPI şeridi PROJE kapsamında distinct sayar."""
    await hucre_fabrikasi(santiye, mehmet, bu_ay(1), _C, admin_kullanicisi)
    await hucre_fabrikasi(ikinci_santiye, ali, bu_ay(1), _C, admin_kullanicisi)

    liste = await _santiye_listesi(client, admin_headers, proje)
    kartlar = {item["code"]: item["worker_count"]["count"] for item in liste["items"]}
    assert kartlar == {"TS-A": 1, "TS-B": 1}
    assert liste["totals"]["active_worker_count"]["count"] == 2


async def test_ayni_kisi_iki_santiyede_proje_toplaminda_bir_kez_sayilir(
    client,
    admin_headers,
    proje,
    santiye,
    ikinci_santiye,
    mehmet,
    admin_kullanicisi,
    hucre_fabrikasi,
):
    """DISTINCT proje düzeyinde de geçerlidir — kart toplamlarının TOPLAMI değildir."""
    await hucre_fabrikasi(santiye, mehmet, bu_ay(1), _C, admin_kullanicisi)
    await hucre_fabrikasi(ikinci_santiye, mehmet, bu_ay(2), _C, admin_kullanicisi)

    liste = await _santiye_listesi(client, admin_headers, proje)
    assert liste["totals"]["active_worker_count"]["count"] == 1


async def test_bolum_sayaci_yalniz_o_bolumun_hucrelerinden(
    client,
    admin_headers,
    santiye,
    bolum,
    ikinci_bolum,
    mehmet,
    ali,
    admin_kullanicisi,
    hucre_fabrikasi,
):
    """Bölümsüz (`section_id: null`) hücre HİÇBİR bölümün sayacına girmez."""
    await hucre_fabrikasi(santiye, mehmet, bu_ay(1), _C, admin_kullanicisi, section=bolum)
    await hucre_fabrikasi(santiye, ali, bu_ay(1), _C, admin_kullanicisi)

    detay = await _santiye_detay(client, admin_headers, santiye)
    bolumler = {b["code"]: b["worker_count"]["count"] for b in detay["sections"]}
    assert bolumler == {"B-1": 1, "B-2": 0}

    bolum_detay = await _bolum_detay(client, admin_headers, bolum)
    assert bolum_detay["worker_count"]["count"] == 1


async def test_taahhut_kartinin_isci_sayisi_projenin_tum_santiyelerinden(
    client,
    admin_headers,
    proje,
    santiye,
    ikinci_santiye,
    mehmet,
    ali,
    admin_kullanicisi,
    hucre_fabrikasi,
):
    """Taahhüt kartı PROJE kapsamındadır (şantiye kırılımı yok)."""
    await hucre_fabrikasi(santiye, mehmet, bu_ay(1), _C, admin_kullanicisi)
    await hucre_fabrikasi(ikinci_santiye, ali, bu_ay(1), _C, admin_kullanicisi)

    liste = await _proje_listesi(client, admin_headers)
    kart = _proje_satiri(liste, proje.id)["contracting"]
    assert kart["worker_count"] == {"available": True, "count": 2, "pending_module": "timesheet"}
    # Bağlanmayanlar yer tutucu KALIR — bu dilim yalnız puantajı bağlar.
    assert kart["subcontractor_count"]["available"] is False
    assert kart["spent"]["available"] is False
