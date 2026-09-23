"""`year` sorgu parametresi SINIRLIDIR (kayıt 348).

`month` `Query(ge=1, le=12)` ile sınırlıyken `year` sınırsızdı. Değer
`period_conditions` → `_month_bounds` (repository.py:141-146) üzerinden doğrudan
`datetime.date()`e gider; `date(0, 1, 1)` ve `date(10000, 1, 1)` `ValueError`
fırlatır ve `app/core/exception_handlers.py`de bu istisna için handler YOKTUR —
yani kullanıcı girdisi 422 değil **500** üretiyordu.

Sınır emsallerden alındı, icat edilmedi: `treasury/router.py:289`
(`cash_flow.MIN_YEAR=2000` / `MAX_YEAR=2200`), `equipment/router.py:223,249,378`
(`ge=2000, le=2200`), `payroll/router.py:537`, `personnel/router.py:746`.

Envanter kaydı #38 (2026-09-20 yeniden triyaj): `130b8d8` bu sınırı yalnız
`router.py`deki iki uca (liste + özet) uyguladı; `router_suggestion.py:73,95`
(işveren/taşeron "günlükten doldur" önerisi) AYNI zincire ("submitted_period_
conditions" -> "period_conditions" -> "_month_bounds") giriyor ama sınırsız
kaldı. Aşağıdaki `test_oneri_sinir_disi_yil_422` / `..._sinir_ici_yil_gecer`
bu ikinci yarıyı kapatır.
"""

import pytest
from httpx import AsyncClient

from ._suggestion import _isveren_onerisi, _taseron_onerisi

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


# --- Kayıt #38: öneri uçları (router_suggestion.py) aynı sınırı taşımalı ---


@pytest.mark.parametrize("yil", [0, 1999, 2201, 10000])
async def test_oneri_isveren_sinir_disi_yil_422(
    client: AsyncClient, admin_headers: dict[str, str], santiye, yil: int
) -> None:
    _, project, _ = santiye
    yanit = await _isveren_onerisi(client, admin_headers, project.id, year=yil)
    assert yanit.status_code == 422, f"isveren year={yil} -> {yanit.status_code}: {yanit.text}"


async def test_oneri_isveren_sinir_ici_yil_gecer(
    client: AsyncClient, admin_headers: dict[str, str], santiye
) -> None:
    _, project, _ = santiye
    yanit = await _isveren_onerisi(client, admin_headers, project.id, year=2026)
    assert yanit.status_code == 200, yanit.text


@pytest.mark.parametrize("yil", [0, 1999, 2201, 10000])
async def test_oneri_taseron_sinir_disi_yil_422(
    client: AsyncClient,
    admin_headers: dict[str, str],
    santiye,
    taseron_sozlesmesi_fabrikasi,
    yil: int,
) -> None:
    _, project, _ = santiye
    tas_sozlesme = await taseron_sozlesmesi_fabrikasi(project)
    yanit = await _taseron_onerisi(client, admin_headers, tas_sozlesme.id, year=yil)
    assert yanit.status_code == 422, f"taseron year={yil} -> {yanit.status_code}: {yanit.text}"


async def test_oneri_taseron_sinir_ici_yil_gecer(
    client: AsyncClient,
    admin_headers: dict[str, str],
    santiye,
    taseron_sozlesmesi_fabrikasi,
) -> None:
    _, project, _ = santiye
    tas_sozlesme = await taseron_sozlesmesi_fabrikasi(project)
    yanit = await _taseron_onerisi(client, admin_headers, tas_sozlesme.id, year=2026)
    assert yanit.status_code == 200, yanit.text
