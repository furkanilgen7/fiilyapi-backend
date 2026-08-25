"""Hakediş satırları — FF KİLİDİ · katsayı öntanımı · sıfır miktar · DURUM KAPISI ·
H6/K1 (kota YAZMA anında sırasız tam kümeden okunur).

`test_lines.py`nin ikinci parçası (800 satır tavanı bölmesi); paylaşılan
yardımcılar `_lines.py`dedir.

FF kapalı sözleşmede katsayı 422'dir ama BİRİM katsayı kabul edilir; sözleşme
sonradan kapatılınca mevcut taslak KİLİTLENMEZ, yalnız YENİ katsayı gönderimi
reddedilir. H6/K1: büyük sıralı onaylı varken küçük sıralı taslak kotayı AŞAMAZ.
"""

import uuid
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.contracts.models import EmployerContractItem
from app.modules.progress_payments import guards
from app.modules.projects.models import Project, ProjectContract
from app.modules.sites.models import Site

from ._lines import (
    _satir,
    _satir_sayisi,
)

pytestmark = pytest.mark.asyncio


async def test_ff_kapali_sozlesmede_katsayi_422(
    client: AsyncClient,
    admin_headers: dict[str, str],
    ff_kapali_ortam: tuple[uuid.UUID, EmployerContractItem, Site],
) -> None:
    payment_id, item, site = ff_kapali_ortam
    yanit = await client.put(
        f"/progress-payments/{payment_id}/lines",
        json={"lines": [_satir(item.id, site.id, "10", coefficient="1.142")]},
        headers=admin_headers,
    )
    assert yanit.status_code == 422, yanit.text
    assert yanit.json()["detail"] == guards.ESCALATION_DISABLED


async def test_ff_kapali_sozlesmede_birim_katsayi_kabul(
    client: AsyncClient,
    admin_headers: dict[str, str],
    ff_kapali_ortam: tuple[uuid.UUID, EmployerContractItem, Site],
) -> None:
    """Kilit yalnız `!= 1` katsayıya kapalıdır; `1.000` meşrudur."""
    payment_id, item, site = ff_kapali_ortam
    yanit = await client.put(
        f"/progress-payments/{payment_id}/lines",
        json={"lines": [_satir(item.id, site.id, "10", coefficient="1.000")]},
        headers=admin_headers,
    )
    assert yanit.status_code == 200, yanit.text


async def test_ff_acik_sozlesmede_katsayi_kabul(
    client: AsyncClient,
    admin_headers: dict[str, str],
    taslak_hakedis: uuid.UUID,
    hakedis_santiyesi: Site,
    hakedis_kalemi: tuple[EmployerContractItem, str],
) -> None:
    """`has_price_escalation=True` (varsayılan) sözleşmede katsayı serbesttir —
    kilidin kapsamı sözleşmeye bağlıdır, tüm hakedişlere değil."""
    item, _ = hakedis_kalemi
    yanit = await client.put(
        f"/progress-payments/{taslak_hakedis}/lines",
        json={"lines": [_satir(item.id, hakedis_santiyesi.id, "10", coefficient="1.142")]},
        headers=admin_headers,
    )
    assert yanit.status_code == 200, yanit.text
    satir = yanit.json()["lines"][0]
    assert Decimal(satir["coefficient"]) == Decimal("1.142")
    # 1850 × 1,142 = 2.112,70 (K5 kuruş kuralı, spec §6.1)
    assert Decimal(satir["adjusted_unit_price"]) == Decimal("2112.70")


async def test_ff_kapali_sozlesmede_baslik_katsayisi_post_422(
    client: AsyncClient,
    admin_headers: dict[str, str],
    ff_kapali_hakedissiz_proje: uuid.UUID,
) -> None:
    """Y1 (kullanıcı kararı 2026-07-31): kilit BAŞLIĞA da uygulanır. Aksi hâlde
    FF'siz sözleşmede `default_coefficient=1.4` kabul edilir, sonra o hakedişin
    HER satırı kilide takılırdı — hakediş doğuştan kullanılamaz olurdu."""
    yanit = await client.post(
        f"/projects/{ff_kapali_hakedissiz_proje}/progress-payments",
        json={"default_coefficient": "1.400"},
        headers=admin_headers,
    )
    assert yanit.status_code == 422, yanit.text
    assert yanit.json()["detail"] == guards.ESCALATION_DISABLED


async def test_ff_kapali_sozlesmede_baslik_katsayisi_patch_422(
    client: AsyncClient,
    admin_headers: dict[str, str],
    ff_kapali_ortam: tuple[uuid.UUID, EmployerContractItem, Site],
) -> None:
    """Y1: PATCH yolu POST'la AYNI kurala tabidir — arka kapı bırakılmaz."""
    payment_id, _, _ = ff_kapali_ortam
    yanit = await client.patch(
        f"/progress-payments/{payment_id}",
        json={"default_coefficient": "1.400"},
        headers=admin_headers,
    )
    assert yanit.status_code == 422, yanit.text
    assert yanit.json()["detail"] == guards.ESCALATION_DISABLED


async def test_ff_sonradan_kapatilinca_taslak_kilitlenmez(
    client: AsyncClient,
    admin_headers: dict[str, str],
    taslak_hakedis: uuid.UUID,
    hakedis_sozlesmesi: tuple[Project, ProjectContract],
    hakedis_santiyesi: Site,
    hakedis_kalemi: tuple[EmployerContractItem, str],
    seeded_db: AsyncSession,
) -> None:
    """Y1 kilitlenme senaryosu (kullanıcı kararı 2026-07-31): FF açıkken yazılmış
    ≠1 katsayı, FF sonradan kapatılınca KORUNUR (grandfather) ve satır katsayı
    GÖNDERİLMEDEN güncellenebilir. Kilit saklanan değere geriye dönük uygulansaydı
    taslak bir daha HİÇBİR şekilde kaydedilemezdi."""
    _, contract = hakedis_sozlesmesi
    item, _ = hakedis_kalemi
    ilk = await client.put(
        f"/progress-payments/{taslak_hakedis}/lines",
        json={"lines": [_satir(item.id, hakedis_santiyesi.id, "10", coefficient="1.142")]},
        headers=admin_headers,
    )
    assert ilk.status_code == 200, ilk.text

    contract.has_price_escalation = False
    await seeded_db.flush()

    yanit = await client.put(
        f"/progress-payments/{taslak_hakedis}/lines",
        json={"lines": [_satir(item.id, hakedis_santiyesi.id, "20")]},
        headers=admin_headers,
    )
    assert yanit.status_code == 200, yanit.text
    satir = yanit.json()["lines"][0]
    assert Decimal(satir["quantity"]) == Decimal("20")
    assert Decimal(satir["coefficient"]) == Decimal("1.142")


async def test_ff_sonradan_kapatilinca_yeni_katsayi_gonderimi_422(
    client: AsyncClient,
    admin_headers: dict[str, str],
    taslak_hakedis: uuid.UUID,
    hakedis_sozlesmesi: tuple[Project, ProjectContract],
    hakedis_santiyesi: Site,
    hakedis_kalemi: tuple[EmployerContractItem, str],
    seeded_db: AsyncSession,
) -> None:
    """Grandfather kuralının SINIRI: eski değer korunur ama YENİ ≠1 katsayı
    gönderimi FF kapalıyken yine 422'dir."""
    _, contract = hakedis_sozlesmesi
    item, _ = hakedis_kalemi
    await client.put(
        f"/progress-payments/{taslak_hakedis}/lines",
        json={"lines": [_satir(item.id, hakedis_santiyesi.id, "10", coefficient="1.142")]},
        headers=admin_headers,
    )
    contract.has_price_escalation = False
    await seeded_db.flush()

    yanit = await client.put(
        f"/progress-payments/{taslak_hakedis}/lines",
        json={"lines": [_satir(item.id, hakedis_santiyesi.id, "10", coefficient="1.300")]},
        headers=admin_headers,
    )
    assert yanit.status_code == 422, yanit.text
    assert yanit.json()["detail"] == guards.ESCALATION_DISABLED


# --- Katsayı öntanımı (spec §4.1) ---


async def test_yeni_satira_default_coefficient_iner(
    client: AsyncClient,
    admin_headers: dict[str, str],
    sozlesmeli_proje: uuid.UUID,
    hakedis_santiyesi: Site,
    hakedis_kalemi: tuple[EmployerContractItem, str],
) -> None:
    item, _ = hakedis_kalemi
    olusturma = await client.post(
        f"/projects/{sozlesmeli_proje}/progress-payments",
        json={"default_coefficient": "1.250"},
        headers=admin_headers,
    )
    payment_id = olusturma.json()["id"]
    yanit = await client.put(
        f"/progress-payments/{payment_id}/lines",
        json={"lines": [_satir(item.id, hakedis_santiyesi.id, "10")]},
        headers=admin_headers,
    )
    assert yanit.status_code == 200, yanit.text
    assert Decimal(yanit.json()["lines"][0]["coefficient"]) == Decimal("1.250")


async def test_gonderilmeyen_katsayi_mevcut_satiri_degistirmez(
    client: AsyncClient,
    admin_headers: dict[str, str],
    taslak_hakedis: uuid.UUID,
    hakedis_santiyesi: Site,
    hakedis_kalemi: tuple[EmployerContractItem, str],
) -> None:
    """§4.1: öntanım YALNIZ yeni satıra iner; var olan satırın katsayısı
    gönderilmediğinde KORUNUR (sessizce 1.000'e düşmez)."""
    item, _ = hakedis_kalemi
    await client.put(
        f"/progress-payments/{taslak_hakedis}/lines",
        json={"lines": [_satir(item.id, hakedis_santiyesi.id, "10", coefficient="1.142")]},
        headers=admin_headers,
    )
    yanit = await client.put(
        f"/progress-payments/{taslak_hakedis}/lines",
        json={"lines": [_satir(item.id, hakedis_santiyesi.id, "20")]},
        headers=admin_headers,
    )
    assert Decimal(yanit.json()["lines"][0]["coefficient"]) == Decimal("1.142")


# --- Sıfır miktar (OLU 172) ---


async def test_sifir_miktarli_satir_kabul(
    client: AsyncClient,
    admin_headers: dict[str, str],
    taslak_hakedis: uuid.UUID,
    hakedis_santiyesi: Site,
    hakedis_kalemi: tuple[EmployerContractItem, str],
    seeded_db: AsyncSession,
) -> None:
    """`0` MEŞRUDUR (sıfır iş) — silme DEĞİL: satır DB'de durur (spec §10/3)."""
    item, _ = hakedis_kalemi
    yanit = await client.put(
        f"/progress-payments/{taslak_hakedis}/lines",
        json={"lines": [_satir(item.id, hakedis_santiyesi.id, "0")]},
        headers=admin_headers,
    )
    assert yanit.status_code == 200, yanit.text
    assert Decimal(yanit.json()["lines"][0]["quantity"]) == Decimal("0")
    assert await _satir_sayisi(seeded_db, taslak_hakedis) == 1


# --- Durum kapısı ve erişim (spec §7, §9.0) ---


async def test_pending_hakediste_lines_409(
    client: AsyncClient, admin_headers: dict[str, str], onay_bekleyen_hakedis: uuid.UUID
) -> None:
    yanit = await client.put(
        f"/progress-payments/{onay_bekleyen_hakedis}/lines",
        json={"lines": []},
        headers=admin_headers,
    )
    assert yanit.status_code == 409, yanit.text
    assert yanit.json()["detail"] == guards.INVALID_STATUS_TRANSITION


async def test_gorunmeyen_hakediste_lines_404_olmayanla_ayni(
    client: AsyncClient, kisitli_headers: dict[str, str], gorunmeyen_hakedis: uuid.UUID
) -> None:
    gercek = await client.put(
        f"/progress-payments/{gorunmeyen_hakedis}/lines",
        json={"lines": []},
        headers=kisitli_headers,
    )
    sahte = await client.put(
        f"/progress-payments/{uuid.uuid4()}/lines", json={"lines": []}, headers=kisitli_headers
    )
    assert gercek.status_code == sahte.status_code == 404
    assert gercek.json() == sahte.json()


async def test_yetkisiz_rol_lines_403(
    client: AsyncClient, hr_headers: dict[str, str], taslak_hakedis: uuid.UUID
) -> None:
    """İK matris satırı `_N`: kapı görünürlükten ÖNCE çalışır → 403."""
    yanit = await client.put(
        f"/progress-payments/{taslak_hakedis}/lines", json={"lines": []}, headers=hr_headers
    )
    assert yanit.status_code == 403


# --- H6 denetimi K1: kota YAZMA anında da sırasız tam kümeden okunur ---


async def test_buyuk_sirali_onayli_varken_kucuk_sirali_taslak_kotayi_asamaz(
    client: AsyncClient,
    admin_headers: dict[str, str],
    ters_sirali_onayli_gecmis: tuple[uuid.UUID, EmployerContractItem, Site],
) -> None:
    """Kota tavanı `sequence_no`'dan BAĞIMSIZDIR — yazma anında da (H6 denetimi K1).

    Kurulum: kota 1.000, `sequence_no=2` hakediş ONAYLI (600), `sequence_no=1`
    hakediş taslak. Sıra tabanlı okumada taslağın "önceki" kümesi BOŞ olurdu
    (`seq < 1`) ve 500 birim SESSİZCE yazılırdı; sırasız tam küme 600+500 = 1.100
    > 1.000 ile 422 verir. Sömürü zincirinin sızdıran yazma adımı buydu.
    """
    payment_id, item, site = ters_sirali_onayli_gecmis
    yanit = await client.put(
        f"/progress-payments/{payment_id}/lines",
        json={"lines": [_satir(item.id, site.id, "500")]},
        headers=admin_headers,
    )
    assert yanit.status_code == 422, yanit.text
    assert yanit.json()["detail"] == guards.QUANTITY_EXCEEDS_QUOTA


async def test_buyuk_sirali_onayli_varken_sigan_miktar_yazilabilir(
    client: AsyncClient,
    admin_headers: dict[str, str],
    ters_sirali_onayli_gecmis: tuple[uuid.UUID, EmployerContractItem, Site],
) -> None:
    """Karşı-test: aynı kurulumda kotaya SIĞAN miktar (400) yazılabilir — kural
    "sıra bozuksa hep reddet" değil, gerçek bir toplam kontrolüdür."""
    payment_id, item, site = ters_sirali_onayli_gecmis
    yanit = await client.put(
        f"/progress-payments/{payment_id}/lines",
        json={"lines": [_satir(item.id, site.id, "400")]},
        headers=admin_headers,
    )
    assert yanit.status_code == 200, yanit.text
