"""İK-1 T1 — `personnel` kart genişlemesi + belge tabloları: ORM/DB seviyesi.

Spec: `docs/superpowers/specs/2026-08-12-ik1-personel-belge-design.md` §1, §2, §5.

Yalnız model/DB davranışı sınanır (router/servis T2-T4'ün işidir):
* yeni kolonlar hepsi nullable + `is_draft` server_default `false`;
* `tc_no` UNIQUE ama iki NULL SERBEST (Postgres `NULLS DISTINCT`);
* `personnel_documents` CHECK: `type_id` XOR `free_label` tam biri dolu olmalı;
* `personnel_id` CASCADE, `type_id` RESTRICT, `document_id` SET NULL.

DB seviyesi ihlalleri `db_session` üstünde ayrı SAVEPOINT'lerde denenir —
`IntegrityError` sonrası oturum aynı test içinde devam edebilsin diye her
ihlal kendi `session.begin_nested()` bloğunda çalışır (SQLAlchemy: bir
`IntegrityError` sonrası dış transaction "aborted" kalır, elle rollback
gerekir — burada nested blok kendini otomatik geri alır).
"""

import uuid
from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.personnel.models import (
    Gender,
    MaritalStatus,
    PaymentMethod,
    Personnel,
    PersonnelDocument,
    PersonnelDocumentType,
    WageType,
)
from app.modules.site_diary.models import WorkerSource


async def _personel(db_session: AsyncSession, **alanlar) -> Personnel:
    varsayilan = {"full_name": "Test İşçi", "source": WorkerSource.company}
    kayit = Personnel(**{**varsayilan, **alanlar})
    db_session.add(kayit)
    await db_session.flush()
    return kayit


# --- Kolon varlığı / nullable / server_default ----------------------------


def test_personnel_yeni_kolonlar_nullable():
    columns = Personnel.__table__.columns
    yeni_nullable = (
        "tc_no",
        "birth_date",
        "gender",
        "marital_status",
        "phone",
        "email",
        "address",
        "emergency_contact_name",
        "emergency_contact_phone",
        "hire_date",
        "wage_type",
        "wage_amount",
        "payment_method",
        "iban",
        "sgk_no",
        "assigned_project_id",
        "assigned_section_id",
    )
    for name in yeni_nullable:
        assert name in columns, name
        assert columns[name].nullable, f"{name} nullable olmali (spec §5 K3)"


def test_personnel_is_draft_not_null_server_default_false():
    columns = Personnel.__table__.columns
    assert not columns["is_draft"].nullable
    assert columns["is_draft"].server_default is not None


def test_personnel_assigned_columns_set_null():
    columns = Personnel.__table__.columns
    (project_fk,) = tuple(columns["assigned_project_id"].foreign_keys)
    assert project_fk.column.table.name == "projects"
    assert project_fk.ondelete == "SET NULL"
    (section_fk,) = tuple(columns["assigned_section_id"].foreign_keys)
    assert section_fk.column.table.name == "sections"
    assert section_fk.ondelete == "SET NULL"


def test_personnel_forbidden_columns_absent():
    """Spec §5 K2/K6: foto kolonu ve vergi no AÇILMADI; enum yeni deger ALMADI."""
    columns = Personnel.__table__.columns
    for name in ("photo", "photo_url", "tax_no"):
        assert name not in columns, f"personnel.{name} açılmamalıydı"
    assert [e.value for e in WorkerSource] == ["company", "subcontractor", "general"], (
        "worker_source enum'una İK-1'de yeni deger EKLENMEMELIYDI (spec §5 K2)"
    )


def test_personnel_document_types_columns():
    columns = PersonnelDocumentType.__table__.columns
    assert set(columns.keys()) == {
        "id",
        "name",
        "is_mandatory",
        "validity_months",
        "sort_order",
        "is_active",
        "created_at",
    }
    assert columns["name"].unique
    assert not columns["is_mandatory"].nullable
    assert columns["validity_months"].nullable
    assert not columns["sort_order"].nullable
    assert not columns["is_active"].nullable


def test_personnel_documents_columns_no_status():
    """Durum TÜREVdir (spec §2 son paragraf) — kolon YOK."""
    columns = PersonnelDocument.__table__.columns
    assert "status" not in columns
    assert set(columns.keys()) == {
        "id",
        "personnel_id",
        "type_id",
        "free_label",
        "document_id",
        "issued_at",
        "valid_until",
        "note",
        "created_at",
        "updated_at",
    }


# --- Taze kart alanları --------------------------------------------------


@pytest.mark.asyncio
async def test_personel_ik1_alanlariyla_olusturulabilir(db_session: AsyncSession):
    kayit = await _personel(
        db_session,
        tc_no="12345678901",
        birth_date=date(1990, 1, 1),
        gender=Gender.male,
        marital_status=MaritalStatus.single,
        phone="5551112233",
        email="isci@ornek.test",
        address="Adres",
        emergency_contact_name="Yakın",
        emergency_contact_phone="5559998877",
        hire_date=date(2026, 1, 1),
        wage_type=WageType.daily,
        wage_amount="1500.00",
        payment_method=PaymentMethod.bank,
        iban="TR000000000000000000000000",
        sgk_no="12345",
    )
    assert kayit.tc_no == "12345678901"
    assert kayit.is_draft is False


# --- tc_no UNIQUE — iki NULL serbest, iki eşit DOLU değer değil -----------


@pytest.mark.asyncio
async def test_iki_null_tc_no_serbesttir(db_session: AsyncSession):
    await _personel(db_session, full_name="Birinci")
    await _personel(db_session, full_name="İkinci")
    sayim = await db_session.execute(select(Personnel))
    assert len(sayim.scalars().all()) == 2


@pytest.mark.asyncio
async def test_ayni_tc_no_ikinci_kayitta_integrity_error(db_session: AsyncSession):
    await _personel(db_session, tc_no="11111111110")
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await _personel(db_session, tc_no="11111111110")


# --- personnel_documents CHECK: type_id XOR free_label ---------------------


@pytest.mark.asyncio
async def test_belge_tip_ve_serbest_etiket_birlikte_integrity_error(db_session: AsyncSession):
    personel = await _personel(db_session)
    tip = PersonnelDocumentType(name="Test Tip " + uuid.uuid4().hex[:8])
    db_session.add(tip)
    await db_session.flush()

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(
                PersonnelDocument(
                    personnel_id=personel.id, type_id=tip.id, free_label="ikisi birden"
                )
            )
            await db_session.flush()


@pytest.mark.asyncio
async def test_belge_tip_de_etiket_de_yoksa_integrity_error(db_session: AsyncSession):
    personel = await _personel(db_session)
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(PersonnelDocument(personnel_id=personel.id))
            await db_session.flush()


@pytest.mark.asyncio
async def test_belge_yalniz_tip_ile_olusturulabilir(db_session: AsyncSession):
    personel = await _personel(db_session)
    tip = PersonnelDocumentType(name="Yalniz Tip " + uuid.uuid4().hex[:8])
    db_session.add(tip)
    await db_session.flush()
    belge = PersonnelDocument(personnel_id=personel.id, type_id=tip.id)
    db_session.add(belge)
    await db_session.flush()
    assert belge.id is not None


@pytest.mark.asyncio
async def test_belge_yalniz_serbest_etiketle_olusturulabilir(db_session: AsyncSession):
    personel = await _personel(db_session)
    belge = PersonnelDocument(personnel_id=personel.id, free_label="Serbest Belge")
    db_session.add(belge)
    await db_session.flush()
    assert belge.id is not None


# --- Silme davranışları -----------------------------------------------------


@pytest.mark.asyncio
async def test_personel_silinince_belgesi_de_gider_cascade(db_session: AsyncSession):
    personel = await _personel(db_session)
    belge = PersonnelDocument(personnel_id=personel.id, free_label="Silinecek")
    db_session.add(belge)
    await db_session.flush()
    belge_id = belge.id

    await db_session.delete(personel)
    await db_session.flush()

    kalan = await db_session.execute(
        select(PersonnelDocument).where(PersonnelDocument.id == belge_id)
    )
    assert kalan.scalar_one_or_none() is None, "personel silinince belge CASCADE ile gitmeli"


@pytest.mark.asyncio
async def test_kullanimda_olan_belge_tipi_silinemez_restrict(db_session: AsyncSession):
    personel = await _personel(db_session)
    tip = PersonnelDocumentType(name="Restrict Tip " + uuid.uuid4().hex[:8])
    db_session.add(tip)
    await db_session.flush()
    db_session.add(PersonnelDocument(personnel_id=personel.id, type_id=tip.id))
    await db_session.flush()

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.delete(tip)
            await db_session.flush()


@pytest.mark.asyncio
async def test_belgenin_bagli_belge_arsivi_silinince_set_null(
    db_session: AsyncSession, project_factory
):
    """BC-2 pilotu: `documents` arşiv kaydı silinse de İK takip kaydı KALIR,
    yalnız `document_id` NULL'a düşer (spec §2 — dosyasız kayıt da meşru)."""
    from app.modules.documents.models import Document

    proje = await project_factory(code="IK1-T1")
    personel = await _personel(db_session)
    arsiv_belgesi = Document(
        project_id=proje.id,
        filename="test.pdf",
        mime_type="application/pdf",
        size_bytes=10,
    )
    db_session.add(arsiv_belgesi)
    await db_session.flush()

    belge = PersonnelDocument(
        personnel_id=personel.id, free_label="Arsivli Belge", document_id=arsiv_belgesi.id
    )
    db_session.add(belge)
    await db_session.flush()

    await db_session.delete(arsiv_belgesi)
    await db_session.flush()
    # DB SET NULL bir kisit tetiklemesidir, ORM'un identity map'indeki `belge`
    # nesnesini GUNCELLEMEZ — DB'deki gercek degeri gormek icin acikca REFRESH.
    await db_session.refresh(belge)

    assert belge.document_id is None, "arsiv silinince document_id SET NULL olmali"


def test_personnel_documents_document_id_set_null_fk():
    columns = PersonnelDocument.__table__.columns
    (document_fk,) = tuple(columns["document_id"].foreign_keys)
    assert document_fk.column.table.name == "documents"
    assert document_fk.ondelete == "SET NULL"
    (type_fk,) = tuple(columns["type_id"].foreign_keys)
    assert type_fk.column.table.name == "personnel_document_types"
    assert type_fk.ondelete == "RESTRICT"
    (personnel_fk,) = tuple(columns["personnel_id"].foreign_keys)
    assert personnel_fk.column.table.name == "personnel"
    assert personnel_fk.ondelete == "CASCADE"
