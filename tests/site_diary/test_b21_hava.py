"""PLN-B2.1 (B2-1, B2-2) — hava genişlemesi: 10 durum + min/max sıcaklık + rüzgâr.

CLEAN-B1 Faz 1 (KIRICI, F2 canlıda + frontend geri düşüşü kalkınca aynı gün merge):
* `temperature_c` API'den KALKTI — yanıtta yok; istekte (POST ve PATCH) AÇIK 422
  (`schemas.TEMPERATURE_C_REMOVED`; Create'te sessizce yutulup sıcaklık kaybolmasın).
* Kolon Faz 2'ye kadar KALIR ve servis onu `temp_max_c`ye eşitler (eski konteyner okur).
"""

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.modules.site_diary import guards
from app.modules.site_diary.models import SiteDiaryEntry, Weather
from app.modules.site_diary.schemas import TEMPERATURE_C_REMOVED
from tests.site_diary.conftest import VARSAYILAN_TARIH

pytestmark = pytest.mark.asyncio

_YENI_HAVA = {"heavy_rain", "drizzle", "windy", "dusty", "foggy"}
_ESKI_HAVA = {"sunny", "partly_cloudy", "cloudy", "rainy", "snowy"}


async def _olustur(client: AsyncClient, headers, site_id, **govde):
    return await client.post(
        f"/sites/{site_id}/diary",
        json={"entry_date": VARSAYILAN_TARIH.isoformat(), **govde},
        headers=headers,
    )


async def _kolon(session: AsyncSession, entry_id) -> SiteDiaryEntry:
    return (
        await session.execute(
            select(SiteDiaryEntry)
            .where(SiteDiaryEntry.id == entry_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


async def test_hava_enumu_eski_bes_aynen_arti_yeni_bes() -> None:
    assert {w.value for w in Weather} == _ESKI_HAVA | _YENI_HAVA


@pytest.mark.parametrize("hava", sorted(_YENI_HAVA))
async def test_yeni_hava_degerleri_yazilir_ve_okunur(
    client: AsyncClient, admin_headers, santiye, hava: str
) -> None:
    site, _, _ = santiye
    yanit = await _olustur(client, admin_headers, site.id, weather=hava)
    assert yanit.status_code == 201, yanit.text
    assert yanit.json()["weather"] == hava


async def test_min_max_ruzgar_yazilir_ve_eski_kolon_max_kopyasi_kalir(
    client: AsyncClient, admin_headers, santiye, seeded_db: AsyncSession
) -> None:
    site, _, _ = santiye

    yanit = await _olustur(
        client, admin_headers, site.id, temp_min_c="17", temp_max_c="28.5", wind_ms="4.2"
    )

    assert yanit.status_code == 201, yanit.text
    govde = yanit.json()
    assert Decimal(govde["temp_min_c"]) == Decimal("17")
    assert Decimal(govde["temp_max_c"]) == Decimal("28.5")
    assert Decimal(govde["wind_ms"]) == Decimal("4.2")
    assert "temperature_c" not in govde  # CLEAN-B1 Faz 1: yanıtta YOK
    # Geri uyum kolonu Faz 2'ye kadar temp_max_c'ye esitlenir (eski konteyner okur).
    assert (await _kolon(seeded_db, govde["id"])).temperature_c == Decimal("28.5")


async def test_POST_temperature_c_acik_422_ve_kayit_acilmaz(
    client: AsyncClient, admin_headers, santiye, seeded_db: AsyncSession
) -> None:
    """Create'te `extra` serbesttir: açık ret olmasa alan SESSİZCE yutulur, sıcaklık kaybolurdu."""
    site, _, _ = santiye

    yanit = await _olustur(client, admin_headers, site.id, temperature_c="21.5")

    assert yanit.status_code == 422, yanit.text
    assert TEMPERATURE_C_REMOVED in yanit.text
    kayitlar = (await seeded_db.execute(select(SiteDiaryEntry))).scalars().all()
    assert [k for k in kayitlar if k.site_id == site.id] == []


@pytest.mark.parametrize("ek", [{}, {"temp_min_c": "10", "temp_max_c": "20"}])
async def test_POST_temperature_c_yeni_alanlarla_birlikte_de_422(
    client: AsyncClient, admin_headers, santiye, ek: dict
) -> None:
    site, _, _ = santiye
    yanit = await _olustur(client, admin_headers, site.id, temperature_c="5", **ek)
    assert yanit.status_code == 422, yanit.text
    assert TEMPERATURE_C_REMOVED in yanit.text


async def test_hic_sicaklik_yoksa_hepsi_bos(client: AsyncClient, admin_headers, santiye) -> None:
    site, _, _ = santiye
    govde = (await _olustur(client, admin_headers, site.id)).json()
    assert (govde["temp_min_c"], govde["temp_max_c"]) == (None,) * 2
    assert "temperature_c" not in govde
    assert govde["wind_ms"] is None


async def test_PATCH_temperature_c_acik_422_ve_deger_degismez(
    client: AsyncClient, admin_headers, santiye
) -> None:
    site, _, _ = santiye
    kayit = (await _olustur(client, admin_headers, site.id, temp_min_c="1", temp_max_c="2")).json()

    yanit = await client.patch(
        f"/diary/{kayit['id']}", json={"temperature_c": "14"}, headers=admin_headers
    )

    assert yanit.status_code == 422, yanit.text
    assert TEMPERATURE_C_REMOVED in yanit.text
    detay = (await client.get(f"/diary/{kayit['id']}", headers=admin_headers)).json()
    assert (detay["temp_min_c"], detay["temp_max_c"]) == ("1.0", "2.0")


async def test_PATCH_tek_alan_digerini_korur_ve_BIRLESIK_min_max_denetlenir(
    client: AsyncClient, admin_headers, santiye
) -> None:
    site, _, _ = santiye
    kayit = (
        await _olustur(client, admin_headers, site.id, temp_min_c="10", temp_max_c="20")
    ).json()

    tamam = await client.patch(
        f"/diary/{kayit['id']}", json={"temp_max_c": "25"}, headers=admin_headers
    )
    ters = await client.patch(
        f"/diary/{kayit['id']}", json={"temp_min_c": "30"}, headers=admin_headers
    )

    assert tamam.status_code == 200, tamam.text
    assert (Decimal(tamam.json()["temp_min_c"]), Decimal(tamam.json()["temp_max_c"])) == (
        Decimal("10"),
        Decimal("25"),
    )
    assert ters.status_code == 422, ters.text
    assert ters.json()["detail"] == guards.TEMP_ORDER


async def test_PATCH_sicakliga_dokunmayan_istek_sicakligi_korur(
    client: AsyncClient, admin_headers, santiye
) -> None:
    site, _, _ = santiye
    kayit = (
        await _olustur(client, admin_headers, site.id, temp_min_c="12", temp_max_c="12")
    ).json()

    yanit = await client.patch(
        f"/diary/{kayit['id']}", json={"work_done": "iş"}, headers=admin_headers
    )

    govde = yanit.json()
    assert (govde["temp_min_c"], govde["temp_max_c"]) == ("12.0",) * 2


@pytest.mark.parametrize(
    "govde",
    [
        {"temp_min_c": "20", "temp_max_c": "10"},
        {"temp_min_c": "-61"},
        {"temp_max_c": "60.1"},
        {"wind_ms": "-0.1"},
        {"wind_ms": "80.1"},
        {"temp_max_c": "12.25"},
        {"weather": "hurricane"},
    ],
)
async def test_gecersiz_hava_govdesi_422(
    client: AsyncClient, admin_headers, santiye, govde: dict
) -> None:
    site, _, _ = santiye
    yanit = await _olustur(client, admin_headers, site.id, **govde)
    assert yanit.status_code == 422, yanit.text


async def test_openapi_temperature_c_yok_yeni_alanlar_opsiyonel() -> None:
    """CLEAN-B1 Faz 1: alan yanıt ve istek şemalarından KALKTI (kırıcı, frontend devriyle aynı
    gün). Yeni alanlar isteğe bağlı kalır."""
    semalar = app.openapi()["components"]["schemas"]
    for ad in ("SiteDiaryEntryDetail", "SiteDiaryEntryCreate", "SiteDiaryEntryUpdate"):
        assert "temperature_c" not in semalar[ad]["properties"], ad
    detay = semalar["SiteDiaryEntryDetail"]
    for alan in ("temp_min_c", "temp_max_c", "wind_ms"):
        assert alan in detay["properties"]
    olusturma = semalar["SiteDiaryEntryCreate"]
    assert not {"temp_min_c", "temp_max_c", "wind_ms"} & set(olusturma.get("required", []))
    hava = semalar["Weather"]["enum"]
    assert set(hava) == _ESKI_HAVA | _YENI_HAVA
