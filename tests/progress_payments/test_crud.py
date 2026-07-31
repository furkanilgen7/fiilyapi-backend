"""Task H4 — CRUD uçları: liste/detay/oluştur/düzenle (spec §9.1/§9.2, §7)."""

import uuid
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.progress_payments import guards
from app.modules.progress_payments.models import ProgressPayment, ProgressPaymentStatus

pytestmark = pytest.mark.asyncio


async def test_olusturma_sequence_no_uretir(
    client: AsyncClient, admin_headers: dict[str, str], sozlesmeli_proje: uuid.UUID
) -> None:
    """E15 65 '#5': proje içi maks+1, sunucu üretir (gövdede gönderilemez)."""
    ilk = await client.post(
        f"/projects/{sozlesmeli_proje}/progress-payments", json={}, headers=admin_headers
    )
    assert ilk.status_code == 201, ilk.text
    assert ilk.json()["sequence_no"] == 1
    assert ilk.json()["status"] == "draft"


async def test_ikinci_hakedis_sequence_no_iki_alir(
    client: AsyncClient,
    admin_headers: dict[str, str],
    sozlesmeli_proje: uuid.UUID,
    seeded_db: AsyncSession,
) -> None:
    """Y2 (H4 denetimi): `repository.get_next_sequence_no` proje içi GERÇEK
    maks+1 üretir — sabit `1` döndürülseydi ikinci hakediş
    `uq_progress_payments_project_sequence` ihlaliyle 500 IntegrityError verirdi.

    Durum geçişi ucu (H6) henüz yazılmadığı için ilk hakedişi `approved` yapmak
    burada doğrudan DB üzerinden yapılır (D8 açık-hakediş kilidini açmak için
    meşru bir test kurulumu — status makinesi kuralı test EDİLMİYOR, yalnız
    `sequence_no` üretimi)."""
    ilk = await client.post(
        f"/projects/{sozlesmeli_proje}/progress-payments", json={}, headers=admin_headers
    )
    assert ilk.status_code == 201, ilk.text
    assert ilk.json()["sequence_no"] == 1

    ilk_kayit = await seeded_db.get(ProgressPayment, uuid.UUID(ilk.json()["id"]))
    ilk_kayit.status = ProgressPaymentStatus.approved
    await seeded_db.flush()

    ikinci = await client.post(
        f"/projects/{sozlesmeli_proje}/progress-payments", json={}, headers=admin_headers
    )
    assert ikinci.status_code == 201, ikinci.text
    assert ikinci.json()["sequence_no"] == 2

    kayitlar = (
        (
            await seeded_db.execute(
                select(ProgressPayment.sequence_no)
                .where(ProgressPayment.project_id == sozlesmeli_proje)
                .order_by(ProgressPayment.sequence_no)
            )
        )
        .scalars()
        .all()
    )
    assert kayitlar == [1, 2]


async def test_snapshot_yuzdeler_sozlesmeden_kopyalanir(
    client: AsyncClient, admin_headers: dict[str, str], sozlesmeli_proje: uuid.UUID
) -> None:
    """D5: vat/advance/retainage oluşturma anında `project_contracts`'tan donar."""
    yanit = await client.post(
        f"/projects/{sozlesmeli_proje}/progress-payments", json={}, headers=admin_headers
    )
    govde = yanit.json()
    assert Decimal(govde["advance_pct"]) == Decimal("20")
    assert Decimal(govde["retainage_pct"]) == Decimal("5")
    assert Decimal(govde["vat_pct"]) == Decimal("20")


async def test_acik_hakedis_varken_ikincisi_409(
    client: AsyncClient, admin_headers: dict[str, str], taslak_hakedisli_proje: uuid.UUID
) -> None:
    """D8/K9."""
    yanit = await client.post(
        f"/projects/{taslak_hakedisli_proje}/progress-payments", json={}, headers=admin_headers
    )
    assert yanit.status_code == 409
    assert yanit.json()["detail"] == guards.OPEN_PAYMENT_EXISTS


async def test_sozlesmesiz_proje_422(
    client: AsyncClient, admin_headers: dict[str, str], sozlesmesiz_proje: uuid.UUID
) -> None:
    yanit = await client.post(
        f"/projects/{sozlesmesiz_proje}/progress-payments", json={}, headers=admin_headers
    )
    assert yanit.status_code == 422
    assert yanit.json()["detail"] == guards.NO_EMPLOYER_CONTRACT


async def test_satirli_olusturma_atomik_ve_snapshot(
    client: AsyncClient,
    admin_headers: dict[str, str],
    sozlesmeli_proje: uuid.UUID,
    hakedis_santiyesi,
    hakedis_kalemi,
) -> None:
    """§9.2: `lines[]` iç içe; satıra `code/description/unit/unit_price/group_name`

    kopyalanır (spec §5 fiyat otoritesi: sözleşme kalemi -> satır snapshot).
    """
    item, group_name = hakedis_kalemi
    yanit = await client.post(
        f"/projects/{sozlesmeli_proje}/progress-payments",
        json={
            "lines": [
                {
                    "contract_item_id": str(item.id),
                    "site_id": str(hakedis_santiyesi.id),
                    "quantity": "100",
                }
            ]
        },
        headers=admin_headers,
    )
    assert yanit.status_code == 201, yanit.text
    govde = yanit.json()
    assert len(govde["lines"]) == 1
    satir = govde["lines"][0]
    assert satir["code"] == item.code
    assert satir["description"] == item.description
    assert satir["unit"] == item.unit
    assert Decimal(satir["contract_unit_price"]) == item.unit_price
    assert satir["group_name"] == group_name
    assert Decimal(satir["quantity"]) == Decimal("100")
    # coefficient gönderilmedi -> hakedişin default_coefficient'ı iner (spec §4.1).
    assert Decimal(satir["coefficient"]) == Decimal("1.000")


async def test_detay_odeme_hesabi(
    client: AsyncClient,
    admin_headers: dict[str, str],
    sozlesmeli_proje: uuid.UUID,
    hakedis_santiyesi,
    hakedis_kalemi,
) -> None:
    """E15 151-172: gross/vat/advance/retention/net tutarlı (spec §6.2-§6.4)."""
    item, _ = hakedis_kalemi
    olusturma = await client.post(
        f"/projects/{sozlesmeli_proje}/progress-payments",
        json={
            "lines": [
                {
                    "contract_item_id": str(item.id),
                    "site_id": str(hakedis_santiyesi.id),
                    "quantity": "100",
                }
            ]
        },
        headers=admin_headers,
    )
    payment_id = olusturma.json()["id"]

    detay = await client.get(f"/progress-payments/{payment_id}", headers=admin_headers)
    assert detay.status_code == 200, detay.text
    calc = detay.json()["calculation"]

    gross = item.unit_price * Decimal("100")
    vat = (gross * Decimal("20") / Decimal("100")).quantize(Decimal("0.01"))
    advance = (gross * Decimal("20") / Decimal("100")).quantize(Decimal("0.01"))
    retention = (gross * Decimal("5") / Decimal("100")).quantize(Decimal("0.01"))
    net = gross + vat - advance - retention

    assert Decimal(calc["gross"]) == gross
    assert Decimal(calc["vat"]) == vat
    assert Decimal(calc["advance_deduction"]) == advance
    assert Decimal(calc["retention"]) == retention
    assert Decimal(calc["net"]) == net


async def test_liste_temel_alanlar(
    client: AsyncClient, admin_headers: dict[str, str], sozlesmeli_proje: uuid.UUID
) -> None:
    await client.post(
        f"/projects/{sozlesmeli_proje}/progress-payments", json={}, headers=admin_headers
    )
    yanit = await client.get(
        "/progress-payments", params={"project_id": str(sozlesmeli_proje)}, headers=admin_headers
    )
    assert yanit.status_code == 200, yanit.text
    items = yanit.json()["items"]
    assert len(items) == 1
    assert items[0]["sequence_no"] == 1
    assert items[0]["status"] == "draft"
    assert "gross_total" in items[0]
    assert "net_total" in items[0]


async def test_pending_hakedis_patch_409(
    client: AsyncClient, admin_headers: dict[str, str], onay_bekleyen_hakedis: uuid.UUID
) -> None:
    yanit = await client.patch(
        f"/progress-payments/{onay_bekleyen_hakedis}",
        json={"description": "x"},
        headers=admin_headers,
    )
    assert yanit.status_code == 409
    assert yanit.json()["detail"] == guards.INVALID_STATUS_TRANSITION


async def test_draft_patch_basarili(
    client: AsyncClient, admin_headers: dict[str, str], sozlesmeli_proje: uuid.UUID
) -> None:
    olusturma = await client.post(
        f"/projects/{sozlesmeli_proje}/progress-payments", json={}, headers=admin_headers
    )
    payment_id = olusturma.json()["id"]
    yanit = await client.patch(
        f"/progress-payments/{payment_id}",
        json={"description": "Kat 6-8 döşeme", "period_year": 2026, "period_month": 7},
        headers=admin_headers,
    )
    assert yanit.status_code == 200, yanit.text
    govde = yanit.json()
    assert govde["description"] == "Kat 6-8 döşeme"
    assert govde["period_year"] == 2026
    assert govde["period_month"] == 7
