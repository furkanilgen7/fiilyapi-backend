"""Makine & ekipman uçları (MK-1 spec §4) — T1'de BOŞ.

Kapı `equipment` iznidir (21. modül, spec §6): okuma `view`, yazmanın tamamı
`full`. Görünmeyen kayıt 404'tür.

`inventory`/`documents` router'larının aksine bu router PREFIX TAŞIR (`/equipment`):
spec §4'ün SAYDIĞI uçların hepsi tek kökün altındadır (`/equipment`,
`/equipment/summary`, `/equipment/work-logs`, `/equipment/work-summary`,
`/equipment/fuel-logs`, `/equipment/fuel-summary`) — ikinci bir kök yoktur.

## T1'de niçin hiç yol yok

Bu dilim şemayı ve izin modülünü açar. Router yine de BURADA tanımlanır ve
`app/main.py`ye BAĞLANIR: bağlama T3'e ertelenseydi, uçlar yazıldığında
çalıştıklarını sanıp canlıda 404 alma riski doğardı (BFF izin listesi tuzağının
kardeşi). Boş router uygulamayı etkilemez — hiçbir yol üretmez.

## AÇILMAYAN uç (spec §4, icat yasağı)

**`DELETE /equipment/{id}` YOKTUR.** Kullanımdan kaldırma
`PATCH {"is_active": false}` iledir; kaydı olan ekipman zaten `RESTRICT`
yüzünden DB seviyesinde de silinemez. Kira hakedişi (M5) ve ekipman belgeleri
MK-2'nindir (spec §9) — bu router'da HİÇBİRİ açılmaz.
"""

from fastapi import APIRouter

from app.core.openapi import COMMON_ERROR_RESPONSES

router = APIRouter(prefix="/equipment", tags=["equipment"], responses=COMMON_ERROR_RESPONSES)
