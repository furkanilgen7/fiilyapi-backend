"""Muhasebe RAPOR yanıt şemaları (MU-2 T4 mizan · T5 KDV beyanı).

`schemas.py` 415 satırdır ve BÜYÜTÜLMEZ (800 tavanı, MU-1 kanonu); rapor
şemaları — dönem şemalarının `periods_schemas.py`de durması gibi — kendi
dosyasında toplanır. T5'in `/vat-return` yanıtı da BURAYA gelir: iki rapor da
yevmiyeden TÜRETİLİR, hiçbiri saklanmaz ve ikisi de aynı `Decimal` sözleşmesini
paylaşır.

🔴 **İSTEK GÖVDESİ YOKTUR.** Mizan bir OKUMA ucudur; dönem seçimi sorgu
parametresidir (`year`/`month`), gövde değil.

## 🔴 Altı para alanının hiçbiri `None` OLMAZ

Boş taraf **`0`** basar. Mockup'ın `—` işareti (satır 84, 88, …) bir SUNUM
kararıdır ve frontend'e aittir: `null` dönseydi ekranın her aritmetiği ve
tfoot'un GENEL TOPLAM satırı `null` yayardı. `Decimal`dir; kayan nokta hiçbir
aşamada devreye girmez.
"""

import uuid
from decimal import Decimal

from pydantic import BaseModel

__all__ = ["TrialBalanceResponse", "TrialBalanceRow", "TrialBalanceTotals"]


class TrialBalanceTotals(BaseModel):
    """tfoot `GENEL TOPLAM` (mockup satır 161-171) — altı kolonun AYRI toplamı.

    🔴 K15: mockup'ın tfoot RAKAMLARI kendi satırlarıyla çelişir (göstermelik);
    SATIRLAR kazanır, tfoot'tan yalnız YAPI alınır — yani "altı ayrı toplam +
    iki kapanış toplamının eşit basıldığı denge iddiası".

    Toplam TÜM kümeyi kapsar; sayfalama olsaydı bu sayı bir SAYFANIN toplamı
    olurdu ve `GENEL TOPLAM` adı yalan söylerdi (bkz. `TrialBalanceResponse`).
    """

    opening_debit: Decimal
    opening_credit: Decimal
    period_debit: Decimal
    period_credit: Decimal
    closing_debit: Decimal
    closing_credit: Decimal


class TrialBalanceRow(BaseModel):
    """Mizanın bir hesap satırı — mockup'ın 8 kolonu birebir (satır 63-77).

    Üç grup AYNI ŞEY DEĞİLDİR ve bu ayrım şemada da görünür:

    | Grup | Nicelik | Kaç taraf dolu |
    |---|---|---|
    | `opening_*` | **NET** | en fazla BİRİ |
    | `period_*`  | **BRÜT** (`Σdebit` ve `Σcredit` ayrı ayrı) | **İKİSİ BİRDEN** |
    | `closing_*` | **NET** | en fazla BİRİ |

    Mockup satır 85-86 (Kasa dönem `2.640.000` **ve** `2.535.200`) brütlüğün
    kanıtıdır; satır 87-88 (kapanış `284.800` / `—`) netliğin.
    """

    account_id: uuid.UUID
    account_code: str
    account_name: str
    opening_debit: Decimal
    opening_credit: Decimal
    period_debit: Decimal
    period_credit: Decimal
    closing_debit: Decimal
    closing_credit: Decimal


class TrialBalanceResponse(BaseModel):
    """Mizanın tamamı — 🔴 **K7 SAYFALAMA ZARFI YOKTUR** (bilinçli sapma).

    Gerekçe: `totals` GENEL TOPLAMDIR ve `is_balanced` onun üzerinden kurulur;
    sayfalanmış bir mizanda ikisi de anlamsızlaşır (2. sayfanın "toplam borç =
    toplam alacak" iddiası hiçbir şey ifade etmez). Küme SINIRLIDIR: tekdüzen
    hesap planı ~200 satırdır ve `include_empty=false` hareketsizleri zaten
    eler. `items`/`total`/`limit`/`offset` yerine `rows`/`totals` adları tam da
    bu farkı görünür kılmak için seçilmiştir.

    `year`/`month` yanıtta TEKRARLANIR: mockup satır 45 (`Ocak–Temmuz 2026`)
    başlığı buradan kurulur ve istemci hangi dönemi gördüğünü kendi isteğinden
    değil SUNUCUNUN cevabından okur.

    `is_balanced` = `totals.closing_debit == totals.closing_credit` (mockup
    satır 54-57 kontrol banner'ı).
    """

    year: int
    month: int
    is_balanced: bool
    rows: list[TrialBalanceRow]
    totals: TrialBalanceTotals
