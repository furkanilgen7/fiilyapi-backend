"""EV yanitlarinda Decimal'in TEK serilestirme noktasi — sabit gosterim, ASLA ustel (PLN-B3.1).

Pydantic Decimal'i JSON'a `str(d)` ile yazar; motorun kesin bolmeleri olcek tasiyabildigi
icin `0/25.0000000` → `Decimal('0E+7')` → `"0E+7"`. Bu hem kendi OpenAPI desenimizi
(`^(?!^[-+.]*$)[+-]?0*\\d*\\.?\\d*$` — `E` YOK) hem frontend `DECIMAL_PATTERN`ini bozar
(sifir oran/ilerleme ekranda "—" gorunurdu). Olculdu: B1 butce `share`, onizleme
`required_people` ("0E+2"), B3 rapor/panel `progress_pct_*`.

`EvDecimal` = Decimal + JSON serilestirici `format(d, "f")`: deger ve olcek aynen, yalniz
ustel yazim sabit gosterime acilir — `"0E+7"` → `"0"`, `"1E-7"` → `"0.0000001"`; sondaki
sifirlar korunur (`"17.00"` kalir). Serilestirici CEKIRDEK semaya eklenir: dogrulama,
kisitlar (`Field(max_digits=…)`) ve OpenAPI semasi (kisitli desen dahil) DEGISMEZ; python
modunda (`model_dump()`) deger Decimal kalir. Motor dokunulmaz.
Bekci: `tests/earned_value_budget/test_decimal_out.py`.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any

from pydantic import GetCoreSchemaHandler
from pydantic_core import CoreSchema, core_schema


def plain_decimal(value: Decimal) -> str:
    """Sabit gosterim: `format(d, "f")` ustel yazmaz; olcek (sondaki sifirlar) korunur."""
    return format(value, "f")


class PlainDecimalJson:
    """Isaretleyici: Decimal cekirdek semasina JSON serilestiricisini ekler (sema aynen)."""

    def __get_pydantic_core_schema__(
        self, source: Any, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        schema = handler(source)
        schema["serialization"] = core_schema.plain_serializer_function_ser_schema(
            plain_decimal, when_used="json-unless-none"
        )
        return schema


EvDecimal = Annotated[Decimal, PlainDecimalJson()]
