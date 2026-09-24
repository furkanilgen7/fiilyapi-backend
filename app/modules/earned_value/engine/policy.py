"""PLN-B0 sirasinda kapanan urun kararlari (PLANLAMA-SPEC §3.7) — TEK isimli nokta.

Her karar burada bir sabit ya da kucuk bir fonksiyondur; motorun geri kalani onu
buradan okur. Karar degisirse YALNIZ bu dosya degisir ve adli testi
(`test_S<n>_...`, `tests/modules/earned_value/test_engine_policy.py`) kirmizi olur.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from .types import SUNDAY, ContractorMix, ContractorType, Node, PfBands

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
