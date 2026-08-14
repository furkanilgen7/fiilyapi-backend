"""Ödeme (tahsilat/ödeme) iş kuralları (HZ-1 T4) — spec §4 uçları 6, 7, 8.

Spec: `docs/superpowers/specs/2026-08-14-hz1-hazine-cekirdegi-design.md`
§2.2, §3 (K5/K6/K7), §4, §5.

## Neden `treasury`de ama izni `invoicing`

Ödeme bir FATURAYA kaydedilir: kapsamı (`visible_invoice`), eşiği (`total`) ve
durum damgası faturanındır — bu yüzden üç ucun da izin kapısı **`invoicing`**tir
(spec §4). İŞ MANTIĞI buna karşılık Hazine'nindir: `payments` tablosu, bakiye
formülü (K2) ve aşırı tahsilat kararı (K6) bu modülde yaşar. `invoicing/router.py`
yalnız YOLU barındırır (spec §5 rota sırası tuzağı), tek satır kural taşımaz.

## 🔴 Import yönü TEK YÖNLÜDÜR (P10 `cost_cards` dersi)

`treasury` → `invoicing` okur (`service.visible_invoice`, `transitions`,
`guards`); `invoicing` paket düzeyinde `treasury`yi OKUMAZ — tek bağ
`invoicing/router.py`nin bu modülü ithal etmesidir ve router'ı kimse ithal
etmez. Çember bu yüzden AÇILMAZ ve gecikmeli import'a da gerek kalmaz.

## 🔴 K7 — EŞİK = KİLİT (WORKFLOW §4, İK-2/İK-3 kanonu)

K6 bir EŞİK denetimidir → kilitsiz yapılamaz. İki eşzamanlı tahsilat AYNI
toplamı okur ve **her ikisi de kapıdan geçer** (İK-3'te iki eşzamanlı ödeme
bordroyu İKİ KEZ ödemişti). Bu yüzden:

    1. KİLİT   — `invoices` satırı, `with_for_update` + `populate_existing`
    2. ödemeler — `Σ payments` (kilitli satırın koruması altında)
    3. hesap    — gövde içi `bank_account_id` referansı
    4. karar    — K6 eşiği (**422**)
    5. yazma + K5 damgası

Kilit **TÜM denetimlerden ÖNCEDİR** (TOCTOU) ve sıra **SABİTTİR**: fatura →
ödemeler → hesap. Ters yönden giren bir yol karşılıklı kilitlenme üretirdi.
Uç 8 (silme) de durumu YENİDEN TÜRETTİĞİ için AYNI kilidi alır — okuma
tarafında kilitsiz bir silme, eşzamanlı bir tahsilatla birleşince faturayı
`collected` bırakıp parayı geri alırdı.

`UPDATE`in örtük satır kilidi YETMEZ: o yazma ANINDA alınır, yani kararın çok
geç bir noktasında. Pencereyi kapatan tek şey OKUMADAKİ açık `FOR UPDATE`tir.

## 🔴 K5 — kısmi tahsilat SATIRDIR, durum TÜRETİLİR

`invoices` üzerinde `paid_amount` kolonu YOKTUR (migration da yoktur). Ödenen =
`Σ payments`, kalan = `invoice.total − Σ payments`; durum bundan türetilerek
damgalanır ve damga **matrisin TANIDIĞI geçişle sınırlıdır**
(`transitions.OUTGOING_TRANSITIONS`). Yani:

* giden fatura, `Σ >= total` ve matris `(status, mark-collected)` çiftini
  tanıyorsa → `collected`;
* **`draft` bir giden fatura tam ödense bile durumu DEĞİŞMEZ** — matriste
  `(draft, mark-collected)` çifti yoktur ve burada uydurulmaz;
* gelen faturada durum Hazine kapsamında HİÇ değişmez (`collected` giden tarafın
  terminalidir, gelen makinede karşılığı yoktur);
* silmede damga GERİ ALINIR: `Σ < total` ise `collected` → o damganın TEK
  kaynağı olan duruma (`sent`) düşer. Hedef sabit yazılmaz, matristen TÜRETİLİR.

## Hangi kural hangi koda düşer

| Durum | Kod | Sınıf |
|---|---|---|
| Görünmeyen/olmayan fatura ya da ödeme | 404 | `NotFoundError` |
| Gövdedeki `bank_account_id` yok | 404 | `NotFoundError` |
| Biçim ihlali (ölçek, `gt=0`, `limit` tavanı, bilinmeyen alan) | 422 | Pydantic |
| **Aşırı tahsilat (K6)** · pasif hesap | 422 | `TreasuryValidationError` |

Yeni `AuditAction` üyesi AÇILMAZ (TB3/T3 kanonu): ayrım `messages.payment_*`
METNİNDEDİR.
"""

import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, TreasuryValidationError
from app.modules.audit import messages
from app.modules.invoicing import guards as invoicing_guards
from app.modules.invoicing import service as invoicing_service
from app.modules.invoicing import transitions
from app.modules.invoicing.models import Invoice, InvoiceDirection, InvoiceStatus
from app.modules.invoicing.transitions import InvoiceAction
from app.modules.treasury import repository
from app.modules.treasury.models import BankAccount, Payment
from app.modules.treasury.schemas import PaymentCreate, PaymentListResponse, PaymentResponse
from app.modules.users.models import User

__all__ = [
    "PERMISSION_MODULE",
    "create_payment",
    "delete_payment",
    "list_payments",
]

PERMISSION_MODULE = invoicing_guards.PERMISSION_MODULE
"""🔴 İzin anahtarı **`invoicing`**tir, `treasury` DEĞİL (spec §4).

Tek kopya `invoicing/guards.py`dedir ve buradan takma adla okunur: ikinci bir
`"invoicing"` string'i yazılsaydı bir gün biri değişir, öteki kalırdı.
"""

# 404 — görünmeyen ile var OLMAYAN ödeme AYNI cümleyi alır. Faturası görünmeyen
# bir ödeme de buraya düşer: ayrı cümle verilseydi elinde kimlik olan kullanıcı
# ödemenin var olduğunu (ve dolayısıyla faturanın da) öğrenirdi.
PAYMENT_MISSING = "Ödeme kaydı bulunamadı"

# 404 — gövdedeki `bank_account_id` yok. Hesap ŞİRKET GENELİDİR (K3), yani
# "görünmeyen hesap" hâli yoktur; 404 yalnız var olmayan kimlik içindir.
PAYMENT_ACCOUNT_MISSING = "Seçilen banka hesabı bulunamadı"

# 422 — kullanımdan kaldırılmış hesaba YENİ para yazılamaz. Repo kanonunda silme
# yolu `is_active=false`tur; oraya yazmaya izin verilseydi o bayrak yalnızca
# listeyi süzen bir SÜS olurdu ve kapatılmış bir kasaya tahsilat girilebilirdi.
PAYMENT_ACCOUNT_INACTIVE = "Kullanımdan kaldırılmış hesaba ödeme kaydedilemez"

# 🔴 422 — K6. Fazla tahsilat hiçbir mockup'ta MODELLENMEMİŞTİR (iade/avans
# kavramı yoktur) ve sessizce kabul etmek bakiyeyi şişirirdi. Karşılaştırma
# `Decimal` üzerinde, KURUŞ BAZINDA ve TAM'dır — tolerans YOKTUR.
PAYMENT_EXCEEDS_TOTAL = "Toplam tahsilat fatura tutarını aşamaz"


def _collected_source_status() -> InvoiceStatus:
    """`collected` damgasının TEK kaynak durumu — matristen TÜRETİLİR.

    Sabit `InvoiceStatus.sent` yazılsaydı geri düşüş matrisin İKİNCİ bir kopyası
    olurdu: `OUTGOING_TRANSITIONS` bir gün değişse damga eski hedefe düşmeye
    devam eder ve iki dosya sessizce ayrışırdı.
    """
    return next(
        durum
        for (durum, islem), hedef in transitions.OUTGOING_TRANSITIONS.items()
        if islem is InvoiceAction.mark_collected and hedef is InvoiceStatus.collected
    )


def _rederive_status(invoice: Invoice, paid_total: Decimal) -> None:
    """🔴 K5 — durumu `Σ payments`ten TÜRETİR (yazma ve silme yolunda AYNI kod).

    İki yol için iki ayrı türetim yazılsaydı biri geri düşüşü unutur ve fatura
    hiç tahsilatı olmadan `collected` kalırdı — saklanan bir `paid_amount`
    olmadığı için hiçbir kolon farkı bunu ele vermezdi.

    GELEN faturaya hiç dokunulmaz: `collected` GİDEN makinenin terminalidir,
    gelen makinede (`pending → approved | disputed`) karşılığı YOKTUR ve
    ödemenin gelen tarafta bir durum üretmesi Hazine kapsamı DIŞIDIR (spec K5).
    """
    if invoice.direction is not InvoiceDirection.outgoing:
        return

    if paid_total >= invoice.total:
        # Damga yalnız matrisin TANIDIĞI geçişle konur: `(draft, mark-collected)`
        # çifti tabloda YOKTUR ve burada uydurulmaz (bir taslak fatura ödenmiş
        # olsa bile GÖNDERİLMEMİŞTİR).
        gecerli = transitions.classify_transition(
            invoice.direction, invoice.status, InvoiceAction.mark_collected
        )
        if gecerli is None:
            invoice.status = transitions.next_status(
                invoice.direction, invoice.status, InvoiceAction.mark_collected
            )
    elif invoice.status is InvoiceStatus.collected:
        # Geri düşüş: damganın dayanağı kalmadı. Yalnız `collected`ten olur —
        # koşulsuz yazılsaydı bir TASLAK fatura, ödemesi silinerek "gönderilmiş"
        # sayılırdı.
        invoice.status = _collected_source_status()


async def _locked_invoice(session: AsyncSession, actor: User, invoice_id: uuid.UUID) -> Invoice:
    """🔴 KİLİT ADIMI — her yazma yolunun İLK işi (K7).

    `visible_invoice(for_update=True)` hem satırı kilitler hem kapsamı denetler;
    kapsam denetimi KİLİTLİ satır üzerinde koşar, böylece kilit ile karar
    arasına başka bir işlem giremez.
    """
    return await invoicing_service.visible_invoice(session, actor, invoice_id, for_update=True)


async def _account_or_404(session: AsyncSession, account_id: uuid.UUID) -> BankAccount:
    """Gövde içi varlık referansı — yok ise **404** (ST kanonu).

    Kilit sırasının SON halkasıdır (fatura → ödemeler → hesap) ve hesap
    KİLİTLENMEZ: hiçbir eşik hesabın durumuna bağlı değildir (bakiye türevdir,
    K2) ve gereksiz bir kilit yalnızca çekişme üretirdi.

    ⚠️ `is_active` denetimi BURADA DEĞİL yalnız YAZMA yolundadır: pasif hesap
    yeni para KABUL ETMEZ ama oraya yanlışlıkla girilmiş bir ödemenin
    SİLİNEBİLMESİ gerekir — kural silmeye de uygulansaydı hesap kapatılır
    kapatılmaz hatası da kalıcılaşırdı.
    """
    account = await repository.get_account(session, account_id)
    if account is None:
        raise NotFoundError(PAYMENT_ACCOUNT_MISSING)
    return account


# --- Uç 6: GET /invoices/{id}/payments ---


async def list_payments(
    session: AsyncSession, actor: User, invoice_id: uuid.UUID, *, limit: int, offset: int
) -> PaymentListResponse:
    """FGI'nin tahsilat listesi + K5'in iki türev toplamı.

    🔴 `paid_total` ve `remaining` **TÜM satırlardan** gelir, sayfadan DEĞİL:
    sayfadan hesaplansaydı `limit`li bir okumada "kalan" birdenbire büyür,
    kullanıcı ekranda gördüğü tutarı girer ve K6'dan 422 alırdı.

    Kilit YOKTUR: okuma bir eşik kararı vermez. Sayfalama ise repo kanonu gereği
    vardır — fatura başına ödeme sayısı küçüktür ama SINIRSIZ bir liste ucu
    açmak, bir gün kalabalıklaşan bir faturada tavanı olmayan tek yer olurdu.
    """
    invoice = await invoicing_service.visible_invoice(session, actor, invoice_id)
    satirlar = await repository.list_payments_for_invoice(
        session, invoice.id, limit=limit, offset=offset
    )
    total = await repository.count_payments_for_invoice(session, invoice.id)
    paid_total = await repository.paid_total_for_invoice(session, invoice.id)
    return PaymentListResponse(
        items=[PaymentResponse.model_validate(satir) for satir in satirlar],
        total=total,
        limit=limit,
        offset=offset,
        paid_total=paid_total,
        remaining=invoice.total - paid_total,
    )


# --- Uç 7: POST /invoices/{id}/payments ---


async def create_payment(
    session: AsyncSession, actor: User, invoice_id: uuid.UUID, data: PaymentCreate
) -> tuple[Payment, str]:
    """🔴 K6 + K7 — sıra modül docstring'indedir ve DEĞİŞTİRİLEMEZ.

    Eşik KİLİTLİ satırın koruması altında okunur; kilit sonraya bırakılsaydı iki
    eşzamanlı istek AYNI `Σ`yı okur, ikisi de kapıdan geçer ve fatura tutarının
    iki katı tahsil edilmiş görünürdü (İK-3 dersi, `test_hz1_payment_lock.py`).

    Eşik MEVCUT toplamı içerir: yalnız `yeni.amount > total` denetlenseydi
    999,99 + 0,02 sessizce geçerdi.
    """
    invoice = await _locked_invoice(session, actor, invoice_id)
    paid_total = await repository.paid_total_for_invoice(session, invoice.id)
    account = await _account_or_404(session, data.bank_account_id)
    if not account.is_active:
        raise TreasuryValidationError(PAYMENT_ACCOUNT_INACTIVE)

    yeni_toplam = paid_total + data.amount
    if yeni_toplam > invoice.total:
        raise TreasuryValidationError(PAYMENT_EXCEEDS_TOTAL)

    payment = Payment(
        invoice_id=invoice.id,
        bank_account_id=account.id,
        method=data.method,
        amount=data.amount,
        paid_on=data.paid_on,
        note=data.note,
        created_by_id=actor.id,
    )
    session.add(payment)
    await session.flush()
    # `updated_at`/`created_at` sunucu damgalarıdır; yanıt şeması onları okuduğunda
    # async bağlamda tembel yükleme `MissingGreenlet` = 500 demektir (P11 dersi).
    await session.refresh(payment)

    _rederive_status(invoice, yeni_toplam)
    await session.flush()
    detail = messages.payment_created(invoice.invoice_no, account.bank_name, account.display_name)
    return payment, detail


# --- Uç 8: DELETE /payments/{id} ---


async def delete_payment(session: AsyncSession, actor: User, payment_id: uuid.UUID) -> str:
    """Yanlış tahsilat geri alınabilmelidir — YALNIZ `admin` (kapı router'da).

    🔴 Kilit sırası burada da SABİTTİR ve ödeme satırı kilidin ARDINDAN yeniden
    okunur: ilk okuma yalnızca faturanın KİMLİĞİNİ öğrenmek içindir, karar
    değildir. Kilit alındıktan sonra taze okuma yapılmasaydı iki eşzamanlı silme
    aynı satırı görür ve ikincisi bayat bir nesneyi silmeye çalışırdı.

    Silme sonrası durum **YENİDEN TÜRETİLİR** (K5): `collected` → `sent`e
    düşebilir. Türetim `create_payment` ile AYNI fonksiyondan geçer.
    """
    ilk_okuma = await repository.get_payment(session, payment_id)
    if ilk_okuma is None:
        raise NotFoundError(PAYMENT_MISSING)

    try:
        invoice = await _locked_invoice(session, actor, ilk_okuma.invoice_id)
    except NotFoundError as exc:
        # Faturası görünmeyen ödeme de "yok"tur: `invoicing`in "Fatura
        # bulunamadı" cümlesi buraya SIZDIRILMAZ, yoksa kullanıcı ödemenin var
        # olduğunu (ve görünmeyen bir faturaya ait olduğunu) öğrenirdi.
        raise NotFoundError(PAYMENT_MISSING) from exc

    payment = await repository.get_payment(session, payment_id, for_update=True)
    if payment is None:
        raise NotFoundError(PAYMENT_MISSING)

    # Hesap kilit sırasının SON halkasıdır ve yalnız denetim METNİ için okunur;
    # `bank_account_id` NOT NULL + FK RESTRICT olduğu için satır YAPISAL OLARAK
    # vardır (404 dalı ulaşılamazdır ama korkuluk olarak durur).
    account = await _account_or_404(session, payment.bank_account_id)
    # Denetim metni silmeden ÖNCE kurulur; sonra kurulsaydı hesap/numara
    # güvenilir okunamaz ve silinenin NE OLDUĞU kaybolurdu.
    detail = messages.payment_deleted(invoice.invoice_no, account.bank_name, account.display_name)

    await session.delete(payment)
    await session.flush()

    _rederive_status(invoice, await repository.paid_total_for_invoice(session, invoice.id))
    await session.flush()
    return detail
