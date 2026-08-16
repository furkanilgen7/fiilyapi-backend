"""Muhasebe RAPOR uçları (MU-2) — `GET /trial-balance` (Mizan) · T5: `/vat-return`.

Kapı **`accounting`** iznidir (`guards.PERMISSION_MODULE`) — 🔴 **yeni izin
modülü AÇILMADI, matris DEĞİŞMEDİ, izin migration'ı YOKTUR.** Mizan bir
OKUMADIR, dolayısıyla `view` yeter: PM · muhasebe · patron · sysadmin görür.

## 🔴 `prefix` YOKTUR — bilinçli

Router bir KÖK taşımaz, iki AYRI birinci-seviye yol taşıyacaktır
(`/trial-balance` bugün, `/vat-return` T5'te). Ortak bir önek uydurmak
(`/accounting-reports/...`) mockup'ın sidebar'ıyla (satır 33, 36 — `Mizan` ve
`KDV Beyanı` kardeş girdilerdir) ve öteki muhasebe köklerinin düz adlandırmasıyla
(`/journal`, `/chart-of-accounts`) çelişirdi. T5 buraya YENİ BİR `@router.get`
ekler; dosya bunun için hazırdır.

## ROTA SIRASI

`/trial-balance` TEK segmentli ve LİTERALDİR. `grep` ile doğrulandı: repoda
`trial-balance` geçen başka hiçbir yol yoktu ve uygulamanın KÖK seviyesinde
`"/{param}"` biçiminde hiçbir rota yoktur (tek `"/{...}"` rotası `/equipment`
öneki altındadır). Dolayısıyla bu yolun UUID sanılması yapısal olarak imkânsızdır
ve `include_router` sırası serbesttir (MK-2 dersinin uygulanamadığı hâl).

## 🔴 `year`/`month` ZORUNLU — sunucunun "bugün"ü HİÇ okunmaz

`ledger.default_period()` gibi bir varsayılan AÇILMADI. Gerekçe TB5'in üretimde
kanıtlı kusurudur: sunucunun yerel takvimini okuyan bir varsayılan, TR gecesinde
bir gün (ve ayın ilk gecesinde bir AY) geride kalır ve kullanıcı hangi mizana
baktığını bilmez. İki parametre de zorunlu tutulunca kusur bu uçta **yapısal
olarak imkânsızdır**; frontend dönemi zaten mockup satır 44-46'daki `‹ Ocak–Temmuz
2026 ›` gezicisinden bilir.

`GET` uçları `record_audit` ÇAĞIRMAZ (WORKFLOW kuralı — okumalar denetlenmez).
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import AccessLevel
from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.openapi import COMMON_ERROR_RESPONSES
from app.core.permissions import require_permission
from app.modules.accounting import balance_sheet, guards, trial_balance, vat_return
from app.modules.accounting.reports_schemas import (
    BalanceSheetResponse,
    TrialBalanceResponse,
    VatReturnResponse,
)
from app.modules.users.models import User

router = APIRouter(tags=["accounting"], responses=COMMON_ERROR_RESPONSES)

_VIEW = require_permission(guards.PERMISSION_MODULE, AccessLevel.view)

# 🔴 Bantlar `accounting_periods`in CHECK'leri ve `periods_router` ile BİREBİR —
# aynı takvim iki uçta farklı aralık kabul etseydi bir dönem kapatılabilir ama
# mizanı görüntülenemez olurdu.
_YEAR = Annotated[int, Query(ge=2000, le=2100)]
_MONTH = Annotated[int, Query(ge=1, le=12)]

# 🔴 Bilançonun penceresi bir TARİHTİR (nokta-zaman), yıl+ay çifti DEĞİL —
# `_YEAR`/`_MONTH` bantları burada YETMEZ. Bant yine de `accounting_periods`in
# yıl CHECK'iyle (2000-2100) tutarlıdır: takvimin iki uçta farklı aralık kabul
# etmesi, kapatılabilen ama bilançosu alınamayan bir dönem üretirdi.
# Sınırlar KAPALIDIR (`ge`/`le`): `lt`/`gt` yazılsaydı `2100` yılının bilançosu
# hiç alınamazdı.
_AS_OF = Annotated[date, Query(ge=date(2000, 1, 1), le=date(2100, 12, 31))]


@router.get("/trial-balance", response_model=TrialBalanceResponse, dependencies=[_VIEW])
async def trial_balance_endpoint(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    year: _YEAR,
    month: _MONTH,
    include_empty: bool = False,
) -> TrialBalanceResponse:
    """Mizan — açılış (NET) · dönem hareketi (**BRÜT**) · kapanış (NET).

    Dönem BİRİKİMLİ bir ARALIKTIR (mockup satır 45 `Ocak–Temmuz 2026`): yılın
    Ocak ayından `month`un SON GÜNÜNE kadar. Ayrıntı ve aritmetik
    `trial_balance.py` modül docstring'indedir.

    🔴 **Sayfalama YOKTUR** (K7 zarfı kullanılmaz): `totals` GENEL TOPLAMDIR ve
    `is_balanced` onun üzerinden kurulur — sayfalanmış bir mizanda ikisi de
    anlamsızlaşırdı. Küme sınırlıdır (tekdüzen hesap planı ~200 satır).

    `include_empty=false` (varsayılan): üç pencerenin HİÇBİRİNDE hareketi
    olmayan hesap listelenmez — mockup'ın 8 satırının hepsi hareketlidir (satır
    80-159) ve kullanılmayan yüzlerce hesap tabloyu okunamaz hâle getirirdi.
    `true` ile hareketsizler de gelir, altı kolonu da `0` basar.

    Sıralama `code` ARTAN — mizan hesap planının sırasını izler.
    """
    return await trial_balance.build_trial_balance(
        session, year=year, month=month, include_empty=include_empty
    )


@router.get("/vat-return", response_model=VatReturnResponse, dependencies=[_VIEW])
async def vat_return_endpoint(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    year: _YEAR,
    month: _MONTH,
) -> VatReturnResponse:
    """KDV Beyannamesi — hesaplanan · indirilecek · ödenecek/devreden.

    🔴 **Pencere TEK AYDIR** (mockup satır 45 `Haziran 2026`), mizanın birikimli
    aralığından FARKLI. Faturanın `issue_date`i esas alınır; sınırlar kapalıdır.
    Sayılan faturalar, oran gruplaması, istisna tanımı ve vade aritmetiği
    `vat_return.py` modül docstring'indedir.

    🔴 Beyanname faturanın parasını YENİDEN YAZMAZ: her fatura için
    `invoicing/amounts.py` yeniden çalıştırılır, matrah avans/teminat düşülmüş
    `tax_base`tir. Aynı formülün ikinci bir kopyası bu uçta yapısal olarak
    yasaktır (kaynak metni testle denetlenir).

    Mockup'ın `XML İndir` / `GİB'e Gönder` düğmeleri (satır 48-49) KAPSAM
    DIŞIDIR: e-Fatura/GİB tümüyle ertelenmiştir, uç AÇILMAMIŞTIR.

    🔴 **Sayfalama YOKTUR**: küme oran sayısıyla (bir avuç) sınırlıdır ve
    `calculated_vat` satırların GENEL toplamıdır — sayfalanmış bir beyanda
    anlamsızlaşırdı.
    """
    return await vat_return.build_vat_return(session, year=year, month=month)


@router.get("/balance-sheet", response_model=BalanceSheetResponse, dependencies=[_VIEW])
async def balance_sheet_endpoint(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    as_of: _AS_OF,
) -> BalanceSheetResponse:
    """Bilanço — AKTİF/PASİF, üç seviye (bölüm bandı → kalem → ara toplam).

    🔴 **Dönem modeli NOKTA-ZAMANDIR**, mizanın birikimli aralığından FARKLI:
    mockup BL:37 üç ayrı **tek gün** sunar (`31 Temmuz 2026` / `30 Haziran 2026`
    / `31 Aralık 2025`). Gövde `entry_date <= as_of` kümülatif nettir; tek
    istisna `Dönem Net Kârı` kalemidir ve penceresi `{as_of.year}-01-01` ile
    `as_of` arasıdır (yılbaşından bugüne). Aritmetik ve kontra netlemesi
    `balance_sheet.py` modül docstring'indedir.

    🔴 **`is_balanced` ÖLÇÜLÜR, `True` VARSAYILMAZ**: dengesiz bir `reversed`
    fiş DB'ye girebilir (`ck_journal_entries_posted_balanced` yalnız `posted`ı
    bağlar) ve sabit `True` basan bir bilanço sessizce yalan söylerdi.

    🔴 **Sayfalama YOKTUR** (K7 zarfı kullanılmaz): `total` GENEL TOPLAMDIR ve
    `is_balanced` onun üzerinden kurulur — sayfalanmış bir bilançoda ikisi de
    anlamsızlaşırdı. Küme SABİTTİR: iki taraf, 13 kalem.

    Kapsam dışı (bilinçli): proje/şantiye süzgeci (üç muhasebe tablosunda da
    `project_id`/`site_id` YOKTUR ve mockup süzgeç çizmiyor) · karşılaştırma
    sütunu (mockup tabloları 2 sütunlu, BL:48-62) · `PDF` düğmesi (BL:38 — düğme
    dışında hiçbir şey söylemiyor) · dönem kilidi rozeti (salt-okuma ucu).
    """
    return await balance_sheet.build_balance_sheet(session, as_of=as_of)
