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
    """DKAP-B — liste satırı, `AccountingPeriodResponse`e ÜÇ türetilmiş alan
    EKLER (SIRA-B ile DÖRT). `close`/`reopen` cevabı hâlâ çıplak `AccountingPeriodResponse`dir
    (görev emri kapsamı yalnız `GET /accounting-periods`); tek bir dönemi
    döndüren o iki uç için bu alanları hesaplamak GEREKSİZ bir sorgu turudur
    ve emrin "kod/uçlar DEĞİŞMEZ" maddesini ihlal ederdi.

    🔴 K9 — bu ekranda İKİ AYRI kapı vardır (ayrıntı `repository.
    count_entries_by_period` docstring'i): (1) kapalı döneme YAZMA yasağı —
    STATÜ AYRIMI YAPMAZ; (2) kapanışın ÖN KOŞULU (`has_draft_entries`) —
    YALNIZ `draft` fişe bakar. `entry_count` (1)e, `draft_count` (2)ye karşılık
    gelir; ikisi AYNI alanmış gibi anlatılırsa (önceki tur böyleydi, K2
    çürütüldü) ekranın "142 fiş var ama kapatamıyorum" sorusu cevapsız kalır.

    `entry_count` — o döneme (`period_year`/`period_month`) ait TÜM yevmiye
    fişi sayısı, STATÜ AYRIMI YAPMADAN. Kapalı dönemde zaten `draft` KALMAZ
    (kapanış onu reddeder), bu yüzden toplamda ayrıma gerek yoktur ve
    mockup'ın "Fiş" sütunu (defter hacmi) budur. Mockup kanıtı: Temmuz satırı
    "3 taslak fiş var" uyarısıyla birlikte Fiş=218 basar — taslak sayının
    İÇİNDEDİR, toplamdan ayrı bir sayı DEĞİLDİR.

    `draft_count` — AYNI dönemdeki `draft` fiş sayısı (`has_draft_entries`in
    baktığı KÜME). Mockup özet şeridindeki "1 engelli" bunun türevidir: ekran
    `draft_count > 0` ile "bu dönem kapatılamaz" OLGUSUNU üretir. 🔴
    Kapanabilirlik KARARININ kendisi (`can_close` gibi) burada TAŞINMAZ —
    karar `periods_service`in kapısıdır; ikinci bir karar kopyası kapı bir gün
    değişince ekranı sessizce yanlış bırakırdı.

    `previous_period_open` — SIRA-B: takvim olarak BİR ÖNCEKİ ayın
    `accounting_periods`ta KAYITLI ve `open` olup olmadığı. 🔴 Anlamı bu kadar
    DARDIR ve `draft_count` ile AYNI sınıftandır: bir OLGU taşır, bir KARAR
    değil. Adı `can_close` DEĞİLDİR ve olmayacaktır — kapatılabilirlik
    `status` + `draft_count` + bu olgunun BİRLEŞİMİDİR ve o birleşimi
    `periods_service.close_period` tanımlar; kararın bir kopyası burada
    dursaydı kapı bir gün değiştiğinde ekran SESSİZCE yanlış kalırdı
    (DKAP-B kanonu).

    🔴 Ekran bunu KENDİ listesinden türetemez, bu yüzden alan ŞART: Ocak'ın
    öncesi bir önceki yılın Aralığıdır ve liste `year` süzgeciyle tek yıl
    çeker — o satır sayfada HİÇ olmaz. Ayrıca sayfa sınırındaki dönemin
    öncesi de sayfada olmayabilir.

    🔴 K10 — olgu ile kapı AYNI iki yardımcıdan beslenir
    (`periods_service.previous_period` + `repository.open_periods_among`);
    "kaydı olmayan ay" ikisinde de `false`/engel-değil demektir (K2).

    🔴 Bu alan YALNIZ liste satırındadır. `close`/`reopen` cevabı çıplak
    `AccountingPeriodResponse` KALIR: tek bir dönem için fazladan bir sorgu
    turudur ve o iki uç zaten kararı KENDİSİ vermiştir — cevabına "önceki
    açık mı" iliştirmek, az önce geçilmiş bir kapıyı tekrar anlatmak olurdu.

    `closed_by_name` — `users.full_name` (K5: depodaki TEK ad kolonu,
    `audit/repository.py`nin `outerjoin(User, ...)` deseniyle AYNI yoldan
    okunur). NULL olabilir (K4): açık dönemde veya kapatan kullanıcı
    silinmişse `None` kalır, `"Bilinmiyor"` gibi bir metin UYDURULMAZ.
    """

    entry_count: int
    draft_count: int
    closed_by_name: str | None
    previous_period_open: bool


class AccountingPeriodListResponse(BaseModel):
    """K7 liste zarfı: `items` + `total` + `limit`/`offset` (repo kanonu)."""

    items: list[AccountingPeriodListItem]
    total: int
    limit: int
    offset: int
