"""HZ-CIFT — taslak/bekleyen faturalı borç İKİ LİSTEDEN BİRDEN kaybolmasın.

## Kusur

`upcoming.py`nin çift sayım kapısı DURUMSUZDU: hakedişe bağlı HERHANGİ bir
fatura satırı hakedişi listeden düşürüyordu. Oysa faturanın listeye GİRMESİ
`direction == incoming` **ve** `status == approved` istiyor. Aradaki her hâlde
borç ikisinden de düşüyordu:

* hakediş — "faturalanmış" sayıldığı için,
* fatura   — henüz `approved` olmadığı için.

Ve bu istisnai değil NORMAL hâldi: gelen fatura sisteme **`pending`** girer
(`InvoiceStatus` K2), yani taşeron faturası kesildiği andan onaylandığı ana
kadar borç GÖRÜNMEZDİ.

## Her iddianın İKİ YARISI

🔴 "Hakediş listede kalır" testleri tek başına, çift sayım kapısı TAMAMEN
silindiğinde de yeşil kalırdı. Bu yüzden her birinin yanında `approved`
faturanın hakedişi GERÇEKTEN düşürdüğü (ve borcun toplamda BİR KEZ göründüğü)
karşıt kanıt durur.
"""

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.invoicing.models import InvoiceDirection, InvoiceStatus
from tests.modules.treasury._hz1_upcoming import _gun, _liste, _onay_zamani

pytestmark = pytest.mark.asyncio


async def _hakedis_ve_fatura(
    taseron_hakedisi_fabrikasi,
    fatura_fabrikasi,
    *,
    status: InvoiceStatus,
    direction: InvoiceDirection = InvoiceDirection.incoming,
):
    """Vadesi pencerede olan onaylı hakediş + ona bağlı fatura."""
    hakedis = await taseron_hakedisi_fabrikasi(
        approved_at=_onay_zamani(_gun(0)), payment_term_days=2, line_amounts=("1000.00",)
    )
    await fatura_fabrikasi(
        direction=direction,
        status=status,
        total="1000.00",
        due_date=_gun(3),
        source_payment=hakedis,
    )
    return hakedis


@pytest.mark.parametrize(
    "status",
    [InvoiceStatus.pending, InvoiceStatus.disputed],
)
async def test_G5_ONAYLANMAMIS_faturali_hakedis_LISTEDE_KALIR(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers,
    taseron_hakedisi_fabrikasi,
    fatura_fabrikasi,
    status: InvoiceStatus,
) -> None:
    """🔴 KUSURUN TA KENDİSİ.

    `pending` gelen faturanın NORMAL giriş durumudur; `disputed` ise itirazdır ve
    borcu ORTADAN KALDIRMAZ (fail-closed: borcun sessizce kaybolması, fazladan
    görünmesinden çok daha pahalıdır). İkisinde de fatura satırı listeye
    giremez, dolayısıyla hakediş satırı KALMAK ZORUNDADIR — yoksa borç hiçbir
    yerde görünmez.
    """
    await _hakedis_ve_fatura(taseron_hakedisi_fabrikasi, fatura_fabrikasi, status=status)

    items = await _liste(client, admin_headers)

    kaynaklar = [s["source_type"] for s in items]
    assert kaynaklar == ["subcontractor_progress_payment"], items
    assert Decimal(items[0]["amount"]) == Decimal("1000.00")


async def test_G5_KARSIT_KANIT_onayli_fatura_hakedisi_LISTEDEN_DUSURUR(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers,
    taseron_hakedisi_fabrikasi,
    fatura_fabrikasi,
) -> None:
    """🔴 İddianın ikinci yarısı: çift sayım kapısı HÂLÂ ÇALIŞIYOR.

    Bu test olmadan yukarıdaki testler, kapı tamamen silindiğinde de yeşil
    kalırdı — yani "doğru süzülüyor"u değil "hiç süzülmüyor"u kanıtlardı.
    """
    await _hakedis_ve_fatura(
        taseron_hakedisi_fabrikasi, fatura_fabrikasi, status=InvoiceStatus.approved
    )

    items = await _liste(client, admin_headers)

    assert [s["source_type"] for s in items] == ["invoice"], items


async def test_G6_ayni_borc_toplamda_BIR_KEZ_gorunur(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers,
    taseron_hakedisi_fabrikasi,
    fatura_fabrikasi,
) -> None:
    """Çift sayım YOK: onaylı faturalı borç tek satır ve tek tutardır.

    Dışlama şartı dahil etme şartından DAR olsaydı (ör. vade/pencere şartı da
    eklenseydi) aynı borç hem hakediş hem fatura satırı olarak görünür ve nakit
    ihtiyacı sessizce iki katına çıkardı.
    """
    await _hakedis_ve_fatura(
        taseron_hakedisi_fabrikasi, fatura_fabrikasi, status=InvoiceStatus.approved
    )

    items = await _liste(client, admin_headers)

    assert len(items) == 1, items
    assert Decimal(items[0]["amount"]) == Decimal("1000.00")


async def test_G5_GIDEN_fatura_hakedisi_DUSURMEZ(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers,
    taseron_hakedisi_fabrikasi,
    fatura_fabrikasi,
) -> None:
    """🔴 YÖN de şartın parçasıdır — ve bu test onu GERÇEKTEN ölçer.

    Taşerona olan borcumuz GELEN faturayla kapanır; aynı hakedişe bağlı bir
    GİDEN fatura o borcu ödemez ve hakedişi listeden düşürmemelidir.

    🔴 **DURUM BİLEREK `approved`TIR.** İlk yazımda `collected` seçilmişti ve
    mutasyon ölçümü şunu gösterdi: `direction` şartını silen mutant HAYATTA
    KALIYORDU, çünkü `status == approved` şartı `collected` faturayı zaten
    eliyordu — yani test yönü değil durumu ölçüyordu. `approved` bir GİDEN
    fatura, uçlardan ULAŞILAMAZ bir hâldir (`transitions.py` yön dışı geçişi
    409'lar) ama veritabanında MÜMKÜNDÜR (veri düzeltmesi, göç). Süzgeç bu yüzden
    fail-closed kurulur ve bekçi tam olarak o hâli çakar: yön şartı silinirse
    borç HİÇBİR listede görünmez (fatura dalı da `incoming` istiyor).
    """
    await _hakedis_ve_fatura(
        taseron_hakedisi_fabrikasi,
        fatura_fabrikasi,
        status=InvoiceStatus.approved,
        direction=InvoiceDirection.outgoing,
    )

    items = await _liste(client, admin_headers)

    assert [s["source_type"] for s in items] == ["subcontractor_progress_payment"], items


async def test_yuklem_TEK_KOPYADIR_risks_de_ayni_kaynagi_okur() -> None:
    """🔴 İKİ YÜZEY, TEK YÜKLEM.

    Kusur ölçüldüğünde `dashboard/risks.py` AYNI durumsuz kopyayı taşıyordu.
    Yüklem `upcoming.invoiced_condition`ta tek kopyaya indirildi; bu bekçi,
    risks tarafında ikinci bir `exists()` yeniden doğmasını engeller
    (`progress_payment_due_expression`ın paylaşım gerekçesiyle aynı desen).
    """
    import inspect

    from app.modules.dashboard import risks
    from app.modules.treasury import upcoming

    kaynak = inspect.getsource(risks._overdue_payment_alerts)
    assert "invoiced_condition()" in kaynak
    assert "exists()" not in kaynak, "risks.py yeniden kendi kopyasını yazmış"
    assert risks.invoiced_condition is upcoming.invoiced_condition
