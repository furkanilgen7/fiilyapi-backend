"""TB4 · B3 — işveren kalemi PATCH'inde ayna BOQ senkronu (spec §1 B3 + §5 S2, plan T3).

P5 devri: sözleşme kaleminin `unit_price`/`code` değeri değişince dağıtım ekranı
doğru değeri gösteriyor ama dağıtımın ürettiği **ayna** BOQ satırları eski değeri
taşımaya devam ediyordu — BOQ ekranı bayat kalıyordu. Kullanıcı kararı (S2):
bu bir "bilinçli snapshot" DEĞİL, unutulmuş senkrondur; PATCH aynı işlemde ayna
satırların ilgili alanlarını tazeler.

Sınırlar burada testle çivilenir:

* **miktara DOKUNULMAZ** — miktar dağıtımın kendi kararıdır,
* **kapsam** yalnız o kaleme bağlı ve projenin şantiyelerindeki hücrelerdir
  (TB4/B2 otorite kümesi) — başka kalemin ya da başka projenin satırı değişmez,
* audit **mevcut** `update` olayının detayına işlenir, yeni `AuditAction` YOK.

Doğrulama BOQ okuma ucundan (`GET /sites/{id}/boq`) yapılır: bayatlığın
görüldüğü yüzey odur, ORM kimlik haritası değil.
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.modules.audit.models import AuditLog
from app.modules.boq.models import BoqGroup, BoqItem
from app.modules.contracts.guards import BOQ_CODE_TAKEN_IN_SITE
from app.modules.contracts.models import EmployerContractGroup, EmployerContractItem
from app.modules.projects.models import ProjectContract
from app.modules.sites.models import Site

GRUP_ADI = "A — Betonarme İşleri"

ESKI_FIYAT = Decimal("21500.00")
YENI_FIYAT = Decimal("24750.00")
ESKI_KOD = "04.001"
YENI_KOD = "04.009"
AYNA_MIKTAR = Decimal("120.000")
YABANCI_MIKTAR = Decimal("30.000")

IKINCI_KOD = "05.001"
IKINCI_FIYAT = Decimal("3300.00")
UCUNCU_KOD = "06.001"
UCUNCU_FIYAT = Decimal("990.00")


async def _boq_satiri(
    session,
    site_id: uuid.UUID,
    contract_item_id: uuid.UUID | None,
    *,
    code: str,
    quantity: Decimal,
    unit_price: Decimal,
) -> BoqItem:
    group = BoqGroup(site_id=site_id, name=GRUP_ADI)
    session.add(group)
    await session.flush()
    row = BoqItem(
        site_id=site_id,
        group_id=group.id,
        contract_item_id=contract_item_id,
        code=code,
        description="Demir donatı",
        unit="Ton",
        quantity=quantity,
        unit_price=unit_price,
    )
    session.add(row)
    await session.flush()
    return row


def _kalem(
    project_id: uuid.UUID,
    group_id: uuid.UUID,
    *,
    code: str,
    unit_price: Decimal,
    sort_order: int,
) -> EmployerContractItem:
    return EmployerContractItem(
        project_id=project_id,
        group_id=group_id,
        code=code,
        description="Demir donatı",
        unit="Ton",
        quantity=Decimal("400.000"),
        unit_price=unit_price,
        sort_order=sort_order,
    )


@pytest.fixture
async def ayna_kurulum(seeded_db, project_factory) -> dict[str, uuid.UUID]:
    """Bir kalemin ayna satırı projenin şantiyesinde, bir kopyası YABANCI şantiyede.

    Ayrıca aynı şantiyede BAŞKA kaleme bağlı bir satır (kalem kapsamı) ve hiç
    dağıtılmamış üçüncü bir kalem (dokunmama senaryosu) kurulur.
    """
    project = await project_factory(code="CL-B3-01", name="Ayna Senkron Projesi")
    seeded_db.add(
        ProjectContract(
            project_id=project.id,
            contract_no="SZL-2026-B3",
            amount=Decimal("50000000"),
            advance_pct=Decimal("20"),
        )
    )
    site = Site(project_id=project.id, code="SNT-B3A", name="Şantiye A")
    seeded_db.add(site)

    yabanci_proje = await project_factory(code="CL-B3-99", name="Devredilmiş Proje")
    yabanci_santiye = Site(project_id=yabanci_proje.id, code="SNT-B3X", name="Yabancı Şantiye")
    seeded_db.add(yabanci_santiye)

    group = EmployerContractGroup(project_id=project.id, name=GRUP_ADI, sort_order=0)
    seeded_db.add(group)
    await seeded_db.flush()

    item = _kalem(project.id, group.id, code=ESKI_KOD, unit_price=ESKI_FIYAT, sort_order=0)
    ikinci = _kalem(project.id, group.id, code=IKINCI_KOD, unit_price=IKINCI_FIYAT, sort_order=1)
    dagitimsiz = _kalem(
        project.id, group.id, code=UCUNCU_KOD, unit_price=UCUNCU_FIYAT, sort_order=2
    )
    seeded_db.add_all([item, ikinci, dagitimsiz])
    await seeded_db.flush()

    ayna = await _boq_satiri(
        seeded_db, site.id, item.id, code=ESKI_KOD, quantity=AYNA_MIKTAR, unit_price=ESKI_FIYAT
    )
    yabanci = await _boq_satiri(
        seeded_db,
        yabanci_santiye.id,
        item.id,
        code=ESKI_KOD,
        quantity=YABANCI_MIKTAR,
        unit_price=ESKI_FIYAT,
    )
    komsu = await _boq_satiri(
        seeded_db,
        site.id,
        ikinci.id,
        code=IKINCI_KOD,
        quantity=Decimal("10.000"),
        unit_price=IKINCI_FIYAT,
    )

    return {
        "project_id": project.id,
        "site_id": site.id,
        "yabanci_site_id": yabanci_santiye.id,
        "item_id": item.id,
        "ikinci_item_id": ikinci.id,
        "dagitimsiz_item_id": dagitimsiz.id,
        "ayna_boq_id": ayna.id,
        "yabanci_boq_id": yabanci.id,
        "komsu_boq_id": komsu.id,
    }


async def _boq_satirlari(client, headers, site_id: uuid.UUID) -> dict[str, dict]:
    yanit = await client.get(f"/sites/{site_id}/boq", headers=headers)
    assert yanit.status_code == 200, yanit.text
    return {satir["id"]: satir for grup in yanit.json()["groups"] for satir in grup["items"]}


async def _patch_kalem(client, headers, item_id: uuid.UUID, govde: dict):
    return await client.patch(f"/contracts/employer/items/{item_id}", json=govde, headers=headers)


async def _audit_metinleri(session) -> list[str]:
    rows = await session.scalars(select(AuditLog.detail))
    return list(rows)


@pytest.mark.asyncio
async def test_birim_fiyat_degisimi_ayna_boq_satirina_yansir(client, admin_headers, ayna_kurulum):
    yanit = await _patch_kalem(
        client, admin_headers, ayna_kurulum["item_id"], {"unit_price": str(YENI_FIYAT)}
    )
    assert yanit.status_code == 200, yanit.text

    satirlar = await _boq_satirlari(client, admin_headers, ayna_kurulum["site_id"])
    ayna = satirlar[str(ayna_kurulum["ayna_boq_id"])]
    assert Decimal(ayna["unit_price"]) == YENI_FIYAT


@pytest.mark.asyncio
async def test_kod_degisimi_ayna_boq_satirina_yansir(client, admin_headers, ayna_kurulum):
    yanit = await _patch_kalem(client, admin_headers, ayna_kurulum["item_id"], {"code": YENI_KOD})
    assert yanit.status_code == 200, yanit.text

    satirlar = await _boq_satirlari(client, admin_headers, ayna_kurulum["site_id"])
    assert satirlar[str(ayna_kurulum["ayna_boq_id"])]["code"] == YENI_KOD


@pytest.mark.asyncio
async def test_tazeleme_ayna_satirin_miktarina_dokunmaz(client, admin_headers, ayna_kurulum):
    """Miktar dağıtımın kararıdır — fiyat/kod senkronu onu YENİDEN YAZMAZ."""
    yanit = await _patch_kalem(
        client,
        admin_headers,
        ayna_kurulum["item_id"],
        {"unit_price": str(YENI_FIYAT), "code": YENI_KOD},
    )
    assert yanit.status_code == 200, yanit.text

    satirlar = await _boq_satirlari(client, admin_headers, ayna_kurulum["site_id"])
    ayna = satirlar[str(ayna_kurulum["ayna_boq_id"])]
    assert Decimal(ayna["quantity"]) == AYNA_MIKTAR


@pytest.mark.asyncio
async def test_dagitimsiz_kalemde_hicbir_boq_satiri_degismez(client, admin_headers, ayna_kurulum):
    onceki = await _boq_satirlari(client, admin_headers, ayna_kurulum["site_id"])

    yanit = await _patch_kalem(
        client,
        admin_headers,
        ayna_kurulum["dagitimsiz_item_id"],
        {"unit_price": "1234.00", "code": "06.009"},
    )
    assert yanit.status_code == 200, yanit.text

    assert await _boq_satirlari(client, admin_headers, ayna_kurulum["site_id"]) == onceki


@pytest.mark.asyncio
async def test_baska_kalemin_boq_satiri_etkilenmez(client, admin_headers, ayna_kurulum):
    yanit = await _patch_kalem(
        client,
        admin_headers,
        ayna_kurulum["item_id"],
        {"unit_price": str(YENI_FIYAT), "code": YENI_KOD},
    )
    assert yanit.status_code == 200, yanit.text

    komsu = (await _boq_satirlari(client, admin_headers, ayna_kurulum["site_id"]))[
        str(ayna_kurulum["komsu_boq_id"])
    ]
    assert komsu["code"] == IKINCI_KOD
    assert Decimal(komsu["unit_price"]) == IKINCI_FIYAT


@pytest.mark.asyncio
async def test_baska_projenin_santiyesindeki_satir_etkilenmez(client, admin_headers, ayna_kurulum):
    """Kapsam = TB4/B2 otorite kümesi: projenin şantiyeleri. Devredilmiş bir

    şantiyede kalmış kopya, projenin sözleşmesi tarafından artık yönetilmez.
    """
    yanit = await _patch_kalem(
        client,
        admin_headers,
        ayna_kurulum["item_id"],
        {"unit_price": str(YENI_FIYAT), "code": YENI_KOD},
    )
    assert yanit.status_code == 200, yanit.text

    yabanci = (await _boq_satirlari(client, admin_headers, ayna_kurulum["yabanci_site_id"]))[
        str(ayna_kurulum["yabanci_boq_id"])
    ]
    assert yabanci["code"] == ESKI_KOD
    assert Decimal(yabanci["unit_price"]) == ESKI_FIYAT


@pytest.mark.asyncio
async def test_audit_detayinda_tazelenen_satir_sayisi_gorunur(
    client, admin_headers, db_session, ayna_kurulum
):
    yanit = await _patch_kalem(
        client, admin_headers, ayna_kurulum["item_id"], {"unit_price": str(YENI_FIYAT)}
    )
    assert yanit.status_code == 200, yanit.text

    guncelleme = [m for m in await _audit_metinleri(db_session) if "poz kalemi güncellendi" in m]
    assert len(guncelleme) == 1, guncelleme
    assert "1 BOQ satırı tazelendi" in guncelleme[0]


@pytest.mark.asyncio
async def test_tazeleme_yoksa_audit_metni_degismez(client, admin_headers, db_session, ayna_kurulum):
    yanit = await _patch_kalem(
        client, admin_headers, ayna_kurulum["dagitimsiz_item_id"], {"unit_price": "1234.00"}
    )
    assert yanit.status_code == 200, yanit.text

    guncelleme = [m for m in await _audit_metinleri(db_session) if "poz kalemi güncellendi" in m]
    assert len(guncelleme) == 1, guncelleme
    assert "tazelendi" not in guncelleme[0]


@pytest.mark.asyncio
async def test_ayna_kodu_santiyede_dolu_ise_alan_ozel_409(
    client, admin_headers, seeded_db, ayna_kurulum
):
    """Tazeleme `uq_boq_items_site_code`'a çarpacaksa çakışma YAZMADAN ÖNCE yakalanır.

    Genel `IntegrityError → 409` yedeği "Veri bütünlüğü hatası" der; korkuluk
    olmadan kullanıcı hangi alanın çakıştığını öğrenemez ve işlem zaten
    kirlenmiş olur (`core/errors.py` deseni: açık SELECT ile ÖNCE yakala).
    """
    await _boq_satiri(
        seeded_db,
        ayna_kurulum["site_id"],
        None,
        code=YENI_KOD,
        quantity=Decimal("5.000"),
        unit_price=Decimal("100.00"),
    )

    yanit = await _patch_kalem(client, admin_headers, ayna_kurulum["item_id"], {"code": YENI_KOD})
    assert yanit.status_code == 409, yanit.text
    assert yanit.json()["detail"] == BOQ_CODE_TAKEN_IN_SITE
