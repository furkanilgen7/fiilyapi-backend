"""MU-3A korkulukları ve Türkçe hata metinleri.

`accounting/guards.py` deseninin kardeşi: hata SINIFLARI `app/core/errors.py`de,
METİNLER burada TEK kopya sabit olarak durur.

## Hangi kural hangi koda düşer

| Durum | Kod | Sınıf |
|---|---|---|
| Eşlemesi olmayan bacak rolü | 422 | `AccountingValidationError` |
| Denge / satır sayısı / yaprak hesap | 422 | `accounting.validation` (ÇAĞRILIR) |
| Hedef dönem kapalı | 409 | `ConflictError` (`accounting.periods_service`) |

🔴 **404 YOKTUR.** `source_id` bir FK DEĞİLDİR (çok biçimli referans) ve
`post_document` belgeyi OKUMAZ — belgenin varlığını ve onay durumunu doğrulamak
ÇAĞIRANIN (MU-3B/C/D/E) işidir. Burada bir 404 üretmek, doğrulanmamış bir
varlığı doğrulanmış gibi gösterirdi.

🔴 **AYRI BİR HATA SINIFI AÇILMADI.** Eşleme eksikliği K1'in engelleriyle AYNI
cümlede (`raise_blockers`) toplanır ve aynı 422'ye düşer: ikisi de fişin
GÖVDESİNE dair kurallardır ve çağıran onları ayrı ele alamaz.
"""

__all__ = ["RULE_MISSING_PREFIX", "rule_missing"]

from collections.abc import Iterable

#: Eksik rollerin HEPSİ TEK cümlede toplanır (FAT-1 `_raise_blockers` dersi):
#: altı bacaklı bir fişte eksik eşlemeleri birer birer keşfettirmek, her
#: denemede bir migration/veri düzeltmesi anlamına gelirdi.
RULE_MISSING_PREFIX = "Belge türü için hesap eşlemesi tanımlı değil"

#: Rol adları SIRALANIR: aynı hata iki kez alındığında sözcüklerin yer
#: değiştirmesi "başka bir hata" izlenimi verirdi.
_ROL_AYRACI = ", "


def rule_missing(roles: Iterable[str]) -> str:
    """`{"payable", "expense"} -> "… değil: expense, payable"`."""
    return f"{RULE_MISSING_PREFIX}: {_ROL_AYRACI.join(sorted(set(roles)))}"
