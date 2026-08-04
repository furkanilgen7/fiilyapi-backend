"""Klasör (T2) ve belge künyesi (T3) şemaları — spec §3.

Versiyon/onay/etiket alanı YOKTUR (spec §1): model de taşımıyor, şema da uydurmaz.
Thumbnail/önizleme alanı da YOKTUR (mockup yalnız emoji tip ikonu basar).

## Klasör listesinde belge SAYACI YOKTUR (T2 kararı; T4'te yeniden onaylandı)

T3 bir ara sayaç alanı eklemişti; dayanağı "mockup'ta 'Sözleşmeler (12)' rozeti
var" idi ve mockup taraması bu rozetin VAR OLMADIĞINI gösterdi — spec §3 de
sayaçtan söz etmez, alan T4'te icat yasağı gereği tamamen söküldü. Sonuç: klasör
listesi her kök çizilişinde `documents` tablosuna bir toplama sorgusu
koşturmaz. F-BC gerçek bir ihtiyaç kanıtlarsa tek sorguyla geri eklenebilir.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# Model `String(150)` — şema ile DB sınırı AYNI olmalı, aksi hâlde 150'den uzun
# ad Pydantic'i geçer ve kullanıcıya anlaşılmaz bir 409/500 olarak döner.
_NAME = Field(min_length=1, max_length=150)


class DocumentFolderCreate(BaseModel):
    """`POST /projects/{id}/document-folders` gövdesi.

    `project_id` GÖVDEDE YOKTUR — yol parametresidir; iki yerden gelseydi
    hangisinin kazandığı belirsiz olur ve kapsam süzgeci atlatılabilirdi.
    """

    name: str = _NAME
    # NULL = proje düzeyi klasör (spec §2; E12 kökü proje/şantiye ikilisidir).
    site_id: uuid.UUID | None = None
    # NULL = kök klasör. Ebeveynin kapsamı doğrulanır (bkz. `guards`).
    parent_id: uuid.UUID | None = None


class DocumentFolderUpdate(BaseModel):
    """`PATCH /document-folders/{id}` gövdesi — YALNIZ ad (spec §3).

    Kapsam alanları (`site_id`/`parent_id`) BİLİNÇLİ olarak yoktur: klasör TAŞIMA
    ucu açılmamıştır. Açılsaydı taşınan klasörün altındaki belgelerin `project_id`/
    `site_id` künyeleriyle klasörün kapsamı ayrışırdı (künye kapsamı spec §2
    gereği klasörden türetilmez, KOPYALANIR).
    """

    name: str = _NAME


class DocumentFolderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    site_id: uuid.UUID | None
    parent_id: uuid.UUID | None
    name: str
    created_at: datetime


class DocumentFolderListResponse(BaseModel):
    """Düz liste; ağacı ekran `parent_id`den kurar (UI iki seviye çizer)."""

    folders: list[DocumentFolderRead]


# --- Belge künyesi (T3) ---


class DocumentRead(BaseModel):
    """Künye — baytlar YOK (spec §2). Liste ve tekil yanıtların ortak gövdesi.

    `uploaded_by_user_id` DIŞARI VERİLMEZ: ekranın gösterdiği şey SNAPSHOT
    addır (SB:144 "Şantiye Şefi: S. Öztürk"); kimliği yayınlamak, arşivi gören
    herkese kullanıcı kimlik havuzunu açardı.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    folder_id: uuid.UUID | None
    project_id: uuid.UUID
    site_id: uuid.UUID | None
    filename: str
    mime_type: str
    size_bytes: int
    description: str | None
    uploaded_by_name: str | None
    created_at: datetime


class DocumentListResponse(BaseModel):
    """Düz liste. TOPLAM SAYI ALANI YOKTUR: sayfalama olmadığı için (spec §3)
    `total` ile `len(documents)` her zaman aynı olurdu — ekranı yanıltan
    ölü bir alan."""

    documents: list[DocumentRead]


class DocumentUpdate(BaseModel):
    """`PATCH /documents/{id}` — üç alan, ÜÇÜ DE İSTEĞE BAĞLI (spec §3).

    Alanın GÖNDERİLMEMESİ ile `null` GÖNDERİLMESİ farklıdır ve fark
    `model_fields_set` ile korunur: `description: null` açıklamayı SİLER,
    `folder_id: null` belgeyi kapsamın KÖKÜNE taşır; hiç göndermemek ikisine de
    DOKUNMAZ. `exclude_unset` olmadan bir ad değişikliği, açıklamayı sessizce
    silerdi.

    `project_id`/`site_id` YOKTUR: belge KAPSAM DEĞİŞTİREMEZ. Değiştirebilseydi
    `visible_projects` süzgecini geçen bir kullanıcı, kendi göremediği bir
    projeye belge taşıyabilir ya da tersine görünmeyen bir belgeyi kendi
    kapsamına çekebilirdi.
    """

    filename: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    folder_id: uuid.UUID | None = None
