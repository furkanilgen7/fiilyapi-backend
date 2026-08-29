"""TB2/T2 + **HAK-NULL** — hakediş listesi + `summary` için `site_id` süzgeci.

Hakediş tablosunda `site_id` KOLONU YOKTUR: şantiye bağı SÖZLEŞMEDEN gelir
(`subcontractor_contracts.site_id`), süzgeç de o join üzerinden kurulur.

🔴 HAK-NULL — BU DOSYA BİR KUSURU ÇİVİLİYORDU. Eski hâli "proje geneli
sözleşmenin hakedişi şantiye süzgeciyle GELMEZ" diye YEŞİL bir test taşıyordu;
canlıda ölçüldü ki YEDİ taşeron sözleşmesinin YEDİSİ DE proje geneli, dolayısıyla
`?site_id=<Cevizli>` **0** satır dönüyordu (süzgeçsiz: 3 hakediş). Yani modülün
tüm parası hiçbir şantiyede görünmüyordu ve bu test o körlüğü KORUYORDU.

Süzgecin sorusu düzeltildi: "sözleşme TAM OLARAK bu şantiyeye mi bağlı" DEĞİL,
**"bu hakediş bu şantiyeyi KAPSIYOR mu"**. Proje geneli sözleşme projenin bütün
şantiyelerini kapsar → kümeye GİRER, ve satır kendi kapsamını `contract_site_id`
ile SÖYLER (`NULL` = proje geneli).

Dört davranış birlikte ölçülür:
1. Süzgeç verilince o şantiyenin sözleşmesinin hakedişleri gelir.
2. **Proje geneli sözleşmenin hakedişi de GELİR** ve `contract_site_id is None`
   ile işaretlenir — kaybolmaz.
3. 🔴 **POZİTİF KONTROL**: AYNI projedeki BAŞKA bir şantiyenin sözleşmesinin
   hakedişi hâlâ ELENİR. Bu bacak olmasaydı "her şeyi döndüren" bozuk bir
   süzgeç (`where` bacağının tümden silinmesi) de testi yeşil geçerdi.
4. Süzgeç kapsamı GENİŞLETMEZ: görünmeyen projenin şantiye kimliği verilse bile
   `visible_projects` süzgeci kazanır (IDOR).

Geriye uyum, parametresiz çağrının eski kümeyi verdiğini gösteren testle ayrıca
çivilenir (mevcut `test_crud.py`/`test_summary.py` testleri DEĞİŞTİRİLMEDEN yeşil
kalır).
"""

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.contracts.models import SubcontractorContract, SubcontractorContractItem
from app.modules.subcontractor_progress_payments.models import (
    SubcontractorPaymentStatus,
    SubcontractorProgressPayment,
    SubcontractorProgressPaymentLine,
)
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio

LISTE_UC = "/subcontractor-progress-payments"
OZET_UC = "/subcontractor-progress-payments/summary"


def _kalemler(contract: SubcontractorContract) -> list[SubcontractorContractItem]:
    return sorted(contract.items, key=lambda item: item.sort_order)


async def _hakedis(
    session: AsyncSession,
    hakedis_fabrikasi,
    contract: SubcontractorContract,
    creator: User,
    *,
    sequence_no: int,
    status: SubcontractorPaymentStatus,
    miktar: Decimal,
    kalem_index: int = 0,
) -> SubcontractorProgressPayment:
    """Tek satırlı hakediş — brüt KPI'ların ölçülebilmesi için satır ŞARTTIR."""
    payment = await hakedis_fabrikasi(
        contract,
        creator,
        sequence_no=sequence_no,
        status=status,
        period_year=2026,
        period_month=7,
    )
    item = _kalemler(contract)[kalem_index]
    session.add(
        SubcontractorProgressPaymentLine(
            payment_id=payment.id,
            contract_item_id=item.id,
            code=item.code,
            description=item.description,
            unit=item.unit,
            contract_unit_price=item.unit_price,
            coefficient=Decimal("1.000"),
            quantity=miktar,
            sort_order=0,
        )
    )
    await session.flush()
    return payment


@pytest.fixture
async def santiye_verisi(
    seeded_db: AsyncSession,
    taseron_sozlesmesi_fabrikasi,
    hakedis_fabrikasi,
    admin_kullanicisi: User,
) -> dict:
    """TEK projede ÜÇ sözleşme — üçü de süzgecin ayrı bir bacağını ölçer.

    Kalem birim fiyatları fixture'dan gelir: kalem#1 = 21.500, kalem#2 = 1.850.

    | Sözleşme            | `site_id`   | Hakediş                    | Brüt      |
    |---------------------|-------------|----------------------------|-----------|
    | A (hedef şantiye)   | `site`      | `pending_approval` 5×1.850 |   9.250   |
    | A (hedef şantiye)   | `site`      | `paid` 2×21.500            |  43.000   |
    | B (proje geneli)    | `NULL`      | `approved` 10×21.500       | 215.000   |
    | C (BAŞKA şantiye)   | `diger_site`| `approved` 3×21.500        |  64.500   |

    🔴 C, POZİTİF KONTROLDÜR ve AYNI projededir: `visible_projects` kapısı onu
    ELEMEZ, onu eleyen tek şey `site_id` süzgecinin KENDİSİDİR. Fabrika
    `with_site=True` ile aynı projeye İKİNCİ bir şantiye açar.
    """
    santiyeli, proje, site = await taseron_sozlesmesi_fabrikasi(
        "THK-F01", subcontractor_name="Şantiye Taşeronu"
    )
    proje_geneli, _, _ = await taseron_sozlesmesi_fabrikasi(
        "THK-F02",
        project=proje,
        subcontractor_name="Proje Geneli Taşeron",
        with_site=False,
    )
    assert proje_geneli.site_id is None
    diger_santiye, _, diger_site = await taseron_sozlesmesi_fabrikasi(
        "THK-F03",
        project=proje,
        subcontractor_name="Diğer Şantiye Taşeronu",
    )
    assert diger_site is not None
    assert site is not None
    assert diger_site.id != site.id

    await _hakedis(
        seeded_db,
        hakedis_fabrikasi,
        santiyeli,
        admin_kullanicisi,
        sequence_no=1,
        status=SubcontractorPaymentStatus.pending_approval,
        miktar=Decimal("5"),
        kalem_index=1,
    )
    await _hakedis(
        seeded_db,
        hakedis_fabrikasi,
        santiyeli,
        admin_kullanicisi,
        sequence_no=2,
        status=SubcontractorPaymentStatus.paid,
        miktar=Decimal("2"),
    )
    await _hakedis(
        seeded_db,
        hakedis_fabrikasi,
        proje_geneli,
        admin_kullanicisi,
        sequence_no=1,
        status=SubcontractorPaymentStatus.approved,
        miktar=Decimal("10"),
    )
    await _hakedis(
        seeded_db,
        hakedis_fabrikasi,
        diger_santiye,
        admin_kullanicisi,
        sequence_no=1,
        status=SubcontractorPaymentStatus.approved,
        miktar=Decimal("3"),
    )
    return {
        "proje": proje,
        "site": site,
        "diger_site": diger_site,
        "santiyeli": santiyeli,
        "proje_geneli": proje_geneli,
        "diger_santiye": diger_santiye,
    }


# --- 1. Liste ucu ---


async def test_site_id_filtresi_santiyeyi_kapsayan_hakedisleri_getirir(
    client: AsyncClient, admin_headers: dict[str, str], santiye_verisi: dict
) -> None:
    """Kapsayan küme = şantiyeye bağlı sözleşme + proje geneli sözleşme.

    BAŞKA şantiyenin sözleşmesi dışarıdadır — bu iddia `test_..._pozitif_kontrol`
    ile AYRICA ve tek başına da çivilenir.
    """
    yanit = await client.get(
        LISTE_UC, params={"site_id": str(santiye_verisi["site"].id)}, headers=admin_headers
    )
    assert yanit.status_code == 200, yanit.text
    govde = yanit.json()
    assert govde["total"] == 3
    assert {item["contract_id"] for item in govde["items"]} == {
        str(santiye_verisi["santiyeli"].id),
        str(santiye_verisi["proje_geneli"].id),
    }


async def test_site_id_filtresi_proje_geneli_sozlesmenin_hakedisini_KAYBETMEZ(
    client: AsyncClient, admin_headers: dict[str, str], santiye_verisi: dict
) -> None:
    """🔴 HAK-NULL'ın BİREBİR bekçisi — bu testin ESKİ hâli tersini iddia ediyordu.

    Proje geneli (`site_id IS NULL`) sözleşme projenin BÜTÜN şantiyelerini
    kapsar; şantiye süzgeciyle çağrıldığında hakedişi KAYBOLMAMALIDIR. Canlıda
    kaybolduğu ölçüldü: yedi sözleşmenin yedisi de proje geneliydi, şantiye
    süzgeci 0 satır dönüyordu.

    Satır ayrıca KENDİ KAPSAMINI söyler: `contract_site_id is None`. Görünürlüğü
    açıp bu alanı yayımlamamak, çağıranın proje geneli parayı şantiyenin parası
    sanıp N şantiyede N kez toplamasına yol açardı.
    """
    yanit = await client.get(
        LISTE_UC, params={"site_id": str(santiye_verisi["site"].id)}, headers=admin_headers
    )
    assert yanit.status_code == 200, yanit.text
    items = yanit.json()["items"]
    proje_geneli = [
        item for item in items if item["contract_id"] == str(santiye_verisi["proje_geneli"].id)
    ]
    assert len(proje_geneli) == 1, "proje geneli sözleşmenin hakedişi ELENDİ (HAK-NULL)"
    assert proje_geneli[0]["contract_site_id"] is None

    santiyeli = [
        item for item in items if item["contract_id"] == str(santiye_verisi["santiyeli"].id)
    ]
    assert len(santiyeli) == 2
    assert {item["contract_site_id"] for item in santiyeli} == {str(santiye_verisi["site"].id)}, (
        "şantiye kapsamlı satır proje geneliymiş gibi işaretlenemez"
    )


async def test_site_id_filtresi_baska_santiyenin_hakedisini_HALA_eler_pozitif_kontrol(
    client: AsyncClient, admin_headers: dict[str, str], santiye_verisi: dict
) -> None:
    """🔴 POZİTİF KONTROL (K-IKIZ1). Süzgeci gevşetmenin bedeli, onu TÜMDEN
    kaldırmak DEĞİLDİR.

    `diger_santiye` AYNI projededir — `visible_projects` kapısı onu elemez, onu
    eleyen tek şey `site_id` süzgecinin kendisidir. Bu bacak olmasaydı
    `_list_stmt`teki `where` çağrısını tamamen silen bir mutant da yukarıdaki
    iki testi yeşil geçerdi ("her şeyi döndüren süzgeç" sahte-yeşili).
    """
    yanit = await client.get(
        LISTE_UC, params={"site_id": str(santiye_verisi["site"].id)}, headers=admin_headers
    )
    assert yanit.status_code == 200, yanit.text
    contract_ids = {item["contract_id"] for item in yanit.json()["items"]}
    assert str(santiye_verisi["diger_santiye"].id) not in contract_ids


async def test_parametresiz_liste_eski_davranisi_korur(
    client: AsyncClient, admin_headers: dict[str, str], santiye_verisi: dict
) -> None:
    """Geriye uyum: süzgeç verilmezse projenin ÜÇ sözleşmesinin hakedişi de gelir."""
    yanit = await client.get(LISTE_UC, headers=admin_headers)
    assert yanit.status_code == 200, yanit.text
    govde = yanit.json()
    assert govde["total"] == 4
    assert {item["contract_id"] for item in govde["items"]} == {
        str(santiye_verisi["santiyeli"].id),
        str(santiye_verisi["proje_geneli"].id),
        str(santiye_verisi["diger_santiye"].id),
    }


# --- 2. Özet (KPI) ucu ---


async def test_ozet_site_id_filtresi_kapsayan_kumeden_hesaplar(
    client: AsyncClient, admin_headers: dict[str, str], santiye_verisi: dict
) -> None:
    """Dört KPI da liste ucuyla AYNI kümeden hesaplanır (`_list_stmt` paylaşılır).

    🔴 TOPLAMLAR KARARI: özet ucu ile liste ucu AYRIŞAMAZ — ayrışsalardı "Toplam
    Hakediş" kartı altındaki tablodan BAŞKA bir şeyi özetlerdi. Bu yüzden özet de
    kapsayan kümeyi (şantiye + proje geneli) özetler: 9.250 + 43.000 + 215.000.
    BAŞKA şantiyenin 64.500'ü yine DIŞARIDADIR.

    "Şantiyenin kendi parası" ayrımı SUNUCUDA değil, satırdaki `contract_site_id`
    ile ÇAĞIRANDA yapılır (frontend `site-payment-scope.ts`): sunucu tek bir
    "şantiye toplamı" tanımı dayatsaydı, proje geneli parayı hem gizleyen hem de
    her şantiyede tekrar sayan iki yanlıştan birini seçmek zorunda kalırdı.
    """
    yanit = await client.get(
        OZET_UC,
        params={
            "site_id": str(santiye_verisi["site"].id),
            "period_year": 2026,
            "period_month": 7,
        },
        headers=admin_headers,
    )
    assert yanit.status_code == 200, yanit.text
    govde = yanit.json()
    assert Decimal(govde["total_gross"]) == Decimal("267250.00")  # 9.250+43.000+215.000
    assert Decimal(govde["pending_gross"]) == Decimal("9250.00")
    assert Decimal(govde["paid_period_gross"]) == Decimal("43000.00")
    assert govde["active_subcontractor_count"] == 2


async def test_ozet_site_id_filtresi_baska_santiyeyi_disarida_birakir_pozitif_kontrol(
    client: AsyncClient, admin_headers: dict[str, str], santiye_verisi: dict
) -> None:
    """Özet ucunun POZİTİF KONTROLÜ: 64.500 (başka şantiye) toplama GİRMEZ —
    girseydi süzgeç tümden kaldırılmış olurdu ve 331.750 okurduk."""
    yanit = await client.get(
        OZET_UC,
        params={
            "site_id": str(santiye_verisi["site"].id),
            "period_year": 2026,
            "period_month": 7,
        },
        headers=admin_headers,
    )
    assert yanit.status_code == 200, yanit.text
    assert Decimal(yanit.json()["total_gross"]) != Decimal("331750.00")
    assert Decimal(yanit.json()["total_gross"]) == Decimal("267250.00")


async def test_ozet_parametresiz_eski_davranisi_korur(
    client: AsyncClient, admin_headers: dict[str, str], santiye_verisi: dict
) -> None:
    yanit = await client.get(
        OZET_UC, params={"period_year": 2026, "period_month": 7}, headers=admin_headers
    )
    assert yanit.status_code == 200, yanit.text
    govde = yanit.json()
    assert Decimal(govde["total_gross"]) == Decimal("331750.00")  # +64.500
    assert govde["active_subcontractor_count"] == 3


# --- 3. IDOR: süzgeç kapsamı GENİŞLETMEZ ---


async def test_gorunmeyen_projenin_santiyesi_liste_getirmez(
    client: AsyncClient, kisitli_headers: dict[str, str], santiye_verisi: dict
) -> None:
    """`kisitli_headers` kullanıcısı yalnız `kisitli_proje`'yi görür; başka projenin
    şantiye kimliği verilse bile hakediş GELMEZ."""
    yanit = await client.get(
        LISTE_UC, params={"site_id": str(santiye_verisi["site"].id)}, headers=kisitli_headers
    )
    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["total"] == 0
    assert yanit.json()["items"] == []


async def test_gorunmeyen_projenin_santiyesi_ozeti_sifirdir(
    client: AsyncClient, kisitli_headers: dict[str, str], santiye_verisi: dict
) -> None:
    yanit = await client.get(
        OZET_UC, params={"site_id": str(santiye_verisi["site"].id)}, headers=kisitli_headers
    )
    assert yanit.status_code == 200, yanit.text
    govde = yanit.json()
    assert Decimal(govde["total_gross"]) == Decimal("0.00")
    assert govde["active_subcontractor_count"] == 0
