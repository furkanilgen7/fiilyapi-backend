"""T4 — `GET /sites/{site_id}/diary/summary?year&month` (spec §3 agregasyon; plan T4).

Hakediş Özeti ekranının (`projedesign/Şantiye - Hakediş Özeti.dc.html`) veri
kaynağı. Alanların mockup gerekçesi:

| Alan                     | Mockup satırı                                        |
|--------------------------|------------------------------------------------------|
| `code`/`description`     | HÖ L131 "İş Kalemi" sütunu                           |
| `boq_quantity`/`…amount` | HÖ L132 "Sözleşme" sütunu (GK L226 "Sözleşme:        |
|                          | 1.200 m³ · Birim fiyat: ₺1.850")                     |
| `quantity`/`amount`      | HÖ L133 "Bu Ay" sütunu                               |
| `completion_ratio`       | HÖ L134 "%" sütunu (GK L229 "900 / 1.200" = %75)     |
| `total_amount`           | HÖ L165-168 tfoot "Bu Ay Toplam ₺269.200"            |
| `contract_item_*`        | plan T4 "`contract_item` köprü alanları" (T5 tüketir)|

## İKİ kural burada testle SABİTLENİR

1. **YALNIZ `submitted` sayılır** (spec §3): taslak bir gün özete GİRMEZ.
2. **Kümülatifle TUTARLILIK**: aynı senaryoda `summary`nin poz miktarı ile T3'ün
   `cumulative_quantity` türevi AYNI sayıdır — ikisi de `submitted` süzgecini
   kullanır, ikinci bir toplama kuralı YOKTUR.
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.modules.site_diary import guards
from app.modules.site_diary.models import DiaryStatus, SiteDiaryEntry, SiteDiaryLine

pytestmark = pytest.mark.asyncio


async def _olustur(client: AsyncClient, headers: dict[str, str], site_id, tarih: date) -> dict:
    yanit = await client.post(
        f"/sites/{site_id}/diary", json={"entry_date": tarih.isoformat()}, headers=headers
    )
    assert yanit.status_code == 201, yanit.text
    return yanit.json()


async def _gun(
    client: AsyncClient,
    headers: dict[str, str],
    site_id,
    tarih: date,
    satirlar: list[dict],
    *,
    gonder: bool,
) -> dict:
    kayit = await _olustur(client, headers, site_id, tarih)
    yanit = await client.put(
        f"/diary/{kayit['id']}/lines", json={"lines": satirlar}, headers=headers
    )
    assert yanit.status_code == 200, yanit.text
    govde = yanit.json()
    if gonder:
        gonderim = await client.post(f"/diary/{kayit['id']}/submit", headers=headers)
        assert gonderim.status_code == 200, gonderim.text
        govde = gonderim.json()
    return govde


async def _ozet(client: AsyncClient, headers: dict[str, str], site_id, **params):
    return await client.get(f"/sites/{site_id}/diary/summary", params=params, headers=headers)


def _kalem(govde: dict, boq_item_id) -> dict | None:
    return next((i for i in govde["items"] if i["boq_item_id"] == str(boq_item_id)), None)


# --- Yalnız `submitted` ---


async def test_taslak_gun_ozete_GIRMEZ(
    client: AsyncClient, admin_headers: dict[str, str], santiye
) -> None:
    """Kritik kural (spec §3): taslak bir gün hakediş özetine SIZAMAZ."""
    site, _, items = santiye
    kalem = sorted(items, key=lambda i: i.code)[0]
    await _gun(
        client,
        admin_headers,
        site.id,
        date(2026, 7, 10),
        [{"boq_item_id": str(kalem.id), "quantity": "10"}],
        gonder=True,
    )
    await _gun(
        client,
        admin_headers,
        site.id,
        date(2026, 7, 12),
        [{"boq_item_id": str(kalem.id), "quantity": "5"}],
        gonder=False,
    )

    ozet = (await _ozet(client, admin_headers, site.id, year=2026, month=7)).json()
    satir = _kalem(ozet, kalem.id)
    assert Decimal(satir["quantity"]) == Decimal("10")
    assert ozet["entry_count"] == 1


async def test_hic_gonderilmemisse_sifirli_ozet(
    client: AsyncClient, admin_headers: dict[str, str], santiye
) -> None:
    """Boş küme 404 DEĞİL sıfırlı özettir (zarif düşüş): kaydı olmayan şantiye de
    ekranı açabilmelidir."""
    site, _, items = santiye
    await _gun(
        client,
        admin_headers,
        site.id,
        date(2026, 7, 10),
        [{"boq_item_id": str(items[0].id), "quantity": "10"}],
        gonder=False,
    )
    ozet = (await _ozet(client, admin_headers, site.id, year=2026, month=7)).json()
    assert ozet["items"] == []
    assert ozet["entry_count"] == 0
    assert Decimal(ozet["total_amount"]) == Decimal("0")


async def test_reopen_edilen_gun_ozetten_DUSER(
    client: AsyncClient, admin_headers: dict[str, str], santiye
) -> None:
    """Durum akışıyla agregasyon TEK kaynaktan beslenir: geri alınan gün artık
    hakedişe sayılmaz."""
    site, _, items = santiye
    kalem = sorted(items, key=lambda i: i.code)[0]
    govde = await _gun(
        client,
        admin_headers,
        site.id,
        date(2026, 7, 10),
        [{"boq_item_id": str(kalem.id), "quantity": "10"}],
        gonder=True,
    )
    assert (await client.post(f"/diary/{govde['id']}/reopen", headers=admin_headers)).status_code

    ozet = (await _ozet(client, admin_headers, site.id, year=2026, month=7)).json()
    assert ozet["items"] == []
    assert ozet["entry_count"] == 0


# --- Poz bazlı toplama ---


async def test_poz_bazli_toplama_ve_toplam_tutar(
    client: AsyncClient, admin_headers: dict[str, str], santiye
) -> None:
    """HÖ L133 "Bu Ay" sütunu + L165-168 "Bu Ay Toplam" tfoot'u."""
    site, _, items = santiye
    a, b = sorted(items, key=lambda i: i.code)
    await _gun(
        client,
        admin_headers,
        site.id,
        date(2026, 7, 10),
        [
            {"boq_item_id": str(a.id), "quantity": "2.000"},
            {"boq_item_id": str(b.id), "quantity": "1.000"},
        ],
        gonder=True,
    )
    await _gun(
        client,
        admin_headers,
        site.id,
        date(2026, 7, 11),
        [{"boq_item_id": str(a.id), "quantity": "3.500"}],
        gonder=True,
    )

    ozet = (await _ozet(client, admin_headers, site.id, year=2026, month=7)).json()
    assert ozet["entry_count"] == 2
    a_satir = _kalem(ozet, a.id)
    b_satir = _kalem(ozet, b.id)
    assert Decimal(a_satir["quantity"]) == Decimal("5.500")
    assert Decimal(b_satir["quantity"]) == Decimal("1.000")

    beklenen_a = (a.unit_price * Decimal("5.5")).quantize(Decimal("0.01"))
    beklenen_b = (b.unit_price * Decimal("1")).quantize(Decimal("0.01"))
    assert Decimal(a_satir["amount"]) == beklenen_a
    assert Decimal(b_satir["amount"]) == beklenen_b
    assert Decimal(ozet["total_amount"]) == beklenen_a + beklenen_b


async def test_kalemler_koda_gore_siralanir(
    client: AsyncClient, admin_headers: dict[str, str], santiye
) -> None:
    """Satır listesi (`SiteDiaryLine.code`) ile özet AYNI sırayı gösterir."""
    site, _, items = santiye
    a, b = sorted(items, key=lambda i: i.code)
    await _gun(
        client,
        admin_headers,
        site.id,
        date(2026, 7, 10),
        [
            {"boq_item_id": str(b.id), "quantity": "1"},
            {"boq_item_id": str(a.id), "quantity": "1"},
        ],
        gonder=True,
    )
    ozet = (await _ozet(client, admin_headers, site.id, year=2026, month=7)).json()
    assert [i["code"] for i in ozet["items"]] == [a.code, b.code]


async def test_sifir_miktarli_poz_ozette_GORUNUR(
    client: AsyncClient, admin_headers: dict[str, str], santiye
) -> None:
    """BOQ iskeleti tüm pozları açar; o ay dokunulmayan poz `0` ile durur —
    ekranın "Sözleşme" ve "%" sütunları o satır için de doludur."""
    site, _, items = santiye
    a, b = sorted(items, key=lambda i: i.code)
    await _gun(
        client,
        admin_headers,
        site.id,
        date(2026, 7, 10),
        [
            {"boq_item_id": str(a.id), "quantity": "2"},
            {"boq_item_id": str(b.id), "quantity": "0"},
        ],
        gonder=True,
    )
    ozet = (await _ozet(client, admin_headers, site.id, year=2026, month=7)).json()
    assert Decimal(_kalem(ozet, b.id)["quantity"]) == Decimal("0")
    assert Decimal(_kalem(ozet, b.id)["amount"]) == Decimal("0")


async def test_baska_ay_ve_baska_santiye_karismaz(
    client: AsyncClient, admin_headers: dict[str, str], santiye, santiye_fabrikasi
) -> None:
    site, proje, items = santiye
    kalem = sorted(items, key=lambda i: i.code)[0]
    komsu_site, _, komsu_items = await santiye_fabrikasi("SD-K2", project=proje)

    await _gun(
        client,
        admin_headers,
        site.id,
        date(2026, 6, 30),
        [{"boq_item_id": str(kalem.id), "quantity": "100"}],
        gonder=True,
    )
    await _gun(
        client,
        admin_headers,
        site.id,
        date(2026, 7, 10),
        [{"boq_item_id": str(kalem.id), "quantity": "7"}],
        gonder=True,
    )
    await _gun(
        client,
        admin_headers,
        komsu_site.id,
        date(2026, 7, 10),
        [{"boq_item_id": str(sorted(komsu_items, key=lambda i: i.code)[0].id), "quantity": "40"}],
        gonder=True,
    )

    ozet = (await _ozet(client, admin_headers, site.id, year=2026, month=7)).json()
    assert len(ozet["items"]) == 1
    assert Decimal(_kalem(ozet, kalem.id)["quantity"]) == Decimal("7")


async def test_ay_verilmezse_TUM_YIL(
    client: AsyncClient, admin_headers: dict[str, str], santiye
) -> None:
    """`year` tek başına anlamlıdır (T2 liste ucuyla aynı kural): yılın tamamı."""
    site, _, items = santiye
    kalem = sorted(items, key=lambda i: i.code)[0]
    await _gun(
        client,
        admin_headers,
        site.id,
        date(2026, 6, 30),
        [{"boq_item_id": str(kalem.id), "quantity": "100"}],
        gonder=True,
    )
    await _gun(
        client,
        admin_headers,
        site.id,
        date(2026, 7, 10),
        [{"boq_item_id": str(kalem.id), "quantity": "7"}],
        gonder=True,
    )
    ozet = (await _ozet(client, admin_headers, site.id, year=2026)).json()
    assert Decimal(_kalem(ozet, kalem.id)["quantity"]) == Decimal("107")


# --- Kümülatif ↔ summary tutarlılığı ---


async def test_summary_T3_kumulatifiyle_AYNI_SAYIYI_soyler(
    client: AsyncClient, admin_headers: dict[str, str], santiye
) -> None:
    """İki ekran aynı sayıyı söylemek ZORUNDADIR (T3 dosya docstring'i).

    Senaryo: 10'u gönderilmiş (10), 12'si TASLAK (5), 15'i gönderilmiş (3).
    Ayın son gönderilmiş kaydının `cumulative_quantity` türevi = 13; özetin
    poz miktarı da 13 olmalıdır — taslak hiçbirine girmez.
    """
    site, _, items = santiye
    kalem = sorted(items, key=lambda i: i.code)[0]
    await _gun(
        client,
        admin_headers,
        site.id,
        date(2026, 7, 10),
        [{"boq_item_id": str(kalem.id), "quantity": "10"}],
        gonder=True,
    )
    await _gun(
        client,
        admin_headers,
        site.id,
        date(2026, 7, 12),
        [{"boq_item_id": str(kalem.id), "quantity": "5"}],
        gonder=False,
    )
    son = await _gun(
        client,
        admin_headers,
        site.id,
        date(2026, 7, 15),
        [{"boq_item_id": str(kalem.id), "quantity": "3"}],
        gonder=True,
    )

    kumulatif = Decimal(
        next(s for s in son["lines"] if s["boq_item_id"] == str(kalem.id))["cumulative_quantity"]
    )
    ozet = (await _ozet(client, admin_headers, site.id, year=2026, month=7)).json()
    assert kumulatif == Decimal("13")
    assert Decimal(_kalem(ozet, kalem.id)["quantity"]) == kumulatif


async def test_santiye_suzgeci_POZ_SAHIPLIGINDEN_BAGIMSIZ_korur(
    client: AsyncClient,
    admin_headers: dict[str, str],
    santiye,
    santiye_fabrikasi,
    seeded_db,
    admin_kullanicisi,
) -> None:
    """İKİNCİ SAVUNMA KATMANI: hem `summary` hem T3 kümülatifi `site_id` süzgeci
    taşır. Normalde poz sahipliği (`lines._resolve`) zaten komşu şantiyenin
    satırını engeller — bu test o katman DELİNMİŞ gibi davranır: başka şantiyenin
    kaydına, BU şantiyenin pozuna işaret eden bir satır DOĞRUDAN DB'ye yazılır.

    Süzgeç kaldırılırsa iki sayı da (kümülatif + özet) komşu şantiyenin miktarını
    yutar; test bunu yakalar.
    """
    site, project, items = santiye
    kalem = sorted(items, key=lambda i: i.code)[0]
    komsu_site, _, _ = await santiye_fabrikasi("SD-SZ", project=project)

    sizinti = SiteDiaryEntry(
        site_id=komsu_site.id,
        project_id=komsu_site.project_id,
        entry_date=date(2026, 7, 10),
        status=DiaryStatus.submitted,
        created_by=admin_kullanicisi.id,
    )
    sizinti.lines.append(
        SiteDiaryLine(
            boq_item_id=kalem.id,
            code=kalem.code,
            description=kalem.description,
            unit=kalem.unit,
            unit_price=kalem.unit_price,
            quantity=Decimal("999.000"),
        )
    )
    seeded_db.add(sizinti)
    await seeded_db.flush()

    bugun = await _gun(
        client,
        admin_headers,
        site.id,
        date(2026, 7, 15),
        [{"boq_item_id": str(kalem.id), "quantity": "2"}],
        gonder=True,
    )
    kumulatif = Decimal(
        next(s for s in bugun["lines"] if s["boq_item_id"] == str(kalem.id))["cumulative_quantity"]
    )
    ozet = (await _ozet(client, admin_headers, site.id, year=2026, month=7)).json()
    assert kumulatif == Decimal("2")
    assert Decimal(_kalem(ozet, kalem.id)["quantity"]) == Decimal("2")


async def test_amount_SNAPSHOT_fiyatindan_hesaplanir(
    client: AsyncClient, admin_headers: dict[str, str], santiye, seeded_db
) -> None:
    """Satır ₺'si o günkü DONMUŞ fiyattan gelir (T3 `line_amount` ile TEK kopya):
    BOQ fiyatı sonradan değişse bile geçmiş ayın hakedişi yeniden yazılmaz."""
    site, _, items = santiye
    kalem = sorted(items, key=lambda i: i.code)[0]
    eski_fiyat = kalem.unit_price
    await _gun(
        client,
        admin_headers,
        site.id,
        date(2026, 7, 10),
        [{"boq_item_id": str(kalem.id), "quantity": "2"}],
        gonder=True,
    )

    kalem.unit_price = eski_fiyat * 2
    await seeded_db.flush()

    ozet = (await _ozet(client, admin_headers, site.id, year=2026, month=7)).json()
    assert Decimal(_kalem(ozet, kalem.id)["amount"]) == (eski_fiyat * Decimal("2")).quantize(
        Decimal("0.01")
    )


async def test_bagi_kopmus_satir_ozete_GIRMEZ(
    client: AsyncClient, admin_headers: dict[str, str], santiye, seeded_db
) -> None:
    """Pozu silinmiş satır (`boq_item_id IS NULL`, FK `SET NULL`) hangi poza
    yazılacağını KAYBETMİŞTİR; `cumulative_quantities_before` ile AYNI kural
    gereği toplamdan düşer — başka bir pozun sayısına sessizce eklenmez."""
    site, _, items = santiye
    a, b = sorted(items, key=lambda i: i.code)
    await _gun(
        client,
        admin_headers,
        site.id,
        date(2026, 7, 10),
        [
            {"boq_item_id": str(a.id), "quantity": "2"},
            {"boq_item_id": str(b.id), "quantity": "3"},
        ],
        gonder=True,
    )
    await seeded_db.delete(b)
    await seeded_db.flush()

    ozet = (await _ozet(client, admin_headers, site.id, year=2026, month=7)).json()
    assert [i["boq_item_id"] for i in ozet["items"]] == [str(a.id)]
    assert Decimal(ozet["total_amount"]) == (a.unit_price * Decimal("2")).quantize(Decimal("0.01"))


# --- `contract_item` köprüsü + "Sözleşme" sütunu ---


async def test_sozlesme_sutunu_BOQ_kaleminden_gelir(
    client: AsyncClient, admin_headers: dict[str, str], santiye
) -> None:
    """HÖ L132 "Sözleşme" = BOQ kaleminin miktarı × birim fiyatı (GK L226)."""
    site, _, items = santiye
    kalem = sorted(items, key=lambda i: i.code)[0]
    await _gun(
        client,
        admin_headers,
        site.id,
        date(2026, 7, 10),
        [{"boq_item_id": str(kalem.id), "quantity": "2"}],
        gonder=True,
    )
    satir = _kalem(
        (await _ozet(client, admin_headers, site.id, year=2026, month=7)).json(), kalem.id
    )
    assert Decimal(satir["boq_quantity"]) == kalem.quantity
    assert Decimal(satir["boq_amount"]) == (kalem.quantity * kalem.unit_price).quantize(
        Decimal("0.01")
    )


async def test_completion_ratio_bu_ay_bolu_sozlesme(
    client: AsyncClient, admin_headers: dict[str, str], santiye_fabrikasi, proje
) -> None:
    """HÖ L134 "%" sütunu — GK L229'daki "900 / 1.200" oranının birebiri."""
    site, _, items = await santiye_fabrikasi(
        "SD-R", project=proje, item_specs=[("01.001", Decimal("1200.000"), Decimal("1850.00"))]
    )
    kalem = items[0]
    await _gun(
        client,
        admin_headers,
        site.id,
        date(2026, 7, 10),
        [{"boq_item_id": str(kalem.id), "quantity": "900"}],
        gonder=True,
    )
    satir = _kalem(
        (await _ozet(client, admin_headers, site.id, year=2026, month=7)).json(), kalem.id
    )
    assert Decimal(satir["completion_ratio"]) == Decimal("0.7500")


async def test_contract_item_koprusu_dolar(
    client: AsyncClient, admin_headers: dict[str, str], santiye, sozlesme_kalemi_fabrikasi
) -> None:
    """Plan T4: sözleşme/kümülatif kolonları `boq_items.contract_item_id`
    köprüsünden beslenir — T5 "günlükten doldur" önerisi de bunu tüketecektir."""
    site, proje, items = santiye
    a, b = sorted(items, key=lambda i: i.code)
    sozlesme_kalemi = await sozlesme_kalemi_fabrikasi(a, proje)

    await _gun(
        client,
        admin_headers,
        site.id,
        date(2026, 7, 10),
        [
            {"boq_item_id": str(a.id), "quantity": "2"},
            {"boq_item_id": str(b.id), "quantity": "1"},
        ],
        gonder=True,
    )
    ozet = (await _ozet(client, admin_headers, site.id, year=2026, month=7)).json()

    kopru = _kalem(ozet, a.id)
    assert kopru["contract_item_id"] == str(sozlesme_kalemi.id)
    assert Decimal(kopru["contract_item_quantity"]) == sozlesme_kalemi.quantity
    assert Decimal(kopru["contract_item_unit_price"]) == sozlesme_kalemi.unit_price

    # Köprüsüz poz (şantiyenin kendi girdiği kalem) SESSİZCE düşmez, alanları NULL'dur.
    koprusuz = _kalem(ozet, b.id)
    assert koprusuz["contract_item_id"] is None
    assert koprusuz["contract_item_quantity"] is None


# --- Süzgeç doğrulaması (T2 liste ucuyla TUTARLI) ---


async def test_ay_tek_basina_422(
    client: AsyncClient, admin_headers: dict[str, str], santiye
) -> None:
    site, _, _ = santiye
    yanit = await _ozet(client, admin_headers, site.id, month=7)
    assert yanit.status_code == 422, yanit.text
    assert guards.YEAR_REQUIRED_FOR_MONTH in yanit.text


async def test_gecersiz_ay_422(client: AsyncClient, admin_headers: dict[str, str], santiye) -> None:
    site, _, _ = santiye
    assert (await _ozet(client, admin_headers, site.id, year=2026, month=13)).status_code == 422


async def test_suzgecsiz_ozet_tum_kayitlari_sayar(
    client: AsyncClient, admin_headers: dict[str, str], santiye
) -> None:
    """`year` de isteğe bağlıdır (T2 listesiyle aynı): süzgeçsiz özet tüm dönemi kapsar."""
    site, _, items = santiye
    kalem = sorted(items, key=lambda i: i.code)[0]
    await _gun(
        client,
        admin_headers,
        site.id,
        date(2025, 12, 31),
        [{"boq_item_id": str(kalem.id), "quantity": "4"}],
        gonder=True,
    )
    await _gun(
        client,
        admin_headers,
        site.id,
        date(2026, 7, 10),
        [{"boq_item_id": str(kalem.id), "quantity": "6"}],
        gonder=True,
    )
    ozet = (await _ozet(client, admin_headers, site.id)).json()
    assert Decimal(_kalem(ozet, kalem.id)["quantity"]) == Decimal("10")


async def test_donem_yanitta_echo_edilir(
    client: AsyncClient, admin_headers: dict[str, str], santiye
) -> None:
    """Ekran hangi dönemi gösterdiğini bilmelidir (HÖ L86 "· Temmuz 2026")."""
    site, _, _ = santiye
    ozet = (await _ozet(client, admin_headers, site.id, year=2026, month=7)).json()
    assert ozet["site_id"] == str(site.id)
    assert ozet["year"] == 2026
    assert ozet["month"] == 7


# --- İzin kapısı + IDOR ---


async def test_pm_ozeti_okuyabilir(
    client: AsyncClient, pm_headers: dict[str, str], admin_headers: dict[str, str], santiye
) -> None:
    """Özet OKUMA ucudur: PM (`site_diary=_V`) görebilir."""
    site, _, items = santiye
    await _gun(
        client,
        admin_headers,
        site.id,
        date(2026, 7, 10),
        [{"boq_item_id": str(items[0].id), "quantity": "2"}],
        gonder=True,
    )
    yanit = await _ozet(client, pm_headers, site.id, year=2026, month=7)
    assert yanit.status_code == 200, yanit.text


async def test_ik_rolu_ozette_403(client: AsyncClient, hr_headers: dict[str, str], santiye) -> None:
    site, _, _ = santiye
    assert (await _ozet(client, hr_headers, site.id, year=2026, month=7)).status_code == 403


async def test_gorunmeyen_santiyenin_ozeti_404(
    client: AsyncClient, sef_headers: dict[str, str], gorunmeyen_santiye
) -> None:
    yanit = await _ozet(client, sef_headers, gorunmeyen_santiye.id, year=2026, month=7)
    assert yanit.status_code == 404, yanit.text
    assert yanit.json()["detail"] == guards.SITE_MISSING


async def test_olmayan_santiye_ile_ayni_404_govdesi(
    client: AsyncClient, sef_headers: dict[str, str], gorunmeyen_santiye
) -> None:
    olmayan = await _ozet(client, sef_headers, uuid.uuid4(), year=2026, month=7)
    gorunmeyen = await _ozet(client, sef_headers, gorunmeyen_santiye.id, year=2026, month=7)
    assert olmayan.status_code == gorunmeyen.status_code == 404
    assert olmayan.json() == gorunmeyen.json()
