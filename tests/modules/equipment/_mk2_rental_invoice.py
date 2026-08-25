"""MK-2 kira faturası uç testlerinin PAYLAŞILAN kurulumu.

`test_mk2_rental_invoice_api.py` 800 satır tavanını aşınca bölündü
(`_journal.py` emsali): yardımcılar KOPYALANMADI, buraya alındı — iki kopya
olsaydı biri güncellenip öteki kalır ve iki dosya AYNI ismi taşıyan FARKLI
gövdelerle koşardı.

Hiçbir testin iddiası bu bölmeyle değişmedi.
"""

import uuid
from datetime import date
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.equipment.models import (
    Equipment,
    EquipmentRentalInvoiceLine,
    EquipmentWorkLog,
    WorkLogType,
)
from app.modules.procurement.models import PaymentTerms, Supplier
from app.modules.sites.models import Site

_YIL = 2026
_AY = 7

#: Tek çalışma kaydının GÜNLÜK tavanı 24 saattir (MK-1 K12, DB CHECK'i de aynısını
#: söyler) ama kira hakedişi satırı bir AYIN toplamını taşır. Bu yüzden testlerin
#: "186 saat"i art arda günlere BÖLÜNEREK yazılır — tek kayda sığdırmak MK-1'in
#: fizik kuralını çiğnerdi.
_GUNLUK_DILIM = Decimal("20")

#: Saatlik bedel — `rate_period=hourly` seçildiği için dönüşüm yoktur ve
#: beklentiler `saat × bedel`den DOĞRUDAN okunur (`cost.DAILY_HOURS` yolu MK-1'in
#: kendi testlerinde zaten kapalıdır; burada onu tekrar ölçmek kuralı iki yere
#: yazardı).
_BEDEL = Decimal("320.00")

#: MK-3 — `monthly` dönemin AYLIK bedeli ve onu saate çeviren PAYDA. İkisi
#: birlikte tam bölünecek şekilde seçildi (64.000 / 200 = 320): beklenti
#: yuvarlamadan değil, kuraldan okunsun.
_AYLIK_BEDEL = Decimal("64000.00")
_KAPASITE = 200


async def _tedarikci(session: AsyncSession, name: str) -> Supplier:
    supplier = Supplier(name=name, payment_terms=PaymentTerms.days_30)
    session.add(supplier)
    await session.flush()
    return supplier


async def _kayit(
    session: AsyncSession,
    equipment: Equipment,
    *,
    hours: str,
    ilk_gun: int,
    site: Site | None = None,
    record_type: WorkLogType = WorkLogType.worked,
) -> list[EquipmentWorkLog]:
    """Dönem toplamını GÜNLERE BÖLEREK yazar (K12 tavanı: gün 24 saattir).

    `ilk_gun` çağrı başına AYRIDIR: aynı ekipmanın çalışma ve arıza kayıtları
    aynı güne düşseydi günlük tavan denetimi test kurulumunu reddederdi.
    """
    kalan = Decimal(hours)
    kayitlar: list[EquipmentWorkLog] = []
    gun = ilk_gun
    while kalan > 0:
        dilim = min(kalan, _GUNLUK_DILIM)
        log = EquipmentWorkLog(
            equipment_id=equipment.id,
            work_date=date(_YIL, _AY, gun),
            site_id=None if site is None else site.id,
            record_type=record_type,
            hours=dilim,
        )
        session.add(log)
        kayitlar.append(log)
        kalan -= dilim
        gun += 1
    await session.flush()
    return kayitlar


def _govde(supplier: Supplier, **kwargs) -> dict:
    govde = {
        "supplier_id": str(supplier.id),
        "period_year": _YIL,
        "period_month": _AY,
        "rate_period": "hourly",
    }
    govde.update(kwargs)
    return govde


async def _fatura_kur(
    client: AsyncClient, headers: dict[str, str], supplier: Supplier, **kwargs
) -> dict:
    resp = await client.post(
        "/equipment/rental-invoices", json=_govde(supplier, **kwargs), headers=headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _detay(client: AsyncClient, headers: dict[str, str], invoice_id: str) -> dict:
    resp = await client.get(f"/equipment/rental-invoices/{invoice_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _satir(detay: dict, line_kind: str, equipment_id: uuid.UUID) -> dict:
    eslesenler = [
        s
        for s in detay["lines"]
        if s["line_kind"] == line_kind and s["equipment_id"] == str(equipment_id)
    ]
    assert len(eslesenler) == 1, f"{line_kind}/{equipment_id} satırı bulunamadı: {detay['lines']}"
    return eslesenler[0]


async def _db_satir(session: AsyncSession, invoice_id: str) -> EquipmentRentalInvoiceLine:
    """Faturanın TEK satırını KOLONLARIYLA okur (yanıt her kolonu basmaz).

    Snapshot iddiası satırın kendi kolonunda ölçülür: yanıttaki türev sayı
    doğru çıkarken kolon boş kalabilirdi ve delik bir sonraki okumada açılırdı.
    """
    satirlar = (
        (
            await session.execute(
                select(EquipmentRentalInvoiceLine).where(
                    EquipmentRentalInvoiceLine.invoice_id == uuid.UUID(invoice_id)
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(satirlar) == 1, satirlar
    await session.refresh(satirlar[0])
    return satirlar[0]


async def _durum_ilerlet(
    client: AsyncClient, headers: dict[str, str], invoice_id: str, adim: int
) -> None:
    """Faturayı `adim` kadar İLERİ taşır (her `approve` TEK adımdır, K5)."""
    for _ in range(adim):
        resp = await client.post(
            f"/equipment/rental-invoices/{invoice_id}/approve", headers=headers
        )
        assert resp.status_code == 200, resp.text
