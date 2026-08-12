"""İK-1 T4 — `GET /hr/documents/summary` (BT mockup birebir).

Spec: `docs/superpowers/specs/2026-08-12-ik1-personel-belge-design.md` §2, §3.

Bu paket ÜÇ farklı şeyi kanıtlar ve karıştırmaz:
1. **KPI/dağılım/liste SAYILARI** — sabit `today` ile durum sınırları deterministik.
2. **`missing` TANIMI** — yalnız AKTİF + YAYINDA personel, KPI toplamı yalnız
   ZORUNLU tipler; taslak/pasif personel `missing` ÜRETMEZ (ATLATMA senaryosu).
3. **N+1 önlemi** — sorgu sayısı 2 vs 10 personelde AYNI (aggrega, per-row SELECT yok).

Testler `create_all` şemasıyla koşar (migration DEĞİL) — belge tipleri migration
seed'idir, burada elle açılır. Durum türevi `status.py` TEK KAYNAĞIDIR; eşik (30
gün) burada tekrarlanmaz, `today` enjekte edilir.
"""

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.personnel import service
from app.modules.personnel.models import (
    Personnel,
    PersonnelDocument,
    PersonnelDocumentType,
)
from app.modules.projects.models import Project
from app.modules.site_diary.models import WorkerSource
from tests.conftest import test_engine

pytestmark = pytest.mark.asyncio

BUGUN = date(2026, 6, 15)


# --- yardımcılar -------------------------------------------------------------


async def _mk_personnel(
    db: AsyncSession,
    name: str,
    *,
    active: bool = True,
    draft: bool = False,
    project_id: uuid.UUID | None = None,
) -> Personnel:
    p = Personnel(
        full_name=name,
        source=WorkerSource.company,
        is_active=active,
        is_draft=draft,
        assigned_project_id=project_id,
    )
    db.add(p)
    await db.flush()
    return p


async def _mk_type(
    db: AsyncSession,
    name: str,
    *,
    mandatory: bool,
    validity: int | None = None,
    order: int = 0,
) -> PersonnelDocumentType:
    t = PersonnelDocumentType(
        name=name, is_mandatory=mandatory, validity_months=validity, sort_order=order
    )
    db.add(t)
    await db.flush()
    return t


async def _mk_doc(
    db: AsyncSession,
    personnel: Personnel,
    *,
    type_id: uuid.UUID | None = None,
    free_label: str | None = None,
    valid_until: date | None = None,
) -> PersonnelDocument:
    d = PersonnelDocument(
        personnel_id=personnel.id,
        type_id=type_id,
        free_label=free_label,
        valid_until=valid_until,
    )
    db.add(d)
    await db.flush()
    return d


# --- 1. KPI altın senaryosu --------------------------------------------------


async def test_bes_kpi_altin(seeded_db: AsyncSession) -> None:
    saglik = await _mk_type(seeded_db, "Sağlık Raporu", mandatory=True, validity=12, order=1)
    isg = await _mk_type(seeded_db, "İSG Eğitimi", mandatory=True, validity=36, order=2)
    diploma = await _mk_type(seeded_db, "Diploma", mandatory=False, order=3)

    a = await _mk_personnel(seeded_db, "A")
    b = await _mk_personnel(seeded_db, "B")
    await _mk_doc(seeded_db, a, type_id=saglik.id, valid_until=BUGUN + timedelta(days=100))  # valid
    await _mk_doc(
        seeded_db, b, type_id=saglik.id, valid_until=BUGUN + timedelta(days=10)
    )  # expiring
    await _mk_doc(
        seeded_db, a, type_id=diploma.id, valid_until=BUGUN - timedelta(days=5)
    )  # expired

    ozet = await service.build_hr_documents_summary(seeded_db, today=BUGUN)

    assert ozet.total_documents == 3
    assert ozet.valid == 1
    assert ozet.expiring == 1
    assert ozet.expired == 1
    # Sağlık: 2 aktif+yayın var, 2'si de sahip → 0 eksik. İSG: kimse yok → 2 eksik.
    # Diploma OPSİYONEL: eksiği (1) KPI'ya girmez. KPI missing = 0 + 2 = 2.
    assert ozet.missing == 2
    assert {t.type_id for t in ozet.by_type} == {saglik.id, isg.id, diploma.id}


# --- 2. `missing` TANIMI: yalnız aktif+yayın+zorunlu -------------------------


async def test_missing_taslak_personel_uretmez(seeded_db: AsyncSession) -> None:
    """ATLATMA: taslak personel `missing` tabanına GİRMEZ (spec §2/§3, §5 K1)."""
    isg = await _mk_type(seeded_db, "İSG Eğitimi", mandatory=True, validity=36, order=1)
    await _mk_personnel(seeded_db, "Yayında")  # aktif+yayın, İSG yok → 1 eksik
    taslak = await _mk_personnel(seeded_db, "Taslak", draft=True)
    # Taslak personelin bir belgesi bile OLSA sayaçlara girmemeli.
    await _mk_doc(seeded_db, taslak, type_id=isg.id, valid_until=BUGUN - timedelta(days=1))

    ozet = await service.build_hr_documents_summary(seeded_db, today=BUGUN)

    assert ozet.missing == 1  # yalnız yayındaki personel eksik sayılır
    assert ozet.total_documents == 0  # taslak personelin belgesi sayılmaz
    assert ozet.expired == 0
    isg_row = next(t for t in ozet.by_type if t.type_id == isg.id)
    assert isg_row.missing == 1


async def test_missing_pasif_personel_uretmez(seeded_db: AsyncSession) -> None:
    isg = await _mk_type(seeded_db, "İSG Eğitimi", mandatory=True, validity=36, order=1)
    await _mk_personnel(seeded_db, "Aktif")  # 1 eksik
    pasif = await _mk_personnel(seeded_db, "Pasif", active=False)
    await _mk_doc(seeded_db, pasif, type_id=isg.id, valid_until=BUGUN - timedelta(days=1))

    ozet = await service.build_hr_documents_summary(seeded_db, today=BUGUN)

    assert ozet.missing == 1
    assert ozet.total_documents == 0


async def test_missing_yalniz_zorunlu_tipler(seeded_db: AsyncSession) -> None:
    """Opsiyonel tip dağılımda GÖSTERİLİR ama KPI `missing` toplamına GİRMEZ."""
    await _mk_type(seeded_db, "Zorunlu", mandatory=True, order=1)
    opsiyonel = await _mk_type(seeded_db, "Opsiyonel", mandatory=False, order=2)
    await _mk_personnel(seeded_db, "Tek Kişi")

    ozet = await service.build_hr_documents_summary(seeded_db, today=BUGUN)

    assert ozet.missing == 1  # yalnız zorunlu tip
    ops_row = next(t for t in ozet.by_type if t.type_id == opsiyonel.id)
    assert ops_row.missing == 1  # dağılımda eksiği GÖRÜNÜR
    assert ops_row.is_mandatory is False


# --- 3. expiring 30/31 sınırı ------------------------------------------------


async def test_expiring_30_dahil_31_haric(seeded_db: AsyncSession) -> None:
    tip = await _mk_type(seeded_db, "Sağlık", mandatory=True, validity=12, order=1)
    p = await _mk_personnel(seeded_db, "Sınır")
    await _mk_doc(seeded_db, p, type_id=tip.id, valid_until=BUGUN + timedelta(days=30))  # expiring
    q = await _mk_personnel(seeded_db, "Sınır2")
    await _mk_doc(seeded_db, q, type_id=tip.id, valid_until=BUGUN + timedelta(days=31))  # valid

    ozet = await service.build_hr_documents_summary(seeded_db, today=BUGUN)

    assert ozet.expiring == 1
    assert ozet.valid == 1


# --- 4. dağılım kırılımı -----------------------------------------------------


async def test_dagilim_kirilim(seeded_db: AsyncSession) -> None:
    tip = await _mk_type(seeded_db, "Sağlık", mandatory=True, validity=12, order=1)
    a = await _mk_personnel(seeded_db, "A")
    b = await _mk_personnel(seeded_db, "B")
    c = await _mk_personnel(seeded_db, "C")  # İSG yok, sağlık yok → dağılımda eksik
    await _mk_doc(seeded_db, a, type_id=tip.id, valid_until=BUGUN + timedelta(days=100))  # valid
    await _mk_doc(seeded_db, b, type_id=tip.id, valid_until=BUGUN + timedelta(days=5))  # expiring
    # A ikinci bir sağlık kaydı (yenileme) — belge sayısı 2 olur ama kişi tekildir.
    await _mk_doc(seeded_db, a, type_id=tip.id, valid_until=BUGUN - timedelta(days=2))  # expired
    assert c is not None

    ozet = await service.build_hr_documents_summary(seeded_db, today=BUGUN)
    row = next(t for t in ozet.by_type if t.type_id == tip.id)

    assert row.valid == 1
    assert row.expiring == 1
    assert row.expired == 1
    assert row.total_documents == 3
    # 3 aktif+yayın personel, sahip olan tekil kişi = {A, B} = 2 → eksik 1 (C).
    assert row.missing == 1
    assert row.validity_months == 12


# --- 5. iki liste: sıralama + limit ------------------------------------------


async def test_listeler_siralama(seeded_db: AsyncSession, project_factory) -> None:
    proje: Project = await project_factory(code="IK1-T4", name="Güneşkent")
    tip = await _mk_type(seeded_db, "Sağlık", mandatory=True, validity=12, order=1)

    # Süresi dolan: en çok geciken önce.
    p1 = await _mk_personnel(seeded_db, "Az Geciken", project_id=proje.id)
    await _mk_doc(seeded_db, p1, type_id=tip.id, valid_until=BUGUN - timedelta(days=3))
    p2 = await _mk_personnel(seeded_db, "Çok Geciken")
    await _mk_doc(seeded_db, p2, type_id=tip.id, valid_until=BUGUN - timedelta(days=40))
    # Yaklaşan: en yakın önce.
    p3 = await _mk_personnel(seeded_db, "Uzak Yaklaşan")
    await _mk_doc(seeded_db, p3, type_id=tip.id, valid_until=BUGUN + timedelta(days=25))
    p4 = await _mk_personnel(seeded_db, "Yakın Yaklaşan")
    await _mk_doc(seeded_db, p4, free_label="Serbest Rapor", valid_until=BUGUN + timedelta(days=2))

    ozet = await service.build_hr_documents_summary(seeded_db, today=BUGUN)

    assert [r.personnel_name for r in ozet.expired_documents] == ["Çok Geciken", "Az Geciken"]
    assert ozet.expired_documents[0].days_overdue == 40
    assert ozet.expired_documents[0].project_name is None
    assert ozet.expired_documents[1].project_name == "Güneşkent"

    assert [r.personnel_name for r in ozet.expiring_documents] == [
        "Yakın Yaklaşan",
        "Uzak Yaklaşan",
    ]
    assert ozet.expiring_documents[0].days_left == 2
    # Serbest etiketli kayıt tip künyesi yerine etiketiyle görünür.
    assert ozet.expiring_documents[0].document_label == "Serbest Rapor"


async def test_liste_limit_50(seeded_db: AsyncSession) -> None:
    tip = await _mk_type(seeded_db, "Sağlık", mandatory=True, validity=12, order=1)
    for i in range(55):
        p = await _mk_personnel(seeded_db, f"P{i:03d}")
        await _mk_doc(seeded_db, p, type_id=tip.id, valid_until=BUGUN - timedelta(days=i + 1))

    ozet = await service.build_hr_documents_summary(seeded_db, today=BUGUN)

    assert ozet.expired == 55  # KPI kırpılmaz
    assert len(ozet.expired_documents) == service.SUMMARY_LIST_LIMIT  # liste 50'de tavan


# --- 6. N+1: sorgu sayısı sabit ---------------------------------------------


async def _personel_sorgu_sayisi(db: AsyncSession, kisi_sayisi: int, etiket: str) -> int:
    tip = await _mk_type(db, f"Sağlık {etiket}", mandatory=True, validity=12, order=1)
    for i in range(kisi_sayisi):
        p = await _mk_personnel(db, f"K{etiket}{i:03d}")
        await _mk_doc(db, p, type_id=tip.id, valid_until=BUGUN + timedelta(days=i))

    sayac: list[str] = []

    def kaydet(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        alt = statement.lower()
        if "personnel" in alt or " projects" in alt:
            sayac.append(alt)

    event.listen(test_engine.sync_engine, "before_cursor_execute", kaydet)
    try:
        await service.build_hr_documents_summary(db, today=BUGUN)
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", kaydet)
    return len(sayac)


async def test_n_plus_1_sabit_sorgu(seeded_db: AsyncSession) -> None:
    """Aggrega kanıtı: 2 vs 10 personelde personel-tabloları sorgu sayısı AYNI."""
    iki = await _personel_sorgu_sayisi(seeded_db, 2, "A")
    # Daha çok kişi (+ ayrı tip adı) — sorgu sayısı veri büyüklüğünden bağımsız olmalı.
    on = await _personel_sorgu_sayisi(seeded_db, 10, "B")

    assert iki == on, f"N+1: sorgu sayısı veriyle değişti ({iki} vs {on})"


# --- 7. yetki + endpoint wiring ----------------------------------------------


async def test_endpoint_view_yeter_200(client, sef_headers: dict[str, str]) -> None:
    """`site_chief` = `personnel=view`: özet ucu OKUMAYA açıktır → 200."""
    yanit = await client.get("/hr/documents/summary", headers=sef_headers)
    assert yanit.status_code == 200, yanit.text
    govde = yanit.json()
    for anahtar in ("total_documents", "valid", "expiring", "expired", "missing", "by_type"):
        assert anahtar in govde


async def test_endpoint_yetkisiz_403(client, yetkisiz_headers: dict[str, str]) -> None:
    """`procurement` = `personnel=none`: 403."""
    yanit = await client.get("/hr/documents/summary", headers=yetkisiz_headers)
    assert yanit.status_code == 403, yanit.text


async def test_endpoint_gercek_veri(client, ik_headers: dict[str, str], seeded_db) -> None:
    """Endpoint yolu (today=date.today()) gerçek veriyle uçtan uca hesaplar."""
    bugun = date.today()
    tip = await _mk_type(seeded_db, "Sağlık", mandatory=True, validity=12, order=1)
    p = await _mk_personnel(seeded_db, "Canlı")
    await _mk_doc(seeded_db, p, type_id=tip.id, valid_until=bugun - timedelta(days=1))

    yanit = await client.get("/hr/documents/summary", headers=ik_headers)
    assert yanit.status_code == 200, yanit.text
    govde = yanit.json()
    assert govde["total_documents"] == 1
    assert govde["expired"] == 1
    assert len(govde["expired_documents"]) == 1
    assert govde["expired_documents"][0]["personnel_name"] == "Canlı"
