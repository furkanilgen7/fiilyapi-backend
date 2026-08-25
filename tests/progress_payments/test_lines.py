"""Hakediş satırları — DEĞİŞTİRME SEMANTİĞİ · dağıtım ön şartı · KOTA TAVANI ·
"Önceki" kolonu · bağı kopmuş satır · sahiplik (IDOR yüzeyi).

PUT gövdesi DEĞİŞTİRME semantiğidir: gövdede olmayan satır SİLİNİR, boş gövde
tüm satırları siler. Kota kümülatifi YALNIZ tamamlanmış hakedişlerden toplanır
ve hakedişin kendi eski miktarı kotayı TÜKETMEZ.

⚠️ Dosya 800 satır tavanını aşınca BÖLÜNDÜ (`_journal.py` emsali): FF kilidi,
katsayı öntanımı, sıfır miktar, durum kapısı ve H6/K1 iddiaları
`test_lines_ff.py`ye taşındı; paylaşılan yardımcılar `_lines.py`dedir.
Hiçbir testin iddiası değişmedi.
"""

import uuid
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.contracts.models import EmployerContractItem
from app.modules.progress_payments import guards
from app.modules.progress_payments.models import (
    ProgressPayment,
    ProgressPaymentLine,
    ProgressPaymentStatus,
)
from app.modules.sites.models import Site

from ._lines import (
    _kotayi_dusur,
    _satir,
    _satir_sayisi,
)

pytestmark = pytest.mark.asyncio


async def test_degistirme_semantigi_govdede_olmayan_satir_silinir(
    client: AsyncClient,
    admin_headers: dict[str, str],
    taslak_hakedis: uuid.UUID,
    hakedis_santiyesi: Site,
    hakedis_kalemi: tuple[EmployerContractItem, str],
    ikinci_dagitilmis_kalem: EmployerContractItem,
    seeded_db: AsyncSession,
) -> None:
    """P5 dağılımının BİRLEŞTİRME kuralının TERSİ: form her kaydedişte tam
    tabloyu gönderir, gövdede geçmeyen satır `quantity: null` beklemeden SİLİNİR."""
    item, _ = hakedis_kalemi
    ilk = await client.put(
        f"/progress-payments/{taslak_hakedis}/lines",
        json={
            "lines": [
                _satir(item.id, hakedis_santiyesi.id, "100"),
                _satir(ikinci_dagitilmis_kalem.id, hakedis_santiyesi.id, "50"),
            ]
        },
        headers=admin_headers,
    )
    assert ilk.status_code == 200, ilk.text
    assert len(ilk.json()["lines"]) == 2

    ikinci = await client.put(
        f"/progress-payments/{taslak_hakedis}/lines",
        json={"lines": [_satir(item.id, hakedis_santiyesi.id, "120")]},
        headers=admin_headers,
    )
    assert ikinci.status_code == 200, ikinci.text
    kalan = ikinci.json()["lines"]
    assert len(kalan) == 1
    assert kalan[0]["contract_item_id"] == str(item.id)
    assert Decimal(kalan[0]["quantity"]) == Decimal("120")
    # Yanıt değil DB kanıtı: birleştirme olsaydı ikinci satır DB'de kalırdı.
    assert await _satir_sayisi(seeded_db, taslak_hakedis) == 1


async def test_bos_govde_tum_satirlari_siler(
    client: AsyncClient,
    admin_headers: dict[str, str],
    taslak_hakedis: uuid.UUID,
    hakedis_santiyesi: Site,
    hakedis_kalemi: tuple[EmployerContractItem, str],
    seeded_db: AsyncSession,
) -> None:
    """`{"lines": []}` = tabloyu temizle (değiştirme semantiğinin sınır hâli)."""
    item, _ = hakedis_kalemi
    await client.put(
        f"/progress-payments/{taslak_hakedis}/lines",
        json={"lines": [_satir(item.id, hakedis_santiyesi.id, "10")]},
        headers=admin_headers,
    )
    yanit = await client.put(
        f"/progress-payments/{taslak_hakedis}/lines", json={"lines": []}, headers=admin_headers
    )
    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["lines"] == []
    assert await _satir_sayisi(seeded_db, taslak_hakedis) == 0


async def test_mevcut_satirin_kimligi_ve_snapshotu_korunur(
    client: AsyncClient,
    admin_headers: dict[str, str],
    taslak_hakedis: uuid.UUID,
    hakedis_santiyesi: Site,
    hakedis_kalemi: tuple[EmployerContractItem, str],
    seeded_db: AsyncSession,
) -> None:
    """Spec §5: snapshot yalnız YENİ satırda kalemden kopyalanır; aynı hücre
    yeniden gönderilince satır SİLİNİP yeniden açılmaz, snapshot DONMUŞ kalır
    (tazeleme yalnız H7'nin `refresh-prices` ucundadır)."""
    item, _ = hakedis_kalemi
    ilk = await client.put(
        f"/progress-payments/{taslak_hakedis}/lines",
        json={"lines": [_satir(item.id, hakedis_santiyesi.id, "10")]},
        headers=admin_headers,
    )
    satir_id = ilk.json()["lines"][0]["id"]

    item.unit_price = Decimal("2500")
    await seeded_db.flush()

    ikinci = await client.put(
        f"/progress-payments/{taslak_hakedis}/lines",
        json={"lines": [_satir(item.id, hakedis_santiyesi.id, "20")]},
        headers=admin_headers,
    )
    satir = ikinci.json()["lines"][0]
    assert satir["id"] == satir_id
    assert Decimal(satir["contract_unit_price"]) == Decimal("1850")
    assert satir["is_price_stale"] is True


async def test_satir_sirasi_govde_sirasini_izler(
    client: AsyncClient,
    admin_headers: dict[str, str],
    taslak_hakedis: uuid.UUID,
    hakedis_santiyesi: Site,
    hakedis_kalemi: tuple[EmployerContractItem, str],
    ikinci_dagitilmis_kalem: EmployerContractItem,
) -> None:
    item, _ = hakedis_kalemi
    yanit = await client.put(
        f"/progress-payments/{taslak_hakedis}/lines",
        json={
            "lines": [
                _satir(ikinci_dagitilmis_kalem.id, hakedis_santiyesi.id, "5"),
                _satir(item.id, hakedis_santiyesi.id, "5"),
            ]
        },
        headers=admin_headers,
    )
    assert yanit.status_code == 200, yanit.text
    satirlar = yanit.json()["lines"]
    assert [s["sort_order"] for s in satirlar] == [0, 1]
    assert satirlar[0]["contract_item_id"] == str(ikinci_dagitilmis_kalem.id)


async def test_mevcut_satirlarin_sirasi_da_govde_sirasina_gore_guncellenir(
    client: AsyncClient,
    admin_headers: dict[str, str],
    taslak_hakedis: uuid.UUID,
    hakedis_santiyesi: Site,
    hakedis_kalemi: tuple[EmployerContractItem, str],
    ikinci_dagitilmis_kalem: EmployerContractItem,
    seeded_db: AsyncSession,
) -> None:
    """D3 (H5 denetimi): kullanıcı satırları SÜRÜKLEYİP yeniden kaydettiğinde
    MEVCUT satırların `sort_order`'ı da yeniden yazılır — kardeş test yalnız
    YENİ satırları kapsıyordu, mevcut satırların sırası hiç doğrulanmamıştı."""
    item, _ = hakedis_kalemi
    ilk = await client.put(
        f"/progress-payments/{taslak_hakedis}/lines",
        json={
            "lines": [
                _satir(item.id, hakedis_santiyesi.id, "10"),
                _satir(ikinci_dagitilmis_kalem.id, hakedis_santiyesi.id, "20"),
            ]
        },
        headers=admin_headers,
    )
    assert [s["sort_order"] for s in ilk.json()["lines"]] == [0, 1]
    ilk_kimlikler = [s["id"] for s in ilk.json()["lines"]]

    ters = await client.put(
        f"/progress-payments/{taslak_hakedis}/lines",
        json={
            "lines": [
                _satir(ikinci_dagitilmis_kalem.id, hakedis_santiyesi.id, "20"),
                _satir(item.id, hakedis_santiyesi.id, "10"),
            ]
        },
        headers=admin_headers,
    )
    assert ters.status_code == 200, ters.text
    satirlar = ters.json()["lines"]
    # Satırlar SİLİNİP yeniden açılmadı (kimlikler aynı), yalnız sıraları döndü.
    assert set(s["id"] for s in satirlar) == set(ilk_kimlikler)
    assert satirlar[0]["contract_item_id"] == str(ikinci_dagitilmis_kalem.id)
    assert [s["sort_order"] for s in satirlar] == [0, 1]

    # Yanıt değil DB kanıtı: ilişki `sort_order`'a göre sıralı okunduğu için
    # yanıttaki sıra tek başına kolonun YAZILDIĞINI kanıtlamaz.
    stmt = select(ProgressPaymentLine.sort_order).where(
        ProgressPaymentLine.payment_id == taslak_hakedis,
        ProgressPaymentLine.contract_item_id == ikinci_dagitilmis_kalem.id,
    )
    assert (await seeded_db.execute(stmt)).scalar_one() == 0


# --- §6.5/1 dağıtım ön şartı ---


async def test_dagitilmamis_cifte_satir_422(
    client: AsyncClient,
    admin_headers: dict[str, str],
    taslak_hakedis: uuid.UUID,
    hakedis_santiyesi: Site,
    dagitilmamis_kalem: EmployerContractItem,
) -> None:
    """POZ 65: şantiye ataması (dağıtım) yapılmadan hakediş satırı açılamaz."""
    yanit = await client.put(
        f"/progress-payments/{taslak_hakedis}/lines",
        json={"lines": [_satir(dagitilmamis_kalem.id, hakedis_santiyesi.id, "10")]},
        headers=admin_headers,
    )
    assert yanit.status_code == 422, yanit.text
    assert yanit.json()["detail"] == guards.ITEM_NOT_DISTRIBUTED


async def test_olusturmada_da_dagitim_onsarti_kosar(
    client: AsyncClient,
    admin_headers: dict[str, str],
    sozlesmeli_proje: uuid.UUID,
    hakedis_santiyesi: Site,
    dagitilmamis_kalem: EmployerContractItem,
) -> None:
    """Tek yol kanıtı: POST'un iç içe `lines[]`'ı da AYNI korkuluk kümesinden
    geçer (§6.5 "her durumda koşar") — `PUT …/lines` bir arka kapı bırakmaz."""
    yanit = await client.post(
        f"/projects/{sozlesmeli_proje}/progress-payments",
        json={"lines": [_satir(dagitilmamis_kalem.id, hakedis_santiyesi.id, "10")]},
        headers=admin_headers,
    )
    assert yanit.status_code == 422, yanit.text
    assert yanit.json()["detail"] == guards.ITEM_NOT_DISTRIBUTED


# --- §6.5/2 kota tavanı ---


async def test_kota_asimi_422_ve_hicbir_sey_yazilmaz(
    client: AsyncClient,
    admin_headers: dict[str, str],
    onayli_gecmisli_ortam: tuple[uuid.UUID, EmployerContractItem, Site, EmployerContractItem],
    seeded_db: AsyncSession,
) -> None:
    """K6 sert 422 + ATOMİKLİK: gövdedeki İLK satır tamamen geçerli olsa bile
    hiçbir satır yazılmaz (P5 C8 dersi: önce TÜM doğrulamalar, sonra yazma)."""
    payment_id, item, site, gecmissiz_kalem = onayli_gecmisli_ortam
    yanit = await client.put(
        f"/progress-payments/{payment_id}/lines",
        json={
            "lines": [
                _satir(gecmissiz_kalem.id, site.id, "10"),
                _satir(item.id, site.id, "401"),
            ]
        },
        headers=admin_headers,
    )
    assert yanit.status_code == 422, yanit.text
    assert yanit.json()["detail"] == guards.QUANTITY_EXCEEDS_QUOTA
    assert await _satir_sayisi(seeded_db, payment_id) == 0


async def test_kota_tam_sinirda_kabul(
    client: AsyncClient,
    admin_headers: dict[str, str],
    onayli_gecmisli_ortam: tuple[uuid.UUID, EmployerContractItem, Site, EmployerContractItem],
) -> None:
    """Kümülatif == kota → 200 (aşım DEĞİL; `>` ile `>=` farkını yakalar)."""
    payment_id, item, site, _ = onayli_gecmisli_ortam
    yanit = await client.put(
        f"/progress-payments/{payment_id}/lines",
        json={"lines": [_satir(item.id, site.id, "400")]},
        headers=admin_headers,
    )
    assert yanit.status_code == 200, yanit.text
    assert Decimal(yanit.json()["lines"][0]["cumulative_quantity"]) == Decimal("1000")


async def test_kota_kumulatifi_detaydaki_onceki_miktarla_ayni_kumeden_gelir(
    client: AsyncClient,
    admin_headers: dict[str, str],
    onayli_gecmisli_ortam: tuple[uuid.UUID, EmployerContractItem, Site, EmployerContractItem],
) -> None:
    """GOREV-SIRASI §2/1 (P5 bulgusu) tekrarlanmasın: aşım kontrolünün topladığı
    küme ile kullanıcıya gösterilen "önceki" AYNI tanımdır — 600 onaylı geçmiş
    hem `previous_quantity`de görünür hem kalanı 400'e düşürür."""
    payment_id, item, site, _ = onayli_gecmisli_ortam
    yanit = await client.put(
        f"/progress-payments/{payment_id}/lines",
        json={"lines": [_satir(item.id, site.id, "400")]},
        headers=admin_headers,
    )
    assert yanit.status_code == 200, yanit.text
    satir = yanit.json()["lines"][0]
    assert Decimal(satir["previous_quantity"]) == Decimal("600")

    asim = await client.put(
        f"/progress-payments/{payment_id}/lines",
        json={"lines": [_satir(item.id, site.id, "401")]},
        headers=admin_headers,
    )
    assert asim.status_code == 422
    assert asim.json()["detail"] == guards.QUANTITY_EXCEEDS_QUOTA


async def test_kota_yalniz_tamamlanmis_hakedislerden_toplanir(
    client: AsyncClient,
    admin_headers: dict[str, str],
    taslak_gecmisli_ortam: tuple[uuid.UUID, EmployerContractItem, Site, EmployerContractItem],
) -> None:
    """§6.6: `prev = approved|paid`. Önceki hakediş `draft` ise kümülatife
    GİRMEZ — 600 taslak + 1.000 yeni miktar kotayı aşmış SAYILMAZ ve
    `previous_quantity` 0'dır (iki taraf tek tanımdan okur)."""
    payment_id, item, site, _ = taslak_gecmisli_ortam
    yanit = await client.put(
        f"/progress-payments/{payment_id}/lines",
        json={"lines": [_satir(item.id, site.id, "1000")]},
        headers=admin_headers,
    )
    assert yanit.status_code == 200, yanit.text
    assert Decimal(yanit.json()["lines"][0]["previous_quantity"]) == Decimal("0")


async def test_ayni_hakedisin_kendi_eski_miktari_kotayi_tuketmez(
    client: AsyncClient,
    admin_headers: dict[str, str],
    onayli_gecmisli_ortam: tuple[uuid.UUID, EmployerContractItem, Site, EmployerContractItem],
) -> None:
    """Değiştirme semantiğinin kotayla kesişimi: aynı taslağı 400 → 400 olarak
    yeniden kaydetmek aşım vermez (kendi satırı iki kez sayılmaz)."""
    payment_id, item, site, _ = onayli_gecmisli_ortam
    for _ in range(2):
        yanit = await client.put(
            f"/progress-payments/{payment_id}/lines",
            json={"lines": [_satir(item.id, site.id, "400")]},
            headers=admin_headers,
        )
        assert yanit.status_code == 200, yanit.text


async def _kotasi_dusmus_taslak(
    client: AsyncClient,
    admin_headers: dict[str, str],
    ortam: tuple[uuid.UUID, EmployerContractItem, Site, EmployerContractItem],
    seeded_db: AsyncSession,
) -> tuple[uuid.UUID, EmployerContractItem, Site]:
    """O1 senaryosunun ortak kurulumu: 600 onaylı geçmiş + 400'lük taslak satır
    yazılır, SONRA kota 1.000 → 500'e düşürülür. Artık satır kotayı zaten aşmış
    durumdadır (600 + 400 > 500)."""
    payment_id, item, site, _ = ortam
    ilk = await client.put(
        f"/progress-payments/{payment_id}/lines",
        json={"lines": [_satir(item.id, site.id, "400")]},
        headers=admin_headers,
    )
    assert ilk.status_code == 200, ilk.text
    await _kotayi_dusur(seeded_db, item, site, "500")
    return payment_id, item, site


async def test_kota_sonradan_dusunce_azaltma_serbest(
    client: AsyncClient,
    admin_headers: dict[str, str],
    onayli_gecmisli_ortam: tuple[uuid.UUID, EmployerContractItem, Site, EmployerContractItem],
    seeded_db: AsyncSession,
) -> None:
    """O1 (kullanıcı kararı 2026-07-31): kota kontrolü YALNIZ ARTIŞTA koşar.
    Kota sonradan düşürülmüşse kullanıcı miktarı AZALTABİLMELİDİR — aksi hâlde
    taslak kilitlenir, düzeltilemez."""
    payment_id, item, site = await _kotasi_dusmus_taslak(
        client, admin_headers, onayli_gecmisli_ortam, seeded_db
    )
    yanit = await client.put(
        f"/progress-payments/{payment_id}/lines",
        json={"lines": [_satir(item.id, site.id, "300")]},
        headers=admin_headers,
    )
    assert yanit.status_code == 200, yanit.text
    assert Decimal(yanit.json()["lines"][0]["quantity"]) == Decimal("300")


async def test_kota_sonradan_dusunce_sifir_serbest(
    client: AsyncClient,
    admin_headers: dict[str, str],
    onayli_gecmisli_ortam: tuple[uuid.UUID, EmployerContractItem, Site, EmployerContractItem],
    seeded_db: AsyncSession,
) -> None:
    """O1 sınır hâli: `0` her zaman serbesttir (OLU 172 ile de tutarlı)."""
    payment_id, item, site = await _kotasi_dusmus_taslak(
        client, admin_headers, onayli_gecmisli_ortam, seeded_db
    )
    yanit = await client.put(
        f"/progress-payments/{payment_id}/lines",
        json={"lines": [_satir(item.id, site.id, "0")]},
        headers=admin_headers,
    )
    assert yanit.status_code == 200, yanit.text
    assert Decimal(yanit.json()["lines"][0]["quantity"]) == Decimal("0")


async def test_kota_sonradan_dusunce_artis_yine_422(
    client: AsyncClient,
    admin_headers: dict[str, str],
    onayli_gecmisli_ortam: tuple[uuid.UUID, EmployerContractItem, Site, EmployerContractItem],
    seeded_db: AsyncSession,
) -> None:
    """O1'in SINIRI: inceltme yalnız azaltmayı serbest bırakır — miktarı ARTIRARAK
    kotayı geçmek yine sert 422'dir."""
    payment_id, item, site = await _kotasi_dusmus_taslak(
        client, admin_headers, onayli_gecmisli_ortam, seeded_db
    )
    yanit = await client.put(
        f"/progress-payments/{payment_id}/lines",
        json={"lines": [_satir(item.id, site.id, "401")]},
        headers=admin_headers,
    )
    assert yanit.status_code == 422, yanit.text
    assert yanit.json()["detail"] == guards.QUANTITY_EXCEEDS_QUOTA


# --- §6.6 "Önceki" kolonu ONAYLI evrakta (H5 denetimi Y2) ---


async def test_onayli_hakedisin_detayinda_kendi_miktari_onceki_sayilmaz(
    client: AsyncClient,
    admin_headers: dict[str, str],
    onayli_gecmisli_ortam: tuple[uuid.UUID, EmployerContractItem, Site, EmployerContractItem],
    seeded_db: AsyncSession,
) -> None:
    """`repository.list_prior_completed_payments` filtresi `sequence_no <` OLMALI,
    `<=` DEĞİL. Fark yalnız ONAYLANMIŞ hakedişin DETAYINDA görünür: `<=` olsaydı
    hakediş KENDİNİ "önceki" sayar, `previous_quantity` 600 yerine 1.000,
    `cumulative_quantity` 1.000 yerine 1.400 olurdu (§6.6 ihlali).

    Durum geçiş ucu H6'da olduğu için durum doğrudan DB üzerinden ayarlanır —
    meşru kurulumdur, test edilen davranış geçiş değil türev hesaptır.
    """
    payment_id, item, site, _ = onayli_gecmisli_ortam
    yazma = await client.put(
        f"/progress-payments/{payment_id}/lines",
        json={"lines": [_satir(item.id, site.id, "400")]},
        headers=admin_headers,
    )
    assert yazma.status_code == 200, yazma.text

    payment = await seeded_db.get(ProgressPayment, payment_id)
    assert payment is not None
    payment.status = ProgressPaymentStatus.approved
    await seeded_db.flush()
    # `updated_at` sunucu tarafında `onupdate` ile tazelenir; flush onu EXPIRE
    # eder. Açık `refresh` olmadan yanıt kurulurken senkron bağlamda lazy IO
    # denenir (`MissingGreenlet`).
    await seeded_db.refresh(payment)

    detay = await client.get(f"/progress-payments/{payment_id}", headers=admin_headers)
    assert detay.status_code == 200, detay.text
    satir = detay.json()["lines"][0]
    assert Decimal(satir["previous_quantity"]) == Decimal("600")
    assert Decimal(satir["cumulative_quantity"]) == Decimal("1000")


# --- Bağı kopmuş satır: sessiz atlama YOK (spec §10/7, H5 denetimi O3) ---


async def test_bagi_kopmus_satir_dusunce_yanitta_bildirilir(
    client: AsyncClient,
    admin_headers: dict[str, str],
    taslak_hakedis: uuid.UUID,
    hakedis_santiyesi: Site,
    hakedis_kalemi: tuple[EmployerContractItem, str],
    ikinci_dagitilmis_kalem: EmployerContractItem,
    seeded_db: AsyncSession,
) -> None:
    """Kalemi silinmiş satır (`contract_item_id IS NULL`) gövdeden ADRESLENEMEZ
    ve ilk kaydetmede düşer — bu kaçınılmazdır ama SESSİZ OLAMAZ: yanıt kaç
    satırın düştüğünü bildirir (spec §10/7)."""
    item, _ = hakedis_kalemi
    await client.put(
        f"/progress-payments/{taslak_hakedis}/lines",
        json={
            "lines": [
                _satir(item.id, hakedis_santiyesi.id, "100"),
                _satir(ikinci_dagitilmis_kalem.id, hakedis_santiyesi.id, "50"),
            ]
        },
        headers=admin_headers,
    )
    stmt = select(ProgressPaymentLine).where(
        ProgressPaymentLine.payment_id == taslak_hakedis,
        ProgressPaymentLine.contract_item_id == ikinci_dagitilmis_kalem.id,
    )
    kopan = (await seeded_db.execute(stmt)).scalar_one()
    kopan.contract_item_id = None
    await seeded_db.flush()

    yanit = await client.put(
        f"/progress-payments/{taslak_hakedis}/lines",
        json={"lines": [_satir(item.id, hakedis_santiyesi.id, "120")]},
        headers=admin_headers,
    )
    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["dropped_orphan_count"] == 1
    assert len(yanit.json()["lines"]) == 1


async def test_bagi_kopmus_satir_yokken_bildirim_sifir(
    client: AsyncClient,
    admin_headers: dict[str, str],
    taslak_hakedis: uuid.UUID,
    hakedis_santiyesi: Site,
    hakedis_kalemi: tuple[EmployerContractItem, str],
) -> None:
    """Normal kaydetmede alan `0`'dır — frontend her yanıtta uyarı göstermez."""
    item, _ = hakedis_kalemi
    yanit = await client.put(
        f"/progress-payments/{taslak_hakedis}/lines",
        json={"lines": [_satir(item.id, hakedis_santiyesi.id, "10")]},
        headers=admin_headers,
    )
    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["dropped_orphan_count"] == 0


# --- §6.5/3-4 sahiplik (IDOR yüzeyi) ---


async def test_baska_projenin_santiyesi_422(
    client: AsyncClient,
    admin_headers: dict[str, str],
    taslak_hakedis: uuid.UUID,
    hakedis_kalemi: tuple[EmployerContractItem, str],
    ikinci_proje_santiyesi: Site,
) -> None:
    item, _ = hakedis_kalemi
    yanit = await client.put(
        f"/progress-payments/{taslak_hakedis}/lines",
        json={"lines": [_satir(item.id, ikinci_proje_santiyesi.id, "10")]},
        headers=admin_headers,
    )
    assert yanit.status_code == 422, yanit.text
    assert yanit.json()["detail"] == guards.SITE_PROJECT_MISMATCH


async def test_baska_projenin_kalemi_422(
    client: AsyncClient,
    admin_headers: dict[str, str],
    taslak_hakedis: uuid.UUID,
    hakedis_santiyesi: Site,
    ikinci_proje_kalemi: EmployerContractItem,
) -> None:
    yanit = await client.put(
        f"/progress-payments/{taslak_hakedis}/lines",
        json={"lines": [_satir(ikinci_proje_kalemi.id, hakedis_santiyesi.id, "10")]},
        headers=admin_headers,
    )
    assert yanit.status_code == 422, yanit.text
    assert yanit.json()["detail"] == guards.ITEM_PROJECT_MISMATCH


async def test_ayni_hucre_iki_kez_gonderilirse_409(
    client: AsyncClient,
    admin_headers: dict[str, str],
    taslak_hakedis: uuid.UUID,
    hakedis_santiyesi: Site,
    hakedis_kalemi: tuple[EmployerContractItem, str],
    seeded_db: AsyncSession,
) -> None:
    """Kısmi benzersiz indeks (`payment`, `item`, `site`) `IntegrityError`'a
    DÜŞMEDEN guards'ta yakalanır (spec §9.7: `DUPLICATE_CELL` = 409)."""
    item, _ = hakedis_kalemi
    yanit = await client.put(
        f"/progress-payments/{taslak_hakedis}/lines",
        json={
            "lines": [
                _satir(item.id, hakedis_santiyesi.id, "10"),
                _satir(item.id, hakedis_santiyesi.id, "20"),
            ]
        },
        headers=admin_headers,
    )
    assert yanit.status_code == 409, yanit.text
    assert yanit.json()["detail"] == guards.DUPLICATE_CELL
    assert await _satir_sayisi(seeded_db, taslak_hakedis) == 0


# --- FF kilidi (spec §10/5) ---
