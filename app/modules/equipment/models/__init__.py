"""Makine & ekipman — veri modeli (MK-1 spec §2/§5 + MK-2 spec §2.1/§2.2/§5) — paket CEPHESİ.

Beş tablo: ekipman kartı (M1+M2) · çalışma kaydı (M3) · yakıt kaydı (M4) ·
kira hakedişi başlığı (M5) · kira hakedişi satırı (M5 tablosu).
Router/servis mantığı BU DOSYADA YOKTUR (T3+).

Bu modülün taşıdığı kalıcı kararlar:

* **K1 — `brand` ve `model` AYRI kolondur.** M2:86 tek alan çiziyor ama M1:94
  kart yalnız markayı basıyor; tek alanda saklansaydı liste ekranı markayı
  ayıklamak için metin parçalardı. Onaylı sapma.
* **K2 — `purchase_amount` DB'de nullable'dır.** Koşullu zorunluluk
  (`ownership == owned` iken 422) SERVİStedir, DB CHECK'i DEĞİL — kiralık
  makinenin alış bedeli yoktur (İK-3 S3 emsali: kural nerede yaşadığı bilinsin).
* **K3 — Satıcı ve kiralama firması TEK `supplier_id`'dir.** SA'nın `suppliers`
  tablosu yeniden kullanılır; iki alan tutulsaydı aynı firma iki kez yazılır ve
  tedarikçi bakiyesi ikiye bölünürdü.
* **K4 — Atama hedefi `site_id`'dir, `warehouse_id` AÇILMAZ.** "Depoda
  (Atanmadı)" = `site_id IS NULL`. İkinci bir atama hedefi "makine nerede"
  sorusuna iki cevap üretirdi. Onaylı sapma.
* **K5 — `norm_consumption` SAYI + `norm_unit` ENUM'a ayrılır.** M4 bunun
  üzerinden yüzde sapma hesaplıyor; metin saklansaydı hesap her okumada metin
  ayrıştırmaya bağlı olurdu.
* **K7 — `monthly_capacity_hours` VERİDİR, koda gömülmez** (İK-3 K1 emsali);
  vinç ile el aleti aynı kapasitede değildir.
* **K8 — `is_company_asset` YALNIZ BİR İŞARETTİR.** Sabit kıymet modülü YOK;
  hiçbir yan etki tetiklemez.
* **K9 — Tarihsel atama izi `equipment_work_logs.site_id`de yaşar**;
  `equipment.site_id` BUGÜNKÜ atamadır. Makine şantiye değiştirince geçmiş
  maliyet dağılımı geriye dönük başka projeye yazılmaz.
* **K10 — Arıza AYRI KAYIT TİPİDİR** (`record_type`), aynı kayıtta ikinci saat
  kolonu değil: M3:282 arızayı kendi satırı (operatörsüz, sebep metniyle),
  M5:128-139 ayrı satır olarak basıyor.
* **`amount` KOLON DEĞİLDİR** (yakıt): `liters × unit_price` her okumada
  türetilir — P10 "tek formül" kanonu; iki yerde yaşayan para zamanla ayrışır.
* **`is_draft` AÇILMAZ:** M2'de taslak butonu YOKTUR (personel formunun aksine).

## 🔴 Paket yapısı (TB-EQUIP) — ŞEMA DEĞİŞMEDİ

Dosya 874 satırdaydı (tavan 800). Yedi tablo + on bir enum, sınıfların KENDİ
sınırlarına göre bölündü; hiçbir kolon, kısıt, indeks, `server_default` ya da
`ondelete` değişmedi. Kanıt tahminde değil ÖLÇÜMDE: `Base.metadata` dökümü
(`tests/tbequip_sema_anlik_goruntu.txt`) bölmeden ÖNCE donduruldu ve sonra
BİREBİR tuttu; `alembic revision --autogenerate` gövdesi BOŞ çıktı.

* `constants.py` — kolon ÖLÇEKLERİ (para · miktar · saat · KDV); `core` ve
  `rental` ikisi de okur, ikinci kopya yazılmaz
* `enums.py`     — on bir DB enum tipi + paylaşılan `equipment_rate_period_enum`
* `core.py`      — MK-1: ekipman kartı · çalışma kaydı · yakıt kaydı
* `rental.py`    — MK-2: kira hakedişi başlığı + satırı
* `documents.py` — MK-2/FRM-1: belge türü + belge

🔴 **Cephe HER SINIFI GERÇEKTEN İÇE AKTARIR** (`__all__` yetmez): bir sınıf
içe aktarılmazsa tablosu `Base.metadata`ya kaydolmaz, `import` yeşil kalır ve
`alembic autogenerate` o tabloyu "SİLİNECEK" diye raporlar — hata içe
aktarmada DEĞİL ilk migration'da/sorguda çıkardı.
`X as X` biçimi bilinçlidir: açık yeniden-ihraç, `noqa` olmadan F401'i susturur.

**`relationship()` BU MODÜLDE HİÇ YOKTUR** (ölçüldü: 0 kullanım) — dize adıyla
çözülen eşleyici ilişkisi riski burada GEÇERSİZDİR; bağlar `ForeignKey` dize
hedefleridir ve onlar da `Base.metadata`dan çözülür (bekçi fiilen çözdürür).
"""

from app.modules.equipment.models.constants import (
    DEFAULT_MONTHLY_CAPACITY_HOURS as DEFAULT_MONTHLY_CAPACITY_HOURS,
)
from app.modules.equipment.models.constants import (
    DEFAULT_VAT_RATE as DEFAULT_VAT_RATE,
)
from app.modules.equipment.models.constants import (
    HOURS_PRECISION as HOURS_PRECISION,
)
from app.modules.equipment.models.constants import (
    HOURS_SCALE as HOURS_SCALE,
)
from app.modules.equipment.models.constants import (
    MONEY_PRECISION as MONEY_PRECISION,
)
from app.modules.equipment.models.constants import (
    MONEY_SCALE as MONEY_SCALE,
)
from app.modules.equipment.models.constants import (
    QUANTITY_PRECISION as QUANTITY_PRECISION,
)
from app.modules.equipment.models.constants import (
    QUANTITY_SCALE as QUANTITY_SCALE,
)
from app.modules.equipment.models.constants import (
    RENTAL_HOURS_PRECISION as RENTAL_HOURS_PRECISION,
)
from app.modules.equipment.models.constants import (
    RENTAL_HOURS_SCALE as RENTAL_HOURS_SCALE,
)
from app.modules.equipment.models.constants import (
    UNIT_PRICE_PRECISION as UNIT_PRICE_PRECISION,
)
from app.modules.equipment.models.constants import (
    UNIT_PRICE_SCALE as UNIT_PRICE_SCALE,
)
from app.modules.equipment.models.constants import (
    VAT_RATE_PRECISION as VAT_RATE_PRECISION,
)
from app.modules.equipment.models.constants import (
    VAT_RATE_SCALE as VAT_RATE_SCALE,
)
from app.modules.equipment.models.core import (
    Equipment as Equipment,
)
from app.modules.equipment.models.core import (
    EquipmentFuelLog as EquipmentFuelLog,
)
from app.modules.equipment.models.core import (
    EquipmentWorkLog as EquipmentWorkLog,
)
from app.modules.equipment.models.documents import (
    EquipmentDocument as EquipmentDocument,
)
from app.modules.equipment.models.documents import (
    EquipmentDocumentType as EquipmentDocumentType,
)
from app.modules.equipment.models.enums import (
    EquipmentCategory as EquipmentCategory,
)
from app.modules.equipment.models.enums import (
    EquipmentFinancing as EquipmentFinancing,
)
from app.modules.equipment.models.enums import (
    EquipmentFuelType as EquipmentFuelType,
)
from app.modules.equipment.models.enums import (
    EquipmentMaintenancePeriod as EquipmentMaintenancePeriod,
)
from app.modules.equipment.models.enums import (
    EquipmentNormUnit as EquipmentNormUnit,
)
from app.modules.equipment.models.enums import (
    EquipmentOwnership as EquipmentOwnership,
)
from app.modules.equipment.models.enums import (
    EquipmentRatePeriod as EquipmentRatePeriod,
)
from app.modules.equipment.models.enums import (
    EquipmentStatus as EquipmentStatus,
)
from app.modules.equipment.models.enums import (
    RentalInvoiceStatus as RentalInvoiceStatus,
)
from app.modules.equipment.models.enums import (
    RentalLineKind as RentalLineKind,
)
from app.modules.equipment.models.enums import (
    WorkLogType as WorkLogType,
)
from app.modules.equipment.models.enums import (
    equipment_rate_period_enum as equipment_rate_period_enum,
)
from app.modules.equipment.models.rental import (
    EquipmentRentalInvoice as EquipmentRentalInvoice,
)
from app.modules.equipment.models.rental import (
    EquipmentRentalInvoiceLine as EquipmentRentalInvoiceLine,
)
