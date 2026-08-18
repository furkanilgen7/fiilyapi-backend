"""FIN-1 T3 — 🔴 K2/K8'in TUREV katmani: `is_due` ve AY PENCERESI.

## Bu dosyanin varlik sebebi

Emrin K2 karari: *"mockup'in 'Vadede' rozeti bir enum uyesi DEGIL, TUREVDIR"*.
Turev bir kez yaziliyorsa bekcisi de bir kez yazilir — ve **sinir gununde**.

🔴 **MU-2 DERSI (WORKFLOW §4 Ortak):** mizanin acilis penceresi `<` → `<=`
yapildiginda 31 testin HICBIRI kirmizi olmadi, cunku hicbiri **sinir gununu**
kullanmiyordu. Bu dosyadaki her pencere iddiasi bu yuzden ayin **ILK** ve **SON**
gunuyle, ve bir sonraki ayin ilk gunuyle AYRI AYRI yazilir.

## Iki pencere AYNI SEY DEGILDIR ve bu bilinclidir

* **`is_due`** (E10:121,148 turuncu rozet) = `portfolio` **ve**
  `due_date <= ay sonu`. Alt sinir YOKTUR: vadesi GECMIS bir cek de kesinlikle
  "vadede"dir.
* **`due_this_month`** (E10:81 karti) = `portfolio` **ve** ayin ILK gunu <=
  `due_date` <= ayin SON gunu. K8: "Bu ay" = TAKVIM AYI, "bugunden 30 gun" DEGIL.

Ikisi de AYNI `month_bounds` yardimcisindan gecer: iki ayri yerde hesaplansaydi
biri ayin son gununu disarida birakir ve rozet ile kart AYRISIRDI.

Pencere ust siniri neden mockup'tan okunur: E10'un "Vadede" basan iki satiri
(25.07.2026 ve 20.07.2026) ile "Portfoyde" basan iki satiri (15.08.2026,
30.09.2026) arasindaki AYRIM tam olarak AY sinirindadir. Gun sayisi (`+30`)
secilseydi 15.08 de "Vadede" olurdu — mockup onu YESIL basiyor.
"""

from datetime import date

import pytest

from app.modules.treasury.instruments import derive
from app.modules.treasury.models import FinancialInstrumentStatus as Durum

_PORTFOY = Durum.portfolio


# --------------------------------------------------------------------------- #
# `month_bounds` — TEK kaynak
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("gun", "beklenen"),
    [
        # Ayin ORTASI.
        (date(2026, 7, 15), (date(2026, 7, 1), date(2026, 7, 31))),
        # 🔴 Ayin ILK gunu — kendi ayinin penceresine DAHIL olmali.
        (date(2026, 7, 1), (date(2026, 7, 1), date(2026, 7, 31))),
        # 🔴 Ayin SON gunu — bir sonraki aya KAYMAMALI.
        (date(2026, 7, 31), (date(2026, 7, 1), date(2026, 7, 31))),
        # 30 gunluk ay.
        (date(2026, 9, 10), (date(2026, 9, 1), date(2026, 9, 30))),
        # Subat (artik OLMAYAN yil).
        (date(2026, 2, 5), (date(2026, 2, 1), date(2026, 2, 28))),
        # 🔴 ARTIK YIL — 29 Subat. `28` sabiti gomulseydi bu satir kirmizi olurdu.
        (date(2028, 2, 5), (date(2028, 2, 1), date(2028, 2, 29))),
        # 🔴 YIL SINIRI — Aralik'in sonu bir sonraki yilin Ocak'ina TASMAZ.
        (date(2026, 12, 20), (date(2026, 12, 1), date(2026, 12, 31))),
        (date(2026, 1, 1), (date(2026, 1, 1), date(2026, 1, 31))),
    ],
)
def test_month_bounds_sinirlari(gun: date, beklenen: tuple[date, date]) -> None:
    assert derive.month_bounds(gun) == beklenen


# --------------------------------------------------------------------------- #
# `is_due` — E10:121,148 turuncu rozetin TEK kaynagi
# --------------------------------------------------------------------------- #


def test_is_due_ayin_SON_gunu_DAHILDIR() -> None:
    """🔴 SINIR GUNU (MU-2 dersi). `<=` yerine `<` yazilirsa BU test kirmizi olur;
    baska hicbir test gormezdi."""
    assert derive.is_due(_PORTFOY, date(2026, 7, 31), as_of=date(2026, 7, 15)) is True


def test_is_due_bir_sonraki_ayin_ILK_gunu_DISARIDADIR() -> None:
    """🔴 SINIRIN OBUR YANI. `<=` yerine `<` mutasyonunu yukaridaki test, `<`
    yerine `<=`(bir gun kaydirma) mutasyonunu BU test yakalar — pencere iki
    yonden de kilitli."""
    assert derive.is_due(_PORTFOY, date(2026, 8, 1), as_of=date(2026, 7, 15)) is False


def test_is_due_VADESI_GECMIS_cek_de_vadededir() -> None:
    """Ust sinir yeterlidir, ALT sinir YOKTUR ve bu bilinclidir: vadesi gecmis
    ama hala portfoyde duran bir cek "Vadede" degil de ne olurdu? Alt sinir
    konsaydi gecikmis cekler sessizce YESIL rozet alirdi."""
    assert derive.is_due(_PORTFOY, date(2026, 5, 1), as_of=date(2026, 7, 15)) is True


def test_is_due_gelecek_ay_vadeli_cek_PORTFOYDEDIR() -> None:
    """E10:128 `15.08.2026` YESIL basar — bugun Temmuz'ken Agustos vadeli cek
    "Vadede" DEGILDIR."""
    assert derive.is_due(_PORTFOY, date(2026, 8, 15), as_of=date(2026, 7, 15)) is False


@pytest.mark.parametrize(
    "durum",
    [Durum.collected, Durum.paid, Durum.returned, Durum.cancelled],
)
def test_is_due_TERMINAL_durumda_HER_ZAMAN_False(durum: Durum) -> None:
    """🔴 K2: rozet IKI kosuldan olusur. `status` kosulu dusurulurse tahsil
    edilmis bir cek vadesi gectigi icin turuncu "Vadede" basardi — E10:155'in
    satiri `Tahsil Edildi` mavisini tasir ve vade tarihi GRIDIR.

    Dort terminal durumun DORDU DE ayri ayri sinanir: tek durumla yazilsaydi
    kosul `status != collected`e daraltilabilir ve iptal edilmis bir cek yine
    vadede gorunurdu.
    """
    assert derive.is_due(durum, date(2026, 5, 1), as_of=date(2026, 7, 15)) is False


# --------------------------------------------------------------------------- #
# Iki pencere ARASINDAKI fark — kasitli
# --------------------------------------------------------------------------- #


def test_gecmis_vade_is_due_EVET_ama_bu_ay_vadeli_HAYIR() -> None:
    """🔴 AYRISMA NOKTASI: iki turev ayni sayiya indirgenirse bu test kirmizi olur.

    Gecen ay vadesi gelmis, hala portfoyde duran bir cek:
      * rozet: "Vadede" (kullanici bunu gormeli — para gecikmis)
      * kart : "Bu Ay Vadeli" DEGIL (K8: takvim ayi)
    Iki turev tek fonksiyona baglansaydi ya kart gecmisi yutar ya rozet susardi.
    """
    gecmis = date(2026, 6, 20)
    bugun = date(2026, 7, 15)
    assert derive.is_due(_PORTFOY, gecmis, as_of=bugun) is True
    ilk, son = derive.month_bounds(bugun)
    assert not (ilk <= gecmis <= son)
