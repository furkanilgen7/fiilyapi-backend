"""SA T2 — tedarikçi kataloğu uçları (`/suppliers`).

Spec: `docs/superpowers/specs/2026-08-12-sa-satinalma-design.md` §2, §4, §5.
Mockup: `Satınalma - Tedarikçiler.dc.html` (**TED**).

Bu dosyanın DONDURDUĞU kararlar:

1. **DELETE UCU YOKTUR** (spec §4). Kullanımdan kaldırma `PATCH {"is_active":
   false}` iledir; yol tanımlı olmadığı için FastAPI **405** döner ve bu bir
   BEKÇİ TESTİYLE kilitlidir.
2. **PUAN/PERFORMANS ALANI YOKTUR** (spec §5): TED 55-58'deki yıldızların giriş
   yüzeyi hiçbir ekranda yoktur. Adres/e-posta/IBAN de yoktur. Gövdede
   gönderilseler bile şema onları YOK SAYAR — bekçi testiyle kilitli.
3. **"Bu Yıl Toplam Sipariş" TÜREVDİR** (TED 52): kolon değildir, içinde
   bulunulan yılın siparişlerinden hesaplanır ve **GÖRÜNEN projelerle**
   sınırlıdır — görünmeyen projenin siparişi tutara girmez.
4. Kapı `procurement` iznidir: okuma `view`, yazma **`full`**. Şef (`_REQ`)
   okur ama tedarikçi AÇAMAZ — katalog satınalmanın işidir.
"""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.modules.procurement.models import PurchaseOrder, Supplier

pytestmark = pytest.mark.asyncio


def _govde(**alanlar) -> dict:
    govde = {
        "name": "Demirsan A.Ş.",
        "category": "Demir-Çelik",
        "tax_no": "1234567890",
        "phone": "0212 555 00 01",
        "payment_terms": "days_30",
    }
    govde.update(alanlar)
    return govde


async def _siparis(session, supplier, project, actor_id, *, tutar: str, yil: int) -> PurchaseOrder:
    """Türev testinin veri kaynağı — sipariş UCU T3'ündür, burada satır elle yazılır.

    "Bu yıl" ölçütü `created_at`tir: `purchase_orders`ta ayrı bir sipariş TARİHİ
    kolonu YOKTUR (spec §2) ve uydurulmaz.
    """
    order = PurchaseOrder(
        order_no=f"SP-{yil}-{uuid.uuid4().hex[:4]}",
        supplier_id=supplier.id,
        project_id=project.id,
        total_amount=Decimal(tutar),
        created_by_user_id=actor_id,
        created_at=datetime(yil, 6, 15, tzinfo=UTC),
    )
    session.add(order)
    await session.flush()
    return order


# --- Mutlu yol: TED kartının alanları birebir ---


async def test_tedarikci_ted_alanlariyla_olusturulur(client, satinalma_headers, seeded_db):
    """TED 44-52: ad · kategori · VKN · telefon · ödeme vadesi · aktiflik."""
    yanit = await client.post("/suppliers", json=_govde(), headers=satinalma_headers)

    assert yanit.status_code == 201, yanit.text
    govde = yanit.json()
    assert govde["name"] == "Demirsan A.Ş."
    assert govde["category"] == "Demir-Çelik"
    assert govde["tax_no"] == "1234567890"
    assert govde["phone"] == "0212 555 00 01"
    assert govde["payment_terms"] == "days_30"
    assert govde["is_active"] is True

    sayim = (await seeded_db.execute(select(func.count()).select_from(Supplier))).scalar_one()
    assert sayim == 1


async def test_yalniz_ad_ve_vade_ile_olusturulur(client, satinalma_headers):
    """TED'de yalnız ad ve vade zorunludur; kategori/VKN/telefon isteğe bağlıdır."""
    yanit = await client.post(
        "/suppliers",
        json={"name": "Ege Demir Sanayi", "payment_terms": "cash"},
        headers=satinalma_headers,
    )
    assert yanit.status_code == 201, yanit.text
    assert yanit.json()["category"] is None


async def test_detay_ucu_kartin_kunyesini_dondurur(client, satinalma_headers, tedarikci_fabrikasi):
    tedarikci = await tedarikci_fabrikasi("Demirsan A.Ş.")
    yanit = await client.get(f"/suppliers/{tedarikci.id}", headers=satinalma_headers)
    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["name"] == "Demirsan A.Ş."


async def test_olmayan_tedarikci_404(client, satinalma_headers):
    yanit = await client.get(f"/suppliers/{uuid.uuid4()}", headers=satinalma_headers)
    assert yanit.status_code == 404


# --- Pasifleştirme: DELETE YOK ---


async def test_pasiflestirme_patch_ile_yapilir(client, satinalma_headers, tedarikci_fabrikasi):
    tedarikci = await tedarikci_fabrikasi("KarTaş Yapı Market")
    yanit = await client.patch(
        f"/suppliers/{tedarikci.id}", json={"is_active": False}, headers=satinalma_headers
    )
    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["is_active"] is False


async def test_silme_ucu_yoktur_405(client, satinalma_headers, tedarikci_fabrikasi):
    """Spec §4: tedarikçi SİLİNMEZ. Yol tanımlı olmadığı için FastAPI 405 döner.

    Bu bekçi olmadan ileride biri DELETE ekleyebilir ve teklif/sipariş geçmişi
    olan tedarikçi kaydı sessizce yok edilebilirdi.
    """
    tedarikci = await tedarikci_fabrikasi("Elektrotek Ltd.")
    yanit = await client.delete(f"/suppliers/{tedarikci.id}", headers=satinalma_headers)
    assert yanit.status_code == 405


# --- İcat yasağı (spec §5) ---


async def test_puan_ve_adres_alanlari_yok_sayilir(client, satinalma_headers):
    """TED 55-58 yıldızları + adres/e-posta/IBAN: şemada YOKTUR (spec §5).

    Gövdede gönderilseler bile Pydantic onları yok sayar; yanıtta da çıkmazlar.
    """
    yanit = await client.post(
        "/suppliers",
        json=_govde(rating="4.2", address="Sincan OSB", email="x@y.co", iban="TR00"),
        headers=satinalma_headers,
    )
    assert yanit.status_code == 201, yanit.text
    govde = yanit.json()
    for yasak in ("rating", "score", "address", "email", "iban"):
        assert yasak not in govde


# --- Süzgeçler + TB3 sayfalama ---


async def test_liste_arama_kategori_ve_aktiflik_suzgecleri(
    client, satinalma_headers, tedarikci_fabrikasi
):
    await tedarikci_fabrikasi("Demirsan A.Ş.", category="Demir-Çelik")
    await tedarikci_fabrikasi("KarTaş Yapı Market", category="Yapı Malzemeleri")
    await tedarikci_fabrikasi("Elektrotek Ltd.", category="Elektrik", is_active=False)

    async def _adlar(**sorgu) -> list[str]:
        yanit = await client.get("/suppliers", params=sorgu, headers=satinalma_headers)
        assert yanit.status_code == 200, yanit.text
        return [i["name"] for i in yanit.json()["items"]]

    assert await _adlar(q="kartaş") == ["KarTaş Yapı Market"]
    assert await _adlar(category="Demir-Çelik") == ["Demirsan A.Ş."]
    assert await _adlar(is_active=False) == ["Elektrotek Ltd."]
    # Süzgeçsiz liste PASİFİ DE gösterir — sessiz gizleme yok.
    assert len(await _adlar()) == 3


async def test_liste_sayfalama_ve_limit_tavani(client, satinalma_headers, tedarikci_fabrikasi):
    """TB3 standardı: `limit` varsayılan 50, tavan 200; tavan aşımı **422**
    (sessizce kırpılmaz), `total` sayfayı değil SÜZÜLEN KÜMEYİ sayar."""
    for i in range(3):
        await tedarikci_fabrikasi(f"Tedarikçi {i}")

    yanit = await client.get(
        "/suppliers", params={"limit": 2, "offset": 0}, headers=satinalma_headers
    )
    assert yanit.status_code == 200, yanit.text
    govde = yanit.json()
    assert len(govde["items"]) == 2
    assert govde["total"] == 3
    assert (govde["limit"], govde["offset"]) == (2, 0)

    asim = await client.get("/suppliers", params={"limit": 201}, headers=satinalma_headers)
    assert asim.status_code == 422


# --- "Bu Yıl Toplam Sipariş" türevi (TED 52) ---


async def test_bu_yil_toplam_siparis_turevi(
    client,
    satinalma_headers,
    seeded_db,
    tedarikci_fabrikasi,
    gorunen_proje,
    kullanici_kimligi,
):
    """Türev İÇİNDE BULUNULAN YILA aittir: geçen yılın siparişi tutara GİRMEZ."""
    tedarikci = await tedarikci_fabrikasi("Demirsan A.Ş.")
    aktor = await kullanici_kimligi("satinalma@satinalma.co")
    bu_yil = date.today().year
    await _siparis(seeded_db, tedarikci, gorunen_proje, aktor, tutar="1500000.00", yil=bu_yil)
    await _siparis(seeded_db, tedarikci, gorunen_proje, aktor, tutar="900000.00", yil=bu_yil)
    await _siparis(seeded_db, tedarikci, gorunen_proje, aktor, tutar="700000.00", yil=bu_yil - 1)

    yanit = await client.get("/suppliers", headers=satinalma_headers)
    assert yanit.status_code == 200, yanit.text
    kart = yanit.json()["items"][0]
    assert Decimal(kart["orders_total_this_year"]) == Decimal("2400000.00")
    assert kart["orders_count_this_year"] == 2


async def test_siparissiz_tedarikcide_turev_sifirdir(
    client, satinalma_headers, tedarikci_fabrikasi
):
    """Sipariş yoksa değer `null` DEĞİL sıfırdır — ekran "veri yok" ile "hiç
    sipariş verilmedi"yi ayırt etmek zorunda kalmasın."""
    await tedarikci_fabrikasi("Anadolu Demir Çelik")
    yanit = await client.get("/suppliers", headers=satinalma_headers)
    kart = yanit.json()["items"][0]
    assert Decimal(kart["orders_total_this_year"]) == Decimal("0")
    assert kart["orders_count_this_year"] == 0


async def test_gorunmeyen_projenin_siparisi_turebe_girmez(
    client,
    satinalma_headers,
    admin_headers,
    seeded_db,
    tedarikci_fabrikasi,
    gorunen_proje,
    gorunmeyen_proje,
    kullanici_kimligi,
):
    """IDOR: tedarikçi kataloğu GLOBALdir ama PARA görünen projeyle sınırlıdır.

    Süzgeç olmasaydı satınalma sorumlusu, erişimi olmayan projenin harcama
    hacmini tedarikçi kartından okuyabilirdi. Karşı örnek de var: `admin`
    (tüm projeleri görür) İKİ siparişi de sayar.
    """
    tedarikci = await tedarikci_fabrikasi("Demirsan A.Ş.")
    aktor = await kullanici_kimligi("admin@satinalma.co")
    bu_yil = date.today().year
    await _siparis(seeded_db, tedarikci, gorunen_proje, aktor, tutar="100000.00", yil=bu_yil)
    await _siparis(seeded_db, tedarikci, gorunmeyen_proje, aktor, tutar="500000.00", yil=bu_yil)

    kisitli = (await client.get("/suppliers", headers=satinalma_headers)).json()["items"][0]
    assert Decimal(kisitli["orders_total_this_year"]) == Decimal("100000.00")
    assert kisitli["orders_count_this_year"] == 1

    tam = (await client.get("/suppliers", headers=admin_headers)).json()["items"][0]
    assert Decimal(tam["orders_total_this_year"]) == Decimal("600000.00")
    assert tam["orders_count_this_year"] == 2


async def test_turev_tek_toplu_sorgudur_n_arti_bir_yok(
    client,
    satinalma_headers,
    seeded_db,
    tedarikci_fabrikasi,
    gorunen_proje,
    kullanici_kimligi,
):
    """Kart başına sipariş sorgusu AÇILMAZ: tedarikçi sayısı üçe katlanınca
    `suppliers`/`purchase_orders` tablolarına giden sorgu sayısı DEĞİŞMEMELİDİR.

    Ölçüm `before_cursor_execute` iledir (`progress_payments/test_summary.py`
    deseni) — iddia tahmine değil ÖLÇÜME dayanır.
    """
    from contextlib import contextmanager

    from sqlalchemy import event

    from tests.conftest import test_engine

    @contextmanager
    def _sayac():
        ifadeler: list[str] = []

        def kaydet(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
            ifadeler.append(" ".join(statement.split()))

        event.listen(test_engine.sync_engine, "before_cursor_execute", kaydet)
        try:
            yield ifadeler
        finally:
            event.remove(test_engine.sync_engine, "before_cursor_execute", kaydet)

    def _ilgili(ifadeler: list[str]) -> list[str]:
        return [i for i in ifadeler if "suppliers" in i or "purchase_orders" in i]

    aktor = await kullanici_kimligi("satinalma@satinalma.co")
    bu_yil = date.today().year
    tedarikci = await tedarikci_fabrikasi("Demirsan A.Ş.")
    await _siparis(seeded_db, tedarikci, gorunen_proje, aktor, tutar="10.00", yil=bu_yil)

    with _sayac() as ifadeler:
        assert (await client.get("/suppliers", headers=satinalma_headers)).status_code == 200
    tek_kart = len(_ilgili(ifadeler))

    for i in range(2):
        baska = await tedarikci_fabrikasi(f"Ek Tedarikçi {i}")
        await _siparis(seeded_db, baska, gorunen_proje, aktor, tutar="20.00", yil=bu_yil)

    with _sayac() as ifadeler:
        assert (await client.get("/suppliers", headers=satinalma_headers)).status_code == 200
    uc_kart = len(_ilgili(ifadeler))

    assert uc_kart == tek_kart, f"N+1: {tek_kart} → {uc_kart}"


# --- Yetki ---


async def test_sef_okur_ama_tedarikci_acamaz(client, sef_headers, tedarikci_fabrikasi):
    """`site_chief` = `_REQ`: okuma `view`i karşılar, yazma `full`ü KARŞILAMAZ."""
    await tedarikci_fabrikasi("Demirsan A.Ş.")
    assert (await client.get("/suppliers", headers=sef_headers)).status_code == 200
    yazma = await client.post("/suppliers", json=_govde(name="Yeni"), headers=sef_headers)
    assert yazma.status_code == 403


async def test_yetkisiz_rol_okumada_bile_403(client, yetkisiz_headers):
    assert (await client.get("/suppliers", headers=yetkisiz_headers)).status_code == 403


# --- Denetim ---


async def test_mutasyonlar_denetime_yazilir(client, satinalma_headers, seeded_db):
    from app.modules.audit.models import AuditLog

    olustur = await client.post("/suppliers", json=_govde(), headers=satinalma_headers)
    assert olustur.status_code == 201, olustur.text
    guncelle = await client.patch(
        f"/suppliers/{olustur.json()['id']}",
        json={"is_active": False},
        headers=satinalma_headers,
    )
    assert guncelle.status_code == 200, guncelle.text

    kayitlar = (
        (await seeded_db.execute(select(AuditLog).order_by(AuditLog.occurred_at))).scalars().all()
    )
    detaylar = [k.detail for k in kayitlar if "Tedarikçi" in (k.detail or "")]
    assert len(detaylar) == 2
    assert "Demirsan A.Ş." in detaylar[0]
