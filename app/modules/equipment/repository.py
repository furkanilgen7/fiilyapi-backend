"""Ekipman çekirdeği veri erişimi (T1 iskeleti) — yalnız SQL, yetki/kapsam KARARI yok.

Kapsam kararı (`visible_projects`, K20) bu katmanda DEĞİL `service.py`dedir
(`inventory`/`documents` repository deseninin kardeşi); buraya yalnız çözülmüş
proje/şantiye kimlikleri gelir.

T1'de yalnız tekil okuma vardır: liste süzgeçleri, sayfalama ve türev toplamlar
(K15) uçlarıyla birlikte T3-T5'te açılır.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.equipment.models import Equipment


async def get_equipment(session: AsyncSession, equipment_id: uuid.UUID) -> Equipment | None:
    """Tekil ekipman — pasifleri DE getirir.

    `is_active=false` süzgeci BURADA UYGULANMAZ: pasif bir ekipmanın kartı
    okunabilmelidir (geçmiş maliyeti hâlâ ona bağlıdır), aksi halde kayıtları
    olan pasif bir makine sistemde erişilemez hale gelirdi. Listenin varsayılan
    süzgeci uç katmanının kararıdır.
    """
    return await session.scalar(select(Equipment).where(Equipment.id == equipment_id))


async def get_equipment_for_update(
    session: AsyncSession, equipment_id: uuid.UUID
) -> Equipment | None:
    """K12 EŞİK = KİLİT kanonu: günlük 24 saat tavanı denetlenmeden ÖNCE
    `equipment` satırı kilitlenir.

    Kilitsiz bir eşik denetimi iki eşzamanlı çalışma kaydında HER İKİSİNİ de
    geçirir (İK-2 K2 / İK-3 dersi) ve tek istekli test bunu GÖRMEZ. Kilit sırası
    tüm uçlarda SABİTTİR: önce `equipment`, sonra kayıt satırları.
    """
    return await session.scalar(
        select(Equipment).where(Equipment.id == equipment_id).with_for_update()
    )
