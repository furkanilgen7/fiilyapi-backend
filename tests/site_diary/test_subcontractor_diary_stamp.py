"""TB4 T1 (B1/SD-2) — TAŞERON hakediş satırının sunucu-tarafı `diary` damgası.

İşveren ikizi `test_employer_diary_stamp.py` ile AYNI kural; İKİ FARK bilinçlidir:

* köprü İKİ ADIMLIDIR (`boq_items.contract_item_id` → `subcontractor_contract_items.
  source_contract_item_id`) ve şantiye süzgeci SÖZLEŞMEDEN gelir,
* `site_id` NULL olan proje-geneli sözleşmede günlük köprüsü YOKTUR (öneri ucunun
  spec §7 S5 kuralı) → o satırlar HER ZAMAN `manual`.

Damga taşeron yanıt şemasında zaten VARDIR (`quantity_source`), bu yüzden
doğrulama uçtan uca yanıttan okunur.
"""

from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.contracts.models import SubcontractorContractItem

pytestmark = pytest.mark.asyncio

DONEM = {"period_year": 2026, "period_month": 7}


async def _hakedis(client: AsyncClient, headers: dict[str, str], contract_id, **govde) -> dict:
    yanit = await client.post(
        f"/subcontractor-contracts/{contract_id}/progress-payments", json=govde, headers=headers
    )
    assert yanit.status_code == 201, yanit.text
    return yanit.json()


async def _kaydet(client: AsyncClient, headers: dict[str, str], payment_id, satirlar: list[dict]):
    return await client.put(
        f"/subcontractor-progress-payments/{payment_id}/lines",
        json={"lines": satirlar},
        headers=headers,
    )


async def _kalem_id(session: AsyncSession, contract_id, code: str):
    return (
        await session.execute(
            select(SubcontractorContractItem.id).where(
                SubcontractorContractItem.contract_id == contract_id,
                SubcontractorContractItem.code == code,
            )
        )
    ).scalar_one()


def _damgalar(govde: dict) -> dict[str, str]:
    """Yalnız miktarı olan satırlar: hakediş açılışı TÜM kalemleri 0 ile kurar."""
    return {
        satir["contract_item_id"]: satir["quantity_source"]
        for satir in govde["lines"]
        if Decimal(satir["quantity"]) != 0
    }


@pytest.fixture
async def kurulum(santiye, sozlesme_kalemi_fabrikasi, taseron_sozlesmesi_fabrikasi):
    """Şantiye + iki köprülü poz + iki kalemli taşeron sözleşmesi."""
    site, project, items = santiye
    kalem_a, kalem_b = sorted(items, key=lambda i: i.code)
    sozlesme_a = await sozlesme_kalemi_fabrikasi(kalem_a, project)
    sozlesme_b = await sozlesme_kalemi_fabrikasi(kalem_b, project)
    contract = await taseron_sozlesmesi_fabrikasi(
        project, site=site, kalemler=[("TK-1", sozlesme_a), ("TK-2", sozlesme_b)]
    )
    return site, project, (kalem_a, kalem_b), contract


# --- 1) Günlük toplamı = satır miktarı → diary ---


async def test_gunluk_toplamiyla_BIREBIR_esit_satir_diary_damgalanir(
    client: AsyncClient, seeded_db: AsyncSession, admin_headers, kurulum, gunluk_api
) -> None:
    site, _, (kalem_a, _), contract = kurulum
    await gunluk_api(
        admin_headers,
        site.id,
        date(2026, 7, 10),
        [{"boq_item_id": str(kalem_a.id), "quantity": "10"}],
    )
    await gunluk_api(
        admin_headers,
        site.id,
        date(2026, 7, 12),
        [{"boq_item_id": str(kalem_a.id), "quantity": "2.5"}],
    )
    tk1 = await _kalem_id(seeded_db, contract.id, "TK-1")

    hakedis = await _hakedis(client, admin_headers, contract.id, **DONEM)
    yanit = await _kaydet(
        client, admin_headers, hakedis["id"], [{"contract_item_id": str(tk1), "quantity": "12.5"}]
    )
    assert yanit.status_code == 200, yanit.text
    assert _damgalar(yanit.json()) == {str(tk1): "diary"}


# --- 2) Farklı miktar (kısmi ve fazla) → manual ---


@pytest.mark.parametrize("miktar", ["6", "20"])
async def test_gunluk_toplamindan_FARKLI_miktar_manual_kalir(
    client: AsyncClient, seeded_db: AsyncSession, admin_headers, kurulum, gunluk_api, miktar: str
) -> None:
    site, _, (kalem_a, _), contract = kurulum
    await gunluk_api(
        admin_headers,
        site.id,
        date(2026, 7, 10),
        [{"boq_item_id": str(kalem_a.id), "quantity": "12"}],
    )
    tk1 = await _kalem_id(seeded_db, contract.id, "TK-1")

    hakedis = await _hakedis(client, admin_headers, contract.id, **DONEM)
    yanit = await _kaydet(
        client, admin_headers, hakedis["id"], [{"contract_item_id": str(tk1), "quantity": miktar}]
    )
    assert yanit.status_code == 200, yanit.text
    assert _damgalar(yanit.json()) == {str(tk1): "manual"}


# --- 3) Taslak günlük SAYILMAZ ---


async def test_yalniz_TASLAK_gunluk_varsa_miktar_esitse_bile_manual(
    client: AsyncClient, seeded_db: AsyncSession, admin_headers, kurulum, gunluk_api
) -> None:
    site, _, (kalem_a, _), contract = kurulum
    await gunluk_api(
        admin_headers,
        site.id,
        date(2026, 7, 10),
        [{"boq_item_id": str(kalem_a.id), "quantity": "12"}],
        gonder=False,
    )
    tk1 = await _kalem_id(seeded_db, contract.id, "TK-1")

    hakedis = await _hakedis(client, admin_headers, contract.id, **DONEM)
    yanit = await _kaydet(
        client, admin_headers, hakedis["id"], [{"contract_item_id": str(tk1), "quantity": "12"}]
    )
    assert yanit.status_code == 200, yanit.text
    assert _damgalar(yanit.json()) == {str(tk1): "manual"}


# --- 4) Köprüsüz satır → manual ---


async def test_gunlugu_olmayan_kalem_manual_kalir(
    client: AsyncClient, seeded_db: AsyncSession, admin_headers, kurulum, gunluk_api
) -> None:
    """Damga SATIR bazındadır: aynı gövdede biri `diary`, diğeri `manual`."""
    site, _, (kalem_a, _), contract = kurulum
    await gunluk_api(
        admin_headers,
        site.id,
        date(2026, 7, 10),
        [{"boq_item_id": str(kalem_a.id), "quantity": "12"}],
    )
    tk1 = await _kalem_id(seeded_db, contract.id, "TK-1")
    tk2 = await _kalem_id(seeded_db, contract.id, "TK-2")

    hakedis = await _hakedis(client, admin_headers, contract.id, **DONEM)
    yanit = await _kaydet(
        client,
        admin_headers,
        hakedis["id"],
        [
            {"contract_item_id": str(tk1), "quantity": "12"},
            {"contract_item_id": str(tk2), "quantity": "4"},
        ],
    )
    assert yanit.status_code == 200, yanit.text
    assert _damgalar(yanit.json()) == {str(tk1): "diary", str(tk2): "manual"}


async def test_KOPRUSUZ_taseron_kalemi_manual_kalir(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers,
    santiye,
    sozlesme_kalemi_fabrikasi,
    taseron_sozlesmesi_fabrikasi,
    gunluk_api,
) -> None:
    """`source_contract_item_id` boş kalem hangi poza karşılık geldiğini
    BİLMEZ — günlükte aynı miktar dursa bile damgalanamaz."""
    site, project, items = santiye
    kalem_a = sorted(items, key=lambda i: i.code)[0]
    await sozlesme_kalemi_fabrikasi(kalem_a, project)
    contract = await taseron_sozlesmesi_fabrikasi(
        project, site=site, kalemler=[("TK-X", None)], code="TS-KOPRUSUZ"
    )
    await gunluk_api(
        admin_headers,
        site.id,
        date(2026, 7, 10),
        [{"boq_item_id": str(kalem_a.id), "quantity": "12"}],
    )
    tkx = await _kalem_id(seeded_db, contract.id, "TK-X")

    hakedis = await _hakedis(client, admin_headers, contract.id, **DONEM)
    yanit = await _kaydet(
        client, admin_headers, hakedis["id"], [{"contract_item_id": str(tkx), "quantity": "12"}]
    )
    assert yanit.status_code == 200, yanit.text
    assert _damgalar(yanit.json()) == {str(tkx): "manual"}


async def test_SANTIYESIZ_sozlesmede_damga_BASILMAZ(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers,
    santiye,
    sozlesme_kalemi_fabrikasi,
    taseron_sozlesmesi_fabrikasi,
    gunluk_api,
) -> None:
    """Spec §7 S5'in yazma-yolu karşılığı: proje-geneli sözleşmede hangi
    şantiyenin günlüğüne bakılacağı belirsizdir → köprü yok, `manual`."""
    site, project, items = santiye
    kalem_a = sorted(items, key=lambda i: i.code)[0]
    sozlesme_a = await sozlesme_kalemi_fabrikasi(kalem_a, project)
    contract = await taseron_sozlesmesi_fabrikasi(
        project, site=None, kalemler=[("TK-1", sozlesme_a)], code="TS-GENEL"
    )
    await gunluk_api(
        admin_headers,
        site.id,
        date(2026, 7, 10),
        [{"boq_item_id": str(kalem_a.id), "quantity": "12"}],
    )
    tk1 = await _kalem_id(seeded_db, contract.id, "TK-1")

    hakedis = await _hakedis(client, admin_headers, contract.id, **DONEM)
    yanit = await _kaydet(
        client, admin_headers, hakedis["id"], [{"contract_item_id": str(tk1), "quantity": "12"}]
    )
    assert yanit.status_code == 200, yanit.text
    assert _damgalar(yanit.json()) == {str(tk1): "manual"}


# --- Dönem süzgeci ---


async def test_BASKA_ayin_gunlugu_damgayi_DOLDURMAZ(
    client: AsyncClient, seeded_db: AsyncSession, admin_headers, kurulum, gunluk_api
) -> None:
    site, _, (kalem_a, _), contract = kurulum
    await gunluk_api(
        admin_headers,
        site.id,
        date(2026, 6, 10),
        [{"boq_item_id": str(kalem_a.id), "quantity": "12"}],
    )
    tk1 = await _kalem_id(seeded_db, contract.id, "TK-1")

    hakedis = await _hakedis(client, admin_headers, contract.id, **DONEM)
    yanit = await _kaydet(
        client, admin_headers, hakedis["id"], [{"contract_item_id": str(tk1), "quantity": "12"}]
    )
    assert yanit.status_code == 200, yanit.text
    assert _damgalar(yanit.json()) == {str(tk1): "manual"}


async def test_DONEMSIZ_hakedis_damgalanmaz(
    client: AsyncClient, seeded_db: AsyncSession, admin_headers, kurulum, gunluk_api
) -> None:
    site, _, (kalem_a, _), contract = kurulum
    await gunluk_api(
        admin_headers,
        site.id,
        date(2026, 7, 10),
        [{"boq_item_id": str(kalem_a.id), "quantity": "12"}],
    )
    tk1 = await _kalem_id(seeded_db, contract.id, "TK-1")

    hakedis = await _hakedis(client, admin_headers, contract.id)
    yanit = await _kaydet(
        client, admin_headers, hakedis["id"], [{"contract_item_id": str(tk1), "quantity": "12"}]
    )
    assert yanit.status_code == 200, yanit.text
    assert _damgalar(yanit.json()) == {str(tk1): "manual"}


# --- 5) Damga her PUT'ta TAZELENİR ---


async def test_ikinci_PUTta_damga_her_iki_yonde_TAZELENIR(
    client: AsyncClient, seeded_db: AsyncSession, admin_headers, kurulum, gunluk_api
) -> None:
    site, _, (kalem_a, _), contract = kurulum
    await gunluk_api(
        admin_headers,
        site.id,
        date(2026, 7, 10),
        [{"boq_item_id": str(kalem_a.id), "quantity": "12"}],
    )
    tk1 = await _kalem_id(seeded_db, contract.id, "TK-1")
    hakedis = await _hakedis(client, admin_headers, contract.id, **DONEM)

    async def _damga(miktar: str) -> str:
        yanit = await _kaydet(
            client,
            admin_headers,
            hakedis["id"],
            [{"contract_item_id": str(tk1), "quantity": miktar}],
        )
        assert yanit.status_code == 200, yanit.text
        return _damgalar(yanit.json())[str(tk1)]

    assert await _damga("12") == "diary"
    assert await _damga("9") == "manual"
    assert await _damga("12") == "diary"


# --- 6) Gövdeden damga sızdırılamaz ---


async def test_govdedeki_quantity_source_ETKISIZDIR(
    client: AsyncClient, seeded_db: AsyncSession, admin_headers, kurulum, gunluk_api
) -> None:
    """Mevcut bilinçli kural SÜRER: giriş şemasında alan yok, gönderilse de
    yok sayılır (miktar eşleşmiyorsa `manual`)."""
    site, _, (kalem_a, _), contract = kurulum
    await gunluk_api(
        admin_headers,
        site.id,
        date(2026, 7, 10),
        [{"boq_item_id": str(kalem_a.id), "quantity": "12"}],
    )
    tk1 = await _kalem_id(seeded_db, contract.id, "TK-1")

    hakedis = await _hakedis(client, admin_headers, contract.id, **DONEM)
    yanit = await _kaydet(
        client,
        admin_headers,
        hakedis["id"],
        [{"contract_item_id": str(tk1), "quantity": "5", "quantity_source": "diary"}],
    )
    assert yanit.status_code == 200, yanit.text
    assert _damgalar(yanit.json()) == {str(tk1): "manual"}


# --- 7) PATCH ile DÖNEM değişince damga BAYAT KALMAZ (T5 bulgusu) ---


async def _donem_yamasi(client: AsyncClient, headers: dict[str, str], payment_id, **govde):
    return await client.patch(
        f"/subcontractor-progress-payments/{payment_id}", json=govde, headers=headers
    )


async def test_PATCH_ile_donem_degisince_diary_damgasi_DUSER(
    client: AsyncClient, seeded_db: AsyncSession, admin_headers, kurulum, gunluk_api
) -> None:
    """İşveren ikizindeki bulgunun taşeron karşılığı: dönem taşınınca satır artık
    başka bir ayın günlüğüyle kıyaslanır, eski `diary` iddiası düşer."""
    site, _, (kalem_a, _), contract = kurulum
    await gunluk_api(
        admin_headers,
        site.id,
        date(2026, 6, 10),
        [{"boq_item_id": str(kalem_a.id), "quantity": "12"}],
    )
    tk1 = await _kalem_id(seeded_db, contract.id, "TK-1")

    hakedis = await _hakedis(client, admin_headers, contract.id, period_year=2026, period_month=6)
    yanit = await _kaydet(
        client, admin_headers, hakedis["id"], [{"contract_item_id": str(tk1), "quantity": "12"}]
    )
    assert yanit.status_code == 200, yanit.text
    assert _damgalar(yanit.json()) == {str(tk1): "diary"}

    yanit = await _donem_yamasi(client, admin_headers, hakedis["id"], period_month=7)
    assert yanit.status_code == 200, yanit.text
    assert _damgalar(yanit.json()) == {str(tk1): "manual"}


async def test_PATCH_ile_donem_gunluge_TASININCA_damga_basilir(
    client: AsyncClient, seeded_db: AsyncSession, admin_headers, kurulum, gunluk_api
) -> None:
    site, _, (kalem_a, _), contract = kurulum
    await gunluk_api(
        admin_headers,
        site.id,
        date(2026, 7, 10),
        [{"boq_item_id": str(kalem_a.id), "quantity": "12"}],
    )
    tk1 = await _kalem_id(seeded_db, contract.id, "TK-1")

    hakedis = await _hakedis(client, admin_headers, contract.id, period_year=2026, period_month=6)
    yanit = await _kaydet(
        client, admin_headers, hakedis["id"], [{"contract_item_id": str(tk1), "quantity": "12"}]
    )
    assert yanit.status_code == 200, yanit.text
    assert _damgalar(yanit.json()) == {str(tk1): "manual"}

    yanit = await _donem_yamasi(client, admin_headers, hakedis["id"], period_month=7)
    assert yanit.status_code == 200, yanit.text
    assert _damgalar(yanit.json()) == {str(tk1): "diary"}


async def test_DONEM_DISI_alan_yamasi_gunluk_sorgusu_KOSTURMAZ(
    client: AsyncClient, seeded_db: AsyncSession, admin_headers, kurulum, gunluk_api, monkeypatch
) -> None:
    """Yalnız `description` değişen PATCH damgaya dokunmaz ve günlük sorgusunu
    hiç koşturmaz."""
    site, _, (kalem_a, _), contract = kurulum
    await gunluk_api(
        admin_headers,
        site.id,
        date(2026, 7, 10),
        [{"boq_item_id": str(kalem_a.id), "quantity": "12"}],
    )
    tk1 = await _kalem_id(seeded_db, contract.id, "TK-1")

    hakedis = await _hakedis(client, admin_headers, contract.id, **DONEM)
    yanit = await _kaydet(
        client, admin_headers, hakedis["id"], [{"contract_item_id": str(tk1), "quantity": "12"}]
    )
    assert yanit.status_code == 200, yanit.text

    from app.modules.site_diary import bridge

    cagrilar: list[int] = []
    gercek = bridge.subcontractor_period_totals

    async def _sayan(*args, **kwargs):
        cagrilar.append(1)
        return await gercek(*args, **kwargs)

    monkeypatch.setattr(bridge, "subcontractor_period_totals", _sayan)

    yanit = await _donem_yamasi(client, admin_headers, hakedis["id"], description="yalnız açıklama")
    assert yanit.status_code == 200, yanit.text
    assert cagrilar == []
    assert _damgalar(yanit.json()) == {str(tk1): "diary"}
