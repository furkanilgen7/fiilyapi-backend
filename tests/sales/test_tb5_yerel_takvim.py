"""TB5 T3 — satis modulunun yerel takvim (TR) regresyonlari.

Kusur GORUNMEZDIR: `date.today()` / `created_at.date()` UTC gunu dondurur ve
TR ile UTC ancak 21:00-24:00 UTC arasinda AYRILIR. Bu yuzden buradaki testler
gercek saati BEKLEMEZ — `tests/_time.sabit_saat` ile TR gecesine sabitlenir.

Iki ayri davranis bekcilenir:
1. Pesinat vadesi (`generate-plan`) — kaydin ACILIS gununun TR karsiligi.
   Yonetimin 2026-08-15 00:2x TSI'de bizzat yakaladigi kusur budur: satir
   "dun" tarihiyle dogar ve kayit dogdugu anda gecikmis gorunur.
2. `is_overdue` — "gecikmis mi" karsilastirmasi TR gunune gore yapilir.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.modules.sales.models import SaleInstallment, UnitSale
from tests._time import TR_GECE_YARISI_SONRASI_UTC, sabit_saat

pytestmark = pytest.mark.asyncio

TAM_GOVDE = {
    "sale_type": "sale",
    "sale_price": "1440000.00",
    "payment_plan_type": "down_payment_installments",
    "down_payment": "440000.00",
    "installment_count": 12,
    "first_installment_date": "2026-09-01",
    "term_interest_pct": "0.00",
}


async def _satis(client, headers, proje, unite, musteri, **degisiklikler) -> dict:
    govde = TAM_GOVDE | {
        "unit_id": str(unite.id),
        "customer_id": str(musteri.id),
        **degisiklikler,
    }
    resp = await client.post(f"/projects/{proje.id}/sales", json=govde, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _created_at_ata(session, sale_id: str, an: datetime) -> None:
    """`created_at` sunucu varsayilanidir (gercek saat); testte ENJEKTE edilir.

    Pesinat vadesi bu sutundan turedigi icin, saat enjeksiyonu yalnizca
    `timezone.now`a yapilsa kaydin dogum ani yine gercek saatten gelirdi ve
    test hicbir sey kanitlamazdi.
    """
    sale = (
        await session.execute(select(UnitSale).where(UnitSale.id == uuid.UUID(sale_id)))
    ).scalar_one()
    sale.created_at = an
    await session.flush()


async def test_pesinat_vadesi_utc_gunune_degil_tr_gunune_yazilir(
    client, admin_headers, proje, unite, musteri, db_session, monkeypatch
):
    """TR'de 11 Mart 00:30'da acilan satisin pesinati 11 Mart'a vadelidir.

    UTC'de o an hala 10 Mart 21:30'dur; `created_at.date()` "10 Mart" derdi ve
    satir DOGDUGU ANDA bir gun gecikmis olurdu (F120 "Sozlesme imzasinda").
    """
    satis = await _satis(client, admin_headers, proje, unite, musteri)
    await _created_at_ata(db_session, satis["id"], TR_GECE_YARISI_SONRASI_UTC)
    sabit_saat(monkeypatch, TR_GECE_YARISI_SONRASI_UTC)

    resp = await client.post(f"/sales/{satis['id']}/generate-plan", headers=admin_headers)
    assert resp.status_code == 200, resp.text

    pesinat = resp.json()["items"][0]
    assert pesinat["label"] == "Peşinat"
    # UTC gunu 2026-03-10, TR gunu 2026-03-11 — KAYIT TR gununu tasir.
    assert pesinat["due_date"] == "2026-03-11"
    # ...ve bu yuzden dogdugu anda gecikmis DEGILDIR.
    assert pesinat["is_overdue"] is False


async def test_gecikmis_mi_karsilastirmasi_tr_gununu_kullanir(
    client, admin_headers, proje, unite, musteri, db_session, monkeypatch
):
    """TR'de gun donmusse dunun taksiti GECIKMISTIR; UTC hala dunu gosterir.

    Enjekte edilen an: 2027-12-31 21:30 UTC = 2028-01-01 00:30 TSI.
    Vadesi 2027-12-31 olan taksit TR takviminde gecmistir. UTC gunune (hala
    2027-12-31) gore bakilirsa `due_date < today` YANLIS cikar ve gecikme bir
    gun gec gorunur.
    """
    an_utc = datetime(2027, 12, 31, 21, 30, tzinfo=UTC)
    satis = await _satis(client, admin_headers, proje, unite, musteri)
    db_session.add(
        SaleInstallment(
            sale_id=uuid.UUID(satis["id"]),
            sequence_no=1,
            label="1 / 1",
            due_date=(an_utc - timedelta(hours=1)).date(),  # 2027-12-31
            amount=Decimal(TAM_GOVDE["sale_price"]),
        )
    )
    await db_session.flush()
    sabit_saat(monkeypatch, an_utc)

    resp = await client.get(f"/sales/{satis['id']}/installments", headers=admin_headers)
    assert resp.status_code == 200, resp.text

    (taksit,) = resp.json()["items"]
    assert taksit["due_date"] == "2027-12-31"
    assert taksit["is_overdue"] is True
