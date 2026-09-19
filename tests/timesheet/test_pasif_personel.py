"""Puantaj — PASİF/TASLAK personele adam-gün yazılamaz (kullanıcı kararı 2026-09-19).

## Kusur

`repository.get_personnel_by_ids` `is_active`/`is_draft` SÜZMÜYORDU; bordro ise
süzüyor (`payroll/service/compute_flow.py`: *"taslak kartın ücreti henüz
doğrulanmamıştır, pasif kişi işten ayrılmıştır"*). Yani puantaj, bordronun ASLA
ödemeyeceği kişiye adam-gün yazabiliyordu ve iki modül sessizce ayrışıyordu.

## 🔴 Neden DÜZ bir süzgeç YANLIŞ olurdu — kullanıcı kararı (b)

Bu uç bir **GÖVDE DEĞİŞTİRME** ucudur: gövde hafta+şantiye kapsamının TAM
kümesidir. Düz bir süzgeç eklenseydi, *sonradan* pasifleşen bir personeli içeren
GEÇMİŞ hafta tümüyle 422 alır ve **bir daha hiç düzenlenemez** hâle gelirdi —
o haftadaki başka bir kişinin saatini düzeltmek bile imkânsızlaşırdı. Üstelik
ürün pasif personelin kayıtlarını KORUMAYI seçmiştir (`personnel/models.py`:
*"Silme YOKTUR (puantaj kayıtları bağlı)"*).

Karar: **yalnız YENİ ya da DEĞİŞEN hücre reddedilir.** Dokunulmamış geçmiş
hücre aynen geçer, silinebilir de — temizlik yolu açık kalır.

## Her iddianın İKİ YARISI vardır

Reddin yanında mutlaka GEÇEN hâl vardır; yoksa "her şeyi reddet" hâline gelen
bir kapı da yeşil kalırdı.
"""

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.timesheet import guards
from app.modules.timesheet.models import TimesheetCode, TimesheetEntry
from tests.timesheet.conftest import ISO_HAFTA, ISO_YIL, hafta_gunu

pytestmark = pytest.mark.asyncio


def _saat_hucresi(personnel, offset: int, hours: str = "9", **ekstra) -> dict:
    return {
        "personnel_id": str(personnel.id),
        "work_date": hafta_gunu(offset).isoformat(),
        "hours": hours,
        **ekstra,
    }


async def _kaydet(client: AsyncClient, headers, site_id, cells):
    return await client.put(
        f"/sites/{site_id}/timesheet/week",
        params={"iso_year": ISO_YIL, "iso_week": ISO_HAFTA},
        json={"cells": cells},
        headers=headers,
    )


async def _hucre_sayisi(seeded_db: AsyncSession, personnel) -> int:
    return len(
        (
            await seeded_db.execute(
                select(TimesheetEntry).where(TimesheetEntry.personnel_id == personnel.id)
            )
        )
        .scalars()
        .all()
    )


# --------------------------------------------------------------------------- #
# GEÇEN hâller — kapı kullanıcıyı KİLİTLEMİYOR
# --------------------------------------------------------------------------- #


async def test_AKTIF_personele_adam_gun_yazilir(
    client: AsyncClient,
    admin_headers: dict[str, str],
    santiye,
    mehmet,
) -> None:
    """🔴 POZİTİF KONTROL — kapı "herkesi reddet" hâline gelirse bu kırmızı olur."""
    resp = await _kaydet(client, admin_headers, santiye.id, [_saat_hucresi(mehmet, 0)])
    assert resp.status_code == 200, resp.text


async def test_pasif_personelin_DEGISMEMIS_gecmis_hucresi_KAYDEDILEBILIR(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    admin_kullanicisi,
    santiye,
    mehmet,
    personel_fabrikasi,
    hucre_fabrikasi,
) -> None:
    """🔴 KARARIN ÇEKİRDEĞİ — (b) seçeneğinin varlık sebebi.

    Ayrılan bir işçinin geçmiş haftası, AYNI hâliyle yeniden gönderildiğinde
    geçmelidir. Düz süzgeç (a seçeneği) burada 422 verir ve o haftayı SONSUZA
    DEK dondururdu: aynı haftadaki Mehmet'in saatini düzeltmek bile imkânsız
    olurdu.
    """
    ayrilan = await personel_fabrikasi("Ayrılan İşçi")
    await hucre_fabrikasi(santiye, ayrilan, hafta_gunu(0), admin_kullanicisi, hours=Decimal("8"))
    ayrilan.is_active = False
    await seeded_db.flush()

    resp = await _kaydet(
        client,
        admin_headers,
        santiye.id,
        [
            _saat_hucresi(ayrilan, 0, hours="8"),  # DEĞİŞMEDİ
            _saat_hucresi(mehmet, 0, hours="9"),  # aynı haftada BAŞKA kişi düzenleniyor
        ],
    )
    assert resp.status_code == 200, resp.text


async def test_pasif_personelin_hucresi_SILINEBILIR(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    admin_kullanicisi,
    santiye,
    personel_fabrikasi,
    hucre_fabrikasi,
) -> None:
    """Temizlik yolu AÇIK kalır: hücreyi gövdeden çıkarmak onu siler ve bu
    yanlışlıkla yazılmış bir kaydın DÜZELTİLEBİLMESİ demektir."""
    ayrilan = await personel_fabrikasi("Ayrılan İşçi")
    await hucre_fabrikasi(santiye, ayrilan, hafta_gunu(0), admin_kullanicisi, hours=Decimal("8"))
    ayrilan.is_active = False
    await seeded_db.flush()

    resp = await _kaydet(client, admin_headers, santiye.id, [])
    assert resp.status_code == 200, resp.text
    assert await _hucre_sayisi(seeded_db, ayrilan) == 0


# --------------------------------------------------------------------------- #
# REDDEDİLEN hâller
# --------------------------------------------------------------------------- #


async def test_PASIF_personele_YENI_adam_gun_yazilamaz(
    client: AsyncClient,
    admin_headers: dict[str, str],
    santiye,
    personel_fabrikasi,
) -> None:
    """Bordronun asla ödemeyeceği kişiye adam-gün yazılamaz."""
    ayrilan = await personel_fabrikasi("Ayrılan İşçi", is_active=False)

    resp = await _kaydet(client, admin_headers, santiye.id, [_saat_hucresi(ayrilan, 0)])
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == guards.personnel_not_payable("Ayrılan İşçi")


async def test_TASLAK_personele_YENI_adam_gun_yazilamaz(
    client: AsyncClient,
    admin_headers: dict[str, str],
    santiye,
    personel_fabrikasi,
) -> None:
    """🔴 İKİ süzgeç AYRI AYRI ölçülür: yalnız `is_active` denetleyen bir kod
    taslak kartı geçirirdi ve ücreti doğrulanmamış kişi puantaja girerdi."""
    taslak = await personel_fabrikasi("Taslak Kart", is_draft=True)

    resp = await _kaydet(client, admin_headers, santiye.id, [_saat_hucresi(taslak, 0)])
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == guards.personnel_not_payable("Taslak Kart")


async def test_pasif_personelin_gecmis_hucresi_DEGISTIRILEMEZ(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    admin_kullanicisi,
    santiye,
    personel_fabrikasi,
    hucre_fabrikasi,
) -> None:
    """Geçmişi KORUMAK, geçmişi DÜZENLEMEYE açmak değildir: 8 saat 10'a çekilemez."""
    ayrilan = await personel_fabrikasi("Ayrılan İşçi")
    await hucre_fabrikasi(santiye, ayrilan, hafta_gunu(0), admin_kullanicisi, hours=Decimal("8"))
    ayrilan.is_active = False
    await seeded_db.flush()

    resp = await _kaydet(client, admin_headers, santiye.id, [_saat_hucresi(ayrilan, 0, hours="10")])
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == guards.personnel_not_payable("Ayrılan İşçi")


async def test_pasif_personelin_hucresi_KODA_cevrilemez(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    admin_kullanicisi,
    santiye,
    personel_fabrikasi,
    hucre_fabrikasi,
) -> None:
    """🔴 "Değişme" YALNIZ saat değildir. Saatli hücreyi KODLUYA çevirmek de bir
    değişikliktir; yalnız `hours` karşılaştıran bir kod bunu kaçırırdı."""
    ayrilan = await personel_fabrikasi("Ayrılan İşçi")
    await hucre_fabrikasi(santiye, ayrilan, hafta_gunu(0), admin_kullanicisi, hours=Decimal("8"))
    ayrilan.is_active = False
    await seeded_db.flush()

    resp = await _kaydet(
        client,
        admin_headers,
        santiye.id,
        [
            {
                "personnel_id": str(ayrilan.id),
                "work_date": hafta_gunu(0).isoformat(),
                "code": TimesheetCode.leave.value,
            }
        ],
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == guards.personnel_not_payable("Ayrılan İşçi")


async def test_pasif_personelin_hucresi_BASKA_BOLUME_tasinamaz(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    admin_kullanicisi,
    santiye,
    bolum,
    personel_fabrikasi,
    hucre_fabrikasi,
) -> None:
    """🔴 Üçüncü değişim ekseni: `section_id`. Saat ve kod AYNI kalsa bile hücre
    başka bir bölüme taşınırsa maliyet BAŞKA bir yere düşer."""
    ayrilan = await personel_fabrikasi("Ayrılan İşçi")
    await hucre_fabrikasi(santiye, ayrilan, hafta_gunu(0), admin_kullanicisi, hours=Decimal("8"))
    ayrilan.is_active = False
    await seeded_db.flush()

    resp = await _kaydet(
        client,
        admin_headers,
        santiye.id,
        [_saat_hucresi(ayrilan, 0, hours="8", section_id=str(bolum.id))],
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == guards.personnel_not_payable("Ayrılan İşçi")


async def test_pasif_personelin_KOD_hucresi_BASKA_KODA_cevrilemez(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    admin_kullanicisi,
    santiye,
    personel_fabrikasi,
    hucre_fabrikasi,
) -> None:
    """🔴 Bu testi MUTASYON DOĞURDU (2026-09-19).

    `code` karşılaştırmasını kaldıran mutasyon YEŞİL kalıyordu: saatliyi koda
    çeviren hâli zaten `hours` (8 → None) yakalıyor, dolayısıyla üstteki testler
    `code` eksenini ölçtüklerini SANIYORDU. KODDAN KODA değişimde (`leave` →
    `holiday`) ise `hours` iki tarafta da NULL'dır ve TEK bekçi `code`tur.
    """
    ayrilan = await personel_fabrikasi("Ayrılan İşçi")
    await hucre_fabrikasi(
        santiye, ayrilan, hafta_gunu(0), admin_kullanicisi, code=TimesheetCode.leave
    )
    ayrilan.is_active = False
    await seeded_db.flush()

    resp = await _kaydet(
        client,
        admin_headers,
        santiye.id,
        [
            {
                "personnel_id": str(ayrilan.id),
                "work_date": hafta_gunu(0).isoformat(),
                "code": TimesheetCode.holiday.value,
            }
        ],
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == guards.personnel_not_payable("Ayrılan İşçi")
