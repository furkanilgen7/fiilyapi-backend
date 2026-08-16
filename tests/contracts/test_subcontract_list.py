"""TB2 T1 — `GET /subcontractor-contracts` taşeron sözleşmesi liste ucu (spec §1 U1).

İşveren `/contracts` liste ucunun deseninin aynısı: `contracts:view` YETKİYİ,
`projects.service.visible_projects` KAPSAMI belirler — görünmeyen projenin
sözleşmesi listede ÇIKMAZ. Sayfalama YOK (mevcut liste uçları deseni),
sıralama deterministik (`contract_no`, sonra `id`).
"""

import uuid
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.modules.contracts.models import (
    ContractStatus,
    Subcontractor,
    SubcontractorContract,
    SubcontractorContractItem,
)
from app.modules.projects.models import Project
from app.modules.sites.models import Site
from app.modules.subcontractor_progress_payments.models import (
    SubcontractorPaymentStatus,
    SubcontractorProgressPayment,
    SubcontractorProgressPaymentLine,
)
from app.modules.users.models import User

UC = "/subcontractor-contracts"
BIRLESIK_UC = "/contracts?type=subcontractor"


@pytest.fixture
async def kayit_sahibi(seeded_db, user_factory) -> uuid.UUID:
    """`created_by` için bağımsız kullanıcı — `admin_headers`'a bağlanmaz:
    yetki/kapsam testleri admin oturumu açmadan da kayıt kurabilmeli."""
    email = "kurucu@tb2-subcontract-list.co"
    await user_factory(email=email, password="parola1234", role_key="system_admin")
    user = (await seeded_db.execute(select(User).where(User.email == email))).scalar_one()
    return user.id


async def _subcontractor(session, name: str) -> Subcontractor:
    sub = Subcontractor(name=name)
    session.add(sub)
    await session.flush()
    return sub


async def _site(session, project: Project, *, code: str, name: str) -> Site:
    site = Site(project_id=project.id, code=code, name=name)
    session.add(site)
    await session.flush()
    return site


async def _contract(
    session, project: Project, created_by: uuid.UUID, **kwargs
) -> SubcontractorContract:
    contract = SubcontractorContract(project_id=project.id, created_by=created_by, **kwargs)
    session.add(contract)
    await session.flush()
    return contract


@pytest.fixture
async def kayitlar(seeded_db, ornek_proje, gorunmeyen_proje, kayit_sahibi) -> dict:
    """Görünür projede iki sözleşme (biri şantiyeli, biri proje geneli) +
    görünmeyen projede bir sözleşme."""
    sub_a = await _subcontractor(seeded_db, "Alfa Kalıp Ltd.")
    sub_b = await _subcontractor(seeded_db, "Beta Sıva A.Ş.")
    site = await _site(seeded_db, ornek_proje, code="SNT-TB2", name="Merkez Şantiye")
    santiyeli = await _contract(
        seeded_db,
        ornek_proje,
        kayit_sahibi,
        site_id=site.id,
        subcontractor_id=sub_a.id,
        subcontractor_name=sub_a.name,
        work_category="Kalıp",
        contract_no="TSD-2026-001",
        status=ContractStatus.active,
        is_draft=False,
    )
    proje_geneli = await _contract(
        seeded_db,
        ornek_proje,
        kayit_sahibi,
        site_id=None,
        subcontractor_id=sub_b.id,
        subcontractor_name=sub_b.name,
        work_category="Sıva",
        contract_no="TSD-2026-002",
        status=ContractStatus.on_hold,
        is_draft=True,
    )
    gizli = await _contract(
        seeded_db,
        gorunmeyen_proje,
        kayit_sahibi,
        contract_no="TSD-2026-999",
        subcontractor_name="Gizli Taşeron",
        status=ContractStatus.active,
        is_draft=False,
    )
    return {
        "site": site,
        "santiyeli": santiyeli,
        "proje_geneli": proje_geneli,
        "gizli": gizli,
    }


async def test_liste_secim_alanlarini_doner(
    client: AsyncClient, admin_headers: dict[str, str], kayitlar: dict, ornek_proje: Project
) -> None:
    yanit = await client.get(UC, headers=admin_headers)

    assert yanit.status_code == 200, yanit.text
    items = yanit.json()["items"]
    satir = next(k for k in items if k["id"] == str(kayitlar["santiyeli"].id))
    assert satir == {
        "id": str(kayitlar["santiyeli"].id),
        "contract_no": "TSD-2026-001",
        "subcontractor_name": "Alfa Kalıp Ltd.",
        "work_category": "Kalıp",
        "project_id": str(ornek_proje.id),
        "project_name": ornek_proje.name,
        "site_id": str(kayitlar["site"].id),
        "site_name": "Merkez Şantiye",
        "status": ContractStatus.active.value,
        "is_draft": False,
    }
    # Proje geneli sözleşmede şantiye bağı YOK — ad da NULL döner (K4).
    genel = next(k for k in items if k["id"] == str(kayitlar["proje_geneli"].id))
    assert genel["site_id"] is None
    assert genel["site_name"] is None
    assert genel["is_draft"] is True


async def test_gorunmeyen_proje_sozlesmesi_listede_yok(
    client: AsyncClient, kisitli_headers: dict[str, str], kayitlar: dict
) -> None:
    """IDOR: kapsam dışı projenin sözleşmesi hiç ÇEKİLMEZ (spec §1 U1)."""
    yanit = await client.get(UC, headers=kisitli_headers)

    assert yanit.status_code == 200, yanit.text
    kimlikler = {k["id"] for k in yanit.json()["items"]}
    assert str(kayitlar["gizli"].id) not in kimlikler
    assert str(kayitlar["santiyeli"].id) in kimlikler


async def test_gorunmeyen_proje_project_id_filtresiyle_de_sizmaz(
    client: AsyncClient, kisitli_headers: dict[str, str], kayitlar: dict, gorunmeyen_proje: Project
) -> None:
    """Kapsam süzgeci filtreyle DELİNMEZ: boş liste döner, 200."""
    yanit = await client.get(f"{UC}?project_id={gorunmeyen_proje.id}", headers=kisitli_headers)

    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["items"] == []


async def test_project_id_filtresi(
    client: AsyncClient, admin_headers: dict[str, str], kayitlar: dict, ornek_proje: Project
) -> None:
    yanit = await client.get(f"{UC}?project_id={ornek_proje.id}", headers=admin_headers)

    assert yanit.status_code == 200, yanit.text
    projeler = {k["project_id"] for k in yanit.json()["items"]}
    assert projeler == {str(ornek_proje.id)}


async def test_site_id_filtresi_proje_geneli_sozlesmeyi_getirmez(
    client: AsyncClient, admin_headers: dict[str, str], kayitlar: dict
) -> None:
    """`site_id=NULL` sözleşme, şantiye filtresiyle GELMEZ (SD S5 tek-anlamlılık)."""
    yanit = await client.get(f"{UC}?site_id={kayitlar['site'].id}", headers=admin_headers)

    assert yanit.status_code == 200, yanit.text
    kimlikler = [k["id"] for k in yanit.json()["items"]]
    assert kimlikler == [str(kayitlar["santiyeli"].id)]


async def test_status_filtresi(
    client: AsyncClient, admin_headers: dict[str, str], kayitlar: dict
) -> None:
    yanit = await client.get(f"{UC}?status=on_hold", headers=admin_headers)

    assert yanit.status_code == 200, yanit.text
    kimlikler = [k["id"] for k in yanit.json()["items"]]
    assert kimlikler == [str(kayitlar["proje_geneli"].id)]


async def test_q_taseron_adinda_arar(
    client: AsyncClient, admin_headers: dict[str, str], kayitlar: dict
) -> None:
    """Arama büyük/küçük harf duyarsız (ILIKE `%q%`, mevcut desen)."""
    yanit = await client.get(f"{UC}?q=alfa", headers=admin_headers)

    assert yanit.status_code == 200, yanit.text
    kimlikler = [k["id"] for k in yanit.json()["items"]]
    assert kimlikler == [str(kayitlar["santiyeli"].id)]


async def test_q_sozlesme_nosunda_arar(
    client: AsyncClient, admin_headers: dict[str, str], kayitlar: dict
) -> None:
    yanit = await client.get(f"{UC}?q=2026-002", headers=admin_headers)

    assert yanit.status_code == 200, yanit.text
    kimlikler = [k["id"] for k in yanit.json()["items"]]
    assert kimlikler == [str(kayitlar["proje_geneli"].id)]


async def test_siralama_deterministik(
    client: AsyncClient,
    admin_headers: dict[str, str],
    kayitlar: dict,
    seeded_db,
    ornek_proje,
    kayit_sahibi: uuid.UUID,
) -> None:
    """`contract_no` ARTAN — ekleme sırasından bağımsız."""
    await _contract(
        seeded_db,
        ornek_proje,
        kayit_sahibi,
        contract_no="TSD-2026-000",
        subcontractor_name="Sıfırıncı",
        status=ContractStatus.active,
        is_draft=False,
    )

    yanit = await client.get(UC, headers=admin_headers)

    assert yanit.status_code == 200, yanit.text
    nolar = [k["contract_no"] for k in yanit.json()["items"]]
    assert nolar == sorted(nolar)
    assert nolar[0] == "TSD-2026-000"


async def test_yetkisiz_rol_403(
    client: AsyncClient, site_chief_headers: dict[str, str], kayitlar: dict
) -> None:
    yanit = await client.get(UC, headers=site_chief_headers)
    assert yanit.status_code == 403, yanit.text


async def test_liste_yolu_detay_ucuyla_carpismaz(
    client: AsyncClient, admin_headers: dict[str, str], kayitlar: dict
) -> None:
    """ROTA SIRASI BEKÇİSİ: statik `/subcontractor-contracts` ile şablonlu
    `/subcontractor-contracts/{contract_id}` birlikte çözülmeli — liste ucu
    şablonlu yolu gölgelememeli (ve tersi).

    NOT (mutasyon denetimi, TB2 T1): bu ÇİFT için gölgeleme yapısal olarak
    imkânsızdır — yol parça sayıları farklı (1'e 2), bu yüzden liste ucunu
    detay ucundan SONRAYA taşıyan mutasyon testi KIRMIZI YAPMADI. Bekçi yine
    de tutulur: ileride `/subcontractor-contracts/list` gibi ikinci parçalı
    STATİK bir yol eklenirse (`/summary` ucundaki gerçek tuzak) sıra hatası
    burada patlar."""
    liste = await client.get(UC, headers=admin_headers)
    assert liste.status_code == 200, liste.text

    detay = await client.get(f"{UC}/{kayitlar['santiyeli'].id}", headers=admin_headers)
    assert detay.status_code == 200, detay.text
    assert detay.json()["contract_no"] == "TSD-2026-001"


async def test_bilinmeyen_status_422(
    client: AsyncClient, admin_headers: dict[str, str], kayitlar: dict
) -> None:
    yanit = await client.get(f"{UC}?status=hayali", headers=admin_headers)
    assert yanit.status_code == 422, yanit.text


async def test_taseron_bedeli_ve_hakedis_alanlari_bu_uctan_donmez(
    client: AsyncClient, admin_headers: dict[str, str], kayitlar: dict
) -> None:
    """Seçim ucu bilinçli olarak DAR: bedel/hakediş toplamı taşımaz — birleşik
    `/contracts?type=subcontractor` ucunun işidir (spec §2 kapsam dışı)."""
    yanit = await client.get(UC, headers=admin_headers)

    assert yanit.status_code == 200, yanit.text
    satir = yanit.json()["items"][0]
    assert "amount" not in satir
    assert "progress_pct" not in satir


async def test_birlesik_liste_ucu_degismedi(
    client: AsyncClient, admin_headers: dict[str, str], kayitlar: dict
) -> None:
    """Geriye uyum: mevcut `/contracts?type=subcontractor` yanıtı ETKİLENMEZ."""
    yanit = await client.get("/contracts?type=subcontractor", headers=admin_headers)

    assert yanit.status_code == 200, yanit.text
    govde = yanit.json()
    assert set(govde) == {"summary", "items"}
    assert Decimal(govde["items"][0]["amount"]) == Decimal("0.00")


# --- TB3 T2: sayfalama (`limit`/`offset`/`total`) -----------------------------
# Desen kaynağı: `subcontractor_progress_payments` liste ucu
# (`schemas.SubcontractorProgressPaymentListResponse` = items/total/limit/offset,
# `router.py` L65-66 = `Query(ge=1, le=200)` / `Query(ge=0)`).


@pytest.fixture
async def cok_sozlesme(seeded_db, ornek_proje, kayit_sahibi) -> list[str]:
    """Görünür projede 5 sözleşme, `contract_no` sırası belirli."""
    numaralar = [f"TSD-2027-{sira:03d}" for sira in range(1, 6)]
    for numara in numaralar:
        await _contract(
            seeded_db,
            ornek_proje,
            kayit_sahibi,
            contract_no=numara,
            subcontractor_name=f"Sayfalama {numara}",
            status=ContractStatus.active,
            is_draft=False,
        )
    return numaralar


async def test_parametresiz_cagri_varsayilan_sayfalama_alanlarini_doner(
    client: AsyncClient, admin_headers: dict[str, str], kayitlar: dict
) -> None:
    """Additive: zarf `items`in yanına `total`/`limit`/`offset` ekler."""
    yanit = await client.get(UC, headers=admin_headers)

    assert yanit.status_code == 200, yanit.text
    govde = yanit.json()
    assert set(govde) == {"items", "total", "limit", "offset"}
    assert govde["limit"] == 50
    assert govde["offset"] == 0
    assert govde["total"] == len(govde["items"])


async def test_parametresiz_cagri_oge_alanlari_degismedi(
    client: AsyncClient, admin_headers: dict[str, str], kayitlar: dict
) -> None:
    """GERİYE UYUM: F-TH seçim adımının okuduğu alanlar BİREBİR aynı."""
    yanit = await client.get(UC, headers=admin_headers)

    assert yanit.status_code == 200, yanit.text
    satir = next(k for k in yanit.json()["items"] if k["id"] == str(kayitlar["santiyeli"].id))
    assert set(satir) == {
        "id",
        "contract_no",
        "subcontractor_name",
        "work_category",
        "project_id",
        "project_name",
        "site_id",
        "site_name",
        "status",
        "is_draft",
    }


async def test_limit_uygulanir_total_limitten_bagimsiz(
    client: AsyncClient, admin_headers: dict[str, str], kayitlar: dict, cok_sozlesme: list[str]
) -> None:
    tamami = await client.get(UC, headers=admin_headers)
    assert tamami.status_code == 200, tamami.text
    beklenen_total = tamami.json()["total"]
    assert beklenen_total >= 5

    yanit = await client.get(f"{UC}?limit=2", headers=admin_headers)

    assert yanit.status_code == 200, yanit.text
    govde = yanit.json()
    assert len(govde["items"]) == 2
    assert govde["limit"] == 2
    assert govde["total"] == beklenen_total


async def test_offset_deterministik_sayfa_dondurur(
    client: AsyncClient, admin_headers: dict[str, str], kayitlar: dict, cok_sozlesme: list[str]
) -> None:
    tamami = await client.get(f"{UC}?q=TSD-2027", headers=admin_headers)
    assert tamami.status_code == 200, tamami.text
    sirali = [k["contract_no"] for k in tamami.json()["items"]]
    assert sirali == cok_sozlesme

    sayfa = await client.get(f"{UC}?q=TSD-2027&limit=2&offset=2", headers=admin_headers)

    assert sayfa.status_code == 200, sayfa.text
    govde = sayfa.json()
    assert [k["contract_no"] for k in govde["items"]] == sirali[2:4]
    assert govde["offset"] == 2
    assert govde["total"] == 5


async def test_limit_tavani_asilirsa_422(
    client: AsyncClient, admin_headers: dict[str, str], kayitlar: dict
) -> None:
    """Referans desenin AYNISI: `Query(ge=1, le=200)` -> tavan aşımı 422."""
    assert (await client.get(f"{UC}?limit=201", headers=admin_headers)).status_code == 422
    assert (await client.get(f"{UC}?limit=0", headers=admin_headers)).status_code == 422
    assert (await client.get(f"{UC}?offset=-1", headers=admin_headers)).status_code == 422
    tavan = await client.get(f"{UC}?limit=200", headers=admin_headers)
    assert tavan.status_code == 200, tavan.text
    assert tavan.json()["limit"] == 200


async def test_total_yalniz_gorulebilen_kayitlari_sayar(
    client: AsyncClient, kisitli_headers: dict[str, str], kayitlar: dict
) -> None:
    """IDOR: görünürlük süzgeci sayfalamadan ÖNCE — `total` kapsam dışını SAYMAZ."""
    yanit = await client.get(UC, headers=kisitli_headers)

    assert yanit.status_code == 200, yanit.text
    govde = yanit.json()
    assert govde["total"] == 2
    assert str(kayitlar["gizli"].id) not in {k["id"] for k in govde["items"]}


async def test_total_filtrelenmis_kumeyi_sayar(
    client: AsyncClient, admin_headers: dict[str, str], kayitlar: dict, cok_sozlesme: list[str]
) -> None:
    yanit = await client.get(f"{UC}?q=TSD-2027&limit=1", headers=admin_headers)

    assert yanit.status_code == 200, yanit.text
    govde = yanit.json()
    assert govde["total"] == 5
    assert len(govde["items"]) == 1


# --- TH-SUM T3: `/contracts?type=subcontractor` KPI şeridi hakediş toplamı ----
#
# `summary.progress_payment_total` taşeron sekmesinde `None` DEĞİL: sözleşme
# başına kümülatif brüt (`approved|paid`) toplanır
# (`subcontractor_progress_payments.summary.cumulative_gross_by_contracts`).
# Kurulumdaki tutarlar bilerek BİRBİRİNDEN FARKLIDIR — eşit sayılar toplama,
# anahtar karışması ve kapsam sızıntısı hatalarını maskeler.


async def _hakedis(
    session,
    contract: SubcontractorContract,
    created_by: uuid.UUID,
    *,
    sequence_no: int,
    status: SubcontractorPaymentStatus,
    unit_price: Decimal,
    quantity: Decimal,
) -> SubcontractorProgressPayment:
    """Tek satırlı hakediş kurar; brüt = `unit_price × 1.000 × quantity`.

    `contract_item_id` NULL bırakılır (model kolonu `nullable`, kısmi tekil
    indeks yalnız NOT NULL satırları kapsar): bu testlerin ölçtüğü şey satır
    bağı DEĞİL, KPI şeridine giren brütün kaynağıdır.
    """
    payment = SubcontractorProgressPayment(
        contract_id=contract.id,
        project_id=contract.project_id,
        sequence_no=sequence_no,
        status=status,
        period_year=2026,
        period_month=7,
        vat_pct=Decimal("20"),
        advance_pct=Decimal("0"),
        retainage_pct=Decimal("0"),
        created_by=created_by,
    )
    payment.lines = [
        SubcontractorProgressPaymentLine(
            code="THS-01",
            description="KPI test pozu",
            unit="m³",
            contract_unit_price=unit_price,
            coefficient=Decimal("1.000"),
            quantity=quantity,
            sort_order=0,
        )
    ]
    session.add(payment)
    await session.flush()
    return payment


def _toplam(govde: dict) -> Decimal:
    ham = govde["summary"]["progress_payment_total"]
    assert ham is not None, "taşeron sekmesinde hakediş toplamı ASLA null olmaz (K4)"
    return Decimal(ham)


@pytest.fixture
async def hakedisli_sozlesmeler(seeded_db, ornek_proje, kayit_sahibi) -> dict:
    """Görünür projede iki taşeron sözleşmesi; ikisinin de onaylı hakedişi VAR
    ve brütleri FARKLI (A = 215.000,00 · B = 5.550,00 → toplam 220.550,00)."""
    a = await _contract(
        seeded_db,
        ornek_proje,
        kayit_sahibi,
        contract_no="TSD-SUM-001",
        subcontractor_name="Toplam A",
        status=ContractStatus.active,
        is_draft=False,
    )
    b = await _contract(
        seeded_db,
        ornek_proje,
        kayit_sahibi,
        contract_no="TSD-SUM-002",
        subcontractor_name="Toplam B",
        status=ContractStatus.active,
        is_draft=False,
    )
    await _hakedis(
        seeded_db,
        a,
        kayit_sahibi,
        sequence_no=1,
        status=SubcontractorPaymentStatus.approved,
        unit_price=Decimal("21500"),
        quantity=Decimal("10"),
    )
    await _hakedis(
        seeded_db,
        b,
        kayit_sahibi,
        sequence_no=1,
        status=SubcontractorPaymentStatus.paid,
        unit_price=Decimal("1850"),
        quantity=Decimal("3"),
    )
    return {"a": a, "b": b}


async def test_birlesik_ozet_iki_sozlesmenin_hakedis_toplamini_verir(
    client: AsyncClient, admin_headers: dict[str, str], hakedisli_sozlesmeler: dict
) -> None:
    yanit = await client.get(BIRLESIK_UC, headers=admin_headers)

    assert yanit.status_code == 200, yanit.text
    # 215.000,00 + 5.550,00 — tek sözleşmenin brütü tek başına YETMEZ.
    assert _toplam(yanit.json()) == Decimal("220550.00")


async def test_hakedissiz_sozlesmede_toplam_sifir_null_degil(
    client: AsyncClient, admin_headers: dict[str, str], kayitlar: dict
) -> None:
    """K4-a: sözleşme VAR, hiç hakediş YOK → `0.00`. `None` dönerse frontend
    "modül henüz yazılmadı" tooltip'ini basmaya devam eder."""
    yanit = await client.get(BIRLESIK_UC, headers=admin_headers)

    assert yanit.status_code == 200, yanit.text
    govde = yanit.json()
    assert govde["items"], "kurulum bozuk: sözleşme listesi boş olmamalı"
    assert govde["summary"]["progress_payment_total"] is not None
    assert _toplam(govde) == Decimal("0.00")


async def test_hic_sozlesme_yokken_toplam_sifir(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    """K4-b: boş liste de `0.00` üretir (işveren dalının boş `rows` davranışı)."""
    yanit = await client.get(BIRLESIK_UC, headers=admin_headers)

    assert yanit.status_code == 200, yanit.text
    govde = yanit.json()
    assert govde["items"] == []
    assert govde["summary"]["progress_payment_total"] is not None
    assert _toplam(govde) == Decimal("0.00")


async def test_taslak_ve_onay_bekleyen_hakedis_toplama_girmez(
    client: AsyncClient,
    admin_headers: dict[str, str],
    seeded_db,
    ornek_proje: Project,
    kayit_sahibi: uuid.UUID,
) -> None:
    """K3: aynı sözleşmede onaylı + taslak + onay bekleyen; üçünün brütü de
    FARKLI, yalnız onaylının brütü toplama girer."""
    sozlesme = await _contract(
        seeded_db,
        ornek_proje,
        kayit_sahibi,
        contract_no="TSD-SUM-010",
        subcontractor_name="Statü Karışımı",
        status=ContractStatus.active,
        is_draft=False,
    )
    await _hakedis(  # 10 × 21.500 = 215.000,00 (SAYILIR)
        seeded_db,
        sozlesme,
        kayit_sahibi,
        sequence_no=1,
        status=SubcontractorPaymentStatus.approved,
        unit_price=Decimal("21500"),
        quantity=Decimal("10"),
    )
    await _hakedis(  # 7 × 21.500 = 150.500,00 (SAYILMAZ)
        seeded_db,
        sozlesme,
        kayit_sahibi,
        sequence_no=2,
        status=SubcontractorPaymentStatus.draft,
        unit_price=Decimal("21500"),
        quantity=Decimal("7"),
    )
    await _hakedis(  # 2 × 1.850 = 3.700,00 (SAYILMAZ)
        seeded_db,
        sozlesme,
        kayit_sahibi,
        sequence_no=3,
        status=SubcontractorPaymentStatus.pending_approval,
        unit_price=Decimal("1850"),
        quantity=Decimal("2"),
    )

    yanit = await client.get(BIRLESIK_UC, headers=admin_headers)

    assert yanit.status_code == 200, yanit.text
    assert _toplam(yanit.json()) == Decimal("215000.00")


async def test_gorunmeyen_projenin_hakedisi_toplama_sizmaz(
    client: AsyncClient,
    kisitli_headers: dict[str, str],
    seeded_db,
    ornek_proje: Project,
    gorunmeyen_proje: Project,
    kayit_sahibi: uuid.UUID,
) -> None:
    """Kapsam: görünmeyen projedeki sözleşmenin onaylı hakedişi (500.000,00 —
    görünürden BÜYÜK ve FARKLI) KPI şeridine SIZMAMALI."""
    gorunur = await _contract(
        seeded_db,
        ornek_proje,
        kayit_sahibi,
        contract_no="TSD-SUM-020",
        subcontractor_name="Görünür Taşeron",
        status=ContractStatus.active,
        is_draft=False,
    )
    gizli = await _contract(
        seeded_db,
        gorunmeyen_proje,
        kayit_sahibi,
        contract_no="TSD-SUM-021",
        subcontractor_name="Gizli Taşeron",
        status=ContractStatus.active,
        is_draft=False,
    )
    await _hakedis(  # 3 × 1.850 = 5.550,00
        seeded_db,
        gorunur,
        kayit_sahibi,
        sequence_no=1,
        status=SubcontractorPaymentStatus.approved,
        unit_price=Decimal("1850"),
        quantity=Decimal("3"),
    )
    await _hakedis(  # 20 × 25.000 = 500.000,00
        seeded_db,
        gizli,
        kayit_sahibi,
        sequence_no=1,
        status=SubcontractorPaymentStatus.approved,
        unit_price=Decimal("25000"),
        quantity=Decimal("20"),
    )

    yanit = await client.get(BIRLESIK_UC, headers=kisitli_headers)

    assert yanit.status_code == 200, yanit.text
    govde = yanit.json()
    assert all(k["id"] != str(gizli.id) for k in govde["items"])
    assert any(k["id"] == str(gorunur.id) for k in govde["items"])
    assert _toplam(govde) == Decimal("5550.00")


async def test_project_id_suzgeci_toplami_da_daraltir(
    client: AsyncClient,
    admin_headers: dict[str, str],
    seeded_db,
    ornek_proje: Project,
    gorunmeyen_proje: Project,
    kayit_sahibi: uuid.UUID,
) -> None:
    """İKİ SAYAÇ AYRI ŞEYLERDİR: `total_amount` sözleşme KALEMLERİNDEN,
    `progress_payment_total` HAKEDİŞLERDEN gelir. Kurulum ikisini bilerek
    ayrıştırır (5.000,00 ↔ 215.000,00) — eşit olsalardı test hiçbir şey
    kanıtlamazdı."""
    icerideki = await _contract(
        seeded_db,
        ornek_proje,
        kayit_sahibi,
        contract_no="TSD-SUM-030",
        subcontractor_name="Süzgeç İçi",
        status=ContractStatus.active,
        is_draft=False,
    )
    disaridaki = await _contract(
        seeded_db,
        gorunmeyen_proje,
        kayit_sahibi,
        contract_no="TSD-SUM-031",
        subcontractor_name="Süzgeç Dışı",
        status=ContractStatus.active,
        is_draft=False,
    )
    seeded_db.add(
        SubcontractorContractItem(
            contract_id=icerideki.id,
            code="01.001",
            description="Kazı",
            unit="m3",
            quantity=Decimal("100"),
            unit_price=Decimal("50.00"),
        )
    )
    await seeded_db.flush()
    await _hakedis(  # 10 × 21.500 = 215.000,00
        seeded_db,
        icerideki,
        kayit_sahibi,
        sequence_no=1,
        status=SubcontractorPaymentStatus.approved,
        unit_price=Decimal("21500"),
        quantity=Decimal("10"),
    )
    await _hakedis(  # 8 × 1.850 = 14.800,00 — süzgeç dışı, toplama GİRMEZ
        seeded_db,
        disaridaki,
        kayit_sahibi,
        sequence_no=1,
        status=SubcontractorPaymentStatus.approved,
        unit_price=Decimal("1850"),
        quantity=Decimal("8"),
    )

    suzgecsiz = await client.get(BIRLESIK_UC, headers=admin_headers)
    assert suzgecsiz.status_code == 200, suzgecsiz.text
    assert _toplam(suzgecsiz.json()) == Decimal("229800.00")

    yanit = await client.get(f"{BIRLESIK_UC}&project_id={ornek_proje.id}", headers=admin_headers)

    assert yanit.status_code == 200, yanit.text
    govde = yanit.json()
    assert [k["id"] for k in govde["items"]] == [str(icerideki.id)]
    assert Decimal(govde["summary"]["total_amount"]) == Decimal("5000.00")
    assert _toplam(govde) == Decimal("215000.00")
