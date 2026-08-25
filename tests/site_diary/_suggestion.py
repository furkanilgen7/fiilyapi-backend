"""Şantiye günlüğü ÖNERİ ucu testlerinin PAYLAŞILAN kurulumu.

`test_suggestion.py` 800 satır tavanını aşınca bölündü (`_journal.py` emsali):
yardımcılar KOPYALANMADI, buraya alındı — iki kopya olsaydı biri güncellenip
öveki kalır ve iki dosya AYNI ismi taşıyan FARKLI gövdelerle koşardı.

Hiçbir testin iddiası bu bölmeyle değişmedi.
"""

from datetime import date

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.progress_payments.models import ProgressPayment, ProgressPaymentLine
from app.modules.site_diary.models import SiteDiaryEntry, SiteDiaryLine
from app.modules.subcontractor_progress_payments.models import (
    SubcontractorProgressPayment,
    SubcontractorProgressPaymentLine,
)

DONEM = {"year": 2026, "month": 7}


# --- Yardımcılar ---


async def _gun(
    client: AsyncClient,
    headers: dict[str, str],
    site_id,
    tarih: date,
    satirlar: list[dict],
    *,
    gonder: bool = True,
) -> dict:
    """Bir günlük kaydı açar, miktarları yazar ve (istenirse) GÖNDERİR."""
    kayit = await client.post(
        f"/sites/{site_id}/diary", json={"entry_date": tarih.isoformat()}, headers=headers
    )
    assert kayit.status_code == 201, kayit.text
    entry_id = kayit.json()["id"]
    yanit = await client.put(f"/diary/{entry_id}/lines", json={"lines": satirlar}, headers=headers)
    assert yanit.status_code == 200, yanit.text
    if gonder:
        gonderim = await client.post(f"/diary/{entry_id}/submit", headers=headers)
        assert gonderim.status_code == 200, gonderim.text
        return gonderim.json()
    return yanit.json()


async def _isveren_onerisi(client: AsyncClient, headers: dict[str, str], project_id, **params):
    return await client.get(
        f"/projects/{project_id}/progress-payments/diary-suggestion",
        params=params,
        headers=headers,
    )


async def _taseron_onerisi(client: AsyncClient, headers: dict[str, str], contract_id, **params):
    return await client.get(
        f"/subcontractor-contracts/{contract_id}/progress-payments/diary-suggestion",
        params=params,
        headers=headers,
    )


async def _db_izi(session: AsyncSession) -> dict:
    """Salt-okunurluk KANITININ gövdesi: öneri ucunun dokunabileceği HER tablonun
    sayımı + günlüğün durum/miktar imzası. Tek bir `flush` bile bu sözlüğü
    değiştirir."""

    async def _say(model) -> int:
        return int((await session.execute(select(func.count()).select_from(model))).scalar_one())

    durumlar = sorted(
        (str(satir[0]), satir[1].value)
        for satir in (await session.execute(select(SiteDiaryEntry.id, SiteDiaryEntry.status))).all()
    )
    miktarlar = sorted(
        (str(satir[0]), str(satir[1]))
        for satir in (await session.execute(select(SiteDiaryLine.id, SiteDiaryLine.quantity))).all()
    )
    return {
        "gunluk_kayit": await _say(SiteDiaryEntry),
        "gunluk_satir": await _say(SiteDiaryLine),
        "isveren_hakedis": await _say(ProgressPayment),
        "isveren_satir": await _say(ProgressPaymentLine),
        "taseron_hakedis": await _say(SubcontractorProgressPayment),
        "taseron_satir": await _say(SubcontractorProgressPaymentLine),
        "durumlar": durumlar,
        "miktarlar": miktarlar,
    }


def _satir(govde: dict, contract_item_id, site_id=None) -> dict | None:
    return next(
        (
            s
            for s in govde["lines"]
            if s["contract_item_id"] == str(contract_item_id)
            and (site_id is None or s["site_id"] == str(site_id))
        ),
        None,
    )
