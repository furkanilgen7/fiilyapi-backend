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
from datetime import date
from decimal import Decimal

from pydantic import BaseModel

__all__ = [
    "TrialBalanceResponse",
    "TrialBalanceRow",
    "TrialBalanceTotals",
    "VatDeductionRow",
    "VatReturnResponse",
    "VatTaxableRow",
]


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


class VatTaxableRow(BaseModel):
    """`Tablo 1 — Matrah ve Vergi`nin bir ORAN satırı (mockup satır 84-89).

    🔴 `rate = 0` satırları BURAYA GİRMEZ: mockup istisnayı ayrı, italik/gri bir
    satır olarak çizer (satır 90-95) ve vergisi tanımı gereği `0`dır. Listeye
    konsaydı `Vergi` kolonu hep `0` olan sahte bir "oran" satırı doğardı.
    `VatReturnResponse.exempt_base` onun yeridir.
    """

    rate: Decimal
    base: Decimal
    vat: Decimal


class VatDeductionRow(BaseModel):
    """`İndirimler` tablosunun bir satırı (mockup satır 116-125).

    🔴 Mockup İKİ satır çizer (`Mal Alışları` / `Hizmet Alımları`) ama bu ayrımın
    veri modelinde karşılığı YOKTUR (ölçüldü: `item_type`/`is_service`/
    `product_type` sıfır eşleşme, kalemin stok bağı yok). Sınıflandırıcı
    UYDURULMADI; tek satır `Alışlar` döner ve boşluk açık borçtur. Liste tipi
    olması, sınıflandırma bir gün gerçekten modellendiğinde şemanın KIRILMADAN
    büyümesi içindir.
    """

    source: str
    base: Decimal
    vat: Decimal


class VatReturnResponse(BaseModel):
    """KDV Beyannamesinin tamamı — 🔴 sayfalama YOKTUR (mizanla aynı gerekçe).

    `year`/`month` yanıtta TEKRARLANIR: istemci hangi dönemi gördüğünü kendi
    isteğinden değil SUNUCUNUN cevabından okur (mockup satır 45 başlığı).

    🔴 **`payable` ve `carried_forward` AYNI ANDA sıfırdan büyük OLAMAZ.**
    `fark = calculated_vat − deductible_vat`; `payable = max(fark, 0)` ve
    `carried_forward = max(−fark, 0)`. Negatif fark "ödenecek" DEĞİL DEVREDEN
    KDV'dir — tek alan açılıp negatif basılsaydı ekran devlete borç yerine
    alacak yazardı. Mockup yalnız `Ödenecek` çizer (satır 65-69, 134-143); alan
    yine de açılır, sunum kararı frontend'indir.

    Para alanlarının hiçbiri `None` OLMAZ; boş dönem her yeri `0` basar ve
    `due_date` YİNE doludur (vade fatura verisine değil TAKVİME bağlıdır).
    """

    year: int
    month: int
    due_date: date
    calculated_vat: Decimal
    deductible_vat: Decimal
    payable: Decimal
    carried_forward: Decimal
    taxable_rows: list[VatTaxableRow]
    exempt_base: Decimal
    deductions: list[VatDeductionRow]
