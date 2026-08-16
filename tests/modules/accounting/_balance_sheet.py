"""MT-1 T4 — Bilanço uç testlerinin PAYLAŞILAN kurulumu.

Dosya 800 satır tavanını aşınca bölündü (`_journal.py` emsali): yardımcılar
KOPYALANMADI, buraya alındı. İki kopya olsaydı biri güncellenip öteki kalır ve
iki dosya AYNI ismi taşıyan FARKLI gövdelerle koşardı.

Hiçbir testin iddiası bu bölmeyle değişmedi.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy import event

from app.modules.accounting.models import ChartAccountType
from tests.conftest import test_engine

YOL = "/balance-sheet"
AS_OF = "2026-07-31"

_T = ChartAccountType


@contextmanager
def _sorgu_sayaci() -> Iterator[list[str]]:
    """Sürücüye giden HER ifadeyi toplar (`test_mu2_trial_balance.py` deseni)."""
    ifadeler: list[str] = []

    def kaydet(conn, cursor, statement, parameters, context, executemany) -> None:  # noqa: ANN001
        ifadeler.append(" ".join(statement.split()))

    event.listen(test_engine.sync_engine, "before_cursor_execute", kaydet)
    try:
        yield ifadeler
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", kaydet)


async def _bilanco(client: AsyncClient, headers: dict[str, str], as_of: str = AS_OF) -> dict:
    resp = await client.get(YOL, params={"as_of": as_of}, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _kalem(govde: dict, key: str) -> dict:
    for taraf in ("assets", "liabilities"):
        for bolum in govde[taraf]["sections"]:
            for satir in bolum["lines"]:
                if satir["key"] == key:
                    return satir
    raise AssertionError(f"{key} kalemi yanıtta yok")


def _tutar(govde: dict, key: str) -> Decimal:
    return Decimal(_kalem(govde, key)["amount"])


def _bolum(govde: dict, taraf: str, key: str) -> dict:
    for b in govde[taraf]["sections"]:
        if b["key"] == key:
            return b
    raise AssertionError(f"{key} bölümü yanıtta yok")
