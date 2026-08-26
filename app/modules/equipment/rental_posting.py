"""🔴 MU-3D — MAKİNE KİRA HAKEDİŞİNİN FİŞİ (KDV'SİZ).

Taşeron ailesiyle AYNI yön: kira hakedişi TEDARİKÇİNİN bize kestiği bir
belgedir, yani gider + cari borç doğurur.

    B 740 Hizmet Üretim Maliyeti = invoice_amount
    A 320 Satıcılar              = invoice_amount

## 🔴 BU AİLE ÖTEKİ İKİSİNDEN ÜÇ YERDE AYRILIR — hepsi ölçüldü

### 1. PARA KOLONU **VAR** (ve bu yüzden BAYATLAMAZ)

Envanterin *"hakedişlerde hiç para kolonu yok"* kaydı BU AİLE İÇİN YANLIŞTIR.
`equipment_rental_invoices` iki para kolonu taşır:

* `invoice_amount: Numeric(18, 2)` **NULLABLE** — 🔴 KDV HARİÇ taban (K1),
* `vat_rate: Numeric(5, 2)` NOT NULL.

Fişin tabanı doğrudan `invoice_amount`tır. Bir avans/teminat kesintisi bu
ailede YOKTUR, dolayısıyla öteki iki ailenin `brüt − avans − teminat`
aritmetiği burada KOŞMAZ ve koşturulmaz — olmayan bir kesintiyi hesaplayan bir
kod, okuyucuya var olmayan bir modeli varmış gibi gösterirdi.

🔴 `our_total` (satırların `saat × birim fiyat` çapraz kontrolü) KULLANILMAZ:
o bir DOĞRULAMA büyüklüğüdür, ödenecek tutar değil. `payable_total` da
KULLANILMAZ çünkü KDV'yi İÇERİR.

🔴 Sonuç: bu ailede fişin tutarı **YAPISAL OLARAK BAYATLAMAZ** — kendi donmuş
kolonundan okunur, hiçbir canlı girdiye bağlı değildir.

### 2. `invoice_amount` NULL OLABİLİR

NULL "girilmedi"dir, sıfır DEĞİL (NULL-EŞİK kanonu). Tutarı girilmemiş bir kira
hakedişi onaylanabilir (DB bunu engellemez, ölçüldü) ve o hâlde FİŞLENECEK PARA
YOKTUR → fiş HİÇ AÇILMAZ. Sıfır sayılsaydı `(0, 0)` bacağı
`ck_journal_lines_single_side`ı ihlal eder, K1'in satır sayısı engeli **422**
verir ve o 422 kullanıcının ONAYINI bloklardı.

### 3. GEÇİŞ MODELİ BİR **KENAR KÜMESİDİR**, `(durum, eylem)` MATRİSİ DEĞİL

`rental_transitions.TRANSITIONS` bir `frozenset[tuple[durum, durum]]`tir ve bu
ailede bir eylem enum'u YOKTUR:

    draft ──▶ pending_verification ──▶ approved ──▶ paid
                       ▲                   │
                       └───────────────────┘   (reject / onay geri alma)

Mali olarak BAĞLAYICI kenar **BİRDİR**: `pending_verification ──▶ approved` —
`approved_by_id` + `approved_at` damgasını yazan ve kaydı düzenlemeye kapatan
(`EDIT_LOCKED_STATUSES`) kenar budur.

🔴 `approve` UCU BİR **TEK ADIM İLERLETİCİDİR** (`next_forward_step`): `draft`
üzerinde çağrıldığında kaydı yalnızca `pending_verification`a taşır ve HİÇBİR
ŞEY damgalamaz. Fiş bu yüzden UÇTAN değil, kaydın FİİLEN `approved` durumuna
geçmesinden doğar — kanca `hedef is RentalInvoiceStatus.approved` dalındadır.
Uca bağlansaydı `draft → pending_verification` adımı da fiş yazar ve
doğrulanmamış bir kira bedeli deftere girerdi.

`approved ──▶ pending_verification` (`reject_invoice`) bir GERİ ALMADIR ve
KARAR-5 gereği STORNO yazar. `approved ──▶ paid` bir ÖDEMEDİR; nakit bacağı
Hazine diliminindir (MU-3C) ve buradan fiş ATILMAZ.

## 🔴 `JournalSourceType.equipment_rental_invoice` — MU-3D'DE AÇILDI

MU-3A üyeyi BİLEREK açmamıştı ("üye ICAT EDILMEZ, fişlendiği dilimde
`ALTER TYPE` ile eklenir"). Migration `b7c8d9e0f1a2`, tohum `a4b5c6d7e8f9`
(ikisi AYRI olmak ZORUNDA — `ADD VALUE` + değeri KULLANMA aynı işlemde HATA).
"""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezone import to_display
from app.modules.accounting import state_service as accounting_state_service
from app.modules.accounting.models import JournalSourceType
from app.modules.accounting.transitions import JournalAction
from app.modules.equipment.models.rental import EquipmentRentalInvoice
from app.modules.posting import repository as posting_repository
from app.modules.posting import service as posting_service
from app.modules.posting.service import PostingLine, PostingOutcome
from app.modules.procurement.models import Supplier
from app.modules.users.models import User

__all__ = [
    "RENTAL_POSTING_RULES",
    "ROLE_EXPENSE",
    "ROLE_PAYABLE",
    "SOURCE_TYPE",
    "description_for",
    "lines_for",
    "post_on_approval",
    "post_rental_invoice",
    "posting_base_for",
    "reverse_rental_invoice",
]

#: üye = TABLO (`equipment_rental_invoices`).
SOURCE_TYPE = JournalSourceType.equipment_rental_invoice

ROLE_EXPENSE = "expense"
ROLE_PAYABLE = "payable"

#: 🔴 TOHUMUN KAYNAĞI — taşeron ailesiyle AYNI kodlar (KARAR-1 + KARAR-2).
#: Aynı olmaları bilinçlidir: ikisi de dışarıdan alınan bir hizmetin
#: maliyetidir ve aynı cari ana hesaba borçlanır.
RENTAL_POSTING_RULES: tuple[tuple[str, str], ...] = (
    (ROLE_EXPENSE, "740"),
    (ROLE_PAYABLE, "320"),
)

_ZERO = Decimal("0")


def description_for(invoice: EquipmentRentalInvoice, supplier_name: str | None) -> str:
    """`Kira hakedişi 2026/07 — Akkaya Makine Ltd.`

    🔴 TUTAR metne GİRMEZ (HZ-1 kanonu). 🔴 Dönem `period_year`/`period_month`
    KOLONLARINDAN okunur ve bu ailede İKİSİ DE NOT NULL'dır (öteki iki ailede
    değildir) — yani metin DAİMA tam kurulur.

    ⚠️ Tedarikçi adı bu ailede bir SNAPSHOT DEĞİLDİR: `equipment_rental_invoices`
    bir `supplier_name` kolonu TAŞIMAZ (taşeron ailesinin aksine) ve ad cari
    karttan CANLI okunur. Bu bir kusurdur ama fişin METNİNE aittir, TUTARINA
    değil — ve bu dilim şema açmaz. `KAPSAM DIŞI`.
    """
    taraf = (supplier_name or "").strip()
    baslik = f"Kira hakedişi {invoice.period_year}/{invoice.period_month:02d}"
    return f"{baslik} — {taraf}" if taraf else baslik


def lines_for(base: Decimal) -> list[PostingLine]:
    """İKİ bacak — sıra SABİTTİR (borç önce, alacak sonra)."""
    return [
        PostingLine(role_key=ROLE_EXPENSE, debit=base),
        PostingLine(role_key=ROLE_PAYABLE, credit=base),
    ]


def posting_base_for(invoice: EquipmentRentalInvoice) -> Decimal:
    """🔴 KDV HARİÇ taban = `invoice_amount`. NULL → `0` (fişlenmez).

    `vat_rate` OKUNMAZ ve okunmamalıdır: hakediş fişi KDV'SİZDİR (kullanıcı
    kararı 2026-08-26) çünkü `vat_return` beyannameyi YALNIZ `invoices`tan
    türetir. KDV yalnız faturada doğar.
    """
    return invoice.invoice_amount if invoice.invoice_amount is not None else _ZERO


async def post_rental_invoice(
    session: AsyncSession,
    actor: User,
    invoice: EquipmentRentalInvoice,
    *,
    entry_date: date,
    supplier_name: str | None,
) -> PostingOutcome | None:
    """Kira hakedişini fişler. `None` = *"fişlenecek para yok"* (tutar girilmemiş).

    🔴 COMMIT ETMEZ: çağıranın (`rental_service.approve_invoice`) kendi
    transaction'ında koşar.
    """
    base = posting_base_for(invoice)
    if base <= _ZERO:
        return None
    return await posting_service.post_document(
        session,
        actor,
        source_type=SOURCE_TYPE,
        source_id=invoice.id,
        entry_date=entry_date,
        description=description_for(invoice, supplier_name),
        lines=lines_for(base),
    )


async def reverse_rental_invoice(session: AsyncSession, actor: User, invoice_id: uuid.UUID) -> bool:
    """🔴 KARAR-5 — CANLI fişi STORNO eder. Gerekçe `progress_payments.posting`ta."""
    entry = await posting_repository.entry_for_source(session, SOURCE_TYPE, invoice_id)
    if entry is None:
        return False
    await accounting_state_service.perform_transition(
        session, actor, entry.id, JournalAction.reverse
    )
    return True


async def post_on_approval(
    session: AsyncSession, actor: User, invoice: EquipmentRentalInvoice
) -> None:
    """🔴 MU-3D — onay kancasının GÖVDESİ. `rental_service`ten ÇAĞRILIR.

    ## Neden `rental_service`te DEĞİL burada

    `rental_service.py` 785 satırdı; gövde orada kalsaydı dosya **832**e çıkıp
    deponun 800 satır tavanını KIRARDI (ölçüldü). Ama yer seçimi bir satır
    sayısı zorunluluğundan İBARET DEĞİLDİR: tedarikçi adının nereden okunduğu
    ve fişin hangi güne yazıldığı FİŞLEME kararlarıdır, kira hakedişinin durum
    makinesinin kararları değil. `rental_service`te kalan tek şey KANCANIN YERİ
    olmalıdır (`hedef is approved` dalı), kancanın İÇERİĞİ değil.

    ## Ne yapar

    Tedarikçi adını çözer ve `post_rental_invoice`i çağırır. Fiş yazılamazsa
    (kapalı dönem **409** · eksik eşleme **422**) onay da GERİ ALINIR —
    "onaylı ama fişsiz" bir kira hakedişi DOĞMAZ. COMMIT ETMEZ.
    """
    # `session.get` — kimlik haritasından okur, ikinci bir sorgu koşmaz
    # (`_supplier_display` ile AYNI desen).
    supplier = await session.get(Supplier, invoice.supplier_id)
    await post_rental_invoice(
        session,
        actor,
        invoice,
        # 🔴 ONAY GÜNÜ — `period_year`/`period_month` DEĞİL. Döneme yazılsaydı
        # geçmiş bir aya ait kira hakedişi KAPALI bir döneme fiş atmayı dener ve
        # KARAR-6'yı delerdi. Damga bu satırdan hemen ÖNCE basılır.
        #
        # 🔴 `to_display` ŞART, çıplak `.date()` DEĞİL (TB5 yerel takvim bekçisi
        # bunu yakaladı): `approved_at` bir `timestamptz`tir ve ham `.date()`
        # UTC gününü verir. TR UTC+3 olduğu için gece 00:00-03:00 arasında
        # onaylanan bir hakedişin fişi BİR GÜN GERİYE düşer — ay sınırında ise
        # ÖNCEKİ AYIN mizanına, hatta KAPALI bir döneme.
        entry_date=to_display(invoice.approved_at).date(),
        supplier_name=supplier.name if supplier is not None else None,
    )
