"""ST T2 — `inventory` izin kapıları + denetim günlüğü.

Spec §4: okuma `view`, yazma `full`, silme `admin` (`full` SİLMEYİ KAPSAMAZ —
`app/core/access.py`). Seed matrisi (`inventory`) DEĞİŞTİRİLMEZ; bu dosya onun
uçlara nasıl yansıdığını dondurur:

* `accounting` (`_N`) → okumada bile 403;
* `site_chief` (`_V`) → okur, POST/PATCH'te 403;
* `procurement` (`_F`) → yazar, DELETE'te 403;
* `system_admin` (`_A`) → hepsi.

Denetim: **üç yazma ucu** (kart oluştur/güncelle, depo oluştur/adlandır/sil) tek
satır yazar; **okuma uçları HİÇBİR ŞEY yazmaz** (WORKFLOW kuralı). Yeni bir
`AuditAction` üyesi AÇILMAZ — ayrım METİNDEDİR.
"""

import uuid

import pytest
from sqlalchemy import select

from app.modules.audit.models import AuditAction, AuditLog

KART = {"code": "SNK-0421", "name": "Nervürlü Demir Ø12", "category": "steel", "unit": "Ton"}


async def _detaylar(session, action: AuditAction | None = None) -> list[str]:
    stmt = select(AuditLog).order_by(AuditLog.occurred_at)
    if action is not None:
        stmt = stmt.where(AuditLog.action == action)
    return [k.detail for k in (await session.execute(stmt)).scalars().all()]


# --- İzin kapıları ---


@pytest.mark.asyncio
async def test_izinsiz_rol_okumada_403(client, yetkisiz_headers):
    yanit = await client.get("/stock/items", headers=yetkisiz_headers)
    assert yanit.status_code == 403, yanit.text
    depo = await client.get("/warehouses", headers=yetkisiz_headers)
    assert depo.status_code == 403, depo.text


@pytest.mark.asyncio
async def test_view_seviyesi_okur(client, sef_headers):
    assert (await client.get("/stock/items", headers=sef_headers)).status_code == 200
    assert (await client.get("/warehouses", headers=sef_headers)).status_code == 200


@pytest.mark.asyncio
async def test_view_seviyesi_yazamaz_403(client, sef_headers, satinalma_headers):
    assert (await client.post("/stock/items", json=KART, headers=sef_headers)).status_code == 403
    assert (
        await client.post("/warehouses", json={"name": "Ana Ambar"}, headers=sef_headers)
    ).status_code == 403

    kart = await client.post("/stock/items", json=KART, headers=satinalma_headers)
    yanit = await client.patch(
        f"/stock/items/{kart.json()['id']}", json={"name": "X"}, headers=sef_headers
    )
    assert yanit.status_code == 403, yanit.text


@pytest.mark.asyncio
async def test_full_seviyesi_silemez_403(client, satinalma_headers):
    """`full` silmeyi KAPSAMAZ: depo silme yalnız `admin`dedir. Sonuç (kabul
    edildi): seed matrisinde `inventory:admin` yalnız `system_admin`dedir —
    patron ve satınalma depo SİLEMEZ."""
    depo = await client.post("/warehouses", json={"name": "Ana Ambar"}, headers=satinalma_headers)
    yanit = await client.delete(f"/warehouses/{depo.json()['id']}", headers=satinalma_headers)
    assert yanit.status_code == 403, yanit.text


@pytest.mark.asyncio
async def test_yetki_kapisi_korkuluktan_once_kosar(client, sef_headers):
    """Yetkisiz aktör, kaydın VAR OLUP OLMADIĞINI öğrenemez: 404 değil 403."""
    yanit = await client.patch(
        f"/warehouses/{uuid.uuid4()}", json={"name": "X"}, headers=sef_headers
    )
    assert yanit.status_code == 403, yanit.text


# --- Denetim günlüğü ---


@pytest.mark.asyncio
async def test_kart_olusturma_ve_guncelleme_denetime_yazar(client, seeded_db, satinalma_headers):
    kart = await client.post("/stock/items", json=KART, headers=satinalma_headers)
    await client.patch(
        f"/stock/items/{kart.json()['id']}",
        json={"name": "Nervürlü Demir Ø14"},
        headers=satinalma_headers,
    )

    olusturma = await _detaylar(seeded_db, AuditAction.create)
    guncelleme = await _detaylar(seeded_db, AuditAction.update)
    assert any("SNK-0421" in d and "Malzeme" in d for d in olusturma), olusturma
    assert any("Nervürlü Demir Ø14" in d for d in guncelleme), guncelleme


@pytest.mark.asyncio
async def test_depo_yazma_uclari_denetime_yazar(client, seeded_db, admin_headers):
    depo = await client.post("/warehouses", json={"name": "Ana Ambar"}, headers=admin_headers)
    depo_id = depo.json()["id"]
    await client.patch(
        f"/warehouses/{depo_id}", json={"name": "Merkez Ambar"}, headers=admin_headers
    )
    await client.delete(f"/warehouses/{depo_id}", headers=admin_headers)

    silme = await _detaylar(seeded_db, AuditAction.delete)
    guncelleme = await _detaylar(seeded_db, AuditAction.update)
    assert any("Merkez Ambar" in d and "→" in d for d in guncelleme), guncelleme
    # Metin kayıt YOK OLMADAN ÖNCE kurulur — sonra kurulsaydı ad okunamaz ve
    # günlüğe adsız bir satır düşerdi (`sites` dersi).
    assert any("Merkez Ambar" in d for d in silme), silme


@pytest.mark.asyncio
async def test_okuma_uclari_denetime_yazmaz(client, seeded_db, admin_headers):
    await client.get("/stock/items", headers=admin_headers)
    await client.get("/warehouses", headers=admin_headers)
    kayitlar = await _detaylar(seeded_db)
    assert all(k == "Sisteme giriş yapıldı" for k in kayitlar), kayitlar


@pytest.mark.asyncio
async def test_engellenen_silme_denetime_yazmaz(
    client, seeded_db, admin_headers, satinalma_headers
):
    """Günlük GERÇEKLEŞEN olayı kaydeder, DENEMEYİ değil (`documents` dersi)."""
    depo = await client.post("/warehouses", json={"name": "Ana Ambar"}, headers=admin_headers)
    await client.delete(f"/warehouses/{depo.json()['id']}", headers=satinalma_headers)
    assert await _detaylar(seeded_db, AuditAction.delete) == []
