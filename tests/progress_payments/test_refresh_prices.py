"""Task H7 — `POST …/refresh-prices` (spec §5.1, §9.3, §14 D3/D5).

## Fiyat otoritesi hatırlatması (spec §5)

Satır snapshot'ı (`code/description/unit/contract_unit_price/group_name`)
oluşturma anında DONAR; sözleşme kalemi sonra değişse bile taslak
KENDİLİĞİNDEN değişmez (§5.1). Bu dosya YALNIZ bilinçli tazeleme ucunu
(`refresh-prices`) test eder — `test_lines.py`/`test_crud.py`'nin kapsadığı
"snapshot dondurma" davranışı burada TEKRARLANMAZ, yalnız tazelemenin NE
YAPTIĞI ve NE YAPMADIĞI doğrulanır.

Üç kural ailesi:
1. Tazeleme öncesi durum — kalem/sözleşme değişince taslak etkilenmez,
   `is_price_stale` bunu görünür kılar (§5.1).
2. Tazeleme — snapshot beşlisi + yüzde üçlüsü kalemden/sözleşmeden yeniden
   kopyalanır; bağı kopmuş satır sayılmaz; yalnız `draft`.
3. "Ne yapmamalı" — miktar/katsayı/satır kimliği/onaylı evrak bozulmaz.
"""

import uuid
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.contracts.models import EmployerContractGroup, EmployerContractItem
from app.modules.progress_payments import guards
from app.modules.progress_payments.models import ProgressPayment, ProgressPaymentStatus
from app.modules.projects.models import ProjectContract

pytestmark = pytest.mark.asyncio


async def _detay(client: AsyncClient, headers: dict[str, str], payment_id: uuid.UUID) -> dict:
    yanit = await client.get(f"/progress-payments/{payment_id}", headers=headers)
    assert yanit.status_code == 200, yanit.text
    return yanit.json()


# --- 1. Tazeleme ÖNCESİ: taslak kendiliğinden değişmez (spec §5.1) ---


async def test_kalem_fiyati_degisince_taslak_etkilenmez_stale_doner(
    client: AsyncClient,
    admin_headers: dict[str, str],
    seeded_db: AsyncSession,
    hakedis_fabrikasi,
    hakedis_kalemi: tuple[EmployerContractItem, str],
) -> None:
    """Kalemin `unit_price`'ı 1850→1900 olsa da satırın `contract_unit_price`'ı
    DONMUŞ kalır; detay yanıtı `is_price_stale=True` ile bunu bildirir."""
    item, _ = hakedis_kalemi
    payment_id = await hakedis_fabrikasi(ProgressPaymentStatus.draft)

    item.unit_price = Decimal("1900")
    await seeded_db.flush()

    detay = await _detay(client, admin_headers, payment_id)
    line = detay["lines"][0]
    assert Decimal(line["contract_unit_price"]) == Decimal("1850")
    assert line["is_price_stale"] is True


async def test_tazelemeden_once_refreshed_count_hicbir_yerde_gorunmez(
    client: AsyncClient,
    admin_headers: dict[str, str],
    seeded_db: AsyncSession,
    hakedis_fabrikasi,
    hakedis_kalemi: tuple[EmployerContractItem, str],
) -> None:
    """`GET` yanıtında `refreshed_count` alanı YOKTUR — bu yalnız
    `refresh-prices` ucunun (`RefreshPricesResponse`) sözleşmesidir."""
    payment_id = await hakedis_fabrikasi(ProgressPaymentStatus.draft)
    detay = await _detay(client, admin_headers, payment_id)
    assert "refreshed_count" not in detay


# --- 2. Tazeleme: snapshot beşlisi + yüzde üçlüsü (spec §5.1, §9.3, D3/D5) ---


async def test_refresh_snapshotu_ve_yuzdeleri_tazeler(
    client: AsyncClient,
    admin_headers: dict[str, str],
    seeded_db: AsyncSession,
    hakedis_fabrikasi,
    hakedis_sozlesmesi: tuple[object, ProjectContract],
    hakedis_kalemi: tuple[EmployerContractItem, str],
) -> None:
    """Kalemin BEŞ alanı + sözleşmenin ÜÇ yüzdesi tek çağrıda tazelenir;
    `refreshed_count` DEĞİŞEN satır sayısını (1) verir."""
    _, contract = hakedis_sozlesmesi
    item, _ = hakedis_kalemi
    payment_id = await hakedis_fabrikasi(ProgressPaymentStatus.draft)

    group = await seeded_db.get(EmployerContractGroup, item.group_id)
    item.code = "03.001-R"
    item.description = "Beton C35/45 dökümü (revize)"
    item.unit = "ton"
    item.unit_price = Decimal("1900")
    group.name = "Betonarme İşleri (Revize)"
    contract.retainage_pct = Decimal("10")
    await seeded_db.flush()

    yanit = await client.post(
        f"/progress-payments/{payment_id}/refresh-prices", headers=admin_headers
    )
    assert yanit.status_code == 200, yanit.text
    assert yanit.json() == {"refreshed_count": 1}

    detay = await _detay(client, admin_headers, payment_id)
    line = detay["lines"][0]
    assert line["code"] == "03.001-R"
    assert line["description"] == "Beton C35/45 dökümü (revize)"
    assert line["unit"] == "ton"
    assert Decimal(line["contract_unit_price"]) == Decimal("1900")
    assert line["group_name"] == "Betonarme İşleri (Revize)"
    assert line["is_price_stale"] is False
    assert Decimal(detay["retainage_pct"]) == Decimal("10")


async def test_refresh_no_op_degismemis_satirda_sayac_sifir(
    client: AsyncClient, admin_headers: dict[str, str], hakedis_fabrikasi
) -> None:
    """Kalem/sözleşme HİÇ değişmediyse tazeleme yine de 200 döner ama
    `refreshed_count=0` — gereksiz yazma yapılmadığının davranışsal kanıtı."""
    payment_id = await hakedis_fabrikasi(ProgressPaymentStatus.draft)
    yanit = await client.post(
        f"/progress-payments/{payment_id}/refresh-prices", headers=admin_headers
    )
    assert yanit.status_code == 200, yanit.text
    assert yanit.json() == {"refreshed_count": 0}


async def test_bagi_kopuk_satir_atlanir_stale_null(
    client: AsyncClient,
    admin_headers: dict[str, str],
    seeded_db: AsyncSession,
    hakedis_fabrikasi,
) -> None:
    """Kalemi silinmiş satır (`contract_item_id IS NULL`, `SET NULL`) tazelenemez:
    kıyaslanacak canlı fiyat yoktur. `refreshed_count` bu satırı SAYMAZ; satır
    SESSİZCE silinmez, yalnız tazelenemez kalır — `is_price_stale=None` bunu
    zaten görünür kılar (spec §5.1 dipnotu)."""
    payment_id = await hakedis_fabrikasi(ProgressPaymentStatus.draft)
    payment = await seeded_db.get(ProgressPayment, payment_id)
    orphan_line_id = payment.lines[0].id
    payment.lines[0].contract_item_id = None
    await seeded_db.flush()

    yanit = await client.post(
        f"/progress-payments/{payment_id}/refresh-prices", headers=admin_headers
    )
    assert yanit.status_code == 200, yanit.text
    assert yanit.json() == {"refreshed_count": 0}

    detay = await _detay(client, admin_headers, payment_id)
    line = detay["lines"][0]
    assert line["id"] == str(orphan_line_id)
    assert line["is_price_stale"] is None
    assert line["contract_item_id"] is None


async def test_pending_hakediste_refresh_409(
    client: AsyncClient, admin_headers: dict[str, str], onay_bekleyen_hakedis: uuid.UUID
) -> None:
    """§5.1: "onaya giden evrak sabittir" — `pending_approval`'da 409."""
    yanit = await client.post(
        f"/progress-payments/{onay_bekleyen_hakedis}/refresh-prices", headers=admin_headers
    )
    assert yanit.status_code == 409, yanit.text
    assert yanit.json()["detail"] == guards.INVALID_STATUS_TRANSITION


async def test_approved_hakediste_refresh_409(
    client: AsyncClient, admin_headers: dict[str, str], hakedis_fabrikasi
) -> None:
    """Yalnız `draft` — onaylanmış evrakın fiyatı asla değişmez (görev tarifi)."""
    payment_id = await hakedis_fabrikasi(ProgressPaymentStatus.approved)
    yanit = await client.post(
        f"/progress-payments/{payment_id}/refresh-prices", headers=admin_headers
    )
    assert yanit.status_code == 409, yanit.text
    assert yanit.json()["detail"] == guards.INVALID_STATUS_TRANSITION


async def test_paid_hakediste_refresh_409(
    client: AsyncClient, admin_headers: dict[str, str], hakedis_fabrikasi
) -> None:
    payment_id = await hakedis_fabrikasi(ProgressPaymentStatus.paid)
    yanit = await client.post(
        f"/progress-payments/{payment_id}/refresh-prices", headers=admin_headers
    )
    assert yanit.status_code == 409, yanit.text
    assert yanit.json()["detail"] == guards.INVALID_STATUS_TRANSITION


# --- 3. "Ne yapmamalı" (H6 dersi: kod ile test aynı yanlış varsayımı paylaşmasın) ---


async def test_refresh_miktar_ve_katsayiyi_bozmaz(
    client: AsyncClient,
    admin_headers: dict[str, str],
    seeded_db: AsyncSession,
    hakedis_fabrikasi,
    hakedis_kalemi: tuple[EmployerContractItem, str],
) -> None:
    """Fiyat tazelenirken kullanıcı verisi (miktar/katsayı) DOKUNULMAZ (plan
    Adım 3): `coefficient`/`quantity` kalemden gelen bir alan değildir."""
    item, _ = hakedis_kalemi
    payment_id = await hakedis_fabrikasi(ProgressPaymentStatus.draft)
    payment = await seeded_db.get(ProgressPayment, payment_id)
    payment.lines[0].coefficient = Decimal("1.250")
    payment.lines[0].quantity = Decimal("42.500")
    await seeded_db.flush()

    item.unit_price = Decimal("1900")
    await seeded_db.flush()

    yanit = await client.post(
        f"/progress-payments/{payment_id}/refresh-prices", headers=admin_headers
    )
    assert yanit.status_code == 200, yanit.text
    assert yanit.json() == {"refreshed_count": 1}

    detay = await _detay(client, admin_headers, payment_id)
    line = detay["lines"][0]
    assert Decimal(line["coefficient"]) == Decimal("1.250")
    assert Decimal(line["quantity"]) == Decimal("42.500")


async def test_refresh_satir_kimligini_ve_sirasini_degistirmez(
    client: AsyncClient,
    admin_headers: dict[str, str],
    seeded_db: AsyncSession,
    hakedis_fabrikasi,
    hakedis_kalemi: tuple[EmployerContractItem, str],
) -> None:
    """Tazeleme YERİNDE günceller — yeni satır YARATMAZ/SİLMEZ (`id`/`sort_order`
    korunur)."""
    item, _ = hakedis_kalemi
    payment_id = await hakedis_fabrikasi(ProgressPaymentStatus.draft)
    payment = await seeded_db.get(ProgressPayment, payment_id)
    onceki_id = payment.lines[0].id
    onceki_sort = payment.lines[0].sort_order

    item.unit_price = Decimal("1900")
    await seeded_db.flush()

    yanit = await client.post(
        f"/progress-payments/{payment_id}/refresh-prices", headers=admin_headers
    )
    assert yanit.status_code == 200, yanit.text
    assert yanit.json() == {"refreshed_count": 1}

    detay = await _detay(client, admin_headers, payment_id)
    line = detay["lines"][0]
    assert line["id"] == str(onceki_id)
    assert line["sort_order"] == onceki_sort
    assert Decimal(line["contract_unit_price"]) == Decimal("1900")


async def test_refresh_durumu_degistirmez(
    client: AsyncClient,
    admin_headers: dict[str, str],
    seeded_db: AsyncSession,
    hakedis_fabrikasi,
    hakedis_kalemi: tuple[EmployerContractItem, str],
) -> None:
    """`refresh-prices` bir durum GEÇİŞİ değildir — hakediş `draft` KALIR."""
    item, _ = hakedis_kalemi
    payment_id = await hakedis_fabrikasi(ProgressPaymentStatus.draft)
    item.unit_price = Decimal("1900")
    await seeded_db.flush()

    yanit = await client.post(
        f"/progress-payments/{payment_id}/refresh-prices", headers=admin_headers
    )
    assert yanit.status_code == 200, yanit.text
    assert yanit.json() == {"refreshed_count": 1}

    seeded_db.expire_all()
    payment = await seeded_db.get(ProgressPayment, payment_id)
    assert payment.status is ProgressPaymentStatus.draft
    assert payment.submitted_at is None
    assert payment.lines[0].contract_unit_price == Decimal("1900")


# --- 4. İzin kapısı + kapsam/IDOR (spec §9.0) ---


async def test_izinsiz_rol_403(
    client: AsyncClient, hr_headers: dict[str, str], hakedis_fabrikasi
) -> None:
    payment_id = await hakedis_fabrikasi(ProgressPaymentStatus.draft)
    yanit = await client.post(f"/progress-payments/{payment_id}/refresh-prices", headers=hr_headers)
    assert yanit.status_code == 403, yanit.text


async def test_gorunmeyen_hakediste_refresh_404_olmayanla_ayni(
    client: AsyncClient, kisitli_headers: dict[str, str], gorunmeyen_hakedis: uuid.UUID
) -> None:
    gercek = await client.post(
        f"/progress-payments/{gorunmeyen_hakedis}/refresh-prices", headers=kisitli_headers
    )
    sahte = await client.post(
        f"/progress-payments/{uuid.uuid4()}/refresh-prices", headers=kisitli_headers
    )
    assert gercek.status_code == sahte.status_code == 404, gercek.text
    assert gercek.json() == sahte.json() == {"detail": guards.PAYMENT_MISSING}
