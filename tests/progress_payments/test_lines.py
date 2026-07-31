"""Task H5 — `PUT /progress-payments/{id}/lines`: DEĞİŞTİRME semantiği + §6.5
miktar korkulukları (dağıtım ön şartı, kota tavanı, FF kilidi, sahiplik).

En tehlikeli frontend tuzağı burada test edilir: bu uç **değiştirme (replace)**
semantiğidir (gövdede geçmeyen satır SİLİNİR), P5'in
`PUT …/contract/distribution` **birleştirme (merge)** semantiğinin TERSİDİR
(orada gövdede geçmeyen hücre KORUNUR, silmek için `quantity: null` gerekir).
`test_degistirme_semantigi_govdede_olmayan_satir_silinir` +
`test_bos_govde_tum_satirlari_siler` bu farkı doğrudan doğrular.
"""

import uuid
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.contracts.models import EmployerContractItem
from app.modules.progress_payments import guards
from app.modules.progress_payments.models import ProgressPaymentLine
from app.modules.sites.models import Site

pytestmark = pytest.mark.asyncio


def _satir(item_id, site_id, quantity: str, coefficient: str | None = None) -> dict:
    govde = {
        "contract_item_id": str(item_id),
        "site_id": str(site_id),
        "quantity": quantity,
    }
    if coefficient is not None:
        govde["coefficient"] = coefficient
    return govde


async def _satir_sayisi(session: AsyncSession, payment_id: uuid.UUID) -> int:
    stmt = select(func.count()).where(ProgressPaymentLine.payment_id == payment_id)
    return (await session.execute(stmt)).scalar_one()


# --- Değiştirme semantiği (spec §9.2/§10-2) ---


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


async def test_ff_kapali_sozlesmede_katsayi_422(
    client: AsyncClient,
    admin_headers: dict[str, str],
    ff_kapali_ortam: tuple[uuid.UUID, EmployerContractItem, Site],
) -> None:
    payment_id, item, site = ff_kapali_ortam
    yanit = await client.put(
        f"/progress-payments/{payment_id}/lines",
        json={"lines": [_satir(item.id, site.id, "10", coefficient="1.142")]},
        headers=admin_headers,
    )
    assert yanit.status_code == 422, yanit.text
    assert yanit.json()["detail"] == guards.ESCALATION_DISABLED


async def test_ff_kapali_sozlesmede_birim_katsayi_kabul(
    client: AsyncClient,
    admin_headers: dict[str, str],
    ff_kapali_ortam: tuple[uuid.UUID, EmployerContractItem, Site],
) -> None:
    """Kilit yalnız `!= 1` katsayıya kapalıdır; `1.000` meşrudur."""
    payment_id, item, site = ff_kapali_ortam
    yanit = await client.put(
        f"/progress-payments/{payment_id}/lines",
        json={"lines": [_satir(item.id, site.id, "10", coefficient="1.000")]},
        headers=admin_headers,
    )
    assert yanit.status_code == 200, yanit.text


async def test_ff_acik_sozlesmede_katsayi_kabul(
    client: AsyncClient,
    admin_headers: dict[str, str],
    taslak_hakedis: uuid.UUID,
    hakedis_santiyesi: Site,
    hakedis_kalemi: tuple[EmployerContractItem, str],
) -> None:
    """`has_price_escalation=True` (varsayılan) sözleşmede katsayı serbesttir —
    kilidin kapsamı sözleşmeye bağlıdır, tüm hakedişlere değil."""
    item, _ = hakedis_kalemi
    yanit = await client.put(
        f"/progress-payments/{taslak_hakedis}/lines",
        json={"lines": [_satir(item.id, hakedis_santiyesi.id, "10", coefficient="1.142")]},
        headers=admin_headers,
    )
    assert yanit.status_code == 200, yanit.text
    satir = yanit.json()["lines"][0]
    assert Decimal(satir["coefficient"]) == Decimal("1.142")
    # 1850 × 1,142 = 2.112,70 (K5 kuruş kuralı, spec §6.1)
    assert Decimal(satir["adjusted_unit_price"]) == Decimal("2112.70")


# --- Katsayı öntanımı (spec §4.1) ---


async def test_yeni_satira_default_coefficient_iner(
    client: AsyncClient,
    admin_headers: dict[str, str],
    sozlesmeli_proje: uuid.UUID,
    hakedis_santiyesi: Site,
    hakedis_kalemi: tuple[EmployerContractItem, str],
) -> None:
    item, _ = hakedis_kalemi
    olusturma = await client.post(
        f"/projects/{sozlesmeli_proje}/progress-payments",
        json={"default_coefficient": "1.250"},
        headers=admin_headers,
    )
    payment_id = olusturma.json()["id"]
    yanit = await client.put(
        f"/progress-payments/{payment_id}/lines",
        json={"lines": [_satir(item.id, hakedis_santiyesi.id, "10")]},
        headers=admin_headers,
    )
    assert yanit.status_code == 200, yanit.text
    assert Decimal(yanit.json()["lines"][0]["coefficient"]) == Decimal("1.250")


async def test_gonderilmeyen_katsayi_mevcut_satiri_degistirmez(
    client: AsyncClient,
    admin_headers: dict[str, str],
    taslak_hakedis: uuid.UUID,
    hakedis_santiyesi: Site,
    hakedis_kalemi: tuple[EmployerContractItem, str],
) -> None:
    """§4.1: öntanım YALNIZ yeni satıra iner; var olan satırın katsayısı
    gönderilmediğinde KORUNUR (sessizce 1.000'e düşmez)."""
    item, _ = hakedis_kalemi
    await client.put(
        f"/progress-payments/{taslak_hakedis}/lines",
        json={"lines": [_satir(item.id, hakedis_santiyesi.id, "10", coefficient="1.142")]},
        headers=admin_headers,
    )
    yanit = await client.put(
        f"/progress-payments/{taslak_hakedis}/lines",
        json={"lines": [_satir(item.id, hakedis_santiyesi.id, "20")]},
        headers=admin_headers,
    )
    assert Decimal(yanit.json()["lines"][0]["coefficient"]) == Decimal("1.142")


# --- Sıfır miktar (OLU 172) ---


async def test_sifir_miktarli_satir_kabul(
    client: AsyncClient,
    admin_headers: dict[str, str],
    taslak_hakedis: uuid.UUID,
    hakedis_santiyesi: Site,
    hakedis_kalemi: tuple[EmployerContractItem, str],
    seeded_db: AsyncSession,
) -> None:
    """`0` MEŞRUDUR (sıfır iş) — silme DEĞİL: satır DB'de durur (spec §10/3)."""
    item, _ = hakedis_kalemi
    yanit = await client.put(
        f"/progress-payments/{taslak_hakedis}/lines",
        json={"lines": [_satir(item.id, hakedis_santiyesi.id, "0")]},
        headers=admin_headers,
    )
    assert yanit.status_code == 200, yanit.text
    assert Decimal(yanit.json()["lines"][0]["quantity"]) == Decimal("0")
    assert await _satir_sayisi(seeded_db, taslak_hakedis) == 1


# --- Durum kapısı ve erişim (spec §7, §9.0) ---


async def test_pending_hakediste_lines_409(
    client: AsyncClient, admin_headers: dict[str, str], onay_bekleyen_hakedis: uuid.UUID
) -> None:
    yanit = await client.put(
        f"/progress-payments/{onay_bekleyen_hakedis}/lines",
        json={"lines": []},
        headers=admin_headers,
    )
    assert yanit.status_code == 409, yanit.text
    assert yanit.json()["detail"] == guards.INVALID_STATUS_TRANSITION


async def test_gorunmeyen_hakediste_lines_404_olmayanla_ayni(
    client: AsyncClient, kisitli_headers: dict[str, str], gorunmeyen_hakedis: uuid.UUID
) -> None:
    gercek = await client.put(
        f"/progress-payments/{gorunmeyen_hakedis}/lines",
        json={"lines": []},
        headers=kisitli_headers,
    )
    sahte = await client.put(
        f"/progress-payments/{uuid.uuid4()}/lines", json={"lines": []}, headers=kisitli_headers
    )
    assert gercek.status_code == sahte.status_code == 404
    assert gercek.json() == sahte.json()


async def test_yetkisiz_rol_lines_403(
    client: AsyncClient, hr_headers: dict[str, str], taslak_hakedis: uuid.UUID
) -> None:
    """İK matris satırı `_N`: kapı görünürlükten ÖNCE çalışır → 403."""
    yanit = await client.put(
        f"/progress-payments/{taslak_hakedis}/lines", json={"lines": []}, headers=hr_headers
    )
    assert yanit.status_code == 403
