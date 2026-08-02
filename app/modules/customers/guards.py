"""Alıcı (müşteri) kartoteksinin korkulukları ve Türkçe hata metinleri (P8 spec §2).

`contracts/guards.py` deseninin aynısı: hata SINIFLARI `app/core/errors.py`'de,
METİNLER modül içinde sabit olarak durur ve tek kopyadır — POST ile PATCH aynı
fonksiyonu ÇAĞIRIR, kuralı kopyalamaz.

## Tek cümlelik kural

**Alıcı tipi hangi kimlik numarasının doldurulacağını belirler: `person` -> TCKN,
`company` -> VKN; ötekisi BOŞ kalır.**

Mockup `Form - Daire Satisi.dc.html` satır 72'de tek bir "TCKN / VKN *" alanı
vardır — ekran tipe göre AYNI kutuya ya TCKN ya VKN yazdırır. Bu yüzden:

* tipin gerektirdiği alan boşsa 422 (satır 72'deki `*` zorunluluk işareti);
* tipe AİT OLMAYAN alan doluysa da 422 — sunucu sessizce TEMİZLEMEZ. Temizleme,
  istemci hatasını (iki alanı birden göndermek) veri kaybına çevirirdi ve
  kullanıcı yanlış numarayı girdiğini hiç öğrenmezdi. Ekranda tek kutu olduğu
  için doğru istemci zaten asla iki alanı birden gönderemez.

## Biçim doğrulaması BİLİNÇLİ OLARAK yok

TCKN/VKN'de hane sayısı, rakam kontrolü ya da doğrulama algoritması KOŞMAZ —
`contracts/schemas.py.SubcontractorCreate.tax_number` ve işveren VKN'si de
yalnız `max_length` ile sınırlıdır. Yeni bir sertlik burada icat edilmez;
gerekirse tüm VKN alanlarıyla BİRLİKTE ve ayrı bir kararla eklenir.
"""

from app.core.errors import CustomerValidationError
from app.modules.customers.models import CustomerType

# 404 gövdesi (`contracts/guards.py` deseni).
CUSTOMER_MISSING = "Müşteri bulunamadı"

# 422 — tip/kimlik uyuşması (mockup 70 + 72).
NATIONAL_ID_REQUIRED = "Gerçek kişi alıcı için TCKN zorunludur."
TAX_NUMBER_REQUIRED = "Tüzel kişi alıcı için VKN zorunludur."
NATIONAL_ID_NOT_ALLOWED = "Tüzel kişi alıcıda TCKN doldurulamaz; VKN giriniz."
TAX_NUMBER_NOT_ALLOWED = "Gerçek kişi alıcıda VKN doldurulamaz; TCKN giriniz."


def _bos(deger: str | None) -> bool:
    """`None` ve yalnız boşluktan oluşan metin AYNI şeydir — ikisi de "girilmedi"."""
    return deger is None or not deger.strip()


def validate_customer_identity(
    customer_type: CustomerType, national_id: str | None, tax_number: str | None
) -> None:
    """Kural BİRLEŞİK kayıt üzerinde koşar.

    PATCH'te tip değişip kimlik alanı değişmeyebilir (ya da tersi); bu yüzden
    çağıran taraf DB'deki değerlerle gövdedeki değerleri birleştirip buraya
    öyle verir. Yalnız gövdeye bakmak, `person -> company` geçişinde eski
    TCKN'nin kayıtta kalmasına izin verirdi.
    """
    if customer_type is CustomerType.person:
        if _bos(national_id):
            raise CustomerValidationError(NATIONAL_ID_REQUIRED)
        if not _bos(tax_number):
            raise CustomerValidationError(TAX_NUMBER_NOT_ALLOWED)
        return
    if _bos(tax_number):
        raise CustomerValidationError(TAX_NUMBER_REQUIRED)
    if not _bos(national_id):
        raise CustomerValidationError(NATIONAL_ID_NOT_ALLOWED)
