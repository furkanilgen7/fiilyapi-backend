"""MT-2 T7 — Gelir Tablosu uç testlerinin PAYLAŞILAN kurulumu.

`_balance_sheet.py` emsali: yardımcılar KOPYALANMAZ, buraya alınır. İki kopya
olsaydı biri güncellenip öteki kalır ve iki dosya AYNI ismi taşıyan FARKLI
gövdelerle koşardı.

🔴 **Hiçbir fixture mockup RAKAMLARINI kopyalamaz** (MT-K4). Mockup'ın gelir
tablosu aritmetiği bu kez TEMİZDİR (24.870.500+124.200 = 24.994.700 ·
12.480.000+5.840.000+3.120.000+42.000 = 21.482.000 · fark = 3.512.700) ama
testler yine de kendi küçük, elle doğrulanabilir tutarlarını kurar: mockup bir
YAPI kaynağıdır, veri kaynağı DEĞİL.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy import event

from app.modules.accounting.models import ChartAccountType
from tests.conftest import test_engine

YOL = "/income-statement"
YIL = 2026
AY = 7

_T = ChartAccountType


@contextmanager
def _sorgu_sayaci() -> Iterator[list[str]]:
    """Sürücüye giden HER ifadeyi toplar (`_balance_sheet.py` deseni)."""
    ifadeler: list[str] = []

    def kaydet(conn, cursor, statement, parameters, context, executemany) -> None:  # noqa: ANN001
        ifadeler.append(" ".join(statement.split()))

    event.listen(test_engine.sync_engine, "before_cursor_execute", kaydet)
    try:
        yield ifadeler
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", kaydet)


async def _tablo(
    client: AsyncClient, headers: dict[str, str], year: int = YIL, month: int = AY
) -> dict:
    resp = await client.get(YOL, params={"year": year, "month": month}, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _kalem(govde: dict, key: str) -> dict:
    for bolum in govde["sections"]:
        for satir in bolum["lines"]:
            if satir["key"] == key:
                return satir
    raise AssertionError(f"{key} kalemi yanıtta yok")


def _tutar(govde: dict, key: str) -> Decimal:
    return Decimal(_kalem(govde, key)["amount"])


def _bolum(govde: dict, key: str) -> dict:
    for b in govde["sections"]:
        if b["key"] == key:
            return b
    raise AssertionError(f"{key} bölümü yanıtta yok")


#: Altı kalemin ANAHTARLARI — izolasyon bekçisi "öteki beşi `0` kaldı" derken
#: bu listeyi gezer. Elle yazılmış bir liste bir kalemi unuttuğunda bekçi
#: sessizce zayıflardı; bu yüzden `statement_map`ten TÜRETİLİR.
def _tum_kalemler() -> list[str]:
    from app.modules.accounting import statement_map

    return [k.key for b in statement_map.INCOME_STATEMENT_SECTIONS for k in b.lines]
