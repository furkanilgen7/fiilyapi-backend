"""T3 — `PUT /sites/{site_id}/timesheet` toplu DEĞİŞTİRME (spec §7 S4).

Mockup'ta tek bir **"Kaydet"** düğmesi vardır (ŞP 101): ekran matrisi BÜTÜN
olarak kaydeder, hücre hücre kaydetmez. Bu yüzden gövde dönem+şantiye
kapsamının TAM kümesidir ve gönderilmeyen hücre SİLİNİR.

Kapsam sınırı bu dosyanın en kritik bölümüdür: "değiştirme" semantiği yanlış
kurulursa bir ayın kaydı başka ayın ya da başka şantiyenin verisini süpürür.
Her iki sınır AYRI testle kanıtlanır.
"""

import uuid
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditLog
from app.modules.sites.guards import SITE_MISSING
from app.modules.timesheet import guards
from app.modules.timesheet.models import TimesheetCode, TimesheetEntry
from tests.timesheet.conftest import AY, YIL, gun

pytestmark = pytest.mark.asyncio

_C = TimesheetCode.worked
_T = TimesheetCode.holiday
_FM = TimesheetCode.overtime


def _hucre(personnel, day: int, code: TimesheetCode = _C, **ekstra) -> dict:
    return {
        "personnel_id": str(personnel.id),
        "work_date": gun(day).isoformat(),
        "code": code.value,
        **ekstra,
    }


async def _kaydet(client: AsyncClient, headers, site_id, cells, *, year=YIL, month=AY):
    return await client.put(
        f"/sites/{site_id}/timesheet",
        params={"year": year, "month": month},
        json={"cells": cells},
        headers=headers,
    )


async def _kayitlar(session: AsyncSession, site_id) -> list[TimesheetEntry]:
    stmt = select(TimesheetEntry).where(TimesheetEntry.site_id == site_id)
    return list((await session.execute(stmt)).scalars().all())


# --- Temel yazma ---


async def test_bos_matrise_hucre_yazar(
    client: AsyncClient, sef_headers, santiye, mehmet, seeded_db
) -> None:
    yanit = await _kaydet(client, sef_headers, santiye.id, [_hucre(mehmet, 1), _hucre(mehmet, 2)])
    assert yanit.status_code == 200, yanit.text

    govde = yanit.json()
    assert govde["worker_count"] == 1
    assert govde["total_man_days"] == 2
    assert len(await _kayitlar(seeded_db, santiye.id)) == 2


async def test_yanit_guncel_matristir(client: AsyncClient, sef_headers, santiye, mehmet) -> None:
    """Kaydet sonrası ekran yeniden çizilir; uç türev toplamları ANINDA döner."""
    yanit = await _kaydet(
        client,
        sef_headers,
        santiye.id,
        [_hucre(mehmet, 1), _hucre(mehmet, 2, _FM, overtime_hours="2.5"), _hucre(mehmet, 3, _T)],
    )
    matris = yanit.json()
    assert matris["rows"][0]["man_days"] == 2
    assert Decimal(matris["total_overtime_hours"]) == Decimal("2.5")


async def test_bolum_ve_proje_hucreye_yazilir(
    client: AsyncClient, sef_headers, santiye, mehmet, bolum, seeded_db
) -> None:
    """`project_id` gövdeden DEĞİL şantiyeden kopyalanır (kapsam süzgecinin alanı)."""
    yanit = await _kaydet(
        client, sef_headers, santiye.id, [_hucre(mehmet, 1, section_id=str(bolum.id))]
    )
    assert yanit.status_code == 200, yanit.text
    (kayit,) = await _kayitlar(seeded_db, santiye.id)
    assert kayit.section_id == bolum.id
    assert kayit.project_id == santiye.project_id


# --- DEĞİŞTİRME semantiği ---


async def test_gonderilmeyen_hucre_silinir(
    client: AsyncClient, sef_headers, santiye, mehmet, admin_kullanicisi, hucre_fabrikasi, seeded_db
) -> None:
    """⚠️ Gövde TAM kümedir: eski hücre gövdede yoksa SİLİNİR (spec §7 S4)."""
    await hucre_fabrikasi(santiye, mehmet, gun(1), _C, admin_kullanicisi)
    await hucre_fabrikasi(santiye, mehmet, gun(2), _C, admin_kullanicisi)

    yanit = await _kaydet(client, sef_headers, santiye.id, [_hucre(mehmet, 1)])
    assert yanit.status_code == 200, yanit.text

    kalanlar = await _kayitlar(seeded_db, santiye.id)
    assert [k.work_date for k in kalanlar] == [gun(1)]


async def test_bos_govde_donemi_temizler(
    client: AsyncClient, sef_headers, santiye, mehmet, admin_kullanicisi, hucre_fabrikasi, seeded_db
) -> None:
    await hucre_fabrikasi(santiye, mehmet, gun(1), _C, admin_kullanicisi)
    yanit = await _kaydet(client, sef_headers, santiye.id, [])
    assert yanit.status_code == 200, yanit.text
    assert await _kayitlar(seeded_db, santiye.id) == []


async def test_mevcut_hucre_kimligi_korunur_kod_guncellenir(
    client: AsyncClient, sef_headers, santiye, mehmet, admin_kullanicisi, hucre_fabrikasi, seeded_db
) -> None:
    """Aynı kişi-gün yeniden gönderilirse satır SİL-YENİDEN-YAZ edilmez.

    Kimlik korunmazsa her kaydetme `created_by`yi ve kaydın yaşını sıfırlardı;
    üstelik sil+ekle aynı transaction'da UQ yarışına açık olurdu.
    """
    eski = await hucre_fabrikasi(santiye, mehmet, gun(1), _C, admin_kullanicisi)
    eski_id = eski.id

    yanit = await _kaydet(client, sef_headers, santiye.id, [_hucre(mehmet, 1, _T)])
    assert yanit.status_code == 200, yanit.text

    (kayit,) = await _kayitlar(seeded_db, santiye.id)
    assert kayit.id == eski_id
    assert kayit.code is TimesheetCode.holiday


async def test_fm_saati_temizlenebilir(
    client: AsyncClient, sef_headers, santiye, mehmet, admin_kullanicisi, hucre_fabrikasi, seeded_db
) -> None:
    """Saat GÖNDERİLMEZSE eski saat kalmaz — hücre gövdedeki hâline eşitlenir."""
    await hucre_fabrikasi(
        santiye, mehmet, gun(1), _FM, admin_kullanicisi, overtime_hours=Decimal("4.0")
    )
    yanit = await _kaydet(client, sef_headers, santiye.id, [_hucre(mehmet, 1, _FM)])
    assert yanit.status_code == 200, yanit.text
    (kayit,) = await _kayitlar(seeded_db, santiye.id)
    assert kayit.overtime_hours is None


# --- KAPSAM SINIRI (kritik) ---


async def test_baska_ayin_hucresine_dokunulmaz(
    client: AsyncClient, sef_headers, santiye, mehmet, admin_kullanicisi, hucre_fabrikasi, seeded_db
) -> None:
    """Temmuz kaydetmesi HAZİRAN ve AĞUSTOS hücrelerini SİLMEZ."""
    from datetime import date as _date

    await hucre_fabrikasi(santiye, mehmet, _date(YIL, 6, 30), _C, admin_kullanicisi)
    await hucre_fabrikasi(santiye, mehmet, _date(YIL, 8, 1), _C, admin_kullanicisi)
    await hucre_fabrikasi(santiye, mehmet, gun(5), _C, admin_kullanicisi)

    yanit = await _kaydet(client, sef_headers, santiye.id, [])
    assert yanit.status_code == 200, yanit.text

    kalan_tarihler = sorted(k.work_date for k in await _kayitlar(seeded_db, santiye.id))
    assert kalan_tarihler == [_date(YIL, 6, 30), _date(YIL, 8, 1)]


async def test_baska_santiyenin_hucresine_dokunulmaz(
    client: AsyncClient,
    sef_headers,
    santiye,
    ikinci_santiye,
    mehmet,
    personel_fabrikasi,
    admin_kullanicisi,
    hucre_fabrikasi,
    seeded_db,
) -> None:
    """AYNI dönem, AYNI proje, BAŞKA şantiye — kapsam `site_id` ile kesilir."""
    komsu = await personel_fabrikasi("Osman Tan", trade="Kaynakçı")
    await hucre_fabrikasi(ikinci_santiye, komsu, gun(1), _C, admin_kullanicisi)
    await hucre_fabrikasi(santiye, mehmet, gun(1), _C, admin_kullanicisi)

    yanit = await _kaydet(client, sef_headers, santiye.id, [])
    assert yanit.status_code == 200, yanit.text

    assert await _kayitlar(seeded_db, santiye.id) == []
    assert len(await _kayitlar(seeded_db, ikinci_santiye.id)) == 1


# --- Kişi-gün tekliği (UQ) ---


async def test_baska_santiyede_kaydi_olan_personel_409(
    client: AsyncClient,
    sef_headers,
    santiye,
    ikinci_santiye,
    mehmet,
    admin_kullanicisi,
    hucre_fabrikasi,
    seeded_db,
) -> None:
    """UQ (personnel_id, work_date): kişi bir günde TEK yerdedir.

    `IntegrityError`a düşülüp "Veri bütünlüğü hatası" denmez — mesaj HANGİ
    personelin HANGİ günü çakıştığını söyler.
    """
    await hucre_fabrikasi(ikinci_santiye, mehmet, gun(3), _C, admin_kullanicisi)

    yanit = await _kaydet(client, sef_headers, santiye.id, [_hucre(mehmet, 3)])
    assert yanit.status_code == 409, yanit.text
    detay = yanit.json()["detail"]
    assert "Mehmet Yılmaz" in detay
    assert gun(3).isoformat() in detay


async def test_cakisma_kismi_yazma_birakmaz(
    client: AsyncClient,
    sef_headers,
    santiye,
    ikinci_santiye,
    mehmet,
    admin_kullanicisi,
    hucre_fabrikasi,
    seeded_db,
) -> None:
    """409 alan istek, gövdesindeki SAĞLAM hücreleri de yazmamalıdır."""
    await hucre_fabrikasi(ikinci_santiye, mehmet, gun(3), _C, admin_kullanicisi)

    yanit = await _kaydet(client, sef_headers, santiye.id, [_hucre(mehmet, 1), _hucre(mehmet, 3)])
    assert yanit.status_code == 409, yanit.text
    assert await _kayitlar(seeded_db, santiye.id) == []


async def test_govde_icinde_ayni_kisi_gun_409(
    client: AsyncClient, sef_headers, santiye, mehmet
) -> None:
    """Çift gövde satırı DB'ye hiç gitmeden yakalanır."""
    yanit = await _kaydet(
        client, sef_headers, santiye.id, [_hucre(mehmet, 1), _hucre(mehmet, 1, _T)]
    )
    assert yanit.status_code == 409, yanit.text
    assert yanit.json()["detail"] == guards.DUPLICATE_CELL


# --- Gövde doğrulaması ---


async def test_donem_disi_tarih_422(client: AsyncClient, sef_headers, santiye, mehmet) -> None:
    """Gövde dönem KAPSAMININ tam kümesidir; dönem dışı hücre sessizce yazılırsa
    ertesi ayın kaydetmesi onu silerdi (görünmez veri kaybı)."""
    from datetime import date as _date

    yanit = await _kaydet(
        client,
        sef_headers,
        santiye.id,
        [
            {
                "personnel_id": str(mehmet.id),
                "work_date": _date(YIL, 8, 1).isoformat(),
                "code": _C.value,
            }
        ],
    )
    assert yanit.status_code == 422, yanit.text
    assert guards.DATE_OUT_OF_PERIOD.split("{")[0] in yanit.json()["detail"]


async def test_fm_saati_yalniz_fm_kodunda_422(
    client: AsyncClient, sef_headers, santiye, mehmet
) -> None:
    """Saat, `overtime` DIŞINDA anlamsızdır (spec §7 S2): ŞP 119'un "128 saat"
    toplamı yalnız FM hücrelerinden gelir; çalışılan güne saat iliştirilirse
    toplam ya yalan söyler ya da girilen veri sessizce yok sayılırdı."""
    yanit = await _kaydet(
        client, sef_headers, santiye.id, [_hucre(mehmet, 1, _C, overtime_hours="3.0")]
    )
    assert yanit.status_code == 422, yanit.text
    assert yanit.json()["detail"] == guards.OVERTIME_HOURS_ONLY_FOR_OVERTIME


async def test_gecersiz_fm_saati_422(client: AsyncClient, sef_headers, santiye, mehmet) -> None:
    """DB CHECK (0 < saat <= 24) Pydantic katmanında da durur."""
    for saat in ("0", "24.5", "-1"):
        yanit = await _kaydet(
            client, sef_headers, santiye.id, [_hucre(mehmet, 1, _FM, overtime_hours=saat)]
        )
        assert yanit.status_code == 422, f"{saat}: {yanit.text}"


async def test_bilinmeyen_personel_422(client: AsyncClient, sef_headers, santiye) -> None:
    yanit = await _kaydet(
        client,
        sef_headers,
        santiye.id,
        [
            {
                "personnel_id": str(uuid.uuid4()),
                "work_date": gun(1).isoformat(),
                "code": _C.value,
            }
        ],
    )
    assert yanit.status_code == 422, yanit.text
    assert yanit.json()["detail"] == guards.PERSONNEL_UNKNOWN


async def test_baska_santiyenin_bolumu_422(
    client: AsyncClient, sef_headers, santiye, mehmet, yabanci_bolum
) -> None:
    """Bölüm hücrenin ŞANTİYESİNE ait olmalı (site_diary `SECTION_MISMATCH` deseni)."""
    yanit = await _kaydet(
        client, sef_headers, santiye.id, [_hucre(mehmet, 1, section_id=str(yabanci_bolum.id))]
    )
    assert yanit.status_code == 422, yanit.text
    assert yanit.json()["detail"] == guards.SECTION_MISMATCH


# --- Denetim ---


async def test_denetim_tek_donem_ozeti_olayi_yazar(
    client: AsyncClient, sef_headers, santiye, mehmet, ali, seeded_db
) -> None:
    """Hücre başına olay YAZILMAZ (spec §3): 31 gün × 48 işçi bir kaydetmede
    1488 denetim satırı üretir ve günlüğü kullanılamaz hâle getirirdi."""
    onceki = len((await seeded_db.execute(select(AuditLog))).scalars().all())

    yanit = await _kaydet(
        client,
        sef_headers,
        santiye.id,
        [_hucre(mehmet, 1), _hucre(mehmet, 2), _hucre(ali, 1)],
    )
    assert yanit.status_code == 200, yanit.text

    kayitlar = (await seeded_db.execute(select(AuditLog))).scalars().all()
    assert len(kayitlar) == onceki + 1
    detay = kayitlar[-1].detail
    assert "A-Blok Şantiyesi" in detay
    assert "2026-07" in detay
    assert "3 hücre" in detay


# --- İzin ---


async def test_saha_muhendisi_okur_yazamaz(
    client: AsyncClient, saha_headers, santiye, mehmet
) -> None:
    """`timesheet=_V` — matrisi GÖRÜR ama kaydedemez (403, spec §3)."""
    okuma = await client.get(
        f"/sites/{santiye.id}/timesheet",
        params={"year": YIL, "month": AY},
        headers=saha_headers,
    )
    assert okuma.status_code == 200, okuma.text

    yazma = await _kaydet(client, saha_headers, santiye.id, [_hucre(mehmet, 1)])
    assert yazma.status_code == 403, yazma.text


async def test_proje_muduru_okumada_da_403(client: AsyncClient, pm_headers, santiye) -> None:
    """`timesheet=_N` — kapı en dıştadır, kapsam sorgusuna hiç girilmez."""
    yanit = await client.get(
        f"/sites/{santiye.id}/timesheet",
        params={"year": YIL, "month": AY},
        headers=pm_headers,
    )
    assert yanit.status_code == 403, yanit.text


# --- IDOR ---


async def test_gorunmeyen_santiyeye_yazma_404(
    client: AsyncClient, sef_headers, gorunmeyen_santiye, mehmet, seeded_db
) -> None:
    """Kapsam dışı GERÇEK şantiye 403 değil 404; hiçbir şey de yazılmaz."""
    yanit = await _kaydet(client, sef_headers, gorunmeyen_santiye.id, [_hucre(mehmet, 1)])
    assert yanit.status_code == 404, yanit.text
    assert yanit.json()["detail"] == SITE_MISSING
    assert await _kayitlar(seeded_db, gorunmeyen_santiye.id) == []


async def test_var_olmayan_santiyeye_yazma_ayni_404(
    client: AsyncClient, sef_headers, mehmet
) -> None:
    yanit = await _kaydet(client, sef_headers, uuid.uuid4(), [_hucre(mehmet, 1)])
    assert yanit.status_code == 404, yanit.text
    assert yanit.json()["detail"] == SITE_MISSING
