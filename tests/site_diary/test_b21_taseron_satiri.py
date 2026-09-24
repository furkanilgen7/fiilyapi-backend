"""PLN-B2.1 (B2-5) — günlük işçi kırılımında TAŞERON FİRMA satırı.

* `subcontractor_id` + `hours` (kişi başı saat, 0 < h ≤ 24) opsiyonel EK alanlar.
* Firma satırı firma başına TEKİLDİR; kaynak `subcontractor` olmak zorundadır.
* Firmasız satırların eski (`trade`, `source`) kimliği ve tekilliği AYNEN korunur.
"""

import uuid
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.contracts import guards as contracts_guards
from app.modules.contracts.models import Subcontractor
from app.modules.site_diary import guards
from app.modules.site_diary.models import SiteDiaryEntry, SiteDiaryWorkerCount, WorkerSource
from tests.site_diary.conftest import VARSAYILAN_TARIH

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def firmalar(seeded_db: AsyncSession) -> tuple[Subcontractor, Subcontractor]:
    kaya = Subcontractor(name="Kaya Duvar")
    deniz = Subcontractor(name="Deniz Tesisat")
    seeded_db.add_all([kaya, deniz])
    await seeded_db.flush()
    return kaya, deniz


async def _kayit(client: AsyncClient, headers, site_id) -> str:
    yanit = await client.post(
        f"/sites/{site_id}/diary",
        json={"entry_date": VARSAYILAN_TARIH.isoformat()},
        headers=headers,
    )
    assert yanit.status_code == 201, yanit.text
    return yanit.json()["id"]


async def _isciler(client: AsyncClient, headers, entry_id, satirlar: list[dict]):
    return await client.patch(
        f"/diary/{entry_id}", json={"worker_counts": satirlar}, headers=headers
    )


def _firma(sub: Subcontractor, count: int, hours: str | None = "9", trade: str = "Duvarcı"):
    satir = {
        "trade": trade,
        "source": "subcontractor",
        "count": count,
        "subcontractor_id": str(sub.id),
    }
    if hours is not None:
        satir["hours"] = hours
    return satir


async def test_firma_satiri_yazilir_ve_okunur(
    client: AsyncClient, admin_headers, santiye, firmalar
) -> None:
    site, _, _ = santiye
    kaya, deniz = firmalar
    entry_id = await _kayit(client, admin_headers, site.id)

    yanit = await _isciler(
        client,
        admin_headers,
        entry_id,
        [_firma(kaya, 6, "9"), _firma(deniz, 4, "8.5", trade="Tesisatçı")],
    )

    assert yanit.status_code == 200, yanit.text
    satirlar = {s["subcontractor_id"]: s for s in yanit.json()["worker_counts"]}
    assert (satirlar[str(kaya.id)]["count"], Decimal(satirlar[str(kaya.id)]["hours"])) == (
        6,
        Decimal("9"),
    )
    assert Decimal(satirlar[str(deniz.id)]["hours"]) == Decimal("8.5")
    assert yanit.json()["worker_total"] == 10


async def test_ayni_meslek_iki_firmada_ve_eski_satirla_birlikte_mesru(
    client: AsyncClient, admin_headers, santiye, firmalar
) -> None:
    """Firma satırı eski (meslek, kaynak) tekilliğine GİRMEZ: aynı "Duvarcı ·
    taşeron" üç satırda (iki firma + firmasız) meşrudur."""
    site, _, _ = santiye
    kaya, deniz = firmalar
    entry_id = await _kayit(client, admin_headers, site.id)

    yanit = await _isciler(
        client,
        admin_headers,
        entry_id,
        [
            _firma(kaya, 2),
            _firma(deniz, 3),
            {"trade": "Duvarcı", "source": "subcontractor", "count": 1},
        ],
    )

    assert yanit.status_code == 200, yanit.text
    assert len(yanit.json()["worker_counts"]) == 3


async def test_ESKI_GOVDE_firmasiz_satir_aynen_ve_eski_tekillik_korunur(
    client: AsyncClient, admin_headers, santiye
) -> None:
    site, _, _ = santiye
    entry_id = await _kayit(client, admin_headers, site.id)

    tamam = await _isciler(
        client, admin_headers, entry_id, [{"trade": "Kalıpçı", "source": "company", "count": 4}]
    )
    cift = await _isciler(
        client,
        admin_headers,
        entry_id,
        [
            {"trade": "Kalıpçı", "source": "company", "count": 4},
            {"trade": "Kalıpçı", "source": "company", "count": 2},
        ],
    )

    assert tamam.status_code == 200, tamam.text
    (satir,) = tamam.json()["worker_counts"]
    assert (satir["subcontractor_id"], satir["hours"]) == (None, None)
    assert cift.status_code == 409, cift.text
    assert cift.json()["detail"] == guards.DUPLICATE_WORKER_COUNT


async def test_ayni_firma_iki_kez_409(
    client: AsyncClient, admin_headers, santiye, firmalar
) -> None:
    site, _, _ = santiye
    kaya, _ = firmalar
    entry_id = await _kayit(client, admin_headers, site.id)

    yanit = await _isciler(
        client, admin_headers, entry_id, [_firma(kaya, 2), _firma(kaya, 3, trade="Sıvacı")]
    )

    assert yanit.status_code == 409, yanit.text
    assert yanit.json()["detail"] == guards.DUPLICATE_WORKER_SUBCONTRACTOR


async def test_olmayan_firma_422(client: AsyncClient, admin_headers, santiye) -> None:
    site, _, _ = santiye
    entry_id = await _kayit(client, admin_headers, site.id)
    sahte = Subcontractor(name="x")
    sahte.id = uuid.uuid4()

    yanit = await _isciler(client, admin_headers, entry_id, [_firma(sahte, 2)])

    assert yanit.status_code == 422, yanit.text
    assert yanit.json()["detail"] == guards.WORKER_SUBCONTRACTOR_UNKNOWN


async def test_firma_yalniz_taseron_kaynagiyla_422(
    client: AsyncClient, admin_headers, santiye, firmalar
) -> None:
    site, _, _ = santiye
    kaya, _ = firmalar
    entry_id = await _kayit(client, admin_headers, site.id)

    yanit = await _isciler(
        client, admin_headers, entry_id, [{**_firma(kaya, 2), "source": "company"}]
    )

    assert yanit.status_code == 422, yanit.text
    assert guards.WORKER_SUBCONTRACTOR_SOURCE in yanit.text


@pytest.mark.parametrize("saat", ["0", "-1", "24.5", "8.25"])
async def test_saat_sinir_disi_422(
    client: AsyncClient, admin_headers, santiye, firmalar, saat: str
) -> None:
    site, _, _ = santiye
    kaya, _ = firmalar
    entry_id = await _kayit(client, admin_headers, site.id)

    yanit = await _isciler(client, admin_headers, entry_id, [_firma(kaya, 2, saat)])

    assert yanit.status_code == 422, yanit.text


async def test_firma_satiri_guncellenir_kimligi_korunur(
    client: AsyncClient, admin_headers, santiye, firmalar
) -> None:
    site, _, _ = santiye
    kaya, _ = firmalar
    entry_id = await _kayit(client, admin_headers, site.id)
    ilk = await _isciler(client, admin_headers, entry_id, [_firma(kaya, 2, "9")])

    ikinci = await _isciler(client, admin_headers, entry_id, [_firma(kaya, 5, "10", "Sıvacı")])

    assert ikinci.status_code == 200, ikinci.text
    (once,), (sonra,) = ilk.json()["worker_counts"], ikinci.json()["worker_counts"]
    assert once["id"] == sonra["id"]
    assert (sonra["count"], Decimal(sonra["hours"]), sonra["trade"]) == (5, Decimal("10"), "Sıvacı")


async def test_DB_firma_basina_tekil_kismi_indeks(
    seeded_db: AsyncSession, santiye, firmalar, admin_kullanicisi
) -> None:
    site, _, _ = santiye
    kaya, _ = firmalar
    entry = SiteDiaryEntry(
        site_id=site.id,
        project_id=site.project_id,
        entry_date=VARSAYILAN_TARIH,
        created_by=admin_kullanicisi.id,
    )
    seeded_db.add(entry)
    await seeded_db.flush()

    def _satir(trade: str) -> SiteDiaryWorkerCount:
        return SiteDiaryWorkerCount(
            entry_id=entry.id,
            trade=trade,
            source=WorkerSource.subcontractor,
            count=1,
            subcontractor_id=kaya.id,
        )

    seeded_db.add(_satir("Duvarcı"))
    await seeded_db.flush()
    with pytest.raises(IntegrityError):
        async with seeded_db.begin_nested():
            seeded_db.add(_satir("Sıvacı"))
            await seeded_db.flush()


# --- PLN-B2.11: taşeron silme korkuluğu ---


async def test_gunlukte_firma_satiri_olan_taseron_silinemez_409_metin(
    client: AsyncClient, admin_headers, santiye, firmalar, seeded_db: AsyncSession
) -> None:
    site, _, _ = santiye
    kaya, deniz = firmalar
    entry_id = await _kayit(client, admin_headers, site.id)
    assert (await _isciler(client, admin_headers, entry_id, [_firma(kaya, 2)])).is_success

    yanit = await client.delete(f"/subcontractors/{kaya.id}", headers=admin_headers)

    assert yanit.status_code == 409, yanit.text
    assert yanit.json()["detail"] == (
        "Taşeronun 1 günlükte 1 işçi satırı var (ilk: 15.07.2026); silinemez"
    )
    assert yanit.json()["detail"] == contracts_guards.subcontractor_has_diary_rows(
        1, 1, VARSAYILAN_TARIH
    )
    assert await seeded_db.get(Subcontractor, kaya.id) is not None


async def test_gunluk_satiri_olmayan_taseron_bugunku_gibi_silinir(
    client: AsyncClient, admin_headers, santiye, firmalar
) -> None:
    site, _, _ = santiye
    kaya, deniz = firmalar
    entry_id = await _kayit(client, admin_headers, site.id)
    assert (await _isciler(client, admin_headers, entry_id, [_firma(kaya, 2)])).is_success

    yanit = await client.delete(f"/subcontractors/{deniz.id}", headers=admin_headers)

    assert yanit.status_code == 204, yanit.text
