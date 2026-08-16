"""BOR-TEMIZ T3 — `GET /personnel/document-types` (Boşluk #4).

Model + repository ZATEN VARDI (`PersonnelDocumentType` / `repository.list_document_types`);
eksik olan yalnız HTTP ucuydu. Servis dosyası 800 tavanının üstünde olduğundan
(K5) ince bir router doğrudan repository'yi çağırır — `equipment/document_router.py`
`GET /equipment/document-types` emsalinin birebiri.

Kapı `personnel` izninin `view` düzeyidir (mevcut personel okuma uçlarıyla
tutarlı — `router.py`deki `_VIEW`). Sıralama `sort_order` iledir (repository
zaten böyle sorgular).

🔴 K7 notu: bu uç "veri kaybı" değil "israf" düzeltmesidir — frontend'in
`by_type[]` türetmesi eksiksizdi (kayıtsız tip de geliyordu), yalnız maliyetliydi
(bir dropdown için tüm personel×belge özet sorgusu).
"""

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.personnel.models import PersonnelDocumentType


async def _seed_types(seeded_db: AsyncSession) -> None:
    seeded_db.add_all(
        [
            PersonnelDocumentType(name="C Tipi", is_mandatory=False, sort_order=3),
            PersonnelDocumentType(
                name="A Tipi", is_mandatory=True, validity_months=12, sort_order=1
            ),
            PersonnelDocumentType(name="B Tipi", is_mandatory=False, sort_order=2),
            PersonnelDocumentType(name="Pasif Tip", is_active=False, sort_order=0),
        ]
    )
    await seeded_db.flush()


async def test_yetkili_200_alanlar_ve_sort_order_sirasi(client: AsyncClient, seeded_db, ik_headers):
    await _seed_types(seeded_db)

    yanit = await client.get("/personnel/document-types", headers=ik_headers)

    assert yanit.status_code == 200, yanit.text
    govde = yanit.json()
    assert "items" in govde
    isimler = [item["name"] for item in govde["items"]]
    # sort_order: Pasif Tip(0) < A Tipi(1) < B Tipi(2) < C Tipi(3)
    assert isimler == ["Pasif Tip", "A Tipi", "B Tipi", "C Tipi"]

    a_tipi = next(item for item in govde["items"] if item["name"] == "A Tipi")
    assert a_tipi["is_mandatory"] is True
    assert a_tipi["validity_months"] == 12
    assert set(a_tipi.keys()) >= {
        "id",
        "name",
        "is_mandatory",
        "validity_months",
        "sort_order",
        "is_active",
    }


async def test_pasif_tip_listede_gorunur_filtrelenmez(client: AsyncClient, seeded_db, ik_headers):
    """Ölçülen gerçek davranış: `repository.list_document_types` `is_active`

    süzgeci UYGULAMAZ — pasif tip de listeye girer. Bu test o davranışı
    KİLİTLER (sessizce değiştirilmesin diye).
    """
    await _seed_types(seeded_db)

    yanit = await client.get("/personnel/document-types", headers=ik_headers)

    assert yanit.status_code == 200, yanit.text
    isimler = {item["name"] for item in yanit.json()["items"]}
    assert "Pasif Tip" in isimler


async def test_view_yetkisi_de_200_gorur(client: AsyncClient, seeded_db, sef_headers):
    """`site_chief` (`personnel=_V`) — okuma ucu yalnız `view` ister."""
    await _seed_types(seeded_db)

    yanit = await client.get("/personnel/document-types", headers=sef_headers)

    assert yanit.status_code == 200, yanit.text


async def test_yetkisiz_403(client: AsyncClient, yetkisiz_headers):
    """`procurement` (`personnel=_N`) — hiçbir personel ucuna giremez."""
    yanit = await client.get("/personnel/document-types", headers=yetkisiz_headers)
    assert yanit.status_code == 403, yanit.text


async def test_oturumsuz_401(client: AsyncClient):
    yanit = await client.get("/personnel/document-types")
    assert yanit.status_code == 401, yanit.text
