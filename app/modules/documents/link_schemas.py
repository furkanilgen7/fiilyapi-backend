"""BC-3 belge ↔ varlık bağı şemaları.

Dört sahip TEK şema kümesini paylaşır (`owner_id` sahibe göre bölüm/ünite/satış/
sözleşme kimliğidir): sahip başına ayrı `SectionDocumentRead` vb. üretmek
OpenAPI'ye dört özdeş şema yazdırır ve frontend'e dört özdeş tip devrederdi.

Bayt YOKTUR (BC kanonu): bağ satırı arşiv KÜNYESİNİ (`DocumentRead`) gömer,
indirme `GET /documents/{id}/download` ucunun işidir.
"""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.documents.models.links import EntityDocumentScope
from app.modules.documents.schemas import DESCRIPTION_MAX_LENGTH, DocumentRead

#: `note` kolonu `Text` (DB sınırsız); tavanı şema koyar — `documents.description`
#: ile AYNI sabit (2000), ikinci bir tavan icat edilmez.
NOTE_MAX_LENGTH = DESCRIPTION_MAX_LENGTH


class EntityDocumentTypeRead(BaseModel):
    """`GET /documents/slot-types` satırı — sabit slot (CRUD ucu YOK)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    scope: EntityDocumentScope
    code: str
    name: str
    is_required: bool
    sort_order: int


class EntityDocumentTypeListResponse(BaseModel):
    items: list[EntityDocumentTypeRead]


class EntityDocumentLinkCreate(BaseModel):
    """`POST /<sahip>/{owner_id}/documents` gövdesi — İKİ ADIMLI akışın 2. adımı.

    Dosya ÖNCE `POST /documents`a yüklenir (`project_id` orada zorunlu), dönen
    künye kimliği burada `document_id` olarak bağlanır (`LeaveRequestFormModal`
    emsali; taslak/staging tablosu AÇILMAZ). `document_id` bu uçta ZORUNLUDUR:
    ucun adı "bağla"dır — dosyasız slot satırı yalnız arşiv kaydı sonradan
    silinince (SET NULL) oluşur, elle açılmaz.

    `project_id`/`site_id` GÖVDEDE YOKTUR: sahipten türetilir; gövdeden alınsaydı
    görünürlük süzgeci bağ üzerinden delinirdi.
    """

    type_id: uuid.UUID
    document_id: uuid.UUID
    issued_at: date | None = None
    valid_until: date | None = None
    note: str | None = Field(default=None, max_length=NOTE_MAX_LENGTH)


class EntityDocumentLinkUpdate(BaseModel):
    """`PATCH /<sahip>/documents/{link_id}` — KAPSAM DAR: üç künye alanı.

    `type_id` ve `document_id` bu uçtan DEĞİŞTİRİLEMEZ; yanlış slot ya da yanlış
    dosya bağı silinip yeniden bağlanır (`EquipmentDocumentUpdate` emsali).
    Gövdeye gönderilse bile Pydantic yok sayar.

    `exclude_unset`: gönderilmeyen alana DOKUNULMAZ, açıkça `null` gönderilen
    alan TEMİZLENİR (`DocumentUpdate` deseni).
    """

    issued_at: date | None = None
    valid_until: date | None = None
    note: str | None = Field(default=None, max_length=NOTE_MAX_LENGTH)


class EntityDocumentLinkRead(BaseModel):
    """Bağ satırı + slot künyesi + (varsa) arşiv künyesi.

    `document` NULL ise arşiv kaydı silinmiş demektir (SET NULL); satır bir
    "belge vardı" kaydı olarak kalır ve ekran onu "dosya yok" rozetiyle basar.
    """

    id: uuid.UUID
    owner_id: uuid.UUID
    scope: EntityDocumentScope
    type_id: uuid.UUID
    type_code: str
    type_name: str
    is_required: bool
    document_id: uuid.UUID | None
    document: DocumentRead | None
    issued_at: date | None
    valid_until: date | None
    note: str | None
    created_at: datetime
    updated_at: datetime


class EntityDocumentLinkListResponse(BaseModel):
    """Düz liste, slot sırasıyla (`sort_order`, sonra `created_at`). Boş slotlar
    LİSTEDE DEĞİLDİR — katalog `GET /documents/slot-types`tan çizilir."""

    items: list[EntityDocumentLinkRead]
