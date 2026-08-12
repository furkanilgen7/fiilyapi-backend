"""SA T3 — sipariş uçları (spec §4; mockup SIP).

## Bu dosyanın kilitlediği üç karar

1. **Doğrudan (talepsiz) sipariş MEŞRUDUR** (§7 S3, SIP 35): `request_id`
   nullable'dır ve SP-035'in talep karşılığı yoktur.
2. **Gövde `request_id` KABUL ETMEZ.** Talebe bağlı siparişin TEK yolu
   `select-and-order`dır; POST talebe bağlanabilseydi durum makinesi (talep →
   `ordered`) atlanır ve talebi hâlâ `quote_wait` görünen bir sipariş doğardı.
3. **`delivered`e ELLE geçilmez** — o damgayı stok girişi atar (§7 S4, T4).
   PATCH ile denenirse 409.
"""

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.modules.procurement.models import PurchaseOrder, PurchaseOrderStatus

_YOL = "/purchase-orders"


def _govde(project_id, supplier_id, **alanlar) -> dict:
    body = {
        "project_id": str(project_id),
        "supplier_id": str(supplier_id),
        "total_amount": "185000.00",
        "expected_delivery": "2026-09-15",
    }
    body.update(alanlar)
    return body


# --- Doğrudan sipariş (POST) ---


async def test_dogrudan_siparis_acilir(
    client, satinalma_headers, gorunen_proje, tedarikci_fabrikasi
):
    from datetime import date

    tedarikci = await tedarikci_fabrikasi("Demirsan A.Ş.")

    yanit = await client.post(
        _YOL, json=_govde(gorunen_proje.id, tedarikci.id, note="Acil"), headers=satinalma_headers
    )

    assert yanit.status_code == 201, yanit.text
    govde = yanit.json()
    assert govde["order_no"].startswith(f"SP-{date.today().year}-")
    assert govde["request_id"] is None, "talepsiz sipariş MEŞRU (§7 S3)"
    assert govde["quote_id"] is None
    assert govde["status"] == "approved"
    assert Decimal(govde["total_amount"]) == Decimal("185000.00")
    assert govde["supplier_name"] == "Demirsan A.Ş."
    assert govde["note"] == "Acil"


async def test_govdedeki_request_id_YOK_SAYILIR(
    client, satinalma_headers, gorunen_proje, tedarikci_fabrikasi, talep_fabrikasi, sef_headers
):
    """Talebe bağlanmanın TEK yolu `select-and-order`dır (modül docstring'i)."""
    talep = await talep_fabrikasi(gorunen_proje, lines=[("1.000", "10.00")])
    tedarikci = await tedarikci_fabrikasi("Demirsan A.Ş.")

    yanit = await client.post(
        _YOL,
        json=_govde(gorunen_proje.id, tedarikci.id, request_id=str(talep.id)),
        headers=satinalma_headers,
    )

    assert yanit.status_code == 201, yanit.text
    assert yanit.json()["request_id"] is None


@pytest.mark.parametrize(
    ("alan", "deger", "beklenen"),
    [
        # Gövde içi VARLIK referansı → 404 (ST §4b kanonu).
        ("project_id", "00000000-0000-0000-0000-000000000000", 404),
        ("supplier_id", "00000000-0000-0000-0000-000000000000", 404),
        # Biçim/kural ihlali → 422 (kanonun karşı örneği).
        ("total_amount", "-1.00", 422),
    ],
)
async def test_siparis_govde_kanonu(
    client, satinalma_headers, gorunen_proje, tedarikci_fabrikasi, alan, deger, beklenen
):
    tedarikci = await tedarikci_fabrikasi("Demirsan A.Ş.")
    govde = _govde(gorunen_proje.id, tedarikci.id)
    govde[alan] = deger

    yanit = await client.post(_YOL, json=govde, headers=satinalma_headers)

    assert yanit.status_code == beklenen, (alan, yanit.text)


async def test_gorunmeyen_projeye_siparis_404(
    client, satinalma_headers, gorunmeyen_proje, tedarikci_fabrikasi
):
    """IDOR: görünmeyen proje ile OLMAYAN proje aynı gövdeyi alır."""
    tedarikci = await tedarikci_fabrikasi("Demirsan A.Ş.")

    yanit = await client.post(
        _YOL, json=_govde(gorunmeyen_proje.id, tedarikci.id), headers=satinalma_headers
    )

    assert yanit.status_code == 404, yanit.text
    assert yanit.json()["detail"] == "Seçilen proje bulunamadı"


async def test_siparis_yazimi_full_kapisi_ister(
    client, sef_headers, gorunen_proje, tedarikci_fabrikasi
):
    tedarikci = await tedarikci_fabrikasi("Demirsan A.Ş.")

    yanit = await client.post(
        _YOL, json=_govde(gorunen_proje.id, tedarikci.id), headers=sef_headers
    )

    assert yanit.status_code == 403, yanit.text


# --- Liste ve detay ---


async def test_liste_suzgecleri_ANDlidir(
    client, satinalma_headers, gorunen_proje, tedarikci_fabrikasi, siparis_fabrikasi
):
    demirsan = await tedarikci_fabrikasi("Demirsan A.Ş.")
    beton = await tedarikci_fabrikasi("Beton A.Ş.")
    await siparis_fabrikasi(gorunen_proje, demirsan, note="çimento sevkiyatı")
    await siparis_fabrikasi(
        gorunen_proje, demirsan, status=PurchaseOrderStatus.in_transit, note="demir"
    )
    await siparis_fabrikasi(gorunen_proje, beton, note="çimento harici")

    async def _sayi(**sorgu) -> int:
        yanit = await client.get(_YOL, params=sorgu, headers=satinalma_headers)
        assert yanit.status_code == 200, yanit.text
        return yanit.json()["total"]

    assert await _sayi() == 3
    assert await _sayi(status="in_transit") == 1
    assert await _sayi(supplier_id=str(demirsan.id)) == 2
    assert await _sayi(supplier_id=str(demirsan.id), status="approved") == 1
    assert await _sayi(project_id=str(gorunen_proje.id)) == 3
    # `q` sipariş NUMARASI ve NOT üzerinde arar (SIP tablosu ikisini de basar).
    assert await _sayi(q="çimento") == 2


async def test_liste_kapsam_suzgeci_gorunmeyen_projeyi_gizler(
    client, satinalma_headers, gorunmeyen_proje, tedarikci_fabrikasi, siparis_fabrikasi
):
    await siparis_fabrikasi(gorunmeyen_proje, await tedarikci_fabrikasi("Demirsan A.Ş."))

    yanit = await client.get(_YOL, headers=satinalma_headers)

    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["total"] == 0, "görünmeyen projenin siparişi `total`a da girmez"


async def test_liste_TB3_sayfalamasi(
    client, satinalma_headers, gorunen_proje, tedarikci_fabrikasi, siparis_fabrikasi
):
    tedarikci = await tedarikci_fabrikasi("Demirsan A.Ş.")
    for _ in range(3):
        await siparis_fabrikasi(gorunen_proje, tedarikci)

    sayfa = await client.get(_YOL, params={"limit": 2, "offset": 0}, headers=satinalma_headers)
    assert sayfa.status_code == 200, sayfa.text
    assert len(sayfa.json()["items"]) == 2
    assert sayfa.json()["total"] == 3
    assert sayfa.json()["limit"] == 2

    # Tavan aşımı sessizce KIRPILMAZ (TB3 standardı).
    assert (
        await client.get(_YOL, params={"limit": 201}, headers=satinalma_headers)
    ).status_code == 422


async def test_liste_sorgu_sayisi_SATIR_SAYISINDAN_BAGIMSIZDIR(
    client, satinalma_headers, gorunen_proje, tedarikci_fabrikasi, siparis_fabrikasi
):
    """N+1 bekçisi: mutlak sorgu SAYISI değil ÖLÇEKLENMESİ ölçülür.

    Tedarikçi adı ve talep numarası satır başına `session.get` ile çözülseydi
    6 satırlık sayfa, 2 satırlık sayfadan 8 sorgu fazla açardı. JOIN sayesinde
    iki istek AYNI sayıda sorgu koşar. Mutlak bir tavan yazılsaydı test,
    kimlik/izin katmanının ilgisiz bir değişiminde kırılırdı.
    """
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    tedarikci = await tedarikci_fabrikasi("Demirsan A.Ş.")
    for _sira in range(6):
        await siparis_fabrikasi(gorunen_proje, tedarikci)

    sayac = {"n": 0}

    def _say(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            sayac["n"] += 1

    async def _olc(limit: int) -> tuple[int, int]:
        sayac["n"] = 0
        event.listen(Engine, "before_cursor_execute", _say)
        try:
            yanit = await client.get(_YOL, params={"limit": limit}, headers=satinalma_headers)
        finally:
            event.remove(Engine, "before_cursor_execute", _say)
        assert yanit.status_code == 200, yanit.text
        return len(yanit.json()["items"]), sayac["n"]

    iki_satir, iki_sorgu = await _olc(2)
    alti_satir, alti_sorgu = await _olc(6)

    assert (iki_satir, alti_satir) == (2, 6)
    assert iki_sorgu == alti_sorgu, (iki_sorgu, alti_sorgu)


async def test_detay_ve_gorunmeyen_siparis_404(
    client,
    satinalma_headers,
    gorunen_proje,
    gorunmeyen_proje,
    tedarikci_fabrikasi,
    siparis_fabrikasi,
):
    tedarikci = await tedarikci_fabrikasi("Demirsan A.Ş.")
    gorunen = await siparis_fabrikasi(gorunen_proje, tedarikci)
    gizli = await siparis_fabrikasi(gorunmeyen_proje, tedarikci)

    ok = await client.get(f"{_YOL}/{gorunen.id}", headers=satinalma_headers)
    assert ok.status_code == 200, ok.text
    assert ok.json()["order_no"] == gorunen.order_no

    yasak = await client.get(f"{_YOL}/{gizli.id}", headers=satinalma_headers)
    assert yasak.status_code == 404, yasak.text
    assert yasak.json()["detail"] == "Sipariş bulunamadı"


# --- Durum makinesi (PATCH) ---


async def test_approved_in_transite_gecer(
    client, satinalma_headers, seeded_db, gorunen_proje, tedarikci_fabrikasi, siparis_fabrikasi
):
    siparis = await siparis_fabrikasi(gorunen_proje, await tedarikci_fabrikasi("Demirsan A.Ş."))

    yanit = await client.patch(
        f"{_YOL}/{siparis.id}", json={"status": "in_transit"}, headers=satinalma_headers
    )

    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["status"] == "in_transit"
    await seeded_db.refresh(siparis)
    assert siparis.status is PurchaseOrderStatus.in_transit


def test_siparis_matrisi_TAM_OLARAK_tek_gecis_tanimlar():
    """🛑 Bu test bir MUTASYON DENETİMİ bulgusudur.

    Aşağıdaki `test_siparis_matrisi_disi_her_gecis_409` parametrelerini
    TABLONUN KENDİSİNDEN üretir — yani tabloya `(in_transit, delivered)`
    eklenirse o çift parametrelerden DÜŞER ve test sessizce yeşil kalır
    (denetimde bizzat görüldü). Tablonun İÇERİĞİ bu yüzden ayrıca ve
    LİTERAL olarak kilitlenir; talep tarafındaki karşılığı
    `test_matris_tam_olarak_dort_gecis_tanimlar`tır.
    """
    from app.modules.procurement import transitions

    assert transitions.ORDER_TRANSITIONS == frozenset(
        {(PurchaseOrderStatus.approved, PurchaseOrderStatus.in_transit)}
    )


def _matris_disi_siparis_ciftleri():
    from app.modules.procurement import transitions

    return [
        (kaynak, hedef)
        for kaynak in PurchaseOrderStatus
        for hedef in PurchaseOrderStatus
        if (kaynak, hedef) not in transitions.ORDER_TRANSITIONS
    ]


@pytest.mark.parametrize(("kaynak", "hedef"), _matris_disi_siparis_ciftleri())
async def test_siparis_matrisi_disi_her_gecis_409(
    client,
    satinalma_headers,
    gorunen_proje,
    tedarikci_fabrikasi,
    siparis_fabrikasi,
    kaynak,
    hedef,
):
    """`in_transit → delivered` DAHİL: teslim damgasını stok girişi atar (§7 S4).

    Elle `delivered` yapılabilseydi hiç mal girmemiş bir sipariş teslim
    görünür ve stok bakiyesiyle satınalma kaydı sessizce ayrışırdı.
    """
    siparis = await siparis_fabrikasi(
        gorunen_proje, await tedarikci_fabrikasi("Demirsan A.Ş."), status=kaynak
    )

    yanit = await client.patch(
        f"{_YOL}/{siparis.id}", json={"status": hedef.value}, headers=satinalma_headers
    )

    assert yanit.status_code == 409, (kaynak, hedef, yanit.text)
    assert yanit.json()["detail"] == "Siparişin durumu bu işleme uygun değil"


async def test_patch_durumsuz_alanlari_gunceller(
    client, satinalma_headers, gorunen_proje, tedarikci_fabrikasi, siparis_fabrikasi
):
    """`status` göndermemek durumu DEĞİŞTİRMEZ — not/tarih düzeltmesi serbesttir."""
    siparis = await siparis_fabrikasi(
        gorunen_proje,
        await tedarikci_fabrikasi("Demirsan A.Ş."),
        status=PurchaseOrderStatus.in_transit,
    )

    yanit = await client.patch(
        f"{_YOL}/{siparis.id}",
        json={"note": "Sevkiyat gecikti", "expected_delivery": "2026-10-01"},
        headers=satinalma_headers,
    )

    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["status"] == "in_transit"
    assert yanit.json()["note"] == "Sevkiyat gecikti"
    assert yanit.json()["expected_delivery"] == "2026-10-01"


async def test_gorunmeyen_siparise_patch_404(
    client, satinalma_headers, gorunmeyen_proje, tedarikci_fabrikasi, siparis_fabrikasi
):
    """Kapsam süzgeci DURUM kontrolünden ÖNCE koşar."""
    siparis = await siparis_fabrikasi(gorunmeyen_proje, await tedarikci_fabrikasi("Demirsan A.Ş."))

    yanit = await client.patch(
        f"{_YOL}/{siparis.id}", json={"status": "in_transit"}, headers=satinalma_headers
    )

    assert yanit.status_code == 404, yanit.text


# --- Açılmayan uç ---


async def test_siparis_silme_ucu_yoktur_405(
    client, admin_headers, gorunen_proje, tedarikci_fabrikasi, siparis_fabrikasi
):
    """Sipariş SİLİNMEZ: verilmiş bir sipariş bir OLAYDIR, geri alınması iptal
    akışı ister ve o akış hiçbir mockup'ta yoktur."""
    siparis = await siparis_fabrikasi(gorunen_proje, await tedarikci_fabrikasi("Demirsan A.Ş."))

    yanit = await client.delete(f"{_YOL}/{siparis.id}", headers=admin_headers)

    assert yanit.status_code == 405, yanit.text


# --- Denetim ---


async def test_siparis_yazmalari_denetim_satiri_yazar(
    client, satinalma_headers, seeded_db, gorunen_proje, tedarikci_fabrikasi
):
    from app.modules.audit.models import AuditLog

    tedarikci = await tedarikci_fabrikasi("Demirsan A.Ş.")
    once = len((await seeded_db.execute(select(AuditLog))).scalars().all())

    olustur = await client.post(
        _YOL, json=_govde(gorunen_proje.id, tedarikci.id), headers=satinalma_headers
    )
    assert olustur.status_code == 201, olustur.text
    siparis_id = olustur.json()["id"]
    assert (
        await client.patch(
            f"{_YOL}/{siparis_id}", json={"status": "in_transit"}, headers=satinalma_headers
        )
    ).status_code == 200

    assert len((await seeded_db.execute(select(AuditLog))).scalars().all()) == once + 2
    assert (
        await seeded_db.execute(select(PurchaseOrder).where(PurchaseOrder.id == siparis_id))
    ).scalar_one() is not None
