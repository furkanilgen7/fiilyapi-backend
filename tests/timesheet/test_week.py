"""`GET /sites/{site_id}/timesheet/week` — E5 haftalık ekranı ve TÜREVLERİ.

Fikstür, mockup `Ekran 5 - Puantaj.dc.html` (`5f3a944`) ızgarasının DÖRT
SATIRIDIR (E5 230-313) ve beklenen sayılar mockup'ın KENDİ kolonlarından alınır
(E5 244-247 · 266-269 · 288-291 · 310-313) — hesabın "kendi çıktısına" değil
mockup'a bağlanması için.

⚠️ **MOCKUP KUSURU (ölçüldü, rapor edildi):** Ayşe'nin Pazar hücresi mockup'ta
BOŞ basılmıştır (E5 309 `placeholder="—"`) ama satırın kolonları `45 / 7 / 52`
der ve tfoot `171 / 27 / 198` ile KPI kartları (E5 182/187/192) o rakamlarla
tutar. Izgaradan okunan hâl (47 saat, FM 2) ile satır/tfoot çelişir. Çelişen tek
şey BOŞ HÜCREDİR: eksik 5 saat konursa on bir sayının on biri de tutar. Bu
yüzden fikstüre **Pazar = 5** konur ve mockup'ın Pazar sütun toplamı (E5 326
"8") ile hafta toplamı (E5 330 "198") arasındaki 5 saatlik fark böyle kapanır.
"""

from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.modules.timesheet.models import TimesheetCode
from tests.timesheet.conftest import ISO_HAFTA, ISO_YIL, gun, hafta_gunu

pytestmark = pytest.mark.asyncio

_IZIN = TimesheetCode.leave
_GOREV = TimesheetCode.temporary_duty

#: E5 236-242 / 258-264 / 280-286 / 302-308 — Pzt…Paz.
#: `None` = hücre YOK (E5 242 "—"), enum = kod rozeti, sayı = saat.
E5_IZGARASI: dict[str, list] = {
    "Mehmet Yılmaz": [9, 11, 9, 9, 9, 6, None],
    "Ali Kaya": [9, _IZIN, _IZIN, 9, 12, 9, None],
    "Hasan Çelik": [9, 9, _GOREV, 9, 10, 9, 8],
    # 🔴 Pazar = 5: mockup'ta boş, ama satır/tfoot/KPI o 5 saatle tutuyor.
    "Ayşe Demir": [9, 9, 9, 4, 9, 7, 5],
}

#: E5 244-247 / 266-269 / 288-291 / 310-313 — Normal · FM · Toplam.
E5_SATIR_KOLONLARI: dict[str, tuple[str, str, str]] = {
    "Mehmet Yılmaz": ("45", "8", "53"),
    "Ali Kaya": ("36", "3", "39"),
    "Hasan Çelik": ("45", "9", "54"),
    "Ayşe Demir": ("45", "7", "52"),
}


@pytest.fixture
async def e5_haftasi(
    hucre_fabrikasi, personel_fabrikasi, santiye, admin_kullanicisi, mehmet, ali, bolum
):
    hasan = await personel_fabrikasi("Hasan Çelik", trade="Elektrikçi")
    ayse = await personel_fabrikasi("Ayşe Demir", trade="Büro Şefi")
    kisiler = {"Mehmet Yılmaz": mehmet, "Ali Kaya": ali, "Hasan Çelik": hasan, "Ayşe Demir": ayse}

    for ad, gunler in E5_IZGARASI.items():
        for offset, deger in enumerate(gunler):
            if deger is None:
                continue
            await hucre_fabrikasi(
                santiye,
                kisiler[ad],
                hafta_gunu(offset),
                admin_kullanicisi,
                hours=deger if isinstance(deger, int) else None,
                code=deger if isinstance(deger, TimesheetCode) else None,
                section=bolum,
            )
    return kisiler


async def _hafta(client: AsyncClient, headers, site_id, **params):
    sorgu = {"iso_year": ISO_YIL, "iso_week": ISO_HAFTA, **params}
    yanit = await client.get(f"/sites/{site_id}/timesheet/week", params=sorgu, headers=headers)
    assert yanit.status_code == 200, yanit.text
    return yanit.json()


def _satir(hafta: dict, ad: str) -> dict:
    return next(row for row in hafta["rows"] if row["full_name"] == ad)


# --- 🔴 FM kuralı: mockup'ın dört satırı ---


@pytest.mark.parametrize("ad", list(E5_SATIR_KOLONLARI))
async def test_satir_normal_fm_toplam_mockupla_BIREBIR(
    client: AsyncClient, admin_headers, santiye, e5_haftasi, ad
) -> None:
    """`normal = min(Σ min(saat,9), 45)` · `FM = toplam − normal`.

    Kuralın bileşik olduğunun kanıtı fikstürün İÇİNDEDİR:
    * Ali'nin haftası **39 saattir** (45'in altında) ve FM'i **3**tür — saf
      haftalık kural 0 verirdi;
    * Mehmet'in FM'i **8**dir — saf günlük kural (yalnız 9 üstü) 2 verirdi.
    """
    hafta = await _hafta(client, admin_headers, santiye.id)
    beklenen = E5_SATIR_KOLONLARI[ad]
    totals = _satir(hafta, ad)["totals"]
    assert (
        Decimal(totals["normal_hours"]),
        Decimal(totals["overtime_hours"]),
        Decimal(totals["total_hours"]),
    ) == tuple(Decimal(x) for x in beklenen)


async def test_tfoot_toplami_SATIRLARDAN_toplanir(
    client: AsyncClient, admin_headers, santiye, e5_haftasi
) -> None:
    """E5 328-330 "171 · 27 · 198" ve E5 182/187/192 KPI kartları.

    🔴 Havuz kuralı YANLIŞ olurdu: 45 saatlik tavan KİŞİ BAŞINADIR. Tüm saatler
    tek havuzda toplanıp `week_totals`a verilseydi normal 45 çıkardı, 171 değil.
    """
    hafta = await _hafta(client, admin_headers, santiye.id)
    assert Decimal(hafta["totals"]["normal_hours"]) == Decimal("171")
    assert Decimal(hafta["totals"]["overtime_hours"]) == Decimal("27")
    assert Decimal(hafta["totals"]["total_hours"]) == Decimal("198")
    assert hafta["worker_count"] == 4


async def test_gunluk_sutun_toplamlari(
    client: AsyncClient, admin_headers, santiye, e5_haftasi
) -> None:
    """E5 320-326 "36 · 29 · 18 · 31 · 40 · 31 · (13)".

    ⚠️ Son sütun mockup'ta **8** yazar; Ayşe'nin eksik hücresiyle tutarlıdır ama
    mockup'ın KENDİ hafta toplamı (198) ile tutmaz — düzeltilmiş ızgarada 13'tür.
    """
    hafta = await _hafta(client, admin_headers, santiye.id)
    gunluk = [Decimal(g["total_hours"]) for g in hafta["day_totals"]]
    assert gunluk == [Decimal(x) for x in (36, 29, 18, 31, 40, 31, 13)]
    assert sum(gunluk) == Decimal(198)


async def test_gun_iskeleti_YEDI_gundur(
    client: AsyncClient, admin_headers, santiye, e5_haftasi
) -> None:
    """E5 216-223: Pzt…Paz. Kaydı olmayan gün de bir SÜTUNDUR."""
    hafta = await _hafta(client, admin_headers, santiye.id)
    assert [g["work_date"] for g in hafta["day_totals"]] == [
        hafta_gunu(i).isoformat() for i in range(7)
    ]
    assert hafta["start_date"] == "2026-07-13"
    assert hafta["end_date"] == "2026-07-19"


# --- Hücreler ---


async def test_hucre_saat_VEYA_kod_tasir(
    client: AsyncClient, admin_headers, santiye, e5_haftasi, bolum
) -> None:
    hafta = await _hafta(client, admin_headers, santiye.id)
    hucreler = {c["work_date"]: c for c in _satir(hafta, "Ali Kaya")["cells"]}

    calisma = hucreler[hafta_gunu(0).isoformat()]
    assert Decimal(calisma["hours"]) == Decimal("9")
    assert calisma["code"] is None
    assert calisma["section_id"] == str(bolum.id)

    izin = hucreler[hafta_gunu(1).isoformat()]
    assert izin["hours"] is None
    assert izin["code"] == "leave"

    # Girilmemiş gün hücre ÜRETMEZ (E5 264 "—").
    assert hafta_gunu(6).isoformat() not in hucreler


async def test_izin_ve_gorev_AYRI_sayilir(
    client: AsyncClient, admin_headers, santiye, e5_haftasi
) -> None:
    """⚠️ E5 191-194 kartı "İzin · 27 saat · 3 gün" der ve o 3'e Hasan'ın GÖREV
    gününü de katar (2 izin + 1 görev). Backend uydurma toplama YAPMAZ: iki
    sayaç ayrı yayınlanır, birleştirme kararı ekranındır."""
    hafta = await _hafta(client, admin_headers, santiye.id)
    assert hafta["leave_day_count"] == 2
    assert hafta["temporary_duty_day_count"] == 1


async def test_gecici_gorev_saate_SIFIR_katar(
    client: AsyncClient, admin_headers, santiye, e5_haftasi
) -> None:
    """Hasan'ın Çarşamba'sı `Görev`tir; o günün sütun toplamı 18'dir (9+9)."""
    hafta = await _hafta(client, admin_headers, santiye.id)
    carsamba = hafta["day_totals"][2]
    assert Decimal(carsamba["total_hours"]) == Decimal("18")
    assert carsamba["worked_day_count"] == 2
    assert carsamba["temporary_duty_count"] == 1


# --- Başlık sabitleri ---


async def test_ekran_sabitleri_UCTAN_yayinlanir(
    client: AsyncClient, admin_headers, santiye, e5_haftasi
) -> None:
    """E5 71: "Normal gün 9 saat · Haftalık normal 45 saat". İstemci bu iki sayıyı
    kendi yazsaydı, FM'i sunucudan farklı hesaplayan bir ekran doğardı."""
    hafta = await _hafta(client, admin_headers, santiye.id)
    assert Decimal(hafta["normal_day_hours"]) == Decimal("9")
    assert Decimal(hafta["weekly_normal_hours"]) == Decimal("45")


# --- Ay şeridi (E5 137-176) ---


async def test_ay_seridi_ayla_kesisen_BES_haftayi_verir(
    client: AsyncClient, admin_headers, santiye, e5_haftasi
) -> None:
    """E5 143-168: Temmuz 2026 için "27. … 31. Hafta" — 27. hafta 29 Haziran'da başlar."""
    hafta = await _hafta(client, admin_headers, santiye.id)
    assert hafta["month_year"] == 2026
    assert hafta["month_month"] == 7
    assert [w["iso_week"] for w in hafta["month_weeks"]] == [27, 28, 29, 30, 31]
    assert hafta["month_weeks"][0]["start_date"] == "2026-06-29"
    assert hafta["month_weeks"][-1]["end_date"] == "2026-08-02"


async def test_girilmemis_hafta_ROZETI_sifir_saatten_AYRIDIR(
    client: AsyncClient,
    admin_headers,
    santiye,
    e5_haftasi,
    mehmet,
    admin_kullanicisi,
    hucre_fabrikasi,
) -> None:
    """E5 163 "girilmedi" rozeti `total_hours == 0` DEĞİLDİR.

    Hepsi izinli geçmiş bir hafta GİRİLMİŞTİR ve 0 saattir; ikisini
    ayırmayan bir ekran, girilmiş bir haftayı "unutuldu" diye gösterirdi.
    """
    # 30. hafta (20-26 Tem): tek hücre, İZİN -> girilmiş ama 0 saat.
    await hucre_fabrikasi(santiye, mehmet, gun(22), admin_kullanicisi, code=_IZIN)

    hafta = await _hafta(client, admin_headers, santiye.id)
    kutular = {w["iso_week"]: w for w in hafta["month_weeks"]}

    assert kutular[30]["has_entries"] is True
    assert Decimal(kutular[30]["total_hours"]) == Decimal("0")
    assert kutular[31]["has_entries"] is False


async def test_ay_toplami_ve_ADAM_GUN_turevi(
    client: AsyncClient, admin_headers, santiye, e5_haftasi
) -> None:
    """E5 347-350: "588 saat · 65,3 adam/gün" — adam-gün `saat ÷ 9` TÜREVİDİR.

    Fikstürde yalnız 29. hafta doludur: 198 saat -> 198/9 = 22,0 adam-gün.
    """
    hafta = await _hafta(client, admin_headers, santiye.id)
    assert Decimal(hafta["month_total_hours"]) == Decimal("198")
    assert Decimal(hafta["month_man_days"]) == Decimal("22.0")


async def test_ay_seridi_KOMSU_ayin_gununu_de_sayar(
    client: AsyncClient,
    admin_headers,
    santiye,
    e5_haftasi,
    mehmet,
    admin_kullanicisi,
    hucre_fabrikasi,
) -> None:
    """27. hafta 29 HAZİRAN'da başlar ve mockup onu "186 sa" ile Temmuz şeridinde
    gösterir. Şerit takvim ayını değil ayla KESİŞEN haftaları kapsar."""
    from datetime import date as _date

    await hucre_fabrikasi(santiye, mehmet, _date(2026, 6, 30), admin_kullanicisi, hours=9)

    hafta = await _hafta(client, admin_headers, santiye.id)
    kutular = {w["iso_week"]: w for w in hafta["month_weeks"]}
    assert Decimal(kutular[27]["total_hours"]) == Decimal("9")
    assert Decimal(hafta["month_total_hours"]) == Decimal("207")


# --- Bölüm süzgeci / kapsam ---


async def test_bolum_suzgeci_hafta_ucunda_da_calisir(
    client: AsyncClient,
    admin_headers,
    santiye,
    e5_haftasi,
    ikinci_bolum,
    personel_fabrikasi,
    admin_kullanicisi,
    hucre_fabrikasi,
) -> None:
    diger = await personel_fabrikasi("Veli Ak", trade="Sıvacı")
    await hucre_fabrikasi(
        santiye, diger, hafta_gunu(0), admin_kullanicisi, hours=8, section=ikinci_bolum
    )

    suzulmus = await _hafta(client, admin_headers, santiye.id, section_id=str(ikinci_bolum.id))
    assert [r["full_name"] for r in suzulmus["rows"]] == ["Veli Ak"]
    assert Decimal(suzulmus["totals"]["total_hours"]) == Decimal("8")
    assert suzulmus["section_name"] == "Kat 1–5 Kaba İnşaat"


async def test_baska_santiyenin_bolumu_404(
    client: AsyncClient, admin_headers, santiye, yabanci_bolum, e5_haftasi
) -> None:
    yanit = await client.get(
        f"/sites/{santiye.id}/timesheet/week",
        params={"iso_year": ISO_YIL, "iso_week": ISO_HAFTA, "section_id": str(yabanci_bolum.id)},
        headers=admin_headers,
    )
    assert yanit.status_code == 404, yanit.text


async def test_baska_haftanin_hucresi_gorunmez(
    client: AsyncClient,
    admin_headers,
    santiye,
    e5_haftasi,
    mehmet,
    admin_kullanicisi,
    hucre_fabrikasi,
) -> None:
    """30. haftanın hücresi 29. haftanın ızgarasına SIZMAZ."""
    await hucre_fabrikasi(santiye, mehmet, gun(22), admin_kullanicisi, hours=9)
    hafta = await _hafta(client, admin_headers, santiye.id)
    assert Decimal(hafta["totals"]["total_hours"]) == Decimal("198")


async def test_hafta_parametresi_zorunludur(client: AsyncClient, admin_headers, santiye) -> None:
    yanit = await client.get(f"/sites/{santiye.id}/timesheet/week", headers=admin_headers)
    assert yanit.status_code == 422, yanit.text
