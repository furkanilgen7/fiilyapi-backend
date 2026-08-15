"""Muhasebe dönemi istek/yanıt şemaları (MU-2 T3).

`schemas.py` 415 satırdır ve BÜYÜTÜLMEZ (800 tavanı, MU-1 kanonu); dönem
şemaları kendi dosyasında durur.

🔴 **İSTEK GÖVDESİ YOKTUR.** `close`/`reopen` uçları gövde ALMAZ: kapatılacak
dönem YOL PARAMETRESİDİR (`/{year}/{month}/close`) ve başka hiçbir alan
kullanıcıdan gelmez. `closed_at`/`closed_by_id` SUNUCU damgalarıdır; gövdeden
kabul edilselerdi istemci geçmişe tarihli bir kapanış uydurabilirdi.

`status` da gövdeden GELMEZ: durum değişimi UCUN KENDİSİDİR (`close` / `reopen`),
bir alan değil — tek bir `PATCH status` ucu olsaydı `full` ile `admin` kapıları
AYRILAMAZDI (açma `admin` ister, kapatma `full`).
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.modules.accounting.models import AccountingPeriodStatus

__all__ = ["AccountingPeriodListResponse", "AccountingPeriodResponse"]


class AccountingPeriodResponse(BaseModel):
    """Dönem satırı — üç ucun ORTAK yanıtı (liste · kapat · aç).

    Ayrı ayrı kurulsalardı `close` ile `reopen` farklı alan kümeleri basar ve
    frontend hangi ucun ne döndüğünü kodun iki köşesinden okurdu
    (`build_detail` deseninin dönem karşılığı).

    `closed_at`/`closed_by_id` NULLABLE'dır ve bu bir eksiklik DEĞİLDİR: `open`
    dönemde ikisi de NULL olmak ZORUNDADIR (`ck_accounting_periods_closed_stamp`).

    TÜREV ALAN YOKTUR: dönemin toplamları/mizanı bu yanıtta TAŞINMAZ — mizan
    yevmiyeden türetilir (T4) ve burada bir kopyası dursaydı bayatlardı.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    year: int
    month: int
    status: AccountingPeriodStatus
    closed_at: datetime | None
    closed_by_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class AccountingPeriodListResponse(BaseModel):
    """K7 liste zarfı: `items` + `total` + `limit`/`offset` (repo kanonu)."""

    items: list[AccountingPeriodResponse]
    total: int
    limit: int
    offset: int
