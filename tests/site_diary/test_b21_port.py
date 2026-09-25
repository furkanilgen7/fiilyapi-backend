"""PLN-B2.1 — günlük yazma yollarının iki PORTU (`app.core.day_hooks`).

* KİLİT (B2-6): oluştur · PATCH (başlık + işçi kırılımı) · `PUT …/lines` · submit ·
  reopen · delete — HEPSİ kilitli güne 409 (metin porttan gelir).
* GÖNDER (B2-3/4/8): `submit` DB'ye yazmadan önce ön-koşulları sorar → 422 +
  `reasons`; kayıt `draft` KALIR.
* Kayıt YOKKEN (modülsüz kurulum) bugünkü davranış aynen sürer.

🔴 `port` fikstürü portu boşaltır ve sonda ESKİ kaydı geri yükler (`_port.py`).
"""

from datetime import date, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.site_diary.models import DiaryStatus, SiteDiaryEntry
from tests.site_diary._port import KILIT_METNI
from tests.site_diary.conftest import VARSAYILAN_TARIH

pytestmark = pytest.mark.asyncio

_GUN = VARSAYILAN_TARIH


async def _olustur(client: AsyncClient, headers, site_id, tarih: date = _GUN):
    return await client.post(
        f"/sites/{site_id}/diary", json={"entry_date": tarih.isoformat()}, headers=headers
    )


async def _taslak(client: AsyncClient, headers, site_id, tarih: date = _GUN) -> dict:
    yanit = await _olustur(client, headers, site_id, tarih)
    assert yanit.status_code == 201, yanit.text
    return yanit.json()


async def _durum(session: AsyncSession, entry_id) -> DiaryStatus:
    entry = (
        await session.execute(
            select(SiteDiaryEntry)
            .where(SiteDiaryEntry.id == entry_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    return entry.status


# --- KİLİT portu: her yazma yolu ---


async def test_kilitli_gune_olusturma_409_metin_porttan(
    client: AsyncClient, admin_headers, santiye, port
) -> None:
    site, _, _ = santiye
    port.kilitle(site.id, _GUN)

    yanit = await _olustur(client, admin_headers, site.id)

    assert yanit.status_code == 409, yanit.text
    assert yanit.json()["detail"] == KILIT_METNI


async def test_kilitli_gunde_patch_409(client: AsyncClient, admin_headers, santiye, port) -> None:
    site, _, _ = santiye
    kayit = await _taslak(client, admin_headers, site.id)
    port.kilitle(site.id, _GUN)

    yanit = await client.patch(
        f"/diary/{kayit['id']}", json={"work_done": "x"}, headers=admin_headers
    )

    assert yanit.status_code == 409, yanit.text
    assert yanit.json()["detail"] == KILIT_METNI


async def test_kilitli_gunde_isci_kirilimi_409(
    client: AsyncClient, admin_headers, santiye, port
) -> None:
    site, _, _ = santiye
    kayit = await _taslak(client, admin_headers, site.id)
    port.kilitle(site.id, _GUN)

    yanit = await client.patch(
        f"/diary/{kayit['id']}",
        json={"worker_counts": [{"trade": "Kalıpçı", "source": "company", "count": 3}]},
        headers=admin_headers,
    )

    assert yanit.status_code == 409, yanit.text


async def test_kilitli_gune_tarih_tasimak_da_409(
    client: AsyncClient, admin_headers, santiye, port
) -> None:
    """Kaynak gün açık, HEDEF gün kilitli: kayıt kilitli güne taşınamaz."""
    site, _, _ = santiye
    kayit = await _taslak(client, admin_headers, site.id)
    hedef = _GUN + timedelta(days=1)
    port.kilitle(site.id, hedef)

    yanit = await client.patch(
        f"/diary/{kayit['id']}", json={"entry_date": hedef.isoformat()}, headers=admin_headers
    )

    assert yanit.status_code == 409, yanit.text
    assert {_GUN, hedef} <= port.sorulan_gunler()


async def test_kilitli_gunde_satir_kaydi_409(
    client: AsyncClient, admin_headers, santiye, port
) -> None:
    site, _, items = santiye
    kayit = await _taslak(client, admin_headers, site.id)
    port.kilitle(site.id, _GUN)

    yanit = await client.put(
        f"/diary/{kayit['id']}/lines",
        json={"lines": [{"boq_item_id": str(items[0].id), "quantity": "1"}]},
        headers=admin_headers,
    )

    assert yanit.status_code == 409, yanit.text


async def test_kilitli_gunde_submit_409_ve_draft_kalir(
    client: AsyncClient, admin_headers, santiye, port, seeded_db: AsyncSession
) -> None:
    site, _, _ = santiye
    kayit = await _taslak(client, admin_headers, site.id)
    port.kilitle(site.id, _GUN)

    yanit = await client.post(f"/diary/{kayit['id']}/submit", headers=admin_headers)

    assert yanit.status_code == 409, yanit.text
    assert await _durum(seeded_db, kayit["id"]) is DiaryStatus.draft


async def test_kilitli_gunde_reopen_409(
    client: AsyncClient, admin_headers, santiye, port, seeded_db: AsyncSession
) -> None:
    site, _, _ = santiye
    kayit = await _taslak(client, admin_headers, site.id)
    assert (await client.post(f"/diary/{kayit['id']}/submit", headers=admin_headers)).is_success
    port.kilitle(site.id, _GUN)

    yanit = await client.post(f"/diary/{kayit['id']}/reopen", headers=admin_headers)

    assert yanit.status_code == 409, yanit.text
    assert await _durum(seeded_db, kayit["id"]) is DiaryStatus.submitted


async def test_kilitli_gunde_silme_409(
    client: AsyncClient, admin_headers, santiye, port, seeded_db: AsyncSession
) -> None:
    site, _, _ = santiye
    kayit = await _taslak(client, admin_headers, site.id)
    port.kilitle(site.id, _GUN)

    yanit = await client.delete(f"/diary/{kayit['id']}", headers=admin_headers)

    assert yanit.status_code == 409, yanit.text
    assert await _durum(seeded_db, kayit["id"]) is DiaryStatus.draft


async def test_komsu_gunun_kilidi_bu_gunu_etkilemez(
    client: AsyncClient, admin_headers, santiye, port
) -> None:
    """Pozitif kontrol: port HER ŞEYİ reddeden bir port olsaydı yukarıdakiler de yeşildi."""
    site, _, _ = santiye
    port.kilitle(site.id, _GUN - timedelta(days=1))

    yanit = await _olustur(client, admin_headers, site.id)

    assert yanit.status_code == 201, yanit.text


# --- GÖNDER portu ---


async def test_gonder_engeli_422_reasons_ve_db_yazilmaz(
    client: AsyncClient, admin_headers, admin_kullanicisi, santiye, port, seeded_db: AsyncSession
) -> None:
    site, _, _ = santiye
    kayit = await _taslak(client, admin_headers, site.id)
    port.engelle("Hava eksik", "Dağıtılmamış saat gerekçesiz")

    yanit = await client.post(f"/diary/{kayit['id']}/submit", headers=admin_headers)

    assert yanit.status_code == 422, yanit.text
    assert yanit.json()["reasons"] == ["Hava eksik", "Dağıtılmamış saat gerekçesiz"]
    assert await _durum(seeded_db, kayit["id"]) is DiaryStatus.draft
    (ctx,) = port.gonder_baglamlari
    assert (str(ctx.entry_id), ctx.site_id, ctx.entry_date, ctx.actor_id) == (
        kayit["id"],
        site.id,
        _GUN,
        admin_kullanicisi.id,
    )


async def test_gonder_portu_bos_liste_donerse_gonderilir(
    client: AsyncClient, admin_headers, santiye, port
) -> None:
    site, _, _ = santiye
    kayit = await _taslak(client, admin_headers, site.id)
    port.dinle()

    yanit = await client.post(f"/diary/{kayit['id']}/submit", headers=admin_headers)

    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["status"] == "submitted"
    assert len(port.gonder_baglamlari) == 1


async def test_gonderilmis_kayda_ikinci_submit_porta_sorulmadan_409(
    client: AsyncClient, admin_headers, santiye, port
) -> None:
    """Sıra: tablo(409) porttan(422) ÖNCE — ikinci Gönder ön-koşul listesi almaz."""
    site, _, _ = santiye
    kayit = await _taslak(client, admin_headers, site.id)
    assert (await client.post(f"/diary/{kayit['id']}/submit", headers=admin_headers)).is_success
    port.engelle("Hava eksik")

    yanit = await client.post(f"/diary/{kayit['id']}/submit", headers=admin_headers)

    assert yanit.status_code == 409, yanit.text
    assert port.gonder_baglamlari == []


async def test_reopen_gonder_portuna_sorulmaz(
    client: AsyncClient, admin_headers, santiye, port
) -> None:
    site, _, _ = santiye
    kayit = await _taslak(client, admin_headers, site.id)
    assert (await client.post(f"/diary/{kayit['id']}/submit", headers=admin_headers)).is_success
    port.engelle("Hava eksik")

    yanit = await client.post(f"/diary/{kayit['id']}/reopen", headers=admin_headers)

    assert yanit.status_code == 200, yanit.text


# --- Kayıt YOK: bugünkü davranış ---


async def test_kayit_yokken_tum_yazma_yollari_bugunku_gibi(
    client: AsyncClient, admin_headers, santiye, port
) -> None:
    site, _, items = santiye
    kayit = await _taslak(client, admin_headers, site.id)
    entry_id = kayit["id"]

    patch = await client.patch(f"/diary/{entry_id}", json={"work_done": "x"}, headers=admin_headers)
    lines = await client.put(
        f"/diary/{entry_id}/lines",
        json={"lines": [{"boq_item_id": str(items[0].id), "quantity": "2"}]},
        headers=admin_headers,
    )
    submit = await client.post(f"/diary/{entry_id}/submit", headers=admin_headers)
    reopen = await client.post(f"/diary/{entry_id}/reopen", headers=admin_headers)
    delete = await client.delete(f"/diary/{entry_id}", headers=admin_headers)

    assert [patch.status_code, lines.status_code, submit.status_code] == [200, 200, 200]
    assert [reopen.status_code, delete.status_code] == [200, 204]
