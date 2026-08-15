"""Yevmiye fişinin durum makinesi — 🔴 **TEK KAYNAK** (MU-1 spec §5, K2).

    draft ──post──▶ posted ──reverse──▶ reversed
                                   (+ YENİ storno fişi, doğrudan `posted`)

Geçerli geçişlerin TAMAMI `JOURNAL_TRANSITIONS`tadır; uçlar ve servis kendi
`if status == …` denetimini **YAZMAZ** (`invoicing/transitions.py` deseni).
Tabloda olmayan her çift **409**dur — "tanımlı olanı say, gerisini reddet"
yaklaşımıyla ileride yeni bir durum eklenirse varsayılan davranış REDDETMEKTİR.

## 🔴 `reversed` TERMİNALDİR

Hiçbir çiftte KAYNAK değildir. Stornonun stornosu sonsuz bir zincir açardı ve
mali anlamı yoktur: bir ters kaydı "iptal etmenin" yolu orijinali yeniden
girmektir. `state_service` bu kuralı ayrıca `reversal_of_id IS NOT NULL`
üzerinden de kapatır (`guards.REVERSAL_NOT_REVERSIBLE`), çünkü matris yalnız
DURUMA bakar ve bir storno `posted`tır.

## 🔴 `reversed` fiş BAKİYEDEN DÜŞMEZ

Bu dosya durumu, `balance.POSTING_STATUSES` ise DEFTERE GİRİŞİ tanımlar ve ikisi
AYRI sorulardır: kayıtlaştırılmış fiş defterden ÇIKMAZ, yalnız ters kaydıyla
NÖTRLENİR. `reversed` bakiyeden düşürülseydi orijinal silinir, storno ters
bacaklarıyla eklenir ve net **−orijinal** çıkardı (çift ters kayıt, R6).

## Neyin tabloda OLMADIĞI da bir karardır (spec §9)

* **`posted → draft` "geri al" YOKTUR** — mali izi delerdi; düzeltmenin tek yolu
  stornodur.
* **`draft` için onay akışı (`request`/`approve`) YOKTUR** — hiçbir mockup ara
  bir onay adımı çizmemiştir.
* **Dönem kilidi (`accounting_periods`) YOKTUR** — MU-2'nindir; yapı hazırdır
  (`period_year`/`period_month` + `ix_journal_entries_period`).

## Düzenleme/silme kapıları neden BURADA

Bunlar bir GEÇİŞ değildir (durum aynı kalır) ama yine de DURUM denetimidir ve
matrisin yanında durur. İki yerde yazılsalardı `PATCH` bir gün `posted` fişi
kabul eder, `PUT lines` etmezdi ve hangisinin doğru olduğu kodun iki ayrı
köşesinden okunurdu.
"""

import enum

from app.core.errors import ConflictError
from app.modules.accounting import guards
from app.modules.accounting.models import JournalEntryStatus

__all__ = [
    "DELETABLE_STATUS",
    "EDITABLE_STATUS",
    "INITIAL_STATUS",
    "JOURNAL_TRANSITIONS",
    "LINES_EDITABLE_STATUS",
    "JournalAction",
    "assert_deletable",
    "assert_editable",
    "assert_lines_editable",
    "next_status",
]


class JournalAction(str, enum.Enum):
    """Durum işlemleri — değerler UÇ YOLLARIYLA birebir aynıdır
    (`…/post`, `…/reverse`), böylece router ile matris arasında ikinci bir
    eşleme sözlüğü gerekmez (`InvoiceAction` deseni)."""

    post = "post"
    reverse = "reverse"


#: §5 matrisi — 🔴 TEK KOPYA. Burada olmayan çift 409'dur.
JOURNAL_TRANSITIONS: dict[tuple[JournalEntryStatus, JournalAction], JournalEntryStatus] = {
    (JournalEntryStatus.draft, JournalAction.post): JournalEntryStatus.posted,
    (JournalEntryStatus.posted, JournalAction.reverse): JournalEntryStatus.reversed,
}

#: Oluşturmanın başlangıç durumu — 🔴 SUNUCUDA. Gövde `status` GÖNDEREMEZ
#: (şema `extra="forbid"` → 422); gönderebilseydi istemci taslak aşamasını
#: atlayıp dengesiz bir fişi doğrudan `posted` yazabilirdi.
INITIAL_STATUS: JournalEntryStatus = JournalEntryStatus.draft

#: BAŞLIK düzenlemeye açık durumlar. `posted`tan sonra fiş DONMUŞTUR.
EDITABLE_STATUS: frozenset[JournalEntryStatus] = frozenset({JournalEntryStatus.draft})

#: SATIR kümesi yalnız `draft`ta toptan yazılır. 🔴 R5: bu, "posted fişin satırı
#: değişmez" iddiasının TEK zorlayıcısıdır (DB'de trigger yoktur).
LINES_EDITABLE_STATUS: frozenset[JournalEntryStatus] = frozenset({JournalEntryStatus.draft})

#: Silinebilir tek durum. `posted` bir OLAYDIR; geri alınmaz, terslenir.
DELETABLE_STATUS: frozenset[JournalEntryStatus] = frozenset({JournalEntryStatus.draft})


def next_status(status: JournalEntryStatus, action: JournalAction) -> JournalEntryStatus:
    """Geçişin TEK kapısı: hedef durumu döndürür ya da **409** atar.

    404 (yok) denetimi BURADA DEĞİL çağıranda ve bu kontrolden ÖNCE koşar; ayrıca
    kilit ondan da öncedir (`state_service` modül docstring'i).
    """
    hedef = JOURNAL_TRANSITIONS.get((status, action))
    if hedef is None:
        raise ConflictError(guards.INVALID_TRANSITION)
    return hedef


def assert_editable(status: JournalEntryStatus) -> None:
    """Başlık düzenlemesinin TEK kapısı — uygun değilse **409**.

    404 (yok) ya da 403 (yetki) DEĞİL: kullanıcının yetkisi VARDIR, engelleyen
    şey kaydın DURUMUDUR.
    """
    if status not in EDITABLE_STATUS:
        raise ConflictError(guards.JOURNAL_ENTRY_NOT_EDITABLE)


def assert_lines_editable(status: JournalEntryStatus) -> None:
    """Satır kümesinin TEK kapısı — `draft` dışında **409**."""
    if status not in LINES_EDITABLE_STATUS:
        raise ConflictError(guards.JOURNAL_ENTRY_NOT_EDITABLE)


def assert_deletable(status: JournalEntryStatus) -> None:
    """Silmenin DURUM kapısı — `draft` dışında **409**.

    YETKİ kapısı (yalnız `admin`) burada DEĞİL router'dadır: biri kaydın
    durumuna, öteki aktörün seviyesine bakar.
    """
    if status not in DELETABLE_STATUS:
        raise ConflictError(guards.JOURNAL_ENTRY_NOT_DELETABLE)
