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

__all__ = ["AccountingPeriodListItem", "AccountingPeriodListResponse", "AccountingPeriodResponse"]


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


class AccountingPeriodListItem(AccountingPeriodResponse):
    """DKAP-B — liste satırı, `AccountingPeriodResponse`e İKİ türetilmiş alan
    EKLER. `close`/`reopen` cevabı hâlâ çıplak `AccountingPeriodResponse`dir
    (görev emri kapsamı yalnız `GET /accounting-periods`); tek bir dönemi
    döndüren o iki uç için bu iki alanı hesaplamak GEREKSİZ bir sorgu turudur
    ve emrin "kod/uçlar DEĞİŞMEZ" maddesini ihlal ederdi.

    `entry_count` — o döneme (`period_year`/`period_month`) ait TÜM yevmiye
    fişi sayısı, STATÜ AYRIMI YAPMADAN (K2 kararı, `periods_service.py`
    modül docstring'inde gerekçelidir): kapanış kapısı (`assert_periods_
    open`/`lock_period`) kapalı dönemde HER statüdeki fişi reddeder, sayaç da
    aynı kümeye bakar. Mockup kanıtı: Temmuz satırı "3 taslak fiş var"
    uyarısıyla birlikte Fiş=218 basar — taslak sayının İÇİNDEDİR.

    `closed_by_name` — `users.full_name` (K5: depodaki TEK ad kolonu,
    `audit/repository.py`nin `outerjoin(User, ...)` deseniyle AYNI yoldan
    okunur). NULL olabilir (K4): açık dönemde veya kapatan kullanıcı
    silinmişse `None` kalır, `"Bilinmiyor"` gibi bir metin UYDURULMAZ.
    """

    entry_count: int
    closed_by_name: str | None


class AccountingPeriodListResponse(BaseModel):
    """K7 liste zarfı: `items` + `total` + `limit`/`offset` (repo kanonu)."""

    items: list[AccountingPeriodListItem]
    total: int
    limit: int
    offset: int
