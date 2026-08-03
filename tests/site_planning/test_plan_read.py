"""T2 — `GET /sites/{site_id}/plan?week_start=` okuma ucu (planlama spec §3).

Kanıtlanan dört şey:
1. **Şekil** — bölüm gruplu satırlar + o haftanın hücreleri + hedefler + aktif sprint.
2. **Hafta kapsamı** — başka haftanın hücresi SIZMAZ, hücresi olmayan satır BOŞ
   hücre listesiyle döner ("hücre yokluğu = plan yok", uydurma hücre yok).
3. **`week_start` Pazartesi ŞART** — değilse 422 (plan T2).
4. **İki katmanlı koruma** — `site_diary` izin kapısı (İK 403, PM okur) +
   `visible_projects` kapsamı (görünmeyen proje → 404, var olmayanla aynı gövde).
"""

import uuid
from datetime import date

import pytest
from httpx import AsyncClient

from app.modules.site_planning.models import PlanCellTag, PlanGoalStatus, PlanResourceKind
from app.modules.sites.guards import SITE_MISSING
from tests.site_planning.conftest import HAFTA, ONCEKI_HAFTA, gun, plan_url

pytestmark = pytest.mark.asyncio


# --- Mutlu yol ---


async def test_mutlu_yol_gruplu_satirlar_hucreler_hedefler_sprint(
    client: AsyncClient,
    admin_headers: dict[str, str],
    santiye,
    bolum,
    satir_fabrikasi,
    hucre_fabrikasi,
    hedef_fabrikasi,
    sprint_fabrikasi,
) -> None:
    """P107 sprint şeridi + P126-179 ızgara + P203-227 hedefler tek yanıtta."""
    kalipci = await satir_fabrikasi(
        santiye, "Kalıpçı", section=bolum, planned_worker_count=14, sort_order=1
    )
    demirci = await satir_fabrikasi(
        santiye, "Demirci", section=bolum, planned_worker_count=18, sort_order=2
    )
    vinc = await satir_fabrikasi(
        santiye, "Tower Crane", kind=PlanResourceKind.equipment, sort_order=1
    )
    await hucre_fabrikasi(kalipci, gun(0), "Kat 9 Kalıp", tag=PlanCellTag.blue)
    await hucre_fabrikasi(kalipci, gun(2), "Döşeme Dök.", tag=PlanCellTag.green)
    await hucre_fabrikasi(demirci, gun(0), "Kolon Demir", tag=PlanCellTag.yellow)
    await hucre_fabrikasi(vinc, gun(0), "✓ Çalışıyor", tag=PlanCellTag.green)
    await hedef_fabrikasi(
        santiye,
        "Kat 9 kalıp montajı tamamla",
        note="Sorumlu: Kalıpçı Ekibi",
        is_done=True,
        status=PlanGoalStatus.completed,
        sort_order=1,
    )
    await hedef_fabrikasi(santiye, "Kat 9 döşeme betonu dök", note="Çar-Per · 160 m³", sort_order=2)
    await sprint_fabrikasi(santiye, "Kat 8–9 Tamamlama")

    yanit = await client.get(plan_url(santiye.id), headers=admin_headers)
    assert yanit.status_code == 200, yanit.text
    veri = yanit.json()

    assert veri["site_id"] == str(santiye.id)
    assert veri["site_name"] == santiye.name
    assert veri["project_id"] == str(santiye.project_id)
    assert veri["week_start"] == HAFTA.isoformat()
    assert veri["week_end"] == gun(6).isoformat()

    # Gün iskeleti TÜREVDİR (7 gün, hafta sonu işaretli — P138-139 vurgusu).
    assert [g["plan_date"] for g in veri["days"]] == [gun(i).isoformat() for i in range(7)]
    assert [g["is_weekend"] for g in veri["days"]] == [False] * 5 + [True, True]

    # İki grup: bölümlü ekip grubu + ekipman grubu (P158 "Makine & Ekipman").
    assert len(veri["groups"]) == 2
    ekip, ekipman = veri["groups"]
    assert ekip["kind"] == "crew"
    assert ekip["section_id"] == str(bolum.id)
    assert ekip["section_name"] == "Kat 6–10 Kaba"
    assert ekip["section_manager_name"] == "Sercan Öztürk"
    assert [s["label"] for s in ekip["rows"]] == ["Kalıpçı", "Demirci"]
    assert ekip["rows"][0]["planned_worker_count"] == 14

    assert ekipman["kind"] == "equipment"
    assert ekipman["section_id"] is None
    assert ekipman["section_name"] is None
    assert [s["label"] for s in ekipman["rows"]] == ["Tower Crane"]

    kalipci_hucreleri = ekip["rows"][0]["cells"]
    assert [h["plan_date"] for h in kalipci_hucreleri] == [gun(0).isoformat(), gun(2).isoformat()]
    assert kalipci_hucreleri[0]["text"] == "Kat 9 Kalıp"
    assert kalipci_hucreleri[0]["tag"] == "blue"

    assert [h["title"] for h in veri["goals"]] == [
        "Kat 9 kalıp montajı tamamla",
        "Kat 9 döşeme betonu dök",
    ]
    assert veri["goals"][0]["is_done"] is True
    assert veri["goals"][0]["status"] == "completed"
    assert veri["goals"][1]["note"] == "Çar-Per · 160 m³"

    assert veri["active_sprint"]["name"] == "Kat 8–9 Tamamlama"


async def test_hucresiz_satir_bos_hucre_listesiyle_doner(
    client: AsyncClient, admin_headers: dict[str, str], santiye, bolum, satir_fabrikasi
) -> None:
    """Hücre YOKLUĞU = plan yok: satır görünür ama uydurma boş hücre BASILMAZ."""
    await satir_fabrikasi(santiye, "Elektrikçi", section=bolum, sort_order=1)

    yanit = await client.get(plan_url(santiye.id), headers=admin_headers)
    assert yanit.status_code == 200, yanit.text
    (grup,) = yanit.json()["groups"]
    (satir,) = grup["rows"]
    assert satir["cells"] == []


async def test_baska_haftanin_hucresi_sizmaz(
    client: AsyncClient,
    admin_headers: dict[str, str],
    santiye,
    bolum,
    satir_fabrikasi,
    hucre_fabrikasi,
) -> None:
    """Hafta penceresi [Pzt, Paz]: bir gün önce/sonra AYNI satırda görünmez."""
    satir = await satir_fabrikasi(santiye, "Kalıpçı", section=bolum, sort_order=1)
    await hucre_fabrikasi(satir, gun(-1), "Önceki hafta Paz")
    await hucre_fabrikasi(satir, gun(3), "Bu hafta Per")
    await hucre_fabrikasi(satir, gun(7), "Sonraki hafta Pzt")

    yanit = await client.get(plan_url(santiye.id), headers=admin_headers)
    assert yanit.status_code == 200, yanit.text
    (grup,) = yanit.json()["groups"]
    (satir_yanit,) = grup["rows"]
    assert [h["text"] for h in satir_yanit["cells"]] == ["Bu hafta Per"]


async def test_baska_haftanin_hedefi_sizmaz(
    client: AsyncClient, admin_headers: dict[str, str], santiye, hedef_fabrikasi
) -> None:
    await hedef_fabrikasi(santiye, "Bu hafta", sort_order=1)
    await hedef_fabrikasi(santiye, "Geçen hafta", week_start=ONCEKI_HAFTA, sort_order=1)

    yanit = await client.get(plan_url(santiye.id), headers=admin_headers)
    assert yanit.status_code == 200, yanit.text
    assert [h["title"] for h in yanit.json()["goals"]] == ["Bu hafta"]


async def test_baska_santiyenin_satiri_sizmaz(
    client: AsyncClient,
    admin_headers: dict[str, str],
    santiye,
    ikinci_santiye,
    satir_fabrikasi,
) -> None:
    """Kapsam `visible_projects`in yan etkisi DEĞİL: iki şantiye AYNI projede."""
    await satir_fabrikasi(santiye, "Kalıpçı", sort_order=1)
    await satir_fabrikasi(ikinci_santiye, "Komşu Ekip", sort_order=1)

    yanit = await client.get(plan_url(santiye.id), headers=admin_headers)
    assert yanit.status_code == 200, yanit.text
    etiketler = [s["label"] for g in yanit.json()["groups"] for s in g["rows"]]
    assert etiketler == ["Kalıpçı"]


async def test_grup_sirasi_bolum_sonra_bolumsuz_sonra_ekipman(
    client: AsyncClient,
    admin_headers: dict[str, str],
    santiye,
    bolum,
    ikinci_bolum,
    satir_fabrikasi,
) -> None:
    """Grup sırası DB'de belirlenir (P125 → P158): bölümlü ekipler bölümün
    `sort_order`ıyla, bölümsüz ekipler sonra, ekipman grubu EN SONDA.

    Bölümsüz ekip satırı (bölüm silinince `SET NULL`) ekipman grubuna
    KARIŞMAMALIDIR — karışsaydı "Makine & Ekipman" başlığı kaybolurdu.
    """
    await satir_fabrikasi(santiye, "İnce İşçi", section=ikinci_bolum, sort_order=1)
    await satir_fabrikasi(santiye, "Kalıpçı", section=bolum, sort_order=1)
    await satir_fabrikasi(santiye, "Bölümsüz Ekip", sort_order=1)
    await satir_fabrikasi(santiye, "Tower Crane", kind=PlanResourceKind.equipment, sort_order=1)

    yanit = await client.get(plan_url(santiye.id), headers=admin_headers)
    assert yanit.status_code == 200, yanit.text
    gruplar = yanit.json()["groups"]
    assert [(g["kind"], g["section_name"]) for g in gruplar] == [
        ("crew", "Kat 6–10 Kaba"),
        ("crew", "Kat 1–5 İnce"),
        ("crew", None),
        ("equipment", None),
    ]
    assert [s["label"] for s in gruplar[2]["rows"]] == ["Bölümsüz Ekip"]
    assert [s["label"] for s in gruplar[3]["rows"]] == ["Tower Crane"]


async def test_pasif_sprint_donmez(
    client: AsyncClient, admin_headers: dict[str, str], santiye, sprint_fabrikasi
) -> None:
    """Aktif sprint YOKSA `null` — geçmiş sprint şeride yazılmaz (P107)."""
    await sprint_fabrikasi(santiye, "Kat 6–7 Tamamlama", is_active=False)

    yanit = await client.get(plan_url(santiye.id), headers=admin_headers)
    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["active_sprint"] is None


async def test_bos_plan_iskeleti_durur(
    client: AsyncClient, admin_headers: dict[str, str], santiye
) -> None:
    """Hiç satır yokken bile gün iskeleti + boş listeler döner (404 DEĞİL)."""
    yanit = await client.get(plan_url(santiye.id), headers=admin_headers)
    assert yanit.status_code == 200, yanit.text
    veri = yanit.json()
    assert veri["groups"] == []
    assert veri["goals"] == []
    assert veri["active_sprint"] is None
    assert len(veri["days"]) == 7


# --- `week_start` normalizasyonu ---


@pytest.mark.parametrize("tarih", [date(2026, 7, 21), date(2026, 7, 25), date(2026, 7, 19)])
async def test_week_start_pazartesi_degilse_422(
    client: AsyncClient, admin_headers: dict[str, str], santiye, tarih: date
) -> None:
    """Pzt olmayan hafta başı SESSİZCE kaydırılmaz: ekran istediğinden başka bir
    haftayı gösterdiğini fark edemezdi (plan T2)."""
    yanit = await client.get(plan_url(santiye.id, tarih), headers=admin_headers)
    assert yanit.status_code == 422, yanit.text


async def test_week_start_zorunlu(
    client: AsyncClient, admin_headers: dict[str, str], santiye
) -> None:
    yanit = await client.get(f"/sites/{santiye.id}/plan", headers=admin_headers)
    assert yanit.status_code == 422, yanit.text


# --- Katman 1: izin kapısı ---


async def test_izin_yoksa_403(client: AsyncClient, ik_headers: dict[str, str], santiye) -> None:
    """`hr_manager` matriste `site_diary=_N` — planı hiç göremez."""
    yanit = await client.get(plan_url(santiye.id), headers=ik_headers)
    assert yanit.status_code == 403, yanit.text


async def test_pm_okuyabilir(
    client: AsyncClient, pm_headers: dict[str, str], santiye, bolum, satir_fabrikasi
) -> None:
    """PM (`site_diary=_V`) kendi projesinin planını GÖRÜR (spec §6 S1)."""
    await satir_fabrikasi(santiye, "Kalıpçı", section=bolum, sort_order=1)

    yanit = await client.get(plan_url(santiye.id), headers=pm_headers)
    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["groups"][0]["rows"][0]["label"] == "Kalıpçı"


async def test_sef_okuyabilir(client: AsyncClient, sef_headers: dict[str, str], santiye) -> None:
    yanit = await client.get(plan_url(santiye.id), headers=sef_headers)
    assert yanit.status_code == 200, yanit.text


# --- Katman 2: kapsam süzgeci (IDOR) ---


async def test_gorunmeyen_projenin_santiyesi_404(
    client: AsyncClient, sef_headers: dict[str, str], gorunmeyen_santiye
) -> None:
    """403 DEĞİL 404: 403 kaydın var olduğunu sızdırırdı."""
    yanit = await client.get(plan_url(gorunmeyen_santiye.id), headers=sef_headers)
    assert yanit.status_code == 404, yanit.text
    assert yanit.json()["detail"] == SITE_MISSING


async def test_var_olmayan_santiye_ayni_404(
    client: AsyncClient, sef_headers: dict[str, str]
) -> None:
    """Var olmayan kimlik ile görünmeyen şantiye AYNI gövdeyi döner."""
    yanit = await client.get(plan_url(uuid.uuid4()), headers=sef_headers)
    assert yanit.status_code == 404, yanit.text
    assert yanit.json()["detail"] == SITE_MISSING
