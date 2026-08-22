"""İK-2 T1 — izin şeması: ORM/DB seviyesi.

Spec: `docs/superpowers/specs/2026-08-12-ik2-izin-yonetimi-design.md` §1, §5.

Yalnız model/DB davranışı sınanır (uçlar/servis T2+'nın işidir):
* `leave_balances` UQ(personnel_id, year) + `annual_entitlement` KOLON YOK (K1);
* `leave_requests` CHECK'leri: `end_date >= start_date`, `days > 0`;
* silme davranışları: personel CASCADE · tip RESTRICT · belge/kullanıcı SET NULL;
* `status` server_default `pending` (tek adımlı onay, K4).

İK-1 emsali: DB seviyesi ihlalleri ayrı `begin_nested()` SAVEPOINT'lerinde
denenir — `IntegrityError` sonrası dış transaction "aborted" kalır.
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.personnel.models import (
    LeaveBalance,
    LeaveRequest,
    LeaveStatus,
    LeaveType,
    Personnel,
)
from app.modules.site_diary.models import WorkerSource


async def _personel(db_session: AsyncSession, **alanlar) -> Personnel:
    varsayilan = {"full_name": "İzinli İşçi", "source": WorkerSource.company}
    kayit = Personnel(**{**varsayilan, **alanlar})
    db_session.add(kayit)
    await db_session.flush()
    return kayit


async def _izin_tipi(db_session: AsyncSession, **alanlar) -> LeaveType:
    varsayilan = {"name": "Test Izin " + uuid.uuid4().hex[:8]}
    kayit = LeaveType(**{**varsayilan, **alanlar})
    db_session.add(kayit)
    await db_session.flush()
    return kayit


# --- Kolon/kisit yapisi -----------------------------------------------------


def test_leave_types_kolonlari():
    columns = LeaveType.__table__.columns
    assert set(columns.keys()) == {
        "id",
        "name",
        "deducts_from_annual",
        "is_paid",
        "requires_document",
        "color",
        "sort_order",
        "is_active",
        "created_at",
    }
    assert columns["name"].unique
    for name in ("deducts_from_annual", "is_paid", "requires_document", "sort_order", "is_active"):
        assert not columns[name].nullable, name
        assert columns[name].server_default is not None, name


def test_leave_balances_annual_entitlement_kolonu_yok():
    """Spec §5 K1: yillik hak KIDEMDEN TUREVDIR — kolon acilirsa iki gercek

    kaynak dogar. `used`/`remaining`/`usage_pct` de kolon DEGILDIR.
    """
    columns = LeaveBalance.__table__.columns
    for yasak in ("annual_entitlement", "used", "remaining", "usage_pct", "entitlement"):
        assert yasak not in columns, f"leave_balances.{yasak} kolon OLMAMALI (spec §5 K1)"
    assert set(columns.keys()) == {
        "id",
        "personnel_id",
        "year",
        "carried_over",
        "created_at",
        "updated_at",
    }


def test_leave_requests_fk_davranislari():
    columns = LeaveRequest.__table__.columns
    (personnel_fk,) = tuple(columns["personnel_id"].foreign_keys)
    assert personnel_fk.column.table.name == "personnel"
    assert personnel_fk.ondelete == "CASCADE"
    (type_fk,) = tuple(columns["leave_type_id"].foreign_keys)
    assert type_fk.column.table.name == "leave_types"
    assert type_fk.ondelete == "RESTRICT"
    (document_fk,) = tuple(columns["document_id"].foreign_keys)
    assert document_fk.column.table.name == "documents"
    assert document_fk.ondelete == "SET NULL"
    (decided_by_fk,) = tuple(columns["decided_by"].foreign_keys)
    assert decided_by_fk.column.table.name == "users"
    assert decided_by_fk.ondelete == "SET NULL"


def test_leave_status_enum_tek_adimli_onay():
    """Spec §5 K4: onay TEK adim — ara durum (`in_review` vb.) YOK.

    🔴 İK-2.2 `withdrawn` uyesini ekledi. Bu bir ARA durum DEGILDIR ve K4'u
    bozmaz: onay hala TEK adimdir. `withdrawn` TERMINAL bir durumdur ve karari
    ONAYLAYAN degil talebin SAHIBI verir (`pending -> withdrawn`, geri donusu
    YOK — vazgecen kisi yeni talep acar).

    🔴 SIRA IDDIA EDILIR ve uye SONA eklenir: Postgres enum'unda `enum_range`
    sirasi migration'daki `ADD VALUE`nun yeridir. Python tarafi ile DB tarafi
    ayrisirsa bu test kirmizi olur — `test_ik22_migration_round.py` ayni sirayi
    DB'de olcer, ikisi birlikte iki katmani da civiler.
    """
    assert [s.value for s in LeaveStatus] == ["pending", "approved", "rejected", "withdrawn"]
    assert list(LeaveStatus)[-1] is LeaveStatus.withdrawn


# --- DB kisitlari -----------------------------------------------------------


@pytest.mark.asyncio
async def test_talep_varsayilan_durumu_pending(db_session: AsyncSession):
    personel = await _personel(db_session)
    tip = await _izin_tipi(db_session)
    talep = LeaveRequest(
        personnel_id=personel.id,
        leave_type_id=tip.id,
        start_date=date(2026, 8, 4),
        end_date=date(2026, 8, 8),
        days=5,  # takvim gunu, sinirlar DAHIL (spec §5 K2)
    )
    db_session.add(talep)
    await db_session.flush()
    await db_session.refresh(talep)
    assert talep.status is LeaveStatus.pending
    assert talep.decided_by is None and talep.decided_at is None


@pytest.mark.asyncio
async def test_bitis_baslangictan_once_ise_integrity_error(db_session: AsyncSession):
    personel = await _personel(db_session)
    tip = await _izin_tipi(db_session)
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(
                LeaveRequest(
                    personnel_id=personel.id,
                    leave_type_id=tip.id,
                    start_date=date(2026, 8, 8),
                    end_date=date(2026, 8, 4),
                    days=5,
                )
            )
            await db_session.flush()


@pytest.mark.asyncio
async def test_sifir_gun_integrity_error(db_session: AsyncSession):
    personel = await _personel(db_session)
    tip = await _izin_tipi(db_session)
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(
                LeaveRequest(
                    personnel_id=personel.id,
                    leave_type_id=tip.id,
                    start_date=date(2026, 8, 4),
                    end_date=date(2026, 8, 4),
                    days=0,
                )
            )
            await db_session.flush()


@pytest.mark.asyncio
async def test_ayni_personel_ayni_yil_iki_bakiye_integrity_error(db_session: AsyncSession):
    personel = await _personel(db_session)
    db_session.add(LeaveBalance(personnel_id=personel.id, year=2026, carried_over=Decimal("3")))
    await db_session.flush()

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(LeaveBalance(personnel_id=personel.id, year=2026))
            await db_session.flush()


@pytest.mark.asyncio
async def test_ayni_personel_farkli_yil_serbest(db_session: AsyncSession):
    personel = await _personel(db_session)
    db_session.add(LeaveBalance(personnel_id=personel.id, year=2025, carried_over=Decimal("2")))
    db_session.add(LeaveBalance(personnel_id=personel.id, year=2026))
    await db_session.flush()
    kayitlar = await db_session.execute(
        select(LeaveBalance).where(LeaveBalance.personnel_id == personel.id)
    )
    assert len(kayitlar.scalars().all()) == 2


@pytest.mark.asyncio
async def test_negatif_devreden_integrity_error(db_session: AsyncSession):
    personel = await _personel(db_session)
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(
                LeaveBalance(personnel_id=personel.id, year=2026, carried_over=Decimal("-1"))
            )
            await db_session.flush()


# --- Silme davranislari -----------------------------------------------------


@pytest.mark.asyncio
async def test_personel_silinince_talep_ve_bakiye_cascade(db_session: AsyncSession):
    personel = await _personel(db_session)
    tip = await _izin_tipi(db_session)
    talep = LeaveRequest(
        personnel_id=personel.id,
        leave_type_id=tip.id,
        start_date=date(2026, 8, 4),
        end_date=date(2026, 8, 5),
        days=2,
    )
    bakiye = LeaveBalance(personnel_id=personel.id, year=2026)
    db_session.add_all([talep, bakiye])
    await db_session.flush()
    talep_id, bakiye_id = talep.id, bakiye.id

    await db_session.delete(personel)
    await db_session.flush()

    kalan_talep = await db_session.execute(select(LeaveRequest).where(LeaveRequest.id == talep_id))
    assert kalan_talep.scalar_one_or_none() is None
    kalan_bakiye = await db_session.execute(
        select(LeaveBalance).where(LeaveBalance.id == bakiye_id)
    )
    assert kalan_bakiye.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_kullanimda_olan_izin_tipi_silinemez_restrict(db_session: AsyncSession):
    personel = await _personel(db_session)
    tip = await _izin_tipi(db_session)
    db_session.add(
        LeaveRequest(
            personnel_id=personel.id,
            leave_type_id=tip.id,
            start_date=date(2026, 8, 4),
            end_date=date(2026, 8, 4),
            days=1,
        )
    )
    await db_session.flush()

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.delete(tip)
            await db_session.flush()


@pytest.mark.asyncio
async def test_rapor_belgesi_arsivden_silinince_set_null(db_session: AsyncSession, project_factory):
    """BC-2 (spec §5 K6): arşiv kaydı silinse de İZİN TALEBİ kalır, yalnız

    `document_id` NULL'a düşer.
    """
    from app.modules.documents.models import Document

    proje = await project_factory(code="IK2-T1")
    personel = await _personel(db_session)
    tip = await _izin_tipi(db_session, requires_document=True)
    arsiv_belgesi = Document(
        project_id=proje.id,
        filename="rapor.pdf",
        mime_type="application/pdf",
        size_bytes=10,
    )
    db_session.add(arsiv_belgesi)
    await db_session.flush()

    talep = LeaveRequest(
        personnel_id=personel.id,
        leave_type_id=tip.id,
        start_date=date(2026, 8, 4),
        end_date=date(2026, 8, 5),
        days=2,
        document_id=arsiv_belgesi.id,
    )
    db_session.add(talep)
    await db_session.flush()

    await db_session.delete(arsiv_belgesi)
    await db_session.flush()
    # SET NULL DB tarafinda olur — ORM identity map'i GUNCELLEMEZ (İK-1 dersi).
    await db_session.refresh(talep)

    assert talep.document_id is None
    assert talep.id is not None, "arsiv silinince talep DURMALI"
