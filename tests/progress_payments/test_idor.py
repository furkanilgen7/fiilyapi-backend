"""Task H4 — spec §9.0 negatif seti: görünmeyen kayıt VE olmayan kimlik ayırt

edilemez 404 döner; modül izni yetersizse 403 (kapı, görünürlükten ÖNCE).

Ayrıca H4 denetimi Y1: `service._build_lines`'taki çapraz-proje satır sahiplik
korkuluğu (`SITE_PROJECT_MISMATCH`/`ITEM_PROJECT_MISMATCH`, service.py:98-104)
— denetimden ÖNCE hiçbir test bu koşulu uygulamıyordu (koşulu silince 68 test
yeşil kalıyordu). `admin_headers` (system_admin) bilinçli olarak kullanılır:
her iki projeyi de GÖRÜR — bu testlerin amacı yetki/görünürlük DEĞİL, aynı
istek gövdesinde başka projenin kimliklerinin sızmasını engelleyen sahiplik
kuralıdır."""

import uuid

import pytest
from httpx import AsyncClient

from app.modules.progress_payments import guards

pytestmark = pytest.mark.asyncio


async def test_gorunmeyen_hakedis_ile_olmayan_id_ayni_yanit(
    client: AsyncClient, kisitli_headers: dict[str, str], gorunmeyen_hakedis: uuid.UUID
) -> None:
    gercek = await client.get(f"/progress-payments/{gorunmeyen_hakedis}", headers=kisitli_headers)
    sahte = await client.get(f"/progress-payments/{uuid.uuid4()}", headers=kisitli_headers)
    assert gercek.status_code == sahte.status_code == 404
    assert gercek.json() == sahte.json()


async def test_sef_atanmadigi_projede_olusturamaz_404(
    client: AsyncClient, site_chief_headers: dict[str, str], gorunmeyen_proje: uuid.UUID
) -> None:
    """Şef `scope=project`: atanmamış proje 403 DEĞİL 404 (varlık sızdırmaz)."""
    yanit = await client.post(
        f"/projects/{gorunmeyen_proje}/progress-payments", json={}, headers=site_chief_headers
    )
    assert yanit.status_code == 404


async def test_gorunmeyen_hakedis_patch_404(
    client: AsyncClient, kisitli_headers: dict[str, str], gorunmeyen_hakedis: uuid.UUID
) -> None:
    yanit = await client.patch(
        f"/progress-payments/{gorunmeyen_hakedis}",
        json={"description": "x"},
        headers=kisitli_headers,
    )
    assert yanit.status_code == 404


async def test_olmayan_hakedis_get_404(
    client: AsyncClient, kisitli_headers: dict[str, str]
) -> None:
    yanit = await client.get(f"/progress-payments/{uuid.uuid4()}", headers=kisitli_headers)
    assert yanit.status_code == 404


async def test_yetkisiz_rol_403(
    client: AsyncClient, hr_headers: dict[str, str], gorunmeyen_hakedis: uuid.UUID
) -> None:
    """İK matris satırı `_N`: modül izni yetersiz -> 403 (kapı, görünürlükten ÖNCE)."""
    yanit = await client.get(f"/progress-payments/{gorunmeyen_hakedis}", headers=hr_headers)
    assert yanit.status_code == 403


async def test_yetkisiz_rol_olusturma_403(
    client: AsyncClient, hr_headers: dict[str, str], gorunmeyen_proje: uuid.UUID
) -> None:
    yanit = await client.post(
        f"/projects/{gorunmeyen_proje}/progress-payments", json={}, headers=hr_headers
    )
    assert yanit.status_code == 403


async def test_kisitli_kullanici_listede_gorunmeyen_projeyi_goremez(
    client: AsyncClient,
    admin_headers: dict[str, str],
    kisitli_headers: dict[str, str],
    gorunmeyen_hakedis: uuid.UUID,
) -> None:
    """Liste ucu da görünürlük süzgecinden geçer (spec §9.0) — başka projenin

    hakedişi `kisitli_headers` kullanıcısının listesinde HİÇ görünmez.
    """
    yanit = await client.get("/progress-payments", headers=kisitli_headers)
    assert yanit.status_code == 200
    ids = [item["id"] for item in yanit.json()["items"]]
    assert str(gorunmeyen_hakedis) not in ids


# --- Y1 (H4 denetimi): çapraz-proje satır sahiplik kontrolü ---


async def test_capraz_proje_kalem_id_422(
    client: AsyncClient,
    admin_headers: dict[str, str],
    sozlesmeli_proje: uuid.UUID,
    hakedis_santiyesi,
    ikinci_proje_kalemi,
) -> None:
    """N1: A projesinde POST gövdesine B projesinin `contract_item_id`'si konursa
    422 `ITEM_PROJECT_MISMATCH` (şantiye A'ya ait, kalem B'ye ait)."""
    yanit = await client.post(
        f"/projects/{sozlesmeli_proje}/progress-payments",
        json={
            "lines": [
                {
                    "contract_item_id": str(ikinci_proje_kalemi.id),
                    "site_id": str(hakedis_santiyesi.id),
                    "quantity": "10",
                }
            ]
        },
        headers=admin_headers,
    )
    assert yanit.status_code == 422, yanit.text
    assert yanit.json()["detail"] == guards.ITEM_PROJECT_MISMATCH


async def test_capraz_proje_santiye_id_422(
    client: AsyncClient,
    admin_headers: dict[str, str],
    sozlesmeli_proje: uuid.UUID,
    hakedis_kalemi,
    ikinci_proje_santiyesi,
) -> None:
    """N2: aynısı B projesinin `site_id`'siyle -> 422 `SITE_PROJECT_MISMATCH`
    (kalem A'ya ait, şantiye B'ye ait)."""
    item, _ = hakedis_kalemi
    yanit = await client.post(
        f"/projects/{sozlesmeli_proje}/progress-payments",
        json={
            "lines": [
                {
                    "contract_item_id": str(item.id),
                    "site_id": str(ikinci_proje_santiyesi.id),
                    "quantity": "10",
                }
            ]
        },
        headers=admin_headers,
    )
    assert yanit.status_code == 422, yanit.text
    assert yanit.json()["detail"] == guards.SITE_PROJECT_MISMATCH


async def test_ayni_hucre_iki_kez_409(
    client: AsyncClient,
    admin_headers: dict[str, str],
    sozlesmeli_proje: uuid.UUID,
    hakedis_santiyesi,
    hakedis_kalemi,
) -> None:
    """N3: aynı (poz, şantiye) hücresi gövdede iki kez geçerse 409 `DUPLICATE_CELL`."""
    item, _ = hakedis_kalemi
    yanit = await client.post(
        f"/projects/{sozlesmeli_proje}/progress-payments",
        json={
            "lines": [
                {
                    "contract_item_id": str(item.id),
                    "site_id": str(hakedis_santiyesi.id),
                    "quantity": "10",
                },
                {
                    "contract_item_id": str(item.id),
                    "site_id": str(hakedis_santiyesi.id),
                    "quantity": "20",
                },
            ]
        },
        headers=admin_headers,
    )
    assert yanit.status_code == 409, yanit.text
    assert yanit.json()["detail"] == guards.DUPLICATE_CELL


async def test_reddedilen_post_kismi_yazma_yok(
    client: AsyncClient,
    admin_headers: dict[str, str],
    sozlesmeli_proje: uuid.UUID,
    hakedis_santiyesi,
    hakedis_kalemi,
) -> None:
    """N3b: reddedilen (409) POST sonrası hakediş kaydı da YAZILMAMALI — kısmi
    yazma yok. `_build_lines` satır sahiplik/tekillik kontrolünü `session.add`'DAN
    ÖNCE yapar; bu test o sıralamanın gerçekten korunduğunu kanıtlar."""
    item, _ = hakedis_kalemi
    yanit = await client.post(
        f"/projects/{sozlesmeli_proje}/progress-payments",
        json={
            "lines": [
                {
                    "contract_item_id": str(item.id),
                    "site_id": str(hakedis_santiyesi.id),
                    "quantity": "10",
                },
                {
                    "contract_item_id": str(item.id),
                    "site_id": str(hakedis_santiyesi.id),
                    "quantity": "20",
                },
            ]
        },
        headers=admin_headers,
    )
    assert yanit.status_code == 409

    liste = await client.get(
        "/progress-payments", params={"project_id": str(sozlesmeli_proje)}, headers=admin_headers
    )
    assert liste.status_code == 200
    assert liste.json()["items"] == []
