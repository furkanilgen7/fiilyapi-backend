"""E4 proje kartlarının maliyet/kâr türevleri (P10 T3, spec §3 "Proje kartları").

## Neden `service.py`dan ayrı

`service.py` oturum/yetki/yazma taşır ve zaten 560 satırdır; buradaki iş ise
"kart hangi rakamı basar" sorusunun TOPLU okuma tarafıdır. `cost_summary.py`
(T2 ucu) ile aynı ayrımın kart ikizidir: hesap formülleri BURADA YENİDEN
YAZILMAZ, hepsi `costs`tan çağrılır.

## Zarf kuralı (KIRICILIK YOK)

Yer tutucular ZARFIN İÇİNDE gerçeğe döner: alan tipi `MetricPlaceholder`
KALIR, yalnız içi dolar (`available=True` + `value`, `pending_module=None`).
Bunu tüketen UI CANLIDA (E4 kartları), bu yüzden kırıcı bir şema değişikliği
yapılmaz. Zarfı `projects.schemas.metric` kurar.

## Kapsam dışı bırakılanlar (icat yasağı)

`physical_progress` · `final_progress_payment` · `construction_progress` ·
`sold_amount` · `sales_ratio` · sayaçlar: P10 kapsamı dışı, yer tutucu KALIR.

## N+1 (spec §4)

Kart türevleri proje başına sorgu AÇMAZ; her iki toplu okuma da TEK `IN`
sorgusudur ve yalnız ilgili tipte hiç proje varsa koşar:

1. üniteler (`units.repository.list_units_for_projects`) — yalnız ünite gelirli
   tiplerde (kendi yatırım / kat karşılığı),
2. taşeron hakediş toplamları (`costs.subcontractor_totals_by_projects`) —
   yalnız HARCANAN alanı olan tipte proje varsa (`_SPENT_TYPES`: taahhüt kartının
   "Harcanan"ı E4 181/206/231/256 + kendi yatırım kartının "Toplam Maliyet"i
   E4 122, kullanıcı kararı 2026-08-09).
"""

# Neden `costs`/`units` importları FONKSİYON İÇİNDE
#
# `projects.service` bu modülü modül düzeyinde import eder; buradan
# `projects.costs` → `units.summary` → `units.schemas` → `units.guards` →
# `projects.service` çemberi kapanır (guards görünürlük süzgecini oradan alır).
# Çemberi kırmanın en az müdahaleli yolu, yaprak olmayan iki bağı gecikmeli
# yapmaktır — `service._write_inline_sites`in `sites.service` importunda kullandığı
# desenin aynısı. Bu modülün modül düzeyi bağları yalnız YAPRAKLARDIR
# (`projects.models` · `projects.unit_sides` — ikincisi de yalnız `units.models`e
# bağlı bir yapraktır, çember açmaz).

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects import unit_sides
from app.modules.projects.models import Project, ProjectType

if TYPE_CHECKING:  # yalnız tip anotasyonu için — çalışma zamanında import YOK
    from app.modules.projects.costs import SubcontractorCostTotals
    from app.modules.units.models import Unit

# Gelir tarafı ÜNİTEDEN türeyen tipler (spec §2) — `cost_summary._UNIT_REVENUE_TYPES`
# ile aynı küme; taahhütte kartın kâr alanı YOKTUR, ünite de çekilmez.
_UNIT_REVENUE_TYPES = (ProjectType.kendi_yatirim, ProjectType.kat_karsiligi)

# HARCANAN rakamına ihtiyacı olan tipler: taahhüt kartı "Harcanan" (E4 181) basar,
# kendi yatırım kartı ise "Toplam Maliyet"i (E4 122) harcanandan üretir (kullanıcı
# kararı 2026-08-09). Kat karşılığı kartı YALNIZ bütçe basar (KK 135) — o tipte
# hakediş tablosuna hiç dokunulmaz (ünite süzgecinin aynı gerekçesi).
_SPENT_TYPES = (ProjectType.taahhut, ProjectType.kendi_yatirim)

# Hakedişi hiç olmayan projede harcanan 0'dır ("henüz harcanmadı"), bilinmeyen değil.
_ZERO = Decimal("0.00")


@dataclass(frozen=True)
class ProjectCardCosts:
    """Bir projenin kart rakamları. Hepsi `Decimal | None`: `None` = "kaynak yok"
    ve zarf boş kalır (`metric` fabrikası bunu bilir).

    * `total_cost` → E4 122 "Toplam Maliyet" (kendi yatırım kartı) = **HARCANAN**
      (arsa + taşeron `approved`+`paid` BRÜT), `costs.total_spent`. KULLANICI
      KARARI 2026-08-09: kanıt KY hero ikilisidir ("Toplam Maliyet ₺20,3M /
      ₺29,8M bütçe" — iki sayı FARKLI şeylerdir). Kaynağı canlı olduğu için değer
      daima bilinir, zarf DOLU döner (`our_share_value` gerekçesi).
    * `construction_cost` → KK 135 "İnşaat Maliyeti" (kat karşılığı kartı) =
      **BÜTÇE** (`costs.entered_budget_cost`) ve kâr projeksiyonunun TABANIDIR
      (spec §2: 30,4 − 17,6 = 12,8). Harcanana DÖNMEZ.
    * `our_share_value` → KK 121 "BİZİM PAY" ünite değer toplamı.
    * `spent` → E4 181/206/231/256 "Harcanan" (taahhüt kartı): taşeron
      hakedişlerinin `approved`+`paid` BRÜT toplamı (spec §2, S1/S2). Kaynak modül
      CANLI olduğu için hakedişi olmayan taahhüt projesinde `0.00` GERÇEK cevaptır
      — bu alan taahhüt projelerinde asla `None` dönmez (`our_share_value` gerekçesi).

    **`total_cost` ile `construction_cost` ARTIK AYRI ALANLARDIR:** eskiden
    `construction_cost` bir property olarak `total_cost`u döndürüyordu; iki alan
    farklı şeyler ölçmeye başladığı için o bağ KOPARILDI. Her kart yalnız kendi
    alanını doldurur, diğeri `None` kalır (kart o alanı hiç basmaz).

    Kartın "Toplam Maliyet = harcanan" + "Tahmini Kâr = bütçe bazlı" karışımı
    MOCKUP'IN KENDİ OKUMASIDIR (E4 122 harcananı, 124 bütçe bazlı kârı basar);
    backend iki tabanı da aynı kartta taşır.

    ## Para OLMAYAN iki alan: taraf ünite sayaçları

    `our_unit_count` / `owner_unit_count` → E4 148-149 paylaşım şeridi ("Biz %55 ·
    23 ünite" / "Arsa %45 · 19"), düz `owner_side` sayımı. Bunlar `Decimal`
    değil `int`tir ve `None` hâli DİĞER alanlardan farklı okunur:

    * **kat karşılığı projede `None` DÖNMEZ** — ünitesi olmayan projede `0`
      GERÇEK cevaptır (`units` modülü canlıdır), bilinmeyen değil;
    * **başka tiplerde `None`** — o tipin kartında böyle bir alan zaten YOKTUR,
      yani "sıfır ünite" değil "soru sorulmadı" demektir.

    Sayaçlar buradan taşınır çünkü üniteler kart okumasında ZATEN yüklüdür
    (`by_projects`); ayrı bir `SELECT count(*)` N+1 kuralını (modül notu §4)
    kırardı.
    """

    total_cost: Decimal | None = None
    construction_cost: Decimal | None = None
    our_share_value: Decimal | None = None
    profit: Decimal | None = None
    margin_pct: Decimal | None = None
    spent: Decimal | None = None
    our_unit_count: int | None = None
    owner_unit_count: int | None = None


EMPTY = ProjectCardCosts()


def _for_project(
    project: Project, units: "Sequence[Unit]", totals: "SubcontractorCostTotals | None"
) -> ProjectCardCosts:
    """Tek projenin kart rakamları — SORGU KOŞMAZ (üniteler/toplamlar hazır gelir).

    Kendi yatırımda `total_cost` HARCANANDIR (`costs.total_spent`), kat
    karşılığında `construction_cost` BÜTÇEDİR — iki alanın ayrımı için bkz.
    `ProjectCardCosts`. Kâr/marj İKİ TİPTE DE bütçe tabanlıdır (`card_projection`).

    Taraf sayaçları AYNI `units` listesinden türer (ek sorgu YOK) ve yalnız kat
    karşılığında doldurulur — paylaşım şeridi (E4 148-149) yalnız o kartta vardır.
    """
    from app.modules.projects import costs

    projection = costs.card_projection(project, units)
    spent = _ZERO if totals is None else totals.spent
    is_investment = project.project_type is ProjectType.kendi_yatirim
    is_land_share = project.project_type is ProjectType.kat_karsiligi
    sides = unit_sides.partition(units)
    return ProjectCardCosts(
        total_cost=costs.total_spent(project, spent) if is_investment else None,
        construction_cost=None if is_investment else projection.cost,
        # Pay değeri ÜNİTEDEN türer ve o modül CANLIDIR: ünitesi olmayan projede
        # `0.00` gerçek bir cevaptır ("henüz pay ünitesi yok"), bilinmeyen değil.
        our_share_value=costs.our_share_value(units, project.project_type),
        profit=projection.profit,
        margin_pct=projection.margin_pct,
        # `0` GERÇEK cevaptır (aynı gerekçe); alanın hiç olmadığı tipte `None`.
        our_unit_count=len(sides.ours) if is_land_share else None,
        owner_unit_count=len(sides.owner) if is_land_share else None,
    )


def _for_contracting(totals: "SubcontractorCostTotals | None") -> ProjectCardCosts:
    """Taahhüt kartı: YALNIZ `spent` (E4 181/206/231/256) — kâr/marj alanı yoktur.

    Toplu okumada bulunmayan proje `EMPTY` döner; toplu okuma her istenen kimliği
    döndürdüğü için bu yalnız "hiç sorulmadı" hâlidir (savunma dalı).
    """
    return EMPTY if totals is None else ProjectCardCosts(spent=totals.spent)


async def by_projects(
    session: AsyncSession, projects: Sequence[Project]
) -> dict[uuid.UUID, ProjectCardCosts]:
    """Liste/detay uçlarının TOPLU okuması (modül notundaki N+1 kuralı).

    İstenen HER proje kimliği yanıtta bulunur: kart alanı olmayan tip `EMPTY` ile
    döner, böylece çağıran eksik anahtar tuzağına düşmez.
    """
    from app.modules.projects import costs
    from app.modules.units import repository as units_repository

    unit_projects = [p for p in projects if p.project_type in _UNIT_REVENUE_TYPES]
    units_by_project = (
        await units_repository.list_units_for_projects(session, [p.id for p in unit_projects])
        if unit_projects
        else {}
    )
    spent_ids = [p.id for p in projects if p.project_type in _SPENT_TYPES]
    spent_by_project = (
        await costs.subcontractor_totals_by_projects(session, spent_ids) if spent_ids else {}
    )
    return {
        project.id: _for_project(
            project, units_by_project.get(project.id, []), spent_by_project.get(project.id)
        )
        if project.project_type in _UNIT_REVENUE_TYPES
        else _for_contracting(spent_by_project.get(project.id))
        for project in projects
    }
