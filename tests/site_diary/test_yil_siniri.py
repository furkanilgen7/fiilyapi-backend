"""`year` sorgu parametresi SINIRLIDIR (kayıt 348).

`month` `Query(ge=1, le=12)` ile sınırlıyken `year` sınırsızdı. Değer
`period_conditions` → `_month_bounds` (repository.py:141-146) üzerinden doğrudan
`datetime.date()`e gider; `date(0, 1, 1)` ve `date(10000, 1, 1)` `ValueError`
fırlatır ve `app/core/exception_handlers.py`de bu istisna için handler YOKTUR —
yani kullanıcı girdisi 422 değil **500** üretiyordu.

Sınır emsallerden alındı, icat edilmedi: `treasury/router.py:289`
(`cash_flow.MIN_YEAR=2000` / `MAX_YEAR=2200`), `equipment/router.py:223,249,378`
(`ge=2000, le=2200`), `payroll/router.py:537`, `personnel/router.py:746`.
"""

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("yil", [0, 1999, 2201, 10000])
@pytest.mark.parametrize("yol", ["", "/summary"])
async def test_sinir_disi_yil_422(
    client: AsyncClient, admin_headers: dict[str, str], santiye, yil: int, yol: str
) -> None:
    site, _, _ = santiye
    yanit = await client.get(
        f"/sites/{site.id}/diary{yol}", params={"year": yil}, headers=admin_headers
    )
    assert yanit.status_code == 422, f"{yol or '/diary'} year={yil} -> {yanit.status_code}"


@pytest.mark.parametrize("yol", ["", "/summary"])
async def test_sinir_ici_yil_gecer(
    client: AsyncClient, admin_headers: dict[str, str], santiye, yol: str
) -> None:
    site, _, _ = santiye
    yanit = await client.get(
        f"/sites/{site.id}/diary{yol}", params={"year": 2026}, headers=admin_headers
    )
    assert yanit.status_code == 200, yanit.text
