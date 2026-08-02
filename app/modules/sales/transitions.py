"""Satış kaydının durum makinesi — P8 T5 (spec §3, §4; mockup S55-56, S166, S188).

## Tek tablo, tek kapı

Geçerli geçişler AŞAĞIDAKİ TEK sözlüktedir (`TRANSITIONS`); uçlar kendi
`if status == …` kontrollerini YAZMAZ. Tabloda olmayan her çift 409
`INVALID_STATUS_TRANSITION`'dır — "tanımlı olanı say, gerisini reddet"
yaklaşımıyla yeni bir durum eklendiğinde varsayılan davranış REDDETMEKTİR.
Desen `progress_payments/transitions.py`ten alınmıştır ve YENİDEN İCAT EDİLMEZ.

`deed_transferred` ve `cancelled` TERMİNALDİR: tabloda KAYNAK olarak geçmezler.
Tapusu devredilmiş bir satış geri alınamaz (devir tapu sicilinde gerçekleşmiş
bir olaydır, bir onay adımı değil); iptal edilmiş kayıt da diriltilmez —
vazgeçilen alıcı yeniden gelirse YENİ satış kaydı açılır, çünkü iptal ünitenin
vitrinini serbest bırakmıştır ve arada başkası satın almış olabilir.

## Ünite senkronu KOPYALANMAZ

Her geçiş T3'ün `service.sync_unit_sales_status` yardımcısını çağırır. Harita
(`active`→`sold`, `deed_transferred`→`sold` KALIR, `cancelled`→`listed`) orada
TEK KOPYADIR; buraya kopyalansaydı iki taraf zamanla ayrışır ve ayrışan taraf
üniteyi yanlış vitrinde bırakırdı.

## İptal gerekçesi neden DENETİM GÜNLÜĞÜNE yazılır

`unit_sales`te iptal gerekçesi KOLONU YOKTUR (T1) ve bu dilimde AÇILMAZ
(migration üretilmez). Gerekçe kaydın bir NİTELİĞİ değil bir OLAYIN
açıklamasıdır: "neden, ne zaman, kim tarafından" üçlüsünü zaten denetim
günlüğü taşır (`progress_payments`in `reject` gerekçesiyle aynı karar, K12).

## Yeni `AuditAction` neden AÇILMADI

`AuditAction` bir PostgreSQL enum tipidir; yeni değer MIGRATION gerektirir ve
bu dilimde migration üretilmemektedir. Üç geçiş de mevcut kaydın durumunu
DEĞİŞTİRİR → `update`. Denetim ekranı aksiyona değil METNE göre okunur ve
`messages.py`deki üç ayrı Türkçe metin olayı tam olarak adlandırır. `approve`
bu modülde KULLANILMAZ: o değer hakediş onay iş akışına aittir, `activate` ise
bir onay değil ticari bir durum değişikliğidir.
"""

import enum
import uuid
from typing import NamedTuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError
from app.modules.audit import messages
from app.modules.projects.models import Project
from app.modules.sales import guards, service
from app.modules.sales.models import UnitSaleStatus
from app.modules.sales.schemas import UnitSaleResponse
from app.modules.units.models import Unit
from app.modules.users.models import User

__all__ = ["TRANSITIONS", "SaleAction", "perform"]


class SaleAction(str, enum.Enum):
    """Geçiş işlemleri — değerler UÇ YOLLARIYLA birebir aynıdır (`…/transfer-deed`),

    böylece router ile tablo arasında ikinci bir eşleme sözlüğü gerekmez
    (`progress_payments.PaymentAction` deseni).
    """

    activate = "activate"
    transfer_deed = "transfer-deed"
    cancel = "cancel"


#: Spec §4 tablosu — TEK KOPYA. Burada olmayan çift 409'dur.
TRANSITIONS: dict[tuple[UnitSaleStatus, SaleAction], UnitSaleStatus] = {
    # S56 "Rezerve" → S55 "Satılan": kapora sözleşmeye dönüştü.
    (UnitSaleStatus.reservation, SaleAction.activate): UnitSaleStatus.active,
    # S166 "Tapu Devredildi".
    (UnitSaleStatus.active, SaleAction.transfer_deed): UnitSaleStatus.deed_transferred,
    # İptal İKİ durumdan da gelinebilir; `deed_transferred`ten GELİNEMEZ.
    (UnitSaleStatus.reservation, SaleAction.cancel): UnitSaleStatus.cancelled,
    (UnitSaleStatus.active, SaleAction.cancel): UnitSaleStatus.cancelled,
}

#: Denetim metni üreticileri — aksiyon başına AYRI metin (yukarıdaki gerekçe).
_MESSAGE_BY_ACTION = {
    SaleAction.activate: messages.sale_activated,
    SaleAction.transfer_deed: messages.sale_deed_transferred,
}


class TransitionResult(NamedTuple):
    response: UnitSaleResponse
    detail: str


def _detail(
    action: SaleAction, project: Project, response: UnitSaleResponse, reason: str | None
) -> str:
    if action is SaleAction.cancel:
        # `reason` yalnız `cancel`de doludur ve şemada ZORUNLUDUR (422); yine de
        # tip daraltması için kontrol edilir — sessiz bir düşüş değildir.
        return messages.sale_cancelled(
            project.name, response.unit_label, response.customer_name, reason or ""
        )
    return _MESSAGE_BY_ACTION[action](project.name, response.unit_label, response.customer_name)


async def perform(
    session: AsyncSession,
    actor: User,
    sale_id: uuid.UUID,
    action: SaleAction,
    *,
    reason: str | None = None,
) -> TransitionResult:
    """Tek geçiş yolu. Sıra: kapsam+kilit → tablo → durum → ünite senkronu → metin.

    Kapsam süzgeci (404) tablo kontrolünden ÖNCE koşar: görünmeyen bir satışın
    durumu hakkında 409 ile bilgi sızdırılmaz (spec §6).

    Ünite `session.get` ile okunur: `unit_id` NOT NULL + FK olduğu için satır
    kesin vardır ve aynı transaction'da zaten yüklüyse kimlik haritasından döner.
    """
    sale, project = await guards.visible_sale_locked(session, actor, sale_id)

    new_status = TRANSITIONS.get((sale.status, action))
    if new_status is None:
        raise ConflictError(guards.INVALID_STATUS_TRANSITION)

    sale.status = new_status
    await session.flush()

    unit = await session.get(Unit, sale.unit_id)
    if unit is not None:  # pragma: no branch - FK garantisi
        # T3'ün TEK OTORİTESİ; harita burada KOPYALANMAZ (modül notu).
        await service.sync_unit_sales_status(session, unit, sale.status)

    response = await service.response_for(session, sale.id)
    return TransitionResult(response, _detail(action, project, response, reason))
