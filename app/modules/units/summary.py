"""Unite listesinin SAF sunum/toplama cekirdegi (spec §6.1, §5.2, §7.4).

Servisten AYRI tutulur ki "24 unitenin toplami ne eder", "taraf yuzdesi nasil
hesaplanir" sorulari veritabanina, oturuma ve yetkiye dokunmadan test
edilebilsin (`bulk.py` ile ayni gerekce). Burada `AsyncSession` YOKTUR ve
olmamalidir: bu modul yalnizca ORM nesnelerini semalara cevirir.
"""

import uuid
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.modules.projects.models import ProjectType
from app.modules.sales.models import UnitSaleStatus
from app.modules.units.models import Block, Unit, UnitKind, UnitOwnerSide, UnitSalesStatus
from app.modules.units.schemas import (
    BlockResponse,
    MetricPlaceholder,
    UnitKindBreakdown,
    UnitResponse,
    UnitSideSummary,
    UnitTotals,
    UnitValueBasis,
)

# Spec §6.1: bu dilimde YAZILMAYAN turev alanlarin bagli oldugu modul anahtarlari.
# Kullaniciya gosterilecek metin degil, B6 yer tutucu sozlesmesindeki anahtardir.
#
# `_UNIT_SALES` KALDIRILDI (P8 T5): dort yer tutucusunun (KY 275 `sale_price`,
# KY 277 `buyer_name`, KY 93 `sales_revenue`, KY 267 `average_sale_price`) veri
# kaynagi artik VAR — `unit_sales` tablosu P8'de acildi. `sales_status`un
# P3.1'de yer tutucudan gercek sutuna donusunun aynisi. Geriye kalan iki anahtar
# hâlâ verisi YAZILMAMIS modulleri gosterir.
#
# `_SHAREHOLDER_UNITS` KALDIRILDI (P9 T3): KKP 91'in hissedar yarisinin veri
# kaynagi artik VAR — `units.shareholder_id` T1'de acildi. `_UNIT_SALES`in P8
# T5'teki kalkisinin aynisi. Geriye TEK anahtar kalir ve o hâlâ verisi
# YAZILMAMIS bir modulu gosterir.
_PROJECT_COSTS = "project_costs"


@dataclass(frozen=True)
class UnitSaleInfo:
    """Bir unitenin ACIK satis kaydindan (P8) okunan sunum verisi.

    ORM nesnesi DEGIL sade bir demet tasinir: bu modulun sozlesmesi "yalniz
    Decimal/str alir, sema dondurur"dur ve `sales` ORM'unu buraya sizdirmak
    saf toplama cekirdegini veritabani nesnelerine baglardi.
    """

    sale_price: Decimal
    customer_name: str
    status: UnitSaleStatus

    @property
    def is_realized(self) -> bool:
        """KY 93 "Satis Geliri" GERCEKLESEN satistir; rezervasyon ciro DEGILDIR.

        Unite SATIRI yine de rezervasyonun bedelini gosterir (o daireye kimin
        kapora verdigi ekranda gorunmelidir); TOPLAM ciroya ise yalniz
        `active`/`deed_transferred` girer. Ayni ayrim satis ozetinin S55/S56
        kartlarinda da vardir (`sales/summary._SOLD_STATUSES`).
        """
        return self.status in (UnitSaleStatus.active, UnitSaleStatus.deed_transferred)


_MONEY = Decimal("0.01")
_HUNDRED = Decimal("100")

# Taraf ozetlerinin SABIT sirasi (spec §5.3): ucu de her zaman doner, unite
# olmasa bile. Ekran "henuz paylasilmadi" durumunu `None` grubundan basar.
_SIDE_ORDER: tuple[UnitOwnerSide | None, ...] = (
    UnitOwnerSide.contractor,
    UnitOwnerSide.landowner,
    None,
)

# Spec §4.4: toplamlarin hangi sutundan hesaplandigi proje tipine baglidir.
VALUE_BASIS_BY_TYPE = {
    ProjectType.kat_karsiligi: UnitValueBasis.appraisal_value,
    ProjectType.kendi_yatirim: UnitValueBasis.list_price,
    ProjectType.taahhut: UnitValueBasis.list_price,
}


def _quantize_money(value: Decimal) -> Decimal:
    return value.quantize(_MONEY, rounding=ROUND_HALF_UP)


def _metric(pending_module: str) -> MetricPlaceholder:
    return MetricPlaceholder(pending_module=pending_module)


def _sum(values: list[Decimal | None]) -> Decimal:
    """NULL'lar 0 SAYILIR (spec §6.1) ve toplama Decimal ile yapilir — float ASLA."""
    return _quantize_money(sum((value for value in values if value is not None), Decimal("0")))


def _counts(units: list[Unit]) -> UnitKindBreakdown:
    return UnitKindBreakdown(
        apartment=sum(1 for u in units if u.unit_kind is UnitKind.apartment),
        shop=sum(1 for u in units if u.unit_kind is UnitKind.shop),
        # UE 74 (spec §4.3) — karar 13: sayaclar eklenir, EKRAN ETIKETLERI DEGIL.
        office=sum(1 for u in units if u.unit_kind is UnitKind.office),
        warehouse=sum(1 for u in units if u.unit_kind is UnitKind.warehouse),
        parking=sum(1 for u in units if u.unit_kind is UnitKind.parking),
    )


def _by_sales_status(units: list[Unit]) -> dict[UnitSalesStatus, int]:
    """UE 94'un dort degerinin sayimi (spec §8.2).

    Sayim BURADA, zaten bellekte olan liste uzerinde yapilir: ayri bir
    `GROUP BY` sorgusu ikinci bir gidis-donus demek olurdu ve `totals` zaten
    projenin TUM unitelerini alan tek sorgudan besleniyor. Dort anahtar da her
    zaman doner; `sales_status` NULL olan (migration oncesi) satirlar hicbir
    sayaca girmez — uydurulmus bir durum atanmaz.
    """
    counts = dict.fromkeys(UnitSalesStatus, 0)
    for unit in units:
        if unit.sales_status is not None:
            counts[unit.sales_status] += 1
    return counts


def _basis_value(unit: Unit, basis: UnitValueBasis) -> Decimal | None:
    if basis is UnitValueBasis.appraisal_value:
        return unit.appraisal_value
    return unit.list_price


def to_block(block: Block, site_name: str, units: list[Unit]) -> BlockResponse:
    return BlockResponse(
        id=block.id,
        name=block.name,
        site_id=block.site_id,
        site_name=site_name,
        sort_order=block.sort_order,
        counts=_counts(units),
        # Blok formu (BE) — 13 alan aynen doner; `estimated_unit_count`
        # BlockResponse'ta TUREVDIR ve burada hesaplanmaz (spec §3.3).
        code=block.code,
        basement_floor_count=block.basement_floor_count,
        floor_count=block.floor_count,
        roof_type=block.roof_type,
        units_per_floor=block.units_per_floor,
        ground_floor_usage=block.ground_floor_usage,
        shop_count=block.shop_count,
        construction_area_m2=block.construction_area_m2,
        elevator_count=block.elevator_count,
        parking_type=block.parking_type,
        estimated_delivery_date=block.estimated_delivery_date,
        status=block.status,
        notes=block.notes,
    )


def to_unit(
    unit: Unit,
    block_name: str,
    sale: UnitSaleInfo | None = None,
    shareholder_name: str | None = None,
) -> UnitResponse:
    """Satis FIYATI/ALICISI (KY 275/277) P8 T5'te GERCEK degere baglandi; satis
    yoksa `None` doner — uydurma deger uretilmez. Satis DURUMU (UE 94) P3.1'de
    gercek sutuna donmustu (kullanici karari 2, spec §4.4). HISSEDAR (KKP 91)
    P9 T3'te ayni yolu izledi: `shareholder_id` gercek kolondur, ADI ise
    CAGIRANDAN gelir — bu modul veritabanina dokunmaz (dosya basligi) ve ad
    cozumu boylece tek toplu sorguda kalir (N+1 yok, spec §4.3)."""
    return UnitResponse(
        id=unit.id,
        block_id=unit.block_id,
        block_name=block_name,
        unit_no=unit.unit_no,
        unit_kind=unit.unit_kind,
        layout=unit.layout,
        gross_area_m2=unit.gross_area_m2,
        net_area_m2=unit.net_area_m2,
        list_price=unit.list_price,
        appraisal_value=unit.appraisal_value,
        owner_side=unit.owner_side,
        sort_order=unit.sort_order,
        floor=unit.floor,
        facing=unit.facing,
        balcony_area_m2=unit.balcony_area_m2,
        bathroom_count=unit.bathroom_count,
        parking_right=unit.parking_right,
        min_sale_price=unit.min_sale_price,
        vat_rate=unit.vat_rate,
        # UE 94 artik GERCEK degerdir (kullanici karari 2, spec §4.4).
        sales_status=unit.sales_status,
        # KY 275/277 — P8 T5'te ACIK satis kaydina baglandi (yer tutucu bitti).
        sale_price=sale.sale_price if sale is not None else None,
        buyer_name=sale.customer_name if sale is not None else None,
        # KKP 91 — P9 T3'te yer tutucu bitti. Ad `None` kalabilir: atama zorunlu
        # DEGILDIR (KKP 119 "—") ve uydurma ad uretilmez.
        shareholder_id=unit.shareholder_id,
        shareholder_name=shareholder_name,
        # Maliyet kolonu ACILMAZ (karar 3): maliyet yoksa kâr da yoktur.
        unit_cost=_metric(_PROJECT_COSTS),
        expected_profit=_metric(_PROJECT_COSTS),
    )


def _average(total: Decimal, count: int) -> Decimal | None:
    """Sifira bolme YOK: unitesi olmayan kumede ortalama `None`'dir, 0 degil."""
    if count == 0:
        return None
    return _quantize_money(total / Decimal(count))


def _side_summary(
    side: UnitOwnerSide | None, units: list[Unit], basis: UnitValueBasis, project_total: int
) -> UnitSideSummary:
    """KK 116-122 / KKP 161-168 tfoot toplami.

    `share_pct` ADET oranidir (spec §5.2): sozlesmedeki yuzde (P1) ile birebir
    tutmak ZORUNDA DEGILDIR ve sapma DOGRULANMAZ, yalnizca raporlanir.
    """
    selected = [u for u in units if u.owner_side is side]
    total_value = _sum([_basis_value(u, basis) for u in selected])
    share_pct = (
        _quantize_money(Decimal(len(selected)) * _HUNDRED / Decimal(project_total))
        if project_total
        else None
    )
    # Satis sayaclari `totals` ile AYNI kaynaktan (`_by_sales_status`) turer ve
    # ZATEN BELLEKTE olan liste uzerinde sayilir — taraf basina ayri bir
    # `GROUP BY` sorgusu ucuncu bir gidis-donus demek olurdu (`_by_sales_status`
    # notunun aynisi).
    by_status = _by_sales_status(selected)
    return UnitSideSummary(
        side=side,
        counts=_counts(selected),
        total_value=total_value,
        average_value=_average(total_value, len(selected)),
        share_pct=share_pct,
        sold=by_status[UnitSalesStatus.sold],
        reserved=by_status[UnitSalesStatus.reserved],
        listed=by_status[UnitSalesStatus.listed],
    )


def totals(
    units: list[Unit],
    basis: UnitValueBasis,
    sales_by_unit: dict[uuid.UUID, UnitSaleInfo] | None = None,
) -> UnitTotals:
    """Spec §7.4: toplamlar SUZGECTEN ETKILENMEZ — cagiran daima projenin TUM
    unitelerini verir (P1 `list_projects_overview` kuralinin birebir tekrari).

    `sales_by_unit` verilen UNITELERE gore suzulur: sozluk projenin tamamini
    tasiyabilir, ciro yalnizca elde tutulan unitelerden toplanir."""
    total_value = _sum([_basis_value(u, basis) for u in units])
    by_status = _by_sales_status(units)
    satislar = sales_by_unit or {}
    gerceklesen = [
        info
        for info in (satislar.get(unit.id) for unit in units)
        if info is not None and info.is_realized
    ]
    sales_revenue = _sum([info.sale_price for info in gerceklesen])
    return UnitTotals(
        counts=_counts(units),
        value_basis=basis,
        total_value=total_value,
        average_value=_average(total_value, len(units)),
        total_list_price=_sum([u.list_price for u in units]),
        total_appraisal_value=_sum([u.appraisal_value for u in units]),
        total_gross_area_m2=_sum([u.gross_area_m2 for u in units]),
        sides=[_side_summary(side, units, basis, len(units)) for side in _SIDE_ORDER],
        by_sales_status=by_status,
        sold_units=by_status[UnitSalesStatus.sold],
        reserved_units=by_status[UnitSalesStatus.reserved],
        available_units=by_status[UnitSalesStatus.listed],
        # KY 93 / KY 267 — P8 T5'te GERCEK degere baglandi. Ortalama SIFIRA
        # BOLUNMEZ: satis yoksa `None`dir, 0 degil (`_average` ile ayni kural).
        sales_revenue=sales_revenue,
        average_sale_price=_average(sales_revenue, len(gerceklesen)),
    )
