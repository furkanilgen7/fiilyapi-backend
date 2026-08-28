"""`PUT /sites/{site_id}/timesheet/week` — HAFTALIK toplu DEĞİŞTİRME (PUAN-SAAT).

Mockup'ta tek bir **"Haftayı Kaydet"** düğmesi vardır (E5 76): ekran haftayı
BÜTÜN olarak kaydeder, hücre hücre kaydetmez. Bu yüzden gövde **hafta**+şantiye
kapsamının TAM kümesidir ve gönderilmeyen hücre SİLİNİR.

🔴 **Kapsam sınırı bu dosyanın en kritik bölümüdür.** Uç aylıktan haftalığa
geçerken silme koşulu ay kapsamında kalsaydı, **bir haftayı kaydetmek ayın geri
kalanını SİLERDİ**. Bu yüzden kapsam testi bir POZİTİF KONTROL taşır (aynı ayın
başka bir haftasındaki hücre HAYATTA KALMALI) — yalnız "gönderilmeyen silinir"
iddiası ölçülseydi, **her şeyi silen** bozuk bir uç da testi yeşil geçerdi.
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
from tests.timesheet.conftest import ISO_HAFTA, ISO_YIL, gun, hafta_gunu

pytestmark = pytest.mark.asyncio

_IZIN = TimesheetCode.leave
_TATIL = TimesheetCode.holiday


def _saat_hucresi(personnel, offset: int, hours: str = "9", **ekstra) -> dict:
    return {
        "personnel_id": str(personnel.id),
        "work_date": hafta_gunu(offset).isoformat(),
        "hours": hours,
        **ekstra,
    }


def _kod_hucresi(personnel, offset: int, code: TimesheetCode = _IZIN, **ekstra) -> dict:
    return {
        "personnel_id": str(personnel.id),
        "work_date": hafta_gunu(offset).isoformat(),
        "code": code.value,
        **ekstra,
    }


async def _kaydet(client: AsyncClient, headers, site_id, cells, *, yil=ISO_YIL, hafta=ISO_HAFTA):
    return await client.put(
        f"/sites/{site_id}/timesheet/week",
        params={"iso_year": yil, "iso_week": hafta},
        json={"cells": cells},
        headers=headers,
    )


async def _kayitlar(session: AsyncSession, site_id) -> list[TimesheetEntry]:
    stmt = select(TimesheetEntry).where(TimesheetEntry.site_id == site_id)
    return list((await session.execute(stmt)).scalars().all())


# --- Temel yazma ---


async def test_bos_haftaya_hucre_yazar(
    client: AsyncClient, sef_headers, santiye, mehmet, seeded_db
) -> None:
    yanit = await _kaydet(
        client, sef_headers, santiye.id, [_saat_hucresi(mehmet, 0), _saat_hucresi(mehmet, 1)]
    )
    assert yanit.status_code == 200, yanit.text

    govde = yanit.json()
    assert govde["worker_count"] == 1
    assert Decimal(govde["totals"]["total_hours"]) == Decimal("18.0")
    assert len(await _kayitlar(seeded_db, santiye.id)) == 2


async def test_yanit_guncel_haftadir(client: AsyncClient, sef_headers, santiye, mehmet) -> None:
    """Kaydet sonrası ekran yeniden çizilir; uç türev toplamları ANINDA döner."""
    yanit = await _kaydet(
        client,
        sef_headers,
        santiye.id,
        [
            _saat_hucresi(mehmet, 0, "9"),
            _saat_hucresi(mehmet, 1, "11"),
            _kod_hucresi(mehmet, 2, _TATIL),
        ],
    )
    hafta = yanit.json()
    satir = hafta["rows"][0]
    # 9 + 11 = 20 saat; gunluk 9 tavani 11'in 2 saatini FM'e atar.
    assert Decimal(satir["totals"]["normal_hours"]) == Decimal("18.0")
    assert Decimal(satir["totals"]["overtime_hours"]) == Decimal("2.0")
    assert Decimal(satir["totals"]["total_hours"]) == Decimal("20.0")


async def test_bolum_ve_proje_hucreye_yazilir(
    client: AsyncClient, sef_headers, santiye, mehmet, bolum, seeded_db
) -> None:
    """`project_id` gövdeden DEĞİL şantiyeden kopyalanır (kapsam süzgecinin alanı)."""
    yanit = await _kaydet(
        client, sef_headers, santiye.id, [_saat_hucresi(mehmet, 0, section_id=str(bolum.id))]
    )
    assert yanit.status_code == 200, yanit.text
    (kayit,) = await _kayitlar(seeded_db, santiye.id)
    assert kayit.section_id == bolum.id
    assert kayit.project_id == santiye.project_id


# --- DEĞİŞTİRME semantiği ---


async def test_gonderilmeyen_hucre_silinir(
    client: AsyncClient, sef_headers, santiye, mehmet, admin_kullanicisi, hucre_fabrikasi, seeded_db
) -> None:
    """⚠️ Gövde TAM kümedir: eski hücre gövdede yoksa SİLİNİR."""
    await hucre_fabrikasi(santiye, mehmet, hafta_gunu(0), admin_kullanicisi, hours=9)
    await hucre_fabrikasi(santiye, mehmet, hafta_gunu(1), admin_kullanicisi, hours=9)

    yanit = await _kaydet(client, sef_headers, santiye.id, [_saat_hucresi(mehmet, 0)])
    assert yanit.status_code == 200, yanit.text

    kalanlar = await _kayitlar(seeded_db, santiye.id)
    assert [k.work_date for k in kalanlar] == [hafta_gunu(0)]


async def test_bos_govde_haftayi_temizler(
    client: AsyncClient, sef_headers, santiye, mehmet, admin_kullanicisi, hucre_fabrikasi, seeded_db
) -> None:
    await hucre_fabrikasi(santiye, mehmet, hafta_gunu(0), admin_kullanicisi, hours=9)
    yanit = await _kaydet(client, sef_headers, santiye.id, [])
    assert yanit.status_code == 200, yanit.text
    assert await _kayitlar(seeded_db, santiye.id) == []


async def test_mevcut_hucre_kimligi_korunur_saat_koda_donusur(
    client: AsyncClient, sef_headers, santiye, mehmet, admin_kullanicisi, hucre_fabrikasi, seeded_db
) -> None:
    """Aynı kişi-gün yeniden gönderilirse satır SİL-YENİDEN-YAZ edilmez.

    Ayrıca hücre saatliden kodluya döndüğünde ESKİ SAAT NULL'a düşmelidir: hücre
    gövdedeki hâline eşitlenir. Düşmeseydi DB'nin saat-XOR-kod CHECK'i satırı
    reddederdi (500), ya da kısıt olmasaydı hücre hem 9 saat hem izin olurdu.
    """
    eski = await hucre_fabrikasi(santiye, mehmet, hafta_gunu(0), admin_kullanicisi, hours=9)
    eski_id = eski.id

    yanit = await _kaydet(client, sef_headers, santiye.id, [_kod_hucresi(mehmet, 0, _IZIN)])
    assert yanit.status_code == 200, yanit.text

    (kayit,) = await _kayitlar(seeded_db, santiye.id)
    assert kayit.id == eski_id
    assert kayit.code is TimesheetCode.leave
    assert kayit.hours is None


async def test_koddan_saate_donusumde_kod_temizlenir(
    client: AsyncClient, sef_headers, santiye, mehmet, admin_kullanicisi, hucre_fabrikasi, seeded_db
) -> None:
    """Ters yön: izinli gün çalışılmış güne döndüğünde KOD NULL'a düşer."""
    await hucre_fabrikasi(santiye, mehmet, hafta_gunu(0), admin_kullanicisi, code=_IZIN)
    yanit = await _kaydet(client, sef_headers, santiye.id, [_saat_hucresi(mehmet, 0, "7.5")])
    assert yanit.status_code == 200, yanit.text
    (kayit,) = await _kayitlar(seeded_db, santiye.id)
    assert kayit.code is None
    assert kayit.hours == Decimal("7.5")


# --- 🔴 KAPSAM SINIRI (bu dosyanın en kritik testi) ---


async def test_hafta_kaydetmek_ayin_diger_haftasina_DOKUNMAZ(
    client: AsyncClient, sef_headers, santiye, mehmet, admin_kullanicisi, hucre_fabrikasi, seeded_db
) -> None:
    """🔴 29. haftayı kaydetmek AYNI AYIN 28. ve 30. haftasını SİLMEZ.

    Silme koşulu ay kapsamında bırakılsaydı bu testin POZİTİF KONTROLÜ düşerdi:
    boş gövdeyle kaydeden istek ayın TAMAMINI süpürür ve `28`/`30` günleri de
    giderdi. Sadece "gönderilmeyen silinir" iddiası ölçülseydi o bozuk uç da
    yeşil geçerdi — bu yüzden burada üç sınır AYNI ANDA ölçülür:
      1) hafta İÇİ hücre silinir (negatif),
      2) aynı ayın BAŞKA haftalarındaki hücreler DURUR (pozitif kontrol),
      3) komşu ayların hücreleri DURUR.
    """
    from datetime import date as _date

    # 28. hafta (6-12 Tem) ve 30. hafta (20-26 Tem) — AYNI AY, BAŞKA hafta.
    await hucre_fabrikasi(santiye, mehmet, gun(8), admin_kullanicisi, hours=9)
    await hucre_fabrikasi(santiye, mehmet, gun(22), admin_kullanicisi, hours=9)
    # Komşu aylar.
    await hucre_fabrikasi(santiye, mehmet, _date(2026, 6, 30), admin_kullanicisi, hours=9)
    await hucre_fabrikasi(santiye, mehmet, _date(2026, 8, 3), admin_kullanicisi, hours=9)
    # 29. haftanın İÇİ — silinmesi beklenen.
    await hucre_fabrikasi(santiye, mehmet, hafta_gunu(2), admin_kullanicisi, hours=9)

    yanit = await _kaydet(client, sef_headers, santiye.id, [])
    assert yanit.status_code == 200, yanit.text

    kalan = sorted(k.work_date for k in await _kayitlar(seeded_db, santiye.id))
    assert kalan == [_date(2026, 6, 30), gun(8), gun(22), _date(2026, 8, 3)]


async def test_hafta_sinirlari_pazartesi_ve_pazari_KAPSAR(
    client: AsyncClient, sef_headers, santiye, mehmet, admin_kullanicisi, hucre_fabrikasi, seeded_db
) -> None:
    """Kapsamın UÇ günleri: 13 Tem (Pzt) ve 19 Tem (Paz) hafta İÇİDİR.

    Sınır bir gün içeri kaysaydı Pazartesi ya da Pazar hücresi "başka haftanın"
    sayılır ve kaydetme onu ne yazar ne silerdi — ekranda görünen ama
    kaydedilemeyen bir sütun doğardı.
    """
    await hucre_fabrikasi(santiye, mehmet, hafta_gunu(0), admin_kullanicisi, hours=9)
    await hucre_fabrikasi(santiye, mehmet, hafta_gunu(6), admin_kullanicisi, hours=9)

    yanit = await _kaydet(client, sef_headers, santiye.id, [])
    assert yanit.status_code == 200, yanit.text
    assert await _kayitlar(seeded_db, santiye.id) == []


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
    """AYNI hafta, AYNI proje, BAŞKA şantiye — kapsam `site_id` ile kesilir."""
    komsu = await personel_fabrikasi("Osman Tan", trade="Kaynakçı")
    await hucre_fabrikasi(ikinci_santiye, komsu, hafta_gunu(0), admin_kullanicisi, hours=9)
    await hucre_fabrikasi(santiye, mehmet, hafta_gunu(0), admin_kullanicisi, hours=9)

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
    await hucre_fabrikasi(ikinci_santiye, mehmet, hafta_gunu(2), admin_kullanicisi, hours=9)

    yanit = await _kaydet(client, sef_headers, santiye.id, [_saat_hucresi(mehmet, 2)])
    assert yanit.status_code == 409, yanit.text
    detay = yanit.json()["detail"]
    assert "Mehmet Yılmaz" in detay
    assert hafta_gunu(2).isoformat() in detay


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
    await hucre_fabrikasi(ikinci_santiye, mehmet, hafta_gunu(2), admin_kullanicisi, hours=9)

    yanit = await _kaydet(
        client, sef_headers, santiye.id, [_saat_hucresi(mehmet, 0), _saat_hucresi(mehmet, 2)]
    )
    assert yanit.status_code == 409, yanit.text
    assert await _kayitlar(seeded_db, santiye.id) == []


async def test_govde_icinde_ayni_kisi_gun_409(
    client: AsyncClient, sef_headers, santiye, mehmet
) -> None:
    """Çift gövde satırı DB'ye hiç gitmeden yakalanır."""
    yanit = await _kaydet(
        client, sef_headers, santiye.id, [_saat_hucresi(mehmet, 0), _kod_hucresi(mehmet, 0)]
    )
    assert yanit.status_code == 409, yanit.text
    assert yanit.json()["detail"] == guards.DUPLICATE_CELL


# --- Gövde doğrulaması ---


async def test_hafta_disi_tarih_422(client: AsyncClient, sef_headers, santiye, mehmet) -> None:
    """Gövde HAFTA kapsamının tam kümesidir; hafta dışı hücre sessizce yazılırsa
    ertesi haftanın kaydetmesi onu silerdi (görünmez veri kaybı)."""
    yanit = await _kaydet(
        client,
        sef_headers,
        santiye.id,
        [{"personnel_id": str(mehmet.id), "work_date": gun(22).isoformat(), "hours": "9"}],
    )
    assert yanit.status_code == 422, yanit.text
    assert guards.DATE_OUT_OF_WEEK.split("{")[0] in yanit.json()["detail"]


async def test_hem_saat_hem_kod_422(client: AsyncClient, sef_headers, santiye, mehmet) -> None:
    """🔴 Hücrenin sözleşmesi: TAM BİRİ dolu. İkisi birden bir günü hem çalışılmış
    hem izinli sayardı."""
    yanit = await _kaydet(
        client, sef_headers, santiye.id, [_saat_hucresi(mehmet, 0, code=_IZIN.value)]
    )
    assert yanit.status_code == 422, yanit.text


async def test_ne_saat_ne_kod_422(client: AsyncClient, sef_headers, santiye, mehmet) -> None:
    """Boş hücre "gün girildi ama hiçbir şey demiyor" olurdu."""
    yanit = await _kaydet(
        client,
        sef_headers,
        santiye.id,
        [{"personnel_id": str(mehmet.id), "work_date": hafta_gunu(0).isoformat()}],
    )
    assert yanit.status_code == 422, yanit.text


async def test_gecersiz_saat_422(client: AsyncClient, sef_headers, santiye, mehmet) -> None:
    """DB CHECK (0 < saat <= 24) Pydantic katmanında da durur."""
    for saat in ("0", "24.5", "-1"):
        yanit = await _kaydet(client, sef_headers, santiye.id, [_saat_hucresi(mehmet, 0, saat)])
        assert yanit.status_code == 422, f"{saat}: {yanit.text}"


async def test_kalkan_kodlar_reddedilir(client: AsyncClient, sef_headers, santiye, mehmet) -> None:
    """`worked` / `overtime` artık BİR KOD DEĞİLDİR — enum'da yoktur, gövdede 422.

    PG enum tipi o etiketleri hâlâ taşır (etiket silinemez); geri sızmalarını
    hem şema hem `ck_timesheet_entries_code_allowed` engeller.
    """
    for kalkan in ("worked", "overtime"):
        yanit = await _kaydet(
            client,
            sef_headers,
            santiye.id,
            [
                {
                    "personnel_id": str(mehmet.id),
                    "work_date": hafta_gunu(0).isoformat(),
                    "code": kalkan,
                }
            ],
        )
        assert yanit.status_code == 422, f"{kalkan}: {yanit.text}"


async def test_bilinmeyen_personel_422(client: AsyncClient, sef_headers, santiye) -> None:
    yanit = await _kaydet(
        client,
        sef_headers,
        santiye.id,
        [
            {
                "personnel_id": str(uuid.uuid4()),
                "work_date": hafta_gunu(0).isoformat(),
                "hours": "9",
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
        client,
        sef_headers,
        santiye.id,
        [_saat_hucresi(mehmet, 0, section_id=str(yabanci_bolum.id))],
    )
    assert yanit.status_code == 422, yanit.text
    assert yanit.json()["detail"] == guards.SECTION_MISMATCH


async def test_var_olmayan_iso_hafta_422(
    client: AsyncClient, sef_headers, santiye, mehmet
) -> None:
    """2027 ISO yılının 53. haftası YOKTUR; `fromisocalendar` ValueError atar.

    Yakalanmasaydı 500 olurdu — kullanıcının düzeltebileceği bir girdi hatası.
    """
    yanit = await _kaydet(client, sef_headers, santiye.id, [], yil=2027, hafta=53)
    assert yanit.status_code == 422, yanit.text
    assert "53" in yanit.json()["detail"]


# --- Denetim ---


async def test_denetim_tek_hafta_ozeti_olayi_yazar(
    client: AsyncClient, sef_headers, santiye, mehmet, ali, seeded_db
) -> None:
    """Hücre başına olay YAZILMAZ (spec §3): 7 gün × 48 işçi bir kaydetmede
    336 denetim satırı üretir ve günlüğü kullanılamaz hâle getirirdi."""
    onceki = len((await seeded_db.execute(select(AuditLog))).scalars().all())

    yanit = await _kaydet(
        client,
        sef_headers,
        santiye.id,
        [_saat_hucresi(mehmet, 0), _saat_hucresi(mehmet, 1), _saat_hucresi(ali, 0)],
    )
    assert yanit.status_code == 200, yanit.text

    kayitlar = (await seeded_db.execute(select(AuditLog))).scalars().all()
    assert len(kayitlar) == onceki + 1
    detay = kayitlar[-1].detail
    assert "A-Blok Şantiyesi" in detay
    assert "2026-W29" in detay
    # Hafta numarası TEK BAŞINA okunamaz; aralık da yazılır.
    assert "2026-07-13" in detay and "2026-07-19" in detay
    assert "3 hücre" in detay


# --- İzin ---


async def test_saha_muhendisi_okur_yazamaz(
    client: AsyncClient, saha_headers, santiye, mehmet
) -> None:
    """`timesheet=_V` — haftayı GÖRÜR ama kaydedemez (403, spec §3)."""
    okuma = await client.get(
        f"/sites/{santiye.id}/timesheet/week",
        params={"iso_year": ISO_YIL, "iso_week": ISO_HAFTA},
        headers=saha_headers,
    )
    assert okuma.status_code == 200, okuma.text

    yazma = await _kaydet(client, saha_headers, santiye.id, [_saat_hucresi(mehmet, 0)])
    assert yazma.status_code == 403, yazma.text


async def test_proje_muduru_okumada_da_403(client: AsyncClient, pm_headers, santiye) -> None:
    """`timesheet=_N` — kapı en dıştadır, kapsam sorgusuna hiç girilmez."""
    yanit = await client.get(
        f"/sites/{santiye.id}/timesheet/week",
        params={"iso_year": ISO_YIL, "iso_week": ISO_HAFTA},
        headers=pm_headers,
    )
    assert yanit.status_code == 403, yanit.text


# --- IDOR ---


async def test_gorunmeyen_santiyeye_yazma_404(
    client: AsyncClient, sef_headers, gorunmeyen_santiye, mehmet, seeded_db
) -> None:
    """Kapsam dışı GERÇEK şantiye 403 değil 404; hiçbir şey de yazılmaz."""
    yanit = await _kaydet(client, sef_headers, gorunmeyen_santiye.id, [_saat_hucresi(mehmet, 0)])
    assert yanit.status_code == 404, yanit.text
    assert yanit.json()["detail"] == SITE_MISSING
    assert await _kayitlar(seeded_db, gorunmeyen_santiye.id) == []


async def test_var_olmayan_santiyeye_yazma_ayni_404(
    client: AsyncClient, sef_headers, mehmet
) -> None:
    yanit = await _kaydet(client, sef_headers, uuid.uuid4(), [_saat_hucresi(mehmet, 0)])
    assert yanit.status_code == 404, yanit.text
    assert yanit.json()["detail"] == SITE_MISSING


async def test_aylik_yazma_ucu_ARTIK_YOKTUR(
    client: AsyncClient, sef_headers, santiye, mehmet
) -> None:
    """🔴 KIRICI DEĞİŞİKLİK bir TESTLE sabitlenir.

    Aylık `PUT` kaldırıldı; kalsaydı bir ay kaydetmek haftalık ekranın
    yazmadığı hücreleri süpüren İKİNCİ bir yazma yolu olurdu.
    """
    yanit = await client.put(
        f"/sites/{santiye.id}/timesheet",
        params={"year": 2026, "month": 7},
        json={"cells": []},
        headers=sef_headers,
    )
    assert yanit.status_code == 405, yanit.text
