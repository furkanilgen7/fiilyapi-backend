"""EV-BORC-2 — günlük detayında puantajdan TÜREYEN ekip (`own_crew_from_timesheet`).

Günlük işçi satırı ile puantaj personeli arasında kimlik bağı YOKTUR (ikisi de serbest metin
`trade`); frontend'in "meslek + kaynak, çoğul eki atarak" eşlemesi yerine backend puantajı
(meslek, kaynak) başına GRUPLAR: kişi sayısı + saat. Kaynak EV dağıtım ızgarasıyla AYNI sorgu
(`timesheet.repository.day_person_hours`). Çekirdek günlük EV import ETMEZ.

Kurallar: yalnız o günün, o şantiyenin SAATLİ hücreleri · kodlu (izin) hücre girmez · meslek
boş/boşluk → "Belirtilmemiş" (kişi kaybolmaz) · sıra meslek, kaynak.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.personnel.models import Personnel
from app.modules.site_diary.models import WorkerSource
from app.modules.site_diary.read import UNSPECIFIED_TRADE
from app.modules.timesheet.models import TimesheetCode, TimesheetEntry
from tests.site_diary.conftest import VARSAYILAN_TARIH

pytestmark = pytest.mark.asyncio


async def _kisi(session: AsyncSession, name: str, trade: str | None, source: WorkerSource):
    person = Personnel(full_name=name, trade=trade, source=source, is_active=True, is_draft=False)
    session.add(person)
    await session.flush()
    return person


def _hucre(person, site, day, *, hours: str | None, actor, code=None) -> TimesheetEntry:  # noqa: ANN001
    return TimesheetEntry(
        personnel_id=person.id,
        site_id=site.id,
        project_id=site.project_id,
        work_date=day,
        hours=None if hours is None else Decimal(hours),
        code=code,
        created_by=actor.id,
    )


async def _detay(client: AsyncClient, headers, site) -> dict:  # noqa: ANN001
    created = await client.post(
        f"/sites/{site.id}/diary",
        json={"entry_date": VARSAYILAN_TARIH.isoformat()},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    resp = await client.get(f"/diary/{created.json()['id']}", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_own_crew_groups_timesheet_by_trade_and_source(
    client: AsyncClient,
    admin_headers,
    admin_kullanicisi,
    santiye,
    santiye_fabrikasi,
    seeded_db: AsyncSession,
) -> None:
    site, _, _ = santiye
    other_site = (await santiye_fabrikasi(code="EV2-B"))[0]
    day = VARSAYILAN_TARIH
    ali = await _kisi(seeded_db, "Ali", "Kalıpçı", WorkerSource.company)
    veli = await _kisi(seeded_db, "Veli", "Kalıpçı", WorkerSource.company)
    can = await _kisi(seeded_db, "Can", None, WorkerSource.company)
    ece = await _kisi(seeded_db, "Ece", "  ", WorkerSource.company)
    hasan = await _kisi(seeded_db, "Hasan", "Duvarcı", WorkerSource.subcontractor)
    izinli = await _kisi(seeded_db, "İzinli", "Kalıpçı", WorkerSource.company)
    dun = await _kisi(seeded_db, "Dünkü", "Kalıpçı", WorkerSource.company)
    baska = await _kisi(seeded_db, "Başka", "Kalıpçı", WorkerSource.company)
    a = admin_kullanicisi
    seeded_db.add_all(
        [
            _hucre(ali, site, day, hours="9", actor=a),
            _hucre(veli, site, day, hours="8", actor=a),
            _hucre(can, site, day, hours="7", actor=a),
            _hucre(ece, site, day, hours="6", actor=a),
            _hucre(hasan, site, day, hours="8", actor=a),
            _hucre(izinli, site, day, hours=None, actor=a, code=TimesheetCode.leave),
            _hucre(dun, site, day - timedelta(days=1), hours="9", actor=a),
            _hucre(baska, other_site, day, hours="9", actor=a),
        ]
    )
    await seeded_db.flush()

    crew = (await _detay(client, admin_headers, site))["own_crew_from_timesheet"]

    got = [(c["trade"], c["source"], c["headcount"], Decimal(c["hours"])) for c in crew]
    assert got == [
        (UNSPECIFIED_TRADE, "company", 2, Decimal(13)),  # boş + boşluk meslek, kaybolmaz
        ("Duvarcı", "subcontractor", 1, Decimal(8)),
        ("Kalıpçı", "company", 2, Decimal(17)),  # izinli / dünkü / başka şantiye GİRMEZ
    ]


async def test_own_crew_empty_without_timesheet(
    client: AsyncClient, admin_headers, santiye
) -> None:
    site, _, _ = santiye
    assert (await _detay(client, admin_headers, site))["own_crew_from_timesheet"] == []
