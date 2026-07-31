from decimal import Decimal

import pytest
from sqlalchemy import inspect, text

from app.modules.progress_payments.models import (
    ProgressPayment,
    ProgressPaymentLine,
    ProgressPaymentStatus,
)


def test_status_uyeleri():
    assert [s.value for s in ProgressPaymentStatus] == [
        "draft",
        "pending_approval",
        "approved",
        "paid",
    ]


def test_is_draft_property():
    """Spec §4.1: is_draft KOLONU yok; Deletable protokolü için property var."""
    p = ProgressPayment(status=ProgressPaymentStatus.draft)
    assert p.is_draft is True
    p.status = ProgressPaymentStatus.pending_approval
    assert p.is_draft is False


@pytest.mark.asyncio
async def test_yeni_tablolar_olusur(db_session):
    tablolar = await db_session.run_sync(lambda s: inspect(s.bind).get_table_names())
    assert "progress_payments" in tablolar
    assert "progress_payment_lines" in tablolar


@pytest.mark.asyncio
async def test_donem_null_olabilir(db_session):
    """Kalıcı karar 4: kullanıcı alanı NULL (taslak desteği)."""
    sonuc = await db_session.execute(
        text(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name='progress_payments' AND column_name='period_year'"
        )
    )
    assert sonuc.scalar_one() == "YES"


@pytest.mark.asyncio
async def test_snapshot_yuzdeler_not_null(db_session):
    sonuc = await db_session.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='progress_payments' AND is_nullable='NO' "
            "AND column_name IN "
            "('vat_pct','advance_pct','retainage_pct','sequence_no','created_by')"
        )
    )
    assert {r[0] for r in sonuc} == {
        "vat_pct",
        "advance_pct",
        "retainage_pct",
        "sequence_no",
        "created_by",
    }


@pytest.mark.asyncio
async def test_satir_miktar_sifir_kabul(
    seeded_db, hakedis_sozlesmesi, hakedis_santiyesi, hakedis_olusturan
):
    """OLU 172 `value="0"`: satırda 0 miktar MEŞRU (CHECK >= 0, BOQ'daki > 0'dan bilinçli fark)."""
    project, _contract = hakedis_sozlesmesi
    payment = ProgressPayment(
        project_id=project.id,
        sequence_no=1,
        vat_pct=Decimal("20"),
        advance_pct=Decimal("20"),
        retainage_pct=Decimal("5"),
        created_by=hakedis_olusturan.id,
    )
    seeded_db.add(payment)
    await seeded_db.flush()

    line = ProgressPaymentLine(
        payment_id=payment.id,
        site_id=hakedis_santiyesi.id,
        code="03.001",
        description="Beton",
        unit="m³",
        contract_unit_price=Decimal("1850"),
        quantity=Decimal("0"),
    )
    seeded_db.add(line)
    await seeded_db.flush()

    assert line.quantity == Decimal("0")
