"""FIN-PAY — ödeme ↔ çek/senet bağının YAZMA yüzeyi.

`payments.financial_instrument_id` FK'si FIN-1'de açıldı ama yazma yüzeyi
yoktu: bir ödeme hiçbir yoldan bir çeke/senede bağlanamıyordu. Bu dilim var
olan İKİ uca (`POST`/`GET /invoices/{id}/payments`) alan ekler; **yeni yol
açılmaz**.

## Bu dosyanın kilitlediği kararlar

1. **K1 — alan İSTEĞE BAĞLIDIR.** `method='cheque'` iken bile zorunlu değildir:
   etiket (`method`) ile varlık (`financial_instrument_id`) AYRI iki olgudur
   (`models.py:226`). Gönderilmeyen alanla ödeme 201 döner ve kolon `NULL`dur.
2. **K2 — var olmayan YA DA GÖRÜNMEYEN enstrüman → 404**, sessiz `None` DEĞİL.
   Gövdede kimlik gönderilip `NULL` yazılsaydı kullanıcı bağladığını sanırdı;
   ham `IntegrityError`a bırakılsaydı 500 olurdu.
3. 🔴 **K3 — YÖN UYUMU.** Uyumlu çiftler `balance.inflow_condition()`tan ÖLÇÜLDÜ:
   *giden* fatura bizim kestiğimizdir → tahsilat → elimize *alınan* (`received`)
   çek girer; *gelen* fatura bize kesilmiştir → ödeme → *verilen* (`issued`) çek
   çıkar. Ters çift **422**dir.
4. 🔴 **K4 — ÇİFT SAYIM YOK.** Bağ bir ETİKETTİR: hiçbir para türevine girdi
   EKLEMEZ. Bağlı bir ödeme banka bakiyesini, nakit akışını ve çek/senet
   `summary` kartlarını bağsız bir ödemeyle **BİREBİR AYNI** oynatır.
5. **K7 — `PaymentResponse` yalnız SAKLANAN kolonu döndürür**; çek no/vade gibi
   türev alan eklenmez (tek kaynak kuralı).
6. **K8 — denetim günlüğü DEĞİŞMEZ**: satır sayısı da metin de bağdan etkilenmez.
"""

import uuid
from decimal import Decimal

from sqlalchemy import select

from app.modules.audit import messages
from app.modules.audit.models import AuditAction, AuditLog
from app.modules.invoicing.models import InvoiceDirection, InvoiceStatus
from app.modules.treasury.instruments import guards as instrument_guards
from app.modules.treasury.models import (
    FinancialInstrumentDirection,
    FinancialInstrumentStatus,
    Payment,
)
from app.modules.treasury.payments_service import PAYMENT_INSTRUMENT_DIRECTION_MISMATCH


def _yol(invoice) -> str:  # noqa: ANN001
    return f"/invoices/{invoice.id}/payments"


def _govde(account, amount: str, **fazlasi) -> dict:  # noqa: ANN001
    return {
        "bank_account_id": str(account.id),
        "method": "cheque",
        "amount": amount,
        "paid_on": "2026-08-14",
        **fazlasi,
    }


async def _kolon(seeded_db, payment_id: str):  # noqa: ANN001
    """Kolonu DB'den TAZE okur: uçtan dönen gövdeye bakmak alanın gerçekten
    YAZILDIĞINI değil yalnızca hesaplandığını kanıtlardı."""
    satir = (
        await seeded_db.execute(select(Payment).where(Payment.id == uuid.UUID(payment_id)))
    ).scalar_one()
    await seeded_db.refresh(satir)
    return satir.financial_instrument_id


# --------------------------------------------------------------------------- #
# K1 — alan İSTEĞE BAĞLIDIR (geriye uyum)
# --------------------------------------------------------------------------- #


async def test_alan_GONDERILMEDEN_odeme_201_ve_kolon_NULL(
    client, muhasebe_headers, seeded_db, fatura_fabrikasi, hesap_fabrikasi, odeme_eslemesi
) -> None:
    """Mevcut istemciler alanı hiç bilmez; zorunlu kılınsaydı hepsi 422 alırdı."""
    invoice = await fatura_fabrikasi(total="1000.00")
    account = await hesap_fabrikasi()

    resp = await client.post(
        _yol(invoice), json=_govde(account, "100.00"), headers=muhasebe_headers
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["financial_instrument_id"] is None
    assert await _kolon(seeded_db, resp.json()["id"]) is None


async def test_method_cheque_olsa_bile_bag_ZORUNLU_DEGIL(
    client, muhasebe_headers, fatura_fabrikasi, hesap_fabrikasi, odeme_eslemesi
) -> None:
    """🔴 K1 — etiket varlığı İMA ETMEZ (`models.py:226`)."""
    invoice = await fatura_fabrikasi(total="1000.00")
    account = await hesap_fabrikasi()

    resp = await client.post(
        _yol(invoice), json=_govde(account, "100.00", method="cheque"), headers=muhasebe_headers
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["financial_instrument_id"] is None


async def test_acikca_null_gonderilen_bag_da_201(
    client, muhasebe_headers, fatura_fabrikasi, hesap_fabrikasi, odeme_eslemesi
) -> None:
    """`null` "bağ yok" demektir; 404'e düşseydi alan fiilen zorunlu olurdu."""
    invoice = await fatura_fabrikasi(total="1000.00")
    account = await hesap_fabrikasi()

    resp = await client.post(
        _yol(invoice),
        json=_govde(account, "100.00", financial_instrument_id=None),
        headers=muhasebe_headers,
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["financial_instrument_id"] is None


# --------------------------------------------------------------------------- #
# Uyumlu bağ — İKİ YÖN de yazılır
# --------------------------------------------------------------------------- #


async def test_GIDEN_faturaya_ALINAN_cek_baglanir_201(
    client,
    muhasebe_headers,
    seeded_db,
    fatura_fabrikasi,
    hesap_fabrikasi,
    cek_fabrikasi,
    odeme_eslemesi,
) -> None:
    """🔴 K3 uyumlu çifti — yön `balance.inflow_condition()`tan ÖLÇÜLDÜ.

    Giden fatura bizim kestiğimizdir → tahsilat → hesaba GİRİŞ → elimize
    **alınan** çek girer.
    """
    invoice = await fatura_fabrikasi(direction=InvoiceDirection.outgoing, total="1000.00")
    account = await hesap_fabrikasi()
    cek = await cek_fabrikasi(direction=FinancialInstrumentDirection.received)

    resp = await client.post(
        _yol(invoice),
        json=_govde(account, "100.00", financial_instrument_id=str(cek.id)),
        headers=muhasebe_headers,
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["financial_instrument_id"] == str(cek.id)
    assert await _kolon(seeded_db, resp.json()["id"]) == cek.id


async def test_GELEN_faturaya_VERILEN_senet_baglanir_201(
    client,
    muhasebe_headers,
    seeded_db,
    fatura_fabrikasi,
    hesap_fabrikasi,
    cek_fabrikasi,
    odeme_eslemesi,
) -> None:
    """K3'ün öbür yarısı: gelen fatura bize kesilmiştir → ödeme → **verilen**."""
    invoice = await fatura_fabrikasi(direction=InvoiceDirection.incoming, total="1000.00")
    account = await hesap_fabrikasi()
    senet = await cek_fabrikasi(direction=FinancialInstrumentDirection.issued)

    resp = await client.post(
        _yol(invoice),
        json=_govde(account, "100.00", financial_instrument_id=str(senet.id)),
        headers=muhasebe_headers,
    )

    assert resp.status_code == 201, resp.text
    assert await _kolon(seeded_db, resp.json()["id"]) == senet.id


async def test_PORTFOY_DISI_cek_de_baglanabilir(
    client, muhasebe_headers, fatura_fabrikasi, hesap_fabrikasi, cek_fabrikasi, odeme_eslemesi
) -> None:
    """Durum denetimi YOKTUR ve uydurulmaz: tahsil edilmiş bir çekin ödemesi
    tam olarak o çek tahsil edildiği için kaydedilir. `portfolio` şartı
    konsaydı gerçek akış (önce tahsil, sonra kayıt) reddedilirdi."""
    invoice = await fatura_fabrikasi(direction=InvoiceDirection.outgoing, total="1000.00")
    account = await hesap_fabrikasi()
    cek = await cek_fabrikasi(
        direction=FinancialInstrumentDirection.received,
        status=FinancialInstrumentStatus.collected,
    )

    resp = await client.post(
        _yol(invoice),
        json=_govde(account, "100.00", financial_instrument_id=str(cek.id)),
        headers=muhasebe_headers,
    )

    assert resp.status_code == 201, resp.text


# --------------------------------------------------------------------------- #
# K2 — var olmayan / görünmeyen enstrüman → 404
# --------------------------------------------------------------------------- #


async def test_VAR_OLMAYAN_enstruman_404_sessiz_NULL_DEGIL(
    client, muhasebe_headers, seeded_db, fatura_fabrikasi, hesap_fabrikasi
) -> None:
    """🔴 K2 — 500 DEĞİL, sessiz `None` DEĞİL.

    Sessiz `None` yazılsaydı kullanıcı bağladığını sanırdı; FK ihlaline
    bırakılsaydı ham `IntegrityError` 500 olarak sızardı.
    """
    invoice = await fatura_fabrikasi(total="1000.00")
    account = await hesap_fabrikasi()

    resp = await client.post(
        _yol(invoice),
        json=_govde(account, "100.00", financial_instrument_id=str(uuid.uuid4())),
        headers=muhasebe_headers,
    )

    assert resp.status_code == 404, resp.text
    # Metin çek/senet uçlarınınkiyle AYNI sabittendir: ikinci bir cümle
    # yazılsaydı aynı olgu iki uçtan iki farklı şekilde bildirilirdi.
    assert resp.json()["detail"] == instrument_guards.INSTRUMENT_MISSING
    # Hiçbir satır yazılmamalı: 404'ten sonra kısmi bir ödeme kalsaydı bağsız
    # bir para kaydı doğar ve kullanıcı onu hiç görmezdi.
    assert (await seeded_db.execute(select(Payment))).scalars().all() == []


async def test_GORUNMEYEN_projenin_ceki_404(
    client,
    kapsamli_muhasebe_headers,
    fatura_fabrikasi,
    hesap_fabrikasi,
    cek_fabrikasi,
    gorunmeyen_proje,
) -> None:
    """Görünmeyen kayıt var olmayanla AYNI 404'ü alır (repo kanonu).

    Sessiz `None` ya da 403 verilseydi, kullanıcı elindeki kimliğin GERÇEK bir
    çeke ait olduğunu öğrenirdi (yan kanal).
    """
    invoice = await fatura_fabrikasi(direction=InvoiceDirection.outgoing, total="1000.00")
    account = await hesap_fabrikasi()
    cek = await cek_fabrikasi(
        direction=FinancialInstrumentDirection.received, project=gorunmeyen_proje
    )

    resp = await client.post(
        _yol(invoice),
        json=_govde(account, "100.00", financial_instrument_id=str(cek.id)),
        headers=kapsamli_muhasebe_headers,
    )

    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"] == instrument_guards.INSTRUMENT_MISSING


# --------------------------------------------------------------------------- #
# 🔴 K3 — TERS YÖN 422
# --------------------------------------------------------------------------- #


async def test_GIDEN_faturaya_VERILEN_cek_422(
    client, muhasebe_headers, seeded_db, fatura_fabrikasi, hesap_fabrikasi, cek_fabrikasi
) -> None:
    """🔴 K3 — giden fatura bir TAHSİLATtır; verilen (`issued`) bir çek oraya
    bağlanamaz, yoksa portföyün yönü ile paranın yönü çelişirdi."""
    invoice = await fatura_fabrikasi(direction=InvoiceDirection.outgoing, total="1000.00")
    account = await hesap_fabrikasi()
    cek = await cek_fabrikasi(direction=FinancialInstrumentDirection.issued)

    resp = await client.post(
        _yol(invoice),
        json=_govde(account, "100.00", financial_instrument_id=str(cek.id)),
        headers=muhasebe_headers,
    )

    assert resp.status_code == 422, resp.text
    # 🔴 Çıplak `422` YETMEZ: bilinmeyen alan/biçim ihlali de 422 verir. Alan
    # eklenmeden ÖNCE bu test `extra="forbid"` sayesinde YEŞİLDİ ve hiçbir şey
    # bekçilik etmiyordu — metin iddiası onu gerçek bir bekçiye çevirir.
    assert resp.json()["detail"] == PAYMENT_INSTRUMENT_DIRECTION_MISMATCH
    assert (await seeded_db.execute(select(Payment))).scalars().all() == []


async def test_GELEN_faturaya_ALINAN_cek_422(
    client, muhasebe_headers, fatura_fabrikasi, hesap_fabrikasi, cek_fabrikasi
) -> None:
    """K3'ün öbür yarısı — denetim TERS kurulsaydı bu test yeşil kalır, üstteki
    kırmızı olurdu; ikisi birlikte yönü KİLİTLER."""
    invoice = await fatura_fabrikasi(direction=InvoiceDirection.incoming, total="1000.00")
    account = await hesap_fabrikasi()
    cek = await cek_fabrikasi(direction=FinancialInstrumentDirection.received)

    resp = await client.post(
        _yol(invoice),
        json=_govde(account, "100.00", financial_instrument_id=str(cek.id)),
        headers=muhasebe_headers,
    )

    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == PAYMENT_INSTRUMENT_DIRECTION_MISMATCH


# --------------------------------------------------------------------------- #
# 🔴 K4 — ÇİFT SAYIM BEKÇİSİ
# --------------------------------------------------------------------------- #


async def _para_goruntusu(client, headers) -> dict:  # noqa: ANN001
    """Üç para yüzeyinin BİRLİKTE anlık görüntüsü.

    Tek yüzeye bakılsaydı, bağın öbür ikisine sızması görülmezdi.
    """
    hesaplar = await client.get("/bank-accounts", headers=headers)
    nakit = await client.get("/treasury/cash-flow?year=2026&month=8", headers=headers)
    ozet = await client.get("/financial-instruments/summary", headers=headers)
    assert hesaplar.status_code == 200, hesaplar.text
    assert nakit.status_code == 200, nakit.text
    assert ozet.status_code == 200, ozet.text
    return {
        "bakiyeler": {k["id"]: k["balance"] for k in hesaplar.json()["items"]},
        "nakit": nakit.json(),
        "ozet": ozet.json(),
    }


async def test_K4_bagli_odeme_para_turevlerini_bagsiz_odemeyle_AYNI_oynatir(
    client, admin_headers, fatura_fabrikasi, hesap_fabrikasi, cek_fabrikasi, odeme_eslemesi
) -> None:
    """🔴 K4 — bağ bir ETİKETTİR, hiçbir para türevine GİRDİ EKLEMEZ.

    `balance.py` bakiyeyi `Σ payments.amount` üzerinden türetir; çek/senet
    portföyü AYRI bir yüzeydir. Bağ bir türeve sızsaydı aynı para İKİ KEZ
    sayılırdı ve hiçbir kolon farkı bunu ele vermezdi (bakiye SAKLANMIYOR).

    Yöntem: aynı tutarlı İKİ ödeme — biri bağsız, biri bağlı — ve iki ödemenin
    ÜÇ yüzeydeki etkisinin BİREBİR aynı olduğu iddia edilir. Tek bir ödemeyle
    yazılsaydı "hiç oynamadı" ile "aynı oynadı" ayırt edilemezdi.
    """
    account = await hesap_fabrikasi(opening_balance="0.00")
    cek = await cek_fabrikasi(direction=FinancialInstrumentDirection.received, amount="500.00")
    fatura_a = await fatura_fabrikasi(direction=InvoiceDirection.outgoing, total="1000.00")
    fatura_b = await fatura_fabrikasi(direction=InvoiceDirection.outgoing, total="1000.00")

    baslangic = await _para_goruntusu(client, admin_headers)

    bagsiz = await client.post(
        _yol(fatura_a), json=_govde(account, "500.00"), headers=admin_headers
    )
    assert bagsiz.status_code == 201, bagsiz.text
    bagsiz_sonrasi = await _para_goruntusu(client, admin_headers)

    bagli = await client.post(
        _yol(fatura_b),
        json=_govde(account, "500.00", financial_instrument_id=str(cek.id)),
        headers=admin_headers,
    )
    assert bagli.status_code == 201, bagli.text
    assert bagli.json()["financial_instrument_id"] == str(cek.id)
    bagli_sonrasi = await _para_goruntusu(client, admin_headers)

    # 1) BAKİYE — iki ödeme de hesabı TAM 500 oynatır.
    def _bakiye(goruntu: dict) -> Decimal:
        return Decimal(goruntu["bakiyeler"][str(account.id)])

    bagsiz_delta = _bakiye(bagsiz_sonrasi) - _bakiye(baslangic)
    bagli_delta = _bakiye(bagli_sonrasi) - _bakiye(bagsiz_sonrasi)
    assert bagsiz_delta == Decimal("500.00")
    assert bagli_delta == bagsiz_delta

    # 2) NAKİT AKIŞI — aynı gün, aynı giriş artışı.
    def _giris(goruntu: dict) -> Decimal:
        return Decimal(goruntu["nakit"]["inflow_total"])

    assert _giris(bagsiz_sonrasi) - _giris(baslangic) == Decimal("500.00")
    assert _giris(bagli_sonrasi) - _giris(bagsiz_sonrasi) == Decimal("500.00")
    assert Decimal(bagli_sonrasi["nakit"]["outflow_total"]) == Decimal(
        baslangic["nakit"]["outflow_total"]
    )

    # 3) ÇEK/SENET ÖZETİ — 🔴 üç anda da BİREBİR AYNI. Çek zaten portföydeydi;
    #    bir ödemeye bağlanması onu portföyden ÇIKARMAZ ve kartları oynatmaz
    #    (durum geçişi AYRI bir uçtur, K5 emsali).
    assert bagsiz_sonrasi["ozet"] == baslangic["ozet"]
    assert bagli_sonrasi["ozet"] == baslangic["ozet"]


# --------------------------------------------------------------------------- #
# Uç 6 — GET listesi alanı döndürür
# --------------------------------------------------------------------------- #


async def test_liste_ucu_bagi_dondurur_bagsizi_NULL_basar(
    client,
    muhasebe_headers,
    pm_headers,
    fatura_fabrikasi,
    hesap_fabrikasi,
    cek_fabrikasi,
    odeme_eslemesi,
) -> None:
    """Yalnız POST'a eklenip GET'e eklenmeseydi kullanıcı yazdığı bağı hiçbir
    ekranda GÖREMEZDİ (yazılabilen ama okunamayan bir alan sınıfı)."""
    invoice = await fatura_fabrikasi(direction=InvoiceDirection.outgoing, total="1000.00")
    account = await hesap_fabrikasi()
    cek = await cek_fabrikasi(direction=FinancialInstrumentDirection.received)

    bagli = await client.post(
        _yol(invoice),
        json=_govde(account, "100.00", financial_instrument_id=str(cek.id)),
        headers=muhasebe_headers,
    )
    assert bagli.status_code == 201, bagli.text
    bagsiz = await client.post(
        _yol(invoice), json=_govde(account, "200.00"), headers=muhasebe_headers
    )
    assert bagsiz.status_code == 201, bagsiz.text

    resp = await client.get(_yol(invoice), headers=pm_headers)

    assert resp.status_code == 200, resp.text
    baglar = {satir["id"]: satir["financial_instrument_id"] for satir in resp.json()["items"]}
    assert baglar[bagli.json()["id"]] == str(cek.id)
    assert baglar[bagsiz.json()["id"]] is None


async def test_K7_yanit_TUREV_alan_TASIMAZ(
    client, muhasebe_headers, fatura_fabrikasi, hesap_fabrikasi, cek_fabrikasi, odeme_eslemesi
) -> None:
    """🔴 K7 — yalnız SAKLANAN kolon döner. Çek no/vade/kesideci eklenseydi tek
    kaynak bozulur, çek düzeltilince ödeme yanıtı BAYAT kalırdı."""
    invoice = await fatura_fabrikasi(direction=InvoiceDirection.outgoing, total="1000.00")
    account = await hesap_fabrikasi()
    cek = await cek_fabrikasi(direction=FinancialInstrumentDirection.received)

    resp = await client.post(
        _yol(invoice),
        json=_govde(account, "100.00", financial_instrument_id=str(cek.id)),
        headers=muhasebe_headers,
    )

    assert resp.status_code == 201, resp.text
    assert set(resp.json()) == {
        "id",
        "invoice_id",
        "bank_account_id",
        "financial_instrument_id",
        "method",
        "amount",
        "paid_on",
        "note",
        "created_by_id",
        "created_at",
        "updated_at",
    }


# --------------------------------------------------------------------------- #
# Mevcut davranış DEĞİŞMEDİ
# --------------------------------------------------------------------------- #


async def test_GORUNMEYEN_projenin_faturasinda_IDOR_YOK(
    client,
    kapsamli_muhasebe_headers,
    fatura_fabrikasi,
    hesap_fabrikasi,
    cek_fabrikasi,
    gorunmeyen_proje,
) -> None:
    """Fatura kapsamı bağdan ÖNCE denetlenir: geçerli bir çek kimliği vermek
    görünmeyen bir faturaya yazma yolu AÇMAZ."""
    invoice = await fatura_fabrikasi(
        direction=InvoiceDirection.outgoing, total="1000.00", project=gorunmeyen_proje
    )
    account = await hesap_fabrikasi()
    cek = await cek_fabrikasi(direction=FinancialInstrumentDirection.received)

    resp = await client.post(
        _yol(invoice),
        json=_govde(account, "100.00", financial_instrument_id=str(cek.id)),
        headers=kapsamli_muhasebe_headers,
    )

    assert resp.status_code == 404, resp.text


async def test_K8_denetim_gunlugu_satiri_da_metni_de_DEGISMEDI(
    client,
    muhasebe_headers,
    seeded_db,
    fatura_fabrikasi,
    hesap_fabrikasi,
    cek_fabrikasi,
    odeme_eslemesi,
) -> None:
    """🔴 K8 — bağ varlığı `messages.payment_created(...)` metnine SIZMAZ.

    Sızsaydı mevcut testlerin metin iddiaları kırılırdı; bu dilimin iddiası
    "mevcut davranış DEĞİŞMEZ"tir.
    """
    invoice = await fatura_fabrikasi(direction=InvoiceDirection.outgoing, total="1000.00")
    account = await hesap_fabrikasi()
    cek = await cek_fabrikasi(direction=FinancialInstrumentDirection.received)

    bagsiz = await client.post(
        _yol(invoice), json=_govde(account, "100.00"), headers=muhasebe_headers
    )
    assert bagsiz.status_code == 201, bagsiz.text
    bagli = await client.post(
        _yol(invoice),
        json=_govde(account, "100.00", financial_instrument_id=str(cek.id)),
        headers=muhasebe_headers,
    )
    assert bagli.status_code == 201, bagli.text

    kayitlar = (
        (
            await seeded_db.execute(
                select(AuditLog)
                .where(AuditLog.action == AuditAction.create)
                .order_by(AuditLog.occurred_at)
            )
        )
        .scalars()
        .all()
    )
    olusturma = [k for k in kayitlar if k.detail.startswith("Ödeme kaydı eklendi")]
    # Bağ, FAZLADAN bir satır da üretmez: portföy geçişi AYRI bir uçtur.
    assert len(olusturma) == 2
    # Metin `messages.payment_created(...)`ın BUGÜNKÜ üç argümanıyla kurulur.
    beklenen = messages.payment_created(invoice.invoice_no, account.bank_name, account.display_name)
    # 🔴 İki satır BİREBİR AYNIDIR: bağ metne sızsaydı ayrışırlardı.
    assert olusturma[0].detail == beklenen
    assert olusturma[1].detail == beklenen
    assert str(cek.id) not in olusturma[1].detail


async def test_bagli_odeme_silinince_durum_TURETIMI_bozulmadi(
    client,
    admin_headers,
    seeded_db,
    fatura_fabrikasi,
    hesap_fabrikasi,
    cek_fabrikasi,
    odeme_eslemesi,
) -> None:
    """K5 türetimi bağdan ETKİLENMEZ: tam ödeme `collected` damgalar, silme
    `sent`e geri düşürür."""
    invoice = await fatura_fabrikasi(
        direction=InvoiceDirection.outgoing, status=InvoiceStatus.sent, total="1000.00"
    )
    account = await hesap_fabrikasi()
    cek = await cek_fabrikasi(direction=FinancialInstrumentDirection.received)

    olustur = await client.post(
        _yol(invoice),
        json=_govde(account, "1000.00", financial_instrument_id=str(cek.id)),
        headers=admin_headers,
    )
    assert olustur.status_code == 201, olustur.text
    await seeded_db.refresh(invoice)
    assert invoice.status is InvoiceStatus.collected

    sil = await client.delete(f"/payments/{olustur.json()['id']}", headers=admin_headers)

    assert sil.status_code == 204, sil.text
    await seeded_db.refresh(invoice)
    assert invoice.status is InvoiceStatus.sent


async def test_YOL_ve_OPERASYON_sayisi_SABIT_kalir() -> None:
    """🔴 Kapsam: TB6-T1 (`GET/PUT /payroll/tax-brackets`) İKİ YENİ YOL açtı.

    🔴 Kapsam bekçisi (tripwire): "yol" ile "operasyon" AYRI ölçülerdir
    (Kanon 3). Bu dosya kendi başına var olan İKİ uca (`POST`/`GET
    /invoices/{id}/payments`) alan ekler, yeni yol AÇMAZ — ama sayaç dosya
    bazlı değil, TÜM uygulamayı ölçer: başka bir dilim aynı anda gerçekten
    yeni uç eklerse bu test kırmızı olur ve kapsam genişlemesi GÖRÜNÜR hâle
    gelir. Sabitler bilinçli olarak ELLE yazılmıştır, tam da bu yüzden.

    Bugünkü değer FIN-PAY (bu dosya) + TB6'nın (`GET /payroll/tax-brackets`
    ve `PUT /payroll/tax-brackets/{year}/{income_kind}` — İKİ ayrı yol) +
    **OK-1A'nın BEŞ yeni yolu**nun toplamıdır.

    🔴 OK-1A (onay zinciri motoru) BİLEREK ve GEREKÇELİ olarak **+4 yol /
    +5 operasyon** ekler: `GET /approvals` · `GET /approvals/settings` ·
    `PUT /approvals/settings` · `GET /approvals/roles` ·
    `PUT /approvals/roles/{user_id}`.

    🔴 **KANON 3 BURADA ISIRDI:** OK-1A tasarım sözleşmesi bu dilimi "5 yol /
    5 operasyon" diye bağlamıştı; ÖLÇÜM onu çürüttü. `/approvals/settings`
    **TEK YOLDUR** ve üzerinde İKİ operasyon (GET + PUT) taşır. Yani
    226→**230** · 333→**338**. Sayılar ölçülerek yazıldı, sayılarak değil.

    🔴 **İK-2.2 (+1 yol / +1 operasyon):** `POST /leave-requests/{request_id}/withdraw`
    — kullanıcının KENDİ bekleyen izin talebini geri çekmesi. Yeni bir YOLDUR
    (mevcut `{request_id}` yolunun altına ayrı bir alt-yol açar) ve üzerinde TEK
    operasyon (POST) taşır; `approve`/`reject` emsalinin birebir kardeşi. Yani
    230→**231** · 338→**339**.

    🔴 **MK-4 (+1 yol / +1 operasyon):** `GET /equipment/{equipment_id}/detail`
    — Ekipman Detay ekranının TÜREV blokları (bakım penceresi + kümülatif
    ödenen). Yeni bir YOLDUR; `GET /equipment/{equipment_id}` gövdesi
    DEĞİŞMEDİ (türevler künyeye konsaydı LİSTE ucu da her çizilişte hareket
    tablosunu tarardı). `GET /equipment/rental-invoices`a eklenen
    `equipment_id` SÜZGECİ ise **ne yol ne operasyon** açar — Kanon 3'ün
    üçüncü ölçüsü: bir sorgu parametresi sözleşmeyi genişletir ama bu iki
    sayacın hiçbirini oynatmaz (sürüklenmeyi `tests/contract/` yakalar).
    Yani 231→**232** · 339→**340**.
    """
    from app.main import app

    sema = app.openapi()
    yollar = sema["paths"]
    operasyonlar = sum(
        1
        for uc in yollar.values()
        for metot in uc
        if metot in {"get", "post", "put", "patch", "delete"}
    )
    assert len(yollar) == 232
    assert operasyonlar == 340
