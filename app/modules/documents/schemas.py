"""Klasör uçlarının şemaları (spec §3 birinci satırı).

Kapsam DIŞI (bilinçli): belge künyesi şemaları T3'tedir; klasörün İÇİNDEKİ belge
SAYISI burada YOKTUR — mockup'ın "Sözleşmeler (12)" rozeti belge listesi ucundan
(T3) beslenir, klasör listesine sayaç eklemek her kök çizilişinde `documents`
tablosuna gereksiz bir toplama sorgusu koştururdu.

Versiyon/onay/etiket alanı YOKTUR (spec §1): model de taşımıyor, şema da uydurmaz.
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
