"""`GET /projects/{id}/costs` gövdesi (P10 T2, spec §3) — türev OKUMA ucu.

## Neden `costs.py`dan ayrı

`costs.py` SAF hesap çekirdeğidir (oturumsuz, yetkisiz test edilebilir);
burası ise oturuma, görünürlük süzgecine ve şemalara dokunan ORKESTRASYON
katmanıdır. Aynı ayrım `progress_payments/summary.py` ile `calculations.py`
arasında da vardır ve orada da uç gövdesi ayrı dosyadadır. Hesap formülleri
BURADA YENİDEN YAZILMAZ: her rakam `costs`tan çağrılır.

## Görünürlük

Kapsam kapısı `service._visible_project`tir — TEK kimlik-ile-erişim kapısı
(P1 spec §5.6). Görünmeyen proje ile var olmayan proje AYIRT EDİLEMEZ 404
verir. `progress_payments/summary.get_summary` aynı özel adı aynı gerekçeyle
çağırır; ikinci bir görünürlük mantığı kopyalanmaz.

## N+1 (spec §4)

Yanıt SABİT sayıda sorgu koşar; taşeron/hakediş/ünite sayısı sorgu sayısını
BÜYÜTMEZ:

1. sözleşmeler (`contracts.repository.list_subcontractor_contracts`) — kalemler
   `lazy="selectin"` ile TEK ek sorguda gelir
2. maliyete giren hakedişler (+ `lines` `selectin` ile ikinci sorgu)
3. üniteler — yalnız gelir tarafı üniteden türeyen tiplerde (taahhütte HİÇ
   çekilmez, çünkü gelir sözleşme bedelidir)

## Sözleşme bedeli hangi kopyadan okunur

`contracts.service._subcontractor_amount` — kalem başına ÖNCE kuruşa yuvarlar
sonra toplar ve zaten yüklü `items`ten okur (ek sorgu YOK). Alternatifi
(`subcontractor_progress_payments.repository.get_contract_amounts`) SQL `SUM`
ile ham çarpımları toplar; `Numeric(14,3) × Numeric(18,2)` beş ondalık
üretebildiği için bu, SZL sözleşme listesinin bastığı bedelden kuruş sapabilir.
Aynı sözleşmenin bedeli iki ekranda farklı görünmemelidir, bu yüzden satır
düzeyi yuvarlama yapan tek kopya kullanılır (özel ada erişim `contracts.
subcontracts` ve `contracts.distribution`daki emsalin aynısı).
"""

import uuid
from collections import defaultdict
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.contracts import repository as contracts_repository
from app.modules.contracts.models import SubcontractorContract
from app.modules.contracts.service import _subcontractor_amount
from app.modules.progress_payments.summary import progress_pct as financial_progress_pct
from app.modules.projects import costs, service
from app.modules.projects.models import Project, ProjectType
from app.modules.projects.schemas import (
    MetricPlaceholder,
    ProjectCostBreakdown,
    ProjectCostsResponse,
    ProjectProfitProjection,
    SubcontractorCostRow,
    SubcontractorCostSummary,
)
from app.modules.sales import repository as sales_repository
from app.modules.sales.models import UnitSale
from app.modules.subcontractor_progress_payments import repository as payments_repository
from app.modules.subcontractor_progress_payments.models import SubcontractorProgressPayment
from app.modules.units import repository as units_repository
from app.modules.units.models import Unit
from app.modules.users.models import User

# Yer tutucu kalemlerin kaynak modülleri (KY 134-154, spec §2). Anahtar
# kullanıcıya gösterilecek metin DEĞİL, izin modülü anahtarıdır (B6 zarf
# sözleşmesi): ekran kalemin hangi modülün MÜLKİYETİNDE olduğunu buradan okur.
#
# ⚠️ 2026-08-22 DENETİMİ — ESKİ GEREKÇE ("modül gelince dolacak") ARTIK YANLIŞ:
# `accounting` de `treasury` de CANLIDIR (router'ları `app/main.py`de kayıtlı;
# muhasebe dört router ile, hazine kendi router'ı + `instruments` ile). Yani üç
# kalemi bekleten şey MODÜLÜN YOKLUĞU değildir.
#
# GERÇEKTEN EKSİK OLAN: gideri bu üç kategoride BİR PROJEYE bağlayan veri.
# Kategorinin KENDİSİ kısmen var — hesap planında `760/631 Pazarlama Giderleri`,
# `780/66 Finansman Giderleri`, `795 Vergi, Resim ve Harçlar` (chart_seed_data.py)
# duruyor. Olmayan şey PROJE KIRILIMI: muhasebenin üç tablosunda da
# `project_id`/`site_id` KOLONU YOKTUR ve bu unutulmuş değil YAPISALDIR —
# `accounting/models.py:67-72` bunu açıkça yazar ve maliyet merkezi/proje
# kırılımını MU-3'e bırakır (`journal_entries`te `project_id` yokluğu a.g.e.
# 613-614'te bir kez daha teyit edilir). Hazine tarafı da aynı: `payments`
# tablosunda `project_id`/`site_id` yoktur (`treasury/repository.py:7-9`).
# Yani fiş de ödeme de yazılabiliyor, ama "bu kayıt X PROJESİNİN ruhsat/
# finansman/pazarlama gideridir" DENEMİYOR. Kısacası: **modül CANLI, kategori
# kısmen var, KATEGORİLENMİŞ-VE-PROJEYE-BAĞLI VERİ yok.** Bu yüzden alanlar 0
# değil "kaynak yok" döner (uydurma 0 yasağı, `_pending`) ve yer tutucunun
# KALMASI doğru sonuçtur.
#
# * Ruhsat & Harçlar + Pazarlama & Satış → `accounting`: ikisi de gider fişidir,
#   proje maliyetine muhasebe kaydından girecektir.
# * Finansman (Kredi Faizi) → `treasury`: kredi ve faiz Hazine modülünün
#   konusudur (KY 145 "₺6M kredi · Kalan faiz: ₺890K").
_ACCOUNTING = "accounting"
_TREASURY = "treasury"

# Gelir tarafı ÜNİTEDEN türeyen tipler (spec §2): kendi yatırımda liste
# fiyatları toplamı, kat karşılığında bizim pay değeri. Taahhütte gelir
# sözleşme bedelidir ve ünite tablosuna hiç DOKUNULMAZ.
_UNIT_REVENUE_TYPES = (ProjectType.kendi_yatirim, ProjectType.kat_karsiligi)


def _pending(module_key: str) -> MetricPlaceholder:
    """Kaynağı olmayan kalem: `available=False` + `value=None` (uydurma 0 YOK)."""
    return MetricPlaceholder(pending_module=module_key)


def _row(
    contract: SubcontractorContract,
    payments_by_contract: dict[uuid.UUID, list[SubcontractorProgressPayment]],
) -> SubcontractorCostRow:
    """Bir SÖZLEŞMENİN satırı: bedeli sözleşmeden, ödenen/bekleyeni hakedişten.

    Taşeron/kategori alanları doğrudan sözleşmeden okunur (şema notu): satır
    birimi sözleşme olduğu için "kategoriler ayrışırsa None" kuralı gerekmez.

    Ödenen/bekleyen `costs.subcontractor_totals` ile hesaplanır — brüt ve durum
    süzgeci tek kopyadır, bu dosya ikinci bir "harcanan" tanımı yazmaz.

    ## "İlerleme" sütunu = `ÖDENEN / SÖZLEŞME × 100` (bekleyen PAYA GİRMEZ)

    Formül MOCKUP ARİTMETİĞİNDEN okundu. Normalde bu repoda mockup RAKAMLARI
    göstermeliktir ve kural mockup'ın YAPISINDAN okunur; burada aritmetiğe
    güvenilmesinin sebebi, tabloyu taşıyan İKİ mockup'ın SÜTUN KÜMELERİNİN
    FARKLI olmasına rağmen 6 satırın 6'sının da TEK bir formülde buluşmasıdır —
    bu dekorasyon değil TASARIM NİYETİDİR:

    * KY 209-251 (Taşeron·İş Kalemi·Sözleşme·Ödenen·**Bekleyen**·İlerleme):
      5,7/8,4 → %68 · 1,2/2,4 → %50 · 0/1,8 → %0
    * KK 213-246 (Taşeron·İş Kalemi·Sözleşme·Ödenen·İlerleme·**Durum**):
      2,9/6,8 → %42 · 0,380/1,9 → %20 · 0/1,4 → %0

    Rakip formül `(Ödenen + Bekleyen) / Sözleşme` KY satırlarının HİÇBİRİNİ
    tutturmaz (ilk satır %77,9 ederdi, mockup %68 basar). Bu yüzden pay YALNIZ
    `paid`tir.

    ## Formül neden BURADA YAZILMIYOR (K3)

    `progress_payments.summary.progress_pct` bu hesabın TEK kopyasıdır (işveren
    tarafındaki ikiz "İlerleme" göstergesi); payda `None`/`<= 0` iken sahte %0
    yerine `None` döndüren bekçi de oradadır. Kopyalamak, iki "İlerleme"
    yüzeyinin zamanla ayrışmasına izin verirdi — bu yüzden ÇAĞRILIYOR. Modül
    sınırının aşılması yeni değil: `projects/costs.py` de
    `progress_payments.calculations`tan `gross_total`/`quantize2` çeker.

    Buradan gelen payda ASLA `None` değildir (`_subcontractor_amount` her zaman
    `Decimal` döner), yani gerçekte çalışan bekçi `<= 0` dalıdır: kalemsiz
    sözleşme ya da bütün kalemleri `unit_price IS NULL` olan sözleşme `0.00`
    bedel üretir ve satır `None` ilerleme ile döner. Bedeli olup hiç ödeme
    görmemiş sözleşme ise GERÇEK `0.00` alır (KY 236-243).
    """
    totals = costs.subcontractor_totals(payments_by_contract.get(contract.id, []))
    contract_amount = _subcontractor_amount(contract)
    return SubcontractorCostRow(
        contract_id=contract.id,
        contract_no=contract.contract_no,
        subcontractor_id=contract.subcontractor_id,
        subcontractor_name=contract.subcontractor_name,
        work_category=contract.work_category,
        contract_amount=contract_amount,
        paid=totals.paid,
        pending=totals.pending,
        progress_pct=financial_progress_pct(totals.paid, contract_amount),
    )


def _sort_key(row: SubcontractorCostRow) -> tuple[str, str, str]:
    """Deterministik sıra: taşeron adı → `contract_no` → `contract_id`.

    `contract_no` taslakta NULL'dur (kolon kısmi tekil indeksli); boş dize ile
    normalize edilir, yoksa aynı taşeronun satırları istekler arasında oynardı.
    """
    return ((row.subcontractor_name or ""), (row.contract_no or ""), str(row.contract_id))


def _rows(
    contracts: list[SubcontractorContract],
    payments_by_contract: dict[uuid.UUID, list[SubcontractorProgressPayment]],
) -> list[SubcontractorCostRow]:
    """KY 205-249 satırları — SÖZLEŞME başına, `_sort_key` ile SIRALI.

    Hakedişi olmayan sözleşme de satır açar (KY 236-243 "Demirci Alüminyum
    ₺1,8M / ₺0 / ₺0"): tablo SÖZLEŞMELERDEN doğar, hakedişlerden değil — aksi
    hâlde henüz hakediş kesilmemiş taşeron ekranda hiç görünmezdi.
    """
    return sorted((_row(contract, payments_by_contract) for contract in contracts), key=_sort_key)


def _total(rows: list[SubcontractorCostRow]) -> SubcontractorCostSummary:
    """tfoot = satırların toplamı (KY 244-248), ikinci bir sorgu KOŞMADAN.

    İLERLEME TOPLAMI YOKTUR: KY tfoot'unun "İlerleme" hücresi harfiyen boştur
    (`<td></td>`), KK'nın tfoot'u ise hiç yoktur — şema notundaki gerekçe.
    """
    return SubcontractorCostSummary(
        contract_amount=costs.money_total(row.contract_amount for row in rows),
        paid=costs.money_total(row.paid for row in rows),
        pending=costs.money_total(row.pending for row in rows),
    )


def _breakdown(project: Project, construction_spent: Decimal) -> ProjectCostBreakdown:
    land = costs.land_cost(project)
    construction_budget = costs.budget_lines_total(project)
    return ProjectCostBreakdown(
        land_cost=land,
        construction_spent=construction_spent,
        construction_budget=construction_budget,
        # Üçü de YER TUTUCU KALIR — doğru sonuç. Engel modül değil, gideri bu üç
        # kategoriye bağlayan verinin hiç olmaması (gerekçe: `_ACCOUNTING` notu).
        permits=_pending(_ACCOUNTING),
        financing=_pending(_TREASURY),
        marketing=_pending(_ACCOUNTING),
        # Girilmemiş arsa (None) toplama 0 katkı yapar; "girilmedi" bilgisi
        # `land_cost` alanında yaşamaya devam eder (`costs.total_budget_cost` kuralı).
        # Hesap `costs.total_spent`tedir: E4 kartı da AYNI fonksiyondan besleniyor.
        total_spent=costs.total_spent(project, construction_spent),
    )


async def _project_units(session: AsyncSession, project: Project) -> list[Unit]:
    if project.project_type not in _UNIT_REVENUE_TYPES:
        return []
    return await units_repository.list_units_for_project(session, project.id)


async def _project_sales(session: AsyncSession, project: Project) -> list[UnitSale]:
    """Gerçekleşen satış tabanı — TEK sorgu (`list_sale_rows`), satış sayısı sorgu
    sayısını BÜYÜTMEZ (spec §4).

    `exclude_cancelled=True`: iptal edilmiş satış ne cirodur ne alacaktır
    (repository notu); "gerçekleşmiş" süzgeci ayrıca `costs.realized_sales_total`
    içindedir. Ünite kavramı olmayan tipte (taahhüt) satış tablosuna HİÇ
    dokunulmaz — `_project_units` süzgecinin aynısı.
    """
    if project.project_type not in _UNIT_REVENUE_TYPES:
        return []
    rows = await sales_repository.list_sale_rows(session, project.id, exclude_cancelled=True)
    return [row[0] for row in rows]


def _profit(
    project: Project,
    units: list[Unit],
    sales: list[UnitSale],
    construction_spent: Decimal,
) -> ProjectProfitProjection:
    """KY 168-194 bloğu. İki satış satırı (173-180) YALNIZ gelir tarafı üniteden
    türeyen tiplerde doludur; taahhütte `None` (ünite/satış kavramı yok)."""
    projection = costs.profit_projection(project, units, construction_spent)
    unit_revenue = project.project_type in _UNIT_REVENUE_TYPES
    return ProjectProfitProjection(
        revenue=projection.revenue,
        cost=projection.cost,
        profit=projection.profit,
        margin_pct=projection.margin_pct,
        realized_sales=costs.realized_sales_total(sales) if unit_revenue else None,
        remaining_stock_value=costs.remaining_stock_value(units) if unit_revenue else None,
    )


async def build_project_costs(session: AsyncSession, project: Project) -> ProjectCostsResponse:
    """Yanıtın GÖVDESİ — görünürlük kontrolü YAPMAZ (çağıran çoktan yapmıştır).

    `progress_payments.summary.build_summary` ile aynı ayrım: gövdeyi ayrı
    tutmak, ileride başka bir ekranın (E4 kartı, şantiye sekmesi) kendi kapsam
    süzgecinden sonra aynı hesabı yeniden kullanabilmesini sağlar.

    MUTASYON YOK: ne proje ne ünite ne sözleşme nesnesi değiştirilir, her rakam
    yeni bir şema nesnesine yazılır.
    """
    contracts = await contracts_repository.list_subcontractor_contracts(
        session, [project.id], project_id=None, status_filter=None, q=None
    )
    grouped_payments = await payments_repository.list_cost_payments_by_projects(
        session, [project.id]
    )
    payments = grouped_payments.get(project.id, [])
    payments_by_contract: dict[uuid.UUID, list[SubcontractorProgressPayment]] = defaultdict(list)
    for payment in payments:
        payments_by_contract[payment.contract_id].append(payment)

    rows = _rows(contracts, payments_by_contract)
    total = _total(rows)
    # Harcanan (S1) tablonun ödenen+bekleyeni ile AYNI kaynaktan gelir: kart ile
    # tablo aynı sayıyı iki farklı yoldan hesaplarsa zamanla ayrışır.
    construction_spent = costs.money_total((total.paid, total.pending))
    units = await _project_units(session, project)
    sales = await _project_sales(session, project)
    return ProjectCostsResponse(
        project_id=project.id,
        project_type=project.project_type,
        breakdown=_breakdown(project, construction_spent),
        profit=_profit(project, units, sales, construction_spent),
        subcontractors=rows,
        subcontractor_total=total,
    )


async def get_project_costs(
    session: AsyncSession, actor: User, project_id: uuid.UUID
) -> ProjectCostsResponse:
    """Uç gövdesi. Kapsam: görünmeyen proje = var olmayan proje = 404 (modül notu)."""
    project = await service._visible_project(session, actor, project_id)
    return await build_project_costs(session, project)
