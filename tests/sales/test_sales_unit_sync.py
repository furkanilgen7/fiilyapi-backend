"""P8 T3 — `units.sales_status` otomasyonu ve ELLE GİRİŞ KİLİDİ (spec §3).

`units/models.py:232-240`'taki "GELECEK IS — P8" notunun kapanışı:
`sales_status` artık satış kaydından TÜRETİLİR ve `PATCH /units` gövdesinden
ÇIKARILMIŞTIR.

Senkron haritası TEK bir yardımcıda (`service.sync_unit_sales_status`) toplanır;
T5'in geçiş uçları (`activate`/`transfer-deed`/`cancel`) aynı yardımcıyı
çağıracaktır — kopyalanan bir harita zamanla ayrışır ve ayrışan taraf sessiz bir
veri tutarsızlığı olur.
"""

import pytest
from sqlalchemy import func, select

from app.main import app
from app.modules.sales import service
from app.modules.sales.models import UnitSaleStatus
from app.modules.units.models import Unit, UnitSalesStatus
from app.modules.units.schemas import UnitUpdate


def test_senkron_haritasi_dort_durumu_da_kapsar():
    """Spec §3: `reservation`→reserved · `active`→sold · `deed_transferred`→sold

    (KALIR) · `cancelled`→listed. `None` = açık satış kaydı yok → `listed`.
    """
    assert service.unit_status_for(UnitSaleStatus.reservation) is UnitSalesStatus.reserved
    assert service.unit_status_for(UnitSaleStatus.active) is UnitSalesStatus.sold
    assert service.unit_status_for(UnitSaleStatus.deed_transferred) is UnitSalesStatus.sold
    assert service.unit_status_for(UnitSaleStatus.cancelled) is UnitSalesStatus.listed
    assert service.unit_status_for(None) is UnitSalesStatus.listed


def test_harita_tum_satis_durumlarini_tanir():
    """Yeni bir `UnitSaleStatus` değeri eklenirse bu test KIRMIZIYA döner —

    sessizce eşlenmemiş bir durum bırakmak üniteyi yanlış vitrinde bırakırdı.
    """
    for durum in UnitSaleStatus:
        assert service.unit_status_for(durum) in set(UnitSalesStatus)


def test_unit_update_semasinda_sales_status_yoktur():
    """Spec §3: elle giriş KİLİTLENİR. Mevcut UI olmadığından kırıcı değildir."""
    assert "sales_status" not in UnitUpdate.model_fields


def test_openapi_unit_update_govdesinde_sales_status_yok():
    """Sözleşme kapısı: `gen:api` istemcisinde alan GÖRÜNMEMELİ."""
    sema = app.openapi()["components"]["schemas"]["UnitUpdate"]

    assert "sales_status" not in sema["properties"]


@pytest.mark.asyncio
async def test_patch_units_sales_status_gonderimi_degistirmez(
    client, admin_headers, unite, db_session
):
    """Alan şemadan çıktığı için gövdedeki değer SESSİZCE YOK SAYILIR (Pydantic

    varsayılanı `extra='ignore'`). Ünite `listed` kalır — satış kaydı yok.
    """
    resp = await client.patch(
        f"/units/{unite.id}", json={"sales_status": "sold", "layout": "4+1"}, headers=admin_headers
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["layout"] == "4+1"
    assert resp.json()["sales_status"] == "listed"
    await db_session.refresh(unite)
    assert unite.sales_status is UnitSalesStatus.listed


# --- P8 T3 körlüğü: ÜNİTE OLUŞTURMA yolu (yukarıdaki testler yalnız PATCH'i ölçüyordu) ---


@pytest.mark.asyncio
@pytest.mark.parametrize("durum", ["sold", "reserved"])
async def test_unite_olusturulurken_satildi_rezerve_secilemez_422(
    client, admin_headers, proje, blok, db_session, durum: str
):
    """`POST /projects/{id}/units` İKİNCİ bir yazma yoluydu: `UnitCreate.sales_status`

    doğrudan sütuna yazılıyordu ve satış kaydı sorulmuyordu. Vitrin durumu satış
    kaydından TÜRER (spec §3) — açılış vitrini yalnız `listed` olabilir.
    """
    resp = await client.post(
        f"/projects/{proje.id}/units",
        json={
            "block_id": str(blok.id),
            "unit_no": "99",
            "unit_kind": "apartment",
            "sales_status": durum,
        },
        headers=admin_headers,
    )

    assert resp.status_code == 422, resp.text
    adet = await db_session.scalar(
        select(func.count()).select_from(Unit).where(Unit.block_id == blok.id, Unit.unit_no == "99")
    )
    assert adet == 0


@pytest.mark.asyncio
async def test_unite_olusturulurken_listed_serbest(client, admin_headers, proje, blok):
    """Kapı yalnız `sold`/`reserved`ı reddeder: açık `listed` gönderimi 201 kalır

    (UE 94 açılır kutusunun varsayılan seçeneği) — alan şemadan DÜŞÜRÜLMEDİ.
    """
    resp = await client.post(
        f"/projects/{proje.id}/units",
        json={
            "block_id": str(blok.id),
            "unit_no": "98",
            "unit_kind": "apartment",
            "sales_status": "listed",
        },
        headers=admin_headers,
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["sales_status"] == "listed"
