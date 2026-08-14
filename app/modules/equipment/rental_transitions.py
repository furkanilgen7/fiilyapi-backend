"""Kira hakedişinin durum makinesi (MK-2 K5) — TEK kapı, tek tablo.

Geçerli geçişler aşağıdaki iki veri yapısındadır; uçlar ve servis kendi
`if status == …` kontrollerini YAZMAZ. Tabloda olmayan her çift **409**'dur —
"tanımlı olanı say, gerisini reddet" yaklaşımıyla yeni bir durum eklendiğinde
varsayılan davranış REDDETMEKTİR. Desen `payroll/transitions.py`den
(İK-3) gelir ve oradaki gerekçeler burada da geçerlidir.

## Neyin tabloda OLMADIĞI da bir karardır

* **`paid` hiçbir çiftin KAYNAĞI değildir** (K5 "uç damgası"): banka çıkışı olmuş
  bir kaydı geri sarmak, kayıt ile para hareketi arasındaki bağı koparırdı. İkinci
  `pay` çağrısının 409'u da buradan gelir — servis ayrıca bir sayaç tutmaz.
* **`draft → approved` YOKTUR** (adım atlama): "Doğrulama Bekliyor" (M5:65)
  ekranda YAŞANMASI gereken bir hâldir; atlanabilseydi doğrulamanın kendisi
  isteğe bağlı olurdu.
* **Ayrı bir `rejected` durumu YOKTUR** (spec §2.1 enum'u dört değerlidir): red
  `approved → pending_verification` GERİ geçişidir. Ayrı durum açılsaydı
  reddedilen fatura "doğrulama bekleyen" listesinden düşer ve sessizce
  kaybolurdu.

## İleri zincir NİÇİN ayrı bir sözlük

`approved`ın İKİ ardılı vardır (`paid` ileri, `pending_verification` geri);
"sıradaki adım" tek tablodan türetilseydi belirsiz olurdu. `FORWARD_STEP` bu
yüzden AÇIKÇA yazılır ama `TRANSITIONS`ın bir ALT KÜMESİ olduğu modül yüklenirken
doğrulanır (aşağıdaki `assert`): iki yapı sessizce ayrışamaz.
"""

from app.core.errors import ConflictError
from app.modules.equipment.models import RentalInvoiceStatus

#: 🔴 K5 — geçerli geçişlerin TAMAMI. Burada olmayan her çift 409'dur.
TRANSITIONS: frozenset[tuple[RentalInvoiceStatus, RentalInvoiceStatus]] = frozenset(
    {
        (RentalInvoiceStatus.draft, RentalInvoiceStatus.pending_verification),
        (RentalInvoiceStatus.pending_verification, RentalInvoiceStatus.approved),
        (RentalInvoiceStatus.approved, RentalInvoiceStatus.paid),
        # Red: ayrı bir `rejected` durumu YOK (İK-3 red deseni).
        (RentalInvoiceStatus.approved, RentalInvoiceStatus.pending_verification),
    }
)

#: İLERİ zincirin sıradaki adımı. `approve` ucu buradan okur; `paid` hedefi
#: servis tarafında AYRICA reddedilir çünkü ödemenin KENDİ ucu vardır
#: ("Onayla ve Ödemeye Gönder"e basan kullanıcı ödeme yapmış olmamalıdır).
FORWARD_STEP: dict[RentalInvoiceStatus, RentalInvoiceStatus] = {
    RentalInvoiceStatus.draft: RentalInvoiceStatus.pending_verification,
    RentalInvoiceStatus.pending_verification: RentalInvoiceStatus.approved,
    RentalInvoiceStatus.approved: RentalInvoiceStatus.paid,
}

assert all(cift in TRANSITIONS for cift in FORWARD_STEP.items()), (
    "FORWARD_STEP, TRANSITIONS'ın alt kümesi olmalıdır"
)

#: 🔴 K5 — bu durumlarda HİÇBİR ŞEY düzenlenemez (başlık PATCH'i, satır PATCH'i,
#: satır silme). İK-3 S5 emsali: onaylanmış bir ödemenin tutarı sonradan
#: oynatılamaz, yoksa onayın kendisi anlamsızlaşırdı.
EDIT_LOCKED_STATUSES: frozenset[RentalInvoiceStatus] = frozenset(
    {RentalInvoiceStatus.approved, RentalInvoiceStatus.paid}
)

TRANSITION_DENIED = "Kira hakedişi bu duruma geçirilemez."


def assert_transition(current: RentalInvoiceStatus, target: RentalInvoiceStatus) -> None:
    """Tabloda olmayan her çift 409 — ADIM ATLAMA dahil (`draft → paid`)."""
    if (current, target) not in TRANSITIONS:
        raise ConflictError(TRANSITION_DENIED)


def next_forward_step(current: RentalInvoiceStatus) -> RentalInvoiceStatus | None:
    """İleri zincirin sıradaki adımı; sonu olmayan durum (`paid`) `None` döner."""
    return FORWARD_STEP.get(current)
