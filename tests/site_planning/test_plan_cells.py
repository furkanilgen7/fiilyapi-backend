"""T3 — `PUT /sites/{site_id}/plan/cells?week_start=` (planlama spec §3).

**Bu dosyanın en kritik testleri kapsam kanıtlarıdır** (PT `PUT` deseni): bir
haftanın kaydetmesi komşu HAFTANIN ya da komşu ŞANTİYENİN hücrelerini süpürürse
geri alınamaz veri kaybı doğar. İkisi AYRI AYRI kanıtlanır — tek testte
kanıtlansaydı, koşulun hangi parçasının düştüğü anlaşılmazdı.

Ayrıca: hafta korkuluğu (Pazartesi şartı) kapsam kararından ÖNCE koşar · boş
metin hücreyi YOK SAYAR ("hücre yokluğu = plan yok", spec §2) · gövde-içi çift
422 · satır sahipliği 422 · PM 403.
"""

import uuid
from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditLog
from app.modules.site_planning import guards
from app.modules.site_planning.models import SitePlanCell
from app.modules.sites.guards import SITE_MISSING
from tests.site_planning.conftest import HAFTA, ONCEKI_HAFTA, cells_url, gun

pytestmark = pytest.mark.asyncio


def _hucre(row_id, offset: int, text: str, *, tag: str | None = None) -> dict:
    return {"row_id": str(row_id), "plan_date": gun(offset).isoformat(), "text": text, "tag": tag}


async def _kaydet(
    client: AsyncClient,
    headers: dict[str, str],
    site_id,
    cells: list[dict],
    week_start: date = HAFTA,
):
    return await client.put(cells_url(site_id, week_start), headers=headers, json={"cells": cells})


# --- DEĞİŞTİRME semantiği ---


async def test_cells_ekler_gunceller_ve_siler(
    client: AsyncClient,
    sef_headers: dict[str, str],
    seeded_db: AsyncSession,
    santiye,
    bolum,
    satir_fabrikasi,
    hucre_fabrikasi,
) -> None:
    """Gövde hafta+şantiye kapsamının TAM kümesidir: geçmeyen hücre SİLİNİR."""
    satir = await satir_fabrikasi(santiye, "Kalıpçı", section=bolum, sort_order=1)
    guncellenecek = await hucre_fabrikasi(satir, gun(0), "Eski metin")
    await hucre_fabrikasi(satir, gun(4), "Silinecek")

    yanit = await _kaydet(
        client,
        sef_headers,
        santiye.id,
        [_hucre(satir.id, 0, "Kat 9 Kalıp", tag="blue"), _hucre(satir.id, 2, "Döşeme Dök.")],
    )
    assert yanit.status_code == 200, yanit.text

    (grup,) = yanit.json()["groups"]
    (satir_yanit,) = grup["rows"]
    assert [(h["plan_date"], h["text"]) for h in satir_yanit["cells"]] == [
        (gun(0).isoformat(), "Kat 9 Kalıp"),
        (gun(2).isoformat(), "Döşeme Dök."),
    ]
    assert satir_yanit["cells"][0]["tag"] == "blue"

    # Mevcut hücrenin KİMLİĞİ korunur (sil + yeniden yaz DEĞİL).
    await seeded_db.refresh(guncellenecek)
    assert guncellenecek.text == "Kat 9 Kalıp"


async def test_gonderilmeyen_tag_null_a_duser(
    client: AsyncClient,
    sef_headers: dict[str, str],
    seeded_db: AsyncSession,
    santiye,
    satir_fabrikasi,
    hucre_fabrikasi,
) -> None:
    """Hücre gövdedeki hâline EŞİTLENİR; eski renk sessizce kalmaz."""
    from app.modules.site_planning.models import PlanCellTag

    satir = await satir_fabrikasi(santiye, "Kalıpçı", sort_order=1)
    hucre = await hucre_fabrikasi(satir, gun(0), "Kat 9 Kalıp", tag=PlanCellTag.blue)

    yanit = await _kaydet(client, sef_headers, santiye.id, [_hucre(satir.id, 0, "Kat 9 Kalıp")])
    assert yanit.status_code == 200, yanit.text
    await seeded_db.refresh(hucre)
    assert hucre.tag is None


# --- KAPSAM KANITI 1: hafta ---


async def test_baska_haftanin_hucresine_dokunmaz(
    client: AsyncClient,
    sef_headers: dict[str, str],
    seeded_db: AsyncSession,
    santiye,
    satir_fabrikasi,
    hucre_fabrikasi,
) -> None:
    """⚠️ Silme koşulunun HAFTA parçası. Aynı satırın önceki/sonraki haftadaki
    hücreleri boş bir kaydetmede bile AYAKTA kalmalıdır."""
    satir = await satir_fabrikasi(santiye, "Kalıpçı", sort_order=1)
    onceki = await hucre_fabrikasi(satir, gun(-1), "Önceki hafta Paz")
    bu_hafta = await hucre_fabrikasi(satir, gun(3), "Bu hafta Per")
    sonraki = await hucre_fabrikasi(satir, gun(7), "Sonraki hafta Pzt")

    yanit = await _kaydet(client, sef_headers, santiye.id, [])
    assert yanit.status_code == 200, yanit.text

    kalanlar = (await seeded_db.execute(select(SitePlanCell))).scalars().all()
    assert {h.id for h in kalanlar} == {onceki.id, sonraki.id}
    assert bu_hafta.id not in {h.id for h in kalanlar}


# --- KAPSAM KANITI 2: şantiye ---


async def test_baska_santiyenin_hucresine_dokunmaz(
    client: AsyncClient,
    sef_headers: dict[str, str],
    seeded_db: AsyncSession,
    santiye,
    ikinci_santiye,
    satir_fabrikasi,
    hucre_fabrikasi,
) -> None:
    """⚠️ Silme koşulunun ŞANTİYE parçası — hücrede `site_id` kolonu YOKTUR,
    koşul satır üzerinden kurulur. İki şantiye AYNI projede ve AYNI haftadadır:
    kapsam `visible_projects`in ya da haftanın yan etkisiyle DEĞİL gerçekten
    `site_id` ile sınırlanmalıdır."""
    kendi = await satir_fabrikasi(santiye, "Kalıpçı", sort_order=1)
    komsu_satir = await satir_fabrikasi(ikinci_santiye, "Komşu Ekip", sort_order=1)
    kendi_hucre = await hucre_fabrikasi(kendi, gun(0), "Kat 9 Kalıp")
    komsu_hucre = await hucre_fabrikasi(komsu_satir, gun(0), "Komşu iş")

    yanit = await _kaydet(client, sef_headers, santiye.id, [])
    assert yanit.status_code == 200, yanit.text

    kalanlar = (await seeded_db.execute(select(SitePlanCell))).scalars().all()
    assert [h.id for h in kalanlar] == [komsu_hucre.id]
    assert kendi_hucre.id not in {h.id for h in kalanlar}


async def test_baska_santiyenin_satirina_yazilamaz_422(
    client: AsyncClient,
    sef_headers: dict[str, str],
    seeded_db: AsyncSession,
    santiye,
    ikinci_santiye,
    satir_fabrikasi,
) -> None:
    """Komşunun satırına hücre yazılabilseydi kapsam sınırı gövdeden AŞILIRDI."""
    komsu = await satir_fabrikasi(ikinci_santiye, "Komşu Ekip", sort_order=1)

    yanit = await _kaydet(client, sef_headers, santiye.id, [_hucre(komsu.id, 0, "Sızıntı")])
    assert yanit.status_code == 422, yanit.text
    assert yanit.json()["detail"] == guards.ROW_UNKNOWN
    assert (await seeded_db.execute(select(SitePlanCell))).scalars().all() == []


async def test_var_olmayan_satira_yazilamaz_422(
    client: AsyncClient, sef_headers: dict[str, str], santiye
) -> None:
    yanit = await _kaydet(client, sef_headers, santiye.id, [_hucre(uuid.uuid4(), 0, "Hayalet")])
    assert yanit.status_code == 422, yanit.text
    assert yanit.json()["detail"] == guards.ROW_UNKNOWN


# --- Hafta korkuluğu ---


@pytest.mark.parametrize("tarih", [date(2026, 7, 21), date(2026, 7, 25)])
async def test_week_start_pazartesi_degilse_422(
    client: AsyncClient, sef_headers: dict[str, str], santiye, tarih: date
) -> None:
    """Kaydırılmış bir hafta, kullanıcının GÖRMEDİĞİ bir haftayı DEĞİŞTİRME
    semantiğiyle süpürürdü (guards.WEEK_START_NOT_MONDAY)."""
    yanit = await _kaydet(client, sef_headers, santiye.id, [], week_start=tarih)
    assert yanit.status_code == 422, yanit.text
    assert yanit.json()["detail"] == guards.WEEK_START_NOT_MONDAY


async def test_hafta_korkulugu_kapsam_kararindan_once_kosar(
    client: AsyncClient, sef_headers: dict[str, str], gorunmeyen_santiye
) -> None:
    """Görünmeyen şantiye + Salı → 404 DEĞİL 422: cevap kaydın varlığından
    bağımsız kalır, bilgi sızmaz (T2 okuma ucundaki sıranın aynısı)."""
    yanit = await _kaydet(
        client, sef_headers, gorunmeyen_santiye.id, [], week_start=date(2026, 7, 21)
    )
    assert yanit.status_code == 422, yanit.text
    assert yanit.json()["detail"] == guards.WEEK_START_NOT_MONDAY


@pytest.mark.parametrize("offset", [-1, 7])
async def test_hafta_disi_hucre_422(
    client: AsyncClient,
    sef_headers: dict[str, str],
    seeded_db: AsyncSession,
    santiye,
    satir_fabrikasi,
    offset: int,
) -> None:
    """Kapsam dışına düşen hücre bir sonraki haftanın kaydetmesinde kimsenin fark
    etmeyeceği şekilde SİLİNİRDİ — 422 (puantajın dönem-dışı korkuluğu)."""
    satir = await satir_fabrikasi(santiye, "Kalıpçı", sort_order=1)

    yanit = await _kaydet(client, sef_headers, santiye.id, [_hucre(satir.id, offset, "Kaçak")])
    assert yanit.status_code == 422, yanit.text
    assert guards.CELL_OUT_OF_WEEK_PREFIX in yanit.json()["detail"]
    assert (await seeded_db.execute(select(SitePlanCell))).scalars().all() == []


# --- Boş metin: hücre yokluğu = plan yok ---


async def test_bos_metin_hucreyi_yok_sayar(
    client: AsyncClient,
    sef_headers: dict[str, str],
    seeded_db: AsyncSession,
    santiye,
    satir_fabrikasi,
    hucre_fabrikasi,
) -> None:
    """Spec §2: "hücre yokluğu = plan yok". Ekranın boşalttığı hücre için boş
    metinli bir SATIR YAZILMAZ — hücre silinir; aksi hâlde ızgarada anlamsız boş
    kayıtlar birikirdi ve "planlanmamış gün" ile "planı silinmiş gün" ayırt
    edilemezdi."""
    satir = await satir_fabrikasi(santiye, "Kalıpçı", sort_order=1)
    await hucre_fabrikasi(satir, gun(0), "Eski plan")

    yanit = await _kaydet(
        client,
        sef_headers,
        santiye.id,
        [_hucre(satir.id, 0, "   "), _hucre(satir.id, 1, "Kat 9 Kalıp")],
    )
    assert yanit.status_code == 200, yanit.text

    kalanlar = (await seeded_db.execute(select(SitePlanCell))).scalars().all()
    assert [(h.plan_date, h.text) for h in kalanlar] == [(gun(1), "Kat 9 Kalıp")]


async def test_metin_kirpilir(
    client: AsyncClient,
    sef_headers: dict[str, str],
    seeded_db: AsyncSession,
    santiye,
    satir_fabrikasi,
) -> None:
    satir = await satir_fabrikasi(santiye, "Kalıpçı", sort_order=1)

    yanit = await _kaydet(client, sef_headers, santiye.id, [_hucre(satir.id, 0, "  Kat 9  ")])
    assert yanit.status_code == 200, yanit.text
    (hucre,) = (await seeded_db.execute(select(SitePlanCell))).scalars().all()
    assert hucre.text == "Kat 9"


# --- Gövde-içi çift ---


async def test_ayni_hucre_iki_kez_422(
    client: AsyncClient, sef_headers: dict[str, str], santiye, satir_fabrikasi
) -> None:
    """UQ (row_id, plan_date) ihlali DB'ye hiç gitmeden yakalanır."""
    satir = await satir_fabrikasi(santiye, "Kalıpçı", sort_order=1)

    yanit = await _kaydet(
        client,
        sef_headers,
        santiye.id,
        [_hucre(satir.id, 0, "İlk"), _hucre(satir.id, 0, "İkinci")],
    )
    assert yanit.status_code == 422, yanit.text
    assert yanit.json()["detail"] == guards.DUPLICATE_CELL


async def test_bos_metinli_cift_de_422(
    client: AsyncClient, sef_headers: dict[str, str], santiye, satir_fabrikasi
) -> None:
    """Çift kontrolü boş metinleri de KAPSAR: "sil" ile "yaz" aynı hücre için
    birlikte gönderilirse hangisinin kazanacağı belirsizdir."""
    satir = await satir_fabrikasi(santiye, "Kalıpçı", sort_order=1)

    yanit = await _kaydet(
        client, sef_headers, santiye.id, [_hucre(satir.id, 0, ""), _hucre(satir.id, 0, "Kat 9")]
    )
    assert yanit.status_code == 422, yanit.text
    assert yanit.json()["detail"] == guards.DUPLICATE_CELL


# --- Denetim ---


async def test_audit_tek_hafta_ozeti_olayi(
    client: AsyncClient,
    sef_headers: dict[str, str],
    seeded_db: AsyncSession,
    santiye,
    satir_fabrikasi,
) -> None:
    """Hücre başına olay basılmaz (7 gün × N satır denetim günlüğünü boğardı)."""
    satir = await satir_fabrikasi(santiye, "Kalıpçı", sort_order=1)
    onceki = len((await seeded_db.execute(select(AuditLog))).scalars().all())

    yanit = await _kaydet(
        client,
        sef_headers,
        santiye.id,
        [_hucre(satir.id, 0, "A"), _hucre(satir.id, 1, "B"), _hucre(satir.id, 2, "C")],
    )
    assert yanit.status_code == 200, yanit.text

    kayitlar = (await seeded_db.execute(select(AuditLog))).scalars().all()
    assert len(kayitlar) == onceki + 1
    detay = kayitlar[-1].detail
    assert "A-Blok Şantiyesi" in detay
    assert HAFTA.isoformat() in detay
    assert "3 hücre" in detay


# --- İzin ve kapsam ---


async def test_saha_muhendisi_yazabilir(
    client: AsyncClient, saha_muh_headers: dict[str, str], santiye
) -> None:
    yanit = await _kaydet(client, saha_muh_headers, santiye.id, [])
    assert yanit.status_code == 200, yanit.text


async def test_pm_yazamaz_403(
    client: AsyncClient,
    pm_headers: dict[str, str],
    seeded_db: AsyncSession,
    santiye,
    satir_fabrikasi,
    hucre_fabrikasi,
) -> None:
    satir = await satir_fabrikasi(santiye, "Kalıpçı", sort_order=1)
    hucre = await hucre_fabrikasi(satir, gun(0), "Kat 9 Kalıp")

    yanit = await _kaydet(client, pm_headers, santiye.id, [])
    assert yanit.status_code == 403, yanit.text
    assert (await seeded_db.execute(select(SitePlanCell))).scalars().all() == [hucre]


async def test_izin_yoksa_403(client: AsyncClient, ik_headers: dict[str, str], santiye) -> None:
    yanit = await _kaydet(client, ik_headers, santiye.id, [])
    assert yanit.status_code == 403, yanit.text


async def test_gorunmeyen_santiye_404(
    client: AsyncClient, sef_headers: dict[str, str], gorunmeyen_santiye
) -> None:
    yanit = await _kaydet(client, sef_headers, gorunmeyen_santiye.id, [])
    assert yanit.status_code == 404, yanit.text
    assert yanit.json()["detail"] == SITE_MISSING


async def test_onceki_haftaya_yazmak_bu_haftayi_bozmaz(
    client: AsyncClient,
    sef_headers: dict[str, str],
    seeded_db: AsyncSession,
    santiye,
    satir_fabrikasi,
    hucre_fabrikasi,
) -> None:
    """Kapsam kanıtının ters yönü: ÖNCEKİ haftayı kaydetmek BU haftaya dokunmaz."""
    satir = await satir_fabrikasi(santiye, "Kalıpçı", sort_order=1)
    bu_hafta = await hucre_fabrikasi(satir, gun(0), "Bu hafta Pzt")

    yanit = await _kaydet(
        client,
        sef_headers,
        santiye.id,
        [
            {
                "row_id": str(satir.id),
                "plan_date": ONCEKI_HAFTA.isoformat(),
                "text": "Geçen hafta Pzt",
                "tag": None,
            }
        ],
        week_start=ONCEKI_HAFTA,
    )
    assert yanit.status_code == 200, yanit.text

    kalanlar = (await seeded_db.execute(select(SitePlanCell))).scalars().all()
    assert {h.text for h in kalanlar} == {"Bu hafta Pzt", "Geçen hafta Pzt"}
    assert bu_hafta.id in {h.id for h in kalanlar}
