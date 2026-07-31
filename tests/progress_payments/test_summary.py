"""Task H9 — özet ucu (spec §9.6) + `contracts` placeholder'larının gerçek
değere dönmesi + H4'ten devredilen performans temizliği (O1 N+1).

Bu paketin ölçtüğü üç ayrı şey vardır ve karıştırılmamalıdır:

1. **Özet uçlarının SAYILARI** — E14 127-147 / SHK 82-84 altın senaryosu.
2. **Kapsam (§9.0)** — özet toplu (batch) sorgu kullandığı için kapsam
   süzgecinin SQL'de uygulandığı AYRICA doğrulanır: toplu çekimde kapsam
   sızıntısı klasik hatadır.
3. **Toplu çekimin GRUPLAMA doğruluğu** — gruplama anahtarı yanlışsa sayılar
   başka projeye/şantiyeye karışır; bunu yakalayan senaryolar (çok proje, çok
   şantiye, çok hakediş) ile sorgu SAYISI üst sınırı birlikte tutulur.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.progress_payments import repository
from tests.conftest import test_engine

pytestmark = pytest.mark.asyncio


@contextmanager
def _sorgu_sayaci() -> Iterator[list[str]]:
    """İstek boyunca sürücüye giden HER ifadeyi toplar (H4 denetimi O1'in
    ölçüm aracı). `test_concurrency.py`'deki `before_cursor_execute` deseninin
    aynısı — sorgu sayısı iddiaları tahmine değil ÖLÇÜME dayanır."""
    ifadeler: list[str] = []

    def kaydet(conn, cursor, statement, parameters, context, executemany) -> None:  # noqa: ANN001
        ifadeler.append(" ".join(statement.split()))

    event.listen(test_engine.sync_engine, "before_cursor_execute", kaydet)
    try:
        yield ifadeler
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", kaydet)


def _hakedis_sorgulari(ifadeler: list[str]) -> list[str]:
    """Yalnız `progress_payments`/`progress_payment_lines` tablolarına giden
    ifadeler — kimlik doğrulama/izin sorguları sayıma girmez (onlar bu task'ın
    ölçtüğü N+1'den bağımsızdır ve sabittir)."""
    return [i for i in ifadeler if "progress_payment" in i]


# --- 1. Özet ucunun sayıları (spec §9.6) ---


async def test_ozet_e14_altin(
    client: AsyncClient, admin_headers: dict[str, str], dort_onayli_hakedisli_proje: uuid.UUID
) -> None:
    """E14 127-147: bedel 11.200.000 · kümülatif 8.400.000 · %75 · avans
    −1.680.000 (tavana varmamış: < 2.240.000) · teminat −420.000 · net
    6.300.000 · remaining 2.800.000 (E15 89-90)."""
    yanit = await client.get(
        f"/projects/{dort_onayli_hakedisli_proje}/progress-payments/summary",
        headers=admin_headers,
    )
    assert yanit.status_code == 200, yanit.text
    govde = yanit.json()
    assert Decimal(govde["contract_amount"]) == Decimal("11200000")
    assert Decimal(govde["cumulative_gross"]) == Decimal("8400000.00")
    assert Decimal(govde["progress_pct"]) == Decimal("75.00")
    assert Decimal(govde["advance_deduction_total"]) == Decimal("1680000.00")
    assert Decimal(govde["retention_total"]) == Decimal("420000.00")
    assert Decimal(govde["net_total"]) == Decimal("6300000.00")
    assert govde["payment_count"] == 4
    assert govde["pending_count"] == 0
    assert Decimal(govde["remaining"]) == Decimal("2800000.00")


async def test_ozet_sayaclari_shk(
    client: AsyncClient, admin_headers: dict[str, str], karisik_durumlu_proje: uuid.UUID
) -> None:
    """SHK 82 "4 hakediş" (approved+paid) · SHK 84 "Onay Bekleyen 3".

    `draft` HİÇBİR sayaca girmez: ne tamamlanmıştır ne onay beklemektedir.
    """
    govde = (
        await client.get(
            f"/projects/{karisik_durumlu_proje}/progress-payments/summary", headers=admin_headers
        )
    ).json()
    assert govde["payment_count"] == 4
    assert govde["pending_count"] == 3
    assert Decimal(govde["cumulative_gross"]) == Decimal("8400000.00")


async def test_taslak_kumulatife_girmez(
    client: AsyncClient, admin_headers: dict[str, str], taslakli_proje: uuid.UUID
) -> None:
    """Yalnız `approved|paid` sayılır (spec §6.6 `prev` kümesi): 1 onaylı +
    1 taslak hakedişte kümülatif 4.200.000 DEĞİL 2.100.000'dir."""
    govde = (
        await client.get(
            f"/projects/{taslakli_proje}/progress-payments/summary", headers=admin_headers
        )
    ).json()
    assert Decimal(govde["cumulative_gross"]) == Decimal("2100000.00")
    assert govde["payment_count"] == 1


async def test_avans_tavani_ozette_de_uygulanir(
    client: AsyncClient, admin_headers: dict[str, str], avans_tavanina_dayanan_proje: uuid.UUID
) -> None:
    """§6.3 kümülatif tavan: 2 × 800.000 brüt, avans %20, tavan 200.000 →
    kesinti toplamı 160.000 + 40.000 = **200.000** (basit toplam 320.000
    olurdu). Net = 1.600.000 − 200.000 − 80.000 = 1.320.000."""
    govde = (
        await client.get(
            f"/projects/{avans_tavanina_dayanan_proje}/progress-payments/summary",
            headers=admin_headers,
        )
    ).json()
    assert Decimal(govde["cumulative_gross"]) == Decimal("1600000.00")
    assert Decimal(govde["advance_deduction_total"]) == Decimal("200000.00")
    assert Decimal(govde["retention_total"]) == Decimal("80000.00")
    assert Decimal(govde["net_total"]) == Decimal("1320000.00")


async def test_hakedissiz_projede_ozet_sifirlar(
    client: AsyncClient, admin_headers: dict[str, str], sozlesmeli_proje: uuid.UUID
) -> None:
    """Sözleşmesi olan ama hiç hakedişi olmayan proje: kümülatifler 0,
    `progress_pct` 0, `remaining` = sözleşme bedeli."""
    govde = (
        await client.get(
            f"/projects/{sozlesmeli_proje}/progress-payments/summary", headers=admin_headers
        )
    ).json()
    assert Decimal(govde["contract_amount"]) == Decimal("11200000")
    assert Decimal(govde["cumulative_gross"]) == Decimal("0.00")
    assert Decimal(govde["progress_pct"]) == Decimal("0.00")
    assert Decimal(govde["net_total"]) == Decimal("0.00")
    assert govde["payment_count"] == 0
    assert govde["pending_count"] == 0
    assert Decimal(govde["remaining"]) == Decimal("11200000")


async def test_sozlesmesiz_projede_ozet_zarif_duser(
    client: AsyncClient, admin_headers: dict[str, str], sozlesmesiz_proje: uuid.UUID
) -> None:
    """Sözleşmesiz projede bedel bilinmez: `contract_amount`/`progress_pct`/
    `remaining` `None` (§8 zarif düşüş deseni), uç yine 200 döner — E14 sekmesi
    hakedişten önce de açılabilir."""
    yanit = await client.get(
        f"/projects/{sozlesmesiz_proje}/progress-payments/summary", headers=admin_headers
    )
    assert yanit.status_code == 200, yanit.text
    govde = yanit.json()
    assert govde["contract_amount"] is None
    assert govde["progress_pct"] is None
    assert govde["remaining"] is None
    assert Decimal(govde["cumulative_gross"]) == Decimal("0.00")


# --- 2. Kapsam ve izin (spec §9.0, §9.6) ---


async def test_ozet_gorunmeyen_proje_ile_olmayan_id_ayni_yanit(
    client: AsyncClient, kisitli_headers: dict[str, str], gorunmeyen_proje: uuid.UUID
) -> None:
    """Çapraz-proje negatifi: görünmeyen projenin GERÇEK özeti ile var olmayan
    proje kimliği AYIRT EDİLEMEZ 404 döner (spec §9.0)."""
    gercek = await client.get(
        f"/projects/{gorunmeyen_proje}/progress-payments/summary", headers=kisitli_headers
    )
    sahte = await client.get(
        f"/projects/{uuid.uuid4()}/progress-payments/summary", headers=kisitli_headers
    )
    assert gercek.status_code == sahte.status_code == 404
    assert gercek.json() == sahte.json()


async def test_ozet_modul_izni_olmayan_rol_403(
    client: AsyncClient, hr_headers: dict[str, str], sozlesmeli_proje: uuid.UUID
) -> None:
    """Kapı `_VIEW` (spec §9.6): `progress_payments=_N` olan rol GÖRÜNÜRLÜKTEN
    ÖNCE 403 alır."""
    yanit = await client.get(
        f"/projects/{sozlesmeli_proje}/progress-payments/summary", headers=hr_headers
    )
    assert yanit.status_code == 403


async def test_toplu_cekim_kapsam_disina_cikmaz(
    seeded_db: AsyncSession, iki_projeli_ozet_ortami: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """Toplu çekimin kapsam süzgeci **SQL'de** uygulanır: istenmeyen projenin
    hakedişi sonuç sözlüğüne HİÇ girmez (bellekte süzülmez — süzgeç bellekte
    olsaydı görünmeyen projenin satırları önce çekilir, sonra bir yerde
    unutulabilirdi)."""
    a_id, b_id = iki_projeli_ozet_ortami
    gruplar = await repository.list_completed_payments_by_projects(seeded_db, [a_id])
    assert set(gruplar) == {a_id}
    assert b_id not in gruplar
    assert len(gruplar[a_id]) == 2

    bos = await repository.list_completed_payments_by_projects(seeded_db, [])
    assert bos == {}


# --- 3. Toplu çekimin gruplama doğruluğu (O1) ---


async def test_ozet_baska_projenin_hakedisini_saymaz(
    client: AsyncClient,
    admin_headers: dict[str, str],
    iki_projeli_ozet_ortami: tuple[uuid.UUID, uuid.UUID],
) -> None:
    """İki projenin kümülatifleri BİRBİRİNE KARIŞMAZ (gruplama anahtarı
    `project_id`)."""
    a_id, b_id = iki_projeli_ozet_ortami
    a = (
        await client.get(f"/projects/{a_id}/progress-payments/summary", headers=admin_headers)
    ).json()
    b = (
        await client.get(f"/projects/{b_id}/progress-payments/summary", headers=admin_headers)
    ).json()
    assert Decimal(a["cumulative_gross"]) == Decimal("4200000.00")
    assert a["payment_count"] == 2
    assert Decimal(b["cumulative_gross"]) == Decimal("300000.00")
    assert b["payment_count"] == 1


async def test_liste_coklu_proje_hakedisleri_karismaz(
    client: AsyncClient,
    admin_headers: dict[str, str],
    iki_projeli_ozet_ortami: tuple[uuid.UUID, uuid.UUID],
) -> None:
    """Liste ucu TOPLU çekilen geçmişi `project_id`'ye göre gruplar: A
    projesinin 2. hakedişi B projesinin hakedişini "önceki" saymaz. Her satırın
    brütü kendi satırlarından gelir."""
    govde = (await client.get("/progress-payments", headers=admin_headers)).json()
    a_id, b_id = iki_projeli_ozet_ortami
    a_satirlari = [i for i in govde["items"] if i["project_id"] == str(a_id)]
    b_satirlari = [i for i in govde["items"] if i["project_id"] == str(b_id)]
    assert [Decimal(i["gross_total"]) for i in a_satirlari] == [
        Decimal("2100000.00"),
        Decimal("2100000.00"),
    ]
    assert [Decimal(i["gross_total"]) for i in b_satirlari] == [Decimal("300000.00")]
    # A'nın 2. hakedişinde avans tavanı yalnız A'nın 1. hakedişinden beslenir:
    # 2.100.000×%20 = 420.000 kesinti → net = 2.100.000+420.000−420.000−105.000.
    assert Decimal(a_satirlari[1]["net_total"]) == Decimal("1995000.00")


async def test_detay_onceki_kolonu_santiye_bazinda_dogru(
    client: AsyncClient,
    admin_headers: dict[str, str],
    iki_santiyeli_cok_hakedisli_proje: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
    seeded_db: AsyncSession,
) -> None:
    """Aynı kalemin İKİ şantiyeye yazılan satırları toplu çekimde AYRI
    kalmalıdır: 3. hakedişin A satırında "Önceki" 200 (2×100), B satırında
    20 (2×10). Gruplama anahtarı yalnız `contract_item_id` olsaydı ikisi de
    220 olurdu."""
    project_id, a_site_id, b_site_id = iki_santiyeli_cok_hakedisli_proje
    liste = (
        await client.get(f"/progress-payments?project_id={project_id}", headers=admin_headers)
    ).json()["items"]
    ucuncu = next(i for i in liste if i["sequence_no"] == 3)
    detay = (await client.get(f"/progress-payments/{ucuncu['id']}", headers=admin_headers)).json()
    a_satir = next(s for s in detay["lines"] if s["site_id"] == str(a_site_id))
    b_satir = next(s for s in detay["lines"] if s["site_id"] == str(b_site_id))
    assert Decimal(a_satir["previous_quantity"]) == Decimal("200.000")
    assert Decimal(b_satir["previous_quantity"]) == Decimal("20.000")
    assert Decimal(a_satir["cumulative_quantity"]) == Decimal("300.000")
    assert Decimal(b_satir["cumulative_quantity"]) == Decimal("30.000")


# --- 4. Sorgu sayısı regresyonu (H4 denetimi O1) ---


async def test_liste_sorgu_sayisi_hakedis_sayisiyla_buyumez(
    client: AsyncClient,
    admin_headers: dict[str, str],
    seeded_db: AsyncSession,
    karisik_durumlu_proje: uuid.UUID,
    dort_onayli_hakedisli_proje: uuid.UUID,
) -> None:
    """O1: liste ucu hakediş BAŞINA geçmiş sorgusu KOŞMAZ.

    İki ölçüm alınır: yalnız 4 hakedişli proje (filtreli) ve 12 hakedişli tüm
    liste (filtresiz). Hakediş sayısı üç katına çıkarken `progress_payment*`
    sorgu sayısı SABİT kalmalıdır. N+1 geri gelirse ikinci ölçüm birinciden
    büyük çıkar ve bu iddia kırmızı döner.
    """
    with _sorgu_sayaci() as az:
        yanit = await client.get(
            f"/progress-payments?project_id={dort_onayli_hakedisli_proje}", headers=admin_headers
        )
    assert yanit.status_code == 200, yanit.text
    az_sayi = len(_hakedis_sorgulari(az))

    with _sorgu_sayaci() as cok:
        yanit = await client.get("/progress-payments", headers=admin_headers)
    assert yanit.status_code == 200, yanit.text
    assert len(yanit.json()["items"]) == 12
    cok_sayi = len(_hakedis_sorgulari(cok))

    assert cok_sayi == az_sayi, f"hakediş sayısıyla büyüdü: {az_sayi} → {cok_sayi}"
    # Üst sınır: liste + satırları (selectin) + tamamlanmış geçmiş + onların
    # satırları = 4. Sayı sessizce büyümesin diye sabitlenir.
    assert cok_sayi <= 4, f"beklenenden fazla sorgu: {cok_sayi}"


async def test_detay_gecmisi_iki_kez_cekmez(
    client: AsyncClient,
    admin_headers: dict[str, str],
    karisik_durumlu_proje: uuid.UUID,
) -> None:
    """Detay ucu tamamlanmış geçmişi TEK kez okur: `_line_rows`'un "Önceki"
    kolonu ile `_history_state`'in avans zinciri AYNI çekimi paylaşır (O1).
    Ayrı ayrı okunsaydı `progress_payments` SELECT'i iki katına çıkardı."""
    liste = (
        await client.get(
            f"/progress-payments?project_id={karisik_durumlu_proje}", headers=admin_headers
        )
    ).json()["items"]
    hedef = next(i for i in liste if i["sequence_no"] == 8)

    with _sorgu_sayaci() as ifadeler:
        yanit = await client.get(f"/progress-payments/{hedef['id']}", headers=admin_headers)
    assert yanit.status_code == 200, yanit.text

    gecmis_sorgulari = [
        i
        for i in _hakedis_sorgulari(ifadeler)
        if i.startswith("SELECT") and "FROM progress_payments" in i and "status IN" in i
    ]
    assert len(gecmis_sorgulari) == 1, gecmis_sorgulari


async def test_olusturma_yaniti_gorunurlugu_iki_kez_sorgulamaz(
    client: AsyncClient, admin_headers: dict[str, str], sozlesmeli_proje: uuid.UUID
) -> None:
    """O3: `POST` yanıtı detayı ÇÖZÜLMÜŞ `(payment, project)` çiftinden kurar —
    `visible_projects` kapsam sorgusu istek başına BİR kez koşar."""
    with _sorgu_sayaci() as ifadeler:
        yanit = await client.post(
            f"/projects/{sozlesmeli_proje}/progress-payments", json={}, headers=admin_headers
        )
    assert yanit.status_code == 201, yanit.text
    kapsam = [i for i in ifadeler if i.startswith("SELECT") and "FROM projects" in i]
    assert len(kapsam) == 1, kapsam


# --- 5. `contracts` yer tutucularının gerçek değere dönmesi (spec §9.6, §10/4) ---


async def test_sozlesme_listesi_gercek_deger_doner(
    client: AsyncClient, admin_headers: dict[str, str], dort_onayli_hakedisli_proje: uuid.UUID
) -> None:
    """P5 yer tutucusu doldu: `progress_payment_total` artık `MetricPlaceholder`
    DEĞİL düz sayıdır; `progress_pct` §8 finansal ilerlemesidir (spec §9.6).

    Kırıcı değişikliğin kendisi de sabitlenir: gövdede `pending_module`/
    `available` anahtarları KALMAMALIDIR (frontend `pending_module` varlığına
    dallanırsa gerçek değer gizlenirdi — §10/4)."""
    govde = (await client.get("/contracts?type=employer", headers=admin_headers)).json()
    assert Decimal(govde["summary"]["progress_payment_total"]) == Decimal("8400000.00")
    assert "pending_module" not in str(govde["summary"]["progress_payment_total"])

    satir = next(i for i in govde["items"] if i["id"] == str(dort_onayli_hakedisli_proje))
    assert Decimal(satir["progress_pct"]) == Decimal("75.00")
    assert "available" not in str(satir["progress_pct"])


async def test_sozlesme_listesi_hakedissiz_projede_sifir_doner(
    client: AsyncClient, admin_headers: dict[str, str], sozlesmeli_proje: uuid.UUID
) -> None:
    """Hakedişi olmayan sözleşme: ilerleme %0 (bedel dolu) — `None` DEĞİL."""
    govde = (await client.get("/contracts?type=employer", headers=admin_headers)).json()
    satir = next(i for i in govde["items"] if i["id"] == str(sozlesmeli_proje))
    assert Decimal(satir["progress_pct"]) == Decimal("0.00")
    assert Decimal(govde["summary"]["progress_payment_total"]) == Decimal("0.00")


async def test_isveren_detayinda_pending_modules_kuculdu(
    client: AsyncClient, admin_headers: dict[str, str], dort_onayli_hakedisli_proje: uuid.UUID
) -> None:
    """E14 detayı: `progress_payments` yer tutucu listesinden ÇIKTI ve
    `progress_payment_summary` gerçek özeti taşıyor (spec §9.6)."""
    govde = (
        await client.get(f"/projects/{dort_onayli_hakedisli_proje}/contract", headers=admin_headers)
    ).json()
    assert "progress_payments" not in govde["pending_modules"]
    assert govde["pending_modules"] == ["project_schedule", "documents"]
    ozet = govde["progress_payment_summary"]
    assert ozet is not None
    assert Decimal(ozet["cumulative_gross"]) == Decimal("8400000.00")
    assert Decimal(ozet["net_total"]) == Decimal("6300000.00")
    assert ozet["payment_count"] == 4


async def test_sozlesme_listesi_baska_projenin_hakedisini_saymaz(
    client: AsyncClient,
    admin_headers: dict[str, str],
    iki_projeli_ozet_ortami: tuple[uuid.UUID, uuid.UUID],
) -> None:
    """Toplu çekimin gruplaması `contracts` listesinde de doğru: A projesi
    %37,50 (4,2M/11,2M), B projesi %6,00 (300K/5M); özet toplamı ikisinin
    TOPLAMIDIR."""
    a_id, b_id = iki_projeli_ozet_ortami
    govde = (await client.get("/contracts?type=employer", headers=admin_headers)).json()
    a = next(i for i in govde["items"] if i["id"] == str(a_id))
    b = next(i for i in govde["items"] if i["id"] == str(b_id))
    assert Decimal(a["progress_pct"]) == Decimal("37.50")
    assert Decimal(b["progress_pct"]) == Decimal("6.00")
    assert Decimal(govde["summary"]["progress_payment_total"]) == Decimal("4500000.00")


async def test_sozlesme_listesi_sorgu_sayisi_proje_sayisiyla_buyumez(
    client: AsyncClient,
    admin_headers: dict[str, str],
    iki_projeli_ozet_ortami: tuple[uuid.UUID, uuid.UUID],
    dort_onayli_hakedisli_proje: uuid.UUID,
) -> None:
    """`contracts` liste yolu kümülatif brütü TEK toplu sorguyla okur (plan H9
    Adım 3) — proje başına ayrı sorgu koşsaydı sayı 3 projeyle birlikte artardı.
    """
    with _sorgu_sayaci() as ifadeler:
        yanit = await client.get("/contracts?type=employer", headers=admin_headers)
    assert yanit.status_code == 200, yanit.text
    assert len(yanit.json()["items"]) == 3
    # hakediş tablosu + satırları (selectin) = 2.
    assert len(_hakedis_sorgulari(ifadeler)) == 2, _hakedis_sorgulari(ifadeler)


async def test_liste_avans_tavani_baska_projeden_beslenmez(
    client: AsyncClient,
    admin_headers: dict[str, str],
    tavana_dayanan_iki_proje: tuple[uuid.UUID, uuid.UUID],
) -> None:
    """Toplu çekimin gruplaması ve SIRA EŞİĞİ birlikte doğrulanır (M3/M8).

    A#2: brüt 800.000 · avans tavanda kalan 40.000 · teminat 40.000 ·
    KDV 160.000 → net 880.000. Toplu çekim `project_id`'ye göre gruplanmazsa
    B'nin 160.000'i A'nın tavanını tüketir; `sequence_no` eşiği `<` yerine `<=`
    olursa A#2 KENDİNİ "önceki" sayar. Her iki hatada da kesinti 0'a düşer ve
    net 920.000 çıkar — brüt ve teminat DEĞİŞMEDİĞİ için fark yalnız burada
    görünür.
    """
    a_id, _ = tavana_dayanan_iki_proje
    # Süzgeçsiz liste BİLİNÇLİ: `project_id` süzgeci verilirse toplu çekim zaten
    # tek projeye iner ve gruplama hatası GÖRÜNMEZ olur (mutasyon denetimi M3).
    liste = (await client.get("/progress-payments", headers=admin_headers)).json()["items"]
    ikinci = next(i for i in liste if i["project_id"] == str(a_id) and i["sequence_no"] == 2)
    assert Decimal(ikinci["gross_total"]) == Decimal("800000.00")
    assert Decimal(ikinci["net_total"]) == Decimal("880000.00")
