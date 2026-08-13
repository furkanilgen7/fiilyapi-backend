"""Yakıt tüketimi ve kullanım oranının TEK KAYNAĞI — saf fonksiyonlar (MK-1 T2).

Spec: `docs/superpowers/specs/2026-08-13-mk1-makine-cekirdegi-design.md`
(K7 · K16 · K17 · K19). `cost.py` kardeşidir: DB'ye DOKUNMAZ, toplamları
KENDİSİ üretmez (onları T5 satırlardan toplar — K15), yalnız verilen
toplamlardan oranı ve rozeti türetir.

## Zincir

    litre + saat → FİİLİ tüketim → norm ile karşılaştırma → SAPMA → ROZET

🔴 **Her halka fail-closed'dur** (K16 · NULL-EŞİK kanonu, WORKFLOW §4):
hesaplanamayan bir değer `None` kalır, **UYDURMA 0 BASILMAZ** ve uydurma bir
"normal" rozeti damgalanmaz. Uydurma 0, "hiç yakmadı" derdi; uydurma "normal",
eksik veriyi "sorun yok" diye gösterirdi — ikisi de sessiz bir yalan.

## Dört fail-closed `None` yolu (K16) — hepsi MAKİNE-OKUNUR bir gerekçeyle

1. `norm_unit = lt_km` → **`no_distance_data`**: kilometre/odometre alanı
   HİÇBİR ekranda yoktur (M2 formunda da, M4 kaydında da). Saatten uydurma bir
   Lt/km üretmek yanlış bir "anormal tüketim" alarmı doğururdu.
2. `norm_consumption` yok → **`no_norm_consumption`**: karşılaştıracak bir
   ölçüt yoktur; sapmayı 0 saymak "normda" demek olurdu.
3. Çalışma saati 0 → **`no_work_hours`**: yakıt alınmış ama çalışma kaydı
   girilmemiştir; sıfıra bölmede 0 basmak "hiç yakmadı" derdi.
4. `monthly_capacity_hours` 0 → **`no_capacity_hours`**: kullanım yüzdesinin
   paydası yoktur.

Gerekçeler DÖRT AYRI dizgedir: tek bir "hesaplanamadı" dizgesi, hangi verinin
eksik olduğunu ekranda kaybederdi (frontend eksik alanı gösteremezdi).

## Bir ondalık

K19 gereği oranlar bir ondalıklıdır (M4 `4,5 Lt/saat` · M3 `%93`) ve **sapma
YUVARLANMIŞ fiili tüketimden türer**: ekranda görünen sayı 4,5'ken rozeti gizli
bir 4,516'dan üretmek, kullanıcının kendi ekranındaki aritmetiği yeniden
yapamaması demek olurdu (M4 hem 4,5 hem "%7 yüksek" basıyor — ikisi tutarlı).
"""

import enum
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from app.modules.equipment.models import EquipmentNormUnit

#: Oran adımı — K19: "Oranlar bir ondalık" (`4,5 Lt/saat`).
RATIO_QUANTUM = Decimal("0.1")

PERCENT_MULTIPLIER = Decimal("100")

#: 🔴 K17 eşikleri — TEK YERDE. `dev ≤ 0` normal · `0 < dev < 10` warning ·
#: `dev ≥ 10` critical. Mockup %7'yi sarı, %16'yı kırmızı basıyor (M4:52, M4:62);
#: aradaki eşik yönetim tarafından 10'a bağlandı. Rozet SUNUCUDAN gelir
#: (F-P10 "rozet sunucu damgasıdır" kanonu) — istemci eşiği yeniden yazmaz.
WARNING_THRESHOLD = Decimal("0")
CRITICAL_THRESHOLD = Decimal("10")

#: Dört fail-closed gerekçesi. `no_distance_data` spec'te AYNEN yazılıdır;
#: diğer üçü aynı üslupta (eksik olan VERİYİ adlandırır, "hata" demez).
REASON_NO_DISTANCE_DATA = "no_distance_data"
REASON_NO_NORM = "no_norm_consumption"
REASON_NO_WORK_HOURS = "no_work_hours"
REASON_NO_CAPACITY_HOURS = "no_capacity_hours"

DeviationReason = Literal["no_distance_data", "no_norm_consumption", "no_work_hours"]
UsageReason = Literal["no_capacity_hours"]


class ConsumptionStatus(str, enum.Enum):
    """Tüketim rozeti — M4'ün `✓ Normal` / `⚠ %7 yüksek` / kırmızı üçlüsü.

    DB'de kolon DEĞİLDİR: her okumada sapmadan türer. Saklansaydı norm
    güncellendiğinde geçmiş rozetler eski norma göre donup kalırdı.
    """

    normal = "normal"
    warning = "warning"
    critical = "critical"


@dataclass(frozen=True)
class ConsumptionResult:
    """Bir ekipmanın bir dönemlik tüketim değerlendirmesi — DONMUŞTUR.

    `actual` ve `deviation_pct` AYRI AYRI `None` olabilir: fiili tüketim
    biliniyorken sapma bilinmiyor olabilir (norm yok ya da `lt_km`). İkisi tek
    alana sıkıştırılsaydı bilinen bir olgu (4,5 Lt/saat) eksik bir ölçüt
    yüzünden kaybolurdu.
    """

    actual: Decimal | None
    deviation_pct: Decimal | None
    deviation_reason: DeviationReason | None
    status: ConsumptionStatus | None


@dataclass(frozen=True)
class UsageResult:
    """Kullanım yüzdesi (M3) — kendi gerekçesiyle."""

    usage_pct: Decimal | None
    usage_reason: UsageReason | None


def quantize_ratio(value: Decimal) -> Decimal:
    """Oran yuvarlamasının TEK tanımı: bir ondalık, `ROUND_HALF_UP` (K19).

    Para ile aynı yuvarlama YÖNÜ kullanılır (`cost.quantize_money`) ki iki
    yüzeyde iki farklı yarım-kural doğmasın; ADIM farklıdır çünkü oran bir
    ondalıklıdır, para tam sayıdır.
    """
    return value.quantize(RATIO_QUANTUM, rounding=ROUND_HALF_UP)


def actual_consumption(*, total_liters: Decimal, total_hours: Decimal) -> Decimal | None:
    """Fiili tüketim = `toplam_litre / toplam_çalışma_saati` (K17).

    Çalışma saati 0 ise **`None`** (K16 · yol 3). Filo düzeyinde de aynı
    formüldür (M4:39 `2.840 / 428 = 6,6`) — ikinci bir ortalama tanımı
    yazılsaydı KPI ile satırlar birbirini tutmazdı.
    """
    if not total_hours:
        return None
    return quantize_ratio(total_liters / total_hours)


def deviation_pct(*, actual: Decimal | None, norm: Decimal | None) -> Decimal | None:
    """Norma göre YÜZDE sapma: `(fiili − norm) / norm × 100`.

    Negatif değer normun ALTINDA kalmaktır (iyi). Girdilerden biri yoksa ya da
    norm 0 ise `None` (K16) — 0 sapma "tam normda" demek olurdu.
    """
    if actual is None or not norm:
        return None
    return quantize_ratio((actual - norm) / norm * PERCENT_MULTIPLIER)


def consumption_status(deviation: Decimal | None) -> ConsumptionStatus | None:
    """🔴 K17 rozeti — eşiklerin OKUNDUĞU tek yer.

    Sapma `None` ise rozet de **`None`**tur. Spec bu durumu yazmıyor; "normal"
    basmak hesaplanamayan bir tüketimi "sorun yok" diye damgalamak olurdu
    (fail-closed ruhu). Gerekçe `ConsumptionResult.deviation_reason`dadır.
    """
    if deviation is None:
        return None
    if deviation <= WARNING_THRESHOLD:
        return ConsumptionStatus.normal
    if deviation < CRITICAL_THRESHOLD:
        return ConsumptionStatus.warning
    return ConsumptionStatus.critical


def compute_usage(*, hours: Decimal, monthly_capacity_hours: int | None) -> UsageResult:
    """Kullanım yüzdesi = `hours / monthly_capacity_hours × 100` (K7).

    Payda VERİDİR, koda gömülü değil: mockup'ın beş rozeti de 200 paydasıyla
    birebir tutar (186→%93 · 152→%76 · 42→%21 · 168→%84 · 144→%72) ama vinç ile
    el aleti aynı kapasitede değildir.

    Kapasite yok/0 ise `None` + `no_capacity_hours` (K16 · yol 4).
    """
    if not monthly_capacity_hours:
        return UsageResult(usage_pct=None, usage_reason=REASON_NO_CAPACITY_HOURS)
    return UsageResult(
        usage_pct=quantize_ratio(hours / Decimal(monthly_capacity_hours) * PERCENT_MULTIPLIER),
        usage_reason=None,
    )


def evaluate_consumption(
    *,
    total_liters: Decimal,
    total_hours: Decimal,
    norm_consumption: Decimal | None,
    norm_unit: EquipmentNormUnit | None,
) -> ConsumptionResult:
    """Tüketim zincirinin TAMAMI — saf: aynı girdiye her zaman aynı çıktı.

    Gerekçe SIRASI anlamlıdır ve en YAPISAL engelden başlar:

    1. `lt_km` → veri modelinde mesafe YOKTUR; norm girilmiş olsa bile sapma
       hesaplanamaz. (Bu yüzden norm denetiminden ÖNCEDİR: kullanıcıya "norm
       gir" demek yanıltıcı olurdu, norm zaten var.)
    2. Fiili tüketim yok (saat 0) → karşılaştıracak SOL taraf yok.
    3. Norm yok → karşılaştıracak SAĞ taraf yok.

    `actual` `lt_km` ekipmanda da DOLDURULUR: litre/saat gerçek bir olgudur ve
    yalnız normla KIYASLANAMAZ; gizlemek, girilmiş yakıtı ekrandan silerdi.
    """
    actual = actual_consumption(total_liters=total_liters, total_hours=total_hours)

    reason: DeviationReason | None = None
    if norm_unit is EquipmentNormUnit.lt_km:
        reason = REASON_NO_DISTANCE_DATA
    elif actual is None:
        reason = REASON_NO_WORK_HOURS
    elif norm_consumption is None or norm_consumption <= 0:
        # 0/negatif norm da "ölçüt YOK"tur (DB CHECK'i zaten `> 0` ister ama
        # kural burada da durur): sıfır normda sapma sonsuza giderdi.
        reason = REASON_NO_NORM

    # 🔴 Gerekçe ile `None` sapma TEK bir noktada bağlanır: sapmanın ayrıca
    # `None` dönebildiği bir yol kalsaydı gerekçesiz bir `None` üretilebilir,
    # ekran "hesaplanamadı" derken NİÇİN'ini söyleyemezdi.
    deviation = None if reason is not None else deviation_pct(actual=actual, norm=norm_consumption)

    return ConsumptionResult(
        actual=actual,
        deviation_pct=deviation,
        deviation_reason=reason,
        status=consumption_status(deviation),
    )
