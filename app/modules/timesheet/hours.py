"""Adam-SAAT turevleri — normal / fazla mesai / adam-gun (PUAN-SAAT).

Mockup `Ekran 5 - Puantaj.dc.html` (`5f3a944`) basligi bu dosyanin sozlesmesidir:
*"Haftalik giris · saat bazli · Normal gun **9 saat** · Haftalik normal **45 saat**"*
(E5 71).

## 🔴 FM kurali — mockup'in dort satirindan OLCULDU

```
normal = min( Σ min(gun_saati, 9), 45 )
FM     = toplam_saat − normal
```

Ne saf gunluk ne saf haftalik bir kuraldir; **ikisinin bilesimidir**: gunluk 9'u
asan saat dogrudan FM'e gider, geriye kalan normal saatler de haftalik 45 tavanina
vurur ve asan kismi yine FM olur.

| Kisi (E5) | Saatler | Σ min(s,9) | Normal | FM | Toplam |
|---|---|---|---|---|---|
| Mehmet 236-245 | 9·11·9·9·9·6·— | 51 | 45 | 8 | 53 |
| Ali 258-267 | 9·İzin·İzin·9·12·9·— | 36 | 36 | 3 | 39 |
| Hasan 280-289 | 9·9·Görev·9·10·9·8 | 53 | 45 | 9 | 54 |
| Ayşe 302-311 | 9·9·9·4·9·7·(5) | 52 | 45 | 7 | 52 |

Ali'nin **39 saatlik** haftasinda FM'in **3** cikmasi saf haftalik kuralla
aciklanamaz (0 verirdi); Mehmet'in FM'inin **8** cikmasi saf gunluk kuralla
aciklanamaz (2 verirdi). Bilesik kural dort satirin dordunu de birebir uretir.

⚠️ **Hucre RENGI kurali TANIMLAMAZ.** `.hin-fm` (amber) mockup'ta Mehmet'in
tamamen FM olan 6 saatlik cumartesisine (E5 241) basilmamis, Hasan'in 8 saatlik
pazarina basilmistir. Renk bir IPUCUDUR; FM **hesaptan** turer, siniftan degil.

## Adam-gun artik TUREVDIR

`588 saat ÷ 9 = 65,3 adam/gun` (E5 349-350). Tam sayi DEGILDIR — bir ondalik
basamaga yuvarlanir (mockup "65,3").

🔴 **PUAN-SAAT-3 ILE BORDRO DA BURAYA BAGLANDI.** Once `payroll` "saati olan gun
SAYISINI" sayiyordu ve 4 saatlik gunu TAM GUN gosteriyordu (yevmiyelide fazla
odeme). Artik bordronun hem adam-gunu hem BRUTU bu dosyanin turevlerinden okunur
(`payroll/compute.compute_gross`, `payroll/service/compute_flow`): **iki yuzey
ayni hafta icin iki farkli sayi basamaz.**
"""

from collections.abc import Iterable
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import NamedTuple

#: E5 71 "Normal gün **9 saat**" — gunluk normal tavan.
NORMAL_DAY_HOURS = Decimal("9")

#: E5 71 "Haftalık normal **45 saat**" — haftalik normal tavan (E5 133 girisi de
#: bu degeri gosterir). Ayar YAPILMADI: mockup'taki kutu bir GORSEL vaattir,
#: sirket ayari olarak acmak bu dilimin kapsami disidir (rapor: KAPSAM DISI).
WEEKLY_NORMAL_HOURS = Decimal("45")

#: Saat kolonunun olcegi (`Numeric(4,1)`) — turevler de ayni olcekte yuvarlanir.
HOUR_QUANTUM = Decimal("0.1")

ZERO_HOURS = Decimal("0.0")


class WeekHours(NamedTuple):
    """Bir haftalik saat kumesinin turevleri. Uctan AYNEN yayinlanir."""

    normal_hours: Decimal
    overtime_hours: Decimal
    total_hours: Decimal


#: Hic saatli hucresi olmayan (ama puantaj KAYDI olan) bir kisinin turevi:
#: uc sifir. `None` DEGILDIR ve bu ayrim para sinifidir — kaydi olan ama tum
#: gunleri izin/tatil KODLU birinde saat 0 GERCEKTIR; kaydi hic olmayanda
#: BILINMEZ ve orada `None` gecer (`payroll.compute.compute_line`).
EMPTY_WEEK = WeekHours(
    normal_hours=ZERO_HOURS, overtime_hours=ZERO_HOURS, total_hours=ZERO_HOURS
)


def _q(value: Decimal) -> Decimal:
    return value.quantize(HOUR_QUANTUM, rounding=ROUND_HALF_UP)


def week_totals(daily_hours: Iterable[Decimal]) -> WeekHours:
    """Bir kisinin BIR haftasi — normal / FM / toplam.

    Girdi o haftada GIRILMIS gun saatleridir; kodlu (izin/tatil/gorev) ve hic
    girilmemis gunler listede YOKTUR — ikisi de saate 0 katar.
    """
    hours = [Decimal(value) for value in daily_hours]
    total = sum(hours, ZERO_HOURS)
    capped = sum((min(value, NORMAL_DAY_HOURS) for value in hours), ZERO_HOURS)
    normal = min(capped, WEEKLY_NORMAL_HOURS)
    return WeekHours(
        normal_hours=_q(normal),
        overtime_hours=_q(total - normal),
        total_hours=_q(total),
    )


def man_days(total_hours: Decimal) -> Decimal:
    """Adam-gun = saat ÷ 9 (E5 349-350: `588 ÷ 9 = 65,3`).

    Tam sayi DEGILDIR: yarim gunun temsil edilebildigi bir dunyada adam-gunu
    tam sayiya zorlamak, girilen saati sessizce yukari/asagi cekerdi.
    """
    return _q(Decimal(total_hours) / NORMAL_DAY_HOURS)


def period_totals(dated_hours: Iterable[tuple[date, Decimal]]) -> WeekHours:
    """Bir kisinin BIR DONEMINI (ay) haftalara bolup `week_totals`i her haftaya
    AYRI uygular ve turevleri toplar.

    🔴 **45 tavani KISI BASINA ve HAFTALIKTIR** (modul basligi). Ay toplamina tek
    seferde uygulansaydi 4 haftalik bir ay icin tavan 45 olur ve gercekte 180
    saat normal calisan biri 135 saat FM yapmis gibi gorunurdu — bordroda
    devasa bir fazla odeme. Bu yuzden gruplama ISO HAFTASINADIR
    (`date.isocalendar()`), ay icindeki gun sirasina degil.

    ## 🔴 Ay sinirinda BOLUNEN hafta: yalniz DONEMIN hucreleri sayilir

    Bir ISO haftasi iki aya yayilabilir. Komsu ayin hucreleri buraya
    KATILMAZ ve bu bilincli bir karardir:

    * bordro AYLIK kapanir ve donem bagimsiz ONAYLANIR; komsu ay cekilseydi
      **kapanmis bir donemin hucresi, acik donemin brutunu degistirirdi**;
    * ayni FM saati iki donemde birden odenebilirdi (haftanin her iki
      yarisi kendi ayinda tavani asarsa) — para sinifi cift odeme.

    Bedeli olculmustur ve KUCUKTUR: bolunen hafta iki parcaya ayrildigi icin
    45 tavanina daha gec vurur, yani FM'i **eksik** hesaplama yonundedir
    (fail-closed yon: fazla odeme uretmez).
    """
    haftalar: dict[tuple[int, int], list[Decimal]] = {}
    for work_date, value in dated_hours:
        yil, hafta, _ = work_date.isocalendar()
        haftalar.setdefault((yil, hafta), []).append(Decimal(value))

    normal = overtime = total = ZERO_HOURS
    for gun_saatleri in haftalar.values():
        hafta = week_totals(gun_saatleri)
        normal += hafta.normal_hours
        overtime += hafta.overtime_hours
        total += hafta.total_hours
    return WeekHours(normal_hours=_q(normal), overtime_hours=_q(overtime), total_hours=_q(total))
