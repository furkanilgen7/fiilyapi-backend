"""BC-3 — DB katmanı bekçileri (ORM + gerçek PG kısıtları).

Dört korumanın dördü de DB'de ÇARPILARAK ölçülür (K-IKIZ1: testin kendisi yolu
kurmaz, kısıta çarpar): bileşik FK · CHECK · SET NULL · CASCADE. Her ihlal
için pozitif kontrol aynı dosyadadır (geçerli değer GEÇER).
"""

import uuid

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.documents.models import (
    Document,
    EntityDocumentScope,
    SectionDocument,
    UnitDocument,
)
from app.modules.projects.models import Project
from app.modules.sites.models import Section
from app.modules.units.models import Unit


async def _hata_bekle(session: AsyncSession, satir, ipucu: str) -> str:
    """SAVEPOINT içinde flush eder, IntegrityError'ı yakalar, PG mesajını döner."""
    with pytest.raises(IntegrityError) as exc_info:
        async with session.begin_nested():
            session.add(satir)
            await session.flush()
    mesaj = str(exc_info.value.orig)
    assert ipucu in mesaj, mesaj
    return mesaj


async def test_bilesik_FK_baska_bolmenin_tipini_REDDEDER(
    seeded_db: AsyncSession, bolum: Section, slot_katalogu
) -> None:
    """`section_documents.type_id` bir SATIŞ slotuna işaret edemez: `(type_id, 'section')`
    çifti katalogda yoktur → FK ihlali. Servis 422 vermese bile DB durdurur."""
    satis_slotu = slot_katalogu[("unit_sale", "sales_contract")]
    await _hata_bekle(
        seeded_db,
        SectionDocument(section_id=bolum.id, type_id=satis_slotu.id),
        "fk_section_documents_type_scope",
    )


async def test_CHECK_scope_kolonu_kendi_sabitine_cakilidir(
    seeded_db: AsyncSession, bolum: Section, slot_katalogu
) -> None:
    """Bileşik FK'yi TATMİN EDEN ama tabloya yabancı bir `scope` (`unit` slotu +
    `scope='unit'`) CHECK'e çarpar — iki koruma AYRI şeyleri ölçer."""
    unite_slotu = slot_katalogu[("unit", "floor_plan")]
    await _hata_bekle(
        seeded_db,
        SectionDocument(
            section_id=bolum.id, type_id=unite_slotu.id, scope=EntityDocumentScope.unit
        ),
        "ck_section_documents_scope",
    )


async def test_POZITIF_KONTROL_dogru_bolme_ve_dogru_sabit_GECER(
    seeded_db: AsyncSession, bolum: Section, unite: Unit, slot_katalogu
) -> None:
    seeded_db.add(
        SectionDocument(
            section_id=bolum.id, type_id=slot_katalogu[("section", "hse_phase_plan")].id
        )
    )
    seeded_db.add(UnitDocument(unit_id=unite.id, type_id=slot_katalogu[("unit", "renders")].id))
    await seeded_db.flush()
    assert (await seeded_db.scalar(select(SectionDocument.scope))) is EntityDocumentScope.section


async def test_arsiv_kaydi_silinince_bag_KALIR_document_id_NULL(
    seeded_db: AsyncSession, proje: Project, bolum: Section, slot_katalogu, belge_fabrikasi
) -> None:
    """BC-2 pilotu: SET NULL — dosya gider, "belge vardı" satırı ve künyesi kalır."""
    belge: Document = await belge_fabrikasi(proje, "metraj.xlsx", data=b"x")
    bag = SectionDocument(
        section_id=bolum.id,
        type_id=slot_katalogu[("section", "quantity_takeoff")].id,
        document_id=belge.id,
        note="Rev2",
    )
    seeded_db.add(bag)
    await seeded_db.flush()
    bag_id = bag.id

    await seeded_db.execute(delete(Document).where(Document.id == belge.id))
    await seeded_db.flush()
    # `expire` + öznitelik erişimi async'te MissingGreenlet üretir; kimlik önceden
    # alınır ve kimlik haritası boşaltılıp satır DB'den YENİDEN okunur.
    seeded_db.expunge_all()

    kalan = await seeded_db.get(SectionDocument, bag_id)
    assert kalan is not None
    assert kalan.document_id is None
    assert kalan.note == "Rev2"


async def test_sahip_silinince_bag_GIDER_dosya_KALIR(
    seeded_db: AsyncSession, proje: Project, bolum: Section, slot_katalogu, belge_fabrikasi
) -> None:
    """CASCADE sahipten bağa; arşivdeki dosyaya DOKUNMAZ (bağ silinir, belge silinmez)."""
    belge: Document = await belge_fabrikasi(proje, "proje.dwg", data=b"x")
    bag = SectionDocument(
        section_id=bolum.id,
        type_id=slot_katalogu[("section", "application_project")].id,
        document_id=belge.id,
    )
    seeded_db.add(bag)
    await seeded_db.flush()
    bag_id = bag.id

    await seeded_db.execute(delete(Section).where(Section.id == bolum.id))
    await seeded_db.flush()
    seeded_db.expunge_all()

    assert await seeded_db.get(SectionDocument, bag_id) is None
    assert await seeded_db.get(Document, belge.id) is not None


async def test_katalog_tipi_kullanimda_iken_SILINEMEZ_restrict(
    seeded_db: AsyncSession, bolum: Section, slot_katalogu
) -> None:
    from app.modules.documents.models import EntityDocumentType

    slot = slot_katalogu[("section", "hse_phase_plan")]
    seeded_db.add(SectionDocument(section_id=bolum.id, type_id=slot.id))
    await seeded_db.flush()
    with pytest.raises(IntegrityError):
        async with seeded_db.begin_nested():
            await seeded_db.execute(
                delete(EntityDocumentType).where(EntityDocumentType.id == slot.id)
            )


async def test_var_olmayan_sahip_FK_ihlali(seeded_db: AsyncSession, slot_katalogu) -> None:
    await _hata_bekle(
        seeded_db,
        SectionDocument(
            section_id=uuid.uuid4(), type_id=slot_katalogu[("section", "hse_phase_plan")].id
        ),
        "section_documents_section_id_fkey",
    )
