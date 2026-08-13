"""Ekipman çekirdeği iş kuralları (T1 iskeleti) — MK-1 spec §2, §4, §6.

İKİ KATMANLI koruma (`inventory`/`documents` servis deseninin birebiri):
`equipment` izni router'da YETKİYİ verir, bu modül `visible_projects` ile
KAPSAMI belirler.

## Kapsam kuralı (K20) — `personnel`/`payroll` İSTİSNASI BURADA GEÇERSİZ

Ekipman bir şantiyeye atanır ve maliyeti bir projeye yansır, dolayısıyla
`visible_projects` süzgeci UYGULANIR. **Tek istisna:** `site_id IS NULL` olan
(depodaki) ekipman hiçbir projeye ait değildir ve `equipment` izni olan HERKESE
görünür — ST'nin merkez depo (`warehouses.site_id IS NULL`) kuralının kardeşi.
Çalışma ve yakıt kayıtları KENDİ `site_id`leriyle süzülür (K9), ekipmanın
bugünkü atamasıyla değil.

## Bu dosyada NE YOK

Yazma uçlarının kuralları (K2 koşullu zorunluluk · K11 `hours` sunucu hesabı ·
K12 kilitli 24 saat tavanı) ve türev hesaplar (K15 satırlardan toplam · K16
fail-closed `null` · K17 sapma rozeti · K18 maliyet formülü) T3-T5'indir.
K17/K18 kendi TEK dosyalarında (`consumption.py` / `cost.py`) duracaktır —
eşikler ve `DAILY_HOURS` sabiti iki yere kopyalanmaz.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.modules.equipment import repository
from app.modules.equipment.models import Equipment

PERMISSION_MODULE = "equipment"


async def get_equipment_or_404(session: AsyncSession, equipment_id: uuid.UUID) -> Equipment:
    """Kapsam dışı ya da olmayan kayıt AYNI cevabı verir: 404 (spec §4).

    Kapsam denetimi (K20) çağıran uçtadır ve 403 DEĞİL 404 üretir — "görmediğin
    kaydın varlığını da öğrenme" kuralı (IDOR deseni, P2).
    """
    equipment = await repository.get_equipment(session, equipment_id)
    if equipment is None:
        raise NotFoundError("Ekipman bulunamadı.")
    return equipment
