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

* **Taahhüt kartının `spent` alanı** BAĞLANMADI. E4 180-181 "Harcanan" basar ve
  spec §2 taahhüt harcananını taşeron hakedişlerinden tanımlar, ancak alanın
  `pending_module`ı `progress_payments`tır (İŞVEREN hakedişi) ve görev emrinin
  bağlanacak alan listesinde `spent` YOKTUR. İki okuma arasında karar kullanıcıya
  aittir — yanlış kaynağa bağlamak kartta sessizce yanlış rakam basmak olurdu.
* `physical_progress` · `final_progress_payment` · `construction_progress` ·
  `sold_amount` · `sales_ratio` · sayaçlar: P10 kapsamı dışı, yer tutucu KALIR.

## N+1 (spec §4)

Kart türevleri proje başına sorgu AÇMAZ: ünite tarafı TEK `IN` sorgusudur
(`units.repository.list_units_for_projects`) ve yalnız ünite gelirli tiplerde
(kendi yatırım / kat karşılığı) hiç proje varsa koşar. Taşeron hakedişlerine
liste yolunda DOKUNULMAZ, çünkü bağlanan hiçbir kart alanı ona dayanmıyor.
"""

# Neden `costs`/`units` importları FONKSİYON İÇİNDE
#
# `projects.service` bu modülü modül düzeyinde import eder; buradan
# `projects.costs` → `units.summary` → `units.schemas` → `units.guards` →
# `projects.service` çemberi kapanır (guards görünürlük süzgecini oradan alır).
# Çemberi kırmanın en az müdahaleli yolu, yaprak olmayan iki bağı gecikmeli
# yapmaktır — `service._write_inline_sites`in `sites.service` importunda kullandığı
# desenin aynısı. Bu modülün modül düzeyi bağları yalnız YAPRAKLARDIR
# (`projects.models`).

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.models import Project, ProjectType

if TYPE_CHECKING:  # yalnız tip anotasyonu için — çalışma zamanında import YOK
    from app.modules.units.models import Unit

# Gelir tarafı ÜNİTEDEN türeyen tipler (spec §2) — `cost_summary._UNIT_REVENUE_TYPES`
# ile aynı küme; taahhütte kartın kâr alanı YOKTUR, ünite de çekilmez.
_UNIT_REVENUE_TYPES = (ProjectType.kendi_yatirim, ProjectType.kat_karsiligi)


@dataclass(frozen=True)
class ProjectCardCosts:
    """Bir projenin kart rakamları. Hepsi `Decimal | None`: `None` = "kaynak yok"
    ve zarf boş kalır (`metric` fabrikası bunu bilir).

    * `total_cost` → KY 182 "Toplam Maliyet" (kendi yatırım kartı).
    * `construction_cost` → KK 135 "İnşaat Maliyeti" (kat karşılığı kartı). İkisi
      de `entered_budget_cost`tur: kat karşılığında arsa tanım gereği 0 olduğu
      için toplam bütçe maliyeti ZATEN inşaat bütçesidir (`costs.total_budget_cost`).
    * `our_share_value` → KK 121 "BİZİM PAY" ünite değer toplamı.
    """

    total_cost: Decimal | None = None
    our_share_value: Decimal | None = None
    profit: Decimal | None = None
    margin_pct: Decimal | None = None

    @property
    def construction_cost(self) -> Decimal | None:
        """KK 135 ile KY 182 AYNI rakamdır (arsa 0 kuralı hesaba gömülü) —
        ikinci bir alan tutmak, iki kartın zamanla ayrışması demekti."""
        return self.total_cost


EMPTY = ProjectCardCosts()


def _for_project(project: Project, units: "Sequence[Unit]") -> ProjectCardCosts:
    """Tek projenin kart rakamları — SORGU KOŞMAZ (üniteler hazır gelir)."""
    from app.modules.projects import costs

    projection = costs.card_projection(project, units)
    return ProjectCardCosts(
        total_cost=projection.cost,
        # Pay değeri ÜNİTEDEN türer ve o modül CANLIDIR: ünitesi olmayan projede
        # `0.00` gerçek bir cevaptır ("henüz pay ünitesi yok"), bilinmeyen değil.
        our_share_value=costs.our_share_value(units, project.project_type),
        profit=projection.profit,
        margin_pct=projection.margin_pct,
    )


async def by_projects(
    session: AsyncSession, projects: Sequence[Project]
) -> dict[uuid.UUID, ProjectCardCosts]:
    """Liste/detay uçlarının TEK toplu okuması (modül notundaki N+1 kuralı).

    İstenen HER proje kimliği yanıtta bulunur: kart alanı olmayan tip (taahhüt)
    `EMPTY` ile döner, böylece çağıran eksik anahtar tuzağına düşmez.
    """
    from app.modules.units import repository as units_repository

    unit_projects = [p for p in projects if p.project_type in _UNIT_REVENUE_TYPES]
    units_by_project = (
        await units_repository.list_units_for_projects(session, [p.id for p in unit_projects])
        if unit_projects
        else {}
    )
    return {
        project.id: _for_project(project, units_by_project.get(project.id, []))
        if project.project_type in _UNIT_REVENUE_TYPES
        else EMPTY
        for project in projects
    }
