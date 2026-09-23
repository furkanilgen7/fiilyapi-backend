"""PARA-GERCEK — kira hakedişi `pay` kapısı (kullanıcı kararı 2026-09-19).

Kullanıcının kuralı (KK-ODM): *"Nakit olarak görmeden veya çekin vadesi gelip
de tahsil edilmeden 'ödendi' gözükmemesi gerekiyor."*

## Neden BURADA, `rental_service`te DEĞİL

`rental_posting`in açtığı precedent izlenir: `rental_service.py` ZATEN 864
satırdır (800 tavanının üstünde, önceden var olan bir borç) ve kapının gövdesi
oraya yazılsaydı borç BÜYÜRDÜ. Ama yer seçimi bir satır sayısından ibaret
değildir: *"para gerçekten geldi mi"* bir HAZİNE sorusudur, kira hakedişinin
durum makinesinin sorusu değil. `rental_service`te kalan tek şey KANCANIN YERİ
olmalıdır (`pay_invoice`ın ilk satırı), kancanın İÇERİĞİ değil.

## Bu aile kardeşlerinden İKİ yerde ayrılır

1. **Eşik `invoice_amount` KOLONUDUR**, satırlardan türeyen bir brüt değil.
   `our_total` (satırların `saat × bedel` çapraz kontrolü) bir DOĞRULAMA
   büyüklüğüdür, ödenecek tutar değil — fişin tabanı da odur değildir
   (`rental_posting:24`). Kardeş iki aile brütü `calculations.gross_total`dan
   alır; burada öyle bir toplama YOKTUR ve uydurulmaz.
2. **`invoice_amount` NULL OLABİLİR** ve NULL "girilmedi"dir, sıfır DEĞİL
   (NULL-EŞİK kanonu). Kardeş ailelerde brüt her zaman bir sayıdır, bu yüzden
   onlarda bu engelin karşılığı YOKTUR.

## Neden bu kapı 2026-09-19'a kadar YOKTU

Bir unutma DEĞİLDİ: `invoicing/source_amounts.py:111-113` kodda YAZILI olarak
*"kira orada bilinçli olarak dışarıdadır"* diyordu. Karar geldi — KK-ODM kirayı
da kapsar. Teknik engel zaten yoktu: `invoices.equipment_rental_invoice_id` FK'sı
ve `uq_invoices_equipment_rental_invoice` tekilliği ŞEMADA HAZIRDI, migration
GEREKMEDİ.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError
from app.modules.equipment.models import EquipmentRentalInvoice
from app.modules.invoicing.models import Invoice
from app.modules.treasury import realized

__all__ = ["RENTAL_AMOUNT_MISSING", "assert_para_gercek"]

#: 🔴 409 — evrağın GÖVDESİ kusurlu değildir (422 olurdu); engel kaydın
#: ARKASINDAKİ para durumudur. Kardeş iki ailede karşılığı YOKTUR (yukarıda §2).
RENTAL_AMOUNT_MISSING = (
    "Kira hakedişi ödendi işaretlenemez: faturanın KDV hariç tutarı "
    "girilmemiş. Önce fatura tutarını girin."
)


async def assert_para_gercek(session: AsyncSession, invoice: EquipmentRentalInvoice) -> None:
    """`pay`in ÖN KOŞULU: para GERÇEKTEN geldi mi?

    Bu kapı öncesinde `pay_invoice` hiçbir şeye BAKMIYORDU — yalnız geçiş
    tablosunu okuyup `paid_at`i yazıyordu ve arkasında tek kuruş hareket
    olmadan kira hakedişi "ödendi" görünebiliyordu (canlıda ölçüldü).

    Dört engelin gövdesi `treasury.realized.assert_realized_covers`tadır ve
    BURADA TEKRARLANMAZ; bu fonksiyonun tek işi ailenin brütünü doğru kolondan
    vermek ve NULL hâlini fail-closed kapatmaktır.
    """
    if invoice.invoice_amount is None:
        raise ConflictError(RENTAL_AMOUNT_MISSING)
    await realized.assert_realized_covers(
        session,
        Invoice.equipment_rental_invoice_id,
        invoice.id,
        source_gross=invoice.invoice_amount,
    )
