"""PARA-GERCEK — kira hakedişi `pay` kapısı (kullanıcı kararı 2026-09-19).

Kullanıcının kuralı (KK-ODM) birebir: *"Nakit olarak görmeden veya çekin vadesi
gelip de tahsil edilmeden 'ödendi' gözükmemesi gerekiyor."* Kardeş iki hakediş
ailesi bu kapıdan 2026-09-03'ten beri geçiyordu; **kira ailesi geçmiyordu** ve
bu bir unutma değildi — `invoicing/source_amounts.py` kodda YAZILI olarak
*"kira orada bilinçli olarak dışarıdadır"* diyordu. Karar 2026-09-19'da geldi:
**KK-ODM kirayı da kapsar.**

## Her iddianın İKİ YARISI vardır

🔴 Her kapı testi ÇİFTTİR: reddedilen hâlin yanında mutlaka *geçen* hâl de
vardır (`test_para_GERCEKLESINCE_...`). Yalnız reddi ölçen bir test, kapı "her
şeyi reddet" hâline geldiğinde de YEŞİL kalırdı — yani "kural işliyor"u değil
"hiçbir şey olmuyor"u kanıtlardı.

## Bu ailenin kardeşlerinden FARKI

Eşik hakedişin `invoice_amount` KOLONUDUR, satırlarından türeyen bir brüt
değil: `our_total` bir DOĞRULAMA büyüklüğüdür ve fişin tabanı da o değildir
(`rental_posting:24`). Avans/teminat kesintisi bu ailede YOKTUR.
"""

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounting.models import JournalSourceType
from app.modules.equipment.models import EquipmentOwnership
from app.modules.equipment.rental_para_gercek import RENTAL_AMOUNT_MISSING
from app.modules.equipment.rental_posting import RENTAL_POSTING_RULES
from app.modules.invoicing.models import InvoiceDirection
from app.modules.sites.models import Site
from app.modules.treasury.models import FinancialInstrumentStatus, PaymentMethodKind
from app.modules.treasury.realized import (
    BINDING_INVOICE_INVALID,
    PAYMENT_NOT_REALIZED,
    SOURCE_NOT_INVOICED,
)
from tests._hakedis_esleme import esleme_kur

from ._mk2_para_gercek import kira_faturasi_kes, kira_parasini_yatir
from ._mk2_rental_invoice import (
    _BEDEL,
    _durum_ilerlet,
    _fatura_kur,
    _kayit,
    _tedarikci,
)

pytestmark = pytest.mark.asyncio

#: 152 saat × 320,00 = 48.640,00 — kira firmasının kestiği faturanın KDV hariç
#: tabanı. `our_total` ile KASITLI olarak aynıdır ki fark rozeti (K6) bu
#: dosyadaki iddiaların hiçbirine karışmasın.
_TUTAR = Decimal("48640.00")


async def _onayli_hakedis(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    ekipman_fabrikasi,
    gorunen_santiye: Site,
    *,
    invoice_amount: str | None = str(_TUTAR),
) -> dict:
    """`approved` kira hakedişi — ödeme kapısının hemen ÖNÜNDEKİ hâl."""
    await esleme_kur(seeded_db, JournalSourceType.equipment_rental_invoice, RENTAL_POSTING_RULES)
    supplier = await _tedarikci(seeded_db, "Liebherr Türkiye A.Ş.")
    kiralik = await ekipman_fabrikasi(
        "Ekskavatör CAT 320",
        site=gorunen_santiye,
        ownership=EquipmentOwnership.rented,
        supplier_id=supplier.id,
        rate_amount=_BEDEL,
    )
    await _kayit(seeded_db, kiralik, hours="152", ilk_gun=1, site=gorunen_santiye)
    ek = {} if invoice_amount is None else {"invoice_amount": invoice_amount}
    fatura = await _fatura_kur(client, admin_headers, supplier, **ek)
    await _durum_ilerlet(client, admin_headers, fatura["id"], 2)
    return fatura


async def _ode(client: AsyncClient, headers: dict[str, str], fatura_id: str):
    return await client.post(f"/equipment/rental-invoices/{fatura_id}/pay", headers=headers)


# --------------------------------------------------------------------------- #
# GEÇEN hâl — kapı kullanıcıyı KİLİTLEMİYOR (pozitif kontrol)
# --------------------------------------------------------------------------- #


async def test_para_GERCEKLESINCE_kira_hakedisi_odenir(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    ekipman_fabrikasi,
    gorunen_santiye: Site,
) -> None:
    """🔴 POZİTİF KONTROL — bu test olmadan kapı "her şeyi reddet" olabilirdi.

    Uçtan uca gerçek kurulum: kira firmasının faturası kesilir, `total`inin
    TAMAMI havale ile yatar, sonra ödeme damgası basılır.
    """
    fatura = await _onayli_hakedis(
        client, seeded_db, admin_headers, ekipman_fabrikasi, gorunen_santiye
    )
    await kira_parasini_yatir(seeded_db, fatura["id"])

    resp = await _ode(client, admin_headers, fatura["id"])
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "paid"
    assert resp.json()["paid_at"] is not None


# --------------------------------------------------------------------------- #
# REDDEDİLEN hâller — dört ayrı engel, dört ayrı 409 metni
# --------------------------------------------------------------------------- #


async def test_FATURASIZ_kira_hakedisi_odenemez(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    ekipman_fabrikasi,
    gorunen_santiye: Site,
) -> None:
    """Arkasında HİÇBİR fatura yokken `paid` damgası basılamaz.

    Bu, canlıda fiilen yaşanan hâldir: onay zinciri tamamlanan kira hakedişi
    tek kuruş hareket olmadan "ödendi" görünebiliyordu.
    """
    fatura = await _onayli_hakedis(
        client, seeded_db, admin_headers, ekipman_fabrikasi, gorunen_santiye
    )

    resp = await _ode(client, admin_headers, fatura["id"])
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == SOURCE_NOT_INVOICED


async def test_PORTFOYDEKI_cek_kira_hakedisini_odetmez(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    ekipman_fabrikasi,
    gorunen_santiye: Site,
) -> None:
    """🔴 Kuralın ÇEKİRDEĞİ: çek YAZILDI ama TAHSİL EDİLMEDİ → para GERÇEKLEŞMEDİ."""
    fatura = await _onayli_hakedis(
        client, seeded_db, admin_headers, ekipman_fabrikasi, gorunen_santiye
    )
    await kira_parasini_yatir(
        seeded_db, fatura["id"], evrak_durumu=FinancialInstrumentStatus.portfolio
    )

    resp = await _ode(client, admin_headers, fatura["id"])
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == PAYMENT_NOT_REALIZED


async def test_EKSIK_odeme_kira_hakedisini_odetmez(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    ekipman_fabrikasi,
    gorunen_santiye: Site,
) -> None:
    """Eşik faturanın `total`idir ve karşılaştırma `<` iledir: 1 kuruş eksik GEÇMEZ."""
    fatura = await _onayli_hakedis(
        client, seeded_db, admin_headers, ekipman_fabrikasi, gorunen_santiye
    )
    await kira_parasini_yatir(seeded_db, fatura["id"], fark=Decimal("-0.01"))

    resp = await _ode(client, admin_headers, fatura["id"])
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == PAYMENT_NOT_REALIZED


async def test_TERS_yonlu_fatura_kira_hakedisini_odetmez(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    ekipman_fabrikasi,
    gorunen_santiye: Site,
) -> None:
    """🔴 Yön denetlenmezse KİRACIYA kestiğimiz bir giden fatura kapıyı açardı:
    bize GİREN para, kira firmasına olan borcumuzu "ödenmiş" gösterirdi."""
    fatura = await _onayli_hakedis(
        client, seeded_db, admin_headers, ekipman_fabrikasi, gorunen_santiye
    )
    ters = await kira_faturasi_kes(seeded_db, fatura["id"], direction=InvoiceDirection.outgoing)
    from tests._para_gercek import odeme_yaz

    await odeme_yaz(seeded_db, ters, tutar=ters.total, method=PaymentMethodKind.transfer)

    resp = await _ode(client, admin_headers, fatura["id"])
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == BINDING_INVOICE_INVALID


async def test_fatura_ARA_TOPLAMI_invoice_amounti_tasimazsa_odetmez(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    ekipman_fabrikasi,
    gorunen_santiye: Site,
) -> None:
    """FAT-HAK — belge KUSURSUZ görünür, tek sorun RAKAMDIR.

    Fatura tam ödenmiştir ve yönü doğrudur; ama ara toplamı hakedişin
    `invoice_amount`ını taşımaz. Bu kapı olmasaydı 48.640'lık bir kira gideri
    5.000'lik bir faturayla kapatılabilir, MİZAN DENK KALIRDI.
    """
    fatura = await _onayli_hakedis(
        client, seeded_db, admin_headers, ekipman_fabrikasi, gorunen_santiye
    )
    await kira_parasini_yatir(seeded_db, fatura["id"], brut=Decimal("5000.00"))

    resp = await _ode(client, admin_headers, fatura["id"])
    assert resp.status_code == 409, resp.text
    assert "5000.00" in resp.json()["detail"]
    assert "48640.00" in resp.json()["detail"]


async def test_invoice_amount_GIRILMEMISSE_odenemez(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    ekipman_fabrikasi,
    gorunen_santiye: Site,
) -> None:
    """🔴 NULL-EŞİK kanonu — NULL "girilmedi"dir, sıfır DEĞİL (fail-closed).

    Tutarı girilmemiş bir kira hakedişi onaylanabilir (DB engellemez, ölçüldü)
    ve o hâlde fişlenecek para da yoktur. Eşiği `0` saymak, sıfır tutarlı bir
    faturayla ödenmesine izin verirdi.
    """
    fatura = await _onayli_hakedis(
        client,
        seeded_db,
        admin_headers,
        ekipman_fabrikasi,
        gorunen_santiye,
        invoice_amount=None,
    )
    await kira_faturasi_kes(seeded_db, fatura["id"], brut=Decimal("48640.00"))

    resp = await _ode(client, admin_headers, fatura["id"])
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == RENTAL_AMOUNT_MISSING
