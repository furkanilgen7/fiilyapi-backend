"""Ünite satışının korkulukları ve Türkçe hata metinleri (P8 spec §2-§6).

`units/guards.py` deseninin aynısı: hata SINIFLARI `app/core/errors.py`'de,
METİNLER modül içinde sabit olarak durur ve TEK kopyadır — POST ile PATCH aynı
fonksiyonu ÇAĞIRIR, kuralı kopyalamaz.

## Görünürlük tek kaynaktan gelir

Süzgeç P1'DEN gelir (`projects.service.visible_projects`); kopya bir erişim
mantığı YAZILMAZ. Aynı desen `units/guards.py:25`, `sites/service.py` ve
`boq/service.py`de de vardır. Görünmeyen kayıt **404** döner (403 DEĞİL) ve var
olmayanla AYNI gövdeyi verir: aksi hâlde elinde UUID olan kullanıcı kaydın var
olduğunu ve başkasına ait olduğunu ayırt edebilirdi (spec §6).

## `customers` neden burada süzülmüyor

Alıcı PROJE-BAĞIMSIZDIR (spec §6, `customers/router.py` notu): tabloda
`project_id` kolonu bile yoktur, aynı kişi birden çok projeden daire alabilir.
`existing_customer` yalnız VARLIK sorar; erişim `sales` izin seviyesindedir.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, DuplicateError, NotFoundError, UnitValidationError
from app.modules.customers.guards import CUSTOMER_MISSING
from app.modules.customers.models import Customer
from app.modules.customers.repository import get_customer
from app.modules.projects.models import Project
from app.modules.projects.service import visible_projects
from app.modules.sales import repository
from app.modules.sales.models import SaleInstallment, UnitSale
from app.modules.units.models import Unit, UnitOwnerSide
from app.modules.units.repository import get_unit
from app.modules.users.models import User

__all__ = [
    "CUSTOMER_MISSING",
    "DELETE_NOT_ALLOWED",
    "DUPLICATE_SEQUENCE_NO",
    "INSTALLMENT_MISSING",
    "INVALID_STATUS_TRANSITION",
    "INSTALLMENT_TOTAL_MISMATCH",
    "LANDOWNER_UNIT_NOT_SELLABLE",
    "PAID_INSTALLMENT_BELOW_PAID",
    "PAID_INSTALLMENT_REMOVED",
    "PAYMENT_EXCEEDS_INSTALLMENT",
    "PLAN_DOWN_PAYMENT_EXCEEDS",
    "PLAN_HAS_PAYMENTS",
    "PLAN_INPUT_MISSING",
    "PROJECT_MISSING",
    "SALE_MISSING",
    "SALE_NOT_DELETABLE",
    "UNIT_ALREADY_SOLD",
    "UNIT_MISSING",
    "USER_NOT_FOUND",
    "ensure_no_open_sale",
    "ensure_plan_replaceable",
    "ensure_unit_sellable",
    "existing_customer",
    "visible_installment",
    "unit_in_project",
    "visible_project",
    "visible_sale",
    "visible_sale_locked",
]

# 404 gövdeleri — görünmeyen ile var olmayan AYNI metni döner (`units/guards.py` dersi).
PROJECT_MISSING = "Proje bulunamadı"
SALE_MISSING = "Satış kaydı bulunamadı"
UNIT_MISSING = "Ünite bulunamadı"
# T4: taksit → satış → proje zinciriyle süzülür; görünmeyen taksit VAR OLMAYANLA
# aynı gövdeyi döner (spec §6).
INSTALLMENT_MISSING = "Taksit bulunamadı"

# 422 — spec §8 S3 (kullanıcı kararı): arsa sahibinin payına düşen üniteler
# satışa KAPALIDIR. Hissedar-ünite dağıtımı P9'un işidir; orada yeniden
# değerlendirilecektir. DB `CHECK`i ile zorlanamaz (`owner_side` başka tabloda
# DEĞİL ama kural iki tabloyu birden okur), bu yüzden servis korkuluğudur.
LANDOWNER_UNIT_NOT_SELLABLE = "Arsa sahibine ait ünite satışa açılamaz"

# 422 — danışman FK'si (F75). `sites/guards.py:45` ile AYNI metin ve AYNI
# gerekçe: istenen kaynak SATIŞTIR, kullanıcı burada bir ALAN DEĞERİDİR.
USER_NOT_FOUND = "Seçilen kullanıcı bulunamadı"

# 409 — `uq_unit_sales_open_unit` (T1): ünite başına en çok BİR açık kayıt.
UNIT_ALREADY_SOLD = "Bu ünitede zaten açık bir satış kaydı var"

# 409 — spec §4: `active`/`deed_transferred` SİLİNMEZ, iptal edilir (T5 `cancel`).
# `DuplicateError` (benzersizlik) değil `ConflictError` (kaydın DURUMU) —
# `progress_payments`in `PAYMENT_NOT_DELETABLE` ayrımının aynısı.
SALE_NOT_DELETABLE = "Yalnızca rezervasyon kaydı silinebilir; satış iptal edilmelidir"

# 403 — `can_delete` (`app/core/access.py`) reddi.
DELETE_NOT_ALLOWED = "Bu satış kaydını silme yetkiniz yok"

# 409 — T5 geçiş matrisinde (bkz. `transitions.TRANSITIONS`) OLMAYAN her çift.
# `ConflictError` (409), `progress_payments.guards.INVALID_STATUS_TRANSITION` ile
# AYNI sınıf ve AYNI kod: durum makinesi reddi bir doğrulama hatası (422) değil,
# kaydın O ANKİ durumuyla çakışmadır.
INVALID_STATUS_TRANSITION = "Satış kaydının durumu bu işleme uygun değil"

# --- Ödeme planı (T4; spec §2/§4, mockup F110-147) ---

# 422 — plan üretilecek girdi yok (ne peşinat ne taksit). Boş plan SESSİZCE
# üretilmez: kullanıcı "Plan Oluştur"a (F100) bastığında hiçbir şey olmaması
# formu doldurduğunu sanmasına yol açardı.
PLAN_INPUT_MISSING = "Ödeme planı için peşinat veya taksit sayısı girilmelidir"

# 422 — F103 peşinat F86 satış bedelini aşamaz (negatif taksit doğardı).
PLAN_DOWN_PAYMENT_EXCEEDS = "Peşinat satış bedelinden büyük olamaz"

# 409 — tahsilatı olan plan YENİDEN ÜRETİLMEZ: satırların silinmesi işlenmiş
# tahsilatı da yok ederdi (geri alınamaz veri kaybı). Kullanıcı önce planı
# `PUT installments` ile düzenler ya da tahsilatı düzeltir.
PLAN_HAS_PAYMENTS = "Tahsilatı yapılmış ödeme planı yeniden üretilemez"

# 422 — spec §2: plan toplamı = `sale_price` (mockup satır 143 TOPLAM = F86).
INSTALLMENT_TOTAL_MISMATCH = "Ödeme planı toplamı satış bedeline eşit olmalıdır"

# 409 — gövdede aynı `sequence_no` iki kez (UQ `uq_sale_installments_sale_sequence`
# ikizi; `lines.DUPLICATE_CELL` deseni).
DUPLICATE_SEQUENCE_NO = "Aynı taksit sırası birden çok kez gönderildi"

# 409 — DEĞİŞTİRME semantiği tahsilatı SESSİZCE YUTAMAZ (aşağıdaki gerekçe).
PAID_INSTALLMENT_REMOVED = "Tahsilatı olan taksit plandan çıkarılamaz"

# 422 — tahsilatın altına inen tutar, satırı "aşırı ödenmiş" hâlde bırakırdı.
PAID_INSTALLMENT_BELOW_PAID = "Taksit tutarı tahsil edilen tutardan küçük olamaz"

# 422 — §8 S2: kısmi ödeme serbesttir, AŞIRI ödeme değil.
PAYMENT_EXCEEDS_INSTALLMENT = "Tahsilat tutarı taksit bakiyesini aşamaz"


# --- Görünürlük (spec §6) ---


async def visible_project(
    session: AsyncSession, actor: User, project_id: uuid.UUID, missing: str = PROJECT_MISSING
) -> Project:
    """Kullanıcı projeyi göremiyorsa 404 — 403 DEĞİL: varlığın kendisi sızdırılmaz."""
    visible = await visible_projects(session, actor)
    project = next((p for p in visible if p.id == project_id), None)
    if project is None:
        raise NotFoundError(missing)
    return project


async def visible_sale(
    session: AsyncSession, actor: User, sale_id: uuid.UUID
) -> tuple[UnitSale, Project]:
    """Satış → proje → görünürlük (`units.guards.visible_unit` deseni).

    Görünmeyen projenin satışı **404** döner ve var olmayan satışla AYNI mesajı
    verir; `unit_sales.project_id` kolonu tam da bu süzgeç için vardır (T1
    modeli), ünite üzerinden JOIN etmek her sorguya bir adım eklerdi.
    """
    sale = await repository.get_sale(session, sale_id)
    if sale is None:
        raise NotFoundError(SALE_MISSING)
    project = await visible_project(session, actor, sale.project_id, SALE_MISSING)
    return sale, project


async def visible_sale_locked(
    session: AsyncSession, actor: User, sale_id: uuid.UUID
) -> tuple[UnitSale, Project]:
    """`visible_sale`in KİLİTLİ ikizi — durum geçişlerinin (T5) tek okuma yolu.

    Satır `SELECT … FOR UPDATE` ile okunur ki iki eşzamanlı geçiş isteği AYNI
    durumu okuyup ikisi de geçerli sanılmasın (`progress_payments.transitions`
    dersi): kilit alınmasaydı `activate` + `cancel` yarışında ünite senkronu
    kaybedene göre kalır ve satış kaydıyla ünitenin vitrini AYRIŞIRDI.

    Kapsam süzgeci kilitten SONRA koşar ama gövde AYNIDIR (404): görünmeyen
    kaydın durumu hakkında 409/422 ile bilgi sızdırılmaz.
    """
    sale = await repository.get_sale_locked(session, sale_id)
    if sale is None:
        raise NotFoundError(SALE_MISSING)
    project = await visible_project(session, actor, sale.project_id, SALE_MISSING)
    return sale, project


async def unit_in_project(session: AsyncSession, project: Project, unit_id: uuid.UUID) -> Unit:
    """Gövdedeki `unit_id` BAŞKA projenin ünitesi olabilir (units IDOR-9).

    Proje sınırını aşan ünite **404** döner (422 değil): ünitenin varlığı da
    gizlidir — kullanıcı o projeyi hiç göremiyor olabilir.
    """
    unit = await get_unit(session, unit_id)
    if unit is None or unit.project_id != project.id:
        raise NotFoundError(UNIT_MISSING)
    return unit


async def existing_customer(session: AsyncSession, customer_id: uuid.UUID) -> Customer:
    """Alıcı proje-bağımsızdır (spec §6) — yalnız VARLIK sorulur, kapsam değil."""
    customer = await get_customer(session, customer_id)
    if customer is None:
        raise NotFoundError(CUSTOMER_MISSING)
    return customer


# --- Alan kuralları ---


def ensure_unit_sellable(unit: Unit) -> None:
    """Spec §8 S3: `owner_side='landowner'` ünite satışa kapalı → 422.

    `contractor` ve NULL (paylaşım henüz girilmemiş, KKP 78) SERBESTTİR: kural
    yalnız arsa sahibine AÇIKÇA atanmış üniteyi engeller.
    """
    if unit.owner_side is UnitOwnerSide.landowner:
        raise UnitValidationError(LANDOWNER_UNIT_NOT_SELLABLE)


async def ensure_no_open_sale(
    session: AsyncSession, unit_id: uuid.UUID, exclude_sale_id: uuid.UUID | None = None
) -> None:
    """Ünite başına tek AÇIK kayıt (`cancelled` hariç) — açık SELECT ile ÖNDEN.

    `customers._assert_identity_free` ile aynı iki katmanlı desen: servis önce
    SELECT ile bakar ki kullanıcıya ALANA ÖZEL Türkçe mesaj verilsin; kısmi
    benzersiz indeks (`uq_unit_sales_open_unit`) + `IntegrityError` → 409
    çevirisi YARIŞ DURUMU emniyet ağı olarak KALIR. Servis korkuluğuna tek
    başına güvenilseydi iki eş zamanlı istek aynı daireyi iki müşteriye satardı.
    """
    if await repository.get_open_sale_for_unit(session, unit_id, exclude_sale_id) is not None:
        raise DuplicateError(UNIT_ALREADY_SOLD)


def ensure_deletable_status(is_reservation: bool) -> None:
    """Spec §4: yalnız `reservation` silinir; gerisi iptal edilir (T5)."""
    if not is_reservation:
        raise ConflictError(SALE_NOT_DELETABLE)


# --- Ödeme planı korkulukları (T4) ---


async def visible_installment(
    session: AsyncSession, actor: User, installment_id: uuid.UUID
) -> tuple[SaleInstallment, UnitSale, Project]:
    """Taksit → satış → proje zinciri (`visible_sale`in bir halka uzunu).

    Görünmeyen taksit **404** döner ve VAR OLMAYANLA aynı gövdeyi verir: aksi
    hâlde elinde taksit UUID'si olan kullanıcı, kaydın var olduğunu ve başka bir
    projeye ait olduğunu ayırt edebilirdi (spec §6).

    Satır burada `SELECT … FOR UPDATE` ile KİLİTLENEREK okunur: `pay` ucunun
    doğrulaması (`paid_amount + tutar ≤ amount`) bu okumadan beslenir ve kilit
    okumadan SONRA alınsaydı iki eşzamanlı tahsilat aynı "tahsil edilen"i görür,
    ikisi de geçerli sanılır ve taksit AŞIRI ödenirdi (TOCTOU).
    """
    installment = await repository.get_installment_locked(session, installment_id)
    if installment is None:
        raise NotFoundError(INSTALLMENT_MISSING)
    sale = await repository.get_sale(session, installment.sale_id)
    if sale is None:  # pragma: no cover - FK CASCADE garantisi
        raise NotFoundError(INSTALLMENT_MISSING)
    project = await visible_project(session, actor, sale.project_id, INSTALLMENT_MISSING)
    return installment, sale, project


def ensure_plan_replaceable(installments: list[SaleInstallment]) -> None:
    """Yeniden üretim tahsilatı YOK EDEMEZ (409) — `PLAN_HAS_PAYMENTS` gerekçesi."""
    if any(row.paid_amount > 0 for row in installments):
        raise ConflictError(PLAN_HAS_PAYMENTS)
