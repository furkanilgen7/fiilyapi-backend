"""TB4 T1b (S4) — `quantity_source` İKİ hakediş ailesinin satır YANITINDA görünür.

T1'de damga sunucuda doğru basılıyordu ama işveren satır şemasında alan YOKTU:
damga DB'de kalıyor, hiçbir istemci "Günlük kayıttan" rozetini göremiyordu. S4
kararı (kullanıcı onayı 2026-08-09): alan işveren `ProgressPaymentLineDetail`
yanıtına da EKLENİR; iki ailenin satır şeması bu alanda SİMETRİKTİR.

Doğrulama DB'den değil, DETAY UCUNUN HTTP JSON'undan okunur — kanıtlanmak
istenen tam olarak alanın tele çıkmasıdır.

GİRİŞ şeması kapsam DIŞIDIR: damganın istekten alınmaması kuralı aynen sürer
(`test_employer_diary_stamp.py::test_govdedeki_quantity_source_ETKISIZDIR`).
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


def _kaynaklar(govde: dict) -> dict[str, str]:
    """Yalnız miktarı olan satırlar: taşeron hakedişi açılışta TÜM kalemleri
    0 ile kurar, sıfır satırlar rozet taşımaz."""
    return {
        satir["contract_item_id"]: satir["quantity_source"]
        for satir in govde["lines"]
        if Decimal(satir["quantity"]) != 0
    }


async def test_ISVEREN_detay_yaniti_satir_basina_quantity_source_tasir(
    client: AsyncClient,
    admin_headers,
    santiye,
    sozlesme_kalemi_fabrikasi,
    gunluk_api,
) -> None:
    """Tek gövdede iki satır: biri günlükle birebir (`diary`), diğerinin günlüğü
    yok (`manual`) — rozet SATIR BAZINDA tele çıkar."""
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

    olustur = await client.post(
        f"/projects/{project.id}/progress-payments", json=DONEM, headers=admin_headers
    )
    assert olustur.status_code == 201, olustur.text
    payment_id = olustur.json()["id"]

    kaydet = await client.put(
        f"/progress-payments/{payment_id}/lines",
        json={
            "lines": [
                {"contract_item_id": str(sozlesme_a.id), "site_id": str(site.id), "quantity": "12"},
                {"contract_item_id": str(sozlesme_b.id), "site_id": str(site.id), "quantity": "3"},
            ]
        },
        headers=admin_headers,
    )
    assert kaydet.status_code == 200, kaydet.text

    detay = await client.get(f"/progress-payments/{payment_id}", headers=admin_headers)
    assert detay.status_code == 200, detay.text
    assert _kaynaklar(detay.json()) == {
        str(sozlesme_a.id): "diary",
        str(sozlesme_b.id): "manual",
    }


async def test_TASERON_detay_yaniti_satir_basina_quantity_source_tasir(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers,
    santiye,
    sozlesme_kalemi_fabrikasi,
    taseron_sozlesmesi_fabrikasi,
    gunluk_api,
) -> None:
    """İşveren ikizinin AYNISI: simetri iddiası ancak iki aile de aynı uçtan
    okunduğunda kanıtlanır."""
    site, project, items = santiye
    kalem_a, kalem_b = sorted(items, key=lambda i: i.code)
    sozlesme_a = await sozlesme_kalemi_fabrikasi(kalem_a, project)
    sozlesme_b = await sozlesme_kalemi_fabrikasi(kalem_b, project)
    contract = await taseron_sozlesmesi_fabrikasi(
        project, site=site, kalemler=[("TK-1", sozlesme_a), ("TK-2", sozlesme_b)]
    )
    kalem_idleri = {
        kod: (
            await seeded_db.execute(
                select(SubcontractorContractItem.id).where(
                    SubcontractorContractItem.contract_id == contract.id,
                    SubcontractorContractItem.code == kod,
                )
            )
        ).scalar_one()
        for kod in ("TK-1", "TK-2")
    }
    await gunluk_api(
        admin_headers,
        site.id,
        date(2026, 7, 10),
        [{"boq_item_id": str(kalem_a.id), "quantity": "12"}],
    )

    olustur = await client.post(
        f"/subcontractor-contracts/{contract.id}/progress-payments",
        json=DONEM,
        headers=admin_headers,
    )
    assert olustur.status_code == 201, olustur.text
    payment_id = olustur.json()["id"]

    kaydet = await client.put(
        f"/subcontractor-progress-payments/{payment_id}/lines",
        json={
            "lines": [
                {"contract_item_id": str(kalem_idleri["TK-1"]), "quantity": "12"},
                {"contract_item_id": str(kalem_idleri["TK-2"]), "quantity": "3"},
            ]
        },
        headers=admin_headers,
    )
    assert kaydet.status_code == 200, kaydet.text

    detay = await client.get(
        f"/subcontractor-progress-payments/{payment_id}", headers=admin_headers
    )
    assert detay.status_code == 200, detay.text
    assert _kaynaklar(detay.json()) == {
        str(kalem_idleri["TK-1"]): "diary",
        str(kalem_idleri["TK-2"]): "manual",
    }
