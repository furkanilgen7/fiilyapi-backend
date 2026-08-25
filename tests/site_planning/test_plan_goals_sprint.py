"""T3 — `PUT …/plan/goals?week_start=` + `PUT …/plan/sprint` (planlama spec §3).

Hedeflerde de **kapsam kanıtı** ayrı ayrı kurulur: bir haftanın hedef listesini
kaydetmek BAŞKA HAFTANIN ve BAŞKA ŞANTİYENİN hedeflerine dokunmaz; başka haftanın
hedef kimliği gövdeye yazılamaz (yazılabilseydi hedef sessizce hafta DEĞİŞTİRİRDİ).

Sprint tarafında kanıtlanan: kısmi UQ (şantiye başına TEK aktif) uçtan uca korunur
· boş ad aktif sprinti KAPATIR · komşu şantiyenin sprinti etkilenmez.
"""

import uuid
from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditLog
from app.modules.site_planning import guards
from app.modules.site_planning.models import SitePlanGoal, SitePlanSprint
from app.modules.sites.guards import SITE_MISSING
from tests.site_planning.conftest import HAFTA, ONCEKI_HAFTA, goals_url, sprint_url

pytestmark = pytest.mark.asyncio


def _hedef(
    title: str,
    *,
    goal_id: uuid.UUID | None = None,
    note: str | None = None,
    is_done: bool = False,
    status: str = "in_progress",
    sort_order: int = 0,
) -> dict:
    return {
        "id": str(goal_id) if goal_id is not None else None,
        "title": title,
        "note": note,
        "is_done": is_done,
        "status": status,
        "sort_order": sort_order,
    }


async def _kaydet(
    client: AsyncClient,
    headers: dict[str, str],
    site_id,
    goals: list[dict],
    week_start: date = HAFTA,
):
    return await client.put(goals_url(site_id, week_start), headers=headers, json={"goals": goals})


# --- DEĞİŞTİRME semantiği ---


async def test_goals_ekler_gunceller_ve_siler(
    client: AsyncClient,
    sef_headers: dict[str, str],
    seeded_db: AsyncSession,
    santiye,
    hedef_fabrikasi,
) -> None:
    kalan = await hedef_fabrikasi(santiye, "Kat 9 kalıp montajı", sort_order=1)
    silinecek = await hedef_fabrikasi(santiye, "Silinecek hedef", sort_order=2)

    yanit = await _kaydet(
        client,
        sef_headers,
        santiye.id,
        [
            _hedef(
                "Kat 9 kalıp montajı tamamla",
                goal_id=kalan.id,
                note="Sorumlu: Kalıpçı Ekibi",
                is_done=True,
                status="completed",
                sort_order=1,
            ),
            _hedef("Kat 9 döşeme betonu dök", note="Çar-Per · 160 m³", sort_order=2),
        ],
    )
    assert yanit.status_code == 200, yanit.text

    hedefler = yanit.json()["goals"]
    assert [h["title"] for h in hedefler] == [
        "Kat 9 kalıp montajı tamamla",
        "Kat 9 döşeme betonu dök",
    ]
    # `is_done` ve `status` AYRI alanlardır, biri diğerini türetmez (spec §2).
    assert hedefler[0]["is_done"] is True
    assert hedefler[0]["status"] == "completed"
    assert hedefler[0]["id"] == str(kalan.id)

    kalanlar = (await seeded_db.execute(select(SitePlanGoal))).scalars().all()
    assert silinecek.id not in {h.id for h in kalanlar}


async def test_bos_govde_haftanin_hedeflerini_siler(
    client: AsyncClient,
    sef_headers: dict[str, str],
    seeded_db: AsyncSession,
    santiye,
    hedef_fabrikasi,
) -> None:
    await hedef_fabrikasi(santiye, "Tek hedef", sort_order=1)

    yanit = await _kaydet(client, sef_headers, santiye.id, [])
    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["goals"] == []
    assert (await seeded_db.execute(select(SitePlanGoal))).scalars().all() == []


# --- KAPSAM KANITI: hafta ---


async def test_baska_haftanin_hedefine_dokunmaz(
    client: AsyncClient,
    sef_headers: dict[str, str],
    seeded_db: AsyncSession,
    santiye,
    hedef_fabrikasi,
) -> None:
    """⚠️ Silme koşulunun HAFTA parçası (`site_id` + `week_start`)."""
    onceki = await hedef_fabrikasi(santiye, "Geçen hafta", week_start=ONCEKI_HAFTA, sort_order=1)
    bu_hafta = await hedef_fabrikasi(santiye, "Bu hafta", sort_order=1)

    yanit = await _kaydet(client, sef_headers, santiye.id, [])
    assert yanit.status_code == 200, yanit.text

    kalanlar = (await seeded_db.execute(select(SitePlanGoal))).scalars().all()
    assert [h.id for h in kalanlar] == [onceki.id]
    assert bu_hafta.id not in {h.id for h in kalanlar}


async def test_baska_haftanin_hedef_kimligi_422(
    client: AsyncClient,
    sef_headers: dict[str, str],
    seeded_db: AsyncSession,
    santiye,
    hedef_fabrikasi,
) -> None:
    """Kimlik kabul edilseydi hedef sessizce HAFTA DEĞİŞTİRİRDİ ve geçen haftanın
    listesinden kaybolurdu."""
    onceki = await hedef_fabrikasi(santiye, "Geçen hafta", week_start=ONCEKI_HAFTA, sort_order=1)

    yanit = await _kaydet(
        client, sef_headers, santiye.id, [_hedef("Taşınmış hedef", goal_id=onceki.id)]
    )
    assert yanit.status_code == 422, yanit.text
    assert yanit.json()["detail"] == guards.GOAL_UNKNOWN

    await seeded_db.refresh(onceki)
    assert onceki.week_start == ONCEKI_HAFTA
    assert onceki.title == "Geçen hafta"


# --- KAPSAM KANITI: şantiye ---


async def test_baska_santiyenin_hedefine_dokunmaz(
    client: AsyncClient,
    sef_headers: dict[str, str],
    seeded_db: AsyncSession,
    santiye,
    ikinci_santiye,
    hedef_fabrikasi,
) -> None:
    """İki şantiye AYNI projede ve AYNI haftadadır — kapsam gerçekten `site_id`
    ile sınırlanmalıdır."""
    komsu = await hedef_fabrikasi(ikinci_santiye, "Komşu hedef", sort_order=1)
    await hedef_fabrikasi(santiye, "Kendi hedefi", sort_order=1)

    yanit = await _kaydet(client, sef_headers, santiye.id, [])
    assert yanit.status_code == 200, yanit.text

    kalanlar = (await seeded_db.execute(select(SitePlanGoal))).scalars().all()
    assert [h.id for h in kalanlar] == [komsu.id]


async def test_baska_santiyenin_hedef_kimligi_422(
    client: AsyncClient, sef_headers: dict[str, str], santiye, ikinci_santiye, hedef_fabrikasi
) -> None:
    komsu = await hedef_fabrikasi(ikinci_santiye, "Komşu hedef", sort_order=1)

    yanit = await _kaydet(client, sef_headers, santiye.id, [_hedef("Çalınmış", goal_id=komsu.id)])
    assert yanit.status_code == 422, yanit.text
    assert yanit.json()["detail"] == guards.GOAL_UNKNOWN


async def test_ayni_kimlik_iki_kez_422(
    client: AsyncClient, sef_headers: dict[str, str], santiye, hedef_fabrikasi
) -> None:
    hedef = await hedef_fabrikasi(santiye, "Hedef", sort_order=1)

    yanit = await _kaydet(
        client,
        sef_headers,
        santiye.id,
        [_hedef("İlk", goal_id=hedef.id), _hedef("İkinci", goal_id=hedef.id)],
    )
    assert yanit.status_code == 422, yanit.text
    assert yanit.json()["detail"] == guards.DUPLICATE_GOAL


# --- Hafta korkuluğu / izin / kapsam ---


async def test_week_start_pazartesi_degilse_422(
    client: AsyncClient, sef_headers: dict[str, str], santiye
) -> None:
    yanit = await _kaydet(client, sef_headers, santiye.id, [], week_start=date(2026, 7, 21))
    assert yanit.status_code == 422, yanit.text
    assert yanit.json()["detail"] == guards.WEEK_START_NOT_MONDAY


async def test_goals_saha_muhendisi_yazabilir(
    client: AsyncClient, saha_muh_headers: dict[str, str], santiye
) -> None:
    yanit = await _kaydet(client, saha_muh_headers, santiye.id, [_hedef("Hedef")])
    assert yanit.status_code == 200, yanit.text


async def test_goals_pm_yazamaz_403(
    client: AsyncClient, pm_headers: dict[str, str], seeded_db: AsyncSession, santiye
) -> None:
    yanit = await _kaydet(client, pm_headers, santiye.id, [_hedef("Hedef")])
    assert yanit.status_code == 403, yanit.text
    assert (await seeded_db.execute(select(SitePlanGoal))).scalars().all() == []


async def test_goals_gorunmeyen_santiye_404(
    client: AsyncClient, sef_headers: dict[str, str], gorunmeyen_santiye
) -> None:
    yanit = await _kaydet(client, sef_headers, gorunmeyen_santiye.id, [])
    assert yanit.status_code == 404, yanit.text
    assert yanit.json()["detail"] == SITE_MISSING


async def test_goals_audit_tek_ozet_olayi(
    client: AsyncClient, sef_headers: dict[str, str], seeded_db: AsyncSession, santiye
) -> None:
    async def _bu_haftanin_kayitlari() -> list[AuditLog]:
        """🔴 KAPSAMLI + DETERMİNİSTİK SIRALI (TB-XDIST, 2026-08-25).

        Önceki hâli iki ayrı belirsizlik taşıyordu; ikisi de bu testi FLAKY yapıyordu
        (TB-LOCK turunda yerelde kırmızı verdi, CI'da tekrarlamadı):
          (a) `select(AuditLog)` **`ORDER BY`suz**du ve `kayitlar[-1]` alınıyordu —
              PostgreSQL sırasız bir `SELECT`i heap sırasında döndürür ve bu **garanti
              değildir**; satır güncellenip yer değiştirdiğinde ya da plan değiştiğinde
              "son kayıt" başka bir satır olur.
          (b) İddia **GLOBAL satır sayısı deltasıydı** — bu tabloya yazan HER kayıt,
              kimin ürettiğine bakılmaksızın iddiayı oynatır.
        Onarım: sorgu **bu testin haftasına** daraltılır ve `ORDER BY occurred_at, id`
        ile sabitlenir. Eşitlik bozucu ikincil anahtar (`id`) ŞARTTIR: `occurred_at`
        `now()` sunucu varsayılanından gelir ve aynı transaction içinde SABİTTİR
        (WORKFLOW §4 "davranış testi sıralama kararını bekçileyemez").
        Şantiye adı KAPSAMA GİRMEZ — aşağıdaki `"A-Blok Şantiyesi" in detay` iddiası
        böylece kendini doğrulamayan gerçek bir iddia olarak kalır.
        """
        stmt = (
            select(AuditLog)
            .where(AuditLog.detail.contains(HAFTA.isoformat()))
            .order_by(AuditLog.occurred_at, AuditLog.id)
        )
        return list((await seeded_db.execute(stmt)).scalars().all())

    onceki = len(await _bu_haftanin_kayitlari())

    yanit = await _kaydet(client, sef_headers, santiye.id, [_hedef("A"), _hedef("B")])
    assert yanit.status_code == 200, yanit.text

    kayitlar = await _bu_haftanin_kayitlari()
    assert len(kayitlar) == onceki + 1, (
        f"{HAFTA.isoformat()} haftası için TEK özet olayı beklenirdi: {onceki} → {len(kayitlar)}"
    )
    detay = kayitlar[-1].detail
    assert "A-Blok Şantiyesi" in detay
    assert HAFTA.isoformat() in detay
    assert "2 hedef" in detay


# --- Sprint ---


async def _sprint_kaydet(client: AsyncClient, headers: dict[str, str], site_id, name: str | None):
    return await client.put(sprint_url(site_id), headers=headers, json={"name": name})


async def test_sprint_olusturur(client: AsyncClient, sef_headers: dict[str, str], santiye) -> None:
    yanit = await _sprint_kaydet(client, sef_headers, santiye.id, "Kat 8–9 Tamamlama")
    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["name"] == "Kat 8–9 Tamamlama"


async def test_sprint_yeniden_adlandirir_ve_tek_aktif_kalir(
    client: AsyncClient,
    sef_headers: dict[str, str],
    seeded_db: AsyncSession,
    santiye,
    sprint_fabrikasi,
) -> None:
    """Kısmi UQ (site_id) WHERE is_active: ikinci kaydetme YENİ aktif satır AÇMAZ,
    mevcudu günceller — açsaydı DB kısıtı patlardı."""
    mevcut = await sprint_fabrikasi(santiye, "Kat 6–7 Tamamlama")

    yanit = await _sprint_kaydet(client, sef_headers, santiye.id, "Kat 8–9 Tamamlama")
    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["id"] == str(mevcut.id)

    aktifler = (
        (await seeded_db.execute(select(SitePlanSprint).where(SitePlanSprint.is_active.is_(True))))
        .scalars()
        .all()
    )
    assert [s.name for s in aktifler] == ["Kat 8–9 Tamamlama"]


async def test_bos_ad_aktif_sprinti_kapatir(
    client: AsyncClient,
    sef_headers: dict[str, str],
    seeded_db: AsyncSession,
    santiye,
    sprint_fabrikasi,
) -> None:
    """`null`/boş ad = sprint şeridi YOK (P107 boş). Kayıt SİLİNMEZ, pasife
    çekilir — geçmiş sprintin denetim izi korunur."""
    mevcut = await sprint_fabrikasi(santiye, "Kat 6–7 Tamamlama")

    yanit = await _sprint_kaydet(client, sef_headers, santiye.id, None)
    assert yanit.status_code == 200, yanit.text
    assert yanit.json() is None

    await seeded_db.refresh(mevcut)
    assert mevcut.is_active is False


async def test_bos_ad_sprint_yokken_de_calisir(
    client: AsyncClient, sef_headers: dict[str, str], santiye
) -> None:
    yanit = await _sprint_kaydet(client, sef_headers, santiye.id, "   ")
    assert yanit.status_code == 200, yanit.text
    assert yanit.json() is None


async def test_pasif_sprint_yeniden_aktif_edilmez_yeni_acilir(
    client: AsyncClient,
    sef_headers: dict[str, str],
    seeded_db: AsyncSession,
    santiye,
    sprint_fabrikasi,
) -> None:
    pasif = await sprint_fabrikasi(santiye, "Eski Sprint", is_active=False)

    yanit = await _sprint_kaydet(client, sef_headers, santiye.id, "Yeni Sprint")
    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["id"] != str(pasif.id)

    await seeded_db.refresh(pasif)
    assert pasif.is_active is False


async def test_sprint_baska_santiyeye_dokunmaz(
    client: AsyncClient,
    sef_headers: dict[str, str],
    seeded_db: AsyncSession,
    santiye,
    ikinci_santiye,
    sprint_fabrikasi,
) -> None:
    komsu = await sprint_fabrikasi(ikinci_santiye, "Komşu Sprint")

    yanit = await _sprint_kaydet(client, sef_headers, santiye.id, None)
    assert yanit.status_code == 200, yanit.text

    await seeded_db.refresh(komsu)
    assert komsu.is_active is True
    assert komsu.name == "Komşu Sprint"


async def test_sprint_pm_yazamaz_403(
    client: AsyncClient, pm_headers: dict[str, str], seeded_db: AsyncSession, santiye
) -> None:
    yanit = await _sprint_kaydet(client, pm_headers, santiye.id, "Sızıntı")
    assert yanit.status_code == 403, yanit.text
    assert (await seeded_db.execute(select(SitePlanSprint))).scalars().all() == []


async def test_sprint_gorunmeyen_santiye_404(
    client: AsyncClient, sef_headers: dict[str, str], gorunmeyen_santiye
) -> None:
    yanit = await _sprint_kaydet(client, sef_headers, gorunmeyen_santiye.id, "Sızıntı")
    assert yanit.status_code == 404, yanit.text
    assert yanit.json()["detail"] == SITE_MISSING


async def test_sprint_audit_yazilir(
    client: AsyncClient, sef_headers: dict[str, str], seeded_db: AsyncSession, santiye
) -> None:
    onceki = len((await seeded_db.execute(select(AuditLog))).scalars().all())

    yanit = await _sprint_kaydet(client, sef_headers, santiye.id, "Kat 8–9 Tamamlama")
    assert yanit.status_code == 200, yanit.text

    kayitlar = (await seeded_db.execute(select(AuditLog))).scalars().all()
    assert len(kayitlar) == onceki + 1
    assert "Kat 8–9 Tamamlama" in kayitlar[-1].detail
