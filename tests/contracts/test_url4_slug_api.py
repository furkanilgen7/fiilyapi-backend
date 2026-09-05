"""URL-4 — taşeron sözleşmesi ve İŞVEREN sözleşmesi okunabilir anahtarla açılır.

## 1. `sozlesmeler/taseron/[contractId]` -> `subcontractor_contracts.slug`

🔴 **EMİR PREMISE'İ ÖLÇÜLEREK DÜZELTİLDİ.** Görev emri `contract_no`yu
*"nullable, unique DEĞİL"* sayıyordu. GERÇEKTE
`contracts/models.py:172-178` bir **KISMİ BENZERSİZ İNDEKS** taşır:

    Index("uq_subcontractor_contracts_contract_no", "contract_no",
          unique=True, postgresql_where=text("contract_no IS NOT NULL"))

Yani numara doldurulduğunda **ŞİRKET GENELİ TEKİLDİR** (`repository.py`
docstring'i de bunu yazar: *"global kısmi benzersiz indeks (spec §3.5)"*).
Mockup da ölçüldü — `projedesign/Form - Sözleşme Oluştur.dc.html:90`:

    <label class="lbl">Sözleşme No <span class="req">*</span></label>
                                    ^^^ `.req{color:#ef4444}` = ZORUNLU

Bu iki ölçüm birlikte `contract_no`yu birinci sınıf bir anahtar yapar. Yine de
kolon NULLABLE kalır (taslak desteği), bu yüzden slug tabanı ÖNCE
`contract_no`dur, yoksa `subcontractor_name` + `work_category`ye düşer.

## 2. `sozlesmeler/isveren/[projectId]` -> **PROJE SLUG'I** (yeni kolon YOK)

🔴 **EMİR PREMISE'İ İKİNCİ KEZ ÖLÇÜLEREK DÜZELTİLDİ.** Emir *"proje ucu zaten
`parse_ref` kullanıyor — muhtemelen sıfır backend işi"* diyordu. ÖLÇÜM:
`contracts/router.py`de `parse_ref` HİÇ GEÇMİYORDU (`command grep -c` -> 0) ve
üç ucun üçü de `project_id: uuid.UUID` alıyordu. Yani iş SIFIR DEĞİLDİ.

Ekran bu üç ucu birden çağırır (`/contract`, `/contract/items`,
`/contract/distribution`); ÜÇÜ DE anahtar kabul eder, yoksa sayfanın bir kısmı
200 bir kısmı 422 alırdı. `project_contracts` PK'sı zaten `project_id`dir —
ikinci bir slug aynı kaydı iki adla anılır kılardı.
"""

import uuid
from decimal import Decimal

import pytest

from app.modules.contracts.models import Subcontractor
from app.modules.projects.models import Project, ProjectContract

_TASERON = "/subcontractor-contracts"


@pytest.fixture
async def taseron(seeded_db) -> uuid.UUID:
    """`test_subcontracts.py`deki fixture'ın ikizi — sibling conftest OTOMATİK
    yüklenmez, bu yüzden yerelde YENİDEN kurulur (ad doğrulandı, uydurulmadı)."""
    subcontractor = Subcontractor(name="Akın İnşaat Ltd. Şti.", category="Betonarme")
    seeded_db.add(subcontractor)
    await seeded_db.flush()
    return subcontractor.id


async def _slugla(session, project_id: uuid.UUID, slug: str) -> Project:
    from sqlalchemy import select

    project = (await session.execute(select(Project).where(Project.id == project_id))).scalar_one()
    project.slug = slug
    await session.flush()
    return project


async def _sozlesme_kur(client, headers, proje, taseron, **alanlar) -> dict:
    govde = {
        "is_draft": False,
        "subcontractor_id": str(taseron),
        "work_category": "Betonarme",
        "contract_no": "TSZ-2026-004",
        "signature_date": "2026-01-01",
        "start_date": "2026-01-05",
        "end_date": "2026-12-31",
    }
    govde.update(alanlar)
    resp = await client.post(
        f"/projects/{proje}/subcontractor-contracts", json=govde, headers=headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# =========================================================================== #
# 1. TAŞERON SÖZLEŞMESİ
# =========================================================================== #


async def test_sozlesme_NUMARADAN_sluglanir(client, admin_headers, ornek_proje, taseron) -> None:
    """Mockup'ta ZORUNLU olan `Sözleşme No` birinci sınıf anahtardır."""
    sozlesme = await _sozlesme_kur(client, admin_headers, ornek_proje.id, taseron)
    assert sozlesme["slug"] == "tsz-2026-004"

    resp = await client.get(f"{_TASERON}/tsz-2026-004", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == sozlesme["id"]


async def test_NUMARASIZ_taslak_AD_ve_KATEGORIDEN_sluglanir(
    client, admin_headers, ornek_proje, taseron
) -> None:
    """Kolon nullable KALIR (taslak desteği) — taban ad + kategoriye düşer."""
    sozlesme = await _sozlesme_kur(
        client, admin_headers, ornek_proje.id, taseron, is_draft=True, contract_no=None
    )
    # `subcontractor_name` kartotekten kopyalanır: "Akın İnşaat Ltd. Şti."
    assert sozlesme["slug"] == "akin-insaat-ltd-sti-betonarme"

    resp = await client.get(f"{_TASERON}/{sozlesme['slug']}", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == sozlesme["id"]


async def test_uuid_ve_slug_AYNI_govdeyi_doner(client, admin_headers, ornek_proje, taseron) -> None:
    sozlesme = await _sozlesme_kur(client, admin_headers, ornek_proje.id, taseron)

    by_uuid = await client.get(f"{_TASERON}/{sozlesme['id']}", headers=admin_headers)
    by_slug = await client.get(f"{_TASERON}/tsz-2026-004", headers=admin_headers)

    assert by_uuid.status_code == by_slug.status_code == 200, by_slug.text
    assert by_uuid.json() == by_slug.json()


async def test_sozlesme_slug_LISTEDE_de_bulunur(
    client, admin_headers, ornek_proje, taseron
) -> None:
    """🔴 Liste ucu `sozlesmeler/taseron/[contractId]` bağlantısını üretir."""
    sozlesme = await _sozlesme_kur(
        client, admin_headers, ornek_proje.id, taseron, contract_no="TSZ-2026-777"
    )
    liste = await client.get(_TASERON, headers=admin_headers)
    assert liste.status_code == 200, liste.text
    satir = next(k for k in liste.json()["items"] if k["id"] == sozlesme["id"])
    assert satir["slug"] == "tsz-2026-777"


async def test_numara_degisince_slug_DEGISMEZ(client, admin_headers, ornek_proje, taseron) -> None:
    sozlesme = await _sozlesme_kur(client, admin_headers, ornek_proje.id, taseron)
    patch = await client.patch(
        f"{_TASERON}/{sozlesme['id']}", json={"contract_no": "TSZ-2026-999"}, headers=admin_headers
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["contract_no"] == "TSZ-2026-999"
    assert patch.json()["slug"] == "tsz-2026-004"
    assert (await client.get(f"{_TASERON}/tsz-2026-004", headers=admin_headers)).status_code == 200
    assert (await client.get(f"{_TASERON}/tsz-2026-999", headers=admin_headers)).status_code == 404


async def test_gorunmeyen_projenin_sozlesmesi_SLUGLA_da_404(
    client, kisitli_headers, admin_headers, gorunmeyen_proje, taseron
) -> None:
    """🔴 GÖRÜNÜRLÜK SÜZGECİ SLUG'LA DELİNMEZ (IDOR — slug TAHMİN EDİLEBİLİR)."""
    sozlesme = await _sozlesme_kur(
        client, admin_headers, gorunmeyen_proje.id, taseron, contract_no="TSZ-GIZLI-001"
    )
    assert sozlesme["slug"] == "tsz-gizli-001"

    slugla = await client.get(f"{_TASERON}/tsz-gizli-001", headers=kisitli_headers)
    uuid_ile = await client.get(f"{_TASERON}/{sozlesme['id']}", headers=kisitli_headers)
    olmayan = await client.get(f"{_TASERON}/tsz-hic-yok-999", headers=kisitli_headers)

    assert slugla.status_code == uuid_ile.status_code == olmayan.status_code == 404
    assert slugla.json() == uuid_ile.json() == olmayan.json()

    # 🔴 POZİTİF KONTROL (K-IKIZ1): GÖREN aktör AYNI slug'la 200 alır.
    goren = await client.get(f"{_TASERON}/tsz-gizli-001", headers=admin_headers)
    assert goren.status_code == 200, goren.text
    assert goren.json()["id"] == sozlesme["id"]


async def test_sozlesme_PATCH_ve_DELETE_slug_kabul_ETMEZ_422(
    client, admin_headers, ornek_proje, taseron
) -> None:
    await _sozlesme_kur(client, admin_headers, ornek_proje.id, taseron)

    patch = await client.patch(
        f"{_TASERON}/tsz-2026-004", json={"work_category": "X"}, headers=admin_headers
    )
    assert patch.status_code == 422, patch.text
    sil = await client.delete(f"{_TASERON}/tsz-2026-004", headers=admin_headers)
    assert sil.status_code == 422, sil.text


# =========================================================================== #
# 2. İŞVEREN SÖZLEŞMESİ — PROJE SLUG'I, ÜÇ UÇ BİRDEN
# =========================================================================== #


async def test_isveren_sozlesmesi_UC_UCU_da_PROJE_SLUGUYLA_acilir(
    client, admin_headers, ornek_proje, seeded_db
) -> None:
    """🔴 Ekranın ÜÇ isteğinin ÜÇÜ de anahtar kabul etmeli.

    Yalnız biri açılsaydı sayfanın bir kısmı 200, kalanı 422 alır ve kusur
    ancak kullanıcı tıklayınca görülürdü.
    """
    seeded_db.add(
        ProjectContract(
            project_id=ornek_proje.id,
            contract_no="SZL-2026-010",
            amount=Decimal("11200000"),
            advance_pct=Decimal("20"),
        )
    )
    await seeded_db.flush()
    await _slugla(seeded_db, ornek_proje.id, "kopru-guclendirme")

    for uc in ("", "/items", "/distribution"):
        by_uuid = await client.get(
            f"/projects/{ornek_proje.id}/contract{uc}", headers=admin_headers
        )
        by_slug = await client.get(
            f"/projects/kopru-guclendirme/contract{uc}", headers=admin_headers
        )
        assert by_uuid.status_code == 200, by_uuid.text
        assert by_slug.status_code == 200, f"{uc}: {by_slug.text}"
        assert by_uuid.json() == by_slug.json()


async def test_isveren_sozlesmesi_gorunmeyen_projede_SLUGLA_da_404(
    client, kisitli_headers, admin_headers, gorunmeyen_proje, seeded_db
) -> None:
    seeded_db.add(
        ProjectContract(
            project_id=gorunmeyen_proje.id,
            contract_no="SZL-GIZLI",
            amount=Decimal("100"),
            advance_pct=Decimal("20"),
        )
    )
    await seeded_db.flush()
    await _slugla(seeded_db, gorunmeyen_proje.id, "gizli-isveren-projesi")

    slugla = await client.get("/projects/gizli-isveren-projesi/contract", headers=kisitli_headers)
    uuid_ile = await client.get(
        f"/projects/{gorunmeyen_proje.id}/contract", headers=kisitli_headers
    )
    olmayan = await client.get("/projects/hic-boyle-bir-proje/contract", headers=kisitli_headers)

    assert slugla.status_code == uuid_ile.status_code == olmayan.status_code == 404
    assert slugla.json() == uuid_ile.json() == olmayan.json()

    # 🔴 POZİTİF KONTROL: GÖREN aktör AYNI slug'la 200 alır.
    goren = await client.get("/projects/gizli-isveren-projesi/contract", headers=admin_headers)
    assert goren.status_code == 200, goren.text


async def test_dagitim_PUT_ikizi_slug_kabul_ETMEZ_422(
    client, admin_headers, ornek_proje, seeded_db
) -> None:
    """URL-2 kararı 3: yalnız OKUMA uçları anahtar kabul eder."""
    seeded_db.add(
        ProjectContract(
            project_id=ornek_proje.id,
            contract_no="SZL-2026-011",
            amount=Decimal("100"),
            advance_pct=Decimal("20"),
        )
    )
    await seeded_db.flush()
    await _slugla(seeded_db, ornek_proje.id, "yazma-projesi")

    resp = await client.put(
        "/projects/yazma-projesi/contract/distribution",
        json={"allocations": []},
        headers=admin_headers,
    )
    assert resp.status_code == 422, resp.text


# =========================================================================== #
# 3. 🔴 K1 — SLUG'IN GEÇ DOĞUMU (kira faturasıyla AYNI sınıf)
# =========================================================================== #


async def test_TABANSIZ_taslaga_ad_girilince_slug_SONRADAN_dogar(
    client, admin_headers, ornek_proje, taseron
) -> None:
    """🔴 K1 — taslakta ad/numara yoksa slug NULL'dır; sonradan girilince DOĞAR.

    Slug yalnız `create`te ayrılsaydı bu kayıt okunabilir URL'ini HİÇ almazdı
    ve özellik "verinin yaşının fonksiyonu" olurdu.
    """
    sozlesme = await _sozlesme_kur(
        client,
        admin_headers,
        ornek_proje.id,
        taseron,
        is_draft=True,
        contract_no=None,
        subcontractor_id=None,
        work_category=None,
    )
    assert sozlesme["slug"] is None, "kurulum: tabansız taslak slug'sız olmalı"

    guncel = await client.patch(
        f"{_TASERON}/{sozlesme['id']}",
        json={"contract_no": "TSZ-GEC-001"},
        headers=admin_headers,
    )
    assert guncel.status_code == 200, guncel.text
    assert guncel.json()["slug"] == "tsz-gec-001"

    acilis = await client.get(f"{_TASERON}/tsz-gec-001", headers=admin_headers)
    assert acilis.status_code == 200, acilis.text
    assert acilis.json()["id"] == sozlesme["id"]


async def test_DOLU_slug_PATCHte_YENIDEN_URETILMEZ(
    client, admin_headers, ornek_proje, taseron
) -> None:
    """🔴 K1'in TERS KAPISI — geç doğum yalnız `NULL -> dolu` geçişinde çalışır.

    Bu iddia olmasaydı geç doğum "her PATCH'te yeniden üret" diye yazılabilir
    ve önceki test yine yeşil kalırdı (URL-2 kararı 4 sessizce ihlal edilirdi).
    """
    sozlesme = await _sozlesme_kur(client, admin_headers, ornek_proje.id, taseron)
    assert sozlesme["slug"] == "tsz-2026-004"

    guncel = await client.patch(
        f"{_TASERON}/{sozlesme['id']}",
        json={"contract_no": "TSZ-2026-888"},
        headers=admin_headers,
    )
    assert guncel.status_code == 200, guncel.text
    assert guncel.json()["slug"] == "tsz-2026-004"
    assert (await client.get(f"{_TASERON}/tsz-2026-004", headers=admin_headers)).status_code == 200
    assert (await client.get(f"{_TASERON}/tsz-2026-888", headers=admin_headers)).status_code == 404
