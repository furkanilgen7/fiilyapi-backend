"""URL-4 — taşeron hakedişi `<sözleşme-slug>-<sıra>` slug'ıyla açılır.

## Bileşik anahtar: AYRIŞTIRILMAZ, ÜRETİLİP SAKLANIR

Tablonun kısıtı `uq_subcontractor_progress_payments_contract_sequence` =
(`contract_id`, `sequence_no`)'dur — işverendeki proje-içi sayacın sözleşme-içi
karşılığı. Mockup ÖLÇÜLDÜ (`projedesign/Taşeron Hakediş Oluştur.dc.html`):
breadcrumb `Akın İnşaat TSZ-2025-001` / `Hakediş #48` — yani insan adı
SÖZLEŞME + SIRA'dır.

🔴 **ZİNCİR**: hakedişin slug'ı sözleşmenin slug'ından TÜRER, sözleşmeninki de
`contract_no`dan. Sözleşmenin slug'ı NULL ise hakedişinki de NULL kalır ve
kayıt UUID'siyle yaşar — uydurma taban yazılmaz. Migration'da da aynı sıra
bağlayıcıdır (`_TABLES`: sözleşmeler ÖNCE doldurulur).
"""

import uuid

from app.modules.subcontractor_progress_payments.guards import PAYMENT_MISSING

_YOL = "/subcontractor-progress-payments"


async def _slugla(session, contract, slug: str | None) -> None:
    contract.slug = slug
    await session.flush()


async def _hakedis_kur(client, headers, contract_id) -> dict:
    resp = await client.post(
        f"/subcontractor-contracts/{contract_id}/progress-payments", json={}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# =========================================================================== #
# 1. ÜRETİM
# =========================================================================== #


async def test_hakedis_SOZLESME_SLUGU_ve_SIRA_ile_sluglanir(
    client, admin_headers, taseron_sozlesmesi, seeded_db
) -> None:
    contract, _, _ = taseron_sozlesmesi
    await _slugla(seeded_db, contract, "tsz-2025-001")

    hakedis = await _hakedis_kur(client, admin_headers, contract.id)
    assert hakedis["sequence_no"] == 1
    assert hakedis["slug"] == "tsz-2025-001-1"


async def test_sozlesmenin_slugu_YOKSA_hakedisin_de_YOKTUR(
    client, admin_headers, taseron_sozlesmesi, seeded_db
) -> None:
    """🔴 ZİNCİR: üst kaydın slug'ı yoksa çocuğununki de olmaz — uydurma taban YOK."""
    contract, _, _ = taseron_sozlesmesi
    await _slugla(seeded_db, contract, None)

    hakedis = await _hakedis_kur(client, admin_headers, contract.id)
    assert hakedis["slug"] is None

    # POZİTİF KONTROL: UUID yolu çalışmaya DEVAM eder.
    assert (await client.get(f"{_YOL}/{hakedis['id']}", headers=admin_headers)).status_code == 200


# =========================================================================== #
# 2. ÇÖZÜMLEME
# =========================================================================== #


async def test_uuid_ve_slug_AYNI_govdeyi_doner(
    client, admin_headers, taseron_sozlesmesi, seeded_db
) -> None:
    contract, _, _ = taseron_sozlesmesi
    await _slugla(seeded_db, contract, "tsz-2025-001")
    hakedis = await _hakedis_kur(client, admin_headers, contract.id)

    by_uuid = await client.get(f"{_YOL}/{hakedis['id']}", headers=admin_headers)
    by_slug = await client.get(f"{_YOL}/tsz-2025-001-1", headers=admin_headers)

    assert by_uuid.status_code == by_slug.status_code == 200, by_slug.text
    assert by_uuid.json() == by_slug.json()


async def test_ustunde_TIRE_TASIYAN_sozlesme_slugu_dogru_cozulur(
    client, admin_headers, taseron_sozlesmesi, seeded_db
) -> None:
    """🔴 AYRIŞTIRMA YAPILMADIĞININ ÖLÇÜTÜ (`-` slug alfabesinin KENDİ harfi).

    Sözleşme slug'ı `tsz-2025-001-2` (çakışma ekli, gerçek bir hâl). Hakediş
    slug'ı `tsz-2025-001-2-1` olur; "son tireden böl" diyen bir çözümleyici
    sözleşmeyi `tsz-2025-001` sırayı `2-1` sanardı.
    """
    contract, _, _ = taseron_sozlesmesi
    await _slugla(seeded_db, contract, "tsz-2025-001-2")
    hakedis = await _hakedis_kur(client, admin_headers, contract.id)
    assert hakedis["slug"] == "tsz-2025-001-2-1"

    resp = await client.get(f"{_YOL}/tsz-2025-001-2-1", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == hakedis["id"]

    # KARŞIT KANIT: yanlış ayrıştırmanın üreteceği slug HİÇBİR ŞEY açmaz.
    assert (await client.get(f"{_YOL}/tsz-2025-001", headers=admin_headers)).status_code == 404


async def test_slug_LISTEDE_de_bulunur(
    client, admin_headers, taseron_sozlesmesi, seeded_db
) -> None:
    """🔴 Liste ucu `hakedisler/taseron/[paymentId]` bağlantısını üretir."""
    contract, _, _ = taseron_sozlesmesi
    await _slugla(seeded_db, contract, "liste-sozlesmesi")
    hakedis = await _hakedis_kur(client, admin_headers, contract.id)

    liste = await client.get(_YOL, headers=admin_headers)
    assert liste.status_code == 200, liste.text
    satir = next(k for k in liste.json()["items"] if k["id"] == hakedis["id"])
    assert satir["slug"] == "liste-sozlesmesi-1"


# =========================================================================== #
# 3. 🔴 GÖRÜNÜRLÜK SÜZGECİ SLUG'LA DELİNMEZ
# =========================================================================== #


async def test_gorunmeyen_projenin_hakedisi_SLUGLA_da_404(
    client,
    admin_headers,
    kisitli_headers,
    kisitli_proje,
    taseron_sozlesmesi_fabrikasi,
    seeded_db,
    project_factory,
) -> None:
    """Slug TAHMİN EDİLEBİLİR, UUID değil — ikisi de AYNI 404'e düşer."""
    gizli_proje = await project_factory(code="SPP-GIZLI", name="Gizli SPP Projesi")
    contract, _, _ = await taseron_sozlesmesi_fabrikasi("SPP-G01", project=gizli_proje)
    await _slugla(seeded_db, contract, "gizli-sozlesme")

    hakedis = await _hakedis_kur(client, admin_headers, contract.id)
    assert hakedis["slug"] == "gizli-sozlesme-1"

    slugla = await client.get(f"{_YOL}/gizli-sozlesme-1", headers=kisitli_headers)
    uuid_ile = await client.get(f"{_YOL}/{hakedis['id']}", headers=kisitli_headers)
    olmayan = await client.get(f"{_YOL}/hic-boyle-bir-slug-1", headers=kisitli_headers)

    assert slugla.status_code == uuid_ile.status_code == olmayan.status_code == 404
    assert slugla.json() == uuid_ile.json() == olmayan.json() == {"detail": PAYMENT_MISSING}

    # 🔴 POZİTİF KONTROL (K-IKIZ1): GÖREN aktör AYNI slug'la 200 alır —
    # 404 slug'ın çözülmemesinden DEĞİL, görünürlükten.
    goren = await client.get(f"{_YOL}/gizli-sozlesme-1", headers=admin_headers)
    assert goren.status_code == 200, goren.text
    assert goren.json()["id"] == hakedis["id"]
    assert kisitli_proje.id is not None


# =========================================================================== #
# 4. YAZMA UÇLARI SLUG KABUL ETMEZ
# =========================================================================== #


async def test_PATCH_ve_DELETE_slug_kabul_ETMEZ_422(
    client, admin_headers, taseron_sozlesmesi, seeded_db
) -> None:
    contract, _, _ = taseron_sozlesmesi
    await _slugla(seeded_db, contract, "yazma-sozlesmesi")
    hakedis = await _hakedis_kur(client, admin_headers, contract.id)

    patch = await client.patch(
        f"{_YOL}/yazma-sozlesmesi-1", json={"description": "x"}, headers=admin_headers
    )
    assert patch.status_code == 422, patch.text
    sil = await client.delete(f"{_YOL}/yazma-sozlesmesi-1", headers=admin_headers)
    assert sil.status_code == 422, sil.text

    # POZİTİF KONTROL: UUID ile AYNI uç çalışır.
    assert (
        await client.patch(
            f"{_YOL}/{hakedis['id']}", json={"description": "x"}, headers=admin_headers
        )
    ).status_code == 200


async def test_bozuk_deger_artik_422_DEGIL_404(client, admin_headers) -> None:
    assert (await client.get(f"{_YOL}/uuid-degil-bu", headers=admin_headers)).status_code == 404
    assert (await client.get(f"{_YOL}/{uuid.uuid4()}", headers=admin_headers)).status_code == 404
