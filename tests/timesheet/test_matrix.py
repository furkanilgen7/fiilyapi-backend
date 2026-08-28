"""T3 — `GET /sites/{site_id}/timesheet` matrisi ve TÜREV toplamları.

Her toplamın kaynağı mockup'tır ve testte SATIR NUMARASIYLA gerekçelenir
(WORKFLOW §3). Örnek veri, ŞP `Şantiye - Puantaj.dc.html` gövdesinin (148-227)
dört satırı ve 14 günüdür; beklenen sayılar oradan TÜRETİLİR.

Sabitlenen kurallar (PUAN-SAAT):
* **Aylık toplam = girilmiş SAATLERİN toplamı.** Kodlu hücre (izin/tatil/görev)
  0 katar.
* **Adam-gün = `toplam saat ÷ 9`** (E5 349-350: `588 ÷ 9 = 65,3`) — artık bir
  GÜN SAYISI değil bir TÜREVDİR ve ondalıklıdır.
* **Genel adam-gün satır adam-günlerinin TOPLAMI DEĞİLDİR:** aylık saatten bir
  kez türer, yoksa satır yuvarlamaları birikirdi.
* **`worked_day_count` saatli hücreleri sayar**, `temporary_duty_count` ayrıdır.

🔴 **Aylık uç artık YALNIZ OKUMADIR** (Excel/arşiv). Yazma haftalıktır ve
`test_week_save.py`dedir.
"""

from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.modules.sites.guards import SITE_MISSING
from app.modules.timesheet.models import TimesheetCode
from tests.timesheet.conftest import AY, YIL, gun

pytestmark = pytest.mark.asyncio

_I = TimesheetCode.leave
_T = TimesheetCode.holiday
_G = TimesheetCode.temporary_duty

#: Dört satırın ilk 14 günü — sayı = SAAT, enum = kod.
#: 6. gün Mehmet'te 12,5 saat (eski FM'in saat karşılığı), 10. gün Ali'de 11.
_SP_SATIRLARI: dict[str, list] = {
    "Mehmet Yılmaz": [9, 9, 9, _T, _T, 12.5, 9, 9, _I, 9, _T, _T, 9, 9],
    "Ali Kaya": [9, _I, _I, _T, _T, 9, 9, 9, 9, 11, _T, _T, 9, 9],
    "Hasan Çelik": [9, 9, 9, _T, _T, 9, 9, 9, 9, 9, _T, _T, _G, 9],
    "Ayşe Demir": [9, 9, 9, _T, _T, 9, _I, 9, 9, 9, _T, _T, 9, 9],
}


@pytest.fixture
async def sp_matrisi(
    hucre_fabrikasi, personel_fabrikasi, santiye, admin_kullanicisi, mehmet, ali, bolum
):
    """Dört satır × 14 gün. Saatler ve kodlar `_SP_SATIRLARI`den okunur."""
    hasan = await personel_fabrikasi("Hasan Çelik", trade="Elektrikçi")
    ayse = await personel_fabrikasi("Ayşe Demir", trade="Büro Şefi")
    kisiler = {"Mehmet Yılmaz": mehmet, "Ali Kaya": ali, "Hasan Çelik": hasan, "Ayşe Demir": ayse}

    for ad, gunler in _SP_SATIRLARI.items():
        for index, deger in enumerate(gunler, start=1):
            kodlu = isinstance(deger, TimesheetCode)
            await hucre_fabrikasi(
                santiye,
                kisiler[ad],
                gun(index),
                admin_kullanicisi,
                hours=None if kodlu else Decimal(str(deger)),
                code=deger if kodlu else None,
                section=bolum,
            )
    return kisiler


async def _matris(client: AsyncClient, headers, site_id, **params):
    sorgu = {"year": YIL, "month": AY, **params}
    yanit = await client.get(f"/sites/{site_id}/timesheet", params=sorgu, headers=headers)
    assert yanit.status_code == 200, yanit.text
    return yanit.json()


def _satir(matris: dict, ad: str) -> dict:
    return next(row for row in matris["rows"] if row["full_name"] == ad)


# --- Kişi listesi (ŞP 149-150, 169-170; E5 92-93) ---


async def test_kisi_listesi_ad_meslek_tur_ve_firma_tasir(
    client: AsyncClient, admin_headers, santiye, sp_matrisi
) -> None:
    """ŞP 149 ad + meslek, 150 "Şirket" rozeti; 169 "Demir Ustası — Akın İnşaat".

    Firma adı AYRI alandır: ŞP 169'daki tire birleştirmesi sunum kararıdır,
    backend meslek ile firmayı tek metne YAPIŞTIRMAZ.
    """
    matris = await _matris(client, admin_headers, santiye.id)

    mehmet_satir = _satir(matris, "Mehmet Yılmaz")
    assert mehmet_satir["trade"] == "Kalıpçı Usta"
    assert mehmet_satir["source"] == "company"
    assert mehmet_satir["subcontractor_name"] is None

    ali_satir = _satir(matris, "Ali Kaya")
    assert ali_satir["trade"] == "Demir Ustası"
    assert ali_satir["source"] == "subcontractor"
    assert ali_satir["subcontractor_name"] == "Akın İnşaat"


async def test_yalniz_donemde_kaydi_olan_personel_dondurulur(
    client: AsyncClient, admin_headers, santiye, sp_matrisi, personel_fabrikasi
) -> None:
    """Matris kartoteksin tamamı DEĞİL, o şantiye+dönemde kaydı olan kişilerdir.

    ŞP 118 "48 işçi" rozeti tablodaki satır sayısını anlatır; kartotekste var
    olup o ay o şantiyede çalışmamış kişi tabloda YOKTUR.
    """
    await personel_fabrikasi("Kayıtsız Kişi", trade="Boyacı")
    matris = await _matris(client, admin_headers, santiye.id)
    adlar = [row["full_name"] for row in matris["rows"]]
    assert "Kayıtsız Kişi" not in adlar
    assert len(adlar) == 4


async def test_bos_donem_bos_matris_dondurur(
    client: AsyncClient, admin_headers, santiye, sp_matrisi
) -> None:
    """Kaydı olmayan ay: satır YOK, ama gün iskeleti ve sıfır toplamlar DURUR.

    Mockup'ta boş durum ekranı yoktur; matris her zaman ay uzunluğunda bir
    sütun iskeleti gösterir (ŞP 127-141). Satır ekleme kartoteksten seçmedir
    (`GET /personnel`), bu uç kişi ÖNERMEZ.
    """
    matris = await _matris(client, admin_headers, santiye.id, month=8)
    assert matris["rows"] == []
    assert matris["worker_count"] == 0
    assert Decimal(matris["total_hours"]) == Decimal(0)
    assert Decimal(matris["total_man_days"]) == Decimal(0)
    assert len(matris["day_totals"]) == 31  # Ağustos
    assert all(gunluk["worked_day_count"] == 0 for gunluk in matris["day_totals"])


# --- Gün hücreleri ---


async def test_gun_hucreleri_saat_VEYA_kod_tasir(
    client: AsyncClient, admin_headers, santiye, sp_matrisi, bolum
) -> None:
    """Hücre = saat XOR kod (+ bölüm)."""
    matris = await _matris(client, admin_headers, santiye.id)
    hucreler = {c["work_date"]: c for c in _satir(matris, "Mehmet Yılmaz")["cells"]}

    assert Decimal(hucreler[gun(1).isoformat()]["hours"]) == Decimal("9")
    assert hucreler[gun(1).isoformat()]["code"] is None
    assert hucreler[gun(4).isoformat()]["code"] == "holiday"
    assert hucreler[gun(4).isoformat()]["hours"] is None
    assert Decimal(hucreler[gun(6).isoformat()]["hours"]) == Decimal("12.5")
    assert hucreler[gun(6).isoformat()]["section_id"] == str(bolum.id)
    # Girilmemiş gün hücre ÜRETMEZ.
    assert gun(20).isoformat() not in hucreler


# --- Kişi bazında adam-gün (ŞP 166/186/206/226) ---


async def test_kisi_toplam_saati_ve_TUREV_adam_gunu(
    client: AsyncClient, admin_headers, santiye, sp_matrisi
) -> None:
    """Mehmet: 8×9 + 12,5 = 84,5 saat -> 84,5/9 = 9,4 adam-gün.

    İzin (İ) ve tatil (T) saate 0 katar. 🔴 Adam-gün artık gün SAYMAZ: 9 saatlik
    dokuz gün ile 12,5 saatlik bir gün aynı sayıyı üretmez.
    """
    matris = await _matris(client, admin_headers, santiye.id)
    mehmet_satir = _satir(matris, "Mehmet Yılmaz")
    assert Decimal(mehmet_satir["total_hours"]) == Decimal("84.5")
    assert Decimal(mehmet_satir["man_days"]) == Decimal("9.4")

    ali_satir = _satir(matris, "Ali Kaya")
    # 7×9 + 11 = 74 saat -> 8,2 adam-gün.
    assert Decimal(ali_satir["total_hours"]) == Decimal("74")
    assert Decimal(ali_satir["man_days"]) == Decimal("8.2")


async def test_gecici_gorev_saate_ve_adam_gune_GIRMEZ(
    client: AsyncClient, admin_headers, santiye, sp_matrisi
) -> None:
    """Hasan 14 günde 9 çalışma günü + 1 `G` yazar; 81 saat, 9,0 adam-gün.

    `G` bir çalışma DEĞİLDİR: saate 0 katar ve ayrı sayaçta gösterilir.
    """
    matris = await _matris(client, admin_headers, santiye.id)
    hasan = _satir(matris, "Hasan Çelik")
    assert Decimal(hasan["total_hours"]) == Decimal("81")
    assert Decimal(hasan["man_days"]) == Decimal("9.0")


# --- Günlük (sütun) toplamlar (ŞP 230-248) ---


async def test_gunluk_sayilar_calisan_kisi_sayisidir(
    client: AsyncClient, admin_headers, santiye, sp_matrisi
) -> None:
    """1. gün 4 kişi, 2-3. gün 3 (İ sayılmaz); tatil günlerinde 0 ve 0 saat."""
    matris = await _matris(client, admin_headers, santiye.id)
    gunluk = {g["work_date"]: g for g in matris["day_totals"]}
    assert gunluk[gun(1).isoformat()]["worked_day_count"] == 4
    assert Decimal(gunluk[gun(1).isoformat()]["total_hours"]) == Decimal("36")
    assert gunluk[gun(2).isoformat()]["worked_day_count"] == 3
    assert gunluk[gun(3).isoformat()]["worked_day_count"] == 3
    assert gunluk[gun(4).isoformat()]["worked_day_count"] == 0
    assert Decimal(gunluk[gun(4).isoformat()]["total_hours"]) == Decimal("0")
    assert gunluk[gun(5).isoformat()]["worked_day_count"] == 0


async def test_uzun_gun_sutun_SAATINE_yansir(
    client: AsyncClient, admin_headers, santiye, sp_matrisi
) -> None:
    """🔴 `has_overtime` bayrağı KALKTI: FM haftalık bir türevdir, bir GÜN
    sütununda hesaplanamaz (haftalık 45 tavanı o sütunda bilinmez).

    Gün sütununda görünen tek şey SAATTİR: 6. gün 3×9 + 12,5 = 39,5.
    """
    matris = await _matris(client, admin_headers, santiye.id)
    gunluk = {g["work_date"]: g for g in matris["day_totals"]}

    assert Decimal(gunluk[gun(6).isoformat()]["total_hours"]) == Decimal("39.5")
    assert gunluk[gun(6).isoformat()]["worked_day_count"] == 4
    assert "has_overtime" not in gunluk[gun(6).isoformat()]


async def test_gecici_gorev_sutunda_ayri_sayilir(
    client: AsyncClient, admin_headers, santiye, sp_matrisi
) -> None:
    """13. günde 3 çalışan + 1 geçici görev."""
    matris = await _matris(client, admin_headers, santiye.id)
    onucuncu = next(g for g in matris["day_totals"] if g["work_date"] == gun(13).isoformat())
    assert onucuncu["worked_day_count"] == 3
    assert onucuncu["temporary_duty_count"] == 1
    assert (
        next(g for g in matris["day_totals"] if g["work_date"] == gun(1).isoformat())[
            "temporary_duty_count"
        ]
        == 0
    )


async def test_gun_iskeleti_ayin_tamamini_kapsar(
    client: AsyncClient, admin_headers, santiye, sp_matrisi
) -> None:
    """ŞP 127-141 gün başlıkları takvim günleridir; kaydı olmayan gün de sütundur."""
    matris = await _matris(client, admin_headers, santiye.id)
    assert len(matris["day_totals"]) == 31  # Temmuz
    assert matris["day_totals"][0]["work_date"] == gun(1).isoformat()
    assert matris["day_totals"][-1]["work_date"] == gun(31).isoformat()


# --- Başlık şeridi (ŞP 116-119) ---


async def test_baslik_seridi_isci_sayisi_saat_ve_adam_gun(
    client: AsyncClient, admin_headers, santiye, sp_matrisi, bolum
) -> None:
    """Toplam saat = 84,5 + 74 + 81 + 81 = 320,5 -> 320,5/9 = 35,6 adam-gün."""
    matris = await _matris(client, admin_headers, santiye.id, section_id=str(bolum.id))
    assert matris["section_name"] == "Kat 6–10 Kaba İnşaat"
    assert matris["worker_count"] == 4
    assert Decimal(matris["total_hours"]) == Decimal("320.5")
    assert Decimal(matris["total_man_days"]) == Decimal("35.6")


async def test_genel_adam_gun_SATIRLARDAN_TOPLANMAZ(
    client: AsyncClient, admin_headers, santiye, sp_matrisi
) -> None:
    """🔴 Yuvarlama biriktirme bekçisi.

    Satır adam-günleri 9,4 + 8,2 + 9,0 + 9,0 = 35,6… bu örnekte tesadüfen
    eşit çıkabilir; asıl iddia toplamın SAATTEN türediğidir: `total_man_days`
    her zaman `total_hours / 9`a eşittir.
    """
    matris = await _matris(client, admin_headers, santiye.id)
    beklenen = (Decimal(matris["total_hours"]) / Decimal(9)).quantize(Decimal("0.1"))
    assert Decimal(matris["total_man_days"]) == beklenen


async def test_bolum_secilmemisse_serit_bolumsuzdur(
    client: AsyncClient, admin_headers, santiye, sp_matrisi
) -> None:
    """ "Tüm Bölümler" (ŞP 99) seçiliyken şerit bir bölüm adı İDDİA ETMEZ."""
    matris = await _matris(client, admin_headers, santiye.id)
    assert matris["section_id"] is None
    assert matris["section_name"] is None
    assert matris["site_name"] == "A-Blok Şantiyesi"
    assert matris["project_name"] == "Güneşkent Konut"


# --- Bölüm filtresi (ŞP 99) ---


async def test_bolum_filtresi_yalniz_o_bolumun_hucrelerini_dondurur(
    client: AsyncClient,
    admin_headers,
    santiye,
    admin_kullanicisi,
    hucre_fabrikasi,
    personel_fabrikasi,
    bolum,
    ikinci_bolum,
    sp_matrisi,
) -> None:
    """İkinci bölümün işçisi, birinci bölüm süzgecinde GÖRÜNMEZ."""
    diger = await personel_fabrikasi("Veli Ak", trade="Sıvacı")
    await hucre_fabrikasi(santiye, diger, gun(1), admin_kullanicisi, hours=9, section=ikinci_bolum)

    hepsi = await _matris(client, admin_headers, santiye.id)
    assert len(hepsi["rows"]) == 5
    assert hepsi["worker_count"] == 5

    suzulmus = await _matris(client, admin_headers, santiye.id, section_id=str(ikinci_bolum.id))
    assert [row["full_name"] for row in suzulmus["rows"]] == ["Veli Ak"]
    assert Decimal(suzulmus["total_hours"]) == Decimal("9")
    assert Decimal(suzulmus["total_man_days"]) == Decimal("1.0")
    assert suzulmus["section_name"] == "Kat 1–5 Kaba İnşaat"


async def test_baska_santiyenin_bolumu_404(
    client: AsyncClient, admin_headers, santiye, yabanci_bolum, sp_matrisi
) -> None:
    """Bölüm bu şantiyeye ait değilse boş matris DEĞİL 404 — sessiz boş sonuç,
    kullanıcıya "o bölümde kimse çalışmamış" YALANINI söylerdi."""
    yanit = await client.get(
        f"/sites/{santiye.id}/timesheet",
        params={"year": YIL, "month": AY, "section_id": str(yabanci_bolum.id)},
        headers=admin_headers,
    )
    assert yanit.status_code == 404, yanit.text


# --- Kapsam: başka şantiye / başka ay sızmaz ---


async def test_baska_santiyenin_hucresi_matriste_gorunmez(
    client: AsyncClient,
    admin_headers,
    santiye,
    ikinci_santiye,
    admin_kullanicisi,
    hucre_fabrikasi,
    personel_fabrikasi,
    sp_matrisi,
) -> None:
    diger = await personel_fabrikasi("Osman Tan", trade="Kaynakçı")
    await hucre_fabrikasi(ikinci_santiye, diger, gun(1), admin_kullanicisi, hours=9)
    matris = await _matris(client, admin_headers, santiye.id)
    assert "Osman Tan" not in [row["full_name"] for row in matris["rows"]]


async def test_baska_ayin_hucresi_matriste_gorunmez(
    client: AsyncClient, admin_headers, santiye, sp_matrisi, admin_kullanicisi, hucre_fabrikasi
) -> None:
    from datetime import date as _date

    mehmet = sp_matrisi["Mehmet Yılmaz"]
    await hucre_fabrikasi(santiye, mehmet, _date(YIL, 8, 3), admin_kullanicisi, hours=9)
    matris = await _matris(client, admin_headers, santiye.id)
    assert Decimal(_satir(matris, "Mehmet Yılmaz")["total_hours"]) == Decimal("84.5")


# --- Dönem parametresi ---


async def test_donem_zorunludur(client: AsyncClient, admin_headers, santiye) -> None:
    """Dönemsiz matris anlamsızdır (ŞP 96 ay seçici her zaman doludur)."""
    yanit = await client.get(f"/sites/{santiye.id}/timesheet", headers=admin_headers)
    assert yanit.status_code == 422, yanit.text


async def test_gecersiz_ay_422(client: AsyncClient, admin_headers, santiye) -> None:
    yanit = await client.get(
        f"/sites/{santiye.id}/timesheet",
        params={"year": YIL, "month": 13},
        headers=admin_headers,
    )
    assert yanit.status_code == 422, yanit.text


# --- IDOR ---


async def test_gorunmeyen_santiye_404(client: AsyncClient, sef_headers, gorunmeyen_santiye) -> None:
    """`visible_projects` dışındaki GERÇEK şantiye 403 değil 404 döner."""
    yanit = await client.get(
        f"/sites/{gorunmeyen_santiye.id}/timesheet",
        params={"year": YIL, "month": AY},
        headers=sef_headers,
    )
    assert yanit.status_code == 404, yanit.text
    assert yanit.json()["detail"] == SITE_MISSING


async def test_var_olmayan_santiye_ayni_404(client: AsyncClient, sef_headers) -> None:
    """Görünmeyen kayıt ile var olmayan kimlik AYIRT EDİLEMEZ (WORKFLOW §4)."""
    import uuid as _uuid

    yanit = await client.get(
        f"/sites/{_uuid.uuid4()}/timesheet",
        params={"year": YIL, "month": AY},
        headers=sef_headers,
    )
    assert yanit.status_code == 404, yanit.text
    assert yanit.json()["detail"] == SITE_MISSING
