"""B9 Excel içe aktarma testlerinin PAYLAŞILAN kurulumu.

`test_units_import.py` 800 satır tavanını aşınca bölündü (`_journal.py` emsali):
yardımcılar KOPYALANMADI, buraya alındı — iki kopya olsaydı biri güncellenip
öveki kalır ve iki dosya AYNI ismi taşıyan FARKLI gövdelerle koşardı.

Hiçbir testin iddiası bu bölmeyle değişmedi.
"""

import io
import uuid

from openpyxl import Workbook
from sqlalchemy import func, select

from app.modules.units.importer import (
    parse_units_file,
)
from app.modules.units.models import Block, Unit
from tests.modules.units._units_api import (
    _auth,
)

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# P3.1 T11 (spec §6.4, EI 85): 9 → 12 sutun, KANONIK sira. Iki baslik yeniden
# adlandirildi (`Tip` → `Oda Tipi`, `Pay` → `Sahiplik`); eskileri ESANLAMLI
# kabul edilir (`_LEGACY_HEADERS`, geriye donuk uyum testi).
_HEADERS = [
    "Blok",
    "Kat",
    "Ünite No",
    "Tür",
    "Oda Tipi",
    "Brüt m²",
    "Net m²",
    "Cephe",
    "Liste Fiyatı",
    "Rayiç Değer",
    "Maliyet",
    "Sahiplik",
]

_LEGACY_HEADERS = ["Blok", "Ünite No", "Tür", "Tip", "Brüt m²", "Net m²", "Liste Fiyatı", "Pay"]

# `Oda Tipi` ve `Brüt m²` P3.1'de ZORUNLU oldu (EI 161, spec §6.5). Bu yuzden
# ortak satir uretecinin varsayilanlari BOS BIRAKILAMAZ: P3'te bos gelen iki
# sutun artik her satiri hataya dusururdu. Testlerin IDDIALARI degismedi,
# yalnizca gecerli bir satirin tanimi genisledi.
_ROW_DEFAULTS: dict = {
    "Kat": None,
    "Oda Tipi": "3+1",
    "Brüt m²": 120,
    "Net m²": None,
    "Cephe": None,
    "Liste Fiyatı": None,
    "Rayiç Değer": None,
    "Maliyet": None,
    "Sahiplik": None,
}


def _xlsx(rows: list[list], headers: list | None = None) -> bytes:
    """Bellekte bir `.xlsx` uretir — testler de diske dosya BIRAKMAZ."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(_HEADERS if headers is None else headers)
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _row(block: str = "A Blok", unit_no: str = "1", kind: str = "Daire", **cells) -> list:
    values: dict = {"Blok": block, "Ünite No": unit_no, "Tür": kind, **_ROW_DEFAULTS}
    values.update(cells)
    return [values[label] for label in _HEADERS]


def _legacy_row(unit_no: str = "1", **cells) -> list:
    """Eski 8 sutunlu dosya (P3 sablonu) — `Tip`/`Pay` esanlamli kabul edilir."""
    values: dict = {
        "Blok": "A Blok",
        "Ünite No": unit_no,
        "Tür": "Daire",
        "Tip": "3+1",
        "Brüt m²": 120,
        "Net m²": None,
        "Liste Fiyatı": None,
        "Pay": None,
    }
    values.update(cells)
    return [values[label] for label in _LEGACY_HEADERS]


def _parse(content: bytes):
    """`parse_units_file` ciktisini eski (satirlar, hatalar, uyarilar) uclusune
    indirger — cozumleme testlerinin ilgilenmedigi `ParsedRow` sarmalayicisini
    her testte acmamak icin."""
    parsed = parse_units_file(content)
    return (
        [row.data for row in parsed if row.data is not None],
        [error for row in parsed for error in row.errors],
        [warning for row in parsed for warning in row.warnings],
    )


async def _post_import(
    client, project, content: bytes, token: str, filename="uniteler.xlsx", **form
):
    return await client.post(
        f"/projects/{project.id}/units/import",
        files={"file": (filename, content, _XLSX_MIME)},
        data={key: str(value) for key, value in form.items()},
        headers=_auth(token),
    )


async def _count_units(session, project_id: uuid.UUID) -> int:
    result = await session.execute(
        select(func.count()).select_from(Unit).where(Unit.project_id == project_id)
    )
    return int(result.scalar_one())


async def _count_blocks(session, project_id: uuid.UUID) -> int:
    result = await session.execute(
        select(func.count()).select_from(Block).where(Block.project_id == project_id)
    )
    return int(result.scalar_one())
