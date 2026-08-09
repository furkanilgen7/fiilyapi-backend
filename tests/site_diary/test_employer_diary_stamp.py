"""TB4 T1 (B1/SD-2) — İŞVEREN hakediş satırının sunucu-tarafı `diary` damgası.

Kural (spec §1 B1 + §5 S1, ONAYLI): `PUT /progress-payments/{id}/lines` ile
kalıcılaşan her satırın miktarı, hakedişin KENDİ DÖNEMİNE ait **yalnız
`submitted`** günlüklerin poz-bazlı toplamıyla karşılaştırılır; **birebir eşitse**
`quantity_source=diary`, aksi HER durumda `manual`. Damga her PUT'ta YENİDEN
türetilir ve gövdeden ASLA alınmaz.

Damga yanıt şemasında (işveren `ProgressPaymentLineDetail`) YOKTUR — bu dilim
şema açmaz (spec §4: openapi farkı yalnız B4). Bu yüzden doğrulama DB'den
okunur; kaynak-of-truth zaten satırın kolonudur.
"""

import uuid
from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.progress_payments.models import ProgressPaymentLine
from app.modules.subcontractor_progress_payments.models import QuantitySource

pytestmark = pytest.mark.asyncio

DONEM = {"period_year": 2026, "period_month": 7}


async def _hakedis(client: AsyncClient, headers: dict[str, str], project_id, **govde) -> dict:
    yanit = await client.post(
        f"/projects/{project_id}/progress-payments", json=govde, headers=headers
    )
    assert yanit.status_code == 201, yanit.text
    return yanit.json()


async def _kaydet(client: AsyncClient, headers: dict[str, str], payment_id, satirlar: list[dict]):
    return await client.put(
        f"/progress-payments/{payment_id}/lines", json={"lines": satirlar}, headers=headers
    )


async def _damgalar(session: AsyncSession, payment_id) -> dict[uuid.UUID, QuantitySource]:
    satirlar = (
        (
            await session.execute(
                select(ProgressPaymentLine)
                .where(ProgressPaymentLine.payment_id == uuid.UUID(str(payment_id)))
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )
    return {satir.contract_item_id: satir.quantity_source for satir in satirlar}


# --- 1) Günlük toplamı = satır miktarı → diary ---


async def test_gunluk_toplamiyla_BIREBIR_esit_satir_diary_damgalanir(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers,
    santiye,
    sozlesme_kalemi_fabrikasi,
    gunluk_api,
) -> None:
    site, project, items = santiye
    kalem = sorted(items, key=lambda i: i.code)[0]
    sozlesme = await sozlesme_kalemi_fabrikasi(kalem, project)
    await gunluk_api(
        admin_headers,
        site.id,
        date(2026, 7, 10),
        [{"boq_item_id": str(kalem.id), "quantity": "10"}],
    )
    await gunluk_api(
        admin_headers, site.id, date(2026, 7, 12), [{"boq_item_id": str(kalem.id), "quantity": "5"}]
    )

    hakedis = await _hakedis(client, admin_headers, project.id, **DONEM)
    yanit = await _kaydet(
        client,
        admin_headers,
        hakedis["id"],
        [{"contract_item_id": str(sozlesme.id), "site_id": str(site.id), "quantity": "15"}],
    )
    assert yanit.status_code == 200, yanit.text
    assert await _damgalar(seeded_db, hakedis["id"]) == {sozlesme.id: QuantitySource.diary}


# --- 2) Farklı miktar (kısmi ve fazla) → manual ---


@pytest.mark.parametrize("miktar", ["9", "16"])
async def test_gunluk_toplamindan_FARKLI_miktar_manual_kalir(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers,
    santiye,
    sozlesme_kalemi_fabrikasi,
    gunluk_api,
    miktar: str,
) -> None:
    """Kısmi (9 < 15) ve fazla (16 > 15) AYNI sonucu verir: yarım eşleşmeye
    `diary` rozeti basmak kullanıcıyı yanıltırdı (S1)."""
    site, project, items = santiye
    kalem = sorted(items, key=lambda i: i.code)[0]
    sozlesme = await sozlesme_kalemi_fabrikasi(kalem, project)
    await gunluk_api(
        admin_headers,
        site.id,
        date(2026, 7, 10),
        [{"boq_item_id": str(kalem.id), "quantity": "15"}],
    )

    hakedis = await _hakedis(client, admin_headers, project.id, **DONEM)
    yanit = await _kaydet(
        client,
        admin_headers,
        hakedis["id"],
        [{"contract_item_id": str(sozlesme.id), "site_id": str(site.id), "quantity": miktar}],
    )
    assert yanit.status_code == 200, yanit.text
    assert await _damgalar(seeded_db, hakedis["id"]) == {sozlesme.id: QuantitySource.manual}


# --- 3) Taslak günlük SAYILMAZ ---


async def test_yalniz_TASLAK_gunluk_varsa_miktar_esitse_bile_manual(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers,
    santiye,
    sozlesme_kalemi_fabrikasi,
    gunluk_api,
) -> None:
    """ "Taslak günler tabloya girmez" emsali: gönderilmemiş gün bir iddia değildir."""
    site, project, items = santiye
    kalem = sorted(items, key=lambda i: i.code)[0]
    sozlesme = await sozlesme_kalemi_fabrikasi(kalem, project)
    await gunluk_api(
        admin_headers,
        site.id,
        date(2026, 7, 10),
        [{"boq_item_id": str(kalem.id), "quantity": "15"}],
        gonder=False,
    )

    hakedis = await _hakedis(client, admin_headers, project.id, **DONEM)
    yanit = await _kaydet(
        client,
        admin_headers,
        hakedis["id"],
        [{"contract_item_id": str(sozlesme.id), "site_id": str(site.id), "quantity": "15"}],
    )
    assert yanit.status_code == 200, yanit.text
    assert await _damgalar(seeded_db, hakedis["id"]) == {sozlesme.id: QuantitySource.manual}


# --- 4) Köprüsüz satır → manual ---


async def test_gunlugu_olmayan_kalem_manual_kalir(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers,
    santiye,
    sozlesme_kalemi_fabrikasi,
    gunluk_api,
) -> None:
    """Aynı gövdede iki satır: biri günlükten gelir (`diary`), diğerinin günlükte
    hiç kaydı yoktur (`manual`) — damga SATIR BAZINDADIR."""
    site, project, items = santiye
    kalem_a, kalem_b = sorted(items, key=lambda i: i.code)
    sozlesme_a = await sozlesme_kalemi_fabrikasi(kalem_a, project)
    sozlesme_b = await sozlesme_kalemi_fabrikasi(kalem_b, project)
    await gunluk_api(
        admin_headers,
        site.id,
        date(2026, 7, 10),
        [{"boq_item_id": str(kalem_a.id), "quantity": "12"}],
    )

    hakedis = await _hakedis(client, admin_headers, project.id, **DONEM)
    yanit = await _kaydet(
        client,
        admin_headers,
        hakedis["id"],
        [
            {"contract_item_id": str(sozlesme_a.id), "site_id": str(site.id), "quantity": "12"},
            {"contract_item_id": str(sozlesme_b.id), "site_id": str(site.id), "quantity": "3"},
        ],
    )
    assert yanit.status_code == 200, yanit.text
    assert await _damgalar(seeded_db, hakedis["id"]) == {
        sozlesme_a.id: QuantitySource.diary,
        sozlesme_b.id: QuantitySource.manual,
    }


async def test_baska_santiyenin_gunlugu_damgayi_DOLDURMAZ(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers,
    santiye,
    santiye_fabrikasi,
    sozlesme_kalemi_fabrikasi,
    gunluk_api,
    proje,
) -> None:
    """Hücre kimliği (kalem, ŞANTİYE) çiftidir: A şantiyesinin günlüğü B
    şantiyesinin satırını damgalayamaz."""
    site_a, project, items_a = santiye
    site_b, _, items_b = await santiye_fabrikasi("SD-B", project=proje)
    kalem_a = sorted(items_a, key=lambda i: i.code)[0]
    kalem_b = sorted(items_b, key=lambda i: i.code)[0]
    sozlesme = await sozlesme_kalemi_fabrikasi(kalem_a, project)
    kalem_b.contract_item_id = sozlesme.id
    await seeded_db.flush()

    await gunluk_api(
        admin_headers,
        site_a.id,
        date(2026, 7, 10),
        [{"boq_item_id": str(kalem_a.id), "quantity": "8"}],
    )

    hakedis = await _hakedis(client, admin_headers, project.id, **DONEM)
    yanit = await _kaydet(
        client,
        admin_headers,
        hakedis["id"],
        [{"contract_item_id": str(sozlesme.id), "site_id": str(site_b.id), "quantity": "8"}],
    )
    assert yanit.status_code == 200, yanit.text
    assert await _damgalar(seeded_db, hakedis["id"]) == {sozlesme.id: QuantitySource.manual}


# --- Dönem süzgeci ---


async def test_BASKA_ayin_gunlugu_damgayi_DOLDURMAZ(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers,
    santiye,
    sozlesme_kalemi_fabrikasi,
    gunluk_api,
) -> None:
    site, project, items = santiye
    kalem = sorted(items, key=lambda i: i.code)[0]
    sozlesme = await sozlesme_kalemi_fabrikasi(kalem, project)
    await gunluk_api(
        admin_headers,
        site.id,
        date(2026, 6, 10),
        [{"boq_item_id": str(kalem.id), "quantity": "15"}],
    )

    hakedis = await _hakedis(client, admin_headers, project.id, **DONEM)
    yanit = await _kaydet(
        client,
        admin_headers,
        hakedis["id"],
        [{"contract_item_id": str(sozlesme.id), "site_id": str(site.id), "quantity": "15"}],
    )
    assert yanit.status_code == 200, yanit.text
    assert await _damgalar(seeded_db, hakedis["id"]) == {sozlesme.id: QuantitySource.manual}


async def test_DONEMSIZ_hakedis_damgalanmaz(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers,
    santiye,
    sozlesme_kalemi_fabrikasi,
    gunluk_api,
) -> None:
    """`period_year` boşsa "hakedişin kendi dönemi" YOKTUR; tüm zamanların
    toplamıyla kıyaslamak uydurma bir iddia olurdu → `manual`."""
    site, project, items = santiye
    kalem = sorted(items, key=lambda i: i.code)[0]
    sozlesme = await sozlesme_kalemi_fabrikasi(kalem, project)
    await gunluk_api(
        admin_headers,
        site.id,
        date(2026, 7, 10),
        [{"boq_item_id": str(kalem.id), "quantity": "15"}],
    )

    hakedis = await _hakedis(client, admin_headers, project.id)
    yanit = await _kaydet(
        client,
        admin_headers,
        hakedis["id"],
        [{"contract_item_id": str(sozlesme.id), "site_id": str(site.id), "quantity": "15"}],
    )
    assert yanit.status_code == 200, yanit.text
    assert await _damgalar(seeded_db, hakedis["id"]) == {sozlesme.id: QuantitySource.manual}


# --- 5) Damga her PUT'ta TAZELENİR ---


async def test_ikinci_PUTta_damga_her_iki_yonde_TAZELENIR(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers,
    santiye,
    sozlesme_kalemi_fabrikasi,
    gunluk_api,
) -> None:
    """Miktar değişince kaynak İDDİASI da düşer; geri dönülünce yeniden basılır."""
    site, project, items = santiye
    kalem = sorted(items, key=lambda i: i.code)[0]
    sozlesme = await sozlesme_kalemi_fabrikasi(kalem, project)
    await gunluk_api(
        admin_headers,
        site.id,
        date(2026, 7, 10),
        [{"boq_item_id": str(kalem.id), "quantity": "15"}],
    )
    hakedis = await _hakedis(client, admin_headers, project.id, **DONEM)

    def _govde(miktar: str) -> list[dict]:
        return [{"contract_item_id": str(sozlesme.id), "site_id": str(site.id), "quantity": miktar}]

    assert (await _kaydet(client, admin_headers, hakedis["id"], _govde("15"))).status_code == 200
    assert await _damgalar(seeded_db, hakedis["id"]) == {sozlesme.id: QuantitySource.diary}

    # diary → manual (miktar günlükten ayrıldı)
    assert (await _kaydet(client, admin_headers, hakedis["id"], _govde("11"))).status_code == 200
    assert await _damgalar(seeded_db, hakedis["id"]) == {sozlesme.id: QuantitySource.manual}

    # manual → diary (miktar günlüğe geri döndü)
    assert (await _kaydet(client, admin_headers, hakedis["id"], _govde("15"))).status_code == 200
    assert await _damgalar(seeded_db, hakedis["id"]) == {sozlesme.id: QuantitySource.diary}


# --- 6) Gövdeden damga sızdırılamaz ---


async def test_govdedeki_quantity_source_ETKISIZDIR(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers,
    santiye,
    sozlesme_kalemi_fabrikasi,
    gunluk_api,
) -> None:
    """Giriş şemasında böyle bir alan YOKTUR (bilinçli kural): gönderilse bile
    yok sayılır — `diary` rozeti istekle sahte doldurulamaz."""
    site, project, items = santiye
    kalem = sorted(items, key=lambda i: i.code)[0]
    sozlesme = await sozlesme_kalemi_fabrikasi(kalem, project)
    await gunluk_api(
        admin_headers,
        site.id,
        date(2026, 7, 10),
        [{"boq_item_id": str(kalem.id), "quantity": "15"}],
    )

    hakedis = await _hakedis(client, admin_headers, project.id, **DONEM)
    yanit = await _kaydet(
        client,
        admin_headers,
        hakedis["id"],
        [
            {
                "contract_item_id": str(sozlesme.id),
                "site_id": str(site.id),
                "quantity": "7",
                "quantity_source": "diary",
            }
        ],
    )
    assert yanit.status_code == 200, yanit.text
    assert await _damgalar(seeded_db, hakedis["id"]) == {sozlesme.id: QuantitySource.manual}


# --- POST'un iç içe `lines[]` yolu da AYNI damgayı basar (arka kapı yok) ---


async def test_POST_ic_ice_satirlar_da_damgalanir(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers,
    santiye,
    sozlesme_kalemi_fabrikasi,
    gunluk_api,
) -> None:
    site, project, items = santiye
    kalem = sorted(items, key=lambda i: i.code)[0]
    sozlesme = await sozlesme_kalemi_fabrikasi(kalem, project)
    await gunluk_api(
        admin_headers,
        site.id,
        date(2026, 7, 10),
        [{"boq_item_id": str(kalem.id), "quantity": "15"}],
    )

    hakedis = await _hakedis(
        client,
        admin_headers,
        project.id,
        **DONEM,
        lines=[{"contract_item_id": str(sozlesme.id), "site_id": str(site.id), "quantity": "15"}],
    )
    assert await _damgalar(seeded_db, hakedis["id"]) == {sozlesme.id: QuantitySource.diary}
