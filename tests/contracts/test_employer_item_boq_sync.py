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

T3b (S7/S8, kullanıcı onayı 2026-08-09) iki şeyi daha çiviler:

* ayna küme DÖRTTÜR (`code`/`description`/`unit`/`unit_price`) ve `MIRRORED_ITEM_FIELDS`
  TEK KAYNAKTIR — kümeye bir alan ENJEKTE edilir ve hem senkron tazelemenin hem
  dağıtımın relink yolunun onu yansıtması beklenir. Yollardan biri kendi elle
  yazılmış listesine dönerse enjeksiyon o yolda etkisiz kalır ve test kırmızı olur;
* kod çakışmasının 409 gövdesi ÇARPILAN şantiyenin adını ve kodu taşır.
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.modules.audit.models import AuditLog
from app.modules.boq.models import BoqGroup, BoqItem
from app.modules.contracts import service
from app.modules.contracts.guards import BOQ_CODE_TAKEN_IN_SITE
from app.modules.contracts.models import EmployerContractGroup, EmployerContractItem
from app.modules.projects.models import ProjectContract
from app.modules.sites.models import Site

GRUP_ADI = "A — Betonarme İşleri"
SANTIYE_ADI = "Şantiye A"
IKINCI_SANTIYE = "Şantiye B"

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
UCUNCU_SIRA = 2

YENI_ACIKLAMA = "Nervürlü demir donatı (B500C)"
YENI_BIRIM = "Kg"

# S7 tek-kaynak kilidinin ENJEKTE ettiği alan: gerçek kümede YOKTUR ama iki
# modelde de bulunur — sabit fiilen okunuyorsa iki yolda da yansır.
ENJEKTE_SIRA = 7


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
    site = Site(project_id=project.id, code="SNT-B3A", name=SANTIYE_ADI)
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
        project.id, group.id, code=UCUNCU_KOD, unit_price=UCUNCU_FIYAT, sort_order=UCUNCU_SIRA
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
    assert yanit.json()["detail"].startswith(BOQ_CODE_TAKEN_IN_SITE)


# --- S8: 409 gövdesi ÇARPILAN ŞANTİYE + KODU taşır (kullanıcı onayı 2026-08-09) ---


@pytest.mark.asyncio
async def test_kod_cakismasi_409_santiye_adini_ve_kodu_bildirir(
    client, admin_headers, seeded_db, ayna_kurulum
):
    """Genel bütünlük metni YETMEZ: kalem birden çok şantiyeye dağıtılmış olabilir

    ve PATCH ekranı BOQ'yu göstermez — kullanıcı hangi şantiyedeki hangi
    numaranın engellediğini gövdeden okumalıdır (S8). `quantity_exceeds_quota`
    (taşeron hakedişi) ile aynı üslup: sabit metin + " · " ile ayrılmış bağlam.
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
    detay = yanit.json()["detail"]
    assert SANTIYE_ADI in detay, detay
    assert YENI_KOD in detay, detay


@pytest.mark.asyncio
async def test_kod_cakismasi_409_baska_santiyenin_adini_vermez(
    client, admin_headers, seeded_db, ayna_kurulum
):
    """Bildirilen şantiye ÇARPILAN şantiyedir — "projenin ilk şantiyesi" değil.

    Çakışma B şantiyesindeyken A'nın adını basmak, kullanıcıyı temiz bir
    şantiyede numara aramaya gönderirdi.
    """
    ikinci_site = Site(project_id=ayna_kurulum["project_id"], code="SNT-B3B", name=IKINCI_SANTIYE)
    seeded_db.add(ikinci_site)
    await seeded_db.flush()
    await _boq_satiri(
        seeded_db,
        ikinci_site.id,
        ayna_kurulum["item_id"],
        code=ESKI_KOD,
        quantity=Decimal("40.000"),
        unit_price=ESKI_FIYAT,
    )
    await _boq_satiri(
        seeded_db,
        ikinci_site.id,
        None,
        code=YENI_KOD,
        quantity=Decimal("5.000"),
        unit_price=Decimal("100.00"),
    )

    yanit = await _patch_kalem(client, admin_headers, ayna_kurulum["item_id"], {"code": YENI_KOD})
    assert yanit.status_code == 409, yanit.text
    detay = yanit.json()["detail"]
    assert IKINCI_SANTIYE in detay, detay
    assert SANTIYE_ADI not in detay, detay


# --- S7: ayna alan kümesi DÖRTTÜR ve TEK KAYNAKTIR ---


@pytest.mark.asyncio
async def test_aciklama_ve_birim_degisimi_ayna_boq_satirina_yansir(
    client, admin_headers, ayna_kurulum
):
    """S7: `description`/`unit` de aynadır — dağıtımın relink yolu bu iki alanı

    zaten sözleşmeden kopyalıyordu; senkron tazelemede dışarıda bırakmak aynı
    bayatlığın yarısını açık bırakırdı.
    """
    yanit = await _patch_kalem(
        client,
        admin_headers,
        ayna_kurulum["item_id"],
        {"description": YENI_ACIKLAMA, "unit": YENI_BIRIM},
    )
    assert yanit.status_code == 200, yanit.text

    ayna = (await _boq_satirlari(client, admin_headers, ayna_kurulum["site_id"]))[
        str(ayna_kurulum["ayna_boq_id"])
    ]
    assert ayna["description"] == YENI_ACIKLAMA
    assert ayna["unit"] == YENI_BIRIM
    assert Decimal(ayna["quantity"]) == AYNA_MIKTAR  # miktara YİNE dokunulmaz


@pytest.mark.asyncio
async def test_ayna_alan_kumesi_senkron_yolunu_fiilen_yonetir(
    client, admin_headers, ayna_kurulum, monkeypatch
):
    """TEK KAYNAK kilidi (1/2): kümeye `sort_order` ENJEKTE edilir ve senkron

    tazeleme yolunun onu da yansıtması beklenir. Alan listesi bu yolda elle
    yazılmış olsaydı enjeksiyonun hiçbir etkisi olmaz, test kırmızı olurdu —
    "dört alan yansıyor" demek bunu kanıtlamazdı.
    """
    monkeypatch.setattr(
        service, "MIRRORED_ITEM_FIELDS", (*service.MIRRORED_ITEM_FIELDS, "sort_order")
    )

    yanit = await _patch_kalem(
        client, admin_headers, ayna_kurulum["item_id"], {"sort_order": ENJEKTE_SIRA}
    )
    assert yanit.status_code == 200, yanit.text

    ayna = (await _boq_satirlari(client, admin_headers, ayna_kurulum["site_id"]))[
        str(ayna_kurulum["ayna_boq_id"])
    ]
    assert ayna["sort_order"] == ENJEKTE_SIRA


@pytest.mark.asyncio
async def test_ayna_alan_kumesi_dagitim_relink_yolunu_fiilen_yonetir(
    client, admin_headers, seeded_db, ayna_kurulum, monkeypatch
):
    """TEK KAYNAK kilidi (2/2): AYNI enjeksiyon dağıtımın relink yolunda da

    görünmelidir. İki yol ayrı listelerden beslenirse (biri sabite uymayı
    bırakırsa) bu test kırmızı olur — S7'nin "tek kaynak" şartı budur.
    """
    monkeypatch.setattr(
        service, "MIRRORED_ITEM_FIELDS", (*service.MIRRORED_ITEM_FIELDS, "sort_order")
    )

    bagsiz = await _boq_satiri(
        seeded_db,
        ayna_kurulum["site_id"],
        None,
        code=UCUNCU_KOD,
        quantity=Decimal("5.000"),
        unit_price=Decimal("1.00"),
    )
    assert bagsiz.sort_order != UCUNCU_SIRA

    yanit = await client.put(
        f"/projects/{ayna_kurulum['project_id']}/contract/distribution",
        json={
            "allocations": [
                {
                    "contract_item_id": str(ayna_kurulum["dagitimsiz_item_id"]),
                    "site_id": str(ayna_kurulum["site_id"]),
                    "quantity": 12,
                }
            ]
        },
        headers=admin_headers,
    )
    assert yanit.status_code == 200, yanit.text

    satir = (await _boq_satirlari(client, admin_headers, ayna_kurulum["site_id"]))[str(bagsiz.id)]
    assert satir["sort_order"] == UCUNCU_SIRA
