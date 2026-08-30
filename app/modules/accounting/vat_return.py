"""KDV Beyannamesinin çekirdeği (MU-2 T5) — `projedesign/Muhasebe - KDV Beyanı.dc.html`.

Mockup üç özet kartı (satır 54-69), `Tablo 1 — Matrah ve Vergi` (74-104),
`İndirimler` (107-132) ve `Sonuç` bandını (134-143) çizer.

## 🔴 TEK PARA FORMÜLÜ — bu modülün varlık sebebi

Beyanname faturadan TÜRETİLİR ve faturanın parası `invoicing/amounts.py`de
TANIMLIDIR. Bu modül matrahı SQL'de `SUM(line_total)` diye yeniden yazmaz:
`invoices.tax_base` avans ve teminat düşümünü İÇERİR (`amounts` 4. adım,
`tax_base = subtotal − avans − teminat`), dolayısıyla satır toplamı matrah
DEĞİLDİR. Yeniden yazılsaydı repoda aynı faturanın İKİ farklı matrahı olurdu:
biri fatura ekranında, öteki beyannamede.

Bu yüzden faturalar SATIRLARIYLA çekilir ve her fatura için `amounts.compute`
**yeniden çağrılır**; oran grupları onun döndürdüğü `line_tax_bases` ve
`line_vat_amounts` payları üzerinde kurulur. Bu paylar tanımı gereği başlığa
kuruşu kuruşuna toplanır (`amounts` En Büyük Kalan kuralı), dolayısıyla
gruplamak SAF TOPLAMADIR — bu modülde İKİNCİ BİR YUVARLAMA YOKTUR ve ölçek
gerektiğinde `amounts.round_money` İTHAL EDİLİR, kopyalanmaz.
`test_vat_return_kaynaginda_IKINCI_yuvarlama_YOK` bunu kaynak metninden
denetler; değer testleri tek başına yetmezdi (bugün doğru olan bir kopya formül
`amounts.py` yarın değiştiğinde sessizce sapardı).

`invoicing/summary.py::vat_difference` de başlık `vat_amount`larını çıkarır;
bu modül aynı büyüklüğün oran kırılımını verir ve onunla ÇELİŞMEZ.

## 🔴 Pencere: TEK AY

Mizanın (`trial_balance.py`) BİRİKİMLİ aralığından FARKLIDIR: mockup satır 45
`Haziran 2026` yazar ve beyanname aylıktır. Sınırlar KAPALIDIR
(`ay_ilk ≤ issue_date ≤ ay_son`); ay sonu `calendar.monthrange` ile saf
aritmetiktir. `issue_date` bir `Date` kolonudur — saat/dilim taşımaz.

🔴 `year`/`month` uçta ZORUNLUDUR: bu modül sunucunun "bugün"üne HİÇ ihtiyaç
duymaz (`date.today()`/`utcnow()` çağrılmaz), TB5'in yerel-takvim kusuru burada
yapısal olarak imkânsızdır.

## 🔴 Hangi faturalar sayılır

| Taraf | Yön | Durum |
|---|---|---|
| Hesaplanan KDV | `outgoing` | `sent` · `collected` |
| İndirilecek KDV | `incoming` | `approved` |

🔴 **KRIT-IADE — `document_type` DA BİR GİRDİDİR.** İade faturası
(`InvoiceDocumentType.refund`) aynı yönün normal faturasıyla AYNI kapıdan
geçer ama tutarları **EKSİ İŞARETLE** girer: hesaplanan KDV'yi ve indirilecek
KDV'yi DÜŞÜRÜR. Öncesinde bu modül belge tipini HİÇ görmüyordu ve iade
beyannameyi ARTIRIYORDU. İşaret yerine iadeyi tümüyle SÜZMEK de yanlış olurdu:
o zaman iade hiçbir yerde görünmez, beyan asıl faturanın tamamını taşımaya
devam ederdi. İade fişleri de aynı işareti taşır
(`invoicing.posting.lines_for`), dolayısıyla İŞ 3 mutabakatı (beyanname ↔
`391`/`191` neti) İADE FATURASINDA DA tutar ve bekçisi odur.

`draft` GİRMEZ (fatura henüz kesilmemiştir), `pending` GİRMEZ (henüz
onaylanmamıştır), `disputed` GİRMEZ (itiraz altındadır, indirim hakkı
belirsizdir). Gerekçe `journal_entries`in `POSTING_STATUSES` kanonuyla
paraleldir: mali beyana yalnız KESİNLEŞMİŞ kayıtlar girer. Her durum ayrı bir
testle kilitlidir.

## İstisna işlemler = `vat_rate = 0`

Mockup satır 90-95 vergili grupların ALTINA italik/gri bir `İstisna İşlemler`
satırı çizer: matrah dolu, vergi `0`. Veri modelinde bunun ÖLÇÜLEBİLİR karşılığı
oranı sıfır olan kalemlerdir — bir "istisna" bayrağı İCAT EDİLMEMİŞTİR. Ayrı bir
`exempt_base` alanıyla döner (`taxable_rows`a KARIŞMAZ) çünkü mockup iki ayrı
satır çizer ve `rate=0` grubu listeye konsaydı `Vergi` kolonu her zaman `0` olan
sahte bir "oran" satırı doğardı.

## 🔴 İndirimler TEK SATIR — açık borç

Mockup `Mal Alışları` / `Hizmet Alımları` diye İKİ satır çizer. **Bu ayrımın veri
modelinde karşılığı YOKTUR**: `invoices`/`invoice_lines`/`inventory`/
`procurement` üzerinde `item_type`/`is_service`/`product_type` alanı sıfır
eşleşme verir, kaleme stok bağı da yoktur (`boq_item_id` bilinçli açılmamıştır).
Bir sınıflandırıcı UYDURULMAZ (uydurulsaydı beyanname sahte bir kırılım vaat
ederdi); tek satır `Alışlar` döner ve boşluk borç olarak kayıtlıdır.

## Sonuç: `payable` ↔ `carried_forward`

`fark = hesaplanan − indirilecek`. 🔴 Negatif fark "ödenecek" DEĞİL **DEVREDEN
KDV**'dir; negatif basan bir uygulama devlete borç yerine alacak yazardı. İki
alan da `max(±fark, 0)`tır, dolayısıyla ikisi AYNI ANDA sıfırdan büyük olamaz.
Mockup yalnız `Ödenecek` çizer; alan yine de açılır, sunum kararı frontend'in.

Vade (mockup satır 68 `Vade: 28.07.2026`, dönem Haziran 2026) = **izleyen ayın
28'i**; Aralık dönemi izleyen YILIN Ocak 28'ine taşar.

## Modüller arası import

Bu modül `invoicing.models` + `invoicing.amounts` okur. Döngü YOKTUR: `invoicing`
paketi `accounting`i hiçbir dosyasında import etmez (ölçüldü). `models.py`nin
"başka modül import etmez" kuralı MODEL dosyası içindir — rapor modülünü
bağlamaz, tersi olsaydı türetilmiş her rapor kendi veri kopyasını taşırdı.

## N+1

**İki** sorgu: faturalar, sonra o faturaların TÜM satırları tek `IN` ile. Fatura
başına satır sorgusu koşan bir uygulama aylık yüzlerce faturada patlardı; ölçüm
tahmine değil `before_cursor_execute` sayacına dayanır. Fatura yoksa ikinci
sorgu HİÇ koşmaz.
"""

import calendar
import uuid
from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounting.reports_schemas import (
    VatDeductionRow,
    VatReturnResponse,
    VatTaxableRow,
)
from app.modules.invoicing.amounts import compute, round_money
from app.modules.invoicing.models import (
    Invoice,
    InvoiceDirection,
    InvoiceLine,
    InvoiceStatus,
    is_refund,
)

__all__ = ["build_vat_return", "due_date_for", "month_bounds"]

#: Hesaplanan KDV'ye giren GİDEN durumları — `draft` yok (kesilmemiş fatura).
OUTGOING_STATUSES = (InvoiceStatus.sent, InvoiceStatus.collected)
#: İndirime giren GELEN durumu — `pending`/`disputed` yok (kesinleşmemiş).
INCOMING_STATUSES = (InvoiceStatus.approved,)

#: Mockup satır 117-124'ün iki satırının veri modelinde karşılığı yok (docstring).
DEDUCTION_SOURCE = "Alışlar"

#: Vade günü — mockup satır 68 `28.07.2026`.
DUE_DAY = 28

ZERO = round_money(Decimal(0))

#: 🔴 KRIT-IADE — beyana giren tutarın İŞARETİ. İade faturası aynı yöndeki
#: normal faturanın TERSİDİR: hesaplanan KDV'yi DÜŞÜRÜR, indirilecek KDV'yi
#: DÜŞÜRÜR. `+1` bir süs değildir — sabit olmadan işaret hesabın içine gömülür
#: ve bir mutant onu sessizce silebilirdi.
ISARET_NORMAL = Decimal(1)
ISARET_IADE = Decimal(-1)


def month_bounds(year: int, month: int) -> tuple[date, date]:
    """Ayın ilk ve SON günü — `calendar.monthrange` ile saf aritmetik.

    İki sınır da KAPALIDIR: ayın son günü kesilen fatura o ayın beyanındadır."""
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def due_date_for(year: int, month: int) -> date:
    """Beyanın son ödeme günü — İZLEYEN ayın 28'i.

    Aralık dönemi izleyen YILIN Ocak'ına taşar; `month + 1` diye yazan bir
    uygulama 13. ayı kurmaya çalışıp patlardı."""
    if month == 12:
        return date(year + 1, 1, DUE_DAY)
    return date(year, month + 1, DUE_DAY)


def _counted_filter():  # noqa: ANN202 — SQLAlchemy ifade tipi
    """Yön ve durumun BİRLİKTE kapısı (docstring'deki tablo)."""
    return or_(
        and_(
            Invoice.direction == InvoiceDirection.outgoing,
            Invoice.status.in_(OUTGOING_STATUSES),
        ),
        and_(
            Invoice.direction == InvoiceDirection.incoming,
            Invoice.status.in_(INCOMING_STATUSES),
        ),
    )


async def build_vat_return(session: AsyncSession, *, year: int, month: int) -> VatReturnResponse:
    """Dönemin KDV beyannamesi. HİÇBİR kaydı değiştirmez, yalnız türetir."""
    ilk_gun, son_gun = month_bounds(year, month)

    invoices = (
        (
            await session.execute(
                select(Invoice)
                .where(Invoice.issue_date >= ilk_gun)
                .where(Invoice.issue_date <= son_gun)
                .where(_counted_filter())
                .order_by(Invoice.issue_date, Invoice.id)
            )
        )
        .scalars()
        .all()
    )

    lines_by_invoice = await _load_lines(session, [invoice.id for invoice in invoices])

    # Oran → [matrah, vergi]; istisna (oran 0) ve indirimler AYRI birikir.
    taxable: dict[Decimal, list[Decimal]] = defaultdict(lambda: [ZERO, ZERO])
    exempt_base = ZERO
    deduction_base = ZERO
    deduction_vat = ZERO

    for invoice in invoices:
        lines = lines_by_invoice.get(invoice.id, [])
        # 🔴 TEK PARA FORMÜLÜ: fatura ekranıyla AYNI hesap yeniden çalıştırılır.
        hesap = compute(
            lines,
            advance_rate=invoice.advance_rate,
            retention_rate=invoice.retention_rate,
            withholding_rate=invoice.withholding_rate,
        )
        # 🔴 KRIT-IADE — İADE, aynı yöndeki normal faturanın TERSİ İŞARETLE
        # girer. Öncesinde bu modül `document_type`ı HİÇ görmüyordu ve iade
        # faturası hesaplanan KDV'yi DÜŞÜRECEĞİ yerde ARTIRIYORDU; beyan,
        # devlete olmayan bir borç yazıyordu. Kalemler POZİTİF olmak
        # ZORUNDADIR (`ck_invoice_lines_quantity_positive`), yani ters yön
        # tutarın işaretiyle DEĞİL yalnız burada ifade edilebilir.
        isaret = ISARET_IADE if is_refund(invoice) else ISARET_NORMAL
        if invoice.direction is InvoiceDirection.incoming:
            deduction_base += isaret * hesap.tax_base
            deduction_vat += isaret * hesap.vat_amount
            continue

        for line, matrah, vergi in zip(
            lines, hesap.line_tax_bases, hesap.line_vat_amounts, strict=True
        ):
            if line.vat_rate == 0:
                exempt_base += isaret * matrah
                continue
            grup = taxable[line.vat_rate]
            grup[0] += isaret * matrah
            grup[1] += isaret * vergi

    taxable_rows = [
        VatTaxableRow(rate=oran, base=grup[0], vat=grup[1])
        # Mockup satır 85-88: en yüksek oran ÜSTTE.
        for oran, grup in sorted(taxable.items(), key=lambda ikili: ikili[0], reverse=True)
    ]
    calculated_vat = sum((satir.vat for satir in taxable_rows), ZERO)
    fark = calculated_vat - deduction_vat

    return VatReturnResponse(
        year=year,
        month=month,
        due_date=due_date_for(year, month),
        calculated_vat=calculated_vat,
        deductible_vat=deduction_vat,
        # 🔴 Negatif fark ödenecek DEĞİL devredendir; ikisi birden dolamaz.
        payable=max(fark, ZERO),
        carried_forward=max(-fark, ZERO),
        taxable_rows=taxable_rows,
        exempt_base=exempt_base,
        deductions=(
            [VatDeductionRow(source=DEDUCTION_SOURCE, base=deduction_base, vat=deduction_vat)]
            if deduction_base or deduction_vat
            else []
        ),
    )


async def _load_lines(
    session: AsyncSession, invoice_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[InvoiceLine]]:
    """TÜM satırlar TEK `IN` sorgusuyla (N+1 yasağı). Boş dönemde HİÇ koşmaz.

    Sıra `sort_order` ARTAN: `amounts` artığı En Büyük Kalanda eşitlik hâlinde
    ÖNCEKİ satıra verir, dolayısıyla satır sırası hesabın GİRDİSİDİR ve
    `repository.load_lines` ile aynı sırayı kullanmak zorunludur.
    """
    if not invoice_ids:
        return {}

    rows = (
        (
            await session.execute(
                select(InvoiceLine)
                .where(InvoiceLine.invoice_id.in_(invoice_ids))
                .order_by(InvoiceLine.sort_order, InvoiceLine.id)
            )
        )
        .scalars()
        .all()
    )

    gruplar: dict[uuid.UUID, list[InvoiceLine]] = defaultdict(list)
    for row in rows:
        gruplar[row.invoice_id].append(row)
    return gruplar
