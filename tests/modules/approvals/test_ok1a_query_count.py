"""OK-1A — 🔴 N+1 YOK: `GET /approvals`in sorgu sayısı SATIR SAYISINDAN BAĞIMSIZ.

İddia tahmine değil ÖLÇÜME dayanır: sürücüye giden HER ifade sayılır
(`tests/subcontractor_progress_payments/test_work_category.py:24-37` deseni).

Bir satır ile ON satır AYNI ifade sayısını üretmelidir. Eşitlik iddiası mutlak
bir tavandan daha güçlüdür: tavan, dilim büyüdükçe sessizce gevşetilebilir;
eşitlik ise satır başına ek sorgu eklendiği anda kırılır.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal

from app.modules.approvals import service
from app.modules.approvals.models import ApprovalDocumentType, ApprovalRole
from sqlalchemy import event

from tests.conftest import test_engine

_TASERON = ApprovalDocumentType.subcontractor_progress_payment


@contextmanager
def _sorgu_sayaci() -> Iterator[list[str]]:
    ifadeler: list[str] = []

    def kaydet(conn, cursor, statement, parameters, context, executemany) -> None:  # noqa: ANN001
        ifadeler.append(" ".join(statement.split()))

    event.listen(test_engine.sync_engine, "before_cursor_execute", kaydet)
    try:
        yield ifadeler
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", kaydet)


async def _zincirler(seeded_db, yaratanlar, adet: int) -> None:
    """Her zincirin YARATANI FARKLIDIR: `created_by` adını satır başına ayrı bir
    sorguyla çözen bir uygulama tam burada N+1'e düşerdi."""
    for sira in range(adet):
        await service.create_chain(
            seeded_db,
            document_type=_TASERON,
            document_id=uuid.uuid4(),
            amount=Decimal("100.00"),
            created_by_user_id=yaratanlar[sira % len(yaratanlar)].id,
        )


async def test_onay_kutusu_sorgu_sayisi_SATIR_SAYISINDAN_BAGIMSIZ(
    client, seeded_db, aktor_fabrikasi, giris
):
    yaratanlar = [
        await aktor_fabrikasi(f"n1-yaratan-{sira}@ok1a.co", full_name=f"Yaratan {sira}")
        for sira in range(5)
    ]
    await aktor_fabrikasi(
        "n1-sef@ok1a.co", role_key="site_chief", approval_roles=[ApprovalRole.site_chief]
    )
    basliklar = await giris("n1-sef@ok1a.co")

    await _zincirler(seeded_db, yaratanlar, 1)
    with _sorgu_sayaci() as tek_satir:
        yanit = await client.get("/approvals", headers=basliklar)
    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["total"] == 1

    await _zincirler(seeded_db, yaratanlar, 9)
    with _sorgu_sayaci() as on_satir:
        yanit = await client.get("/approvals", headers=basliklar)
    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["total"] == 10

    assert len(on_satir) == len(tek_satir), (
        f"satır sayısı 1→10 olunca sorgu sayısı {len(tek_satir)}→{len(on_satir)} oldu — N+1"
    )
