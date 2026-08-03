"""T4 — `GET /sites/{site_id}/timesheet/export.xlsx` (spec §3).

Çıktı, T3 matrisinin AYNI türevlerini taşır: kişi satırları + gün sütunları +
kişi adam-günü + günlük alt toplam satırı + FM saat toplamı. Hesap `matrix.py`de
kalır, bu uç yalnız onu çalışma kitabına çevirir — iki farklı toplam mantığı
ekranla Excel'i ayrıştırırdı.

Kapı `timesheet:view`tir (indirme bir OKUMADIR): matrisi göremeyen indiremez,
gören indirebilir. Görünmeyen şantiye 404'tür (var olmayanla ayırt EDİLEMEZ).
"""

from decimal import Decimal
from io import BytesIO

import openpyxl
import pytest
from httpx import AsyncClient

from app.modules.timesheet.export import (
    COLUMN_HEADERS,
    DAY_TOTAL_LABEL,
    EMPTY_VALUE,
    HEADER_ROW,
    INFO_LABELS,
    SHEET_TITLE,
    XLSX_MEDIA_TYPE,
)
from app.modules.timesheet.models import TimesheetCode
from tests.timesheet.conftest import AY, YIL, gun

pytestmark = pytest.mark.asyncio

_C = TimesheetCode.worked
_I = TimesheetCode.leave
_T = TimesheetCode.holiday
_FM = TimesheetCode.overtime
_G = TimesheetCode.temporary_duty


async def _indir(client: AsyncClient, headers, site_id, **params):
    sorgu = {"year": YIL, "month": AY, **params}
    yanit = await client.get(
        f"/sites/{site_id}/timesheet/export.xlsx", params=sorgu, headers=headers
    )
    assert yanit.status_code == 200, yanit.text
    return yanit


def _sayfa(yanit):
    workbook = openpyxl.load_workbook(BytesIO(yanit.content))
    return workbook[SHEET_TITLE]


def _satir(sheet, row: int) -> list:
    return [sheet.cell(row=row, column=col).value for col in range(1, sheet.max_column + 1)]


def _kisi_satiri(sheet, ad: str) -> list:
    for row in range(HEADER_ROW + 1, sheet.max_row + 1):
        if sheet.cell(row=row, column=1).value == ad:
            return _satir(sheet, row)
    raise AssertionError(f"kişi satırı yok: {ad}")


@pytest.fixture
async def ornek_ay(hucre_fabrikasi, santiye, admin_kullanicisi, mehmet, ali, bolum):
    """İki kişi, ilk üç gün. Mehmet'in 2. günü FM'dir ve saati (3.5) GİRİLMİŞTİR;

    Ali'nin 3. günü `G`dir — alt toplam satırının "+" ve "G" işaretlerinin kaynağı.
    """
    await hucre_fabrikasi(santiye, mehmet, gun(1), _C, admin_kullanicisi, section=bolum)
    await hucre_fabrikasi(
        santiye,
        mehmet,
        gun(2),
        _FM,
        admin_kullanicisi,
        overtime_hours=Decimal("3.5"),
        section=bolum,
    )
    await hucre_fabrikasi(santiye, mehmet, gun(3), _T, admin_kullanicisi, section=bolum)
    await hucre_fabrikasi(santiye, ali, gun(1), _C, admin_kullanicisi, section=bolum)
    await hucre_fabrikasi(santiye, ali, gun(2), _I, admin_kullanicisi, section=bolum)
    await hucre_fabrikasi(santiye, ali, gun(3), _G, admin_kullanicisi, section=bolum)


# --- HTTP zarfı (boq/audit export deseni) ---


async def test_xlsx_content_type_ve_dosya_adi(client, admin_headers, santiye, ornek_ay):
    """`Content-Type` xlsx'tir ve dosya adı şantiye kodu + dönemden türer."""
    yanit = await _indir(client, admin_headers, santiye.id)

    assert yanit.headers["content-type"] == XLSX_MEDIA_TYPE
    disposition = yanit.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert f"puantaj-{santiye.code}-{YIL}-{AY:02d}.xlsx" in disposition


# --- İçerik: başlık şeridi (ŞP 116-119) ---


async def test_baslik_seridi_matrisin_turevleriyle_ayni(
    client, admin_headers, santiye, proje, bolum, ornek_ay
):
    """ŞP 117 bölüm · 118 işçi sayısı · 119 adam-gün + FM saat toplamı.

    Adam-gün 3'tür: Mehmet Ç+FM (2) + Ali Ç (1). `İ`, `T` ve `G` SAYILMAZ.
    """
    sheet = _sayfa(await _indir(client, admin_headers, santiye.id, section_id=str(bolum.id)))

    bilgi = {
        sheet.cell(row=i, column=1).value: sheet.cell(row=i, column=2).value
        for i in range(1, len(INFO_LABELS) + 1)
    }
    assert bilgi[INFO_LABELS[0]] == proje.name
    assert bilgi[INFO_LABELS[1]] == santiye.name
    assert bilgi[INFO_LABELS[2]] == f"{AY:02d}.{YIL}"
    assert bilgi[INFO_LABELS[3]] == bolum.name
    assert bilgi[INFO_LABELS[4]] == "2"
    assert bilgi[INFO_LABELS[5]] == "3"
    assert bilgi[INFO_LABELS[6]] == "3.5"


async def test_bolum_secilmemisse_serit_bolum_iddia_etmez(client, admin_headers, santiye, ornek_ay):
    sheet = _sayfa(await _indir(client, admin_headers, santiye.id))
    assert sheet.cell(row=4, column=1).value == INFO_LABELS[3]
    assert sheet.cell(row=4, column=2).value == EMPTY_VALUE


# --- İçerik: tablo ---


async def test_sutun_basliklari_kisi_alanlari_gunler_ve_toplam(
    client, admin_headers, santiye, ornek_ay
):
    """Sabit kişi sütunları + ayın TÜM günleri (Temmuz = 31) + "Toplam"."""
    sheet = _sayfa(await _indir(client, admin_headers, santiye.id))
    basliklar = _satir(sheet, HEADER_ROW)

    assert basliklar[: len(COLUMN_HEADERS)] == list(COLUMN_HEADERS)
    assert basliklar[len(COLUMN_HEADERS) : len(COLUMN_HEADERS) + 31] == [
        str(day) for day in range(1, 32)
    ]
    assert basliklar[-1] == "Toplam"


async def test_kisi_satiri_ad_meslek_tur_firma_kod_harfleri_ve_adam_gun(
    client, admin_headers, santiye, ornek_ay
):
    """ŞP 149-150 / 169-170: taşeron firma AYRI sütundur, meslekle birleştirilmez."""
    sheet = _sayfa(await _indir(client, admin_headers, santiye.id))

    mehmet_satir = _kisi_satiri(sheet, "Mehmet Yılmaz")
    assert mehmet_satir[:4] == ["Mehmet Yılmaz", "Kalıpçı Usta", "Şirket", EMPTY_VALUE]
    assert mehmet_satir[4:7] == ["Ç", "FM", "T"]
    assert mehmet_satir[7] is None  # kaydı olmayan gün BOŞ kalır
    assert mehmet_satir[-1] == "2"

    ali_satir = _kisi_satiri(sheet, "Ali Kaya")
    assert ali_satir[:4] == ["Ali Kaya", "Demir Ustası", "Taşeron", "Akın İnşaat"]
    assert ali_satir[4:7] == ["Ç", "İ", "G"]
    assert ali_satir[-1] == "1"


async def test_alt_toplam_satiri_gunluk_sayilar_arti_ve_g_isareti(
    client, admin_headers, santiye, ornek_ay
):
    """ŞP 237 "4+" (sütunda en az bir FM) · ŞP 245 "3G" (geçici görev sayıya girmez)."""
    sheet = _sayfa(await _indir(client, admin_headers, santiye.id))
    toplam = _kisi_satiri(sheet, DAY_TOTAL_LABEL)

    assert toplam[4] == "2"  # 1. gün: iki Ç
    assert toplam[5] == "1+"  # 2. gün: Mehmet FM (sayılır) + Ali İ; sütunda FM var
    assert toplam[6] == "0G"  # 3. gün: Mehmet T, Ali G — sayı 0, `G` ayrı işaret
    assert toplam[-1] == "3"


async def test_bolum_filtresi_ciktiyi_daraltir(
    client,
    admin_headers,
    santiye,
    admin_kullanicisi,
    hucre_fabrikasi,
    personel_fabrikasi,
    ikinci_bolum,
    ornek_ay,
):
    diger = await personel_fabrikasi("Veli Ak", trade="Sıvacı")
    await hucre_fabrikasi(santiye, diger, gun(1), _C, admin_kullanicisi, section=ikinci_bolum)

    sheet = _sayfa(await _indir(client, admin_headers, santiye.id, section_id=str(ikinci_bolum.id)))
    adlar = [
        sheet.cell(row=row, column=1).value for row in range(HEADER_ROW + 1, sheet.max_row + 1)
    ]
    assert adlar == ["Veli Ak", DAY_TOTAL_LABEL]


async def test_bos_donemde_gecerli_dosya_doner(client, admin_headers, santiye):
    """Kayıtsız ay boş dosya DEĞİL, başlıklı ve sıfır toplamlı bir çalışma kitabıdır."""
    sheet = _sayfa(await _indir(client, admin_headers, santiye.id, year=2030, month=2))

    assert _satir(sheet, HEADER_ROW)[: len(COLUMN_HEADERS)] == list(COLUMN_HEADERS)
    toplam = _kisi_satiri(sheet, DAY_TOTAL_LABEL)
    assert toplam[-1] == "0"
    assert len([c for c in _satir(sheet, HEADER_ROW) if c is not None]) == len(COLUMN_HEADERS) + 29


# --- İzin ve IDOR ---


async def test_saha_muhendisi_indirebilir(client, saha_headers, santiye, ornek_ay):
    """`timesheet:view` YETER: indirme bir okumadır, `full` istenmez (spec §3)."""
    yanit = await _indir(client, saha_headers, santiye.id)
    assert yanit.content


async def test_proje_muduru_403(client, pm_headers, santiye, ornek_ay):
    yanit = await client.get(
        f"/sites/{santiye.id}/timesheet/export.xlsx",
        params={"year": YIL, "month": AY},
        headers=pm_headers,
    )
    assert yanit.status_code == 403, yanit.text


async def test_gorunmeyen_santiye_404(client, sef_headers, gorunmeyen_santiye):
    """Görünmeyen projenin GERÇEK şantiyesi ile var olmayan kimlik AYIRT EDİLEMEZ."""
    yanit = await client.get(
        f"/sites/{gorunmeyen_santiye.id}/timesheet/export.xlsx",
        params={"year": YIL, "month": AY},
        headers=sef_headers,
    )
    assert yanit.status_code == 404, yanit.text


async def test_baska_santiyenin_bolumu_404(client, admin_headers, santiye, yabanci_bolum):
    yanit = await client.get(
        f"/sites/{santiye.id}/timesheet/export.xlsx",
        params={"year": YIL, "month": AY, "section_id": str(yabanci_bolum.id)},
        headers=admin_headers,
    )
    assert yanit.status_code == 404, yanit.text
