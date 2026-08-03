"""T3 — `PUT /sites/{site_id}/plan/rows` (planlama spec §3).

Kanıtlanan beş şey:
1. **DEĞİŞTİRME semantiği** — gövdede olmayan satır SİLİNİR, `id` verilen satır
   KİMLİĞİNİ KORUYARAK güncellenir, `id`siz satır eklenir.
2. **CASCADE** — silinen satırın hücreleri de gider (FK `ondelete="CASCADE"`).
3. **Kapsam kanıtı** — kaydetme BAŞKA şantiyenin satırlarına DOKUNMAZ ve başka
   şantiyenin satır kimliği gövdeye yazılamaz.
4. **T1'den devredilen sınır** — UQ (site_id, kind, section_id, label) Postgres'te
   `section_id IS NULL` dalında ÇALIŞMAZ (NULL'lar çakışmaz); tekillik uygulama
   katmanında doğrulanır ve ekipman satırlarında da 422 verir.
5. **İki katmanlı koruma** — PM (`site_diary=_V`) yazamaz (403), görünmeyen
   projenin şantiyesi 404.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditLog
from app.modules.site_planning import guards
from app.modules.site_planning.models import PlanResourceKind, SitePlanCell, SitePlanRow
from app.modules.sites.guards import SITE_MISSING
from tests.site_planning.conftest import gun, plan_url, rows_url

pytestmark = pytest.mark.asyncio


def _satir(
    label: str,
    *,
    row_id: uuid.UUID | None = None,
    kind: str = "crew",
    section_id: uuid.UUID | None = None,
    planned_worker_count: int | None = None,
    sort_order: int = 0,
) -> dict:
    return {
        "id": str(row_id) if row_id is not None else None,
        "kind": kind,
        "section_id": str(section_id) if section_id is not None else None,
        "label": label,
        "planned_worker_count": planned_worker_count,
        "sort_order": sort_order,
    }


async def _kaydet(client: AsyncClient, headers: dict[str, str], site_id, rows: list[dict]):
    return await client.put(rows_url(site_id), headers=headers, json={"rows": rows})


# --- DEĞİŞTİRME semantiği ---


async def test_rows_ekler_gunceller_ve_siler(
    client: AsyncClient,
    sef_headers: dict[str, str],
    seeded_db: AsyncSession,
    santiye,
    bolum,
    satir_fabrikasi,
) -> None:
    """Gövde şantiyenin satır kümesinin TAMAMIDIR: geçmeyen satır silinir."""
    kalan = await satir_fabrikasi(santiye, "Kalıpçı", section=bolum, sort_order=1)
    silinecek = await satir_fabrikasi(santiye, "Demirci", section=bolum, sort_order=2)

    yanit = await _kaydet(
        client,
        sef_headers,
        santiye.id,
        [
            _satir(
                "Kalıpçı Ekibi",
                row_id=kalan.id,
                section_id=bolum.id,
                planned_worker_count=14,
                sort_order=1,
            ),
            _satir("Tower Crane", kind="equipment", sort_order=1),
        ],
    )
    assert yanit.status_code == 200, yanit.text
    assert [s["label"] for s in yanit.json()["rows"]] == ["Kalıpçı Ekibi", "Tower Crane"]

    # Mevcut satırın KİMLİĞİ korunur — hücreleri sil+yeniden yaz ile kaybolmaz.
    korunan = next(s for s in yanit.json()["rows"] if s["label"] == "Kalıpçı Ekibi")
    assert korunan["id"] == str(kalan.id)
    assert korunan["planned_worker_count"] == 14

    kalanlar = (await seeded_db.execute(select(SitePlanRow))).scalars().all()
    assert {s.label for s in kalanlar} == {"Kalıpçı Ekibi", "Tower Crane"}
    assert silinecek.id not in {s.id for s in kalanlar}


async def test_bos_govde_tum_satirlari_siler(
    client: AsyncClient,
    sef_headers: dict[str, str],
    seeded_db: AsyncSession,
    santiye,
    satir_fabrikasi,
) -> None:
    await satir_fabrikasi(santiye, "Kalıpçı", sort_order=1)

    yanit = await _kaydet(client, sef_headers, santiye.id, [])
    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["rows"] == []
    assert (await seeded_db.execute(select(SitePlanRow))).scalars().all() == []


# --- CASCADE ---


async def test_silinen_satirin_hucreleri_cascade_gider(
    client: AsyncClient,
    sef_headers: dict[str, str],
    seeded_db: AsyncSession,
    santiye,
    bolum,
    satir_fabrikasi,
    hucre_fabrikasi,
) -> None:
    """Satır silinince hücreleri de gider; DURAN satırın hücresi KALIR."""
    duran = await satir_fabrikasi(santiye, "Kalıpçı", section=bolum, sort_order=1)
    silinecek = await satir_fabrikasi(santiye, "Demirci", section=bolum, sort_order=2)
    await hucre_fabrikasi(duran, gun(0), "Kat 9 Kalıp")
    await hucre_fabrikasi(silinecek, gun(0), "Kolon Demir")
    await hucre_fabrikasi(silinecek, gun(3), "Perde Demir")

    yanit = await _kaydet(
        client,
        sef_headers,
        santiye.id,
        [_satir("Kalıpçı", row_id=duran.id, section_id=bolum.id, sort_order=1)],
    )
    assert yanit.status_code == 200, yanit.text

    hucreler = (await seeded_db.execute(select(SitePlanCell))).scalars().all()
    assert [h.text for h in hucreler] == ["Kat 9 Kalıp"]
    assert all(h.row_id == duran.id for h in hucreler)


# --- Kapsam kanıtı ---


async def test_rows_baska_santiyenin_satirini_silmez(
    client: AsyncClient,
    sef_headers: dict[str, str],
    seeded_db: AsyncSession,
    santiye,
    ikinci_santiye,
    satir_fabrikasi,
) -> None:
    """Silme koşulu `site_id`dir: iki şantiye AYNI projede olsa bile komşunun
    satırı DEĞİŞTİRME kapsamına girmez."""
    komsu = await satir_fabrikasi(ikinci_santiye, "Komşu Ekip", sort_order=1)
    await satir_fabrikasi(santiye, "Kalıpçı", sort_order=1)

    yanit = await _kaydet(client, sef_headers, santiye.id, [])
    assert yanit.status_code == 200, yanit.text

    kalanlar = (await seeded_db.execute(select(SitePlanRow))).scalars().all()
    assert [s.id for s in kalanlar] == [komsu.id]


async def test_baska_santiyenin_satir_kimligi_422(
    client: AsyncClient,
    sef_headers: dict[str, str],
    seeded_db: AsyncSession,
    santiye,
    ikinci_santiye,
    satir_fabrikasi,
) -> None:
    """Komşunun satır kimliği gövdeye yazılamaz — yazılabilseydi satır sessizce
    başka şantiyeye TAŞINIRDI."""
    komsu = await satir_fabrikasi(ikinci_santiye, "Komşu Ekip", sort_order=1)

    yanit = await _kaydet(
        client, sef_headers, santiye.id, [_satir("Kalıpçı", row_id=komsu.id, sort_order=1)]
    )
    assert yanit.status_code == 422, yanit.text
    assert yanit.json()["detail"] == guards.ROW_UNKNOWN

    taze = (
        await seeded_db.execute(select(SitePlanRow).where(SitePlanRow.id == komsu.id))
    ).scalar_one()
    assert taze.site_id == ikinci_santiye.id
    assert taze.label == "Komşu Ekip"


async def test_var_olmayan_satir_kimligi_422(
    client: AsyncClient, sef_headers: dict[str, str], santiye
) -> None:
    yanit = await _kaydet(client, sef_headers, santiye.id, [_satir("Kalıpçı", row_id=uuid.uuid4())])
    assert yanit.status_code == 422, yanit.text
    assert yanit.json()["detail"] == guards.ROW_UNKNOWN


# --- Tekillik (T1'den devredilen sınır) ---


async def test_yinelenen_ekip_satiri_422(
    client: AsyncClient, sef_headers: dict[str, str], santiye, bolum
) -> None:
    """Aynı bölümün aynı etiketli satırı iki kez açılmaz (UQ'nun kendisi)."""
    yanit = await _kaydet(
        client,
        sef_headers,
        santiye.id,
        [_satir("Kalıpçı", section_id=bolum.id), _satir("Kalıpçı", section_id=bolum.id)],
    )
    assert yanit.status_code == 422, yanit.text
    assert yanit.json()["detail"] == guards.DUPLICATE_ROW


async def test_yinelenen_ekipman_satiri_422(
    client: AsyncClient, sef_headers: dict[str, str], seeded_db: AsyncSession, santiye
) -> None:
    """⚠️ T1 sınırı: `section_id IS NULL` olan ekipman satırlarında Postgres UQ'su
    FİİLEN ÇALIŞMAZ (NULL'lar çakışmaz). Tekilliği bu uç doğrular — doğrulamasaydı
    ızgarada aynı vinç iki satır olurdu ve DB itiraz ETMEZDİ."""
    yanit = await _kaydet(
        client,
        sef_headers,
        santiye.id,
        [_satir("Tower Crane", kind="equipment"), _satir("Tower Crane", kind="equipment")],
    )
    assert yanit.status_code == 422, yanit.text
    assert yanit.json()["detail"] == guards.DUPLICATE_ROW
    assert (await seeded_db.execute(select(SitePlanRow))).scalars().all() == []


async def test_yinelenen_bolumsuz_ekip_satiri_422(
    client: AsyncClient, sef_headers: dict[str, str], santiye
) -> None:
    """Bölümsüz EKİP satırı da aynı NULL boşluğuna düşer."""
    yanit = await _kaydet(client, sef_headers, santiye.id, [_satir("Bölümsüz"), _satir("Bölümsüz")])
    assert yanit.status_code == 422, yanit.text
    assert yanit.json()["detail"] == guards.DUPLICATE_ROW


async def test_ayni_etiket_farkli_bolumde_serbest(
    client: AsyncClient, sef_headers: dict[str, str], santiye, bolum, ikinci_bolum
) -> None:
    """Tekillik ÜÇLÜ anahtardadır: aynı meslek iki bölümde ayrı satırdır."""
    yanit = await _kaydet(
        client,
        sef_headers,
        santiye.id,
        [_satir("Kalıpçı", section_id=bolum.id), _satir("Kalıpçı", section_id=ikinci_bolum.id)],
    )
    assert yanit.status_code == 200, yanit.text
    assert len(yanit.json()["rows"]) == 2


# --- Bölüm sahipliği ---


async def test_baska_santiyenin_bolumu_422(
    client: AsyncClient, sef_headers: dict[str, str], santiye, ikinci_santiye, seeded_db
) -> None:
    from app.modules.sites.models import Section

    yabanci = Section(site_id=ikinci_santiye.id, code="PB-X", name="Yabancı Bölüm")
    seeded_db.add(yabanci)
    await seeded_db.flush()

    yanit = await _kaydet(
        client, sef_headers, santiye.id, [_satir("Kalıpçı", section_id=yabanci.id)]
    )
    assert yanit.status_code == 422, yanit.text
    assert yanit.json()["detail"] == guards.SECTION_MISMATCH


async def test_ekipman_satirina_bolum_atanamaz_422(
    client: AsyncClient, sef_headers: dict[str, str], santiye, bolum
) -> None:
    """Spec §2: ekipman satırında `section_id` NULL'dur. Bölümlü bir ekipman
    satırı okuma tarafında AYRI bir grup açar ve "Makine & Ekipman" başlığını
    (P158) ikiye böler."""
    yanit = await _kaydet(
        client,
        sef_headers,
        santiye.id,
        [_satir("Tower Crane", kind="equipment", section_id=bolum.id)],
    )
    assert yanit.status_code == 422, yanit.text
    assert yanit.json()["detail"] == guards.EQUIPMENT_ROW_HAS_SECTION


# --- Okuma ucuyla tutarlılık ---


async def test_kaydedilen_satirlar_okuma_ucunda_gorunur(
    client: AsyncClient, sef_headers: dict[str, str], santiye, bolum
) -> None:
    yanit = await _kaydet(
        client,
        sef_headers,
        santiye.id,
        [
            _satir("Kalıpçı", section_id=bolum.id, planned_worker_count=14, sort_order=1),
            _satir("Tower Crane", kind="equipment", sort_order=1),
        ],
    )
    assert yanit.status_code == 200, yanit.text

    okuma = await client.get(plan_url(santiye.id), headers=sef_headers)
    assert okuma.status_code == 200, okuma.text
    gruplar = okuma.json()["groups"]
    assert [(g["kind"], g["section_name"]) for g in gruplar] == [
        ("crew", "Kat 6–10 Kaba"),
        ("equipment", None),
    ]


# --- Denetim ---


async def test_audit_tek_ozet_olayi(
    client: AsyncClient, sef_headers: dict[str, str], seeded_db: AsyncSession, santiye
) -> None:
    """Satır başına olay basılmaz: TEK özet satırı (spec §3)."""
    onceki = len((await seeded_db.execute(select(AuditLog))).scalars().all())

    yanit = await _kaydet(
        client,
        sef_headers,
        santiye.id,
        [_satir("Kalıpçı"), _satir("Demirci"), _satir("Tower Crane", kind="equipment")],
    )
    assert yanit.status_code == 200, yanit.text

    kayitlar = (await seeded_db.execute(select(AuditLog))).scalars().all()
    assert len(kayitlar) == onceki + 1
    detay = kayitlar[-1].detail
    assert "A-Blok Şantiyesi" in detay
    assert "3 satır" in detay


# --- İzin ve kapsam ---


async def test_saha_muhendisi_yazabilir(
    client: AsyncClient, saha_muh_headers: dict[str, str], santiye
) -> None:
    """`field_engineer` matriste `site_diary=_F` — planı O da doldurur."""
    yanit = await _kaydet(client, saha_muh_headers, santiye.id, [_satir("Kalıpçı")])
    assert yanit.status_code == 200, yanit.text


async def test_pm_yazamaz_403(
    client: AsyncClient, pm_headers: dict[str, str], seeded_db: AsyncSession, santiye
) -> None:
    """PM (`site_diary=_V`) planı OKUR ama YAZAMAZ (spec §6 S1)."""
    yanit = await _kaydet(client, pm_headers, santiye.id, [_satir("Kalıpçı")])
    assert yanit.status_code == 403, yanit.text
    assert (await seeded_db.execute(select(SitePlanRow))).scalars().all() == []


async def test_izin_yoksa_403(client: AsyncClient, ik_headers: dict[str, str], santiye) -> None:
    yanit = await _kaydet(client, ik_headers, santiye.id, [_satir("Kalıpçı")])
    assert yanit.status_code == 403, yanit.text


async def test_gorunmeyen_santiye_404(
    client: AsyncClient, sef_headers: dict[str, str], gorunmeyen_santiye
) -> None:
    yanit = await _kaydet(client, sef_headers, gorunmeyen_santiye.id, [_satir("Kalıpçı")])
    assert yanit.status_code == 404, yanit.text
    assert yanit.json()["detail"] == SITE_MISSING


async def test_var_olmayan_santiye_ayni_404(
    client: AsyncClient, sef_headers: dict[str, str]
) -> None:
    yanit = await _kaydet(client, sef_headers, uuid.uuid4(), [_satir("Kalıpçı")])
    assert yanit.status_code == 404, yanit.text
    assert yanit.json()["detail"] == SITE_MISSING


async def test_kind_gecersizse_422(
    client: AsyncClient, sef_headers: dict[str, str], santiye
) -> None:
    yanit = await _kaydet(client, sef_headers, santiye.id, [_satir("Kalıpçı", kind="robot")])
    assert yanit.status_code == 422, yanit.text


async def test_bilinmeyen_alan_reddedilir(
    client: AsyncClient, sef_headers: dict[str, str], santiye
) -> None:
    """`extra="forbid"`: kapsam alanı (`project_id`) gövdeden ASLA alınmaz."""
    govde = _satir("Kalıpçı")
    govde["project_id"] = str(uuid.uuid4())
    yanit = await _kaydet(client, sef_headers, santiye.id, [govde])
    assert yanit.status_code == 422, yanit.text


async def test_kind_degisimi_ayni_kimlikte_yazilir(
    client: AsyncClient,
    sef_headers: dict[str, str],
    seeded_db: AsyncSession,
    santiye,
    satir_fabrikasi,
) -> None:
    """`kind` de güncellenebilir bir ALANDIR (kimliğin parçası değil)."""
    satir = await satir_fabrikasi(santiye, "Tower Crane", sort_order=1)

    yanit = await _kaydet(
        client,
        sef_headers,
        santiye.id,
        [_satir("Tower Crane", row_id=satir.id, kind="equipment", sort_order=1)],
    )
    assert yanit.status_code == 200, yanit.text
    await seeded_db.refresh(satir)
    assert satir.kind is PlanResourceKind.equipment
