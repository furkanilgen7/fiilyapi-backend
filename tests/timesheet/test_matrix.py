"""T3 — `GET /sites/{site_id}/timesheet` matrisi ve TÜREV toplamları.

Her toplamın kaynağı mockup'tır ve testte SATIR NUMARASIYLA gerekçelenir
(WORKFLOW §3). Örnek veri, ŞP `Şantiye - Puantaj.dc.html` gövdesinin (148-227)
dört satırı ve 14 günüdür; beklenen sayılar oradan TÜRETİLİR.

Sabitlenen kurallar:
* **Adam-gün = `worked` + `overtime`.** E5 197-211 ayak satırı kanıtıdır:
  6. sütunda Mehmet FM (E5 122), diğer üçü Ç'dir ve toplam **4**'tür (E5 203) —
  FM'li gün çalışılmış SAYILIR. Aynısı 13. sütunda Ali'nin FM'i içindir (E5 149
  → E5 210 "4").
* **`temporary_duty` adam-güne GİRMEZ.** ŞP 245'te 13. sütun **"3G"**tir: o gün
  dört kişinin dördü de kayıtlıdır (Hasan `G` — ŞP 203) ama sayı 4 DEĞİL 3'tür.
  Sayı `G`'yi dışarıda bırakır, `G` ayrı bir işaret olarak gösterilir.
* **`+` işareti** ŞP 237 ("4+") — sütunda EN AZ BİR fazla mesai olduğunu söyler;
  sayının kendisi (4) değişmez.
* **FM saat toplamı YALNIZ girilmiş saatlerden** (spec §7 S2): saat opsiyoneldir,
  girilmemiş FM hücresi ŞP 119'un "128 saat" toplamına 0 katar.
"""

from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.modules.sites.guards import SITE_MISSING
from app.modules.timesheet.models import TimesheetCode
from tests.timesheet.conftest import AY, YIL, gun

pytestmark = pytest.mark.asyncio

_C = TimesheetCode.worked
_I = TimesheetCode.leave
_T = TimesheetCode.holiday
_FM = TimesheetCode.overtime
_G = TimesheetCode.temporary_duty

# ŞP 151-164 / 171-184 / 191-204 / 211-224 — dört satırın ilk 14 günü.
_SP_SATIRLARI = {
    "Mehmet Yılmaz": [_C, _C, _C, _T, _T, _FM, _C, _C, _I, _C, _T, _T, _C, _C],
    "Ali Kaya": [_C, _I, _I, _T, _T, _C, _C, _C, _C, _FM, _T, _T, _C, _C],
    "Hasan Çelik": [_C, _C, _C, _T, _T, _C, _C, _C, _C, _C, _T, _T, _G, _C],
    "Ayşe Demir": [_C, _C, _C, _T, _T, _C, _I, _C, _C, _C, _T, _T, _C, _C],
}


@pytest.fixture
async def sp_matrisi(
    hucre_fabrikasi, personel_fabrikasi, santiye, admin_kullanicisi, mehmet, ali, bolum
):
    """ŞP gövdesinin dört satırı; Mehmet'in 6. gün FM'ine 3.5 saat GİRİLİR,

    Ali'nin 10. gün FM'ine GİRİLMEZ — "yalnız girilenlerden toplanır" kuralının
    kanıtı (spec §7 S2).
    """
    hasan = await personel_fabrikasi("Hasan Çelik", trade="Elektrikçi")
    ayse = await personel_fabrikasi("Ayşe Demir", trade="Büro Şefi")
    kisiler = {"Mehmet Yılmaz": mehmet, "Ali Kaya": ali, "Hasan Çelik": hasan, "Ayşe Demir": ayse}

    for ad, kodlar in _SP_SATIRLARI.items():
        for index, kod in enumerate(kodlar, start=1):
            saat = Decimal("3.5") if (ad == "Mehmet Yılmaz" and index == 6) else None
            await hucre_fabrikasi(
                santiye,
                kisiler[ad],
                gun(index),
                kod,
                admin_kullanicisi,
                overtime_hours=saat,
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
    assert matris["total_man_days"] == 0
    assert len(matris["day_totals"]) == 31  # Ağustos
    assert all(gunluk["worked_count"] == 0 for gunluk in matris["day_totals"])


# --- Gün hücreleri ---


async def test_gun_hucreleri_kod_ve_fm_saati_tasir(
    client: AsyncClient, admin_headers, santiye, sp_matrisi, bolum
) -> None:
    """Hücre = kod + (varsa) saat + bölüm. ŞP 156 Mehmet'in 6. günü FM'dir."""
    matris = await _matris(client, admin_headers, santiye.id)
    hucreler = {c["work_date"]: c for c in _satir(matris, "Mehmet Yılmaz")["cells"]}

    assert hucreler[gun(1).isoformat()]["code"] == "worked"
    assert hucreler[gun(4).isoformat()]["code"] == "holiday"
    assert hucreler[gun(6).isoformat()]["code"] == "overtime"
    assert Decimal(hucreler[gun(6).isoformat()]["overtime_hours"]) == Decimal("3.5")
    assert hucreler[gun(1).isoformat()]["overtime_hours"] is None
    assert hucreler[gun(6).isoformat()]["section_id"] == str(bolum.id)
    # Girilmemiş gün hücre ÜRETMEZ (ŞP 165 "…" boş süz).
    assert gun(20).isoformat() not in hucreler


# --- Kişi bazında adam-gün (ŞP 166/186/206/226) ---


async def test_kisi_adam_gunu_calisti_ve_fm_sayar(
    client: AsyncClient, admin_headers, santiye, sp_matrisi
) -> None:
    """ŞP 166 "Toplam" sütunu. 14 günlük örnekte: Mehmet 9 (3 Ç + FM + 2 Ç + Ç + 2 Ç).

    İzin (İ) ve tatil (T) SAYILMAZ — ŞP 235-236'da tatil sütunlarının günlük
    toplamı 0'dır, yani T bir adam-gün değildir.
    """
    matris = await _matris(client, admin_headers, santiye.id)
    assert _satir(matris, "Mehmet Yılmaz")["man_days"] == 9
    assert _satir(matris, "Ali Kaya")["man_days"] == 8


async def test_gecici_gorev_kisi_adam_gunune_girmez(
    client: AsyncClient, admin_headers, santiye, sp_matrisi
) -> None:
    """Hasan 14 günde 9 Ç + 1 `G` yazar; adam-günü **9**'dur.

    ŞP 245: `G`'nin bulunduğu sütunun toplamı 4 değil "3G"dir — `G` sayıya
    KATILMAZ, ayrı işaretlenir.
    """
    matris = await _matris(client, admin_headers, santiye.id)
    assert _satir(matris, "Hasan Çelik")["man_days"] == 9


# --- Günlük (sütun) toplamlar (ŞP 230-248) ---


async def test_gunluk_sayilar_calisan_kisi_sayisidir(
    client: AsyncClient, admin_headers, santiye, sp_matrisi
) -> None:
    """ŞP 232-234: 1. gün 4, 2. gün 3, 3. gün 3 (İ sayılmaz); 235-236: tatil 0."""
    matris = await _matris(client, admin_headers, santiye.id)
    gunluk = {g["work_date"]: g for g in matris["day_totals"]}
    assert gunluk[gun(1).isoformat()]["worked_count"] == 4
    assert gunluk[gun(2).isoformat()]["worked_count"] == 3
    assert gunluk[gun(3).isoformat()]["worked_count"] == 3
    assert gunluk[gun(4).isoformat()]["worked_count"] == 0
    assert gunluk[gun(5).isoformat()]["worked_count"] == 0


async def test_fm_gunu_sayiya_katilir_ve_arti_ile_isaretlenir(
    client: AsyncClient, admin_headers, santiye, sp_matrisi
) -> None:
    """ŞP 237 "4+" · E5 203 "4": FM'li gün SAYILIR, üstüne `+` işareti konur."""
    matris = await _matris(client, admin_headers, santiye.id)
    gunluk = {g["work_date"]: g for g in matris["day_totals"]}

    altinci = gunluk[gun(6).isoformat()]
    assert altinci["worked_count"] == 4
    assert altinci["has_overtime"] is True

    onuncu = gunluk[gun(10).isoformat()]
    assert onuncu["worked_count"] == 4
    assert onuncu["has_overtime"] is True

    assert gunluk[gun(1).isoformat()]["has_overtime"] is False


async def test_gecici_gorev_sutunda_ayri_sayilir(
    client: AsyncClient, admin_headers, santiye, sp_matrisi
) -> None:
    """ŞP 245 "3G": 13. günde 3 çalışan + 1 geçici görev."""
    matris = await _matris(client, admin_headers, santiye.id)
    onucuncu = next(g for g in matris["day_totals"] if g["work_date"] == gun(13).isoformat())
    assert onucuncu["worked_count"] == 3
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


async def test_baslik_seridi_isci_sayisi_adam_gun_ve_fm_saati(
    client: AsyncClient, admin_headers, santiye, sp_matrisi, bolum
) -> None:
    """ŞP 117 bölüm adı · 118 "48 işçi" · 119 "864 adam/gün · 128 saat fazla mesai".

    Toplam adam-gün ŞP 248'in ("86") kaynağıyla AYNIDIR: kişi toplamlarının
    toplamı (22+20+23+21=86). Örnekte 9+8+9+9=35.
    """
    matris = await _matris(client, admin_headers, santiye.id, section_id=str(bolum.id))
    assert matris["section_name"] == "Kat 6–10 Kaba İnşaat"
    assert matris["worker_count"] == 4
    assert matris["total_man_days"] == 35
    assert sum(row["man_days"] for row in matris["rows"]) == matris["total_man_days"]


async def test_fm_saat_toplami_yalniz_girilenlerden(
    client: AsyncClient, admin_headers, santiye, sp_matrisi
) -> None:
    """İki FM hücresi var, saati girilmiş olan TEK (3.5) — toplam 3.5 (spec §7 S2)."""
    matris = await _matris(client, admin_headers, santiye.id)
    assert Decimal(matris["total_overtime_hours"]) == Decimal("3.5")


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
    await hucre_fabrikasi(santiye, diger, gun(1), _C, admin_kullanicisi, section=ikinci_bolum)

    hepsi = await _matris(client, admin_headers, santiye.id)
    assert len(hepsi["rows"]) == 5
    assert hepsi["worker_count"] == 5

    suzulmus = await _matris(client, admin_headers, santiye.id, section_id=str(ikinci_bolum.id))
    assert [row["full_name"] for row in suzulmus["rows"]] == ["Veli Ak"]
    assert suzulmus["total_man_days"] == 1
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
    await hucre_fabrikasi(ikinci_santiye, diger, gun(1), _C, admin_kullanicisi)
    matris = await _matris(client, admin_headers, santiye.id)
    assert "Osman Tan" not in [row["full_name"] for row in matris["rows"]]


async def test_baska_ayin_hucresi_matriste_gorunmez(
    client: AsyncClient, admin_headers, santiye, sp_matrisi, admin_kullanicisi, hucre_fabrikasi
) -> None:
    from datetime import date as _date

    mehmet = sp_matrisi["Mehmet Yılmaz"]
    await hucre_fabrikasi(santiye, mehmet, _date(YIL, 8, 3), _C, admin_kullanicisi)
    matris = await _matris(client, admin_headers, santiye.id)
    assert _satir(matris, "Mehmet Yılmaz")["man_days"] == 9


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
