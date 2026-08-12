"""ST ↔ SA bağının TEK kapısı (SA spec §3, §7 S4) — T4.

`inventory` paketinin satınalmadan ihtiyaç duyduğu HER ŞEY bu modüldedir ve
başka hiçbir `procurement` modülü oradan çağrılmaz.

## İMPORT YÖNÜ — çember NEDEN kurulmuyor

`procurement → inventory` yönü T2'de açıldı ve AÇIK KALIR (`repository` bakiye
ve malzeme kartı okur). Ters yön MODÜL DÜZEYİNDE açılsaydı iki paket birbirini
import eder, içe aktarma sırası bir gün patlar ve P10'un `cost_cards` çemberi
tekrarlanırdı.

Çözüm: `inventory.service` bu modülü **fonksiyon gövdesinden, gecikmeli**
import eder. Böylece modül grafiği tek yönlü kalır (import zamanında
`inventory → procurement` kenarı YOKTUR) ve bağ yalnızca ÇAĞRI ANINDA kurulur.

Bir kayıt/registry (procurement'ın kendini `inventory`ye tanıtması) tercih
EDİLMEDİ: kayıt yapılmazsa zincir SESSİZCE çalışmaz — bir teslim damgasının
hiç düşmediği, hiçbir testin bağırmadığı bir sistem en kötü sonuçtur. Gecikmeli
import ise ya çalışır ya patlar.

Yön iki bekçi testiyle kilitlidir (`test_stock_entry_delivery_chain`):
`inventory/*.py` modül düzeyinde `procurement` import ETMEZ ·
`procurement/*.py` `inventory.service` import ETMEZ.

## Neden İKİ fonksiyon (çöz + damgala)

`resolve_order` YAZIMDAN ÖNCE koşar ve görünmeyen/olmayan siparişte **404**
atar; `stamp_delivery` yazımdan SONRA damgayı basar. Tek fonksiyon olsaydı ya
doğrulama geç kalır (reddedilen istekten geriye yarım bir hareket kalırdı) ya
da damga erken düşerdi (hareket yazılamasa bile sipariş teslim görünürdü).
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.procurement import repository, service, transitions
from app.modules.procurement.models import (
    PurchaseOrder,
    PurchaseOrderStatus,
    PurchaseRequestStatus,
)
from app.modules.users.models import User

__all__ = ["pending_order_count", "resolve_order", "stamp_delivery"]


async def resolve_order(session: AsyncSession, actor: User, order_id: uuid.UUID) -> PurchaseOrder:
    """Stok girişinin gövdesindeki sipariş referansını ÇÖZER.

    Görünmeyen ya da hiç olmayan sipariş **404**tür ve iki durum BİREBİR AYNI
    gövdeyi alır (ST §4b kanonu). Kapsam kararı kopyalanmaz: satınalmanın tek
    kapısı `service.visible_order`dır.
    """
    return await service.visible_order(session, actor, order_id)


async def stamp_delivery(session: AsyncSession, order: PurchaseOrder) -> None:
    """Siparişi (ve varsa bağlı talebi) `delivered` damgalar — §7 S4.

    **İdempotenttir:** sipariş zaten `delivered` ise hiçbir şey yapılmaz ve
    HATA ATILMAZ. Gerekçe: stok hareketi bir OLGUDUR; kısmi teslim ayrımı
    olmadığı için (bilinen sınır) ikinci parti tam olarak bu yoldan gelir ve
    409 verilseydi gerçekten gelen mal kayda GİREMEZDİ.

    Talep tarafı ayrıca kontrol edilir: `request_id` NULL olabilir (SIP 35
    doğrudan siparişi) ve talep başka bir durumda olsa bile damga zorlanmaz —
    tablo ne diyorsa o.
    """
    if (order.status, PurchaseOrderStatus.delivered) not in transitions.ORDER_DELIVERY_TRANSITIONS:
        return

    order.status = PurchaseOrderStatus.delivered
    if order.request_id is not None:
        request = await repository.get_request(session, order.request_id)
        if (
            request is not None
            and (request.status, PurchaseRequestStatus.delivered)
            in transitions.REQUEST_DELIVERY_TRANSITIONS
        ):
            request.status = PurchaseRequestStatus.delivered
    await session.flush()


async def pending_order_count(session: AsyncSession, project_ids: list[uuid.UUID]) -> int:
    """E3 81 "Bekleyen Sipariş" — `approved` + `in_transit` sipariş sayısı.

    Küme `transitions.PENDING_ORDER_STATUSES`tir ve SATINALMA ÖZETİYLE aynı
    kaynaktır: iki ekran ("Bekleyen Sipariş" / SIP 39 "Aktif Siparişler") aynı
    sayıyı göstermek zorundadır.

    Kapsam ÇAĞIRANDAN gelir (görünen proje kimlikleri) — bu modül yetki kararı
    VERMEZ.
    """
    sayimlar = await repository.order_status_counts(session, project_ids, project_id=None)
    return sum(sayimlar.get(durum, 0) for durum in transitions.PENDING_ORDER_STATUSES)
