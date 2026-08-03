"""T4 — `GET /sites/{site_id}/plan/day-summary?start=&days=` (planlama spec §4).

GK mockup'ının (`Şantiye - Günlük Kayıt.dc.html` 321-348) "📅 Planlama —
Önümüzdeki 5 Gün" bloğu bu ucu tüketir. Blok gün başına DÖRT şey gösterir:
gün etiketi (satır 327) · planlanan işler metni (satır 328) · "İşçi" sayısı
(satır 329) · "Bölüm" (satır 330). Üçüncü kutu (satır 341-346) planı OLMAYAN
günü kesikli çerçeve + "Henüz planlanmadı..." ile çizer — yani gün ATLANMAZ,
blok her hâlükârda 5 kutu çizer.

Kanıtlanan altı şey:
1. **Şekil** — çok satırlı/çok günlü ızgaradan gün başına özet (metin birleşimi
   + işçi toplamı + bölüm etiketleri).
2. **"Plan yok" AÇIKÇA işaretlenir** (`has_plan: false`) — gün listeden düşmez.
3. **İşçi toplamı YALNIZ `crew` satırlarından** — ekipman satırı toplama girmez
   (`planned_worker_count` dolu olsa bile).
4. **Aralık kapsamı** — `start` öncesi/`days` sonrası hücre SIZMAZ; başka
   şantiyenin hücresi SIZMAZ.
5. **`days` tavanı** — `service.MAX_SUMMARY_DAYS` üstü 422 (sınırsız aralık tek
   sorguyla tüm geçmişi tarardı).
6. **İki katmanlı koruma** — `site_diary` kapısı (İK 403, PM okur) +
   `visible_projects` kapsamı (görünmeyen proje → 404, var olmayanla aynı gövde).

`start` için Pazartesi şartı YOKTUR (T2'nin `week_start`inden bilinçli fark):
GK bloğu "önümüzdeki 5 gün"dür, haftalık ızgara değildir.
"""

import uuid

import pytest
from httpx import AsyncClient

from app.modules.site_planning.models import PlanResourceKind
from app.modules.site_planning.service import MAX_SUMMARY_DAYS
from app.modules.sites.guards import SITE_MISSING
from tests.site_planning.conftest import HAFTA, day_summary_url, gun

pytestmark = pytest.mark.asyncio


# --- Mutlu yol ---


async def test_mutlu_yol_cok_satir_cok_gun(
    client: AsyncClient,
    admin_headers: dict[str, str],
    santiye,
    bolum,
    ikinci_bolum,
    satir_fabrikasi,
    hucre_fabrikasi,
) -> None:
    """GK 321-348 bloğunun beş kutusu: metin (328) + işçi (329) + bölüm (330)."""
    kalipci = await satir_fabrikasi(
        santiye, "Kalıpçı", section=bolum, planned_worker_count=14, sort_order=1
    )
    demirci = await satir_fabrikasi(
        santiye, "Demirci", section=bolum, planned_worker_count=18, sort_order=2
    )
    elektrikci = await satir_fabrikasi(
        santiye, "Elektrikçi", section=ikinci_bolum, planned_worker_count=6, sort_order=1
    )
    await hucre_fabrikasi(kalipci, gun(0), "Kat 9 kolon betonu dökümü (60 m³)")
    await hucre_fabrikasi(demirci, gun(0), "Kat 8 demir devamı")
    await hucre_fabrikasi(demirci, gun(1), "Demir imalatı devam")
    await hucre_fabrikasi(elektrikci, gun(1), "Elektrik tesisat 7. kat")

    yanit = await client.get(day_summary_url(santiye.id), headers=admin_headers)
    assert yanit.status_code == 200, yanit.text
    veri = yanit.json()

    assert veri["site_id"] == str(santiye.id)
    assert veri["site_name"] == santiye.name
    assert veri["project_id"] == str(santiye.project_id)
    assert veri["start"] == HAFTA.isoformat()
    # Varsayılan `days` = 5 (GK bloğu beş kutu çizer); `end` DAHİLDİR.
    assert veri["end"] == gun(4).isoformat()
    assert [g["plan_date"] for g in veri["days"]] == [gun(i).isoformat() for i in range(5)]

    pzt, sal = veri["days"][0], veri["days"][1]
    assert pzt["has_plan"] is True
    assert pzt["text"] == "Kat 9 kolon betonu dökümü (60 m³) · Kat 8 demir devamı"
    assert pzt["planned_worker_total"] == 32
    assert pzt["section_names"] == ["Kat 6–10 Kaba"]

    assert sal["has_plan"] is True
    assert sal["text"] == "Demir imalatı devam · Elektrik tesisat 7. kat"
    assert sal["planned_worker_total"] == 24
    assert sal["section_names"] == ["Kat 6–10 Kaba", "Kat 1–5 İnce"]


async def test_plan_olmayan_gun_acikca_isaretlenir(
    client: AsyncClient,
    admin_headers: dict[str, str],
    santiye,
    bolum,
    satir_fabrikasi,
    hucre_fabrikasi,
) -> None:
    """GK 341-346: planlanmamış gün blokta kutu OLARAK durur, atlanmaz."""
    kalipci = await satir_fabrikasi(
        santiye, "Kalıpçı", section=bolum, planned_worker_count=14, sort_order=1
    )
    await hucre_fabrikasi(kalipci, gun(0), "Kat 9 Kalıp")

    yanit = await client.get(day_summary_url(santiye.id), headers=admin_headers)
    assert yanit.status_code == 200, yanit.text
    gunler = yanit.json()["days"]

    assert len(gunler) == 5
    assert [g["has_plan"] for g in gunler] == [True, False, False, False, False]
    bos = gunler[1]
    assert bos["text"] == ""
    assert bos["planned_worker_total"] == 0
    assert bos["section_names"] == []


async def test_hic_plan_yoksa_tum_gunler_plan_yok(
    client: AsyncClient, admin_headers: dict[str, str], santiye
) -> None:
    """Hiç satır yokken bile gün iskeleti durur — 404 DEĞİL."""
    yanit = await client.get(day_summary_url(santiye.id), headers=admin_headers)
    assert yanit.status_code == 200, yanit.text
    gunler = yanit.json()["days"]
    assert len(gunler) == 5
    assert all(g["has_plan"] is False for g in gunler)


async def test_isci_toplami_yalniz_crew_satirlarindan(
    client: AsyncClient,
    admin_headers: dict[str, str],
    santiye,
    bolum,
    satir_fabrikasi,
    hucre_fabrikasi,
) -> None:
    """Ekipman satırı işçi toplamına GİRMEZ — `planned_worker_count` DOLU olsa bile.

    Kolon modelde ekipman için de yazılabilir (spec §2 yasaklamaz); toplam GK'nin
    "İşçi" kutusudur (satır 329) ve bir vincin "işçi sayısı" yoktur.
    """
    kalipci = await satir_fabrikasi(
        santiye, "Kalıpçı", section=bolum, planned_worker_count=14, sort_order=1
    )
    sayisiz = await satir_fabrikasi(santiye, "Yardımcı Ekip", section=bolum, sort_order=2)
    vinc = await satir_fabrikasi(
        santiye,
        "Tower Crane",
        kind=PlanResourceKind.equipment,
        planned_worker_count=99,
        sort_order=1,
    )
    await hucre_fabrikasi(kalipci, gun(0), "Kat 9 Kalıp")
    await hucre_fabrikasi(sayisiz, gun(0), "Destek")
    await hucre_fabrikasi(vinc, gun(0), "✓ Çalışıyor")

    yanit = await client.get(day_summary_url(santiye.id), headers=admin_headers)
    assert yanit.status_code == 200, yanit.text
    pzt = yanit.json()["days"][0]

    # 14 (Kalıpçı) + 0 (sayısız ekip) — 99'luk vinç YOK.
    assert pzt["planned_worker_total"] == 14
    # Ekipman hücresinin METNİ özete girer (gün ne yapılacağını anlatır).
    assert pzt["text"] == "Kat 9 Kalıp · Destek · ✓ Çalışıyor"


async def test_hucresiz_satir_isci_toplamina_girmez(
    client: AsyncClient,
    admin_headers: dict[str, str],
    santiye,
    bolum,
    satir_fabrikasi,
    hucre_fabrikasi,
) -> None:
    """Toplam GÜNE aittir: o gün hücresi olmayan ekip o güne sayılmaz."""
    kalipci = await satir_fabrikasi(
        santiye, "Kalıpçı", section=bolum, planned_worker_count=14, sort_order=1
    )
    await satir_fabrikasi(santiye, "Demirci", section=bolum, planned_worker_count=18, sort_order=2)
    await hucre_fabrikasi(kalipci, gun(0), "Kat 9 Kalıp")

    yanit = await client.get(day_summary_url(santiye.id), headers=admin_headers)
    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["days"][0]["planned_worker_total"] == 14


async def test_bolum_etiketleri_tekillesir(
    client: AsyncClient,
    admin_headers: dict[str, str],
    santiye,
    bolum,
    satir_fabrikasi,
    hucre_fabrikasi,
) -> None:
    """GK "Bölüm" kutusu (satır 330) tek tek satırları değil BÖLÜMLERİ listeler.

    Bölümsüz satır (`SET NULL`) ve ekipman satırı etiket ÜRETMEZ — `null` bir
    bölüm adı kutuda boş bir seçenek olurdu.
    """
    kalipci = await satir_fabrikasi(santiye, "Kalıpçı", section=bolum, sort_order=1)
    demirci = await satir_fabrikasi(santiye, "Demirci", section=bolum, sort_order=2)
    bolumsuz = await satir_fabrikasi(santiye, "Bölümsüz Ekip", sort_order=3)
    vinc = await satir_fabrikasi(
        santiye, "Tower Crane", kind=PlanResourceKind.equipment, sort_order=1
    )
    for satir in (kalipci, demirci, bolumsuz, vinc):
        await hucre_fabrikasi(satir, gun(0), f"{satir.label} işi")

    yanit = await client.get(day_summary_url(santiye.id), headers=admin_headers)
    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["days"][0]["section_names"] == ["Kat 6–10 Kaba"]


# --- Aralık kapsamı ---


async def test_aralik_disi_hucre_sizmaz(
    client: AsyncClient,
    admin_headers: dict[str, str],
    santiye,
    bolum,
    satir_fabrikasi,
    hucre_fabrikasi,
) -> None:
    """Pencere `[start, start + days - 1]` DAHİLDİR: bir gün önce/sonra girmez."""
    kalipci = await satir_fabrikasi(santiye, "Kalıpçı", section=bolum, sort_order=1)
    await hucre_fabrikasi(kalipci, gun(-1), "Önceki gün")
    await hucre_fabrikasi(kalipci, gun(0), "İlk gün")
    await hucre_fabrikasi(kalipci, gun(2), "Son gün")
    await hucre_fabrikasi(kalipci, gun(3), "Pencere dışı")

    yanit = await client.get(day_summary_url(santiye.id, days=3), headers=admin_headers)
    assert yanit.status_code == 200, yanit.text
    veri = yanit.json()
    assert veri["end"] == gun(2).isoformat()
    assert [g["text"] for g in veri["days"]] == ["İlk gün", "", "Son gün"]


async def test_baska_santiyenin_hucresi_sizmaz(
    client: AsyncClient,
    admin_headers: dict[str, str],
    santiye,
    ikinci_santiye,
    satir_fabrikasi,
    hucre_fabrikasi,
) -> None:
    """İki şantiye AYNI projede: kapsam `visible_projects`in yan etkisi DEĞİL."""
    benim = await satir_fabrikasi(santiye, "Kalıpçı", planned_worker_count=14, sort_order=1)
    komsu = await satir_fabrikasi(
        ikinci_santiye, "Komşu Ekip", planned_worker_count=50, sort_order=1
    )
    await hucre_fabrikasi(benim, gun(0), "Benim işim")
    await hucre_fabrikasi(komsu, gun(0), "Komşu işi")

    yanit = await client.get(day_summary_url(santiye.id), headers=admin_headers)
    assert yanit.status_code == 200, yanit.text
    pzt = yanit.json()["days"][0]
    assert pzt["text"] == "Benim işim"
    assert pzt["planned_worker_total"] == 14


async def test_start_pazartesi_olmak_zorunda_degil(
    client: AsyncClient,
    admin_headers: dict[str, str],
    santiye,
    satir_fabrikasi,
    hucre_fabrikasi,
) -> None:
    """T2'nin `week_start`inden bilinçli fark: bu blok KAYAN 5 gündür.

    Pencere hafta sınırını da AŞABİLİR (Cuma'dan başlayan beş gün gelecek
    haftanın Salı'sına taşar).
    """
    kalipci = await satir_fabrikasi(santiye, "Kalıpçı", sort_order=1)
    await hucre_fabrikasi(kalipci, gun(4), "Cuma işi")
    await hucre_fabrikasi(kalipci, gun(8), "Gelecek hafta Salı")

    yanit = await client.get(day_summary_url(santiye.id, start=gun(4)), headers=admin_headers)
    assert yanit.status_code == 200, yanit.text
    veri = yanit.json()
    assert veri["start"] == gun(4).isoformat()
    assert veri["end"] == gun(8).isoformat()
    assert [g["text"] for g in veri["days"]] == ["Cuma işi", "", "", "", "Gelecek hafta Salı"]


# --- Parametre korkulukları ---


async def test_start_zorunlu(client: AsyncClient, admin_headers: dict[str, str], santiye) -> None:
    yanit = await client.get(f"/sites/{santiye.id}/plan/day-summary", headers=admin_headers)
    assert yanit.status_code == 422, yanit.text


@pytest.mark.parametrize("gun_sayisi", [0, -1, MAX_SUMMARY_DAYS + 1, 400])
async def test_days_siniri_disinda_422(
    client: AsyncClient, admin_headers: dict[str, str], santiye, gun_sayisi: int
) -> None:
    """Sınırsız `days` tek istekle tüm geçmişi taratırdı (sınır `service`de)."""
    yanit = await client.get(day_summary_url(santiye.id, days=gun_sayisi), headers=admin_headers)
    assert yanit.status_code == 422, yanit.text


async def test_days_tavani_kabul_edilir(
    client: AsyncClient, admin_headers: dict[str, str], santiye
) -> None:
    """Tavan DAHİLDİR — sınırın kendisi reddedilmez."""
    yanit = await client.get(
        day_summary_url(santiye.id, days=MAX_SUMMARY_DAYS), headers=admin_headers
    )
    assert yanit.status_code == 200, yanit.text
    assert len(yanit.json()["days"]) == MAX_SUMMARY_DAYS


# --- Katman 1: izin kapısı ---


async def test_izin_yoksa_403(client: AsyncClient, ik_headers: dict[str, str], santiye) -> None:
    """`hr_manager` matriste `site_diary=_N` — özeti de göremez."""
    yanit = await client.get(day_summary_url(santiye.id), headers=ik_headers)
    assert yanit.status_code == 403, yanit.text


async def test_pm_okuyabilir(
    client: AsyncClient,
    pm_headers: dict[str, str],
    santiye,
    bolum,
    satir_fabrikasi,
    hucre_fabrikasi,
) -> None:
    """PM (`site_diary=_V`) salt-okur türevi GÖRÜR (spec §6 S1)."""
    kalipci = await satir_fabrikasi(
        santiye, "Kalıpçı", section=bolum, planned_worker_count=14, sort_order=1
    )
    await hucre_fabrikasi(kalipci, gun(0), "Kat 9 Kalıp")

    yanit = await client.get(day_summary_url(santiye.id), headers=pm_headers)
    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["days"][0]["text"] == "Kat 9 Kalıp"


# --- Katman 2: kapsam süzgeci (IDOR) ---


async def test_gorunmeyen_projenin_santiyesi_404(
    client: AsyncClient, sef_headers: dict[str, str], gorunmeyen_santiye
) -> None:
    """403 DEĞİL 404: 403 kaydın var olduğunu sızdırırdı."""
    yanit = await client.get(day_summary_url(gorunmeyen_santiye.id), headers=sef_headers)
    assert yanit.status_code == 404, yanit.text
    assert yanit.json()["detail"] == SITE_MISSING


async def test_var_olmayan_santiye_ayni_404(
    client: AsyncClient, sef_headers: dict[str, str]
) -> None:
    yanit = await client.get(day_summary_url(uuid.uuid4()), headers=sef_headers)
    assert yanit.status_code == 404, yanit.text
    assert yanit.json()["detail"] == SITE_MISSING
