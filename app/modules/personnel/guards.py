"""Personel korkulukları ve Türkçe hata metinleri (puantaj spec §2, §3).

`customers/guards.py` deseninin aynısı: hata SINIFLARI `app/core/errors.py`'de,
METİNLER modül içinde tek kopya sabit olarak durur ve POST ile PATCH aynı
fonksiyonu ÇAĞIRIR, kuralı kopyalamaz.

## Tek cümlelik kural

**Kaynak `subcontractor` DEĞİLSE taşeron bağı BOŞ olmalıdır.**

Aynı kural DB'de de vardır (`ck_personnel_subcontractor_only_for_subcontractor_source`),
ama CHECK ihlali `IntegrityError` -> 409 "Veri bütünlüğü hatası" verirdi; kullanıcı
hangi alanı düzelteceğini öğrenemezdi. Bu yüzden servis DB'ye DÜŞMEDEN 422 atar,
DB CHECK'i yarış/doğrudan-SQL emniyet ağı olarak KALIR.

**Ters yön ZORLANMAZ** (spec §2): kaynağı `subcontractor` olan bir kayıt taşeron
seçilmeden de oluşturulabilir — taslak esnekliği. Sonraki okuyucu bunu "eksik"
sanıp zorunluluk EKLEMESİN.
"""

import uuid

from app.core.errors import PersonnelValidationError
from app.modules.site_diary.models import WorkerSource

# 404 gövdesi (`customers/guards.py` deseni).
PERSONNEL_MISSING = "Personel bulunamadı"

# 422 — kaynak/taşeron uyuşmazlığı.
SUBCONTRACTOR_NOT_ALLOWED = (
    "Taşeron firması yalnız kaynağı taşeron olan personelde doldurulabilir; "
    "kaynağı değiştirin ya da firma bağını temizleyin."
)


def validate_personnel_source(source: WorkerSource, subcontractor_id: uuid.UUID | None) -> None:
    """Kural BİRLEŞİK kayıt üzerinde koşar.

    PATCH'te kaynak değişip taşeron alanı değişmeyebilir (ya da tersi); bu yüzden
    çağıran taraf DB'deki değerlerle gövdedeki değerleri birleştirip buraya öyle
    verir. Yalnız gövdeye bakmak, `subcontractor -> company` geçişinde eski taşeron
    bağının kayıtta kalmasına izin verirdi.
    """
    if source is not WorkerSource.subcontractor and subcontractor_id is not None:
        raise PersonnelValidationError(SUBCONTRACTOR_NOT_ALLOWED)
