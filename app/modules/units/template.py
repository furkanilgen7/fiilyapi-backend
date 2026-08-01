"""Unite ice aktarma SABLONU (spec §6.7, plan T14).

Saf sunum katmani (`boq/export.py` emsali): `Request`/`Response` bilmez, DB'ye
dokunmaz, proje verisi ALMAZ — urettigi dosya tek satirdan ibarettir.

BASLIKLAR ELLE YAZILMAZ. `importer.COLUMNS` TEK OTORITEDIR ve sablon ondan
TURETILIR: ikinci bir liste, `COLUMNS` degistigi gun sessizce eskir ve
kullanicinin indirdigi sablon cozumleyiciden "baslik eksik" 422'si alirdi.
Bu bagi `test_units_import_template.py`'nin dongu testi uctan uca kilitler.

VERI SATIRI YOKTUR (spec §6.7): ornek satir koymak, kullanicinin onu silmeyi
unutup hatali satir olarak yuklemesine yol acar.
"""

from io import BytesIO

from openpyxl import Workbook

from app.modules.units.importer import COLUMNS

SHEET_TITLE = "Üniteler"

# Zorunlu sutunlar biraz daha genis: kullanici baslik satirinda hangi alanlari
# doldurmasi gerektigini once GORUR (EI 161'in yildizinin Excel'deki karsiligi).
_REQUIRED_WIDTH = 18
_OPTIONAL_WIDTH = 14


def template_headers() -> tuple[str, ...]:
    """Sablonun ilk satiri — `importer.COLUMNS` sirasi ve metinleriyle BIREBIR."""
    return tuple(column.label for column in COLUMNS)


def build_template_workbook() -> BytesIO:
    """12 baslikli, veri satirsiz `.xlsx` sablonu uretir."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = SHEET_TITLE

    for index, column in enumerate(COLUMNS, start=1):
        cell = sheet.cell(row=1, column=index)
        cell.value = column.label
        width = _REQUIRED_WIDTH if column.required else _OPTIONAL_WIDTH
        sheet.column_dimensions[cell.column_letter].width = width

    sheet.freeze_panes = "A2"

    buffer = BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer
