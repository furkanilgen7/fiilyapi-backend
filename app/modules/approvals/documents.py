"""Zincirin çok-biçimli `document_id`'sinin PROJEYE bağlandığı TEK yer (T4).

`approval_chains.document_id` bir FK DEĞİLDİR (üç ayrı evrak ailesi, Postgres'te
çok-biçimli FK yok — `models.py` docstring'i). Buna karşılık onay kutusu bir
YETKİ yüzeyidir ve kapsam kararı ancak evrağın projesinden verilebilir. Bu
modül o eşlemeyi taşır ve **SQL süzgecini üretir**.

🔴 SÜZGEÇ SQL'DEDİR, BELLEKTE DEĞİL (BOR-TEMİZ kanonu). `items` süzülüp `total`
süzülmeseydi kullanıcı GÖREMEDİĞİ kayıtları SAYAR, sayfalayıcı boş sayfalar
üretir ve "kaç imza bekliyor" rozeti yalan söylerdi. Aynı `WHERE` gövdesi hem
sayfaya hem `COUNT`a girer.

🔴 FAIL-CLOSED (SA kanonu). Kaynağı çözülemeyen zincir (evrağı silinmiş ya da
hiç var olmamış `document_id`) HİÇBİR projeye düşmez, dolayısıyla `IN (...)`
alt sorgusunu doğal olarak kaçırır ve GÖRÜNMEZ. Ters yön ("bilinmiyorsa
göster") kapsamı ne olursa olsun herkese açık bir satır bırakırdı.

Burada YALNIZ model eşlemesi vardır; satır zenginleştirmesi (başlık/alt başlık/
tutar) `inbox.py`dedir. Ayrım kasıtlı: bu dosyayı `repository.py` ithal eder ve
onun hesap motorlarına ihtiyacı YOKTUR.
"""

import uuid

from sqlalchemy import ColumnElement, and_, false, or_, select
from sqlalchemy.orm import InstrumentedAttribute

from app.modules.approvals.models import ApprovalChain, ApprovalDocumentType
from app.modules.procurement.models import PurchaseRequest
from app.modules.progress_payments.models import ProgressPayment
from app.modules.subcontractor_progress_payments.models import SubcontractorProgressPayment

__all__ = ["DOCUMENT_PROJECT_COLUMNS", "visible_document_clause"]

#: Evrak ailesi -> (`id` kolonu, `project_id` kolonu).
#:
#: ÜÇÜNDE DE `project_id` DOĞRUDAN evrak satırındadır — taşeron hakedişinde bu
#: kolon zaten "her liste sorgusunda JOIN gerektirmesin" diye sözleşmeden
#: kopyalanmıştır (`subcontractor_progress_payments/models.py`). Yani süzgeç
#: tek bir alt sorguyla kurulur, aile başına JOIN zinciri gerekmez.
DOCUMENT_PROJECT_COLUMNS: dict[
    ApprovalDocumentType, tuple[InstrumentedAttribute, InstrumentedAttribute]
] = {
    ApprovalDocumentType.subcontractor_progress_payment: (
        SubcontractorProgressPayment.id,
        SubcontractorProgressPayment.project_id,
    ),
    ApprovalDocumentType.purchase_request: (
        PurchaseRequest.id,
        PurchaseRequest.project_id,
    ),
    ApprovalDocumentType.progress_payment: (
        ProgressPayment.id,
        ProgressPayment.project_id,
    ),
}


def visible_document_clause(visible_project_ids: list[uuid.UUID]) -> ColumnElement[bool]:
    """Zincirin evrağı, aktörün GÖRDÜĞÜ bir projeye mi ait?

    🔴 BOŞ KÜME "HEPSİ" DEĞİLDİR: kapsamı olmayan aktör için `false()` döner.
    `IN ()` yazan bir uygulama SQL'de sözdizimi hatası ya da (kötüsü) süzgeci
    düşürüp TÜM satırları döndürme davranışı üretirdi.
    """
    if not visible_project_ids:
        return false()
    return or_(
        *[
            and_(
                ApprovalChain.document_type == document_type,
                ApprovalChain.document_id.in_(
                    select(id_column).where(project_column.in_(visible_project_ids))
                ),
            )
            for document_type, (id_column, project_column) in DOCUMENT_PROJECT_COLUMNS.items()
        ]
    )
