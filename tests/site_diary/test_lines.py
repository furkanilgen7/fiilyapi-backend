"""T3 — günlük poz satırları + işçi kırılımı yazma semantiği (spec §2, §3; plan T3).

Kapsam: `PUT /diary/{entry_id}/lines` DEĞİŞTİRME semantiği (yalnız `draft`,
FOR UPDATE kilidi), `PATCH /diary/{entry_id}` gövdesindeki `worker_counts[]`
değiştirme semantiği, ve OKUMA türevleri (`cumulative_quantity`, `line_amount`,
`lines_total`, `worker_total`) — hiçbiri KOLON DEĞİL.

Kapsam DIŞI (T4/T5): `submit`/`reopen`, `summary`, `diary-suggestion`.

## Kümülatif kararı (bu dosyada TESTLE SABİTLENİR)

`cumulative_quantity` = **aynı ayda, aynı şantiyede, aynı poz için, bu günden
ÖNCEKİ `submitted` kayıtların toplamı + BU kaydın kendi miktarı** (kaydın durumu
ne olursa olsun).

Gerekçe: T4 `summary` ucu spec §3 gereği YALNIZ `submitted` kayıtları sayar.
Bu tanım kayıt gönderildiğinde `summary`nin o güne kadarki ön-toplamına BİREBİR
eşitlenir (gönderilmiş kayıt için "öncekiler + kendisi" = "≤ bugün olan
gönderilmişler"), taslakta ise "gönderirsem kümülatif ne olacak" sorusunu
yanıtlar. BAŞKA günlerin TASLAKLARI sayılmaz — sayılsaydı ekrandaki kümülatif
ile hakediş özeti iki farklı sayı gösterirdi.
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditLog
from app.modules.site_diary import guards
from app.modules.site_diary.models import DiaryStatus, SiteDiaryEntry
from tests.site_diary.conftest import VARSAYILAN_TARIH

pytestmark = pytest.mark.asyncio


async def _olustur(
    client: AsyncClient, headers: dict[str, str], site_id, tarih: date = VARSAYILAN_TARIH
) -> dict:
    yanit = await client.post(
        f"/sites/{site_id}/diary", json={"entry_date": tarih.isoformat()}, headers=headers
    )
    assert yanit.status_code == 201, yanit.text
    return yanit.json()


async def _kaydet(client: AsyncClient, headers: dict[str, str], entry_id, satirlar: list[dict]):
    return await client.put(f"/diary/{entry_id}/lines", json={"lines": satirlar}, headers=headers)


def _satir(govde: dict, boq_item_id) -> dict | None:
    return next((s for s in govde["lines"] if s["boq_item_id"] == str(boq_item_id)), None)


async def _gonderildi_yap(seeded_db: AsyncSession, entry_id: uuid.UUID) -> None:
    """`submit` ucu T4'tedir — durum DOĞRUDAN damgalanır (test bağımsızlığı)."""
    entry = (
        await seeded_db.execute(select(SiteDiaryEntry).where(SiteDiaryEntry.id == entry_id))
    ).scalar_one()
    entry.status = DiaryStatus.submitted
    await seeded_db.flush()


# --- DEĞİŞTİRME semantiği ---


async def test_gonderilmeyen_satir_silinir(
    client: AsyncClient, admin_headers: dict[str, str], santiye
) -> None:
    """Gövde ekranın TAMAMIDIR: iskeletteki iki pozdan yalnız biri gönderilirse
    diğeri SİLİNİR (taşeron `lines.py` semantiğinin aynısı)."""
    site, _, items = santiye
    kayit = await _olustur(client, admin_headers, site.id)
    assert len(kayit["lines"]) == 2

    kalan, dusen = sorted(items, key=lambda i: i.code)
    yanit = await _kaydet(
        client, admin_headers, kayit["id"], [{"boq_item_id": str(kalan.id), "quantity": "12.500"}]
    )
    assert yanit.status_code == 200, yanit.text
    govde = yanit.json()
    assert len(govde["lines"]) == 1
    assert govde["lines"][0]["boq_item_id"] == str(kalan.id)
    assert _satir(govde, dusen.id) is None


async def test_bos_liste_tum_satirlari_temizler(
    client: AsyncClient, admin_headers: dict[str, str], santiye
) -> None:
    site, _, _ = santiye
    kayit = await _olustur(client, admin_headers, site.id)
    yanit = await _kaydet(client, admin_headers, kayit["id"], [])
    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["lines"] == []
    assert Decimal(yanit.json()["lines_total"]) == Decimal("0.00")


async def test_mevcut_satir_guncellenir_kimligi_korunur(
    client: AsyncClient, admin_headers: dict[str, str], santiye
) -> None:
    """Var olan satır SİLİNİP yeniden kurulmaz: kimliği korunur, yalnız miktar değişir."""
    site, _, items = santiye
    kayit = await _olustur(client, admin_headers, site.id)
    kalem = sorted(items, key=lambda i: i.code)[0]
    onceki_id = _satir(kayit, kalem.id)["id"]

    govde = (
        await _kaydet(
            client,
            admin_headers,
            kayit["id"],
            [{"boq_item_id": str(kalem.id), "quantity": "7.250"}],
        )
    ).json()
    satir = _satir(govde, kalem.id)
    assert satir["id"] == onceki_id
    assert Decimal(satir["quantity"]) == Decimal("7.250")


async def test_silinen_satir_yeniden_eklenebilir(
    client: AsyncClient, admin_headers: dict[str, str], santiye
) -> None:
    """Değiştirme semantiği tek yönlü değildir: temizlenen poz yeniden gönderilince
    snapshot'ı BOQ'dan yeniden kurulur."""
    site, _, items = santiye
    kayit = await _olustur(client, admin_headers, site.id)
    kalem = sorted(items, key=lambda i: i.code)[1]

    await _kaydet(client, admin_headers, kayit["id"], [])
    govde = (
        await _kaydet(
            client, admin_headers, kayit["id"], [{"boq_item_id": str(kalem.id), "quantity": "3"}]
        )
    ).json()
    satir = _satir(govde, kalem.id)
    assert satir is not None
    assert satir["code"] == kalem.code
    assert satir["description"] == kalem.description
    assert satir["unit"] == kalem.unit
    assert Decimal(satir["unit_price"]) == kalem.unit_price


async def test_satirlar_koda_gore_sirali_doner(
    client: AsyncClient, admin_headers: dict[str, str], santiye
) -> None:
    site, _, items = santiye
    kayit = await _olustur(client, admin_headers, site.id)
    tersine = sorted(items, key=lambda i: i.code, reverse=True)
    govde = (
        await _kaydet(
            client,
            admin_headers,
            kayit["id"],
            [{"boq_item_id": str(k.id), "quantity": "1"} for k in tersine],
        )
    ).json()
    kodlar = [s["code"] for s in govde["lines"]]
    assert kodlar == sorted(kodlar)


# --- Durum kapısı + kilit ---


async def test_gonderilmis_kayda_put_reddedilir(
    client: AsyncClient, admin_headers: dict[str, str], santiye, seeded_db: AsyncSession
) -> None:
    site, _, items = santiye
    kayit = await _olustur(client, admin_headers, site.id)
    await _gonderildi_yap(seeded_db, uuid.UUID(kayit["id"]))

    yanit = await _kaydet(
        client, admin_headers, kayit["id"], [{"boq_item_id": str(items[0].id), "quantity": "1"}]
    )
    assert yanit.status_code == 409, yanit.text
    assert yanit.json()["detail"] == guards.ENTRY_NOT_EDITABLE


async def test_kilit_alinir(
    client: AsyncClient, admin_headers: dict[str, str], santiye, monkeypatch
) -> None:
    """Yazma yolu KİLİTLİ satır üzerinden çalışır — kilitsiz okunsaydı eşzamanlı
    bir `submit` durum kapısını TOCTOU ile atlatırdı."""
    from app.modules.site_diary import repository

    site, _, items = santiye
    kayit = await _olustur(client, admin_headers, site.id)

    cagrilar: list[uuid.UUID] = []
    gercek = repository.get_entry_locked

    async def casus(session, entry_id):
        cagrilar.append(entry_id)
        return await gercek(session, entry_id)

    monkeypatch.setattr(repository, "get_entry_locked", casus)
    yanit = await _kaydet(
        client, admin_headers, kayit["id"], [{"boq_item_id": str(items[0].id), "quantity": "1"}]
    )
    assert yanit.status_code == 200, yanit.text
    assert cagrilar, "PUT …/lines `SELECT … FOR UPDATE` almadan yazıyor"


# --- Gövde doğrulamaları ---


async def test_negatif_miktar_reddedilir(
    client: AsyncClient, admin_headers: dict[str, str], santiye
) -> None:
    site, _, items = santiye
    kayit = await _olustur(client, admin_headers, site.id)
    yanit = await _kaydet(
        client, admin_headers, kayit["id"], [{"boq_item_id": str(items[0].id), "quantity": "-1"}]
    )
    assert yanit.status_code == 422, yanit.text


async def test_sifir_miktar_mesrudur(
    client: AsyncClient, admin_headers: dict[str, str], santiye
) -> None:
    """0 "girilmedi" değil "bugün bu pozda iş yok" demektir (GK228)."""
    site, _, items = santiye
    kayit = await _olustur(client, admin_headers, site.id)
    yanit = await _kaydet(
        client, admin_headers, kayit["id"], [{"boq_item_id": str(items[0].id), "quantity": "0"}]
    )
    assert yanit.status_code == 200, yanit.text
    assert Decimal(yanit.json()["lines"][0]["quantity"]) == Decimal("0")


async def test_yabanci_boq_pozu_reddedilir(
    client: AsyncClient, admin_headers: dict[str, str], santiye, santiye_fabrikasi
) -> None:
    """BAŞKA şantiyenin pozu ile VAR OLMAYAN poz AYNI 422'yi alır (IDOR yüzeyi)."""
    site, _, _ = santiye
    _, _, yabanci_kalemler = await santiye_fabrikasi("SD-Y")
    kayit = await _olustur(client, admin_headers, site.id)

    yabanci = await _kaydet(
        client,
        admin_headers,
        kayit["id"],
        [{"boq_item_id": str(yabanci_kalemler[0].id), "quantity": "1"}],
    )
    assert yabanci.status_code == 422, yabanci.text
    assert yabanci.json()["detail"] == guards.LINE_ITEM_MISMATCH

    yok = await _kaydet(
        client, admin_headers, kayit["id"], [{"boq_item_id": str(uuid.uuid4()), "quantity": "1"}]
    )
    assert yok.status_code == 422, yok.text
    assert yok.json()["detail"] == guards.LINE_ITEM_MISMATCH


async def test_govdede_cift_poz_reddedilir(
    client: AsyncClient, admin_headers: dict[str, str], santiye
) -> None:
    """UQ (entry_id, boq_item_id) `IntegrityError`a DÜŞMEDEN net 409 olur."""
    site, _, items = santiye
    kayit = await _olustur(client, admin_headers, site.id)
    yanit = await _kaydet(
        client,
        admin_headers,
        kayit["id"],
        [
            {"boq_item_id": str(items[0].id), "quantity": "1"},
            {"boq_item_id": str(items[0].id), "quantity": "2"},
        ],
    )
    assert yanit.status_code == 409, yanit.text
    assert yanit.json()["detail"] == guards.DUPLICATE_LINE


async def test_istemci_birim_fiyat_enjekte_edemez(
    client: AsyncClient, admin_headers: dict[str, str], santiye
) -> None:
    """Snapshot dörtlüsü İSTEMCİDEN GELMEZ: gövdeye fiyat yazma denemesi 422'dir
    ve kayıtlı fiyat BOQ'nun fiyatı olarak KALIR."""
    site, _, items = santiye
    kalem = sorted(items, key=lambda i: i.code)[0]
    kayit = await _olustur(client, admin_headers, site.id)

    for alan, deger in (
        ("unit_price", "1.00"),
        ("code", "SAHTE"),
        ("description", "sahte"),
        ("unit", "Adet"),
    ):
        yanit = await _kaydet(
            client,
            admin_headers,
            kayit["id"],
            [{"boq_item_id": str(kalem.id), "quantity": "1", alan: deger}],
        )
        assert yanit.status_code == 422, f"{alan}: {yanit.text}"

    govde = (
        await _kaydet(
            client, admin_headers, kayit["id"], [{"boq_item_id": str(kalem.id), "quantity": "1"}]
        )
    ).json()
    satir = _satir(govde, kalem.id)
    assert Decimal(satir["unit_price"]) == kalem.unit_price
    assert satir["code"] == kalem.code


async def test_bagi_kopmus_satir_duser_ve_sayisi_bildirilir(
    client: AsyncClient,
    admin_headers: dict[str, str],
    santiye,
    gunluk_fabrikasi,
    admin_kullanicisi,
) -> None:
    """`boq_item_id IS NULL` satır gövdeden ADRESLENEMEZ → düşer; SESSİZ değil."""
    site, _, items = santiye
    kayit = await gunluk_fabrikasi(
        site, admin_kullanicisi, lines=[("99.001", Decimal("5"), Decimal("100.00"))]
    )
    yanit = await _kaydet(
        client, admin_headers, str(kayit.id), [{"boq_item_id": str(items[0].id), "quantity": "1"}]
    )
    assert yanit.status_code == 200, yanit.text
    govde = yanit.json()
    assert govde["dropped_orphan_count"] == 1
    assert len(govde["lines"]) == 1


# --- Erişim ---


async def test_pm_salt_okur(
    client: AsyncClient, admin_headers: dict[str, str], pm_headers: dict[str, str], santiye
) -> None:
    site, _, items = santiye
    kayit = await _olustur(client, admin_headers, site.id)
    yanit = await _kaydet(
        client, pm_headers, kayit["id"], [{"boq_item_id": str(items[0].id), "quantity": "1"}]
    )
    assert yanit.status_code == 403, yanit.text


async def test_gorunmeyen_kayit_404(
    client: AsyncClient, sef_headers: dict[str, str], gorunmeyen_gunluk
) -> None:
    yanit = await _kaydet(client, sef_headers, str(gorunmeyen_gunluk), [])
    assert yanit.status_code == 404, yanit.text
    assert yanit.json()["detail"] == guards.ENTRY_MISSING


async def test_denetim_kaydi_yazilir(
    client: AsyncClient, admin_headers: dict[str, str], santiye, seeded_db: AsyncSession
) -> None:
    site, _, items = santiye
    kayit = await _olustur(client, admin_headers, site.id)
    await _kaydet(
        client, admin_headers, kayit["id"], [{"boq_item_id": str(items[0].id), "quantity": "1"}]
    )
    kayitlar = (await seeded_db.execute(select(AuditLog))).scalars().all()
    assert any("poz satırları kaydedildi" in k.detail for k in kayitlar), [
        k.detail for k in kayitlar
    ]


# --- Türevler: line_amount / lines_total ---


async def test_line_amount_ve_lines_total_dogru(
    client: AsyncClient, admin_headers: dict[str, str], santiye
) -> None:
    """₺ katkısı KATSAYISIZ `quantity × unit_price` (spec §2); toplam SATIR BAZINDA
    yuvarlanmış değerlerin toplamıdır."""
    site, _, items = santiye
    a, b = sorted(items, key=lambda i: i.code)
    kayit = await _olustur(client, admin_headers, site.id)
    govde = (
        await _kaydet(
            client,
            admin_headers,
            kayit["id"],
            [
                {"boq_item_id": str(a.id), "quantity": "2.500"},
                {"boq_item_id": str(b.id), "quantity": "1.125"},
            ],
        )
    ).json()

    beklenen_a = (a.unit_price * Decimal("2.500")).quantize(Decimal("0.01"))
    beklenen_b = (b.unit_price * Decimal("1.125")).quantize(Decimal("0.01"))
    assert Decimal(_satir(govde, a.id)["line_amount"]) == beklenen_a
    assert Decimal(_satir(govde, b.id)["line_amount"]) == beklenen_b
    assert Decimal(govde["lines_total"]) == beklenen_a + beklenen_b


# --- Türev: cumulative_quantity (çok günlü senaryo) ---


async def test_kumulatif_yalniz_gonderilmis_onceki_gunler_ve_kendisi(
    client: AsyncClient, admin_headers: dict[str, str], santiye, seeded_db: AsyncSession
) -> None:
    """Kümülatif kararı (dosya docstring'i) — DÖRT ayrım tek testte sabitlenir:
    önceki ay sayılmaz · başka günün TASLAĞI sayılmaz · SONRAKİ gün sayılmaz ·
    kaydın KENDİ miktarı sayılır.
    """
    site, _, items = santiye
    kalem = sorted(items, key=lambda i: i.code)[0]

    async def gun(tarih: date, miktar: str, *, gonderildi: bool) -> dict:
        kayit = await _olustur(client, admin_headers, site.id, tarih)
        yanit = await _kaydet(
            client, admin_headers, kayit["id"], [{"boq_item_id": str(kalem.id), "quantity": miktar}]
        )
        assert yanit.status_code == 200, yanit.text
        if gonderildi:
            await _gonderildi_yap(seeded_db, uuid.UUID(kayit["id"]))
        return yanit.json()

    # Onceki ay — sayilMAZ (kumulatif AY BASINDAN itibarendir).
    await gun(date(2026, 6, 30), "100", gonderildi=True)
    # Ayni ay, onceki gun, GONDERILMIS — sayilir.
    await gun(date(2026, 7, 10), "10", gonderildi=True)
    # Ayni ay, onceki gun, TASLAK — sayilMAZ (summary de saymaz).
    await gun(date(2026, 7, 12), "5", gonderildi=False)
    # Sonraki gun, gonderilmis — sayilMAZ (kumulatif ileriye bakmaz).
    await gun(date(2026, 7, 20), "7", gonderildi=True)

    bugun = await gun(date(2026, 7, 15), "3", gonderildi=False)
    satir = _satir(bugun, kalem.id)
    assert Decimal(satir["quantity"]) == Decimal("3")
    assert Decimal(satir["cumulative_quantity"]) == Decimal("13")

    # Kaydin KENDISI gonderildiginde tanim degismez (10 + 3).
    await _gonderildi_yap(seeded_db, uuid.UUID(bugun["id"]))
    detay = (await client.get(f"/diary/{bugun['id']}", headers=admin_headers)).json()
    assert Decimal(_satir(detay, kalem.id)["cumulative_quantity"]) == Decimal("13")


async def test_kumulatif_baska_santiyeyi_saymaz(
    client: AsyncClient,
    admin_headers: dict[str, str],
    santiye,
    santiye_fabrikasi,
    seeded_db: AsyncSession,
) -> None:
    """Kümülatif ŞANTİYE + POZ ikilisine bağlıdır; komşu şantiyenin aynı kodlu
    pozu ayrı bir `boq_item_id`dir ve karışmaz."""
    site, proje, items = santiye
    komsu_site, _, komsu_items = await santiye_fabrikasi("SD-K", project=proje)
    kalem = sorted(items, key=lambda i: i.code)[0]
    komsu_kalem = sorted(komsu_items, key=lambda i: i.code)[0]

    komsu = await _olustur(client, admin_headers, komsu_site.id, date(2026, 7, 10))
    await _kaydet(
        client, admin_headers, komsu["id"], [{"boq_item_id": str(komsu_kalem.id), "quantity": "40"}]
    )
    await _gonderildi_yap(seeded_db, uuid.UUID(komsu["id"]))

    bugun = await _olustur(client, admin_headers, site.id, date(2026, 7, 15))
    govde = (
        await _kaydet(
            client, admin_headers, bugun["id"], [{"boq_item_id": str(kalem.id), "quantity": "2"}]
        )
    ).json()
    assert Decimal(_satir(govde, kalem.id)["cumulative_quantity"]) == Decimal("2")


# --- İşçi kırılımı yazma (PATCH gövdesinde iç içe) ---


async def _patch(client: AsyncClient, headers: dict[str, str], entry_id, **govde):
    return await client.patch(f"/diary/{entry_id}", json=govde, headers=headers)


async def test_isci_kirilimi_yazilir_ve_toplam_turetilir(
    client: AsyncClient, admin_headers: dict[str, str], santiye
) -> None:
    site, _, _ = santiye
    kayit = await _olustur(client, admin_headers, site.id)
    yanit = await _patch(
        client,
        admin_headers,
        kayit["id"],
        worker_counts=[
            {"trade": "Kalıpçı", "source": "company", "count": 12},
            {"trade": "Demirci", "source": "subcontractor", "count": 8},
        ],
    )
    assert yanit.status_code == 200, yanit.text
    govde = yanit.json()
    assert govde["worker_total"] == 20
    assert {(s["trade"], s["source"], s["count"]) for s in govde["worker_counts"]} == {
        ("Kalıpçı", "company", 12),
        ("Demirci", "subcontractor", 8),
    }


async def test_isci_kirilimi_degistirme_semantigi(
    client: AsyncClient, admin_headers: dict[str, str], santiye
) -> None:
    """Gönderilmeyen (meslek, kaynak) çifti SİLİNİR; boş liste hepsini temizler."""
    site, _, _ = santiye
    kayit = await _olustur(client, admin_headers, site.id)
    await _patch(
        client,
        admin_headers,
        kayit["id"],
        worker_counts=[
            {"trade": "Kalıpçı", "source": "company", "count": 12},
            {"trade": "Demirci", "source": "company", "count": 8},
        ],
    )
    govde = (
        await _patch(
            client,
            admin_headers,
            kayit["id"],
            worker_counts=[{"trade": "Kalıpçı", "source": "company", "count": 3}],
        )
    ).json()
    assert len(govde["worker_counts"]) == 1
    assert govde["worker_counts"][0]["count"] == 3
    assert govde["worker_total"] == 3

    bos = (await _patch(client, admin_headers, kayit["id"], worker_counts=[])).json()
    assert bos["worker_counts"] == []
    assert bos["worker_total"] == 0


async def test_isci_kirilimi_gonderilmezse_korunur(
    client: AsyncClient, admin_headers: dict[str, str], santiye
) -> None:
    """`exclude_unset`: başlık alanı güncelleyen bir PATCH işçi kırılımını
    SESSİZCE SİLMEZ."""
    site, _, _ = santiye
    kayit = await _olustur(client, admin_headers, site.id)
    await _patch(
        client,
        admin_headers,
        kayit["id"],
        worker_counts=[{"trade": "Kalıpçı", "source": "company", "count": 4}],
    )
    govde = (await _patch(client, admin_headers, kayit["id"], work_done="Kalıp söküldü")).json()
    assert govde["work_done"] == "Kalıp söküldü"
    assert govde["worker_total"] == 4


async def test_isci_kirilimi_null_reddedilir(
    client: AsyncClient, admin_headers: dict[str, str], santiye
) -> None:
    """`null` bir niyet DEĞİLDİR: sessizce yok sayılsaydı "hepsini sil" demek
    isteyen kullanıcı sildiğini sanırdı. Temizlemenin tek yolu BOŞ LİSTEDİR."""
    site, _, _ = santiye
    kayit = await _olustur(client, admin_headers, site.id)
    await _patch(
        client,
        admin_headers,
        kayit["id"],
        worker_counts=[{"trade": "Kalıpçı", "source": "company", "count": 4}],
    )
    yanit = await _patch(client, admin_headers, kayit["id"], worker_counts=None)
    assert yanit.status_code == 422, yanit.text

    korunan = (await client.get(f"/diary/{kayit['id']}", headers=admin_headers)).json()
    assert korunan["worker_total"] == 4


async def test_isci_kirilimi_govde_ici_cakisma_reddedilir(
    client: AsyncClient, admin_headers: dict[str, str], santiye
) -> None:
    """UQ (entry_id, trade, source) `IntegrityError`a DÜŞMEDEN net 409 olur —
    500 DEĞİL."""
    site, _, _ = santiye
    kayit = await _olustur(client, admin_headers, site.id)
    yanit = await _patch(
        client,
        admin_headers,
        kayit["id"],
        worker_counts=[
            {"trade": "Kalıpçı", "source": "company", "count": 4},
            {"trade": "Kalıpçı", "source": "company", "count": 6},
        ],
    )
    assert yanit.status_code == 409, yanit.text
    assert yanit.json()["detail"] == guards.DUPLICATE_WORKER_COUNT


async def test_isci_kirilimi_ayni_meslek_farkli_kaynak_mesrudur(
    client: AsyncClient, admin_headers: dict[str, str], santiye
) -> None:
    site, _, _ = santiye
    kayit = await _olustur(client, admin_headers, site.id)
    yanit = await _patch(
        client,
        admin_headers,
        kayit["id"],
        worker_counts=[
            {"trade": "Kalıpçı", "source": "company", "count": 4},
            {"trade": "Kalıpçı", "source": "subcontractor", "count": 6},
        ],
    )
    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["worker_total"] == 10


async def test_negatif_isci_sayisi_reddedilir(
    client: AsyncClient, admin_headers: dict[str, str], santiye
) -> None:
    site, _, _ = santiye
    kayit = await _olustur(client, admin_headers, site.id)
    yanit = await _patch(
        client,
        admin_headers,
        kayit["id"],
        worker_counts=[{"trade": "Kalıpçı", "source": "company", "count": -1}],
    )
    assert yanit.status_code == 422, yanit.text


@pytest.mark.parametrize("meslek", ["", "   ", "\t\n"])
async def test_bos_meslek_reddedilir(
    client: AsyncClient, admin_headers: dict[str, str], santiye, meslek: str
) -> None:
    """`trade` serbest metindir ama BOŞ olamaz — katalogsuz bir alanın tek
    korkuluğu budur."""
    site, _, _ = santiye
    kayit = await _olustur(client, admin_headers, site.id)
    yanit = await _patch(
        client,
        admin_headers,
        kayit["id"],
        worker_counts=[{"trade": meslek, "source": "company", "count": 3}],
    )
    assert yanit.status_code == 422, yanit.text
    assert guards.TRADE_REQUIRED in yanit.text


async def test_meslek_bosluklari_kirpilir(
    client: AsyncClient, admin_headers: dict[str, str], santiye
) -> None:
    """Kırpılmasaydı "Kalıpçı" ile " Kalıpçı" UQ'da AYRI iki satır olur, ekranda
    aynı meslek iki kez görünürdü."""
    site, _, _ = santiye
    kayit = await _olustur(client, admin_headers, site.id)
    govde = (
        await _patch(
            client,
            admin_headers,
            kayit["id"],
            worker_counts=[{"trade": "  Kalıpçı  ", "source": "company", "count": 3}],
        )
    ).json()
    assert govde["worker_counts"][0]["trade"] == "Kalıpçı"


async def test_gonderilmis_kayda_isci_kirilimi_yazilamaz(
    client: AsyncClient, admin_headers: dict[str, str], santiye, seeded_db: AsyncSession
) -> None:
    site, _, _ = santiye
    kayit = await _olustur(client, admin_headers, site.id)
    await _gonderildi_yap(seeded_db, uuid.UUID(kayit["id"]))
    yanit = await _patch(
        client,
        admin_headers,
        kayit["id"],
        worker_counts=[{"trade": "Kalıpçı", "source": "company", "count": 3}],
    )
    assert yanit.status_code == 409, yanit.text
    assert yanit.json()["detail"] == guards.ENTRY_NOT_EDITABLE


async def test_isci_kirilimi_pm_salt_okur(
    client: AsyncClient, admin_headers: dict[str, str], pm_headers: dict[str, str], santiye
) -> None:
    site, _, _ = santiye
    kayit = await _olustur(client, admin_headers, site.id)
    yanit = await _patch(
        client,
        pm_headers,
        kayit["id"],
        worker_counts=[{"trade": "Kalıpçı", "source": "company", "count": 3}],
    )
    assert yanit.status_code == 403, yanit.text


async def test_isci_kirilimi_listede_toplam_olarak_gorunur(
    client: AsyncClient, admin_headers: dict[str, str], santiye
) -> None:
    site, _, _ = santiye
    kayit = await _olustur(client, admin_headers, site.id)
    await _patch(
        client,
        admin_headers,
        kayit["id"],
        worker_counts=[{"trade": "Kalıpçı", "source": "general", "count": 9}],
    )
    liste = (await client.get(f"/sites/{site.id}/diary", headers=admin_headers)).json()
    assert liste["items"][0]["worker_total"] == 9
