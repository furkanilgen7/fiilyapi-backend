"""URL-4 — işveren hakedişi `<proje-slug>-<sıra>` slug'ıyla açılır.

## Bileşik anahtar: AYRIŞTIRILMAZ, ÜRETİLİP SAKLANIR (yönetim eğilimi (b))

Bir hakedişin insan adı BİLEŞİKTİR. Mockup ölçüldü
(`projedesign/Ekran 15 - İşveren Hakedişi.dc.html`): h1 `İşveren Hakedişi #5`,
hemen altı `Güneşkent A-Blok · Temmuz 2026 · SZL-2025-001` — yani kimlik
PROJE + SIRA'dır. Tablonun kısıtı da bunu söyler:
`uq_progress_payments_project_sequence` = (`project_id`, `sequence_no`).

Üç seçenek vardı; (b) seçildi: `<proje-slug>-<sıra>` **üretilip saklanır**.
* (a) iki segmentli yol (`/hakedisler/<proje>/<sıra>`) URL-2 kararı 1'i ihlal
  ederdi (yol şablonu değişirdi, üretilmiş istemcinin anahtarı kayardı);
* (c) UUID kalması kullanıcının şikâyetini hiç çözmezdi.

🔴 **AYRIŞTIRMA YAPILMAZ ve bunun bir ölçütü vardır**: `-` slug alfabesinin
KENDİ harfidir, dolayısıyla `kopru-a-2-5` gibi bir slug'da "son tireden böl"
YANLIŞ cevap verir. Saklanan slug tek bir eşitlik karşılaştırmasına iner ve
`test_ustunde_TIRE_TASIYAN_proje_slugu_dogru_cozulur` bunu ölçer.
"""

import uuid

from sqlalchemy import select

from app.modules.progress_payments.guards import PAYMENT_MISSING
from app.modules.progress_payments.models import ProgressPayment

_YOL = "/progress-payments"


async def _slugla(seeded_db, project_id: uuid.UUID, slug: str) -> None:
    """Projeye URL-2 slug'ını verir (fabrika slug AYIRMAZ — servis ayırır)."""
    from app.modules.projects.models import Project

    project = (
        await seeded_db.execute(select(Project).where(Project.id == project_id))
    ).scalar_one()
    project.slug = slug
    await seeded_db.flush()


# =========================================================================== #
# 1. ÜRETİM
# =========================================================================== #


async def test_hakedis_olusturulurken_PROJE_SLUGU_ve_SIRA_ile_sluglanir(
    client, admin_headers, sozlesmeli_proje, seeded_db
) -> None:
    await _slugla(seeded_db, sozlesmeli_proje, "kopru-guclendirme")

    resp = await client.post(f"/projects/{sozlesmeli_proje}{_YOL}", json={}, headers=admin_headers)
    assert resp.status_code == 201, resp.text
    assert resp.json()["sequence_no"] == 1
    assert resp.json()["slug"] == "kopru-guclendirme-1"


async def test_projenin_slugu_YOKSA_hakedisin_de_YOKTUR_ama_kayit_ACILIR(
    client, admin_headers, sozlesmeli_proje, seeded_db
) -> None:
    """Uydurma taban YAZILMAZ; kayıt UUID'siyle yaşar (URL-2 `slug.py` kanonu)."""
    resp = await client.post(f"/projects/{sozlesmeli_proje}{_YOL}", json={}, headers=admin_headers)
    assert resp.status_code == 201, resp.text
    assert resp.json()["slug"] is None

    # POZİTİF KONTROL: UUID yolu çalışmaya DEVAM eder.
    assert (
        await client.get(f"{_YOL}/{resp.json()['id']}", headers=admin_headers)
    ).status_code == 200


# =========================================================================== #
# 2. ÇÖZÜMLEME
# =========================================================================== #


async def test_uuid_ve_slug_AYNI_govdeyi_doner(
    client, admin_headers, sozlesmeli_proje, seeded_db
) -> None:
    await _slugla(seeded_db, sozlesmeli_proje, "kopru-guclendirme")
    olusan = await client.post(
        f"/projects/{sozlesmeli_proje}{_YOL}", json={}, headers=admin_headers
    )
    assert olusan.status_code == 201, olusan.text

    by_uuid = await client.get(f"{_YOL}/{olusan.json()['id']}", headers=admin_headers)
    by_slug = await client.get(f"{_YOL}/kopru-guclendirme-1", headers=admin_headers)

    assert by_uuid.status_code == by_slug.status_code == 200, by_slug.text
    assert by_uuid.json() == by_slug.json()


async def test_ustunde_TIRE_TASIYAN_proje_slugu_dogru_cozulur(
    client, admin_headers, sozlesmeli_proje, seeded_db
) -> None:
    """🔴 AYRIŞTIRMA YAPILMADIĞININ ÖLÇÜTÜ.

    Proje slug'ı `kopru-a-2` (URL-2'nin çakışma ekiyle üretilmiş, gerçek bir
    hâl). Hakediş slug'ı `kopru-a-2-1` olur. "Son tireden böl" diye ayrıştıran
    bir çözümleyici projeyi `kopru-a` sırayı `2-1` sanardı ve YANLIŞ cevap
    verirdi; saklanan slug tek eşitliğe indiği için bu kusur YAPISAL olarak
    imkânsızdır.
    """
    await _slugla(seeded_db, sozlesmeli_proje, "kopru-a-2")
    olusan = await client.post(
        f"/projects/{sozlesmeli_proje}{_YOL}", json={}, headers=admin_headers
    )
    assert olusan.json()["slug"] == "kopru-a-2-1"

    resp = await client.get(f"{_YOL}/kopru-a-2-1", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == olusan.json()["id"]

    # KARŞIT KANIT: yanlış ayrıştırmanın üreteceği slug HİÇBİR ŞEY açmaz.
    assert (await client.get(f"{_YOL}/kopru-a", headers=admin_headers)).status_code == 404


async def test_slug_LISTEDE_de_bulunur(client, admin_headers, sozlesmeli_proje, seeded_db) -> None:
    """🔴 Liste ucu `hakedisler/[paymentId]` bağlantısını üretir.

    URL-2'de `SiteOptionListResponse`e slug EKLENMEDİĞİ için seçici slug
    üretememiş ve `routes.ts:34-45`e bir kural yazılmıştı — aynı yarım göç
    tekrarlanmaz.
    """
    await _slugla(seeded_db, sozlesmeli_proje, "liste-projesi")
    olusan = await client.post(
        f"/projects/{sozlesmeli_proje}{_YOL}", json={}, headers=admin_headers
    )

    liste = await client.get(_YOL, headers=admin_headers)
    assert liste.status_code == 200, liste.text
    satir = next(k for k in liste.json()["items"] if k["id"] == olusan.json()["id"])
    assert satir["slug"] == "liste-projesi-1"


# =========================================================================== #
# 3. 🔴 GÖRÜNÜRLÜK SÜZGECİ SLUG'LA DELİNMEZ
# =========================================================================== #


async def test_gorunmeyen_projenin_hakedisi_SLUGLA_da_404(
    client, kisitli_headers, admin_headers, gorunmeyen_proje, seeded_db, db_session
) -> None:
    """Slug TAHMİN EDİLEBİLİR (`<proje-slug>-1`), UUID değil.

    Görünmeyen projedeki gerçek hakediş, var OLMAYAN slug'la BİREBİR AYNI 404
    gövdesini alır.
    """
    from decimal import Decimal

    from app.modules.projects.models import ProjectContract

    seeded_db.add(
        ProjectContract(
            project_id=gorunmeyen_proje,
            contract_no="SZL-GIZLI",
            amount=Decimal("1000000"),
            advance_pct=Decimal("20"),
            retainage_pct=Decimal("5"),
            vat_pct=Decimal("20"),
        )
    )
    await seeded_db.flush()
    await _slugla(seeded_db, gorunmeyen_proje, "gizli-proje")

    olusan = await client.post(
        f"/projects/{gorunmeyen_proje}{_YOL}", json={}, headers=admin_headers
    )
    assert olusan.status_code == 201, olusan.text
    assert olusan.json()["slug"] == "gizli-proje-1"

    slugla = await client.get(f"{_YOL}/gizli-proje-1", headers=kisitli_headers)
    uuid_ile = await client.get(f"{_YOL}/{olusan.json()['id']}", headers=kisitli_headers)
    olmayan = await client.get(f"{_YOL}/hic-boyle-bir-slug-1", headers=kisitli_headers)

    assert slugla.status_code == uuid_ile.status_code == olmayan.status_code == 404
    assert slugla.json() == uuid_ile.json() == olmayan.json() == {"detail": PAYMENT_MISSING}

    # 🔴 POZİTİF KONTROL (K-IKIZ1): kayıt GERÇEKTEN duruyor ve GÖREN aktör
    # AYNI slug'la açıyor — 404 slug'ın çalışmamasından DEĞİL görünmezlikten.
    goren = await client.get(f"{_YOL}/gizli-proje-1", headers=admin_headers)
    assert goren.status_code == 200, goren.text
    assert goren.json()["id"] == olusan.json()["id"]
    assert (
        await db_session.execute(
            select(ProgressPayment).where(ProgressPayment.slug == "gizli-proje-1")
        )
    ).scalar_one()


# =========================================================================== #
# 4. YAZMA UÇLARI SLUG KABUL ETMEZ (URL-2 kararı 3)
# =========================================================================== #


async def test_PATCH_ve_DELETE_slug_kabul_ETMEZ_422(
    client, admin_headers, sozlesmeli_proje, seeded_db
) -> None:
    await _slugla(seeded_db, sozlesmeli_proje, "yazma-projesi")
    olusan = await client.post(
        f"/projects/{sozlesmeli_proje}{_YOL}", json={}, headers=admin_headers
    )
    assert olusan.json()["slug"] == "yazma-projesi-1"

    patch = await client.patch(
        f"{_YOL}/yazma-projesi-1", json={"description": "x"}, headers=admin_headers
    )
    assert patch.status_code == 422, patch.text

    sil = await client.delete(f"{_YOL}/yazma-projesi-1", headers=admin_headers)
    assert sil.status_code == 422, sil.text

    # POZİTİF KONTROL: UUID ile AYNI uçlar çalışır.
    assert (
        await client.patch(
            f"{_YOL}/{olusan.json()['id']}", json={"description": "x"}, headers=admin_headers
        )
    ).status_code == 200
