"""TB3-T1 — taşeron hakediş liste/detay şemalarında `work_category` (spec TB3-A).

Alan hakediş tablosunda SAKLANMAZ: zaten kurulu olan sözleşme JOIN'inden okunur
(`SubcontractorContract.work_category`). Kanıtı buradaki sorgu sayacıdır — alan
eklendikten sonra liste ucunun ifade sayısı hakediş sayısıyla BÜYÜMEZ.

Ekrandaki gerekçe: F-TH şantiye sekmesi kategoriyi göstermek için ikinci bir
sözleşme isteği atıyordu; alan liste satırına girince o istek kalkar.
"""

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import test_engine

pytestmark = pytest.mark.asyncio


@contextmanager
def _sorgu_sayaci() -> Iterator[list[str]]:
    """Sürücüye giden HER ifadeyi toplar (`progress_payments/test_summary.py`
    `_sorgu_sayaci` deseninin aynısı) — N+1 iddiası tahmine değil ÖLÇÜME dayanır."""
    ifadeler: list[str] = []

    def kaydet(conn, cursor, statement, parameters, context, executemany) -> None:  # noqa: ANN001
        ifadeler.append(" ".join(statement.split()))

    event.listen(test_engine.sync_engine, "before_cursor_execute", kaydet)
    try:
        yield ifadeler
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", kaydet)


async def _olustur(client: AsyncClient, headers: dict[str, str], contract_id):  # noqa: ANN001
    """Detay testleri hakedişi UÇTAN açar (`test_crud.py` deseni): doğrudan DB'ye
    yazılan hakedişin `lines` bağıntısı detay yolunda tembel yüklenemez."""
    return await client.post(
        f"/subcontractor-contracts/{contract_id}/progress-payments", json={}, headers=headers
    )


def _sozlesme_sorgulari(ifadeler: list[str]) -> list[str]:
    """Yalnız taşeron sözleşmesi tablosuna giden ifadeler — oturum/izin sorguları
    sayıma girmez."""
    return [ifade for ifade in ifadeler if "subcontractor_contracts" in ifade.lower()]


async def test_liste_satiri_sozlesmenin_work_category_alanini_tasir(
    client: AsyncClient,
    admin_headers: dict[str, str],
    seeded_db: AsyncSession,
    taseron_sozlesmesi,
    admin_kullanicisi,
    hakedis_fabrikasi,
) -> None:
    contract, _, _ = taseron_sozlesmesi
    contract.work_category = "Betonarme"
    await seeded_db.flush()
    await hakedis_fabrikasi(contract, admin_kullanicisi)

    yanit = await client.get("/subcontractor-progress-payments", headers=admin_headers)

    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["items"][0]["work_category"] == "Betonarme"


async def test_detay_sozlesmenin_work_category_alanini_tasir(
    client: AsyncClient,
    admin_headers: dict[str, str],
    seeded_db: AsyncSession,
    taseron_sozlesmesi,
) -> None:
    contract, _, _ = taseron_sozlesmesi
    contract.work_category = "Elektrik"
    await seeded_db.flush()
    olusan = (await _olustur(client, admin_headers, contract.id)).json()

    yanit = await client.get(
        f"/subcontractor-progress-payments/{olusan['id']}", headers=admin_headers
    )

    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["work_category"] == "Elektrik"


async def test_kategorisiz_sozlesmede_alan_null_doner(
    client: AsyncClient,
    admin_headers: dict[str, str],
    taseron_sozlesmesi,
) -> None:
    """Sözleşmede kategori girilmemişse alan NULL'dur — taslak sözleşmede
    `work_category` boş bırakılabilir (`guards.validate_subcontract` yalnız
    taslak DIŞI kayıtta zorunlu tutar), yanıt bu yüzden KIRILMAZ."""
    contract, _, _ = taseron_sozlesmesi
    assert contract.work_category is None
    olusan = (await _olustur(client, admin_headers, contract.id)).json()

    liste = await client.get("/subcontractor-progress-payments", headers=admin_headers)
    detay = await client.get(
        f"/subcontractor-progress-payments/{olusan['id']}", headers=admin_headers
    )

    assert liste.json()["items"][0]["work_category"] is None
    assert detay.json()["work_category"] is None


async def test_work_category_ek_sozlesme_sorgusu_acmaz(
    client: AsyncClient,
    admin_headers: dict[str, str],
    seeded_db: AsyncSession,
    taseron_sozlesmesi,
    admin_kullanicisi,
    hakedis_fabrikasi,
) -> None:
    """N+1 kapısı: kategori hakediş BAŞINA okunsaydı sözleşme tablosuna giden
    ifade sayısı hakediş sayısıyla büyürdü. Ölçüm bunun olmadığını gösterir."""
    contract, _, _ = taseron_sozlesmesi
    contract.work_category = "Mekanik"
    await seeded_db.flush()
    await hakedis_fabrikasi(contract, admin_kullanicisi, sequence_no=1)

    with _sorgu_sayaci() as tek_hakedis:
        yanit = await client.get("/subcontractor-progress-payments", headers=admin_headers)
    assert yanit.json()["total"] == 1

    await hakedis_fabrikasi(contract, admin_kullanicisi, sequence_no=2)
    await hakedis_fabrikasi(contract, admin_kullanicisi, sequence_no=3)

    with _sorgu_sayaci() as uc_hakedis:
        yanit = await client.get("/subcontractor-progress-payments", headers=admin_headers)
    assert yanit.json()["total"] == 3
    assert yanit.json()["items"][0]["work_category"] == "Mekanik"

    assert len(_sozlesme_sorgulari(uc_hakedis)) == len(_sozlesme_sorgulari(tek_hakedis))
