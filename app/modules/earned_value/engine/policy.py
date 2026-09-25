"""PLN-B0/B1 urun kararlari (PLANLAMA-SPEC §3.7, §3.8, §3.9) — TEK isimli nokta.

Her karar burada bir sabit ya da kucuk bir fonksiyondur; motorun geri kalani onu
buradan okur. Karar degisirse YALNIZ bu dosya degisir ve adli testi
(`test_S<n>_...`, `tests/modules/earned_value/test_engine_policy.py`) kirmizi olur.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

from .types import SUNDAY, ContractorMix, ContractorType, Distribution, Node, PfBands

# S1 — Own/Subcon planli %: disiplin egrisi o egrideki own/subcon BUTCE PAYIYLA bolunur.
#   planned_mhr_own(D, d) = planned_mhr(D, d) × budget_own(D) / budget(D)   (subcon ayni)
#   Overall–Own/Subcon = bu paylarin toplami; variance/status bunun ustunden.
#   Uygulama: `summary._curve_weights` bu bayrakla pay agirligini kullanir.
OWN_SUBCON_PLAN_BY_BUDGET_SHARE = True


# S2 — basliga yazilan saat (direct) ve prorata'da miktarsiz gun (unallocated): saatin
#   DUSTUGU dugumun kendi `is_direct` / `contractor_type` alanina gore kovaya girer.
#   `summary` her "nokta"yi (yaprak degeri ya da saat inisi) YALNIZ bu fonksiyonla siniflar;
#   baslik saati atalardan/yapraklardan alan MIRAS ALMAZ.
def point_class(node: Node) -> tuple[bool, ContractorType]:
    """Noktanin kovasi: (is_direct, contractor_type) — dustugu dugumun KENDI alanlari."""
    return node.is_direct, node.contractor_type


# S3 — is_direct=false: KPI satirlarina (Overall, Own/Subcon, disiplin) GIRMEZ, tek bir
#   "Dogrudan olmayan" satiri acilir. Agac dugumu metrikleri TUM alt agaci tasir.
KPI_ROWS_DIRECT_ONLY = True


# K26 (CEO 2026-09-25) — togo YAPRAK duzeyinde, spec §3.4 AYNEN: kalan miktar × YAPRAGIN
#   orani, KIRPMASIZ (asimda negatif katki; Σ yaprak = Σ butce − Σ earned = g − h). Baslik
#   togo'su = Σ yaprak (B0: baslik = Σ cocuk) — ortalama oran × toplam kalan (d × n) DEGIL:
#   bolum bazinda farkli yaprak oranlarinda (K3 ezmeleri) o yanlis bolume yanlis oran uygular.
#   Asimda 0'da kirpma KULLANICI KARARI bekliyor (KARARLAR-BEKLEYEN); onaylanirsa TEK yer burasi.
def leaf_togo(remaining_qty: Decimal, rate: Decimal) -> Decimal:
    return remaining_qty * rate


# S4 — karma birimli baslik: qty tabanli alanlar yaprak birimleri ayni degilse None;
#   ayniysa baslik planned_unit_mhr = budget / planned_qty. Adam-saat alanlari her zaman Σ.
HEADER_QTY_REQUIRES_UNIFORM_UOM = True


# K11 — prorata payi: M'nin yapraklari AYNI birimdeyse o gunku qty_day payi (spec aynen);
#   birimler KARISIKSA qty × unit_mhr (kazanilmis) payi — farkli birimler toplanamaz.
def prorata_by_earned(uniform_uom: str | None) -> bool:
    return uniform_uom is None


# S5 — tatil kurali: haftanin gunleri kumesi + elle liste; varsayilan Pazar.
#   "Her 2. haftanin X gunu" kurali ilk surumde YOK.
DEFAULT_WEEKLY_HOLIDAYS: frozenset[int] = frozenset({SUNDAY})

# S6 — PF bantlari. Gunluk: < 0,95 kirmizi · [0,95; 1,05] yesil · > 1,05 HIGH (supheli yuksek).
#   Kumulatif/haftalik (spec §3.6): < 0,95 kirmizi · [0,95; 1,00) amber · >= 1,00 yesil.
#   Sinirlar ayardir; bunlar ayar verilmediginde kullanilan varsayilanlardir.
DEFAULT_DAILY_PF_BANDS = PfBands(
    red_below=Decimal("0.95"), green_from=Decimal("0.95"), high_above=Decimal("1.05")
)
DEFAULT_CUMULATIVE_PF_BANDS = PfBands(red_below=Decimal("0.95"), green_from=Decimal("1.00"))


# K18 — PF bandi GOSTERILEN degere uygulanir: karsilastirma 2 ondaliga ROUND_HALF_UP ile
#   yuvarlanmis degerle (0,9499 → 0,95 → amber). PF'nin KENDISI ham kalir; yalniz bant
#   karari yuvarlanmis degere bakar (renk ile metin celismesin — Panel sorunu).
PF_BAND_QUANTUM = Decimal("0.01")
PF_BAND_ROUNDING = ROUND_HALF_UP


# K27 — status da GOSTERILEN degerle karar verir (K18 ile ayni sinif): variance PUANA
#   (× 100) cevrilir, 1 ondaliga ROUND_HALF_UP yuvarlanir, sonra |v| <= tolerans → Normal.
#   Tolerans PUAN birimindedir (ayar ekranindaki "± 2,0 puan"). Variance'in KENDISI ham kalir.
STATUS_POINTS_SCALE = Decimal(100)
STATUS_QUANTUM = Decimal("0.1")
STATUS_ROUNDING = ROUND_HALF_UP


# S7 — disiplin–own/subcon alt satiri YALNIZ karma disiplinde; tek tip disiplinde satir
#   yok, disiplin satiri `contractor_mix` rozetini tasir.
def discipline_has_split_rows(mix: ContractorMix | None) -> bool:
    return mix is ContractorMix.MIXED


def contractor_mix(types: set[ContractorType]) -> ContractorMix | None:
    """Disiplinin (direct) yapraklarindaki yuklenici tiplerinden rozet."""
    if not types:
        return None
    if types == {ContractorType.OWN}:
        return ContractorMix.OWN
    if types == {ContractorType.SUBCON}:
        return ContractorMix.SUBCON
    return ContractorMix.MIXED


# --- PLN-B1 -----------------------------------------------------------------------------

# B1-1 — yayma agirligi (mockup "Planlama - Adam-Saat Butcesi" `preview()` W tablosu AYNEN,
#   kullanici kabulu): u ∈ [0, 1] pencere icindeki konum.
#   dogrusal w = 1 · can w = 6u(1−u) + 0,05 · on w = 2(1−u) + 0,05 · arka w = 2u + 0,05.
#   +0,05 tabani: can/on/arka pencerenin UC gunlerini de sifirlamaz.
_W_FLOOR = Decimal("0.05")
_ONE, _TWO, _SIX = Decimal(1), Decimal(2), Decimal(6)
DISTRIBUTION_WEIGHTS: Mapping[Distribution, Callable[[Decimal], Decimal]] = {
    Distribution.LINEAR: lambda u: _ONE,
    Distribution.BELL: lambda u: _SIX * u * (_ONE - u) + _W_FLOOR,
    Distribution.FRONT: lambda u: _TWO * (_ONE - u) + _W_FLOOR,
    Distribution.BACK: lambda u: _TWO * u + _W_FLOOR,
}

# B1-1 — tatil / calisilmayan gun agirligi: 0 (o gune pay dusmez, sozluge girmez).
NON_WORKING_DAY_WEIGHT = Decimal(0)


def spread_position(t: date, start: date, end: date) -> Decimal:
    """B1-1: u = (t − s) / max(1, e − s) — TAKVIM gunu farki (tatiller de sayilir)."""
    return Decimal((t - start).days) / Decimal(max(1, (end - start).days))


# B1-1 — gun paylarinin yuvarlanmasi: EN BUYUK KALAN (Hamilton). Ham paylar (butce × w/Σw,
#   hepsi >= 0) kuantuma ASAGI iner; hedef = butcenin kuantuma asagi yuvarlanmisi; eksik
#   TAM kuantumlar kesirli kalani en buyuk gunlere birer birer verilir (esitlikte EN ERKEN);
#   kuantum-alti artik (butce 7–8 ondalik tasiyabilir) en buyuk payli gune (esitlikte en
#   erken) eklenir. Sonuc: her gun >= 0 ve Σ == butce TAM. ("Kalan son gune" yontemi kucuk
#   butcede son gunu EKSIYE dusuruyordu — olcum `test_engine_spread.py` docstring'inde.)
def largest_remainder(raw: list[Decimal], budget: Decimal, quantum: Decimal) -> list[Decimal]:
    """Sirali ham paylari (gun sirasi) kuantuma boler; Σ == budget, her pay >= 0."""
    floors = [r.quantize(quantum, rounding=ROUND_FLOOR) for r in raw]
    target = budget.quantize(quantum, rounding=ROUND_FLOOR)
    missing = int((target - sum(floors, Decimal(0))) / quantum)
    if not 0 <= missing <= len(raw):
        raise ArithmeticError(f"largest_remainder: eksik kuantum sayisi tutarsiz ({missing})")
    by_fraction = sorted(range(len(raw)), key=lambda i: (-(raw[i] - floors[i]), i))
    shares = list(floors)
    for i in by_fraction[:missing]:
        shares[i] += quantum
    residue = budget - target
    if residue and shares:
        top = min(range(len(shares)), key=lambda i: (-shares[i], i))
        shares[top] += residue
    return shares


# B1-2 — dagilim tipi disiplin × revizyon basina; ayar verilmediginde dogrusal.
DEFAULT_DISTRIBUTION = Distribution.LINEAR

# K10 — gereken kisi = planli a-s ÷ (is gunu × standart gunluk saat); standart gun 9 sa.
DEFAULT_STANDARD_DAILY_HOURS = Decimal(9)


def required_people(
    mhr: Decimal, working_days: int, standard_daily_hours: Decimal
) -> Decimal | None:
    """K10: haftanin gereken kisi sayisi; is gunu yoksa tanimsiz (None)."""
    if working_days == 0:
        return None
    return mhr / (Decimal(working_days) * standard_daily_hours)


# K10 (B1.1 uygulama karari, CEO onayina acik) — haftalik kova son haftada ARALIK SONUNA
#   kirpilir: aralik Sali biterse son hafta Pzt–Sal (2 is gunu). Ilk haftanin kisa olmasi
#   (hafta basi aralik basindan once olmaz, calendar.py) ile simetrik; kirpilmasaydi son
#   haftanin a-s'i 6 is gunune bolunur ve gereken kisi oldugundan dusuk gorunurdu.
WEEK_LOAD_CLIPPED_TO_RANGE_END = True

# K9 — girdide YAPRAK anahtarli planned_mhr varsa satirlarin planlisi yaprak egrilerinden
#   (satirin nokta kumesindeki yapraklarin egri toplami) kurulur; disiplin (curve) noktalari
#   YOK SAYILIR. Yaprak egrisi hic yoksa B0 davranisi (disiplin egrisi + S1) aynen.
LEAF_CURVES_OVERRIDE_DISCIPLINE_CURVES = True


def use_leaf_curves(has_leaf_points: bool, has_curve_points: bool) -> bool:
    """K9: bu rapor planliyi yaprak egrilerinden mi kurar?"""
    if has_leaf_points and has_curve_points:
        return LEAF_CURVES_OVERRIDE_DISCIPLINE_CURVES
    return has_leaf_points
