"""🔴 FAT-HAK — İŞVEREN ailesinde fatura ↔ hakediş TUTAR kapısı (uçtan uca).

## Kapatılan canlı kusur

1.000.000 ₺'lik bir hakedişe 1 ₺'lik fatura kesilebiliyor, hakediş `paid`
oluyor ve kalan 999.999 ₺ sessizce siliniyordu. `total > 0` şartı (kusur 1)
bunu GÖRMEZ: 1 ₺ sıfır değildir. Yön şartı (kusur 2) de görmez: fatura doğru
yöndedir. Belge kusursuz görünür, tek yanlış olan RAKAMDIR.

## 🔴 Bu dosya İKİ AYRI KATMANI ölçer ve ikisi de GEREKLİDİR

* **`send` (422)** — belge kesinleşirken. Bu ailede `approve` ULAŞILAMAZ bir
  geçiştir (`OUTGOING_TRANSITIONS` yalnız `draft → sent → collected` taşır),
  yani kapı `approve`a konsaydı bu ailede HİÇBİR yerde koşmazdı.
* **`mark-paid` (409)** — para kapısı. `send`e hiç uğramamış bir `draft`
  faturaya ödeme YAZILABİLİR (`payments_service`: *"`draft` bir giden fatura
  tam ödense bile durumu DEĞİŞMEZ"*) ve `binding_invoice_for_source` faturanın
  DURUMUNA HİÇ BAKMAZ — yani 422 katmanı tek başına delinebilirdi.

Her katmanın KENDİ mutasyon bekçisi vardır (deponun "iki katman birbirini
maskeler" kanonu): birini kaldırmak ötekinin testini kırmaz.

## Her iddianın İKİ YARISI vardır

Her red testinin yanında GEÇEN hâl de durur. Yalnız reddi ölçen bir test, kapı
"her şeyi reddet" hâline geldiğinde de yeşil kalırdı (K-IKIZ1).
"""

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounting.models import JournalSourceType
from app.modules.invoicing.models import InvoiceDocumentType, InvoiceStatus
from app.modules.invoicing.posting import INVOICE_POSTING_RULES
from app.modules.invoicing.validation import source_amount_mismatch
from app.modules.progress_payments.models import ProgressPaymentStatus
from app.modules.treasury.realized import BINDING_INVOICE_INVALID, PAYMENT_NOT_REALIZED
from tests._hakedis_esleme import esleme_kur
from tests._para_gercek import fatura_kes, hakedis_bruttu, odeme_yaz

pytestmark = pytest.mark.asyncio

_HAKEDIS = "/progress-payments"
_FATURA = "/invoices"

#: 🔴 Beklenen metnin ELLE YAZILMIŞ başlangıcı (OK-1C kanonu: durum kodu tek
#: başına iddia değildir). Sabitten okunsaydı, metni başka bir korkuluğun
#: metniyle değiştiren mutant sağ kalırdı — üç 409 metni kullanıcıya ÜÇ FARKLI
#: iş söyler ("fatura kes" · "faturayı düzelt" · "ödemeyi tamamla").
_TUTAR_409_BASI = "Hakediş ödendi işaretlenemez: hakedişe bağlı faturanın ara toplamı"


async def _sapmali_faturali_hakedis(seeded_db: AsyncSession, hakedis_fabrikasi, sapma: Decimal):
    """Onaylı hakediş + brütünden `sapma` kadar sapan, TAMAMI ÖDENMİŞ fatura.

    🔴 Fatura ürünün KENDİ para motorundan geçer (`_para_gercek.fatura_kes` →
    `invoicing.amounts.compute`) ve ödeme faturanın `total`ini TAM karşılar:
    böylece `mark-paid` yolundaki ÖTEKİ üç engel (fatura yok · belge geçersiz ·
    para yetmiyor) kesin olarak ELENİR ve testin ölçtüğü tek şey TUTAR kapısı
    kalır. Sapmayı ödeme eksikliğinin taşıması, kapıyı bekçisiz bırakırdı.
    """
    payment_id = await hakedis_fabrikasi(ProgressPaymentStatus.approved)
    brut = await hakedis_bruttu(seeded_db, payment_id, taseron=False)
    fatura = await fatura_kes(seeded_db, payment_id, taseron=False, brut=brut + sapma)
    await odeme_yaz(seeded_db, fatura, taseron=False, tutar=fatura.total)
    return payment_id, brut, fatura


# --------------------------------------------------------------------------- #
# KATMAN 1 — `mark-paid` (409)
# --------------------------------------------------------------------------- #


async def test_FH1_BIR_TL_lik_fatura_hakedisi_ODETEMEZ(
    client: AsyncClient,
    admin_headers: dict[str, str],
    seeded_db: AsyncSession,
    hakedis_fabrikasi,
) -> None:
    """Dilime adını veren kusur: fatura GEÇERLİ görünür, tamamı ÖDENMİŞTİR ve
    yine de hakediş kapanmaz — çünkü o para hakedişin parası değildir."""
    payment_id = await hakedis_fabrikasi(ProgressPaymentStatus.approved)
    brut = await hakedis_bruttu(seeded_db, payment_id, taseron=False)
    assert brut > Decimal("1.00"), "kurulum: brüt 1 ₺'den büyük olmalı"
    fatura = await fatura_kes(seeded_db, payment_id, taseron=False, brut=Decimal("1.00"))
    assert fatura.total > 0, "kurulum: `total > 0` şartı BU testte elenmiş olmalı"
    await odeme_yaz(seeded_db, fatura, taseron=False, tutar=fatura.total)

    yanit = await client.post(f"{_HAKEDIS}/{payment_id}/mark-paid", headers=admin_headers)

    assert yanit.status_code == 409, yanit.text
    detay = yanit.json()["detail"]
    assert detay.startswith(_TUTAR_409_BASI), detay
    # 🔴 Üç metin AYRIŞMALIDIR: bu red ne "fatura geçersiz" ne "para yetmiyor".
    assert detay != BINDING_INVOICE_INVALID
    assert detay != PAYMENT_NOT_REALIZED
    # İki sayı da kullanıcıya gösterilir (mesajın kendi gerekçesi).
    assert "1.00" in detay and str(brut) in detay


async def test_FH1_POZITIF_KONTROL_dogru_tutarli_fatura_hakedisi_ODER(
    client: AsyncClient,
    admin_headers: dict[str, str],
    seeded_db: AsyncSession,
    hakedis_fabrikasi,
) -> None:
    """🔴 İddianın ikinci yarısı: kapı "her şeyi reddet" olursa KIRMIZI."""
    payment_id, _, _ = await _sapmali_faturali_hakedis(
        seeded_db, hakedis_fabrikasi, Decimal("0.00")
    )

    yanit = await client.post(f"{_HAKEDIS}/{payment_id}/mark-paid", headers=admin_headers)

    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["status"] == "paid"


@pytest.mark.parametrize(
    "sapma", [Decimal("0.01"), Decimal("-0.01")], ids=["arti_bir_kurus", "eksi_bir_kurus"]
)
async def test_FH2_SINIR_bir_kurusluk_sapma_GECER(
    client: AsyncClient,
    admin_headers: dict[str, str],
    seeded_db: AsyncSession,
    hakedis_fabrikasi,
    sapma: Decimal,
) -> None:
    """Tolerans kullanıcı kararıdır ve GERÇEK bir ihtiyaçtır: iki taraf farklı
    noktalarda yuvarlar (hakedişte ÇİFT `quantize2`, faturada TEK `round_money`),
    yani kuruşluk sapma meşru bir faturada da doğabilir."""
    payment_id, _, _ = await _sapmali_faturali_hakedis(seeded_db, hakedis_fabrikasi, sapma)

    yanit = await client.post(f"{_HAKEDIS}/{payment_id}/mark-paid", headers=admin_headers)

    assert yanit.status_code == 200, yanit.text


@pytest.mark.parametrize(
    "sapma", [Decimal("0.02"), Decimal("-0.02")], ids=["arti_iki_kurus", "eksi_iki_kurus"]
)
async def test_FH2_SINIR_iki_kurusluk_sapma_REDDEDILIR(
    client: AsyncClient,
    admin_headers: dict[str, str],
    seeded_db: AsyncSession,
    hakedis_fabrikasi,
    sapma: Decimal,
) -> None:
    """🔴 `-0,02` satırı `abs()`i düşüren mutantın TEK bekçisidir: mutlak değer
    olmadan EKSİK faturalanan her hakediş sessizce geçerdi."""
    payment_id, _, _ = await _sapmali_faturali_hakedis(seeded_db, hakedis_fabrikasi, sapma)

    yanit = await client.post(f"{_HAKEDIS}/{payment_id}/mark-paid", headers=admin_headers)

    assert yanit.status_code == 409, yanit.text
    assert yanit.json()["detail"].startswith(_TUTAR_409_BASI), yanit.text


# --------------------------------------------------------------------------- #
# KATMAN 2 — `send` (422). Bu ailede `approve` ULAŞILAMAZ.
# --------------------------------------------------------------------------- #


async def _giden_fatura_kes(
    client: AsyncClient,
    admin_headers: dict[str, str],
    payment_id,
    birim_fiyat: Decimal,
    *,
    kaynaga_bagla: bool = True,
) -> str:
    """🔴 Fatura ÜRÜNÜN KENDİ `POST /invoices` yolundan kurulur.

    `_para_gercek.fatura_kes` bu katman için YETMEZ ve bu ÖLÇÜLDÜ: o yardımcı
    yalnız BAŞLIK kolonlarını yazar, `invoice_lines` satırı AÇMAZ — yani
    ürünün hiçbir zaman üretemeyeceği bir hâl kurar ve `send` K6'nın
    `LINES_REQUIRED` engeline takılır. Kapıyı o hâlde ölçmek, kapının ölçtüğü
    yolu testin kendisinin bozması olurdu (deponun "bir bekçi, ölçtüğü yolu
    kendisi kuruyorsa hiçbir şey ölçmüyordur" kanonu).

    🔴 GİDEN faturada `POST` kapısı YOKTUR (kural yalnız GELEN taraftadır,
    gerekçesi `service.create_invoice`te), yani yanlış tutarlı bir taslak
    burada MEŞRU biçimde doğar — kullanıcının canlıda yaptığının birebir aynısı.
    """
    govde = {
        "direction": "outgoing",
        "document_type": "einvoice",
        "issue_date": "2026-07-18",
        "party_name": "Güneşkent Gayrimenkul A.Ş.",
        "party_tax_number": "1234567890",
        "lines": [
            {
                "description": "Hakediş bedeli",
                "unit": "ad",
                "quantity": "1.000",
                "unit_price": str(birim_fiyat),
                "vat_rate": "20.00",
            }
        ],
    }
    if kaynaga_bagla:
        govde["progress_payment_id"] = str(payment_id)

    yanit = await client.post(_FATURA, headers=admin_headers, json=govde)
    assert yanit.status_code == 201, yanit.text
    assert yanit.json()["status"] == InvoiceStatus.draft.value
    return yanit.json()["id"]


async def test_FH3_send_TUTARSIZ_baglanmis_faturayi_REDDEDER(
    client: AsyncClient,
    admin_headers: dict[str, str],
    seeded_db: AsyncSession,
    hakedis_fabrikasi,
) -> None:
    """🔴 Sahte fatura DAHA KESİNLEŞİRKEN durdurulur.

    `mark-paid` kapısı tek başına kalsaydı belge `sent` olur, kısmi UNIQUE
    indeks (`uq_invoices_progress_payment`) hakedişin fatura slotunu İŞGAL
    ederdi ve `sent` bir fatura ne silinebilir ne düzeltilebilir.
    """
    payment_id = await hakedis_fabrikasi(ProgressPaymentStatus.approved)
    brut = await hakedis_bruttu(seeded_db, payment_id, taseron=False)
    fatura_id = await _giden_fatura_kes(client, admin_headers, payment_id, Decimal("1.00"))

    yanit = await client.post(f"{_FATURA}/{fatura_id}/send", headers=admin_headers)

    assert yanit.status_code == 422, yanit.text
    assert yanit.json()["detail"] == source_amount_mismatch(Decimal("1.00"), brut), yanit.text


async def test_FH3_POZITIF_KONTROL_send_DOGRU_tutarda_GECER(
    client: AsyncClient,
    admin_headers: dict[str, str],
    seeded_db: AsyncSession,
    hakedis_fabrikasi,
) -> None:
    """🔴 Karşıt kanıt: aynı yol, aynı gövde, YALNIZ tutar doğru → 200.

    Fişleme eşlemesi kurulur çünkü `send` FİŞ KESER (MU-3B); eşleme yoksa
    BAŞKA bir 422 döner ve test "kapı çalışıyor"u değil "uç hep 422 veriyor"u
    kanıtlardı.
    """
    await esleme_kur(seeded_db, JournalSourceType.invoice, INVOICE_POSTING_RULES)
    payment_id = await hakedis_fabrikasi(ProgressPaymentStatus.approved)
    brut = await hakedis_bruttu(seeded_db, payment_id, taseron=False)
    fatura_id = await _giden_fatura_kes(client, admin_headers, payment_id, brut)

    yanit = await client.post(f"{_FATURA}/{fatura_id}/send", headers=admin_headers)

    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["status"] == InvoiceStatus.sent.value


async def test_FH4_KAYNAKSIZ_fatura_send_yolunda_ETKILENMEZ(
    client: AsyncClient,
    admin_headers: dict[str, str],
    seeded_db: AsyncSession,
    hakedis_fabrikasi,
) -> None:
    """🔴 Kapsam bekçisi: kural YALNIZ hakedişe bağlı faturalar içindir.

    `source_gross_for_invoice` her faturaya bir brüt uyduran bir hâle gelirse
    (ör. `None` yerine `Decimal(0)` dönerse) hakedişsiz faturaların TAMAMI
    gönderilemez olurdu — ve bu, ürünün ÇOĞUNLUĞUDUR.
    """
    await esleme_kur(seeded_db, JournalSourceType.invoice, INVOICE_POSTING_RULES)
    payment_id = await hakedis_fabrikasi(ProgressPaymentStatus.approved)
    fatura_id = await _giden_fatura_kes(
        client, admin_headers, payment_id, Decimal("1.00"), kaynaga_bagla=False
    )

    yanit = await client.post(f"{_FATURA}/{fatura_id}/send", headers=admin_headers)

    assert yanit.status_code == 200, yanit.text


# --------------------------------------------------------------------------- #
# MEVCUT VERİ — "kaç kayıt etkilenir" sorusunun cevabı (migration b4d7e1c9f2a3)
# --------------------------------------------------------------------------- #


async def test_FH9_OLCUM_sorgusu_IHLALLI_faturayi_sayar_TEMIZI_saymaz(
    seeded_db: AsyncSession,
    hakedis_fabrikasi,
) -> None:
    """🔴 Yeni kapı CANLIDA ZATEN VAR OLAN faturaları da bağlar.

    "Kaç kayıt etkilenir" gelistirme makinesinden ÖLÇÜLEMEZ (canlı DB'ye erişim
    YOK); cevabı `b4d7e1c9f2a3` migration'ı deploy günlüğüne yazar. Bu test o
    sorgunun DOĞRU KÜMEYİ saydığını kurar — sorgu yanlış sayarsa rapor da yalan
    olur ve kullanıcı canlıda kilitli hakedişle karşılaşır.

    🔴 İddia İKİ YÖNLÜDÜR (sayma kanonu): ihlalli SAYILIR **ve** temiz
    SAYILMAZ. Yalnız "ihlalli >= 1" diyen bir test, her satırı ihlal sayan bir
    sorguda da yeşil kalırdı.
    """
    # 🔴 `alembic/versions` bir PAKET DEĞİLDİR (`__init__.py` yok) — modül
    #    YOLDAN yüklenir. Kopyalanmış bir SQL metniyle ölçülseydi test, ürünün
    #    canlıda koşacak sorgusunu değil kendi kopyasını ölçerdi.
    import importlib.util

    from tests.modules.accounting._mu1_migration import BACKEND_DIR

    _yol = (
        BACKEND_DIR / "alembic" / "versions" / "b4d7e1c9f2a3_fathak_canli_tutarsiz_fatura_olcumu.py"
    )
    _spec = importlib.util.spec_from_file_location("_fathak_olcum", _yol)
    assert _spec is not None and _spec.loader is not None
    _mig = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mig)
    AILELER, _olcum_sql = _mig.AILELER, _mig._olcum_sql

    _aile, kaynak_kolonu, hakedis_tablosu, satir_tablosu, satir_fk = AILELER[0]
    assert kaynak_kolonu == "progress_payment_id", "bu test İŞVEREN ailesini ölçer"

    # 1) TEMİZ: brütüne eşit fatura.
    temiz_id = await hakedis_fabrikasi(ProgressPaymentStatus.approved)
    temiz_brut = await hakedis_bruttu(seeded_db, temiz_id, taseron=False)
    await fatura_kes(seeded_db, temiz_id, taseron=False, brut=temiz_brut)

    # 2) İHLALLİ: 1 ₺'lik sahte fatura.
    ihlal_id = await hakedis_fabrikasi(ProgressPaymentStatus.approved)
    ihlal_brut = await hakedis_bruttu(seeded_db, ihlal_id, taseron=False)
    await fatura_kes(seeded_db, ihlal_id, taseron=False, brut=Decimal("1.00"))

    # 3) İADE: tutarı tutmaz ama BAĞLAYICI DEĞİLDİR — sayılmamalı.
    iade_id = await hakedis_fabrikasi(ProgressPaymentStatus.approved)
    await fatura_kes(
        seeded_db,
        iade_id,
        taseron=False,
        brut=Decimal("5.00"),
        document_type=InvoiceDocumentType.refund,
    )

    satir = (
        await seeded_db.execute(_olcum_sql(kaynak_kolonu, hakedis_tablosu, satir_tablosu, satir_fk))
    ).one()

    assert satir.baglayici == 2, "iade faturası bağlayıcı sayıldı (süzgeç çalışmıyor)"
    assert satir.ihlalli == 1, "ölçüm yanlış kümeyi sayıyor"
    assert satir.en_buyuk_sapma == ihlal_brut - Decimal("1.00")
    assert temiz_brut == ihlal_brut, "kurulum: iki hakediş aynı brütte olmalı"
