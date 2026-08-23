"""Ekipman çekirdeği iş kuralları (MK-1 spec §2, §4, §6) — paket CEPHESİ.

İKİ KATMANLI koruma (`inventory`/`documents` servis deseninin birebiri):
`equipment` izni router'da YETKİYİ verir, bu paket `visible_projects` ile
KAPSAMI belirler.

## 🔴 Paket yapısı (TB-EQUIP) — davranış DEĞİŞMEDİ

Dosya 962 satırdaydı (tavan 800). Dosyanın KENDİ bölüm başlıklarına
(`# --- Çalışma kaydı`, `# --- Çalışma özeti`, `# --- Yakıt kaydı`,
`# --- Yakıt özeti`) göre bölündü; hiçbir uç, SQL, yanıt gövdesi, hata metni,
izin kapısı ya da kilit sırası değişmedi. Dış imza KORUNDU: eski `service.py`nin
TÜM modül düzeyi adları (özel `_` adları DÂHİL) buradan aynen okunabilir —
`router.py`, `rental_service.py`, `document_service.py` ve testler onlara
`service.X` biçimiyle ULAŞIYORDU. Çağıran tarafta tek satır değişmedi.

🔴 Özel adların re-export'u ZORUNLUDUR, süs değil: `rental_service.py`
`service._is_visible_site` ve `service._visible_project_ids` çağırıyor
(ölçüldü: 5 çağrı). Yalnız "genel" adlar ihraç edilseydi kira modülü
İÇE AKTARMADA değil İLK İSTEKTE patlardı.

Katmanlar (ok yönü = bağımlılık, çember YOK):

    periods  ←  core  ←  work_logs
       ↑         ↑   ←  work_summary
       └─────────┴───←  fuel_logs · fuel_summary

* `periods.py`      — ay/hafta sınırlarının TEK tanımı (DB'siz yaprak)
* `core.py`         — 🔴 KAPSAM kapısı (K20) · kartoteks CRUD (K2) · M1 KPI (K15/K16/K18)
* `work_logs.py`    — M3 kaydı: K11 sunucu saati · 🔴 K12 EŞİK = KİLİT · K9 damgası
* `work_summary.py` — M3 tablosu + haftalık kovalar (K15/K7/K16)
* `fuel_logs.py`    — M4 kaydı: K13/K14 · K9'un yakıttaki eşi
* `fuel_summary.py` — M4 özeti: K15/K16/K17/K19

**K16/K17/K18 BU PAKETTE DEĞİLDİR:** fail-closed `null`, sapma rozeti ve maliyet
formülü kendi TEK dosyalarındadır (`consumption.py` / `cost.py`) ve bu paket
onlardan yalnız OKUR — eşikler ile `DAILY_HOURS` sabiti iki yere kopyalanmaz.

`X as X` biçimi bilinçlidir: açık yeniden-ihraç, `noqa` olmadan F401'i susturur
ve `__all__`e girmeyen özel adları da kapsar.
"""

from app.modules.equipment.service.core import (
    EQUIPMENT_MISSING as EQUIPMENT_MISSING,
)
from app.modules.equipment.service.core import (
    OPERATOR_MISSING as OPERATOR_MISSING,
)
from app.modules.equipment.service.core import (
    PERMISSION_MODULE as PERMISSION_MODULE,
)
from app.modules.equipment.service.core import (
    PURCHASE_AMOUNT_REQUIRED as PURCHASE_AMOUNT_REQUIRED,
)
from app.modules.equipment.service.core import (
    SITE_MISSING as SITE_MISSING,
)
from app.modules.equipment.service.core import (
    SUPPLIER_MISSING as SUPPLIER_MISSING,
)
from app.modules.equipment.service.core import (
    EquipmentSummary as EquipmentSummary,
)
from app.modules.equipment.service.core import (
    _assert_purchase_amount as _assert_purchase_amount,
)
from app.modules.equipment.service.core import (
    _assert_references as _assert_references,
)
from app.modules.equipment.service.core import (
    _is_visible_site as _is_visible_site,
)
from app.modules.equipment.service.core import (
    _visible_project_ids as _visible_project_ids,
)
from app.modules.equipment.service.core import (
    create_equipment as create_equipment,
)
from app.modules.equipment.service.core import (
    get_equipment_or_404 as get_equipment_or_404,
)
from app.modules.equipment.service.core import (
    list_equipment as list_equipment,
)
from app.modules.equipment.service.core import (
    summarize as summarize,
)
from app.modules.equipment.service.core import (
    update_equipment as update_equipment,
)
from app.modules.equipment.service.core import (
    visible_equipment as visible_equipment,
)
from app.modules.equipment.service.fuel_logs import (
    FUEL_LOG_MISSING as FUEL_LOG_MISSING,
)
from app.modules.equipment.service.fuel_logs import (
    create_fuel_log as create_fuel_log,
)
from app.modules.equipment.service.fuel_logs import (
    delete_fuel_log as delete_fuel_log,
)
from app.modules.equipment.service.fuel_logs import (
    list_fuel_logs as list_fuel_logs,
)
from app.modules.equipment.service.fuel_logs import (
    update_fuel_log as update_fuel_log,
)
from app.modules.equipment.service.fuel_logs import (
    visible_fuel_log as visible_fuel_log,
)
from app.modules.equipment.service.fuel_summary import (
    _UNIT_PRICE_QUANTUM as _UNIT_PRICE_QUANTUM,
)
from app.modules.equipment.service.fuel_summary import (
    _quantize_unit_price as _quantize_unit_price,
)
from app.modules.equipment.service.fuel_summary import (
    fuel_summary as fuel_summary,
)
from app.modules.equipment.service.periods import (
    _monday as _monday,
)
from app.modules.equipment.service.periods import (
    _month_bounds as _month_bounds,
)
from app.modules.equipment.service.periods import (
    month_bounds as month_bounds,
)
from app.modules.equipment.service.work_logs import (
    _HOURS_INPUTS as _HOURS_INPUTS,
)
from app.modules.equipment.service.work_logs import (
    _HOURS_QUANTUM as _HOURS_QUANTUM,
)
from app.modules.equipment.service.work_logs import (
    _SECONDS_PER_HOUR as _SECONDS_PER_HOUR,
)
from app.modules.equipment.service.work_logs import (
    DAILY_HOURS_EXCEEDED as DAILY_HOURS_EXCEEDED,
)
from app.modules.equipment.service.work_logs import (
    HOURS_IS_SERVER_COMPUTED as HOURS_IS_SERVER_COMPUTED,
)
from app.modules.equipment.service.work_logs import (
    HOURS_REQUIRED as HOURS_REQUIRED,
)
from app.modules.equipment.service.work_logs import (
    MAX_DAILY_HOURS as MAX_DAILY_HOURS,
)
from app.modules.equipment.service.work_logs import (
    OVERNIGHT_NOT_SUPPORTED as OVERNIGHT_NOT_SUPPORTED,
)
from app.modules.equipment.service.work_logs import (
    TIME_PAIR_REQUIRED as TIME_PAIR_REQUIRED,
)
from app.modules.equipment.service.work_logs import (
    WORK_LOG_MISSING as WORK_LOG_MISSING,
)
from app.modules.equipment.service.work_logs import (
    _assert_daily_cap as _assert_daily_cap,
)
from app.modules.equipment.service.work_logs import (
    _lock_equipment as _lock_equipment,
)
from app.modules.equipment.service.work_logs import (
    _resolve_hours as _resolve_hours,
)
from app.modules.equipment.service.work_logs import (
    create_work_log as create_work_log,
)
from app.modules.equipment.service.work_logs import (
    delete_work_log as delete_work_log,
)
from app.modules.equipment.service.work_logs import (
    list_work_logs as list_work_logs,
)
from app.modules.equipment.service.work_logs import (
    update_work_log as update_work_log,
)
from app.modules.equipment.service.work_logs import (
    visible_work_log as visible_work_log,
)
from app.modules.equipment.service.work_summary import (
    _week_buckets as _week_buckets,
)
from app.modules.equipment.service.work_summary import (
    work_summary as work_summary,
)
