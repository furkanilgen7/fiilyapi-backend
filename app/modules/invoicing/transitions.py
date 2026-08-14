"""Faturanın İKİ durum makinesi — TEK kaynak (FAT-1 spec §3, K1/K2).

Geçerli geçişlerin tamamı aşağıdaki iki tablodadır (`OUTGOING_TRANSITIONS` ·
`INCOMING_TRANSITIONS`); uçlar ve servis kendi `if status == …` denetimini
YAZMAZ. Tabloda olmayan her çift 409'dur — "tanımlı olanı say, gerisini
reddet" yaklaşımıyla ileride yeni bir durum eklenirse varsayılan davranış
REDDETMEKTİR.

    Giden:  draft ──send──▶ sent ──mark-collected──▶ collected
    Gelen:  pending ──approve──▶ approved
               └────dispute────▶ disputed

## İki tablo neden BİRLEŞTİRİLMEDİ

`status` tek bir enum tipidir (tek kolon), ama makineler ayrıdır. Tek tabloda
birleştirilseydi "giden faturaya `approve`" ile "taslak faturaya
`mark-collected`" AYNI kayıp aramaya düşerdi ve ikisi ayırt edilemezdi. Ayrım
davranışsaldır:

* **YÖN DIŞI** (`wrong_direction`): işlem bu yöne AİT DEĞİL — istemci yanlış
  ucu çağırdı; hiçbir durumda düzelmez, ekran kusurudur.
* **MATRİS DIŞI** (`invalid_transition`): işlem doğru yöne ait ama kayıt o
  aşamada değil — eş zamanlı ikinci istek ya da bayat ekran; kaydın durumu
  değişince aynı çağrı geçerli olabilir.

İkisi de HTTP'de 409'a çıkar (§3) ama çağıran (T4) ayrımı yapabilmelidir;
tek sınıfa indirgenseydi FGE'deki bir düğme kusuru ile normal bir yarış
çekişmesi günlükte birbirinden ayrılamazdı.

## Neyin tabloda OLMADIĞI da bir karardır

* **İptal / iade geçişi YOKTUR** — FGI'de iptal aksiyonu çizilmemiştir. `draft`
  fatura SİLİNİR (uç 6, yalnız `admin`), durumu geri alınmaz.
* **`approved` sonrası ÖDEME durumu YOKTUR** — Hazine diliminindir. Bu dilimde
  yalnız `collected` DAMGASI vardır (`progress_payments.mark-paid` emsali).
* **`Kısmi Onayla` (FGE:140) AÇILMADI** — etkisi hiçbir mockup'ta çizilmemiş
  (envanter md.8), FAT-2'nin işidir.
* `collected` / `approved` / `disputed` TERMİNALDİR: hiçbir çiftte KAYNAK
  değillerdir.

## K1 — "Vadeli" AYRI BİR DURUM DEĞİLDİR (onaylı sapma)

FY:91 süzgeci `Gönderildi` ve `Vadeli`yi yan yana sunar ama FY'de `Gönderildi`
rozetli tek satır yoktur. Karar: `sent` TEK durumdur; ekran etiketi `due_date`
doluysa "Vadeli", boşsa "Gönderildi"dir. Türetilebilen SAKLANMAZ — bu yüzden
matriste `overdue`/`due` diye bir düğüm aramayın.

## K2 — `draft` yalnız GİDEN tarafta vardır

Gelen fatura sisteme zaten kesilmiş olarak girer (FGE:69 `GİB'den Geldi ✓`);
taslak gelen fatura hiçbir mockup'ta yoktur. Başlangıç durumu bu yüzden yöne
göre ayrışır ve `INITIAL_STATUS`ta TEK yerde durur (T3 kendi eşlemesini
yazmaz).
"""

import enum

from app.core.errors import ConflictError
from app.modules.invoicing.models import InvoiceDirection, InvoiceStatus

__all__ = [
    "DELETABLE_STATUS",
    "EDITABLE_STATUS",
    "INCOMING_TRANSITIONS",
    "INITIAL_STATUS",
    "INVALID_TRANSITION_MESSAGE",
    "LINES_EDITABLE_STATUS",
    "NOT_DELETABLE_MESSAGE",
    "NOT_EDITABLE_MESSAGE",
    "OUTGOING_TRANSITIONS",
    "WRONG_DIRECTION_MESSAGE",
    "InvoiceAction",
    "TransitionRejection",
    "assert_deletable",
    "assert_editable",
    "assert_lines_editable",
    "classify_transition",
    "next_status",
]


class InvoiceAction(str, enum.Enum):
    """Durum işlemleri — değerler UÇ YOLLARIYLA birebir aynıdır
    (`…/mark-collected`), böylece router ile matris arasında ikinci bir eşleme
    sözlüğü gerekmez (`RequestAction` deseni)."""

    send = "send"
    mark_collected = "mark-collected"
    approve = "approve"
    dispute = "dispute"


class TransitionRejection(str, enum.Enum):
    """Ret SEBEBİ — ikisi de 409'dur, ama aynı hata değildir (modül
    docstring'i)."""

    wrong_direction = "wrong_direction"
    invalid_transition = "invalid_transition"


#: §3 GİDEN tablosu — TEK KOPYA. Burada olmayan çift 409'dur.
OUTGOING_TRANSITIONS: dict[tuple[InvoiceStatus, InvoiceAction], InvoiceStatus] = {
    (InvoiceStatus.draft, InvoiceAction.send): InvoiceStatus.sent,
    (InvoiceStatus.sent, InvoiceAction.mark_collected): InvoiceStatus.collected,
}

#: §3 GELEN tablosu. `pending` İKİ yola ayrılır ve ikisi de terminaldir.
INCOMING_TRANSITIONS: dict[tuple[InvoiceStatus, InvoiceAction], InvoiceStatus] = {
    (InvoiceStatus.pending, InvoiceAction.approve): InvoiceStatus.approved,
    (InvoiceStatus.pending, InvoiceAction.dispute): InvoiceStatus.disputed,
}

#: K2 — oluşturmanın başlangıç durumu YÖNE göre ayrışır (T3 uç 3).
INITIAL_STATUS: dict[InvoiceDirection, InvoiceStatus] = {
    InvoiceDirection.outgoing: InvoiceStatus.draft,
    InvoiceDirection.incoming: InvoiceStatus.pending,
}

#: Her işlemin sahibi yön — tablolardan TÜRETİLİR ki üçüncü bir kopya olmasın.
_ACTION_DIRECTION: dict[InvoiceAction, InvoiceDirection] = {
    **{islem: InvoiceDirection.outgoing for _, islem in OUTGOING_TRANSITIONS},
    **{islem: InvoiceDirection.incoming for _, islem in INCOMING_TRANSITIONS},
}

_TRANSITIONS: dict[InvoiceDirection, dict[tuple[InvoiceStatus, InvoiceAction], InvoiceStatus]] = {
    InvoiceDirection.outgoing: OUTGOING_TRANSITIONS,
    InvoiceDirection.incoming: INCOMING_TRANSITIONS,
}

WRONG_DIRECTION_MESSAGE = "Bu işlem faturanın yönüne uygulanamaz"
INVALID_TRANSITION_MESSAGE = "Fatura bu işlem için uygun durumda değil"

_MESSAGES: dict[TransitionRejection, str] = {
    TransitionRejection.wrong_direction: WRONG_DIRECTION_MESSAGE,
    TransitionRejection.invalid_transition: INVALID_TRANSITION_MESSAGE,
}


def classify_transition(
    direction: InvoiceDirection, status: InvoiceStatus, action: InvoiceAction
) -> TransitionRejection | None:
    """Geçiş neden reddedilir — `None` "geçerli" demektir.

    YÖN denetimi durum denetiminden ÖNCE koşar: gelen bir faturaya `send`
    atıldığında sebep yöndür, "kayıt bu aşamada değil" değil. Sıra ters olsaydı
    istemci yanlış ucu çağırdığını hiç öğrenemez, kaydın durumunu düzeltmeye
    çalışırdı.
    """
    if _ACTION_DIRECTION[action] is not direction:
        return TransitionRejection.wrong_direction
    if (status, action) not in _TRANSITIONS[direction]:
        return TransitionRejection.invalid_transition
    return None


def next_status(
    direction: InvoiceDirection, status: InvoiceStatus, action: InvoiceAction
) -> InvoiceStatus:
    """Geçişin TEK kapısı: hedef durumu döndürür ya da 409 atar.

    Kapsam süzgeci (404) BURADA DEĞİL çağıranda koşar ve bu kontrolden
    ÖNCEDİR: görünmeyen bir faturanın durumu hakkında 409 ile bilgi sızdırılmaz
    (SA emsali).
    """
    rejection = classify_transition(direction, status, action)
    if rejection is not None:
        raise ConflictError(_MESSAGES[rejection])
    return _TRANSITIONS[direction][(status, action)]


# --------------------------------------------------------------------------- #
# DÜZENLEME/SİLME KAPILARI (T3 uçları 5, 6, 7)
#
# Bunlar bir GEÇİŞ değildir (durum aynı kalır) ama yine de DURUM denetimidir ve
# bu yüzden burada, matrisin yanında durur: uçlar ve servis kendi `if status ==
# …` denetimini YAZMAZ (spec §3). İki yerde yazılsalardı `PATCH` bir gün
# `sent` faturayı kabul eder, `PUT lines` etmezdi ve hangisinin doğru olduğu
# kodun iki ayrı köşesinden okunurdu.
# --------------------------------------------------------------------------- #

#: BAŞLIK düzenlemeye açık durumlar — YÖNE göre (spec §7 md.5).
#: Gelen faturada `pending` düzenlenebilir ama yalnız ÜÇ ALAN (`guards.
#: INCOMING_PATCHABLE_FIELDS`): hangi ALANLAR sorusu bir DURUM sorusu değildir,
#: o yüzden burada değil `guards`tadır.
EDITABLE_STATUS: dict[InvoiceDirection, frozenset[InvoiceStatus]] = {
    InvoiceDirection.outgoing: frozenset({InvoiceStatus.draft}),
    InvoiceDirection.incoming: frozenset({InvoiceStatus.pending}),
}

#: KALEM kümesi yalnız `draft`ta yazılır (spec §7 md.7) ve `draft` yalnız GİDEN
#: taraftadır (K2) — yani gelen faturanın kalemleri hiçbir durumda toptan
#: değiştirilmez. Bu, `EDITABLE_STATUS`tan DAHA DARDIR ve bilinçlidir: gelen
#: faturanın kalemi satıcının belgesindendir, düzeltmesi bizde değildir.
LINES_EDITABLE_STATUS: frozenset[InvoiceStatus] = frozenset({InvoiceStatus.draft})

#: Silinebilir tek durum `draft`tır (spec §7 md.6). `sent` bir OLAYDIR; iptal
#: geçişi hiçbir mockup'ta çizilmemiştir (modül docstring'i) ve silme onun
#: yerine geçirilmez.
DELETABLE_STATUS: frozenset[InvoiceStatus] = frozenset({InvoiceStatus.draft})

NOT_EDITABLE_MESSAGE = "Fatura bu durumda düzenlenemez"
NOT_DELETABLE_MESSAGE = "Yalnızca taslak fatura silinebilir"


def assert_editable(direction: InvoiceDirection, status: InvoiceStatus) -> None:
    """Başlık düzenlemesinin TEK kapısı — uygun değilse **409**.

    404 (yok) ya da 403 (yetki) DEĞİL: kullanıcının yetkisi VARDIR, engelleyen
    şey kaydın DURUMUDUR. Kural aynı zamanda K7'nin bekçisidir: gönderilmiş bir
    faturanın oranı düzeltilebilseydi donmuş çarpanlar canlıya dönerdi.
    """
    if status not in EDITABLE_STATUS[direction]:
        raise ConflictError(NOT_EDITABLE_MESSAGE)


def assert_lines_editable(status: InvoiceStatus) -> None:
    """Kalem kümesinin TEK kapısı — `draft` dışında **409**."""
    if status not in LINES_EDITABLE_STATUS:
        raise ConflictError(NOT_EDITABLE_MESSAGE)


def assert_deletable(status: InvoiceStatus) -> None:
    """Silmenin DURUM kapısı — `draft` dışında **409**.

    YETKİ kapısı (yalnız `admin`) burada DEĞİL router'dadır: biri kaydın
    durumuna, öteki aktörün seviyesine bakar ve tek yerde toplanırlarsa
    "yetkiniz yok" cümlesi bir durum engelinden dönerdi.
    """
    if status not in DELETABLE_STATUS:
        raise ConflictError(NOT_DELETABLE_MESSAGE)
