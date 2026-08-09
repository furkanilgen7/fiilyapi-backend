"""Maliyet/kâr türev çekirdeği (P10 T1, spec §2) — yeni tablo/kolon YOK.

P10 bir **TÜREV OKUMA** dilimidir: burada hiçbir maliyet SAKLANMAZ, mevcut
verinin (bütçe kalemleri · `project_investment.land_cost` · taşeron hakedişleri ·
ünite alan/fiyat kolonları) karşısına gerçekleşeni ve kâr türevlerini koyar.
Elle maliyet girişi yüzeyi AÇILMAZ — hiçbir mockup'ta yoktur (spec §1, §5).

## Neden ayrı dosya

`service.py` oturum/yetki/yazma taşır; "29,8M bütçe maliyeti nasıl çıkar",
"%38,2 marj nereden gelir" soruları veritabanına ve yetkiye DOKUNMADAN test
edilebilmelidir (`units/summary.py` ve `progress_payments/calculations.py` ile
aynı gerekçe). Bu dosyadaki tek DB'ye dokunan fonksiyon
`subcontractor_totals_by_projects`tır ve o da yalnız TOPLU okuma yapar.

## Para matematiği TEK kopyadır

Kuruş yuvarlaması `progress_payments.calculations.quantize2`, hakediş brütü
`calculations.gross_total`tır — bu modül ikinci bir para/brüt tanımı YAZMAZ
(TH T3 "paylaş, kopyalama" kuralı). Aynı nedenle ünite değer sütunu seçimi
`units.summary.VALUE_BASIS_BY_TYPE` + `_basis_value`ten okunur.

## Onaylı kararlar (spec §7, kullanıcı onaylı)

* **S1** harcanan = `approved`+`paid` · ödenen = `paid` · bekleyen = `approved`.
* **S2** BRÜT (`gross_total`) — teminat/avans kesintileri ödeme zamanlamasıdır,
  işin maliyetini değiştirmez.
* **S3** ünite maliyeti = toplam bütçe maliyeti × ünite brüt m² / proje brüt m².
* **S4** kendi yatırım gelirinde `sales_target` kolonu KULLANILMAZ; gelir ünite
  liste fiyatları toplamıdır.
"""

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.progress_payments.calculations import gross_total, quantize2
from app.modules.projects.models import Project, ProjectType
from app.modules.subcontractor_progress_payments import repository as subcontractor_repository
from app.modules.subcontractor_progress_payments.models import (
    SubcontractorPaymentStatus,
    SubcontractorProgressPayment,
)
from app.modules.units.models import Unit, UnitOwnerSide
from app.modules.units.summary import VALUE_BASIS_BY_TYPE, basis_value

_ZERO = Decimal("0.00")
_HUNDRED = Decimal("100")

# Kat karşılığında arsa maliyeti TANIM GEREĞİ sıfırdır (KK 105-106 "Arsa Maliyeti
# ₺0 — Kat karşılığı ✓"): arsa bedeli para olarak değil ÜNİTE PAYI olarak ödenir.
# `service._LAND_COST_FIXED` ile aynı kararın hesap tarafı.
_LAND_COST_LAND_SHARE = Decimal("0")


@dataclass(frozen=True)
class SubcontractorCostTotals:
    """KY 212-249 tablosunun tfoot üçlüsü (147-149: Sözleşme/Ödenen/Bekleyen).

    `spent` = `paid` + `pending`tir ama TÜRETİLMİŞ HALDE taşınır: çağıranların
    üçünü de aynı kaynaktan okuması, "harcanan"ın ekranda iki farklı tanıma
    ayrılmasını engeller.
    """

    spent: Decimal
    paid: Decimal
    pending: Decimal


EMPTY_TOTALS = SubcontractorCostTotals(spent=_ZERO, paid=_ZERO, pending=_ZERO)


@dataclass(frozen=True)
class ProfitProjection:
    """KY 168-194 / KK 121-141 kâr projeksiyonu bloğunun dört sayısı.

    `profit`/`margin_pct` bilinmeyen girdide `None`dır — sahte 0 BASILMAZ
    (`units.summary._average` korkuluğunun aynısı).
    """

    revenue: Decimal | None
    cost: Decimal | None
    profit: Decimal | None
    margin_pct: Decimal | None


def money_total(values: Iterable[Decimal | None]) -> Decimal:
    """NULL para 0 SAYILIR (`units.summary._sum` kuralı), toplama `Decimal` ile.

    PUBLIC (T2): uç gövdesi (`cost_summary`) de para toplarken bu tek kuralı
    kullanır — ikinci bir "None nasıl toplanır" tanımı doğmasın.
    """
    return quantize2(sum((value for value in values if value is not None), Decimal("0")))


def _margin_pct(profit: Decimal | None, revenue: Decimal | None) -> Decimal | None:
    """Marj = kâr / gelir × 100. Gelir yok ya da ≤ 0 ise `None` — sıfıra bölme YOK
    ve "geliri olmayan projenin marjı %0" yalanı basılmaz."""
    if profit is None or revenue is None or revenue <= 0:
        return None
    return quantize2(profit / revenue * _HUNDRED)


def _projection(revenue: Decimal | None, cost: Decimal | None) -> ProfitProjection:
    profit = None if revenue is None or cost is None else quantize2(revenue - cost)
    return ProfitProjection(
        revenue=revenue, cost=cost, profit=profit, margin_pct=_margin_pct(profit, revenue)
    )


# --- Taşeron hakediş toplamları (spec §2, S1/S2) ---


def subcontractor_totals(
    payments: Sequence[SubcontractorProgressPayment],
) -> SubcontractorCostTotals:
    """Hakediş kümesinin maliyet üçlüsü — SORGU KOŞMAZ, `lines` yüklü gelmelidir.

    Durum süzgeci (S1): yalnız `approved` ve `paid` maliyete girer. `draft` ve
    `pending_approval` GİRMEZ; "Revize Gerekli" BEŞİNCİ bir durum DEĞİLDİR
    (`draft AND rejected_at IS NOT NULL` türevidir), dolayısıyla o da dışarıdadır.

    Toplam SQL'de değil BELLEKTE alınır: `line_total` kuruş yuvarlaması SATIR
    düzeyindedir (`progress_payments/summary.py:98-114` gerekçesi), SQL `SUM`
    para matematiğinin ikinci bir kopyasını doğururdu.
    """
    paid = money_total(
        gross_total(payment.lines)
        for payment in payments
        if payment.status is SubcontractorPaymentStatus.paid
    )
    pending = money_total(
        gross_total(payment.lines)
        for payment in payments
        if payment.status is SubcontractorPaymentStatus.approved
    )
    return SubcontractorCostTotals(spent=quantize2(paid + pending), paid=paid, pending=pending)


async def subcontractor_totals_by_projects(
    session: AsyncSession, project_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, SubcontractorCostTotals]:
    """Liste ucunun (E4 kartları) TEK toplu okuması — proje başına sorgu YASAK
    (spec §4; `progress_payments.summary.cumulative_gross_by_projects` deseni).

    İstenen HER proje kimliği yanıtta bulunur: hakedişi olmayan proje
    `EMPTY_TOTALS` ile döner, böylece çağıran eksik anahtar tuzağına düşmez.
    Kapsam süzgeci SQL'dedir — listede olmayan projenin satırı hiç ÇEKİLMEZ.
    """
    grouped = await subcontractor_repository.list_cost_payments_by_projects(
        session, list(project_ids)
    )
    return {
        project_id: subcontractor_totals(grouped.get(project_id, [])) for project_id in project_ids
    }


# --- Arsa ve bütçe maliyeti (spec §2) ---


def land_cost(project: Project) -> Decimal | None:
    """Arsa maliyeti proje tipine göre ÜÇ FARKLI ŞEY söyler:

    * kendi yatırım → `project_investment.land_cost` (KY 118-122); satır ya da
      değer yoksa `None` = "girilmedi", 0 DEĞİL.
    * kat karşılığı → tanım gereği `0` (KK 105-106).
    * taahhüt → `None`: arsa KAVRAMI yoktur, 0 basmak "bedava arsa" yalanı olurdu.
    """
    if project.project_type is ProjectType.kat_karsiligi:
        return _LAND_COST_LAND_SHARE
    if project.project_type is not ProjectType.kendi_yatirim:
        return None
    investment = project.investment
    return investment.land_cost if investment is not None else None


def budget_lines_total(project: Project) -> Decimal:
    """Dört bütçe kalemi (P1: material+labor+subcontractor+overhead).

    `projects.budget` kolonu OKUNMAZ: göç öncesi satırlarda o alan dört kalemin
    toplamı DEĞİLDİR (`models.Project.budget` notu) — tek doğruluk kalemlerdedir.
    """
    return money_total(
        (
            project.budget_material,
            project.budget_labor,
            project.budget_subcontractor,
            project.budget_overhead,
        )
    )


def total_budget_cost(project: Project) -> Decimal:
    """Toplam bütçe maliyeti = 4 bütçe kalemi + arsa maliyeti (KY 182 ₺29.800.000).

    Girilmemiş arsa maliyeti toplama 0 katkı yapar (`units.summary._sum` kuralı);
    "girilmedi" bilgisi kaybolmaz, `land_cost()` yine `None` döner ve ekran "—"
    basabilir. Kat karşılığında arsa 0 olduğu için bu değer aynı zamanda İNŞAAT
    bütçesidir (KK 135 ₺17,6M).
    """
    return money_total((budget_lines_total(project), land_cost(project)))


# --- Ünite değer toplamları ---


def unit_list_price_total(units: Sequence[Unit]) -> Decimal:
    """S4: kendi yatırım gelirinin tabanı — `sales_target` kolonu DEĞİL (KY 169)."""
    return money_total(unit.list_price for unit in units)


def our_share_value(units: Sequence[Unit], project_type: ProjectType) -> Decimal:
    """KK 121 "BİZİM PAY" değeri: yalnız `owner_side=contractor` üniteler.

    Değer sütunu proje tipine göre seçilir ve seçim `units.summary`de TEK
    kopyadır (kat karşılığında `appraisal_value`, diğerlerinde `list_price`) —
    aksi hâlde aynı proje iki ekranda iki farklı "pay değeri" gösterirdi.
    """
    basis = VALUE_BASIS_BY_TYPE[project_type]
    return money_total(
        basis_value(unit, basis) for unit in units if unit.owner_side is UnitOwnerSide.contractor
    )


def gross_area_total(units: Sequence[Unit]) -> Decimal:
    """Ünite maliyeti dağıtımının paydası (S3). m²'si girilmemiş ünite 0 katkı yapar."""
    return money_total(unit.gross_area_m2 for unit in units)


# --- Kâr/marj türevleri (spec §2 formülleri) ---


def investment_projection(project: Project, units: Sequence[Unit]) -> ProfitProjection:
    """Kendi yatırım (KY 169/182/187-188): 48,2M − 29,8M = 18,4M · %38,2 marj.

    Gelir ünite liste fiyatlarından TÜRER (S4); `sales_target` hesapla
    ÇELİŞTİRİLMEZ, yalnız kendi alanında dönmeye devam eder.
    """
    return _projection(unit_list_price_total(units), total_budget_cost(project))


def land_share_projection(project: Project, units: Sequence[Unit]) -> ProfitProjection:
    """Kat karşılığı (KK 121/135/139-140): 30,4M − 17,6M = 12,8M · %42,1 marj.

    Maliyet `total_budget_cost`tır; arsanın 0 olması kuralı hesaba GÖMÜLÜDÜR
    (`land_cost`), burada ikinci bir "arsa yok" dalı açılmaz.
    """
    return _projection(our_share_value(units, project.project_type), total_budget_cost(project))


def contracting_projection(project: Project, spent: Decimal) -> ProfitProjection:
    """Taahhüt: kâr = sözleşme bedeli − harcanan.

    E4 180-181 kartında YALNIZ "Sözleşme Bedeli / Harcanan" basılır; tahmini kâr
    kartta YOKTUR — bu yüzden değer iç türev olarak döner, kart alanı açılmaz.
    Bedel girilmemişse kâr `None`dır (bedelsiz projeye kâr uydurulmaz).
    """
    return _projection(project.contract_amount, spent)


def profit_projection(project: Project, units: Sequence[Unit], spent: Decimal) -> ProfitProjection:
    """Tip bazlı dağıtıcı — E4'ün üç kart alan seti tek yerden beslenir (E4 75/82/89)."""
    if project.project_type is ProjectType.kendi_yatirim:
        return investment_projection(project, units)
    if project.project_type is ProjectType.kat_karsiligi:
        return land_share_projection(project, units)
    return contracting_projection(project, spent)


# --- Ünite maliyeti ve satıştan kâr ---


def unit_cost(
    project_budget_cost: Decimal,
    unit_gross_area_m2: Decimal | None,
    project_gross_area_m2: Decimal,
) -> Decimal | None:
    """S3 (onaylı iş kuralı): toplam bütçe maliyeti × ünite brüt m² / proje brüt m².

    **Bütçe bazlıdır, gerçekleşen bazlı DEĞİL:** inşaat sürerken gerçekleşen
    maliyet düşük olduğu için ünite maliyeti saçma derecede düşük çıkardı ve
    satıştan kâr olduğundan büyük görünürdü.

    m² bilgisi olmayan ünitede ya da toplam m²'si 0 olan projede `None` döner —
    uydurma maliyet üretilmez (sıfıra bölme korkuluğu).
    """
    if unit_gross_area_m2 is None or project_gross_area_m2 <= 0:
        return None
    return quantize2(project_budget_cost * unit_gross_area_m2 / project_gross_area_m2)


def entered_budget_cost(project: Project) -> Decimal | None:
    """`total_budget_cost` ama GİRİLMEMİŞ bütçe `None` döner (P10 T3).

    Dört bütçe kalemi de arsa da NOT NULL/`0` varsayılanlıdır: bütçesi hiç
    girilmemiş projede toplam `0.00` çıkar. O sıfır "bu projenin maliyeti ₺0"
    DEĞİL "maliyet bilinmiyor"dur ve kart zarfına dolu değer olarak basılırsa
    ekranda beklenen kâr satış bedelinin TAMAMI görünür — `_margin_pct`in
    sıfıra bölmeyi `None`a çevirmesiyle aynı gerekçe (uydurma değer yasağı).

    T2 ucu (`cost_summary`) bu süzgeci KULLANMAZ: orada `construction_budget`
    ayrı bir satırdır ve "₺0 bütçe girilmiş" bilgisi ekranda kırılım kartında
    zaten görünür.
    """
    total = total_budget_cost(project)
    return total if total > 0 else None


@dataclass(frozen=True)
class UnitCostAllocation:
    """Ünite maliyeti m² dağıtımının proje düzeyi bağlamı (S3).

    Bağlam BİR KEZ kurulur ve ünite başına yeniden hesaplanmaz: liste uçlarında
    (ünite listesi, satış listesi) payda tüm ünitelerin brüt m² toplamıdır ve
    onu her satır için yeniden toplamak N² iş demekti.
    """

    budget_cost: Decimal | None
    total_gross_area_m2: Decimal

    def for_unit(self, unit_gross_area_m2: Decimal | None) -> Decimal | None:
        """Tek ünitenin maliyeti; bilinmeyen girdide `None` (bkz. `unit_cost`)."""
        if self.budget_cost is None:
            return None
        return unit_cost(self.budget_cost, unit_gross_area_m2, self.total_gross_area_m2)

    def expected_profit(
        self, unit_gross_area_m2: Decimal | None, price: Decimal | None
    ) -> Decimal | None:
        """UE 98 "Beklenen Kâr" = liste fiyatı − ünite maliyeti.

        İki bilinmeyenden BİRİ eksikse kâr da bilinmez: fiyatsız ünitede
        "kâr = −maliyet" basmak, henüz fiyatlanmamış daireyi zararda göstermek
        olurdu.
        """
        cost = self.for_unit(unit_gross_area_m2)
        return None if cost is None or price is None else quantize2(price - cost)


def allocation(project: Project, units: Sequence[Unit]) -> UnitCostAllocation:
    """Projenin dağıtım bağlamı. `units` projenin TAMAMI olmalıdır (payda)."""
    return UnitCostAllocation(
        budget_cost=entered_budget_cost(project), total_gross_area_m2=gross_area_total(units)
    )


def card_projection(project: Project, units: Sequence[Unit]) -> ProfitProjection:
    """E4 kartlarının kâr/marj türevi (E4 75/82/89) — `profit_projection`tan İKİ farkla:

    1. maliyet `entered_budget_cost`tur: bütçesi girilmemiş projede kâr/marj
       zarfı BOŞ kalır, sahte "maliyet 0 → kâr = tüm satış" basılmaz.
    2. taahhüt dalı YOKTUR: E4 180-181 taahhüt kartında tahmini kâr/marj alanı
       hiç BASILMAZ (spec §2) — olmayan alan için hesap da yapılmaz.
    """
    revenue = (
        unit_list_price_total(units)
        if project.project_type is ProjectType.kendi_yatirim
        else our_share_value(units, project.project_type)
    )
    return _projection(revenue, entered_budget_cost(project))


def sale_profit(sale_price: Decimal, unit_cost_value: Decimal | None) -> ProfitProjection:
    """DS 90-91 "Bu Satıştan Kâr": satış bedeli − ünite maliyeti; marj = kâr / bedel.

    Ünite maliyeti bilinmiyorsa (m²'siz ünite) kâr da bilinmez → `None`.
    """
    return _projection(sale_price, unit_cost_value)
