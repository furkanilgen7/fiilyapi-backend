"""FIN-1 K2 — durum makinesi. TEK TABLO, tek kapi.

## Tablo neyi soyler, neyi SOYLEMEZ

Gecerli ciftler asagidaki `TRANSITIONS` sozlugundedir; servis ve uclar kendi
`if status == ...` kontrollerini YAZMAZ. Tabloda olmayan her cift **409**dur —
"tanimli olani say, gerisini reddet" yaklasimiyla yeni bir durum eklendiginde
varsayilan davranis REDDETMEKTIR. Desen `procurement/transitions.py`ten alindi.

## Neyin tabloda OLMADIGI da bir karardir

* 🔴 **TERMINAL DURUMDAN CIKIS YOK.** `collected`/`paid`/`returned`/`cancelled`
  hicbir ciftte KAYNAK degildir. Tahsil edilmis bir cek "geri portfoye" alinmaz;
  islem yanlissa DUZELTME bir denetim olayidir, durum makinesinin isi degil.
* 🔴 **`portfolio → portfolio` YOKTUR.** "Degismedi" sessizce basari sayilsaydi
  ekran, gecersiz bir dugmeyi calisiyor sanirdi (`assert_order_transition`
  kanonu).
* 🔴 **YON KENDI HEDEFINI TASIR.** Alinan cek `paid` OLAMAZ (parayi biz
  odemedik), verilen cek `collected` OLAMAZ. Iki yon TEK bir kumede
  birlestirilseydi bu iki cift sessizce mesrulasirdi.

`returned` ve `cancelled` IKI yonde de vardir: karsiliksiz cikma ve iptal
evrakin yonunden bagimsiz olgulardir.

## Neden UC AYRI hata metni

Tek "gecersiz gecis" mesaji, kullanicinin YAPABILECEGI seyi gizlerdi:

| tani | metin | kullaniciya anlami |
|---|---|---|
| kaynak terminal | `TERMINAL_STATUS` | bu kayit kapandi, yeni kayit ac |
| hedef obur yonun | `DIRECTION_MISMATCH` | yonu yanlis okudun |
| ne biri ne oteki | `INVALID_TRANSITION` | baska bir hedef sec |

Sira ONEMLIDIR ve T4'te bir kez YANLIS yazilip test tarafindan yakalandi:

1. **once KABUL** — `(portfolio, returned)` ve `(portfolio, cancelled)` IKI
   yonde de gecerlidir; "obur yonun tablosunda mi" sorusu once sorulsaydi bu
   dort mesru gecis "yon hatasi" diye REDDEDILIRDI (T4 kirmizisi tam olarak
   buydu);
2. sonra **terminal** (asil engel odur);
3. sonra **yon** (obur yonun tablosundaysa tani odur);
4. en sonda **genel**.

2 ile 3 yer degistirseydi terminal bir `received` kaydinda `paid` denemesi
"yon hatasi" diye bildirilir ve asil engel (kayit kapali) gizlenirdi —
`test_TERMINAL_tanisi_YON_tanisindan_ONCE_gelir` bunu ayrica kilitler.
"""

from app.core.errors import ConflictError
from app.modules.treasury.instruments import guards
from app.modules.treasury.models import (
    FinancialInstrumentDirection as Direction,
)
from app.modules.treasury.models import (
    FinancialInstrumentStatus as Status,
)

__all__ = ["TERMINAL_STATUSES", "TRANSITIONS", "assert_transition"]

#: 🔴 K2 tablosu — TEK KOPYA. Burada olmayan her cift 409'dur.
TRANSITIONS: dict[Direction, frozenset[tuple[Status, Status]]] = {
    Direction.received: frozenset(
        {
            (Status.portfolio, Status.collected),
            (Status.portfolio, Status.returned),
            (Status.portfolio, Status.cancelled),
        }
    ),
    Direction.issued: frozenset(
        {
            (Status.portfolio, Status.paid),
            (Status.portfolio, Status.returned),
            (Status.portfolio, Status.cancelled),
        }
    ),
}

#: Hicbir ciftte KAYNAK olmayan durumlar. Elle yazilmis bir liste tablodan
#: sapabilirdi; bu yuzden TABLODAN TURETILIR — yeni bir cift eklendiginde
#: terminal kumesi kendiliginden kuculur.
TERMINAL_STATUSES: frozenset[Status] = frozenset(Status) - {
    kaynak for cift_kumesi in TRANSITIONS.values() for kaynak, _ in cift_kumesi
}


def _obur_yon(direction: Direction) -> Direction:
    return Direction.issued if direction is Direction.received else Direction.received


def assert_transition(direction: Direction, current: Status, target: Status) -> None:
    """Gecisin TEK kapisi. Tabloda olmayan her cift 409, uc ayri tani ile.

    🔴 **Bu fonksiyon KILIT ALMAZ ve almamalidir.** Kilit CAGIRANDADIR
    (`service.change_status`, `with_for_update`) ve DENETIMLERDEN ONCE alinir:
    kilit burada alinsaydi cagiran onu almadan da bu tabloyu okuyabilir ve
    EŞİK=KİLİT kanonunun tam olarak yasakladigi TOCTOU penceresi acik kalirdi.
    """
    if (current, target) in TRANSITIONS[direction]:
        return
    if current in TERMINAL_STATUSES:
        raise ConflictError(guards.TERMINAL_STATUS)
    if (current, target) in TRANSITIONS[_obur_yon(direction)]:
        raise ConflictError(guards.DIRECTION_MISMATCH)
    raise ConflictError(guards.INVALID_TRANSITION)
