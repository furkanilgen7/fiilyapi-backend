"""URL-4 — makine kartı ve kira hakedişi okunabilir anahtarla açılır.

## İki rota, iki slug kaynağı (ikisi de ÖLÇÜLDÜ)

* `makine/[id]` -> `equipment.slug` <- **`name`**. `plate_no` NULLABLE'dır
  (`equipment/models/core.py:140`), yani anahtar OLAMAZ: plakasız her makine
  URL'siz kalırdı.
* `makine/kira/[invoiceId]` -> `equipment_rental_invoices.slug` <-
  **`invoice_no`**. Mockup ÖLÇÜLDÜ (`Makine - Kira Hakedişi Liste.dc.html`):
  listede tanımlayıcı olarak YALNIZ `Fatura No` sütunu vardır, hakediş sıra
  numarası sütunu HİÇ YOKTUR; faturası girilmemiş taslak satır ekranda birebir
  `— (kayıt no yok)` basar. Bu yüzden numarasız taslakta slug de NULL'dır —
  uydurulmuş bir taban EKRANDAKİ gerçeği bozardı.

🔴 Kira faturasında UQ `(supplier_id, invoice_no)`dur, yani `invoice_no` ŞİRKET
GENELİ TEKİL DEĞİLDİR ve doğrudan anahtar olarak kullanılamazdı. Slug kolonu
tam olarak bu boşluğu kapatır: iki tedarikçinin aynı numarası `unique_slug` ile
`-2` eki alır ve çözüm hâlâ tek eşitliğe iner
(`test_IKI_TEDARIKCININ_ayni_numarasi_SESSIZCE_CAKISMAZ`).
"""

import uuid
from decimal import Decimal

from sqlalchemy import select

from app.modules.equipment.models import Equipment, EquipmentRentalInvoice
from app.modules.procurement.models import PaymentTerms, Supplier

from ._mk2_rental_invoice import _fatura_kur

_MAKINE = "/equipment"
_KIRA = "/equipment/rental-invoices"


def _makine_govdesi(name: str) -> dict:
    """`owned` ekipmanda `purchase_amount` ZORUNLUDUR (K2) — tek yerde tutulur."""
    return {
        "name": name,
        "category": "machinery",
        "ownership": "owned",
        "purchase_amount": "100000.00",
    }


async def _tedarikci(session, name: str) -> Supplier:
    supplier = Supplier(name=name, payment_terms=PaymentTerms.cash)
    session.add(supplier)
    await session.flush()
    return supplier


# =========================================================================== #
# 1. MAKİNE KARTI — `equipment.slug` <- `name`
# =========================================================================== #


async def test_makine_olustururken_TURKCE_ad_sluglanir(client, admin_headers) -> None:
    resp = await client.post(
        _MAKINE,
        json=_makine_govdesi("Beko Loder Şantiye"),
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["slug"] == "beko-loder-santiye"


async def test_makine_uuid_ve_slug_AYNI_govdeyi_doner(client, admin_headers) -> None:
    olusan = await client.post(
        _MAKINE,
        json=_makine_govdesi("Kule Vinç"),
        headers=admin_headers,
    )
    assert olusan.status_code == 201, olusan.text

    by_uuid = await client.get(f"{_MAKINE}/{olusan.json()['id']}", headers=admin_headers)
    by_slug = await client.get(f"{_MAKINE}/kule-vinc", headers=admin_headers)

    assert by_uuid.status_code == by_slug.status_code == 200, by_slug.text
    assert by_uuid.json() == by_slug.json()


async def test_makine_DETAY_ucu_da_slug_kabul_eder(client, admin_headers) -> None:
    """🔴 Ekran İKİ istek atar (`/{id}` + `/{id}/detail`); İKİSİ de anahtar almalı.

    Yalnız biri açılsaydı sayfa yarısı 200 yarısı 404 alır ve kusur ancak
    kullanıcı tıklayınca görülürdü.
    """
    olusan = await client.post(
        _MAKINE,
        json=_makine_govdesi("Paletli Ekskavatör"),
        headers=admin_headers,
    )
    resp = await client.get(f"{_MAKINE}/paletli-ekskavator/detail", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["equipment"]["id"] == olusan.json()["id"]


async def test_makine_adi_degisince_slug_DEGISMEZ(client, admin_headers) -> None:
    olusan = await client.post(
        _MAKINE,
        json=_makine_govdesi("Silindir Bir"),
        headers=admin_headers,
    )
    patch = await client.patch(
        f"{_MAKINE}/{olusan.json()['id']}", json={"name": "Silindir İki"}, headers=admin_headers
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["slug"] == "silindir-bir"
    assert (await client.get(f"{_MAKINE}/silindir-bir", headers=admin_headers)).status_code == 200
    assert (await client.get(f"{_MAKINE}/silindir-iki", headers=admin_headers)).status_code == 404


async def test_makine_slug_LISTEDE_de_bulunur(client, admin_headers) -> None:
    olusan = await client.post(
        _MAKINE,
        json=_makine_govdesi("Liste Makinesi"),
        headers=admin_headers,
    )
    liste = await client.get(_MAKINE, headers=admin_headers)
    assert liste.status_code == 200, liste.text
    satir = next(k for k in liste.json()["items"] if k["id"] == olusan.json()["id"])
    assert satir["slug"] == "liste-makinesi"


async def test_gorunmeyen_santiyedeki_makine_SLUGLA_da_404(
    client, sef_headers, admin_headers, ekipman_fabrikasi, gorunmeyen_santiye, seeded_db
) -> None:
    """🔴 GÖRÜNÜRLÜK SÜZGECİ SLUG'LA DELİNMEZ (K20 / ST IDOR dersi)."""
    makine = await ekipman_fabrikasi("Gizli Makine", site=gorunmeyen_santiye)
    makine.slug = "gizli-makine"
    await seeded_db.flush()

    slugla = await client.get(f"{_MAKINE}/gizli-makine", headers=sef_headers)
    uuid_ile = await client.get(f"{_MAKINE}/{makine.id}", headers=sef_headers)
    olmayan = await client.get(f"{_MAKINE}/hic-boyle-bir-makine", headers=sef_headers)

    assert slugla.status_code == uuid_ile.status_code == olmayan.status_code == 404
    assert slugla.json() == uuid_ile.json() == olmayan.json()

    # 🔴 POZİTİF KONTROL (K-IKIZ1): GÖREN aktör AYNI slug'la 200 alır.
    goren = await client.get(f"{_MAKINE}/gizli-makine", headers=admin_headers)
    assert goren.status_code == 200, goren.text
    assert goren.json()["id"] == str(makine.id)


async def test_makine_PATCH_slug_kabul_ETMEZ_422(client, admin_headers) -> None:
    olusan = await client.post(
        _MAKINE,
        json=_makine_govdesi("Yazma Makinesi"),
        headers=admin_headers,
    )
    resp = await client.patch(
        f"{_MAKINE}/yazma-makinesi", json={"brand": "X"}, headers=admin_headers
    )
    assert resp.status_code == 422, resp.text
    assert (
        await client.patch(
            f"{_MAKINE}/{olusan.json()['id']}", json={"brand": "X"}, headers=admin_headers
        )
    ).status_code == 200


async def test_sluglanamayan_makine_adi_NULL_birakir(client, admin_headers, seeded_db) -> None:
    olusan = await client.post(
        _MAKINE,
        json=_makine_govdesi("???"),
        headers=admin_headers,
    )
    assert olusan.status_code == 201, olusan.text
    assert olusan.json()["slug"] is None
    assert (
        await client.get(f"{_MAKINE}/{olusan.json()['id']}", headers=admin_headers)
    ).status_code == 200


# =========================================================================== #
# 2. KİRA HAKEDİŞİ — `equipment_rental_invoices.slug` <- `invoice_no`
# =========================================================================== #


async def test_kira_faturasi_NUMARADAN_sluglanir(client, admin_headers, seeded_db) -> None:
    supplier = await _tedarikci(seeded_db, "Liebherr Kiralama")
    fatura = await _fatura_kur(client, admin_headers, supplier, invoice_no="LT2026080211")
    assert fatura["slug"] == "lt2026080211"

    resp = await client.get(f"{_KIRA}/lt2026080211", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == fatura["id"]


async def test_NUMARASIZ_taslakta_slug_NULL_kalir_MOCKUPLA_AYNI(
    client, admin_headers, seeded_db
) -> None:
    """🔴 Mockup ÖLÇÜLDÜ: numarasız taslak satır ekranda `— (kayıt no yok)` basar.

    Yani o kaydın İNSAN ADI YOKTUR. Uydurulmuş bir taban yazmak ekrandaki
    gerçeği bozardı; slug NULL kalır ve kayıt UUID'siyle yaşar.
    """
    supplier = await _tedarikci(seeded_db, "Taslak Kiralama")
    fatura = await _fatura_kur(client, admin_headers, supplier)
    assert fatura["invoice_no"] is None
    assert fatura["slug"] is None

    # POZİTİF KONTROL: UUID yolu çalışmaya DEVAM eder.
    assert (await client.get(f"{_KIRA}/{fatura['id']}", headers=admin_headers)).status_code == 200


async def test_IKI_TEDARIKCININ_ayni_numarasi_SESSIZCE_CAKISMAZ(
    client, admin_headers, seeded_db
) -> None:
    """🔴 `invoice_no` ŞİRKET GENELİ TEKİL DEĞİLDİR (UQ = supplier + no).

    Bu yüzden `invoice_no` DOĞRUDAN anahtar olarak kullanılamazdı: iki
    tedarikçinin aynı numarası aynı URL'ye düşerdi ve biri sessizce seçilirdi.
    Slug kolonu `unique_slug` ile `-2` eki verir; İKİSİ DE kendi anahtarıyla
    açılır ve karışmaz.
    """
    a = await _tedarikci(seeded_db, "Alfa Kiralama")
    b = await _tedarikci(seeded_db, "Beta Kiralama")

    ilk = await _fatura_kur(client, admin_headers, a, invoice_no="ORTAK2026001")
    ikinci = await _fatura_kur(client, admin_headers, b, invoice_no="ORTAK2026001")

    assert ilk["slug"] == "ortak2026001"
    assert ikinci["slug"] == "ortak2026001-2"
    assert ilk["id"] != ikinci["id"]

    for fatura in (ilk, ikinci):
        resp = await client.get(f"{_KIRA}/{fatura['slug']}", headers=admin_headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["id"] == fatura["id"]


async def test_kira_slug_LISTEDE_de_bulunur(client, admin_headers, seeded_db) -> None:
    supplier = await _tedarikci(seeded_db, "Liste Kiralama")
    fatura = await _fatura_kur(client, admin_headers, supplier, invoice_no="LISTE2026001")

    liste = await client.get(_KIRA, headers=admin_headers)
    assert liste.status_code == 200, liste.text
    satir = next(k for k in liste.json()["items"] if k["id"] == fatura["id"])
    assert satir["slug"] == "liste2026001"


async def test_kira_PATCH_slug_kabul_ETMEZ_422(client, admin_headers, seeded_db) -> None:
    supplier = await _tedarikci(seeded_db, "Yazma Kiralama")
    fatura = await _fatura_kur(client, admin_headers, supplier, invoice_no="YAZMA2026001")

    resp = await client.patch(
        f"{_KIRA}/yazma2026001", json={"invoice_amount": "100.00"}, headers=admin_headers
    )
    assert resp.status_code == 422, resp.text
    assert (
        await client.patch(
            f"{_KIRA}/{fatura['id']}", json={"invoice_amount": "100.00"}, headers=admin_headers
        )
    ).status_code == 200


async def test_kira_numara_degisince_slug_DEGISMEZ(client, admin_headers, seeded_db) -> None:
    """URL-2 kararı 4 kira faturasında da geçerlidir."""
    supplier = await _tedarikci(seeded_db, "Sabit Kiralama")
    fatura = await _fatura_kur(client, admin_headers, supplier, invoice_no="SABIT2026001")

    patch = await client.patch(
        f"{_KIRA}/{fatura['id']}", json={"invoice_no": "DEGISTI2026001"}, headers=admin_headers
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["invoice_no"] == "DEGISTI2026001"
    assert patch.json()["slug"] == "sabit2026001"
    assert (await client.get(f"{_KIRA}/sabit2026001", headers=admin_headers)).status_code == 200
    assert (await client.get(f"{_KIRA}/degisti2026001", headers=admin_headers)).status_code == 404


# =========================================================================== #
# 3. MODEL — kolon GERÇEKTEN yazılıyor (şema iddiası, gövde iddiası değil)
# =========================================================================== #


async def test_slug_kolonlari_VERITABANINA_yazilir(client, admin_headers, db_session) -> None:
    """Gövdedeki `slug` bir türev DEĞİL, SAKLANAN kolondur — kaynağı doğrula."""
    makine = await client.post(
        _MAKINE,
        json=_makine_govdesi("Kolon Testi"),
        headers=admin_headers,
    )
    satir = (
        await db_session.execute(
            select(Equipment).where(Equipment.id == uuid.UUID(makine.json()["id"]))
        )
    ).scalar_one()
    assert satir.slug == "kolon-testi"

    supplier = await _tedarikci(db_session, "Kolon Kiralama")
    fatura = await _fatura_kur(client, admin_headers, supplier, invoice_no="KOLON2026001")
    kira = (
        await db_session.execute(
            select(EquipmentRentalInvoice).where(
                EquipmentRentalInvoice.id == uuid.UUID(fatura["id"])
            )
        )
    ).scalar_one()
    assert kira.slug == "kolon2026001"
    assert Decimal("0") == Decimal("0")  # tip importunun kullanıldığı yer


# =========================================================================== #
# 4. 🔴 K1 — SLUG'IN GEÇ DOĞUMU (NULL -> dolu geçişi)
# =========================================================================== #


async def test_NUMARASIZ_taslaga_numara_girilince_slug_SONRADAN_dogar(
    client, admin_headers, seeded_db
) -> None:
    """🔴 K1 — özellik "verinin yaşının fonksiyonu" OLMAMALI.

    Kira faturası taslakta numarasız açılır (mockup: `— (kayıt no yok)`) ve
    numara SONRADAN girilir. Slug yalnız `create`te ayrılsaydı bu kayıt
    okunabilir URL'ini HİÇ almazdı — üstelik migration deploy anındaki aynı
    şekilli satırları doldurduğu için "deploy'dan önce numarası girilen slug
    alır, sonra girilen almaz" gibi keyfî bir ayrım doğardı.

    Mutasyon: `update_invoice`taki `_slug_gec_dogum` çağrısını kaldır → bu test
    kırmızı olur (slug `None` kalır).
    """
    supplier = await _tedarikci(seeded_db, "Geç Doğum Kiralama")
    fatura = await _fatura_kur(client, admin_headers, supplier)
    assert fatura["slug"] is None, "kurulum: numarasız taslak slug'sız olmalı"

    guncel = await client.patch(
        f"{_KIRA}/{fatura['id']}", json={"invoice_no": "GEC2026001"}, headers=admin_headers
    )
    assert guncel.status_code == 200, guncel.text
    assert guncel.json()["slug"] == "gec2026001"

    # Ve yeni slug GERÇEKTEN o kaydı açar (karşıt kanıt).
    acilis = await client.get(f"{_KIRA}/gec2026001", headers=admin_headers)
    assert acilis.status_code == 200, acilis.text
    assert acilis.json()["id"] == fatura["id"]


async def test_DOLU_numara_degisince_slug_DEGISMEZ_gec_dogum_TETIKLENMEZ(
    client, admin_headers, seeded_db
) -> None:
    """🔴 K1'in TERS KAPISI — geç doğum yalnız `NULL -> dolu` geçişinde çalışır.

    Dolu bir numaranın düzeltilmesi slug'ı YENİDEN üretmemeli: URL-2 kararı 4
    (paylaşılmış bağlantı yeniden adlandırmayla ölmez). Bu iddia olmasaydı
    `_slug_gec_dogum` "her PATCH'te yeniden üret" diye yazılabilir ve önceki
    test yine yeşil kalırdı.
    """
    supplier = await _tedarikci(seeded_db, "Sabit Kalan Kiralama")
    fatura = await _fatura_kur(client, admin_headers, supplier, invoice_no="ILK2026001")
    assert fatura["slug"] == "ilk2026001"

    guncel = await client.patch(
        f"{_KIRA}/{fatura['id']}", json={"invoice_no": "IKINCI2026001"}, headers=admin_headers
    )
    assert guncel.status_code == 200, guncel.text
    assert guncel.json()["invoice_no"] == "IKINCI2026001"
    assert guncel.json()["slug"] == "ilk2026001", "dolu->dolu yeniden adlandırmada slug DEĞİŞMEZ"
    assert (await client.get(f"{_KIRA}/ilk2026001", headers=admin_headers)).status_code == 200
    assert (await client.get(f"{_KIRA}/ikinci2026001", headers=admin_headers)).status_code == 404


# =========================================================================== #
# 5. 🔴 K3 — kira faturasında GÖRÜNÜRLÜK BEKÇİSİ
# =========================================================================== #


async def test_gorunmeyen_santiyedeki_kira_faturasi_SLUGLA_da_404(
    client, sef_headers, admin_headers, seeded_db, gorunmeyen_santiye
) -> None:
    """🔴 K3 — bu rota, kapısı `site_id IS NULL -> herkese görünür` olan TEK rota.

    Yani süzgecin GERÇEKTEN bir şeyi kestiğini ölçmek için faturanın şantiyesi
    DOLU olmalı; boş bırakılsaydı test hiçbir şeyi savunmazdı (`_is_visible_site`
    NULL'da `True` döner).
    """
    supplier = await _tedarikci(seeded_db, "Gizli Kiralama")
    fatura = await _fatura_kur(
        client,
        admin_headers,
        supplier,
        invoice_no="GIZLIKIRA2026001",
        site_id=str(gorunmeyen_santiye.id),
    )
    assert fatura["slug"] == "gizlikira2026001"

    slugla = await client.get(f"{_KIRA}/gizlikira2026001", headers=sef_headers)
    uuid_ile = await client.get(f"{_KIRA}/{fatura['id']}", headers=sef_headers)
    olmayan = await client.get(f"{_KIRA}/hic-boyle-bir-fatura", headers=sef_headers)

    assert slugla.status_code == uuid_ile.status_code == olmayan.status_code == 404
    assert slugla.json() == uuid_ile.json() == olmayan.json()

    # 🔴 POZİTİF KONTROL (K-IKIZ1): GÖREN aktör AYNI slug'la 200 alır.
    goren = await client.get(f"{_KIRA}/gizlikira2026001", headers=admin_headers)
    assert goren.status_code == 200, goren.text
    assert goren.json()["id"] == fatura["id"]
