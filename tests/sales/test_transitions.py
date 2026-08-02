"""P8 T5 — satış durumu geçişleri (spec §4; mockup `Satış Yönetimi.dc.html`).

Mockup satır numaraları:
- 55 "Satılan (Tapulu)" · 56 "Rezerve" — KPI'lar durumun İKİ ucunu gösterir
- 166 / 202 "Tapu Devredildi" rozeti = `deed_transferred` durumu
- 188 "Kapora alındı · 15 gün süre" = `reservation` durumu (§8 S4)

Geçiş matrisi TEK KAYNAKTIR (`app/modules/sales/transitions.py`) ve buradaki
"matris deliği taraması" testi onu TÜM (durum, işlem) çiftleri üzerinde dolaşır:
tabloya yeni bir çift eklendiğinde test kendiliğinden onu geçerli sayar, ama
tablodan bağımsız yazılmış bir `if` bloğu eklenirse tarama onu YAKALAR.
"""

import inspect
import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.modules.audit.models import AuditAction, AuditLog
from app.modules.sales import transitions
from app.modules.sales.guards import INVALID_STATUS_TRANSITION, SALE_MISSING
from app.modules.sales.models import UnitSale, UnitSaleStatus
from app.modules.sales.transitions import TRANSITIONS, SaleAction
from app.modules.units.models import Unit, UnitSalesStatus

pytestmark = pytest.mark.asyncio

# Ünite senkronunun beklenen çıktısı (spec §3) — geçiş uçlarının SONUCU.
BEKLENEN_UNITE_DURUMU = {
    UnitSaleStatus.reservation: UnitSalesStatus.reserved,
    UnitSaleStatus.active: UnitSalesStatus.sold,
    # Tapu devri üniteyi `sold`ta BIRAKIR: `UnitSalesStatus`ta "Tapulu" YOKTUR.
    UnitSaleStatus.deed_transferred: UnitSalesStatus.sold,
    UnitSaleStatus.cancelled: UnitSalesStatus.listed,
}

TAM_GOVDE = {
    "sale_type": "sale",  # F56 → başlangıç durumu `active`
    "sale_price": "1440000.00",  # F86
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


async def _unite_durumu(session, unite_id) -> UnitSalesStatus | None:
    unit = (await session.execute(select(Unit).where(Unit.id == unite_id))).scalar_one()
    await session.refresh(unit)
    return unit.sales_status


async def _durum_ata(session, sale_id, status: UnitSaleStatus) -> None:
    """Matris taraması için kaydı DOĞRUDAN istenen duruma çeker.

    Uçlar üzerinden kurulamayan durum bileşimleri de (örn. `cancelled`ten sonra
    yeniden `active`) taranabilsin diye DB'ye elle yazılır; test edilen şey
    geçiş TABLOSUDUR, oraya nasıl gelindiği değil.
    """
    sale = (await session.execute(select(UnitSale).where(UnitSale.id == sale_id))).scalar_one()
    sale.status = status
    await session.flush()


async def _denetim_metinleri(session) -> list[str]:
    rows = (await session.execute(select(AuditLog))).scalars().all()
    return [row.detail for row in rows]


# --- 1) Geçerli geçişler + ünite senkronu ---


async def test_rezervasyon_aktiflestirilince_unite_sold_olur(
    client, admin_headers, seeded_db, proje, unite, musteri
):
    """`reservation` → `active` (S56 "Rezerve" kartından S55 "Satılan"a geçiş)."""
    satis = await _satis(client, admin_headers, proje, unite, musteri, sale_type="reservation")
    assert satis["status"] == "reservation"
    assert await _unite_durumu(seeded_db, unite.id) is UnitSalesStatus.reserved

    resp = await client.post(f"/sales/{satis['id']}/activate", headers=admin_headers)

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "active"
    assert await _unite_durumu(seeded_db, unite.id) is UnitSalesStatus.sold


async def test_tapu_devri_uniteyi_sold_birakir(
    client, admin_headers, seeded_db, proje, unite, musteri
):
    """S166 "Tapu Devredildi": satış kaydı ilerler, ünite `sold` KALIR (spec §3)."""
    satis = await _satis(client, admin_headers, proje, unite, musteri)
    assert satis["status"] == "active"

    resp = await client.post(f"/sales/{satis['id']}/transfer-deed", headers=admin_headers)

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "deed_transferred"
    assert await _unite_durumu(seeded_db, unite.id) is UnitSalesStatus.sold


async def test_rezervasyon_iptali_uniteyi_vitrine_dondurur(
    client, admin_headers, seeded_db, proje, unite, musteri
):
    satis = await _satis(client, admin_headers, proje, unite, musteri, sale_type="reservation")

    resp = await client.post(
        f"/sales/{satis['id']}/cancel",
        json={"reason": "Alıcı kaporadan vazgeçti"},
        headers=admin_headers,
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "cancelled"
    assert await _unite_durumu(seeded_db, unite.id) is UnitSalesStatus.listed


async def test_aktif_satis_iptali_uniteyi_vitrine_dondurur(
    client, admin_headers, seeded_db, proje, unite, musteri
):
    satis = await _satis(client, admin_headers, proje, unite, musteri)

    resp = await client.post(
        f"/sales/{satis['id']}/cancel",
        json={"reason": "Sözleşme feshedildi"},
        headers=admin_headers,
    )

    assert resp.status_code == 200, resp.text
    assert await _unite_durumu(seeded_db, unite.id) is UnitSalesStatus.listed


async def test_iptalden_sonra_unite_yeniden_satilabilir(
    client, admin_headers, proje, unite, musteri
):
    """İptal `uq_unit_sales_open_unit` kısmi indeksinin dışına düşer — ünite serbest."""
    satis = await _satis(client, admin_headers, proje, unite, musteri)
    resp = await client.post(
        f"/sales/{satis['id']}/cancel", json={"reason": "Fesih"}, headers=admin_headers
    )
    assert resp.status_code == 200, resp.text

    yeni = await _satis(client, admin_headers, proje, unite, musteri)
    assert yeni["status"] == "active"


# --- 2) Geçersiz geçişler: matris deliği taraması ---


@pytest.mark.parametrize(
    ("baslangic", "yol"),
    [
        # Terminal durumdan ÇIKIŞ yoktur.
        (UnitSaleStatus.deed_transferred, "activate"),
        (UnitSaleStatus.deed_transferred, "transfer-deed"),
        (UnitSaleStatus.deed_transferred, "cancel"),
        (UnitSaleStatus.cancelled, "activate"),
        (UnitSaleStatus.cancelled, "transfer-deed"),
        (UnitSaleStatus.cancelled, "cancel"),
        # Ara adım ATLANAMAZ: rezervasyondan doğrudan tapuya geçilmez.
        (UnitSaleStatus.reservation, "transfer-deed"),
        # Zaten aktif olan kayıt yeniden aktifleştirilemez.
        (UnitSaleStatus.active, "activate"),
    ],
)
async def test_gecersiz_gecis_409_doner(
    client, admin_headers, seeded_db, proje, unite, musteri, baslangic, yol
):
    satis = await _satis(client, admin_headers, proje, unite, musteri)
    await _durum_ata(seeded_db, uuid.UUID(satis["id"]), baslangic)

    resp = await client.post(
        f"/sales/{satis['id']}/{yol}", json={"reason": "gerekçe"}, headers=admin_headers
    )

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == INVALID_STATUS_TRANSITION


async def test_matris_disi_tum_ciftler_409(client, admin_headers, seeded_db, proje, unite, musteri):
    """TÜM (durum × işlem) çiftlerini tarar: tabloda olmayan HER çift 409'dur.

    Tablo dışında yazılmış bir `if` dalı (ya da tabloya eklenmemiş bir "kolaylık"
    geçişi) burada yakalanır — kapsam el yordamıyla seçilen örneklere DEĞİL,
    çarpımın tamamına dayanır.
    """
    satis = await _satis(client, admin_headers, proje, unite, musteri)
    for durum in UnitSaleStatus:
        for action in SaleAction:
            await _durum_ata(seeded_db, uuid.UUID(satis["id"]), durum)
            resp = await client.post(
                f"/sales/{satis['id']}/{action.value}",
                json={"reason": "gerekçe"},
                headers=admin_headers,
            )
            beklenen = TRANSITIONS.get((durum, action))
            if beklenen is None:
                assert resp.status_code == 409, f"{durum}/{action}: {resp.text}"
                assert resp.json()["detail"] == INVALID_STATUS_TRANSITION
            else:
                assert resp.status_code == 200, f"{durum}/{action}: {resp.text}"
                assert resp.json()["status"] == beklenen.value


def test_terminal_durumlar_kaynak_degildir():
    """`deed_transferred` ve `cancelled` tabloda KAYNAK olarak GEÇMEZ (spec §4)."""
    kaynaklar = {durum for durum, _ in TRANSITIONS}
    assert UnitSaleStatus.deed_transferred not in kaynaklar
    assert UnitSaleStatus.cancelled not in kaynaklar


def test_unite_senkronu_kopyalanmaz_servis_yardimcisi_cagrilir():
    """T3'ün `sync_unit_sales_status` yardımcısı ÇAĞRILIR; harita KOPYALANMAZ.

    Kopyalanan bir eşleme zamanla ayrışır ve ayrışan taraf üniteyi yanlış
    vitrinde bırakır (T3 `service.py` notu).
    """
    kaynak = inspect.getsource(transitions)
    assert "sync_unit_sales_status" in kaynak
    assert "UnitSalesStatus.sold" not in kaynak
    assert "UnitSalesStatus.listed" not in kaynak


# --- 3) İptal gerekçesi ---


async def test_iptal_gerekcesi_denetim_gunlugune_yazilir(
    client, admin_headers, seeded_db, proje, unite, musteri
):
    """`unit_sales`te gerekçe KOLONU YOKTUR (T1) — gerekçe denetim METNİNE gider.

    Yeni kolon/migration açmak yerine denetim günlüğü kullanılır: iptal
    gerekçesi bir OLAY açıklamasıdır, kaydın bir NİTELİĞİ değil.
    """
    satis = await _satis(client, admin_headers, proje, unite, musteri)

    resp = await client.post(
        f"/sales/{satis['id']}/cancel",
        json={"reason": "Alıcı krediden çıkamadı"},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text

    metinler = await _denetim_metinleri(seeded_db)
    iptal = [m for m in metinler if "iptal" in m.lower()]
    assert len(iptal) == 1
    assert "Alıcı krediden çıkamadı" in iptal[0]
    assert proje.name in iptal[0]
    assert "A Blok · 12" in iptal[0]
    assert musteri.name in iptal[0]


@pytest.mark.parametrize("govde", [{}, {"reason": ""}, {"reason": "   "}, {"reason": None}])
async def test_gerekcesiz_iptal_422(client, admin_headers, proje, unite, musteri, govde):
    """Gerekçe ZORUNLUDUR: boş/boşluk gövde 422 — sessizce "gerekçesiz" iptal yok."""
    satis = await _satis(client, admin_headers, proje, unite, musteri)

    resp = await client.post(f"/sales/{satis['id']}/cancel", json=govde, headers=admin_headers)

    assert resp.status_code == 422, resp.text


async def test_reddedilen_iptal_denetim_satiri_birakmaz(
    client, admin_headers, seeded_db, proje, unite, musteri
):
    satis = await _satis(client, admin_headers, proje, unite, musteri)
    await _durum_ata(seeded_db, uuid.UUID(satis["id"]), UnitSaleStatus.cancelled)

    resp = await client.post(
        f"/sales/{satis['id']}/cancel", json={"reason": "tekrar"}, headers=admin_headers
    )

    assert resp.status_code == 409
    assert not [m for m in await _denetim_metinleri(seeded_db) if "iptal" in m.lower()]


# --- 4) Denetim günlüğü (her geçiş AYRI metin) ---


async def test_her_gecis_ayri_denetim_metni_birakir(
    client, admin_headers, seeded_db, proje, unite, musteri
):
    satis = await _satis(client, admin_headers, proje, unite, musteri, sale_type="reservation")
    assert (
        await client.post(f"/sales/{satis['id']}/activate", headers=admin_headers)
    ).status_code == 200
    assert (
        await client.post(f"/sales/{satis['id']}/transfer-deed", headers=admin_headers)
    ).status_code == 200

    rows = (await seeded_db.execute(select(AuditLog))).scalars().all()
    gecisler = [row for row in rows if "Satış" in row.detail or "Tapu" in row.detail]
    metinler = [row.detail for row in gecisler if "oluşturuldu" not in row.detail]
    assert any("aktifleştirildi" in m.lower() for m in metinler)
    assert any("tapu" in m.lower() for m in metinler)
    # İki metin BİRBİRİNDEN farklıdır (tek "güncellendi" metnine düşmez).
    assert len(metinler) == 2
    assert len(set(metinler)) == 2
    # Mevcut `update` aksiyonu yeter — yeni `AuditAction` (dolayısıyla migration) YOK.
    assert {row.action for row in gecisler if row.detail in metinler} == {AuditAction.update}


# --- 5) IDOR (spec §6) ---


@pytest.mark.parametrize("yol", ["activate", "transfer-deed", "cancel"])
async def test_kapsam_disi_gecis_404(
    client, admin_headers, kapsam_disi_headers, proje, unite, musteri, yol
):
    """Görünmeyen projenin satışı 404 — var olmayanla AYNI gövde (403 DEĞİL)."""
    satis = await _satis(client, admin_headers, proje, unite, musteri)

    resp = await client.post(
        f"/sales/{satis['id']}/{yol}", json={"reason": "x"}, headers=kapsam_disi_headers
    )

    assert resp.status_code == 404
    assert resp.json()["detail"] == SALE_MISSING


@pytest.mark.parametrize("yol", ["activate", "transfer-deed", "cancel"])
async def test_olmayan_satis_gecisi_404(client, admin_headers, yol):
    resp = await client.post(
        f"/sales/{uuid.uuid4()}/{yol}", json={"reason": "x"}, headers=admin_headers
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == SALE_MISSING


# --- 6) Yetki (403) ---


@pytest.mark.parametrize("yol", ["activate", "transfer-deed", "cancel"])
async def test_yetkisiz_gecis_403(
    client, admin_headers, view_headers, yetkisiz_headers, proje, unite, musteri, yol
):
    """Geçişler `sales:full` ister: `view` (muhasebe) ve `none` (şantiye şefi) 403."""
    satis = await _satis(client, admin_headers, proje, unite, musteri)

    for headers in (view_headers, yetkisiz_headers):
        resp = await client.post(
            f"/sales/{satis['id']}/{yol}", json={"reason": "x"}, headers=headers
        )
        assert resp.status_code == 403, resp.text


# --- 7) Rezervasyon süresi (S188, §8 S4): otomatik iptal YOK ---


async def test_suresi_dolan_rezervasyon_kendiliginden_iptal_OLMAZ(
    client, admin_headers, seeded_db, proje, unite, musteri
):
    """§8 S4: zamanlanmış iş YOKTUR; süresi dolmuş rezervasyon `reservation` KALIR."""
    satis = await _satis(
        client,
        admin_headers,
        proje,
        unite,
        musteri,
        sale_type="reservation",
        reservation_deposit="50000.00",
        reservation_due_date=str(date.today() - timedelta(days=3)),
    )

    resp = await client.get(f"/sales/{satis['id']}", headers=admin_headers)

    assert resp.status_code == 200
    assert resp.json()["status"] == "reservation"
    assert await _unite_durumu(seeded_db, unite.id) is UnitSalesStatus.reserved
