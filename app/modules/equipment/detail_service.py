"""Ekipman Detay ucunun iş kuralları (MK-4).

`rental_service.py` / `document_service.py` kardeşidir: `service` PAKETİNİN
DIŞINDA durur çünkü o paketin yüzeyi bir anlık görüntü bekçisiyle DONDURULMUŞTUR
(`tests/test_tbequip_servis_yuzeyi_anlik_goruntu.py`) ve MK-4 o bölmenin
kapsamına ait değildir. Kapsam kapısını (`visible_equipment`, K20) ve proje
kimliklerini oradan OKUR.

## Bu dosyada hangi karar yaşıyor

* **Türevin TEK hesaplandığı yer BURASI DEĞİL:** bakım penceresi
  `maintenance.py`de, kira parası `rental.py`de yaşar. Bu modül yalnız
  GİRDİLERİ toplar ve iki saf çekirdeği çağırır — formülün ikinci bir kopyası
  buraya yazılsaydı aynı sayı iki yerden türer ve ayrışırdı.
* **`as_of` PARAMETREDİR, `today()` çağrısı hesabın içinde DEĞİLDİR:** tahmini
  bakım tarihi bir "bugünden itibaren" büyüklüğüdür; sunucunun kendi gününü
  hesabın derinine gömseydik yanıt hangi güne göre üretildiğini SÖYLEYEMEZ ve
  test onu sabitleyemezdi. Varsayılan `timezone.today()`dır (TR takvimi).
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezone import today
from app.modules.equipment import maintenance, rental, rental_repository, repository, service
from app.modules.equipment.detail_schemas import (
    EquipmentDetailResponse,
    EquipmentMaintenanceBlock,
    EquipmentRentalTotals,
)
from app.modules.equipment.models import Equipment, RentalLineKind
from app.modules.equipment.schemas import EquipmentResponse
from app.modules.users.models import User

ZERO = Decimal("0")


def _maintenance_block(
    equipment: Equipment, *, window_hours: Decimal, as_of: date
) -> EquipmentMaintenanceBlock:
    """Bakım kartının dokuz alanı — hepsi `maintenance.py`den TÜRER."""
    kullanilan = maintenance.used_hours(
        hourmeter_hours=equipment.hourmeter_hours,
        last_service_hourmeter=equipment.last_service_hourmeter,
    )
    sonraki = maintenance.next_service_hourmeter(
        last_service_hourmeter=equipment.last_service_hourmeter,
        period=equipment.maintenance_period,
    )
    kalan = maintenance.remaining_hours(
        next_service_hourmeter=sonraki, hourmeter_hours=equipment.hourmeter_hours
    )
    return EquipmentMaintenanceBlock(
        period=equipment.maintenance_period,
        period_hours=maintenance.period_hours(equipment.maintenance_period),
        last_service_date=equipment.last_service_date,
        last_service_hourmeter=equipment.last_service_hourmeter,
        hourmeter_hours=equipment.hourmeter_hours,
        next_service_hourmeter=sonraki,
        used_hours=kullanilan,
        remaining_hours=kalan,
        usage_pct=maintenance.usage_pct(used_hours=kullanilan, period=equipment.maintenance_period),
        estimated_service_date=maintenance.estimated_service_date(
            remaining_hours=kalan,
            daily_rate=maintenance.daily_rate(window_hours=window_hours),
            as_of=as_of,
        ),
    )


async def _rental_totals(
    session: AsyncSession, project_ids: list[uuid.UUID], *, equipment_id: uuid.UUID
) -> EquipmentRentalTotals:
    """MD:82 `Kümülatif Ödenen` — ÖDENMİŞ hakedişlerin `rented` satırlarından.

    🔴 Tutar `rental.compute_our_amount` ile üretilir, SQL `SUM`u ile DEĞİL
    (MK-2 K4 "tek formül"): dönem dönüşümü ve `capacity_hours` snapshot'ı
    yalnız orada birlikte okunur. 🔴 `owned`/`breakdown` satırlar toplama
    GİRMEZ (MK-2 K3) — çift ödeme yapısal olarak imkânsız kalır.
    """
    satirlar = await rental_repository.paid_lines_for_equipment(
        session, project_ids, equipment_id=equipment_id
    )
    toplam = ZERO
    bilinmeyen = 0
    fatura_kimlikleri: set[uuid.UUID] = set()
    for line, rate_period in satirlar:
        fatura_kimlikleri.add(line.invoice_id)
        if line.line_kind is not RentalLineKind.rented:
            continue
        tutar = rental.compute_our_amount(
            worked_hours=line.worked_hours,
            line_rate_amount=line.rate_amount,
            equipment_rate_amount=None,
            rate_period=rate_period,
            monthly_capacity_hours=line.capacity_hours,
        )
        if tutar is None:
            bilinmeyen += 1
            continue
        toplam += tutar
    return EquipmentRentalTotals(
        cumulative_paid=toplam,
        cumulative_paid_unknown_count=bilinmeyen,
        paid_invoice_count=len(fatura_kimlikleri),
    )


async def equipment_detail(
    session: AsyncSession,
    actor: User,
    equipment_ref: uuid.UUID | str,
    *,
    as_of: date | None = None,
) -> EquipmentDetailResponse:
    """`GET /equipment/{equipment_id}/detail`.

    Kapsam kapısı ÖNCE geçilir (`visible_equipment`, K20): görünmeyen ekipmanın
    türevleri hesaplanmadan 404 döner, yoksa kullanıcı göremediği bir makinenin
    kira toplamını okurdu.
    """
    gun = as_of or today()
    equipment = await service.visible_equipment(session, actor, equipment_ref)
    # 🔴 Bundan SONRAKİ her türev `equipment.id` ile hesaplanır, `equipment_ref`
    # ile DEĞİL: `ref` bir slug olabilir ve `equipment_id=` bekleyen sorgulara
    # verilseydi Postgres `uuid = text` karşılaştırmasında patlardı. Kapıdan
    # geçen kaydın KİMLİĞİ tek meşru anahtardır.
    project_ids = await service._visible_project_ids(session, actor)
    # Pencere `gun` DÂHİL geriye doğru tam `ESTIMATE_WINDOW_DAYS` takvim günüdür.
    pencere_saati = await repository.worked_hours_in_window(
        session,
        project_ids,
        equipment_id=equipment.id,
        date_from=gun - timedelta(days=maintenance.ESTIMATE_WINDOW_DAYS - 1),
        date_to=gun,
    )
    return EquipmentDetailResponse(
        equipment=EquipmentResponse.model_validate(equipment),
        maintenance=_maintenance_block(equipment, window_hours=pencere_saati, as_of=gun),
        rental=await _rental_totals(session, project_ids, equipment_id=equipment.id),
        as_of=gun,
    )
